"""Glue Python Shell: bronze → silver FAOSTAT.

Reads all bronze Parquet files for a commodity from S3 using pyarrow.dataset,
applies the silver transform, and writes per-year silver Parquet files back to S3.

Required args: --commodity, --bucket, --aws_region
"""
from __future__ import annotations

import io
import sys

from awsglue.utils import getResolvedOptions

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
    _subprocess.check_call([sys.executable, "-m", "pip", "install", _whl, "--no-deps", "--quiet"])


try:
    _install_leviathan()
except Exception as _exc:
    print(f"[BOOTSTRAP ERROR] {type(_exc).__name__}: {_exc}", flush=True)
    raise
# ---- End bootstrap ----

import boto3
import pyarrow.dataset as ds
import pyarrow.fs as pafs

from leviathan.common.logging import get_logger
from leviathan.transforms.bronze_to_silver.faostat_production import transform_faostat_production_silver_df

logger = get_logger(__name__)

REQUIRED_ARGS = ["commodity", "bucket", "aws_region"]

args = getResolvedOptions(sys.argv, REQUIRED_ARGS)

COMMODITY: str = args["commodity"]
BUCKET: str = args["bucket"]
AWS_REGION: str = args["aws_region"]

BRONZE_PATH = f"{BUCKET}/bronze/production/source=faostat/dataset=QCL/commodity={COMMODITY}"

# Single shared client — FAOSTAT silver is O(tens) of files, concurrency not needed
_s3 = boto3.client("s3", region_name=AWS_REGION)


def main() -> None:
    s3_fs = pafs.S3FileSystem(region=AWS_REGION)

    # --- Bulk parallel read of all bronze FAOSTAT files ---
    logger.info("Reading bronze FAOSTAT from s3://%s ...", BRONZE_PATH)
    bronze_ds = ds.dataset(BRONZE_PATH, filesystem=s3_fs, format="parquet")
    bronze_df = bronze_ds.to_table().to_pandas()
    logger.info("Loaded %d bronze rows from %d files", len(bronze_df), len(bronze_ds.files))

    # --- Vectorized silver transform, commodity-aware ---
    year_frames = transform_faostat_production_silver_df(bronze_df, commodity=COMMODITY)
    logger.info("Silver transform produced %d years of data", len(year_frames))

    success = failed = 0

    for year, year_df in year_frames:
        silver_key = f"silver/production/commodity={COMMODITY}/year={year}/part-000.parquet"
        try:
            buf = io.BytesIO()
            year_df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
            _s3.put_object(Body=buf.getvalue(), Bucket=BUCKET, Key=silver_key)
            logger.info("Wrote %s  rows=%d", silver_key, len(year_df))
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
