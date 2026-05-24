"""Fetch USDA AMS Cotton Annual Quality Report PDFs to raw S3.

Two sources covering 1986-present:

  Source A — Archive (1986–1998)
    Static IIS directory listing at:
      https://apps.ams.usda.gov/Cotton/AnnualCNMarketNewsReports/Quality/
    Crawled with BeautifulSoup; yields files like 1986ACQ.pdf … 1998ACQ.pdf.
    Plain requests (no WAF on static gov server).

  Source B — MyMarketNews slug 1658 / live cnaacq.pdf (2008–present)
    Annual Cotton Quality Report (CNAACQ).  Historical PDF URLs are discovered
    via the Wayback Machine CDX API (mymarketnews.ams.usda.gov blocks all
    programmatic HTTP connections).  The current-season report is downloaded
    directly from www.ams.usda.gov/mnreports/cnaacq.pdf (different, accessible
    server).
    Discovered URLs are written to
      configs/sources/usda_ams_cotton_annual_manifest.yaml
    which stores a ``download_url`` field (Wayback archive URL or direct) in
    addition to the canonical ``pdf_url``.

Modes
-----
--discover
    Query Wayback CDX API for filerepo/1658 PDFs (2017-present) and
    for unique cnaacq.pdf snapshots (2008-2016 gap).  Add current-season
    live cnaacq.pdf entry.  Write/update the manifest YAML.  No Playwright
    or AWS credentials required.

Normal (no --discover)
    Download from both Source A (live directory crawl) and Source B (manifest).
    Use ``--source`` to restrict: archive | mymarketnews | all  (default: all).

Idempotency
-----------
Pass ``--skip-existing-s3`` (recommended) to skip PDFs already in S3.
Add ``--dry-run`` to print URLs without downloading anything.
"""
from __future__ import annotations

import argparse
import logging
import re
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import requests
import yaml
from bs4 import BeautifulSoup

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_cotton_annual_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ARCHIVE_URL = (
    "https://apps.ams.usda.gov/Cotton/AnnualCNMarketNewsReports/Quality/"
)
_CNAACQ_URL = "https://www.ams.usda.gov/mnreports/cnaacq.pdf"
_WAYBACK_CDX_URL = "http://web.archive.org/cdx/search/cdx"

_MANIFEST_PATH = (
    Path(__file__).parent.parent.parent
    / "configs"
    / "sources"
    / "usda_ams_cotton_annual_manifest.yaml"
)

_PDF_MAGIC = b"%PDF"
_REQUEST_TIMEOUT_S = 60

