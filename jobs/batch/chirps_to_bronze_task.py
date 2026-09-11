"""AWS Batch entrypoint: CHIRPS COG → bronze.

Runs as a Fargate container task.  No Glue bootstrap — leviathan is
installed in the image via ``pip install -e ".[batch]"``.

THE AUGUST-2026 FREEZE, AND THE THREE GATES THAT CLOSE IT (2026-09-11)
---------------------------------------------------------------------
MEASURED: ``bronze/weather/source=chirps/commodity=corn_cbot/.../year=2026/month=08/part-000.parquet``
held 31 rows and ZERO precipitation observations, LastModified 2026-08-22T09:04:3xZ, unchanged through
twenty consecutive green daily runs.  Silver's F044 null-drop turned that into NO August partition at
all, and ``gold_weather_z`` -- a SERVED numbers card -- tipped at data month 2026-07 while its own card
promised 2026-08.  Three independent mechanisms produced it, and all three are closed here:

1. THE ALL-NULL WRITE GATE.  ``fetch_chirps_daily_values`` returns ``{region: None}`` on a 404
   (chirps.py:59-63) -- a TRUTHY dict -- so a month the source has not published yet was written as a
   full-length, all-null SKELETON.  The sibling backfill task has refused that since BF-W1
   (``chirps_year_to_bronze_task.py:177-188``); the daily task only WARNED and wrote it anyway.  Now
   it refuses too: the honest representation of no data is NO partition.
2. THE EXISTENCE-ONLY WRITE SKIP.  ``head_object`` -> "Skipping existing" -> ``continue`` preserved
   that skeleton forever.  CHIRPS has NO RAW TIER, so the cpc lane's mtime rule has nothing to measure
   against; the yardstick here is the OBSERVATION COUNT (``_rewrite_admitted``), which is strictly
   monotone and therefore carries its own anti-shrink floor.
3. THE M-2 IMMUTABILITY ASSUMPTION.  ``_months_to_process`` refetched an older month only when a
   sentinel object was ABSENT.  The skeleton was present, so from 2026-10-01 (August becomes M-2)
   August would never have been re-downloaded again -- not even after CHIRPS published it.  MEASURED:
   CHIRPS v2.0 finals publish in MONTH BLOCKS (all of July present by 2026-08-22; none of August
   present at 2026-09-11, 11 days past month-end), so a month lands AFTER it becomes M-2.  The
   sentinel test is now a COMPLETENESS test, and a month leaves the window the instant it completes.

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

# CHIRPS is a quasi-global product: coverage hard-stops at 50S-50N
# (configs/sources/chirps.yaml, coverage.lat_max).  DUPLICATED from
# ``chirps_year_to_bronze_task.CHIRPS_LAT_LIMIT`` rather than imported: the two Batch entrypoints are
# invoked BY PATH (``python jobs/batch/<task>.py``), which puts jobs/batch/ -- not the repo root -- on
# sys.path[0], and the unit deck loads each file standalone via ``spec_from_file_location``, so a
# cross-task import would resolve at runtime and not in the deck.  The duplication is PINNED instead:
# ``tests/unit/test_chirps_month_window_completeness.py`` asserts the two constants are equal, so a
# drift in either file is a red deck rather than a silent divergence.
CHIRPS_LAT_LIMIT = 50.0

# How long after a month ENDS this task keeps asking whether the source has published (more of) it.
# MEASURED, not defensive: the July 2026 block was complete by 2026-08-22 (<= 22 days past month-end)
# and the August block is still absent at 2026-09-11 (>= 11 days and counting), so the observed
# publication lag for a whole-month CHIRPS block sits in the low tens of days.  120 is ~5x the longest
# lag actually observed, which is generous enough that no real publication is missed and short enough
# that a month the source will NEVER complete (a permanently-missing day) stops costing a daily
# re-download within one quarter.  Past the window the sentinel is trusted on EXISTENCE exactly as
# before, so the pre-fix cost profile is restored for every settled month.
#
# READ 120 AS A COST CEILING, NOT ONLY AS A PATIENCE WINDOW (named in review).  For a month the source
# will never complete -- one permanently-missing CHIRPS day in the sentinel region -- this is the worst
# case in full: the month re-enters the window on EVERY daily run from M-2 until month_end + 120, each
# pass downloading the whole month for every region of that commodity, and ``_rewrite_admitted`` then
# DECLINES the write because the count is equal.  Real raster reads, no write, bounded at ~4 months.
# The far more common shape is cheap: an entirely unpublished month leaves NO sentinel at all (the
# all-null write gate refuses to mint one), so its re-entry costs only 404s.  Lowering this constant
# trades publication coverage for that ceiling; raising it does the reverse.
_COMPLETENESS_LOOKBACK_DAYS = 120


def _nonnull_day_count(rows: list[dict]) -> int:
    """How many of these bronze rows carry an actual precipitation OBSERVATION.

    ROW COUNT IS NOT A MEASUREMENT HERE.  ``fetch_chirps_daily_values`` returns ``{region: None}`` for a
    day the source has not published (chirps.py:59-63) -- a TRUTHY dict -- so ``_process_month`` builds a
    row for that day anyway with ``precipitation_mm=None``.  The row count is therefore ALWAYS the
    calendar length of the month and says nothing at all about how much data arrived; the honest count
    is the non-null one.  A float NaN counts as ABSENT for the same reason parquet excludes NaN from
    min/max and ``value_census.FileColumnStat.effective_nonnull`` books it as missing."""
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

    THE YARDSTICK IS OBSERVATION COUNT, NOT OBJECT MTIME.  The cpc lane closed the same defect class one
    seam over with ``_bronze_is_stale(bronze_mtime, raw_max_mtime)``, but that rule needs a RAW object
    whose mtime can prove the bronze stale, and CHIRPS HAS NO RAW TIER (configs/sources/chirps.yaml:
    "HTTP range-read via rasterio/vsicurl -- no raw S3 tier").  What both sides of this comparison CAN
    state is how many days of the month actually carry an observation.

    STRICTLY MONOTONE, so the anti-shrink floor the cpc lane had to ship as a SEPARATE rule
    (``_rewrite_would_shrink``) is built into this one: a rewrite is admitted only when this run holds
    MORE observed days than the stored partition already does.  EQUAL is not an improvement -- that is
    the ordinary same-day rerun, and it stays a no-op (AV-12).  FEWER is exactly the shrink a floor
    exists to refuse: a run that reached 5 of 31 days because UCSB was throttling must never replace a
    31-day partition and call it a refresh.

    ``stored_nonnull is None`` -- the stored partition's count could not be read at all -- is NOT
    grounds to act, the same reading ``_bronze_is_stale`` and ``_rewrite_would_shrink`` take of an
    unknown.  A rewrite REPLACES, and a run that cannot see what it is replacing cannot prove it would
    not shrink.  ``--force_overwrite true`` is the operator naming the overwrite and steps past all of
    this on purpose."""
    if stored_nonnull is None:
        return False
    return new_nonnull > stored_nonnull


