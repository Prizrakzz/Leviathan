"""Fetch CFTC Disaggregated COT reports to raw S3.

Source
------
CFTC Commitments of Traders — Disaggregated weekly position reports
    https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm

No authentication required.  All files are publicly accessible.

Two report types
----------------
disagg_futures
    Disaggregated Futures Only.  Pure futures book, four trader categories:
    Producer/Merchant, Swap Dealer, Managed Money, Other Reportables.

disagg_combined
    Disaggregated Futures-and-Options Combined.  CFTC delta-adjusts options
    positions into futures-equivalent contracts before publication.  The
    difference (combined minus futures-only) isolates managed money options
    exposure (mm_options_equiv signal).

Two modes
---------
backfill
    1. Download the 2006–2016 bulk ZIP (covers disaggregated history from
       inception in September 2006 through December 2016).  Extract and store
       the TXT in S3.
    2. Download annual ZIPs for 2017 through (current_year - 1).  Extract
       and store each TXT in S3.

    Both steps run for both report types.  Skips files already in S3 when
    --skip-existing-s3 is passed.

weekly
    Download the live TXT files for both report types (no ZIP extraction
    needed for the current-week files).  Partition by as_of date (the
    Friday publication date).

S3 key structure
----------------
    backfill bulk:
        raw/production/source=cftc_cot/{report_type}/backfill/{prefix}_2006_2016.txt
    backfill annual:
        raw/production/source=cftc_cot/{report_type}/backfill/{prefix}_{year}.txt
    weekly:
        raw/production/source=cftc_cot/{report_type}/year={year}/as_of={YYYYMMDD}/{prefix}_{YYYYMMDD}.txt

    Where {prefix} is ``fut_disagg`` for disagg_futures and ``com_disagg``
    for disagg_combined.

Update schedule
---------------
Run --mode weekly every Friday after 18:00 UTC.  The Airflow DAG
``cot_weekly_ingest`` handles this automatically.

Idempotency
-----------
Pass ``--skip-existing-s3`` to skip files already present in S3.
Pass ``--dry-run`` to print S3 keys without downloading anything.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import io
import logging
import time
import zipfile

import requests

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_cot_backfill_key, raw_cot_weekly_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# CFTC base URLs for historical ZIPs and current-week TXT files.
_BULK_ZIP_URLS = {
    "disagg_futures":  "https://www.cftc.gov/files/dea/history/fut_disagg_txt_hist_2006_2016.zip",
    "disagg_combined": "https://www.cftc.gov/files/dea/history/com_disagg_txt_hist_2006_2016.zip",
}

_ANNUAL_ZIP_URL_PATTERNS = {
    "disagg_futures":  "https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip",
    "disagg_combined": "https://www.cftc.gov/files/dea/history/com_disagg_txt_{year}.zip",
}

_WEEKLY_TXT_URLS = {
    "disagg_futures":  "https://www.cftc.gov/dea/newcot/f_disagg.txt",
    "disagg_combined": "https://www.cftc.gov/dea/newcot/c_disagg.txt",
}

# File prefix used in S3 keys.
_S3_PREFIX = {
    "disagg_futures":  "fut_disagg",
    "disagg_combined": "com_disagg",
}

_REPORT_TYPES = list(_BULK_ZIP_URLS.keys())

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Header column name carried by the annual / bulk backfill ZIP files.  The live
# weekly newcot TXT files (f_disagg.txt / c_disagg.txt) became HEADERLESS in
# 2026 — their first line is now the first data row rather than this header.
_EXPECTED_HEADER_COLUMN = "Market_and_Exchange_Names"

# The disaggregated "short format" is a fixed 191-column schema.  A headerless
# weekly data row must have exactly this many fields; anything else (an HTML
# error page, a truncated file, or a schema change) fails validation closed.
_EXPECTED_FIELD_COUNT = 191

# Exchange separator that appears in every CFTC Market_and_Exchange_Names value
# (e.g. "CORN - CHICAGO BOARD OF TRADE").  Used to sanity-check that the first
# field of a headerless file really is a market name and not stray text.
_MARKET_EXCHANGE_SEP = " - "

# CORN-CBOT (002602) appears in every annual and weekly disaggregated file.
# Used as a sentinel to confirm we have a valid COT file (not an HTML error page).
_SENTINEL_CONTRACT_CODE = "002602"

# Timeout for each request.  Annual ZIPs can be 5–15 MB; 120 s is generous.
_DOWNLOAD_TIMEOUT = 120

# Polite delay between requests in backfill mode.
_BACKFILL_SLEEP = 0.5

# Content-type for S3 metadata.
_CONTENT_TYPE = "text/plain"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_txt_from_zip(zip_bytes: bytes, url: str) -> bytes:
    """Unzip *zip_bytes* in memory and return the first .txt file found.

    Each CFTC historical ZIP contains exactly one TXT file.  We do not
    assume a specific filename inside the archive.
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        txt_names = [n for n in zf.namelist() if n.lower().endswith(".txt")]
        if not txt_names:
            raise RuntimeError(
                f"No .txt file found in ZIP from {url}. "
                f"Archive contents: {zf.namelist()}"
            )
        return zf.read(txt_names[0])


