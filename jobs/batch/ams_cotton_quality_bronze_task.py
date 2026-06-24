"""USDA AMS Cotton Annual Quality raw PDFs -> bronze."""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.storage.paths import bronze_ams_cotton_key, parse_hive_key  # noqa: E402
from leviathan.storage.s3 import (  # noqa: E402
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.raw_to_bronze.usda_ams_cotton_quality import (  # noqa: E402
    extract_ams_cotton_quality_pdf,
)

logger = get_logger("ams_cotton_quality_bronze_task")
_RAW_PREFIX = "raw/production/source=usda_ams_cotton_classing/report_type=annual_quality/"


def _bronze_exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001
        return False


def _process_raw_key(
    raw_key: str,
    *,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
) -> tuple[str, str]:
    s3 = get_thread_local_s3_client(aws_region)
    season_raw = parse_hive_key(raw_key, "season")
    if not season_raw:
        logger.warning("skipping raw key without season partition: %s", raw_key)
        return "error", raw_key

    season = int(season_raw)
    bronze_key = bronze_ams_cotton_key(season)
    if not force_overwrite and _bronze_exists(s3, bucket, bronze_key):
        return "skipped", raw_key

    head = s3.head_object(Bucket=bucket, Key=raw_key)
    pdf_bytes = s3_download_with_retry(bucket, raw_key, s3)
    df = extract_ams_cotton_quality_pdf(
        pdf_bytes,
        season=season,
        source_raw_key=raw_key,
        source_file_etag=str(head.get("ETag", "")).strip('"'),
    )
    if df.empty:
        logger.warning("no AMS cotton metrics extracted from %s", raw_key)
        return "empty", raw_key

    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3.put_object(Bucket=bucket, Key=bronze_key, Body=buf.getvalue())
    logger.info("AMS cotton bronze written season=%s rows=%d key=%s", season, len(df), bronze_key)
    return "written", raw_key


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_env()
    parser = argparse.ArgumentParser(description="AMS cotton annual quality raw -> bronze")
    parser.add_argument("--bucket", default=os.environ.get("LEVIATHAN_BUCKET"))
    parser.add_argument("--aws-region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if not args.bucket:
        args.bucket = get_required_env("LEVIATHAN_BUCKET")

    keys = list_s3_keys(args.bucket, _RAW_PREFIX, suffix=".pdf", aws_region=args.aws_region)
    keys.sort()
    workers = max(1, args.workers)
    written = skipped = empty = 0
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _process_raw_key,
                raw_key,
                bucket=args.bucket,
                aws_region=args.aws_region,
                force_overwrite=args.force_overwrite,
            ): raw_key
            for raw_key in keys
        }
        for future in as_completed(futures):
            raw_key = futures[future]
            try:
                status, _ = future.result()
            except Exception as exc:  # noqa: BLE001
                logger.exception("AMS cotton bronze failed for %s: %s", raw_key, exc)
                errors.append(raw_key)
                continue
            if status == "written":
                written += 1
            elif status == "skipped":
                skipped += 1
            elif status == "empty":
                empty += 1
            else:
                errors.append(raw_key)
    logger.info("AMS cotton bronze done written=%d skipped=%d empty=%d", written, skipped, empty)
    if errors:
        raise SystemExit(f"AMS cotton bronze failed for {len(errors)} files")


if __name__ == "__main__":
    main()
