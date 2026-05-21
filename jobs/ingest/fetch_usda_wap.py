"""Fetch USDA FAS World Agricultural Production (WAP) monthly PDFs to raw S3.

Published once a month (same day as WASDE, ~10th of each month) by USDA FAS.
Each release is a single PDF covering wheat, corn, rice, soybeans, cotton and
other oilseeds with country-level area / production / trade estimates.

Source
------
    https://www.fas.usda.gov/data/world-agricultural-production
    report_type = 13286  (286 releases as of May 2026)

URL pattern
-----------
    https://www.fas.usda.gov/sites/default/files/{YYYY-MM}/production.pdf

This CDN path is fully deterministic and bypasses the Akamai-protected search
page, so plain ``requests`` works without curl_cffi.

S3 key structure
----------------
    raw/production/source=usda_wap/release_month={YYYY-MM}/production.pdf

Modes
-----
--discover
    HEAD-check every calendar month from 2003-01 to the current month.
    Confirmed 200-OK months are written to
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
import datetime
import time
from pathlib import Path

import requests
import yaml

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

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)

_MANIFEST_PATH = (
    Path(__file__).parent.parent.parent
    / "configs"
    / "sources"
    / "usda_wap_manifest.yaml"
)


# ---------------------------------------------------------------------------
# Month iteration helpers
# ---------------------------------------------------------------------------

def _month_range(
    start_year: int,
    start_month: int,
    end_year: int,
    end_month: int,
) -> list[str]:
    """Return list of ``YYYY-MM`` strings from start to end inclusive."""
    months: list[str] = []
    y, m = start_year, start_month
    while (y, m) <= (end_year, end_month):
        months.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def _cdn_url(ym: str) -> str:
    return f"{_CDN_BASE}/{ym}/production.pdf"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_pdf(data: bytes, url: str) -> None:
    if data[:4] != _PDF_MAGIC:
        raise RuntimeError(
            f"Response from {url} is not a PDF (got {data[:4]!r})"
        )


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _discover(session: requests.Session, sleep_seconds: float) -> list[dict]:
    """HEAD-check every month from _START_YM to today; return confirmed entries."""
    today = datetime.date.today()
    candidates = _month_range(
        *_START_YM,
        today.year,
        today.month,
    )
    logger.info("Discovery: probing %d month URLs (%s → %d-%02d)",
                len(candidates), candidates[0], today.year, today.month)

    confirmed: list[dict] = []
    for ym in candidates:
        url = _cdn_url(ym)
        try:
            r = session.head(url, timeout=_REQUEST_TIMEOUT_S, allow_redirects=True)
            if r.status_code == 200:
                logger.info("  ✓  %s", ym)
                confirmed.append({"release_month": ym, "url": url})
            else:
                logger.debug("  ✗  %s  HTTP %s", ym, r.status_code)
        except Exception as exc:
            logger.warning("  ✗  %s  error: %s", ym, exc)
        time.sleep(sleep_seconds)

    logger.info("Discovery complete: %d/%d months confirmed", len(confirmed), len(candidates))
    return confirmed


def _save_manifest(entries: list[dict]) -> None:
    _MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "# USDA FAS World Agricultural Production — monthly PDF archive": None,
        "releases": entries,
    }
    with _MANIFEST_PATH.open("w", encoding="utf-8") as fh:
        fh.write("# USDA FAS World Agricultural Production — monthly PDF archive\n")
        fh.write("# Generated by: python jobs/ingest/fetch_usda_wap.py --discover\n")
        fh.write("# CDN URL pattern: https://www.fas.usda.gov/sites/default/files/{YYYY-MM}/production.pdf\n\n")
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
    session: requests.Session,
    skip_existing: bool,
    sleep_seconds: float,
) -> str:
    """Download one WAP PDF and upload to raw S3.  Returns 'uploaded', 'skipped', or 'error'."""
    ym = entry["release_month"]
    url = entry["url"]
    s3_key = raw_wap_key(ym)

    try:
        if skip_existing and s3_object_exists(bucket, s3_key, region):
            logger.info("Skipping — already in S3: %s", s3_key)
            time.sleep(sleep_seconds)
            return "skipped"

        logger.info("Downloading %s  %s …", ym, url)
        resp = session.get(url, timeout=_REQUEST_TIMEOUT_S, allow_redirects=True)
        resp.raise_for_status()
        data = resp.content

        _validate_pdf(data, url)
        check_min_file_size(data, "usda_wap", context=url)

        upload_bytes_to_s3(data, bucket, s3_key, region)
        write_raw_s3_metadata(bucket, s3_key, data, url, "application/pdf", region)

        logger.info(
            "Uploaded %s  (%.1f KB)  →  s3://%s/%s",
            ym, len(data) / 1024, bucket, s3_key,
        )
        time.sleep(sleep_seconds)
        return "uploaded"

    except Exception as exc:
        logger.error("Failed %s (%s): %s", ym, url, exc)
        time.sleep(sleep_seconds)
        return "error"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
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
            "HEAD-check all months from 2003-01 to today and rebuild "
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
        default=0.5,
        help="Polite delay between HTTP requests in seconds (default: 0.5).",
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

    session = requests.Session()
    session.headers.update({"User-Agent": _UA})

    # ------------------------------------------------------------------
    # Discover mode
    # ------------------------------------------------------------------
    if args.discover:
        entries = _discover(session, sleep_seconds=args.sleep_seconds)
        _save_manifest(entries)
        session.close()
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
        session.close()
        return

    if args.dry_run:
        print(f"Would process {len(entries)} files:")
        for e in entries:
            print(f"  {e['release_month']}  →  {raw_wap_key(e['release_month'])}")
        session.close()
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

    session.close()
    logger.info("Done. uploaded=%d  skipped=%d  errors=%d", uploaded, skipped, errors)


if __name__ == "__main__":
    main()
