"""AWS Batch entrypoint: NOAA CPC Soil Moisture daily GeoTIFFs → raw S3.

Runs as a Fargate container task.  No Glue bootstrap — leviathan is
installed in the image via ``pip install -e ".[batch]"``.

For years prior to the current year, downloads the full annual tarball
(~82–89MB) and extracts all 365/366 daily GeoTIFFs in memory.  For the
current year, downloads individual daily files from the live GeoTIFF
directory — the two directories have DISJOINT domains, so this is not a
preference but the only route.  MEASURED 2026-09-11: ``clim/`` carries
closed years only (``w.2000``..``w.2025`` plus ``w.40ym``; HEAD
``clim/w.2026.tif.tar.gz`` = 404 while ``clim/w.2025.tif.tar.gz`` = 200),
while ``GeoTIFF/`` carries 1,512 files that are all 2026.  See
``tests/fixtures/cpc_soil/capture_notes.md``.

EXIT-CODE CONTRACT.  A day CPC has not published, or one day that fails to download, is a stated
DECLINE and the leg still exits 0 — its job is to carry forward every day it can reach.  Two things
exit nonzero, and only two:

  * ``DailyWindowOutage`` — every day of a fetch window at least ``_OUTAGE_MIN_WINDOW_DAYS`` wide
    declined.  Reaching NOTHING is not a decline.  A one-day window (the steady state) that wholly
    declined is a WARNING instead: it is red on the next run if the break lasts, and a source that
    has actually stopped is caught by the alarm below, which needs no window at all.
  * ``PublisherStall`` — CPC's newest PUBLISHED day has fallen ``_PUBLISHER_STALL_RED_DAYS`` days
    behind the calendar (measured against ``_PUBLICATION_LAG_DAYS``), with a WARNING from
    ``_PUBLISHER_STALL_WARN_DAYS``.  Moving the expectation onto CPC's published set is what killed
    the phantom hole, and it is also what would have made a stopped publisher invisible: raw
    complete to a frozen tip reports no deficit at all.  This is the calendar, kept.

This matters because the exit code is the only instrument on this leg: measured 2026-09-11 there
are no metric filters on ``/aws/batch/job``, and both weather freshness alarms read OK while
silver_cpc_soil sat frozen at 2026-09-05.  ``weather_daily``'s fetch Map tolerates a failed cpc job
(measured: SUCCEEDED executions on 09-08, 09-09 and 09-10 with this job FAILED inside them), so red
here is an alarm, never a chain break.

Raw S3 path: raw/weather/source=cpc_soil/variable={v}/date={YYYYMMDD}/{v}.{YYYYMMDD}.tif

Required args: --year, --bucket, --aws_region
Optional args: --variable (default: w), --ingest_date, --force_overwrite
"""
from __future__ import annotations

import argparse
import calendar
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

import requests
from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.ingestion.weather.cpc_soil_moisture import (
    CPC_FTP_BASE,
    download_cpc_annual_tarball,
    download_cpc_daily_tif,
    extract_tifs_from_tarball,
)
from leviathan.storage.paths import raw_cpc_tif_key
from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys

logger = get_logger("cpc_soil_to_raw_task")

# MEASURED 2026-09-11: ``GeoTIFF/w.20260909.tif`` carries Last-Modified
# "Thu, 10 Sep 2026 17:53:44 GMT" -- CPC publishes day D at about 17:53Z on D+1, which is AFTER the
# 08:00Z weather_daily fire (``GeoTIFF/w.20260910.tif`` was still 404 at 09:30Z on 09-11).  So at
# run time on day T the newest published day is T-2, never T-1.  The pre-2026-09-11 code assumed a
# ONE-day lag, which manufactured a phantom trailing hole on every single run and then tried to
# heal it from a current-year tarball that does not exist.  This constant is only a FALLBACK: the
# live GeoTIFF index is the primary statement of what has been published.
_PUBLICATION_LAG_DAYS = 2

# MEASURED 2026-09-11: ``clim/w.2025.tif.tar.gz`` carries Last-Modified "Tue, 03 Mar 2026 23:03:20
# GMT" -- a year CLOSING does not make its archive exist; 2025's appeared about two months after
# 2025 ended.  So the opportunistic previous-December self-heal has a SEASON: it can only succeed
# once the archive is published, and outside that season a still-short December is an OPERATOR
# backfill (``--year <prev>``), stated on its own line rather than retried at 86MB a day forever.
_ARCHIVE_SELF_HEAL_THROUGH_MONTH = 3

# THE PUBLISHER-STALL THRESHOLDS, counted in days BEYOND the measured ``_PUBLICATION_LAG_DAYS``
# above.  ``days_behind = (today - _PUBLICATION_LAG_DAYS) - newest_published_day``: 0 is the steady
# state, and each threshold is compared with ``>=`` so the drive dates read straight off the
# calendar.  With the index tip at 20260909 the leg is quiet through 2026-09-13 (days_behind 2),
# WARNS from 2026-09-14 (3) and goes RED from 2026-09-18 (7).
#
# WHY THESE NUMBERS.  The warn threshold is one day past the widest lag this source has been
# measured at: the 2026 GeoTIFF index carried Jan 1 .. Sep 9 with NO interior gap on 2026-09-11, so
# every day of 2026 arrived within the two-day lag and a three-day distance has never been normal
# here.  The red threshold is 7 because ``leviathan-dev-freshness-sla-breach-weather`` fires on
# FreshnessLagDays > 3 and read OK throughout the September freeze -- an alarm that cannot be
# trusted cannot set this floor, so RED is set where a week of silence has certainly stopped being
# lateness.  Both are POLICY, and they are named so a measurement can move them.
_PUBLISHER_STALL_WARN_DAYS = 3
_PUBLISHER_STALL_RED_DAYS = 7

