"""Fetch SAGIS South Africa Crop Estimates Committee (CEC) reports to raw S3.

Discovery
---------
SAGIS maintains a public WordPress page listing all historical CEC meeting
reports.  The WordPress JSON API provides the full page content as rendered
HTML, which contains direct file links:

    GET https://www.sagis.org.za/wp-json/wp/v2/pages
        ?slug=crop-estimates-committee-2&_fields=content

Parsing ``content.rendered`` with a regex extracts all
``https://www.sagis.org.za/wp-content/uploads/.../CEC*.{pdf,doc,xls}`` links.

Archive coverage: 1999 - present (~358 files across ~230 meetings).
No authentication required.

File formats
------------
CEC reports span three physical formats across the 27-year archive::

    CEC_2026-05-07.pdf      (current style, PDF since ~2010)
    CEC-2024-12.doc         (Word .doc, 2007-~2024)
    CEC_2005_-_1905S.doc    (old Word .doc, 2001-2006)
    CEC_2004_-_1905S.xls    (Excel .xls, 2002-2004 only)

PDF and DOC/XLS use different magic bytes for validation::

    PDF:      b"%PDF"
    DOC/XLS:  b"\\xd0\\xcf\\x11\\xe0"  (OLE compound file, same for both)

Filenames are stored as-is in S3.  Document date and crop coverage
extraction are deferred to the bronze transform.

S3 key structure
----------------
    raw/production/source=sagis_cec/{filename}

Flat layout.  The WordPress upload path (``/uploads/YYYY/MM/``) is not
usable for partitioning: the entire historical archive (~170 files) was
bulk-uploaded to ``/2026/05/`` in May 2026, so the upload path bears no
relation to document date for pre-2025 content.

Manifest
--------
Successfully uploaded files are appended to
``configs/sources/sagis_cec_manifest.yaml`` so future runs can skip
already-seen URLs without a round-trip to S3.

Idempotency
-----------
  --skip-existing-s3   Skip keys already present in S3 (combine with manifest
                       check for fastest re-runs).
  --dry-run            Print candidate URLs without downloading anything.
  --limit N            Process at most N files - use 3 for a smoke test.
  --newest-first       Sort newest reports first (default: True).  Keeps
                       routine monthly runs fast by processing recent files
                       before the long tail of the 1999 archive.

Rate limiting
-------------
1.0 s between downloads.  All downloads are sequential; no threading.
"""
from __future__ import annotations

import argparse
import logging
import re
import time
from pathlib import Path
from urllib.parse import unquote

import requests
import yaml

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_sagis_cec_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WP_API_URL = (
    "https://www.sagis.org.za/wp-json/wp/v2/pages"
    "?slug=crop-estimates-committee-2&_fields=content"
)

# Matches CEC report files (PDF, DOC, XLS) in WordPress-rendered HTML.
# The negative lookahead excludes admin/schedule files (CEC_Dates_YYYY.pdf).
# URLs are double-quote-delimited in the rendered HTML; [^"] stops at the
# closing quote without consuming it.
_FILE_LINK_RE = re.compile(
    r'(https://www\.sagis\.org\.za/wp-content/uploads/[^"]+/CEC(?!_Dates_)[^"]+\.(?:pdf|doc|xls))',
    re.IGNORECASE,
)# Extracts the calendar year (YYYY) from any CEC filename style:
#   CEC_2026-05-07.pdf, CEC-2024-12.doc, CEC_2005_-_1905S.doc
_YEAR_RE = re.compile(r"CEC[_-](\d{4})", re.IGNORECASE)
_PDF_MAGIC = b"%PDF"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0"  # OLE compound file — both .doc and .xls

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_MANIFEST_PATH = (
    Path(__file__).parent.parent.parent / "configs" / "sources" / "sagis_cec_manifest.yaml"
)

_DEFAULT_SLEEP = 1.0

