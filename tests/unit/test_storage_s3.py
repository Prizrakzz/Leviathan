"""Unit tests for leviathan.storage.s3."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import boto3
import pytest
from botocore.exceptions import BotoCoreError, ClientError
from moto import mock_aws

from leviathan.storage.s3 import (
    _is_retryable,
    download_s3_json,
    list_s3_keys,
    s3_download_with_retry,
    s3_object_exists,
    upload_bytes_to_s3,
    upload_file_to_s3,
)

BUCKET = "test-leviathan"
REGION = "us-east-1"


@pytest.fixture()
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name=REGION)
        client.create_bucket(Bucket=BUCKET)
        yield client


# ---------------------------------------------------------------------------
# _is_retryable
# ---------------------------------------------------------------------------

class TestIsRetryable:
    def _make_client_error(self, code: str) -> ClientError:
        return ClientError(
            {"Error": {"Code": code, "Message": "test"}}, "TestOperation"
        )

    def test_slow_down_is_retryable(self):
        assert _is_retryable(self._make_client_error("SlowDown")) is True

    def test_throttling_is_retryable(self):
        assert _is_retryable(self._make_client_error("Throttling")) is True

    def test_503_is_retryable(self):
        assert _is_retryable(self._make_client_error("503")) is True

    def test_internal_error_is_retryable(self):
        assert _is_retryable(self._make_client_error("InternalError")) is True

    def test_no_such_key_is_not_retryable(self):
        assert _is_retryable(self._make_client_error("NoSuchKey")) is False

    def test_access_denied_is_not_retryable(self):
        assert _is_retryable(self._make_client_error("AccessDenied")) is False

    def test_botocore_error_is_retryable(self):
        # BotoCoreError (e.g. network-level) is always retryable
        class _FakeBotoCoreError(BotoCoreError):
            msg = "oops"
        assert _is_retryable(_FakeBotoCoreError()) is True

    def test_non_aws_exception_is_not_retryable(self):
        assert _is_retryable(ValueError("unrelated")) is False


# ---------------------------------------------------------------------------
# s3_object_exists
# ---------------------------------------------------------------------------

class TestS3ObjectExists:
    def test_returns_true_when_object_exists(self, s3):
        s3.put_object(Bucket=BUCKET, Key="some/key.json", Body=b"{}")
        assert s3_object_exists(BUCKET, "some/key.json", REGION) is True

    def test_returns_false_when_object_missing(self, s3):
        assert s3_object_exists(BUCKET, "missing/key.json", REGION) is False

    def test_different_keys_are_independent(self, s3):
        s3.put_object(Bucket=BUCKET, Key="present.json", Body=b"{}")
        assert s3_object_exists(BUCKET, "present.json", REGION) is True
        assert s3_object_exists(BUCKET, "absent.json", REGION) is False


# ---------------------------------------------------------------------------
# list_s3_keys
# ---------------------------------------------------------------------------

class TestListS3Keys:
    def test_returns_all_keys_under_prefix(self, s3):
        s3.put_object(Bucket=BUCKET, Key="bronze/a.json", Body=b"{}")
        s3.put_object(Bucket=BUCKET, Key="bronze/b.json", Body=b"{}")
        s3.put_object(Bucket=BUCKET, Key="silver/c.json", Body=b"{}")
        keys = list_s3_keys(BUCKET, "bronze/", aws_region=REGION)
        assert sorted(keys) == ["bronze/a.json", "bronze/b.json"]

    def test_suffix_filter_applied(self, s3):
        s3.put_object(Bucket=BUCKET, Key="data/file.parquet", Body=b"")
        s3.put_object(Bucket=BUCKET, Key="data/file.json", Body=b"")
        keys = list_s3_keys(BUCKET, "data/", suffix=".parquet", aws_region=REGION)
        assert keys == ["data/file.parquet"]

    def test_empty_prefix_returns_empty_when_no_keys(self, s3):
        keys = list_s3_keys(BUCKET, "nonexistent/", aws_region=REGION)
        assert keys == []

    def test_no_suffix_returns_all_objects(self, s3):
        s3.put_object(Bucket=BUCKET, Key="prefix/a.parquet", Body=b"")
        s3.put_object(Bucket=BUCKET, Key="prefix/b.json", Body=b"")
        keys = list_s3_keys(BUCKET, "prefix/", aws_region=REGION)
        assert len(keys) == 2


# ---------------------------------------------------------------------------
# download_s3_json
# ---------------------------------------------------------------------------

class TestDownloadS3Json:
    def test_returns_parsed_dict(self, s3):
        payload = {"commodity": "cocoa", "year": 2020}
        s3.put_object(
            Bucket=BUCKET, Key="data/payload.json", Body=json.dumps(payload).encode()
        )
        result = download_s3_json(BUCKET, "data/payload.json", REGION)
        assert result == payload

    def test_returns_nested_dict(self, s3):
        nested = {"properties": {"parameters": {"T2M": {"2020010": 28.5}}}}
        s3.put_object(
            Bucket=BUCKET, Key="data/nested.json", Body=json.dumps(nested).encode()
        )
        result = download_s3_json(BUCKET, "data/nested.json", REGION)
        assert result["properties"]["parameters"]["T2M"]["2020010"] == 28.5

    def test_raises_client_error_on_missing_key(self, s3):
        with pytest.raises(ClientError):
            download_s3_json(BUCKET, "no/such/key.json", REGION)


# ---------------------------------------------------------------------------
# upload_bytes_to_s3
# ---------------------------------------------------------------------------

class TestUploadBytesToS3:
    def test_object_retrievable_after_upload(self, s3):
        data = b"hello world"
        upload_bytes_to_s3(data, BUCKET, "test/hello.bin", REGION)
        response = s3.get_object(Bucket=BUCKET, Key="test/hello.bin")
        assert response["Body"].read() == data

    def test_empty_bytes_uploaded(self, s3):
        upload_bytes_to_s3(b"", BUCKET, "test/empty.bin", REGION)
        response = s3.get_object(Bucket=BUCKET, Key="test/empty.bin")
        assert response["Body"].read() == b""


# ---------------------------------------------------------------------------
# upload_file_to_s3
# ---------------------------------------------------------------------------

class TestUploadFileToS3:
    def test_file_uploaded_correctly(self, s3, tmp_path):
        local_file = tmp_path / "data.json"
        local_file.write_bytes(b'{"x": 1}')
        upload_file_to_s3(local_file, BUCKET, "uploaded/data.json", REGION)
        response = s3.get_object(Bucket=BUCKET, Key="uploaded/data.json")
        assert response["Body"].read() == b'{"x": 1}'

    def test_raises_when_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            upload_file_to_s3(tmp_path / "missing.json", BUCKET, "key", REGION)

    def test_accepts_string_path(self, s3, tmp_path):
        local_file = tmp_path / "str_path.json"
        local_file.write_bytes(b"data")
        upload_file_to_s3(str(local_file), BUCKET, "str/path.json", REGION)
        assert s3_object_exists(BUCKET, "str/path.json", REGION) is True


# ---------------------------------------------------------------------------
# s3_download_with_retry
# ---------------------------------------------------------------------------

class TestS3DownloadWithRetry:
    def test_returns_bytes_from_client(self):
        mock_client = MagicMock()
        mock_client.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"data bytes"))
        }
        result = s3_download_with_retry(BUCKET, "some/key.bin", mock_client)
        mock_client.get_object.assert_called_once_with(Bucket=BUCKET, Key="some/key.bin")
        assert result == b"data bytes"

    def test_non_retryable_error_propagates_immediately(self):
        mock_client = MagicMock()
        mock_client.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "Not found"}}, "GetObject"
        )
        with pytest.raises(ClientError) as exc_info:
            s3_download_with_retry(BUCKET, "missing/key.bin", mock_client)
        assert exc_info.value.response["Error"]["Code"] == "NoSuchKey"
        # retry=retry_if_exception(_is_retryable) → NoSuchKey is NOT retryable → single attempt
        assert mock_client.get_object.call_count == 1