# The smallest fetch window a TOTAL decline may redden the leg on.  In the steady state the window
# is exactly ONE day -- the single day CPC published since the last run -- so keying the outage on
# "every day of the window declined" alone put the whole leg's exit code on one GET of one 875KB
# file.  A one-day window that wholly declined is a stated WARNING instead; what makes that safe is
# the calendar-side PUBLISHER STALL alarm above (a source that has actually STOPPED is now caught
# against the calendar, not against an empty window) and the window's own arithmetic (a break that
# lasts into a second run makes the window two days, and RED fires then).
_OUTAGE_MIN_WINDOW_DAYS = 2

# Which yardstick produced a month's expectation.  Tokens, not prose, so the report and the tests
# name the same fact; ``_BASIS_PHRASE`` is the only place the operator-facing wording lives.
_BASIS_PUBLISHED = "published"
_BASIS_CALENDAR_LAGGED = "calendar-lagged"
_BASIS_CALENDAR_FULL = "calendar-full"
_BASIS_PHRASE = {
    _BASIS_PUBLISHED: "the days CPC has PUBLISHED",
    _BASIS_CALENDAR_LAGGED: (
        f"CALENDAR days minus the measured {_PUBLICATION_LAG_DAYS}-day publication lag "
        f"-- the live index could not be read this run"
    ),
    _BASIS_CALENDAR_FULL: "the CALENDAR days of a month the current listing does not cover",
}


class DailyWindowOutage(RuntimeError):
    """EVERY day of a non-empty fetch window failed to download.

    Why this is an exception and not another warning.  A per-day 404 is a decline -- the leg's job
    is to carry forward every day it can reach.  But the case where it reached NOTHING from a
    window it believed non-empty is not a decline, it is an outage: a vanished source directory, an
    egress break, an expired cert.  MEASURED 2026-09-11, the exit code is the ONLY instrument that
    fires on this leg -- ``aws logs describe-metric-filters --log-group-name /aws/batch/job``
    returns nothing, and both weather alarms (``leviathan-dev-freshness-sla-breach-weather``,
    FreshnessLagDays > 3d, and ``leviathan-dev-freshness-breach-count-weather``) read OK on 09-07
    and 09-08 while silver_cpc_soil was frozen at 2026-09-05.  A leg that reports SUCCEEDED on a
    total outage is exactly the "every scheduled run succeeded while the data froze" class this
    repair exists to close, so the outage keeps the nonzero exit the pre-repair shape had.

    THE WINDOW IS MEASURED (review round 2).  The first shape of this floor keyed only on "every
    day declined", and the steady-state window here is exactly ONE day -- so a single failed 875KB
    GET reddened the whole leg, and "if the live index is unreadable AND CPC is a day late" was
    enough to do it.  The floor is now ``_OUTAGE_MIN_WINDOW_DAYS`` wide: a one-day total decline is
    a stated WARNING (SINGLE-DAY DECLINE), which is honest because a break that lasts into the next
    run widens the window past the floor, and because a source that has STOPPED is caught by
    ``PublisherStall`` against the calendar rather than by an empty window.

    The residual cost is stated too: two or more days unreachable at once -- including the case
    where the index is unreadable and the calendar fallback enumerates days CPC has not published
    yet -- is red.  That is a true statement (the leg could not get what it expected), and the DAG's
    map tolerates a failed cpc job, so red here is an alarm, never a chain break.
    """


