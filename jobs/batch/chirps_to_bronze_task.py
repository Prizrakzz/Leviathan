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

THE PRELIM PRODUCT, AND THE TWO THINGS IT FORCED HERE (2026-09-15)
-----------------------------------------------------------------
CHIRPS v2.0 also publishes a PRELIM daily series, current to ~2 days past each closing pentad, while the
FINAL block lands +11..+16 days past month-end (five blocks over five years; the +11 is 2026-08, ONE
block write measured 2026-09-15 at Last-Modified 2026-09-11 21:10Z, which moved the lower bound down
from the 12 an earlier cut of this line carried).  Reading it moves ``gold_weather_z.drought_z`` about
eighteen days earlier -- but only if the estate can say WHICH PRODUCT a figure came from and can REPLACE
it when the authoritative block lands.  Two mechanisms carry that, and neither is optional:

A. THE SUPERSESSION AXIS.  ``_rewrite_admitted`` was a SCALAR on observed days, and EQUAL was a
   deliberate no-op.  A final block replacing a COMPLETE prelim month is exactly equal (31 -> 31), so
   under the shipped rule the final would be refused and the prelim would stand forever -- the 25-day
   revision horizon a promise the estate documents and never keeps.  The yardstick is now a
   LEXICOGRAPHIC PAIR ``(observed_days, final_days)``: observed keeps the anti-shrink floor untouched,
   final_days is the new monotone axis that carries supersession.
B. THE PRODUCT IS PERSISTED FROM THE FETCH, NOT DERIVED FROM THE ROWS.  final/prelim is a property of
   the DAY at the source (one global raster per day), so ``_meta.json`` carries ``final_days`` /
   ``prelim_days`` / ``absent_days`` counted over the days FETCHED.  A region whose single prelim day
   lands on a nodata pixel has NO prelim-valued row, and a row-derived flag would read that month as
   all-final while prelim bytes fed it.

THE ASYMMETRY, STATED ONCE: **any prelim day makes the month preliminary; only ALL final days make it
final.**  ``is_preliminary`` on a bronze row is a native bool (bronze has no pinned schema); the
bronze->silver seam converts it to the ``'0'``/``'1'`` string the pinned silver schema declares.

AND THE COST.  This task opened the raster ONCE PER (day, COMMODITY) while its sibling year task opened
each day once for every commodity at once.  Unpublished days used to cost an instant 404; with prelim
they are REAL multi-MB reads that ``/vsigzip/`` must inflate from byte 0 to the target row.  So the
per-run day cache below gives this task the year task's cross-commodity dedup: each (year, month, day)
raster is opened ONCE PER RUN, and every commodity reads its own pixels out of that one open.

Required args: --commodity, --year, --bucket, --aws_region
Optional args: --ingest_date (default: today), --force_overwrite (default: false)
"""
from __future__ import annotations

import argparse
import calendar
import io
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone

import pandas as pd
from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.common.types import Region
from leviathan.ingestion.weather.chirps import (
    PRELIM_MONTH_REACH,
    PRODUCT_ABSENT,
    PRODUCT_FINAL,
    PRODUCT_PRELIM,
    day_url_template,
    fetch_chirps_daily_values_with_product,
    is_prelim_reachable,
)
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


def _rewrite_admitted(new_nonnull: int, stored_nonnull: int | None,
                      new_final: int | None = None, stored_final: int | None = None) -> bool:
    """May this run REPLACE an existing bronze month with what it just fetched?

    A LEXICOGRAPHIC PAIR, NOT A SCALAR (2026-09-15, the prelim lane).  ``(observed_days, final_days)``:
    admitted when the pair strictly increases in EITHER component and decreases in NEITHER.

      * ``observed_days`` is the original yardstick and keeps its meaning exactly -- MORE observed days
        is an improvement, FEWER is the shrink the floor refuses, EQUAL is the ordinary same-day rerun.
      * ``final_days`` is the SUPERSESSION axis, and it is the reason a scalar could not be stretched to
        carry this.  When the FINAL block lands over a month already complete on PRELIM, the observed
        count goes 31 -> 31: EQUAL, which the scalar rule refuses by design (AV-12).  The final would
        never replace the prelim, the served drought_z would be the prelim vintage forever, and the
        revision horizon would be documentation of something that does not happen.  MEASURED proof the
        two vintages differ: malaysia_palm 2026-07-15 read 6.5214 mm final vs 7.6490 mm prelim.
      * A DECREASE on the final axis is refused for the same reason a decrease on the observed axis is:
        a run that saw fewer FINAL days than the stored partition holds is a regression in vintage, not
        a refresh, and it must never overwrite the better bytes.

    BOTH AXES DEFAULT TO ``None`` = NOT STATED, and with the final axis unstated the verdict is the
    pre-lane scalar rule byte for byte -- which is what keeps ``test_chirps_bronze_completeness_skip``'s
    whole decision table green without an edit.

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
    if new_nonnull < stored_nonnull:
        return False
    if new_final is not None and stored_final is not None:
        if new_final < stored_final:
            return False                              # a vintage regression is a shrink too
        return new_nonnull > stored_nonnull or new_final > stored_final
    return new_nonnull > stored_nonnull


