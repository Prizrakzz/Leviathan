"""AWS Batch entrypoint: CHIRPS COG → bronze.

Runs as a Fargate container task.  No Glue bootstrap — leviathan is
installed in the image via ``pip install -e ".[batch]"``.

Required args: --commodity, --year, --bucket, --aws_region
Optional args: --ingest_date (default: today), --force_overwrite (default: false)
"""
from __future__ import annotations

# GDAL env vars must be set before rasterio is imported anywhere in the process.
import os

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "3")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "1")
os.environ.setdefault("GDAL_HTTP_TIMEOUT", "30")
os.environ.setdefault("CPL_VSIL_CURL_CACHE_SIZE", "200000000")

import argparse
import calendar
import io
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import boto3
import pandas as pd
import yaml

from leviathan.common.logging import get_logger
from leviathan.ingestion.weather.chirps import fetch_chirps_daily_values
from leviathan.storage.paths import bronze_weather_key
from leviathan.storage.s3 import get_thread_local_s3_client

logger = get_logger("chirps_to_bronze_task")


def _load_regions(s3_client, bucket: str, commodity: str) -> list[dict]:
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
    days_in_month = calendar.monthrange(year, month)[1]
    region_rows: dict[tuple[str, str], list[dict]] = {}

    def _fetch_day(day: int) -> tuple[int, dict]:
        try:
            return day, fetch_chirps_daily_values(year, month, day, locations)
        except Exception as exc:
            logger.warning(
                "Failed to fetch %d-%02d-%02d: %s — skipping day",
                year, month, day, exc,
            )
            return day, {}

    with ThreadPoolExecutor(max_workers=5) as pool:  # cap at 5 to avoid throttling UCSB server
        futures = {pool.submit(_fetch_day, d): d for d in range(1, days_in_month + 1)}
        for future in as_completed(futures):
            day, values = future.result()
            if not values:
                continue
            day_str = date(year, month, day).isoformat()
            for loc in locations:
                region  = loc["region"]
                country = loc["country"]
                region_rows.setdefault((country, region), []).append({
                    "commodity":         commodity,
                    "source":            "chirps",
                    "country":           country,
                    "region":            region,
                    "date":              day_str,
                    "year":              year,
                    "month":             month,
                    "day":               day,
                    "latitude":          loc["latitude"],
                    "longitude":         loc["longitude"],
                    "precipitation_mm":  values.get(region),
                    "ingest_date":       ingest_date,
                })

    if not region_rows:
        logger.warning("No data for %d-%02d commodity=%s", year, month, commodity)
        return

    s3_client = get_thread_local_s3_client(aws_region)
    for (country, region), rows in region_rows.items():
        bkey = bronze_weather_key(
            "chirps", commodity, country, region, year, month, "part-000.parquet"
        )
        if not force_overwrite:
            try:
                s3_client.head_object(Bucket=bucket, Key=bkey)
                logger.info("Skipping existing: %s", bkey)
                continue
            except s3_client.exceptions.ClientError as exc:
                if exc.response["Error"]["Code"] != "404":
                    raise

        df  = pd.DataFrame(rows)
        buf = io.BytesIO()
        df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
        s3_client.put_object(Bucket=bucket, Key=bkey, Body=buf.getvalue())
        logger.info("Wrote bronze: %s (%d rows)", bkey, len(df))


def main() -> None:
    parser = argparse.ArgumentParser(description="CHIRPS COG → bronze (Batch task)")
    parser.add_argument("--commodity",      required=True)
    parser.add_argument("--year",           required=True, type=int)
    parser.add_argument("--bucket",         required=True)
    parser.add_argument("--aws_region",     required=True)
    parser.add_argument("--ingest_date",    default=date.today().isoformat())
    parser.add_argument("--force_overwrite", default="false")
    args = parser.parse_args()

    force_overwrite = args.force_overwrite.lower() == "true"

    logger.info(
        "CHIRPS → bronze  commodity=%s  year=%d  force_overwrite=%s",
        args.commodity, args.year, force_overwrite,
    )

    s3_client = boto3.client("s3", region_name=args.aws_region)
    locations = _load_regions(s3_client, args.bucket, args.commodity)
    logger.info("Loaded %d locations for commodity=%s", len(locations), args.commodity)

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {
            pool.submit(
                _process_month,
                aws_region=args.aws_region,
                bucket=args.bucket,
                commodity=args.commodity,
                year=args.year,
                month=month,
                locations=locations,
                ingest_date=args.ingest_date,
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

    logger.info("Done: commodity=%s year=%d", args.commodity, args.year)


if __name__ == "__main__":
    main()
