"""Grouped walk-forward CV for WASDE snapshot model-ready matrices."""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.base import clone

from leviathan.model_datasets.wasde_snapshot_diagnostics import (
    BASELINE_COLUMNS,
    build_baseline_diagnostics,
)
from leviathan.model_datasets.wasde_snapshot_model_ready import (
    TARGET_LEAKAGE_COLUMNS,
    TARGET_LEAKAGE_PREFIXES,
)
from leviathan.model_datasets.wasde_snapshot_targets import GROUP_KEY as TARGET_GROUP_KEY

SUPPORTED_FEATURE_STACKS = (
    "static_snapshot_context",
    "wasde_monthly_revision",
    "preseason_static_plus_wasde_revision",
)

PREDICTION_ID_COLUMNS = [
    "dataset_key",
    "contract_key",
    "origin_key",
    "target_market_year",
    "target_key",
    "as_of_date",
    "snapshot_stage",
    "cv_group",
    "cv_time",
]


@dataclass(frozen=True)
class SnapshotFeatureSelection:
    """Selected and dropped features for one snapshot feature stack."""

    feature_stack_id: str
    selected_features: tuple[str, ...]
    dropped_features: pd.DataFrame


@dataclass(frozen=True)
class SnapshotCVFold:
    """One grouped walk-forward split."""

    test_year: int
    train_years: tuple[int, ...]
    test_years: tuple[int, ...]
    train_index: tuple[int, ...]
    test_index: tuple[int, ...]
    n_train_rows: int
    n_test_rows: int
    n_train_groups: int
    n_test_groups: int


@dataclass(frozen=True)
class SnapshotCVResult:
    """Result of one WASDE snapshot CV smoke."""

    feature_stack_id: str
    model_name: str
    feature_columns: tuple[str, ...]
    folds: tuple[SnapshotCVFold, ...]
    predictions: pd.DataFrame
    snapshot_metrics: dict[str, float]
    annual_metrics: dict[str, float]
    baseline_diagnostics: pd.DataFrame
    dropped_features: pd.DataFrame


def _feature_candidates(matrix: pd.DataFrame, feature_columns: Iterable[str] | None) -> list[str]:
    if feature_columns is not None:
        return [str(feature) for feature in feature_columns]
    excluded = set(PREDICTION_ID_COLUMNS) | set(TARGET_GROUP_KEY) | set(BASELINE_COLUMNS.values()) | {
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
    }
    return [
        str(col)
        for col in matrix.columns
        if str(col) not in excluded
        and not str(col).startswith(TARGET_LEAKAGE_PREFIXES)
    ]


def _is_numeric_feature(series: pd.Series) -> bool:
    return bool(pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series))


def ensure_snapshot_cv_columns(matrix: pd.DataFrame) -> pd.DataFrame:
    """Return a matrix with deterministic grouped-CV helper columns.

    Older snapshot model-ready versions may have the natural target group but
    not the convenience CV columns.  The safe policy is to derive them from the
    annual outcome group and weight snapshots so each annual outcome contributes
    one total unit of weight.
    """
    required = set(TARGET_GROUP_KEY)
    missing_group = required - set(matrix.columns)
    if missing_group:
        raise ValueError(f"snapshot matrix missing target group columns: {sorted(missing_group)}")
    out = matrix.copy()
    if "cv_group" not in out.columns:
        out["cv_group"] = out[list(TARGET_GROUP_KEY)].astype(str).agg("|".join, axis=1)
    if "cv_time" not in out.columns:
        out["cv_time"] = pd.to_numeric(out["target_market_year"], errors="coerce")
    if "sample_weight" not in out.columns:
        counts = out.groupby(list(TARGET_GROUP_KEY), dropna=False)["as_of_date"].transform("count")
        counts = pd.to_numeric(counts, errors="coerce").replace(0, np.nan)
        out["sample_weight"] = 1.0 / counts
    return out


