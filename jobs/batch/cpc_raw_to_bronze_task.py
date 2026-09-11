"""AWS Batch entrypoint: CPC Soil Moisture raw S3 TIFs → bronze Parquet.

Runs as a Fargate container task.  No Glue bootstrap — leviathan is
installed in the image via ``pip install -e ".[batch]"``.

Reads raw CPC GeoTIFF files stored at:
  raw/weather/source=cpc_soil/variable={v}/date={YYYYMMDD}/{v}.{YYYYMMDD}.tif

For each date, extracts one pixel value per commodity region defined in:
  configs/geographies/{commodity}_regions.yaml (identical format to CHIRPS)

Writes one bronze Parquet per (commodity, country, region, year, month):
  bronze/weather/source=cpc_soil/commodity={c}/country={co}/region={r}/year={y}/month={mm}/part-000.parquet

A month partition is rewritten when the newest RAW object feeding it is newer than the bronze
object (``_bronze_is_stale`` — the SILVER-V002 rule, one layer down; existence-only skipping is
what froze August 2026 at 20/31 days).  A rewrite REPLACES, so it is held to the SHRINK FLOOR
(``_rewrite_would_shrink``): a rewrite that would leave the partition with fewer rows than it
already holds is declined by name and the partition is left alone.  ``--force_overwrite true``
names the overwrite and steps past that floor.

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
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    list_s3_keys_with_mtime,
)

logger = get_logger("cpc_raw_to_bronze_task")


def _date_str_from_key(key: str) -> str | None:
    """Return the ``YYYYMMDD`` in a raw key's ``date=`` segment, or None if absent/unparseable."""
    for part in key.split("/"):
        if part.startswith("date="):
            stem = part[len("date="):]
            try:
                datetime.strptime(stem, "%Y%m%d")
            except ValueError:
                return None
            return stem
    return None


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

def _bronze_is_stale(bronze_mtime, raw_max_mtime) -> bool:
    """The SILVER-V002 freshness rule, applied one layer down (2026-09-11).

    A bronze month partition is stale — and so must be rewritten — when the newest RAW object
    feeding it is newer than the bronze object itself.  Before this, ``_write_bronze_partition``
    skipped any existing month object on EXISTENCE alone, which froze the current month at whatever
    day count it first had.  MEASURED on ``corn_cbot/us_corn_south_dakota/year=2026``: month=08
    held 20 of 31 days with access_timestamp 2026-08-22T11:31:43Z and month=09 held Sep 1..5 with
    2026-09-07T08:55:12Z, while the job SUCCEEDED on 09-08 and 09-09, read all 252 raw days, and
    declined to rewrite either.  Silver carried the freeze faithfully (max(date) 2026-09-05 over
    101,254 rows) — the same defect class ``select_partitions_to_write`` closed for bronze->silver,
    still open one layer below it.

    Either timestamp missing => NOT stale.  An unknown is never grounds for a rewrite, so a benign
    no-op rerun stays a no-op (AV-12), exactly as ``select_partitions_to_write`` treats a null
    ``bronze_max_mtime``.
    """
    if bronze_mtime is None or raw_max_mtime is None:
        return False
    return bool(bronze_mtime < raw_max_mtime)


# THE SHRINK FLOOR, stated once and quoted into the declining log line so the rule an operator
# reads is the rule the code applies.
_SHRINK_FLOOR_RULE = (
    "a freshness-driven rewrite may never replace a bronze month partition with FEWER rows than it "
    "already holds"
)