def _stored_day_counts(s3_client, bucket: str, bronze_key: str) -> tuple[int | None, int | None]:
    """``(observed days, FINAL-product days)`` of the bronze month at ``bronze_key``; None where unknown.

    TWO READS, CHEAPEST FIRST.  The companion ``_meta.json`` carries ``nonnull_count`` for every
    partition this module has written since 2026-09-11 -- one small GET -- and ``final_days`` for every
    one written since the prelim lane.  Every partition minted BEFORE that has neither field, and the
    2026-08-22 all-null August skeletons are precisely those, so the fallback reads the partition
    itself: 7.4 KB MEASURED for a 31-row region-month, ONE column.

    THE COLUMN THIS FUNCTION MUST NEVER ASK FOR IS ``is_preliminary`` (T-B2).  Asking pyarrow for a
    column a pre-lane partition does not have RAISES, and the ``except`` below books that as UNKNOWN,
    which DECLINES the rewrite -- so the one column added to carry supersession would have switched OFF
    the self-heal the 2026-09-11 lane had just built, for every legacy month of 1981-2025.  The final
    count is therefore read from the META alone, and a partition whose meta does not declare one is a
    PRE-LANE OBJECT whose observed days are ALL FINAL: prelim was unreachable when those bytes were
    written, so ``final_days = nonnull_count`` is a true statement about them and not a convenience.

    ANY FAILURE TO READ IS AN UNKNOWN (None), never a decline in itself -- ``_rewrite_admitted`` owns
    what an unknown means, and this function only reports what it could and could not see."""
    meta_key = bronze_key.replace("part-000.parquet", "_meta.json")
    nonnull: int | None = None
    final: int | None = None
    try:
        meta = json.loads(s3_client.get_object(Bucket=bucket, Key=meta_key)["Body"].read())
        value = meta.get("nonnull_count")
        if isinstance(value, int) and not isinstance(value, bool):
            nonnull = value
        stated_final = meta.get("final_days")
        if isinstance(stated_final, int) and not isinstance(stated_final, bool):
            final = stated_final
    except Exception as exc:  # noqa: BLE001 -- no/unreadable meta is ordinary for a pre-2026-09-11 object
        logger.debug("No readable nonnull_count in %s (%s) -- reading the partition", meta_key, exc)
    if nonnull is None:
        try:
            body = s3_client.get_object(Bucket=bucket, Key=bronze_key)["Body"].read()
            col = pd.read_parquet(io.BytesIO(body), columns=["precipitation_mm"])["precipitation_mm"]
            nonnull = int(col.notna().sum())
        except Exception as exc:  # noqa: BLE001 -- an unreadable partition is an UNKNOWN, never a decline
            logger.warning(
                "Could not read the stored observation count of %s (%s: %s) -- treating it as UNKNOWN, "
                "which declines the rewrite; --force_overwrite true names the overwrite",
                bronze_key, type(exc).__name__, str(exc)[:200],
            )
    if final is None and nonnull is not None:
        final = nonnull                     # a pre-lane partition is all-final by construction
    return nonnull, final