def resolve_snapshot_feature_stack_id(
    feature_set_id: str,
    explicit_stack_id: str | None = None,
) -> str:
    """Resolve a governed feature-set id to a snapshot CV stack policy.

    Model-ready feature sets describe what columns are eligible.  Snapshot CV
    stack ids describe the extra pruning rule used for a smoke/certification
    run.  This resolver keeps Batch submitters compact while still making the
    policy explicit in reports.
    """
    if explicit_stack_id and explicit_stack_id.lower() not in {"", "auto", "none", "null"}:
        if explicit_stack_id not in SUPPORTED_FEATURE_STACKS:
            raise ValueError(
                f"unsupported WASDE snapshot feature stack {explicit_stack_id!r}; "
                f"expected one of {SUPPORTED_FEATURE_STACKS}"
            )
        return explicit_stack_id
    normalized = str(feature_set_id)
    if normalized == "wasde_monthly_revision":
        return "wasde_monthly_revision"
    if "wasde" in normalized:
        return "preseason_static_plus_wasde_revision"
    return "static_snapshot_context"


def select_snapshot_feature_stack(
    matrix: pd.DataFrame,
    *,
    feature_stack_id: str,
    feature_columns: Iterable[str] | None = None,
    min_non_null_rate: float = 0.2,
    drop_constant: bool = True,
) -> SnapshotFeatureSelection:
    """Select and prune feature columns for a Phase 7 snapshot smoke."""
    if feature_stack_id not in SUPPORTED_FEATURE_STACKS:
        raise ValueError(
            f"unsupported WASDE snapshot feature stack {feature_stack_id!r}; "
            f"expected one of {SUPPORTED_FEATURE_STACKS}"
        )
    candidates = _feature_candidates(matrix, feature_columns)
    rows: list[dict[str, object]] = []
    selected: list[str] = []
    for feature in candidates:
        reason = ""
        if feature not in matrix.columns:
            reason = "missing_from_matrix"
        elif feature.startswith(TARGET_LEAKAGE_PREFIXES) or feature in TARGET_LEAKAGE_COLUMNS:
            reason = "leakage_like_name"
        elif feature_stack_id == "wasde_monthly_revision" and not feature.startswith("wasde_"):
            reason = "not_wasde_revision_feature"
        elif feature_stack_id == "static_snapshot_context" and feature.startswith("wasde_"):
            reason = "not_static_snapshot_feature"
        elif not _is_numeric_feature(matrix[feature]):
            reason = "non_numeric"
        else:
            non_null_rate = float(matrix[feature].notna().mean()) if len(matrix) else 0.0
            unique_count = int(matrix[feature].dropna().nunique())
            if non_null_rate == 0.0:
                reason = "all_missing"
            elif non_null_rate < float(min_non_null_rate):
                reason = "too_sparse"
            elif drop_constant and unique_count <= 1:
                reason = "constant"
            else:
                selected.append(feature)
                reason = "selected"
        rows.append({
            "feature": feature,
            "decision": "selected" if reason == "selected" else "dropped",
            "reason": reason,
            "non_null_rate": (
                float(matrix[feature].notna().mean())
                if feature in matrix.columns and len(matrix) else np.nan
            ),
            "unique_value_count": (
                int(matrix[feature].dropna().nunique())
                if feature in matrix.columns else 0
            ),
        })
    dropped = pd.DataFrame(rows).sort_values(["decision", "feature"]).reset_index(drop=True)
    selected_tuple = tuple(sorted(selected))
    if not selected_tuple:
        raise ValueError(f"feature stack {feature_stack_id} selected zero usable features")
    return SnapshotFeatureSelection(feature_stack_id, selected_tuple, dropped)


def _group_keys(frame: pd.DataFrame) -> set[tuple[object, ...]]:
    return {
        tuple(row)
        for row in frame[TARGET_GROUP_KEY].drop_duplicates().itertuples(index=False, name=None)
    }


