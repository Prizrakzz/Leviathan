"""Authoritative structured-dataset registry for the Leviathan data lake."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_PATH = (
    Path(__file__).resolve().parents[3] / "configs" / "datasets" / "datasets.yaml"
)
_VALID_LAYERS = {"metadata", "silver", "gold", "graphrag"}
_VALID_ROLES = {"feature_source", "label_source", "narrative", "diagnostic", "metadata"}
_VALID_STATUSES = {
    "active",
    "blocked_pending_phase2",
    "diagnostic_only",
    "empty_pending_backfill",
}
_VALID_FORMATS = {"PARQUET", "JSON", "JSONL"}
_VALID_TYPES = {
    "boolean",
    "tinyint",
    "smallint",
    "int",
    "bigint",
    "float",
    "double",
    "decimal",
    "string",
    "date",
    "timestamp",
}


class DatasetRegistryError(ValueError):
    """The checked-in dataset registry is internally inconsistent."""


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    type: str
    nullable: bool = True


@dataclass(frozen=True)
class PartitionSpec:
    name: str
    type: str
    projection: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AthenaSpec:
    table: str
    database: str
    location: str
    storage_template: str | None
    properties: dict[str, str]
    smoke_query: str
    serde: str | None
    input_format: str | None
    output_format: str | None


@dataclass(frozen=True)
class DatasetSpec:
    dataset_id: str
    layer: str
    role: str
    status: str
    s3_prefix: str
    file_format: str
    schema: tuple[ColumnSpec, ...]
    natural_key: tuple[str, ...]
    partitions: tuple[PartitionSpec, ...]
    owner_transform: str | None
    owner_task: str | None
    primary_timestamps: tuple[str, ...]
    freshness_days: int | None
    historical_start: str | None
    historical_end: str | None
    core_fundamental: bool
    athena: AthenaSpec
    notes: str | None = None

    @property
    def schema_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.schema)

    @property
    def partition_names(self) -> tuple[str, ...]:
        return tuple(partition.name for partition in self.partitions)

    @property
    def ddl_columns(self) -> tuple[ColumnSpec, ...]:
        partition_names = set(self.partition_names)
        return tuple(column for column in self.schema if column.name not in partition_names)


@dataclass(frozen=True)
class DatasetRegistry:
    schema_version: int
    bucket: str
    database: str
    datasets: tuple[DatasetSpec, ...]
    retired_tables: tuple[str, ...]
    content_sha256: str

    def by_id(self) -> dict[str, DatasetSpec]:
        return {dataset.dataset_id: dataset for dataset in self.datasets}

    def by_table(self) -> dict[str, DatasetSpec]:
        return {dataset.athena.table: dataset for dataset in self.datasets}


def _canonical_sha256(raw: Any) -> str:
    body = json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _normalise_prefix(value: str, field_name: str) -> str:
    value = str(value).strip().lstrip("/")
    if value.startswith("s3://"):
        raise DatasetRegistryError(f"{field_name} must be bucket-relative, got {value!r}")
    if ".." in value.split("/"):
        raise DatasetRegistryError(f"{field_name} contains a parent traversal: {value!r}")
    if value.endswith("="):
        return value
    return value.rstrip("/") + "/"


def _normalise_type(value: str, context: str) -> str:
    value = str(value).lower().strip()
    base = value.split("(", 1)[0]
    if base not in _VALID_TYPES:
        raise DatasetRegistryError(f"{context}: unsupported Athena type {value!r}")
    return value


def _normalise_projection(raw: Any, context: str) -> dict[str, str]:
    projection = raw or {}
    if not isinstance(projection, dict):
        raise DatasetRegistryError(f"{context}: projection must be a mapping")
    allowed = {
        "type",
        "values",
        "range",
        "format",
        "digits",
        "interval",
        "interval.unit",
    }
    unknown = set(projection) - allowed
    if unknown:
        raise DatasetRegistryError(
            f"{context}: unsupported projection keys: {sorted(unknown)}"
        )
    if any(value is None or isinstance(value, (dict, list)) for value in projection.values()):
        raise DatasetRegistryError(f"{context}: projection values must be scalar")
    return {
        str(key): (
            "".join(str(value).split())
            if str(key) in {"values", "range"}
            else str(value)
        )
        for key, value in projection.items()
    }


def _parse_dataset(raw: dict[str, Any], defaults: dict[str, Any]) -> DatasetSpec:
    dataset_id = str(raw.get("dataset_id", "")).strip()
    if not dataset_id:
        raise DatasetRegistryError("dataset is missing dataset_id")

    schema = tuple(
        ColumnSpec(
            name=str(column["name"]),
            type=_normalise_type(column["type"], f"{dataset_id}.schema"),
            nullable=bool(column.get("nullable", True)),
        )
        for column in raw.get("schema", [])
    )
    if not schema:
        raise DatasetRegistryError(f"{dataset_id}: schema must not be empty")
    if len({column.name for column in schema}) != len(schema):
        raise DatasetRegistryError(f"{dataset_id}: duplicate schema columns")

    partitions = tuple(
        PartitionSpec(
            name=str(partition["name"]),
            type=_normalise_type(partition["type"], f"{dataset_id}.partitions"),
            projection=_normalise_projection(
                partition.get("projection"),
                f"{dataset_id}.partitions.{partition['name']}",
            ),
        )
        for partition in raw.get("partitions", [])
    )
    if len({partition.name for partition in partitions}) != len(partitions):
        raise DatasetRegistryError(f"{dataset_id}: duplicate partition columns")

    schema_names = {column.name for column in schema}
    natural_key = tuple(str(value) for value in raw.get("natural_key", []))
    unknown_key = set(natural_key) - schema_names
    if unknown_key:
        raise DatasetRegistryError(
            f"{dataset_id}: natural_key columns absent from schema: {sorted(unknown_key)}"
        )
    unknown_partitions = {part.name for part in partitions} - schema_names
    if unknown_partitions:
        raise DatasetRegistryError(
            f"{dataset_id}: partition columns absent from schema: "
            f"{sorted(unknown_partitions)}"
        )

    layer = str(raw.get("layer", "")).strip()
    role = str(raw.get("role", "")).strip()
    status = str(raw.get("status", "active")).strip()
    file_format = str(raw.get("format", "PARQUET")).upper()
    if layer not in _VALID_LAYERS:
        raise DatasetRegistryError(f"{dataset_id}: invalid layer {layer!r}")
    if role not in _VALID_ROLES:
        raise DatasetRegistryError(f"{dataset_id}: invalid role {role!r}")
    if status not in _VALID_STATUSES:
        raise DatasetRegistryError(f"{dataset_id}: invalid status {status!r}")
    if file_format not in _VALID_FORMATS:
        raise DatasetRegistryError(f"{dataset_id}: invalid format {file_format!r}")

    athena_raw = raw.get("athena") or {}
    table = str(athena_raw.get("table", dataset_id)).strip()
    database = str(athena_raw.get("database", defaults["database"])).strip()
    location = _normalise_prefix(
        athena_raw.get("location", raw["s3_prefix"]),
        f"{dataset_id}.athena.location",
    )
    storage_template = athena_raw.get("storage_template")
    if storage_template is not None:
        storage_template = "".join(str(storage_template).split()).lstrip("/")

    smoke_query = str(
        athena_raw.get(
            "smoke_query",
            f'SELECT * FROM "{database}"."{table}" LIMIT 1',
        )
    )
    if ";" in smoke_query.rstrip(";"):
        raise DatasetRegistryError(f"{dataset_id}: smoke_query must be one statement")

    owner = raw.get("owner") or {}
    timestamps = raw.get("timestamps") or {}
    historical = raw.get("historical_range") or {}
    return DatasetSpec(
        dataset_id=dataset_id,
        layer=layer,
        role=role,
        status=status,
        s3_prefix=_normalise_prefix(raw["s3_prefix"], f"{dataset_id}.s3_prefix"),
        file_format=file_format,
        schema=schema,
        natural_key=natural_key,
        partitions=partitions,
        owner_transform=owner.get("transform"),
        owner_task=owner.get("task"),
        primary_timestamps=tuple(str(value) for value in timestamps.get("primary", [])),
        freshness_days=(
            None if raw.get("freshness_days") is None else int(raw["freshness_days"])
        ),
        historical_start=historical.get("start"),
        historical_end=historical.get("end"),
        core_fundamental=bool(raw.get("core_fundamental", False)),
        athena=AthenaSpec(
            table=table,
            database=database,
            location=location,
            storage_template=storage_template,
            properties={
                str(key): str(value)
                for key, value in (athena_raw.get("properties") or {}).items()
            },
            smoke_query=smoke_query,
            serde=athena_raw.get("serde"),
            input_format=athena_raw.get("input_format"),
            output_format=athena_raw.get("output_format"),
        ),
        notes=raw.get("notes"),
    )


def load_dataset_registry(path: str | Path | None = None) -> DatasetRegistry:
    registry_path = Path(path) if path is not None else _DEFAULT_PATH
    text = registry_path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text) or {}
    defaults = {
        "database": str(raw.get("database", "leviathan_dev")),
    }
    datasets = tuple(_parse_dataset(item, defaults) for item in raw.get("datasets", []))
    if not datasets:
        raise DatasetRegistryError("registry contains no datasets")

    ids = [dataset.dataset_id for dataset in datasets]
    tables = [dataset.athena.table for dataset in datasets]
    if len(set(ids)) != len(ids):
        raise DatasetRegistryError("registry contains duplicate dataset_id values")
    if len(set(tables)) != len(tables):
        raise DatasetRegistryError("registry contains duplicate Athena table values")

    table_set = set(tables)
    retired_tables = tuple(str(value) for value in raw.get("retired_tables", []))
    collision = table_set & set(retired_tables)
    if collision:
        raise DatasetRegistryError(
            f"active and retired table sets overlap: {sorted(collision)}"
        )

    # Parent/child prefixes are valid only when their Athena locations are
    # disjoint through partition projection or the parent is explicitly a
    # metadata dataset. Exact duplicate physical prefixes are never valid.
    prefixes: dict[str, str] = {}
    for dataset in datasets:
        previous = prefixes.get(dataset.s3_prefix)
        if previous:
            raise DatasetRegistryError(
                f"{dataset.dataset_id} and {previous} share s3_prefix "
                f"{dataset.s3_prefix!r}"
            )
        prefixes[dataset.s3_prefix] = dataset.dataset_id

    return DatasetRegistry(
        schema_version=int(raw.get("schema_version", 1)),
        bucket=str(raw["bucket"]),
        database=defaults["database"],
        datasets=tuple(sorted(datasets, key=lambda item: item.dataset_id)),
        retired_tables=tuple(sorted(retired_tables)),
        content_sha256=_canonical_sha256(raw),
    )
