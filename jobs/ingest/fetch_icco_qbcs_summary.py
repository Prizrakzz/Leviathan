"""Fetch ICCO Quarterly Bulletin of Cocoa Statistics (QBCS) free HTML summary pages
and the annual EWG cocoa bean stocks report to raw S3.

Each quarterly ICCO bulletin release has a free news page on icco.org containing a
structured HTML summary table with world-level cocoa production, grindings,
surplus/deficit, end-of-season stocks, and stocks-to-grindings ratio.  These are the
only publicly available numbers from the QBCS (the full bulletin requires a paid
subscription).

The annual Expert Working Group (EWG) stocks report is published in January each year
and provides a regional breakdown of cocoa bean stocks (importing countries, exporting
countries, SE Asia, manufacturers, in-transit).

Sources
-------
    QBCS:  https://www.icco.org/{month}-{year}-quarterly-bulletin-of-cocoa-statistics/
    EWG:   https://www.icco.org/world-cocoa-bean-stocks-for-the-{YYYY-YY}-season/

Coverage
--------
    QBCS:  February 2008 → present  (~73 releases, 4×/year: Feb / May / Aug / Nov)
    EWG:   2013/14 season → present  (~13 releases, 1×/year)

S3 key structure
----------------
    QBCS:  raw/production/source=icco_qbcs_summary/release_date={YYYY-MM-DD}/
               icco_qbcs_summary_{YYYYMMDD}.json
               page.html                  the page that MINTED that record, and only ever that
               page_parse_failure.html    a body that yielded no record, kept for the replay
    EWG:   raw/production/source=icco_ewg_stocks/season={YYYY-YY}/
               icco_ewg_stocks_{YYYY-YY}.json
               page.html

Idempotency
-----------
Pass ``--skip-existing-s3`` to skip pages already in S3.
Pass ``--dry-run`` to print S3 keys without fetching or uploading anything.

Exit contract (P10, 2026-09-22)
-------------------------------
A release the fetcher believes EXISTS (HTTP 200) that yields no record is a FAILURE, not a
warning.  Before this contract ``_parse_qbcs_table`` returning ``None`` logged a WARNING, uploaded
``page.html`` anyway and returned ``"parse_error"``, which the tail never counted -- so the
2025-08-31 and 2026-08-31 QBCS bulletins landed as HTML-only orphans under a SUCCEEDED fire and a
PASSING gate, and ``silver_icco_cocoa`` (the estate's only cocoa balance sheet) sat a full quarter
behind while every instrument read healthy.

Three rules now hold:

* ``parse_error`` and a non-200/non-404 response are TERMINAL for a GATED leg (QBCS, which feeds
  ``silver_icco_cocoa``) when the estate does not already hold a record for that release.  A
  release the estate HAS banked that fails on a re-fetch is counted and named, never fatal -- an
  archive page from 2013 may not kill the fire that owes the current quarter (the same partition
  ``fetch_mpoc.py`` applies by release_type).
* The EWG annual stocks leg is UNGATED: no SERVED TABLE reads ``raw/production/source=icco_ewg_stocks/``
  (``silver_icco_cocoa`` is built from QBCS).  The TEXT/EVIDENCE layer DOES read it --
  ``jobs/utils/run_text_extraction_track_b.py`` lists the prefix in ``ICCO_SOURCES`` and queues every
  ``.html`` under it, ``src/leviathan/graphrag/evidence.py`` routes cocoa at ``icco_ewg_stocks`` and
  ``corpus_ingest_task`` treats ``.html`` as document-shaped -- which is exactly why a parse failure
  lands under its OWN ``page_parse_failure.html`` on BOTH prefixes and never on the page that minted a
  banked record (the closing review's X-1).  Its failures are counted, named in the summary and
  emitted as a metric, never an exit code.  ``season=2022-23`` is an HTML-only orphan today (a
  per-LOCATION table shape ``_parse_ewg_table`` does not know); flipping EWG to gated needs that
  layout taught FIRST, which is why the leg is declared here rather than assumed.
* Every ``page.html`` THIS RUN lands must have its sibling JSON in S3 at the end of the run --
  unless the estate already HOLDS that release's JSON, in which case the page is a re-read of a
  banked record and not an orphan at all.

The HTML is still uploaded on a parse failure -- the fence CORRECTS the exit code and keeps the
evidence; it never deletes the page that makes the replay possible.

What round 2 corrected (2026-09-22)
-----------------------------------
Both halves of that partition were INERT as first written, and the adversarial review measured it:

* ``banked`` was computed BEFORE the fetch from a TENTATIVE last-day-of-month key, while the
  record actually lands on the key recomputed from the page's own dateline.  Measured against the
  48 summary records the estate really holds, the tentative key finds 26 and a release-window
  lookup over the landed keys finds all 48 -- so ``banked`` read FALSE on 22 of 48 releases
  (2013-05-29, 2013-08-30, 2026-02-27, 2026-05-29 ...), including the 2013 May page the report
  used as its worked example and both of the two most recent quarters.  ``banked`` is now read off
  the keys the estate REALLY holds (:func:`banked_summary_key` over one listing of the prefix),
  and refined to the exact dateline key once the dateline is known.
* the orphan fence defeated the exemption anyway: a parse failure always uploads ``page.html`` and
  leaves ``json_key`` None, so a BANKED gated parse_error was exempt from ``terminal_failures``
  and then raised ``SystemExit`` from ``orphan_pages`` instead.  The fence now reads the BANKED
  key, and a release already banked is not an orphan.  A page with no banked JSON and a failed
  parse is still terminal -- and is named ONCE, not twice.

What round 3 corrected (2026-09-22)
-----------------------------------
* A PARSE FAILURE NO LONGER OVERWRITES THE PAGE THAT MINTED THE RECORD.  Round 2 moved the failure
  page to ``<banked folder>/page.html`` so it would sit beside the record instead of minting an
  orphan folder -- and that is the very key the successful run wrote.  The bucket's versioning
  reads ``Suspended`` (re-measured 2026-09-22), so one re-fetch of a re-laid-out 2013 archive page
  would have destroyed the 138,448-byte page that produced
  ``release_date=2013-05-29/icco_qbcs_summary_20130529.json``, unrecoverably.  An unparseable body
  now lands under its own name (:data:`_PARSE_FAILURE_PAGE`), which also makes ``page.html``
  inside a ``release_date=`` folder mean exactly one thing: the page that minted that record.
  THE SAME RULE BINDS BOTH LEGS.  The first cut applied it to the gated leg only, and left the
  identical unrecoverable delete standing one function away in ``_process_ewg``, where it is
  strictly worse: the EWG key carries no dateline, so the failure key IS the success key on every
  season, and ``configs/silver/dags/icco_cocoa.json`` sets ``skip_existing: false``, so all 13
  seasons walk that path on every monthly fire.  Four of the five live ``season=`` folders hold a
  record JSON beside its minting page.  ``page.html`` under
  ``raw/production/source=icco_ewg_stocks/season=<s>/`` now means the page that minted that
  season's record, exactly as it does under ``release_date=``, and the deck walks BOTH legs.
* THE GATED LEG GOT THE RETRY THE OTHER PRODUCER ALREADY HAD.  ``_fetch_page`` had ONE attempt and
  no backoff in the same commit that gave ``fetch_mpoc.py`` four attempts and a Retry-After
  honour, so the terminal surface this lane deliberately narrowed to -- the UNBANKED current
  quarter -- was one transient away from a family red with nothing behind it.  It now retries 429
  and 503 with Retry-After / exponential backoff, and still never retries a 404, which is the
  normal answer for a quarter that was never published.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, NamedTuple

import requests
from bs4 import BeautifulSoup

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_icco_ewg_stocks_key, raw_icco_qbcs_summary_key
from leviathan.storage.raw_metadata import write_raw_s3_metadata
from leviathan.storage.s3 import list_s3_keys, s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://www.icco.org"
_REQUEST_TIMEOUT_S = 15

# Retry policy for the GATED leg.  Statuses that mean "slow down", not "gone" -- a 404 is the
# NORMAL answer for a quarter that was never published (27 of the enumerated bulletins 404 on a
# healthy fire) and is never retried.
#
# STILL 429/503 ONLY, AND THAT IS A KNOWN, MEASURED GAP, NOT AN ARGUMENT (PART 3 item 9).
# icco.org sits behind a CDN whose transient reads 502 or 504 at least as often as 503, so one
# edge blip on the UNBANKED current quarter -- the single surface this lane narrowed the exit
# contract down to -- is still terminal with nothing behind it.  The fix is this tuple, widened to
# (429, 500, 502, 503, 504).  It is NOT applied here because widening it to five members takes the
# constant over the f091 raw-literal census's MIN_CARDINALITY floor: measured this sitting, the
# census moves 359 -> 360 raw literals (this file 5 -> 6; files stay 134), and PIN_RAW_LITERALS
# lives in tests/unit/silver/test_f091_source_universe_lint.py, outside this lane's allowlist.
# A census pin and the population it counts move in the SAME change or not at all.
_RETRY_STATUS = (429, 503)
_DEFAULT_MAX_ATTEMPTS = 4
_BACKOFF_BASE_S = 2.0
_BACKOFF_CAP_S = 60.0

# The estate's one custom-metric namespace; the batch job role already carries PutMetricData scoped
# to it by the freshness-put-metric inline policy, so this needs no new IAM.
METRIC_NAMESPACE = "Leviathan/Silver"
INGEST_LEG_FAILURE_METRIC = "IngestLegFailures"

# Months in which QBCS issues are published.
_QBCS_MONTHS = ("february", "may", "august", "november")

# QBCS month → approximate day of publication (used as fallback when the page
# intro text does not contain a parseable date).
_QBCS_FALLBACK_DAY = {"february": 28, "may": 31, "august": 31, "november": 30}

# Map month name → month number (for date construction).
_MONTH_NAME_TO_NUM: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

# Earliest QBCS bulletin confirmed on the live ICCO website.
_QBCS_START_YEAR = 2008
# EWG stocks reports confirmed on the live ICCO website from 2013/14 onwards.
_EWG_START_SEASON_YEAR = 2013  # cocoa year starting Oct 2013

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# ---------------------------------------------------------------------------
# URL enumeration
# ---------------------------------------------------------------------------


def _qbcs_urls(from_year: int, to_date: date) -> list[dict[str, str]]:
    """Enumerate all expected QBCS bulletin page URLs from *from_year* to *to_date*.

    Returns a list of dicts: {"url": ..., "month": ..., "year": ..., "type": "qbcs"}
    """
    entries = []
    for year in range(from_year, to_date.year + 1):
        for month in _QBCS_MONTHS:
            month_num = _MONTH_NAME_TO_NUM[month]
            # Skip future months (a May 2026 issue won't exist before ~May 2026).
            if year == to_date.year and month_num > to_date.month:
                continue
            url = f"{_BASE_URL}/{month}-{year}-quarterly-bulletin-of-cocoa-statistics/"
            entries.append({"url": url, "month": month, "year": str(year), "type": "qbcs"})
    return entries


def _ewg_urls(start_season_year: int, to_date: date) -> list[dict[str, str]]:
    """Enumerate expected EWG stocks report page URLs.

    The EWG report covers the cocoa year starting in October.  It is published
    in January of the following calendar year, e.g. the 2024/25 report is
    published in January 2026.

    Returns a list of dicts: {"url": ..., "season": ..., "type": "ewg"}
    """
    entries = []
    # season_year is the Oct start year, published in Jan(season_year+1).
    for season_year in range(start_season_year, to_date.year):
        next_year_2d = str(season_year + 1)[-2:]
        season = f"{season_year}-{next_year_2d}"
        url = f"{_BASE_URL}/world-cocoa-bean-stocks-for-the-{season}-season/"
        entries.append({"url": url, "season": season, "type": "ewg"})
    return entries


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def _retry_after_seconds(resp: "requests.Response", attempt: int,
                         base: float = _BACKOFF_BASE_S, cap: float = _BACKOFF_CAP_S) -> float:
    """Seconds to wait before the next attempt: Retry-After when the host states one, else 2**n.

    ``Retry-After`` is either a decimal count of seconds or an HTTP-date; both are honoured, and
    both are capped so a hostile or mis-set header cannot park a Batch job for an hour.
    """
    raw = (getattr(resp, "headers", None) or {}).get("Retry-After")
    if raw:
        try:
            return max(0.0, min(float(raw), cap))
        except (TypeError, ValueError):
            pass
        try:
            when = parsedate_to_datetime(raw)
            if when is not None:
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                return max(0.0, min((when - datetime.now(timezone.utc)).total_seconds(), cap))
        except (TypeError, ValueError):
            pass
    return min(base * (2 ** attempt), cap)


def _fetch_page(url: str, *, max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
                sleep=time.sleep) -> tuple[int, str]:
    """GET *url* with Retry-After / exponential backoff, returning (status_code, text).

    NEVER raises: the caller's whole exit contract is built on the status code, and a fetcher that
    threw here would bypass the banked partition entirely.

    Why this exists (2026-09-22, round 3).  The gated leg had ONE attempt and no backoff, in the
    same commit that gave MPOC four attempts and a Retry-After honour.  The terminal surface this
    lane narrowed to -- the UNBANKED current quarter -- was therefore one transient away from a
    family red with nothing behind it.  The narrowing is still the right trade; it just needed the
    same retry the other producer got.

    A 404 is NOT retried: it is the normal answer for a quarter that was never published, and
    retrying it four times would multiply a healthy fire's request count by four for nothing.  A
    retry-exhausted 429 still returns 429, so the caller maps it to ``error`` and the partition --
    not this function -- decides whether it is fatal.
    """
    last_status, last_text = 0, ""
    for attempt in range(max_attempts):
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT_S,
                                allow_redirects=True)
        except requests.RequestException as exc:
            last_status, last_text = 0, ""
            if attempt == max_attempts - 1:
                logger.warning("Request error for %s after %d attempt(s): %s",
                               url, max_attempts, exc)
                break
            wait = min(_BACKOFF_BASE_S * (2 ** attempt), _BACKOFF_CAP_S)
            logger.warning("Request error for %s - attempt %d/%d, backing off %.1fs: %s",
                           url, attempt + 1, max_attempts, wait, exc)
            sleep(wait)
            continue
        last_status, last_text = resp.status_code, resp.text
        if resp.status_code in _RETRY_STATUS and attempt < max_attempts - 1:
            wait = _retry_after_seconds(resp, attempt)
            logger.warning("HTTP %s from %s - attempt %d/%d, backing off %.1fs",
                           resp.status_code, url, attempt + 1, max_attempts, wait)
            sleep(wait)
            continue
        return resp.status_code, resp.text
    return last_status, last_text


# ---------------------------------------------------------------------------
# QBCS HTML parsing
# ---------------------------------------------------------------------------

# Regex to extract "DD Month YYYY" from the page intro text.
_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+(\d{4})\b",
    re.IGNORECASE,
)

# Regex to extract volume and issue from strings like "Issue No. 1 – Volume LII"
_VOLUME_RE = re.compile(
    r"Issue\s+No[.\s]+(\d)\s*[–\-]\s*Volume\s+([IVXLCDM]+)",
    re.IGNORECASE,
)

# Regex to extract cocoa year labels like "2024/25" or "2024/2025"
_COCOA_YEAR_RE = re.compile(r"\b(20\d{2})/(\d{2,4})\b")

# Regex to parse numeric values with optional thousands separators (spaces or commas).
_NUMBER_RE = re.compile(r"[-–]?\s*[\d][\d\s,]*")

# ---------------------------------------------------------------------------
# Release-date window (P10)
# ---------------------------------------------------------------------------
# The intro dateline is the AUTHORITATIVE release date and stays primary -- but it is prose ICCO
# writes by hand, and on the August 2026 bulletin it reads "Abidjan, Cote d'Ivoire, 29 May 2026",
# the MAY issue's dateline copy-pasted into the August page.  Taken at face value that date
# recomputes the S3 keys onto release_date=2026-05-29 and OVERWRITES the May record with August's
# numbers -- silently, and strictly worse than the missed release it would be fixing.
#
# So the dateline is FENCED, never replaced: it must fall inside a window that opens on the first
# day of the bulletin's own month.  Measured over the 50 landed QBCS pages, every one of the 48
# that parse today sits 25..34 days into that window; the August 2026 dateline sits 64 days BEFORE
# it.  The ceiling is 75 days -- comfortably past the widest real lag and comfortably short of the
# ~92-day quarterly spacing, so a date belonging to the NEXT issue can never be accepted.
#
# When the dateline is out of window the page's own WordPress publication stamp is tried against
# the same window (2026-08-31, +30 days: correct).  Only if BOTH fail does the last-day-of-month
# fallback stand.  The fence CORRECTS the date; it never drops the release.
_RELEASE_WINDOW_DAYS = 75

# ---------------------------------------------------------------------------
# QBCS PROSE layout (P10) -- the Q3/August shape
# ---------------------------------------------------------------------------
# Twice now -- 2025-08-31 and 2026-08-31 -- the Secretariat has "temporarily withheld" the current
# season and published the balance sheet as a BULLETED PARAGRAPH with no <table> element at all
# (both pages carry zero <table> tags).  _parse_qbcs_table cannot see it, returned None, and the
# release was lost.  The numbers are stated plainly and are parsed here, with the same four metrics
# in the same insertion order the table layout produces, so a prose release and a table release are
# the same record downstream.
#
# The prose layout states ONE season (the one not withheld), so the record carries `current` only
# and no `prior` block.  raw_to_bronze/icco_cocoa.py already skips a vintage whose block or cocoa
# year is absent, so this reduces to 4 bronze rows instead of 8.  The year-on-year PERCENTAGES the
# prose also prints are deliberately NOT back-divided into a prior column: a prior minted by
# arithmetic is not a figure the page printed.
_PROSE_NUM = r"([0-9][0-9\s,. ]*[0-9]|[0-9])"
_PROSE_UNIT = r"\s*(million|thousand)?\s*(?:metric\s+)?tonnes"
# The gap between the anchor and its figure may not cross a "tonnes" (that would let a metric whose
# own figure is missing steal the NEXT metric's) nor a semicolon.
_PROSE_GAP = r"(?:(?!tonnes)[^;]){0,140}?"

_PROSE_SEASON_RE = re.compile(r"data\s+for\s+the\s+(20\d{2}/\d{2,4})\s+season", re.IGNORECASE)
# The prose page names TWO seasons and only one of them owns the figures.  On both August pages the
# FIRST "data for the ... season" belongs to the season the Secretariat WITHHELD ("temporarily
# withheld production and grindings data for the 2025/26 season"), and the figures belong to the
# SECOND ("However, data for the 2024/25 season are estimated as:").  Labelling a 2024/25 balance
# sheet 2025/26 would publish the right numbers under the wrong year -- worse than the miss it
# replaces -- so the season is chosen per SENTENCE: a sentence carrying "withheld" is rejected, a
# sentence must carry an affirmative verb to be eligible, and zero or ambiguous candidates return
# None (a terminal parse_error) rather than a guess.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.:;])\s+(?=[A-Z])")
_PROSE_WITHHELD_RE = re.compile(r"\bwithheld\b", re.IGNORECASE)
_PROSE_AFFIRM_RE = re.compile(r"\b(?:estimated|unchanged|revised|remain|stand)\w*\b", re.IGNORECASE)
_PROSE_PRODUCTION_RE = re.compile(
    r"world\s+(?:gross\s+)?production\b" + _PROSE_GAP + r"\bto\s+" + _PROSE_NUM + _PROSE_UNIT,
    re.IGNORECASE,
)
_PROSE_GRINDINGS_RE = re.compile(
    r"world\s+grindings\b" + _PROSE_GAP + r"\bto\s+" + _PROSE_NUM + _PROSE_UNIT,
    re.IGNORECASE,
)
_PROSE_BALANCE_RE = re.compile(
    r"global\s+supply\s+(surplus|deficit)\b" + _PROSE_GAP + r"\b(?:as|to|of|at)\s+"
    + _PROSE_NUM + _PROSE_UNIT,
    re.IGNORECASE,
)
_PROSE_STOCKS_RE = re.compile(
    r"end[-\s]?of[-\s]?season\s+stocks\b" + _PROSE_GAP + r"\bto\s+" + _PROSE_NUM + _PROSE_UNIT,
    re.IGNORECASE,
)

# div.entry-content is the estate's own PIT-correct container for this site (the selector
# raw_to_text/icco_qbcs.py uses): it drops the "Latest News" sidebar, which links FUTURE bulletins.
_CONTENT_SELECTOR = "entry-content"

# The GATED leg feeds a served table (silver_icco_cocoa) and its failures are terminal.  The EWG
# leg feeds no SERVED table; the text/evidence layer reads its pages -- see the module docstring.
_GATED_LEG = "qbcs"

# The prefix every QBCS summary lands under, and the release date inside a landed key.  ONE listing
# of this prefix per run answers "does the estate already hold this bulletin?" for all ~73 issues;
# asking with a CONSTRUCTED key cannot, because the key is only known after the dateline is read.
_QBCS_SUMMARY_PREFIX = "raw/production/source=icco_qbcs_summary/"
_RELEASE_DATE_IN_KEY_RE = re.compile(r"release_date=(\d{4}-\d{2}-\d{2})/")

# The filename an UNPARSEABLE page lands under, and the one invariant it buys: inside a
# release_date folder, ``page.html`` is ALWAYS the page that minted that folder's record.
#
# Round 2 landed a parse failure at ``<banked folder>/page.html`` so the evidence would sit beside
# the record instead of minting an orphan folder -- and that is the SAME key the successful run
# wrote.  ``get_bucket_versioning(leviathan-dev-shahem-001)`` reads ``Status: Suspended``
# (re-measured 2026-09-22), so that PUT destroyed the 138,448-byte page that produced
# ``release_date=2013-05-29/icco_qbcs_summary_20130529.json`` and nothing could restore it: a fix
# for a fence that deleted an exit code must not itself delete an object.  A page that yielded no
# record is never named as if it had.
#
# BOTH LEGS, not one.  On the UNGATED (EWG) leg the key is built from the season alone, so there
# is no dateline to move the failure onto a different partition: `raw/production/
# source=icco_ewg_stocks/season=<s>/page.html` is the success key AND the failure key, on all 13
# seasons, on every monthly fire (`skip_existing: false`).  The same constant is used there.
_PARSE_FAILURE_PAGE = "page_parse_failure.html"


def _parse_number(text: str) -> float | None:
    """Parse a potentially formatted number like "1 300", "4,698", "– 478" → float."""
    t = text.strip()
    # Normalise minus signs.
    t = re.sub(r"^[–−]", "-", t)
    # Remove thousands separators (spaces and commas between digits).
    t = re.sub(r"(?<=\d)[,\s](?=\d)", "", t)
    # Strip trailing percent.
    t = t.rstrip("%").strip()
    # Remove any remaining whitespace.
    t = t.replace(" ", "")
    try:
        return float(t)
    except ValueError:
        return None


def _cell_text(cell: Any) -> str:
    return cell.get_text(separator=" ", strip=True)


def _parse_qbcs_table(soup: BeautifulSoup) -> dict[str, Any] | None:
    """Extract the QBCS world balance summary table.

    The table has 5 data rows (production, grindings, surplus/deficit, stocks,
    stocks/grindings ratio) and is consistent from Feb 2008 to the present.

    Returns a dict with keys: cocoa_year_prior, cocoa_year_current, prior, current,
    or None if parsing fails.
    """
    # Find the table that contains "production" in one of its cells.
    target_table = None
    for table in soup.find_all("table"):
        text = table.get_text(separator=" ", strip=True).lower()
        if "production" in text and "grindings" in text and "stocks" in text:
            target_table = table
            break

    if target_table is None:
        return None

    rows = target_table.find_all("tr")
    if not rows:
        return None

    # -----------------------------------------------------------------------
    # Extract cocoa year labels from header row(s).
    # The column header typically looks like "2023/24" or "2023/2024".
    # -----------------------------------------------------------------------
    header_text = " ".join(
        _cell_text(c) for row in rows[:3] for c in row.find_all(["th", "td"])
    )
    year_matches = _COCOA_YEAR_RE.findall(header_text)
    # Deduplicate while preserving order.
    seen: set[str] = set()
    cocoa_years: list[str] = []
    for full, short in year_matches:
        label = f"{full}/{short[-2:]}"  # normalise to 4/2 format, e.g. 2024/25
        if label not in seen:
            seen.add(label)
            cocoa_years.append(label)

    cocoa_year_prior = cocoa_years[0] if len(cocoa_years) >= 1 else None
    cocoa_year_current = cocoa_years[-1] if len(cocoa_years) >= 2 else cocoa_years[0] if cocoa_years else None

    # -----------------------------------------------------------------------
    # Identify data rows by searching for keywords in the first cell.
    # -----------------------------------------------------------------------
    ROW_KEYS = {
        "production": ("world_production_kt", False),
        "grindings":  ("world_grindings_kt",  False),
        "surplus":    ("surplus_deficit_kt",   True),   # may be negative
        "deficit":    ("surplus_deficit_kt",   True),
        "stocks":     ("end_season_stocks_kt", False),
        "ratio":      ("stocks_grindings_pct", False),
    }

    extracted: dict[str, dict[str, float | None]] = {"prior": {}, "current": {}}

    for row in rows:
        cells = row.find_all(["th", "td"])
        if len(cells) < 3:
            continue
        row_label = _cell_text(cells[0]).lower()

        matched_key: str | None = None
        is_signed = False
        for keyword, (field_name, signed) in ROW_KEYS.items():
            if keyword in row_label:
                matched_key = field_name
                is_signed = signed
                break
        if matched_key is None:
            continue
        # Already captured this field (e.g. "surplus/deficit" matches both "surplus" and
        # the next keyword "deficit" in a later iteration); skip if already set.
        if matched_key in extracted["prior"]:
            continue

        # The table typically has: [label | prior_prev_estimate | prior_revised | current | change_kt | change_pct]
        # Or simpler: [label | prior | current | change_kt | change_pct]
        # We want the two *estimated* values (skip the "previous estimates a/" column
        # which is the first data column in some years).
        # Strategy: take the last two numeric columns before the YoY change columns.
        numeric_cells = []
        for cell in cells[1:]:
            val = _parse_number(_cell_text(cell))
            if val is not None:
                numeric_cells.append(val)

        # For ratio rows the values are percentages, not thousands of tonnes.
        # The table usually has 2–3 numeric values before the change columns.
        # We take index -4 (prior revised) and -3 (current) when ≥4 values,
        # else -2 and -1.
        if is_signed:
            # Surplus/deficit row can have negative values — all are already parsed.
            pass

        if len(numeric_cells) >= 4:
            # [prev_estimate, prior_revised, current_estimate, change_kt, change_pct]
            prior_val = numeric_cells[-4]
            current_val = numeric_cells[-3]
        elif len(numeric_cells) >= 2:
            prior_val = numeric_cells[-2]
            current_val = numeric_cells[-1]
        else:
            continue

        extracted["prior"][matched_key] = prior_val
        extracted["current"][matched_key] = current_val

    if not extracted["current"]:
        return None

    return {
        "cocoa_year_prior": cocoa_year_prior,
        "cocoa_year_current": cocoa_year_current,
        "prior": extracted["prior"],
        "current": extracted["current"],
    }


def _content_text(soup: BeautifulSoup) -> str:
    """Visible text of div.entry-content, or of the whole page when that container is absent."""
    container = soup.find("div", class_=_CONTENT_SELECTOR)
    node = container if container is not None else soup
    return node.get_text(separator=" ", strip=True).replace(" ", " ")


def _kt(value: float, unit: str | None) -> float:
    """Normalise a prose figure to thousands of tonnes (the estate's kt unit)."""
    u = (unit or "").strip().lower()
    if u == "million":
        return round(value * 1000.0, 3)
    if u == "thousand":
        return round(value, 3)
    # A bare "tonnes" figure ("estimated as 37,000 tonnes").
    return round(value / 1000.0, 3)


def _published_time_date(soup: BeautifulSoup) -> str | None:
    """ISO date from the page's own WordPress ``article:published_time`` meta, or None."""
    meta = soup.find("meta", attrs={"property": "article:published_time"})
    content = (meta.get("content") or "") if meta is not None else ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", content)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def _in_release_window(iso_date: str, month: str, year: int) -> bool:
    """True when *iso_date* sits in [first day of the bulletin's month, +_RELEASE_WINDOW_DAYS)."""
    try:
        start = date(year, _MONTH_NAME_TO_NUM[month], 1)
        candidate = date.fromisoformat(iso_date)
    except (KeyError, ValueError):
        return False
    return start <= candidate < start + timedelta(days=_RELEASE_WINDOW_DAYS)


def _parse_release_date(soup: BeautifulSoup, fallback_month: str, fallback_year: int) -> str:
    """ISO release date for the bulletin, fenced against a dateline from the WRONG issue.

    Order: the intro dateline (authoritative, and in window on all 48 QBCS pages that parse today),
    then the page's own WordPress publication stamp, then the last day of the bulletin's month.  A
    candidate is taken only when :func:`_in_release_window` accepts it -- see _RELEASE_WINDOW_DAYS
    for the August-2026 dateline that names the MAY issue.
    """
    text = soup.get_text(separator=" ", strip=True)
    m = _DATE_RE.search(text)
    if m:
        day = int(m.group(1))
        month_num = _MONTH_NAME_TO_NUM[m.group(2).lower()]
        year = int(m.group(3))
        try:
            candidate = date(year, month_num, day).isoformat()
        except ValueError:
            candidate = None
        if candidate and _in_release_window(candidate, fallback_month, fallback_year):
            return candidate
        if candidate:
            logger.warning(
                "Dateline %s is outside the %s %d release window -- it does not belong to this "
                "issue; falling through to the page's publication stamp",
                candidate, fallback_month, fallback_year,
            )

    published = _published_time_date(soup)
    if published and _in_release_window(published, fallback_month, fallback_year):
        logger.info("Release date taken from the page's publication stamp: %s", published)
        return published

    # Fallback: use the last day of the publication month.
    month_num = _MONTH_NAME_TO_NUM[fallback_month]
    fallback_day = _QBCS_FALLBACK_DAY[fallback_month]
    return date(fallback_year, month_num, fallback_day).isoformat()


def _sentences(text: str) -> list[tuple[int, str]]:
    """Split *text* into (offset, sentence) pairs.  Decimals survive: the split needs a capital."""
    out: list[tuple[int, str]] = []
    start = 0
    for m in _SENTENCE_SPLIT_RE.finditer(text):
        out.append((start, text[start:m.start()]))
        start = m.end()
    out.append((start, text[start:]))
    return out


def _prose_season(text: str) -> tuple[str, int] | None:
    """The cocoa year the prose figures belong to, and the offset the figures start after.

    Returns None when no sentence qualifies OR when more than one distinct season does -- an
    ambiguous page is a parse failure the fence announces, never a coin flip.
    """
    candidates: list[tuple[str, int]] = []
    for offset, sentence in _sentences(text):
        m = _PROSE_SEASON_RE.search(sentence)
        if m is None:
            continue
        if _PROSE_WITHHELD_RE.search(sentence):
            continue
        if not _PROSE_AFFIRM_RE.search(sentence):
            continue
        full, _, short = m.group(1).partition("/")
        candidates.append((f"{full}/{short[-2:]}", offset + len(sentence)))

    distinct = {label for label, _ in candidates}
    if len(distinct) != 1:
        if candidates:
            logger.warning("Prose layout names %d distinct data seasons %s -- refusing to guess",
                           len(distinct), sorted(distinct))
        return None
    return candidates[0]


def _parse_qbcs_prose(soup: BeautifulSoup) -> dict[str, Any] | None:
    """Extract the QBCS world balance summary from the Q3/August PROSE layout.

    Used only when :func:`_parse_qbcs_table` finds no table.  Returns the same dict shape, with
    ``prior`` empty and ``cocoa_year_prior`` None (the prose states one season), or None when the
    page states no season or no metric -- which is then a TERMINAL parse_error, not a warning.
    """
    full_text = _content_text(soup)

    chosen = _prose_season(full_text)
    if chosen is None:
        return None
    cocoa_year, metrics_from = chosen

    # The figures are read ONLY from the text that follows the sentence naming their season, so a
    # withheld season stated earlier on the page can never lend its words to these numbers.
    text = full_text[metrics_from:]

    current: dict[str, float | None] = {}

    # Insertion order matches the table layout's row order, so the JSON record is shape-identical.
    prod_m = _PROSE_PRODUCTION_RE.search(text)
    if prod_m:
        val = _parse_number(prod_m.group(1))
        if val is not None:
            current["world_production_kt"] = _kt(val, prod_m.group(2))

    grind_m = _PROSE_GRINDINGS_RE.search(text)
    if grind_m:
        val = _parse_number(grind_m.group(1))
        if val is not None:
            current["world_grindings_kt"] = _kt(val, grind_m.group(2))

    bal_m = _PROSE_BALANCE_RE.search(text)
    if bal_m:
        val = _parse_number(bal_m.group(2))
        if val is not None:
            magnitude = _kt(abs(val), bal_m.group(3))
            current["surplus_deficit_kt"] = (
                -magnitude if bal_m.group(1).lower() == "deficit" else magnitude
            )

    stocks_m = _PROSE_STOCKS_RE.search(text)
    if stocks_m:
        val = _parse_number(stocks_m.group(1))
        if val is not None:
            current["end_season_stocks_kt"] = _kt(val, stocks_m.group(2))

    if not current:
        return None

    return {
        "cocoa_year_prior": None,
        "cocoa_year_current": cocoa_year,
        "prior": {},
        "current": current,
    }


def _parse_volume_issue(soup: BeautifulSoup) -> tuple[str | None, int | None]:
    """Extract volume (Roman numeral string) and issue number from page text."""
    text = soup.get_text(separator=" ", strip=True)
    m = _VOLUME_RE.search(text)
    if m:
        issue = int(m.group(1))
        volume = m.group(2).upper()
        return volume, issue
    return None, None


# ---------------------------------------------------------------------------
# EWG stocks HTML parsing
# ---------------------------------------------------------------------------

_EWG_REGIONS = {
    "importing": "importing_countries_kt",
    "exporting": "exporting_countries_kt",
    "south-east asia": "se_asia_kt",
    "southeast asia": "se_asia_kt",
    "manufacturers": "manufacturers_kt",
    "in transit": "in_transit_kt",
    "total identified": "total_identified_kt",
    "total estimated world": "total_estimated_world_kt",
}

_EWG_SEASON_RE = re.compile(r"(\d{4})/(\d{2,4})", re.IGNORECASE)


def _parse_ewg_table(soup: BeautifulSoup, season: str) -> dict[str, Any] | None:
    """Parse the EWG annual cocoa bean stocks table.

    The table rows represent stock categories; columns represent seasons.
    We capture the column matching *season* (the most recent year's data).
    """
    target_table = None
    for table in soup.find_all("table"):
        text = table.get_text(separator=" ", strip=True).lower()
        if "importing" in text and "stocks" in text:
            target_table = table
            break

    if target_table is None:
        return None

    rows = target_table.find_all("tr")
    if not rows:
        return None

    # Find which column corresponds to the target season.
    # Header cells typically contain season labels like "2024/25" or "September 2025".
    header_row = rows[0]
    header_cells = header_row.find_all(["th", "td"])

    # Use the rightmost data column (most recent season) as the primary.
    n_data_cols = max(0, len(header_cells) - 1)
    col_idx = n_data_cols  # 1-based column for the last data column

    stocks: dict[str, float | None] = {}
    for row in rows[1:]:
        cells = row.find_all(["th", "td"])
        if not cells:
            continue
        label = _cell_text(cells[0]).lower()
        matched_field: str | None = None
        for keyword, field_name in _EWG_REGIONS.items():
            if keyword in label:
                matched_field = field_name
                break
        if matched_field is None:
            continue
        if matched_field in stocks:
            continue
        # Take the last data cell.
        data_cells = cells[1:]
        if not data_cells:
            continue
        val = _parse_number(_cell_text(data_cells[-1]))
        stocks[matched_field] = val

    if not stocks:
        return None

    # Extract the season labels from the header to know which years the columns cover.
    header_text = " ".join(_cell_text(c) for c in header_cells)
    season_matches = _EWG_SEASON_RE.findall(header_text)
    seen_s: set[str] = set()
    season_labels: list[str] = []
    for full, short in season_matches:
        label = f"{full}/{short[-2:]}"
        if label not in seen_s:
            seen_s.add(label)
            season_labels.append(label)
    current_season_label = season_labels[-1] if season_labels else season

    return {
        "season": season,
        "season_label": current_season_label,
        "stocks_kt": stocks,
    }


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------


def landed_summary_keys(
    bucket: str,
    region: str,
    lister: Callable[..., list[str]] = list_s3_keys,
) -> list[str]:
    """Every QBCS summary JSON key the estate holds, in ONE listing (48 keys on 2026-09-22).

    One LIST answers the banked question for all ~75 enumerated bulletins.  A per-issue HEAD could
    not: the key a record lands on is not known until its dateline is read.
    """
    return lister(bucket, _QBCS_SUMMARY_PREFIX, ".json", region)


def banked_summary_key(month: str, year: int, landed_keys: list[str]) -> str | None:
    """The summary JSON the estate ALREADY holds for this bulletin, or None -- from the REAL keys.

    The bug this replaces: ``banked`` was a HEAD on ``release_date=<last day of month>/``, a key
    the record does not land on.  The landed key carries the page's own dateline, and measured
    against the 48 summary records the estate really holds (2026-09-22) the tentative key finds
    26 of them while this window lookup finds all 48 -- so the banked exemption was ABSENT on 22
    of 48 releases, including the 2013 May page the partition was written for, and both of the
    two most recent quarters.  Two records (2020-03-06, 2020-12-02) landed in the month AFTER
    their bulletin's, which is why the window and not a month prefix is the right question.

    The match is the SAME release window :func:`_parse_release_date` accepts a dateline from, so
    the question "is this key this bulletin's?" has exactly one answer in the module.  Keys arrive
    from S3 in lexicographic order, so the earliest matching release date wins deterministically.
    """
    for key in landed_keys:
        if not key.endswith(".json"):
            continue
        m = _RELEASE_DATE_IN_KEY_RE.search(key)
        if m is None:
            continue
        if _in_release_window(m.group(1), month, year):
            return key
    return None


class FetchOutcome(NamedTuple):
    """One release's result, plus what the run actually PUT and whether the estate had it.

    ``banked`` is the partition that keeps an archive page from killing the current quarter: a
    release the estate already holds a record for may fail on a re-fetch without setting the exit
    code.  ``banked_key`` is the key that record REALLY lives on -- carried, not re-derived, so
    the orphan fence and the terminal fence read the same fact and can never disagree.
    ``html_key`` / ``json_key`` are the keys THIS RUN uploaded (None when it uploaded nothing),
    and they are what the end-of-run sibling assertion reads.
    """

    result: str
    leg: str
    url: str
    banked: bool
    html_key: str | None = None
    json_key: str | None = None
    banked_key: str | None = None


def _process_qbcs(
    entry: dict[str, str],
    bucket: str,
    region: str,
    skip_existing: bool,
    dry_run: bool,
    sleep_seconds: float,
    landed_keys: list[str] | None = None,
) -> FetchOutcome:
    """Fetch, parse, and upload one QBCS bulletin page."""
    url = entry["url"]
    month = entry["month"]
    year = int(entry["year"])

    # Use a tentative release date for the S3 key (will be refined from page content).
    tentative_date = date(year, _MONTH_NAME_TO_NUM[month], _QBCS_FALLBACK_DAY[month]).isoformat()
    json_key = raw_icco_qbcs_summary_key(tentative_date, f"icco_qbcs_summary_{tentative_date.replace('-', '')}.json")
    html_key = raw_icco_qbcs_summary_key(tentative_date, "page.html")

    if dry_run:
        logger.info("DRY-RUN  QBCS  %s-%s  →  %s", year, month, json_key)
        return FetchOutcome("dry_run", _GATED_LEG, url, banked=False)

    # What the estate REALLY holds for this bulletin, read off the landed keys and never off a
    # constructed one -- the record lives on the dateline key, which is not known until the page
    # is parsed and is not the last-day-of-month key on 22 of the 50 landed releases.
    banked_key = banked_summary_key(month, year, landed_keys or [])
    banked = banked_key is not None

    if skip_existing and banked:
        logger.info("Skipping - already in S3: %s", banked_key)
        time.sleep(sleep_seconds)
        return FetchOutcome("skipped", _GATED_LEG, url, banked=True, banked_key=banked_key)

    status_code, html_text = _fetch_page(url)
    time.sleep(sleep_seconds)

    if status_code == 404:
        logger.debug("404 (no such issue)  %s", url)
        return FetchOutcome("missing", _GATED_LEG, url, banked=banked, banked_key=banked_key)
    if status_code != 200:
        logger.warning("HTTP %s for %s", status_code, url)
        return FetchOutcome("error", _GATED_LEG, url, banked=banked, banked_key=banked_key)

    soup = BeautifulSoup(html_text, "html.parser")
    release_date = _parse_release_date(soup, month, year)
    volume, issue = _parse_volume_issue(soup)
    table_data = _parse_qbcs_table(soup)
    if table_data is None:
        table_data = _parse_qbcs_prose(soup)
        if table_data is not None:
            logger.info(
                "No summary TABLE on %s -- read the Q3/PROSE layout instead: cocoa_year=%s "
                "metrics=%s",
                url, table_data["cocoa_year_current"], sorted(table_data["current"]),
            )

    if table_data is None:
        # No dateline is trustworthy on a page that yields no record, so the HTML lands beside the
        # record the estate ALREADY holds when there is one.  Writing it to the last-day-of-month
        # key instead is what minted release_date=2025-08-31/page.html, an orphan folder no run
        # will ever complete.
        #
        # It lands under its OWN filename, never `page.html`: on a bucket whose versioning reads
        # Suspended, writing an unparseable body to the record's own page.html is an unrecoverable
        # delete of the evidence that minted the record.  See _PARSE_FAILURE_PAGE.
        folder = (banked_key or html_key).rsplit("/", 1)[0]
        html_key = f"{folder}/{_PARSE_FAILURE_PAGE}"
        logger.error(
            "PARSE FAILURE: neither the table nor the prose layout yields a record from %s "
            "(banked=%s) -- the HTML is kept at %s for the replay, beside the record and never "
            "over it",
            url, banked_key or False, html_key,
        )
        # Still store the raw HTML: the fence corrects the exit code, it never drops the evidence.
        html_bytes = html_text.encode("utf-8")
        upload_bytes_to_s3(html_bytes, bucket, html_key, region)
        write_raw_s3_metadata(bucket, html_key, html_bytes, url, "text/html", region)
        return FetchOutcome("parse_error", _GATED_LEG, url, banked=banked, html_key=html_key,
                            banked_key=banked_key)

    # Recompute keys with the actual release date parsed from the page.
    json_key = raw_icco_qbcs_summary_key(release_date, f"icco_qbcs_summary_{release_date.replace('-', '')}.json")
    html_key = raw_icco_qbcs_summary_key(release_date, "page.html")

    # NOW the dateline is known: refine `banked` onto the REAL key this record lands on.  The
    # window lookup above already answers the same question for every landed release; this makes
    # the carried key the exact one whenever the two can differ.
    if json_key in (landed_keys or []):
        banked_key = json_key
        banked = True

    record: dict[str, Any] = {
        "release_date": release_date,
        "bulletin_volume": volume,
        "bulletin_issue": issue,
        "cocoa_year_prior": table_data["cocoa_year_prior"],
        "cocoa_year_current": table_data["cocoa_year_current"],
        "prior": table_data["prior"],
        "current": table_data["current"],
        "source_url": url,
        "ingested_at": datetime.utcnow().isoformat() + "Z",
    }

    json_bytes = json.dumps(record, indent=2, ensure_ascii=False).encode("utf-8")
    html_bytes = html_text.encode("utf-8")

    upload_bytes_to_s3(json_bytes, bucket, json_key, region)
    write_raw_s3_metadata(bucket, json_key, json_bytes, url, "application/json", region)
    upload_bytes_to_s3(html_bytes, bucket, html_key, region)
    write_raw_s3_metadata(bucket, html_key, html_bytes, url, "text/html", region)

    logger.info(
        "Uploaded  QBCS  %s  volume=%s issue=%s  cocoa_year=%s  →  s3://%s/%s",
        release_date, volume, issue, table_data["cocoa_year_current"],
        bucket, json_key,
    )
    return FetchOutcome("uploaded", _GATED_LEG, url, banked=banked,
                        html_key=html_key, json_key=json_key, banked_key=banked_key)


def _process_ewg(
    entry: dict[str, str],
    bucket: str,
    region: str,
    skip_existing: bool,
    dry_run: bool,
    sleep_seconds: float,
) -> FetchOutcome:
    """Fetch, parse, and upload one EWG stocks page (the UNGATED leg -- see the module docstring)."""
    url = entry["url"]
    season = entry["season"]

    json_key = raw_icco_ewg_stocks_key(season, f"icco_ewg_stocks_{season}.json")
    html_key = raw_icco_ewg_stocks_key(season, "page.html")

    if dry_run:
        logger.info("DRY-RUN  EWG   %s  →  %s", season, json_key)
        return FetchOutcome("dry_run", "ewg", url, banked=False)

    # The EWG key is deterministic from the season and carries no dateline, so the constructed key
    # IS the real key here -- the defect banked_summary_key exists for cannot arise on this leg.
    banked = s3_object_exists(bucket, json_key, region)
    banked_key = json_key if banked else None

    if skip_existing and banked:
        logger.info("Skipping - already in S3: %s", json_key)
        time.sleep(sleep_seconds)
        return FetchOutcome("skipped", "ewg", url, banked=True, banked_key=banked_key)

    status_code, html_text = _fetch_page(url)
    time.sleep(sleep_seconds)

    if status_code == 404:
        logger.debug("404 (no such season)  %s", url)
        return FetchOutcome("missing", "ewg", url, banked=banked, banked_key=banked_key)
    if status_code != 200:
        logger.warning("HTTP %s for %s", status_code, url)
        return FetchOutcome("error", "ewg", url, banked=banked, banked_key=banked_key)

    soup = BeautifulSoup(html_text, "html.parser")
    table_data = _parse_ewg_table(soup, season)

    if table_data is None:
        # UNGATED, and that is exactly why this leg is the WORSE of the two.  The EWG key is
        # deterministic from the season and carries no dateline, so the failure key and the
        # success key are not merely similar -- they are the SAME key, on every season, on every
        # fire.  There is no second partition here to absorb a failure the way a re-parsed
        # dateline absorbs one on the gated leg.  `configs/silver/dags/icco_cocoa.json` sets
        # `skip_existing: false` and the fetch task passes no flags, so all 13 seasons are
        # re-fetched monthly; four of the five live season folders hold a record JSON beside the
        # page that minted it, and the bucket's versioning reads Suspended.  Writing an
        # unparseable body to `page.html` there is an unrecoverable DELETE of the only evidence
        # those records have.  It lands under its own name for the same reason it does on the
        # gated leg.  See _PARSE_FAILURE_PAGE.
        html_key = raw_icco_ewg_stocks_key(season, _PARSE_FAILURE_PAGE)
        logger.warning(
            "Could not parse EWG stocks table from %s -- UNGATED leg, counted and named, "
            "never an exit code; the HTML is kept at %s, beside the page that minted the "
            "record and never over it",
            url, html_key,
        )
        html_bytes = html_text.encode("utf-8")
        upload_bytes_to_s3(html_bytes, bucket, html_key, region)
        write_raw_s3_metadata(bucket, html_key, html_bytes, url, "text/html", region)
        return FetchOutcome("parse_error", "ewg", url, banked=banked, html_key=html_key,
                            banked_key=banked_key)

    record: dict[str, Any] = {
        "season": season,
        "season_label": table_data.get("season_label"),
        "stocks_kt": table_data["stocks_kt"],
        "source_url": url,
        "ingested_at": datetime.utcnow().isoformat() + "Z",
    }

    json_bytes = json.dumps(record, indent=2, ensure_ascii=False).encode("utf-8")
    html_bytes = html_text.encode("utf-8")

    upload_bytes_to_s3(json_bytes, bucket, json_key, region)
    write_raw_s3_metadata(bucket, json_key, json_bytes, url, "application/json", region)
    upload_bytes_to_s3(html_bytes, bucket, html_key, region)
    write_raw_s3_metadata(bucket, html_key, html_bytes, url, "text/html", region)

    logger.info(
        "Uploaded  EWG   %s  →  s3://%s/%s",
        season, bucket, json_key,
    )
    return FetchOutcome("uploaded", "ewg", url, banked=banked,
                        html_key=html_key, json_key=json_key, banked_key=banked_key)


# ---------------------------------------------------------------------------
# End-of-run fences (P10)
# ---------------------------------------------------------------------------


def is_terminal(outcome: FetchOutcome) -> bool:
    """The ONE terminal predicate: GATED leg, a failure, and the release NOT already banked.

    Both fences read this, so ``terminal_failures`` and ``orphan_pages`` can never disagree about
    the same outcome -- which is exactly what they did as first written (see the module docstring).
    """
    return (
        outcome.result in ("error", "parse_error")
        and outcome.leg == _GATED_LEG
        and not outcome.banked
    )


def orphan_pages(
    outcomes: list[FetchOutcome],
    bucket: str,
    region: str,
    exists: Callable[[str, str, str], bool] = s3_object_exists,
) -> list[str]:
    """Every GATED ``page.html`` THIS RUN landed that the estate holds no summary JSON for.

    Four scopes, every one of them deliberate and measured:

    * THIS RUN. ``release_date=2025-08-31/page.html`` is a PRE-EXISTING orphan left by the bug this
      fence closes (the Aug-2025 bulletin's true dateline is 2025-08-29, so the repaired run writes
      its record to a different key and leaves the old HTML behind); a fence that tripped on it
      would red every fire forever over a page no run touched.
    * GATED LEG. ``season=2022-23`` is a standing EWG orphan whose per-LOCATION table shape
      ``_parse_ewg_table`` does not know. Counting it here would hand the family a PERMANENT red on
      an UNGATED leg nothing reads -- a fence that cannot be satisfied is not a fence. It is logged
      as an UNGATED deficiency and metered instead, and it flips to fatal the day that layout is
      taught and EWG becomes gated.
    * BANKED. A page whose release the estate ALREADY holds a summary for is a re-read, not an
      orphan -- the fence reads the BANKED key.  Without this the banked exemption was defeated
      entirely: a parse failure always uploads the HTML and leaves ``json_key`` None, so a 2013
      archive page that changed shape once raised SystemExit on every fire forever, on a leg whose
      record was already in the estate.
    * NAMED ONCE. An outcome the TERMINAL line already names is not counted again here; the
      operator reading one line at 12:00Z gets the real damage, not double it.

    An ``uploaded`` outcome is still read BACK against its own sibling: a JSON put that silently
    failed is caught here, banked or not.
    """
    orphans: list[str] = []
    for o in outcomes:
        if o.html_key is None or o.leg != _GATED_LEG:
            continue
        if o.json_key is not None:
            if not exists(bucket, o.json_key, region):
                orphans.append(o.html_key)
            continue
        if is_terminal(o):
            continue
        if o.banked_key and exists(bucket, o.banked_key, region):
            continue
        orphans.append(o.html_key)
    return orphans


def terminal_failures(outcomes: list[FetchOutcome]) -> list[FetchOutcome]:
    """Failures that must set the exit code: GATED leg, release NOT already banked.

    A banked release failing a re-fetch is a re-read of something the estate already holds -- named
    and counted, never fatal.  An UNGATED leg never sets the exit code at all.
    """
    return [o for o in outcomes if is_terminal(o)]


def exit_message(terminal: list[FetchOutcome], orphans: list[str]) -> str | None:
    """The SystemExit line for this run, or None when the run may exit 0.

    Each defect is counted in exactly one clause and every clause names its releases, so the line
    an operator reads at 12:00Z states the damage and not a multiple of it.
    """
    if not terminal and not orphans:
        return None
    parts: list[str] = []
    if terminal:
        parts.append(
            f"{len(terminal)} gated release(s) yielded no record "
            f"({', '.join(sorted(o.url for o in terminal))})"
        )
    if orphans:
        parts.append(
            f"{len(orphans)} page(s) landed with no summary JSON in the estate "
            f"({', '.join(sorted(orphans))})"
        )
    return " and ".join(parts) + " - see the TERMINAL/ORPHAN lines above."


def emit_parse_failure_metric(outcomes: list[FetchOutcome]) -> None:
    """Publish the per-leg parse/fetch failure counts to CloudWatch.  NEVER raises.

    ZERO is emitted on a clean run as well: an alarm on "> 0" whose metric only appears when it is
    breaching is an alarm on missing data, which the estate has had enough of.  boto3 is imported
    inside the function so the unit suite exercises every other path with no AWS dependency, and
    telemetry may never change an exit code.
    """
    try:
        import boto3
        now = datetime.now(timezone.utc)
        data = []
        for leg in (_GATED_LEG, "ewg"):
            failures = sum(
                1 for o in outcomes
                if o.leg == leg and o.result in ("error", "parse_error")
            )
            data.append({
                "MetricName": INGEST_LEG_FAILURE_METRIC, "Timestamp": now,
                "Value": float(failures), "Unit": "Count",
                "Dimensions": [{"Name": "Source", "Value": "icco"},
                               {"Name": "Leg", "Value": leg}],
            })
        boto3.client("cloudwatch").put_metric_data(
            Namespace=METRIC_NAMESPACE, MetricData=data)
        logger.info("[metric] %s -> %s: %s", INGEST_LEG_FAILURE_METRIC, METRIC_NAMESPACE,
                    {d["Dimensions"][1]["Value"]: d["Value"] for d in data})
    except Exception as exc:  # noqa: BLE001 -- telemetry must never change an exit code
        logger.warning("[metric] WARN could not emit %s (%s: %s) -- the exit code below stands",
                       INGEST_LEG_FAILURE_METRIC, type(exc).__name__, str(exc)[:160])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(
        description=(
            "Fetch ICCO QBCS quarterly bulletin press releases and annual EWG stocks "
            "reports from icco.org and upload parsed JSON + raw HTML to S3. "
            "Covers QBCS Feb 2008–present (~73 releases) and EWG 2013–present (~13 reports)."
        )
    )
    parser.add_argument(
        "--bucket",
        default=None,
        help="S3 bucket name (default: LEVIATHAN_BUCKET env var).",
    )
    parser.add_argument(
        "--aws-region",
        default="us-east-1",
        help="AWS region (default: us-east-1).",
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help="Skip pages whose S3 JSON key already exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print S3 keys without fetching or uploading anything.",
    )
    parser.add_argument(
        "--from-year",
        type=int,
        default=_QBCS_START_YEAR,
        metavar="YYYY",
        help=f"Process QBCS issues from this year onwards (default: {_QBCS_START_YEAR}).",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=1.0,
        help="Polite delay between HTTP requests in seconds (default: 1.0).",
    )
    parser.add_argument(
        "--no-ewg",
        action="store_true",
        help="Skip EWG annual stocks reports (fetch only QBCS bulletins).",
    )
    parser.add_argument(
        "--no-qbcs",
        action="store_true",
        help="Skip QBCS quarterly bulletins (fetch only EWG annual stocks reports).",
    )
    args = parser.parse_args()

    load_env()
    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    region: str = args.aws_region
    today = date.today()

    # ------------------------------------------------------------------
    # Build work lists
    # ------------------------------------------------------------------
    qbcs_entries = [] if args.no_qbcs else _qbcs_urls(args.from_year, today)
    ewg_entries = [] if args.no_ewg else _ewg_urls(_EWG_START_SEASON_YEAR, today)

    total = len(qbcs_entries) + len(ewg_entries)
    logger.info(
        "Work list: %d QBCS bulletins + %d EWG stocks reports = %d total",
        len(qbcs_entries), len(ewg_entries), total,
    )

    if args.dry_run:
        logger.info("--- DRY-RUN: printing S3 keys only, no network or S3 calls ---")

    # ONE listing answers "does the estate hold this bulletin?" for every issue, off the keys the
    # records REALLY land on. A per-issue HEAD on a constructed last-day-of-month key was wrong on
    # 22 of the 50 landed releases.
    landed_keys: list[str] = []
    if qbcs_entries and not args.dry_run:
        landed_keys = landed_summary_keys(bucket, region)
        logger.info(
            "The estate holds %d QBCS summary record(s) under %s -- these are the keys the banked "
            "exemption reads", len(landed_keys), _QBCS_SUMMARY_PREFIX,
        )

    # ------------------------------------------------------------------
    # Process QBCS bulletins
    # ------------------------------------------------------------------
    counters: dict[str, int] = {
        "uploaded": 0, "skipped": 0, "missing": 0, "error": 0,
        "parse_error": 0, "dry_run": 0,
    }
    outcomes: list[FetchOutcome] = []

    for i, entry in enumerate(qbcs_entries, 1):
        logger.debug(
            "QBCS [%d/%d]  %s-%s", i, len(qbcs_entries), entry["year"], entry["month"]
        )
        outcome = _process_qbcs(
            entry, bucket, region, args.skip_existing_s3, args.dry_run, args.sleep_seconds,
            landed_keys,
        )
        outcomes.append(outcome)
        counters[outcome.result] = counters.get(outcome.result, 0) + 1

    # ------------------------------------------------------------------
    # Process EWG reports
    # ------------------------------------------------------------------
    for i, entry in enumerate(ewg_entries, 1):
        logger.debug("EWG  [%d/%d]  %s", i, len(ewg_entries), entry["season"])
        outcome = _process_ewg(
            entry, bucket, region, args.skip_existing_s3, args.dry_run, args.sleep_seconds
        )
        outcomes.append(outcome)
        counters[outcome.result] = counters.get(outcome.result, 0) + 1

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    logger.info(
        "Done. uploaded=%d  skipped=%d  missing=%d  parse_error=%d  error=%d  dry_run=%d",
        counters.get("uploaded", 0),
        counters.get("skipped", 0),
        counters.get("missing", 0),
        counters.get("parse_error", 0),
        counters.get("error", 0),
        counters.get("dry_run", 0),
    )

    if args.dry_run:
        return

    # ------------------------------------------------------------------
    # The three fences (P10).  Every failure is NAMED before the exit code is set.
    # ------------------------------------------------------------------
    emit_parse_failure_metric(outcomes)

    ungated = [o for o in outcomes if o.leg != _GATED_LEG and o.result in ("error", "parse_error")]
    for o in ungated:
        logger.warning("UNGATED deficiency (no exit code): %s on %s", o.result, o.url)

    banked_failures = [
        o for o in outcomes
        if o.result in ("error", "parse_error") and o.leg == _GATED_LEG and o.banked
    ]
    for o in banked_failures:
        logger.warning(
            "Re-fetch of a BANKED release failed (no exit code): %s on %s -- the estate already "
            "holds %s", o.result, o.url, o.banked_key,
        )

    terminal = terminal_failures(outcomes)
    for o in terminal:
        logger.error("TERMINAL: %s on %s (gated leg, release not banked)", o.result, o.url)

    orphans = orphan_pages(outcomes, bucket, region)
    for key in orphans:
        logger.error("ORPHAN: this run landed %s and the estate holds no summary JSON for that "
                     "release", key)

    message = exit_message(terminal, orphans)
    if message:
        raise SystemExit(message)


if __name__ == "__main__":
    main()
