"""Backup and restore primitives for the SQLite-backed ML platform services."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class ServiceSpec:
    """Configuration for one SQLite-backed service."""

    name: str
    database_path: str
    service_units: tuple[str, ...]
    owner: str
    health_url: str
    version_command: str
    backup_prefix: str


SERVICE_SPECS: dict[str, ServiceSpec] = {
    "mlflow": ServiceSpec(
        name="mlflow",
        database_path="/home/ec2-user/mlflow/mlflow.db",
        service_units=("mlflow",),
        owner="ec2-user:ec2-user",
        health_url="http://localhost:5000/health",
        version_command="/opt/mlflow-venv/bin/mlflow --version",
        backup_prefix="mlflow/backups/backend",
    ),
    "airflow": ServiceSpec(
        name="airflow",
        database_path="/home/ec2-user/airflow/airflow.db",
        service_units=("airflow-webserver", "airflow-scheduler"),
        owner="ec2-user:ec2-user",
        health_url="http://localhost:8080/health",
        version_command="/opt/airflow-venv/bin/airflow version",
        backup_prefix="airflow/backups/backend",
    ),
}


def utc_backup_id(now: datetime | None = None) -> str:
    """Return a filesystem- and S3-safe UTC backup identifier."""
    current = now or datetime.now(timezone.utc)
    return current.astimezone(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def backup_keys(spec: ServiceSpec, backup_id: str) -> dict[str, str]:
    """Return the immutable S3 keys for a service backup."""
    base = f"{spec.backup_prefix}/{backup_id}"
    return {
        "database": f"{base}/{spec.name}.db",
        "manifest": f"{base}/manifest.json",
    }


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_s3_uri(uri: str) -> tuple[str, str]:
    """Split an S3 URI into bucket and key."""
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
        raise ValueError(f"invalid S3 URI: {uri!r}")
    return parsed.netloc, parsed.path.lstrip("/")


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")


def canonical_sha256(payload: Any) -> str:
    return sha256_bytes(canonical_json_bytes(payload))


def validate_backup_manifest(
    manifest: dict[str, Any],
    *,
    expected_service: str | None = None,
) -> None:
    """Raise when a backup manifest is incomplete or internally inconsistent."""
    required = {
        "schema_version",
        "backup_id",
        "created_at",
        "service",
        "instance_id",
        "database_path",
        "database_size_bytes",
        "database_sha256",
        "source_integrity_check",
        "backup_integrity_check",
        "service_version",
        "service_status",
        "table_counts",
        "database_s3_uri",
    }
    missing = sorted(required - set(manifest))
    if missing:
        raise ValueError(f"backup manifest missing fields: {missing}")
    if expected_service and manifest["service"] != expected_service:
        raise ValueError(
            f"backup service mismatch: expected {expected_service!r}, "
            f"got {manifest['service']!r}"
        )
    if manifest["service"] not in SERVICE_SPECS:
        raise ValueError(f"unknown backup service: {manifest['service']!r}")
    if manifest["source_integrity_check"] != "ok":
        raise ValueError("source SQLite integrity check did not return 'ok'")
    if manifest["backup_integrity_check"] != "ok":
        raise ValueError("backup SQLite integrity check did not return 'ok'")
    if int(manifest["database_size_bytes"]) <= 0:
        raise ValueError("backup database is empty")
    digest = str(manifest["database_sha256"])
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError("backup database_sha256 is not a lowercase SHA-256 digest")
    parse_s3_uri(str(manifest["database_s3_uri"]))
    if not isinstance(manifest["table_counts"], dict):
        raise ValueError("backup table_counts must be an object")


def redact_command(command: str) -> str:
    """Return a safe command label for logs without exposing presigned URLs."""
    if "X-Amz-Signature" in command:
        return "<remote command containing presigned URL>"
    return command

