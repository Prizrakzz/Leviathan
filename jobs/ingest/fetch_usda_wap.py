"""Fetch USDA FAS World Agricultural Production (WAP) monthly PDFs to raw S3.

Published once a month (same day as WASDE, ~10th of each month) by USDA FAS.
Each release is a single PDF covering wheat, corn, rice, soybeans, cotton and
other oilseeds with country-level area / production / trade estimates.

Source
------
    https://www.fas.usda.gov/data/world-agricultural-production
    report_type = 13286  (286 releases as of May 2026)

URL patterns
------------
    Recent (2025–present): {CDN}/{YYYY-MM}/production.pdf
    2024:                  {CDN}/{YYYY-MM}/production - {Month} {YYYY}.pdf
    Pre-2024:              {CDN}/{migration-date}/{YYYY}-{Mon}-{Production|WAP}.pdf

    The CDN folder and filename vary unpredictably across years because USDA
    did a bulk CDN migration in mid-2025.  The only reliable approach is to
    scrape each report's landing page to obtain the actual PDF URL.
    Landing pages are Akamai-protected; uses ``curl_cffi`` with Chrome
    impersonation to bypass bot-detection.

S3 key structure
----------------
    raw/production/source=usda_wap/release_month={YYYY-MM}/production.pdf

Modes
-----
--discover
    Paginate the FAS search results for report type 13286 to collect all
    WAP landing-page URLs, then fetch each landing page to extract the real
    PDF download URL (which varies across years due to the 2025 CDN
    migration).  Results are written to
    ``configs/sources/usda_wap_manifest.yaml``.  No AWS credentials required.

Normal (no --discover)
    Load manifest and download/upload each PDF to raw S3.

Idempotency
-----------
Pass ``--skip-existing-s3`` to skip PDFs already in S3.
Pass ``--dry-run`` to print S3 keys without downloading anything.
"""
from __future__ import annotations

import argparse
import logging
import re
import time
from pathlib import Path

import yaml
from curl_cffi import requests as cr

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_wap_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CDN_BASE = "https://www.fas.usda.gov/sites/default/files"
_START_YM = (2003, 1)   # earliest month to probe; earlier months use a different archive
_PDF_MAGIC = b"%PDF"
_REQUEST_TIMEOUT_S = 60

_IMPERSONATE = "chrome136"

_MANIFEST_PATH = (
    Path(__file__).parent.parent.parent
    / "configs"
    / "sources"
    / "usda_wap_manifest.yaml"
)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_pdf(data: bytes, url: str) -> None:
    if data[:4] != _PDF_MAGIC:
        raise RuntimeError(
            f"Response from {url} is not a PDF (got {data[:4]!r})"
        )


def _fetch(url: str, timeout: int = _REQUEST_TIMEOUT_S, stream: bool = False) -> cr.Response:
    """GET with Chrome impersonation (curl_cffi) to bypass Akamai bot detection."""
    return cr.get(url, impersonate=_IMPERSONATE, timeout=timeout,
                  allow_redirects=True, stream=stream)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

# Regex for WAP landing-page slugs embedded in FAS search result pages.
_LANDING_RE = re.compile(
    r'href="(/data/world-agricultural-production-(\d{2})(\d{2})(\d{4}))"'
)
# Regex for the PDF link on each WAP landing page.
_PDF_RE = re.compile(
    r'href="(https?://(?:www\.)?fas\.usda\.gov/sites/default/files/[^"]+\.pdf[^"]*)"'
)
_SEARCH_URL = (
    "https://www.fas.usda.gov/data/search"
    "?reports%5B0%5D=report_type%3A13286&page={page}"
)
_MAX_SEARCH_PAGES = 35


def _discover(sleep_seconds: float) -> list[dict]:
    """
    Two-stage FAS website scrape to build the complete WAP manifest.

    Stage 1 — paginate through the FAS search results for report type 13286
    and collect every report landing-page URL (format:
    ``/data/world-agricultural-production-MMDDYYYY``).

    Stage 2 — fetch each landing page with Chrome impersonation and extract
    the real PDF download URL, which varies across years because USDA
    reorganised their CDN in mid-2025.
    """
    # ------------------------------------------------------------------
    # Stage 1: collect all landing-page paths via paginated search
    # ------------------------------------------------------------------
    landing_paths: list[tuple[str, str]] = []  # (path, release_month)
    for page in range(_MAX_SEARCH_PAGES):
        url = _SEARCH_URL.format(page=page)
        try:
            r = _fetch(url, timeout=20)
        except Exception as exc:  # noqa: BLE001 — any HTTP error stops this discovery page; loop breaks or continues
            logger.warning("Search page %d error: %s — stopping", page, exc)
            break
        if r.status_code != 200:
            logger.info("Search page %d → HTTP %s — stopping", page, r.status_code)
            break

        matches = _LANDING_RE.findall(r.text)
        if not matches:
            logger.info("Search page %d: no landing URLs found — done", page)
            break

        for path, mm, dd, yyyy in matches:
            release_month = f"{yyyy}-{mm}"
            landing_paths.append((path, release_month))

        logger.info(
            "Search page %d: %d landing URLs (total: %d)",
            page, len(matches), len(landing_paths),
        )
        time.sleep(sleep_seconds)

    logger.info("Stage 1 complete: %d landing pages", len(landing_paths))

    # ------------------------------------------------------------------
    # Stage 2: fetch each landing page to get the real PDF URL
    # ------------------------------------------------------------------
    confirmed: list[dict] = []
    for path, release_month in landing_paths:
        landing_url = f"https://www.fas.usda.gov{path}"
        try:
            r = _fetch(landing_url, timeout=20)
            if r.status_code != 200:
                logger.warning("  MISS   %s  HTTP %s", release_month, r.status_code)
                time.sleep(sleep_seconds)
                continue

            pdf_match = _PDF_RE.search(r.text)
            if pdf_match:
                pdf_url = pdf_match.group(1)
                # Normalise protocol-relative / non-www variants
                pdf_url = pdf_url.replace("//fas.usda.gov", "//www.fas.usda.gov")
                confirmed.append({"release_month": release_month, "url": pdf_url})
                logger.info("  FOUND  %s  →  %s", release_month, pdf_url)
            else:
                logger.warning(
                    "  MISS   %s  — no PDF link in %s", release_month, landing_url
                )
        except Exception as exc:  # noqa: BLE001 — any HTTP error on landing page fetch is logged; loop continues
            logger.warning("  ERROR  %s  %s: %s", release_month, landing_url, exc)
        time.sleep(sleep_seconds)

    confirmed.sort(key=lambda e: e["release_month"])
    logger.info(
        "Discovery complete: %d/%d months confirmed",
        len(confirmed), len(landing_paths),
    )
    return confirmed


