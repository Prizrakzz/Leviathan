"""AWS Batch task: USDA NASS annual bronze Parquet -> silver (shadow-first, SILVER-F015/INV-6).

Reads NASS annual bronze shards from S3, converts them to a state/national wide
annual feature table, and publishes partitions under ``silver/nass_annual/``.

Publish contract (A-W4 CLASS-B retrofit)
----------------------------------------
``silver_nass_annual`` is a PARTITIONED (projected) table -- one object per
``(commodity, year)``. The flat-table ``build_flat_publish`` path does NOT fit
(its single-object plan + exact contract-column encode cannot express the
per-partition fan-out, and the parquet body carries the ``year`` partition
column), so the write routes through the SILVER-F015 shadow-first publisher
(:class:`leviathan.silver.publisher.ShadowPublisher`, PROJECTED strategy) directly
-- the same pattern the quandl CHRIS task uses -- with the task's own parquet
writer (preserving the on-disk byte layout). ``--publish-mode`` (default
``dry-run``) resolves through the publish guard:

  * dry-run   : nothing is written anywhere.
  * shadow    : each partition object is staged ONLY under ``silver/nass_annual/_shadow/``;
                canonical partitions are untouched.
  * canonical : shadow-stage -> validate -> promote, ONLY with a verified signed approval.

This replaces the former latest-only ``put_object`` overwrite so a red rebuild
gate can protect the canonical writes. The projected table is never partition-
registered in Glue (INV-3); PROJECTED cataloging is a no-op.
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.silver.flat_producer import authorize_for_contract
from leviathan.silver.publisher import (
    ManifestState,
    PublishStrategy,
    ShadowPublisher,
    StagedObject,
    ValidationHooks,
)
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import parse_hive_key, silver_nass_annual_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.bronze_to_silver.usda_nass_annual import (
    OUTPUT_COLUMNS,
    transform_nass_annual_bronze_to_silver,
)

logger = get_logger("nass_annual_silver_task")

_BRONZE_PREFIX = "bronze/production/source=usda_nass/series=annual/"
_TABLE = "silver_nass_annual"
_JOB = "nass_annual_silver"


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="USDA NASS annual bronze -> silver (shadow-first)")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", default="false")
    parser.add_argument("--limit", type=int, default=0, help="Cap bronze keys for smoke tests")
    parser.add_argument(
        "--workers",
        type=_positive_int,
        default=8,
        help="Concurrent S3/parquet load workers. Use 1 for sequential debugging.",
    )
    parser.add_argument(
        "--bronze-commodities",
        default="all",
        help="Comma-separated bronze commodity partitions or 'all'.",
    )
    parser.add_argument(
        "--years",
        default="all",
        help="Comma-separated years or 'all'.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Alias for --publish-mode dry-run (writes nothing).")
    parser.add_argument("--publish-mode", default="dry-run",
                        choices=["dry-run", "shadow", "canonical"], dest="publish_mode",
                        help="dry-run|shadow|canonical (default dry-run; canonical needs a signed approval)")
    parser.add_argument("--role-arn", default="", dest="role_arn")
    parser.add_argument("--account-id", default="", dest="account_id")
    args = parser.parse_args()
    args.force_overwrite = _parse_bool(args.force_overwrite)
    return args


def _selected(value: str, allowed: set[str] | None) -> bool:
    return allowed is None or value in allowed


def _select_keys(
    keys: list[str],
    bronze_commodities: str,
    years: str,
    limit: int,
) -> list[str]:
    commodity_filter = None if bronze_commodities.strip().lower() == "all" else {
        item.strip() for item in bronze_commodities.split(",") if item.strip()
    }
    year_filter = None if years.strip().lower() == "all" else {
        item.strip() for item in years.split(",") if item.strip()
    }

    selected = [
        key
        for key in keys
        if _selected(parse_hive_key(key, "commodity"), commodity_filter)
        and _selected(parse_hive_key(key, "year"), year_filter)
    ]
    selected.sort()
    return selected[:limit] if limit else selected


def _load_and_transform(bucket: str, key: str, aws_region: str) -> pd.DataFrame:
    s3 = get_thread_local_s3_client(aws_region)
    raw_bytes = s3_download_with_retry(bucket, key, s3)
    bronze = pd.read_parquet(io.BytesIO(raw_bytes))
    silver = transform_nass_annual_bronze_to_silver(bronze)
    logger.info("transformed key=%s bronze_rows=%d silver_rows=%d", key, len(bronze), len(silver))
    return silver


def _transform_keys(
    bucket: str,
    keys: list[str],
    aws_region: str,
    workers: int,
) -> tuple[list[pd.DataFrame], int]:
    frames: list[pd.DataFrame] = []
    errors = 0
    completed = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_key = {
            executor.submit(_load_and_transform, bucket, key, aws_region): key
            for key in keys
        }
        for future in as_completed(future_to_key):
            key = future_to_key[future]
            completed += 1
            try:
                silver = future.result()
            except Exception as exc:  # noqa: BLE001
                logger.error("failed to transform %s: %s", key, exc)
                errors += 1
                continue
            if not silver.empty:
                frames.append(silver)
            logger.info("transform progress=%d/%d key=%s", completed, len(keys), key)

    return frames, errors


def _validate_final_uniqueness(df: pd.DataFrame) -> None:
    duplicate_mask = df.duplicated(subset=["leviathan_slug", "state", "year"], keep=False)
    if duplicate_mask.any():
        dupes = df.loc[duplicate_mask, ["leviathan_slug", "state", "year"]].drop_duplicates()
        preview = dupes.head(5).to_dict("records")
        raise ValueError(f"NASS annual silver has duplicate output rows: {preview}")


# ---------------------------------------------------------------------------
# Shadow-first publish (A-W4 CLASS-B retrofit)
# ---------------------------------------------------------------------------

def _exists(s3_client, bucket: str, key: str) -> bool:
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


def _partition_body(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    return buf.getvalue()


def _publish_nass_annual(
    final: pd.DataFrame,
    contract: dict,
    auth,
    s3_client,
    bucket: str,
    *,
    force_overwrite: bool,
) -> ManifestState | None:
    """Publish one silver object per (commodity, year) through the shadow-first publisher (PROJECTED).
    Returns the manifest state, or ``None`` when every partition is a skipped existing canonical
    object (canonical mode only)."""
    groups = [
        (str(commodity), int(year), group.reset_index(drop=True))
        for (commodity, year), group in final.groupby(["leviathan_slug", "year"])
    ]
    staged: list[StagedObject] = []
    skipped = 0
    for commodity, year, group in groups:
        canonical_key = silver_nass_annual_key(commodity, year)
        if (
            not force_overwrite
            and auth.may_mutate_canonical
            and s3_client is not None
            and _exists(s3_client, bucket, canonical_key)
        ):
            logger.info("skipping existing silver partition: %s", canonical_key)
            skipped += 1
            continue
        staged.append(StagedObject(
            canonical_key=canonical_key,
            body=_partition_body(group[OUTPUT_COLUMNS]),
            partition_values=[commodity, str(year)],
            row_count=len(group),
        ))

    if not staged:
        logger.info("nass_annual: no partitions to publish (skipped=%d existing)", skipped)
        return None

    # dry-run (no client) needs a no-op manifest sink; shadow/canonical persist via the S3 store.
    manifest_store = None if s3_client is not None else (lambda _k, _b: None)
    publisher = ShadowPublisher(
        job=_JOB,
        table=contract["table_name"],
        database=contract["glue_database"],
        bucket=bucket,
        canonical_root=contract["s3_root"],
        auth=auth,
        s3_client=s3_client,
        strategy=PublishStrategy.PROJECTED,
        validation=ValidationHooks(min_rows=1),
        manifest_store=manifest_store,
    )
    manifest = publisher.run(staged)
    logger.info(
        "nass_annual silver publish mode=%s state=%s partitions=%d skipped=%d",
        auth.mode.value, manifest.state.value, len(staged), skipped,
    )
    return manifest.state


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    load_env()
    args = _parse_args()

    publish_mode = "dry-run" if args.dry_run else args.publish_mode
    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    contract = load_registry().table(_TABLE)

    account_id, role_arn = args.account_id, args.role_arn
    if publish_mode == "canonical" and not account_id and not role_arn:
        account_id, role_arn = _caller_identity(aws_region)
    auth = authorize_for_contract(
        contract, publish_mode=publish_mode,
        role_arn=role_arn, account_id=account_id, env=os.environ,
    )
    logger.info("publish authorized: mode=%s may_canonical=%s", auth.mode.value, auth.may_mutate_canonical)

    s3_read = get_thread_local_s3_client(aws_region)
    publish_client = None if publish_mode == "dry-run" else s3_read

    all_keys = list_s3_keys(bucket, _BRONZE_PREFIX, suffix=".parquet", aws_region=aws_region)
    keys = _select_keys(all_keys, args.bronze_commodities, args.years, args.limit)
    if not keys:
        raise FileNotFoundError(f"No NASS annual bronze parquet files found under {_BRONZE_PREFIX}")

    logger.info(
        "NASS annual silver task bucket=%s bronze_keys=%d force=%s workers=%d mode=%s",
        bucket, len(keys), args.force_overwrite, args.workers, publish_mode,
    )

    start = datetime.now(timezone.utc)
    frames, errors = _transform_keys(bucket, keys, aws_region, args.workers)

    if errors:
        raise SystemExit(1)
    if not frames:
        logger.warning("All selected bronze keys transformed to empty silver outputs")
        return

    final = pd.concat(frames, ignore_index=True)
    final = final[OUTPUT_COLUMNS].drop_duplicates().reset_index(drop=True)
    _validate_final_uniqueness(final)

    _publish_nass_annual(final, contract, auth, publish_client, bucket,
                         force_overwrite=args.force_overwrite)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        "Done NASS annual silver rows=%d elapsed=%.1fs", len(final), elapsed,
    )


if __name__ == "__main__":
    main()