def _stored_nonnull_days(s3_client, bucket: str, bronze_key: str) -> int | None:
    """Observed (non-null) days in the bronze month already at ``bronze_key``; None when unknowable.

    The observed half of :func:`_stored_day_counts`, kept as its own name because it is the yardstick
    ``_rewrite_admitted``'s anti-shrink floor is written in terms of."""
    return _stored_day_counts(s3_client, bucket, bronze_key)[0]


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
        stored, stored_final = _stored_day_counts(s3_client, bucket, sentinel)
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
            continue
        # THE FINAL RE-CHECK CLAUSE (2026-09-15).  A month completed on PRELIM reads 31/31 observed and
        # would leave the window permanently on the observed axis alone -- the same M-2 immutability
        # defect, re-opened one level up by the prelim.  A month still inside PRELIM_MONTH_REACH whose
        # sentinel holds fewer FINAL days than the calendar month therefore comes back, so the landed
        # block can supersede.  STATED PLAINLY: under PRELIM_MONTH_REACH = 1 this branch is UNREACHABLE,
        # because the loop above already appends the current and previous month unconditionally and the
        # reach admits nothing older.  It is written, and decked, because it is the INVARIANT -- widen
        # the reach and a prelim month would otherwise be stranded silently -- and because the two
        # windows must read the same constant rather than agree by coincidence.
        if (stored_final is not None and stored_final < days_in_month
                and is_prelim_reachable(year, month, today)):
            logger.info(
                "commodity=%s %d-%02d re-enters the window on the FINAL axis: sentinel %s holds %d of "
                "%d FINAL days (the rest are preliminary and the authoritative block may have landed)",
                commodity, year, month, sentinel_region, stored_final, days_in_month,
            )
            months.append(month)
    return months


def _coord(loc: Region) -> tuple[float, float] | None:
    """The (lat, lon) key a raster pixel is cached under -- rounded exactly as the year task rounds it.

    ``None`` when the config does not state coordinates this run can read, for the same reason
    ``_abs_latitude`` returns None: a malformed entry must yield a NULL reading (which the all-null
    write gate then handles) and never take the whole commodity-month down with a ValueError. The
    pre-lane code reached ``values.get(region)`` for such a location and got None; ``values.get(None)``
    is that same None."""
    try:
        return (round(float(loc["latitude"]), 6), round(float(loc["longitude"]), 6))
    except (KeyError, TypeError, ValueError):
        return None


def _build_flat_locations(commodity_regions: dict[str, list[Region]]) -> list[Region]:
    """Every distinct in-band COORDINATE across the commodities this run will process.

    THE COST GATE'S MITIGATION (b), ported from ``chirps_year_to_bronze_task._build_location_index``.
    This task opened each day's raster once per (day, COMMODITY); the sibling opens it once per day for
    every commodity at once.  While unpublished days cost an instant 404 that difference was invisible.
    With the prelim fallback each of those days is a real 2-11 MB transfer that ``/vsigzip/`` must
    inflate from byte 0 to the deepest requested row, so the per-commodity shape would multiply the
    daily run's transfer by the commodity count.

    Regions outside the CHIRPS 50S-50N band are dropped here exactly as the sibling drops them: their
    pixel read returns None today (``src.index`` lands outside the raster), so excluding the coordinate
    changes no row and only stops paying for a read whose answer is known."""
    seen: set[tuple[float, float]] = set()
    flat: list[Region] = []
    for regions in commodity_regions.values():
        for loc in regions:
            lat = _abs_latitude(loc)
            if lat is None or lat > CHIRPS_LAT_LIMIT:
                continue
            coord = _coord(loc)
            if coord is None or coord in seen:
                continue
            seen.add(coord)
            flat.append(loc)
    return flat


