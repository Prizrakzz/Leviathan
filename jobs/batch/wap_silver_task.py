"""AWS Batch task: WAP Table 01 bronze/ → silver/ layer.

Downloads all WAP Table 01 bronze Parquets, applies the silver transforms,
and writes two silver Parquets to S3:

Output S3 keys
--------------
    silver/wap_table01/part-000.parquet
    silver/wap_table01_revisions/part-000.parquet

A JSON run log is written to:
    silver/wap_table01/_run_log.json

Usage
-----
    # Idempotent run (skip existing silver Parquets)
    python jobs/batch/wap_silver_task.py \\
        --bucket leviathan-dev-shahem-001 --aws-region us-east-1

    # Force overwrite
    python jobs/batch/wap_silver_task.py \\
        --bucket leviathan-dev-shahem-001 --aws-region us-east-1 --force-overwrite

    # Dry-run (no writes)
    python jobs/batch/wap_silver_task.py \\
        --bucket leviathan-dev-shahem-001 --aws-region us-east-1 --dry-run
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from datetime import datetime, timezone

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import (
    silver_wap_table01_key,
    silver_wap_table01_revisions_key,
)
from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys
from leviathan.transforms.bronze_to_silver.wap_table01 import (
    build_long_table,
    build_revision_table,
)

logger = get_logger("wap_silver_task")

_BRONZE_PREFIX = "bronze/production/source=usda_wap/"
_SILVER_LOG_KEY = "silver/wap_table01/_run_log.json"


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WAP Table 01 bronze → silver")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        default=False,
        help="Overwrite existing silver Parquets (default: skip).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Log what would be written without writing to S3.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------

def _key_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001
        return False


def _download_parquet(s3_client, bucket: str, key: str) -> pd.DataFrame:
    resp = s3_client.get_object(Bucket=bucket, Key=key)
    return pd.read_parquet(io.BytesIO(resp["Body"].read()))


def _upload_parquet(s3_client, bucket: str, key: str, df: pd.DataFrame) -> None:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=buf.getvalue(),
        ContentType="application/octet-stream",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )

    load_env()
    args = _parse_args()

    bucket: str = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region: str = args.aws_region or get_required_env("AWS_REGION")

    logger.info(
        "wap_silver_task  bucket=%s  force=%s  dry_run=%s",
        bucket, args.force_overwrite, args.dry_run,
    )

    start = datetime.now(timezone.utc)
    s3 = get_thread_local_s3_client(aws_region)

    # ------------------------------------------------------------------
    # Step 1 — discover and download all WAP bronze Parquets
    # ------------------------------------------------------------------
    bronze_keys = sorted(
        list_s3_keys(bucket, _BRONZE_PREFIX, suffix=".parquet", aws_region=aws_region)
    )
    logger.info("Found %d WAP bronze Parquets", len(bronze_keys))

    dfs: list[pd.DataFrame] = []
    for key in bronze_keys:
        try:
            df = _download_parquet(s3, bucket, key)
            dfs.append(df)
        except Exception as exc:  # noqa: BLE001
            logger.error("Download failed  key=%s: %s", key, exc)
            raise

    release_count = len(dfs)
    # Legacy EU era is identified by presence of the old "eu" column
    excluded_count = sum(1 for df in dfs if "eu" in df.columns)
    logger.info(
        "release_count=%d  excluded_legacy_eu=%d",
        release_count, excluded_count,
    )

    # ------------------------------------------------------------------
    # Step 2 — build long table
    # ------------------------------------------------------------------
    df_long = build_long_table(dfs)
    long_rows = len(df_long)
    logger.info("build_long_table → %d rows", long_rows)

    # ------------------------------------------------------------------
    # Step 3 — build revision table
    # ------------------------------------------------------------------
    df_revisions = build_revision_table(df_long)
    revisions_rows = len(df_revisions)
    logger.info("build_revision_table → %d rows", revisions_rows)

    # Count missing months (release months in bronze that produced 0 long rows
    # after exclusions — i.e. they were excluded or produced no data)
    present_release_months = set(df_long["release_month"].unique()) if long_rows else set()
    all_release_months = set()
    for df in dfs:
        if "release_month" in df.columns:
            all_release_months.update(df["release_month"].unique())
    missing_months_count = len(all_release_months - present_release_months)

    if args.dry_run:
        logger.info(
            "[DRY-RUN]  long_table_rows=%d  revisions_rows=%d"
            "  missing_months=%d",
            long_rows, revisions_rows, missing_months_count,
        )
        sys.exit(0)

    # ------------------------------------------------------------------
    # Step 4 — write silver Parquets
    # ------------------------------------------------------------------
    long_key = silver_wap_table01_key()
    revisions_key = silver_wap_table01_revisions_key()

    # Long table
    if force_overwrite_check(args.force_overwrite, s3, bucket, long_key):
        _upload_parquet(s3, bucket, long_key, df_long)
        logger.info("silver written  key=%s  rows=%d", long_key, long_rows)
    else:
        logger.info("silver exists — skipping  key=%s", long_key)

    # Revisions table
    if force_overwrite_check(args.force_overwrite, s3, bucket, revisions_key):
        _upload_parquet(s3, bucket, revisions_key, df_revisions)
        logger.info("silver written  key=%s  rows=%d", revisions_key, revisions_rows)
    else:
        logger.info("silver exists — skipping  key=%s", revisions_key)

    # ------------------------------------------------------------------
    # Step 5 — write run log
    # ------------------------------------------------------------------
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info("Done  elapsed=%.1fs", elapsed)

    try:
        run_log = {
            "run_date": datetime.now(timezone.utc).date().isoformat(),
            "elapsed_s": round(elapsed, 1),
            "release_count": release_count,
            "excluded_count": excluded_count,
            "long_table_rows": long_rows,
            "revisions_rows": revisions_rows,
            "missing_months_count": missing_months_count,
        }
        s3.put_object(
            Bucket=bucket,
            Key=_SILVER_LOG_KEY,
            Body=json.dumps(run_log, indent=2).encode(),
            ContentType="application/json",
        )
        logger.info("Run log written  key=%s", _SILVER_LOG_KEY)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to write run log: %s", exc)


def force_overwrite_check(force_overwrite: bool, s3_client, bucket: str, key: str) -> bool:
    """Return True if the key should be written (force or does not yet exist)."""
    if force_overwrite:
        return True
    return not _key_exists(s3_client, bucket, key)


if __name__ == "__main__":
    main()
