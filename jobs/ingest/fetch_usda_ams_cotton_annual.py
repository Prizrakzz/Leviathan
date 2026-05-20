"""Fetch USDA AMS Cotton Annual Quality Report PDFs to raw S3.

Two sources covering 1986-present:

  Source A — Archive (1986–2013)
    Static IIS directory listing at:
      https://apps.ams.usda.gov/Cotton/AnnualCNMarketNewsReports/Quality/
    Crawled with BeautifulSoup; yields files like 1986ACQ.pdf … 2013ACQ.pdf.
    Plain requests (no WAF on static gov server).

  Source B — MyMarketNews slug 1658 (~2013–present)
    Annual Cotton Quality Report (CNAACQ).  Historical PDF URLs are discovered
    via a Playwright scrape of:
      https://mymarketnews.ams.usda.gov/viewReport/1658
    which expands "Previous Releases" decade accordion sections.  Discovered
    URLs are written to configs/sources/usda_ams_cotton_annual_manifest.yaml.

Modes
-----
--discover  (requires ``playwright[chromium]``, installed via the [biweekly] extra)
    Playwright headless scrape of viewReport/1658 → write/update manifest YAML.
    Run once to seed the manifest; subsequent normal runs use the manifest.

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
import re
import time
from pathlib import Path
from typing import Any

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
_VIEW_REPORT_URL = "https://mymarketnews.ams.usda.gov/viewReport/1658"
_FILEREPO_BASE = "https://mymarketnews.ams.usda.gov"

_MANIFEST_PATH = (
    Path(__file__).parent.parent.parent
    / "configs"
    / "sources"
    / "usda_ams_cotton_annual_manifest.yaml"
)

_PDF_MAGIC = b"%PDF"
_REQUEST_TIMEOUT_S = 60
_PLAYWRIGHT_TIMEOUT_MS = 30_000

_ARCHIVE_FILENAME_RE = re.compile(r"(\d{4})ACQ\.pdf", re.IGNORECASE)
_FILEREPO_PATH_RE = re.compile(
    r"/filerepo/sites/default/files/1658/(\d{4})-\d{2}-\d{2}/\d+/([^\"'\s]+\.pdf)"
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
# --discover  (Playwright)
# ---------------------------------------------------------------------------

def _discover_and_update_manifest() -> None:
    """Scrape viewReport/1658 with Playwright, update the manifest YAML."""
    import asyncio

    new_reports = asyncio.run(_discover_async())

    if not new_reports:
        logger.info("Playwright: no new reports discovered.")
        return

    # Merge with existing manifest (de-duplicate by season_year)
    existing_data = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8")) or {}
    existing: list[dict[str, Any]] = existing_data.get("reports") or []
    existing_years = {int(r["season_year"]) for r in existing}

    added = 0
    for report in new_reports:
        if int(report["season_year"]) not in existing_years:
            existing.append(report)
            existing_years.add(int(report["season_year"]))
            added += 1
            logger.info(
                "Manifest: adding season_year=%d  %s",
                report["season_year"],
                report["filename"],
            )

    existing.sort(key=lambda r: r["season_year"], reverse=True)

    # Preserve the header comment then dump updated reports list
    header_lines: list[str] = []
    for line in _MANIFEST_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.strip() == "":
            header_lines.append(line)
        else:
            break

    with _MANIFEST_PATH.open("w", encoding="utf-8") as fh:
        fh.write("\n".join(header_lines) + "\n\n")
        fh.write("reports:\n\n")
        for report in existing:
            fh.write(f"  - season_year: {report['season_year']}\n")
            fh.write(f"    report_begin_date: \"{report['report_begin_date']}\"\n")
            fh.write(f"    pdf_url: \"{report['pdf_url']}\"\n")
            fh.write(f"    filename: \"{report['filename']}\"\n\n")

    logger.info(
        "Manifest updated: %d new entries added, %d total",
        added,
        len(existing),
    )


async def _discover_async() -> list[dict[str, Any]]:
    """Playwright scrape of viewReport/1658. Returns list of discovered report dicts."""
    from playwright.async_api import async_playwright

    found: list[dict[str, Any]] = []
    seen_years: set[int] = set()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()

        logger.info("Playwright: navigating to %s", _VIEW_REPORT_URL)
        await page.goto(
            _VIEW_REPORT_URL,
            wait_until="networkidle",
            timeout=_PLAYWRIGHT_TIMEOUT_MS,
        )

        def _extract_links_from_html(html: str) -> list[dict[str, Any]]:
            """Parse all filerepo/1658 PDF links from page HTML."""
            results = []
            for m in _FILEREPO_PATH_RE.finditer(html):
                year_str, fname = m.group(1), m.group(2)
                season_year = int(year_str)
                if season_year in seen_years:
                    continue
                # Reconstruct the full filerepo path from the HTML
                full_match = m.group(0)  # e.g. /filerepo/sites/default/files/1658/2024-07-01/1254489/ams_1658_00010.pdf
                pdf_url = _FILEREPO_BASE + full_match
                # report_begin_date is the date component in the URL path
                date_m = re.search(r"/1658/(\d{4}-\d{2}-\d{2})/", full_match)
                report_begin_date = date_m.group(1) if date_m else f"{season_year}-07-01"
                results.append({
                    "season_year": season_year,
                    "report_begin_date": report_begin_date,
                    "pdf_url": pdf_url,
                    "filename": fname,
                })
                seen_years.add(season_year)
            return results

        # Collect links from initial page load
        html = await page.content()
        initial = _extract_links_from_html(html)
        found.extend(initial)
        logger.info("Playwright: found %d links on initial page load", len(initial))

        # Expand any collapsed "Previous Releases" accordion sections
        # Look for buttons/elements with aria-expanded="false" or text like "2020s"/"2010s"
        expand_selectors = [
            "button[aria-expanded='false']",
            "a[aria-expanded='false']",
            "[data-toggle='collapse']:not(.collapsed)",
            ".accordion-button.collapsed",
        ]
        for selector in expand_selectors:
            try:
                elements = await page.locator(selector).all()
                for el in elements:
                    try:
                        text = (await el.inner_text()).strip()
                        logger.info("Playwright: clicking expand element: %r", text[:60])
                        await el.click()
                        await page.wait_for_timeout(800)
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("Playwright: click failed (%s)", exc)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Playwright: selector %r failed (%s)", selector, exc)

        # Re-collect links after expansion
        html = await page.content()
        expanded = _extract_links_from_html(html)
        found.extend(expanded)
        logger.info("Playwright: found %d additional links after expansion", len(expanded))

        await browser.close()

    found.sort(key=lambda r: r["season_year"], reverse=True)
    logger.info("Playwright: discovered %d unique annual report entries", len(found))
    return found


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
    pdf_url = entry["pdf_url"]
    s3_key = raw_cotton_annual_key(season_year, filename)

    try:
        if skip_existing and s3_object_exists(bucket, s3_key, region):
            logger.info("Skipping — already in S3: %s", s3_key)
            time.sleep(sleep_seconds)
            return "skipped"

        logger.info("Downloading season=%d  %s …", season_year, pdf_url)
        pdf_bytes = _download_pdf(pdf_url, session)

        if not pdf_bytes.startswith(_PDF_MAGIC):
            raise RuntimeError(
                f"Response is not a valid PDF (missing %PDF header): {pdf_url}"
            )
        check_min_file_size(pdf_bytes, "usda_ams_cotton_classing_annual", context=pdf_url)

        upload_bytes_to_s3(pdf_bytes, bucket, s3_key, region)
        write_raw_s3_metadata(
            bucket, s3_key, pdf_bytes, pdf_url, "application/pdf", region
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

    except Exception as exc:  # noqa: BLE001
        logger.error("Failed season=%d (%s): %s", season_year, pdf_url, exc)
        time.sleep(sleep_seconds)
        return "error"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
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
            "Playwright scrape of mymarketnews.ams.usda.gov/viewReport/1658 "
            "to discover historical slug-1658 PDF URLs and update the manifest YAML. "
            "Requires playwright[chromium] (pip install leviathan[biweekly])."
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

    # --discover: scrape viewReport/1658, update manifest, then exit
    if args.discover:
        _discover_and_update_manifest()
        return

    # Build combined entry list
    headers = {"User-Agent": "Mozilla/5.0"}
    session = requests.Session()
    session.headers.update(headers)

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