def _validate_txt(data: bytes, url: str) -> None:
    """Raise RuntimeError if *data* does not look like a valid COT TXT file.

    Accepts both on-disk variants of the disaggregated report:

    * Headered — the annual / 2006-2016 bulk ZIP files.  Line 1 is the column
      header containing :data:`_EXPECTED_HEADER_COLUMN`.
    * Headerless — the live weekly newcot TXT files (headerless since 2026).
      Line 1 is the first data row; it must have exactly
      :data:`_EXPECTED_FIELD_COUNT` fields and begin with a market name.

    Fails closed on genuinely wrong payloads (HTML error pages, truncated files,
    wrong field count) regardless of variant.
    """
    body = data.decode("utf-8", errors="replace")
    try:
        first_line = body.splitlines()[0]
    except IndexError as exc:
        raise RuntimeError(
            f"Validation failed: empty file from {url}"
        ) from exc

    if _EXPECTED_HEADER_COLUMN not in first_line:
        # Headerless (weekly) file — structurally validate the first data row.
        try:
            fields = next(csv.reader([first_line]))
        except csv.Error as exc:
            raise RuntimeError(
                f"Validation failed: could not CSV-parse first line from {url}. "
                f"First line: {first_line[:200]!r}"
            ) from exc

        if len(fields) != _EXPECTED_FIELD_COUNT:
            raise RuntimeError(
                f"Validation failed: expected a header column "
                f"'{_EXPECTED_HEADER_COLUMN}' or a {_EXPECTED_FIELD_COUNT}-field "
                f"headerless data row from {url}, got {len(fields)} fields. "
                f"First line: {first_line[:200]!r}"
            )

        market = fields[0].strip()
        if _MARKET_EXCHANGE_SEP not in market or market[:1].isdigit():
            raise RuntimeError(
                f"Validation failed: first field {market[:80]!r} from {url} does "
                "not look like a CFTC market name (expected '<COMMODITY> - "
                "<EXCHANGE>'). File may be an HTML error response."
            )

    # Confirm the sentinel contract code is present anywhere in the file.
    # Avoids silently storing HTML error pages as if they were COT data.
    if _SENTINEL_CONTRACT_CODE not in body:
        raise RuntimeError(
            f"Validation failed: sentinel contract code '{_SENTINEL_CONTRACT_CODE}' "
            f"(CORN-CBOT) not found in data from {url}. "
            "File may be empty, truncated, or an HTML error response."
        )


