"""Glue Python Shell job: raw → bronze for FAOSTAT QCL production data.

Downloads the raw FAOSTAT ZIP from S3 to /tmp, runs the existing
transform_faostat_qcl_zip_to_bronze() function writing Parquet to /tmp,
then uploads each Parquet file to its bronze S3 key.

Required args:
  --commodity      e.g. cocoa
  --fao_item_name  exact FAO CSV Item string, e.g. "Maize (corn)"
  --bucket         S3 bucket name
  --aws_region     e.g. us-east-1
  --ingest_date    YYYY-MM-DD
  --s3_raw_key     full S3 key of the raw FAOSTAT ZIP file
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from awsglue.utils import getResolvedOptions
from bootstrap import run_bootstrap

run_bootstrap()

from datetime import date as _dt_date

from leviathan.common.logging import get_logger
from leviathan.storage.s3 import upload_file_to_s3
from leviathan.transforms.raw_to_bronze.faostat_qcl import transform_faostat_qcl_zip_to_bronze

logger = get_logger(__name__)

REQUIRED_ARGS = ["commodity", "fao_item_name", "bucket", "aws_region", "s3_raw_key"]

# ingest_date is OPTIONAL and resolves to TODAY AT RUN TIME. It used to be required and was
# supplied by a baked Glue default argument built with formatdate(timestamp()) -- i.e. the date of
# the last `terraform apply`. That value ROTS: every run after the apply stamped bronze with a date
# that grew staler by the day (it read 2026-06-13 until an apply on 2026-07-30 moved it), and it
# also made three Glue jobs diff on EVERY terraform plan, because timestamp() is unknowable at plan
# time. Defaulting here -- the same shape raw_to_bronze_nasa_power already used -- fixes both: the
# stamp is the real run date, and the terraform default_arguments no longer carry a moving value.
args = getResolvedOptions(sys.argv, REQUIRED_ARGS)
_ingest_override = next(
    (a.split("=", 1)[1] for a in sys.argv if a.startswith("--ingest_date=")),
    None,
) or next(
    (sys.argv[i + 1] for i, a in enumerate(sys.argv)
     if a == "--ingest_date" and i + 1 < len(sys.argv)),
    None,
)
args["ingest_date"] = _ingest_override or _dt_date.today().isoformat()

COMMODITY:      str = args["commodity"]
FAO_ITEM_NAME:  str = args["fao_item_name"]
BUCKET:         str = args["bucket"]
AWS_REGION:     str = args["aws_region"]
INGEST_DATE:    str = args["ingest_date"]
S3_RAW_KEY:     str = args["s3_raw_key"]

TMP_ZIP = Path("/tmp/faostat_raw.zip")
TMP_BRONZE = Path("/tmp/bronze_faostat")
BRONZE_S3_PREFIX = f"bronze/production/source=faostat/dataset=QCL/commodity={COMMODITY}/"


def main() -> None:
    import boto3
    from botocore.config import Config

    _retry_cfg = Config(retries={"max_attempts": 10, "mode": "adaptive"})

    logger.info("Downloading raw FAOSTAT ZIP from s3://%s/%s", BUCKET, S3_RAW_KEY)
    s3 = boto3.client("s3", region_name=AWS_REGION, config=_retry_cfg)
    TMP_ZIP.parent.mkdir(parents=True, exist_ok=True)
    s3.download_file(BUCKET, S3_RAW_KEY, str(TMP_ZIP))
    logger.info("Downloaded %d bytes", TMP_ZIP.stat().st_size)

    TMP_BRONZE.mkdir(parents=True, exist_ok=True)

    written_local = transform_faostat_qcl_zip_to_bronze(
        zip_path=TMP_ZIP,
        output_dir=TMP_BRONZE,
        ingest_date=INGEST_DATE,
        commodity=COMMODITY,
        fao_item_name=FAO_ITEM_NAME,
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
        except Exception as exc:  # noqa: BLE001 — intentional: catch per-file upload errors, accumulate failures, and continue uploading remaining files; RuntimeError is raised below if any failed
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
