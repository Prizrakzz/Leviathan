"""Thin AWS S3 wrappers used across batch tasks and Glue jobs.

Provides upload, existence checks, download, and listing helpers built on
boto3, with a shared retry configuration for transient S3 errors.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_random_exponential

if TYPE_CHECKING:
    from datetime import datetime  # noqa: F401 -- forward ref for list_s3_keys_with_mtime

    from mypy_boto3_s3 import S3Client

# ---------------------------------------------------------------------------
# Module-level boto3 retry configuration
# ---------------------------------------------------------------------------

_BOTO_RETRY_CONFIG = Config(retries={"max_attempts": 10, "mode": "adaptive"})

_RETRYABLE_CODES = frozenset({
    "503",
    "SlowDown",
    "InternalError",
    "RequestTimeout",
    "ServiceUnavailable",
    "RequestThrottled",
    "Throttling",
})


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        return code in _RETRYABLE_CODES
    return isinstance(exc, BotoCoreError)


def upload_file_to_s3(
    local_path: str | Path,
    bucket: str,
    key: str,
    aws_region: str = "us-east-1",
) -> None:
    path = Path(local_path)

    if not path.exists():
        raise FileNotFoundError(f"Local file does not exist: {path}")

    s3 = boto3.client("s3", region_name=aws_region, config=_BOTO_RETRY_CONFIG)
    s3.upload_file(str(path), bucket, key)


def s3_object_exists(
    bucket: str,
    key: str,
    aws_region: str = "us-east-1",
) -> bool:
    s3 = boto3.client("s3", region_name=aws_region, config=_BOTO_RETRY_CONFIG)

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
    s3 = boto3.client("s3", region_name=aws_region, config=_BOTO_RETRY_CONFIG)
    paginator = s3.get_paginator("list_objects_v2")

    keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not suffix or key.endswith(suffix):
                keys.append(key)

    return keys


def list_s3_keys_with_mtime(
    bucket: str,
    prefix: str,
    suffix: str = "",
    aws_region: str = "us-east-1",
) -> dict[str, "datetime"]:
    """Return ``{key: LastModified}`` for objects under *prefix* ending in *suffix*.

    Used by the SILVER-V002 freshness-aware skip-existing check so the bronze->silver
    runner never silently declines to refresh a silver partition whose bronze source
    is newer (the CHIRPS stale-silver hazard, base_jobs.py:338-356)."""
    s3 = boto3.client("s3", region_name=aws_region, config=_BOTO_RETRY_CONFIG)
    paginator = s3.get_paginator("list_objects_v2")

    out: dict[str, "datetime"] = {}
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not suffix or key.endswith(suffix):
                out[key] = obj["LastModified"]
    return out


def download_s3_json(
    bucket: str,
    key: str,
    aws_region: str = "us-east-1",
) -> dict[str, Any]:
    """Download an S3 object and parse it as JSON. No local file is written."""
    s3 = boto3.client("s3", region_name=aws_region, config=_BOTO_RETRY_CONFIG)
    response = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(response["Body"].read())  # type: ignore[no-any-return]


def upload_bytes_to_s3(
    data: bytes,
    bucket: str,
    key: str,
    aws_region: str = "us-east-1",
) -> None:
    """Upload raw bytes to S3. No local file is required."""
    s3 = boto3.client("s3", region_name=aws_region, config=_BOTO_RETRY_CONFIG)
    s3.put_object(Body=data, Bucket=bucket, Key=key)


_s3_local = threading.local()


# The pool a THREAD-LOCAL client carries. botocore's default max_pool_connections is 10, and
# callers that create the client on the main thread and then hand it to a wider pool (e.g.
# wasde_silver_task.py -> _READ_WORKERS = 16) burn urllib3's "Connection pool is full,
# discarding connection ... pool size: 10" on every fire -- each discard is a torn-down TLS
# session re-established on the next read. 32 covers every in-repo worker count (max 16) with
# headroom; it is a CEILING, not an allocation, so a single-threaded caller pays nothing.
_BOTO_POOLED_CONFIG = Config(retries={"max_attempts": 10, "mode": "adaptive"},
                             max_pool_connections=32)


def get_thread_local_s3_client(aws_region: str) -> S3Client:
    """Return a thread-local boto3 S3 client for use in ThreadPoolExecutor workers.

    Creates a new client on first access per thread, then reuses it.
    Avoids connection-pool contention when many threads share an S3 client.
    """
    if not hasattr(_s3_local, "clients"):
        _s3_local.clients = {}
    if aws_region not in _s3_local.clients:
        _s3_local.clients[aws_region] = boto3.client(
            "s3", region_name=aws_region, config=_BOTO_POOLED_CONFIG
        )
    return _s3_local.clients[aws_region]


@retry(
    wait=wait_random_exponential(min=1, max=60),
    stop=stop_after_attempt(5),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)
def s3_download_with_retry(bucket: str, key: str, s3_client: S3Client) -> bytes:
    """Download an S3 object with exponential-backoff retry on transient errors.

    Retries up to 5 times on SlowDown / InternalError / network-level failures.
    Raises immediately on non-retryable errors (e.g. 404 NoSuchKey).
    """
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()
