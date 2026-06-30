"""Rolling backtest evaluation for WASDE snapshot anomaly scores."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from leviathan.model_datasets.wasde_snapshot_anomaly_scores import (
    SNAPSHOT_SCORE_ID_COLUMNS,
)
from leviathan.model_datasets.wasde_snapshot_diagnostics import BASELINE_COLUMNS
from leviathan.model_datasets.wasde_snapshot_targets import GROUP_KEY as TARGET_GROUP_KEY

EVAL_JOIN_COLUMNS = SNAPSHOT_SCORE_ID_COLUMNS

SNAPSHOT_DETECTOR_COLUMNS = [
    *SNAPSHOT_SCORE_ID_COLUMNS,
    "detector_id",
    "score_value",
    "component_count",
    "non_null_component_count",
    "source_attribute_count",
    "source_features",
    "target_event_label",
    "target_value",
    "target_event_threshold",
    "target_event_direction",
    "is_trainable",
    "sample_weight",
    "cv_group",
    "cv_time",
]

FOLD_METRIC_COLUMNS = [
    "target_key",
    "detector_id",
    "fold_id",
    "test_year",
    "threshold_policy",
    "threshold",
    "threshold_metric",
    "train_group_count",
    "test_group_count",
    "event_count",
    "alert_group_count",
    "true_positive_count",
    "false_negative_count",
    "false_positive_count",
    "event_recall_any_alert",
    "annual_precision_any_alert",
    "annual_f2_any_alert",
    "top_20pct_precision",
    "average_precision",
    "median_first_alert_lead_days",
    "snapshot_alert_rate",
]

THRESHOLD_COLUMNS = [
    "target_key",
    "detector_id",
    "fold_id",
    "test_year",
    "threshold_policy",
    "threshold",
    "selected_metric",
    "selected_recall",
    "selected_precision",
    "selected_false_positive_rate",
    "threshold_floor",
    "min_persistent_releases",
    "train_group_count",
    "candidate_count",
]

OOF_PREDICTION_COLUMNS = [
    *SNAPSHOT_SCORE_ID_COLUMNS,
    "detector_id",
    "fold_id",
    "threshold_policy",
    "threshold",
    "score_value",
    "raw_alert",
    "alert",
    "target_event_label",
    "target_value",
    "target_event_threshold",
    "target_event_direction",
    "sample_weight",
]

BASELINE_COMPARISON_COLUMNS = [
    "target_key",
    "baseline_name",
    "n_groups",
    "event_count",
    "predicted_event_count",
    "true_positive_count",
    "false_negative_count",
    "false_positive_count",
    "recall",
    "precision",
    "f2_score",
]

THRESHOLD_POLICIES = {
    "legacy_f2",
    "precision_guarded_f2",
    "recall_with_fp_budget",
}


@dataclass(frozen=True)
class WasdeSnapshotAnomalyBacktestResult:
    """Container for Phase 2 rolling evaluation outputs."""

    snapshot_detector_scores: pd.DataFrame
    fold_metrics: pd.DataFrame
    thresholds: pd.DataFrame
    oof_predictions: pd.DataFrame
    annual_alert_cases: pd.DataFrame
    baseline_comparison: pd.DataFrame
    report: dict[str, object]


def _as_bool(series: pd.Series) -> pd.Series:
    return series.fillna(False).astype(bool)


def _safe_float(value: object) -> float:
    try:
        out = float(value)
    except Exception:  # noqa: BLE001
        return np.nan
    return out if np.isfinite(out) else np.nan


def _f2_score(recall: float, precision: float) -> float:
    if not np.isfinite(recall) or not np.isfinite(precision):
        return np.nan
    denom = (4.0 * precision) + recall
    return float((5.0 * precision * recall) / denom) if denom else np.nan


def _average_precision(y_true: pd.Series, scores: pd.Series) -> float:
    valid = y_true.notna() & scores.notna()
    if not valid.any():
        return np.nan
    y = _as_bool(y_true.loc[valid])
    s = pd.to_numeric(scores.loc[valid], errors="coerce")
    if int(y.sum()) == 0:
        return np.nan
    ordered = pd.DataFrame({"y": y, "score": s}).sort_values("score", ascending=False)
    tp = ordered["y"].cumsum()
    precision = tp / np.arange(1, len(ordered) + 1)
    return float((precision * ordered["y"]).sum() / int(ordered["y"].sum()))


def _precision_at_top_quantile(y_true: pd.Series, scores: pd.Series, quantile: float) -> float:
    valid = y_true.notna() & scores.notna()
    if not valid.any():
        return np.nan
    frame = pd.DataFrame({
        "y": _as_bool(y_true.loc[valid]),
        "score": pd.to_numeric(scores.loc[valid], errors="coerce"),
    }).sort_values("score", ascending=False)
    top_n = max(1, int(np.ceil(len(frame) * float(quantile))))
    return float(frame.head(top_n)["y"].mean())


def _binary_event_metrics(actual_event: pd.Series, predicted_event: pd.Series) -> dict[str, float]:
    actual = _as_bool(actual_event)
    pred = _as_bool(predicted_event)
    tp = int((actual & pred).sum())
    fn = int((actual & ~pred).sum())
    fp = int((~actual & pred).sum())
    event_count = int(actual.sum())
    pred_count = int(pred.sum())
    recall = float(tp / event_count) if event_count else np.nan
    precision = float(tp / pred_count) if pred_count else np.nan
    return {
        "event_count": event_count,
        "alert_group_count": pred_count,
        "true_positive_count": tp,
        "false_negative_count": fn,
        "false_positive_count": fp,
        "event_recall_any_alert": recall,
        "annual_precision_any_alert": precision,
        "annual_f2_any_alert": _f2_score(recall, precision),
    }


def prepare_score_evaluation_frame(scores: pd.DataFrame, matrix: pd.DataFrame) -> pd.DataFrame:
    """Join long score rows to target labels, weights, and baseline metadata."""
    missing_scores = sorted(set(EVAL_JOIN_COLUMNS) - set(scores.columns))
    missing_matrix = sorted(set(EVAL_JOIN_COLUMNS) - set(matrix.columns))
    if missing_scores:
        raise ValueError(f"score frame missing columns: {missing_scores}")
    if missing_matrix:
        raise ValueError(f"matrix frame missing columns: {missing_matrix}")

    metadata_cols = [
        col
        for col in [
            *EVAL_JOIN_COLUMNS,
            "target_event_label",
            "target_value",
            "target_event_threshold",
            "target_event_direction",
            "is_trainable",
            "sample_weight",
            "cv_group",
            "cv_time",
            *BASELINE_COLUMNS.values(),
        ]
        if col in matrix.columns
    ]
    metadata = matrix[metadata_cols].drop_duplicates(EVAL_JOIN_COLUMNS).copy()
    out = scores.copy()
    out["as_of_date"] = pd.to_datetime(out["as_of_date"], errors="coerce")
    out["target_market_year"] = pd.to_numeric(out["target_market_year"], errors="coerce")
    metadata["as_of_date"] = pd.to_datetime(metadata["as_of_date"], errors="coerce")
    metadata["target_market_year"] = pd.to_numeric(
        metadata["target_market_year"], errors="coerce"
    )
    joined = out.merge(
        metadata,
        on=EVAL_JOIN_COLUMNS,
        how="left",
        validate="many_to_one",
    )
    if "target_event_label" in joined.columns:
        joined["target_event_label"] = joined["target_event_label"].astype("boolean")
    if "is_trainable" in joined.columns:
        joined["is_trainable"] = _as_bool(joined["is_trainable"])
    else:
        joined["is_trainable"] = True
    if "sample_weight" not in joined.columns:
        joined["sample_weight"] = 1.0
    return joined


def aggregate_snapshot_detector_scores(evaluation_frame: pd.DataFrame) -> pd.DataFrame:
    """Collapse component-level scores to one score per snapshot/target/detector."""
    if evaluation_frame.empty:
        return pd.DataFrame(columns=SNAPSHOT_DETECTOR_COLUMNS)
    usable = evaluation_frame.loc[
        evaluation_frame["detector_id"].astype(str) != "missing_input"
    ].copy()
    if usable.empty:
        return pd.DataFrame(columns=SNAPSHOT_DETECTOR_COLUMNS)
    usable["score_value"] = pd.to_numeric(usable["score_value"], errors="coerce")
    group_cols = [*SNAPSHOT_SCORE_ID_COLUMNS, "detector_id"]
    usable["_nonnull_attribute"] = usable["source_attribute"].where(usable["score_value"].notna())
    aggregated = (
        usable.groupby(group_cols, dropna=False, sort=True)
        .agg(
            score_value=("score_value", "max"),
            component_count=("component_count", "max"),
            non_null_component_count=("score_value", "count"),
            source_attribute_count=("_nonnull_attribute", "nunique"),
            target_event_label=("target_event_label", "first"),
            target_value=("target_value", "first"),
            target_event_threshold=("target_event_threshold", "first"),
            target_event_direction=("target_event_direction", "first"),
            is_trainable=("is_trainable", "first"),
            sample_weight=("sample_weight", "first"),
            cv_group=("cv_group", "first"),
            cv_time=("cv_time", "first"),
        )
        .reset_index()
    )
    aggregated["source_features"] = ""
    return aggregated.reindex(columns=SNAPSHOT_DETECTOR_COLUMNS).sort_values(
        [*SNAPSHOT_SCORE_ID_COLUMNS, "detector_id"]
    ).reset_index(drop=True)


def validate_snapshot_weights(snapshot_scores: pd.DataFrame) -> pd.DataFrame:
    """Return annual groups whose snapshot weights do not sum to one."""
    if snapshot_scores.empty:
        return pd.DataFrame(columns=[*TARGET_GROUP_KEY, "weight_sum", "row_count"])
    required = set(TARGET_GROUP_KEY) | {"sample_weight"}
    missing = sorted(required - set(snapshot_scores.columns))
    if missing:
        raise ValueError(f"snapshot scores missing weight columns: {missing}")
    unique = snapshot_scores.drop_duplicates([*EVAL_JOIN_COLUMNS, "detector_id"]).copy()
    grouped = (
        unique.groupby([*TARGET_GROUP_KEY, "detector_id"], dropna=False)
        .agg(weight_sum=("sample_weight", "sum"), row_count=("sample_weight", "size"))
        .reset_index()
    )
    return grouped.loc[~np.isclose(grouped["weight_sum"].astype(float), 1.0, atol=1e-6)]


def _candidate_thresholds(
    valid_scores: pd.Series,
    *,
    candidate_quantiles: Iterable[float],
    threshold_floor: float | None,
) -> list[float]:
    scores = pd.to_numeric(valid_scores, errors="coerce").dropna()
    if scores.empty:
        return []
    candidates = {
        float(scores.quantile(float(q)))
        for q in candidate_quantiles
    }
    floor = _safe_float(threshold_floor)
    if np.isfinite(floor):
        candidates = {max(candidate, floor) for candidate in candidates}
        candidates.add(float(floor))
    return sorted(candidate for candidate in candidates if np.isfinite(candidate))


def _apply_alert_policy(
    snapshots: pd.DataFrame,
    *,
    threshold: float,
    min_persistent_releases: int = 1,
) -> pd.DataFrame:
    out = snapshots.copy()
    score = pd.to_numeric(out["score_value"], errors="coerce")
    out["threshold"] = float(threshold) if np.isfinite(_safe_float(threshold)) else np.nan
    out["raw_alert"] = score >= out["threshold"]
    if int(min_persistent_releases) <= 1 or out.empty:
        out["alert"] = out["raw_alert"]
        return out
    out = out.sort_values([*TARGET_GROUP_KEY, "detector_id", "as_of_date"]).copy()
    out["_raw_alert_count"] = (
        out["raw_alert"].astype(int)
        .groupby([out[col] for col in [*TARGET_GROUP_KEY, "detector_id"]])
        .cumsum()
    )
    out["alert"] = out["raw_alert"] & (
        out["_raw_alert_count"] >= int(min_persistent_releases)
    )
    return out.drop(columns=["_raw_alert_count"])


def _candidate_metric_row(
    annual: pd.DataFrame,
    *,
    threshold: float,
    threshold_policy: str,
    min_precision: float,
    max_false_positive_rate: float,
) -> dict[str, float | bool]:
    metrics = _binary_event_metrics(annual["target_event_label"], annual["any_alert"])
    non_event_count = max(0, int(len(annual)) - int(metrics["event_count"]))
    false_positive_rate = (
        float(metrics["false_positive_count"] / non_event_count)
        if non_event_count else np.nan
    )
    precision = metrics["annual_precision_any_alert"]
    recall = metrics["event_recall_any_alert"]
    f2 = metrics["annual_f2_any_alert"]
    if threshold_policy == "legacy_f2":
        eligible = True
        objective = f2
    elif threshold_policy == "precision_guarded_f2":
        eligible = bool(np.isfinite(precision) and precision >= float(min_precision))
        objective = f2
    elif threshold_policy == "recall_with_fp_budget":
        eligible = bool(
            np.isfinite(false_positive_rate)
            and false_positive_rate <= float(max_false_positive_rate)
        )
        objective = recall
    else:
        raise ValueError(
            f"threshold_policy must be one of {sorted(THRESHOLD_POLICIES)}, "
            f"got {threshold_policy!r}"
        )
    return {
        "threshold": float(threshold),
        "objective": _safe_float(objective),
        "eligible": eligible,
        "recall": _safe_float(recall),
        "precision": _safe_float(precision),
        "f2": _safe_float(f2),
        "false_positive_rate": _safe_float(false_positive_rate),
        "false_positive_count": int(metrics["false_positive_count"]),
    }


def _select_alert_threshold_details(
    train_snapshots: pd.DataFrame,
    *,
    candidate_quantiles: Iterable[float] = (0.50, 0.60, 0.70, 0.80, 0.90),
    threshold_policy: str = "legacy_f2",
    min_precision: float = 0.0,
    max_false_positive_rate: float = 1.0,
    min_persistent_releases: int = 1,
    threshold_floor: float | None = None,
) -> dict[str, float | int | str]:
    valid = train_snapshots.loc[
        pd.to_numeric(train_snapshots["score_value"], errors="coerce").notna()
        & train_snapshots["target_event_label"].notna()
    ].copy()
    if valid.empty:
        return {
            "threshold": np.nan,
            "selected_metric": np.nan,
            "candidate_count": 0,
            "selected_recall": np.nan,
            "selected_precision": np.nan,
            "selected_false_positive_rate": np.nan,
        }
    valid["score_value"] = pd.to_numeric(valid["score_value"], errors="coerce")
    candidates = _candidate_thresholds(
        valid["score_value"],
        candidate_quantiles=candidate_quantiles,
        threshold_floor=threshold_floor,
    )
    if not candidates:
        return {
            "threshold": np.nan,
            "selected_metric": np.nan,
            "candidate_count": 0,
            "selected_recall": np.nan,
            "selected_precision": np.nan,
            "selected_false_positive_rate": np.nan,
        }

    scored: list[dict[str, float | bool]] = []
    for threshold in candidates:
        trial = _apply_alert_policy(
            valid,
            threshold=threshold,
            min_persistent_releases=min_persistent_releases,
        )
        annual = _annual_alert_frame(trial)
        scored.append(
            _candidate_metric_row(
                annual,
                threshold=threshold,
                threshold_policy=threshold_policy,
                min_precision=min_precision,
                max_false_positive_rate=max_false_positive_rate,
            )
        )
    eligible = [row for row in scored if bool(row["eligible"])]
    if threshold_policy == "recall_with_fp_budget":
        sort_key = lambda row: (
            _safe_float(row["recall"]),
            _safe_float(row["f2"]),
            -_safe_float(row["false_positive_rate"]),
            _safe_float(row["threshold"]),
        )
    elif threshold_policy == "precision_guarded_f2":
        sort_key = lambda row: (
            _safe_float(row["f2"]),
            _safe_float(row["recall"]),
            _safe_float(row["precision"]),
            _safe_float(row["threshold"]),
        )
    else:
        sort_key = lambda row: (
            _safe_float(row["f2"]),
            _safe_float(row["recall"]),
            _safe_float(row["threshold"]),
        )
    if eligible:
        selected = max(eligible, key=sort_key)
    else:
        selected = max(
            scored,
            key=lambda row: (
                _safe_float(row["precision"]),
                -_safe_float(row["false_positive_rate"]),
                _safe_float(row["f2"]),
                _safe_float(row["threshold"]),
            ),
        )
    return {
        "threshold": _safe_float(selected["threshold"]),
        "selected_metric": _safe_float(selected["objective"]),
        "candidate_count": int(len(candidates)),
        "selected_recall": _safe_float(selected["recall"]),
        "selected_precision": _safe_float(selected["precision"]),
        "selected_false_positive_rate": _safe_float(selected["false_positive_rate"]),
    }


def select_alert_threshold(
    train_snapshots: pd.DataFrame,
    *,
    candidate_quantiles: Iterable[float] = (0.50, 0.60, 0.70, 0.80, 0.90),
    threshold_policy: str = "legacy_f2",
    min_precision: float = 0.0,
    max_false_positive_rate: float = 1.0,
    min_persistent_releases: int = 1,
    threshold_floor: float | None = None,
) -> tuple[float, float, int]:
    """Select a score threshold from training snapshots only."""
    details = _select_alert_threshold_details(
        train_snapshots,
        candidate_quantiles=candidate_quantiles,
        threshold_policy=threshold_policy,
        min_precision=min_precision,
        max_false_positive_rate=max_false_positive_rate,
        min_persistent_releases=min_persistent_releases,
        threshold_floor=threshold_floor,
    )
    return (
        _safe_float(details["threshold"]),
        _safe_float(details["selected_metric"]),
        int(details["candidate_count"]),
    )


def _annual_alert_frame(snapshot_predictions: pd.DataFrame) -> pd.DataFrame:
    if snapshot_predictions.empty:
        return pd.DataFrame(columns=[
            *TARGET_GROUP_KEY,
            "detector_id",
            "target_event_label",
            "any_alert",
            "first_alert_date",
            "max_score",
            "snapshot_count",
        ])
    rows: list[dict[str, object]] = []
    for keys, group in snapshot_predictions.groupby([*TARGET_GROUP_KEY, "detector_id"], dropna=False, sort=True):
        values = dict(zip([*TARGET_GROUP_KEY, "detector_id"], keys, strict=False))
        alerts = _as_bool(group["alert"])
        alert_dates = pd.to_datetime(group.loc[alerts, "as_of_date"], errors="coerce")
        rows.append({
            **values,
            "target_event_label": bool(_as_bool(group["target_event_label"]).iloc[0]),
            "any_alert": bool(alerts.any()),
            "first_alert_date": alert_dates.min() if not alert_dates.empty else pd.NaT,
            "max_score": _safe_float(pd.to_numeric(group["score_value"], errors="coerce").max()),
            "snapshot_count": int(len(group)),
        })
    return pd.DataFrame(rows)


def build_rolling_year_splits(
    snapshot_scores: pd.DataFrame,
    *,
    min_train_years: int = 10,
) -> list[dict[str, object]]:
    """Return expanding walk-forward folds by target and detector."""
    if snapshot_scores.empty:
        return []
    folds: list[dict[str, object]] = []
    source = snapshot_scores.loc[
        snapshot_scores["is_trainable"].fillna(False).astype(bool)
        & snapshot_scores["target_event_label"].notna()
    ].copy()
    for (target_key, detector_id), group in source.groupby(["target_key", "detector_id"], dropna=False, sort=True):
        years = sorted(pd.to_numeric(group["target_market_year"], errors="coerce").dropna().astype(int).unique())
        fold_id = 0
        for test_year in years:
            train_years = [year for year in years if year < test_year]
            if len(train_years) < int(min_train_years):
                continue
            train = group.loc[group["target_market_year"].isin(train_years)]
            test = group.loc[group["target_market_year"].astype(int) == int(test_year)]
            if train.empty or test.empty:
                continue
            folds.append({
                "target_key": str(target_key),
                "detector_id": str(detector_id),
                "fold_id": fold_id,
                "test_year": int(test_year),
                "train_index": train.index.to_numpy(),
                "test_index": test.index.to_numpy(),
                "train_group_count": int(train[TARGET_GROUP_KEY].drop_duplicates().shape[0]),
                "test_group_count": int(test[TARGET_GROUP_KEY].drop_duplicates().shape[0]),
            })
            fold_id += 1
    return folds


def build_baseline_comparison(matrix: pd.DataFrame) -> pd.DataFrame:
    """Evaluate materialized annual anomaly baselines on independent groups."""
    if matrix.empty or not set(TARGET_GROUP_KEY).issubset(matrix.columns):
        return pd.DataFrame(columns=BASELINE_COMPARISON_COLUMNS)
    annual = (
        matrix.sort_values([*TARGET_GROUP_KEY, "as_of_date"])
        .groupby(TARGET_GROUP_KEY, dropna=False, as_index=False)
        .first()
    )
    annual = annual.loc[annual.get("is_trainable", True).fillna(False).astype(bool)].copy()
    rows: list[dict[str, object]] = []
    for target_key, group in annual.groupby("target_key", dropna=False, sort=True):
        actual = _as_bool(group["target_event_label"])
        baselines = {"zero_anomaly": pd.Series(0.0, index=group.index)}
        for name, column in BASELINE_COLUMNS.items():
            if column in group.columns:
                baselines[name] = pd.to_numeric(group[column], errors="coerce")
        for baseline_name, values in baselines.items():
            if str(baseline_name) == "zero_anomaly":
                pred_event = pd.Series(False, index=group.index)
            else:
                direction = group["target_event_direction"].astype(str)
                threshold = pd.to_numeric(group["target_event_threshold"], errors="coerce")
                pred_value = pd.to_numeric(values, errors="coerce")
                pred_event = pd.Series(False, index=group.index)
                lower = direction == "lower_is_stress"
                higher = direction == "higher_is_stress"
                pred_event.loc[lower] = pred_value.loc[lower] <= -threshold.loc[lower].abs()
                pred_event.loc[higher] = pred_value.loc[higher] >= threshold.loc[higher].abs()
            metrics = _binary_event_metrics(actual, pred_event)
            rows.append({
                "target_key": str(target_key),
                "baseline_name": str(baseline_name),
                "n_groups": int(len(group)),
                "event_count": metrics["event_count"],
                "predicted_event_count": metrics["alert_group_count"],
                "true_positive_count": metrics["true_positive_count"],
                "false_negative_count": metrics["false_negative_count"],
                "false_positive_count": metrics["false_positive_count"],
                "recall": metrics["event_recall_any_alert"],
                "precision": metrics["annual_precision_any_alert"],
                "f2_score": metrics["annual_f2_any_alert"],
            })
    return pd.DataFrame(rows, columns=BASELINE_COMPARISON_COLUMNS)


def evaluate_wasde_snapshot_anomaly_scores(
    scores: pd.DataFrame,
    matrix: pd.DataFrame,
    *,
    min_train_years: int = 10,
    candidate_quantiles: Iterable[float] = (0.50, 0.60, 0.70, 0.80, 0.90),
    threshold_policy: str = "legacy_f2",
    min_precision: float = 0.0,
    max_false_positive_rate: float = 1.0,
    min_persistent_releases: int = 1,
    detector_threshold_floors: dict[str, float] | None = None,
) -> WasdeSnapshotAnomalyBacktestResult:
    """Run Phase 2 grouped rolling backtest evaluation."""
    if threshold_policy not in THRESHOLD_POLICIES:
        raise ValueError(
            f"threshold_policy must be one of {sorted(THRESHOLD_POLICIES)}, "
            f"got {threshold_policy!r}"
        )
    threshold_floors = {
        str(key): float(value)
        for key, value in (detector_threshold_floors or {}).items()
    }
    evaluation_frame = prepare_score_evaluation_frame(scores, matrix)
    snapshot_scores = aggregate_snapshot_detector_scores(evaluation_frame)
    folds = build_rolling_year_splits(snapshot_scores, min_train_years=min_train_years)
    metric_rows: list[dict[str, object]] = []
    threshold_rows: list[dict[str, object]] = []
    prediction_frames: list[pd.DataFrame] = []

    for fold in folds:
        train = snapshot_scores.loc[fold["train_index"]].copy()
        test = snapshot_scores.loc[fold["test_index"]].copy()
        detector_id = str(fold["detector_id"])
        threshold_floor = threshold_floors.get(detector_id)
        threshold_details = _select_alert_threshold_details(
            train,
            candidate_quantiles=candidate_quantiles,
            threshold_policy=threshold_policy,
            min_precision=min_precision,
            max_false_positive_rate=max_false_positive_rate,
            min_persistent_releases=min_persistent_releases,
            threshold_floor=threshold_floor,
        )
        threshold = _safe_float(threshold_details["threshold"])
        metric = _safe_float(threshold_details["selected_metric"])
        candidate_count = int(threshold_details["candidate_count"])
        test["fold_id"] = int(fold["fold_id"])
        test["threshold_policy"] = threshold_policy
        test = _apply_alert_policy(
            test,
            threshold=threshold,
            min_persistent_releases=min_persistent_releases,
        )
        prediction_frames.append(test)

        annual = _annual_alert_frame(test)
        metrics = _binary_event_metrics(annual["target_event_label"], annual["any_alert"])
        first_alert = pd.to_datetime(annual.loc[_as_bool(annual["any_alert"]), "first_alert_date"], errors="coerce")
        lead_days = np.nan
        if not first_alert.empty:
            year_start = pd.to_datetime(annual.loc[first_alert.index, "target_market_year"].astype(int).astype(str) + "-01-01")
            lead_days = float((first_alert - year_start).dt.days.median())
        metric_rows.append({
            "target_key": fold["target_key"],
            "detector_id": detector_id,
            "fold_id": int(fold["fold_id"]),
            "test_year": int(fold["test_year"]),
            "threshold_policy": threshold_policy,
            "threshold": threshold,
            "threshold_metric": metric,
            "train_group_count": int(fold["train_group_count"]),
            "test_group_count": int(fold["test_group_count"]),
            "event_count": metrics["event_count"],
            "alert_group_count": metrics["alert_group_count"],
            "true_positive_count": metrics["true_positive_count"],
            "false_negative_count": metrics["false_negative_count"],
            "false_positive_count": metrics["false_positive_count"],
            "event_recall_any_alert": metrics["event_recall_any_alert"],
            "annual_precision_any_alert": metrics["annual_precision_any_alert"],
            "annual_f2_any_alert": metrics["annual_f2_any_alert"],
            "top_20pct_precision": _precision_at_top_quantile(annual["target_event_label"], annual["max_score"], 0.20),
            "average_precision": _average_precision(annual["target_event_label"], annual["max_score"]),
            "median_first_alert_lead_days": lead_days,
            "snapshot_alert_rate": float(_as_bool(test["alert"]).mean()) if len(test) else np.nan,
        })
        threshold_rows.append({
            "target_key": fold["target_key"],
            "detector_id": detector_id,
            "fold_id": int(fold["fold_id"]),
            "test_year": int(fold["test_year"]),
            "threshold_policy": threshold_policy,
            "threshold": threshold,
            "selected_metric": metric,
            "selected_recall": _safe_float(threshold_details["selected_recall"]),
            "selected_precision": _safe_float(threshold_details["selected_precision"]),
            "selected_false_positive_rate": _safe_float(
                threshold_details["selected_false_positive_rate"]
            ),
            "threshold_floor": _safe_float(threshold_floor),
            "min_persistent_releases": int(min_persistent_releases),
            "train_group_count": int(fold["train_group_count"]),
            "candidate_count": int(candidate_count),
        })

    fold_metrics = pd.DataFrame(metric_rows, columns=FOLD_METRIC_COLUMNS)
    thresholds = pd.DataFrame(threshold_rows, columns=THRESHOLD_COLUMNS)
    oof = (
        pd.concat(prediction_frames, ignore_index=True)
        if prediction_frames else pd.DataFrame(columns=OOF_PREDICTION_COLUMNS)
    )
    if not oof.empty:
        oof = oof.reindex(columns=OOF_PREDICTION_COLUMNS)
    annual_cases = _annual_alert_frame(oof) if not oof.empty else pd.DataFrame()
    baselines = build_baseline_comparison(matrix)

    best = (
        fold_metrics.sort_values(
            ["event_recall_any_alert", "annual_f2_any_alert", "top_20pct_precision"],
            ascending=False,
        ).head(1).to_dict("records")
        if not fold_metrics.empty else []
    )
    report = {
        "phase": "wasde_snapshot_anomaly_phase2_backtest",
        "status": "go" if not fold_metrics.empty else "blocked",
        "parameters": {
            "min_train_years": int(min_train_years),
            "candidate_quantiles": [float(q) for q in candidate_quantiles],
            "threshold_policy": threshold_policy,
            "min_precision": float(min_precision),
            "max_false_positive_rate": float(max_false_positive_rate),
            "min_persistent_releases": int(min_persistent_releases),
            "detector_threshold_floors": threshold_floors,
        },
        "inputs": {
            "score_row_count": int(len(scores)),
            "snapshot_detector_row_count": int(len(snapshot_scores)),
            "matrix_row_count": int(len(matrix)),
        },
        "evaluation": {
            "fold_count": int(len(fold_metrics)),
            "oof_prediction_count": int(len(oof)),
            "annual_case_count": int(len(annual_cases)),
            "best_detector_fold": best[0] if best else None,
        },
        "baselines": {
            "row_count": int(len(baselines)),
            "baseline_names": sorted(baselines["baseline_name"].dropna().astype(str).unique())
            if not baselines.empty else [],
        },
    }
    return WasdeSnapshotAnomalyBacktestResult(
        snapshot_detector_scores=snapshot_scores,
        fold_metrics=fold_metrics,
        thresholds=thresholds,
        oof_predictions=oof,
        annual_alert_cases=annual_cases,
        baseline_comparison=baselines,
        report=report,
    )
