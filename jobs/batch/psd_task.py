"""USDA PSD raw → bronze Batch task.

Downloads each psd_alldata.zip from S3 raw/ and writes a single bronze
Parquet per release date covering all commodities.

S3 key structure
----------------
  Raw:    raw/production/source=usda_psd/release_type=bulk/
              release_date={YYYY-MM-DD}/psd_alldata.zip
  Bronze: bronze/production/source=usda_psd/
              release_date={YYYY-MM-DD}/part-000.parquet

Usage
-----
    python jobs/batch/psd_task.py [--bucket B] [--aws-region R] [--force-overwrite]

Smoke test (process all — only 1–2 ZIPs expected):
    python jobs/batch/psd_task.py --force-overwrite
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
from datetime import datetime, timezone

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_psd_key, parse_hive_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.raw_to_bronze.usda_psd import extract_usda_psd

logger = get_logger("psd_task")

_RAW_PREFIX = "raw/production/source=usda_psd/"
_WORKERS = 4


def _bronze_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except s3_client.exceptions.ClientError as exc:
        if exc.response["Error"]["Code"] == "404":
            return False
        raise
    except Exception:  # noqa: BLE001
        return False


def _process(
    raw_key: str,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
) -> tuple[str, str]:
    """Download one PSD ZIP, transform, and write bronze Parquet.

    Returns:
        ``(status, raw_key)`` where status is ``"written"``, ``"skipped"``, or ``"error"``.
    """
    s3 = get_thread_local_s3_client(aws_region)
    release_date = parse_hive_key(raw_key, "release_date")
    if not release_date:
        logger.warning("Could not parse release_date from key: %s", raw_key)
        return "error", raw_key

    b_key = bronze_psd_key(release_date)

    if not force_overwrite and _bronze_exists(s3, bucket, b_key):
        return "skipped", raw_key

    try:
        raw_bytes = s3_download_with_retry(bucket, raw_key, s3)
    except Exception as exc:  # noqa: BLE001
        logger.error("S3 download failed  key=%s: %s", raw_key, exc)
        return "error", raw_key

    try:
        df = extract_usda_psd(raw_bytes, release_date)
    except Exception as exc:  # noqa: BLE001
        logger.error("PSD transform failed  key=%s: %s", raw_key, exc)
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

    parser = argparse.ArgumentParser(description="USDA PSD raw → bronze")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Cap number of files processed (0 = no limit)",
    )
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    raw_keys = list_s3_keys(bucket, _RAW_PREFIX, suffix=".zip", aws_region=aws_region)
    raw_keys.sort()

    logger.info(
        "PSD task  bucket=%s  raw_keys=%d  force=%s",
        bucket, len(raw_keys), args.force_overwrite,
    )

    if args.limit:
        raw_keys = raw_keys[: args.limit]

    start = datetime.now(timezone.utc)
    written = skipped = errors = 0

    for key in raw_keys:
        status, _ = _process(key, bucket, aws_region, args.force_overwrite)
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
