"""Deterministic loader + validator for the silver operational registry (SILVER-F010, R1).

The registry (``configs/silver/tables/<table>.yaml`` validated against
``configs/silver/table_contract.schema.json``) is the SUPERSET authority for the 42 live silver
tables + ``gold_weather_z``: identity, the explicit INV-2 writer schema, ``value_columns`` /
``min_nonnull_frac`` (the single V001/V002 authority, Attack 3 finding #6), vintage/PIT semantics,
consumers, producer entrypoints, and back-pointers into the numbers/cascade/source-contract/
features consumer configs (reconciled by :mod:`leviathan.silver.reconcile`).

This module is READ-ONLY and AWS-free. It ships a small self-contained JSON-Schema *subset*
validator so the loader has zero new runtime dependency (``jsonschema`` is not in the project
env). The subset covers exactly the keywords ``table_contract.schema.json`` uses.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from leviathan.silver.types import is_narrowing_change

# ---------------------------------------------------------------------------
# Repo locations (resolved relative to this file; no CWD dependence).
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIGS_SILVER_DIR = _REPO_ROOT / "configs" / "silver"
SCHEMA_PATH = CONFIGS_SILVER_DIR / "table_contract.schema.json"
TABLES_DIR = CONFIGS_SILVER_DIR / "tables"
KNOWN_DRIFT_PATH = CONFIGS_SILVER_DIR / "known_drift.yaml"

# Approved canonical roots (mirrors publish_guard.PROD_ENVIRONMENT; no AWS call). A registry
# s3_root MUST live under one of these -- an "unsafe root" is a hard load error.
APPROVED_BUCKET = "leviathan-dev-shahem-001"
APPROVED_PREFIXES = ("silver/", "gold/")


# ---------------------------------------------------------------------------
# Self-contained JSON-Schema subset validator.
# ---------------------------------------------------------------------------
_PY_TYPE = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def _type_ok(value: Any, t: str) -> bool:
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, _PY_TYPE[t])


def _validate(instance: Any, schema: dict, path: str, errors: list[str]) -> None:
    # type
    if "type" in schema:
        types = schema["type"]
        types = [types] if isinstance(types, str) else list(types)
        if not any(_type_ok(instance, t) for t in types):
            errors.append(f"{path}: expected type {types}, got {type(instance).__name__}")
            return  # further keyword checks are unreliable on a type mismatch
    # enum
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum {schema['enum']}")
    # numeric bounds (only when actually a number)
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: {instance} < minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: {instance} > maximum {schema['maximum']}")
    # string length
    if isinstance(instance, str) and "minLength" in schema and len(instance) < schema["minLength"]:
        errors.append(f"{path}: string shorter than minLength {schema['minLength']}")
    # object
    if isinstance(instance, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in instance:
                errors.append(f"{path}: missing required property '{req}'")
        addl = schema.get("additionalProperties", True)
        pat_props = schema.get("patternProperties", {})
        for key, val in instance.items():
            if key in props:
                _validate(val, props[key], f"{path}.{key}", errors)
                continue
            pat = next((p for p in pat_props if re.search(p, key)), None)
            if pat is not None:
                _validate(val, pat_props[pat], f"{path}.{key}", errors)
            elif addl is False:
                errors.append(f"{path}: additional property '{key}' not permitted")
    # array
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: fewer than minItems {schema['minItems']}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(instance):
                _validate(item, item_schema, f"{path}[{i}]", errors)


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_contract(contract: dict, schema: Optional[dict] = None) -> list[str]:
    """Return a (possibly empty) list of human-readable schema violations for one contract."""
    schema = schema if schema is not None else load_schema()
    errors: list[str] = []
    _validate(contract, schema, contract.get("table_name", "<contract>"), errors)
    return errors


# ---------------------------------------------------------------------------
# Registry model.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SilverRegistry:
    """The loaded, validated registry keyed by table_name."""

    tables: dict[str, dict]
    schema: dict = field(repr=False, default_factory=dict)

    def names(self) -> list[str]:
        return sorted(self.tables)

    def table(self, name: str) -> dict:
        return self.tables[name]

    def value_columns(self, name: str) -> list[str]:
        return list(self.tables[name].get("value_columns", []))

    def min_nonnull_frac(self, name: str) -> Optional[float]:
        return self.tables[name].get("min_nonnull_frac")

    def columns(self, name: str) -> set[str]:
        """All column names known for a table: physical columns + partition keys."""
        c = self.tables[name]
        cols = {col["name"] for col in c.get("physical_columns", [])}
        cols |= {pk["name"] for pk in c.get("partition_keys", [])}
        return cols


def _column_names(contract: dict) -> list[str]:
    return [col["name"] for col in contract.get("physical_columns", [])]


def load_registry(tables_dir: Optional[Path] = None, *, strict: bool = True) -> SilverRegistry:
    """Load + validate every ``<table>.yaml`` under ``tables_dir``.

    Runs schema validation plus the structural lints (duplicate table, duplicate column, unsafe
    root, missing ownership, incomplete producer metadata). Raises :class:`RegistryError` on the
    first class of problem when ``strict`` (default); returns the registry regardless of ``strict``
    only if there are no errors."""
    tables_dir = tables_dir or TABLES_DIR
    schema = load_schema()
    tables: dict[str, dict] = {}
    problems: list[str] = []

    for yaml_path in sorted(tables_dir.glob("*.yaml")):
        contract = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        if not isinstance(contract, dict):
            problems.append(f"{yaml_path.name}: not a YAML mapping")
            continue
        name = contract.get("table_name")
        # schema
        for err in validate_contract(contract, schema):
            problems.append(f"{yaml_path.name}: schema: {err}")
        # filename must match table_name
        if name and yaml_path.stem != name:
            problems.append(f"{yaml_path.name}: filename stem != table_name '{name}'")
        # duplicate table
        if name in tables:
            problems.append(f"{yaml_path.name}: duplicate table_name '{name}'")
        # structural lints
        problems.extend(_structural_lints(contract, yaml_path.name))
        if name:
            tables[name] = contract

    if problems and strict:
        raise RegistryError(
            f"{len(problems)} registry problem(s):\n  - " + "\n  - ".join(problems)
        )
    if problems:
        raise RegistryError("\n".join(problems))
    return SilverRegistry(tables=tables, schema=schema)


def _structural_lints(contract: dict, label: str) -> list[str]:
    out: list[str] = []
    # duplicate columns within the table
    names = _column_names(contract)
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        out.append(f"{label}: duplicate physical column(s) {sorted(dupes)}")
    pk_names = [pk["name"] for pk in contract.get("partition_keys", [])]
    overlap = set(names) & set(pk_names)
    if overlap:
        out.append(f"{label}: column(s) declared as BOTH physical and partition key {sorted(overlap)}")
    # unsafe root
    root = contract.get("s3_root", "")
    if not _is_safe_root(root):
        out.append(f"{label}: unsafe s3_root {root!r} (not under {APPROVED_BUCKET}/{APPROVED_PREFIXES})")
    # missing ownership
    if not contract.get("owner"):
        out.append(f"{label}: missing owner")
    # incomplete producer metadata
    prod = contract.get("producer") or {}
    status = prod.get("status")
    if status == "producer" and not (prod.get("transform") or prod.get("batch_task")):
        out.append(f"{label}: producer.status=producer but no transform/batch_task entrypoint")
    # value / min_nonnull_frac coherence (INV-5 single authority)
    vcs = contract.get("value_columns", [])
    frac = contract.get("min_nonnull_frac")
    if vcs and frac is None:
        out.append(f"{label}: value_columns set but min_nonnull_frac is null")
    if not vcs and frac is not None:
        out.append(f"{label}: min_nonnull_frac set but value_columns empty")
    for vc in vcs:
        if vc not in set(names) | set(pk_names):
            out.append(f"{label}: value_column '{vc}' is not a declared column")
    # OP-8 per-column floor calibration: overrides must target declared value_columns and stay
    # fractions; an override without a base floor has nothing to calibrate against.
    overrides = contract.get("min_nonnull_frac_overrides") or {}
    for oc, ofl in overrides.items():
        if oc not in vcs:
            out.append(f"{label}: min_nonnull_frac_overrides key '{oc}' is not a value_column")
        if not isinstance(ofl, (int, float)) or isinstance(ofl, bool) or not (0 <= float(ofl) <= 1):
            out.append(f"{label}: min_nonnull_frac_overrides['{oc}'] must be a fraction in [0,1]")
    if overrides and frac is None:
        out.append(f"{label}: min_nonnull_frac_overrides set but min_nonnull_frac is null")
    return out


def _is_safe_root(root: str) -> bool:
    m = re.match(r"^s3://([^/]+)/(.+)$", root or "")
    if not m:
        return False
    bucket, key = m.group(1), m.group(2)
    if bucket != APPROVED_BUCKET:
        return False
    return any(key.startswith(p) for p in APPROVED_PREFIXES)


def check_illegal_type_change(old_contract: dict, new_contract: dict) -> list[str]:
    """Return violations where a column's INV-2 target type narrows/changes base between two
    versions of the same table's contract (registry edits must not silently narrow a type)."""
    out: list[str] = []
    old_by = {c["name"]: c for c in old_contract.get("physical_columns", [])}
    for col in new_contract.get("physical_columns", []):
        prev = old_by.get(col["name"])
        if not prev:
            continue
        ot, nt = prev.get("target_arrow_type", ""), col.get("target_arrow_type", "")
        if is_narrowing_change(ot, nt):
            out.append(f"{new_contract.get('table_name')}.{col['name']}: illegal type change {ot} -> {nt}")
    return out


class RegistryError(RuntimeError):
    """Raised when the registry fails schema validation or a structural lint."""


def load_known_drift(path: Optional[Path] = None) -> dict:
    """Load the reconciliation known-drift allowlist (each entry tied to an owning R2 package)."""
    path = path or KNOWN_DRIFT_PATH
    if not path.exists():
        return {"reconciliation_drift": []}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {"reconciliation_drift": []}
