"""AWS Batch task: UNICA annual-by-state bronze -> silver Parquet (shadow-first, SILVER-F015/INV-6).

Reads all per-season UNICA bronze Parquets from S3, pivots the EAV rows into a wide annual table
with one row per (harvest_year, state_region), and publishes a single FLAT silver object at:

    silver/unica_annual_state/part-000.parquet

Coverage: Brazil Centre-South historical seasons 1980/1981-2020/2021.

Publish contract (A-W4 CLASS-B retrofit)
----------------------------------------
``silver_unica_annual_state`` is a FLAT table (``partition_mode: flat``, ``projection: forbidden``),
so the write routes through ``leviathan.silver.flat_producer.build_flat_publish`` with the EXPLICIT
INV-2 arrow schema from the table's F010 registry contract -- never a bespoke
``df.to_parquet(...) + put_object(...)``. ``--publish-mode`` (default ``dry-run``) resolves through
the publish guard:

  * dry-run   : nothing is written anywhere (the manifest is an in-memory plan).
  * shadow    : the object is staged ONLY under ``silver/unica_annual_state/_shadow/``; canonical is
                untouched (INV-6 -- a red rebuild gate can still protect canonical).
  * canonical : shadow-stage -> validate -> promote -> catalog, ONLY with a verified signed approval.

The legacy ``--dry-run`` flag is retained as an alias for ``--publish-mode dry-run``; ``--force-overwrite``
continues to accept its string value (``--force-overwrite true``) and only bites the canonical path.
The unica family DAG runs ``promote_mode=stop_and_notify``, so the canonical wiring here is
correct-by-construction -- it does not execute until the A-W4 promotion.

Usage
-----
    # dry-run (writes nothing)
    python jobs/batch/unica_annual_state_task.py --bucket B --aws-region us-east-1

    # shadow (stages under _shadow/, canonical untouched)
    python jobs/batch/unica_annual_state_task.py --bucket B --aws-region us-east-1 --publish-mode shadow

    # canonical (needs a signed approval)
    python jobs/batch/unica_annual_state_task.py --bucket B --aws-region us-east-1 \\
        --publish-mode canonical --force-overwrite true
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from datetime import datetime, timezone

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.silver.flat_producer import authorize_for_contract, build_flat_publish
from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import (
    parse_hive_key,
    silver_unica_annual_state_key,
)
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.bronze_to_silver.unica_annual_state import (
    transform_unica_annual_state,
)

logger = get_logger("unica_annual_state_task")

TABLE = "silver_unica_annual_state"
_JOB = "unica_annual_state_silver"
_BRONZE_PREFIX = "bronze/production/source=unica/"


# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="UNICA annual-by-state bronze -> silver (shadow-first)"
    )
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument(
        "--force-overwrite",
        default="false",
        help="Re-write the canonical silver object even if it already exists (canonical mode only).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Alias for --publish-mode dry-run (writes nothing).",
    )
    parser.add_argument(
        "--publish-mode",
        default="dry-run",
        choices=["dry-run", "shadow", "canonical"],
        dest="publish_mode",
        help="dry-run|shadow|canonical (default dry-run; canonical needs a signed approval)",
    )
    parser.add_argument("--role-arn", default="", dest="role_arn")
    parser.add_argument("--account-id", default="", dest="account_id")
    args = parser.parse_args()
    args.force_overwrite = _parse_bool(args.force_overwrite)
    return args


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


def _available_harvest_years(bucket: str, aws_region: str) -> list[str]:
    """List harvest years for which a UNICA bronze Parquet exists in S3."""
    keys = list_s3_keys(bucket, _BRONZE_PREFIX, suffix=".parquet", aws_region=aws_region)
    years: list[str] = []
    for key in keys:
        hy = parse_hive_key(key, "harvest_year")
        if hy:
            years.append(hy)
    return sorted(set(years))


def _load_bronze_for_year(
    bucket: str, harvest_year: str, aws_region: str, s3_client
) -> pd.DataFrame:
    key = f"bronze/production/source=unica/harvest_year={harvest_year}/part-000.parquet"
    raw_bytes = s3_download_with_retry(bucket, key, s3_client)
    df = pd.read_parquet(io.BytesIO(raw_bytes))
    if "harvest_year" not in df.columns:
        df["harvest_year"] = harvest_year
    logger.info("loaded bronze harvest_year=%s  rows=%d", harvest_year, len(df))
    return df


def _load_all_bronze(bucket: str, harvest_years: list[str], aws_region: str) -> pd.DataFrame:
    s3_client = get_thread_local_s3_client(aws_region)
    frames: list[pd.DataFrame] = []
    for hy in harvest_years:
        try:
            frames.append(_load_bronze_for_year(bucket, hy, aws_region, s3_client))
        except Exception as exc:  # noqa: BLE001
            logger.error("failed to load harvest_year=%s: %s", hy, exc)
            raise
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Shadow-first publish (A-W4 CLASS-B retrofit)
# ---------------------------------------------------------------------------


def _key_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001
        return False


def _caller_identity(aws_region: str) -> tuple[str, str]:
    """Best-effort STS identity for the canonical publish target (empty on failure).

    Thin wrapper over the shared resolver ``leviathan.common.aws_identity.resolve_caller_identity``
    (the one idiom the batch-task family shares). Kept as a module-level seam so tests can
    monkeypatch it and readiness/unit runs stay AWS-free; an empty identity still makes the publish
    guard fail closed on the canonical path exactly as before."""
    from leviathan.common.aws_identity import resolve_caller_identity

    return resolve_caller_identity(aws_region)


def _publish_silver(
    df: pd.DataFrame,
    contract: dict,
    auth,
    s3_client,
    canonical_key: str,
    *,
    force_overwrite: bool,
    bucket: str,
) -> ManifestState | None:
    """Publish the single flat UNICA annual-state silver object through the shadow-first publisher.

    Returns the manifest state, or ``None`` when an existing canonical object is skipped (canonical
    mode, no ``--force-overwrite``)."""
    if (
        not force_overwrite
        and auth.may_mutate_canonical
        and s3_client is not None
        and _key_exists(s3_client, bucket, canonical_key)
    ):
        logger.info("silver exists -- skipping (canonical, no --force-overwrite): %s", canonical_key)
        return None
    plan = build_flat_publish(
        df=df,
        contract=contract,
        canonical_key=canonical_key,
        auth=auth,
        s3_client=s3_client,
        job=_JOB,
    )
    return plan.run().state


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    t0 = datetime.now(tz=timezone.utc)
    load_env()
    args = _parse_args()

    publish_mode = "dry-run" if args.dry_run else args.publish_mode
    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    contract = load_registry().table(TABLE)

    account_id, role_arn = args.account_id, args.role_arn
    if publish_mode == "canonical" and not account_id and not role_arn:
        account_id, role_arn = _caller_identity(aws_region)

    logger.info(
        "UNICA annual state silver task  bucket=%s  mode=%s  force=%s",
        bucket,
        publish_mode,
        args.force_overwrite,
    )

    harvest_years = _available_harvest_years(bucket, aws_region)
    if not harvest_years:
        logger.error("No UNICA bronze Parquets found under %s", _BRONZE_PREFIX)
        return 1

    logger.info("Found %d UNICA bronze season(s)", len(harvest_years))

    bronze = _load_all_bronze(bucket, harvest_years, aws_region)
    logger.info("Total bronze rows loaded: %d", len(bronze))

    silver = transform_unica_annual_state(bronze)
    logger.info("Silver rows after transform: %d", len(silver))

    if silver.empty:
        logger.warning("Silver transform returned empty DataFrame -- nothing to write")
        return 0

    auth = authorize_for_contract(
        contract,
        publish_mode=publish_mode,
        role_arn=role_arn,
        account_id=account_id,
        env=os.environ,
    )
    # A read client already loaded bronze; the publisher only writes in shadow/canonical.
    publish_client = None
    if publish_mode != "dry-run":
        from leviathan.storage.s3 import get_thread_local_s3_client as _pub_client_factory

        publish_client = _pub_client_factory(aws_region)

    state = _publish_silver(
        silver,
        contract,
        auth,
        publish_client,
        silver_unica_annual_state_key(),
        force_overwrite=args.force_overwrite,
        bucket=bucket,
    )
    logger.info(
        "publish %s state=%s mode=%s rows=%d",
        TABLE,
        state.value if state else "skipped",
        publish_mode,
        len(silver),
    )

    elapsed = (datetime.now(tz=timezone.utc) - t0).total_seconds()
    logger.info("done  elapsed=%.1fs", elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
