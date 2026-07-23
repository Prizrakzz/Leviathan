"""Fetch USDA NASS Florida Citrus PDF reports to raw S3.

Six report series, all from nass.usda.gov (static hosting, no auth required):

  Citrus Forecast series (Citrus_Forecast/history.php):
    monthly_forecast  — Monthly Citrus Production Forecast (Oct–Jul, ~10/season)
    maturity_test     — Maturity Test Results (Sept + Nov, ~2/season)
    freeze_damage     — Freeze Damage Reports (ad hoc, ~8 total across all seasons)

  Citrus Statistics (Citrus_Statistics/index.php):
    annual_statistics — FL Citrus Statistics annual book (March, one/season)
                        Available: 2008-09 through present.

  Citrus Summary (Citrus_Summary/index.php):
    citrus_summary_prelim — Preliminary citrus summary (September, one/season)
                            Available: 1996-97 through present.
    citrus_summary_final  — Final annual citrus summary book (one/season)
                            Available: 1998-99 through 2007-08; superseded by
                            annual_statistics from 2008-09 onward.

All ~370 PDFs are on live nass.usda.gov servers — no Wayback Machine required.

Modes
-----
--discover
    Scrape the three NASS Citrus index pages to discover all PDF URLs.
    Write/update configs/sources/usda_nass_citrus_manifest.yaml.
    No AWS credentials required.

Normal (no --discover)
    Load manifest and upload discovered PDFs to raw S3.
    Use --report-type and --season to restrict scope.

Idempotency
-----------
Pass --skip-existing-s3 (recommended) to skip PDFs already in S3.
Add --dry-run to print S3 keys without downloading anything.
"""
from __future__ import annotations

import argparse
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
import yaml
from bs4 import BeautifulSoup

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_nass_citrus_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3
from leviathan.transforms.raw_to_bronze.nass_citrus import current_forecast_season

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://www.nass.usda.gov"

_FORECAST_HISTORY_URL = (
    "https://www.nass.usda.gov/Statistics_by_State/Florida/Publications/Citrus/"
    "Citrus_Forecast/history.php"
)
_STATISTICS_INDEX_URL = (
    "https://www.nass.usda.gov/Statistics_by_State/Florida/Publications/Citrus/"
    "Citrus_Statistics/index.php"
)
_SUMMARY_INDEX_URL = (
    "https://www.nass.usda.gov/Statistics_by_State/Florida/Publications/Citrus/"
    "Citrus_Summary/index.php"
)

_MANIFEST_PATH = (
    Path(__file__).parent.parent.parent
    / "configs"
    / "sources"
    / "usda_nass_citrus_manifest.yaml"
)

_PDF_MAGIC = b"%PDF"
_REQUEST_TIMEOUT_S = 60

_SEASON_FROM_URL_RE = re.compile(r"/(\d{4}-\d{2})/")
_SEASON_FROM_TEXT_RE = re.compile(r"(\d{4}-\d{2})")
_STATS_DATE_RE = re.compile(r"^(\d{2}/\d{2}/\d{2}):")

# Month-name typos seen on live nass.usda.gov pages
_MONTH_TYPOS: dict[str, str] = {
    "Janurary": "January",
    "janurary": "January",
}

_DATE_FORMATS = [
    "%B %d, %Y",  # "October 11, 2024"
    "%B %d,%Y",   # "March 08,2019"  — no space before year
    "%B, %Y",     # "July, 2018"     — no day; will use 1st of month
    "%B %Y",      # "July 2018"      — no comma
]

_ALL_REPORT_TYPES: frozenset[str] = frozenset({
    "monthly_forecast",
    "maturity_test",
    "freeze_damage",
    "annual_statistics",
    "citrus_summary_prelim",
    "citrus_summary_final",
})

_REPORT_TYPE_CHOICES = [
    "forecast", "maturity", "freeze", "statistics",
    "summary-prelim", "summary-final", "all",
]

