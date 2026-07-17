"""Fetch NOAA PSL Indian Ocean Dipole (IOD) DMI file and write raw + bronze to S3.

Source
------
NOAA Physical Sciences Laboratory — DMI long-record dataset (HadSST-derived)
    https://psl.noaa.gov/gcos_wgsp/Timeseries/Data/dmi.had.long.data

No authentication required.  Single ASCII text file (~12 KB) updated monthly.
Full history from January 1870 included in every release.

Because this is a single tiny file with no WAF, no pagination, and no URL
discovery step, the ingest and bronze transform are combined in one script —
exactly the same pattern as ``fetch_noaa_oni.py``.

S3 layout
---------
    Raw:    raw/weather/source=noaa_iod/dmi.had.long.data   (overwrite)
    Bronze: bronze/weather/source=noaa_iod/part-000.parquet (overwrite)

Both objects are overwritten on each run.

Usage
-----
    python jobs/ingest/fetch_noaa_iod.py
    python jobs/ingest/fetch_noaa_iod.py --dry-run
    python jobs/ingest/fetch_noaa_iod.py --skip-existing-raw
    python jobs/ingest/fetch_noaa_iod.py --force-bronze
"""
from __future__ import annotations

import argparse
import io
import logging
import sys

import requests

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_iod_key, raw_iod_key
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3
from leviathan.transforms.raw_to_bronze.noaa_iod import extract_iod_bronze

logger = get_logger("fetch_noaa_iod")

_IOD_URL = "https://psl.noaa.gov/gcos_wgsp/Timeseries/Data/dmi.had.long.data"
_TIMEOUT  = 30

# Sanity check: file must start with a 4-digit year in the range header
_EXPECTED_START = "1870"


def _write_parquet(data: bytes, bucket: str, key: str, aws_region: str) -> None:
    import boto3
    from leviathan.storage.s3 import _BOTO_RETRY_CONFIG
    s3 = boto3.client("s3", region_name=aws_region, config=_BOTO_RETRY_CONFIG)
    s3.put_object(Bucket=bucket, Key=key, Body=data,
                  ContentType="application/octet-stream")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(
        description="Fetch NOAA IOD DMI file → raw S3 + bronze Parquet"
    )
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument(
        "--skip-existing-raw", action="store_true",
        help="Skip the HTTP fetch if the raw S3 key already exists",
    )
    parser.add_argument(
        "--force-bronze", action="store_true",
        help="Re-write bronze even if raw was skipped",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the S3 keys and row count without writing anything",
    )
    args = parser.parse_args()

    bucket     = args.bucket     or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    r_key = raw_iod_key()
    b_key = bronze_iod_key()

    logger.info("IOD ingest  bucket=%s  raw=%s", bucket, r_key)

    if args.dry_run:
        print(f"Source URL : {_IOD_URL}")
        print(f"Raw key    : {r_key}")
        print(f"Bronze key : {b_key}")
        print("(dry-run — no writes)")
        return

    # ------------------------------------------------------------------
    # Fetch raw
    # ------------------------------------------------------------------
    raw_skipped = False

    if args.skip_existing_raw and s3_object_exists(bucket, r_key, aws_region):
        logger.info("Raw already exists — skipping HTTP fetch: %s", r_key)
        raw_skipped = True
    else:
        logger.info("Fetching %s …", _IOD_URL)
        resp = requests.get(_IOD_URL, timeout=_TIMEOUT)
        resp.raise_for_status()
        iod_bytes = resp.content

        first_line = iod_bytes[:20].decode("utf-8", errors="replace").strip()
        if not first_line.startswith(_EXPECTED_START):
            logger.error(
                "Response from %s does not look like the IOD DMI file "
                "(expected to start with '%s'). Got: %r",
                _IOD_URL, _EXPECTED_START, iod_bytes[:60],
            )
            sys.exit(1)

        logger.info("Downloaded %d bytes", len(iod_bytes))
        upload_bytes_to_s3(iod_bytes, bucket, r_key, aws_region)
        logger.info("Raw written → s3://%s/%s", bucket, r_key)

    # ------------------------------------------------------------------
    # Bronze transform
    # ------------------------------------------------------------------
    if raw_skipped and not args.force_bronze:
        logger.info(
            "Raw was skipped and --force-bronze not set — skipping bronze write"
        )
        return

    if raw_skipped:
        import boto3
        from leviathan.storage.s3 import _BOTO_RETRY_CONFIG, s3_download_with_retry
        s3_client = boto3.client("s3", region_name=aws_region,
                                 config=_BOTO_RETRY_CONFIG)
        iod_bytes = s3_download_with_retry(bucket, r_key, s3_client)
        logger.info("Re-read raw from S3 for bronze parse (%d bytes)", len(iod_bytes))

    df = extract_iod_bronze(iod_bytes)

    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    _write_parquet(buf.getvalue(), bucket, b_key, aws_region)
    logger.info(
        "Bronze written → s3://%s/%s  rows=%d  years=%d–%d",
        bucket, b_key, len(df), int(df["year"].min()), int(df["year"].max()),
    )


if __name__ == "__main__":
    main()
