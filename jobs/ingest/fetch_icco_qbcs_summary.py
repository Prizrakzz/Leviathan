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
               page.html
    EWG:   raw/production/source=icco_ewg_stocks/season={YYYY-YY}/
               icco_ewg_stocks_{YYYY-YY}.json
               page.html

Idempotency
-----------
Pass ``--skip-existing-s3`` to skip pages already in S3.
Pass ``--dry-run`` to print S3 keys without fetching or uploading anything.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import date, datetime
from typing import Any

import requests
from bs4 import BeautifulSoup

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_icco_ewg_stocks_key, raw_icco_qbcs_summary_key
from leviathan.storage.raw_metadata import write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://www.icco.org"
_REQUEST_TIMEOUT_S = 15

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


def _fetch_page(url: str) -> tuple[int, str]:
    """GET *url*, returning (status_code, text).  Never raises on HTTP errors."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT_S,
                            allow_redirects=True)
        return resp.status_code, resp.text
    except requests.RequestException as exc:
        logger.warning("Request error for %s: %s", url, exc)
        return 0, ""


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


def _parse_release_date(soup: BeautifulSoup, fallback_month: str, fallback_year: int) -> str:
    """Extract ISO release date from page text; fall back to end of fallback month."""
    text = soup.get_text(separator=" ", strip=True)
    m = _DATE_RE.search(text)
    if m:
        day = int(m.group(1))
        month_num = _MONTH_NAME_TO_NUM[m.group(2).lower()]
        year = int(m.group(3))
        try:
            return date(year, month_num, day).isoformat()
        except ValueError:
            pass
    # Fallback: use the last day of the publication month.
    month_num = _MONTH_NAME_TO_NUM[fallback_month]
    fallback_day = _QBCS_FALLBACK_DAY[fallback_month]
    return date(fallback_year, month_num, fallback_day).isoformat()


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


def _process_qbcs(
    entry: dict[str, str],
    bucket: str,
    region: str,
    skip_existing: bool,
    dry_run: bool,
    sleep_seconds: float,
) -> str:
    """Fetch, parse, and upload one QBCS bulletin page.  Returns 'uploaded', 'skipped', or 'error'."""
    url = entry["url"]
    month = entry["month"]
    year = int(entry["year"])

    # Use a tentative release date for the S3 key (will be refined from page content).
    tentative_date = date(year, _MONTH_NAME_TO_NUM[month], _QBCS_FALLBACK_DAY[month]).isoformat()
    json_key = raw_icco_qbcs_summary_key(tentative_date, f"icco_qbcs_summary_{tentative_date.replace('-', '')}.json")
    html_key = raw_icco_qbcs_summary_key(tentative_date, "page.html")

    if dry_run:
        logger.info("DRY-RUN  QBCS  %s-%s  →  %s", year, month, json_key)
        return "dry_run"

    if skip_existing and s3_object_exists(bucket, json_key, region):
        logger.info("Skipping - already in S3: %s", json_key)
        time.sleep(sleep_seconds)
        return "skipped"

    status_code, html_text = _fetch_page(url)
    time.sleep(sleep_seconds)

    if status_code == 404:
        logger.debug("404 (no such issue)  %s", url)
        return "missing"
    if status_code != 200:
        logger.warning("HTTP %s for %s", status_code, url)
        return "error"

    soup = BeautifulSoup(html_text, "html.parser")
    release_date = _parse_release_date(soup, month, year)
    volume, issue = _parse_volume_issue(soup)
    table_data = _parse_qbcs_table(soup)

    if table_data is None:
        logger.warning("Could not parse summary table from %s", url)
        # Still store the raw HTML for manual inspection.
        html_bytes = html_text.encode("utf-8")
        upload_bytes_to_s3(html_bytes, bucket, html_key, region)
        write_raw_s3_metadata(bucket, html_key, html_bytes, url, "text/html", region)
        return "parse_error"

    # Recompute keys with the actual release date parsed from the page.
    json_key = raw_icco_qbcs_summary_key(release_date, f"icco_qbcs_summary_{release_date.replace('-', '')}.json")
    html_key = raw_icco_qbcs_summary_key(release_date, "page.html")

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
    return "uploaded"


def _process_ewg(
    entry: dict[str, str],
    bucket: str,
    region: str,
    skip_existing: bool,
    dry_run: bool,
    sleep_seconds: float,
) -> str:
    """Fetch, parse, and upload one EWG stocks page.  Returns 'uploaded', 'skipped', or 'error'."""
    url = entry["url"]
    season = entry["season"]

    json_key = raw_icco_ewg_stocks_key(season, f"icco_ewg_stocks_{season}.json")
    html_key = raw_icco_ewg_stocks_key(season, "page.html")

    if dry_run:
        logger.info("DRY-RUN  EWG   %s  →  %s", season, json_key)
        return "dry_run"

    if skip_existing and s3_object_exists(bucket, json_key, region):
        logger.info("Skipping - already in S3: %s", json_key)
        time.sleep(sleep_seconds)
        return "skipped"

    status_code, html_text = _fetch_page(url)
    time.sleep(sleep_seconds)

    if status_code == 404:
        logger.debug("404 (no such season)  %s", url)
        return "missing"
    if status_code != 200:
        logger.warning("HTTP %s for %s", status_code, url)
        return "error"

    soup = BeautifulSoup(html_text, "html.parser")
    table_data = _parse_ewg_table(soup, season)

    if table_data is None:
        logger.warning("Could not parse EWG stocks table from %s", url)
        html_bytes = html_text.encode("utf-8")
        upload_bytes_to_s3(html_bytes, bucket, html_key, region)
        write_raw_s3_metadata(bucket, html_key, html_bytes, url, "text/html", region)
        return "parse_error"

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
    return "uploaded"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
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

    # ------------------------------------------------------------------
    # Process QBCS bulletins
    # ------------------------------------------------------------------
    counters: dict[str, int] = {
        "uploaded": 0, "skipped": 0, "missing": 0, "error": 0,
        "parse_error": 0, "dry_run": 0,
    }

    for i, entry in enumerate(qbcs_entries, 1):
        logger.debug(
            "QBCS [%d/%d]  %s-%s", i, len(qbcs_entries), entry["year"], entry["month"]
        )
        result = _process_qbcs(
            entry, bucket, region, args.skip_existing_s3, args.dry_run, args.sleep_seconds
        )
        counters[result] = counters.get(result, 0) + 1

    # ------------------------------------------------------------------
    # Process EWG reports
    # ------------------------------------------------------------------
    for i, entry in enumerate(ewg_entries, 1):
        logger.debug("EWG  [%d/%d]  %s", i, len(ewg_entries), entry["season"])
        result = _process_ewg(
            entry, bucket, region, args.skip_existing_s3, args.dry_run, args.sleep_seconds
        )
        counters[result] = counters.get(result, 0) + 1

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

    if counters.get("error", 0) > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
