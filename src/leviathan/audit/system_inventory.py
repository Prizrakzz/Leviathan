"""Pure helpers for deterministic system inventory snapshots."""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Iterable

from leviathan.ops.ml_platform import canonical_sha256


def stable_sort_records(
    records: Iterable[dict[str, Any]],
    keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Sort records deterministically while treating missing values as empty."""
    return sorted(
        (dict(record) for record in records),
        key=lambda record: tuple(str(record.get(key, "")) for key in keys),
    )


def normalize_inventory(content: dict[str, Any]) -> dict[str, Any]:
    """Normalize known inventory sections before hashing or serialization."""
    normalized = dict(content)
    section_keys: dict[str, tuple[str, ...]] = {
        "s3_root_prefixes": ("prefix",),
        "s3_datasets": ("layer", "prefix"),
        "glue_tables": ("database", "name"),
        "batch_job_definitions": ("name", "revision"),
        "ecr_images": ("repository", "pushed_at", "digest"),
        "ec2_instances": ("instance_id",),
        "ebs_volumes": ("volume_id",),
    }
    for section, keys in section_keys.items():
        if section in normalized:
            normalized[section] = stable_sort_records(normalized[section], keys)
    return normalized


def inventory_content_sha256(content: dict[str, Any]) -> str:
    logical_content = deepcopy(normalize_inventory(content))
    for metric in logical_content.get("s3_bucket_metrics", {}).values():
        if isinstance(metric, dict):
            metric.pop("timestamp", None)
    return canonical_sha256(logical_content)


def json_document(
    *,
    run_id: str,
    generated_at: str,
    content: dict[str, Any],
) -> dict[str, Any]:
    normalized = normalize_inventory(content)
    return {
        "schema_version": 1,
        "run_id": run_id,
        "generated_at": generated_at,
        "logical_content_sha256": inventory_content_sha256(normalized),
        "content": normalized,
    }


def parquet_rows(content: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten dataset records for the companion Parquet inventory."""
    rows: list[dict[str, Any]] = []
    for record in normalize_inventory(content).get("s3_datasets", []):
        row = dict(record)
        for key, value in list(row.items()):
            if isinstance(value, (list, dict, tuple)):
                row[key] = json.dumps(value, sort_keys=True, default=str)
        rows.append(row)
    return rows
