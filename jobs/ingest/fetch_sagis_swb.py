"""Fetch SAGIS South Africa Weekly Bulletin (SWB) PDFs to raw S3.

Discovery
---------
SAGIS maintains a public WordPress page listing all historical SWB bulletins.
The WordPress JSON API provides the full page content as rendered HTML, which
contains direct PDF links:

    GET https://www.sagis.org.za/wp-json/wp/v2/pages?slug=swb&_fields=content

Parsing ``content.rendered`` with a regex extracts all
``https://www.sagis.org.za/wp-content/uploads/.../SWB*.pdf`` links.

Archive coverage: 2011 – present (~780 PDFs; ~52/year).  No authentication
required.

Filename variability
--------------------
SAGIS uses inconsistent filename conventions across the archive::

    SWB_20260514.pdf          (current style, underscore + 8-digit date)
    SWB-2024-10-17.pdf        (hyphen-separated ISO date)
    SWB20231116.pdf           (no separator)
    SWB_20251106-1.pdf        (suffix for re-issued bulletins)

Filenames are stored as-is in S3.  Bulletin date extraction is deferred to the
bronze transform.

S3 key structure
----------------
    raw/production/source=sagis_swb/
        upload_year={YYYY}/
        upload_month={MM}/
        {filename}

``upload_year`` / ``upload_month`` come from the ``/wp-content/uploads/YYYY/MM/``
URL path component, consistent with the FNC PDF pattern.

Manifest
--------
Successfully uploaded PDFs are appended to
``configs/sources/sagis_swb_manifest.yaml`` so future runs can skip
already-seen URLs without a round-trip to S3.

Idempotency
-----------
  --skip-existing-s3   Skip keys already present in S3 (combine with manifest
                       check for fastest re-runs).
  --dry-run            Print candidate URLs without downloading anything.
  --limit N            Process at most N PDFs — use 3 for a smoke test.
  --newest-first       Sort newest bulletins first (default: True).  Keeps
                       routine weekly runs fast by processing recent files
                       before the long tail of the 2011 archive.

Rate limiting
-------------
1.0 s between downloads.  All downloads are sequential; no threading.
"""
from __future__ import annotations

import argparse
import re
import time
from pathlib import Path
from urllib.parse import unquote

import requests
import yaml

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_sagis_swb_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WP_API_URL = (
    "https://www.sagis.org.za/wp-json/wp/v2/pages"
    "?slug=swb&_fields=content"
)

# Matches any SWB PDF link in the WordPress-rendered HTML.
# URLs are quoted with double-quotes in the rendered HTML; [^"] stops at the
# closing quote without consuming it.
_PDF_LINK_RE = re.compile(
    r'(https://www\.sagis\.org\.za/wp-content/uploads/[^"]+SWB[^"]+\.pdf)',
    re.IGNORECASE,
)

# Extracts upload year/month from the /uploads/YYYY/MM/ URL path component.
_UPLOAD_YM_RE = re.compile(r"/uploads/(\d{4})/(\d{2})/")

_PDF_MAGIC = b"%PDF"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_MANIFEST_PATH = (
    Path(__file__).parent.parent / "configs" / "sources" / "sagis_swb_manifest.yaml"
)

_DEFAULT_SLEEP = 1.0


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _discover_bulletin_urls(session: requests.Session) -> list[str]:
    """Query the SAGIS WP JSON API and return all unique SWB PDF URLs.

    Args:
        session: An active :class:`requests.Session`.

    Returns:
        Deduplicated list of PDF URLs, in page order.

    Raises:
        RuntimeError: If the API returns no pages or no PDF links.
    """
    logger.info("Querying SAGIS WP API …")
    resp = session.get(_WP_API_URL, timeout=30)
    resp.raise_for_status()

    pages = resp.json()
    if not pages:
        raise RuntimeError(
            "SAGIS WP API returned an empty response.  "
            "The page slug 'swb' may have changed."
        )

    html = pages[0]["content"]["rendered"]
    raw_links = _PDF_LINK_RE.findall(html)

    seen: set[str] = set()
    urls: list[str] = []
    for link in raw_links:
        if link not in seen:
            seen.add(link)
            urls.append(link)

    logger.info("Discovered %d unique SWB PDF links.", len(urls))
    if not urls:
        raise RuntimeError(
            "No SWB PDF links found in page content.  "
            "SAGIS may have changed the page layout or URL structure."
        )
    return urls


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def _load_manifest() -> list[dict]:
    if _MANIFEST_PATH.exists():
        data = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8")) or {}
        return data.get("bulletins", [])
    return []


