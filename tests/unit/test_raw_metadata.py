"""Unit tests for leviathan.storage.raw_metadata."""
from __future__ import annotations

import json

import boto3
import pytest
from leviathan.common.validation import SchemaValidationError
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from moto import mock_aws

BUCKET = "test-leviathan-bucket"
REGION = "us-east-1"


@pytest.fixture()
def s3_bucket():
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        yield s3


# ---------------------------------------------------------------------------
# check_min_file_size
# ---------------------------------------------------------------------------

class TestCheckMinFileSize:
    def test_nasa_power_above_threshold_passes(self):
        data = b"x" * 2_000  # 2 KB > 1 KB minimum
        check_min_file_size(data, "nasa_power")  # should not raise

    def test_nasa_power_below_threshold_raises(self):
        data = b"x" * 500  # 500 B < 1 KB minimum
        with pytest.raises(SchemaValidationError, match="below the minimum"):
            check_min_file_size(data, "nasa_power", context="test_key")

    def test_faostat_below_threshold_raises(self):
        data = b"x" * 100  # tiny — well below 10 MB
        with pytest.raises(SchemaValidationError, match="faostat_qcl"):
            check_min_file_size(data, "faostat_qcl")

    def test_unknown_source_skips_check(self):
        tiny_data = b"x" * 5
        check_min_file_size(tiny_data, "unknown_source")  # should not raise

    def test_error_message_includes_context(self):
        with pytest.raises(SchemaValidationError, match="my_context"):
            check_min_file_size(b"x", "nasa_power", context="my_context")


# ---------------------------------------------------------------------------
# write_raw_s3_metadata
# ---------------------------------------------------------------------------

class TestWriteRawS3Metadata:
    def test_creates_companion_json(self, s3_bucket):
        raw_bytes = b'{"data": "test"}'
        raw_key = "raw/weather/source=nasa_power/commodity=cocoa/test.json"

        write_raw_s3_metadata(
            bucket=BUCKET,
            raw_key=raw_key,
            raw_bytes=raw_bytes,
            source_url="https://power.larc.nasa.gov/api",
            content_type="application/json",
            aws_region=REGION,
        )

        meta_key = f"raw_meta/{raw_key}_meta.json"
        obj = s3_bucket.get_object(Bucket=BUCKET, Key=meta_key)
        record = json.loads(obj["Body"].read())

        assert record["raw_key"] == raw_key
        assert record["source_url"] == "https://power.larc.nasa.gov/api"
        assert record["content_type"] == "application/json"
        assert record["file_size_bytes"] == len(raw_bytes)
        assert len(record["sha256"]) == 64  # SHA-256 hex digest length
        assert "download_timestamp" in record

    def test_sha256_is_correct(self, s3_bucket):
        import hashlib

        raw_bytes = b"hello world"
        raw_key = "raw/test_sha256.json"

        write_raw_s3_metadata(
            bucket=BUCKET,
            raw_key=raw_key,
            raw_bytes=raw_bytes,
            source_url="test",
            content_type="application/json",
            aws_region=REGION,
        )

        meta_key = f"raw_meta/{raw_key}_meta.json"
        record = json.loads(s3_bucket.get_object(Bucket=BUCKET, Key=meta_key)["Body"].read())
        expected = hashlib.sha256(raw_bytes).hexdigest()
        assert record["sha256"] == expected

    def test_write_failure_does_not_raise(self):
        # Calling without a real/mock S3 bucket should log but not raise
        write_raw_s3_metadata(
            bucket="nonexistent-bucket-xyz",
            raw_key="raw/test.json",
            raw_bytes=b"data",
            source_url="test",
            content_type="application/json",
            aws_region=REGION,
        )  # should not raise
