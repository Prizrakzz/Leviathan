"""Flatten Phase 10 certification reports into ranking tables."""
from __future__ import annotations

from typing import Any

import pandas as pd


def _get(obj: dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def flatten_certification_report(report: dict[str, Any]) -> dict[str, Any]:
    """Return one leaderboard row from a certification report JSON."""
    candidate = report.get("candidate", {}) or {}
    aggregate = report.get("aggregate_metrics", {}) or {}
    extreme = report.get("extreme_metrics", {}) or {}
    bad_years = report.get("bad_production_year_metrics", {}) or {}
    target_policy = report.get("target_event_policy", {}) or {}
    target_events = report.get("target_stress_event_metrics", {}) or {}
    target_alerts = (
        (report.get("target_alert_metrics", {}) or {}).get("summary", {}) or {}
    )
    downside_alerts = (
        (report.get("downside_alert_metrics", {}) or {}).get("summary", {}) or {}
    )
    gate = report.get("promotion_gate", {}) or {}
    questions = report.get("promotion_questions", {}) or {}
    baseline_metrics = (report.get("baseline_comparison", {}) or {}).get("metrics", {}) or {}
    inputs = report.get("inputs", {}) or {}
    row = {
        "candidate_id": candidate.get("candidate_id"),
        "commodity": candidate.get("commodity"),
        "feature_set": candidate.get("feature_set_id"),
        "dataset_key": candidate.get("dataset_key"),
        "target_key": candidate.get("target_key"),
        "model": candidate.get("model_name"),
        "model_params_sha": candidate.get("model_params_sha"),
        "cv_policy": candidate.get("cv_policy"),
        "model_dataset_version": candidate.get("model_dataset_version"),
        "source_dataset_version": candidate.get("source_dataset_version"),
        "min_train_years": candidate.get("min_train_years"),
        "aggregate_rmse": aggregate.get("rmse"),
        "aggregate_mae": aggregate.get("mae"),
        "aggregate_sign_accuracy": aggregate.get("directional_accuracy"),
        "n_folds": aggregate.get("n_folds"),
        "n_prediction_rows": aggregate.get("n_prediction_rows"),
        "quintile_directional_accuracy": extreme.get("directional_accuracy"),
        "n_extreme_independent_country_years": extreme.get(
            "n_extreme_independent_country_years"
        ),
        "extreme_metric_validated": bool(extreme.get("validated")),
        "bad_year_negative_recall": bad_years.get("bad_year_negative_recall"),
        "bad_year_sign_accuracy": bad_years.get("bad_year_sign_accuracy"),
        "bad_year_metric_validated": bool(bad_years.get("validated")),
        "target_stress_event_direction": target_policy.get(
            "stress_event_direction",
            target_events.get("stress_event_direction"),
        ),
        "target_stress_event_label": target_policy.get(
            "stress_event_label",
            target_events.get("stress_event_label"),
        ),
        "target_stress_event_recall": target_events.get(
            "stress_event_directional_recall"
        ),
        "target_stress_event_sign_accuracy": target_events.get(
            "stress_event_sign_accuracy"
        ),
        "target_stress_event_validated": bool(target_events.get("validated")),
        "target_stress_5pct_pred_direction_recall": target_alerts.get(
            "target_stress_0p05_pred_stress_direction_recall"
        ),
        "target_stress_5pct_pred_direction_precision": target_alerts.get(
            "target_stress_0p05_pred_stress_direction_precision"
        ),
        "target_stress_5pct_pred_direction_false_negatives": target_alerts.get(
            "target_stress_0p05_pred_stress_direction_false_negatives"
        ),
        "target_stress_5pct_pred_direction_f2": target_alerts.get(
            "target_stress_0p05_pred_stress_direction_f2_score"
        ),
        "target_stress_10pct_pred_direction_recall": target_alerts.get(
            "target_stress_0p1_pred_stress_direction_recall"
        ),
        "target_stress_10pct_pred_direction_precision": target_alerts.get(
            "target_stress_0p1_pred_stress_direction_precision"
        ),
        "target_stress_10pct_pred_direction_false_negatives": target_alerts.get(
            "target_stress_0p1_pred_stress_direction_false_negatives"
        ),
        "target_stress_10pct_pred_direction_f2": target_alerts.get(
            "target_stress_0p1_pred_stress_direction_f2_score"
        ),
        "downside_5pct_pred_lt_0_recall": downside_alerts.get(
            "downside_0p05_pred_lt_0_recall"
        ),
        "downside_5pct_pred_lt_0_precision": downside_alerts.get(
            "downside_0p05_pred_lt_0_precision"
        ),
        "downside_5pct_pred_lt_0_false_negatives": downside_alerts.get(
            "downside_0p05_pred_lt_0_false_negatives"
        ),
        "downside_5pct_pred_lt_0_f2": downside_alerts.get(
            "downside_0p05_pred_lt_0_f2_score"
        ),
        "downside_10pct_pred_lt_0_recall": downside_alerts.get(
            "downside_0p1_pred_lt_0_recall"
        ),
        "downside_10pct_pred_lt_0_precision": downside_alerts.get(
            "downside_0p1_pred_lt_0_precision"
        ),
        "downside_10pct_pred_lt_0_false_negatives": downside_alerts.get(
            "downside_0p1_pred_lt_0_false_negatives"
        ),
        "downside_10pct_pred_lt_0_f2": downside_alerts.get(
            "downside_0p1_pred_lt_0_f2_score"
        ),
        "best_baseline_rmse": baseline_metrics.get("best_baseline_rmse"),
        "model_vs_best_baseline_rmse_delta": baseline_metrics.get(
            "model_vs_best_baseline_rmse_delta"
        ),
        "best_baseline_mae": baseline_metrics.get("best_baseline_mae"),
        "model_vs_best_baseline_mae_delta": baseline_metrics.get(
            "model_vs_best_baseline_mae_delta"
        ),
        "beats_zero_baseline_rmse": questions.get("beats_zero_baseline_rmse"),
        "beats_prior_year_baseline_rmse": questions.get("beats_prior_year_baseline_rmse"),
        "beats_trailing_mean_baseline_rmse": questions.get(
            "beats_trailing_mean_baseline_rmse"
        ),
        "beats_trailing_trend_baseline_rmse": questions.get(
            "beats_trailing_trend_baseline_rmse"
        ),
        "leakage_status": _get(report, "leakage_audit.status"),
        "permutation_status": _get(report, "permutation_sanity.status"),
        "country_blocked_rmse": questions.get("country_blocked_rmse"),
        "stress_year_rmse": questions.get("stress_year_rmse"),
        "promotion_gate_status": gate.get("status"),
        "promotion_recommendation": gate.get("recommendation"),
        "ready_for_model_registration": bool(questions.get("ready_for_model_registration")),
        "certification_report_uri": inputs.get("certification_report_uri"),
        "matrix_uri": inputs.get("matrix_uri"),
        "manifest_uri": inputs.get("manifest_uri"),
    }
    return row


def certification_ranking_frame(reports: list[dict[str, Any]]) -> pd.DataFrame:
    """Build a sorted leaderboard from a list of report dicts."""
    rows = [flatten_certification_report(report) for report in reports]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    status_order = {"pass": 0, "warn": 1, "fail": 2}
    df["_status_order"] = df["promotion_gate_status"].map(status_order).fillna(3)
    df["_baseline_delta"] = pd.to_numeric(
        df["model_vs_best_baseline_rmse_delta"], errors="coerce"
    )
    df["_rmse"] = pd.to_numeric(df["aggregate_rmse"], errors="coerce")
    df = df.sort_values(
        ["_status_order", "_baseline_delta", "_rmse", "candidate_id"],
        na_position="last",
    ).drop(columns=["_status_order", "_baseline_delta", "_rmse"])
    return df.reset_index(drop=True)
