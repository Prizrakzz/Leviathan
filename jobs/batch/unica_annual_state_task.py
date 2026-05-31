"""AWS Batch task: UNICA annual-by-state bronze → silver Parquet.

Reads all per-season UNICA bronze Parquets from S3, pivots the EAV rows into
a wide annual table with one row per (harvest_year, state_region), then writes
a single flat silver file at:

    silver/unica_annual_state/part-000.parquet

Coverage: Brazil Centre-South historical seasons 1980/1981–2020/2021.

Usage
-----
    # Dry-run: show what would be written
    python jobs/batch/unica_annual_state_task.py --bucket leviathan-dev-shahem-001 \\
        --aws-region us-east-1 --dry-run

    # Full run (idempotent)
    python jobs/batch/unica_annual_state_task.py --bucket leviathan-dev-shahem-001 \\
        --aws-region us-east-1

    # Force overwrite
    python jobs/batch/unica_annual_state_task.py --force-overwrite true
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
    parse_hive_key,
    silver_unica_annual_state_key,
)
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.bronze_to_silver.unica_annual_state import (
    transform_unica_annual_state,
)

logger = get_logger("unica_annual_state_task")

_BRONZE_PREFIX = "bronze/production/source=unica/"


# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UNICA annual-by-state bronze → silver")
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


def _available_harvest_years(bucket: str, aws_region: str) -> list[str]:
    """List harvest years for which a UNICA bronze Parquet exists in S3."""
    keys = list_s3_keys(bucket, _BRONZE_PREFIX, suffix=".parquet", aws_region=aws_region)
    years: list[str] = []
    for key in keys:
        hy = parse_hive_key(key, "harvest_year")
        if hy:
            years.append(hy)
    return sorted(set(years))


def _load_bronze_for_year(
    bucket: str, harvest_year: str, aws_region: str, s3_client
) -> pd.DataFrame:
    key = f"bronze/production/source=unica/harvest_year={harvest_year}/part-000.parquet"
    raw_bytes = s3_download_with_retry(bucket, key, s3_client)
    df = pd.read_parquet(io.BytesIO(raw_bytes))
    if "harvest_year" not in df.columns:
        df["harvest_year"] = harvest_year
    logger.info("loaded bronze harvest_year=%s  rows=%d", harvest_year, len(df))
    return df


def _load_all_bronze(bucket: str, harvest_years: list[str], aws_region: str) -> pd.DataFrame:
    s3_client = get_thread_local_s3_client(aws_region)
    frames: list[pd.DataFrame] = []
    for hy in harvest_years:
        try:
            frames.append(_load_bronze_for_year(bucket, hy, aws_region, s3_client))
        except Exception as exc:  # noqa: BLE001
            logger.error("failed to load harvest_year=%s: %s", hy, exc)
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
    key = silver_unica_annual_state_key()

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
        "UNICA annual state silver task  bucket=%s  force=%s  dry_run=%s",
        bucket,
        args.force_overwrite,
        args.dry_run,
    )

    harvest_years = _available_harvest_years(bucket, aws_region)
    if not harvest_years:
        logger.error("No UNICA bronze Parquets found under %s", _BRONZE_PREFIX)
        return 1

    logger.info("Found %d UNICA bronze season(s)", len(harvest_years))

    bronze = _load_all_bronze(bucket, harvest_years, aws_region)
    logger.info("Total bronze rows loaded: %d", len(bronze))

    silver = transform_unica_annual_state(bronze)
    logger.info("Silver rows after transform: %d", len(silver))

    if silver.empty:
        logger.warning("Silver transform returned empty DataFrame — nothing to write")
        return 0

    result = _write_silver(bucket, aws_region, silver, args.force_overwrite, args.dry_run)
    logger.info("result=%s", result)

    elapsed = (datetime.now(tz=timezone.utc) - t0).total_seconds()
    logger.info("done  elapsed=%.1fs", elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
