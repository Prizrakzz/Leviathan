"""AWS Batch entrypoint: CHIRPS tif.gz -> bronze for ALL commodities, ONE year.

One task per year (46 total for 1981-2026).  Downloads each daily .tif.gz file
EXACTLY ONCE and extracts pixel values for every commodity region in a single
rasterio pass.  This is 31x more efficient than chirps_to_bronze_task.py
(one file per commodity) and avoids throttling from 1,400+ concurrent Batch jobs.

The output schema and S3 partition structure are identical to the per-commodity
task, so all downstream silver tasks are unaffected.

Required args: --year, --bucket, --aws_region
Optional args: --force_overwrite (default: false), --ingest_date (default: today)
"""
from __future__ import annotations

import argparse
import calendar
import io
import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone

import pandas as pd

from leviathan.common.constants import ALL_COMMODITIES
from leviathan.common.logging import get_logger
from leviathan.common.types import Region
from leviathan.ingestion.weather.chirps import fetch_chirps_daily_values
from leviathan.storage.configs import load_commodity_regions
from leviathan.storage.paths import bronze_weather_key
from leviathan.storage.s3 import get_thread_local_s3_client

logger = get_logger("chirps_year_to_bronze_task")


# ---------------------------------------------------------------------------
# Location index
# ---------------------------------------------------------------------------

# CHIRPS is a quasi-global product: coverage hard-stops at 50S-50N. Regions beyond the
# band (Canadian canola/HRS, northern France/Germany/Poland wheat + rapeseed, ...) can NEVER
# carry CHIRPS precipitation -- the first ingest minted 15,142 all-NaN month partitions for
# 27 such regions (BF-W1 census). Their precipitation lives in nasa_power (global coverage).
CHIRPS_LAT_LIMIT = 50.0


def _build_location_index(
    commodity_regions: dict[str, list[Region]],
) -> tuple[
    list[Region],
    dict[str, list[dict]],
]:
    """Deduplicate locations by coordinate; build commodity reverse mapping.

    Regions outside the CHIRPS 50S-50N coverage band are dropped here (structural
    absence, logged once) so no downstream stage can mint fabricated NaN rows for them.

    Returns:
        flat_locations: unique Region list passed to fetch_chirps_daily_values.
        region_to_entries: canonical_region -> [{commodity, country, region, lat, lon}]
    """
    seen: dict[tuple[float, float], str] = {}  # (lat, lon) -> canonical region name
    flat_locations: list[Region] = []
    region_to_entries: dict[str, list[dict]] = defaultdict(list)
    out_of_band: set[tuple[str, str]] = set()

    for commodity, regions in commodity_regions.items():
        for loc in regions:
            if abs(loc["latitude"]) > CHIRPS_LAT_LIMIT:
                out_of_band.add((loc["country"], loc["region"]))
                continue
            coord = (round(loc["latitude"], 6), round(loc["longitude"], 6))
            if coord not in seen:
                seen[coord] = loc["region"]
                flat_locations.append(loc)
            canonical = seen[coord]
            region_to_entries[canonical].append({
                "commodity": commodity,
                "country":   loc["country"],
                "region":    loc["region"],
                "latitude":  loc["latitude"],
                "longitude": loc["longitude"],
            })

    if out_of_band:
        logger.info(
            "CHIRPS coverage skip (|lat| > %s): %d regions structurally out of band: %s",
            CHIRPS_LAT_LIMIT, len(out_of_band),
            ", ".join(f"{c}/{r}" for c, r in sorted(out_of_band)),
        )
    return flat_locations, dict(region_to_entries)


# ---------------------------------------------------------------------------
# Month processor
# ---------------------------------------------------------------------------

