"""Tests for ML platform backup, restore, and manifest helpers."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from leviathan.ops.ml_platform import (
    SERVICE_SPECS,
    backup_keys,
    canonical_sha256,
    parse_s3_uri,
    utc_backup_id,
    validate_backup_manifest,
)
from leviathan.ops.ssm import encoded_python_command


def _manifest(service: str = "mlflow") -> dict:
    return {
        "schema_version": 1,
        "backup_id": "2026-06-23T12-00-00Z",
        "created_at": "2026-06-23T12:00:00+00:00",
        "service": service,
        "instance_id": "i-123",
        "database_path": SERVICE_SPECS[service].database_path,
        "database_size_bytes": 100,
        "database_sha256": "a" * 64,
        "source_integrity_check": "ok",
        "backup_integrity_check": "ok",
        "service_version": "test 1.0",
        "service_status": {unit: "active" for unit in SERVICE_SPECS[service].service_units},
        "table_counts": {"runs": 1},
        "database_s3_uri": f"s3://bucket/{service}.db",
    }


def test_backup_id_and_keys_are_path_safe() -> None:
    backup_id = utc_backup_id(datetime(2026, 6, 23, 12, 34, 56, tzinfo=timezone.utc))
    assert backup_id == "2026-06-23T12-34-56Z"
    keys = backup_keys(SERVICE_SPECS["mlflow"], backup_id)
    assert keys["database"] == f"mlflow/backups/backend/{backup_id}/mlflow.db"
    assert keys["manifest"].endswith("/manifest.json")


def test_validate_backup_manifest_accepts_complete_manifest() -> None:
    validate_backup_manifest(_manifest(), expected_service="mlflow")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_integrity_check", "corrupt", "source SQLite"),
        ("backup_integrity_check", "corrupt", "backup SQLite"),
        ("database_size_bytes", 0, "empty"),
        ("database_sha256", "not-a-sha", "SHA-256"),
    ],
)
def test_validate_backup_manifest_rejects_invalid_values(
    field: str, value, message: str
) -> None:
    manifest = _manifest()
    manifest[field] = value
    with pytest.raises(ValueError, match=message):
        validate_backup_manifest(manifest)


def test_validate_backup_manifest_rejects_wrong_service() -> None:
    with pytest.raises(ValueError, match="service mismatch"):
        validate_backup_manifest(_manifest("airflow"), expected_service="mlflow")


def test_parse_s3_uri() -> None:
    assert parse_s3_uri("s3://bucket/path/to/file") == ("bucket", "path/to/file")
    with pytest.raises(ValueError):
        parse_s3_uri("https://bucket/path")


def test_canonical_hash_is_order_independent() -> None:
    assert canonical_sha256({"b": 2, "a": 1}) == canonical_sha256({"a": 1, "b": 2})


def test_encoded_python_command_does_not_embed_payload_plaintext() -> None:
    command = encoded_python_command("print('ok')", {"secret": "do-not-print"})
    assert "do-not-print" not in command
    assert "base64 -d" in command