_REPORT_TYPE_MAP: dict[str, frozenset[str]] = {
    "forecast":      frozenset({"monthly_forecast"}),
    "maturity":      frozenset({"maturity_test"}),
    "freeze":        frozenset({"freeze_damage"}),
    "statistics":    frozenset({"annual_statistics"}),
    "summary-prelim": frozenset({"citrus_summary_prelim"}),
    "summary-final": frozenset({"citrus_summary_final"}),
    "all":           _ALL_REPORT_TYPES,
}

# Abbreviated month names seen in Summary index link text
_MONTH_ABBR_MAP: dict[str, str] = {
    "Jan.": "January", "Feb.": "February", "Mar.": "March",
    "Apr.": "April",   "May.": "May",      "Jun.": "June",
    "Jul.": "July",    "Aug.": "August",   "Sept.": "September",
    "Sep.": "September", "Oct.": "October", "Nov.": "November",
    "Dec.": "December",
}


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _download_pdf(
    url: str,
    session: requests.Session,
    timeout: int = _REQUEST_TIMEOUT_S,
) -> bytes:
    resp = session.get(url, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return resp.content


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _season_from_url(url: str) -> str:
    """Extract YYYY-YY season string from a URL path component."""
    m = _SEASON_FROM_URL_RE.search(url)
    return m.group(1) if m else ""


def _season_from_text(text: str) -> str:
    """Extract YYYY-YY season string from link text."""
    m = _SEASON_FROM_TEXT_RE.search(text)
    return m.group(1) if m else ""


def _parse_release_date(raw: str) -> str:
    """Parse a date fragment and return YYYYMMDD, or '' on failure.

    Handles formats like:
        "October 11, 2024"  →  "20241011"
        "July, 2018"        →  "20180701"
        "March 08,2019"     →  "20190308"

    Fixes known page typos (e.g. "Janurary") and rejects implausible years.
    """
    for wrong, right in _MONTH_TYPOS.items():
        raw = raw.replace(wrong, right)
    raw = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(raw, fmt)
            if not (1990 <= dt.year <= 2035):
                continue
            return dt.strftime("%Y%m%d")
        except ValueError:
            continue
    return ""


def _classify_forecast_link(href: str, link_text: str) -> str:
    """Return report_type for a link found on Citrus_Forecast/history.php.

    Classification priority:
      1. Filename prefix mat* → maturity_test
      2. Filename prefix frz* → freeze_damage
      3. "Maturity Test" in link text → maturity_test
      4. "Freeze Damage" in link text → freeze_damage
      5. Default → monthly_forecast
    """
    filename = href.rsplit("/", 1)[-1].lower()
    text_lower = link_text.lower()
    if filename.startswith("mat") or "maturity test" in text_lower:
        return "maturity_test"
    if filename.startswith("frz") or "freeze damage" in text_lower:
        return "freeze_damage"
    return "monthly_forecast"


# ---------------------------------------------------------------------------
# Discovery — Forecast series (Citrus_Forecast/history.php)
# ---------------------------------------------------------------------------

def _discover_forecast_series(session: requests.Session) -> list[dict[str, Any]]:
    """Scrape history.php and return entries for all three forecast series types."""
    logger.info("Scraping forecast history: %s", _FORECAST_HISTORY_URL)
    resp = session.get(_FORECAST_HISTORY_URL, timeout=_REQUEST_TIMEOUT_S)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for tag in soup.find_all("a", href=True):
        href: str = tag["href"]
        full_url = urljoin(_FORECAST_HISTORY_URL, href)
        if "/Citrus_Forecast/" not in full_url or not full_url.lower().endswith(".pdf"):
            continue
        link_text = tag.get_text(strip=True)
        season = _season_from_url(full_url)
        if not season:
            continue
        filename = full_url.rsplit("/", 1)[-1]
        report_type = _classify_forecast_link(full_url, link_text)
        release_date = _parse_release_date(link_text)
        key = (report_type, season, filename)
        if key in seen:
            continue
        seen.add(key)
        entries.append({
            "report_type": report_type,
            "season": season,
            "release_date": release_date,
            "pdf_url": full_url,
            "filename": filename,
        })

    entries.sort(key=lambda e: (e["season"], e["filename"]), reverse=True)
    counts = {
        rt: sum(1 for e in entries if e["report_type"] == rt)
        for rt in ("monthly_forecast", "maturity_test", "freeze_damage")
    }
    logger.info(
        "Forecast series: %d total (forecast=%d  maturity=%d  freeze=%d)",
        len(entries),
        counts.get("monthly_forecast", 0),
        counts.get("maturity_test", 0),
        counts.get("freeze_damage", 0),
    )
    return entries


# ---------------------------------------------------------------------------
# Discovery — Annual Statistics (Citrus_Statistics/index.php)
# ---------------------------------------------------------------------------

def _discover_statistics(session: requests.Session) -> list[dict[str, Any]]:
    """Scrape Citrus_Statistics/index.php and return annual_statistics entries."""
    logger.info("Scraping statistics index: %s", _STATISTICS_INDEX_URL)
    resp = session.get(_STATISTICS_INDEX_URL, timeout=_REQUEST_TIMEOUT_S)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    for tag in soup.find_all("a", href=True):
        href: str = tag["href"]
        full_url = urljoin(_STATISTICS_INDEX_URL, href)
        if "/Citrus_Statistics/" not in full_url or not full_url.lower().endswith(".pdf"):
            continue
        link_text = tag.get_text(strip=True)
        filename = full_url.rsplit("/", 1)[-1]
        if filename in seen:
            continue
        seen.add(filename)
        season = _season_from_url(full_url) or _season_from_text(link_text)
        if not season:
            continue

        # Link text format: "02/18/25: FL Citrus Statistics 2023-24"
        release_date = ""
        m = _STATS_DATE_RE.match(link_text)
        if m:
            try:
                dt = datetime.strptime(m.group(1), "%m/%d/%y")
                if 1990 <= dt.year <= 2035:
                    release_date = dt.strftime("%Y%m%d")
            except ValueError:
                pass

        entries.append({
            "report_type": "annual_statistics",
            "season": season,
            "release_date": release_date,
            "pdf_url": full_url,
            "filename": filename,
        })

    entries.sort(key=lambda e: e["season"], reverse=True)
    logger.info("Statistics series: %d entries", len(entries))
    return entries


# ---------------------------------------------------------------------------
# Discovery — Citrus Summary (Citrus_Summary/index.php)
# ---------------------------------------------------------------------------

def _discover_summary(session: requests.Session) -> list[dict[str, Any]]:
    """Scrape Citrus_Summary/index.php and return prelim and final summary entries."""
    logger.info("Scraping summary index: %s", _SUMMARY_INDEX_URL)
    resp = session.get(_SUMMARY_INDEX_URL, timeout=_REQUEST_TIMEOUT_S)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    for tag in soup.find_all("a", href=True):
        href: str = tag["href"]
        full_url = urljoin(_SUMMARY_INDEX_URL, href)
        if "/Citrus_Summary/" not in full_url or not full_url.lower().endswith(".pdf"):
            continue
        link_text = tag.get_text(strip=True)
        filename = full_url.rsplit("/", 1)[-1]
        if filename in seen:
            continue
        seen.add(filename)
        season = _season_from_url(full_url) or _season_from_text(link_text)
        if not season:
            continue

        # Classify by URL path component
        if "Citrus_Summary_Prelim" in full_url:
            report_type = "citrus_summary_prelim"
        else:
            report_type = "citrus_summary_final"

        # Parse release date from the link text remainder
        # e.g. "Citrus Summary 2023-24, Prelim. Sept. 2024"
        #      "Citrus Summary 2004-05, April 2006"
        release_date = ""
        remainder = re.sub(
            r"^Citrus Summary \d{4}-\d{2}[,.]?\s*",
            "",
            link_text,
            flags=re.IGNORECASE,
        )
        remainder = re.sub(r"Prelim\.?\s*", "", remainder, flags=re.IGNORECASE)
        for abbr, full in _MONTH_ABBR_MAP.items():
            remainder = remainder.replace(abbr, full)
        remainder = remainder.strip().strip(",.")
        if remainder:
            release_date = _parse_release_date(remainder)

        entries.append({
            "report_type": report_type,
            "season": season,
            "release_date": release_date,
            "pdf_url": full_url,
            "filename": filename,
        })

    entries.sort(key=lambda e: (e["report_type"], e["season"]), reverse=True)
    counts = {
        rt: sum(1 for e in entries if e["report_type"] == rt)
        for rt in ("citrus_summary_prelim", "citrus_summary_final")
    }
    logger.info(
        "Summary series: %d total (prelim=%d  final=%d)",
        len(entries),
        counts.get("citrus_summary_prelim", 0),
        counts.get("citrus_summary_final", 0),
    )
    return entries


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def _load_manifest() -> list[dict[str, Any]]:
    data = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8"))
    reports: list[dict[str, Any]] = data.get("reports") or []
    logger.info("Manifest: loaded %d entries from %s", len(reports), _MANIFEST_PATH.name)
    return reports


def _save_manifest(reports: list[dict[str, Any]]) -> None:
    """Write the manifest YAML, preserving the header comment block."""
    header_lines: list[str] = []
    for line in _MANIFEST_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.strip() == "":
            header_lines.append(line)
        else:
            break
    with _MANIFEST_PATH.open("w", encoding="utf-8") as fh:
        fh.write("\n".join(header_lines) + "\n\n")
        fh.write("reports:\n\n")
        for r in reports:
            fh.write(f"  - report_type: {r['report_type']}\n")
            fh.write(f"    season: \"{r['season']}\"\n")
            fh.write(f"    release_date: \"{r.get('release_date', '')}\"\n")
            fh.write(f"    pdf_url: \"{r['pdf_url']}\"\n")
            fh.write(f"    filename: \"{r['filename']}\"\n")
            fh.write("\n")


def _discover_and_update_manifest(session: requests.Session) -> None:
    """Scrape all three NASS Citrus index pages and update the manifest."""
    new_reports: list[dict[str, Any]] = []
    new_reports.extend(_discover_forecast_series(session))
    new_reports.extend(_discover_statistics(session))
    new_reports.extend(_discover_summary(session))

    if not new_reports:
        logger.warning("Discovery: no entries found — check network connectivity.")
        return

    existing = _load_manifest()
    existing_by_key: dict[str, dict[str, Any]] = {
        f"{r['report_type']}/{r['season']}/{r['filename']}": r
        for r in existing
    }

    added = updated = 0
    for report in new_reports:
        key = f"{report['report_type']}/{report['season']}/{report['filename']}"
        if key not in existing_by_key:
            existing_by_key[key] = report
            added += 1
        elif not existing_by_key[key].get("release_date") and report.get("release_date"):
            existing_by_key[key]["release_date"] = report["release_date"]
            updated += 1

    # Sort: newest season first, then by report_type, then filename
    merged = sorted(
        existing_by_key.values(),
        key=lambda r: (r["season"], r["report_type"], r["filename"]),
        reverse=True,
    )
    _save_manifest(merged)

    total_counts = {
        rt: sum(1 for r in merged if r["report_type"] == rt)
        for rt in sorted(_ALL_REPORT_TYPES)
    }
    logger.info(
        "Manifest: %d added, %d updated, %d total → %s",
        added,
        updated,
        len(merged),
        "  ".join(f"{rt}={n}" for rt, n in total_counts.items()),
    )


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def _upload_report(
    entry: dict[str, Any],
    bucket: str,
    region: str,
    session: requests.Session,
    skip_existing: bool,
    sleep_seconds: float,
) -> str:
    """Download one PDF and upload to raw S3.  Returns 'uploaded', 'skipped', or 'error'."""
    report_type = entry["report_type"]
    season = entry["season"]
    filename = entry["filename"]
    pdf_url = entry["pdf_url"]
    s3_key = raw_nass_citrus_key(season, report_type, filename)

    try:
        if skip_existing and s3_object_exists(bucket, s3_key, region):
            logger.info("Skipping — already in S3: %s", s3_key)
            time.sleep(sleep_seconds)
            return "skipped"

        logger.info("Downloading %s / %s  %s …", report_type, season, pdf_url)
        pdf_bytes = _download_pdf(pdf_url, session)

        if not pdf_bytes.startswith(_PDF_MAGIC):
            raise RuntimeError(
                f"Response is not a valid PDF (missing %PDF header): {pdf_url}"
            )
        check_min_file_size(pdf_bytes, "usda_nass_citrus", context=pdf_url)

        upload_bytes_to_s3(pdf_bytes, bucket, s3_key, region)
        write_raw_s3_metadata(
            bucket, s3_key, pdf_bytes, pdf_url, "application/pdf", region
        )
        logger.info(
            "Uploaded %s/%s  (%.1f KB)  →  s3://%s/%s",
            report_type,
            season,
            len(pdf_bytes) / 1024,
            bucket,
            s3_key,
        )
        time.sleep(sleep_seconds)
        return "uploaded"

    except Exception as exc:  # noqa: BLE001 — any download, validation, or S3 error is logged; caller checks return value
        logger.error("Failed %s/%s (%s): %s", report_type, season, pdf_url, exc)
        time.sleep(sleep_seconds)
        return "error"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(
        description=(
            "Download USDA NASS Florida Citrus PDFs to raw S3. "
            "Six series: monthly_forecast, maturity_test, freeze_damage, "
            "annual_statistics, citrus_summary_prelim, citrus_summary_final."
        )
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help=(
            "Scrape NASS Citrus index pages to discover all PDF URLs and update "
            "configs/sources/usda_nass_citrus_manifest.yaml. "
            "No AWS credentials required."
        ),
    )
    parser.add_argument(
        "--report-type",
        choices=_REPORT_TYPE_CHOICES,
        default="all",
        help="Which report type(s) to process (default: all).",
    )
    parser.add_argument(
        "--season",
        metavar="YYYY-YY",
        default=None,
        help="Process only entries for this season, e.g. 2024-25.",
    )
    parser.add_argument(
        "--current-season",
        action="store_true",
        help=(
            "Season-scoped chain mode: derive the CURRENT open forecast season from --asof (or "
            "today), discover that season's monthly_forecast PDFs LIVE (independent of the baked "
            "manifest), and upload them. This is the fetch phase of the citrus SFN chain."
        ),
    )
    parser.add_argument(
        "--asof",
        default=None,
        help="Scheduled-time ISO used by --current-season to derive the open season.",
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help="Skip PDFs whose S3 key already exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print S3 keys without downloading anything.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=1.0,
        help="Polite delay between HTTP requests in seconds (default: 1.0).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process at most N PDFs — use 1-5 for smoke tests.",
    )
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    if args.discover:
        _discover_and_update_manifest(session)
        return

    if args.current_season:
        # Chain fetch phase: never trust the baked manifest to be current -- discover the open
        # season's monthly_forecast PDFs live so genuinely new releases are picked up each fire.
        season = current_forecast_season(args.asof)
        entries = [
            e for e in _discover_forecast_series(session)
            if e["report_type"] == "monthly_forecast" and e["season"] == season
        ]
        logger.info("current-season mode: season=%s  discovered %d monthly_forecast entries",
                    season, len(entries))
    else:
        entries = _load_manifest()
        # Filter by --report-type
        allowed_types = _REPORT_TYPE_MAP[args.report_type]
        entries = [e for e in entries if e["report_type"] in allowed_types]
        # Filter by --season
        if args.season:
            entries = [e for e in entries if e["season"] == args.season]

    if not entries:
        logger.warning("No entries to process after filtering.")
        return

    if args.limit:
        entries = entries[: args.limit]

    if args.dry_run:
        print(f"Would process {len(entries)} PDFs:")
        for e in entries:
            s3_key = raw_nass_citrus_key(e["season"], e["report_type"], e["filename"])
            print(
                f"  {e['report_type']}/{e['season']}  {e['filename']}"
                f"  →  {s3_key}"
            )
        return

    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    uploaded = skipped = errors = 0
    for entry in entries:
        result = _upload_report(
            entry,
            bucket,
            region,
            session,
            skip_existing=args.skip_existing_s3,
            sleep_seconds=args.sleep_seconds,
        )
        if result == "uploaded":
            uploaded += 1
        elif result == "skipped":
            skipped += 1
        else:
            errors += 1

    logger.info(
        "Done. uploaded=%d  skipped=%d  errors=%d", uploaded, skipped, errors
    )


if __name__ == "__main__":
    main()
