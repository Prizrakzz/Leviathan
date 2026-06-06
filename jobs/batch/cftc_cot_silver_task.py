"""AWS Batch entrypoint: CFTC COT bronze → silver.

Reads all bronze Parquets, deduplicates overlapping year-label ranges,
computes rolling 156-week z-scores, and writes:

    silver/cot/part-000.parquet

Usage
-----
    python jobs/batch/cftc_cot_silver_task.py
    python jobs/batch/cftc_cot_silver_task.py --force-overwrite
    python jobs/batch/cftc_cot_silver_task.py --dry-run
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
from leviathan.storage.paths import silver_cot_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.bronze_to_silver.cftc_cot import build_cot_silver

logger = get_logger("cftc_cot_silver_task")

_BRONZE_PREFIX = "bronze/production/source=cftc_cot/"


def _exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def _write(s3_client, bucket: str, key: str, df: pd.DataFrame) -> None:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3_client.put_object(Bucket=bucket, Key=key, Body=buf.getvalue(),
                         ContentType="application/octet-stream")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(description="CFTC COT bronze → silver")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    bucket     = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    s3         = get_thread_local_s3_client(aws_region)
    s_key      = silver_cot_key()

    if not args.force_overwrite and not args.dry_run and _exists(s3, bucket, s_key):
        logger.info("Silver exists — use --force-overwrite to re-run: %s", s_key)
        return

    # Load bronze in year order so bulk (2006_2016) comes before individual
    # years — dedup keeps LAST occurrence so individual years override bulk
    bronze_keys = sorted(list_s3_keys(bucket, _BRONZE_PREFIX, suffix=".parquet",
                                       aws_region=aws_region))
    logger.info("Loading %d bronze Parquets …", len(bronze_keys))

    dfs: list[pd.DataFrame] = []
    for k in bronze_keys:
        try:
            raw = s3_download_with_retry(bucket, k, s3)
            dfs.append(pd.read_parquet(io.BytesIO(raw)))
        except Exception:
            logger.exception("Failed to load: %s", k)

    df_silver = build_cot_silver(dfs)

    if args.dry_run:
        logger.info("dry-run — would write %s  rows=%d", s_key, len(df_silver))
        # Show sample: corn COT around 2012 drought
        sample = df_silver[
            (df_silver["leviathan_slug"] == "corn_cbot") &
            (df_silver["report_date"] >= "2012-06-01") &
            (df_silver["report_date"] <= "2012-09-30")
        ][["report_date", "mm_net", "mm_pct_oi", "mm_net_z_3yr"]].head(10)
        if not sample.empty:
            print(sample.to_string(index=False))
        return

    _write(s3, bucket, s_key, df_silver)
    logger.info("Silver written  %s  rows=%d", s_key, len(df_silver))


if __name__ == "__main__":
    main()
