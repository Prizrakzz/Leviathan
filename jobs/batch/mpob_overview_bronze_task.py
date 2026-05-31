"""AWS Batch task: MPOB overview PDFs → bronze/ layer (Phase 2).

Downloads each of the 7 MPOB Overview of the Malaysian Oil Palm Industry PDFs
(2010–2016) from raw/, parses the two statistics table pages (0-indexed pages
5–6) using pdfplumber, and writes an annual EAV Parquet to:

    bronze/production/source=mpob/release_type=overview_pdf/year={YYYY}/part-000.parquet

Schema: (year, variable, value, release_type, source, ingest_date).
Contains 5 rows per year (one per canonical variable).

No OCR needed — all 7 PDFs are digital/typeset (pdfplumber extraction, $0).

Usage
-----
    # Dry-run
    python jobs/batch/mpob_overview_bronze_task.py --bucket leviathan-dev-shahem-001 \\
        --aws-region us-east-1 --dry-run

    # Full run (idempotent)
    python jobs/batch/mpob_overview_bronze_task.py --bucket leviathan-dev-shahem-001 \\
        --aws-region us-east-1

    # Force overwrite
    python jobs/batch/mpob_overview_bronze_task.py --force-overwrite true
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
from datetime import datetime, timezone

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import (
    bronze_mpob_overview_key,
    parse_hive_key,
    raw_mpob_overview_pdf_key,
)
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.raw_to_bronze.mpob_pdf import extract_mpob_overview_annual

logger = get_logger("mpob_overview_bronze_task")

_RAW_PREFIX = "raw/production/source=mpob/release_type=overview_pdf/"


# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MPOB overview PDFs → bronze/")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument(
        "--force-overwrite",
        default="false",
        help="Overwrite existing bronze Parquets.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be written without writing to S3.",
    )
    args = parser.parse_args()
    args.force_overwrite = _parse_bool(args.force_overwrite)
    return args


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _available_years(bucket: str, aws_region: str) -> list[int]:
    """List calendar years for which a raw overview PDF exists in S3."""
    keys = list_s3_keys(bucket, _RAW_PREFIX, suffix=".pdf", aws_region=aws_region)
    years: list[int] = []
    for key in keys:
        year_str = parse_hive_key(key, "year")
        if year_str and year_str.isdigit():
            years.append(int(year_str))
    return sorted(set(years))


def _target_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except s3_client.exceptions.ClientError as exc:
        if exc.response["Error"]["Code"] == "404":
            return False
        raise


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )
    t0 = datetime.now(tz=timezone.utc)
    load_env()
    args = _parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    ingest_date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    logger.info(
        "MPOB overview bronze task  bucket=%s  force=%s  dry_run=%s",
        bucket,
        args.force_overwrite,
        args.dry_run,
    )

    years = _available_years(bucket, aws_region)
    if not years:
        logger.error("No overview PDF keys found under %s", _RAW_PREFIX)
        return 1

    logger.info("Found %d overview PDF year(s): %s", len(years), years)

    s3_client = get_thread_local_s3_client(aws_region)
    written = 0
    skipped = 0
    errors = 0

    for year in years:
        raw_key = raw_mpob_overview_pdf_key(year)
        bronze_key = bronze_mpob_overview_key(year)

        if not args.force_overwrite and _target_exists(s3_client, bucket, bronze_key):
            logger.info("skipping year=%d (already exists): %s", year, bronze_key)
            skipped += 1
            continue

        if args.dry_run:
            logger.info("[DRY RUN] Would write: %s", bronze_key)
            written += 1
            continue

        try:
            pdf_bytes = s3_download_with_retry(bucket, raw_key, s3_client)
            df = extract_mpob_overview_annual(pdf_bytes, year, ingest_date)

            if df.empty:
                logger.error("year=%d: extraction returned empty DataFrame", year)
                errors += 1
                continue

            buf = io.BytesIO()
            df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
            s3_client.put_object(
                Bucket=bucket,
                Key=bronze_key,
                Body=buf.getvalue(),
                ContentType="application/octet-stream",
            )
            logger.info("wrote year=%d  key=%s  rows=%d", year, bronze_key, len(df))
            written += 1

        except Exception as exc:  # noqa: BLE001
            logger.error("failed year=%d: %s", year, exc)
            errors += 1

    elapsed = (datetime.now(tz=timezone.utc) - t0).total_seconds()
    logger.info(
        "done  written=%d  skipped=%d  errors=%d  elapsed=%.1fs",
        written,
        skipped,
        errors,
        elapsed,
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
