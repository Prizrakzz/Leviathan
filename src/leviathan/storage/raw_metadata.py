"""Raw-layer metadata helpers for Leviathan ingestion.

Provides two functions used by raw-file producers (fetch/upload jobs):
- ``check_min_file_size`` — validates the downloaded payload is above a minimum
  threshold before it is written to S3.
- ``write_raw_s3_metadata`` — persists a companion JSON record alongside each
  raw S3 object containing the SHA-256 checksum, file size, source URL, content
  type, and download timestamp for lineage tracking.

Failures in ``write_raw_s3_metadata`` are logged but never re-raised so that a
metadata write failure does not abort the main ingestion pipeline.
"""
from __future__ import annotations

import hashlib
import json

import boto3
from botocore.config import Config

from leviathan.common.constants import MIN_RAW_FILE_SIZES
from leviathan.common.logging import get_logger
from leviathan.common.validation import SchemaValidationError
from leviathan.storage.metadata import utc_now_iso

logger = get_logger(__name__)

_META_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "standard"})


def check_min_file_size(data: bytes, source: str, context: str = "") -> None:
    """Raise :exc:`SchemaValidationError` if *data* is below the minimum threshold.

    Args:
        data:    Raw bytes of the downloaded file.
        source:  Source identifier, e.g. ``"nasa_power"`` or ``"faostat_qcl"``.
        context: Optional human-readable label for the error message.

    Raises:
        SchemaValidationError: If the file is smaller than the expected minimum.
    """
    min_size = MIN_RAW_FILE_SIZES.get(source)
    if min_size is None:
        return
    if len(data) < min_size:
        prefix = f"[{context}] " if context else ""
        raise SchemaValidationError(
            f"{prefix}File size {len(data):,} bytes is below the minimum "
            f"{min_size:,} bytes for source '{source}'."
        )


def write_raw_s3_metadata(
    bucket: str,
    raw_key: str,
    raw_bytes: bytes,
    source_url: str,
    content_type: str,
    aws_region: str = "us-east-1",
) -> None:
    """Write a companion JSON metadata file next to a raw S3 object.

    Stored at ``raw_meta/{raw_key}_meta.json``.  Contains:

    - ``raw_key``             — the S3 key of the raw file
    - ``source_url``          — the URL or origin label the file was fetched from
    - ``content_type``        — MIME type of the payload (e.g. ``"application/json"``)
    - ``file_size_bytes``     — byte length of the raw payload
    - ``sha256``              — hex-encoded SHA-256 digest of the raw payload
    - ``download_timestamp``  — UTC ISO-8601 timestamp of when the metadata was written

    Args:
        bucket:       S3 bucket name.
        raw_key:      S3 key of the raw file (used to derive the metadata key).
        raw_bytes:    Exact bytes of the raw payload.
        source_url:   The URL the data was fetched from (or ``"local_upload"`` if
                      the file was manually sourced).
        content_type: MIME content-type string.
        aws_region:   AWS region for the S3 client.
    """
    checksum = hashlib.sha256(raw_bytes).hexdigest()
    meta_key = f"raw_meta/{raw_key}_meta.json"
    record = {
        "raw_key": raw_key,
        "source_url": source_url,
        "content_type": content_type,
        "file_size_bytes": len(raw_bytes),
        "sha256": checksum,
        "download_timestamp": utc_now_iso(),
    }
    try:
        s3 = boto3.client("s3", region_name=aws_region, config=_META_RETRY_CONFIG)
        s3.put_object(
            Body=json.dumps(record, indent=2).encode("utf-8"),
            Bucket=bucket,
            Key=meta_key,
            ContentType="application/json",
        )
        logger.debug("Wrote raw metadata: %s", meta_key)
    except Exception:  # noqa: BLE001 — intentional: metadata write is best-effort; failure must not abort the raw download
        logger.exception("Failed to write raw metadata for %s — continuing", raw_key)
