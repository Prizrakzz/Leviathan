"""Local bronze backfill for USDA FAS ESR — avoids Glue quota limits.

Reads every raw JSON from S3, runs transform_esr_json_to_bronze(), and
writes Parquet to the bronze S3 key.  Idempotent via --skip-existing.

Usage:
    python jobs/ingest/backfill_bronze_usda_esr.py
    python jobs/ingest/backfill_bronze_usda_esr.py --skip-existing
    python jobs/ingest/backfill_bronze_usda_esr.py --commodity-codes 401 --start-year 2025 --end-year 2025
    python jobs/ingest/backfill_bronze_usda_esr.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import datetime
import io
import sys
from pathlib import Path

import boto3
import pyarrow.parquet as pq

# Ensure the src package is importable when run from the project root.
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from leviathan.common.config import load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_esr_key, raw_esr_backfill_key
from leviathan.transforms.raw_to_bronze.usda_esr import transform_esr_json_to_bronze

logger = get_logger(__name__)

BUCKET = "leviathan-dev-shahem-001"
AWS_REGION = "us-east-1"

_DEFAULT_COMMODITY_CODES = [101, 102, 103, 104, 107, 401, 701, 801, 901, 902]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Local ESR raw → bronze backfill")
    p.add_argument("--commodity-codes", nargs="+", type=int, default=_DEFAULT_COMMODITY_CODES)
    p.add_argument("--start-year", type=int, default=1990)
    p.add_argument("--end-year", type=int, default=datetime.date.today().year)
    p.add_argument("--ingest-date", default=datetime.date.today().isoformat())
    p.add_argument("--skip-existing", action="store_true", help="Skip pairs where bronze key already exists in S3")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()
    args = parse_args()
    s3 = boto3.client("s3", region_name=AWS_REGION)

    pairs = [
        (code, year)
        for code in args.commodity_codes
        for year in range(args.start_year, args.end_year + 1)
    ]
    total = len(pairs)
    logger.info("ESR local bronze backfill — %d pairs to process", total)
    if args.dry_run:
        logger.info("DRY RUN — no data will be read or written")

    success = skipped = failed = 0

    for idx, (commodity_code, market_year) in enumerate(pairs, 1):
        raw_key = raw_esr_backfill_key(commodity_code, market_year)
        b_key = bronze_esr_key(commodity_code, market_year, args.ingest_date.replace("-", ""))

        # Skip if bronze already written
        if args.skip_existing and not args.dry_run:
            try:
                s3.head_object(Bucket=BUCKET, Key=b_key)
                logger.info("[%d/%d] SKIP (bronze exists) commodity_code=%d year=%d", idx, total, commodity_code, market_year)
                skipped += 1
                continue
            except s3.exceptions.ClientError as exc:
                if exc.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
                    raise

        # Check raw exists
        try:
            s3.head_object(Bucket=BUCKET, Key=raw_key)
        except s3.exceptions.ClientError as exc:
            if exc.response["ResponseMetadata"]["HTTPStatusCode"] == 404:
                logger.warning("[%d/%d] SKIP (no raw) commodity_code=%d year=%d", idx, total, commodity_code, market_year)
                skipped += 1
                continue
            raise

        if args.dry_run:
            logger.info("[%d/%d] DRY RUN commodity_code=%d year=%d  raw=%s", idx, total, commodity_code, market_year, raw_key)
            success += 1
            continue

        try:
            # Download raw JSON
            raw_bytes = s3.get_object(Bucket=BUCKET, Key=raw_key)["Body"].read()

            # Transform
            df = transform_esr_json_to_bronze(
                raw_bytes=raw_bytes,
                commodity_code=commodity_code,
                market_year=market_year,
                as_of_date=args.ingest_date.replace("-", ""),
                ingest_date=args.ingest_date,
            )

            # Serialize to Parquet in-memory
            buf = io.BytesIO()
            df.to_parquet(buf, index=False, compression="snappy", engine="pyarrow")
            buf.seek(0)
            parquet_bytes = buf.read()

            # Upload to bronze
            s3.put_object(Bucket=BUCKET, Key=b_key, Body=parquet_bytes)
            logger.info(
                "[%d/%d] OK commodity_code=%d year=%d  rows=%d  %d KB → s3://%s/%s",
                idx, total, commodity_code, market_year, len(df), len(parquet_bytes) // 1024, BUCKET, b_key,
            )
            success += 1

        except Exception as exc:  # noqa: BLE001
            logger.error("[%d/%d] FAILED commodity_code=%d year=%d: %s", idx, total, commodity_code, market_year, exc)
            failed += 1

    logger.info("Bronze backfill complete.  success=%d  skipped=%d  failed=%d", success, skipped, failed)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
