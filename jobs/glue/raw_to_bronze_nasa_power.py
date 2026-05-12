"""Glue Python Shell job: raw → bronze for NASA POWER weather data.

Reads all raw JSON files from S3 under:
  raw/weather/source=nasa_power/commodity=<commodity>/...
Writes bronze Parquet files to S3 under:
  bronze/weather/source=nasa_power/commodity=<commodity>/...

Country and region are inferred from the S3 key path components.
Pass --ingest_date to override today's date (YYYY-MM-DD).
"""
from __future__ import annotations

import io
import sys
from datetime import date

from awsglue.utils import getResolvedOptions

import pandas as pd

# ---- Bootstrap: install leviathan package from S3 at runtime ----
import os as _os
import subprocess as _subprocess


def _install_leviathan() -> None:
    import boto3 as _boto3

    _bucket = next(
        (sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--bucket" and i + 1 < len(sys.argv)),
        None,
    )
    if not _bucket:
        raise RuntimeError("--bucket argument required for leviathan bootstrap")
    _whl = "/tmp/leviathan-0.1.0-py3-none-any.whl"
    if not _os.path.exists(_whl):
        _boto3.client("s3").download_file(_bucket, "glue-libs/leviathan-0.1.0-py3-none-any.whl", _whl)
    _subprocess.check_call([sys.executable, "-m", "pip", "install", _whl, "--quiet"])


_install_leviathan()
# ---- End bootstrap ----

from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_weather_key, raw_weather_key
from leviathan.storage.s3 import (
    download_s3_json,
    list_s3_keys,
    s3_object_exists,
    upload_bytes_to_s3,
)
from leviathan.transforms.raw_to_bronze.nasa_power import nasa_power_payload_to_daily_dataframe

logger = get_logger(__name__)

REQUIRED_ARGS = ["JOB_NAME", "commodity", "bucket", "aws_region"]
OPTIONAL_ARGS = ["ingest_date"]

args = getResolvedOptions(sys.argv, REQUIRED_ARGS + OPTIONAL_ARGS)

COMMODITY: str = args["commodity"]
BUCKET: str = args["bucket"]
AWS_REGION: str = args["aws_region"]
INGEST_DATE: str = args.get("ingest_date") or date.today().isoformat()

RAW_PREFIX = f"raw/weather/source=nasa_power/commodity={COMMODITY}/"


def infer_country_region(key: str) -> tuple[str, str]:
    """Extract country and region from an S3 key with Hive-style partitions."""
    parts = key.split("/")
    country = ""
    region = ""
    for part in parts:
        if part.startswith("country="):
            country = part[len("country="):]
        elif part.startswith("region="):
            region = part[len("region="):]
    if not country or not region:
        raise ValueError(f"Could not infer country/region from key: {key}")
    return country, region


def infer_year_month(key: str) -> tuple[int, int]:
    """Extract year and month from an S3 key with Hive-style partitions."""
    parts = key.split("/")
    year = 0
    month = 0
    for part in parts:
        if part.startswith("year="):
            year = int(part[len("year="):])
        elif part.startswith("month="):
            month = int(part[len("month="):])
    if not year or not month:
        raise ValueError(f"Could not infer year/month from key: {key}")
    return year, month


def main() -> None:
    raw_keys = list_s3_keys(BUCKET, RAW_PREFIX, suffix=".json", aws_region=AWS_REGION)
    logger.info("Found %d raw NASA POWER JSON files for commodity=%s", len(raw_keys), COMMODITY)

    success = 0
    skipped = 0
    failed = 0

    for raw_key in raw_keys:
        try:
            country, region = infer_country_region(raw_key)
            year, month = infer_year_month(raw_key)
        except ValueError as exc:
            logger.warning("Skipping key — %s", exc)
            failed += 1
            continue

        filename = raw_key.rsplit("/", 1)[-1].replace(".json", ".parquet")
        bronze_key = bronze_weather_key(
            source="nasa_power",
            commodity=COMMODITY,
            country=country,
            region=region,
            year=year,
            month=month,
            filename=filename,
        )

        if s3_object_exists(BUCKET, bronze_key, aws_region=AWS_REGION):
            logger.debug("Bronze already exists, skipping: %s", bronze_key)
            skipped += 1
            continue

        try:
            payload = download_s3_json(BUCKET, raw_key, aws_region=AWS_REGION)
            source_file_name = raw_key.rsplit("/", 1)[-1]

            df = nasa_power_payload_to_daily_dataframe(
                payload=payload,
                source_file_name=source_file_name,
                commodity=COMMODITY,
                country=country,
                region=region,
                ingest_date=INGEST_DATE,
            )

            buf = io.BytesIO()
            df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
            upload_bytes_to_s3(buf.getvalue(), BUCKET, bronze_key, aws_region=AWS_REGION)

            logger.info("Wrote bronze: %s  rows=%d", bronze_key, len(df))
            success += 1

        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to process %s — %s", raw_key, exc)
            failed += 1

    logger.info(
        "raw→bronze NASA POWER complete. success=%d  skipped=%d  failed=%d",
        success, skipped, failed,
    )

    if failed > 0:
        raise RuntimeError(f"{failed} files failed during raw→bronze NASA POWER transform.")


if __name__ == "__main__":
    main()