# Content-type by lowercase file extension
_CONTENT_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "xls": "application/vnd.ms-excel",
}


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _discover_report_urls(session: requests.Session) -> list[str]:
    """Query the SAGIS WP JSON API and return all unique CEC report file URLs.

    Args:
        session: An active :class:`requests.Session`.

    Returns:
        Deduplicated list of file URLs, in page order.

    Raises:
        RuntimeError: If the API returns no pages or no file links.
    """
    logger.info("Querying SAGIS WP API ...")
    resp = session.get(_WP_API_URL, timeout=30)
    resp.raise_for_status()

    pages = resp.json()
    if not pages:
        raise RuntimeError(
            "SAGIS WP API returned an empty response.  "
            "The page slug 'crop-estimates-committee-2' may have changed."
        )

    html = pages[0]["content"]["rendered"]
    raw_links = _FILE_LINK_RE.findall(html)

    seen: set[str] = set()
    urls: list[str] = []
    for link in raw_links:
        if link not in seen:
            seen.add(link)
            urls.append(link)

    logger.info("Discovered %d unique CEC report links.", len(urls))
    if not urls:
        raise RuntimeError(
            "No CEC report links found in page content.  "
            "SAGIS may have changed the page layout or URL structure."
        )
    return urls


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def _load_manifest() -> list[dict]:
    if _MANIFEST_PATH.exists():
        data = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8")) or {}
        return data.get("reports", [])
    return []