def _stored_nonnull_days(s3_client, bucket: str, bronze_key: str) -> int | None:
    """Observed (non-null) days in the bronze month already at ``bronze_key``; None when unknowable.

    TWO READS, CHEAPEST FIRST.  The companion ``_meta.json`` carries ``nonnull_count`` for every
    partition this module has written since 2026-09-11 -- one small GET.  Every partition minted BEFORE
    that has no such field, and the 2026-08-22 all-null August skeletons are precisely those, so the
    fallback reads the partition itself: 7.4 KB MEASURED for a 31-row region-month, one column.

    ANY FAILURE TO READ IS AN UNKNOWN (None), never a decline in itself -- ``_rewrite_admitted`` owns
    what an unknown means, and this function only reports what it could and could not see."""
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


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _within_completeness_window(year: int, month: int, today: date,
                                lookback_days: int = _COMPLETENESS_LOOKBACK_DAYS) -> bool:
    """Is this elapsed month still young enough that the source may yet publish (more of) it?

    See ``_COMPLETENESS_LOOKBACK_DAYS``.  Outside the window the sentinel is trusted on EXISTENCE, which
    is the pre-fix behaviour byte for byte -- so a 1981 backfill month is never re-probed."""
    return (today - _month_end(year, month)).days <= lookback_days


