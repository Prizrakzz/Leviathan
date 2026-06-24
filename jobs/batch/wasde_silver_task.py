"""USDA WASDE bronze -> revision-aware silver Batch task."""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.storage.paths import parse_hive_key, silver_wasde_key  # noqa: E402
from leviathan.storage.s3 import (  # noqa: E402
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.bronze_to_silver.usda_wasde import (  # noqa: E402
    OUTPUT_COLUMNS,
    transform_wasde_bronze_to_silver,
)

logger = get_logger("wasde_silver_task")
_BRONZE_PREFIX = "bronze/production/source=usda_wasde/"


def _download_parquet(bucket: str, key: str, aws_region: str) -> pd.DataFrame:
    s3 = get_thread_local_s3_client(aws_region)
    raw = s3_download_with_retry(bucket, key, s3)
    return pd.read_parquet(io.BytesIO(raw))


def _write_parquet(s3, bucket: str, key: str, df: pd.DataFrame, force: bool) -> str:
    if not force:
        try:
            s3.head_object(Bucket=bucket, Key=key)
            return "skipped"
        except Exception:  # noqa: BLE001
            pass
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    return "written"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_env()
    parser = argparse.ArgumentParser(description="USDA WASDE bronze -> silver")
    parser.add_argument("--bucket", default=os.environ.get("LEVIATHAN_BUCKET"))
    parser.add_argument("--aws-region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--release-date", action="append", default=[])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--force-overwrite", action="store_true")
    args = parser.parse_args()
    if not args.bucket:
        args.bucket = get_required_env("LEVIATHAN_BUCKET")
    args.workers = max(1, args.workers)

    bronze_keys = list_s3_keys(
        args.bucket,
        _BRONZE_PREFIX,
        suffix=".parquet",
        aws_region=args.aws_region,
    )
    if args.release_date:
        wanted = set(args.release_date)
        bronze_keys = [
            key for key in bronze_keys
            if parse_hive_key(key, "release_date") in wanted
        ]
    bronze_keys.sort()
    logger.info("WASDE silver selected %d bronze keys", len(bronze_keys))
    if not bronze_keys:
        raise SystemExit("no WASDE bronze keys selected")

    frames: list[pd.DataFrame] = []
    failures: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_download_parquet, args.bucket, key, args.aws_region): key
            for key in bronze_keys
        }
        for done, fut in enumerate(as_completed(futures), start=1):
            key = futures[fut]
            try:
                df = fut.result()
                if not df.empty:
                    frames.append(df)
            except Exception as exc:  # noqa: BLE001
                failures.append((key, str(exc)))
            if done % 50 == 0 or done == len(futures):
                logger.info("downloaded %d/%d WASDE bronze keys", done, len(futures))
    if failures:
        for key, error in failures[:20]:
            logger.error("download failed key=%s error=%s", key, error)
        raise SystemExit(f"{len(failures)} WASDE bronze downloads failed")

    bronze = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    silver = transform_wasde_bronze_to_silver(bronze, on_conflict="drop")
    if silver.empty:
        raise SystemExit("WASDE silver transform produced zero rows")
    silver = silver[OUTPUT_COLUMNS].drop_duplicates().reset_index(drop=True)
    key_cols = [
        "release_date",
        "commodity",
        "table_type",
        "region",
        "marketing_year",
        "attribute",
        "unit",
    ]
    dupes = int(silver.duplicated(subset=key_cols).sum())
    if dupes:
        raise SystemExit(f"WASDE silver has {dupes} duplicate natural keys")

    s3 = boto3.client("s3", region_name=args.aws_region)
    written = skipped = 0
    for release_date, group in silver.groupby("release_date"):
        key = silver_wasde_key(str(release_date))
        status = _write_parquet(s3, args.bucket, key, group, args.force_overwrite)
        if status == "written":
            written += 1
        else:
            skipped += 1
    logger.info("WASDE silver done rows=%d written=%d skipped=%d", len(silver), written, skipped)


if __name__ == "__main__":
    main()
