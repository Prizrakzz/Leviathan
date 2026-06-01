"""AWS Batch task: USDA PSD bronze/ → silver/ layer.

Downloads all PSD bronze Parquets (one per monthly release date), applies the
silver transform, and writes a single consolidated silver Parquet to S3.

Output S3 keys
--------------
    silver/psd/part-000.parquet
    silver/psd/_run_log.json

Usage
-----
    # Idempotent run (skip if silver already exists)
    python jobs/batch/psd_silver_task.py \\
        --bucket leviathan-dev-shahem-001 --aws-region us-east-1

    # Force overwrite
    python jobs/batch/psd_silver_task.py \\
        --bucket leviathan-dev-shahem-001 --aws-region us-east-1 --force-overwrite

    # Dry-run (no writes)
    python jobs/batch/psd_silver_task.py \\
        --bucket leviathan-dev-shahem-001 --aws-region us-east-1 --dry-run
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from datetime import datetime, timezone

import boto3
import pandas as pd
from botocore.config import Config

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import silver_psd_key
from leviathan.storage.s3 import list_s3_keys
from leviathan.transforms.bronze_to_silver.usda_psd import transform_psd_bronze_to_silver

logger = get_logger("psd_silver_task")

_BRONZE_PREFIX = "bronze/production/source=usda_psd/"
_SILVER_LOG_KEY = "silver/psd/_run_log.json"


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="USDA PSD bronze → silver")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        default=False,
        help="Overwrite existing silver Parquet (default: skip).",
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

def _make_s3_client(aws_region: str):
    return boto3.client(
        "s3",
        region_name=aws_region,
        config=Config(retries={"max_attempts": 3, "mode": "standard"}),
    )


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


def _upload_json(s3_client, bucket: str, key: str, payload: dict) -> None:
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(payload, indent=2, default=str).encode(),
        ContentType="application/json",
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

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    s3 = _make_s3_client(aws_region)
    silver_key = silver_psd_key()
    start = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Locate bronze Parquets
    # ------------------------------------------------------------------
    bronze_keys = list_s3_keys(
        bucket, _BRONZE_PREFIX, suffix="part-000.parquet", aws_region=aws_region
    )
    bronze_keys.sort()

    logger.info(
        "PSD silver task  bucket=%s  bronze_partitions=%d  force=%s  dry_run=%s",
        bucket,
        len(bronze_keys),
        args.force_overwrite,
        args.dry_run,
    )

    if not bronze_keys:
        logger.error("No bronze PSD Parquets found under %s — aborting", _BRONZE_PREFIX)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Short-circuit if silver already up-to-date
    # ------------------------------------------------------------------
    if not args.force_overwrite and _key_exists(s3, bucket, silver_key):
        logger.info("Silver already exists at %s — skipping (use --force-overwrite)", silver_key)
        sys.exit(0)

    # ------------------------------------------------------------------
    # Download all bronze partitions
    # ------------------------------------------------------------------
    dfs: list[pd.DataFrame] = []
    for key in bronze_keys:
        logger.info("Downloading bronze  %s", key)
        try:
            df = _download_parquet(s3, bucket, key)
            dfs.append(df)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to download %s: %s", key, exc)
            sys.exit(1)

    # ------------------------------------------------------------------
    # Transform
    # ------------------------------------------------------------------
    logger.info("Running PSD silver transform on %d bronze DataFrames", len(dfs))
    try:
        silver_df = transform_psd_bronze_to_silver(dfs)
    except Exception as exc:  # noqa: BLE001
        logger.error("PSD silver transform failed: %s", exc)
        sys.exit(1)

    logger.info(
        "Silver DataFrame: rows=%d  cols=%d  slugs=%d  releases=%d",
        len(silver_df),
        len(silver_df.columns),
        silver_df["leviathan_slug"].nunique(),
        silver_df["release_date"].nunique(),
    )

    # ------------------------------------------------------------------
    # Write silver Parquet
    # ------------------------------------------------------------------
    if args.dry_run:
        logger.info("DRY RUN — skipping write to %s", silver_key)
    else:
        logger.info("Writing silver Parquet  %s", silver_key)
        try:
            _upload_parquet(s3, bucket, silver_key, silver_df)
            logger.info("Silver written  %s", silver_key)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to write silver Parquet: %s", exc)
            sys.exit(1)

    # ------------------------------------------------------------------
    # Write run log
    # ------------------------------------------------------------------
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    run_log = {
        "task":             "psd_silver_task",
        "completed_at":     datetime.now(timezone.utc).isoformat(),
        "bucket":           bucket,
        "silver_key":       silver_key,
        "bronze_partitions": bronze_keys,
        "silver_rows":      len(silver_df),
        "silver_slugs":     int(silver_df["leviathan_slug"].nunique()),
        "silver_releases":  int(silver_df["release_date"].nunique()),
        "dry_run":          args.dry_run,
        "force_overwrite":  args.force_overwrite,
        "elapsed_seconds":  round(elapsed, 2),
    }

    if not args.dry_run:
        try:
            _upload_json(s3, bucket, _SILVER_LOG_KEY, run_log)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not write run log: %s", exc)

    logger.info("Done  elapsed=%.1fs", elapsed)


if __name__ == "__main__":
    main()
