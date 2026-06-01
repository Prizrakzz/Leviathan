"""AWS Batch task: World Bank Pink Sheet bronze/ → silver/ layer.

Downloads all Pink Sheet bronze Parquets, applies the silver transform,
and writes one silver Parquet to S3:

Output S3 key
-------------
    silver/pink_sheet/part-000.parquet

A JSON run log is written to:
    silver/pink_sheet/_run_log.json

Usage
-----
    # Idempotent run (skip if silver already exists)
    python jobs/batch/pink_sheet_silver_task.py \\
        --bucket leviathan-dev-shahem-001 --aws-region us-east-1

    # Force overwrite
    python jobs/batch/pink_sheet_silver_task.py \\
        --bucket leviathan-dev-shahem-001 --aws-region us-east-1 --force-overwrite

    # Dry-run (no writes)
    python jobs/batch/pink_sheet_silver_task.py \\
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
from leviathan.storage.paths import silver_pink_sheet_key
from leviathan.storage.s3 import list_s3_keys
from leviathan.transforms.bronze_to_silver.pink_sheet import build_silver

logger = get_logger("pink_sheet_silver_task")

_BRONZE_PREFIX = "bronze/production/source=world_bank_pink_sheet/"
_SILVER_LOG_KEY = "silver/pink_sheet/_run_log.json"


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pink Sheet bronze → silver")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        default=False,
        help="Overwrite existing silver Parquet (default: skip if already exists).",
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


def _should_write(force_overwrite: bool, s3_client, bucket: str, key: str) -> bool:
    """Return True if the key should be (over)written."""
    if force_overwrite:
        return True
    return not _key_exists(s3_client, bucket, key)


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
        "pink_sheet_silver_task  bucket=%s  force=%s  dry_run=%s",
        bucket, args.force_overwrite, args.dry_run,
    )

    start = datetime.now(timezone.utc)
    s3 = _make_s3_client(aws_region)

    # ------------------------------------------------------------------
    # Step 1 — discover and download all Pink Sheet bronze Parquets
    # ------------------------------------------------------------------
    bronze_keys = sorted(
        list_s3_keys(bucket, _BRONZE_PREFIX, suffix=".parquet", aws_region=aws_region)
    )
    logger.info("Found %d Pink Sheet bronze Parquets", len(bronze_keys))

    if not bronze_keys:
        logger.error("No bronze Parquets found under %s — aborting.", _BRONZE_PREFIX)
        sys.exit(1)

    dfs: list[pd.DataFrame] = []
    for key in bronze_keys:
        try:
            df = _download_parquet(s3, bucket, key)
            dfs.append(df)
            logger.info("downloaded  %s  rows=%d", key, len(df))
        except Exception as exc:  # noqa: BLE001
            logger.error("Download failed  key=%s: %s", key, exc)
            raise

    release_count = len(dfs)
    release_yms = sorted({df["release_ym"].iloc[0] for df in dfs if "release_ym" in df.columns and len(df) > 0})
    logger.info("release_count=%d  releases=%s", release_count, release_yms)

    # ------------------------------------------------------------------
    # Step 2 — build silver table
    # ------------------------------------------------------------------
    df_silver = build_silver(dfs)
    silver_rows = len(df_silver)
    date_min = str(df_silver["date"].min().date()) if silver_rows else "n/a"
    date_max = str(df_silver["date"].max().date()) if silver_rows else "n/a"
    logger.info(
        "build_silver → %d rows  date_range=%s→%s", silver_rows, date_min, date_max
    )

    if args.dry_run:
        logger.info(
            "[DRY-RUN]  silver_rows=%d  date_range=%s→%s",
            silver_rows, date_min, date_max,
        )
        sys.exit(0)

    # ------------------------------------------------------------------
    # Step 3 — write silver Parquet
    # ------------------------------------------------------------------
    silver_key = silver_pink_sheet_key()

    if _should_write(args.force_overwrite, s3, bucket, silver_key):
        _upload_parquet(s3, bucket, silver_key, df_silver)
        logger.info("silver written  key=%s  rows=%d", silver_key, silver_rows)
    else:
        logger.info("silver exists — skipping  key=%s", silver_key)

    # ------------------------------------------------------------------
    # Step 4 — write run log
    # ------------------------------------------------------------------
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info("Done  elapsed=%.1fs", elapsed)

    try:
        run_log = {
            "run_date": datetime.now(timezone.utc).date().isoformat(),
            "elapsed_s": round(elapsed, 1),
            "release_count": release_count,
            "releases": release_yms,
            "silver_rows": silver_rows,
            "date_min": date_min,
            "date_max": date_max,
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


if __name__ == "__main__":
    main()
