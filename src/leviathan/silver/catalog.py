"""Deterministic Glue-catalog normalization + hashing (shared by SILVER-F012 and SILVER-F013).

The migration tool (F012) and the partition publisher (F013) both have to answer "did the managed
part of this Glue object change?" without being fooled by AWS-generated dictionary noise
(``transient_lastDdlTime``, ``CreationTime``, ``VersionId``, empty ``Skewed*`` scaffolding,
``serialization.format`` defaults, ...). This module pins ONE normalization of the fields we
actually manage:

  * table:      columns (ordered name+type), partition keys (ordered), location, input/output
                format, SerDe library, table_type, and the *managed* table parameters.
  * partition:  location, columns (ordered), input/output format, SerDe library, and managed SD
                parameters -- exactly the F013 step-2 comparison set.

Everything else is dropped. :func:`hash_table` / :func:`hash_partition` then hash the normalized
form so F012 can compare a desired vs live table by a single ``catalog_hash`` and refuse an apply if
the live hash drifted after the plan was cut. Pure + AWS-free; deterministic JSON (sorted keys).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

# AWS-generated parameters that are noise for change detection (never operator intent).
_NOISE_TABLE_PARAMS = frozenset(
    {
        "transient_lastDdlTime",
        "last_modified_time",
        "last_modified_by",
        "CrawlerSchemaDeserializerVersion",
        "CrawlerSchemaSerializerVersion",
        "UPDATED_BY_CRAWLER",
        "averageRecordSize",
        "recordCount",
        "sizeKey",
        "objectCount",
        "numFiles",
        "numRows",
        "rawDataSize",
        "totalSize",
        "COLUMN_STATS_ACCURATE",
    }
)
_NOISE_SERDE_PARAMS = frozenset({"serialization.format"})


def _cols(columns: Optional[list[dict]]) -> list[dict]:
    """Ordered [{name, type}] -- ORDER IS SIGNIFICANT (a reordering is a real Glue change)."""
    out = []
    for c in columns or []:
        out.append({"name": c.get("Name", c.get("name")), "type": (c.get("Type", c.get("type")) or "").lower()})
    return out


def _clean_params(params: Optional[dict], noise: frozenset) -> dict:
    return {k: v for k, v in (params or {}).items() if k not in noise}


def _normalize_location(location: Optional[str]) -> str:
    """Trailing-slash-insensitive location compare (Glue stores ``.../as_of=X`` and ``.../as_of=X/``
    interchangeably for the same partition)."""
    return (location or "").rstrip("/")


def normalize_storage_descriptor(sd: Optional[dict]) -> dict:
    """The managed subset of a StorageDescriptor (F013 step-2 comparison set)."""
    sd = sd or {}
    serde = sd.get("SerdeInfo") or {}
    return {
        "location": _normalize_location(sd.get("Location")),
        "columns": _cols(sd.get("Columns")),
        "input_format": sd.get("InputFormat"),
        "output_format": sd.get("OutputFormat"),
        "serde_library": serde.get("SerializationLibrary"),
        "serde_params": _clean_params(serde.get("Parameters"), _NOISE_SERDE_PARAMS),
        "sd_params": _clean_params(sd.get("Parameters"), frozenset()),
    }


def normalize_table(table: dict) -> dict:
    """The managed subset of a Glue ``Table`` (or ``TableInput``). AWS-generated timestamps,
    version ids, owner, and crawler noise are dropped."""
    sd = table.get("StorageDescriptor") or {}
    return {
        "name": table.get("Name"),
        "table_type": table.get("TableType"),
        "storage_descriptor": normalize_storage_descriptor(sd),
        "partition_keys": _cols(table.get("PartitionKeys")),
        "parameters": _clean_params(table.get("Parameters"), _NOISE_TABLE_PARAMS),
    }


def normalize_partition(partition: dict) -> dict:
    """The managed subset of a Glue ``Partition`` (values + managed SD)."""
    return {
        "values": [str(v) for v in (partition.get("Values") or [])],
        "storage_descriptor": normalize_storage_descriptor(partition.get("StorageDescriptor")),
    }


def _digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode("utf-8")).hexdigest()


def hash_storage_descriptor(sd: Optional[dict]) -> str:
    return _digest(normalize_storage_descriptor(sd))


def hash_table(table: dict) -> str:
    """The catalog hash F012 compares desired-vs-live and freezes into a plan."""
    return _digest(normalize_table(table))


def hash_partition(partition: dict) -> str:
    return _digest(normalize_partition(partition))


def diff_storage_descriptor(existing: dict, desired: dict) -> list[str]:
    """Human-readable list of the managed-field differences between two SDs (empty == exact match).
    ``existing``/``desired`` are raw StorageDescriptor dicts; both are normalized first."""
    a, b = normalize_storage_descriptor(existing), normalize_storage_descriptor(desired)
    out: list[str] = []
    for field in ("location", "input_format", "output_format", "serde_library"):
        if a[field] != b[field]:
            out.append(f"{field}: {a[field]!r} != {b[field]!r}")
    if a["columns"] != b["columns"]:
        out.append(f"columns: {a['columns']} != {b['columns']}")
    if a["serde_params"] != b["serde_params"]:
        out.append(f"serde_params: {a['serde_params']} != {b['serde_params']}")
    if a["sd_params"] != b["sd_params"]:
        out.append(f"sd_params: {a['sd_params']} != {b['sd_params']}")
    return out


def diff_partition_managed(existing: dict, desired: dict) -> list[str]:
    """Managed-field differences between two Glue partitions (empty == no managed change).

    ``existing``/``desired`` are raw Glue ``Partition`` dicts. Compares the partition ``Values`` and
    the managed StorageDescriptor subset (the SILVER-F081 recovery-verification set). Used to explain
    a byte-for-byte partition mismatch during a recovery rehearsal."""
    a, b = normalize_partition(existing), normalize_partition(desired)
    out: list[str] = []
    if a["values"] != b["values"]:
        out.append(f"values: {a['values']} != {b['values']}")
    out.extend(diff_storage_descriptor(
        existing.get("StorageDescriptor") or {}, desired.get("StorageDescriptor") or {}
    ))
    return out


def diff_table(existing: dict, desired: dict) -> list[str]:
    """Managed-field differences between two Glue tables (empty == no managed change)."""
    a, b = normalize_table(existing), normalize_table(desired)
    out: list[str] = []
    if a["table_type"] != b["table_type"]:
        out.append(f"table_type: {a['table_type']!r} != {b['table_type']!r}")
    if a["partition_keys"] != b["partition_keys"]:
        out.append(f"partition_keys: {a['partition_keys']} != {b['partition_keys']}")
    out.extend(diff_storage_descriptor(
        existing.get("StorageDescriptor") or {}, desired.get("StorageDescriptor") or {}
    ))
    if a["parameters"] != b["parameters"]:
        out.append(f"parameters: {a['parameters']} != {b['parameters']}")
    return out
