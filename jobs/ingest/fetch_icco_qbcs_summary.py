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
               capture_<digest16>.html    a LATER capture that states something different
                                          (never written over page.html; see _land_page)
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

What the data repairs changed (2026-09-29, ICCO-1..4)
-----------------------------------------------------
* ONE page parser, in ``transforms/raw_to_bronze/icco_cocoa.py`` (:func:`parse_qbcs_page`): the
  table parser that took "the last two parsed numbers" of a row is deleted -- it lost every signed
  cell written with a NO-BREAK SPACE after the sign and labelled the same season's previous estimate
  with the prior season's name.  The silver task builds ``silver_icco_cocoa_releases`` from the
  banked page BYTES with the same function, so the fetcher and the table never read a page two ways.
* A capture is FILED BY THE PUBLISHER'S IDENTITY: the dateline is fenced to the month the page's own
  title names, not the URL's.  The November-2019 URL serves the August-2017 bulletin (Vol. XLIII
  No. 3); it is filed at release_date=2017-08-31, where its record already is.
* A BANKED RELEASE IS NEVER REWRITTEN (T-ICCO-12): neither its record JSON nor the ``page.html`` that
  minted it.  A capture that STATES something different lands beside them as
  ``capture_<digest16>.html`` (addressed by what it states, because the page's "Latest News" sidebar
  changes every month); one that states the same thing writes nothing and reports ``unchanged``.
* The record JSON of a NEW release is the parse record (identity, dated rung, every column with its
  header season, kind and footnote marker, prose rows, withheld seasons) plus ``page_key`` and
  ``statement_sha256``.  It is a record of the fetch, not evidence: the page is.

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
import hashlib
import json
import logging
import re
import time
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, NamedTuple

import requests
from bs4 import BeautifulSoup

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_icco_ewg_stocks_key, raw_icco_qbcs_summary_key
from leviathan.storage.raw_metadata import write_raw_s3_metadata
from leviathan.storage.s3 import list_s3_keys, s3_object_exists, upload_bytes_to_s3
from leviathan.transforms.raw_to_bronze.icco_cocoa import (
    CAPTURE_PAGE_TEMPLATE,
    PARSE_FAILURE_PAGE_NAME,
    QBCS_ISSUE_MONTHS,
    ParsedPage,
    parse_qbcs_page,
)
from leviathan.transforms.raw_to_bronze.icco_cocoa import in_release_window as _in_release_window

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

# Months in which QBCS issues are published -- declared ONCE, in the page parser's module (issue N
# of a volume is the Nth of these months, which is also how a page's own title is checked).
_QBCS_MONTHS = QBCS_ISSUE_MONTHS

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
# QBCS page parsing: ONE parser, in the pure module the silver task reads the banked pages with
# ---------------------------------------------------------------------------
# 2026-09-29 (data repairs ICCO-2).  The table parser that lived here took "the last two parsed
# numbers" of each row, so a sign followed by a NO-BREAK SPACE (``+NBSP75``) parsed to nothing and
# shifted every value one column left, and its ``prior`` block was the SAME season's previous estimate
# under the PRIOR season's name.  It is deleted.  ONE parser now reads a page --
# :func:`leviathan.transforms.raw_to_bronze.icco_cocoa.parse_qbcs_page` -- here to decide the key a
# capture is filed under, and in the silver task to build the releases table from the banked bytes,
# so the two can never read one page two ways.  The Q3/August PROSE layout and the P10 dateline fence
# moved there unchanged, with one correction: the fence opens on the first day of the month the
# PAGE's own title names, not the URL's (the August-2017 bulletin is served from the November-2019
# URL, and the URL-month fence filed it under release_date=2019-11-30).  The URL month is used only
# when a page's title names no bulletin month.

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
_PARSE_FAILURE_PAGE = PARSE_FAILURE_PAGE_NAME   # declared once, beside the parser that reads the folder


# A later capture of a bulletin the estate already holds lands beside it as ``capture_<digest16>.html``
# (CAPTURE_PAGE_TEMPLATE), keyed by a digest of what the page STATES (its identity, date, columns,
# prose and withheld seasons) -- never over ``page.html`` (T-ICCO-12: the bucket's versioning reads
# Suspended, so an overwrite is a delete).  Addressed by the statement and not by the raw bytes
# because every icco.org page carries a "Latest News" sidebar that changes every month: a raw-byte
# address would mint ~50 new captures on every fire while the bulletin itself said nothing new.
_CAPTURE_PAGE_TEMPLATE = CAPTURE_PAGE_TEMPLATE


def _parse_number(text: str) -> float | None:
    """Parse "1 300", "4,698", "- 478" -> float.  EWG leg only (unsigned stock figures); the QBCS
    page parser, whose signed cells this rule lost, lives in transforms/raw_to_bronze/icco_cocoa.py."""
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


def statement_digest(page: ParsedPage) -> str:
    """sha256 of what a page STATES -- the parse record minus the page's own byte digest."""
    record = page.to_record()
    record.pop("page_sha256", None)
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=True).encode("ascii")).hexdigest()


