"""False-case RCA tables for WASDE snapshot anomaly evaluation."""
from __future__ import annotations

import numpy as np
import pandas as pd

from leviathan.model_datasets.wasde_snapshot_targets import GROUP_KEY as TARGET_GROUP_KEY

FALSE_CASE_COLUMNS = [
    *TARGET_GROUP_KEY,
    "detector_id",
    "case_type",
    "target_event_label",
    "any_alert",
    "first_alert_date",
    "first_alert_stage",
    "max_score",
    "max_score_stage",
    "threshold",
    "score_threshold_margin",
    "target_value",
    "target_event_threshold",
    "target_event_direction",
    "snapshot_count",
    "alert_snapshot_count",
    "rca_reason_code",
]

ANNUAL_CASE_COLUMNS = [
    *TARGET_GROUP_KEY,
    "detector_id",
    "target_event_label",
    "any_alert",
    "first_alert_date",
    "first_alert_stage",
    "max_score",
    "max_score_stage",
    "threshold",
    "score_threshold_margin",
    "target_value",
    "target_event_threshold",
    "target_event_direction",
    "snapshot_count",
    "alert_snapshot_count",
]

DETECTOR_SUMMARY_COLUMNS = [
    "target_key",
    "detector_id",
    "fold_count",
    "event_count",
    "true_positive_count",
    "false_negative_count",
    "false_positive_count",
    "alert_group_count",
    "mean_recall",
    "mean_precision",
    "mean_f2",
    "mean_top20_precision",
    "mean_snapshot_alert_rate",
]

THRESHOLD_STABILITY_COLUMNS = [
    "target_key",
    "detector_id",
    "fold_count",
    "threshold_min",
    "threshold_median",
    "threshold_max",
    "threshold_std",
    "selected_metric_mean",
    "train_group_count_min",
    "train_group_count_max",
]


def _as_bool(series: pd.Series) -> pd.Series:
    return series.fillna(False).astype(bool)


def _safe_float(value: object) -> float:
    try:
        out = float(value)
    except Exception:  # noqa: BLE001
        return np.nan
    return out if np.isfinite(out) else np.nan


def _stress_ratio_to_threshold(row: pd.Series) -> float:
    target_value = _safe_float(row.get("target_value"))
    target_threshold = abs(_safe_float(row.get("target_event_threshold")))
    if not np.isfinite(target_value) or not np.isfinite(target_threshold) or target_threshold <= 0:
        return np.nan
    direction = str(row.get("target_event_direction") or "")
    if direction == "lower_is_stress":
        stress_value = -target_value
    elif direction == "higher_is_stress":
        stress_value = target_value
    else:
        return np.nan
    return float(stress_value / target_threshold)


def build_annual_alert_cases(oof_predictions: pd.DataFrame) -> pd.DataFrame:
    """Collapse out-of-fold snapshot alerts to annual event cases."""
    if oof_predictions.empty:
        return pd.DataFrame(columns=ANNUAL_CASE_COLUMNS)
    rows: list[dict[str, object]] = []
    for keys, group in oof_predictions.groupby([*TARGET_GROUP_KEY, "detector_id"], dropna=False, sort=True):
        values = dict(zip([*TARGET_GROUP_KEY, "detector_id"], keys, strict=False))
        alerts = _as_bool(group["alert"])
        alert_group = group.loc[alerts].copy()
        dates = pd.to_datetime(group.loc[alerts, "as_of_date"], errors="coerce")
        score = pd.to_numeric(group["score_value"], errors="coerce")
        max_idx = score.idxmax() if score.notna().any() else group.index[0]
        threshold = _safe_float(pd.to_numeric(group.get("threshold"), errors="coerce").dropna().iloc[0]) if "threshold" in group.columns and pd.to_numeric(group.get("threshold"), errors="coerce").notna().any() else np.nan
        first_alert_stage = ""
        if not alert_group.empty:
            first_alert_stage = str(
                alert_group.sort_values("as_of_date").iloc[0].get("snapshot_stage") or ""
            )
        rows.append({
            **values,
            "target_event_label": bool(_as_bool(group["target_event_label"]).iloc[0]),
            "any_alert": bool(alerts.any()),
            "first_alert_date": dates.min() if not dates.empty else pd.NaT,
            "first_alert_stage": first_alert_stage,
            "max_score": _safe_float(pd.to_numeric(group["score_value"], errors="coerce").max()),
            "max_score_stage": str(group.loc[max_idx].get("snapshot_stage") or ""),
            "threshold": threshold,
            "score_threshold_margin": _safe_float(score.max() - threshold),
            "target_value": _safe_float(group.get("target_value", pd.Series(dtype=float)).iloc[0])
            if "target_value" in group.columns else np.nan,
            "target_event_threshold": _safe_float(
                group.get("target_event_threshold", pd.Series(dtype=float)).iloc[0]
            ) if "target_event_threshold" in group.columns else np.nan,
            "target_event_direction": str(
                group.get("target_event_direction", pd.Series([""])).iloc[0] or ""
            ) if "target_event_direction" in group.columns else "",
            "snapshot_count": int(len(group)),
            "alert_snapshot_count": int(alerts.sum()),
        })
    return pd.DataFrame(rows, columns=ANNUAL_CASE_COLUMNS)


