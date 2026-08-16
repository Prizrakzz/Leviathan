"""Fetch the World Bank Commodity Markets Pink Sheet XLSX to raw S3.

Source
------
World Bank Prospects Group — Commodity Markets ("Pink Sheet")
    https://www.worldbank.org/en/research/commodity-markets

No authentication required.  The file is a publicly accessible XLSX
(~2–3 MB) containing monthly commodity price series back to January 1960.
Because the full history is bundled in every release, one download is
sufficient to bootstrap the entire historical baseline.

URL discovery
-------------
The World Bank uses an opaque document-ID that changes every month, so
there is no stable direct download URL.  This script scrapes the entry-point
page to locate the current "CMO-Pink-Sheet-*.xlsx" href, following the same
pattern documented in ``configs/sources/world_bank_pink_sheet.yaml``.

S3 key structure
----------------
    raw/production/source=world_bank_pink_sheet/
        release={YYYYMmm}/{original_filename}.xlsx

e.g.
    raw/production/source=world_bank_pink_sheet/
        release=2026M05/CMO-Pink-Sheet-May-2026.xlsx

Each monthly release is stored as a separate, immutable object.  This
preserves retroactive WB revisions (WB frequently revises prior months)
and enables exact point-in-time reconstruction of the historical price series.

Update schedule
---------------
The WB publishes around the first Tuesday of each month.  The Airflow DAG
``pink_sheet_monthly_ingest_dag.py`` runs at 14:00 UTC on the first Tuesday
of each month (cron: ``0 14 1-7 * 2``).

Idempotency
-----------
Pass ``--skip-existing-s3`` to skip the download if the S3 key already exists.
Pass ``--dry-run`` to print the discovered URL and S3 key without downloading.
Pass ``--release-month YYYY-MM`` to override the release month extracted from
the filename (useful when re-running after the page has rotated to the next
release but you need to ingest the prior month's data from a cached URL).
"""
from __future__ import annotations

import argparse
import datetime
import io
import logging
import re
import zipfile

import requests
from bs4 import BeautifulSoup

from leviathan.common.config import get_required_env, load_env
from leviathan.common.dates import coerce_date
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_pink_sheet_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ENTRY_URL = "https://www.worldbank.org/en/research/commodity-markets"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Monthly historical data file (the download target).
# The XLSX filename is static: "CMO-Historical-Data-Monthly.xlsx".
# The opaque document-ID in the URL changes each month.
_XLS_RE = re.compile(r"CMO-Historical-Data-Monthly\.xlsx", re.IGNORECASE)

# Fallback: any href ending in .xlsx on thedocs.worldbank.org
_XLS_FALLBACK_RE = re.compile(r"thedocs\.worldbank\.org.*\.xlsx", re.IGNORECASE)

# The release month is extracted from the accompanying PDF href, which DOES
# contain the month name and year in its filename.
# e.g. "CMO-Pink-Sheet-May-2026.pdf"
_PDF_DATE_RE = re.compile(r"CMO-Pink-Sheet-([A-Za-z]+)-(\d{4})\.pdf", re.IGNORECASE)

# Timeout for all HTTP requests.  Entry page is ~200 KB; XLS is ~2–3 MB.
_PAGE_TIMEOUT = 30
_DOWNLOAD_TIMEOUT = 120


# ---------------------------------------------------------------------------
# URL discovery
# ---------------------------------------------------------------------------

def _discover_xls_url_from_html(page_html: str) -> tuple[str, str]:
    """Return (xls_url, filename) from already-fetched page HTML."""
    soup = BeautifulSoup(page_html, "html.parser")

    all_hrefs = [tag["href"] for tag in soup.find_all("a", href=True)]

    # Pass 1: look for CMO-Historical-Data-Monthly.xlsx
    for href in all_hrefs:
        if _XLS_RE.search(href):
            url = href if href.startswith("http") else f"https://www.worldbank.org{href}"
            filename = "CMO-Historical-Data-Monthly.xlsx"
            logger.info("Discovered Pink Sheet XLS URL: %s", url)
            return url, filename

    # Pass 2: any xlsx on thedocs.worldbank.org
    for href in all_hrefs:
        if _XLS_FALLBACK_RE.search(href):
            url = href
            filename = href.rstrip("/").split("/")[-1].split("?")[0]
            logger.info("Discovered Pink Sheet XLS URL (fallback): %s", url)
            return url, filename

    raise RuntimeError(
        "Could not locate the Pink Sheet XLSX href on the World Bank commodity-markets "
        f"page ({_ENTRY_URL}). The page structure may have changed. "
        "Check the page manually and update _XLS_RE in this script."
    )