def _append_manifest(entry: dict) -> None:
    bulletins = _load_manifest()
    bulletins.append(entry)
    _MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.dump(
        {"bulletins": bulletins},
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    _MANIFEST_PATH.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _upload_ym(url: str) -> tuple[int, int]:
    """Extract ``(upload_year, upload_month)`` from a wp-content/uploads URL."""
    m = _UPLOAD_YM_RE.search(url)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 0, 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch SAGIS Weekly Bulletin (SWB) PDFs to raw S3. "
            "Discovers all bulletins via the SAGIS WordPress JSON API."
        )
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help="Skip PDFs whose S3 key already exists (safe for re-runs).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover and print all candidate URLs without downloading anything.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process at most N PDFs — use 3 for a smoke test.",
    )
    parser.add_argument(
        "--newest-first",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Sort newest bulletins first (default: True).  "
            "Use --no-newest-first for chronological (oldest-first) order."
        ),
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=_DEFAULT_SLEEP,
        help=f"Polite delay between downloads in seconds (default: {_DEFAULT_SLEEP}).",
    )
    args = parser.parse_args()

    session = requests.Session()
    session.headers["User-Agent"] = _UA

    # -----------------------------------------------------------------------
    # Discover
    # -----------------------------------------------------------------------
    urls = _discover_bulletin_urls(session)

    # Sort by (upload_year, upload_month) from the URL path.
    urls.sort(key=_upload_ym, reverse=args.newest_first)

    # -----------------------------------------------------------------------
    # Dry run
    # -----------------------------------------------------------------------
    if args.dry_run:
        print(f"Discovered: {len(urls)} SWB PDFs")
        for u in urls:
            uy, um = _upload_ym(u)
            print(f"  upload_year={uy}  upload_month={um:02d}  {u}")
        return

    # -----------------------------------------------------------------------
    # Live run
    # -----------------------------------------------------------------------
    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    known_urls: set[str] = {e["bulletin_url"] for e in _load_manifest()}

    if args.limit:
        urls = urls[: args.limit]

    uploaded = skipped = errors = 0

    for pdf_url in urls:
        upload_year, upload_month = _upload_ym(pdf_url)
        filename = unquote(pdf_url.rsplit("/", 1)[-1])
        s3_key = raw_sagis_swb_key(upload_year, upload_month, filename)

        try:
            if pdf_url in known_urls:
                logger.info("Skipping — in manifest: %s", filename)
                skipped += 1
                continue

            if args.skip_existing_s3 and s3_object_exists(bucket, s3_key, region):
                logger.info("Skipping — already in S3: %s", s3_key)
                skipped += 1
                continue

            resp = session.get(pdf_url, timeout=60)
            resp.raise_for_status()
            pdf_bytes = resp.content

            if not pdf_bytes.startswith(_PDF_MAGIC):
                raise RuntimeError(
                    f"Response is not a valid PDF (missing %%PDF header): {pdf_url}"
                )

            check_min_file_size(pdf_bytes, "sagis_swb", context=pdf_url)

            upload_bytes_to_s3(pdf_bytes, bucket, s3_key, region)
            write_raw_s3_metadata(
                bucket, s3_key, pdf_bytes, pdf_url, "application/pdf", region
            )

            _append_manifest(
                {
                    "bulletin_url": pdf_url,
                    "upload_year": upload_year,
                    "upload_month": upload_month,
                    "filename": filename,
                    "s3_key": s3_key,
                }
            )
            known_urls.add(pdf_url)

            logger.info(
                "Uploaded uy=%d um=%02d  %.1f KB → s3://%s/%s",
                upload_year,
                upload_month,
                len(pdf_bytes) / 1024,
                bucket,
                s3_key,
            )
            uploaded += 1

        except Exception as exc:  # noqa: BLE001
            logger.error("Failed %s: %s", filename, exc)
            errors += 1

        time.sleep(args.sleep_seconds)

    logger.info(
        "Done. uploaded=%d  skipped=%d  errors=%d", uploaded, skipped, errors
    )

    if errors:
        raise SystemExit(f"{errors} bulletin(s) failed — see logs above.")


if __name__ == "__main__":
    main()