def _classify_false_negative(row: pd.Series) -> str:
    max_score = _safe_float(row.get("max_score"))
    threshold = _safe_float(row.get("threshold"))
    margin = _safe_float(row.get("score_threshold_margin"))
    if not np.isfinite(max_score):
        return "no_wasde_signal"
    if str(row.get("max_score_stage") or "") in {"", "unknown"}:
        return "missing_driver"
    if np.isfinite(margin) and margin >= -0.05:
        return "threshold_too_strict"
    if np.isfinite(threshold) and threshold > 0 and max_score >= threshold * 0.85:
        return "threshold_too_strict"
    if str(row.get("detector_id")) in {"stage_level_z", "stage_level_percentile"}:
        return "stage_normalization_issue"
    return "no_wasde_signal"


def _classify_false_positive(row: pd.Series) -> str:
    margin = _safe_float(row.get("score_threshold_margin"))
    stress_ratio = _stress_ratio_to_threshold(row)
    if str(row.get("detector_id")) == "revision_streak":
        return "revision_streak_overfires"
    if np.isfinite(margin) and margin <= 0.05:
        return "threshold_too_loose"
    if np.isfinite(stress_ratio) and stress_ratio >= 0.75:
        return "final_outcome_reversal"
    if np.isfinite(stress_ratio) and stress_ratio < 0.50:
        return "benign_final_outcome"
    if str(row.get("detector_id")) == "composite_balance_sheet_stress":
        return "genuine_temporary_stress"
    return "event_definition_too_narrow"


