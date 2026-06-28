"""Lightweight feature-set quality gates for model-ready matrices."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd

from leviathan.model_datasets.feature_pruning import (
    DENSE_WEATHER_FEATURE_SETS,
    DENSE_WEATHER_PREFIX,
    DENSE_WEATHER_REVIEW_MIN_NON_NULL_RATE,
)


DEFAULT_HIGH_MISSING_THRESHOLD = 0.8
DEFAULT_MAX_FEATURE_ROW_RATIO = 1.0
DEFAULT_MIN_ROWS_FOR_FEATURE_ROW_RATIO = 30
SNAPSHOT_WASDE_FEATURE_SETS = {
    "wasde_monthly_revision",
    "preseason_physical_plus_wasde_revision",
    "corn_preseason_core_plus_wasde",
    "corn_weather_wasde",
}
ANNUAL_WASDE_FEATURE_SETS = {"official_revision"}
LEGACY_PSD_VINTAGE_FEATURE_SETS = {
    "psd_monthly_vintage_features",
    "preseason_physical_plus_psd_vintage",
}


@dataclass(frozen=True)
class FeatureQualityPolicy:
    """Thresholds and strictness for pre-training feature-set gates."""

    mode: str = "strict"
    high_missing_threshold: float = DEFAULT_HIGH_MISSING_THRESHOLD
    max_feature_row_ratio: float = DEFAULT_MAX_FEATURE_ROW_RATIO
    min_rows_for_feature_row_ratio: int = DEFAULT_MIN_ROWS_FOR_FEATURE_ROW_RATIO
    fail_on_constant: bool = False


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _metadata_by_feature(membership: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    if membership is None or membership.empty or "feature" not in membership.columns:
        return {}
    rows = (
        membership.drop_duplicates("feature", keep="first")
        .set_index("feature")
        .to_dict(orient="index")
    )
    return {str(feature): dict(meta) for feature, meta in rows.items()}


def _selected_feature_set_ids(selected_feature_sets: Iterable[str] | None) -> set[str]:
    return {str(item) for item in (selected_feature_sets or []) if str(item).strip()}


def _feature_names_look_like_labels(features: Iterable[str]) -> list[str]:
    blocked: list[str] = []
    for feature in features:
        lower = str(feature).lower()
        if lower.startswith("label_") or lower in {"target_value", "actual_value"}:
            blocked.append(str(feature))
    return sorted(blocked)


def _metadata_label_features(feature_cols: Iterable[str], membership: pd.DataFrame | None) -> list[str]:
    if membership is None or membership.empty or "feature" not in membership.columns:
        return []
    if "is_label" not in membership.columns:
        return []
    selected = set(str(feature) for feature in feature_cols)
    labels = membership.loc[
        membership["feature"].astype(str).isin(selected)
        & membership["is_label"].fillna(False).map(_as_bool),
        "feature",
    ]
    return sorted(labels.astype(str).unique())


def _semantic_duplicate_findings(
    *,
    dataset_key: str,
    selected_feature_sets: set[str],
    feature_cols: list[str],
    membership: pd.DataFrame | None,
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if (
        str(dataset_key).endswith("_snapshot")
        and selected_feature_sets & SNAPSHOT_WASDE_FEATURE_SETS
        and selected_feature_sets & ANNUAL_WASDE_FEATURE_SETS
    ):
        findings.append({
            "reason": "annual_and_snapshot_wasde_feature_sets_mixed",
            "detail": (
                "Do not mix annual official_revision WASDE context with "
                "snapshot WASDE revision feature sets in one training slice."
            ),
        })

    meta = _metadata_by_feature(membership)
    wasde_features = [
        feature for feature in feature_cols
        if str(feature).startswith("wasde_")
        or str(meta.get(feature, {}).get("sources", "")).lower() == "wasde"
    ]
    if selected_feature_sets & SNAPSHOT_WASDE_FEATURE_SETS and "official_revision" in selected_feature_sets:
        findings.append({
            "reason": "official_revision_requested_with_snapshot_wasde",
            "detail": f"Potential duplicate WASDE semantics in features: {sorted(wasde_features)[:10]}",
        })
    return findings


def build_feature_quality_report(
    matrix: pd.DataFrame,
    feature_cols: list[str],
    *,
    trainable_only: bool = True,
    membership: pd.DataFrame | None = None,
    dataset_key: str = "",
    feature_set_id: str = "",
    selected_feature_sets: Iterable[str] | None = None,
    policy: FeatureQualityPolicy | None = None,
) -> dict[str, Any]:
    """Return pass/warn/fail quality diagnostics for selected model inputs."""
    policy = policy or FeatureQualityPolicy()
    selected_sets = _selected_feature_set_ids(selected_feature_sets) or {feature_set_id}
    frame = matrix.copy()
    if trainable_only and "is_trainable" in frame.columns:
        frame = frame.loc[frame["is_trainable"].fillna(False).astype(bool)].copy()
    row_count = int(len(frame))
    feature_cols = [str(feature) for feature in feature_cols]

    missing_columns = sorted(feature for feature in feature_cols if feature not in frame.columns)
    present = [feature for feature in feature_cols if feature in frame.columns]
    duplicate_columns = sorted(
        str(col) for col in frame.columns[frame.columns.duplicated()].unique()
    )
    all_missing: list[str] = []
    high_missing: list[str] = []
    constant: list[str] = []
    non_numeric: list[str] = []
    dense_weather_review: list[str] = []
    feature_summaries: list[dict[str, Any]] = []

    for feature in present:
        series = frame[feature]
        non_null = int(series.notna().sum())
        non_null_rate = float(non_null / row_count) if row_count else 0.0
        numeric = pd.to_numeric(series, errors="coerce")
        numeric_non_null = int(numeric.notna().sum())
        is_numeric = bool(non_null == 0 or numeric_non_null == non_null)
        unique_non_null = int(series.dropna().nunique())
        if non_null == 0:
            all_missing.append(feature)
        if row_count and (1.0 - non_null_rate) > policy.high_missing_threshold:
            high_missing.append(feature)
        if (
            selected_sets & DENSE_WEATHER_FEATURE_SETS
            and feature.startswith(DENSE_WEATHER_PREFIX)
            and non_null_rate < DENSE_WEATHER_REVIEW_MIN_NON_NULL_RATE
        ):
            dense_weather_review.append(feature)
        if non_null > 0 and unique_non_null <= 1:
            constant.append(feature)
        if not is_numeric:
            non_numeric.append(feature)
        feature_summaries.append({
            "feature": feature,
            "non_null_count": non_null,
            "non_null_rate": non_null_rate,
            "null_rate": float(1.0 - non_null_rate) if row_count else 1.0,
            "unique_non_null_count": unique_non_null,
            "is_numeric": is_numeric,
            "is_constant": bool(non_null > 0 and unique_non_null <= 1),
            "is_all_missing": bool(non_null == 0),
        })

    label_like = sorted(set(_feature_names_look_like_labels(feature_cols)) | set(
        _metadata_label_features(feature_cols, membership)
    ))
    semantic_duplicates = _semantic_duplicate_findings(
        dataset_key=dataset_key,
        selected_feature_sets=selected_sets,
        feature_cols=present,
        membership=membership,
    )
    feature_row_ratio = float(len(present) / row_count) if row_count else float("inf")

    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if not present:
        failures.append({"reason": "zero_selected_features", "features": []})
    if missing_columns:
        failures.append({"reason": "selected_features_missing_from_matrix", "features": missing_columns})
    if all_missing:
        failures.append({"reason": "all_missing_features", "features": all_missing})
    if non_numeric:
        failures.append({"reason": "non_numeric_features", "features": non_numeric})
    if label_like:
        failures.append({"reason": "label_or_target_like_features", "features": label_like})
    if duplicate_columns:
        failures.append({"reason": "duplicate_matrix_columns", "features": duplicate_columns})
    if semantic_duplicates:
        failures.append({"reason": "duplicate_semantic_feature_sets", "findings": semantic_duplicates})
    if (
        row_count >= policy.min_rows_for_feature_row_ratio
        and feature_row_ratio > policy.max_feature_row_ratio
    ):
        failures.append({
            "reason": "feature_count_too_large_for_rows",
            "feature_count": len(present),
            "row_count": row_count,
            "feature_row_ratio": feature_row_ratio,
            "max_feature_row_ratio": policy.max_feature_row_ratio,
            "min_rows_for_feature_row_ratio": policy.min_rows_for_feature_row_ratio,
        })
    if constant:
        target = failures if policy.fail_on_constant else warnings
        target.append({"reason": "constant_features", "features": constant})
    if high_missing:
        warnings.append({
            "reason": "high_missing_features",
            "features": high_missing,
            "threshold": policy.high_missing_threshold,
        })
    if dense_weather_review:
        warnings.append({
            "reason": "dense_weather_low_model_ready_coverage",
            "features": sorted(dense_weather_review),
            "threshold": DENSE_WEATHER_REVIEW_MIN_NON_NULL_RATE,
        })
    if selected_sets & LEGACY_PSD_VINTAGE_FEATURE_SETS:
        warnings.append({
            "reason": "legacy_psd_vintage_feature_set_requested",
            "feature_sets": sorted(selected_sets & LEGACY_PSD_VINTAGE_FEATURE_SETS),
        })

    status = "fail" if failures else ("warn" if warnings else "pass")
    if policy.mode == "warn" and failures:
        warnings.extend(failures)
        failures = []
        status = "warn"
    return {
        "status": status,
        "policy": {
            "mode": policy.mode,
            "high_missing_threshold": policy.high_missing_threshold,
            "max_feature_row_ratio": policy.max_feature_row_ratio,
            "min_rows_for_feature_row_ratio": policy.min_rows_for_feature_row_ratio,
            "fail_on_constant": policy.fail_on_constant,
        },
        "dataset_key": dataset_key,
        "feature_set_id": feature_set_id,
        "selected_feature_sets": sorted(selected_sets),
        "row_count": row_count,
        "feature_count": int(len(present)),
        "requested_feature_count": int(len(feature_cols)),
        "feature_row_ratio": feature_row_ratio,
        "all_missing_feature_count": int(len(all_missing)),
        "high_missing_feature_count": int(len(high_missing)),
        "dense_weather_review_feature_count": int(len(dense_weather_review)),
        "constant_feature_count": int(len(constant)),
        "non_numeric_feature_count": int(len(non_numeric)),
        "label_like_feature_count": int(len(label_like)),
        "semantic_duplicate_count": int(len(semantic_duplicates)),
        "failures": failures,
        "warnings": warnings,
        "feature_summaries": sorted(feature_summaries, key=lambda row: row["feature"]),
    }


def enforce_feature_quality(report: dict[str, Any]) -> None:
    """Raise when a strict quality report fails."""
    if report.get("status") == "fail":
        reasons = [str(item.get("reason", "unknown")) for item in report.get("failures", [])]
        raise ValueError(f"feature quality gate failed: {', '.join(reasons)}")
