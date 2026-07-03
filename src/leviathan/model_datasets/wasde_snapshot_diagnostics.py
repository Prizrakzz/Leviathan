"""Diagnostics and readiness gates for WASDE snapshot model-ready matrices."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from leviathan.model_datasets.wasde_snapshot_model_ready import (
    SNAPSHOT_MATRIX_NATURAL_KEY,
    TARGET_LEAKAGE_COLUMNS,
    TARGET_LEAKAGE_PREFIXES,
)
from leviathan.model_datasets.wasde_snapshot_targets import GROUP_KEY as TARGET_GROUP_KEY

BASELINE_COLUMNS = {
    "zero_anomaly": "zero_anomaly_baseline",
    "prior_year": "prior_year_anomaly_baseline",
    "trailing_mean": "trailing_mean_anomaly_baseline",
    "trailing_trend": "trailing_trend_anomaly_baseline",
}

DIAGNOSTIC_ISSUE_COLUMNS = [
    "severity",
    "issue_type",
    "feature",
    "row_count",
    "detail",
]

FEATURE_QUALITY_COLUMNS = [
    "feature",
    "feature_origin",
    "row_count",
    "trainable_row_count",
    "non_null_rate",
    "trainable_non_null_rate",
    "stage_non_null_min",
    "origin_non_null_min",
    "unique_value_count",
    "constant_rate",
    "quality_bucket",
]

TARGET_DIAGNOSTIC_COLUMNS = [
    "target_key",
    "row_count",
    "trainable_row_count",
    "annual_group_count",
    "trainable_annual_group_count",
    "snapshot_count_median",
    "target_mean",
    "target_std",
    "target_min",
    "target_max",
    "event_group_count",
    "event_group_share",
    "event_snapshot_count",
    "event_snapshot_share",
    "origin_event_group_min",
    "stage_event_snapshot_min",
]

BASELINE_DIAGNOSTIC_COLUMNS = [
    "target_key",
    "baseline_name",
    "n_groups",
    "rmse",
    "mae",
    "sign_accuracy",
    "event_count",
    "predicted_event_count",
    "true_positive_count",
    "false_negative_count",
    "false_positive_count",
    "recall",
    "precision",
    "f2_score",
]

LAGGED_PSD_TOKENS = (
    "prior",
    "lag",
    "previous",
    "trailing",
    "trend",
    "yoy",
    "history",
    "available",
    "source_disagreement",
)


@dataclass(frozen=True)
class WasdeSnapshotDiagnosticsReport:
    """Container for snapshot matrix diagnostics."""

    integrity: dict[str, object]
    leakage_issues: pd.DataFrame
    feature_quality: pd.DataFrame
    target_diagnostics: pd.DataFrame
    baseline_diagnostics: pd.DataFrame
    readiness: dict[str, object]


def _feature_columns(matrix: pd.DataFrame, feature_columns: Iterable[str] | None) -> tuple[str, ...]:
    if feature_columns is not None:
        return tuple(str(feature) for feature in feature_columns)
    metadata = set(SNAPSHOT_MATRIX_NATURAL_KEY) | set(TARGET_GROUP_KEY) | {
        "source_dataset_version",
        "commodity",
        "commodity_group",
        "origin",
        "target_family",
        "target_attribute",
        "target_source",
        "target_value",
        "target_anomaly_pct",
        "actual_value",
        "trend_prediction",
        "history_years",
        "target_available",
        "target_observation_release_date",
        "target_source_vintage",
        "snapshot_month_code",
        "snapshot_policy",
        "snapshot_sequence",
        "snapshot_count",
        "target_event_label",
        "target_event_threshold",
        "target_event_threshold_type",
        "target_event_direction",
        "target_event_definition",
        "sample_weight",
        "cv_group",
        "cv_time",
        "is_trainable",
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
    return tuple(
        str(col)
        for col in matrix.columns
        if str(col) not in metadata
        and not str(col).startswith(TARGET_LEAKAGE_PREFIXES)
    )


def _group_frame(matrix: pd.DataFrame) -> pd.DataFrame:
    if matrix.empty:
        return matrix.copy()
    required = set(TARGET_GROUP_KEY)
    missing = required - set(matrix.columns)
    if missing:
        raise ValueError(f"snapshot matrix missing target group columns: {sorted(missing)}")
    return (
        matrix.sort_values([*TARGET_GROUP_KEY, "as_of_date"])
        .groupby(TARGET_GROUP_KEY, dropna=False, as_index=False)
        .first()
    )


def _as_bool(series: pd.Series) -> pd.Series:
    return series.fillna(False).astype(bool)


def _is_lagged_psd_feature(feature: str) -> bool:
    lowered = feature.lower()
    return lowered.startswith("psd_") and any(token in lowered for token in LAGGED_PSD_TOKENS)


def _constant_rate(series: pd.Series) -> float:
    non_null = series.dropna()
    if non_null.empty:
        return np.nan
    return float(non_null.value_counts(dropna=True, normalize=True).max())


def _safe_float(value: object) -> float:
    try:
        out = float(value)
    except Exception:  # noqa: BLE001
        return np.nan
    return out if np.isfinite(out) else np.nan


def build_matrix_integrity_report(matrix: pd.DataFrame) -> dict[str, object]:
    """Summarize row-grain and grouped-CV integrity."""
    missing_key_cols = sorted(set(SNAPSHOT_MATRIX_NATURAL_KEY) - set(matrix.columns))
    duplicate_key_count = (
        int(matrix.duplicated(SNAPSHOT_MATRIX_NATURAL_KEY).sum())
        if not missing_key_cols and not matrix.empty else 0
    )
    missing_cv_cols = sorted({"cv_group", "cv_time", "sample_weight"} - set(matrix.columns))
    cv_group_has_dates = (
        bool(matrix["cv_group"].astype(str).str.contains(r"\d{4}-\d{2}-\d{2}", regex=True).any())
        if "cv_group" in matrix.columns else False
    )
    weight_sums = pd.Series(dtype=float)
    bad_weight_group_count = 0
    if set(TARGET_GROUP_KEY).issubset(matrix.columns) and "sample_weight" in matrix.columns:
        weight_sums = matrix.groupby(TARGET_GROUP_KEY, dropna=False)["sample_weight"].sum()
        bad_weight_group_count = int((~np.isclose(weight_sums.astype(float), 1.0, atol=1e-6)).sum())
    trainable = (
        int(matrix["is_trainable"].fillna(False).astype(bool).sum())
        if "is_trainable" in matrix.columns else 0
    )
    group_count = (
        int(matrix[TARGET_GROUP_KEY].drop_duplicates().shape[0])
        if set(TARGET_GROUP_KEY).issubset(matrix.columns) else 0
    )
    return {
        "row_count": int(len(matrix)),
        "trainable_row_count": trainable,
        "snapshot_count": int(matrix["as_of_date"].nunique()) if "as_of_date" in matrix.columns else 0,
        "annual_outcome_group_count": group_count,
        "missing_key_columns": missing_key_cols,
        "duplicate_key_count": duplicate_key_count,
        "missing_cv_columns": missing_cv_cols,
        "cv_group_has_dates": cv_group_has_dates,
        "bad_weight_group_count": bad_weight_group_count,
        "sample_weight_sum_min": _safe_float(weight_sums.min()) if not weight_sums.empty else np.nan,
        "sample_weight_sum_max": _safe_float(weight_sums.max()) if not weight_sums.empty else np.nan,
    }


def audit_wasde_snapshot_leakage(
    matrix: pd.DataFrame,
    *,
    feature_columns: Iterable[str] | None = None,
    static_manifest: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return fail/warn leakage issues without mutating the matrix."""
    features = _feature_columns(matrix, feature_columns)
    rows: list[dict[str, object]] = []

    if {"source_release_date_max", "as_of_date"}.issubset(matrix.columns):
        release_dates = pd.to_datetime(matrix["source_release_date_max"], errors="coerce")
        as_of = pd.to_datetime(matrix["as_of_date"], errors="coerce")
        future_count = int((release_dates.notna() & (release_dates > as_of)).sum())
        if future_count:
            rows.append({
                "severity": "fail",
                "issue_type": "future_source_release",
                "feature": "",
                "row_count": future_count,
                "detail": "source_release_date_max is after as_of_date",
            })

    for feature in features:
        if feature.startswith(TARGET_LEAKAGE_PREFIXES) or feature in TARGET_LEAKAGE_COLUMNS:
            rows.append({
                "severity": "fail",
                "issue_type": "target_feature_selected",
                "feature": feature,
                "row_count": int(len(matrix)),
                "detail": "feature name is target/label-like",
            })
        if feature.startswith("psd_") and not _is_lagged_psd_feature(feature):
            rows.append({
                "severity": "fail",
                "issue_type": "same_year_psd_feature_selected",
                "feature": feature,
                "row_count": int(len(matrix)),
                "detail": "PSD static feature does not look lagged or prior-year safe",
            })

    if static_manifest is not None and not static_manifest.empty:
        feature_set = set(features)
        blocked = static_manifest.loc[
            static_manifest["decision"].astype(str).isin({"blocked", "missing_static_feature"})
        ]
        leaked = sorted(set(blocked["feature"].astype(str)) & feature_set)
        for feature in leaked:
            decision = blocked.loc[blocked["feature"].astype(str) == feature].iloc[0]
            rows.append({
                "severity": "fail",
                "issue_type": "blocked_static_feature_selected",
                "feature": feature,
                "row_count": int(len(matrix)),
                "detail": str(decision.get("reason", "")),
            })

    if not rows:
        return pd.DataFrame(columns=DIAGNOSTIC_ISSUE_COLUMNS)
    return pd.DataFrame(rows, columns=DIAGNOSTIC_ISSUE_COLUMNS)