def _abs_latitude(loc) -> float | None:
    """``|latitude|`` of a region, or None when the config does not state one this run can read."""
    try:
        return abs(float(loc["latitude"]))
    except (KeyError, TypeError, ValueError):
        return None


def _sentinel_location(locations: list[Region]):
    """The region whose bronze month object stands for "this month was processed, and how much arrived".

    TWO CHANGES FROM ``locations[0]``, both forced by the all-null write gate.  (a) The sentinel must be
    a region CHIRPS can actually cover: an out-of-band region (|lat| > 50) is now never written at all,
    so a commodity whose first region sits in Saskatchewan or Poland would have no sentinel for ANY
    month and every elapsed month would re-enter the window forever.  (b) Among in-band regions the one
    nearest the equator is chosen -- deterministic, and the least likely to sit at a coverage edge.

    AN UNSTATED LATITUDE IS NOT AN EXCLUSION.  A region whose config carries no readable ``latitude``
    cannot be PROVEN out of band, and here the consequence of excluding it is severe and asymmetric:
    excluding every region would leave the commodity with no sentinel at all and put every elapsed
    month back in the download window permanently.  So an unknown ranks BEHIND every region with a
    known in-band latitude and is used only when nothing else qualifies -- which reduces to
    ``locations[0]``, the pre-2026-09-11 sentinel, byte for byte.

    None means every region has a KNOWN latitude and all of them are outside the coverage band:
    structural absence, not a gap, and the caller declines the whole commodity rather than
    downloading rasters it cannot use."""
    in_band: list[tuple[float, Region]] = []
    unknown: list[Region] = []
    for loc in locations:
        lat = _abs_latitude(loc)
        if lat is None:
            unknown.append(loc)
        elif lat <= CHIRPS_LAT_LIMIT:
            in_band.append((lat, loc))
    if in_band:
        return min(in_band, key=lambda pair: pair[0])[1]
    return unknown[0] if unknown else None


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
    * The CURRENT year (the daily self-window) -> always re-download the current (incomplete) month
      AND the previous month; for an older month, download only when a sentinel bronze object is
      ABSENT (self-heal a within-year gap). ``force_overwrite`` re-downloads every elapsed month.
      PARTIAL-MONTH PERMANENCE FIX (2026-08-22): the sentinel proves the month was PROCESSED, not
      that it was COMPLETE -- July 2026 sat at ZERO chirps days behind an existing sentinel while
      daily runs kept succeeding. The previous month is therefore always in the window: by M-2 the
      source is final and the sentinel may again be trusted. NOTE the January edge: a daily
      January run passes year=current only, so December year-1 is refetched via main()'s
      previous-year top-up, not through this function.

      THE M-2 IMMUTABILITY ASSUMPTION, CLOSED (2026-09-11). "By M-2 the source is final" is FALSE for
      CHIRPS and was measured false: v2.0 finals publish in MONTH BLOCKS, and the August 2026 block was
      still entirely absent on 2026-09-11 -- eleven days past month-end, with the whole month due to
      land at once, i.e. AFTER August becomes M-2 on 2026-10-01. The 2026-08-22 all-null skeleton would
      have outlived the publication that was supposed to replace it, silently and forever. So for an
      older CURRENT-YEAR month the sentinel is no longer asked "do you EXIST" but "are you COMPLETE":
      absent -> download; present but holding fewer observed days than the calendar month has ->
      download; complete -> leave it, permanently. A month drops out of the window the instant it
      completes, so the extra cost is self-retiring, and past ``_COMPLETENESS_LOOKBACK_DAYS`` the
      existence test returns unchanged."""
    if year > today.year:
        return []
    if year == today.year - 1 and today.month == 1 and not force_overwrite:
        # The January edge of the partial-month fix: main()'s previous-year top-up only needs
        # December -- returning the full backfill window here would re-download 12 months of
        # global rasters every January daily run. An explicit operator backfill that truly wants
        # all of year-1 in January passes --force_overwrite (documented surprise, stated here).
        return [12]
    if year < today.year:
        return list(range(1, 13))
    if not locations:
        return []
    sentinel_loc = _sentinel_location(locations)
    if sentinel_loc is None:
        logger.info(
            "commodity=%s year=%d: every region is outside the CHIRPS %.0fS-%.0fN coverage band -- "
            "structural absence, no month of this year can carry precipitation",
            commodity, year, CHIRPS_LAT_LIMIT, CHIRPS_LAT_LIMIT,
        )
        return []
    sentinel_country = sentinel_loc["country"]
    sentinel_region = sentinel_loc["region"]
    months: list[int] = []
    for month in range(1, today.month + 1):
        if force_overwrite or month >= today.month - 1:      # current AND previous month, always
            months.append(month)
            continue
        sentinel = bronze_weather_key(
            "chirps", commodity, sentinel_country, sentinel_region, year, month, "part-000.parquet"
        )
        try:
            s3_client.head_object(Bucket=bucket, Key=sentinel)
        except Exception:  # noqa: BLE001 -- absent (or unprovable): (re)download this past month
            months.append(month)
            continue
        if not _within_completeness_window(year, month, today):
            continue                                          # settled: existence is final, as before
        stored = _stored_nonnull_days(s3_client, bucket, sentinel)
        if stored is None:
            continue          # unknown is never grounds to spend a month of global raster reads
        days_in_month = calendar.monthrange(year, month)[1]
        if stored < days_in_month:
            logger.info(
                "commodity=%s %d-%02d re-enters the window: sentinel %s holds %d of %d observed days "
                "(the source publishes CHIRPS finals in month blocks, so an incomplete elapsed month "
                "is a month still arriving, not a settled one)",
                commodity, year, month, sentinel_region, stored, days_in_month,
            )
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
        new_nonnull = _nonnull_day_count(rows)

        # WRITE-GATE (BF-W1, ported from chirps_year_to_bronze_task.py:177-188 -- the sibling has had
        # it since the post-rebuild census and this task never did). An all-null region-month is
        # STRUCTURAL ABSENCE: out of the 50S-50N coverage band, or a month the source has not published
        # yet. Minting a NaN partition fabricates presence, and that fabrication is what froze
        # gold_weather_z at 2026-07 for twenty days. The honest representation of no data is NO
        # partition. UNCONDITIONAL -- ``--force_overwrite`` may not overwrite a real month with an
        # empty one either, exactly as in the sibling.
        if new_nonnull == 0:
            logger.warning(
                "SKIP all-null precipitation (no partition written): commodity=%s country=%s "
                "region=%s %d-%02d (%d days fetched, 0 observed)",
                commodity, country, region, year, month, len(rows),
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
                # THE EXISTENCE-ONLY SKIP, REPLACED (2026-09-11). See ``_rewrite_admitted``: the old
                # branch logged "Skipping existing" and continued on EXISTENCE alone, which preserved
                # the 2026-08-22 all-null August skeleton through every subsequent green run.
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
            # THE YARDSTICK, PERSISTED. row_count is the calendar length of the month and is the same
            # 31 whether the source published 31 days or none; nonnull_count is what the next run's
            # ``_rewrite_admitted`` measures against, and writing it here is what keeps that decision
            # to one small GET instead of a Parquet read (``_stored_nonnull_days``).
            "nonnull_count": new_nonnull,
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

    # PARTIAL-MONTH FIX, the January edge (2026-08-22): a scheduled run passes only the current
    # year, so in January the always-refetch-previous-month rule cannot reach December year-1
    # through _months_to_process. Top it up with an explicit December pass of the prior year.
    years = [year]
    if args.year is None and today.month == 1:
        years.insert(0, year - 1)

    failures: list[str] = []
    for commodity in commodities:
        try:
            for y in years:
                _process_commodity(bucket, aws_region, commodity, y, args.ingest_date,
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
