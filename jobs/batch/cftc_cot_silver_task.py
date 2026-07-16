"""AWS Batch entrypoint: CFTC COT bronze -> silver (shadow-first, SILVER-F015/INV-6).

Reads all bronze Parquets, deduplicates overlapping year-label ranges,
computes rolling 156-week z-scores, and publishes the flat table:

    silver/cot/part-000.parquet

Publish contract (A-W4 CLASS-B retrofit)
----------------------------------------
The silver write is routed through the SILVER-F015 shadow-first controlled
publisher via ``leviathan.silver.flat_producer.build_flat_publish`` with an
EXPLICIT registry-derived INV-2 arrow schema (the F010 ``silver_cot`` contract).
``--publish-mode`` (default ``dry-run``) resolves through the publish guard:

  * dry-run   : nothing is written anywhere (the manifest is an in-memory plan).
  * shadow    : the object is staged ONLY under ``silver/cot/_shadow/`` and
                validated; the canonical object is never touched.
  * canonical : shadow-stage -> validate -> promote -> catalog, but ONLY with a
                verified signed approval (the guard raises otherwise before any write).

This replaces the former latest-only ``put_object`` overwrite so a red rebuild
gate can protect the canonical write (a red gate cannot protect data already
overwritten). The legacy ``--dry-run`` flag is retained as an alias for
``--publish-mode dry-run``.

Usage
-----
    python jobs/batch/cftc_cot_silver_task.py                         # dry-run (writes nothing)
    python jobs/batch/cftc_cot_silver_task.py --publish-mode shadow
    python jobs/batch/cftc_cot_silver_task.py --publish-mode canonical --force-overwrite
    python jobs/batch/cftc_cot_silver_task.py --dry-run
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.silver.flat_producer import authorize_for_contract, build_flat_publish
from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import silver_cot_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.bronze_to_silver.cftc_cot import build_cot_silver

logger = get_logger("cftc_cot_silver_task")

_BRONZE_PREFIX = "bronze/production/source=cftc_cot/"
_TABLE = "silver_cot"
_JOB = "cftc_cot_silver"


def _exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def _caller_identity(aws_region: str) -> tuple[str, str]:
    """Best-effort STS identity for the canonical publish target. Returns (account_id, role_arn);
    empty strings when no credentials are available (fine for dry-run / shadow, which skip the
    environment check)."""
    try:
        import boto3
        ident = boto3.client("sts", region_name=aws_region).get_caller_identity()
        return ident.get("Account", ""), ident.get("Arn", "")
    except Exception as exc:  # noqa: BLE001 -- dry-run / shadow must not require live credentials
        logger.info("STS identity unavailable (%s); using empty target (dry-run/shadow only)", exc)
        return "", ""


def _load_bronze(bucket: str, aws_region: str, s3_client) -> list[pd.DataFrame]:
    """Load bronze in year order so bulk (2006_2016) comes before individual years -- dedup keeps
    the LAST occurrence so individual years override the bulk file."""
    bronze_keys = sorted(list_s3_keys(bucket, _BRONZE_PREFIX, suffix=".parquet",
                                      aws_region=aws_region))
    logger.info("Loading %d bronze Parquets ...", len(bronze_keys))
    dfs: list[pd.DataFrame] = []
    for k in bronze_keys:
        try:
            raw = s3_download_with_retry(bucket, k, s3_client)
            dfs.append(pd.read_parquet(io.BytesIO(raw)))
        except Exception:
            logger.exception("Failed to load: %s", k)
    return dfs


def _publish_cot(
    df: pd.DataFrame,
    contract: dict,
    auth,
    s3_client,
    bucket: str,
    *,
    force_overwrite: bool,
) -> ManifestState | None:
    """Publish the flat COT silver object through the shadow-first publisher. Returns the manifest
    state, or ``None`` when an existing canonical object is skipped (canonical mode only)."""
    canonical_key = silver_cot_key()
    if (
        not force_overwrite
        and auth.may_mutate_canonical
        and s3_client is not None
        and _exists(s3_client, bucket, canonical_key)
    ):
        logger.info(
            "silver exists -- use --publish-mode canonical --force-overwrite to re-run: %s",
            canonical_key,
        )
        return None
    plan = build_flat_publish(
        df=df, contract=contract, canonical_key=canonical_key,
        auth=auth, s3_client=s3_client, job=_JOB,
    )
    manifest = plan.run()
    logger.info(
        "COT silver publish mode=%s state=%s rows=%d key=%s",
        auth.mode.value, manifest.state.value, len(df), canonical_key,
    )
    return manifest.state


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(description="CFTC COT bronze -> silver (shadow-first)")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="Alias for --publish-mode dry-run (writes nothing).")
    parser.add_argument("--publish-mode", default="dry-run",
                        choices=["dry-run", "shadow", "canonical"], dest="publish_mode",
                        help="dry-run|shadow|canonical (default dry-run; canonical needs a signed approval)")
    parser.add_argument("--role-arn", default="", dest="role_arn")
    parser.add_argument("--account-id", default="", dest="account_id")
    args = parser.parse_args()

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

    # A read client is always needed to load bronze; the publisher only writes in shadow/canonical.
    s3_read = get_thread_local_s3_client(aws_region)
    publish_client = None if publish_mode == "dry-run" else s3_read

    dfs = _load_bronze(bucket, aws_region, s3_read)
    df_silver = build_cot_silver(dfs)

    if publish_mode == "dry-run":
        logger.info("dry-run -- would publish %s rows=%d", silver_cot_key(), len(df_silver))
        # Diagnostic sample: corn COT around the 2012 drought.
        sample = df_silver[
            (df_silver["leviathan_slug"] == "corn_cbot")
            & (df_silver["report_date"] >= "2012-06-01")
            & (df_silver["report_date"] <= "2012-09-30")
        ][["report_date", "mm_net", "mm_pct_oi", "mm_net_z_3yr"]].head(10)
        if not sample.empty:
            print(sample.to_string(index=False))

    _publish_cot(df_silver, contract, auth, publish_client, bucket,
                 force_overwrite=args.force_overwrite)


if __name__ == "__main__":
    main()
