"""CONAB XLS bronze -> revision-aware coffee silver Batch task."""
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
from leviathan.storage.paths import silver_conab_key  # noqa: E402
from leviathan.storage.s3 import list_s3_keys, s3_download_with_retry  # noqa: E402
from leviathan.transforms.bronze_to_silver.conab_coffee import (  # noqa: E402
    OUTPUT_COLUMNS,
    transform_conab_coffee_bronze_to_silver,
)

logger = get_logger("conab_silver_task")
_BRONZE_PREFIX = "bronze/production/source=conab_xls/"


def _read_parquet(s3, bucket: str, key: str) -> pd.DataFrame:
    raw = s3_download_with_retry(bucket, key, s3)
    return pd.read_parquet(io.BytesIO(raw))


def _exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001
        return False


def _write(s3, bucket: str, key: str, df: pd.DataFrame, force: bool) -> str:
    if not force and _exists(s3, bucket, key):
        return "skipped"
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    return "written"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_env()
    parser = argparse.ArgumentParser(description="CONAB XLS bronze -> coffee silver")
    parser.add_argument("--bucket", default=os.environ.get("LEVIATHAN_BUCKET"))
    parser.add_argument("--aws-region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--force-overwrite", action="store_true")
    args = parser.parse_args()
    if not args.bucket:
        args.bucket = get_required_env("LEVIATHAN_BUCKET")

    s3 = boto3.client("s3", region_name=args.aws_region)
    keys = list_s3_keys(args.bucket, _BRONZE_PREFIX, suffix=".parquet", aws_region=args.aws_region)
    keys.sort()
    if not keys:
        raise SystemExit("no CONAB XLS bronze keys found")

    frames = [_read_parquet(s3, args.bucket, key) for key in keys]
    silver = transform_conab_coffee_bronze_to_silver(pd.concat(frames, ignore_index=True))
    if silver.empty:
        raise SystemExit("CONAB silver transform produced zero rows")
    silver = silver[OUTPUT_COLUMNS]
    key_cols = ["commodity", "safra_year", "survey_number", "region"]
    dupes = int(silver.duplicated(subset=key_cols).sum())
    if dupes:
        raise SystemExit(f"CONAB silver has {dupes} duplicate natural keys")

    written = skipped = 0
    for (commodity, safra_year, survey_number), group in silver.groupby(
        ["commodity", "safra_year", "survey_number"]
    ):
        key = silver_conab_key(str(commodity), int(safra_year), int(survey_number))
        status = _write(s3, args.bucket, key, group, args.force_overwrite)
        if status == "written":
            written += 1
        else:
            skipped += 1
    logger.info("CONAB silver done rows=%d written=%d skipped=%d", len(silver), written, skipped)


if __name__ == "__main__":
    main()