def _append_manifest(entry: dict) -> None:
    reports = _load_manifest()
    reports.append(entry)
    _MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.dump(
        {"reports": reports},
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    _MANIFEST_PATH.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _filename_from_url(url: str) -> str:
    """Extract and URL-decode the filename from a wp-content/uploads URL."""
    return unquote(url.rsplit("/", 1)[-1])


def _validate_magic(data: bytes, filename: str) -> None:
    """Check that magic bytes match the file extension.

    Args:
        data:     Downloaded file bytes.
        filename: Filename with extension (determines expected magic).

    Raises:
        RuntimeError: If the magic bytes don't match the expected format.
    """
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext == "pdf":
        if not data.startswith(_PDF_MAGIC):
            raise RuntimeError(
                f"Expected PDF magic (%%PDF) but got {data[:8]!r}: {filename}"
            )
    elif ext in ("doc", "xls"):
        if not data.startswith(_OLE_MAGIC):
            raise RuntimeError(
                f"Expected OLE magic for .{ext} but got {data[:8]!r}: {filename}"
            )


# ---------------------------------------------------------------------------
# Error classification / run summary
# ---------------------------------------------------------------------------

def _is_permanent_404(exc: Exception) -> bool:
    """True if *exc* is an HTTP 404 — a permanently-pruned historical report.

    SAGIS leaves dead download links in the WordPress page HTML long after the
    underlying file is removed, so they are re-discovered on every run and can
    never enter the skip-manifest (only successful uploads are recorded there).
    A 404 is therefore tallied as ``missing`` and tolerated; any other status
    (5xx, etc.) stays a hard error.
    """
    return (
        isinstance(exc, requests.HTTPError)
        and exc.response is not None
        and exc.response.status_code == 404
    )


def _exit_reason(uploaded: int, skipped: int, errors: int, missing: int) -> str | None:
    """Return a SystemExit message if the run should fail, else ``None``.

    Any non-404 failure fails the run.  A run that uploaded nothing, skipped
    nothing, and saw only 404s means every discovered link is dead — fail
    rather than exit green with no signal.
    """
    if errors:
        return f"{errors} report(s) failed - see logs above."
    if uploaded == 0 and skipped == 0 and missing > 0:
        return f"No reports uploaded and {missing} link(s) returned 404 - source may be dead."
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(
        description=(
            "Fetch SAGIS Crop Estimates Committee (CEC) reports to raw S3. "
            "Discovers all reports via the SAGIS WordPress JSON API."
        )
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help="Skip files whose S3 key already exists (safe for re-runs).",
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
        help="Process at most N files - use 3 for a smoke test.",
    )
    parser.add_argument(
        "--newest-first",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Sort newest reports first (default: True).  "
            "Use --no-newest-first for chronological (oldest-first) order."
        ),
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=_DEFAULT_SLEEP,
        help=f"Polite delay between downloads in seconds (default: {_DEFAULT_SLEEP}).",
    )
    parser.add_argument(
        "--year-from",
        type=int,
        default=None,
        metavar="YYYY",
        help="Only process reports from this year onward (inclusive).",
    )
    parser.add_argument(
        "--year-to",
        type=int,
        default=None,
        metavar="YYYY",
        help="Only process reports up to and including this year.",
    )
    args = parser.parse_args()

    session = requests.Session()
    session.headers["User-Agent"] = _UA

    # -----------------------------------------------------------------------
    # Discover
    # -----------------------------------------------------------------------
    urls = _discover_report_urls(session)

    # Sort by filename (descending = newest-first).  Filenames begin with
    # CEC_YYYY or CEC-YYYY, so lexicographic descending approximates
    # chronological descending order across the full archive.
    urls.sort(key=lambda u: _filename_from_url(u).lower(), reverse=args.newest_first)

    if args.year_from is not None or args.year_to is not None:
        def _url_year(url: str) -> int | None:
            m = _YEAR_RE.search(_filename_from_url(url))
            return int(m.group(1)) if m else None

        urls = [
            u for u in urls
            if (y := _url_year(u)) is not None
            and (args.year_from is None or y >= args.year_from)
            and (args.year_to is None or y <= args.year_to)
        ]
        logger.info(
            "Year filter %s\u2013%s: %d URLs remaining.",
            args.year_from or "*", args.year_to or "*", len(urls),
        )

    # -----------------------------------------------------------------------
    # Dry run
    # -----------------------------------------------------------------------
    if args.dry_run:
        print(f"Discovered: {len(urls)} CEC reports")
        for u in urls:
            print(f"  {_filename_from_url(u):<60}  {u}")
        return

    # -----------------------------------------------------------------------
    # Live run
    # -----------------------------------------------------------------------
    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    known_urls: set[str] = {e["report_url"] for e in _load_manifest()}

    if args.limit:
        urls = urls[: args.limit]

    uploaded = skipped = errors = missing = 0

    for file_url in urls:
        filename = _filename_from_url(file_url)
        s3_key = raw_sagis_cec_key(filename)
        ext = filename.rsplit(".", 1)[-1].lower()
        content_type = _CONTENT_TYPES.get(ext, "application/octet-stream")

        try:
            if file_url in known_urls:
                logger.info("Skipping - in manifest: %s", filename)
                skipped += 1
                continue

            if args.skip_existing_s3 and s3_object_exists(bucket, s3_key, region):
                logger.info("Skipping - already in S3: %s", s3_key)
                skipped += 1
                continue

            resp = session.get(file_url, timeout=60)
            resp.raise_for_status()
            file_bytes = resp.content

            _validate_magic(file_bytes, filename)
            check_min_file_size(file_bytes, "sagis_cec", context=file_url)

            upload_bytes_to_s3(file_bytes, bucket, s3_key, region)
            write_raw_s3_metadata(
                bucket, s3_key, file_bytes, file_url, content_type, region
            )

            _append_manifest(
                {
                    "report_url": file_url,
                    "filename": filename,
                    "s3_key": s3_key,
                }
            )
            known_urls.add(file_url)

            logger.info(
                "Uploaded %.1f KB  %s",
                len(file_bytes) / 1024,
                filename,
            )
            uploaded += 1

        except Exception as exc:  # noqa: BLE001 — download, validation, or S3 error; 404s tolerated below
            if _is_permanent_404(exc):
                # Link is still on the page but the file was pruned from the
                # site.  It can never enter the skip-manifest, so tolerate it
                # every run rather than fail the whole fetch forever.
                logger.warning(
                    "Missing (HTTP 404) - link on page but file pruned: %s",
                    filename,
                )
                missing += 1
            else:
                logger.error("Failed %s: %s", filename, exc)
                errors += 1

        time.sleep(args.sleep_seconds)

    logger.info(
        "Done. uploaded=%d  skipped=%d  missing=%d  errors=%d",
        uploaded,
        skipped,
        missing,
        errors,
    )

    reason = _exit_reason(
        uploaded=uploaded, skipped=skipped, errors=errors, missing=missing
    )
    if reason:
        raise SystemExit(reason)


if __name__ == "__main__":
    main()
