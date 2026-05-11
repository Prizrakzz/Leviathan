from __future__ import annotations

from pathlib import Path

import boto3
from botocore.exceptions import ClientError


def upload_file_to_s3(
    local_path: str | Path,
    bucket: str,
    key: str,
    aws_region: str = "us-east-1",
) -> None:
    path = Path(local_path)

    if not path.exists():
        raise FileNotFoundError(f"Local file does not exist: {path}")

    s3 = boto3.client("s3", region_name=aws_region)
    s3.upload_file(str(path), bucket, key)


def s3_object_exists(
    bucket: str,
    key: str,
    aws_region: str = "us-east-1",
) -> bool:
    s3 = boto3.client("s3", region_name=aws_region)

    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as error:
        status_code = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")

        if status_code == 404:
            return False

        raise
