"""Fetch the USDA PSD bulk all-commodities ZIP to raw S3.

Source
------
USDA Foreign Agricultural Service — Production, Supply and Distribution (PSD)
    https://apps.fas.usda.gov/psdonline/downloads/psd_alldata_csv.zip

No authentication required.  The file is a publicly accessible ZIP containing
a single CSV with all PSD commodities, all countries, all marketing years
(1960s–present), and all monthly WASDE vintages.

The ``Month`` column in the CSV records which WASDE release produced each row,
enabling downstream bronze/silver jobs to compute WASDE revision-surprise
features via diff(current_month_value - prior_month_value).

S3 key structure
----------------
    raw/production/source=usda_psd/release_type=bulk/
        release_date={YYYY-MM-DD}/psd_alldata.zip

Using ``release_date`` (daily granularity) rather than ``release_month`` avoids
key collision when downloading both before and after the WASDE release within
the same calendar month (WASDE drops on the second Friday of each month).

Update schedule
---------------
WASDE releases monthly (second Friday).  Re-run this script after each WASDE
to capture the revised vintage.  Use ``--skip-existing-s3`` on same-day re-runs.

Idempotency
-----------
Pass ``--skip-existing-s3`` to skip the download if the key already exists in S3.
Pass ``--dry-run`` to print the S3 key without downloading anything.
"""
from __future__ import annotations

import argparse
import datetime
import io
import zipfile

import requests

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_psd_bulk_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BULK_URL = "https://apps.fas.usda.gov/psdonline/downloads/psd_alldata_csv.zip"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Expected column name in the CSV header — used to validate the download.
_EXPECTED_COLUMN = "Commodity_Code"

# Timeout for the streaming download.  The file is ~50-80 MB; allow 3 minutes.
_DOWNLOAD_TIMEOUT = 180


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_zip(data: bytes, source_url: str) -> str:
    """Validate that *data* is a well-formed ZIP containing the PSD CSV.

    Returns the name of the CSV file found inside the ZIP.

    Raises:
        RuntimeError: If validation fails for any reason.
    """
    buf = io.BytesIO(data)

    if not zipfile.is_zipfile(buf):
        raise RuntimeError(
            f"Validation failed: response from {source_url} is not a valid ZIP file."
        )

    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            raise RuntimeError(
                f"Validation failed: no CSV file found inside ZIP from {source_url}. "
                f"Contents: {zf.namelist()}"
            )

        csv_name = csv_names[0]

        # Read just the first line to verify the expected column header is present.
        with zf.open(csv_name) as csv_file:
            first_line = csv_file.readline().decode("utf-8", errors="replace")

        if _EXPECTED_COLUMN not in first_line:
            raise RuntimeError(
                f"Validation failed: expected column '{_EXPECTED_COLUMN}' not found in "
                f"CSV header of '{csv_name}'. "
                f"First line: {first_line[:200]!r}"
            )

    return csv_name


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    today = datetime.date.today().isoformat()  # e.g. "2026-05-20"

    parser = argparse.ArgumentParser(
        description=(
            "Download the USDA PSD bulk all-commodities ZIP to raw S3. "
            "No API key required."
        )
    )
    parser.add_argument(
        "--release-date",
        default=today,
        metavar="YYYY-MM-DD",
        help=(
            f"Date label for the S3 key partition (default: today = {today}). "
            "Use the WASDE release date when downloading after a WASDE drop."
        ),
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help="Skip the download if the S3 key already exists (safe for re-runs).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the S3 key and source URL without downloading anything.",
    )
    args = parser.parse_args()

    s3_key = raw_psd_bulk_key(args.release_date)

    # ------------------------------------------------------------------
    # Dry run
    # ------------------------------------------------------------------
    if args.dry_run:
        print(f"Source URL : {_BULK_URL}")
        print(f"S3 key     : {s3_key}")
        print(f"Release    : {args.release_date}")
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

    logger.info("Downloading USDA PSD bulk ZIP from %s …", _BULK_URL)

    session = requests.Session()
    session.headers.update({"User-Agent": _UA})

    resp = session.get(_BULK_URL, timeout=_DOWNLOAD_TIMEOUT, stream=False)
    resp.raise_for_status()
    data = resp.content

    logger.info("Downloaded %.1f MB", len(data) / 1_048_576)

    # Validate: well-formed ZIP + CSV header
    csv_name = _validate_zip(data, _BULK_URL)
    logger.info("Validation passed — CSV inside ZIP: %s", csv_name)

    # Validate minimum file size
    check_min_file_size(data, "usda_psd", context=_BULK_URL)

    upload_bytes_to_s3(data, bucket, s3_key, region)
    logger.info("Uploaded → s3://%s/%s", bucket, s3_key)

    write_raw_s3_metadata(
        bucket,
        s3_key,
        data,
        _BULK_URL,
        "application/zip",
        region,
    )
    logger.info("Metadata written → raw_meta/%s_meta.json", s3_key)

    session.close()
    logger.info(
        "Done. release_date=%s  size=%.1f MB  key=%s",
        args.release_date,
        len(data) / 1_048_576,
        s3_key,
    )


if __name__ == "__main__":
    main()
