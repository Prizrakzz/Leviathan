"""Local silver backfill for USDA FAS ESR — avoids Glue quota limits.

Reads every bronze Parquet from S3, runs transform_esr_bronze_to_silver(), and
writes Parquet to the silver S3 key.  Idempotent via --skip-existing.

One-to-one mapping: each bronze (commodity_code, market_year, as_of_date)
partition produces exactly one silver partition at the same coordinates.

Usage:
    python jobs/ingest/backfill_silver_usda_esr.py
    python jobs/ingest/backfill_silver_usda_esr.py --skip-existing
    python jobs/ingest/backfill_silver_usda_esr.py --commodity-codes 401 --start-year 2024 --end-year 2024
    python jobs/ingest/backfill_silver_usda_esr.py --dry-run
"""
from __future__ import annotations

import argparse
import datetime
import io
import logging
import sys
from pathlib import Path

import boto3

# Ensure the src package is importable when run from the project root.
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from leviathan.common.config import load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_esr_key, silver_esr_key
from leviathan.transforms.bronze_to_silver.usda_esr import transform_esr_bronze_to_silver

logger = get_logger(__name__)

BUCKET = "leviathan-dev-shahem-001"
AWS_REGION = "us-east-1"

_DEFAULT_COMMODITY_CODES = [101, 102, 103, 104, 107, 401, 701, 801, 901, 902]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Local ESR bronze → silver backfill")
    p.add_argument("--commodity-codes", nargs="+", type=int, default=_DEFAULT_COMMODITY_CODES)
    p.add_argument("--start-year", type=int, default=1990)
    p.add_argument("--end-year", type=int, default=datetime.date.today().year)
    p.add_argument(
        "--as-of-date",
        default=None,
        help=(
            "Snapshot date of the bronze files to read (YYYYMMDD). "
            "Defaults to today (matches the backfill_bronze default)."
        ),
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip pairs where the silver key already exists in S3.",
    )
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def _s3_key_exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except s3.exceptions.ClientError as exc:
        if exc.response["ResponseMetadata"]["HTTPStatusCode"] == 404:
            return False
        raise


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    import pandas as pd

    load_env()
    args = parse_args()
    s3 = boto3.client("s3", region_name=AWS_REGION)

    as_of_date = args.as_of_date or datetime.date.today().strftime("%Y%m%d")

    pairs = [
        (code, year)
        for code in args.commodity_codes
        for year in range(args.start_year, args.end_year + 1)
    ]
    total = len(pairs)
    logger.info(
        "ESR local silver backfill — %d pairs  as_of_date=%s",
        total,
        as_of_date,
    )
    if args.dry_run:
        logger.info("DRY RUN — no data will be read or written")

    success = skipped = failed = 0

    for idx, (commodity_code, market_year) in enumerate(pairs, 1):
        b_key = bronze_esr_key(commodity_code, market_year, as_of_date)
        s_key = silver_esr_key(commodity_code, market_year, as_of_date)

        # --- Skip if silver already written ---
        if args.skip_existing and not args.dry_run:
            if _s3_key_exists(s3, BUCKET, s_key):
                logger.info(
                    "[%d/%d] SKIP (silver exists) commodity_code=%d year=%d",
                    idx, total, commodity_code, market_year,
                )
                skipped += 1
                continue

        # --- Skip if bronze does not exist ---
        if not args.dry_run and not _s3_key_exists(s3, BUCKET, b_key):
            logger.warning(
                "[%d/%d] SKIP (no bronze) commodity_code=%d year=%d  key=%s",
                idx, total, commodity_code, market_year, b_key,
            )
            skipped += 1
            continue

        if args.dry_run:
            logger.info(
                "[%d/%d] DRY RUN commodity_code=%d year=%d  bronze=%s",
                idx, total, commodity_code, market_year, b_key,
            )
            success += 1
            continue

        try:
            # --- Download bronze Parquet ---
            bronze_bytes = s3.get_object(Bucket=BUCKET, Key=b_key)["Body"].read()
            df = pd.read_parquet(io.BytesIO(bronze_bytes))

            # --- Transform bronze → silver ---
            silver_df = transform_esr_bronze_to_silver(df, market_year=market_year)

            # --- Serialize to Parquet in-memory ---
            buf = io.BytesIO()
            silver_df.to_parquet(buf, index=False, compression="snappy", engine="pyarrow")
            buf.seek(0)
            parquet_bytes = buf.read()

            # --- Upload to silver ---
            s3.put_object(Bucket=BUCKET, Key=s_key, Body=parquet_bytes)
            logger.info(
                "[%d/%d] OK commodity_code=%d year=%d  rows=%d  %d KB → s3://%s/%s",
                idx, total, commodity_code, market_year,
                len(silver_df), len(parquet_bytes) // 1024,
                BUCKET, s_key,
            )
            success += 1

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[%d/%d] FAILED commodity_code=%d year=%d: %s",
                idx, total, commodity_code, market_year, exc,
            )
            failed += 1

    logger.info(
        "Silver backfill complete.  success=%d  skipped=%d  failed=%d",
        success, skipped, failed,
    )
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