# ---------------------------------------------------------------------------
# Release-month parsing
# ---------------------------------------------------------------------------

def _parse_release_ym_from_page(html: str) -> str | None:
    """Extract the release year-month from the Pink Sheet PDF href on the page.

    The XLSX filename is static (``CMO-Historical-Data-Monthly.xlsx``), so the
    release date is inferred from the accompanying PDF href, which does encode
    the month and year: ``CMO-Pink-Sheet-May-2026.pdf``.

    Returns:
        ``"YYYYMmm"`` string (e.g. ``"2026M05"``), or ``None`` if not found.
    """
    m = _PDF_DATE_RE.search(html)
    if not m:
        return None
    month_name, year_str = m.group(1), m.group(2)
    try:
        month_num = datetime.datetime.strptime(month_name, "%B").month
    except ValueError:
        return None
    return f"{year_str}M{month_num:02d}"


def _release_ym_from_override(release_month: str) -> str:
    """Convert a ``YYYY-MM`` CLI override to the ``YYYYMmm`` S3 partition format.

    Args:
        release_month: e.g. ``"2026-05"``

    Returns:
        e.g. ``"2026M05"``
    """
    try:
        dt = datetime.datetime.strptime(release_month, "%Y-%m")
    except ValueError:
        raise ValueError(
            f"--release-month must be in YYYY-MM format, got: {release_month!r}"
        )
    return f"{dt.year}M{dt.month:02d}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_xlsx(data: bytes, source_url: str) -> None:
    """Validate that *data* is a well-formed XLSX (ZIP) file.

    XLSX files are ZIP archives.  We perform two checks:
    1. Magic bytes: first two bytes must be ``PK`` (0x50 0x4B).
    2. Open with :mod:`zipfile` to confirm structural integrity.
    3. Minimum size check via :func:`check_min_file_size`.

    We deliberately do NOT open the file with openpyxl here — that is a heavy
    dependency and belongs in the bronze transform, not the raw ingest layer.

    Raises:
        RuntimeError: If any check fails.
    """
    # Magic bytes (ZIP / XLSX)
    if len(data) < 4 or data[:2] != b"PK":
        raise RuntimeError(
            f"Validation failed: response from {source_url} does not have XLSX/ZIP "
            f"magic bytes. Got: {data[:8]!r}. Possible HTML error page."
        )

    # Structural integrity
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile as exc:
        raise RuntimeError(
            f"Validation failed: response from {source_url} is not a valid ZIP/XLSX "
            f"file: {exc}"
        ) from exc

    # Sanity: at minimum an xl/ directory should be present in a real XLSX
    if not any(n.startswith("xl/") for n in names):
        raise RuntimeError(
            f"Validation failed: ZIP from {source_url} does not look like a valid XLSX "
            f"(no xl/ entries found). Contents: {names[:10]}"
        )

    # Minimum size check
    check_min_file_size(data, "world_bank_pink_sheet", context=source_url)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(
        description=(
            "Download the World Bank Commodity Markets Pink Sheet XLSX to raw S3. "
            "Scrapes the WB commodity-markets page to discover the current monthly "
            "download URL (the document ID is opaque and changes each month). "
            "No authentication required."
        )
    )
    parser.add_argument(
        "--release-month",
        metavar="YYYY-MM",
        default=None,
        help=(
            "Override the release month used for the S3 key partition. "
            "Default: parsed from the filename discovered on the WB page. "
            "Use this if the page has already rotated to the next release but you "
            "need to re-ingest a prior month from a known URL."
        ),
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help="Skip the download if the S3 key already exists (safe for re-runs).",
    )
    parser.add_argument(
        "--asof",
        default=None,
        help="Scheduled-time ISO the release-recency fence measures against. Default: today (UTC).",
    )
    parser.add_argument(
        "--max-release-lag-months",
        type=int,
        default=1,
        dest="max_release_lag_months",
        help=(
            "Advance fence: fail if the release discovered on the WB page is more than this "
            "many calendar months behind --asof. Default 1 (the WB publishes monthly, around "
            "the first Tuesday; a fire on the 4th legitimately sees month-1, never month-2)."
        ),
    )
    parser.add_argument(
        "--no-advance-fence",
        dest="advance_fence",
        action="store_false",
        default=True,
        help="Disable the D-SG G2-1 release-recency fence (deliberate historical reruns only).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover the URL and print the S3 key without downloading anything.",
    )
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": _UA})

    # Fetch the entry page once — needed for both URL discovery and release-month
    # extraction (the PDF href encodes the month name we need).
    logger.info("Fetching entry page: %s", _ENTRY_URL)
    page_resp = session.get(_ENTRY_URL, timeout=_PAGE_TIMEOUT)
    page_resp.raise_for_status()
    page_html = page_resp.text

    # Discover the current XLS download URL.
    xls_url, filename = _discover_xls_url_from_html(page_html)

    # Determine the release year-month for the S3 partition.
    if args.release_month:
        release_ym = _release_ym_from_override(args.release_month)
    else:
        release_ym = _parse_release_ym_from_page(page_html)
        if release_ym is None:
            today = datetime.date.today()
            release_ym = f"{today.year}M{today.month:02d}"
            logger.warning(
                "Could not extract release month from PDF href on page; "
                "defaulting to current calendar month: %s. "
                "Use --release-month to override.",
                release_ym,
            )

    s3_key = raw_pink_sheet_key(release_ym, filename)

    # ---- D-SG G2-1(c) RELEASE-RECENCY FENCE ---------------------------------
    # The release label is whatever CMO-Pink-Sheet-<Month>-<Year>.pdf href the page
    # happens to show at fire time. The schedule fires on the 4th; the WB publishes
    # "around the first Tuesday" -- so in any month where the WB posts later, this
    # job re-downloads the PRIOR month's workbook into the SAME release= key, bronze
    # skips it, and the whole chain exits 0 having landed nothing. On 2026-08-04 that
    # produced release=2026M07 (a legal month-1) with raw/bronze still holding only
    # {2026M05, 2026M07}. A month-2 lag is NOT legal and must go red.
    if args.advance_fence:
        _asof = coerce_date(args.asof)
        _rel_year, _rel_month = int(release_ym[:4]), int(release_ym[5:7])
        _lag = (_asof.year - _rel_year) * 12 + (_asof.month - _rel_month)
        if _lag > args.max_release_lag_months:
            raise SystemExit(
                f"ZERO-ADVANCE: the World Bank commodity-markets page still advertises "
                f"release {release_ym}, which is {_lag} calendar months behind asof "
                f"{_asof.isoformat()} (limit {args.max_release_lag_months}). Either the WB "
                "has stopped publishing, or the page structure moved and _PDF_DATE_RE is "
                "matching a stale/archive href. This fire would have re-downloaded an "
                "already-held release and exited 0."
            )
        logger.info(
            "release-recency fence OK: release=%s, lag=%d month(s) behind asof=%s",
            release_ym, _lag, _asof.isoformat(),
        )

    # ------------------------------------------------------------------
    # Dry run
    # ------------------------------------------------------------------
    if args.dry_run:
        print(f"Entry page : {_ENTRY_URL}")
        print(f"XLS URL    : {xls_url}")
        print(f"Filename   : {filename}")
        print(f"Release    : {release_ym}")
        print(f"S3 key     : {s3_key}")
        return

    # ------------------------------------------------------------------
    # Live run
    # ------------------------------------------------------------------
    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    if args.skip_existing_s3 and s3_object_exists(bucket, s3_key, region):
        logger.info("Skipping — already in S3: %s", s3_key)
        return

    logger.info("Downloading Pink Sheet XLSX from %s …", xls_url)
    resp = session.get(xls_url, timeout=_DOWNLOAD_TIMEOUT, stream=False)
    resp.raise_for_status()
    data = resp.content

    logger.info("Downloaded %.2f MB", len(data) / 1_048_576)

    _validate_xlsx(data, xls_url)
    logger.info("Validation passed — %d bytes, well-formed XLSX", len(data))

    upload_bytes_to_s3(data, bucket, s3_key, region)
    logger.info("Uploaded → s3://%s/%s", bucket, s3_key)

    write_raw_s3_metadata(
        bucket,
        s3_key,
        data,
        xls_url,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        region,
    )
    logger.info("Metadata written → raw_meta/%s_meta.json", s3_key)


if __name__ == "__main__":
    main()
