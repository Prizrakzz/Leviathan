from __future__ import annotations

import argparse
from pathlib import Path

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_production_key
from leviathan.storage.s3 import upload_file_to_s3
from leviathan.transforms.raw_to_bronze.faostat_qcl import transform_faostat_qcl_zip_to_bronze


logger = get_logger("build_bronze_faostat_cocoa")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--raw-zip",
        required=True,
        help="Local path to raw FAOSTAT QCL ZIP",
    )
    parser.add_argument(
        "--ingest-date",
        required=True,
        help="Raw ingest date, format YYYY-MM-DD",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload bronze Parquet files to S3",
    )

    args = parser.parse_args()

    load_env()

    bucket = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    output_dir = Path("data/bronze/production/faostat/qcl")

    written_files = transform_faostat_qcl_zip_to_bronze(
        zip_path=args.raw_zip,
        output_dir=output_dir,
        ingest_date=args.ingest_date,
    )

    if not args.upload:
        logger.info("Upload disabled. Bronze files written locally only.")
        return

    for file_path in written_files:
        year_part = next(
            part for part in file_path.parts
            if part.startswith("year=")
        )
        year = int(year_part.split("=")[1])

        s3_key = bronze_production_key(
            source="faostat",
            dataset="QCL",
            commodity="cocoa",
            year=year,
            filename=file_path.name,
        )

        upload_file_to_s3(
            local_path=file_path,
            bucket=bucket,
            key=s3_key,
            aws_region=aws_region,
        )

        logger.info("Uploaded bronze file to s3://%s/%s", bucket, s3_key)


if __name__ == "__main__":
    main()