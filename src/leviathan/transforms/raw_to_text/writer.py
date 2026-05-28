from __future__ import annotations

import json
from typing import TYPE_CHECKING

from botocore.exceptions import ClientError

from leviathan.transforms.raw_to_text.schema import DocumentJson

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


def document_exists(s3_client: S3Client, bucket: str, key: str) -> bool:
    """Return True if a document.json already exists at *key* in *bucket*.

    Used as the idempotency gate before any extraction is attempted — covers
    pdfplumber, TXT decode, and Textract uniformly.
    """
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "404":
            return False
        raise


def write_document(
    s3_client: S3Client,
    bucket: str,
    key: str,
    doc: DocumentJson,
) -> None:
    """Serialise *doc* as compact JSON and write it to S3 at *key*."""
    body = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/json",
    )