def build_feature_quality_report(
    matrix: pd.DataFrame,
    *,
    feature_columns: Iterable[str] | None = None,
    static_manifest: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Summarize selected feature coverage by row, trainable row, stage, and origin."""
    features = _feature_columns(matrix, feature_columns)
    if not features:
        return pd.DataFrame(columns=FEATURE_QUALITY_COLUMNS)
    static_features = (
        set(static_manifest["feature"].astype(str))
        if static_manifest is not None and not static_manifest.empty and "feature" in static_manifest.columns
        else set()
    )
    trainable = (
        matrix.loc[matrix["is_trainable"].fillna(False).astype(bool)]
        if "is_trainable" in matrix.columns else matrix
    )
    rows: list[dict[str, object]] = []
    for feature in features:
        if feature not in matrix.columns:
            rows.append({
                "feature": feature,
                "feature_origin": "missing",
                "row_count": int(len(matrix)),
                "trainable_row_count": int(len(trainable)),
                "non_null_rate": 0.0,
                "trainable_non_null_rate": 0.0,
                "stage_non_null_min": np.nan,
                "origin_non_null_min": np.nan,
                "unique_value_count": 0,
                "constant_rate": np.nan,
                "quality_bucket": "missing",
            })
            continue
        series = matrix[feature]
        train_series = trainable[feature] if feature in trainable.columns else pd.Series(dtype=float)
        non_null_rate = float(series.notna().mean()) if len(series) else np.nan
        trainable_rate = float(train_series.notna().mean()) if len(train_series) else np.nan
        stage_min = (
            float(matrix.groupby("snapshot_stage")[feature].apply(lambda s: s.notna().mean()).min())
            if "snapshot_stage" in matrix.columns and len(matrix) else np.nan
        )
        origin_min = (
            float(matrix.groupby("origin_key")[feature].apply(lambda s: s.notna().mean()).min())
            if "origin_key" in matrix.columns and len(matrix) else np.nan
        )
        constant_rate = _constant_rate(series)
        unique_count = int(series.dropna().nunique())
        if non_null_rate == 0.0:
            bucket = "all_missing"
        elif non_null_rate < 0.2:
            bucket = "ultra_sparse"
        elif unique_count <= 1:
            bucket = "constant"
        elif non_null_rate < 0.6:
            bucket = "sparse"
        elif non_null_rate < 0.9:
            bucket = "usable"
        else:
            bucket = "dense"
        origin = "dynamic_wasde" if feature.startswith("wasde_") else (
            "static_annual" if feature in static_features else "matrix_feature"
        )
        rows.append({
            "feature": feature,
            "feature_origin": origin,
            "row_count": int(len(matrix)),
            "trainable_row_count": int(len(trainable)),
            "non_null_rate": non_null_rate,
            "trainable_non_null_rate": trainable_rate,
            "stage_non_null_min": stage_min,
            "origin_non_null_min": origin_min,
            "unique_value_count": unique_count,
            "constant_rate": constant_rate,
            "quality_bucket": bucket,
        })
    return pd.DataFrame(rows, columns=FEATURE_QUALITY_COLUMNS).sort_values("feature").reset_index(drop=True)


def build_target_event_diagnostics(matrix: pd.DataFrame) -> pd.DataFrame:
    """Summarize targets and event balance by independent annual outcome group."""
    if matrix.empty or "target_key" not in matrix.columns:
        return pd.DataFrame(columns=TARGET_DIAGNOSTIC_COLUMNS)
    group = _group_frame(matrix)
    rows: list[dict[str, object]] = []
    for target_key, target_rows in matrix.groupby("target_key", dropna=False, sort=True):
        annual = group.loc[group["target_key"].astype(str) == str(target_key)].copy()
        trainable_rows = target_rows.loc[target_rows.get("is_trainable", False).fillna(False).astype(bool)]
        trainable_annual = annual.loc[annual.get("is_trainable", False).fillna(False).astype(bool)]
        target_values = pd.to_numeric(trainable_annual.get("target_value"), errors="coerce").dropna()
        event_rows = target_rows.loc[target_rows["target_event_label"].notna()] if "target_event_label" in target_rows.columns else pd.DataFrame()
        event_annual = annual.loc[annual["target_event_label"].notna()] if "target_event_label" in annual.columns else pd.DataFrame()
        event_group_count = int(_as_bool(event_annual.get("target_event_label", pd.Series(dtype=bool))).sum())
        event_snapshot_count = int(_as_bool(event_rows.get("target_event_label", pd.Series(dtype=bool))).sum())
        snapshot_counts = (
            target_rows.groupby(TARGET_GROUP_KEY, dropna=False).size()
            if set(TARGET_GROUP_KEY).issubset(target_rows.columns) else pd.Series(dtype=float)
        )
        origin_event_min = np.nan
        if not event_annual.empty and "origin_key" in event_annual.columns:
            origin_event_min = float(
                event_annual.groupby("origin_key")["target_event_label"]
                .apply(lambda s: _as_bool(s).mean())
                .min()
            )
        stage_event_min = np.nan
        if not event_rows.empty and "snapshot_stage" in event_rows.columns:
            stage_event_min = float(
                event_rows.groupby("snapshot_stage")["target_event_label"]
                .apply(lambda s: _as_bool(s).mean())
                .min()
            )
        rows.append({
            "target_key": str(target_key),
            "row_count": int(len(target_rows)),
            "trainable_row_count": int(len(trainable_rows)),
            "annual_group_count": int(len(annual)),
            "trainable_annual_group_count": int(len(trainable_annual)),
            "snapshot_count_median": _safe_float(snapshot_counts.median()) if not snapshot_counts.empty else np.nan,
            "target_mean": _safe_float(target_values.mean()),
            "target_std": _safe_float(target_values.std(ddof=0)),
            "target_min": _safe_float(target_values.min()),
            "target_max": _safe_float(target_values.max()),
            "event_group_count": event_group_count,
            "event_group_share": float(event_group_count / len(event_annual)) if len(event_annual) else np.nan,
            "event_snapshot_count": event_snapshot_count,
            "event_snapshot_share": float(event_snapshot_count / len(event_rows)) if len(event_rows) else np.nan,
            "origin_event_group_min": origin_event_min,
            "stage_event_snapshot_min": stage_event_min,
        })
    return pd.DataFrame(rows, columns=TARGET_DIAGNOSTIC_COLUMNS)


def _event_prediction(y_pred: pd.Series, threshold: pd.Series, direction: pd.Series) -> pd.Series:
    preds = []
    for pred, thresh, direct in zip(y_pred, threshold, direction, strict=False):
        if not np.isfinite(_safe_float(pred)) or not np.isfinite(_safe_float(thresh)):
            preds.append(False)
        elif str(direct) == "higher_is_stress":
            preds.append(float(pred) >= abs(float(thresh)))
        else:
            preds.append(float(pred) <= -abs(float(thresh)))
    return pd.Series(preds, index=y_pred.index, dtype=bool)


def build_baseline_diagnostics(matrix: pd.DataFrame) -> pd.DataFrame:
    """Score materialized baselines on independent annual outcome groups."""
    if matrix.empty:
        return pd.DataFrame(columns=BASELINE_DIAGNOSTIC_COLUMNS)
    annual = _group_frame(matrix)
    if "is_trainable" in annual.columns:
        annual = annual.loc[annual["is_trainable"].fillna(False).astype(bool)].copy()
    if annual.empty:
        return pd.DataFrame(columns=BASELINE_DIAGNOSTIC_COLUMNS)
    rows: list[dict[str, object]] = []
    for target_key, target_rows in annual.groupby("target_key", dropna=False, sort=True):
        y = pd.to_numeric(target_rows["target_value"], errors="coerce")
        baseline_series: dict[str, pd.Series] = {
            "zero_anomaly": pd.Series(0.0, index=target_rows.index),
        }
        for baseline_name, baseline_col in BASELINE_COLUMNS.items():
            if baseline_col in target_rows.columns:
                baseline_series[baseline_name] = pd.to_numeric(
                    target_rows[baseline_col], errors="coerce"
                )
        for baseline_name, pred in baseline_series.items():
            valid = y.notna() & pred.notna()
            if not valid.any():
                rows.append({
                    "target_key": str(target_key),
                    "baseline_name": baseline_name,
                    "n_groups": 0,
                    "rmse": np.nan,
                    "mae": np.nan,
                    "sign_accuracy": np.nan,
                    "event_count": 0,
                    "predicted_event_count": 0,
                    "true_positive_count": 0,
                    "false_negative_count": 0,
                    "false_positive_count": 0,
                    "recall": np.nan,
                    "precision": np.nan,
                    "f2_score": np.nan,
                })
                continue
            y_valid = y.loc[valid]
            pred_valid = pred.loc[valid]
            error = pred_valid - y_valid
            sign_actual = np.sign(y_valid)
            sign_pred = np.sign(pred_valid)
            sign_accuracy = float((sign_actual == sign_pred).mean()) if len(y_valid) else np.nan
            event_eval = target_rows.loc[valid].copy()
            event_eval = event_eval.loc[event_eval["target_event_label"].notna()] if "target_event_label" in event_eval.columns else pd.DataFrame()
            tp = fn = fp = event_count = pred_event_count = 0
            recall = precision = f2 = np.nan
            if not event_eval.empty:
                actual_event = _as_bool(event_eval["target_event_label"])
                pred_for_events = (
                    pd.Series(0.0, index=event_eval.index)
                    if baseline_name == "zero_anomaly"
                    else pd.to_numeric(event_eval[BASELINE_COLUMNS[baseline_name]], errors="coerce")
                )
                pred_event = _event_prediction(
                    pred_for_events,
                    pd.to_numeric(event_eval["target_event_threshold"], errors="coerce"),
                    event_eval["target_event_direction"].astype(str),
                )
                tp = int((actual_event & pred_event).sum())
                fn = int((actual_event & ~pred_event).sum())
                fp = int((~actual_event & pred_event).sum())
                event_count = int(actual_event.sum())
                pred_event_count = int(pred_event.sum())
                recall = float(tp / event_count) if event_count else np.nan
                precision = float(tp / pred_event_count) if pred_event_count else np.nan
                denom = (4 * precision) + recall
                f2 = float((5 * precision * recall) / denom) if np.isfinite(precision) and np.isfinite(recall) and denom else np.nan
            rows.append({
                "target_key": str(target_key),
                "baseline_name": baseline_name,
                "n_groups": int(valid.sum()),
                "rmse": float(np.sqrt(np.mean(np.square(error)))),
                "mae": float(np.mean(np.abs(error))),
                "sign_accuracy": sign_accuracy,
                "event_count": event_count,
                "predicted_event_count": pred_event_count,
                "true_positive_count": tp,
                "false_negative_count": fn,
                "false_positive_count": fp,
                "recall": recall,
                "precision": precision,
                "f2_score": f2,
            })
    return pd.DataFrame(rows, columns=BASELINE_DIAGNOSTIC_COLUMNS)


def build_readiness_decision(
    *,
    integrity: dict[str, object],
    leakage_issues: pd.DataFrame,
    feature_quality: pd.DataFrame,
    target_diagnostics: pd.DataFrame,
    min_trainable_annual_groups: int = 20,
    min_event_groups: int = 5,
    max_sparse_feature_share: float = 0.5,
) -> dict[str, object]:
    """Return pass/warn/fail gate decision for Phase 7 training readiness."""
    failures: list[str] = []
    warnings: list[str] = []
    if int(integrity.get("row_count", 0)) == 0:
        failures.append("matrix_has_zero_rows")
    if integrity.get("missing_key_columns"):
        failures.append("missing_key_columns")
    if int(integrity.get("duplicate_key_count", 0)) > 0:
        failures.append("duplicate_snapshot_keys")
    if integrity.get("missing_cv_columns"):
        failures.append("missing_cv_columns")
    if bool(integrity.get("cv_group_has_dates", False)):
        failures.append("cv_group_contains_snapshot_dates")
    if int(integrity.get("bad_weight_group_count", 0)) > 0:
        failures.append("sample_weights_do_not_sum_to_one")
    if not leakage_issues.empty and (leakage_issues["severity"] == "fail").any():
        failures.append("leakage_audit_failed")

    trainable_groups = int(target_diagnostics["trainable_annual_group_count"].sum()) if not target_diagnostics.empty else 0
    if trainable_groups <= 0:
        failures.append("no_trainable_annual_groups")
    elif trainable_groups < min_trainable_annual_groups:
        warnings.append(f"trainable_annual_groups_below_{min_trainable_annual_groups}")

    event_groups = int(target_diagnostics["event_group_count"].sum()) if not target_diagnostics.empty else 0
    if event_groups == 0:
        warnings.append("no_target_events_observed")
    elif event_groups < min_event_groups:
        warnings.append(f"event_groups_below_{min_event_groups}")

    if feature_quality.empty:
        warnings.append("no_feature_quality_rows")
    else:
        all_missing_count = int((feature_quality["quality_bucket"] == "all_missing").sum())
        constant_count = int((feature_quality["quality_bucket"] == "constant").sum())
        sparse_count = int(feature_quality["quality_bucket"].isin({"all_missing", "ultra_sparse", "sparse"}).sum())
        sparse_share = float(sparse_count / len(feature_quality)) if len(feature_quality) else 0.0
        if all_missing_count:
            warnings.append("all_missing_features_present")
        if constant_count:
            warnings.append("constant_features_present")
        if sparse_share > max_sparse_feature_share:
            warnings.append("sparse_feature_share_high")

    status = "fail" if failures else ("warn" if warnings else "pass")
    return {
        "status": status,
        "failures": failures,
        "warnings": warnings,
        "trainable_annual_group_count": trainable_groups,
        "event_group_count": event_groups,
    }


def diagnose_wasde_snapshot_matrix(
    matrix: pd.DataFrame,
    *,
    feature_columns: Iterable[str] | None = None,
    static_manifest: pd.DataFrame | None = None,
    min_trainable_annual_groups: int = 20,
    min_event_groups: int = 5,
    max_sparse_feature_share: float = 0.5,
) -> WasdeSnapshotDiagnosticsReport:
    """Run the full Phase 6 diagnostics gate for one snapshot matrix."""
    features = _feature_columns(matrix, feature_columns)
    integrity = build_matrix_integrity_report(matrix)
    leakage = audit_wasde_snapshot_leakage(
        matrix,
        feature_columns=features,
        static_manifest=static_manifest,
    )
    quality = build_feature_quality_report(
        matrix,
        feature_columns=features,
        static_manifest=static_manifest,
    )
    targets = build_target_event_diagnostics(matrix)
    baselines = build_baseline_diagnostics(matrix)
    readiness = build_readiness_decision(
        integrity=integrity,
        leakage_issues=leakage,
        feature_quality=quality,
        target_diagnostics=targets,
        min_trainable_annual_groups=min_trainable_annual_groups,
        min_event_groups=min_event_groups,
        max_sparse_feature_share=max_sparse_feature_share,
    )
    return WasdeSnapshotDiagnosticsReport(
        integrity=integrity,
        leakage_issues=leakage,
        feature_quality=quality,
        target_diagnostics=targets,
        baseline_diagnostics=baselines,
        readiness=readiness,
    )
