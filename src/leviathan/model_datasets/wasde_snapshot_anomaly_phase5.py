"""Phase 5 root-cause audits for WASDE snapshot anomaly detectors."""
from __future__ import annotations

import numpy as np
import pandas as pd

from leviathan.model_datasets.wasde_snapshot_targets import GROUP_KEY as TARGET_GROUP_KEY

EVENT_LABEL_AUDIT_COLUMNS = [
    "target_key",
    "detector_id",
    "case_count",
    "hard_event_count",
    "alert_count",
    "false_positive_count",
    "false_negative_count",
    "soft_stress_false_positive_count",
    "weak_stress_false_positive_count",
    "benign_false_positive_count",
    "near_miss_false_positive_share",
    "false_positive_median_stress_ratio",
    "false_negative_median_stress_ratio",
    "event_definition_diagnosis",
]

FALSE_POSITIVE_SEVERITY_COLUMNS = [
    *TARGET_GROUP_KEY,
    "detector_id",
    "target_value",
    "target_event_threshold",
    "target_event_direction",
    "stress_ratio_to_hard_threshold",
    "target_severity_band",
    "max_score",
    "threshold",
    "score_threshold_margin",
    "first_alert_stage",
]

STAGE_NORMALIZATION_AUDIT_COLUMNS = [
    "target_key",
    "detector_id",
    "fold_count",
    "threshold_min",
    "threshold_median",
    "threshold_max",
    "threshold_std",
    "absurd_threshold_count",
    "threshold_cap",
    "normalization_diagnosis",
]

SCORE_SCALE_AUDIT_COLUMNS = [
    "target_key",
    "detector_id",
    "row_count",
    "non_null_count",
    "score_median",
    "score_q95",
    "score_q99",
    "score_max",
    "extreme_score_count",
    "score_cap",
    "score_scale_diagnosis",
]

REVISION_STREAK_AUDIT_COLUMNS = [
    "target_key",
    "case_count",
    "false_positive_count",
    "false_negative_count",
    "soft_stress_false_positive_count",
    "benign_false_positive_count",
    "raw_alert_snapshot_count",
    "final_alert_snapshot_count",
    "mean_raw_alerts_per_case",
    "mean_final_alerts_per_case",
    "benign_false_positive_share",
    "soft_false_positive_share",
    "revision_streak_diagnosis",
]

THRESHOLD_TRADEOFF_AUDIT_COLUMNS = [
    "target_key",
    "detector_id",
    "fold_count",
    "mean_fold_recall",
    "mean_fold_precision",
    "mean_fold_f2",
    "mean_selected_recall",
    "mean_selected_precision",
    "mean_selected_false_positive_rate",
    "false_positive_count",
    "false_negative_count",
    "threshold_policy_diagnosis",
]

DETECTOR_SCORE_CAPS = {
    "stage_level_z": 8.0,
    "revision_shock": 8.0,
    "stage_level_percentile": 1.0,
    "composite_balance_sheet_stress": 1.0,
    "revision_streak": 12.0,
}


def _as_bool(series: pd.Series) -> pd.Series:
    return series.fillna(False).astype(bool)


def _safe_float(value: object) -> float:
    try:
        out = float(value)
    except Exception:  # noqa: BLE001
        return np.nan
    return out if np.isfinite(out) else np.nan


