"""USDA NASS QuickStats raw → bronze Batch task.

Streams the 1 GB+ .gz file from S3 raw/ in chunks and writes per-commodity
per-year bronze Parquets for two series:

  ``annual``        — Area Planted/Harvested, Yield, Production by state
  ``crop_progress`` — Weekly Good/Excellent % and condition rows

Memory requirements
-------------------
The uncompressed QuickStats file is ~1 GB.  Streaming with chunksize=100,000
rows keeps peak RSS below ~800 MB.  Set container memory to ≥4 GB at Batch
submission.

S3 key structure
----------------
  Raw:    raw/production/source=usda_nass/sector=crops/
              download_date={YYYY-MM-DD}/qs.crops.txt.gz
  Bronze: bronze/production/source=usda_nass/
              series={annual|crop_progress}/
              commodity={slug}/
              year={YYYY}/
              part-000.parquet

Usage
-----
    python jobs/batch/nass_task.py [--bucket B] [--aws-region R] [--force-overwrite]

Smoke test (crop_progress series, 2024 only):
    python jobs/batch/nass_task.py --series crop_progress --limit-years 2024
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
from leviathan.storage.paths import bronze_nass_key, parse_hive_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.raw_to_bronze.usda_nass import extract_usda_nass

logger = get_logger("nass_task")

_RAW_PREFIX = "raw/production/source=usda_nass/sector=crops/"
_WORKERS = 16   # writing small per-(commodity, year) Parquets is fast


def _bronze_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001
        return False


def _write_shards(
    series_dfs: dict[str, object],  # dict[series_name, pd.DataFrame]
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
    only_series: str | None,
    only_year: int | None,
) -> tuple[int, int, int]:
    """Write per-(series, commodity, year) Parquet shards to S3.

    Returns:
        ``(written, skipped, errors)``
    """
    import pandas as pd

    def _write_one(args: tuple) -> tuple[str, str]:
        series, slug, year, shard_df, b_key = args
        s3 = get_thread_local_s3_client(aws_region)
        if not force_overwrite and _bronze_exists(s3, bucket, b_key):
            return "skipped", b_key
        try:
            buf = io.BytesIO()
            shard_df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
            s3.put_object(
                Bucket=bucket,
                Key=b_key,
                Body=buf.getvalue(),
                ContentType="application/octet-stream",
            )
            logger.info("bronze written  %s  rows=%d", b_key, len(shard_df))
            return "written", b_key
        except Exception as exc:  # noqa: BLE001
            logger.error("Parquet write failed  key=%s: %s", b_key, exc)
            return "error", b_key

    tasks: list[tuple] = []
    for series_name, df in series_dfs.items():
        if only_series and series_name != only_series:
            continue
        if df is None or (hasattr(df, "empty") and df.empty):
            continue

        year_col = "year" if "year" in df.columns else None
        slug_col = "leviathan_slug" if "leviathan_slug" in df.columns else None
        if year_col is None or slug_col is None:
            logger.warning("NASS: missing year/slug columns in series=%s", series_name)
            continue

        for (slug, year), shard in df.groupby([slug_col, year_col]):
            year_int = int(year) if year is not None else 0
            if only_year and year_int != only_year:
                continue
            b_key = bronze_nass_key(series_name, str(slug), year_int)
            tasks.append((series_name, slug, year_int, shard, b_key))

    written = skipped = errors = 0
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        for status, _ in pool.map(_write_one, tasks):
            if status == "written":
                written += 1
            elif status == "skipped":
                skipped += 1
            else:
                errors += 1

    return written, skipped, errors


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )

    load_env()

    parser = argparse.ArgumentParser(description="USDA NASS raw → bronze")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument(
        "--series",
        choices=["annual", "crop_progress", "all"],
        default="all",
        help="Which series to write (default: all)",
    )
    parser.add_argument(
        "--limit-years",
        type=int,
        default=None,
        dest="limit_years",
        help="Only write shards for this specific year (smoke test)",
    )
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    raw_keys = list_s3_keys(bucket, _RAW_PREFIX, suffix=".gz", aws_region=aws_region)
    raw_keys.sort()
    logger.info(
        "NASS task  bucket=%s  raw_keys=%d  series=%s  force=%s",
        bucket, len(raw_keys), args.series, args.force_overwrite,
    )

    if not raw_keys:
        logger.error("No NASS .gz files found under %s", _RAW_PREFIX)
        sys.exit(1)

    # Use the most recent download
    latest_key = raw_keys[-1]
    download_date = parse_hive_key(latest_key, "download_date")
    logger.info("Using latest NASS key: %s", latest_key)

    s3 = get_thread_local_s3_client(aws_region)
    try:
        raw_bytes = s3_download_with_retry(bucket, latest_key, s3)
    except Exception as exc:
        logger.error("S3 download failed  key=%s: %s", latest_key, exc)
        sys.exit(1)

    logger.info("Download complete  bytes=%d  Parsing...", len(raw_bytes))
    start = datetime.now(timezone.utc)

    try:
        series_dfs = extract_usda_nass(raw_bytes, download_date)
    except Exception as exc:
        logger.error("NASS transform failed: %s", exc)
        sys.exit(1)

    only_series = None if args.series == "all" else args.series
    written, skipped, errors = _write_shards(
        series_dfs,
        bucket,
        aws_region,
        args.force_overwrite,
        only_series,
        args.limit_years,
    )

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        "Done  written=%d  skipped=%d  errors=%d  elapsed=%.1fs",
        written, skipped, errors, elapsed,
    )

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
