"""Glue Python Shell job: bronze → silver for FAOSTAT production data.

Reads all bronze Parquet files from S3 under:
  bronze/production/source=faostat/dataset=QCL/commodity=<commodity>/...
Concatenates them into one DataFrame, applies the silver transform,
then writes per-year silver Parquet files to S3 under:
  silver/production/commodity=<commodity>/year=<year>/part-000.parquet

Uses s3fs so pd.read_parquet() works directly on s3:// URIs.
"""
from __future__ import annotations

import io
import sys

from awsglue.utils import getResolvedOptions

import pandas as pd

# ---- Bootstrap: install leviathan package from S3 at runtime ----
import os as _os
import subprocess as _subprocess


def _install_leviathan() -> None:
    import boto3 as _boto3

    _bucket = next(
        (sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--bucket" and i + 1 < len(sys.argv)),
        None,
    )
    if not _bucket:
        raise RuntimeError("--bucket argument required for leviathan bootstrap")
    _whl = "/tmp/leviathan-0.1.0-py3-none-any.whl"
    if not _os.path.exists(_whl):
        _boto3.client("s3").download_file(_bucket, "glue-libs/leviathan-0.1.0-py3-none-any.whl", _whl)
    _subprocess.check_call([sys.executable, "-m", "pip", "install", _whl, "--quiet"])


_install_leviathan()
# ---- End bootstrap ----

from leviathan.common.logging import get_logger
from leviathan.storage.s3 import list_s3_keys, upload_bytes_to_s3
from leviathan.transforms.bronze_to_silver.faostat_cocoa import transform_faostat_cocoa_silver_df

logger = get_logger(__name__)

REQUIRED_ARGS = ["JOB_NAME", "commodity", "bucket", "aws_region"]

args = getResolvedOptions(sys.argv, REQUIRED_ARGS)

COMMODITY: str = args["commodity"]
BUCKET: str = args["bucket"]
AWS_REGION: str = args["aws_region"]

BRONZE_PREFIX = f"bronze/production/source=faostat/dataset=QCL/commodity={COMMODITY}/"


def main() -> None:
    bronze_keys = list_s3_keys(BUCKET, BRONZE_PREFIX, suffix=".parquet", aws_region=AWS_REGION)
    logger.info(
        "Found %d bronze FAOSTAT Parquet files for commodity=%s",
        len(bronze_keys), COMMODITY,
    )

    if not bronze_keys:
        raise RuntimeError(
            f"No bronze FAOSTAT Parquet files found at s3://{BUCKET}/{BRONZE_PREFIX}"
        )

    frames: list[pd.DataFrame] = []
    for key in bronze_keys:
        df = pd.read_parquet(
            f"s3://{BUCKET}/{key}",
            storage_options={"anon": False},
        )
        frames.append(df)

    bronze_df = pd.concat(frames, ignore_index=True)
    logger.info("Loaded %d total bronze FAOSTAT rows", len(bronze_df))

    year_frames = transform_faostat_cocoa_silver_df(bronze_df)
    logger.info("Silver transform produced data for %d years", len(year_frames))

    success = 0
    failed = 0

    for year, year_df in year_frames:
        silver_key = f"silver/production/commodity={COMMODITY}/year={year}/part-000.parquet"

        try:
            buf = io.BytesIO()
            year_df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
            upload_bytes_to_s3(buf.getvalue(), BUCKET, silver_key, aws_region=AWS_REGION)

            logger.info("Wrote silver: %s  rows=%d", silver_key, len(year_df))
            success += 1

        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to write %s — %s", silver_key, exc)
            failed += 1

    logger.info(
        "bronze→silver FAOSTAT complete. success=%d  failed=%d",
        success, failed,
    )

    if failed > 0:
        raise RuntimeError(f"{failed} years failed during bronze→silver FAOSTAT transform.")


if __name__ == "__main__":
    main()