def grouped_walk_forward_splits(
    matrix: pd.DataFrame,
    *,
    min_train_years: int = 5,
    cv_time_col: str = "cv_time",
    train_start_year: int | None = None,
) -> tuple[SnapshotCVFold, ...]:
    """Return grouped expanding walk-forward splits by annual outcome year."""
    required = set(TARGET_GROUP_KEY) | {cv_time_col}
    missing = required - set(matrix.columns)
    if missing:
        raise ValueError(f"snapshot matrix missing CV split columns: {sorted(missing)}")
    data = matrix.copy()
    data[cv_time_col] = pd.to_numeric(data[cv_time_col], errors="coerce")
    data = data.dropna(subset=[cv_time_col]).copy()
    data[cv_time_col] = data[cv_time_col].astype(int)
    years = sorted(int(year) for year in data[cv_time_col].unique())
    if len(years) < min_train_years + 1:
        raise ValueError(
            "grouped WASDE snapshot CV needs at least "
            f"{min_train_years + 1} unique {cv_time_col} values; got {len(years)}"
        )
    folds: list[SnapshotCVFold] = []
    for test_year in years:
        train_years = [year for year in years if year < test_year]
        if train_start_year is not None:
            train_years = [year for year in train_years if year >= int(train_start_year)]
        if len(train_years) < min_train_years:
            continue
        train_mask = data[cv_time_col].isin(set(train_years))
        test_mask = data[cv_time_col] == test_year
        train_df = data.loc[train_mask]
        test_df = data.loc[test_mask]
        overlap = _group_keys(train_df) & _group_keys(test_df)
        if overlap:
            raise ValueError(f"group leakage across train/test split for {test_year}: {list(overlap)[:5]}")
        folds.append(SnapshotCVFold(
            test_year=int(test_year),
            train_years=tuple(int(year) for year in train_years),
            test_years=(int(test_year),),
            train_index=tuple(int(idx) for idx in train_df.index),
            test_index=tuple(int(idx) for idx in test_df.index),
            n_train_rows=int(len(train_df)),
            n_test_rows=int(len(test_df)),
            n_train_groups=int(len(_group_keys(train_df))),
            n_test_groups=int(len(_group_keys(test_df))),
        ))
    if not folds:
        raise ValueError("grouped WASDE snapshot CV produced no folds")
    return tuple(folds)


def _fit_model(model: object, x_train: pd.DataFrame, y_train: pd.Series, sample_weight: pd.Series | None) -> object:
    try:
        estimator = clone(model)
    except Exception:  # noqa: BLE001
        estimator = model
    if sample_weight is None:
        estimator.fit(x_train, y_train)
        return estimator
    try:
        params = inspect.signature(estimator.fit).parameters
        if "sample_weight" in params:
            estimator.fit(x_train, y_train, sample_weight=sample_weight)
        else:
            estimator.fit(x_train, y_train)
    except (TypeError, ValueError):
        estimator.fit(x_train, y_train)
    return estimator


def _fold_usable_features(
    train_df: pd.DataFrame,
    features: Iterable[str],
    *,
    min_non_null_rate: float,
) -> tuple[str, ...]:
    usable: list[str] = []
    for feature in features:
        if feature not in train_df.columns:
            continue
        series = train_df[feature]
        non_null_rate = float(series.notna().mean()) if len(series) else 0.0
        if non_null_rate < float(min_non_null_rate):
            continue
        if int(series.dropna().nunique()) <= 1:
            continue
        usable.append(feature)
    return tuple(usable)


def _weighted_metrics(y_true: pd.Series, y_pred: pd.Series, weights: pd.Series | None = None) -> dict[str, float]:
    valid = y_true.notna() & y_pred.notna()
    if not valid.any():
        return {"n": 0.0, "mae": np.nan, "rmse": np.nan, "sign_accuracy": np.nan}
    y = y_true.loc[valid].astype(float)
    pred = y_pred.loc[valid].astype(float)
    w = weights.loc[valid].astype(float) if weights is not None else pd.Series(1.0, index=y.index)
    w_sum = float(w.sum())
    if not np.isfinite(w_sum) or w_sum <= 0:
        w = pd.Series(1.0, index=y.index)
        w_sum = float(w.sum())
    err = pred - y
    mae = float((np.abs(err) * w).sum() / w_sum)
    rmse = float(np.sqrt(((err ** 2) * w).sum() / w_sum))
    sign_accuracy = float((np.sign(y) == np.sign(pred)).mean()) if len(y) else np.nan
    return {"n": float(len(y)), "mae": mae, "rmse": rmse, "sign_accuracy": sign_accuracy}


