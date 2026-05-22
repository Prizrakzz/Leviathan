"""Fetch pre-2002 USDA FAS World Agricultural Production HTML pages from the
Wayback Machine and upload them to raw S3.

Reads ``configs/sources/usda_wap_wayback_manifest.yaml`` (built by
``discover_wap_wayback.py``) and downloads each archived HTML page.  These
1996–2001 WAP circulars contain embedded production tables that are parseable
directly by BeautifulSoup — more ML-accessible than scanned PDFs.

HTML pages are stored under a separate source prefix (``usda_wap_html``) to
distinguish them from PDF-format WAP reports in bronze extraction pipelines.

Any 2002 gap entries with format=pdf are uploaded to ``source=usda_wap``
(same key pattern as the modern FAS manifest) using ``raw_wap_key()``.

Run (Fargate Batch or locally)
------------------------------
    python jobs/ingest/fetch_usda_wap_wayback.py [--skip-existing-s3]
    python jobs/ingest/fetch_usda_wap_wayback.py --dry-run
    python jobs/ingest/fetch_usda_wap_wayback.py --limit 3   # smoke test

S3 key structure
----------------
    HTML:  raw/production/source=usda_wap_html/release_month={YYYY-MM}/wap.html
    PDF:   raw/production/source=usda_wap/release_month={YYYY-MM}/production.pdf
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import requests
import yaml

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_wap_html_key, raw_wap_key
from leviathan.storage.raw_metadata import write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MANIFEST_PATH = (
    Path(__file__).parent.parent.parent
    / "configs"
    / "sources"
    / "usda_wap_wayback_manifest.yaml"
)

_PDF_MAGIC = b"%PDF"
_REQUEST_TIMEOUT_S = 60
_HEADERS = {"User-Agent": "Leviathan-WAP-Ingest/1.0 (research; non-commercial)"}

# Minimum bytes for a meaningful WAP HTML page
_MIN_HTML_BYTES = 2_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fetch(url: str) -> requests.Response:
    r = requests.get(url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT_S,
                     allow_redirects=True)
    r.raise_for_status()
    return r


def _validate_html(data: bytes, url: str) -> None:
    """Raise if the payload doesn't look like an HTML document."""
    lowered = data[:2048].lower()
    if b"<html" not in lowered and b"<table" not in lowered and b"<!doctype" not in lowered:
        raise RuntimeError(
            f"Response from {url} does not appear to be HTML "
            f"(first 200 bytes: {data[:200]!r})"
        )
    if len(data) < _MIN_HTML_BYTES:
        raise RuntimeError(
            f"Response from {url} is suspiciously small ({len(data)} bytes) "
            "— may be an empty Wayback Machine error page."
        )


def _validate_pdf(data: bytes, url: str) -> None:
    if data[:4] != _PDF_MAGIC:
        raise RuntimeError(
            f"Response from {url} is not a PDF (got {data[:4]!r})"
        )


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


def _load_manifest() -> list[dict]:
    if not _MANIFEST_PATH.exists():
        raise FileNotFoundError(
            f"Manifest not found: {_MANIFEST_PATH}\n"
            "Run: python jobs/ingest/discover_wap_wayback.py"
        )
    data = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8"))
    releases: list[dict] = data.get("releases") or []
    logger.info(
        "Manifest: loaded %d entries from %s", len(releases), _MANIFEST_PATH.name
    )
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
    """Download one Wayback Machine snapshot and upload to raw S3.

    Returns ``'uploaded'``, ``'skipped'``, or ``'error'``.
    """
    ym = entry["release_month"]
    url = entry["wayback_url"]
    fmt = entry.get("format", "html")

    if fmt == "pdf":
        s3_key = raw_wap_key(ym)
        content_type = "application/pdf"
    else:
        s3_key = raw_wap_html_key(ym)
        content_type = "text/html; charset=utf-8"

    try:
        if skip_existing and s3_object_exists(bucket, s3_key, region):
            logger.info("Skipping — already in S3: %s", s3_key)
            time.sleep(sleep_seconds)
            return "skipped"

        logger.info("Downloading  %s  [%s]  %s ...", ym, fmt, url)
        resp = _fetch(url)
        data = resp.content

        if fmt == "pdf":
            _validate_pdf(data, url)
        else:
            _validate_html(data, url)

        upload_bytes_to_s3(data, bucket, s3_key, region)
        write_raw_s3_metadata(bucket, s3_key, data, url, content_type, region)

        logger.info(
            "Uploaded  %s  [%s]  (%.1f KB)  →  s3://%s/%s",
            ym, fmt, len(data) / 1024, bucket, s3_key,
        )
        time.sleep(sleep_seconds)
        return "uploaded"

    except Exception as exc:  # noqa: BLE001
        logger.error("Failed  %s  [%s]  (%s): %s", ym, fmt, url, exc)
        time.sleep(sleep_seconds)
        return "error"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download pre-2002 USDA WAP HTML pages from the Wayback Machine to raw S3. "
            "Requires configs/sources/usda_wap_wayback_manifest.yaml "
            "(run discover_wap_wayback.py first)."
        )
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help="Skip files whose S3 key already exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print S3 keys without downloading anything.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=1.5,
        help="Polite delay between HTTP requests in seconds (default: 1.5).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process at most N files — use 1–5 for smoke tests.",
    )
    parser.add_argument(
        "--format",
        choices=["html", "pdf", "all"],
        default="all",
        help="Filter by format: html, pdf, or all (default: all).",
    )
    args = parser.parse_args()

    entries = _load_manifest()

    if args.format != "all":
        entries = [e for e in entries if e.get("format", "html") == args.format]
    if args.limit:
        entries = entries[: args.limit]

    if not entries:
        logger.warning("No entries to process after filtering.")
        return

    if args.dry_run:
        print(f"Would process {len(entries)} files:")
        for e in entries:
            fmt = e.get("format", "html")
            key = raw_wap_key(e["release_month"]) if fmt == "pdf" else raw_wap_html_key(e["release_month"])
            print(f"  {e['release_month']}  [{fmt}]  →  {key}")
        return

    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    uploaded = skipped = errors = 0
    for entry in entries:
        result = _upload_entry(
            entry,
            bucket=bucket,
            region=region,
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
        "Done — uploaded=%d  skipped=%d  errors=%d  (total=%d)",
        uploaded, skipped, errors, len(entries),
    )
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
