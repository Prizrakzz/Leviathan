"""Glue Python Shell job: raw → bronze for FAOSTAT QCL production data.

Downloads the raw FAOSTAT ZIP from S3 to /tmp, runs the existing
transform_faostat_qcl_zip_to_bronze() function writing Parquet to /tmp,
then uploads each Parquet file to its bronze S3 key.

Required args:
  --commodity    e.g. cocoa
  --bucket       S3 bucket name
  --aws_region   e.g. us-east-1
  --ingest_date  YYYY-MM-DD
  --s3_raw_key   full S3 key of the raw FAOSTAT ZIP file
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

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

from leviathan.common.logging import get_logger
from leviathan.storage.s3 import list_s3_keys, s3_object_exists, upload_file_to_s3
from leviathan.transforms.raw_to_bronze.faostat_qcl import transform_faostat_qcl_zip_to_bronze

logger = get_logger(__name__)

REQUIRED_ARGS = ["JOB_NAME", "commodity", "bucket", "aws_region", "ingest_date", "s3_raw_key"]

args = getResolvedOptions(sys.argv, REQUIRED_ARGS)

COMMODITY: str = args["commodity"]
BUCKET: str = args["bucket"]
AWS_REGION: str = args["aws_region"]
INGEST_DATE: str = args["ingest_date"]
S3_RAW_KEY: str = args["s3_raw_key"]

TMP_ZIP = Path("/tmp/faostat_raw.zip")
TMP_BRONZE = Path("/tmp/bronze_faostat")
BRONZE_S3_PREFIX = f"bronze/production/source=faostat/dataset=QCL/commodity={COMMODITY}/"


def main() -> None:
    import boto3

    logger.info("Downloading raw FAOSTAT ZIP from s3://%s/%s", BUCKET, S3_RAW_KEY)
    s3 = boto3.client("s3", region_name=AWS_REGION)
    TMP_ZIP.parent.mkdir(parents=True, exist_ok=True)
    s3.download_file(BUCKET, S3_RAW_KEY, str(TMP_ZIP))
    logger.info("Downloaded %d bytes", TMP_ZIP.stat().st_size)

    TMP_BRONZE.mkdir(parents=True, exist_ok=True)

    written_local = transform_faostat_qcl_zip_to_bronze(
        zip_path=TMP_ZIP,
        output_dir=TMP_BRONZE,
        ingest_date=INGEST_DATE,
    )

    logger.info("Bronze transform wrote %d local Parquet files", len(written_local))

    success = 0
    failed = 0

    for local_path in written_local:
        # local_path is like /tmp/bronze_faostat/source=faostat/dataset=QCL/commodity=cocoa/year=2023/part-000.parquet
        # Derive the S3 key relative to TMP_BRONZE
        relative = local_path.relative_to(TMP_BRONZE)
        s3_key = f"bronze/production/{relative.as_posix()}"

        try:
            upload_file_to_s3(local_path, BUCKET, s3_key, aws_region=AWS_REGION)
            logger.info("Uploaded: %s", s3_key)
            success += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to upload %s — %s", s3_key, exc)
            failed += 1

    # Clean up /tmp to keep container tidy
    TMP_ZIP.unlink(missing_ok=True)
    shutil.rmtree(TMP_BRONZE, ignore_errors=True)

    logger.info(
        "raw→bronze FAOSTAT complete. success=%d  failed=%d",
        success, failed,
    )

    if failed > 0:
        raise RuntimeError(f"{failed} files failed during raw→bronze FAOSTAT transform.")


if __name__ == "__main__":
    main()