def _event_prediction(y_pred: pd.Series, threshold: pd.Series, direction: pd.Series) -> pd.Series:
    out: list[bool] = []
    for pred, thresh, direct in zip(y_pred, threshold, direction):
        try:
            pred_f = float(pred)
            thresh_f = abs(float(thresh))
        except Exception:  # noqa: BLE001
            out.append(False)
            continue
        if not np.isfinite(pred_f) or not np.isfinite(thresh_f):
            out.append(False)
        elif str(direct) == "higher_is_stress":
            out.append(pred_f >= thresh_f)
        else:
            out.append(pred_f <= -thresh_f)
    return pd.Series(out, index=y_pred.index, dtype=bool)


def collapse_snapshot_predictions(
    predictions: pd.DataFrame,
    *,
    policy: str = "latest",
) -> pd.DataFrame:
    """Collapse snapshot-row predictions to one row per annual outcome group."""
    if predictions.empty:
        return predictions.copy()
    if policy not in {"latest", "mean", "weighted_mean"}:
        raise ValueError("prediction collapse policy must be latest, mean, or weighted_mean")
    ordered = predictions.sort_values([*TARGET_GROUP_KEY, "as_of_date"])
    if policy == "latest":
        return ordered.groupby(TARGET_GROUP_KEY, dropna=False, as_index=False).tail(1).reset_index(drop=True)
    if policy == "mean":
        grouped = ordered.groupby(TARGET_GROUP_KEY, dropna=False, as_index=False)
        base = grouped.tail(1).drop(columns=["y_pred"]).reset_index(drop=True)
        means = grouped["y_pred"].mean()
        return base.merge(means, on=TARGET_GROUP_KEY, how="left", validate="one_to_one")
    grouped_rows: list[pd.Series] = []
    for _, group in ordered.groupby(TARGET_GROUP_KEY, dropna=False):
        row = group.tail(1).iloc[0].copy()
        weights = pd.to_numeric(group.get("sample_weight", pd.Series(1.0, index=group.index)), errors="coerce").fillna(0.0)
        preds = pd.to_numeric(group["y_pred"], errors="coerce")
        if float(weights.sum()) > 0:
            row["y_pred"] = float((preds * weights).sum() / weights.sum())
        else:
            row["y_pred"] = float(preds.mean())
        grouped_rows.append(row)
    return pd.DataFrame(grouped_rows).reset_index(drop=True)


def score_snapshot_predictions(
    predictions: pd.DataFrame,
    *,
    collapse_policy: str = "latest",
) -> tuple[dict[str, float], dict[str, float]]:
    """Return snapshot-row and annual-group metrics for predictions."""
    snapshot_metrics = _weighted_metrics(
        predictions["y_actual"],
        predictions["y_pred"],
        predictions["sample_weight"] if "sample_weight" in predictions.columns else None,
    )
    annual = collapse_snapshot_predictions(predictions, policy=collapse_policy)
    annual_metrics = _weighted_metrics(annual["y_actual"], annual["y_pred"])
    if "target_event_label" in annual.columns:
        event_rows = annual.loc[annual["target_event_label"].notna()].copy()
        if not event_rows.empty:
            actual_event = event_rows["target_event_label"].fillna(False).astype(bool)
            pred_event = _event_prediction(
                event_rows["y_pred"],
                event_rows["target_event_threshold"],
                event_rows["target_event_direction"],
            )
            tp = int((actual_event & pred_event).sum())
            fn = int((actual_event & ~pred_event).sum())
            fp = int((~actual_event & pred_event).sum())
            event_count = int(actual_event.sum())
            pred_count = int(pred_event.sum())
            recall = float(tp / event_count) if event_count else np.nan
            precision = float(tp / pred_count) if pred_count else np.nan
            denom = (4 * precision) + recall
            f2 = float((5 * precision * recall) / denom) if np.isfinite(precision) and np.isfinite(recall) and denom else np.nan
            annual_metrics.update({
                "event_count": float(event_count),
                "predicted_event_count": float(pred_count),
                "true_positive_count": float(tp),
                "false_negative_count": float(fn),
                "false_positive_count": float(fp),
                "recall": recall,
                "precision": precision,
                "f2_score": f2,
            })
    return snapshot_metrics, annual_metrics


