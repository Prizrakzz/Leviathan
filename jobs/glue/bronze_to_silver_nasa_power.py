"""Glue Python Shell: bronze → silver NASA POWER (bulk parallel I/O).

Performance:
  Before: ~40 min  — serial loop, 3 S3 API calls per file, new boto3 client each call
  After:  ~2 min   — pyarrow.dataset reads all files in parallel (internal thread pool),
                     one vectorized pandas transform, ThreadPoolExecutor(32) writes
                     all partitions concurrently

Reusable: pass --commodity <name> to handle any commodity's weather data.
Pass --force_overwrite to delete and re-write existing silver partitions.
"""
from __future__ import annotations

import io
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    _subprocess.check_call([sys.executable, "-m", "pip", "install", _whl, "--quiet"])


_install_leviathan()
# ---- End bootstrap ----

import boto3
import pyarrow.dataset as ds
import pyarrow.fs as pafs

from leviathan.common.logging import get_logger
from leviathan.transforms.bronze_to_silver.nasa_power_weather import clean_one_weather_df

logger = get_logger(__name__)

REQUIRED_ARGS = ["JOB_NAME", "commodity", "bucket", "aws_region"]
OPTIONAL_ARGS = ["force_overwrite"]

args = getResolvedOptions(sys.argv, REQUIRED_ARGS + OPTIONAL_ARGS)

COMMODITY: str = args["commodity"]
BUCKET: str = args["bucket"]
AWS_REGION: str = args["aws_region"]
FORCE_OVERWRITE: bool = args.get("force_overwrite", "false").lower() == "true"

BRONZE_PATH = f"{BUCKET}/bronze/weather/source=nasa_power/commodity={COMMODITY}"
SILVER_BASE = f"silver/weather/source=nasa_power/commodity={COMMODITY}"
MAX_WORKERS = 64

# One boto3 client per thread
_local = threading.local()


def _s3():
    if not hasattr(_local, "client"):
        _local.client = boto3.client("s3", region_name=AWS_REGION)
    return _local.client


def write_partition(args_tuple: tuple) -> str:
    (country, region, year, month), group_df = args_tuple
    silver_key = (
        f"{SILVER_BASE}/country={country}/region={region}"
        f"/year={year}/month={month:02d}/part-000.parquet"
    )
    buf = io.BytesIO()
    group_df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    _s3().put_object(Body=buf.getvalue(), Bucket=BUCKET, Key=silver_key)
    return silver_key


def main() -> None:
    s3_fs = pafs.S3FileSystem(region=AWS_REGION)

    # --- Read ALL bronze files in parallel (pyarrow internal thread pool) ---
    logger.info("Reading bronze dataset from s3://%s ...", BRONZE_PATH)
    bronze_ds = ds.dataset(BRONZE_PATH, filesystem=s3_fs, format="parquet")
    n_files = len(bronze_ds.files)
    table = bronze_ds.to_table()
    logger.info("Loaded %d rows from %d bronze files", len(table), n_files)

    # --- Single vectorized silver transform over the full DataFrame ---
    import pandas as pd  # noqa: PLC0415 — imported here to avoid top-level import order issues
    df = table.to_pandas()
    silver_df = clean_one_weather_df(df, source_label=BRONZE_PATH)
    logger.info("Silver transform produced %d rows", len(silver_df))

    # --- Skip partitions that already exist unless force_overwrite ---
    partitions = list(silver_df.groupby(["country", "region", "year", "month"]))
    logger.info("Total silver partitions to consider: %d", len(partitions))

    if not FORCE_OVERWRITE:
        from leviathan.storage.s3 import list_s3_keys  # noqa: PLC0415
        existing = set(
            list_s3_keys(BUCKET, SILVER_BASE + "/", suffix=".parquet", aws_region=AWS_REGION)
        )
        before = len(partitions)
        partitions = [
            (key, group) for key, group in partitions
            if (
                f"{SILVER_BASE}/country={key[0]}/region={key[1]}"
                f"/year={key[2]}/month={key[3]:02d}/part-000.parquet"
            ) not in existing
        ]
        logger.info(
            "Skipping %d existing silver partitions. Writing %d new.",
            before - len(partitions), len(partitions),
        )

    if not partitions:
        logger.info("All silver partitions already exist. Nothing to write.")
        return

    # --- Write all partitions concurrently ---
    logger.info("Writing %d partitions with %d workers ...", len(partitions), MAX_WORKERS)

    success = failed = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(write_partition, item): item[0] for item in partitions}
        for future in as_completed(futures):
            try:
                future.result()
                success += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                logger.error("Partition write failed: %s", exc)

    logger.info(
        "bronze→silver NASA POWER complete. written=%d  failed=%d",
        success, failed,
    )
    if failed > 0:
        raise RuntimeError(f"{failed} partition writes failed during bronze→silver NASA POWER.")


if __name__ == "__main__":
    main()
