"""Feature-set selection for gold_v2 MLflow experiments."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

_DEFAULT_FEATURE_SETS_PATH = (
    Path(__file__).resolve().parents[3] / "configs" / "features" / "feature_sets_v2.yaml"
)

MATRIX_IDENTITY_COLUMNS = [
    "entity_type",
    "entity_id",
    "physical_commodity",
    "contract_slug",
    "origin",
    "crop_year",
    "as_of_date",
    "snapshot_stage",
    "dataset_version",
    "commodity",
]


class FeatureSetV2Error(ValueError):
    """A gold_v2 feature-set specification or selection is invalid."""


@dataclass(frozen=True)
class FeatureSetSpec:
    feature_set_id: str
    version: int
    description: str
    allowed_semantic_scopes: tuple[str, ...]
    allowed_policies: tuple[str, ...]
    allowed_mechanisms: tuple[str, ...]
    excluded_policies: tuple[str, ...]
    excluded_mechanisms: tuple[str, ...]
    required_as_of_policy: str
    decision_lag_days: int
    minimum_non_null_rate: float
    maximum_missing_rate: float
    target_compatibility: tuple[str, ...]


@dataclass(frozen=True)
class FeatureSetSelection:
    feature_set_id: str
    columns: tuple[str, ...]
    report: dict[str, Any]


def _tuple(raw: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in (raw or []))


def load_feature_sets_v2(path: str | Path | None = None) -> dict[str, FeatureSetSpec]:
    raw = yaml.safe_load(Path(path or _DEFAULT_FEATURE_SETS_PATH).read_text(encoding="utf-8")) or {}
    specs: dict[str, FeatureSetSpec] = {}
    for index, item in enumerate(raw.get("feature_sets", [])):
        feature_set_id = str(item.get("feature_set_id", "")).strip()
        if not feature_set_id:
            raise FeatureSetV2Error(f"feature_sets[{index}] missing feature_set_id")
        if feature_set_id in specs:
            raise FeatureSetV2Error(f"duplicate feature_set_id {feature_set_id!r}")
        specs[feature_set_id] = FeatureSetSpec(
            feature_set_id=feature_set_id,
            version=int(item.get("version", 1)),
            description=str(item.get("description", "")),
            allowed_semantic_scopes=_tuple(item.get("allowed_semantic_scopes")),
            allowed_policies=_tuple(item.get("allowed_policies")),
            allowed_mechanisms=_tuple(item.get("allowed_mechanisms")),
            excluded_policies=_tuple(item.get("excluded_policies")),
            excluded_mechanisms=_tuple(item.get("excluded_mechanisms")),
            required_as_of_policy=str(item.get("required_as_of_policy", "point_in_time")),
            decision_lag_days=int(item.get("decision_lag_days", 0)),
            minimum_non_null_rate=float(item.get("minimum_non_null_rate", 0.0)),
            maximum_missing_rate=float(item.get("maximum_missing_rate", 1.0)),
            target_compatibility=_tuple(item.get("target_compatibility")),
        )
    if not specs:
        raise FeatureSetV2Error("feature_sets_v2 contains no feature sets")
    return specs


def _catalog_candidates(catalog_df: pd.DataFrame, spec: FeatureSetSpec) -> pd.DataFrame:
    work = catalog_df.copy()
    if spec.allowed_semantic_scopes:
        work = work.loc[work["semantic_scope"].isin(spec.allowed_semantic_scopes)]
    if spec.allowed_policies:
        work = work.loc[work["policy"].isin(spec.allowed_policies)]
    if spec.allowed_mechanisms:
        work = work.loc[work["mechanism"].isin(spec.allowed_mechanisms)]
    if spec.excluded_policies:
        work = work.loc[~work["policy"].isin(spec.excluded_policies)]
    if spec.excluded_mechanisms:
        work = work.loc[~work["mechanism"].isin(spec.excluded_mechanisms)]
    return work


def _drop_duplicate_columns(df: pd.DataFrame, columns: list[str]) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    dropped: list[str] = []
    fingerprints: dict[int, str] = {}
    for column in columns:
        fingerprint = int(pd.util.hash_pandas_object(df[column], index=False).sum())
        previous = fingerprints.get(fingerprint)
        if previous is not None and df[column].equals(df[previous]):
            dropped.append(column)
            continue
        fingerprints[fingerprint] = column
        kept.append(column)
    return kept, dropped


def select_feature_set_columns_v2(
    matrix_df: pd.DataFrame,
    catalog_df: pd.DataFrame,
    feature_set_id: str,
    *,
    target: str | None = None,
    apply_reduction: bool = True,
    specs: dict[str, FeatureSetSpec] | None = None,
) -> FeatureSetSelection:
    """Select a stable feature list from a v2 matrix and feature catalog."""
    specs = specs or load_feature_sets_v2()
    if feature_set_id not in specs:
        raise FeatureSetV2Error(f"unknown feature_set_id {feature_set_id!r}")
    spec = specs[feature_set_id]
    if target and spec.target_compatibility and target not in spec.target_compatibility:
        raise FeatureSetV2Error(
            f"feature_set_id={feature_set_id!r} is not compatible with target={target!r}"
        )

    candidates = _catalog_candidates(catalog_df, spec)
    present_features = [
        feature for feature in candidates["feature"].astype(str).tolist()
        if feature in matrix_df.columns and feature not in MATRIX_IDENTITY_COLUMNS
    ]
    columns = sorted(dict.fromkeys(present_features))
    dropped: dict[str, list[str]] = {
        "missing_from_matrix": sorted(set(candidates["feature"].astype(str)) - set(columns)),
        "all_null": [],
        "low_coverage": [],
        "zero_variance": [],
        "duplicate": [],
    }

    if apply_reduction and columns:
        usable: list[str] = []
        min_non_null = max(spec.minimum_non_null_rate, 1.0 - spec.maximum_missing_rate)
        for column in columns:
            series = matrix_df[column]
            non_null_rate = float(series.notna().mean())
            if series.notna().sum() == 0:
                dropped["all_null"].append(column)
                continue
            if non_null_rate < min_non_null:
                dropped["low_coverage"].append(column)
                continue
            if pd.to_numeric(series, errors="coerce").nunique(dropna=True) <= 1:
                dropped["zero_variance"].append(column)
                continue
            usable.append(column)
        columns, duplicate = _drop_duplicate_columns(matrix_df, usable)
        dropped["duplicate"] = duplicate

    return FeatureSetSelection(
        feature_set_id=feature_set_id,
        columns=tuple(columns),
        report={
            "feature_set_id": feature_set_id,
            "feature_set_version": spec.version,
            "target": target,
            "candidate_count": int(len(candidates)),
            "selected_count": int(len(columns)),
            "dropped": dropped,
            "required_as_of_policy": spec.required_as_of_policy,
            "decision_lag_days": spec.decision_lag_days,
        },
    )