class PublisherStall(RuntimeError):
    """CPC's newest PUBLISHED day has fallen too far behind the calendar.

    THE HOLE THIS CLOSES (review round 2, 2026-09-11).  The repair above moved the current year's
    expectation off the calendar and onto CPC's own published set, which is what killed the phantom
    hole -- but it also made the leg blind to CPC STOPPING.  Drive the shipped code with the index
    frozen at tip 20260909 and raw complete to that tip and the leg is silent: a run on 2026-09-12
    exits 0 with zero warnings, and so does one on 2026-09-20, eleven days stale.  The hole report
    compares raw against the published set and finds no deficit (we hold every published day); the
    UPSTREAM SHORT fence skips September until it is settled past the lag, so its first word comes
    only on 2026-10-05.  Three weeks of a frozen source, reported as SUCCEEDED.

    So the calendar is not deleted, it is put where it belongs: the published SET stays the
    expectation for what we must HOLD, and the published TIP is measured against the calendar for
    whether the source is still alive.  ``_PUBLISHER_STALL_WARN_DAYS`` days behind the measured lag
    is a WARNING, ``_PUBLISHER_STALL_RED_DAYS`` is this exception and a nonzero exit -- because the
    exit code is still the only instrument that fires on this leg.

    The DAG tolerates it: ``weather_daily``'s fetch Map ran to SUCCEEDED on 09-08, 09-09 and 09-10
    with this job FAILED inside it, so a red cpc job is an alarm and never a chain break.  And a
    stall is reported even when the run is otherwise perfect -- there is nothing for the leg to DO
    about an upstream stall except say so loudly.
    """


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _put_tif(
    s3_client,
    bucket: str,
    variable: str,
    date_str: str,
    tif_bytes: bytes,
    source_url: str,
    access_timestamp: str,
    force_overwrite: bool,
) -> bool:
    """Write one TIF and its companion meta JSON to S3 raw.  Returns True if written."""
    filename = f"{variable}.{date_str}.tif"
    key = raw_cpc_tif_key(variable, date_str, filename)

    if not force_overwrite:
        try:
            s3_client.head_object(Bucket=bucket, Key=key)
            logger.debug("Skip existing: %s", key)
            return False
        except s3_client.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] != "404":
                raise

    s3_client.put_object(Bucket=bucket, Key=key, Body=tif_bytes)
    logger.info("Wrote raw TIF: %s (%d bytes)", key, len(tif_bytes))

    meta_key = key.replace(f"{filename}", "_meta.json")
    meta = {
        "source": "cpc_soil",
        "variable": variable,
        "date": date_str,
        "file_size_bytes": len(tif_bytes),
        "source_url": source_url,
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
# Historical backfill (annual tarball)
# ---------------------------------------------------------------------------

def _process_year_via_tarball(
    year: int,
    variable: str,
    bucket: str,
    aws_region: str,
    ingest_date: str,
    force_overwrite: bool,
) -> tuple[int, int]:
    """Download annual tarball, extract all TIFs, store to S3.  Returns (written, skipped)."""
    tar_bytes = download_cpc_annual_tarball(year, variable)
    daily_tifs = extract_tifs_from_tarball(tar_bytes, variable)

    if not daily_tifs:
        logger.warning("No TIFs extracted from tarball for variable=%s year=%d", variable, year)
        return 0, 0

    access_timestamp = datetime.now(timezone.utc).isoformat()
    source_url_template = f"{CPC_FTP_BASE}/clim/{variable}.{year}.tif.tar.gz"

    written = skipped = 0

    def _upload(date_str: str, tif_bytes: bytes) -> bool:
        s3_client = get_thread_local_s3_client(aws_region)
        return _put_tif(
            s3_client, bucket, variable, date_str, tif_bytes,
            source_url_template, access_timestamp, force_overwrite,
        )

    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(_upload, ds, tb): ds for ds, tb in daily_tifs.items()}
        for future in as_completed(futures):
            if future.result():
                written += 1
            else:
                skipped += 1

    logger.info(
        "Tarball backfill complete  variable=%s year=%d  written=%d skipped=%d",
        variable, year, written, skipped,
    )
    return written, skipped


# ---------------------------------------------------------------------------
# Current-year incremental (daily files)
# ---------------------------------------------------------------------------

def _parse_daily_listing(html: str, year: int, variable: str) -> list[str]:
    """Pure parser for the CPC GeoTIFF index page -> sorted ``YYYYMMDD`` strings.

    The index carries EVERY variable for the whole calendar year (measured 2026-09-11: 1,512
    anchors = six variables x 252 days), so both the variable prefix and the year are real filters,
    never assumptions about what the page holds.  Kept parameter-pure so the parse is unit-tested
    against the captured fixture (``tests/fixtures/cpc_soil/geotiff_index.sample.html``) with no
    network in the loop.
    """
    prefix = f"{variable}.{year}"
    dates: set[str] = set()
    for line in html.splitlines():
        # HTML anchor lines carry the filename inside quotes: href="w.20260524.tif"
        for token in line.split('"'):
            if token.startswith(prefix) and token.endswith(".tif"):
                stem = token[len(variable) + 1:-4]  # strip "w." and ".tif"
                try:
                    datetime.strptime(stem, "%Y%m%d")
                except ValueError:
                    continue
                dates.add(stem)
    return sorted(dates)


def _list_available_daily_dates(year: int, variable: str) -> tuple[list[str], bool]:
    """Return ``(YYYYMMDD list, listing_verified)`` for the live GeoTIFF directory.

    ``listing_verified`` is False when the live index could not be read or did not parse: the
    calendar enumeration returned in its place is a guess good enough to ATTEMPT (a day CPC has not
    published answers 404 and is declined per-day), but it must never be mistaken for a statement
    of what has been published when counting holes.
    """
    url = f"{CPC_FTP_BASE}/GeoTIFF/"
    logger.info("Listing CPC GeoTIFF directory: %s", url)
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Failed to list GeoTIFF directory: %s — falling back to calendar enumeration", exc)
        return _enumerate_dates_up_to_today(year), False

    dates = _parse_daily_listing(resp.text, year, variable)
    if dates:
        logger.info(
            "Found %d daily files for %s %d in GeoTIFF dir (publication tip %s)",
            len(dates), variable, year, dates[-1],
        )
        return dates, True
    # Fallback if directory listing didn't parse cleanly
    logger.warning(
        "GeoTIFF listing parsed to zero %s.%d files -- falling back to calendar enumeration",
        variable, year,
    )
    return _enumerate_dates_up_to_today(year), False


def _enumerate_dates_up_to_today(year: int) -> list[str]:
    """Every day of ``year`` up to the newest day CPC can be EXPECTED to have published.

    Only reached when the live index is unreadable.  The cutoff carries the measured
    ``_PUBLICATION_LAG_DAYS``, not the one-day lag this helper assumed before 2026-09-11.
    """
    cutoff = date.today() - timedelta(days=_PUBLICATION_LAG_DAYS)
    dates: list[str] = []
    d = date(year, 1, 1)
    while d.year == year and d <= cutoff:
        dates.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    return dates