class _DayRasterCache:
    """ONE open per (year, month, day) PER RUN, shared by every commodity and every month worker.

    Keyed by COORDINATE rather than by region name on purpose: two commodities may carry the same
    growing cell under different region tokens, and a name-keyed cache would either alias them or miss.

    THREAD-SAFE BY A PER-KEY LOCK, not by a global one: months run in a 12-thread pool and days inside
    a month in a 5-thread pool, so a single global lock would serialise the whole fetch, while no lock
    at all would let N threads open the SAME day concurrently -- which is the cost this class exists to
    remove.  A failed day is cached as a FAILURE, not retried per commodity: the retry budget belongs to
    ``_read_cog_values``'s tenacity wrapper, and re-opening a day that just failed once per commodity is
    exactly the throttling spiral the pool cap of 5 exists to avoid."""

    def __init__(self, flat_locations: list[Region], today: date | None = None) -> None:
        # THE FETCH KEYS ARE SYNTHETIC, and that is not tidiness. ``_read_cog_values`` returns a dict
        # keyed by ``loc["region"]``, so two DIFFERENT coordinates that happen to share a region token
        # -- entirely possible once the union spans 31 commodities' region files -- would collapse into
        # one entry and silently give both cells the same reading. Fetching under an index-derived name
        # makes the key unique by construction; the coordinate is the only thing callers ever look up.
        self._coords = [_coord(loc) for loc in flat_locations]
        self._fetch_locs: list[Region] = [
            {"region": f"_c{i}", "latitude": loc["latitude"], "longitude": loc["longitude"]}
            for i, loc in enumerate(flat_locations)
        ]
        self._today = today
        self._guard = threading.Lock()
        self._key_locks: dict[tuple[int, int, int], threading.Lock] = {}
        self._cache: dict[tuple[int, int, int], tuple[dict, str, str | None]] = {}

    def get(self, year: int, month: int, day: int) -> tuple[dict, str, str | None]:
        """``(values_by_coord, product, failure_kind)``.  ``failure_kind`` is None on a clean read."""
        key = (int(year), int(month), int(day))
        with self._guard:
            hit = self._cache.get(key)
            if hit is not None:
                return hit
            key_lock = self._key_locks.setdefault(key, threading.Lock())
        with key_lock:
            with self._guard:
                hit = self._cache.get(key)
            if hit is not None:
                return hit
            try:
                values, product = fetch_chirps_daily_values_with_product(
                    year, month, day, self._fetch_locs, today=self._today)
                by_coord = {coord: values.get(loc["region"])
                            for coord, loc in zip(self._coords, self._fetch_locs) if coord is not None}
                result = (by_coord, product, None)
            except Exception as exc:  # noqa: BLE001 -- one day's transport failure must not kill the month
                logger.warning("Failed to fetch %d-%02d-%02d -- skipping day", year, month, day,
                               exc_info=True)
                result = ({}, PRODUCT_ABSENT, type(exc).__name__)
            with self._guard:
                self._cache[key] = result
            return result