def yields_release(page: ParsedPage) -> bool:
    """True when the page states at least one season (a table column, a prose row or a withheld season)."""
    return page.failure is None and bool(page.columns or page.prose_rows or page.withheld_seasons)


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

    The match is the SAME release window the page parser accepts a dateline from, so
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

    html_bytes = html_text.encode("utf-8")
    # ONE parser (the silver task reads the banked bytes with the same function).  The URL month is
    # passed only as the fallback for a page whose own title names no bulletin month.
    page = parse_qbcs_page(html_bytes, url_month=month, url_year=year, source_url=url)
    for note in page.notes:
        logger.warning("QBCS page %s: %s", url, note)

    if not yields_release(page):
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
            "PARSE FAILURE: the page yields no release (%s) from %s (banked=%s) -- the HTML is kept "
            "at %s for the replay, beside the record and never over it",
            page.failure or "no season stated", url, banked_key or False, html_key,
        )
        # Still store the raw HTML: the fence corrects the exit code, it never drops the evidence.
        upload_bytes_to_s3(html_bytes, bucket, html_key, region)
        write_raw_s3_metadata(bucket, html_key, html_bytes, url, "text/html", region)
        return FetchOutcome("parse_error", _GATED_LEG, url, banked=banked, html_key=html_key,
                            banked_key=banked_key)

    # The keys come from the PAGE: its own dateline, fenced by its own bulletin identity.
    release_date = page.release_date
    json_key = raw_icco_qbcs_summary_key(release_date, f"icco_qbcs_summary_{release_date.replace('-', '')}.json")

    # NOW the page's own date is known, `banked` is re-read on the key THIS page's record lands on.
    # The URL-window lookup above answered for the bulletin the URL names; the page may be another
    # (the November-2019 URL serves the August-2017 bulletin, whose record the estate holds).
    banked = json_key in (landed_keys or [])
    banked_key = json_key if banked else None

    digest = statement_digest(page)
    page_key, wrote_page = _land_page(bucket, region, release_date, html_bytes, digest, url)

    if banked:
        # T-ICCO-12: a banked release is never rewritten.  Its record JSON and the page that minted
        # it stay exactly as they are; a capture that STATES something different was kept beside
        # them under its statement digest (the silver task lists it; it never replaces the record).
        logger.info("QBCS %s (Vol. %s No. %s) is banked at %s -- %s", release_date,
                    page.bulletin_volume, page.bulletin_issue, banked_key,
                    f"a capture stating something new was kept at {page_key}" if wrote_page
                    else "the page states nothing new; nothing written")
        return FetchOutcome("uploaded" if wrote_page else "unchanged", _GATED_LEG, url, banked=True,
                            html_key=page_key if wrote_page else None, banked_key=banked_key)

    record: dict[str, Any] = {
        **page.to_record(),
        "canonical_url": page.source_url,
        "source_url": url,
        "page_key": page_key,
        "statement_sha256": digest,
        "ingested_at": datetime.utcnow().isoformat() + "Z",
    }
    json_bytes = json.dumps(record, indent=2, ensure_ascii=False).encode("utf-8")
    upload_bytes_to_s3(json_bytes, bucket, json_key, region)
    write_raw_s3_metadata(bucket, json_key, json_bytes, url, "application/json", region)

    logger.info(
        "Uploaded  QBCS  %s  (%s)  Vol. %s No. %s  layout=%s  page=%s  ->  s3://%s/%s",
        release_date, page.release_date_source, page.bulletin_volume, page.bulletin_issue,
        page.layout, page_key, bucket, json_key,
    )
    return FetchOutcome("uploaded", _GATED_LEG, url, banked=False,
                        html_key=page_key, json_key=json_key, banked_key=None)


def _read_s3_bytes(bucket: str, key: str, region: str) -> bytes | None:
    """The bytes of an object the estate holds, or None when they cannot be read (never raises)."""
    try:
        from leviathan.storage.s3 import get_thread_local_s3_client, s3_download_with_retry
        return s3_download_with_retry(bucket, key, get_thread_local_s3_client(region))
    except Exception as exc:  # noqa: BLE001 -- an unreadable held page is treated as DIFFERENT
        logger.warning("could not read %s (%s: %s) -- a new capture is kept beside it, never over it",
                       key, type(exc).__name__, str(exc)[:160])
        return None


def _land_page(bucket: str, region: str, release_date: str, html_bytes: bytes, digest: str,
               url: str) -> tuple[str, bool]:
    """Keep this capture WITHOUT ever overwriting a page the estate holds: (key, wrote?).

    * no ``page.html`` in the release folder -> it lands there;
    * a ``page.html`` that states the same thing (its statement digest equals this one) -> nothing is
      written and that page's key is returned;
    * a ``page.html`` that states something else, or cannot be read -> this capture lands beside it
      under ``capture_<digest[:16]>.html``, once (a capture already held under that name is not
      rewritten).
    """
    page_key = raw_icco_qbcs_summary_key(release_date, "page.html")
    if not s3_object_exists(bucket, page_key, region):
        upload_bytes_to_s3(html_bytes, bucket, page_key, region)
        write_raw_s3_metadata(bucket, page_key, html_bytes, url, "text/html", region)
        return page_key, True
    held = _read_s3_bytes(bucket, page_key, region)
    if held is not None and statement_digest(parse_qbcs_page(held)) == digest:
        return page_key, False
    capture_key = raw_icco_qbcs_summary_key(
        release_date, _CAPTURE_PAGE_TEMPLATE.format(digest=digest[:16]))
    if s3_object_exists(bucket, capture_key, region):
        return capture_key, False
    upload_bytes_to_s3(html_bytes, bucket, capture_key, region)
    write_raw_s3_metadata(bucket, capture_key, html_bytes, url, "text/html", region)
    return capture_key, True


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
        "uploaded": 0, "unchanged": 0, "skipped": 0, "missing": 0, "error": 0,
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
        "Done. uploaded=%d  unchanged=%d  skipped=%d  missing=%d  parse_error=%d  error=%d  dry_run=%d",
        counters.get("uploaded", 0),
        counters.get("unchanged", 0),
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