def _process_month(
    aws_region: str,
    bucket: str,
    year: int,
    month: int,
    flat_locations: list[Region],
    region_to_entries: dict[str, list[dict]],
    ingest_date: str,
    force_overwrite: bool,
) -> int:
    """Fetch all days in *month*, write bronze per (commodity, country, region).

    Returns number of parquet files written.
    """
    days_in_month = calendar.monthrange(year, month)[1]

    # commodity -> (country, region) -> [row_dict]
    all_rows: dict[str, dict[tuple[str, str], list[dict]]] = defaultdict(
        lambda: defaultdict(list)
    )

    def _fetch_day(day: int) -> tuple[int, dict[str, float | None]]:
        try:
            return day, fetch_chirps_daily_values(year, month, day, flat_locations)
        except Exception:
            logger.warning(
                "Failed to fetch %d-%02d-%02d — skipping day",
                year, month, day, exc_info=True,
            )
            return day, {}

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_fetch_day, d): d for d in range(1, days_in_month + 1)}
        for fut in as_completed(futures):
            day, values = fut.result()
            if not values:
                continue
            day_str = date(year, month, day).isoformat()
            for canonical_region, precip in values.items():
                for entry in region_to_entries.get(canonical_region, []):
                    all_rows[entry["commodity"]][(entry["country"], entry["region"])].append({
                        "commodity":        entry["commodity"],
                        "source":           "chirps",
                        "country":          entry["country"],
                        "region":           entry["region"],
                        "date":             day_str,
                        "year":             year,
                        "month":            month,
                        "day":              day,
                        "latitude":         entry["latitude"],
                        "longitude":        entry["longitude"],
                        "precipitation_mm": precip,
                        "ingest_date":      ingest_date,
                    })

    s3_client = get_thread_local_s3_client(aws_region)
    access_timestamp = datetime.now(timezone.utc).isoformat()
    source_url_template = (
        f"https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/tifs/p05"
        f"/{year}/chirps-v2.0.{year}.{month:02d}.{{DD}}.tif.gz"
    )
    written = 0

    for commodity, region_rows in all_rows.items():
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

            null_count = sum(1 for r in rows if r["precipitation_mm"] is None)
            if null_count == len(rows):
                # WRITE-GATE (BF-W1): an all-null region-month is structural absence (out of
                # coverage, or the source file is not published yet). Minting a NaN partition
                # fabricates presence -- the exact defect the 2026-05-16 vintage carpeted the
                # lake with. Skip; the honest representation of no data is NO partition.
                logger.warning(
                    "SKIP all-null precipitation (no partition written): commodity=%s "
                    "country=%s region=%s %d-%02d",
                    commodity, country, region, year, month,
                )
                continue

            df = pd.DataFrame(rows)
            buf = io.BytesIO()
            df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
            s3_client.put_object(Bucket=bucket, Key=bkey, Body=buf.getvalue())
            logger.info("Wrote bronze: %s (%d rows)", bkey, len(df))
            written += 1

            meta_key = bkey.replace("part-000.parquet", "_meta.json")
            s3_client.put_object(
                Bucket=bucket,
                Key=meta_key,
                Body=json.dumps({
                    "source":              "chirps",
                    "commodity":           commodity,
                    "year":                year,
                    "month":               month,
                    "country":             country,
                    "region":              region,
                    "row_count":           len(df),
                    "source_url_template": source_url_template,
                    "access_timestamp":    access_timestamp,
                }, indent=2).encode("utf-8"),
                ContentType="application/json",
            )

    return written


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="CHIRPS tif.gz -> bronze for ALL commodities, one year."
    )
    parser.add_argument("--year",           required=True, type=int)
    parser.add_argument("--bucket",         required=True)
    parser.add_argument("--aws_region",     required=True)
    parser.add_argument("--ingest_date",    default=date.today().isoformat())
    parser.add_argument("--force_overwrite", default="false")
    args = parser.parse_args()

    force_overwrite = args.force_overwrite.lower() == "true"

    logger.info(
        "CHIRPS year -> bronze  year=%d  force_overwrite=%s",
        args.year, force_overwrite,
    )

    s3_client = get_thread_local_s3_client(args.aws_region)

    commodity_regions: dict[str, list[Region]] = {}
    for commodity in ALL_COMMODITIES:
        try:
            regions = load_commodity_regions(s3_client, args.bucket, commodity)
            if regions:
                commodity_regions[commodity] = regions
        except Exception:
            logger.warning("No region config for %s — skipping", commodity)

    flat_locations, region_to_entries = _build_location_index(commodity_regions)
    logger.info(
        "Loaded %d commodities, %d unique locations",
        len(commodity_regions), len(flat_locations),
    )

    total_written = 0
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {
            pool.submit(
                _process_month,
                aws_region=args.aws_region,
                bucket=args.bucket,
                year=args.year,
                month=month,
                flat_locations=flat_locations,
                region_to_entries=region_to_entries,
                ingest_date=args.ingest_date,
                force_overwrite=force_overwrite,
            ): month
            for month in range(1, 13)
        }
        for fut in as_completed(futures):
            month = futures[fut]
            try:
                total_written += fut.result()
            except Exception as exc:
                logger.error("Month %02d failed: %s", month, exc)
                raise

    logger.info(
        "Done: year=%d  files_written=%d", args.year, total_written,
    )


if __name__ == "__main__":
    main()
