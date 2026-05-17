"""Unit tests for leviathan.storage.dead_letter."""
from __future__ import annotations

import json
import re

import boto3
import pytest
from moto import mock_aws


BUCKET = "test-leviathan-bucket"
REGION = "us-east-1"


@pytest.fixture()
def s3_bucket():
    """Create a mock S3 bucket for each test."""
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        yield s3


class TestWriteDeadLetter:
    def test_creates_s3_object(self, s3_bucket):
        from leviathan.storage.dead_letter import write_dead_letter

        write_dead_letter(
            bucket=BUCKET,
            source="nasa_power",
            commodity="cocoa",
            original_key="raw/weather/source=nasa_power/cocoa/2020_01.json",
            error="TimeoutError: S3 read timed out",
            aws_region=REGION,
        )

        objects = s3_bucket.list_objects_v2(Bucket=BUCKET, Prefix="dead_letter/")
        assert objects["KeyCount"] == 1

    def test_key_format(self, s3_bucket):
        from leviathan.storage.dead_letter import write_dead_letter

        write_dead_letter(
            bucket=BUCKET,
            source="faostat",
            commodity="corn_cbot",
            original_key="bronze/production/source=faostat/dataset=QCL/commodity=corn_cbot/year=2020/part-000.parquet",
            error="KeyError: ingest_date",
            aws_region=REGION,
        )

        objects = s3_bucket.list_objects_v2(Bucket=BUCKET, Prefix="dead_letter/")
        key = objects["Contents"][0]["Key"]
        # dead_letter/source={source}/commodity={commodity}/{ts}_{filename}_error.json
        assert re.match(
            r"dead_letter/source=faostat/commodity=corn_cbot/\d{8}T\d{6}Z_.+_error\.json",
            key,
        )

    def test_optional_fields_included_in_record(self, s3_bucket):
        from leviathan.storage.dead_letter import write_dead_letter

        write_dead_letter(
            bucket=BUCKET,
            source="nasa_power",
            commodity="cocoa",
            original_key="raw/weather/source=nasa_power/cocoa/test.json",
            error="SomeError",
            aws_region=REGION,
            source_url="https://power.larc.nasa.gov/api",
            checksum_sha256="abc123",
        )

        objects = s3_bucket.list_objects_v2(Bucket=BUCKET, Prefix="dead_letter/")
        record = json.loads(
            s3_bucket.get_object(Bucket=BUCKET, Key=objects["Contents"][0]["Key"])["Body"].read()
        )
        assert record["source_url"] == "https://power.larc.nasa.gov/api"
        assert record["checksum_sha256"] == "abc123"

    def test_optional_fields_absent_when_not_provided(self, s3_bucket):
        from leviathan.storage.dead_letter import write_dead_letter

        write_dead_letter(
            bucket=BUCKET,
            source="nasa_power",
            commodity="cocoa",
            original_key="raw/weather/source=nasa_power/cocoa/test.json",
            error="SomeError",
            aws_region=REGION,
        )

        objects = s3_bucket.list_objects_v2(Bucket=BUCKET, Prefix="dead_letter/")
        record = json.loads(
            s3_bucket.get_object(Bucket=BUCKET, Key=objects["Contents"][0]["Key"])["Body"].read()
        )
        assert "source_url" not in record
        assert "checksum_sha256" not in record

    def test_record_content(self, s3_bucket):
        from leviathan.storage.dead_letter import write_dead_letter

        original_key = "raw/weather/2020_01.json"
        error_msg = "ValueError: missing column"

        write_dead_letter(
            bucket=BUCKET,
            source="nasa_power",
            commodity="cocoa",
            original_key=original_key,
            error=error_msg,
            aws_region=REGION,
        )

        objects = s3_bucket.list_objects_v2(Bucket=BUCKET, Prefix="dead_letter/")
        key = objects["Contents"][0]["Key"]
        body = s3_bucket.get_object(Bucket=BUCKET, Key=key)["Body"].read()
        record = json.loads(body)

        assert record["original_key"] == original_key
        assert record["error"] == error_msg
        assert record["source"] == "nasa_power"
        assert record["commodity"] == "cocoa"

    def test_never_raises_on_s3_error(self):
        """write_dead_letter must not propagate its own S3 errors."""
        from unittest.mock import MagicMock, patch

        from leviathan.storage.dead_letter import write_dead_letter

        mock_s3 = MagicMock()
        mock_s3.put_object.side_effect = RuntimeError("S3 put failed")

        with patch("leviathan.storage.dead_letter.boto3.client", return_value=mock_s3):
            # Should complete without raising
            write_dead_letter(
                bucket=BUCKET,
                source="nasa_power",
                commodity="cocoa",
                original_key="raw/test.json",
                error="some error",
                aws_region=REGION,
            )
