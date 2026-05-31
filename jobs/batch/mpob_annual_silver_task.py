"""AWS Batch task: MPOB overview_pdf bronze → annual silver Parquet.

Reads all overview_pdf annual bronze Parquets from S3, pivots the EAV rows
into a wide yearly time-series, and writes a single flat silver file at:

    silver/mpob_annual/part-000.parquet

This silver table covers 2010–2016 (pre-BEPI-HTML era), complementing the
monthly HTML-based silver table (silver/mpob/) which covers 2017–present.

Usage
-----
    # Dry-run: show what would be written
    python jobs/batch/mpob_annual_silver_task.py --bucket leviathan-dev-shahem-001 \\
        --aws-region us-east-1 --dry-run

    # Full run
    python jobs/batch/mpob_annual_silver_task.py --bucket leviathan-dev-shahem-001 \\
        --aws-region us-east-1

    # Force overwrite
    python jobs/batch/mpob_annual_silver_task.py --force-overwrite true
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
from datetime import datetime, timezone

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import (
    bronze_mpob_overview_key,
    parse_hive_key,
    silver_mpob_annual_key,
)
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.bronze_to_silver.mpob_annual import (
    transform_mpob_annual_bronze_to_silver,
)

logger = get_logger("mpob_annual_silver_task")

_BRONZE_PREFIX = "bronze/production/source=mpob/release_type=overview_pdf/"


# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MPOB overview_pdf bronze → annual silver")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument(
        "--force-overwrite",
        default="false",
        help="Re-write the silver file even if it already exists.",
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
# Load
# ---------------------------------------------------------------------------


def _available_years(bucket: str, aws_region: str) -> list[int]:
    """List calendar years for which an overview_pdf bronze Parquet exists."""
    keys = list_s3_keys(bucket, _BRONZE_PREFIX, suffix=".parquet", aws_region=aws_region)
    years: list[int] = []
    for key in keys:
        year_str = parse_hive_key(key, "year")
        if year_str and year_str.isdigit():
            years.append(int(year_str))
    return sorted(set(years))


def _load_annual_bronze(bucket: str, year: int, aws_region: str) -> pd.DataFrame:
    s3 = get_thread_local_s3_client(aws_region)
    key = bronze_mpob_overview_key(year)
    raw_bytes = s3_download_with_retry(bucket, key, s3)
    df = pd.read_parquet(io.BytesIO(raw_bytes))
    logger.info("loaded bronze year=%d  key=%s  rows=%d", year, key, len(df))
    return df


def _load_all_bronze(bucket: str, years: list[int], aws_region: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for year in years:
        try:
            frames.append(_load_annual_bronze(bucket, year, aws_region))
        except Exception as exc:  # noqa: BLE001
            logger.error("failed to load year=%d: %s", year, exc)
            raise
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def _target_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except s3_client.exceptions.ClientError as exc:
        if exc.response["Error"]["Code"] == "404":
            return False
        raise


def _write_silver(
    bucket: str,
    aws_region: str,
    df: pd.DataFrame,
    force_overwrite: bool,
    dry_run: bool,
) -> str:
    key = silver_mpob_annual_key()

    if dry_run:
        logger.info("[DRY RUN] Would write: %s  rows=%d", key, len(df))
        return "dry_run"

    s3_client = get_thread_local_s3_client(aws_region)
    if not force_overwrite and _target_exists(s3_client, bucket, key):
        logger.info("skipping existing silver file: %s", key)
        return "skipped"

    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=buf.getvalue(),
        ContentType="application/octet-stream",
    )
    logger.info("wrote silver file: %s  rows=%d", key, len(df))
    return "written"


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

    logger.info(
        "MPOB annual silver task  bucket=%s  force=%s  dry_run=%s",
        bucket,
        args.force_overwrite,
        args.dry_run,
    )

    years = _available_years(bucket, aws_region)
    if not years:
        logger.error("No overview_pdf bronze Parquets found under %s", _BRONZE_PREFIX)
        return 1

    logger.info("Found %d overview_pdf bronze year(s): %s", len(years), years)

    bronze = _load_all_bronze(bucket, years, aws_region)
    logger.info("Total bronze rows loaded: %d", len(bronze))

    silver = transform_mpob_annual_bronze_to_silver(bronze)
    logger.info("Silver rows after transform: %d", len(silver))

    if silver.empty:
        logger.error("Silver transform returned empty DataFrame — aborting write")
        return 1

    result = _write_silver(bucket, aws_region, silver, args.force_overwrite, args.dry_run)
    logger.info("result=%s", result)

    elapsed = (datetime.now(tz=timezone.utc) - t0).total_seconds()
    logger.info("done  elapsed=%.1fs", elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
