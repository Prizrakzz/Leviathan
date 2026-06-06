"""AWS Batch entrypoint: CFTC COT disagg_futures TXT → bronze Parquets.

Processes the 10 futures-only disaggregated COT files (2006–2025) and
writes one Parquet per year-label to:

    bronze/production/source=cftc_cot/year={label}/part-000.parquet

Skips the disagg_combined files entirely — futures-only positioning is the
industry-standard basis for the cot_net_managed_money_z ML feature.

Usage
-----
    python jobs/batch/cftc_cot_bronze_task.py
    python jobs/batch/cftc_cot_bronze_task.py --force-overwrite
    python jobs/batch/cftc_cot_bronze_task.py --dry-run
"""
from __future__ import annotations

import argparse
import io
import logging
import re
import sys
from datetime import datetime, timezone

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_cot_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.raw_to_bronze.cftc_cot import parse_cot_txt

logger = get_logger("cftc_cot_bronze_task")

_RAW_PREFIX = "raw/production/source=cftc_cot/disagg_futures/backfill/"


def _year_label_from_key(key: str) -> str | None:
    """Extract year label from key like fut_disagg_2024.txt or fut_disagg_2006_2016.txt."""
    fname = key.split("/")[-1]
    m = re.search(r"fut_disagg_(.+)\.txt$", fname)
    return m.group(1) if m else None


def _bronze_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def _write_parquet(s3_client, bucket: str, key: str, df: pd.DataFrame) -> None:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3_client.put_object(
        Bucket=bucket, Key=key, Body=buf.getvalue(),
        ContentType="application/octet-stream",
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(description="CFTC COT disagg_futures → bronze")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    bucket     = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    s3         = get_thread_local_s3_client(aws_region)

    raw_keys = sorted(list_s3_keys(bucket, _RAW_PREFIX, suffix=".txt",
                                    aws_region=aws_region))
    logger.info("Found %d disagg_futures TXT files  force=%s  dry_run=%s",
                len(raw_keys), args.force_overwrite, args.dry_run)

    started_at = datetime.now(timezone.utc)
    written = skipped = errors = 0

    for raw_key in raw_keys:
        year_label = _year_label_from_key(raw_key)
        if not year_label:
            logger.warning("Could not parse year label from %s", raw_key)
            errors += 1
            continue

        b_key = bronze_cot_key(year_label)

        if not args.force_overwrite and not args.dry_run and _bronze_exists(s3, bucket, b_key):
            logger.debug("skipped (exists)  year=%s", year_label)
            skipped += 1
            continue

        logger.info("Processing year=%s  (%s)", year_label, raw_key.split("/")[-1])
        try:
            raw_bytes = s3_download_with_retry(bucket, raw_key, s3)
        except Exception:
            logger.exception("S3 download failed: %s", raw_key)
            errors += 1
            continue

        try:
            df = parse_cot_txt(raw_bytes, year_label)
        except Exception:
            logger.exception("Parse failed: %s", raw_key)
            errors += 1
            continue

        if df.empty:
            logger.warning("No mapped markets in year=%s — skipping write", year_label)
            errors += 1
            continue

        if args.dry_run:
            logger.info("dry-run  year=%s  rows=%d  slugs=%s",
                        year_label, len(df), sorted(df["leviathan_slug"].unique().tolist()))
            written += 1
            continue

        try:
            _write_parquet(s3, bucket, b_key, df)
            logger.info("written  year=%s  rows=%d  %s", year_label, len(df), b_key)
            written += 1
        except Exception:
            logger.exception("Write failed: %s", b_key)
            errors += 1

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
    label = "dry-run" if args.dry_run else "written"
    logger.info(
        "Done in %.1fs — %s=%d  skipped=%d  errors=%d",
        elapsed, label, written, skipped, errors,
    )
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
