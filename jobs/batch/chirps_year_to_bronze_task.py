"""AWS Batch entrypoint: CHIRPS tif.gz -> bronze for ALL commodities, ONE year.

One task per year (46 total for 1981-2026).  Downloads each daily .tif.gz file
EXACTLY ONCE and extracts pixel values for every commodity region in a single
rasterio pass.  This is 31x more efficient than chirps_to_bronze_task.py
(one file per commodity) and avoids throttling from 1,400+ concurrent Batch jobs.

The output schema and S3 partition structure are identical to the per-commodity
task, so all downstream silver tasks are unaffected.

THE COMPLETENESS-AWARE WRITE SKIP (2026-09-11).  This task's all-null write gate has been correct
since BF-W1, but its write skip was EXISTENCE-ONLY -- the same defect that froze the daily task's
August 2026 at 31 rows / 0 observations for twenty days.  A re-run over a month whose source has since
published more days declined to refresh it, so the only repair available was ``--force_overwrite``,
which steps past the shrink protection as well.  The skip now measures OBSERVED DAYS on both sides
(``_rewrite_admitted``), which is monotone and therefore its own anti-shrink floor.  The helper trio is
the byte-equivalent of ``chirps_to_bronze_task``'s -- see that module's note on why it is duplicated
rather than imported, and ``tests/unit/test_chirps_bronze_completeness_skip.py``, which runs the SAME
case table through both modules so a drift is a red deck.

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


# ---------------------------------------------------------------------------
# The observation-count yardstick (2026-09-11) -- see the module docstring.
# ---------------------------------------------------------------------------

def _nonnull_day_count(rows: list[dict]) -> int:
    """How many of these bronze rows carry an actual precipitation OBSERVATION.

    Row count is the calendar length of the month whether the source published 31 days or none
    (``fetch_chirps_daily_values`` returns ``{region: None}`` on a 404), so the honest count is the
    non-null one; a float NaN counts as absent."""
    n = 0
    for r in rows:
        v = r.get("precipitation_mm")
        if v is None:
            continue
        if isinstance(v, float) and v != v:      # NaN -- present in the column, absent as data
            continue
        n += 1
    return n


def _rewrite_admitted(new_nonnull: int, stored_nonnull: int | None) -> bool:
    """May this run REPLACE an existing bronze month with what it just fetched?

    STRICTLY MONOTONE: admitted only when this run holds MORE observed days than the stored partition.
    EQUAL is the ordinary rerun and stays a no-op; FEWER is the shrink an anti-shrink floor exists to
    refuse; UNKNOWN (``None``) is not grounds to act, because a rewrite REPLACES and a run that cannot
    see what it is replacing cannot prove it would not shrink.  ``--force_overwrite true`` is the
    operator naming the overwrite."""
    if stored_nonnull is None:
        return False
    return new_nonnull > stored_nonnull


def _stored_nonnull_days(s3_client, bucket: str, bronze_key: str) -> int | None:
    """Observed (non-null) days in the bronze month already at ``bronze_key``; None when unknowable.

    Companion ``_meta.json``'s ``nonnull_count`` first (one small GET); the partition itself as the
    fallback for every object minted before that field existed.  Any failure to READ is an UNKNOWN,
    never a decline in itself -- ``_rewrite_admitted`` owns what an unknown means."""
    meta_key = bronze_key.replace("part-000.parquet", "_meta.json")
    try:
        meta = json.loads(s3_client.get_object(Bucket=bucket, Key=meta_key)["Body"].read())
        value = meta.get("nonnull_count")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    except Exception as exc:  # noqa: BLE001 -- no/unreadable meta is ordinary for a pre-2026-09-11 object
        logger.debug("No readable nonnull_count in %s (%s) -- reading the partition", meta_key, exc)
    try:
        body = s3_client.get_object(Bucket=bucket, Key=bronze_key)["Body"].read()
        col = pd.read_parquet(io.BytesIO(body), columns=["precipitation_mm"])["precipitation_mm"]
        return int(col.notna().sum())
    except Exception as exc:  # noqa: BLE001 -- an unreadable partition is an UNKNOWN, never a decline
        logger.warning(
            "Could not read the stored observation count of %s (%s: %s) -- treating it as UNKNOWN, "
            "which declines the rewrite; --force_overwrite true names the overwrite",
            bronze_key, type(exc).__name__, str(exc)[:200],
        )
        return None


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
            new_nonnull = _nonnull_day_count(rows)
            if new_nonnull == 0:
                # WRITE-GATE (BF-W1): an all-null region-month is structural absence (out of
                # coverage, or the source file is not published yet). Minting a NaN partition
                # fabricates presence -- the exact defect the 2026-05-16 vintage carpeted the
                # lake with. Skip; the honest representation of no data is NO partition.
                # HOISTED ABOVE THE WRITE SKIP (2026-09-11) so the decision that needs no S3 call at
                # all is taken first; the verdict is unchanged either way.
                logger.warning(
                    "SKIP all-null precipitation (no partition written): commodity=%s "
                    "country=%s region=%s %d-%02d",
                    commodity, country, region, year, month,
                )
                continue

            if not force_overwrite:
                try:
                    s3_client.head_object(Bucket=bucket, Key=bkey)
                except s3_client.exceptions.ClientError as exc:
                    if exc.response["Error"]["Code"] != "404":
                        raise
                    # absent -> write it
                else:
                    # EXISTENCE-ONLY -> COMPLETENESS-AWARE (2026-09-11), see _rewrite_admitted.
                    stored = _stored_nonnull_days(s3_client, bucket, bkey)
                    if not _rewrite_admitted(new_nonnull, stored):
                        logger.info(
                            "Skipping fresh: %s (this run observed %d of %d days; stored holds %s -- "
                            "a rewrite may only ADD observed days)",
                            bkey, new_nonnull, len(rows),
                            "an unreadable count" if stored is None else f"{stored}",
                        )
                        continue
                    logger.info(
                        "Refreshing INCOMPLETE bronze: %s (observed days %d -> %d of %d)",
                        bkey, stored, new_nonnull, len(rows),
                    )

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
                    # The yardstick the NEXT run measures against (see _stored_nonnull_days):
                    # row_count is the calendar length of the month either way.
                    "nonnull_count":       new_nonnull,
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