def _rewrite_would_shrink(prior_row_count: int | None, new_row_count: int) -> bool:
    """Would this rewrite REPLACE a month partition with fewer rows than it already has?

    THE ASYMMETRY THE FRESHNESS RULE OPENED (review round 2, 2026-09-11).  ``_bronze_is_stale``
    turned a partition that used to be write-once into one that is rewritten whenever its raw is
    newer -- which is the whole repair, and is what brings the fifteen lost days back.  But a
    rewrite is a REPLACE, not a merge: the new Parquet is whatever ``rows_by_partition`` collected
    this run, and any day that failed its ``_fetch_tif`` is simply absent from it.  So a run that
    reads 5 of 30 raw days for a month -- S3 throttling, a truncated LIST, a raw prefix half
    deleted -- would have silently written a 5-row partition over a 30-row one and called it a
    refresh.  Before this repair that could not happen, because the partition was never rewritten
    at all; the freshness rule is what made the shrink reachable, so the floor ships with it.

    UNKNOWN IS NOT SHRINKAGE.  ``prior_row_count is None`` (no companion meta, unreadable meta, no
    ``row_count`` in it) means the prior size is not a fact this run holds, and declining on an
    unknown would refuse exactly the partitions whose meta predates this layout.  The symmetric
    reading of ``_bronze_is_stale``'s own rule: an unknown is never grounds to act.

    EQUAL IS NOT SHRINKAGE either -- the ordinary same-day rerun writes the same row count back.
    """
    if prior_row_count is None:
        return False
    return new_row_count < prior_row_count


