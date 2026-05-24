"""Fetch the USDA NASS QuickStats bulk crops-sector .gz to raw S3.

Source
------
USDA National Agricultural Statistics Service (NASS) — QuickStats large datasets
    https://www.nass.usda.gov/datasets/

No authentication required.  The file is publicly accessible and contains the
full QuickStats CROPS sector as a tab-delimited text file, compressed with gzip.
Coverage includes all U.S. commodities (corn, soybeans, wheat, cotton, rice, …),
all geographies (national, state, county — ~3,100 counties), and all time periods
from the 1860s to the present day.

Two distinct signals are bundled in the same file:

1. **Annual production stats** — AREA PLANTED, AREA HARVESTED, YIELD, PRODUCTION
   at national / state / county level.  Complements USDA PSD (which is global
   balance sheets) with sub-national U.S. measurements from actual farmer surveys.

2. **Crop Progress** (weekly, ``statisticcat_desc = 'PROGRESS'``,
   ``unit_desc = 'PCT'``) — % planted, % emerged, % rated Good/Excellent, etc.
   Released every Monday at 4 pm ET during growing season.  This is the single
   most-watched leading indicator for U.S. corn and soybean futures.

URL format
----------
The datasets page lists files named ``qs.crops_{YYYYMMDD}.txt.gz``, regenerated
nightly at ~3 am ET with the current date in the filename.  There is no stable
permanent URL, so this script scrapes the datasets index page to discover the
current filename, then derives the ``download_date`` from the filename itself.

S3 key structure
----------------
    raw/production/source=usda_nass/sector=crops/
        download_date={YYYY-MM-DD}/qs.crops.txt.gz

The date-stamped portion of the original filename is captured in the partition
key; the stored filename is normalised to ``qs.crops.txt.gz``.

Update schedule
---------------
Run monthly (or after each major USDA crops report).  Each download captures
all weekly Crop Progress rows accumulated since the last download alongside
the updated annual production figures.

Idempotency
-----------
Pass ``--skip-existing-s3`` to skip the download if the key already exists.
Pass ``--dry-run`` to discover and print the source URL and S3 key without
downloading anything.
"""
from __future__ import annotations

import argparse
import gzip
import io
import logging
import re
import zlib

import requests

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_nass_crops_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DATASETS_INDEX_URL = "https://www.nass.usda.gov/datasets/"
_DATASETS_BASE_URL = "https://www.nass.usda.gov/datasets/"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Regex to extract the crops bulk file link from the datasets index page.
# Matches: qs.crops_20260520.txt.gz
_CROPS_FILENAME_RE = re.compile(r'(qs\.crops_(\d{8})\.txt\.gz)')

# Expected column name in the first line of the decompressed CSV (headers are uppercase).
_EXPECTED_COLUMN = "SOURCE_DESC"

# Download timeout in seconds.  The file is ~1 GB; allow 15 minutes.
_DOWNLOAD_TIMEOUT = 900

# Streaming chunk size: 8 MB.
_CHUNK_SIZE = 8 * 1024 * 1024


# ---------------------------------------------------------------------------
# URL discovery
# ---------------------------------------------------------------------------