def _list_present_raw_days(bucket: str, aws_region: str, variable: str, year: int) -> set[str]:
    """ONE paginated LIST of the raw year prefix -> the ``{YYYYMMDD}`` already in S3.

    Replaces the per-day ``head_object`` probes the trailing-hole check used to make (about sixty a
    run) and hands the daily path its skip set up front, so a run fetches only the days CPC has
    published that raw does not already hold.
    """
    # ``date=`` is a day-grain segment; the year prefix is that segment truncated.  Derive it from
    # the path builder so the raw layout keeps exactly one definition.
    prefix = raw_cpc_tif_key(variable, str(year), "").rstrip("/")
    days: set[str] = set()
    for key in list_s3_keys(bucket, prefix, suffix=".tif", aws_region=aws_region):
        for part in key.split("/"):
            if part.startswith("date="):
                stem = part[len("date="):]
                try:
                    datetime.strptime(stem, "%Y%m%d")
                except ValueError:
                    break
                days.add(stem)
                break
    logger.info("Raw already holds %d day-keys for variable=%s year=%d", len(days), variable, year)
    return days


def _process_year_via_daily_files(
    year: int,
    variable: str,
    bucket: str,
    aws_region: str,
    ingest_date: str,
    force_overwrite: bool,
    published_days: list[str],
    present_days: set[str],
) -> tuple[int, int]:
    """Download individual daily TIFs for the current year.  Returns (written, skipped).

    BOUNDED (2026-09-11): the window is the days CPC has PUBLISHED minus the days raw already
    holds — in the steady state exactly the days after the last ingested one, and never a day
    beyond the listing.  Interior gaps stay in the window on purpose: a strict high-water mark
    would reopen the partial-month permanence trap that 0b16421b was written to close, and
    re-attempting a listed day costs one GET of ~875KB.  ``--force_overwrite true`` re-fetches
    every published day.

    A day that fails to download is a per-day DECLINE, never a leg failure — the leg's job is to
    carry forward every day it can reach, and the trailing-hole report below is what makes an
    unreachable day visible.  The ONE exception is a TOTAL outage: when every day of a window at
    least ``_OUTAGE_MIN_WINDOW_DAYS`` wide declined, nothing was reached at all and the leg raises
    ``DailyWindowOutage`` so the exit code -- the only instrument that fires here -- is nonzero.  A
    partial outage stays green and visible: the days that came through are written, the ones that
    did not are declined and surface in the hole report.  A ONE-day window that wholly declined is
    the steady state failing once, and is a stated WARNING rather than red -- see the floor's
    reasoning on ``_OUTAGE_MIN_WINDOW_DAYS`` and ``DailyWindowOutage``.
    """
    published = sorted(set(published_days))
    targets = published if force_overwrite else [d for d in published if d not in present_days]
    already = len(published) - len(targets)

    # The printed triple ADDS UP: published = already_raw + to_fetch, always. ``already_raw`` is the
    # count this window actually treats as satisfied, not ``len(present_days)`` -- the two disagree
    # whenever raw holds a day the listing does not (and under --force_overwrite, which satisfies
    # nothing), so the raw day-key count rides alongside as its own figure instead of being
    # substituted for one it is not.
    logger.info(
        "Daily window  variable=%s year=%d  published=%d already_raw=%d to_fetch=%d"
        "  raw_day_keys=%d%s",
        variable, year, len(published), already, len(targets), len(present_days),
        f"  publication tip={published[-1]}" if published else "",
    )
    if not targets:
        logger.info(
            "Nothing to fetch: raw already holds every published day for %s %d "
            "(later calendar days are not yet published -- deferring)", variable, year,
        )
        return 0, already

    access_timestamp = datetime.now(timezone.utc).isoformat()
    written = declined = present = 0

    def _fetch_and_upload(date_str: str) -> str:
        """``"written"`` | ``"declined"`` (unreachable) | ``"present"`` (S3 already had it).

        The three are kept apart on purpose: only ``declined`` means the SOURCE could not be
        reached, and the outage test below must not be tripped by a day S3 turned out to hold.
        """
        source_url = f"{CPC_FTP_BASE}/GeoTIFF/{variable}.{date_str}.tif"
        try:
            tif_bytes = download_cpc_daily_tif(date_str, variable)
        except Exception as exc:  # noqa: BLE001 — ONE day's failure is a decline, not a leg failure
            logger.warning("Failed to download %s %s: %s -- declining this day", variable, date_str, exc)
            return "declined"
        s3_client = get_thread_local_s3_client(aws_region)
        wrote = _put_tif(
            s3_client, bucket, variable, date_str, tif_bytes,
            source_url, access_timestamp, force_overwrite,
        )
        return "written" if wrote else "present"

    with ThreadPoolExecutor(max_workers=5) as pool:  # cap to avoid hammering NOAA FTP
        futures = {pool.submit(_fetch_and_upload, ds): ds for ds in targets}
        for future in as_completed(futures):
            status = future.result()
            if status == "written":
                written += 1
            elif status == "present":
                present += 1
            else:
                declined += 1

    logger.info(
        "Daily ingest complete  variable=%s year=%d  written=%d declined=%d already_raw=%d",
        variable, year, written, declined + present, already,
    )

    if targets and declined == len(targets):
        # TOTAL DECLINE. Not one day of a window we believed non-empty could be reached. The WINDOW
        # is what decides whether that is an outage or a late day, so it is measured, never assumed.
        if len(targets) >= _OUTAGE_MIN_WINDOW_DAYS:
            # OUTAGE. Raised, not warned: the exit code is the only instrument on this leg, and
            # "SUCCEEDED, written=0" on a vanished source directory is the failure mode this repair
            # exists to close.
            raise DailyWindowOutage(
                f"fetched NOTHING from a non-empty window: variable={variable} year={year} "
                f"to_fetch={len(targets)} declined={declined} "
                f"first={targets[0]} last={targets[-1]} -- every day of the window was unreachable, "
                f"which is a source outage, not a per-day decline "
                f"(window {len(targets)} days >= the {_OUTAGE_MIN_WINDOW_DAYS}-day outage floor)"
            )
        # ONE DAY, AND ONLY ONE. This is the steady-state window: the single day CPC published since
        # the last run. Reddening the whole leg on one 875KB GET made the exit code a coin flip on
        # any transient, so it is a stated WARNING -- and two things make that safe rather than a
        # softening. A source that has actually STOPPED is now caught against the CALENDAR by the
        # PUBLISHER STALL alarm, which needs no fetch window at all. And a break that survives into
        # the next run makes the window two days wide, which is the floor above: this decline is
        # loud today and red tomorrow.
        logger.warning(
            "SINGLE-DAY DECLINE %s %s: the only day in this window could not be reached "
            "(window=1 day, below the %d-day outage floor) -- WARNING not RED: a source that has "
            "stopped is caught by the PUBLISHER STALL line against the calendar, and a break that "
            "lasts into the next run widens this window past the floor",
            variable, targets[0], _OUTAGE_MIN_WINDOW_DAYS,
        )

    return written, declined + present + already


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _inspected_months(today: date) -> list[tuple[int, int]]:
    """The ``(year, month)`` pairs the hole report inspects — ONE definition, two consumers.

    The current month and the previous one, PLUS the previous calendar December all year round.

    THE YEAR-BOUNDARY DAYS.  CPC publishes day D at about 17:53Z on D+1, so Dec 30 lands on Dec 31
    and Dec 31 lands on Jan 1 — both AFTER the last 08:00Z fire that asks for that year (the Dec 31
    fire sees a tip of Dec 29, and from Jan 1 the default year is the new one while
    ``_parse_daily_listing`` filters on the new year's prefix).  Neither day ever reaches the daily
    path.  In this estate that is measured, not hypothetical: raw ``date=20251230`` and
    ``date=20251231`` exist but carry LastModified 2026-05-24 — five months late, and by an
    operator's hand ``--year 2025``, never by the scheduled leg.

    Before 2026-09-11 this helper looked only one month back, so from February 1 a December hole
    stopped being reported at all — months before the annual archive that could heal it is even
    published.  Keeping December in view ALL YEAR costs one extra raw LIST per run and is the only
    thing that makes the loss visible for the whole span in which it can still be repaired.  The
    remedy is seasonal (``_ARCHIVE_SELF_HEAL_THROUGH_MONTH``); the REPORT is not.

    ``year`` is the calendar year each month belongs to, so the caller knows which raw year
    prefixes it must LIST before counting — the same "one fact per run, derived once" shape the
    published set already has.
    """
    months = [(today.year, today.month)]
    months.append((today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12))
    prev_december = (today.year - 1, 12)
    if prev_december not in months:
        months.append(prev_december)
    return months


