"""Glue Python Shell: CHIRPS v3 COG → bronze.

Reads CHIRPS v3 Cloud-Optimized GeoTIFF files directly via HTTP range requests
(rasterio/vsicurl).  No raw S3 tier — pixel values are extracted and written
straight to bronze Parquet, one file per region per month.

The COG files are permanently hosted at UCSB.  Re-running this job is free:
it re-reads the same public files rather than burning API quota.

Required args: --commodity, --year, --bucket, --aws_region
Optional args: --ingest_date (default: today), --force_overwrite (default: false)
"""
from __future__ import annotations

# GDAL env vars must be set before rasterio is imported anywhere in the process.
import os as _os
_os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
_os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "3")
_os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "1")
_os.environ.setdefault("GDAL_HTTP_TIMEOUT", "30")
_os.environ.setdefault("CPL_VSIL_CURL_CACHE_SIZE", "200000000")

import sys
import subprocess as _subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed


# ---- Bootstrap: install leviathan package from S3 at runtime ----
def _install_leviathan() -> None:
    import boto3 as _boto3
    import time as _time

    _bucket = next(
        (sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--bucket" and i + 1 < len(sys.argv)),
        None,
    )
    if not _bucket:
        raise RuntimeError("--bucket argument required for leviathan bootstrap")
    _whl = "/tmp/leviathan-0.1.0-py3-none-any.whl"
    for _attempt in range(3):
        try:
            if not _os.path.exists(_whl):
                _boto3.client("s3").download_file(_bucket, "glue-libs/leviathan-0.1.0-py3-none-any.whl", _whl)
            _subprocess.check_call([sys.executable, "-m", "pip", "install", _whl, "--no-deps", "--quiet"])
            return
        except Exception:
            if _attempt == 2:
                raise
            if _os.path.exists(_whl):
                _os.remove(_whl)
            _time.sleep(5 * (_attempt + 1))


try:
    _install_leviathan()
except Exception as _exc:
    print(f"[BOOTSTRAP ERROR] {type(_exc).__name__}: {_exc}", flush=True)
    raise
# ---- End bootstrap ----

import calendar
import io
from datetime import date

import boto3
import pandas as pd
import yaml

from leviathan.common.logging import get_logger
from leviathan.ingestion.weather.chirps import fetch_chirps_daily_values
from leviathan.storage.paths import bronze_weather_key
from leviathan.storage.s3 import get_thread_local_s3_client

logger = get_logger("chirps_to_bronze")

_REQUIRED_ARGS = ["commodity", "year", "bucket", "aws_region"]


def _parse_args() -> dict[str, str]:
    try:
        from awsglue.utils import getResolvedOptions  # type: ignore[import]
        return getResolvedOptions(sys.argv, _REQUIRED_ARGS)
    except ImportError:
        result: dict[str, str] = {}
        for arg in _REQUIRED_ARGS:
            idx = next((i for i, a in enumerate(sys.argv) if a == f"--{arg}"), None)
            if idx is not None and idx + 1 < len(sys.argv):
                result[arg] = sys.argv[idx + 1]
            else:
                raise RuntimeError(f"Missing required argument: --{arg}")
        return result


def _parse_optional(name: str, default: str) -> str:
    idx = next((i for i, a in enumerate(sys.argv) if a == f"--{name}"), None)
    return sys.argv[idx + 1] if idx is not None and idx + 1 < len(sys.argv) else default


def _load_regions(s3_client, bucket: str, commodity: str) -> list[dict]:
    """Download and flatten the geography config for this commodity from S3."""
    key = f"configs/geographies/{commodity}_regions.yaml"
    body = s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
    config = yaml.safe_load(body)
    locations: list[dict] = []
    for region_block in config["regions"]:
        country = region_block["country"]
        for loc in region_block["locations"]:
            locations.append({
                "country": country,
                "region": loc["region"],
                "latitude": loc["latitude"],
                "longitude": loc["longitude"],
            })
    return locations


def _process_month(
    aws_region: str,
    bucket: str,
    commodity: str,
    year: int,
    month: int,
    locations: list[dict],
    ingest_date: str,
    force_overwrite: bool,
) -> None:
    """Extract CHIRPS values for every day in a month and write one Parquet per region.

    All days are fetched concurrently — each rasterio.open() call opens an
    independent GDAL dataset handle, so parallel reads are safe.
    """
    days_in_month = calendar.monthrange(year, month)[1]
    region_rows: dict[tuple[str, str], list[dict]] = {}

    def _fetch_day(day: int) -> tuple[int, dict]:
        try:
            return day, fetch_chirps_daily_values(year, month, day, locations)
        except Exception as exc:
            logger.warning(
                "Failed to fetch %d-%02d-%02d after retries: %s — skipping day",
                year, month, day, exc,
            )
            return day, {}

    # Fetch all days in this month concurrently.
    with ThreadPoolExecutor(max_workers=days_in_month) as pool:
        futures = {pool.submit(_fetch_day, d): d for d in range(1, days_in_month + 1)}
        for future in as_completed(futures):
            day, values = future.result()
            if not values:
                continue
            day_str = date(year, month, day).isoformat()
            for loc in locations:
                region = loc["region"]
                country = loc["country"]
                region_rows.setdefault((country, region), []).append({
                    "commodity": commodity,
                    "source": "chirps",
                    "country": country,
                    "region": region,
                    "date": day_str,
                    "year": year,
                    "month": month,
                    "day": day,
                    "latitude": loc["latitude"],
                    "longitude": loc["longitude"],
                    "precipitation_mm": values.get(region),
                    "ingest_date": ingest_date,
                })

    if not region_rows:
        logger.warning("No data collected for %d-%02d commodity=%s", year, month, commodity)
        return

    s3_client = get_thread_local_s3_client(aws_region)
    for (country, region), rows in region_rows.items():
        bkey = bronze_weather_key("chirps", commodity, country, region, year, month, "part-000.parquet")

        if not force_overwrite:
            try:
                s3_client.head_object(Bucket=bucket, Key=bkey)
                logger.info("Skipping existing bronze: %s", bkey)
                continue
            except s3_client.exceptions.ClientError as exc:
                if exc.response["Error"]["Code"] != "404":
                    raise

        df = pd.DataFrame(rows)
        buf = io.BytesIO()
        df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
        s3_client.put_object(Bucket=bucket, Key=bkey, Body=buf.getvalue())
        logger.info("Wrote bronze: %s (%d rows)", bkey, len(df))


def main() -> None:
    args = _parse_args()
    commodity: str = args["commodity"]
    year: int = int(args["year"])
    bucket: str = args["bucket"]
    aws_region: str = args["aws_region"]
    ingest_date: str = _parse_optional("ingest_date", default=date.today().isoformat())
    force_overwrite: bool = _parse_optional("force_overwrite", "false").lower() == "true"

    logger.info(
        "CHIRPS → bronze  commodity=%s  year=%d  force_overwrite=%s",
        commodity, year, force_overwrite,
    )

    s3_client = boto3.client("s3", region_name=aws_region)
    locations = _load_regions(s3_client, bucket, commodity)
    logger.info("Loaded %d locations for commodity=%s", len(locations), commodity)

    # Process all 12 months concurrently; within each month all days run concurrently.
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {
            pool.submit(
                _process_month,
                aws_region=aws_region,
                bucket=bucket,
                commodity=commodity,
                year=year,
                month=month,
                locations=locations,
                ingest_date=ingest_date,
                force_overwrite=force_overwrite,
            ): month
            for month in range(1, 13)
        }
        for future in as_completed(futures):
            month = futures[future]
            try:
                future.result()
            except Exception as exc:
                logger.error("Month %02d failed: %s", month, exc)
                raise

    logger.info("CHIRPS -> bronze complete  commodity=%s  year=%d", commodity, year)


main()