def _safe_median(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return _safe_float(values.median()) if not values.empty else np.nan


def _stress_ratio(row: pd.Series) -> float:
    value = _safe_float(row.get("target_value"))
    threshold = abs(_safe_float(row.get("target_event_threshold")))
    if not np.isfinite(value) or not np.isfinite(threshold) or threshold <= 0:
        return np.nan
    direction = str(row.get("target_event_direction") or "")
    if direction == "lower_is_stress":
        stress_value = -value
    elif direction == "higher_is_stress":
        stress_value = value
    else:
        return np.nan
    return float(stress_value / threshold)


def add_target_severity_bands(
    annual_cases: pd.DataFrame,
    *,
    soft_stress_ratio: float = 0.75,
    weak_stress_ratio: float = 0.50,
) -> pd.DataFrame:
    """Add continuous target-severity bands to annual alert cases."""
    if annual_cases.empty:
        out = annual_cases.copy()
        out["stress_ratio_to_hard_threshold"] = pd.Series(dtype=float)
        out["target_severity_band"] = pd.Series(dtype=str)
        return out
    out = annual_cases.copy()
    out["stress_ratio_to_hard_threshold"] = out.apply(_stress_ratio, axis=1)
    event = _as_bool(out["target_event_label"])
    ratio = pd.to_numeric(out["stress_ratio_to_hard_threshold"], errors="coerce")
    bands = pd.Series("benign_non_event", index=out.index, dtype=object)
    bands.loc[ratio >= float(weak_stress_ratio)] = "weak_stress_near_miss"
    bands.loc[ratio >= float(soft_stress_ratio)] = "soft_stress_near_miss"
    bands.loc[event] = "hard_event"
    bands.loc[ratio.isna() & ~event] = "unknown"
    out["target_severity_band"] = bands
    return out


def build_event_label_audit(
    annual_cases: pd.DataFrame,
    *,
    soft_stress_ratio: float = 0.75,
    weak_stress_ratio: float = 0.50,
) -> pd.DataFrame:
    """Quantify whether false positives are truly benign or near-miss events."""
    if annual_cases.empty:
        return pd.DataFrame(columns=EVENT_LABEL_AUDIT_COLUMNS)
    cases = add_target_severity_bands(
        annual_cases,
        soft_stress_ratio=soft_stress_ratio,
        weak_stress_ratio=weak_stress_ratio,
    )
    rows: list[dict[str, object]] = []
    for (target_key, detector_id), group in cases.groupby(
        ["target_key", "detector_id"],
        dropna=False,
        sort=True,
    ):
        event = _as_bool(group["target_event_label"])
        alert = _as_bool(group["any_alert"])
        fp = ~event & alert
        fn = event & ~alert
        soft_fp = fp & (group["target_severity_band"] == "soft_stress_near_miss")
        weak_fp = fp & (group["target_severity_band"] == "weak_stress_near_miss")
        benign_fp = fp & (group["target_severity_band"] == "benign_non_event")
        fp_count = int(fp.sum())
        near_miss_share = (
            float((soft_fp.sum() + weak_fp.sum()) / fp_count)
            if fp_count else np.nan
        )
        if fp_count and near_miss_share >= 0.40:
            diagnosis = "event_definition_may_be_too_narrow"
        elif fp_count and int(benign_fp.sum()) / fp_count >= 0.60:
            diagnosis = "detector_overalerts_benign_cases"
        elif int(fn.sum()) > fp_count:
            diagnosis = "threshold_or_score_misses_events"
        else:
            diagnosis = "event_definition_not_primary_blocker"
        rows.append({
            "target_key": str(target_key),
            "detector_id": str(detector_id),
            "case_count": int(len(group)),
            "hard_event_count": int(event.sum()),
            "alert_count": int(alert.sum()),
            "false_positive_count": fp_count,
            "false_negative_count": int(fn.sum()),
            "soft_stress_false_positive_count": int(soft_fp.sum()),
            "weak_stress_false_positive_count": int(weak_fp.sum()),
            "benign_false_positive_count": int(benign_fp.sum()),
            "near_miss_false_positive_share": _safe_float(near_miss_share),
            "false_positive_median_stress_ratio": _safe_float(
                _safe_median(group.loc[fp, "stress_ratio_to_hard_threshold"])
            ),
            "false_negative_median_stress_ratio": _safe_float(
                _safe_median(group.loc[fn, "stress_ratio_to_hard_threshold"])
            ),
            "event_definition_diagnosis": diagnosis,
        })
    return pd.DataFrame(rows, columns=EVENT_LABEL_AUDIT_COLUMNS).sort_values(
        ["false_positive_count", "false_negative_count"],
        ascending=False,
    ).reset_index(drop=True)


def build_false_positive_severity_cases(
    annual_cases: pd.DataFrame,
    *,
    soft_stress_ratio: float = 0.75,
    weak_stress_ratio: float = 0.50,
) -> pd.DataFrame:
    """Return row-level false positives with target-severity context."""
    if annual_cases.empty:
        return pd.DataFrame(columns=FALSE_POSITIVE_SEVERITY_COLUMNS)
    cases = add_target_severity_bands(
        annual_cases,
        soft_stress_ratio=soft_stress_ratio,
        weak_stress_ratio=weak_stress_ratio,
    )
    event = _as_bool(cases["target_event_label"])
    alert = _as_bool(cases["any_alert"])
    out = cases.loc[~event & alert].copy()
    return out.reindex(columns=FALSE_POSITIVE_SEVERITY_COLUMNS).sort_values(
        ["target_severity_band", "stress_ratio_to_hard_threshold", "max_score"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def _detector_cap(detector_id: object) -> float:
    return float(DETECTOR_SCORE_CAPS.get(str(detector_id), np.inf))


def build_stage_normalization_audit(thresholds: pd.DataFrame) -> pd.DataFrame:
    """Flag unstable detector thresholds, especially explosive z-score thresholds."""
    if thresholds.empty:
        return pd.DataFrame(columns=STAGE_NORMALIZATION_AUDIT_COLUMNS)
    work = thresholds.copy()
    work["threshold"] = pd.to_numeric(work["threshold"], errors="coerce")
    rows: list[dict[str, object]] = []
    for (target_key, detector_id), group in work.groupby(
        ["target_key", "detector_id"],
        dropna=False,
        sort=True,
    ):
        cap = _detector_cap(detector_id)
        values = group["threshold"].dropna()
        absurd = int((values > cap).sum()) if np.isfinite(cap) else 0
        median = _safe_float(values.median())
        max_value = _safe_float(values.max())
        std = _safe_float(values.std())
        if absurd:
            diagnosis = "unstable_threshold_scale"
        elif str(detector_id) in {"stage_level_z", "revision_shock"} and np.isfinite(std) and np.isfinite(median) and std > max(1.0, abs(median) * 2.0):
            diagnosis = "threshold_drift"
        elif str(detector_id) == "stage_level_percentile" and max_value > 1.0:
            diagnosis = "percentile_out_of_bounds"
        else:
            diagnosis = "ok"
        rows.append({
            "target_key": str(target_key),
            "detector_id": str(detector_id),
            "fold_count": int(len(group)),
            "threshold_min": _safe_float(values.min()),
            "threshold_median": median,
            "threshold_max": max_value,
            "threshold_std": std,
            "absurd_threshold_count": absurd,
            "threshold_cap": cap if np.isfinite(cap) else np.nan,
            "normalization_diagnosis": diagnosis,
        })
    return pd.DataFrame(rows, columns=STAGE_NORMALIZATION_AUDIT_COLUMNS).sort_values(
        ["absurd_threshold_count", "threshold_max"],
        ascending=False,
    ).reset_index(drop=True)


def build_score_scale_audit(oof_predictions: pd.DataFrame) -> pd.DataFrame:
    """Summarize out-of-fold score scale and extreme-score incidence."""
    if oof_predictions.empty:
        return pd.DataFrame(columns=SCORE_SCALE_AUDIT_COLUMNS)
    work = oof_predictions.copy()
    work["score_value"] = pd.to_numeric(work["score_value"], errors="coerce")
    rows: list[dict[str, object]] = []
    for (target_key, detector_id), group in work.groupby(
        ["target_key", "detector_id"],
        dropna=False,
        sort=True,
    ):
        score = group["score_value"].dropna()
        cap = _detector_cap(detector_id)
        extreme = int((score.abs() > cap).sum()) if np.isfinite(cap) else 0
        if extreme:
            diagnosis = "extreme_scores_present"
        elif score.empty:
            diagnosis = "no_scores"
        else:
            diagnosis = "ok"
        if score.empty:
            score_median = score_q95 = score_q99 = score_max = np.nan
        else:
            score_median = _safe_float(score.median())
            score_q95 = _safe_float(score.quantile(0.95))
            score_q99 = _safe_float(score.quantile(0.99))
            score_max = _safe_float(score.max())
        rows.append({
            "target_key": str(target_key),
            "detector_id": str(detector_id),
            "row_count": int(len(group)),
            "non_null_count": int(score.notna().sum()),
            "score_median": score_median,
            "score_q95": score_q95,
            "score_q99": score_q99,
            "score_max": score_max,
            "extreme_score_count": extreme,
            "score_cap": cap if np.isfinite(cap) else np.nan,
            "score_scale_diagnosis": diagnosis,
        })
    return pd.DataFrame(rows, columns=SCORE_SCALE_AUDIT_COLUMNS).sort_values(
        ["extreme_score_count", "score_max"],
        ascending=False,
    ).reset_index(drop=True)


def build_revision_streak_audit(
    oof_predictions: pd.DataFrame,
    annual_cases: pd.DataFrame,
    *,
    soft_stress_ratio: float = 0.75,
    weak_stress_ratio: float = 0.50,
) -> pd.DataFrame:
    """Explain whether revision-streak alerts are persistent, benign, or near misses."""
    if annual_cases.empty:
        return pd.DataFrame(columns=REVISION_STREAK_AUDIT_COLUMNS)
    streak_cases = add_target_severity_bands(
        annual_cases.loc[annual_cases["detector_id"].astype(str) == "revision_streak"],
        soft_stress_ratio=soft_stress_ratio,
        weak_stress_ratio=weak_stress_ratio,
    )
    if streak_cases.empty:
        return pd.DataFrame(columns=REVISION_STREAK_AUDIT_COLUMNS)
    streak_oof = oof_predictions.loc[
        oof_predictions["detector_id"].astype(str) == "revision_streak"
    ].copy()
    if not streak_oof.empty:
        raw_col = "raw_alert" if "raw_alert" in streak_oof.columns else "alert"
        counts = (
            streak_oof.assign(
                raw_alert=_as_bool(streak_oof[raw_col]),
                alert=_as_bool(streak_oof["alert"]),
            )
            .groupby([*TARGET_GROUP_KEY, "detector_id"], dropna=False)
            .agg(
                raw_alert_snapshot_count=("raw_alert", "sum"),
                final_alert_snapshot_count=("alert", "sum"),
            )
            .reset_index()
        )
        streak_cases = streak_cases.merge(
            counts,
            on=[*TARGET_GROUP_KEY, "detector_id"],
            how="left",
        )
    for col in ["raw_alert_snapshot_count", "final_alert_snapshot_count"]:
        if col not in streak_cases.columns:
            streak_cases[col] = 0
        streak_cases[col] = pd.to_numeric(streak_cases[col], errors="coerce").fillna(0)
    rows: list[dict[str, object]] = []
    for target_key, group in streak_cases.groupby("target_key", dropna=False, sort=True):
        event = _as_bool(group["target_event_label"])
        alert = _as_bool(group["any_alert"])
        fp = ~event & alert
        fn = event & ~alert
        soft_fp = fp & (group["target_severity_band"] == "soft_stress_near_miss")
        benign_fp = fp & (group["target_severity_band"] == "benign_non_event")
        fp_count = int(fp.sum())
        benign_share = float(benign_fp.sum() / fp_count) if fp_count else np.nan
        soft_share = float(soft_fp.sum() / fp_count) if fp_count else np.nan
        if fp_count and benign_share >= 0.50:
            diagnosis = "magnitude_filter_needed"
        elif fp_count and soft_share >= 0.35:
            diagnosis = "watchlist_label_may_be_needed"
        elif int(fn.sum()) and float(group["raw_alert_snapshot_count"].sum()) > float(group["final_alert_snapshot_count"].sum()):
            diagnosis = "persistence_policy_too_strict"
        else:
            diagnosis = "not_primary_blocker"
        rows.append({
            "target_key": str(target_key),
            "case_count": int(len(group)),
            "false_positive_count": fp_count,
            "false_negative_count": int(fn.sum()),
            "soft_stress_false_positive_count": int(soft_fp.sum()),
            "benign_false_positive_count": int(benign_fp.sum()),
            "raw_alert_snapshot_count": int(group["raw_alert_snapshot_count"].sum()),
            "final_alert_snapshot_count": int(group["final_alert_snapshot_count"].sum()),
            "mean_raw_alerts_per_case": _safe_float(group["raw_alert_snapshot_count"].mean()),
            "mean_final_alerts_per_case": _safe_float(group["final_alert_snapshot_count"].mean()),
            "benign_false_positive_share": _safe_float(benign_share),
            "soft_false_positive_share": _safe_float(soft_share),
            "revision_streak_diagnosis": diagnosis,
        })
    return pd.DataFrame(rows, columns=REVISION_STREAK_AUDIT_COLUMNS).reset_index(drop=True)


def build_threshold_tradeoff_audit(
    fold_metrics: pd.DataFrame,
    thresholds: pd.DataFrame,
) -> pd.DataFrame:
    """Combine fold outcomes with selected-threshold training diagnostics."""
    if fold_metrics.empty:
        return pd.DataFrame(columns=THRESHOLD_TRADEOFF_AUDIT_COLUMNS)
    fold = fold_metrics.copy()
    selected = thresholds.copy()
    for col in [
        "event_recall_any_alert",
        "annual_precision_any_alert",
        "annual_f2_any_alert",
        "false_positive_count",
        "false_negative_count",
    ]:
        if col in fold.columns:
            fold[col] = pd.to_numeric(fold[col], errors="coerce")
    for col in [
        "selected_recall",
        "selected_precision",
        "selected_false_positive_rate",
    ]:
        if col in selected.columns:
            selected[col] = pd.to_numeric(selected[col], errors="coerce")
    fold_summary = (
        fold.groupby(["target_key", "detector_id"], dropna=False)
        .agg(
            fold_count=("fold_id", "count"),
            mean_fold_recall=("event_recall_any_alert", "mean"),
            mean_fold_precision=("annual_precision_any_alert", "mean"),
            mean_fold_f2=("annual_f2_any_alert", "mean"),
            false_positive_count=("false_positive_count", "sum"),
            false_negative_count=("false_negative_count", "sum"),
        )
        .reset_index()
    )
    if selected.empty or "selected_recall" not in selected.columns:
        fold_summary["mean_selected_recall"] = np.nan
        fold_summary["mean_selected_precision"] = np.nan
        fold_summary["mean_selected_false_positive_rate"] = np.nan
    else:
        selected_summary = (
            selected.groupby(["target_key", "detector_id"], dropna=False)
            .agg(
                mean_selected_recall=("selected_recall", "mean"),
                mean_selected_precision=("selected_precision", "mean"),
                mean_selected_false_positive_rate=("selected_false_positive_rate", "mean"),
            )
            .reset_index()
        )
        fold_summary = fold_summary.merge(
            selected_summary,
            on=["target_key", "detector_id"],
            how="left",
        )
    diagnoses: list[str] = []
    for _, row in fold_summary.iterrows():
        recall = _safe_float(row.get("mean_fold_recall"))
        precision = _safe_float(row.get("mean_fold_precision"))
        fp = _safe_float(row.get("false_positive_count"))
        fn = _safe_float(row.get("false_negative_count"))
        if np.isfinite(recall) and recall < 0.75:
            diagnosis = "recall_loss"
        elif np.isfinite(precision) and precision < 0.45:
            diagnosis = "precision_too_low"
        elif np.isfinite(fn) and np.isfinite(fp) and fn > fp:
            diagnosis = "too_strict"
        else:
            diagnosis = "acceptable_tradeoff_candidate"
        diagnoses.append(diagnosis)
    fold_summary["threshold_policy_diagnosis"] = diagnoses
    return fold_summary.reindex(columns=THRESHOLD_TRADEOFF_AUDIT_COLUMNS).sort_values(
        ["mean_fold_recall", "mean_fold_f2"],
        ascending=False,
    ).reset_index(drop=True)


def recommend_phase5_decision(
    event_audit: pd.DataFrame,
    stage_audit: pd.DataFrame,
    revision_streak_audit: pd.DataFrame,
    threshold_tradeoff: pd.DataFrame,
) -> dict[str, object]:
    """Return an ordered diagnosis for the next remediation step."""
    blockers: list[str] = []
    if not stage_audit.empty and (
        stage_audit["normalization_diagnosis"].astype(str) != "ok"
    ).any():
        blockers.append("repair_stage_normalization")
    if not revision_streak_audit.empty and (
        revision_streak_audit["revision_streak_diagnosis"].astype(str)
        != "not_primary_blocker"
    ).any():
        blockers.append("repair_revision_streak_magnitude_filter")
    if not event_audit.empty and (
        event_audit["event_definition_diagnosis"].astype(str)
        == "event_definition_may_be_too_narrow"
    ).any():
        blockers.append("add_watchlist_or_soft_stress_label")
    if not threshold_tradeoff.empty and (
        threshold_tradeoff["threshold_policy_diagnosis"].astype(str)
        .isin({"recall_loss", "precision_too_low", "too_strict"})
    ).any():
        blockers.append("retune_threshold_policy_after_score_repairs")

    if "repair_stage_normalization" in blockers:
        next_step = "fix_stage_level_z_before_more_sweeps"
    elif "repair_revision_streak_magnitude_filter" in blockers:
        next_step = "fix_revision_streak_before_more_sweeps"
    elif "add_watchlist_or_soft_stress_label" in blockers:
        next_step = "test_hard_event_plus_watchlist_labels"
    elif blockers:
        next_step = "retune_threshold_policy"
    else:
        next_step = "proceed_to_context_or_meta_model_smoke"
    return {
        "decision": next_step,
        "blockers": blockers,
        "stage_issue_count": int(
            0 if stage_audit.empty else (
                stage_audit["normalization_diagnosis"].astype(str) != "ok"
            ).sum()
        ),
        "revision_streak_issue_count": int(
            0 if revision_streak_audit.empty else (
                revision_streak_audit["revision_streak_diagnosis"].astype(str)
                != "not_primary_blocker"
            ).sum()
        ),
        "event_definition_issue_count": int(
            0 if event_audit.empty else (
                event_audit["event_definition_diagnosis"].astype(str)
                == "event_definition_may_be_too_narrow"
            ).sum()
        ),
        "threshold_policy_issue_count": int(
            0 if threshold_tradeoff.empty else (
                threshold_tradeoff["threshold_policy_diagnosis"].astype(str)
                .isin({"recall_loss", "precision_too_low", "too_strict"})
            ).sum()
        ),
    }