def _process_month(
    aws_region: str,
    bucket: str,
    commodity: str,
    year: int,
    month: int,
    locations: list[Region],
    ingest_date: str,
    force_overwrite: bool,
    day_cache: "_DayRasterCache | None" = None,
    today: date | None = None,
) -> None:
    days_in_month = calendar.monthrange(year, month)[1]
    region_rows: dict[tuple[str, str], list[dict]] = {}
    # THE DAY -> PRODUCT MAP, held at MONTH grain because that is the grain the source publishes at and
    # the grain the flag is decided at.  It is filled from the FETCH result, never from the rows.
    day_product: dict[int, str] = {}
    # T-C2: a month that is short because N transport failures ate its days is a DIFFERENT fact from a
    # month that is short because the source has not published it, and before this the two were the same
    # silent WARNING.  Counted here, written into _meta.json, printed in the write line.
    fetch_failures: dict[str, int] = {}
    # ...AND THE SEPARATION IS ONLY REAL IF absent_days STOPS DOUBLE-COUNTING.  _DayRasterCache books a
    # transport failure as PRODUCT_ABSENT because it has no values to hand back, so without this set a
    # throttled day would read as "CHIRPS has not published this day" in the ONE field an operator
    # reaches for -- which is exactly the inference T-C2 exists to forbid.  A failed day is booked in
    # fetch_failures and NOWHERE else; final + prelim + absent therefore need not sum to the calendar
    # month, and the shortfall IS the failure count.
    failed_days: set[int] = set()

    # With no cache supplied (a single-commodity backfill, or a deck driving one month) the cache is
    # built over THIS commodity's own coordinates -- identical reads to the pre-lane shape, and the
    # within-commodity dedup comes free.
    cache = day_cache if day_cache is not None else _DayRasterCache(
        _build_flat_locations({commodity: locations}), today=today)

    def _fetch_day(day: int) -> tuple[int, dict, str, str | None]:
        by_coord, product, failure = cache.get(year, month, day)
        return day, by_coord, product, failure

    with ThreadPoolExecutor(max_workers=5) as pool:  # cap at 5 to avoid throttling UCSB server
        futures = {pool.submit(_fetch_day, d): d for d in range(1, days_in_month + 1)}
        for future in as_completed(futures):
            day, values, product, failure = future.result()
            if failure is not None:
                fetch_failures[failure] = fetch_failures.get(failure, 0) + 1
                failed_days.add(day)
            day_product[day] = product
            if not values:
                continue
            day_str = date(year, month, day).isoformat()
            is_prelim = product == PRODUCT_PRELIM
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
                    "precipitation_mm":  values.get(_coord(loc)),
                    # Bronze has NO pinned schema, so the flag rides as a native bool here; the
                    # bronze->silver seam converts it to the '0'/'1' string the pinned silver schema
                    # declares (the gold_board_crush.is_roll_boundary precedent).
                    "is_preliminary":    is_prelim,
                    "ingest_date":       ingest_date,
                })

    final_days   = sum(1 for p in day_product.values() if p == PRODUCT_FINAL)
    prelim_days  = sum(1 for p in day_product.values() if p == PRODUCT_PRELIM)
    # SOURCE ABSENCE ONLY -- a 404 on BOTH products.  A day whose fetch RAISED is excluded here and
    # counted in fetch_failures alone (see failed_days above, T-C2 / R-6).
    absent_days  = sum(1 for d, p in day_product.items()
                       if p == PRODUCT_ABSENT and d not in failed_days)

    if not region_rows:
        logger.warning("No data for %d-%02d commodity=%s (final=%d prelim=%d absent=%d, "
                       "transport failures=%s)",
                       year, month, commodity, final_days, prelim_days, absent_days,
                       fetch_failures or "none")
        return

    s3_client = get_thread_local_s3_client(aws_region)
    access_timestamp = datetime.now(timezone.utc).isoformat()
    # PROVENANCE COMES FROM THE FETCHER, NOT FROM A LITERAL HERE: day_url_template is the same
    # function _build_cog_url / _build_prelim_cog_url format, so a base-URL move can never leave the
    # recorded URL describing a path the bytes did not come from.
    source_url_template = day_url_template(year, month)
    prelim_source_url_template = day_url_template(year, month, preliminary=True)
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
                # THE SECOND AXIS (2026-09-15): final_days carries supersession, because a landed FINAL
                # block over a complete PRELIM month is EQUAL on the observed axis and would be refused.
                stored, stored_final = _stored_day_counts(s3_client, bucket, bkey)
                if not _rewrite_admitted(new_nonnull, stored, final_days, stored_final):
                    logger.info(
                        "Skipping fresh: %s (this run observed %d of %d days, %d of them FINAL; "
                        "stored holds %s observed / %s final -- a rewrite may only ADD observed days "
                        "or ADD final days)",
                        bkey, new_nonnull, len(rows), final_days,
                        "an unreadable count" if stored is None else f"{stored}",
                        "an unreadable count" if stored_final is None else f"{stored_final}",
                    )
                    continue
                logger.info(
                    "Refreshing bronze: %s (observed days %d -> %d of %d; FINAL days %s -> %d)",
                    bkey, stored, new_nonnull, len(rows), stored_final, final_days,
                )

        df  = pd.DataFrame(rows)
        buf = io.BytesIO()
        df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
        s3_client.put_object(Bucket=bucket, Key=bkey, Body=buf.getvalue())
        logger.info("Wrote bronze: %s (%d rows; final=%d prelim=%d absent=%d%s)",
                    bkey, len(df), final_days, prelim_days, absent_days,
                    "  PRELIMINARY MONTH" if prelim_days else "")

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
            # THE PRODUCT COUNTS, from the FETCH and never from the rows (T-B3). final_days is the
            # SUPERSESSION axis the next run reads; prelim_days > 0 is what makes the month
            # PRELIMINARY (any prelim day does; only ALL final days make it final); absent_days is
            # the source having published neither product for that day -- SOURCE ABSENCE ONLY, with a
            # day whose fetch raised excluded and carried in fetch_failures instead, so the three
            # product counts need not sum to the calendar month and the shortfall is the failures.
            # These are counted over the days FETCHED, so they describe the SOURCE, not this region's
            # pixel -- a region whose one prelim day sits on a nodata pixel still declares the month
            # preliminary here.
            "final_days": final_days,
            "prelim_days": prelim_days,
            "absent_days": absent_days,
            "is_preliminary": prelim_days > 0,
            # T-C2: distinguishes "the source has not published" from "the host refused us N times".
            # absent_days answers the first question and ONLY the first; this map answers the second.
            "fetch_failures": fetch_failures,
            "source_url_template": source_url_template,
            "prelim_source_url_template": prelim_source_url_template,
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
    locations: list[Region] | None = None,
    day_cache: "_DayRasterCache | None" = None,
) -> None:
    s3_client = get_thread_local_s3_client(aws_region)
    if locations is None:
        # The caller could not pre-load this commodity, so the SHARED day cache was built without its
        # coordinates and a pixel read against it would return None for every day -- an all-null month
        # and no partition, silently. Load here and drop to a PRIVATE cache over this commodity alone.
        locations = load_commodity_regions(s3_client, bucket, commodity)
        day_cache = None
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
                day_cache=day_cache,
                today=today,
            ): month
            for month in months
        }
        for future in as_completed(futures):
            month = futures[future]
            future.result()  # re-raise: a failed month must be LOUD (per-commodity caught in main)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(description="CHIRPS COG -> bronze (Batch task)")
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
        "CHIRPS -> bronze  commodities=%d  year=%d  force_overwrite=%s",
        len(commodities), year, force_overwrite,
    )

    # THE PER-RUN DAY CACHE (the cost gate's mitigation (b)). Load every commodity's regions ONCE, take
    # the union of their in-band COORDINATES, and open each (year, month, day) raster once for all of
    # them -- the shape the sibling year task has always had. Before the prelim fallback the difference
    # was invisible because an unpublished day cost an instant 404; now each such day is a real
    # multi-MB read that ``/vsigzip/`` cannot seek into, so the per-commodity shape would have
    # multiplied the daily run's transfer by the commodity count against a public academic host.
    s3_boot = get_thread_local_s3_client(aws_region)
    regions_by_commodity: dict[str, list[Region] | None] = {}
    for commodity in commodities:
        try:
            regions_by_commodity[commodity] = load_commodity_regions(s3_boot, bucket, commodity)
        except Exception as exc:  # noqa: BLE001 -- the per-commodity loop below owns this failure
            # NOT swallowed: left as None so ``_process_commodity`` loads it again and raises into the
            # per-commodity try below, exactly as it did before this cache existed. A pre-load that
            # turned a config failure into a silent skip would be a new way to lose a commodity.
            logger.warning("Region config pre-load failed for %s (%s) -- deferring to the run loop",
                           commodity, type(exc).__name__)
            regions_by_commodity[commodity] = None
    flat_locations = _build_flat_locations(
        {c: r for c, r in regions_by_commodity.items() if r})
    day_cache = _DayRasterCache(flat_locations, today=today)
    logger.info(
        "day-raster cache: %d unique in-band coordinates across %d commodities -- one open per day "
        "per RUN (prelim reach = the current month and the %d before it)",
        len(flat_locations), len(regions_by_commodity), PRELIM_MONTH_REACH,
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
                                   force_overwrite, today,
                                   locations=regions_by_commodity.get(commodity),
                                   day_cache=day_cache)
        except Exception as exc:  # noqa: BLE001 -- one commodity's failure must not kill the rest
            logger.error("[%s] FAILED: %s: %s", commodity, type(exc).__name__, str(exc)[:300])
            failures.append(commodity)

    logger.info("Done: commodities=%d year=%d%s",
                len(commodities), year, f"  FAILURES={failures}" if failures else "")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
