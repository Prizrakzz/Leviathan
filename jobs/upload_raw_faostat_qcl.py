from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.s3 import upload_file_to_s3

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="Local FAOSTAT QCL ZIP path")
    parser.add_argument("--ingest-date", default=str(date.today()), help="YYYY-MM-DD")
    args = parser.parse_args()

    load_env()

    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    local_path = Path(args.file)

    s3_filename = local_path.name.replace("(", "").replace(")", "")
    s3_key = (
        f"raw/production/"
        f"source=faostat/"
        f"dataset=QCL/"
        f"ingest_date={args.ingest_date}/"
        f"{s3_filename}"
    )

    upload_file_to_s3(
        local_path=local_path,
        bucket=bucket,
        key=s3_key,
        aws_region=region,
    )

    logger.info("Uploaded %s to s3://%s/%s", local_path, bucket, s3_key)


if __name__ == "__main__":
    main()