def run_grouped_walk_forward_cv(
    matrix: pd.DataFrame,
    *,
    model: object,
    feature_stack_id: str,
    feature_columns: Iterable[str] | None = None,
    target_col: str = "target_value",
    min_train_years: int = 5,
    min_non_null_rate: float = 0.2,
    train_start_year: int | None = None,
    collapse_policy: str = "latest",
) -> SnapshotCVResult:
    """Train/evaluate one model with grouped walk-forward snapshot CV."""
    if target_col not in matrix.columns:
        raise ValueError(f"target column {target_col!r} missing from snapshot matrix")
    data = ensure_snapshot_cv_columns(matrix)
    if "is_trainable" in data.columns:
        data = data.loc[data["is_trainable"].fillna(False).astype(bool)].copy()
    data = data.loc[data[target_col].notna()].copy()
    if data.empty:
        raise ValueError("WASDE snapshot CV has no trainable target rows")
    selection = select_snapshot_feature_stack(
        data,
        feature_stack_id=feature_stack_id,
        feature_columns=feature_columns,
        min_non_null_rate=min_non_null_rate,
    )
    folds = grouped_walk_forward_splits(
        data,
        min_train_years=min_train_years,
        train_start_year=train_start_year,
    )
    prediction_frames: list[pd.DataFrame] = []
    for fold in folds:
        train_df = data.loc[list(fold.train_index)].copy()
        test_df = data.loc[list(fold.test_index)].copy()
        fold_features = _fold_usable_features(
            train_df,
            selection.selected_features,
            min_non_null_rate=min_non_null_rate,
        )
        if not fold_features:
            raise ValueError(
                f"fold {fold.test_year} has zero usable features after fold-local pruning"
            )
        estimator = _fit_model(
            model,
            train_df[list(fold_features)],
            train_df[target_col].astype(float),
            train_df["sample_weight"].astype(float) if "sample_weight" in train_df.columns else None,
        )
        y_pred = estimator.predict(test_df[list(fold_features)])
        cols = [col for col in PREDICTION_ID_COLUMNS if col in test_df.columns]
        extra_cols = [
            col for col in (
                "target_event_label",
                "target_event_threshold",
                "target_event_direction",
                "sample_weight",
            ) if col in test_df.columns
        ]
        pred = test_df[cols + extra_cols].copy()
        pred["y_actual"] = test_df[target_col].astype(float).to_numpy()
        pred["y_pred"] = np.asarray(y_pred, dtype=float)
        pred["fold_test_year"] = fold.test_year
        pred["fold_feature_count"] = len(fold_features)
        prediction_frames.append(pred)
    if not prediction_frames:
        raise ValueError("WASDE snapshot CV produced no predictions")
    predictions = pd.concat(prediction_frames, ignore_index=True)
    snapshot_metrics, annual_metrics = score_snapshot_predictions(
        predictions,
        collapse_policy=collapse_policy,
    )
    baseline_source = matrix.merge(
        predictions[[*TARGET_GROUP_KEY]].drop_duplicates(),
        on=TARGET_GROUP_KEY,
        how="inner",
    )
    baseline_diagnostics = build_baseline_diagnostics(baseline_source)
    model_name = type(model).__name__
    return SnapshotCVResult(
        feature_stack_id=feature_stack_id,
        model_name=model_name,
        feature_columns=selection.selected_features,
        folds=folds,
        predictions=predictions,
        snapshot_metrics=snapshot_metrics,
        annual_metrics=annual_metrics,
        baseline_diagnostics=baseline_diagnostics,
        dropped_features=selection.dropped_features,
    )
