"""AWS Batch entrypoint: CPC Soil Moisture raw S3 TIFs → bronze Parquet.

Runs as a Fargate container task.  No Glue bootstrap — leviathan is
installed in the image via ``pip install -e ".[batch]"``.

Reads raw CPC GeoTIFF files stored at:
  raw/weather/source=cpc_soil/variable={v}/date={YYYYMMDD}/{v}.{YYYYMMDD}.tif

For each date, extracts one pixel value per commodity region defined in:
  configs/geographies/{commodity}_regions.yaml (identical format to CHIRPS)

Writes one bronze Parquet per (country, region, year, month):
  bronze/weather/source=cpc_soil/commodity={c}/country={co}/region={r}/year={y}/month={mm}/part-000.parquet

Required args: --commodity, --year, --bucket, --aws_region
Optional args: --variable (default: w), --ingest_date, --force_overwrite
"""
from __future__ import annotations

import argparse
import io
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone

import boto3
import pandas as pd
import yaml

from leviathan.common.logging import get_logger
from leviathan.ingestion.weather.cpc_soil_moisture import extract_region_values
from leviathan.storage.paths import bronze_weather_key, raw_cpc_tif_key
from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys

logger = get_logger("cpc_raw_to_bronze_task")


# ---------------------------------------------------------------------------
# Region config loader (identical to CHIRPS pattern)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Per-day processing
# ---------------------------------------------------------------------------

def _fetch_and_extract(
    aws_region: str,
    bucket: str,
    variable: str,
    date_str: str,
    locations: list[dict],
) -> tuple[str, dict[str, float | None]]:
    """Download one raw TIF from S3 and extract region pixel values.

    Returns:
        (date_str, {region_name: value_or_None})
    """
    filename = f"{variable}.{date_str}.tif"
    key = raw_cpc_tif_key(variable, date_str, filename)
    s3_client = get_thread_local_s3_client(aws_region)
    try:
        body = s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
    except s3_client.exceptions.ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
            logger.warning("Raw TIF not found in S3: %s — skipping day", key)
            return date_str, {}
        raise
    values = extract_region_values(body, locations)
    return date_str, values


# ---------------------------------------------------------------------------
# Bronze write
# ---------------------------------------------------------------------------

