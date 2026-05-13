"""Glue Python Shell: raw → bronze NASA POWER.

Downloads raw JSON files from S3, parses the NASA POWER payload into daily rows,
and writes bronze Parquet files. Processes files concurrently using a thread pool.
Skips files that already have a bronze counterpart unless --force_overwrite is set.

Required args: --commodity, --bucket, --aws_region
Optional args: --ingest_date (default: today), --force_overwrite (default: false)
"""
from __future__ import annotations

import io
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from awsglue.utils import getResolvedOptions

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
    _subprocess.check_call([sys.executable, "-m", "pip", "install", _whl, "--no-deps", "--quiet"])


_install_leviathan()
# ---- End bootstrap ----

import boto3

from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_weather_key
from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys
from leviathan.transforms.raw_to_bronze.nasa_power import nasa_power_payload_to_daily_dataframe

logger = get_logger(__name__)

REQUIRED_ARGS = ["JOB_NAME", "commodity", "bucket", "aws_region"]
OPTIONAL_ARGS = ["ingest_date", "force_overwrite"]

args = getResolvedOptions(sys.argv, REQUIRED_ARGS + OPTIONAL_ARGS)

COMMODITY: str = args["commodity"]
BUCKET: str = args["bucket"]
AWS_REGION: str = args["aws_region"]
INGEST_DATE: str = args.get("ingest_date") or date.today().isoformat()
FORCE_OVERWRITE: bool = args.get("force_overwrite", "false").lower() == "true"

RAW_PREFIX = f"raw/weather/source=nasa_power/commodity={COMMODITY}/"
BRONZE_PREFIX = f"bronze/weather/source=nasa_power/commodity={COMMODITY}/"
MAX_WORKERS = 64


def _parse_hive_partition(key: str, field: str) -> str:
    parts = key.split("/")
    return next((p[len(field) + 1:] for p in parts if p.startswith(f"{field}=")), "")


def process_one(raw_key: str, existing_bronze: set[str]) -> tuple[str, str]:
    country = _parse_hive_partition(raw_key, "country")
    region = _parse_hive_partition(raw_key, "region")
    year_s = _parse_hive_partition(raw_key, "year")
    month_s = _parse_hive_partition(raw_key, "month")

    if not country or not region or not year_s or not month_s:
        return ("failed", f"Could not parse partitions from key: {raw_key}")

    year = int(year_s)
    month = int(month_s)
    filename = raw_key.rsplit("/", 1)[-1].replace(".json", ".parquet")

    bkey = bronze_weather_key(
        source="nasa_power",
        commodity=COMMODITY,
        country=country,
        region=region,
        year=year,
        month=month,
        filename=filename,
    )

    if bkey in existing_bronze:
        return ("skipped", bkey)

    try:
        response = get_thread_local_s3_client(AWS_REGION).get_object(Bucket=BUCKET, Key=raw_key)
        payload = json.loads(response["Body"].read())

        df = nasa_power_payload_to_daily_dataframe(
            payload=payload,
            source_file_name=raw_key.rsplit("/", 1)[-1],
            commodity=COMMODITY,
            country=country,
            region=region,
            ingest_date=INGEST_DATE,
        )

        buf = io.BytesIO()
        df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
        get_thread_local_s3_client(AWS_REGION).put_object(Body=buf.getvalue(), Bucket=BUCKET, Key=bkey)
        return ("success", bkey)

    except Exception as exc:  # noqa: BLE001
        return ("failed", f"{raw_key}: {exc}")


def main() -> None:
    raw_keys = list_s3_keys(BUCKET, RAW_PREFIX, suffix=".json", aws_region=AWS_REGION)
    logger.info("Found %d raw files for commodity=%s", len(raw_keys), COMMODITY)

    # One LIST call replaces N head_object calls for the skip check
    if FORCE_OVERWRITE:
        existing_bronze: set[str] = set()
        logger.info("force_overwrite=true — reprocessing all files")
    else:
        existing_bronze = set(
            list_s3_keys(BUCKET, BRONZE_PREFIX, suffix=".parquet", aws_region=AWS_REGION)
        )
        logger.info("%d existing bronze files will be skipped", len(existing_bronze))

    success = skipped = failed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(process_one, k, existing_bronze): k for k in raw_keys}
        for future in as_completed(futures):
            status, info = future.result()
            if status == "success":
                success += 1
            elif status == "skipped":
                skipped += 1
            else:
                failed += 1
                logger.error("Failed: %s", info)

    logger.info(
        "raw→bronze NASA POWER complete. success=%d  skipped=%d  failed=%d",
        success, skipped, failed,
    )
    if failed > 0:
        raise RuntimeError(f"{failed} files failed during raw→bronze NASA POWER transform.")


if __name__ == "__main__":
    main()