_ARCHIVE_FILENAME_RE = re.compile(r"(\d{4})ACQ\.pdf", re.IGNORECASE)
_FILEREPO_PATH_RE = re.compile(
    r"/filerepo/sites/default/files/1658/(\d{4})-\d{2}-\d{2}/(\d+)/([^?\"'\s]+\.pdf)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# HTTP download
# ---------------------------------------------------------------------------

def _download_pdf(url: str, session: requests.Session, timeout: int = _REQUEST_TIMEOUT_S) -> bytes:
    """Download a PDF from a URL using a plain requests session."""
    resp = session.get(url, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return resp.content


# ---------------------------------------------------------------------------
# Source A — Archive directory crawl
# ---------------------------------------------------------------------------

def _crawl_archive(session: requests.Session) -> list[dict[str, Any]]:
    """GET the archive directory listing and enumerate all {YEAR}ACQ.pdf entries.

    Returns a list of dicts with keys: season_year, pdf_url, filename.
    """
    logger.info("Crawling archive directory: %s", _ARCHIVE_URL)
    resp = session.get(_ARCHIVE_URL, timeout=_REQUEST_TIMEOUT_S)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    entries: list[dict[str, Any]] = []

    for tag in soup.find_all("a", href=True):
        href: str = tag["href"]
        m = _ARCHIVE_FILENAME_RE.search(href)
        if not m:
            continue
        season_year = int(m.group(1))
        filename = m.group(0)  # e.g. "1986ACQ.pdf"
        # href may be relative ("1986ACQ.pdf") or absolute
        if href.startswith("http"):
            pdf_url = href
        else:
            pdf_url = _ARCHIVE_URL.rstrip("/") + "/" + filename
        entries.append(
            {"season_year": season_year, "pdf_url": pdf_url, "filename": filename}
        )

    entries.sort(key=lambda e: e["season_year"])
    logger.info("Archive: found %d PDFs (%d–%d)", len(entries),
                entries[0]["season_year"] if entries else 0,
                entries[-1]["season_year"] if entries else 0)
    return entries


# ---------------------------------------------------------------------------
# Source B — Manifest load
# ---------------------------------------------------------------------------

def _load_manifest() -> list[dict[str, Any]]:
    """Read configs/sources/usda_ams_cotton_annual_manifest.yaml."""
    data = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8"))
    reports: list[dict[str, Any]] = data.get("reports") or []
    logger.info("Manifest: loaded %d entries from %s", len(reports), _MANIFEST_PATH.name)
    return reports


# ---------------------------------------------------------------------------
# --discover  (Wayback CDX API)
# ---------------------------------------------------------------------------

def _wayback_cdx(
    session: requests.Session,
    url_pattern: str,
    fl: str,
    extra_params: dict[str, Any] | None = None,
) -> list[list[str]]:
    """Query the Wayback Machine CDX API.  Returns data rows (header stripped)."""
    params: dict[str, Any] = {
        "url": url_pattern,
        "output": "json",
        "fl": fl,
    }
    if extra_params:
        params.update(extra_params)
    resp = session.get(_WAYBACK_CDX_URL, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data[1:] if len(data) > 1 else []  # skip header row


def _discover_via_wayback(session: requests.Session) -> list[dict[str, Any]]:
    """Query Wayback CDX to enumerate annual cotton quality PDFs.

    Part 1 — filerepo/1658 PDFs archived by Wayback (2017-present):
        One entry per season_year; picks the highest node-ID URL variant
        (most recent file version) and wraps it in a Wayback ``if_`` URL.

    Part 2 — /mnreports/cnaacq.pdf unique versions (2008-2016 gap fill):
        Uses ``collapse=digest`` to get one row per unique file.  Season year
        is derived from the month of the first-seen timestamp (≥6 → same year).

    Part 3 — live cnaacq.pdf for the current season:
        Direct download from www.ams.usda.gov (no Wayback needed).
    """
    reports: list[dict[str, Any]] = []
    seen_years: set[int] = set()

    # ---- Part 1: filerepo/1658 Wayback snapshots ----
    logger.info("Wayback CDX: querying filerepo/1658 PDFs...")
    filerepo_rows = _wayback_cdx(
        session,
        "mymarketnews.ams.usda.gov/filerepo/sites/default/files/1658/*",
        fl="original,timestamp,statuscode",
        extra_params={"filter": "statuscode:200", "limit": "500", "collapse": "original"},
    )

    # Pick highest node-ID entry per season_year (most recent/canonical)
    best: dict[int, dict[str, Any]] = {}
    for original, timestamp, _status in filerepo_rows:
        if ".pdf" not in original.lower():
            continue
        m = _FILEREPO_PATH_RE.search(original)
        if not m:
            continue
        year = int(m.group(1))
        node_id = int(m.group(2))
        filename = unquote(m.group(3))
        date_m = re.search(r"/1658/(\d{4}-\d{2}-\d{2})/", original)
        if year not in best or node_id > best[year]["_node_id"]:
            best[year] = {
                "season_year": year,
                "report_begin_date": date_m.group(1) if date_m else f"{year}-07-01",
                "pdf_url": original,
                "filename": filename,
                "download_url": f"https://web.archive.org/web/{timestamp}if_/{original}",
                "_node_id": node_id,
            }

    for year in sorted(best):
        entry = {k: v for k, v in best[year].items() if not k.startswith("_")}
        reports.append(entry)
        seen_years.add(year)
        logger.info("Wayback CDX: filerepo season=%d  %s", year, entry["filename"])

    # ---- Part 2: cnaacq.pdf unique versions (gap fill) ----
    logger.info("Wayback CDX: querying cnaacq.pdf unique versions...")
    cnaacq_rows = _wayback_cdx(
        session,
        "www.ams.usda.gov/mnreports/cnaacq.pdf",
        fl="timestamp,length,statuscode",
        extra_params={"filter": "statuscode:200", "collapse": "digest", "limit": "100"},
    )

    for timestamp, _length, _status in cnaacq_rows:
        ts_year = int(timestamp[:4])
        ts_month = int(timestamp[4:6])
        # Published late June/early July; snapshot month ≥6 → that year's report
        season_year = ts_year if ts_month >= 6 else ts_year - 1
        if season_year in seen_years:
            continue
        wayback_url = f"https://web.archive.org/web/{timestamp}if_/{_CNAACQ_URL}"
        reports.append({
            "season_year": season_year,
            "report_begin_date": f"{season_year}-07-01",
            "pdf_url": _CNAACQ_URL,
            "filename": f"cnaacq_{season_year}.pdf",
            "download_url": wayback_url,
        })
        seen_years.add(season_year)
        logger.info(
            "Wayback CDX: cnaacq.pdf season=%d  (snapshot %s)", season_year, timestamp[:8]
        )

    # ---- Part 3: live cnaacq.pdf for the current season ----
    today = date.today()
    current_season = today.year if today.month >= 7 else today.year - 1
    if current_season not in seen_years:
        reports.append({
            "season_year": current_season,
            "report_begin_date": f"{current_season}-07-01",
            "pdf_url": _CNAACQ_URL,
            "filename": f"cnaacq_{current_season}.pdf",
            # download_url == pdf_url (direct, no Wayback needed)
        })
        seen_years.add(current_season)
        logger.info("Live cnaacq.pdf: current season=%d", current_season)

    reports.sort(key=lambda r: r["season_year"], reverse=True)
    logger.info(
        "Wayback discover: %d entries, years %s",
        len(reports),
        sorted(seen_years),
    )
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
        for report in reports:
            fh.write(f"  - season_year: {report['season_year']}\n")
            fh.write(f"    report_begin_date: \"{report['report_begin_date']}\"\n")
            fh.write(f"    pdf_url: \"{report['pdf_url']}\"\n")
            fh.write(f"    filename: \"{report['filename']}\"\n")
            dl = report.get("download_url")
            if dl and dl != report["pdf_url"]:
                fh.write(f"    download_url: \"{dl}\"\n")
            fh.write("\n")


def _discover_and_update_manifest(session: requests.Session) -> None:
    """Query Wayback CDX to discover historical PDFs and update the manifest."""
    new_reports = _discover_via_wayback(session)
    if not new_reports:
        logger.info("Wayback discover: no entries found.")
        return

    existing = _load_manifest()
    existing_by_year: dict[int, dict[str, Any]] = {
        int(r["season_year"]): r for r in existing
    }

    added = updated = 0
    for report in new_reports:
        year = int(report["season_year"])
        if year not in existing_by_year:
            existing_by_year[year] = report
            added += 1
            logger.info("Manifest: +season=%d  %s", year, report["filename"])
        elif not existing_by_year[year].get("download_url"):
            # Existing entry has no download_url — update with Wayback info
            existing_by_year[year] = report
            updated += 1
            logger.info("Manifest: updated season=%d with download_url", year)

    merged = sorted(existing_by_year.values(), key=lambda r: r["season_year"], reverse=True)
    _save_manifest(merged)
    logger.info(
        "Manifest: %d added, %d updated, %d total", added, updated, len(merged)
    )


# ---------------------------------------------------------------------------
# Upload helper
# ---------------------------------------------------------------------------

def _upload_report(
    entry: dict[str, Any],
    bucket: str,
    region: str,
    session: requests.Session,
    skip_existing: bool,
    sleep_seconds: float,
) -> str:
    """Download one PDF and upload to S3.  Returns 'uploaded', 'skipped', or 'error'."""
    season_year = int(entry["season_year"])
    filename = entry["filename"]
    canonical_url = entry["pdf_url"]
    # Use download_url (Wayback or direct) if provided, else fall back to pdf_url
    download_url = entry.get("download_url") or canonical_url
    s3_key = raw_cotton_annual_key(season_year, filename)

    try:
        if skip_existing and s3_object_exists(bucket, s3_key, region):
            logger.info("Skipping — already in S3: %s", s3_key)
            time.sleep(sleep_seconds)
            return "skipped"

        logger.info("Downloading season=%d  %s …", season_year, download_url)
        pdf_bytes = _download_pdf(download_url, session)

        if not pdf_bytes.startswith(_PDF_MAGIC):
            raise RuntimeError(
                f"Response is not a valid PDF (missing %PDF header): {download_url}"
            )
        check_min_file_size(pdf_bytes, "usda_ams_cotton_classing_annual", context=download_url)

        upload_bytes_to_s3(pdf_bytes, bucket, s3_key, region)
        write_raw_s3_metadata(
            bucket, s3_key, pdf_bytes, canonical_url, "application/pdf", region
        )
        logger.info(
            "Uploaded season=%d  (%.1f MB) → s3://%s/%s",
            season_year,
            len(pdf_bytes) / 1_048_576,
            bucket,
            s3_key,
        )
        time.sleep(sleep_seconds)
        return "uploaded"

    except Exception as exc:  # noqa: BLE001 — any download, validation, or S3 error is logged; caller checks return value
        logger.error("Failed season=%d (%s): %s", season_year, download_url, exc)
        time.sleep(sleep_seconds)
        return "error"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(
        description=(
            "Download USDA AMS Cotton Annual Quality Report PDFs to raw S3. "
            "Covers 1986-present via archive directory (1986-2013) and "
            "MyMarketNews slug 1658 manifest (2013-present)."
        )
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help=(
            "Query Wayback Machine CDX API to discover historical slug-1658 "
            "PDF URLs and cnaacq.pdf snapshots; update the manifest YAML. "
            "No Playwright or AWS credentials required."
        ),
    )
    parser.add_argument(
        "--source",
        choices=["archive", "mymarketnews", "all"],
        default="all",
        help="Which source to download from (default: all).",
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help="Skip PDFs whose S3 key already exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print all URLs without downloading anything.",
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
        help="Process at most N PDFs — use 1 for a smoke test.",
    )
    args = parser.parse_args()

    # Build shared HTTP session
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    # --discover: query Wayback CDX, update manifest, then exit
    if args.discover:
        _discover_and_update_manifest(session)
        return

    entries: list[dict[str, Any]] = []

    if args.source in ("archive", "all"):
        archive_entries = _crawl_archive(session)
        entries.extend(archive_entries)

    if args.source in ("mymarketnews", "all"):
        manifest_entries = _load_manifest()
        entries.extend(manifest_entries)

    if not entries:
        logger.warning("No entries to process.")
        return

    if args.limit:
        entries = entries[: args.limit]

    # Dry run
    if args.dry_run:
        print(f"Would process {len(entries)} PDFs:")
        for e in entries:
            s3_key = raw_cotton_annual_key(int(e["season_year"]), e["filename"])
            print(f"  season={e['season_year']}  {e['filename']}  →  {s3_key}")
        return

    # Download & upload
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