def build_false_case_tables(
    annual_alert_cases: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return false-negative and false-positive RCA tables."""
    if annual_alert_cases.empty:
        empty = pd.DataFrame(columns=FALSE_CASE_COLUMNS)
        return empty.copy(), empty.copy()
    cases = annual_alert_cases.copy()
    cases["target_event_label"] = _as_bool(cases["target_event_label"])
    cases["any_alert"] = _as_bool(cases["any_alert"])

    false_negatives = cases.loc[cases["target_event_label"] & ~cases["any_alert"]].copy()
    false_negatives["case_type"] = "false_negative"
    false_negatives["rca_reason_code"] = false_negatives.apply(
        _classify_false_negative,
        axis=1,
    )

    false_positives = cases.loc[~cases["target_event_label"] & cases["any_alert"]].copy()
    false_positives["case_type"] = "false_positive"
    false_positives["rca_reason_code"] = false_positives.apply(
        _classify_false_positive,
        axis=1,
    )

    return (
        false_negatives.reindex(columns=FALSE_CASE_COLUMNS).reset_index(drop=True),
        false_positives.reindex(columns=FALSE_CASE_COLUMNS).reset_index(drop=True),
    )


def build_detector_rca_summary(fold_metrics: pd.DataFrame) -> pd.DataFrame:
    """Aggregate fold metrics by target and detector for RCA ranking."""
    if fold_metrics.empty:
        return pd.DataFrame(columns=DETECTOR_SUMMARY_COLUMNS)
    grouped = (
        fold_metrics.groupby(["target_key", "detector_id"], dropna=False)
        .agg(
            fold_count=("fold_id", "count"),
            event_count=("event_count", "sum"),
            true_positive_count=("true_positive_count", "sum"),
            false_negative_count=("false_negative_count", "sum"),
            false_positive_count=("false_positive_count", "sum"),
            alert_group_count=("alert_group_count", "sum"),
            mean_recall=("event_recall_any_alert", "mean"),
            mean_precision=("annual_precision_any_alert", "mean"),
            mean_f2=("annual_f2_any_alert", "mean"),
            mean_top20_precision=("top_20pct_precision", "mean"),
            mean_snapshot_alert_rate=("snapshot_alert_rate", "mean"),
        )
        .reset_index()
    )
    return grouped.reindex(columns=DETECTOR_SUMMARY_COLUMNS).sort_values(
        ["mean_recall", "mean_f2", "false_positive_count"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def build_threshold_stability_report(thresholds: pd.DataFrame) -> pd.DataFrame:
    """Summarize threshold drift by detector and target."""
    if thresholds.empty:
        return pd.DataFrame(columns=THRESHOLD_STABILITY_COLUMNS)
    work = thresholds.copy()
    work["threshold"] = pd.to_numeric(work["threshold"], errors="coerce")
    work["selected_metric"] = pd.to_numeric(work["selected_metric"], errors="coerce")
    grouped = (
        work.groupby(["target_key", "detector_id"], dropna=False)
        .agg(
            fold_count=("fold_id", "count"),
            threshold_min=("threshold", "min"),
            threshold_median=("threshold", "median"),
            threshold_max=("threshold", "max"),
            threshold_std=("threshold", "std"),
            selected_metric_mean=("selected_metric", "mean"),
            train_group_count_min=("train_group_count", "min"),
            train_group_count_max=("train_group_count", "max"),
        )
        .reset_index()
    )
    return grouped.reindex(columns=THRESHOLD_STABILITY_COLUMNS).sort_values(
        ["target_key", "detector_id"]
    ).reset_index(drop=True)


def build_rca_reason_summary(
    false_negatives: pd.DataFrame,
    false_positives: pd.DataFrame,
) -> pd.DataFrame:
    """Count RCA reason codes by case type, target, and detector."""
    cases = pd.concat([false_negatives, false_positives], ignore_index=True)
    columns = [
        "case_type",
        "target_key",
        "detector_id",
        "rca_reason_code",
        "case_count",
    ]
    if cases.empty:
        return pd.DataFrame(columns=columns)
    return (
        cases.groupby(["case_type", "target_key", "detector_id", "rca_reason_code"], dropna=False)
        .size()
        .reset_index(name="case_count")
        .reindex(columns=columns)
        .sort_values(["case_type", "case_count"], ascending=[True, False])
        .reset_index(drop=True)
    )


def recommend_phase4_decision(
    detector_summary: pd.DataFrame,
    reason_summary: pd.DataFrame,
) -> dict[str, object]:
    """Return a deterministic RCA decision for the next phase."""
    if detector_summary.empty:
        return {
            "decision": "fix_feature_mapping",
            "reason": "no_detector_summary",
        }
    best = detector_summary.sort_values(
        ["mean_recall", "mean_f2", "false_positive_count"],
        ascending=[False, False, True],
    ).iloc[0]
    fp_reasons = reason_summary.loc[reason_summary["case_type"] == "false_positive"]
    revision_overfires = int(
        fp_reasons.loc[
            fp_reasons["rca_reason_code"] == "revision_streak_overfires",
            "case_count",
        ].sum()
    ) if not fp_reasons.empty else 0
    false_positives = int(detector_summary["false_positive_count"].sum())
    false_negatives = int(detector_summary["false_negative_count"].sum())
    if false_positives > false_negatives * 5:
        decision = "tune_threshold_policy"
        reason = "false_positives_dominate_false_negatives"
    elif revision_overfires > 0:
        decision = "tune_threshold_policy"
        reason = "revision_streak_overfires_present"
    elif float(best.get("mean_recall", 0.0)) >= 0.85:
        decision = "add_substitute_context"
        reason = "transparent_signal_has_high_recall_but_needs_context"
    else:
        decision = "reform_event_definition"
        reason = "transparent_signal_recall_not_strong_enough"
    return {
        "decision": decision,
        "reason": reason,
        "best_target_key": str(best["target_key"]),
        "best_detector_id": str(best["detector_id"]),
        "best_mean_recall": _safe_float(best["mean_recall"]),
        "best_mean_f2": _safe_float(best["mean_f2"]),
        "false_positive_count": false_positives,
        "false_negative_count": false_negatives,
    }
