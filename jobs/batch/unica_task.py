"""UNICA production-and-milling HTML → bronze Batch task.

Processes raw UNICA PHP-rendered HTML pages from S3 raw/ and writes
long/tidy bronze Parquets keyed by harvest year.

S3 key structure
----------------
  Raw:    raw/production/source=unica/
              harvest_year={YYYY_YY}/production_milling.html
  Bronze: bronze/production/source=unica/
              harvest_year={YYYY_YY}/part-000.parquet

Usage
-----
    python jobs/batch/unica_task.py [--bucket B] [--aws-region R] [--force-overwrite]

Smoke test (first 2 harvest years):
    python jobs/batch/unica_task.py --limit 2
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_unica_key, parse_hive_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.raw_to_bronze.unica_html import extract_unica

logger = get_logger("unica_task")

_RAW_PREFIX = "raw/production/source=unica/"
_WORKERS = 4


def _bronze_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001
        return False


def _process(
    raw_key: str,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
    ingest_date: str,
) -> tuple[str, str]:
    s3 = get_thread_local_s3_client(aws_region)
    harvest_year = parse_hive_key(raw_key, "harvest_year")
    if not harvest_year:
        logger.warning("Could not parse harvest_year from key: %s", raw_key)
        return "error", raw_key

    b_key = bronze_unica_key(harvest_year)

    if not force_overwrite and _bronze_exists(s3, bucket, b_key):
        return "skipped", raw_key

    try:
        raw_bytes = s3_download_with_retry(bucket, raw_key, s3)
    except Exception as exc:  # noqa: BLE001
        logger.error("S3 download failed  key=%s: %s", raw_key, exc)
        return "error", raw_key

    df = extract_unica(raw_bytes, harvest_year, ingest_date)

    if df.empty:
        logger.warning("UNICA: empty result for harvest_year=%s  key=%s", harvest_year, raw_key)
        return "skipped", raw_key

    try:
        buf = io.BytesIO()
        df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
        s3.put_object(
            Bucket=bucket,
            Key=b_key,
            Body=buf.getvalue(),
            ContentType="application/octet-stream",
        )
        logger.info(
            "bronze written  harvest_year=%s  rows=%d  %s", harvest_year, len(df), b_key
        )
        return "written", raw_key
    except Exception as exc:  # noqa: BLE001
        logger.error("Parquet write failed  key=%s: %s", raw_key, exc)
        return "error", raw_key


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )

    load_env()

    parser = argparse.ArgumentParser(description="UNICA HTML raw → bronze")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    raw_keys = list_s3_keys(bucket, _RAW_PREFIX, suffix=".html", aws_region=aws_region)
    raw_keys.sort()

    logger.info(
        "UNICA task  bucket=%s  raw_keys=%d  force=%s",
        bucket, len(raw_keys), args.force_overwrite,
    )

    if args.limit:
        raw_keys = raw_keys[: args.limit]

    ingest_date = datetime.now(timezone.utc).date().isoformat()
    start = datetime.now(timezone.utc)
    written = skipped = errors = 0

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {
            pool.submit(
                _process, key, bucket, aws_region, args.force_overwrite, ingest_date
            ): key
            for key in raw_keys
        }
        for fut in as_completed(futures):
            try:
                status, _ = fut.result()
            except Exception as exc:  # noqa: BLE001
                logger.error("Unexpected error: %s", exc)
                errors += 1
                continue
            if status == "written":
                written += 1
            elif status == "skipped":
                skipped += 1
            else:
                errors += 1

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        "Done  written=%d  skipped=%d  errors=%d  elapsed=%.1fs",
        written, skipped, errors, elapsed,
    )

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
