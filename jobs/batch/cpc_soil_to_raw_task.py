"""AWS Batch entrypoint: NOAA CPC Soil Moisture daily GeoTIFFs → raw S3.

Runs as a Fargate container task.  No Glue bootstrap — leviathan is
installed in the image via ``pip install -e ".[batch]"``.

For years prior to the current year, downloads the full annual tarball
(~82–89MB) and extracts all 365/366 daily GeoTIFFs in memory.  For the
current year, downloads individual daily files from the live GeoTIFF
directory (since the annual tarball is incomplete mid-year).

Raw S3 path: raw/weather/source=cpc_soil/variable={v}/date={YYYYMMDD}/{v}.{YYYYMMDD}.tif

Required args: --year, --bucket, --aws_region
Optional args: --variable (default: w), --ingest_date, --force_overwrite
"""
from __future__ import annotations

import argparse
import calendar
import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone

import boto3
import requests

from leviathan.common.logging import get_logger
from leviathan.ingestion.weather.cpc_soil_moisture import (
    download_cpc_annual_tarball,
    download_cpc_daily_tif,
    extract_tifs_from_tarball,
    CPC_FTP_BASE,
)
from leviathan.storage.paths import raw_cpc_tif_key
from leviathan.storage.s3 import get_thread_local_s3_client

