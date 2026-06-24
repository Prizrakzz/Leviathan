"""Source-specific silver certification for experiment readiness.

The catalog tells us what a dataset *should* look like.  Certification answers
whether the current data is safe to feed into gold/model experiments:
natural-key uniqueness, usable date range, null rates, revision availability,
freshness, and source-specific unit/category contracts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from leviathan.catalog.registry import DatasetSpec


class SourceCertificationError(ValueError):
    """Raised when a certification contract is malformed."""


@dataclass(frozen=True)
class SourceContract:
    """Additional source-specific checks not expressible in the catalog schema."""

    dataset_id: str
    expected_units: dict[str, tuple[str, ...]] = field(default_factory=dict)
    expected_categories: dict[str, tuple[str, ...]] = field(default_factory=dict)
    required_nonzero_revision_columns: tuple[str, ...] = ()
    known_limitations: tuple[str, ...] = ()


def load_source_contracts(path: str | Path) -> dict[str, SourceContract]:
    """Load source-level certification contracts keyed by dataset_id."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    contracts: dict[str, SourceContract] = {}
    for item in raw.get("contracts", []):
        dataset_id = str(item["dataset_id"])
        contracts[dataset_id] = SourceContract(
            dataset_id=dataset_id,
            expected_units={
                str(col): tuple(str(value) for value in values)
                for col, values in (item.get("expected_units") or {}).items()
            },
            expected_categories={
                str(col): tuple(str(value) for value in values)
                for col, values in (item.get("expected_categories") or {}).items()
            },
            required_nonzero_revision_columns=tuple(
                str(value)
                for value in item.get("required_nonzero_revision_columns", [])
            ),
            known_limitations=tuple(
                str(value) for value in item.get("known_limitations", [])
            ),
        )
    return contracts


_NUMERIC_TYPES = {
    "tinyint",
    "smallint",
    "int",
    "bigint",
    "float",
    "double",
    "decimal",
}
_NON_VALUE_COLUMNS = {
    "year",
    "month",
    "day",
    "week",
    "week_number",
    "week_of_year",
    "safra_year",
    "survey",
    "survey_number",
    "report_month",
    "report_year",
    "production_year",
    "crop_year",
    "marketing_year",
    "release_year",
    "release_month",
}
_REVISION_TOKENS = ("revision", "delta", "change", "surprise")


def _base_type(type_name: str) -> str:
    return type_name.split("(", 1)[0].lower().strip()