def _fetch_zip_and_extract(
    session: requests.Session, url: str, label: str
) -> bytes:
    """Download a CFTC ZIP, extract the TXT, validate, and return bytes."""
    logger.info("Downloading ZIP %s …", url)
    resp = session.get(url, timeout=_DOWNLOAD_TIMEOUT)
    resp.raise_for_status()
    logger.info("  ZIP: %.1f KB received", len(resp.content) / 1024)

    data = _extract_txt_from_zip(resp.content, url)
    logger.info("  TXT: %.1f KB after extraction", len(data) / 1024)

    _validate_txt(data, url)
    check_min_file_size(data, "cftc_cot", context=label)
    return data


def _fetch_txt(session: requests.Session, url: str, label: str) -> bytes:
    """Download a CFTC live TXT file, validate, and return bytes."""
    logger.info("Downloading TXT %s …", url)
    resp = session.get(url, timeout=_DOWNLOAD_TIMEOUT)
    resp.raise_for_status()
    data = resp.content
    logger.info("  %.1f KB received", len(data) / 1024)

    _validate_txt(data, url)
    check_min_file_size(data, "cftc_cot", context=label)
    return data


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------

def run_backfill(
    end_year: int,
    bucket: str,
    region: str,
    skip_existing: bool,
    dry_run: bool,
) -> None:
    """Download the 2006–2016 bulk file plus annual files (2017–end_year).

    Runs for both report types.  Order: bulk first, then annual years
    ascending, interleaved across report types to keep the sleep cadence
    predictable.
    """
    annual_years = list(range(2017, end_year + 1))
    total_files = len(_REPORT_TYPES) * (1 + len(annual_years))
    logger.info(
        "Backfill: %d report types × (1 bulk + %d annual) = %d files total",
        len(_REPORT_TYPES), len(annual_years), total_files,
    )

    if dry_run:
        for rtype in _REPORT_TYPES:
            s3_key = raw_cot_backfill_key(rtype, "2006_2016")
            print(f"[dry-run] s3://{bucket}/{s3_key}")
        for year in annual_years:
            for rtype in _REPORT_TYPES:
                s3_key = raw_cot_backfill_key(rtype, str(year))
                print(f"[dry-run] s3://{bucket}/{s3_key}")
        return

    session = requests.Session()
    session.headers.update({"User-Agent": _UA})

    uploaded = skipped = failed = 0
    request_count = 0  # tracks requests made to enforce sleep

    # --- 2006–2016 bulk files ---
    for rtype in _REPORT_TYPES:
        s3_key = raw_cot_backfill_key(rtype, "2006_2016")
        url = _BULK_ZIP_URLS[rtype]
        label = f"cftc_cot {rtype} bulk 2006_2016"

        if skip_existing and s3_object_exists(bucket, s3_key, region):
            logger.info("[skip] already in S3: %s", s3_key)
            skipped += 1
            continue

        if request_count > 0:
            time.sleep(_BACKFILL_SLEEP)

        try:
            data = _fetch_zip_and_extract(session, url, label)
            upload_bytes_to_s3(data, bucket, s3_key, region)
            write_raw_s3_metadata(bucket, s3_key, data, url, _CONTENT_TYPE, region)
            logger.info("  → s3://%s/%s", bucket, s3_key)
            uploaded += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("FAILED %s — %s", label, exc)
            failed += 1

        request_count += 1

    # --- Annual files 2017–end_year ---
    for year in annual_years:
        for rtype in _REPORT_TYPES:
            s3_key = raw_cot_backfill_key(rtype, str(year))
            url = _ANNUAL_ZIP_URL_PATTERNS[rtype].format(year=year)
            label = f"cftc_cot {rtype} {year}"

            if skip_existing and s3_object_exists(bucket, s3_key, region):
                logger.info("[skip] already in S3: %s", s3_key)
                skipped += 1
                continue

            if request_count > 0:
                time.sleep(_BACKFILL_SLEEP)

            try:
                data = _fetch_zip_and_extract(session, url, label)
                upload_bytes_to_s3(data, bucket, s3_key, region)
                write_raw_s3_metadata(bucket, s3_key, data, url, _CONTENT_TYPE, region)
                logger.info("  → s3://%s/%s", bucket, s3_key)
                uploaded += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("FAILED %s — %s", label, exc)
                failed += 1

            request_count += 1

    logger.info(
        "Backfill complete. uploaded=%d  skipped=%d  failed=%d",
        uploaded, skipped, failed,
    )
    if failed:
        raise SystemExit(f"{failed} file(s) failed — see log above.")