logger = get_logger("cpc_soil_to_raw_task")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _put_tif(
    s3_client,
    bucket: str,
    variable: str,
    date_str: str,
    tif_bytes: bytes,
    source_url: str,
    access_timestamp: str,
    force_overwrite: bool,
) -> bool:
    """Write one TIF and its companion meta JSON to S3 raw.  Returns True if written."""
    filename = f"{variable}.{date_str}.tif"
    key = raw_cpc_tif_key(variable, date_str, filename)

    if not force_overwrite:
        try:
            s3_client.head_object(Bucket=bucket, Key=key)
            logger.debug("Skip existing: %s", key)
            return False
        except s3_client.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] != "404":
                raise

    s3_client.put_object(Bucket=bucket, Key=key, Body=tif_bytes)
    logger.info("Wrote raw TIF: %s (%d bytes)", key, len(tif_bytes))

    meta_key = key.replace(f"{filename}", "_meta.json")
    meta = {
        "source": "cpc_soil",
        "variable": variable,
        "date": date_str,
        "file_size_bytes": len(tif_bytes),
        "source_url": source_url,
        "access_timestamp": access_timestamp,
    }
    s3_client.put_object(
        Bucket=bucket,
        Key=meta_key,
        Body=json.dumps(meta, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    return True


# ---------------------------------------------------------------------------
# Historical backfill (annual tarball)
# ---------------------------------------------------------------------------

def _process_year_via_tarball(
    year: int,
    variable: str,
    bucket: str,
    aws_region: str,
    ingest_date: str,
    force_overwrite: bool,
) -> tuple[int, int]:
    """Download annual tarball, extract all TIFs, store to S3.  Returns (written, skipped)."""
    tar_bytes = download_cpc_annual_tarball(year, variable)
    daily_tifs = extract_tifs_from_tarball(tar_bytes, variable)

    if not daily_tifs:
        logger.warning("No TIFs extracted from tarball for variable=%s year=%d", variable, year)
        return 0, 0

    access_timestamp = datetime.now(timezone.utc).isoformat()
    source_url_template = f"{CPC_FTP_BASE}/clim/{variable}.{year}.tif.tar.gz"

    written = skipped = 0

    def _upload(date_str: str, tif_bytes: bytes) -> bool:
        s3_client = get_thread_local_s3_client(aws_region)
        return _put_tif(
            s3_client, bucket, variable, date_str, tif_bytes,
            source_url_template, access_timestamp, force_overwrite,
        )

    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(_upload, ds, tb): ds for ds, tb in daily_tifs.items()}
        for future in as_completed(futures):
            if future.result():
                written += 1
            else:
                skipped += 1

    logger.info(
        "Tarball backfill complete  variable=%s year=%d  written=%d skipped=%d",
        variable, year, written, skipped,
    )
    return written, skipped


# ---------------------------------------------------------------------------
# Current-year incremental (daily files)
# ---------------------------------------------------------------------------

def _list_available_daily_dates(year: int, variable: str) -> list[str]:
    """Return YYYYMMDD strings for all daily TIF files available in the live GeoTIFF directory."""
    url = f"{CPC_FTP_BASE}/GeoTIFF/"
    logger.info("Listing CPC GeoTIFF directory: %s", url)
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Failed to list GeoTIFF directory: %s — falling back to calendar enumeration", exc)
        return _enumerate_dates_up_to_today(year)

    prefix = f"{variable}.{year}"
    dates: list[str] = []
    for line in resp.text.splitlines():
        # HTML anchor lines contain the filename: href="w.20260524.tif"
        for token in line.split('"'):
            if token.startswith(prefix) and token.endswith(".tif"):
                stem = token[len(variable) + 1:-4]  # strip "w." and ".tif"
                try:
                    datetime.strptime(stem, "%Y%m%d")
                    dates.append(stem)
                except ValueError:
                    pass
    if dates:
        logger.info("Found %d daily files for %s %d in GeoTIFF dir", len(dates), variable, year)
        return sorted(dates)
    # Fallback if directory listing didn't parse cleanly
    return _enumerate_dates_up_to_today(year)


def _enumerate_dates_up_to_today(year: int) -> list[str]:
    """Return YYYYMMDD strings for every day from Jan 1 of year up to yesterday (1-day lag)."""
    today = date.today()
    cutoff = date(today.year, today.month, today.day)
    dates = []
    for month in range(1, 13):
        days_in_month = calendar.monthrange(year, month)[1]
        for day in range(1, days_in_month + 1):
            d = date(year, month, day)
            if d >= cutoff:
                break
            dates.append(d.strftime("%Y%m%d"))
        else:
            continue
        break
    return dates


def _process_year_via_daily_files(
    year: int,
    variable: str,
    bucket: str,
    aws_region: str,
    ingest_date: str,
    force_overwrite: bool,
) -> tuple[int, int]:
    """Download individual daily TIFs for the current year.  Returns (written, skipped)."""
    dates = _list_available_daily_dates(year, variable)
    logger.info("Processing %d daily files for variable=%s year=%d", len(dates), variable, year)

    access_timestamp = datetime.now(timezone.utc).isoformat()
    written = skipped = 0

    def _fetch_and_upload(date_str: str) -> bool:
        source_url = f"{CPC_FTP_BASE}/GeoTIFF/{variable}.{date_str}.tif"
        try:
            tif_bytes = download_cpc_daily_tif(date_str, variable)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to download %s %s: %s — skipping", variable, date_str, exc)
            return False
        s3_client = get_thread_local_s3_client(aws_region)
        return _put_tif(
            s3_client, bucket, variable, date_str, tif_bytes,
            source_url, access_timestamp, force_overwrite,
        )

    with ThreadPoolExecutor(max_workers=5) as pool:  # cap to avoid hammering NOAA FTP
        futures = {pool.submit(_fetch_and_upload, ds): ds for ds in dates}
        for future in as_completed(futures):
            if future.result():
                written += 1
            else:
                skipped += 1

    logger.info(
        "Daily ingest complete  variable=%s year=%d  written=%d skipped=%d",
        variable, year, written, skipped,
    )
    return written, skipped


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(description="CPC Soil Moisture → raw S3 (Batch task)")
    parser.add_argument("--year",           required=True, type=int)
    parser.add_argument("--bucket",         required=True)
    parser.add_argument("--aws_region",     required=True)
    parser.add_argument("--variable",       default="w", help="CPC variable prefix (default: w)")
    parser.add_argument("--ingest_date",    default=date.today().isoformat())
    parser.add_argument("--force_overwrite", default="false")
    args = parser.parse_args()

    force_overwrite = args.force_overwrite.lower() == "true"
    current_year = date.today().year

    logger.info(
        "CPC soil moisture → raw  variable=%s  year=%d  force_overwrite=%s",
        args.variable, args.year, force_overwrite,
    )

    if args.year < current_year:
        written, skipped = _process_year_via_tarball(
            year=args.year,
            variable=args.variable,
            bucket=args.bucket,
            aws_region=args.aws_region,
            ingest_date=args.ingest_date,
            force_overwrite=force_overwrite,
        )
    else:
        written, skipped = _process_year_via_daily_files(
            year=args.year,
            variable=args.variable,
            bucket=args.bucket,
            aws_region=args.aws_region,
            ingest_date=args.ingest_date,
            force_overwrite=force_overwrite,
        )

    logger.info("Done  written=%d  skipped=%d", written, skipped)


if __name__ == "__main__":
    main()