def _trailing_month_holes(
    present_days: set[str],
    published_days: set[str] | None,
    today: date | None = None,
) -> dict[str, tuple[int, int, str]]:
    """PARTIAL-MONTH PERMANENCE FIX (2026-08-22), CORRECTED 2026-09-11.

    ``{YYYY-MM: (present, expected, basis)}`` for the months ``_inspected_months`` names — the
    current and previous calendar months, plus the previous December all year — counting the raw
    day-keys already in S3 against what CPC has actually PUBLISHED.  ``basis`` names the yardstick
    that produced ``expected`` (``_BASIS_PUBLISHED`` | ``_BASIS_CALENDAR_LAGGED`` |
    ``_BASIS_CALENDAR_FULL``) so the report can PRINT which one it used instead of asserting one.

    What changed and why.  The 2026-08-22 version expected ``today.day - 1`` days of the current
    month — a one-day publication lag.  The real lag at the 08:00Z fire is TWO days
    (``_PUBLICATION_LAG_DAYS``), so every single run manufactured a phantom one-day hole and then
    tried to heal it from ``clim/w.<current year>.tif.tar.gz``, which does not exist: HTTP 404,
    tenacity exhausted, exit 1, on every run since about 2026-08-28.

    So the expectation is the PUBLISHED set, not the calendar: a day CPC has not yet published is a
    stated decline, never a hole.  ``published_days is None`` means the live index could not be
    read, and the calendar count stands in carrying the measured lag.  A month the listing does not
    cover at all — the January run looking back at the previous December — also uses the calendar:
    that month IS closed, its annual tarball DOES exist, and the calendar is the honest expectation
    for it.  That fallback is also what keeps this instrument loud if the directory ever does start
    rolling days off within the year.

    The count the calendar and the publisher disagree on is not dropped, only moved: it is reported
    on its own line by ``_upstream_short_months``.

    Pure — no S3, no network.  Both sets are gathered once by the caller, which is also what turned
    about sixty per-day ``head_object`` probes into one LIST.
    """
    today = today or date.today()
    out: dict[str, tuple[int, int, str]] = {}
    for (y, m) in _inspected_months(today):
        stem = f"{y}{m:02d}"
        is_current = (y, m) == (today.year, today.month)
        present = sum(1 for d in present_days if d.startswith(stem))
        if published_days is None:
            # No publisher statement at all this run: the calendar stands in, and for the CURRENT
            # month it carries the measured lag.
            expected, basis = (
                (max(0, today.day - _PUBLICATION_LAG_DAYS), _BASIS_CALENDAR_LAGGED) if is_current
                else (calendar.monthrange(y, m)[1], _BASIS_CALENDAR_FULL)
            )
        else:
            month_published = sum(1 for d in published_days if d.startswith(stem))
            expected, basis = (
                (month_published, _BASIS_PUBLISHED) if (month_published or is_current)
                else (calendar.monthrange(y, m)[1], _BASIS_CALENDAR_FULL)
            )
        # THE BASIS RIDES WITH THE FIGURE (review round 2). The hole line used to assert
        # "expected = days CPC has PUBLISHED, not calendar days" unconditionally -- a sentence that
        # is FALSE on both calendar branches above, and most misleading in the blind case, which is
        # exactly when an operator is reading the line hardest. Which yardstick produced the
        # expectation is a computed fact per month, so it is computed here, once, beside it.
        out[f"{y}-{m:02d}"] = (present, expected, basis)
    return out