def _write_bronze_partition(
    s3_client,
    bucket: str,
    commodity: str,
    variable: str,
    country: str,
    region: str,
    year: int,
    month: int,
    rows: list[dict],
    ingest_date: str,
    access_timestamp: str,
    force_overwrite: bool,
) -> bool:
    """Write one Parquet partition + companion meta JSON.  Returns True if written."""
    bkey = bronze_weather_key("cpc_soil", commodity, country, region, year, month, "part-000.parquet")

    if not force_overwrite:
        try:
            s3_client.head_object(Bucket=bucket, Key=bkey)
            logger.info("Skipping existing: %s", bkey)
            return False
        except s3_client.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] != "404":
                raise

    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3_client.put_object(Bucket=bucket, Key=bkey, Body=buf.getvalue())
    logger.info("Wrote bronze: %s (%d rows)", bkey, len(df))

    meta_key = bkey.replace("part-000.parquet", "_meta.json")
    meta = {
        "source": "cpc_soil",
        "variable": variable,
        "commodity": commodity,
        "country": country,
        "region": region,
        "year": year,
        "month": month,
        "row_count": len(df),
        "ingest_date": ingest_date,
        "access_timestamp": access_timestamp,
    }
    s3_client.put_object(
        Bucket=bucket,
        Key=meta_key,
        Body=json.dumps(meta, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    return True


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def _process_year(
    aws_region: str,
    bucket: str,
    commodity: str,
    variable: str,
    year: int,
    locations: list[dict],
    ingest_date: str,
    force_overwrite: bool,
) -> None:
    # List all raw TIF keys for this year/variable
    prefix = f"raw/weather/source=cpc_soil/variable={variable}/"
    year_prefix = f"raw/weather/source=cpc_soil/variable={variable}/date={year}"
    all_keys = list_s3_keys(bucket, year_prefix, suffix=".tif", aws_region=aws_region)

    if not all_keys:
        logger.warning(
            "No raw CPC TIFs found for variable=%s year=%d — run cpc_soil_to_raw_task first",
            variable, year,
        )
        return

    # Parse date strings from keys: .../date=YYYYMMDD/...
    date_strings: list[str] = []
    for key in all_keys:
        for part in key.split("/"):
            if part.startswith("date="):
                date_strings.append(part[5:])
                break

    logger.info(
        "Processing %d raw TIFs → bronze  commodity=%s variable=%s year=%d",
        len(date_strings), commodity, variable, year,
    )

    # Fetch and extract all days concurrently (S3 reads, cap at 20 workers)
    # rows_by_partition: {(country, region, year, month) -> [row, ...]}
    rows_by_partition: dict[tuple[str, str, int, int], list[dict]] = defaultdict(list)

    def _extract(ds: str) -> tuple[str, dict]:
        return _fetch_and_extract(aws_region, bucket, variable, ds, locations)

    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(_extract, ds): ds for ds in date_strings}
        for future in as_completed(futures):
            date_str, values = future.result()
            if not values:
                continue
            try:
                dt = datetime.strptime(date_str, "%Y%m%d")
            except ValueError:
                logger.warning("Unparseable date_str from S3 key: %s — skipping", date_str)
                continue
            for loc in locations:
                region = loc["region"]
                country = loc["country"]
                rows_by_partition[(country, region, dt.year, dt.month)].append({
                    "commodity":          commodity,
                    "source":             "cpc_soil",
                    "variable":           variable,
                    "country":            country,
                    "region":             region,
                    "date":               date_str[:4] + "-" + date_str[4:6] + "-" + date_str[6:],
                    "year":               dt.year,
                    "month":              dt.month,
                    "day":                dt.day,
                    "latitude":           loc["latitude"],
                    "longitude":          loc["longitude"],
                    "soil_moisture_mm":   values.get(region),
                    "ingest_date":        ingest_date,
                })

    if not rows_by_partition:
        logger.warning("No rows collected for commodity=%s variable=%s year=%d", commodity, variable, year)
        return

    # Write one Parquet per partition
    access_timestamp = datetime.now(timezone.utc).isoformat()
    s3_client = boto3.client("s3", region_name=aws_region)
    written = skipped = 0
    for (country, region, yr, month), rows in rows_by_partition.items():
        # Warn if all soil_moisture_mm are None
        null_count = sum(1 for r in rows if r["soil_moisture_mm"] is None)
        if null_count == len(rows):
            logger.warning(
                "All-null soil_moisture_mm: country=%s region=%s %d-%02d",
                country, region, yr, month,
            )
        result = _write_bronze_partition(
            s3_client=s3_client,
            bucket=bucket,
            commodity=commodity,
            variable=variable,
            country=country,
            region=region,
            year=yr,
            month=month,
            rows=rows,
            ingest_date=ingest_date,
            access_timestamp=access_timestamp,
            force_overwrite=force_overwrite,
        )
        if result:
            written += 1
        else:
            skipped += 1

    logger.info(
        "Bronze write complete  commodity=%s variable=%s year=%d  written=%d skipped=%d",
        commodity, variable, year, written, skipped,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="CPC raw S3 → bronze Parquet (Batch task)")
    parser.add_argument("--commodity",      required=True)
    parser.add_argument("--year",           required=True, type=int)
    parser.add_argument("--bucket",         required=True)
    parser.add_argument("--aws_region",     required=True)
    parser.add_argument("--variable",       default="w")
    parser.add_argument("--ingest_date",    default=date.today().isoformat())
    parser.add_argument("--force_overwrite", default="false")
    args = parser.parse_args()

    force_overwrite = args.force_overwrite.lower() == "true"

    logger.info(
        "CPC raw → bronze  commodity=%s  variable=%s  year=%d  force_overwrite=%s",
        args.commodity, args.variable, args.year, force_overwrite,
    )

    s3_client = boto3.client("s3", region_name=args.aws_region)
    locations = _load_regions(s3_client, args.bucket, args.commodity)
    logger.info("Loaded %d locations for commodity=%s", len(locations), args.commodity)

    _process_year(
        aws_region=args.aws_region,
        bucket=args.bucket,
        commodity=args.commodity,
        variable=args.variable,
        year=args.year,
        locations=locations,
        ingest_date=args.ingest_date,
        force_overwrite=force_overwrite,
    )


if __name__ == "__main__":
    main()
