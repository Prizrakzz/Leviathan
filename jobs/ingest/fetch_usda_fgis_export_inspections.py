"""Fetch USDA FGIS Export Inspections CSVs to raw S3.

Source
------
USDA Federal Grain Inspection Service (FGIS) — per-shipment export grain records
    https://fgisonline.ams.usda.gov/ExportGrainReport/

No authentication required.  Files are publicly accessible CSVs.

Two modes
---------
backfill
    Download historical annual CSV files CY{start_year}–CY{end_year} to the
    static ``backfill/`` S3 prefix.  Prior-year files are frozen once the
    calendar year closes; a single download per year is sufficient.

    Default range: 1983 to (current_year - 1).

weekly
    Snapshot the current-year CSV (CY{year}.csv) to a date-partitioned key
    ``year={year}/as_of={YYYYMMDD}/CY{year}.csv``.

    FGIS updates the current-year file in-place every week.  Storing an
    immutable snapshot on each Thursday preserves point-in-time correctness
    for backtested ML features (prevents lookahead bias).

S3 key structure
----------------
    backfill:  raw/production/source=usda_fgis_export_inspections/backfill/CY{year}.csv
    weekly:    raw/production/source=usda_fgis_export_inspections/year={year}/as_of={YYYYMMDD}/CY{year}.csv

Update schedule
---------------
Run --mode weekly every Thursday after FGIS publishes (Mon–Wed).
The Airflow DAG ``fgis_weekly_ingest`` handles this automatically.

Idempotency
-----------
Pass ``--skip-existing-s3`` to skip files already present in S3.
Pass ``--dry-run`` to print S3 keys without downloading anything.
"""
from __future__ import annotations

import argparse
import logging
import datetime
import time

import requests

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_fgis_backfill_key, raw_fgis_weekly_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://fgisonline.ams.usda.gov/ExportGrainReport"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Expected column in the CSV header — used to validate the download.
_EXPECTED_HEADER_COLUMN = "date"

# Minimum plausible CSV size.  Even the sparse 1983 file is several hundred KB.
_MIN_SIZE_BYTES = 10_000

# Timeout for each file download.  Files are 1–20 MB; 60 s is generous.
_DOWNLOAD_TIMEOUT = 60

# Polite delay between requests in backfill mode.
_BACKFILL_SLEEP = 0.5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_url(year: int) -> str:
    return f"{_BASE_URL}/CY{year}.csv"


def _validate_csv(data: bytes, url: str) -> None:
    """Raise RuntimeError if *data* does not look like a valid FGIS CSV."""
    try:
        first_line = data[:512].decode("utf-8", errors="replace").splitlines()[0].lower()
    except (IndexError, UnicodeDecodeError) as exc:
        raise RuntimeError(
            f"Validation failed: could not decode first line from {url}"
        ) from exc

    if _EXPECTED_HEADER_COLUMN not in first_line:
        raise RuntimeError(
            f"Validation failed: expected column '{_EXPECTED_HEADER_COLUMN}' not found "
            f"in CSV header from {url}. First line: {first_line[:200]!r}"
        )


def _fetch_one(session: requests.Session, year: int) -> bytes:
    """Download CY{year}.csv and return raw bytes."""
    url = _build_url(year)
    logger.info("Downloading %s …", url)
    resp = session.get(url, timeout=_DOWNLOAD_TIMEOUT)
    resp.raise_for_status()
    data = resp.content
    logger.info("  %.1f KB received", len(data) / 1024)
    _validate_csv(data, url)
    check_min_file_size(data, f"usda_fgis_export_inspections CY{year}", context=url)
    return data


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------

def run_backfill(
    start_year: int,
    end_year: int,
    bucket: str,
    region: str,
    skip_existing: bool,
    dry_run: bool,
) -> None:
    years = range(start_year, end_year + 1)
    logger.info("Backfill: %d years (%d–%d)", len(years), start_year, end_year)

    if dry_run:
        for year in years:
            print(f"[dry-run] s3://{bucket}/{raw_fgis_backfill_key(year)}")
        return

    session = requests.Session()
    session.headers.update({"User-Agent": _UA})

    uploaded = skipped = failed = 0

    for i, year in enumerate(years):
        s3_key = raw_fgis_backfill_key(year)

        if skip_existing and s3_object_exists(bucket, s3_key, region):
            logger.info("  [skip] already in S3: %s", s3_key)
            skipped += 1
            continue

        try:
            data = _fetch_one(session, year)
            upload_bytes_to_s3(data, bucket, s3_key, region)
            write_raw_s3_metadata(
                bucket, s3_key, data, _build_url(year), "text/csv", region
            )
            logger.info("  → s3://%s/%s", bucket, s3_key)
            uploaded += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("  FAILED CY%d — %s", year, exc)
            failed += 1

        if i < len(years) - 1:
            time.sleep(_BACKFILL_SLEEP)

    logger.info(
        "Backfill complete. uploaded=%d  skipped=%d  failed=%d",
        uploaded, skipped, failed,
    )
    if failed:
        raise SystemExit(f"{failed} year(s) failed — see log above.")


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
    year = int(as_of_date[:4])
    s3_key = raw_fgis_weekly_key(year, as_of_date)

    if dry_run:
        print(f"[dry-run] s3://{bucket}/{s3_key}")
        return

    if skip_existing and s3_object_exists(bucket, s3_key, region):
        logger.info("Skipping — already in S3: %s", s3_key)
        return

    session = requests.Session()
    session.headers.update({"User-Agent": _UA})

    data = _fetch_one(session, year)
    upload_bytes_to_s3(data, bucket, s3_key, region)
    write_raw_s3_metadata(
        bucket, s3_key, data, _build_url(year), "text/csv", region
    )
    logger.info("Weekly snapshot → s3://%s/%s", bucket, s3_key)


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
            "Download USDA FGIS Export Inspections CSVs to raw S3. "
            "No API key required."
        )
    )
    parser.add_argument(
        "--mode",
        choices=["backfill", "weekly"],
        required=True,
        help=(
            "backfill: download historical annual CSVs (1983–last year). "
            "weekly: snapshot the current-year CSV with an as_of date partition."
        ),
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=1983,
        metavar="YYYY",
        help="First year to download in backfill mode (default: 1983).",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=current_year - 1,
        metavar="YYYY",
        help=f"Last year to download in backfill mode (default: {current_year - 1}).",
    )
    parser.add_argument(
        "--as-of",
        default=default_as_of,
        metavar="YYYYMMDD",
        help=(
            f"Snapshot date for weekly mode (default: today = {default_as_of}). "
            "Used as the as_of partition key."
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
            start_year=args.start_year,
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
