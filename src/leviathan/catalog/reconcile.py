"""Pure catalog diffing and immutable reconciliation-plan helpers."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from leviathan.catalog.ddl import ddl_sha256, render_registry_ddls
from leviathan.catalog.registry import DatasetRegistry, DatasetSpec


def _normalise_type(value: str) -> str:
    value = value.lower().strip()
    aliases = {
        "integer": "int",
        "long": "bigint",
        "bool": "boolean",
        "varchar": "string",
    }
    return aliases.get(value, value)


def _normalise_location(value: str | None) -> str | None:
    return value.rstrip("/") if value else None


def _normalise_properties(properties: dict[str, Any] | None) -> dict[str, str]:
    if not properties:
        return {}
    keep = {
        key: str(value)
        for key, value in properties.items()
        if key.startswith("projection.")
        or key in {
            "projection.enabled",
            "storage.location.template",
        }
    }
    for key, value in tuple(keep.items()):
        if key.endswith(".values"):
            keep[key] = ",".join(sorted(part.strip() for part in value.split(",")))
    return dict(sorted(keep.items()))


def desired_table_signature(dataset: DatasetSpec, bucket: str) -> dict[str, Any]:
    properties = {
        "parquet.compression": "SNAPPY",
        **dataset.athena.properties,
    }
    for partition in dataset.partitions:
        for key, value in partition.projection.items():
            properties[f"projection.{partition.name}.{key}"] = value
    if dataset.partitions and any(partition.projection for partition in dataset.partitions):
        properties["projection.enabled"] = "true"
    if dataset.athena.storage_template:
        properties["storage.location.template"] = (
            f"s3://{bucket}/{dataset.athena.storage_template}"
        )
    return {
        "columns": [
            {"name": column.name, "type": _normalise_type(column.type)}
            for column in dataset.ddl_columns
        ],
        "partitions": [
            {"name": partition.name, "type": _normalise_type(partition.type)}
            for partition in dataset.partitions
        ],
        "location": _normalise_location(
            f"s3://{bucket}/{dataset.athena.location}"
        ),
        "properties": _normalise_properties(properties),
    }


def live_table_signature(table: dict[str, Any]) -> dict[str, Any]:
    descriptor = table.get("StorageDescriptor") or {}
    return {
        "columns": [
            {"name": column["Name"], "type": _normalise_type(column["Type"])}
            for column in descriptor.get("Columns", [])
        ],
        "partitions": [
            {"name": column["Name"], "type": _normalise_type(column["Type"])}
            for column in table.get("PartitionKeys", [])
        ],
        "location": _normalise_location(descriptor.get("Location")),
        "properties": _normalise_properties(table.get("Parameters")),
    }


def signature_differences(
    desired: dict[str, Any],
    live: dict[str, Any],
) -> list[str]:
    return [
        key
        for key in ("columns", "partitions", "location", "properties")
        if desired.get(key) != live.get(key)
    ]


@dataclass(frozen=True)
class CatalogAction:
    table: str
    action: str
    dataset_id: str | None
    reasons: tuple[str, ...]
    ddl_sha256: str | None


def build_catalog_plan(
    registry: DatasetRegistry,
    live_tables: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rendered = render_registry_ddls(registry)
    actions: list[CatalogAction] = []
    for dataset in registry.datasets:
        table = dataset.athena.table
        live = live_tables.get(table)
        if live is None:
            actions.append(
                CatalogAction(
                    table=table,
                    action="create",
                    dataset_id=dataset.dataset_id,
                    reasons=("table_missing",),
                    ddl_sha256=ddl_sha256(rendered[table]),
                )
            )
            continue
        differences = signature_differences(
            desired_table_signature(dataset, registry.bucket),
            live_table_signature(live),
        )
        actions.append(
            CatalogAction(
                table=table,
                action="replace" if differences else "noop",
                dataset_id=dataset.dataset_id,
                reasons=tuple(differences) if differences else (),
                ddl_sha256=ddl_sha256(rendered[table]),
            )
        )

    for table in registry.retired_tables:
        if table in live_tables:
            actions.append(
                CatalogAction(
                    table=table,
                    action="retire",
                    dataset_id=None,
                    reasons=("listed_in_retired_tables",),
                    ddl_sha256=None,
                )
            )

    known = set(registry.by_table()) | set(registry.retired_tables)
    for table in sorted(set(live_tables) - known):
        actions.append(
            CatalogAction(
                table=table,
                action="unmanaged",
                dataset_id=None,
                reasons=("live_table_not_in_registry",),
                ddl_sha256=None,
            )
        )

    body = {
        "schema_version": 1,
        "registry_sha256": registry.content_sha256,
        "database": registry.database,
        "bucket": registry.bucket,
        "actions": [
            {
                "table": action.table,
                "action": action.action,
                "dataset_id": action.dataset_id,
                "reasons": list(action.reasons),
                "ddl_sha256": action.ddl_sha256,
            }
            for action in sorted(actions, key=lambda item: item.table)
        ],
    }
    body["plan_sha256"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return body


def verify_plan_hash(plan: dict[str, Any]) -> bool:
    expected = plan.get("plan_sha256")
    payload = {
        key: value
        for key, value in plan.items()
        if key not in {"plan_sha256", "generated_at"}
    }
    actual = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return bool(expected) and expected == actual
