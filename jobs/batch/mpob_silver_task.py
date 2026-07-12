"""AWS Batch task: MPOB annual_summary bronze → silver Parquet.

Reads all annual_summary bronze Parquets from S3, pivots the EAV rows into a
wide monthly time-series, and writes a single flat silver file at
``silver/mpob/part-000.parquet``.

Usage
-----
    # Dry-run: show what would be written
    python jobs/batch/mpob_silver_task.py --bucket leviathan-dev-shahem-001 \\
        --aws-region us-east-1 --dry-run

    # Full run
    python jobs/batch/mpob_silver_task.py --bucket leviathan-dev-shahem-001 \\
        --aws-region us-east-1

    # Force overwrite
    python jobs/batch/mpob_silver_task.py --force-overwrite true
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
from leviathan.silver.flat_producer import authorize_for_contract, build_flat_publish
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import (
    bronze_mpob_annual_key,
    parse_hive_key,
    silver_mpob_key,
)
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.bronze_to_silver.mpob import transform_mpob_bronze_to_silver

logger = get_logger("mpob_silver_task")

TABLE = "silver_mpob"

_BRONZE_PREFIX = "bronze/production/source=mpob/release_type=annual_summary/"


# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MPOB bronze -> silver (F062: common publisher)")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--run-id", default=None, dest="run_id")
    parser.add_argument(
        "--force-overwrite",
        default="false",
        help="(legacy) retained for compatibility; the publisher governs idempotency.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="(legacy alias) equivalent to --publish-mode dry-run.",
    )
    parser.add_argument(
        "--publish-mode",
        default=None,
        choices=["dry-run", "shadow", "canonical"],
        dest="publish_mode",
        help="SILVER-F015 publish mode (default dry-run; --dry-run forces dry-run).",
    )
    args = parser.parse_args()
    args.force_overwrite = _parse_bool(args.force_overwrite)
    if args.publish_mode is None:
        args.publish_mode = "dry-run"
    if args.dry_run:
        args.publish_mode = "dry-run"
    return args


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


def _available_years(bucket: str, aws_region: str) -> list[int]:
    """List calendar years for which an annual_summary bronze Parquet exists."""
    keys = list_s3_keys(bucket, _BRONZE_PREFIX, suffix=".parquet", aws_region=aws_region)
    years: list[int] = []
    for key in keys:
        year_str = parse_hive_key(key, "year")
        if year_str.isdigit():
            years.append(int(year_str))
    return sorted(set(years))


def _load_annual_bronze(bucket: str, year: int, aws_region: str) -> pd.DataFrame:
    s3 = get_thread_local_s3_client(aws_region)
    key = bronze_mpob_annual_key(year)
    raw_bytes = s3_download_with_retry(bucket, key, s3)
    df = pd.read_parquet(io.BytesIO(raw_bytes))
    logger.info("loaded bronze year=%d key=%s rows=%d", year, key, len(df))
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


def _publish(df: pd.DataFrame, publish_mode: str, run_id, aws_region: str) -> str:
    """F062 adoption: write through the SILVER-F015 shadow-first publisher under the INV-2 schema
    pinned from the registry contract (retires the bespoke df.to_parquet + put_object)."""
    contract = load_registry().table(TABLE)
    s3_client = None if publish_mode == "dry-run" else get_thread_local_s3_client(aws_region)
    auth = authorize_for_contract(contract, publish_mode=publish_mode)
    plan = build_flat_publish(
        df=df, contract=contract, canonical_key=silver_mpob_key(),
        auth=auth, s3_client=s3_client, job="mpob_silver", run_id=run_id,
    )
    manifest = plan.run()
    logger.info("publish %s state=%s mode=%s rows=%d", TABLE, manifest.state.value,
                publish_mode, len(df))
    return manifest.state.value


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

    logger.info("MPOB silver task  bucket=%s  publish_mode=%s", bucket, args.publish_mode)

    years = _available_years(bucket, aws_region)
    if not years:
        logger.error("No annual_summary bronze Parquets found under %s", _BRONZE_PREFIX)
        return 1

    logger.info("Found %d annual bronze years: %s", len(years), years)

    bronze = _load_all_bronze(bucket, years, aws_region)
    logger.info("Total bronze rows loaded: %d", len(bronze))

    silver = transform_mpob_bronze_to_silver(bronze)
    logger.info("Silver rows after transform: %d", len(silver))

    if silver.empty:
        logger.error("Silver transform produced empty DataFrame — aborting.")
        return 1

    status = _publish(silver, args.publish_mode, args.run_id, aws_region)

    elapsed = (datetime.now(tz=timezone.utc) - t0).total_seconds()
    logger.info(
        "Done  status=%s  rows=%d  elapsed=%.1fs",
        status,
        len(silver),
        elapsed,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
