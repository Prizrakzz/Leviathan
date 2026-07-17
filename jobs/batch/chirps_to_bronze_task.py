"""AWS Batch entrypoint: CHIRPS COG → bronze.

Runs as a Fargate container task.  No Glue bootstrap — leviathan is
installed in the image via ``pip install -e ".[batch]"``.

Required args: --commodity, --year, --bucket, --aws_region
Optional args: --ingest_date (default: today), --force_overwrite (default: false)
"""
from __future__ import annotations

import argparse
import calendar
import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.common.types import Region
from leviathan.ingestion.weather.chirps import fetch_chirps_daily_values
from leviathan.storage.configs import load_commodity_regions
from leviathan.storage.paths import bronze_weather_key
from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys

logger = get_logger("chirps_to_bronze_task")


def _discover_commodities(bucket: str, aws_region: str) -> list[str]:
    """Commodity slugs from configs/geographies/*_regions.yaml in S3 (thin-contract 'all' sentinel)."""
    keys = list_s3_keys(bucket, "configs/geographies/", suffix="_regions.yaml", aws_region=aws_region)
    return sorted(k.split("/")[-1][: -len("_regions.yaml")] for k in keys)


def _months_to_process(
    s3_client, bucket: str, commodity: str, locations: list[Region], year: int,
    force_overwrite: bool, today: date,
) -> list[int]:
    """Which months of ``year`` a scheduled run should (re)download.

    * A FUTURE year -> no months (no data yet).
    * A PAST year (the preserved backfill path) -> every month 1..12; ``_process_month``'s write-time
      skip-existing still dedups, so behaviour is unchanged from the pre-retrofit backfill.
    * The CURRENT year (the daily self-window) -> always re-download the current (incomplete) month;
      for an earlier month, download only when a sentinel bronze object is ABSENT (self-heal a
      within-year gap) -- so a normal daily run downloads just the current month. ``force_overwrite``
      re-downloads every elapsed month of the current year."""
    if year > today.year:
        return []
    if year < today.year:
        return list(range(1, 13))
    if not locations:
        return []
    sentinel_country = locations[0]["country"]
    sentinel_region = locations[0]["region"]
    months: list[int] = []
    for month in range(1, today.month + 1):
        if force_overwrite or month == today.month:
            months.append(month)
            continue
        sentinel = bronze_weather_key(
            "chirps", commodity, sentinel_country, sentinel_region, year, month, "part-000.parquet"
        )
        try:
            s3_client.head_object(Bucket=bucket, Key=sentinel)
        except Exception:  # noqa: BLE001 -- absent (or unprovable): (re)download this past month
            months.append(month)
    return months


def _process_month(
    aws_region: str,
    bucket: str,
    commodity: str,
    year: int,
    month: int,
    locations: list[Region],
    ingest_date: str,
    force_overwrite: bool,
) -> None:
    days_in_month = calendar.monthrange(year, month)[1]
    region_rows: dict[tuple[str, str], list[dict]] = {}

    def _fetch_day(day: int) -> tuple[int, dict]:
        try:
            return day, fetch_chirps_daily_values(year, month, day, locations)
        except Exception:  # noqa: BLE001 — intentional: rasterio/network failure skips one day; batch continues
            logger.warning(
                "Failed to fetch %d-%02d-%02d — skipping day",
                year, month, day,
                exc_info=True,
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

    # Entity check: warn if any expected location has all-null precipitation values
    for (country, region), rows in region_rows.items():
        null_count = sum(1 for r in rows if r["precipitation_mm"] is None)
        if null_count == len(rows):
            logger.warning(
                "All-null precipitation for country=%s region=%s %d-%02d commodity=%s",
                country, region, year, month, commodity,
            )

    s3_client = get_thread_local_s3_client(aws_region)
    access_timestamp = datetime.now(timezone.utc).isoformat()
    source_url_template = (
        f"https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/tifs/p05"
        f"/{year}/chirps-v2.0.{year}.{month:02d}.{{DD}}.tif.gz"
    )
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

        # Write companion access-metadata JSON alongside the bronze Parquet
        meta_key = bkey.replace("part-000.parquet", "_meta.json")
        meta = {
            "source": "chirps",
            "commodity": commodity,
            "year": year,
            "month": month,
            "country": country,
            "region": region,
            "row_count": len(df),
            "source_url_template": source_url_template,
            "access_timestamp": access_timestamp,
        }
        s3_client.put_object(
            Bucket=bucket,
            Key=meta_key,
            Body=json.dumps(meta, indent=2).encode("utf-8"),
            ContentType="application/json",
        )


def _process_commodity(
    bucket: str, aws_region: str, commodity: str, year: int, ingest_date: str,
    force_overwrite: bool, today: date,
) -> None:
    s3_client = get_thread_local_s3_client(aws_region)
    locations = load_commodity_regions(s3_client, bucket, commodity)
    months = _months_to_process(s3_client, bucket, commodity, locations, year, force_overwrite, today)
    if not months:
        logger.info("commodity=%s year=%d: no months to process (current-year bronze already present)",
                    commodity, year)
        return
    logger.info("commodity=%s year=%d: %d locations, processing months %s",
                commodity, year, len(locations), months)

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
            for month in months
        }
        for future in as_completed(futures):
            month = futures[future]
            future.result()  # re-raise: a failed month must be LOUD (per-commodity caught in main)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(description="CHIRPS COG → bronze (Batch task)")
    # A-Wave-3 thin-contract: every arg optional. --commodity 'all' iterates discovered commodities,
    # --year self-windows to the current calendar year (month-level skip-existing keeps a daily run
    # incremental + self-healing). A single --commodity/--year is the preserved backfill invocation.
    parser.add_argument("--commodity",      default="all",
                        help="commodity slug, or 'all' to iterate every discovered commodity (default: all)")
    parser.add_argument("--year",           type=int, default=None, help="calendar year (default: current)")
    parser.add_argument("--bucket",         default=None, help="S3 bucket (default: $LEVIATHAN_BUCKET)")
    parser.add_argument("--aws_region",     default=None, help="AWS region (default: $AWS_REGION)")
    parser.add_argument("--ingest_date",    default=date.today().isoformat())
    parser.add_argument("--force_overwrite", default="false")
    args = parser.parse_args()

    load_env()
    force_overwrite = args.force_overwrite.lower() == "true"
    today = date.today()
    year = args.year if args.year is not None else today.year
    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    if args.commodity.strip().lower() == "all":
        commodities = _discover_commodities(bucket, aws_region)
        if not commodities:
            raise SystemExit("ERROR: No commodity region configs found in S3 under configs/geographies/")
    else:
        commodities = [args.commodity.strip()]

    logger.info(
        "CHIRPS → bronze  commodities=%d  year=%d  force_overwrite=%s",
        len(commodities), year, force_overwrite,
    )

    failures: list[str] = []
    for commodity in commodities:
        try:
            _process_commodity(bucket, aws_region, commodity, year, args.ingest_date,
                               force_overwrite, today)
        except Exception as exc:  # noqa: BLE001 -- one commodity's failure must not kill the rest
            logger.error("[%s] FAILED: %s: %s", commodity, type(exc).__name__, str(exc)[:300])
            failures.append(commodity)

    logger.info("Done: commodities=%d year=%d%s",
                len(commodities), year, f"  FAILURES={failures}" if failures else "")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