def _save_manifest(entries: list[dict]) -> None:
    _MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _MANIFEST_PATH.open("w", encoding="utf-8") as fh:
        fh.write("# USDA FAS World Agricultural Production — monthly PDF archive\n")
        fh.write("# Generated by: python jobs/ingest/fetch_usda_wap.py --discover\n")
        fh.write("# URLs scraped from FAS landing pages (vary by year due to 2025 CDN migration)\n\n")
        fh.write("releases:\n\n")
        for e in entries:
            fh.write(f"  - release_month: \"{e['release_month']}\"\n")
            fh.write(f"    url: \"{e['url']}\"\n")
            fh.write("\n")
    logger.info("Manifest saved: %d entries → %s", len(entries), _MANIFEST_PATH)


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------

def _load_manifest() -> list[dict]:
    data = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8"))
    releases: list[dict] = data.get("releases") or []
    logger.info("Manifest: loaded %d entries from %s", len(releases), _MANIFEST_PATH.name)
    return releases


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def _upload_entry(
    entry: dict,
    bucket: str,
    region: str,
    skip_existing: bool,
    sleep_seconds: float,
) -> str:
    """Download one WAP PDF and upload to raw S3.  Returns 'uploaded', 'skipped', or 'error'."""
    ym = entry["release_month"]
    url = entry["url"]
    s3_key = raw_wap_key(ym)

    try:
        if skip_existing and s3_object_exists(bucket, s3_key, region):
            logger.info("Skipping - already in S3: %s", s3_key)
            time.sleep(sleep_seconds)
            return "skipped"

        logger.info("Downloading %s  %s ...", ym, url)
        resp = _fetch(url)
        resp.raise_for_status()
        data = resp.content

        _validate_pdf(data, url)
        check_min_file_size(data, "usda_wap", context=url)

        upload_bytes_to_s3(data, bucket, s3_key, region)
        write_raw_s3_metadata(bucket, s3_key, data, url, "application/pdf", region)

        logger.info(
            "Uploaded %s  (%.1f KB)  ->  s3://%s/%s",
            ym, len(data) / 1024, bucket, s3_key,
        )
        time.sleep(sleep_seconds)
        return "uploaded"

    except Exception as exc:  # noqa: BLE001 — any download, validation, or S3 error is logged; caller accumulates errors
        logger.error("Failed %s (%s): %s", ym, url, exc)
        time.sleep(sleep_seconds)
        return "error"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(
        description=(
            "Download USDA FAS World Agricultural Production monthly PDFs to raw S3. "
            "~286 releases from 2003-01 to present."
        )
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help=(
            "Scrape the FAS website to collect all WAP report landing pages, "
            "extract the real PDF URL from each, and rebuild "
            "configs/sources/usda_wap_manifest.yaml.  No AWS credentials required."
        ),
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
        help="Process at most N files — use 1–5 for smoke tests.",
    )
    parser.add_argument(
        "--year-from",
        type=int,
        default=None,
        metavar="YYYY",
        help="Process only entries with release year >= YYYY.",
    )
    parser.add_argument(
        "--year-to",
        type=int,
        default=None,
        metavar="YYYY",
        help="Process only entries with release year <= YYYY.",
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Discover mode
    # ------------------------------------------------------------------
    if args.discover:
        entries = _discover(sleep_seconds=args.sleep_seconds)
        _save_manifest(entries)
        return

    # ------------------------------------------------------------------
    # Upload mode
    # ------------------------------------------------------------------
    entries = _load_manifest()

    if args.year_from is not None:
        entries = [e for e in entries if int(e["release_month"][:4]) >= args.year_from]
    if args.year_to is not None:
        entries = [e for e in entries if int(e["release_month"][:4]) <= args.year_to]
    if args.limit:
        entries = entries[: args.limit]

    if not entries:
        logger.warning("No entries to process after filtering.")
        return

    if args.dry_run:
        print(f"Would process {len(entries)} files:")
        for e in entries:
            print(f"  {e['release_month']}  ->  {raw_wap_key(e['release_month'])}")
        return

    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    uploaded = skipped = errors = 0
    for entry in entries:
        result = _upload_entry(
            entry,
            bucket,
            region,
            skip_existing=args.skip_existing_s3,
            sleep_seconds=args.sleep_seconds,
        )
        if result == "uploaded":
            uploaded += 1
        elif result == "skipped":
            skipped += 1
        else:
            errors += 1

    logger.info("Done. uploaded=%d  skipped=%d  errors=%d", uploaded, skipped, errors)


if __name__ == "__main__":
    main()