def _upstream_short_months(
    published_days: set[str] | None,
    today: date | None = None,
) -> dict[str, tuple[int, int]]:
    """``{YYYY-MM: (published, calendar_days)}`` for any settled month the PUBLISHER is short on.

    ``_trailing_month_holes`` now counts raw against what CPC published, so an upstream gap can no
    longer masquerade as one of ours — but it must not vanish either (fences CORRECT or COMPUTE,
    never delete).  This is the calendar fact, kept on its own line.  A month whose tail is still
    inside the publication lag is skipped: it is short by construction, not by defect.  Measured
    2026-09-11 the index carried every day of 2026 from Jan 1 to Sep 9 with no interior gap, so
    this reports nothing today.
    """
    if not published_days:
        return {}
    today = today or date.today()
    settled_before = today - timedelta(days=_PUBLICATION_LAG_DAYS)
    out: dict[str, tuple[int, int]] = {}
    for stem in sorted({d[:6] for d in published_days}):
        y, m = int(stem[:4]), int(stem[4:6])
        days_in_month = calendar.monthrange(y, m)[1]
        if date(y, m, days_in_month) > settled_before:
            continue
        published = sum(1 for d in published_days if d.startswith(stem))
        if published < days_in_month:
            out[f"{y}-{m:02d}"] = (published, days_in_month)
    return out


def _publisher_stall(
    published_days: set[str] | None,
    today: date | None = None,
) -> tuple[str, int, str] | None:
    """``(newest_published, days_behind, level)`` -- IS CPC STILL PUBLISHING?  ``None`` when blind.

    THE ONE INSTRUMENT THAT LOOKS AT THE CALENDAR ON PURPOSE.  Every other fence on this leg now
    measures raw against CPC's published SET, which is what killed the phantom hole -- and which,
    alone, cannot see the source stop.  Freeze the index at tip ``20260909`` with raw complete to
    it and the shipped code says nothing on 2026-09-12, nothing on 2026-09-20, and reaches its
    first WARNING only on 2026-10-05 when ``_upstream_short_months`` finally considers September
    settled.  This function is the answer: the published TIP against the calendar.

    ``days_behind = (today - _PUBLICATION_LAG_DAYS) - newest_published``.  Zero is the steady state
    (CPC exactly at its measured lag).  A NEGATIVE value is possible and is kept, not clamped: it
    means CPC published faster than the measured lag, which is the honest reading and the signal
    that would justify re-measuring ``_PUBLICATION_LAG_DAYS`` downward.

    ``level`` is ``"quiet"`` | ``"warning"`` | ``"red"`` against the two named thresholds, compared
    with ``>=``.  ``None`` -- no published set, or an empty one -- is a BLIND run, not a quiet one:
    the caller must say so out loud, the same way ``_upstream_short_months`` does, because silence
    from an instrument with nothing to measure reads exactly like silence from a healthy one.

    Pure -- no S3, no network, no ``date.today()`` unless the caller declines to state it.
    """
    if not published_days:
        return None
    today = today or date.today()
    # THE TIP IS CAPPED AT TODAY (review 2026-09-11, the one-entry off switch): ``max(published_days)``
    # with no cap let ONE future-dated entry -- a listing anomaly, or a container clock running early --
    # read as a tip months ahead, so ``days_behind`` went negative for the rest of the year and the
    # alarm the round was built to close reopened.  A day CPC cannot have published yet is discarded
    # here and NAMED by ``_future_dated`` (the caller prints it as a WARNING); a set the cap empties
    # is BLIND, not quiet.  A tip one day ahead of the measured lag is still kept negative (see below).
    cutoff = today.strftime("%Y%m%d")
    usable = {d for d in published_days if d <= cutoff}
    if not usable:
        return None
    newest = max(usable)
    newest_date = datetime.strptime(newest, "%Y%m%d").date()
    days_behind = ((today - timedelta(days=_PUBLICATION_LAG_DAYS)) - newest_date).days
    if days_behind >= _PUBLISHER_STALL_RED_DAYS:
        level = "red"
    elif days_behind >= _PUBLISHER_STALL_WARN_DAYS:
        level = "warning"
    else:
        level = "quiet"
    return newest, days_behind, level


