from __future__ import annotations

import argparse
from pathlib import Path

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.s3 import upload_file_to_s3

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="Local FAOSTAT QCL ZIP path")
    args = parser.parse_args()

    load_env()

    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    local_path = Path(args.file)

    # Single shared ZIP for all commodities — no ingest_date or commodity prefix.
    # The Glue job filters to the relevant FAO item at runtime.
    s3_key = "raw/production/source=faostat/dataset=QCL/Production_Crops_Livestock_E_All_Data_Normalized.zip"

    upload_file_to_s3(
        local_path=local_path,
        bucket=bucket,
        key=s3_key,
        aws_region=region,
    )

    logger.info("Uploaded %s to s3://%s/%s", local_path, bucket, s3_key)


if __name__ == "__main__":
    main()