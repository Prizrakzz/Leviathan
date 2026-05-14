from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)

_DL_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "standard"})


def write_dead_letter(
    bucket: str,
    source: str,
    commodity: str,
    original_key: str,
    error: str,
    aws_region: str = "us-east-1",
) -> None:
    """Write a JSON dead-letter record for a file that exhausted all retries.

    Stored at:
        dead_letter/source={source}/commodity={commodity}/{ts}_{filename}_error.json

    Failures to write the dead-letter record are logged but never re-raised so
    that a dead-letter write failure does not mask the original error.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = original_key.rsplit("/", 1)[-1]
    dl_key = f"dead_letter/source={source}/commodity={commodity}/{ts}_{filename}_error.json"

    record = {
        "original_key": original_key,
        "error": error,
        "timestamp": ts,
        "commodity": commodity,
        "source": source,
    }

    try:
        s3 = boto3.client("s3", region_name=aws_region, config=_DL_RETRY_CONFIG)
        s3.put_object(
            Body=json.dumps(record, indent=2).encode("utf-8"),
            Bucket=bucket,
            Key=dl_key,
            ContentType="application/json",
        )
        logger.warning("Dead-lettered %s → %s", original_key, dl_key)
    except Exception:
        logger.exception(
            "Failed to write dead-letter record for %s (original error: %s)",
            original_key,
            error,
        )