def _to_iso(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return str(value)
    return parsed.date().isoformat()


def _timestamp_columns(dataset: DatasetSpec, df: pd.DataFrame) -> list[str]:
    declared = [col for col in dataset.primary_timestamps if col in df.columns]
    if declared:
        return declared
    fallback = [
        "date",
        "release_date",
        "report_date",
        "week_ending_date",
        "position_date",
        "fortnight_date",
        "year",
    ]
    return [col for col in fallback if col in df.columns]


def _value_columns(dataset: DatasetSpec) -> list[str]:
    key_like = set(dataset.natural_key) | set(dataset.partition_names) | set(dataset.primary_timestamps)
    value_cols: list[str] = []
    for column in dataset.schema:
        if column.name in key_like or column.name in _NON_VALUE_COLUMNS:
            continue
        if _base_type(column.type) in _NUMERIC_TYPES:
            value_cols.append(column.name)
    return value_cols


def _duplicate_count(df: pd.DataFrame, natural_key: tuple[str, ...]) -> tuple[int, list[str]]:
    if not natural_key:
        return 0, []
    missing = [col for col in natural_key if col not in df.columns]
    if missing:
        return 0, missing
    return int(df.duplicated(subset=list(natural_key)).sum()), []


def _null_rates(df: pd.DataFrame, value_columns: list[str]) -> dict[str, float]:
    rates: dict[str, float] = {}
    if df.empty:
        return {col: 1.0 for col in value_columns if col in df.columns}
    for col in value_columns:
        if col in df.columns:
            rates[col] = float(df[col].isna().mean())
    return rates


def _revision_counts(
    dataset: DatasetSpec,
    df: pd.DataFrame,
    contract: SourceContract | None,
) -> dict[str, int]:
    schema_numeric = {
        col.name
        for col in dataset.schema
        if _base_type(col.type) in _NUMERIC_TYPES
    }
    candidates = {
        col for col in schema_numeric
        if any(token in col.lower() for token in _REVISION_TOKENS)
    }
    if contract:
        candidates.update(contract.required_nonzero_revision_columns)
    counts: dict[str, int] = {}
    for col in sorted(candidates):
        if col not in df.columns:
            counts[col] = 0
            continue
        numeric = pd.to_numeric(df[col], errors="coerce")
        counts[col] = int((numeric.fillna(0) != 0).sum())
    return counts


def _unexpected_values(
    df: pd.DataFrame,
    expected: dict[str, tuple[str, ...]],
) -> dict[str, int]:
    out: dict[str, int] = {}
    for col, allowed in expected.items():
        if col not in df.columns:
            out[col] = 0
            continue
        allowed_set = {str(value).strip().lower() for value in allowed}
        values = df[col].dropna().astype(str).str.strip().str.lower()
        out[col] = int((~values.isin(allowed_set)).sum())
    return out


def _freshness(
    dataset: DatasetSpec,
    history_end: str | None,
    *,
    as_of: date,
) -> dict[str, Any]:
    if not history_end or dataset.freshness_days is None:
        return {"max_age_days": None, "freshness_days": dataset.freshness_days, "is_stale": False}
    parsed = pd.to_datetime(history_end, errors="coerce")
    if pd.isna(parsed):
        return {"max_age_days": None, "freshness_days": dataset.freshness_days, "is_stale": False}
    age = (as_of - parsed.date()).days
    return {
        "max_age_days": int(age),
        "freshness_days": dataset.freshness_days,
        "is_stale": bool(age > dataset.freshness_days),
    }


def certify_dataframe(
    dataset: DatasetSpec,
    df: pd.DataFrame,
    *,
    contract: SourceContract | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Return a deterministic certification report for one dataset DataFrame."""
    if contract and contract.dataset_id != dataset.dataset_id:
        raise SourceCertificationError(
            f"contract dataset_id {contract.dataset_id!r} does not match {dataset.dataset_id!r}"
        )

    as_of = as_of or datetime.now(timezone.utc).date()
    row_count = int(len(df))
    duplicate_count, missing_key_columns = _duplicate_count(df, dataset.natural_key)
    timestamp_cols = _timestamp_columns(dataset, df)

    if timestamp_cols and row_count:
        ts_col = timestamp_cols[0]
        history_start = _to_iso(df[ts_col].min())
        history_end = _to_iso(df[ts_col].max())
    else:
        ts_col = None
        history_start = dataset.historical_start
        history_end = dataset.historical_end

    value_columns = _value_columns(dataset)
    null_rates = _null_rates(df, value_columns)
    revision_counts = _revision_counts(dataset, df, contract)
    unexpected_units = _unexpected_values(df, contract.expected_units if contract else {})
    unexpected_categories = _unexpected_values(
        df, contract.expected_categories if contract else {}
    )
    freshness = _freshness(dataset, history_end, as_of=as_of)

    blockers: list[str] = []
    warnings: list[str] = []
    if dataset.status == "blocked_pending_phase2":
        blockers.append("dataset registry status is blocked_pending_phase2")
    if dataset.status == "active" and row_count == 0:
        blockers.append("active dataset has zero rows")
    if missing_key_columns:
        blockers.append(f"missing natural-key columns: {missing_key_columns}")
    if duplicate_count:
        blockers.append(f"{duplicate_count} duplicate rows on natural key")
    for col, count in unexpected_units.items():
        if count:
            blockers.append(f"{count} unexpected unit values in {col}")
    for col, count in unexpected_categories.items():
        if count:
            blockers.append(f"{count} unexpected category values in {col}")
    if contract:
        for col in contract.required_nonzero_revision_columns:
            if revision_counts.get(col, 0) == 0:
                blockers.append(f"{col} has zero nonzero revisions")
    if freshness["is_stale"]:
        warnings.append(
            f"latest timestamp is {freshness['max_age_days']} days old "
            f"(freshness_days={freshness['freshness_days']})"
        )
    for col, rate in null_rates.items():
        if rate == 1.0:
            warnings.append(f"{col} is entirely null")

    status = "block" if blockers else ("warn" if warnings else "pass")
    return {
        "dataset_id": dataset.dataset_id,
        "athena_table": dataset.athena.table,
        "registry_status": dataset.status,
        "certification_status": status,
        "row_count": row_count,
        "history": {
            "timestamp_column": ts_col,
            "start": history_start,
            "end": history_end,
        },
        "natural_key": list(dataset.natural_key),
        "duplicate_count": duplicate_count,
        "null_rate_by_value_column": null_rates,
        "nonzero_revision_count": revision_counts,
        "unexpected_unit_count": unexpected_units,
        "unexpected_category_count": unexpected_categories,
        "freshness": freshness,
        "known_limitations": list(contract.known_limitations if contract else ()),
        "blockers": blockers,
        "warnings": warnings,
    }