def _prior_bronze_row_count(s3_client, bucket: str, bronze_key: str) -> int | None:
    """The ``row_count`` of the bronze partition already at ``bronze_key``, or None if unknowable.

    Read from the companion ``_meta.json`` this very function's writer emits beside every partition
    -- one small GET, never a Parquet download, and never a guess: a meta that is missing,
    unreadable, non-JSON or carries no integer ``row_count`` returns None and the floor stands down
    (see ``_rewrite_would_shrink``).  Only reached on the stale branch, so a fresh skip still costs
    nothing beyond the ``head_object`` that was already happening.
    """
    meta_key = bronze_key.replace("part-000.parquet", "_meta.json")
    try:
        body = s3_client.get_object(Bucket=bucket, Key=meta_key)["Body"].read()
    except Exception as exc:  # noqa: BLE001 -- any failure to READ is an unknown, never a decline
        logger.info("No readable bronze meta at %s (%s) -- shrink floor stands down", meta_key, exc)
        return None
    try:
        value = json.loads(body).get("row_count")
    except (ValueError, AttributeError) as exc:
        logger.info("Unparseable bronze meta at %s (%s) -- shrink floor stands down", meta_key, exc)
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        logger.info(
            "Bronze meta at %s carries no integer row_count (%r) -- shrink floor stands down",
            meta_key, value,
        )
        return None
    return value


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
    raw_max_mtime=None,
) -> str:
    """Write one Parquet partition + companion meta JSON.

    Returns ``"written"`` | ``"skipped"`` (already fresh) | ``"declined"`` (the shrink floor held).
    A TRI-STATE, not a bool, for the same reason the daily fetch leg's per-day result is one: a
    DECLINE is not a skip.  A skip means the partition is already correct; a decline means this run
    wanted to change it and was stopped, which is the operator's business and must not be folded
    into a count that reads like "nothing needed doing".

    An existing partition is skipped only while it is FRESH — see ``_bronze_is_stale``.  The
    freshness read costs nothing extra: ``head_object`` already had to be called, and its response
    carries ``LastModified``.

    A stale partition is then held to the SHRINK FLOOR: a rewrite that would replace it with fewer
    rows than it already holds is DECLINED BY NAME — see ``_rewrite_would_shrink``.
    ``--force_overwrite true`` is the operator naming the overwrite and steps past the floor on
    purpose: repairing a partition that is corrupt, duplicated or simply wrong is exactly what that
    flag is for, and some of those repairs are legitimately smaller.
    """
    bkey = bronze_weather_key("cpc_soil", commodity, country, region, year, month, "part-000.parquet")

    if not force_overwrite:
        try:
            head = s3_client.head_object(Bucket=bucket, Key=bkey)
        except s3_client.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] != "404":
                raise
        else:
            bronze_mtime = head.get("LastModified")
            if not _bronze_is_stale(bronze_mtime, raw_max_mtime):
                logger.info(
                    "Skipping fresh: %s (bronze %s, newest raw %s)",
                    bkey, bronze_mtime, raw_max_mtime,
                )
                return "skipped"
            prior_rows = _prior_bronze_row_count(s3_client, bucket, bkey)
            if _rewrite_would_shrink(prior_rows, len(rows)):
                logger.warning(
                    "BRONZE REWRITE DECLINED (shrink floor) %s: this run collected %d rows for a "
                    "partition that holds %d -- %s. The partition is LEFT AS IT IS; the %d rows "
                    "this run is short (one row per day per region in this layout) are the defect "
                    "to chase -- see the 'Raw TIF not found in S3' lines above. Re-run once raw is "
                    "whole, or name the overwrite with --force_overwrite true if the smaller "
                    "partition is the correct one",
                    bkey, len(rows), prior_rows, _SHRINK_FLOOR_RULE, prior_rows - len(rows),
                )
                return "declined"
            logger.info(
                "Refreshing STALE bronze: %s (bronze %s < newest raw %s, rows %s -> %d)",
                bkey, bronze_mtime, raw_max_mtime,
                "unknown" if prior_rows is None else prior_rows, len(rows),
            )

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
    return "written"


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
    # The SAME LIST that enumerates the days carries their mtimes, so the freshness yardstick each
    # bronze partition is measured against is free (see _bronze_is_stale).
    raw_mtimes = list_s3_keys_with_mtime(bucket, year_prefix, suffix=".tif", aws_region=aws_region)

    if not raw_mtimes:
        logger.warning(
            "No raw CPC TIFs found for variable=%s year=%d — run cpc_soil_to_raw_task first",
            variable, year,
        )
        return

    # Parse date strings from keys: .../date=YYYYMMDD/..., and fold the newest raw mtime per month.
    date_strings: list[str] = []
    raw_max_mtime_by_month: dict[tuple[int, int], datetime] = {}
    for key in sorted(raw_mtimes):
        date_str = _date_str_from_key(key)
        if date_str is None:
            logger.warning("Unparseable date= segment in raw key: %s -- skipping", key)
            continue
        date_strings.append(date_str)
        dt = datetime.strptime(date_str, "%Y%m%d")
        current = raw_max_mtime_by_month.get((dt.year, dt.month))
        mtime = raw_mtimes[key]
        if current is None or mtime > current:
            raw_max_mtime_by_month[(dt.year, dt.month)] = mtime

    logger.info(
        "Newest raw object per month: %s",
        ", ".join(
            f"{y}-{m:02d}={mt.isoformat()}"
            for (y, m), mt in sorted(raw_max_mtime_by_month.items())
        ) or "(none)",
    )

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
    written = skipped = declined = 0
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
            raw_max_mtime=raw_max_mtime_by_month.get((yr, month)),
        )
        if result == "written":
            written += 1
        elif result == "declined":
            declined += 1
        else:
            skipped += 1

    logger.info(
        "Bronze write complete  commodities=%d variable=%s year=%d  "
        "written=%d skipped=%d declined=%d",
        n_commodities, variable, year, written, skipped, declined,
    )
    if declined:
        # The summary line an operator reads must not let a held floor hide inside "skipped": a
        # skip means the partition was already correct, a decline means this run tried to shrink it
        # and was stopped, and the days it could not read are still missing downstream.
        logger.warning(
            "BRONZE SHRINK FLOOR HELD on %d partition(s) this run -- %s. Each is named on its own "
            "BRONZE REWRITE DECLINED line above; those partitions were NOT rewritten",
            declined, _SHRINK_FLOOR_RULE,
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(description="CPC raw S3 -> bronze Parquet (Batch task)")
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
