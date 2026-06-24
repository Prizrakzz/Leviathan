"""USDA AMS Cotton Annual Quality bronze -> silver."""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from pathlib import Path

import boto3
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.storage.paths import silver_ams_cotton_key  # noqa: E402
from leviathan.storage.s3 import list_s3_keys, s3_download_with_retry  # noqa: E402
from leviathan.transforms.bronze_to_silver.usda_ams_cotton_quality import (  # noqa: E402
    transform_ams_cotton_quality_bronze_to_silver,
)

logger = get_logger("ams_cotton_quality_silver_task")
_BRONZE_PREFIX = "bronze/production/source=usda_ams_cotton_classing/"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_env()
    parser = argparse.ArgumentParser(description="AMS cotton annual quality bronze -> silver")
    parser.add_argument("--bucket", default=os.environ.get("LEVIATHAN_BUCKET"))
    parser.add_argument("--aws-region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--force-overwrite", action="store_true")
    args = parser.parse_args()
    if not args.bucket:
        args.bucket = get_required_env("LEVIATHAN_BUCKET")

    s3 = boto3.client("s3", region_name=args.aws_region)
    out_key = silver_ams_cotton_key()
    if not args.force_overwrite:
        try:
            s3.head_object(Bucket=args.bucket, Key=out_key)
            logger.info("silver exists, skipping %s", out_key)
            return
        except Exception:  # noqa: BLE001
            pass

    keys = list_s3_keys(args.bucket, _BRONZE_PREFIX, suffix=".parquet", aws_region=args.aws_region)
    keys.sort()
    if not keys:
        raise SystemExit("no AMS cotton bronze keys found")
    frames = [
        pd.read_parquet(io.BytesIO(s3_download_with_retry(args.bucket, key, s3)))
        for key in keys
    ]
    silver = transform_ams_cotton_quality_bronze_to_silver(pd.concat(frames, ignore_index=True))
    if silver.empty:
        raise SystemExit("AMS cotton silver transform produced zero rows")
    dupes = int(silver.duplicated(subset=["season", "geography"]).sum())
    if dupes:
        raise SystemExit(f"AMS cotton silver has {dupes} duplicate keys")
    buf = io.BytesIO()
    silver.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3.put_object(Bucket=args.bucket, Key=out_key, Body=buf.getvalue())
    logger.info("AMS cotton silver written rows=%d key=%s", len(silver), out_key)


if __name__ == "__main__":
    main()
