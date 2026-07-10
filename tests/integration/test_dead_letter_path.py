"""Integration tests for the dead-letter S3 path.

Tests that write_dead_letter creates a retrievable S3 object and that
s3_object_exists correctly detects its presence after writing.
Uses moto to mock AWS S3 calls.
"""
from __future__ import annotations

import json

import boto3
import pytest
from leviathan.storage.dead_letter import write_dead_letter
from leviathan.storage.s3 import s3_object_exists
from moto import mock_aws

BUCKET = "test-leviathan-dl"
REGION = "us-east-1"


@pytest.fixture()
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name=REGION)
        client.create_bucket(Bucket=BUCKET)
        yield client


class TestDeadLetterS3Integration:
    def test_object_exists_after_write(self, s3):
        write_dead_letter(
            bucket=BUCKET,
            source="nasa_power",
            commodity="cocoa",
            original_key="raw/weather/source=nasa_power/cocoa/2020_01.json",
            error="TimeoutError: read timed out",
            aws_region=REGION,
        )
        objects = s3.list_objects_v2(Bucket=BUCKET, Prefix="dead_letter/")
        assert objects["KeyCount"] == 1

    def test_s3_object_exists_detects_dead_letter(self, s3):
        write_dead_letter(
            bucket=BUCKET,
            source="faostat",
            commodity="corn_cbot",
            original_key="bronze/production/part-000.parquet",
            error="KeyError: ingest_date",
            aws_region=REGION,
        )
        objects = s3.list_objects_v2(Bucket=BUCKET, Prefix="dead_letter/")
        key = objects["Contents"][0]["Key"]
        # s3_object_exists should find the same object
        assert s3_object_exists(BUCKET, key, REGION) is True

    def test_dead_letter_record_is_valid_json(self, s3):
        write_dead_letter(
            bucket=BUCKET,
            source="chirps",
            commodity="cocoa",
            original_key="raw/weather/chirps/2020_01.tif",
            error="ValueError: empty file",
            aws_region=REGION,
        )
        objects = s3.list_objects_v2(Bucket=BUCKET, Prefix="dead_letter/")
        key = objects["Contents"][0]["Key"]
        body = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
        record = json.loads(body)
        assert record["source"] == "chirps"
        assert record["commodity"] == "cocoa"
        assert "error" in record
        assert "timestamp" in record

    def test_optional_source_url_in_record(self, s3):
        write_dead_letter(
            bucket=BUCKET,
            source="nasa_power",
            commodity="cocoa",
            original_key="raw/weather/source=nasa_power/test.json",
            error="SomeError",
            aws_region=REGION,
            source_url="https://power.larc.nasa.gov/api",
        )
        objects = s3.list_objects_v2(Bucket=BUCKET, Prefix="dead_letter/")
        key = objects["Contents"][0]["Key"]
        record = json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())
        assert record["source_url"] == "https://power.larc.nasa.gov/api"

    def test_non_existent_key_not_found(self, s3):
        # Sanity-check: a key that was never written should not exist
        assert s3_object_exists(BUCKET, "dead_letter/nonexistent.json", REGION) is False

    def test_two_separate_errors_create_two_objects(self, s3):
        import time

        write_dead_letter(
            bucket=BUCKET,
            source="nasa_power",
            commodity="cocoa",
            original_key="raw/key1.json",
            error="Error 1",
            aws_region=REGION,
        )
        time.sleep(0.01)  # ensure different timestamps
        write_dead_letter(
            bucket=BUCKET,
            source="nasa_power",
            commodity="cocoa",
            original_key="raw/key2.json",
            error="Error 2",
            aws_region=REGION,
        )
        objects = s3.list_objects_v2(Bucket=BUCKET, Prefix="dead_letter/")
        assert objects["KeyCount"] == 2
