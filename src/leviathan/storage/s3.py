from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

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


def list_s3_keys(
    bucket: str,
    prefix: str,
    suffix: str = "",
    aws_region: str = "us-east-1",
) -> list[str]:
    """Return all S3 keys under *prefix* that end with *suffix* (paginated)."""
    s3 = boto3.client("s3", region_name=aws_region)
    paginator = s3.get_paginator("list_objects_v2")

    keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not suffix or key.endswith(suffix):
                keys.append(key)

    return keys


def download_s3_json(
    bucket: str,
    key: str,
    aws_region: str = "us-east-1",
) -> Any:
    """Download an S3 object and parse it as JSON. No local file is written."""
    s3 = boto3.client("s3", region_name=aws_region)
    response = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(response["Body"].read())


def upload_bytes_to_s3(
    data: bytes,
    bucket: str,
    key: str,
    aws_region: str = "us-east-1",
) -> None:
    """Upload raw bytes to S3. No local file is required."""
    s3 = boto3.client("s3", region_name=aws_region)
    s3.put_object(Body=data, Bucket=bucket, Key=key)