# ---------------------------------------------------------------------------
# Weekly snapshot
# ---------------------------------------------------------------------------

def run_weekly(
    as_of_date: str,
    bucket: str,
    region: str,
    skip_existing: bool,
    dry_run: bool,
) -> None:
    """Download the current-week TXT files for both report types."""
    year = int(as_of_date[:4])

    if dry_run:
        for rtype in _REPORT_TYPES:
            s3_key = raw_cot_weekly_key(rtype, year, as_of_date)
            print(f"[dry-run] s3://{bucket}/{s3_key}")
        return

    session = requests.Session()
    session.headers.update({"User-Agent": _UA})

    uploaded = skipped = failed = 0

    for i, rtype in enumerate(_REPORT_TYPES):
        s3_key = raw_cot_weekly_key(rtype, year, as_of_date)
        url = _WEEKLY_TXT_URLS[rtype]
        label = f"cftc_cot {rtype} weekly {as_of_date}"

        if skip_existing and s3_object_exists(bucket, s3_key, region):
            logger.info("[skip] already in S3: %s", s3_key)
            skipped += 1
            continue

        if i > 0:
            time.sleep(_BACKFILL_SLEEP)

        try:
            data = _fetch_txt(session, url, label)
            upload_bytes_to_s3(data, bucket, s3_key, region)
            write_raw_s3_metadata(bucket, s3_key, data, url, _CONTENT_TYPE, region)
            logger.info("Weekly snapshot → s3://%s/%s", bucket, s3_key)
            uploaded += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("FAILED %s — %s", label, exc)
            failed += 1

    logger.info(
        "Weekly complete. uploaded=%d  skipped=%d  failed=%d",
        uploaded, skipped, failed,
    )
    if failed:
        raise SystemExit(f"{failed} file(s) failed — see log above.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    today = datetime.date.today()
    current_year = today.year
    default_as_of = today.strftime("%Y%m%d")

    parser = argparse.ArgumentParser(
        description=(
            "Download CFTC Disaggregated COT reports (futures-only and "
            "futures+options combined) to raw S3. No API key required."
        )
    )
    parser.add_argument(
        "--mode",
        choices=["backfill", "weekly"],
        required=True,
        help=(
            "backfill: download the 2006–2016 bulk file and annual ZIPs "
            "(2017 through end-year) for both report types. "
            "weekly: download the current-week live TXT files."
        ),
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=current_year - 1,
        metavar="YYYY",
        help=(
            f"Last year to download in backfill mode (default: {current_year - 1}). "
            "The 2006–2016 bulk file is always included regardless of this value."
        ),
    )
    parser.add_argument(
        "--as-of",
        default=default_as_of,
        metavar="YYYYMMDD",
        help=(
            f"Publication date for weekly mode (default: today = {default_as_of}). "
            "Should be the Friday on which CFTC publishes (positions as-of Tuesday)."
        ),
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help="Skip download if the S3 key already exists (safe for re-runs).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print S3 keys without downloading anything.",
    )
    args = parser.parse_args()

    if not args.dry_run:
        load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET") if not args.dry_run else "BUCKET"
    region = get_required_env("AWS_REGION") if not args.dry_run else "us-east-1"

    if args.mode == "backfill":
        run_backfill(
            end_year=args.end_year,
            bucket=bucket,
            region=region,
            skip_existing=args.skip_existing_s3,
            dry_run=args.dry_run,
        )
    else:
        run_weekly(
            as_of_date=args.as_of,
            bucket=bucket,
            region=region,
            skip_existing=args.skip_existing_s3,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
