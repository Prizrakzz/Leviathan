"""AWS Batch task: SAGIS producer deliveries raw -> silver (SILVER-F042).

Reads the cumulative per-season SAGIS producer-delivery Excel snapshots from raw S3,
ranks overlapping snapshots by PUBLICATION METADATA (the S3 ``LastModified``, never
filename order), selects one authoritative record per (season, crop, week_number),
guards grade/total double counting, computes prior-year + trailing-z comparisons AFTER
uniqueness, and publishes ``silver_sagis_weekly_deliveries`` through the shadow-first
controlled publisher with an EXPLICIT registry-derived arrow schema (INV-2/INV-6).

Default ``--publish-mode`` is dry-run (nothing written). No canonical mutation without a
verified signed approval.

Usage:
    python jobs/batch/sagis_deliveries_task.py --dry-run
    python jobs/batch/sagis_deliveries_task.py --publish-mode shadow
"""
from __future__ import annotations

import argparse
import io
import logging
import re
import sys
from urllib.parse import unquote

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys_with_mtime
from leviathan.transforms.bronze_to_silver.sagis_common import build_snapshot
from leviathan.transforms.bronze_to_silver.sagis_deliveries import (
    build_deliveries_silver,
    read_deliveries_xlsx,
)
from jobs.batch._sb_producer_publish import publish_flat_silver

logger = get_logger("sagis_deliveries_task")

_RAW_PREFIX = "raw/production/source=sagis_weekly/dataset=producer_deliveries/"
_SILVER_KEY = "silver/sagis_weekly_deliveries/part-000.parquet"
_CROP_RE = re.compile(r"/crop=([^/]+)/")


def _crop_from_key(key: str) -> str | None:
    m = _CROP_RE.search(key)
    return m.group(1) if m else None


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(description="SAGIS producer deliveries raw -> silver")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--publish-mode", default=None,
                        help="dry-run|shadow|canonical (default dry-run)")
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    s3 = get_thread_local_s3_client(aws_region)

    key_to_mtime = list_s3_keys_with_mtime(bucket, _RAW_PREFIX, aws_region=aws_region)
    logger.info("Found %d SAGIS producer-delivery snapshots", len(key_to_mtime))

    records = []
    read_ok = read_err = 0
    for key, mtime in sorted(key_to_mtime.items()):
        crop = _crop_from_key(key)
        if crop is None or not key.lower().endswith((".xlsx", ".xls")):
            continue
        filename = unquote(key.rsplit("/", 1)[-1])
        snap = build_snapshot(
            s3_key=key, filename=filename, dataset="producer_deliveries",
            crop=crop, published_at=mtime,
        )
        try:
            data = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            recs = read_deliveries_xlsx(data, snap)
            records.extend(recs)
            read_ok += 1
        except Exception as exc:  # noqa: BLE001 -- log + skip a bad snapshot; keep going
            logger.error("SAGIS read failed key=%s: %s", key, exc)
            read_err += 1

    logger.info("Parsed %d week-records from %d snapshots (%d read errors)",
                len(records), read_ok, read_err)

    df_silver = build_deliveries_silver(records)
    logger.info("Deliveries silver rows=%d  seasons=%d", len(df_silver),
                df_silver["season"].nunique() if len(df_silver) else 0)

    if args.dry_run:
        logger.info("[DRY-RUN] would publish %d rows to %s", len(df_silver), _SILVER_KEY)

    manifest = publish_flat_silver(
        table_name="silver_sagis_weekly_deliveries",
        df=df_silver,
        job="sagis_deliveries_task",
        canonical_key=_SILVER_KEY,
        bucket=bucket,
        s3_client=s3,
        argv=sys.argv,
    )
    logger.info("Silver publish %s  state=%s  rows=%d",
                _SILVER_KEY, manifest.state.value, len(df_silver))


if __name__ == "__main__":
    main()
