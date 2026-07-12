"""Fetch the NOAA CPC Oceanic Nino Index (ONI) file and write raw + bronze to S3 (SILVER-F057).

Source
------
NOAA Climate Prediction Center -- ONI ascii record (ERSSTv5, 30-year base periods)
    https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt

No authentication required.  Single ASCII text file (~30 KB) updated monthly in-place; the
full history from the DJF 1950 season is included in every release.  Because this is a single
tiny file with no WAF, no pagination and no URL discovery step, the ingest and bronze
transform are combined in one script -- the same pattern as ``fetch_noaa_iod.py``.

The source decision (why the CPC ascii file and not the website table / the raw Nino-3.4
monthly file) is recorded in ``docs/adr/ADR-002-noaa-oni-source.md``.

S3 layout
---------
    Raw:    raw/weather/source=noaa_oni/oni.ascii.txt         (overwrite)
    Bronze: bronze/weather/source=noaa_oni/part-000.parquet   (overwrite)

Both objects are overwritten on each run.

Usage
-----
    python jobs/ingest/fetch_noaa_oni.py
    python jobs/ingest/fetch_noaa_oni.py --dry-run
    python jobs/ingest/fetch_noaa_oni.py --skip-existing-raw
    python jobs/ingest/fetch_noaa_oni.py --force-bronze
"""
from __future__ import annotations

import argparse
import io
import logging
import sys

import requests

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_oni_key, raw_oni_key
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3
from leviathan.transforms.raw_to_bronze.noaa_oni import extract_oni_bronze

logger = get_logger("fetch_noaa_oni")

_ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
_TIMEOUT = 30

# Sanity check: the file's first line is the header " SEAS  YR   TOTAL   ANOM".
_EXPECTED_HEADER_TOKEN = "SEAS"


def _write_parquet(data: bytes, bucket: str, key: str, aws_region: str) -> None:
    import boto3
    from leviathan.storage.s3 import _BOTO_RETRY_CONFIG
    s3 = boto3.client("s3", region_name=aws_region, config=_BOTO_RETRY_CONFIG)
    s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType="application/octet-stream")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(
        description="Fetch NOAA CPC ONI ascii file -> raw S3 + bronze Parquet"
    )
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--skip-existing-raw", action="store_true",
                        help="Skip the HTTP fetch if the raw S3 key already exists")
    parser.add_argument("--force-bronze", action="store_true",
                        help="Re-write bronze even if raw was skipped")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the S3 keys and row count without writing anything")
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    r_key = raw_oni_key()
    b_key = bronze_oni_key()

    logger.info("ONI ingest  bucket=%s  raw=%s", bucket, r_key)

    if args.dry_run:
        print(f"Source URL : {_ONI_URL}")
        print(f"Raw key    : {r_key}")
        print(f"Bronze key : {b_key}")
        print("(dry-run -- no writes)")
        return

    # ------------------------------------------------------------------
    # Fetch raw
    # ------------------------------------------------------------------
    raw_skipped = False
    if args.skip_existing_raw and s3_object_exists(bucket, r_key, aws_region):
        logger.info("Raw already exists -- skipping HTTP fetch: %s", r_key)
        raw_skipped = True
    else:
        logger.info("Fetching %s ...", _ONI_URL)
        resp = requests.get(_ONI_URL, timeout=_TIMEOUT)
        resp.raise_for_status()
        oni_bytes = resp.content

        header = oni_bytes[:40].decode("utf-8", errors="replace")
        if _EXPECTED_HEADER_TOKEN not in header:
            logger.error(
                "Response from %s does not look like the ONI ascii file "
                "(expected header token %r). Got: %r",
                _ONI_URL, _EXPECTED_HEADER_TOKEN, oni_bytes[:60],
            )
            sys.exit(1)

        logger.info("Downloaded %d bytes", len(oni_bytes))
        upload_bytes_to_s3(oni_bytes, bucket, r_key, aws_region)
        logger.info("Raw written -> s3://%s/%s", bucket, r_key)

    # ------------------------------------------------------------------
    # Bronze transform
    # ------------------------------------------------------------------
    if raw_skipped and not args.force_bronze:
        logger.info("Raw was skipped and --force-bronze not set -- skipping bronze write")
        return

    if raw_skipped:
        import boto3
        from leviathan.storage.s3 import _BOTO_RETRY_CONFIG, s3_download_with_retry
        s3_client = boto3.client("s3", region_name=aws_region, config=_BOTO_RETRY_CONFIG)
        oni_bytes = s3_download_with_retry(bucket, r_key, s3_client)
        logger.info("Re-read raw from S3 for bronze parse (%d bytes)", len(oni_bytes))

    df = extract_oni_bronze(oni_bytes)

    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    _write_parquet(buf.getvalue(), bucket, b_key, aws_region)
    logger.info(
        "Bronze written -> s3://%s/%s  rows=%d  years=%d-%d",
        bucket, b_key, len(df), int(df["year"].min()), int(df["year"].max()),
    )


if __name__ == "__main__":
    main()
