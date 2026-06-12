"""AWS Batch task: UNICA biweekly bronze/ → silver/ layer.

Reads all bronze Parquet files produced by ``unica_biweekly_task.py`` for
the four main tables, applies the silver transforms, and writes one flat
Parquet per output table to silver/.

Output S3 keys
--------------
    silver/unica_biweekly_season_history/part-000.parquet
    silver/unica_biweekly_release_series/part-000.parquet
    silver/unica_corn_ethanol/part-000.parquet
    silver/unica_monthly_ethanol_sales/part-000.parquet

Usage
-----
    # Idempotent run (skip existing silver Parquets)
    python jobs/batch/unica_biweekly_silver_task.py \\
        --bucket leviathan-dev-shahem-001 --aws-region us-east-1

    # Force overwrite
    python jobs/batch/unica_biweekly_silver_task.py \\
        --bucket leviathan-dev-shahem-001 --aws-region us-east-1 --force-overwrite

    # Dry-run (no writes)
    python jobs/batch/unica_biweekly_silver_task.py \\
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
    silver_unica_biweekly_season_history_key,
    silver_unica_biweekly_release_series_key,
    silver_unica_corn_ethanol_key,
    silver_unica_monthly_ethanol_sales_key,
)
from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys
from leviathan.transforms.bronze_to_silver.unica_biweekly import (
    transform_corn_ethanol,
    transform_monthly_ethanol_sales,
    transform_release_series,
    transform_season_history,
)

logger = get_logger("unica_biweekly_silver_task")

_BRONZE_PREFIX = "bronze/production/source=unica_biweekly/"
_SILVER_LOG_KEY = "silver/unica_biweekly/_run_log.json"

# Maps bronze table name → (transform function, silver key function)
_TABLE_MAP = [
    ("fortnight_production",  transform_season_history,       silver_unica_biweekly_season_history_key),
    ("summary_snapshot",      transform_release_series,       silver_unica_biweekly_release_series_key),
    ("corn_ethanol",          transform_corn_ethanol,         silver_unica_corn_ethanol_key),
    ("monthly_ethanol_sales", transform_monthly_ethanol_sales, silver_unica_monthly_ethanol_sales_key),
]


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UNICA biweekly bronze → silver")
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
# Per-table processing
# ---------------------------------------------------------------------------

def _process_table(
    table_name: str,
    transform_fn,
    silver_key_fn,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
    dry_run: bool,
) -> dict:
    """Download all bronze Parquets for *table_name*, transform, upload silver.

    Returns a summary dict with keys: table, bronze_files, input_rows,
    output_rows, silver_key, status.
    """
    s3 = get_thread_local_s3_client(aws_region)
    prefix = f"{_BRONZE_PREFIX}table={table_name}/"

    bronze_keys = list(list_s3_keys(bucket, prefix, suffix=".parquet", aws_region=aws_region))
    logger.info("table=%s  bronze_keys=%d", table_name, len(bronze_keys))

    if not bronze_keys:
        logger.warning("table=%s: no bronze Parquets found under %s", table_name, prefix)
        return {
            "table": table_name,
            "bronze_files": 0,
            "input_rows": 0,
            "output_rows": 0,
            "silver_key": silver_key_fn(),
            "status": "empty",
        }

    # Download all bronze Parquets serially.
    frames: list[pd.DataFrame] = []
    for key in sorted(bronze_keys):
        try:
            df = _download_parquet(s3, bucket, key)
            frames.append(df)
        except Exception as exc:  # noqa: BLE001
            logger.error("Download failed  key=%s: %s", key, exc)
            raise

    df_bronze = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    input_rows = len(df_bronze)
    logger.info("table=%s  input_rows=%d", table_name, input_rows)

    # Transform.
    df_silver = transform_fn(df_bronze)
    output_rows = len(df_silver)
    silver_key = silver_key_fn()

    if dry_run:
        logger.info(
            "[DRY-RUN] table=%s  output_rows=%d  silver_key=%s",
            table_name, output_rows, silver_key,
        )
        return {
            "table": table_name,
            "bronze_files": len(bronze_keys),
            "input_rows": input_rows,
            "output_rows": output_rows,
            "silver_key": silver_key,
            "status": "dry_run",
        }

    # Skip if exists and not force-overwrite.
    if not force_overwrite and _key_exists(s3, bucket, silver_key):
        logger.info("silver exists — skipping  key=%s", silver_key)
        return {
            "table": table_name,
            "bronze_files": len(bronze_keys),
            "input_rows": input_rows,
            "output_rows": output_rows,
            "silver_key": silver_key,
            "status": "skipped",
        }

    _upload_parquet(s3, bucket, silver_key, df_silver)
    logger.info(
        "silver written  table=%s  output_rows=%d  key=%s",
        table_name, output_rows, silver_key,
    )
    return {
        "table": table_name,
        "bronze_files": len(bronze_keys),
        "input_rows": input_rows,
        "output_rows": output_rows,
        "silver_key": silver_key,
        "status": "written",
    }


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
        "unica_biweekly_silver_task  bucket=%s  force=%s  dry_run=%s",
        bucket, args.force_overwrite, args.dry_run,
    )

    start = datetime.now(timezone.utc)
    table_results: list[dict] = []
    errors = 0

    for table_name, transform_fn, silver_key_fn in _TABLE_MAP:
        try:
            result = _process_table(
                table_name=table_name,
                transform_fn=transform_fn,
                silver_key_fn=silver_key_fn,
                bucket=bucket,
                aws_region=aws_region,
                force_overwrite=args.force_overwrite,
                dry_run=args.dry_run,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("FAILED  table=%s: %s", table_name, exc)
            table_results.append({
                "table": table_name,
                "status": "error",
                "error": str(exc),
            })
            errors += 1
            continue
        table_results.append(result)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        "Done  tables=%d  errors=%d  elapsed=%.1fs",
        len(table_results), errors, elapsed,
    )

    # Write run log to S3 (skip on dry-run).
    if not args.dry_run:
        try:
            run_log = {
                "run_date":    datetime.now(timezone.utc).date().isoformat(),
                "elapsed_s":   round(elapsed, 1),
                "tables":      table_results,
                "errors":      errors,
            }
            s3 = get_thread_local_s3_client(aws_region)
            s3.put_object(
                Bucket=bucket,
                Key=_SILVER_LOG_KEY,
                Body=json.dumps(run_log, indent=2).encode(),
                ContentType="application/json",
            )
            logger.info("Run log written  key=%s", _SILVER_LOG_KEY)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to write run log: %s", exc)

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
