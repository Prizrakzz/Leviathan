"""Glue partition registration for REGISTERED-partition silver tables (the post-projection contract).

Since 2026-07 the sparse serving tables (silver_wasde, silver_esr, silver_model_predictions) use REGISTERED
Glue partitions instead of partition projection — projection's enumerated grids (esr: ~6M candidates over
370 real dirs) caused the Jul-2026 S3 LIST storm ($134/2 days; any non-sargable query re-fired it).
Registered partitions prune catalog-side for ANY query shape.

THE CONTRACT THIS MODULE ENFORCES: a writer that creates a NEW partition directory in S3 MUST register it
here in the same run — an unregistered partition is invisible to Athena (silently missing data, worse than
the storm). `ensure_partition` is idempotent (AlreadyExists is success), so writers call it unconditionally
after their S3 write. `jobs/utils/deproject_glue_table.py` re-runs as a catch-up sync if a writer ever
misses.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_GLUE = None


def _glue():
    global _GLUE
    if _GLUE is None:
        import boto3
        _GLUE = boto3.client("glue", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return _GLUE


def _partition_input(table_sd: dict, values: list[str], location: str) -> dict:
    sd = dict(table_sd)
    sd["Location"] = location
    # partition SDs must not carry table-level keys Glue rejects on partitions
    sd.pop("SortColumns", None)
    return {"Values": [str(v) for v in values], "StorageDescriptor": sd}


def table_sd(database: str, table: str) -> dict:
    return _glue().get_table(DatabaseName=database, Name=table)["Table"]["StorageDescriptor"]


def ensure_partition(database: str, table: str, values: list[str], location: str,
                     sd: Optional[dict] = None) -> bool:
    """Idempotently register one partition. Returns True if newly created, False if it already existed.
    Raises only on real failures (permissions, bad schema) — callers treat those as pipeline errors, not
    something to swallow: an unregistered partition means invisible data."""
    sd = sd or table_sd(database, table)
    try:
        _glue().create_partition(DatabaseName=database, TableName=table,
                                 PartitionInput=_partition_input(sd, values, location))
        logger.info("registered partition %s.%s %s -> %s", database, table, values, location)
        return True
    except _glue().exceptions.AlreadyExistsException:
        return False


def batch_ensure(database: str, table: str, parts: list[tuple[list[str], str]],
                 sd: Optional[dict] = None, batch: int = 100) -> tuple[int, int]:
    """Register many (values, location) partitions via batch_create_partition. Returns (created, existed).
    AlreadyExists errors inside a batch are counted as existing; any other per-partition error raises."""
    sd = sd or table_sd(database, table)
    created = existed = 0
    for lo in range(0, len(parts), batch):
        chunk = parts[lo:lo + batch]
        resp = _glue().batch_create_partition(
            DatabaseName=database, TableName=table,
            PartitionInputList=[_partition_input(sd, v, loc) for v, loc in chunk])
        errs = resp.get("Errors") or []
        hard = [e for e in errs if (e.get("ErrorDetail") or {}).get("ErrorCode") != "AlreadyExistsException"]
        if hard:
            raise RuntimeError(f"batch_create_partition failures on {table}: {hard[:3]}")
        existed += len(errs)
        created += len(chunk) - len(errs)
    return created, existed
