"""MPOB BEPI palm oil HTML → bronze Batch task.

Processes raw MPOB HTML pages from S3 raw/ and writes long/tidy bronze
Parquets for two release types:

  ``annual_summary``  — one Parquet per calendar year (12 monthly rows each)
  ``monthly_release`` — one Parquet per (year, month) (regional breakdown)

S3 key structure
----------------
  Raw annual:   raw/production/source=mpob/release_type=annual_summary/
                    year={y}/mpob_annual_summary_{y}.html
  Raw monthly:  raw/production/source=mpob/release_type=monthly_release/
                    year={y}/month={mm}/mpob_monthly_{y}_{mm}.html
  Bronze annual: bronze/production/source=mpob/release_type=annual_summary/
                     year={y}/part-000.parquet
  Bronze monthly: bronze/production/source=mpob/release_type=monthly_release/
                      year={y}/month={mm}/part-000.parquet

Usage
-----
    python jobs/batch/mpob_task.py [--bucket B] [--aws-region R] [--force-overwrite]
    python jobs/batch/mpob_task.py --release-type annual_summary
    python jobs/batch/mpob_task.py --release-type monthly_release

Smoke test:
    python jobs/batch/mpob_task.py --limit 3
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
from leviathan.storage.paths import (
    bronze_mpob_annual_key,
    bronze_mpob_monthly_key,
    parse_hive_key,
)
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.raw_to_bronze.mpob_html import (
    extract_mpob_annual,
    extract_mpob_monthly,
)

logger = get_logger("mpob_task")

_RAW_PREFIX = "raw/production/source=mpob/"
_WORKERS = 8


def _bronze_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001
        return False


def _process_annual(
    raw_key: str,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
    ingest_date: str,
) -> tuple[str, str]:
    s3 = get_thread_local_s3_client(aws_region)
    year_str = parse_hive_key(raw_key, "year")
    if not year_str:
        logger.warning("Could not parse year from key: %s", raw_key)
        return "error", raw_key

    year = int(year_str)
    b_key = bronze_mpob_annual_key(year)

    if not force_overwrite and _bronze_exists(s3, bucket, b_key):
        return "skipped", raw_key

    try:
        raw_bytes = s3_download_with_retry(bucket, raw_key, s3)
    except Exception as exc:  # noqa: BLE001
        logger.error("S3 download failed  key=%s: %s", raw_key, exc)
        return "error", raw_key

    df = extract_mpob_annual(raw_bytes, year, ingest_date)

    if df.empty:
        logger.warning("MPOB annual: empty result for year=%d  key=%s", year, raw_key)
        return "error", raw_key

    try:
        buf = io.BytesIO()
        df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
        s3.put_object(
            Bucket=bucket,
            Key=b_key,
            Body=buf.getvalue(),
            ContentType="application/octet-stream",
        )
        logger.info("bronze written  year=%d  rows=%d  %s", year, len(df), b_key)
        return "written", raw_key
    except Exception as exc:  # noqa: BLE001
        logger.error("Parquet write failed  key=%s: %s", raw_key, exc)
        return "error", raw_key


def _process_monthly(
    raw_key: str,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
    ingest_date: str,
) -> tuple[str, str]:
    s3 = get_thread_local_s3_client(aws_region)
    year_str = parse_hive_key(raw_key, "year")
    month_str = parse_hive_key(raw_key, "month")
    if not year_str or not month_str:
        logger.warning("Could not parse year/month from key: %s", raw_key)
        return "error", raw_key

    year = int(year_str)
    month = int(month_str)
    b_key = bronze_mpob_monthly_key(year, month)

    if not force_overwrite and _bronze_exists(s3, bucket, b_key):
        return "skipped", raw_key

    try:
        raw_bytes = s3_download_with_retry(bucket, raw_key, s3)
    except Exception as exc:  # noqa: BLE001
        logger.error("S3 download failed  key=%s: %s", raw_key, exc)
        return "error", raw_key

    df = extract_mpob_monthly(raw_bytes, year, month, ingest_date)

    if df.empty:
        logger.warning("MPOB monthly: empty result for %d-%02d  key=%s", year, month, raw_key)
        # Don't fail the task for "Under Construction" pages
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
        logger.info("bronze written  %d-%02d  rows=%d  %s", year, month, len(df), b_key)
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

    parser = argparse.ArgumentParser(description="MPOB BEPI HTML → bronze")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument(
        "--release-type",
        choices=["annual_summary", "monthly_release", "all"],
        default="all",
        dest="release_type",
    )
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    all_keys = list_s3_keys(bucket, _RAW_PREFIX, suffix=".html", aws_region=aws_region)

    annual_keys = [k for k in all_keys if "release_type=annual_summary" in k]
    monthly_keys = [k for k in all_keys if "release_type=monthly_release" in k]

    if args.release_type == "annual_summary":
        run_annual, run_monthly = True, False
    elif args.release_type == "monthly_release":
        run_annual, run_monthly = False, True
    else:
        run_annual, run_monthly = True, True

    logger.info(
        "MPOB task  bucket=%s  annual=%d  monthly=%d  force=%s",
        bucket, len(annual_keys), len(monthly_keys), args.force_overwrite,
    )

    if args.limit:
        annual_keys = annual_keys[: args.limit]
        monthly_keys = monthly_keys[: args.limit]

    ingest_date = datetime.now(timezone.utc).date().isoformat()
    start = datetime.now(timezone.utc)
    written = skipped = errors = 0

    def _update_counts(status: str) -> None:
        nonlocal written, skipped, errors
        if status == "written":
            written += 1
        elif status == "skipped":
            skipped += 1
        else:
            errors += 1

    tasks: list[tuple] = []
    if run_annual:
        tasks.extend(("annual", k) for k in annual_keys)
    if run_monthly:
        tasks.extend(("monthly", k) for k in monthly_keys)

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {}
        for release_type, key in tasks:
            if release_type == "annual":
                fut = pool.submit(
                    _process_annual, key, bucket, aws_region, args.force_overwrite, ingest_date
                )
            else:
                fut = pool.submit(
                    _process_monthly, key, bucket, aws_region, args.force_overwrite, ingest_date
                )
            futures[fut] = key

        for fut in as_completed(futures):
            try:
                status, _ = fut.result()
                _update_counts(status)
            except Exception as exc:  # noqa: BLE001
                logger.error("Unexpected error: %s", exc)
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
