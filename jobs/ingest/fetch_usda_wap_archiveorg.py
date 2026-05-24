"""Fetch pre-2002 USDA FAS World Agricultural Production PDFs from the
Internet Archive and upload them to raw S3.

Reads ``configs/sources/usda_wap_archiveorg_manifest.yaml`` (built by
``discover_wap_archiveorg.py``) and downloads each PDF to the same S3 key
pattern as the modern FAS WAP PDFs (``source=usda_wap``).  No key conflicts
exist because Archive.org covers months prior to 2002-08.

Run (Fargate Batch or locally)
------------------------------
    python jobs/ingest/fetch_usda_wap_archiveorg.py [--skip-existing-s3]
    python jobs/ingest/fetch_usda_wap_archiveorg.py --dry-run
    python jobs/ingest/fetch_usda_wap_archiveorg.py --limit 3   # smoke test

S3 key structure (identical to modern WAP)
------------------------------------------
    raw/production/source=usda_wap/release_month={YYYY-MM}/production.pdf
"""
from __future__ import annotations

import argparse
import logging
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

_MANIFEST_PATH = (
    Path(__file__).parent.parent.parent
    / "configs"
    / "sources"
    / "usda_wap_archiveorg_manifest.yaml"
)

_PDF_MAGIC = b"%PDF"
_REQUEST_TIMEOUT_S = 60
_HEADERS = {"User-Agent": "Leviathan-WAP-Ingest/1.0 (research; non-commercial)"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fetch(url: str) -> requests.Response:
    """GET with a standard requests session (no bot protection on archive.org)."""
    r = requests.get(url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT_S,
                     allow_redirects=True)
    r.raise_for_status()
    return r


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
            "Run: python jobs/ingest/discover_wap_archiveorg.py"
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
    """Download one Archive.org WAP PDF and upload to raw S3.

    Returns ``'uploaded'``, ``'skipped'``, or ``'error'``.
    """
    ym = entry["release_month"]
    url = entry["url"]
    s3_key = raw_wap_key(ym)

    try:
        if skip_existing and s3_object_exists(bucket, s3_key, region):
            logger.info("Skipping — already in S3: %s", s3_key)
            time.sleep(sleep_seconds)
            return "skipped"

        logger.info("Downloading  %s  %s ...", ym, url)
        resp = _fetch(url)
        data = resp.content

        _validate_pdf(data, url)
        check_min_file_size(data, "usda_wap", context=url)

        upload_bytes_to_s3(data, bucket, s3_key, region)
        write_raw_s3_metadata(bucket, s3_key, data, url, "application/pdf", region)

        logger.info(
            "Uploaded  %s  (%.1f KB)  →  s3://%s/%s",
            ym, len(data) / 1024, bucket, s3_key,
        )
        time.sleep(sleep_seconds)
        return "uploaded"

    except Exception as exc:  # noqa: BLE001
        logger.error("Failed  %s  (%s): %s", ym, url, exc)
        time.sleep(sleep_seconds)
        return "error"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(
        description=(
            "Download pre-2002 USDA WAP PDFs from Archive.org to raw S3. "
            "Requires configs/sources/usda_wap_archiveorg_manifest.yaml "
            "(run discover_wap_archiveorg.py first)."
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
            print(f"  {e['release_month']}  →  {raw_wap_key(e['release_month'])}")
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
