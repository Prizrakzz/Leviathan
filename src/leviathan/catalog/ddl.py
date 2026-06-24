"""Deterministic Athena DDL rendering from the dataset registry."""
from __future__ import annotations

import hashlib
from pathlib import Path

from leviathan.catalog.registry import DatasetRegistry, DatasetSpec


def _quote(value: str) -> str:
    return value.replace("'", "''")


def render_ddl(dataset: DatasetSpec, bucket: str, registry_sha256: str) -> str:
    columns = dataset.ddl_columns
    width = max(len(column.name) for column in columns)
    column_sql = ",\n".join(
        f"    {f'`{column.name}`'.ljust(width + 2)} {column.type.upper()}"
        for column in columns
    )
    lines = [
        "-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.",
        f"-- dataset_id={dataset.dataset_id}",
        f"-- registry_sha256={registry_sha256}",
        f"CREATE EXTERNAL TABLE IF NOT EXISTS `{dataset.athena.database}`."
        f"`{dataset.athena.table}` (",
        column_sql,
        ")",
    ]
    if dataset.partitions:
        partition_sql = ", ".join(
            f"`{partition.name}` {partition.type.upper()}"
            for partition in dataset.partitions
        )
        lines.append(f"PARTITIONED BY ({partition_sql})")
    if dataset.athena.serde:
        lines.append(f"ROW FORMAT SERDE '{_quote(dataset.athena.serde)}'")
    if dataset.athena.input_format:
        lines.append(
            f"STORED AS INPUTFORMAT '{_quote(dataset.athena.input_format)}'"
        )
        if not dataset.athena.output_format:
            raise ValueError(
                f"{dataset.dataset_id}: output_format required with input_format"
            )
        lines.append(f"OUTPUTFORMAT '{_quote(dataset.athena.output_format)}'")
    else:
        lines.append(f"STORED AS {dataset.file_format}")
    lines.append(f"LOCATION 's3://{bucket}/{dataset.athena.location}'")

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
    if properties:
        body = ",\n".join(
            f"    '{_quote(key)}' = '{_quote(value)}'"
            for key, value in sorted(properties.items())
        )
        lines.extend(["TBLPROPERTIES (", body, ")"])
    return "\n".join(lines) + ";\n"


def ddl_sha256(ddl: str) -> str:
    return hashlib.sha256(ddl.encode("utf-8")).hexdigest()


def render_registry_ddls(registry: DatasetRegistry) -> dict[str, str]:
    return {
        dataset.athena.table: render_ddl(
            dataset,
            registry.bucket,
            registry.content_sha256,
        )
        for dataset in registry.datasets
    }


def write_registry_ddls(
    registry: DatasetRegistry,
    output_dir: str | Path,
) -> list[Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    rendered = render_registry_ddls(registry)
    paths: list[Path] = []
    expected = {f"{table}.sql" for table in rendered}
    for stale in target.glob("*.sql"):
        if stale.name not in expected:
            stale.unlink()
    for table, ddl in sorted(rendered.items()):
        path = target / f"{table}.sql"
        path.write_text(ddl, encoding="utf-8", newline="\n")
        paths.append(path)
    return paths