def _future_dated(published_days: set[str] | None, today: date | None = None) -> list[str]:
    """The listed days CPC cannot have published yet -- every ``YYYYMMDD`` after ``today``.

    Pure.  ``_publisher_stall`` discards these when it picks the tip; this names them so the caller can
    say so out loud (a source listing tomorrow, or a container clock running early, is a fact worth a
    WARNING line, never a silent drop).  Empty list when there is nothing to name.
    """
    if not published_days:
        return []
    today = today or date.today()
    cutoff = today.strftime("%Y%m%d")
    return sorted(d for d in published_days if d > cutoff)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(description="CPC Soil Moisture -> raw S3 (Batch task)")
    # A-Wave-3 thin-contract: every arg optional. --year self-windows to the current calendar year
    # (its daily-files path is incremental + skip-existing, so a scheduled run self-heals within-year
    # gaps); an explicit --year keeps the backfill (annual tarball for a prior year) unchanged.
    parser.add_argument("--year",           type=int, default=None,
                        help="calendar year (default: current year)")
    parser.add_argument("--bucket",         default=None, help="S3 bucket (default: $LEVIATHAN_BUCKET)")
    parser.add_argument("--aws_region",     default=None, help="AWS region (default: $AWS_REGION)")
    parser.add_argument("--variable",       default="w", help="CPC variable prefix (default: w)")
    parser.add_argument("--ingest_date",    default=date.today().isoformat())
    parser.add_argument("--force_overwrite", default="false")
    args = parser.parse_args()

    load_env()
    force_overwrite = args.force_overwrite.lower() == "true"
    current_year = date.today().year
    year = args.year if args.year is not None else current_year
    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    logger.info(
        "CPC soil moisture → raw  variable=%s  year=%d  force_overwrite=%s",
        args.variable, year, force_overwrite,
    )

    outage: DailyWindowOutage | None = None     # only the daily path can raise one
    stall: PublisherStall | None = None         # ditto -- a closed year has no live tip to measure
    if year < current_year:
        written, skipped = _process_year_via_tarball(
            year=year,
            variable=args.variable,
            bucket=bucket,
            aws_region=aws_region,
            ingest_date=args.ingest_date,
            force_overwrite=force_overwrite,
        )
    else:
        # The live index is read ONCE and handed to both the fetch window and the hole report, so
        # "what CPC has published" is one fact this run, not two independently derived guesses.
        published_list, listing_verified = _list_available_daily_dates(year, args.variable)
        published_days = set(published_list) if listing_verified else None
        present_days = _list_present_raw_days(bucket, aws_region, args.variable, year)

        # A TOTAL outage still gets its instruments read before it fails. The hole report is the
        # only visible statement of WHAT is missing, and an outage run is the one where that
        # matters most -- so the exception is caught, everything below is reported, and the leg
        # fails at the end with the outage intact.
        try:
            written, skipped = _process_year_via_daily_files(
                year=year,
                variable=args.variable,
                bucket=bucket,
                aws_region=aws_region,
                ingest_date=args.ingest_date,
                force_overwrite=force_overwrite,
                published_days=published_list,
                present_days=present_days,
            )
        except DailyWindowOutage as exc:
            logger.error("DAILY WINDOW OUTAGE: %s", exc)
            outage = exc
            written = skipped = 0

        # PARTIAL-MONTH PERMANENCE FIX (2026-08-22), corrected 2026-09-11. Re-LIST raw after the
        # writes (S3 LIST is strongly consistent) so the report counts what this run just put
        # there, and LIST every OTHER year the report inspects -- the previous December, which the
        # daily path can never reach. The hole line stays loud: it is the only visible instrument
        # on this leg, and the exit code is the only one that alarms.
        today = date.today()
        present_days = _list_present_raw_days(bucket, aws_region, args.variable, year)
        for other_year in sorted({y for (y, _m) in _inspected_months(today)} - {year}):
            present_days |= _list_present_raw_days(bucket, aws_region, args.variable, other_year)

        holes = _trailing_month_holes(present_days, published_days, today=today)
        for ym, (present, expected, basis) in holes.items():
            if present < expected:
                # THE BASIS IS PRINTED, NEVER ASSERTED (review round 2). This line used to end with
                # "expected = days CPC has PUBLISHED, not calendar days" whatever had actually been
                # counted -- so on a blind run it told the operator the opposite of the truth.
                logger.warning(
                    "TRAILING-MONTH HOLE %s: %d/%d raw days present (expected basis = %s)",
                    ym, present, expected, _BASIS_PHRASE[basis],
                )
        for ym, (published, cal_days) in _upstream_short_months(published_days, today=today).items():
            logger.warning(
                "UPSTREAM SHORT %s: CPC has published %d of %d calendar days -- not a raw hole",
                ym, published, cal_days,
            )

        # THE PUBLISHER-STALL ALARM. Every fence above measures raw against what CPC published, so
        # none of them can see CPC STOP. This one measures the published TIP against the calendar.
        future = _future_dated(published_days, today=today)
        if future:
            logger.warning(
                "PUBLISHER TIP DISCARDED: the index lists %d day(s) CPC cannot have published yet "
                "(%s) -- ignored by the stall alarm; check the source listing and the container clock",
                len(future), ", ".join(future[:5]) + (" ..." if len(future) > 5 else ""),
            )
        measured = _publisher_stall(published_days, today=today)
        if measured is None:
            logger.warning(
                "PUBLISHER STALL BLIND: no publisher tip to measure this run, so the calendar-side "
                "stall alarm declines -- it cannot tell a stopped source from an unreadable index, "
                "and will not call either one quiet"
            )
        else:
            newest, days_behind, level = measured
            reason = (
                f"UPSTREAM STALL: newest published {args.variable}.{newest} is {days_behind} days "
                f"behind the lag (measured publication lag {_PUBLICATION_LAG_DAYS} days; "
                f"warn at {_PUBLISHER_STALL_WARN_DAYS}, red at {_PUBLISHER_STALL_RED_DAYS})"
            )
            if level == "red":
                logger.error("%s -- RED, the leg exits nonzero", reason)
                stall = PublisherStall(reason)
            elif level == "warning":
                logger.warning("%s -- WARNING", reason)
            else:
                logger.info(
                    "Publisher tip %s.%s is %d days behind the measured %d-day lag -- within the "
                    "%d-day warn threshold",
                    args.variable, newest, days_behind, _PUBLICATION_LAG_DAYS,
                    _PUBLISHER_STALL_WARN_DAYS,
                )

        if published_days is None:
            # The publisher-shortfall fence measures raw against CPC's OWN statement of what it
            # published, and this run has no such statement. Silence there would be worst exactly
            # when an upstream problem is likeliest, so the fence declines out loud instead of
            # returning an empty dict that reads like "nothing is short".
            logger.warning(
                "UPSTREAM SHORT BLIND: the live GeoTIFF index could not be read this run, so there "
                "is no publisher statement to measure against -- the TRAILING-MONTH HOLE line(s) "
                "above stand on the calendar and the measured %d-day publication lag instead",
                _PUBLICATION_LAG_DAYS,
            )

        hole_years = sorted({int(ym.split("-")[0]) for ym, (p, e, _b) in holes.items() if p < e})
        if hole_years and outage is not None:
            # An opportunistic remedy against a source this run has already PROVEN unreachable is
            # pure waste, and a second failure here would bury the outage under a different error.
            logger.warning(
                "SELF-HEAL DECLINED for %s: the source was unreachable this run (see DAILY WINDOW "
                "OUTAGE above); the hole(s) stand as reported and the leg exits nonzero",
                ", ".join(str(hy) for hy in hole_years),
            )
            hole_years = []
        for hy in hole_years:                       # a December hole needs YEAR-1's tarball
            if hy >= current_year:
                # ``clim/`` carries CLOSED years ONLY -- measured 2026-09-11: w.2000..w.2025 plus
                # w.40ym, with HEAD clim/w.2026.tif.tar.gz = 404 while clim/w.2025.tif.tar.gz =
                # 200. There is no current-year tarball to fall back TO, and the 2026-08-22 claim
                # that the daily path cannot self-heal was wrong: the GeoTIFF directory is NOT a
                # rolling window within the calendar year (all 252 days of 2026 were still listed
                # on 09-11), so the daily path above already re-attempted every listed day this
                # run. Reaching for the tarball here is what failed the whole leg, daily, for a
                # hole that does not exist.
                logger.warning(
                    "CURRENT-YEAR HOLE %d: no annual tarball exists for an open year -- "
                    "the daily GeoTIFF path is the remedy and already re-attempted every listed day",
                    hy,
                )
                continue
            if today.month > _ARCHIVE_SELF_HEAL_THROUGH_MONTH:
                # OUT OF SEASON. The archive that could heal a previous-December hole publishes
                # around March (measured: clim/w.2025.tif.tar.gz, Last-Modified 2026-03-03), so by
                # April either the self-heal already worked or the archive itself is short. Retrying
                # an 86MB download every day for the rest of the year would buy nothing; the hole
                # stays REPORTED above, and the remedy is named so an operator can run it.
                logger.warning(
                    "YEAR-BOUNDARY HOLE %d STANDS: the opportunistic annual-archive self-heal runs "
                    "only through month %d (a year closing does not publish its archive -- 2025's "
                    "appeared 2026-03-03), so this is now an OPERATOR backfill: run this leg with "
                    "--year %d",
                    hy, _ARCHIVE_SELF_HEAL_THROUGH_MONTH, hy,
                )
                continue
            try:
                tw, ts = _process_year_via_tarball(
                    year=hy, variable=args.variable, bucket=bucket, aws_region=aws_region,
                    ingest_date=args.ingest_date, force_overwrite=False,
                )
            except requests.HTTPError as exc:
                # THE JANUARY EDGE. A year CLOSING does not make its tarball exist: measured
                # 2026-09-11, clim/w.2025.tif.tar.gz carries Last-Modified "Tue, 03 Mar 2026
                # 23:03:20 GMT" -- about two months after 2025 ended. So from January until
                # roughly March a previous-December hole finds no archive, and the pre-2026-09-11
                # shape would have failed the whole leg on exactly the 404 that broke September,
                # three months later. An OPPORTUNISTIC self-heal must decline and leave the hole
                # reported; only the EXPLICIT --year backfill above may die on a missing archive,
                # because there the operator asked for that year and must not be told it worked.
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status is not None and 400 <= status < 500:
                    logger.warning(
                        "TARBALL NOT PUBLISHED for %d (HTTP %s) -- declining the self-heal; "
                        "the %d hole stands as reported above", hy, status, hy,
                    )
                    continue
                raise
            written += tw
            skipped += ts

    logger.info("Done  written=%d  skipped=%d", written, skipped)

    if outage is not None:
        # Every instrument has now been read. THE EXIT CODE IS THE ALARM -- re-raise so Batch marks
        # the job FAILED rather than SUCCEEDED-with-a-warning. The OUTAGE goes first when both are
        # standing: "we reached nothing" is what this run did, and the stall it would also report
        # is already on its own ERROR line above, so nothing is lost by ordering them.
        raise outage
    if stall is not None:
        # A run can be PERFECT and still red here: raw holds every published day, nothing declined,
        # written=0 -- and the source has not moved in a week. That is the case the published-set
        # expectation made invisible, and the exit code is the only instrument that can say it.
        raise stall


if __name__ == "__main__":
    main()
