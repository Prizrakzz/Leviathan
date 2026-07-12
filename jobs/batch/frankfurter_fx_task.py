"""AWS Batch entrypoint: Frankfurter FX -> raw + bronze + silver (SILVER-F040).

Builds the ``silver_fred_fx`` table (a documented legacy misnomer -- the true source
is Frankfurter, see ADR-003) from scratch: fetch the base=USD time series, parse a
long bronze, derive the wide silver (90-day calendar-lag percent changes), and publish
the silver through the shadow-first controlled publisher with an EXPLICIT registry-derived
arrow schema (INV-2/INV-6). Default ``--publish-mode`` is dry-run (nothing written);
canonical requires a verified signed approval.

S3 layout (truthful ``source=frankfurter`` prefix for raw/bronze; canonical silver keeps
the legacy ``silver/fred_fx/`` location per ADR-003):
    raw:    raw/fx/source=frankfurter/timeseries.json
    bronze: bronze/fx/source=frankfurter/part-000.parquet
    silver: silver/fred_fx/part-000.parquet

Usage:
    python jobs/batch/frankfurter_fx_task.py --dry-run
    python jobs/batch/frankfurter_fx_task.py --publish-mode shadow
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
from datetime import date

import requests

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import silver_fred_fx_key
from leviathan.storage.s3 import get_thread_local_s3_client, upload_bytes_to_s3
from leviathan.transforms.bronze_to_silver.frankfurter_fx import build_fx_silver
from leviathan.transforms.raw_to_bronze.frankfurter_fx import SERIES_MAP, extract_fx_bronze
from jobs.batch._sb_producer_publish import publish_flat_silver

logger = get_logger("frankfurter_fx_task")

_API_BASE = "https://api.frankfurter.dev/v1"
_START_DATE = "2004-12-31"          # matches the existing history floor (OP-6)
_TIMEOUT = 60

RAW_KEY = "raw/fx/source=frankfurter/timeseries.json"
BRONZE_KEY = "bronze/fx/source=frankfurter/part-000.parquet"


def _timeseries_url(start: str, end: str) -> str:
    symbols = ",".join(SERIES_MAP.keys())
    return f"{_API_BASE}/{start}..{end}?base=USD&symbols={symbols}"


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(description="Frankfurter FX -> raw + bronze + silver")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--start", default=_START_DATE)
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--dry-run", action="store_true",
                        help="do not write raw/bronze; the silver publish still honours --publish-mode")
    # --publish-mode is consumed by the publish guard via sys.argv (default dry-run).
    parser.add_argument("--publish-mode", default=None,
                        help="dry-run|shadow|canonical (default dry-run)")
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    s3 = get_thread_local_s3_client(aws_region)

    url = _timeseries_url(args.start, args.end)
    logger.info("Fetching %s", url)
    resp = requests.get(url, timeout=_TIMEOUT)
    resp.raise_for_status()
    raw_bytes = resp.content
    logger.info("Downloaded %d bytes", len(raw_bytes))

    if not args.dry_run:
        upload_bytes_to_s3(raw_bytes, bucket, RAW_KEY, aws_region)
        logger.info("Raw written -> %s", RAW_KEY)

    df_bronze = extract_fx_bronze(raw_bytes)
    if not args.dry_run:
        buf = io.BytesIO()
        df_bronze.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
        s3.put_object(Bucket=bucket, Key=BRONZE_KEY, Body=buf.getvalue(),
                      ContentType="application/octet-stream")
        logger.info("Bronze written -> %s  rows=%d", BRONZE_KEY, len(df_bronze))

    df_silver = build_fx_silver(df_bronze)

    manifest = publish_flat_silver(
        table_name="silver_fred_fx",
        df=df_silver,
        job="frankfurter_fx_task",
        canonical_key=silver_fred_fx_key(),
        bucket=bucket,
        s3_client=s3,
        argv=sys.argv,
    )
    logger.info("Silver publish %s  state=%s  rows=%d",
                silver_fred_fx_key(), manifest.state.value, len(df_silver))


if __name__ == "__main__":
    main()
