"""World Bank Pink Sheet raw → bronze Batch task.

Downloads each monthly Pink Sheet XLSX from S3 raw/ and writes a long-format
bronze Parquet with the 6 fertiliser / energy price series.

S3 key structure
----------------
  Raw:    raw/production/source=world_bank_pink_sheet/
              release={YYYYMmm}/{filename}.xlsx
  Bronze: bronze/production/source=world_bank_pink_sheet/
              release={YYYYMmm}/part-000.parquet

Usage
-----
    python jobs/batch/pink_sheet_task.py [--bucket B] [--aws-region R] [--force-overwrite]

Smoke test (first 3 releases):
    python jobs/batch/pink_sheet_task.py --limit 3
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
from leviathan.storage.paths import bronze_pink_sheet_key, parse_hive_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.raw_to_bronze.world_bank_pink_sheet import extract_pink_sheet

logger = get_logger("pink_sheet_task")

_RAW_PREFIX = "raw/production/source=world_bank_pink_sheet/"
_WORKERS = 6


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
) -> tuple[str, str]:
    s3 = get_thread_local_s3_client(aws_region)
    release_ym = parse_hive_key(raw_key, "release")
    if not release_ym:
        logger.warning("Could not parse release from key: %s", raw_key)
        return "error", raw_key

    b_key = bronze_pink_sheet_key(release_ym)

    if not force_overwrite and _bronze_exists(s3, bucket, b_key):
        return "skipped", raw_key

    try:
        raw_bytes = s3_download_with_retry(bucket, raw_key, s3)
    except Exception as exc:  # noqa: BLE001
        logger.error("S3 download failed  key=%s: %s", raw_key, exc)
        return "error", raw_key

    try:
        df = extract_pink_sheet(raw_bytes, release_ym)
    except Exception as exc:  # noqa: BLE001
        logger.error("Pink Sheet transform failed  key=%s: %s", raw_key, exc)
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
        logger.info("bronze written  %s", b_key)
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

    parser = argparse.ArgumentParser(description="World Bank Pink Sheet raw → bronze")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    raw_keys = list_s3_keys(bucket, _RAW_PREFIX, aws_region=aws_region)
    # Keep only Excel files
    raw_keys = [k for k in raw_keys if k.endswith((".xlsx", ".xls"))]
    raw_keys.sort()
    logger.info(
        "Pink Sheet task  bucket=%s  raw_keys=%d  force=%s",
        bucket, len(raw_keys), args.force_overwrite,
    )

    if args.limit:
        raw_keys = raw_keys[: args.limit]

    start = datetime.now(timezone.utc)
    written = skipped = errors = 0

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {
            pool.submit(_process, key, bucket, aws_region, args.force_overwrite): key
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
