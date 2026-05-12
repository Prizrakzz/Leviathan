"""Glue Python Shell job: bronze → silver for NASA POWER weather data.

Reads all bronze Parquet files from S3 under:
  bronze/weather/source=nasa_power/commodity=<commodity>/...
Writes silver Parquet files to S3 under:
  silver/weather/source=nasa_power/commodity=<commodity>/...

Uses s3fs so pd.read_parquet() works directly on s3:// URIs.
"""
from __future__ import annotations

import io
import sys

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
from leviathan.storage.paths import silver_weather_key
from leviathan.storage.s3 import list_s3_keys, s3_object_exists, upload_bytes_to_s3
from leviathan.transforms.bronze_to_silver.nasa_power_weather import clean_one_weather_df

logger = get_logger(__name__)

REQUIRED_ARGS = ["JOB_NAME", "commodity", "bucket", "aws_region"]

args = getResolvedOptions(sys.argv, REQUIRED_ARGS)

COMMODITY: str = args["commodity"]
BUCKET: str = args["bucket"]
AWS_REGION: str = args["aws_region"]

BRONZE_PREFIX = f"bronze/weather/source=nasa_power/commodity={COMMODITY}/"


def main() -> None:
    bronze_keys = list_s3_keys(BUCKET, BRONZE_PREFIX, suffix=".parquet", aws_region=AWS_REGION)
    logger.info(
        "Found %d bronze NASA POWER Parquet files for commodity=%s",
        len(bronze_keys), COMMODITY,
    )

    success = 0
    skipped = 0
    failed = 0

    for bronze_key in bronze_keys:
        # Derive silver key from the bronze key path components
        # bronze: bronze/weather/source=nasa_power/commodity=cocoa/country=X/region=Y/year=YYYY/month=MM/file.parquet
        # silver: silver/weather/source=nasa_power/commodity=cocoa/country=X/region=Y/year=YYYY/month=MM/file.parquet
        silver_key = bronze_key.replace("bronze/weather/", "silver/weather/", 1)

        if s3_object_exists(BUCKET, silver_key, aws_region=AWS_REGION):
            logger.debug("Silver already exists, skipping: %s", silver_key)
            skipped += 1
            continue

        try:
            df = pd.read_parquet(
                f"s3://{BUCKET}/{bronze_key}",
                storage_options={"anon": False},
            )

            silver = clean_one_weather_df(df, source_label=bronze_key)

            if silver.empty:
                logger.warning("Empty silver output for %s, skipping", bronze_key)
                skipped += 1
                continue

            buf = io.BytesIO()
            silver.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
            upload_bytes_to_s3(buf.getvalue(), BUCKET, silver_key, aws_region=AWS_REGION)

            logger.info("Wrote silver: %s  rows=%d", silver_key, len(silver))
            success += 1

        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to process %s — %s", bronze_key, exc)
            failed += 1

    logger.info(
        "bronze→silver NASA POWER complete. success=%d  skipped=%d  failed=%d",
        success, skipped, failed,
    )

    if failed > 0:
        raise RuntimeError(f"{failed} files failed during bronze→silver NASA POWER transform.")


if __name__ == "__main__":
    main()
