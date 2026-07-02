"""Audit helpers for WASDE snapshot anomaly-detector readiness.

This module audits an existing WASDE snapshot model-ready matrix. It does not
train detectors or tune alert thresholds; it answers whether the matrix has the
row grain, feature coverage, event balance, and prior-history depth needed for
rolling point-in-time anomaly scores.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from leviathan.model_datasets.wasde_snapshot_diagnostics import BASELINE_COLUMNS
from leviathan.model_datasets.wasde_snapshot_model_ready import (
    SNAPSHOT_MATRIX_NATURAL_KEY,
    TARGET_LEAKAGE_COLUMNS,
    TARGET_LEAKAGE_PREFIXES,
)
from leviathan.model_datasets.wasde_snapshot_targets import GROUP_KEY as TARGET_GROUP_KEY

REQUIRED_ID_COLUMNS = [
    "dataset_key",
    "contract_key",
    "origin_key",
    "target_market_year",
    "target_key",
    "as_of_date",
    "snapshot_stage",
]

REQUIRED_TARGET_COLUMNS = [
    "target_value",
    "target_event_label",
    "target_event_threshold",
    "target_event_threshold_type",
    "target_event_direction",
    "is_trainable",
]

SNAPSHOT_KEY_WITHOUT_TARGET = [
    "dataset_key",
    "contract_key",
    "origin_key",
    "target_market_year",
    "as_of_date",
    "snapshot_stage",
]

PRIOR_HISTORY_GROUPINGS: dict[str, list[str]] = {
    "contract_origin_stage": ["contract_key", "origin_key", "snapshot_stage"],
    "contract_stage": ["contract_key", "snapshot_stage"],
    "commodity_group_stage": ["commodity_group", "snapshot_stage"],
}

FEATURE_METADATA_COLUMNS = set(REQUIRED_ID_COLUMNS) | set(REQUIRED_TARGET_COLUMNS) | {
    "source_dataset_version",
    "commodity",
    "commodity_group",
    "origin",
    "crop_year",
    "target_family",
    "target_attribute",
    "target_source",
    "target_anomaly_pct",
    "actual_value",
    "trend_prediction",
    "prior_year_value",
    "trailing_mean_prediction",
    "history_years",
    "target_available",
    "target_observation_release_date",
    "target_source_vintage",
    "snapshot_month_code",
    "snapshot_policy",
    "snapshot_sequence",
    "snapshot_count",
    "target_event_definition",
    "sample_weight",
    "cv_group",
    "cv_time",
    "excluded_reason",
    "snapshot_available",
    "mapping_confidence",
    "target_status",
    "psd_source_slug",
    "psd_commodity",
    "psd_country",
    "origin_role",
    "wasde_commodity",
    "wasde_origin",
    "wasde_region",
    "wasde_release_count_for_group",
    "psd_mapping_sha",
    "wasde_mapping_sha",
    "source_release_date_max",
    "source_release_count_visible",
} | set(BASELINE_COLUMNS.values())


@dataclass(frozen=True)
class WasdeSnapshotAnomalyAuditResult:
    """Container for anomaly-detector Phase 0 audit outputs."""

    report: dict[str, object]
    feature_coverage: pd.DataFrame
    event_distribution: pd.DataFrame
    prior_history: pd.DataFrame


def _as_bool(series: pd.Series) -> pd.Series:
    return series.fillna(False).astype(bool)


def _safe_float(value: object) -> float | None:
    try:
        out = float(value)
    except Exception:  # noqa: BLE001
        return None
    return out if np.isfinite(out) else None


def _constant_rate(series: pd.Series) -> float:
    non_null = series.dropna()
    if non_null.empty:
        return np.nan
    return float(non_null.value_counts(dropna=True, normalize=True).max())


def _normalize_matrix(matrix: pd.DataFrame) -> pd.DataFrame:
    out = matrix.copy()
    if "as_of_date" in out.columns:
        out["as_of_date"] = pd.to_datetime(out["as_of_date"], errors="coerce")
    if "target_market_year" in out.columns:
        out["target_market_year"] = pd.to_numeric(
            out["target_market_year"], errors="coerce"
        )
    if "target_event_label" in out.columns:
        out["target_event_label"] = _as_bool(out["target_event_label"])
    if "is_trainable" in out.columns:
        out["is_trainable"] = _as_bool(out["is_trainable"])
    return out


def feature_columns_for_anomaly_audit(
    matrix: pd.DataFrame,
    *,
    include_static_features: bool = False,
) -> tuple[str, ...]:
    """Return numeric feature columns suitable for anomaly-readiness auditing."""
    candidates: list[str] = []
    for column in matrix.columns:
        name = str(column)
        if name in FEATURE_METADATA_COLUMNS:
            continue
        if name in TARGET_LEAKAGE_COLUMNS:
            continue
        if name.startswith(TARGET_LEAKAGE_PREFIXES):
            continue
        if not include_static_features and not name.startswith("wasde_"):
            continue
        if name in {"wasde_commodity", "wasde_origin", "wasde_region"}:
            continue
        pd.to_numeric(matrix[column], errors="coerce")
        candidates.append(name)
    return tuple(sorted(candidates))


def build_snapshot_key_audit(matrix: pd.DataFrame) -> dict[str, object]:
    """Summarize required columns, duplicate keys, and grouped-CV shape."""
    source = _normalize_matrix(matrix)
    missing_id = sorted(set(REQUIRED_ID_COLUMNS) - set(source.columns))
    missing_target = sorted(set(REQUIRED_TARGET_COLUMNS) - set(source.columns))
    missing_natural = sorted(set(SNAPSHOT_MATRIX_NATURAL_KEY) - set(source.columns))
    duplicate_natural = (
        int(source.duplicated(SNAPSHOT_MATRIX_NATURAL_KEY).sum())
        if not missing_natural and not source.empty else 0
    )
    missing_snapshot = sorted(set(SNAPSHOT_KEY_WITHOUT_TARGET) - set(source.columns))
    duplicate_snapshot_without_target = (
        int(source.duplicated(SNAPSHOT_KEY_WITHOUT_TARGET).sum())
        if not missing_snapshot and not source.empty else 0
    )
    missing_group = sorted(set(TARGET_GROUP_KEY) - set(source.columns))
    annual_group_count = (
        int(source[TARGET_GROUP_KEY].drop_duplicates().shape[0])
        if not missing_group and not source.empty else 0
    )
    trainable_group_count = 0
    if not missing_group and "is_trainable" in source.columns:
        trainable = source.loc[_as_bool(source["is_trainable"])]
        trainable_group_count = int(trainable[TARGET_GROUP_KEY].drop_duplicates().shape[0])
    return {
        "row_count": int(len(source)),
        "target_count": int(source["target_key"].nunique()) if "target_key" in source.columns else 0,
        "snapshot_count": int(source["as_of_date"].nunique()) if "as_of_date" in source.columns else 0,
        "origin_count": int(source["origin_key"].nunique()) if "origin_key" in source.columns else 0,
        "annual_group_count": annual_group_count,
        "trainable_annual_group_count": trainable_group_count,
        "missing_id_columns": missing_id,
        "missing_target_columns": missing_target,
        "duplicate_natural_key_count": duplicate_natural,
        "duplicate_snapshot_without_target_count": duplicate_snapshot_without_target,
    }


def build_feature_coverage_audit(
    matrix: pd.DataFrame,
    *,
    feature_columns: Iterable[str] | None = None,
    include_static_features: bool = False,
) -> pd.DataFrame:
    """Summarize feature density, uniqueness, and stage/origin coverage."""
    source = _normalize_matrix(matrix)
    features = tuple(feature_columns or feature_columns_for_anomaly_audit(
        source,
        include_static_features=include_static_features,
    ))
    columns = [
        "feature",
        "feature_family",
        "row_count",
        "trainable_row_count",
        "non_null_count",
        "non_null_rate",
        "trainable_non_null_count",
        "trainable_non_null_rate",
        "stage_non_null_min",
        "origin_non_null_min",
        "unique_value_count",
        "constant_rate",
        "quality_bucket",
    ]
    rows: list[dict[str, object]] = []
    trainable_mask = _as_bool(source["is_trainable"]) if "is_trainable" in source.columns else pd.Series(True, index=source.index)
    trainable = source.loc[trainable_mask]
    for feature in features:
        values = pd.to_numeric(source[feature], errors="coerce")
        train_values = pd.to_numeric(trainable[feature], errors="coerce") if not trainable.empty else pd.Series(dtype=float)
        stage_min = np.nan
        if "snapshot_stage" in source.columns:
            stage_min = float(
                source.assign(_present=values.notna())
                .groupby("snapshot_stage", dropna=False)["_present"]
                .mean()
                .min()
            )
        origin_min = np.nan
        if "origin_key" in source.columns:
            origin_min = float(
                source.assign(_present=values.notna())
                .groupby("origin_key", dropna=False)["_present"]
                .mean()
                .min()
            )
        non_null_rate = float(values.notna().mean()) if len(values) else 0.0
        train_non_null_rate = float(train_values.notna().mean()) if len(train_values) else 0.0
        unique_count = int(values.dropna().nunique())
        constant_rate = _constant_rate(values)
        if non_null_rate == 0.0:
            bucket = "all_missing"
        elif unique_count <= 1:
            bucket = "constant"
        elif train_non_null_rate >= 0.70:
            bucket = "dense"
        elif train_non_null_rate >= 0.20:
            bucket = "usable_sparse"
        else:
            bucket = "too_sparse"
        rows.append({
            "feature": feature,
            "feature_family": "wasde_dynamic" if feature.startswith("wasde_") else "static_context",
            "row_count": int(len(source)),
            "trainable_row_count": int(len(trainable)),
            "non_null_count": int(values.notna().sum()),
            "non_null_rate": non_null_rate,
            "trainable_non_null_count": int(train_values.notna().sum()),
            "trainable_non_null_rate": train_non_null_rate,
            "stage_non_null_min": stage_min,
            "origin_non_null_min": origin_min,
            "unique_value_count": unique_count,
            "constant_rate": constant_rate,
            "quality_bucket": bucket,
        })
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["quality_bucket", "feature"]
    ).reset_index(drop=True)


def _annual_group_frame(matrix: pd.DataFrame) -> pd.DataFrame:
    source = _normalize_matrix(matrix)
    missing = sorted(set(TARGET_GROUP_KEY) - set(source.columns))
    if missing or source.empty:
        return pd.DataFrame(columns=list(TARGET_GROUP_KEY))
    return (
        source.sort_values([*TARGET_GROUP_KEY, "as_of_date"])
        .groupby(TARGET_GROUP_KEY, dropna=False, as_index=False)
        .first()
    )


def build_event_distribution_audit(matrix: pd.DataFrame) -> pd.DataFrame:
    """Summarize stress-event balance by target, origin, and snapshot stage."""
    source = _normalize_matrix(matrix)
    columns = [
        "level",
        "target_key",
        "origin_key",
        "snapshot_stage",
        "row_count",
        "trainable_row_count",
        "event_count",
        "event_rate",
        "threshold_type",
        "threshold_value",
        "event_direction",
    ]
    if source.empty or "target_event_label" not in source.columns:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, object]] = []

    def append_rows(frame: pd.DataFrame, level: str, group_cols: list[str]) -> None:
        present_group_cols = [col for col in group_cols if col in frame.columns]
        for keys, group in frame.groupby(present_group_cols, dropna=False, sort=True):
            if not isinstance(keys, tuple):
                keys = (keys,)
            values = dict(zip(present_group_cols, keys, strict=False))
            trainable = group.loc[_as_bool(group["is_trainable"])] if "is_trainable" in group.columns else group
            events = _as_bool(trainable["target_event_label"]) if "target_event_label" in trainable.columns else pd.Series(dtype=bool)
            rows.append({
                "level": level,
                "target_key": str(values.get("target_key", "all")),
                "origin_key": str(values.get("origin_key", "all")),
                "snapshot_stage": str(values.get("snapshot_stage", "all")),
                "row_count": int(len(group)),
                "trainable_row_count": int(len(trainable)),
                "event_count": int(events.sum()) if len(events) else 0,
                "event_rate": float(events.mean()) if len(events) else np.nan,
                "threshold_type": str(
                    trainable["target_event_threshold_type"].dropna().iloc[0]
                    if "target_event_threshold_type" in trainable.columns and trainable["target_event_threshold_type"].notna().any()
                    else ""
                ),
                "threshold_value": _safe_float(
                    trainable["target_event_threshold"].dropna().iloc[0]
                    if "target_event_threshold" in trainable.columns and trainable["target_event_threshold"].notna().any()
                    else np.nan
                ),
                "event_direction": str(
                    trainable["target_event_direction"].dropna().iloc[0]
                    if "target_event_direction" in trainable.columns and trainable["target_event_direction"].notna().any()
                    else ""
                ),
            })

    annual = _annual_group_frame(source)
    append_rows(annual, "annual_group_by_target", ["target_key"])
    append_rows(annual, "annual_group_by_target_origin", ["target_key", "origin_key"])
    append_rows(source, "snapshot_by_target_stage", ["target_key", "snapshot_stage"])
    return pd.DataFrame(rows, columns=columns).reset_index(drop=True)


def build_prior_history_viability_audit(
    matrix: pd.DataFrame,
    *,
    min_prior_observations: int = 10,
) -> pd.DataFrame:
    """Summarize whether snapshots have enough prior history by grouping rule."""
    source = _normalize_matrix(matrix)
    columns = [
        "grouping",
        "target_key",
        "snapshot_stage",
        "origin_key",
        "row_count",
        "rows_with_min_prior_observations",
        "share_with_min_prior_observations",
        "prior_count_min",
        "prior_count_median",
        "prior_count_max",
        "min_prior_observations",
    ]
    if source.empty or "as_of_date" not in source.columns:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, object]] = []
    for grouping, group_cols in PRIOR_HISTORY_GROUPINGS.items():
        if not set(group_cols).issubset(source.columns):
            continue
        work = source.copy()
        work["_snapshot_key"] = (
            work[SNAPSHOT_KEY_WITHOUT_TARGET].astype(str).agg("|".join, axis=1)
            if set(SNAPSHOT_KEY_WITHOUT_TARGET).issubset(work.columns)
            else work.index.astype(str)
        )
        unique_snapshots = work.drop_duplicates([*group_cols, "as_of_date", "_snapshot_key"]).copy()
        unique_snapshots = unique_snapshots.sort_values([*group_cols, "as_of_date"])
        unique_snapshots["_prior_count"] = (
            unique_snapshots.groupby(group_cols, dropna=False).cumcount()
        )
        work = work.merge(
            unique_snapshots[[*group_cols, "as_of_date", "_snapshot_key", "_prior_count"]],
            on=[*group_cols, "as_of_date", "_snapshot_key"],
            how="left",
            validate="many_to_one",
        )
        summary_cols = ["target_key", "snapshot_stage"]
        if grouping == "contract_origin_stage" and "origin_key" in work.columns:
            summary_cols.append("origin_key")
        for keys, group in work.groupby(summary_cols, dropna=False, sort=True):
            if not isinstance(keys, tuple):
                keys = (keys,)
            values = dict(zip(summary_cols, keys, strict=False))
            counts = pd.to_numeric(group["_prior_count"], errors="coerce")
            has_min = counts >= int(min_prior_observations)
            rows.append({
                "grouping": grouping,
                "target_key": str(values.get("target_key", "all")),
                "snapshot_stage": str(values.get("snapshot_stage", "all")),
                "origin_key": str(values.get("origin_key", "all")),
                "row_count": int(len(group)),
                "rows_with_min_prior_observations": int(has_min.sum()),
                "share_with_min_prior_observations": float(has_min.mean()) if len(has_min) else np.nan,
                "prior_count_min": _safe_float(counts.min()),
                "prior_count_median": _safe_float(counts.median()),
                "prior_count_max": _safe_float(counts.max()),
                "min_prior_observations": int(min_prior_observations),
            })
    return pd.DataFrame(rows, columns=columns).reset_index(drop=True)


def build_wasde_snapshot_anomaly_audit_report(
    matrix: pd.DataFrame,
    *,
    feature_coverage: pd.DataFrame,
    event_distribution: pd.DataFrame,
    prior_history: pd.DataFrame,
    min_independent_groups: int = 100,
    min_event_groups: int = 20,
    min_prior_observations: int = 10,
) -> dict[str, object]:
    """Build a compact go/no-go report for Phase 0 anomaly readiness."""
    key_audit = build_snapshot_key_audit(matrix)
    blockers: list[str] = []
    warnings: list[str] = []

    if key_audit["missing_id_columns"]:
        blockers.append("missing_required_id_columns")
    if key_audit["missing_target_columns"]:
        blockers.append("missing_required_target_columns")
    if int(key_audit["duplicate_natural_key_count"]) > 0:
        blockers.append("duplicate_snapshot_target_keys")
    if int(key_audit["trainable_annual_group_count"]) < int(min_independent_groups):
        blockers.append("insufficient_independent_annual_groups")

    annual_target_events = event_distribution.loc[
        event_distribution["level"] == "annual_group_by_target"
    ] if not event_distribution.empty else pd.DataFrame()
    event_counts = {
        str(row["target_key"]): int(row["event_count"])
        for _, row in annual_target_events.iterrows()
    }
    if annual_target_events.empty or max(event_counts.values() or [0]) < int(min_event_groups):
        blockers.append("insufficient_stress_event_groups")

    quality_counts = (
        feature_coverage["quality_bucket"].value_counts(dropna=False).to_dict()
        if not feature_coverage.empty else {}
    )
    dense_or_usable = int(quality_counts.get("dense", 0) + quality_counts.get("usable_sparse", 0))
    if dense_or_usable == 0:
        blockers.append("no_usable_wasde_features")
    too_sparse = int(quality_counts.get("too_sparse", 0) + quality_counts.get("all_missing", 0))
    if too_sparse > dense_or_usable:
        warnings.append("more_sparse_than_usable_wasde_features")

    viable_history = prior_history.loc[
        prior_history["share_with_min_prior_observations"] >= 0.50
    ] if not prior_history.empty else pd.DataFrame()
    if viable_history.empty:
        blockers.append("no_viable_prior_history_grouping")
    elif not (viable_history["grouping"] == "contract_origin_stage").any():
        warnings.append("requires_broader_normalization_fallback")

    if blockers:
        status = "blocked"
    elif warnings:
        status = "go_with_warnings"
    else:
        status = "go"

    return {
        "phase": "wasde_snapshot_anomaly_phase0_audit",
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "thresholds": {
            "min_independent_groups": int(min_independent_groups),
            "min_event_groups": int(min_event_groups),
            "min_prior_observations": int(min_prior_observations),
        },
        "key_audit": key_audit,
        "feature_coverage": {
            "feature_count": int(len(feature_coverage)),
            "quality_bucket_counts": {str(k): int(v) for k, v in quality_counts.items()},
            "usable_feature_count": dense_or_usable,
        },
        "event_distribution": {
            "annual_event_counts_by_target": event_counts,
        },
        "prior_history": {
            "viable_grouping_count": int(len(viable_history)),
            "viable_groupings": sorted(viable_history["grouping"].dropna().astype(str).unique())
            if not viable_history.empty else [],
        },
        "phase1_recommendation": {
            "proceed": status in {"go", "go_with_warnings"},
            "recommended_first_detectors": [
                "stage_level_z",
                "revision_shock",
                "composite_balance_sheet_stress",
            ],
            "notes": [
                "Fit all normalization statistics with rolling prior-only history.",
                "Evaluate alert thresholds by annual outcome group, not raw snapshot rows.",
                "Use false-negative and false-positive RCA before expanding grids.",
            ],
        },
    }


def audit_wasde_snapshot_anomaly_inputs(
    matrix: pd.DataFrame,
    *,
    min_independent_groups: int = 100,
    min_event_groups: int = 20,
    min_prior_observations: int = 10,
    include_static_features: bool = False,
) -> WasdeSnapshotAnomalyAuditResult:
    """Run the full Phase 0 anomaly-detector input audit."""
    source = _normalize_matrix(matrix)
    feature_coverage = build_feature_coverage_audit(
        source,
        include_static_features=include_static_features,
    )
    event_distribution = build_event_distribution_audit(source)
    prior_history = build_prior_history_viability_audit(
        source,
        min_prior_observations=min_prior_observations,
    )
    report = build_wasde_snapshot_anomaly_audit_report(
        source,
        feature_coverage=feature_coverage,
        event_distribution=event_distribution,
        prior_history=prior_history,
        min_independent_groups=min_independent_groups,
        min_event_groups=min_event_groups,
        min_prior_observations=min_prior_observations,
    )
    return WasdeSnapshotAnomalyAuditResult(
        report=report,
        feature_coverage=feature_coverage,
        event_distribution=event_distribution,
        prior_history=prior_history,
    )