def _discover_crops_url(session: requests.Session) -> tuple[str, str]:
    """Scrape the NASS datasets index page and return (url, download_date).

    Args:
        session: An active :class:`requests.Session`.

    Returns:
        A tuple of ``(full_url, download_date)`` where ``download_date`` is in
        ``YYYY-MM-DD`` format parsed from the filename (e.g. ``"2026-05-20"``).

    Raises:
        RuntimeError: If no crops bulk file link is found on the page.
    """
    logger.info("Discovering current qs.crops URL from %s …", _DATASETS_INDEX_URL)
    resp = session.get(_DATASETS_INDEX_URL, timeout=30)
    resp.raise_for_status()

    match = _CROPS_FILENAME_RE.search(resp.text)
    if not match:
        raise RuntimeError(
            f"Could not find a qs.crops_*.txt.gz link on {_DATASETS_INDEX_URL}. "
            "NASS may have changed the page layout."
        )

    filename = match.group(1)          # e.g. "qs.crops_20260520.txt.gz"
    date_str = match.group(2)          # e.g. "20260520"
    download_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"  # "2026-05-20"
    url = _DATASETS_BASE_URL + filename

    logger.info("Discovered: %s  (download_date=%s)", url, download_date)
    return url, download_date


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_gz(data: bytes, source_url: str) -> None:
    """Validate that *data* is a well-formed gzip file containing the NASS CSV.

    Checks:
    1. Gzip magic bytes (``0x1f 0x8b``) at the start.
    2. Decompressing the first 4 KB yields a line containing the expected
       column header ``source_desc``.

    Raises:
        RuntimeError: If either check fails.
    """
    if len(data) < 2 or data[:2] != b'\x1f\x8b':
        raise RuntimeError(
            f"Validation failed: response from {source_url} does not start with "
            f"gzip magic bytes (got {data[:2]!r})."
        )

    try:
        with gzip.open(io.BytesIO(data)) as gz:
            head = gz.read(4096)
    except (OSError, EOFError, zlib.error) as exc:
        raise RuntimeError(
            f"Validation failed: could not decompress gzip header from {source_url}: {exc}"
        ) from exc

    first_line = head.decode("utf-8", errors="replace").splitlines()[0] if head else ""
    if _EXPECTED_COLUMN not in first_line:
        raise RuntimeError(
            f"Validation failed: expected column '{_EXPECTED_COLUMN}' not found in "
            f"first line of decompressed content from {source_url}. "
            f"First line: {first_line[:200]!r}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(
        description=(
            "Download the USDA NASS QuickStats bulk crops .gz to raw S3. "
            "Discovers the current file URL by scraping the NASS datasets index page. "
            "No API key required."
        )
    )
    parser.add_argument(
        "--download-date",
        default=None,
        metavar="YYYY-MM-DD",
        help=(
            "Override the S3 partition date (default: date parsed from the discovered "
            "filename, e.g. '2026-05-20'). Only affects the S3 key; does not change "
            "which file is downloaded."
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
        help=(
            "Discover the source URL and print the S3 key without downloading anything."
        ),
    )
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": _UA})

    # Always discover the URL — cheap GET against the index page.
    source_url, discovered_date = _discover_crops_url(session)
    download_date = args.download_date or discovered_date
    s3_key = raw_nass_crops_key(download_date)

    # ------------------------------------------------------------------
    # Dry run
    # ------------------------------------------------------------------
    if args.dry_run:
        print(f"Source URL    : {source_url}")
        print(f"S3 key        : {s3_key}")
        print(f"Download date : {download_date}")
        session.close()
        return

    # ------------------------------------------------------------------
    # Live run
    # ------------------------------------------------------------------
    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    if args.skip_existing_s3 and s3_object_exists(bucket, s3_key, region):
        logger.info("Skipping — already in S3: %s", s3_key)
        session.close()
        return

    logger.info("Downloading %s …", source_url)

    buf = bytearray()
    with session.get(source_url, stream=True, timeout=_DOWNLOAD_TIMEOUT) as resp:
        resp.raise_for_status()
        for chunk in resp.iter_content(chunk_size=_CHUNK_SIZE):
            if chunk:
                buf.extend(chunk)
                if len(buf) % (100 * 1024 * 1024) < _CHUNK_SIZE:
                    logger.info("  … %.0f MB received", len(buf) / 1_048_576)

    data = bytes(buf)
    logger.info("Download complete: %.1f MB", len(data) / 1_048_576)

    _validate_gz(data, source_url)
    logger.info("Validation passed.")

    check_min_file_size(data, "usda_nass_crops", context=source_url)

    upload_bytes_to_s3(data, bucket, s3_key, region)
    logger.info("Uploaded → s3://%s/%s", bucket, s3_key)

    write_raw_s3_metadata(
        bucket,
        s3_key,
        data,
        source_url,
        "application/gzip",
        region,
    )
    logger.info("Metadata written → raw_meta/%s_meta.json", s3_key)

    session.close()
    logger.info(
        "Done. download_date=%s  size=%.1f MB  key=%s",
        download_date,
        len(data) / 1_048_576,
        s3_key,
    )


if __name__ == "__main__":
    main()
