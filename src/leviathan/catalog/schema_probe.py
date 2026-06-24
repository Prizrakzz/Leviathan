"""Bounded Parquet schema probing for registered S3 prefixes."""
from __future__ import annotations

import hashlib
import io
import json
import struct
from dataclasses import dataclass
from typing import Any

import pyarrow.parquet as pq

from leviathan.catalog.registry import DatasetSpec


def arrow_to_athena(value: str) -> str:
    value = value.lower()
    if value.startswith("timestamp"):
        return "timestamp"
    aliases = {
        "large_string": "string",
        "string": "string",
        "bool": "boolean",
        "double": "double",
        "float": "float",
        "int64": "bigint",
        "int32": "int",
        "int16": "smallint",
        "int8": "tinyint",
        "date32[day]": "date",
    }
    return aliases.get(value, value)


@dataclass(frozen=True)
class PrefixProbe:
    prefix: str
    object_count_seen: int
    sampled_files: tuple[str, ...]
    schema_hashes: tuple[str, ...]
    schemas: tuple[tuple[tuple[str, str], ...], ...]


def _read_parquet_schema(s3, *, bucket: str, key: str):
    footer = s3.get_object(
        Bucket=bucket,
        Key=key,
        Range="bytes=-8",
    )["Body"].read()
    if len(footer) != 8 or footer[-4:] != b"PAR1":
        raise ValueError(f"{key}: invalid Parquet footer")
    metadata_length = struct.unpack("<I", footer[:4])[0]
    metadata = s3.get_object(
        Bucket=bucket,
        Key=key,
        Range=f"bytes=-{metadata_length + 8}",
    )["Body"].read()
    return pq.read_schema(io.BytesIO(metadata))


def probe_prefix(
    s3,
    *,
    bucket: str,
    prefix: str,
    max_files: int = 3,
) -> PrefixProbe:
    keys: list[str] = []
    object_count = 0
    pending = [prefix]
    visited: set[str] = set()
    paginator = s3.get_paginator("list_objects_v2")
    while pending and len(keys) < max_files:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        children: list[str] = []
        for page in paginator.paginate(
            Bucket=bucket,
            Prefix=current,
            Delimiter="/",
            PaginationConfig={"MaxItems": 1000},
        ):
            for item in page.get("Contents", []):
                object_count += 1
                if (
                    len(keys) < max_files
                    and item["Key"].endswith(".parquet")
                    and item["Size"] > 0
                ):
                    keys.append(item["Key"])
            children.extend(
                item["Prefix"]
                for item in page.get("CommonPrefixes", [])
                if not item["Prefix"].rstrip("/").split("/")[-1].startswith("_")
            )
            if len(keys) >= max_files:
                break
        pending.extend(sorted(children, reverse=True))

    schemas_by_hash: dict[str, tuple[tuple[str, str], ...]] = {}
    for key in keys:
        schema = _read_parquet_schema(s3, bucket=bucket, key=key)
        values = tuple(
            (field.name, arrow_to_athena(str(field.type))) for field in schema
        )
        digest = hashlib.sha256(
            json.dumps(values, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        schemas_by_hash[digest] = values
    return PrefixProbe(
        prefix=prefix,
        object_count_seen=object_count,
        sampled_files=tuple(keys),
        schema_hashes=tuple(sorted(schemas_by_hash)),
        schemas=tuple(schemas_by_hash[key] for key in sorted(schemas_by_hash)),
    )


def schema_mismatches(dataset: DatasetSpec, probe: PrefixProbe) -> list[dict[str, Any]]:
    expected_columns = dataset.ddl_columns
    expected = tuple((column.name, column.type.lower()) for column in expected_columns)
    partition_names = set(dataset.partition_names)
    mismatches: list[dict[str, Any]] = []
    for schema in probe.schemas:
        actual = tuple(item for item in schema if item[0] not in partition_names)
        compatible = len(actual) == len(expected) and all(
            actual_name == expected_name
            and (
                actual_type == expected_type
                or (actual_type == "null" and expected_column.nullable)
            )
            for (actual_name, actual_type), (expected_name, expected_type), expected_column
            in zip(actual, expected, expected_columns)
        )
        if not compatible:
            mismatches.append({"expected": expected, "actual": actual})
    return mismatches
