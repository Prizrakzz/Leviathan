"""AWS Batch entrypoint: CPC Soil Moisture raw S3 TIFs → bronze Parquet.

Runs as a Fargate container task.  No Glue bootstrap — leviathan is
installed in the image via ``pip install -e ".[batch]"``.

Reads raw CPC GeoTIFF files stored at:
  raw/weather/source=cpc_soil/variable={v}/date={YYYYMMDD}/{v}.{YYYYMMDD}.tif

For each date, extracts one pixel value per commodity region defined in:
  configs/geographies/{commodity}_regions.yaml (identical format to CHIRPS)

Writes one bronze Parquet per (commodity, country, region, year, month):
  bronze/weather/source=cpc_soil/commodity={c}/country={co}/region={r}/year={y}/month={mm}/part-000.parquet

Required args: --year, --bucket, --aws_region
Optional args: --commodity (default: all commodities discovered from S3),
               --variable (default: w), --ingest_date, --force_overwrite
"""
from __future__ import annotations

import argparse
import io
import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.common.types import Region
from leviathan.ingestion.weather.cpc_soil_moisture import extract_region_values
from leviathan.storage.configs import load_commodity_regions
from leviathan.storage.paths import bronze_weather_key, raw_cpc_tif_key
from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys

logger = get_logger("cpc_raw_to_bronze_task")


def _discover_commodities(bucket: str, aws_region: str) -> list[str]:
    """Return commodity names discovered from configs/geographies/*_regions.yaml keys in S3."""
    keys = list_s3_keys(bucket, "configs/geographies/", suffix="_regions.yaml", aws_region=aws_region)
    return sorted(k.split("/")[-1][: -len("_regions.yaml")] for k in keys)


# ---------------------------------------------------------------------------
# Per-day processing
# ---------------------------------------------------------------------------

def _fetch_tif(
    aws_region: str,
    bucket: str,
    variable: str,
    date_str: str,
) -> tuple[str, bytes | None]:
    """Download one raw TIF from S3.  Returns (date_str, bytes) or (date_str, None) if missing."""
    filename = f"{variable}.{date_str}.tif"
    key = raw_cpc_tif_key(variable, date_str, filename)
    s3_client = get_thread_local_s3_client(aws_region)
    try:
        body = s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
        return date_str, body
    except s3_client.exceptions.ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
            logger.warning("Raw TIF not found in S3: %s — skipping day", key)
            return date_str, None
        raise


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
    all_commodity_locations: dict[str, list[Region]],
    variable: str,
    year: int,
    ingest_date: str,
    force_overwrite: bool,
) -> None:
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

    n_commodities = len(all_commodity_locations)
    logger.info(
        "Processing %d raw TIFs → bronze  commodities=%d variable=%s year=%d",
        len(date_strings), n_commodities, variable, year,
    )

    # rows_by_partition: {(commodity, country, region, year, month) -> [row, ...]}
    rows_by_partition: dict[tuple[str, str, str, int, int], list[dict]] = defaultdict(list)

    def _extract_all(ds: str) -> tuple[str, dict[str, dict[str, float | None]]]:
        """Download TIF once; extract values for every commodity."""
        date_str, body = _fetch_tif(aws_region, bucket, variable, ds)
        if body is None:
            return date_str, {}
        return date_str, {
            commodity: extract_region_values(body, locations)
            for commodity, locations in all_commodity_locations.items()
        }

    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(_extract_all, ds): ds for ds in date_strings}
        for future in as_completed(futures):
            date_str, commodity_values = future.result()
            if not commodity_values:
                continue
            try:
                dt = datetime.strptime(date_str, "%Y%m%d")
            except ValueError:
                logger.warning("Unparseable date_str from S3 key: %s — skipping", date_str)
                continue
            formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
            for commodity, values in commodity_values.items():
                for loc in all_commodity_locations[commodity]:
                    country = loc["country"]
                    region = loc["region"]
                    rows_by_partition[(commodity, country, region, dt.year, dt.month)].append({
                        "commodity":        commodity,
                        "source":           "cpc_soil",
                        "variable":         variable,
                        "country":          country,
                        "region":           region,
                        "date":             formatted_date,
                        "year":             dt.year,
                        "month":            dt.month,
                        "day":              dt.day,
                        "latitude":         loc["latitude"],
                        "longitude":        loc["longitude"],
                        "soil_moisture_mm": values.get(region),
                        "ingest_date":      ingest_date,
                    })

    if not rows_by_partition:
        logger.warning("No rows collected for variable=%s year=%d", variable, year)
        return

    # Write one Parquet per partition
    access_timestamp = datetime.now(timezone.utc).isoformat()
    s3_client = get_thread_local_s3_client(aws_region)
    written = skipped = 0
    for (commodity, country, region, yr, month), rows in rows_by_partition.items():
        null_count = sum(1 for r in rows if r["soil_moisture_mm"] is None)
        if null_count == len(rows):
            logger.warning(
                "All-null soil_moisture_mm: commodity=%s country=%s region=%s %d-%02d",
                commodity, country, region, yr, month,
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
        "Bronze write complete  commodities=%d variable=%s year=%d  written=%d skipped=%d",
        n_commodities, variable, year, written, skipped,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(description="CPC raw S3 → bronze Parquet (Batch task)")
    # A-Wave-3 thin-contract: every arg optional. --commodity defaults to all-discovered, --year
    # self-windows to the current calendar year (skip-existing makes a scheduled run incremental +
    # self-healing within-year); explicit --commodity/--year keep the backfill unchanged.
    parser.add_argument("--commodity",       default=None,
                        help="Single commodity to process (default: all discovered from S3).")
    parser.add_argument("--year",            type=int, default=None,
                        help="calendar year (default: current year)")
    parser.add_argument("--bucket",          default=None, help="S3 bucket (default: $LEVIATHAN_BUCKET)")
    parser.add_argument("--aws_region",      default=None, help="AWS region (default: $AWS_REGION)")
    parser.add_argument("--variable",        default="w")
    parser.add_argument("--ingest_date",     default=date.today().isoformat())
    parser.add_argument("--force_overwrite", default="false")
    args = parser.parse_args()

    load_env()
    force_overwrite = args.force_overwrite.lower() == "true"
    year = args.year if args.year is not None else date.today().year
    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    s3_client = get_thread_local_s3_client(aws_region)

    if args.commodity and args.commodity.strip().lower() != "all":
        commodities = [args.commodity]
    else:
        commodities = _discover_commodities(bucket, aws_region)
        if not commodities:
            raise SystemExit("ERROR: No commodity region configs found in S3 under configs/geographies/")

    logger.info(
        "CPC raw → bronze  commodities=%d  variable=%s  year=%d  force_overwrite=%s",
        len(commodities), args.variable, year, force_overwrite,
    )

    all_commodity_locations = {
        c: load_commodity_regions(s3_client, bucket, c) for c in commodities
    }
    total_locations = sum(len(v) for v in all_commodity_locations.values())
    logger.info("Loaded %d locations across %d commodities", total_locations, len(commodities))

    _process_year(
        aws_region=aws_region,
        bucket=bucket,
        all_commodity_locations=all_commodity_locations,
        variable=args.variable,
        year=year,
        ingest_date=args.ingest_date,
        force_overwrite=force_overwrite,
    )


if __name__ == "__main__":
    main()
