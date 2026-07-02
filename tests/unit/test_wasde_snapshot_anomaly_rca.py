from __future__ import annotations

import pandas as pd

from leviathan.model_datasets.wasde_snapshot_anomaly_rca import (
    build_annual_alert_cases,
    build_detector_rca_summary,
    build_false_case_tables,
    build_rca_reason_summary,
    build_threshold_stability_report,
    recommend_phase4_decision,
)


def _prediction(
    *,
    year: int,
    event: bool,
    alert: bool,
    detector: str = "composite_balance_sheet_stress",
) -> dict[str, object]:
    return {
        "dataset_key": "corn_wasde_snapshot_solo",
        "contract_key": "corn_cbot",
        "origin_key": "united_states",
        "target_market_year": year,
        "target_key": "psd_stock_to_use_anomaly_pct",
        "as_of_date": f"{year}-08-12",
        "snapshot_stage": "early_season",
        "detector_id": detector,
        "fold_id": 0,
        "threshold": 0.5,
        "score_value": 0.9 if alert else 0.1,
        "alert": alert,
        "target_event_label": event,
        "target_value": -0.2 if event else 0.1,
        "target_event_threshold": 0.1,
        "target_event_direction": "lower_is_stress",
        "sample_weight": 1.0,
    }


def test_false_negative_case_table_contains_required_columns() -> None:
    predictions = pd.DataFrame([
        _prediction(year=2000, event=True, alert=False),
        _prediction(year=2001, event=False, alert=True),
    ])
    annual = build_annual_alert_cases(predictions)
    false_negatives, _ = build_false_case_tables(annual)

    assert len(false_negatives) == 1
    assert false_negatives.iloc[0]["case_type"] == "false_negative"
    assert false_negatives.iloc[0]["rca_reason_code"] in {
        "no_wasde_signal",
        "threshold_too_strict",
    }


def test_false_positive_case_table_contains_required_columns() -> None:
    predictions = pd.DataFrame([
        _prediction(year=2000, event=True, alert=False),
        _prediction(year=2001, event=False, alert=True),
    ])
    annual = build_annual_alert_cases(predictions)
    _, false_positives = build_false_case_tables(annual)

    assert len(false_positives) == 1
    assert false_positives.iloc[0]["case_type"] == "false_positive"
    assert false_positives.iloc[0]["rca_reason_code"] in {
        "final_outcome_reversal",
        "genuine_temporary_stress",
        "threshold_too_loose",
        "event_definition_too_narrow",
        "benign_final_outcome",
    }


def test_rca_reason_codes_are_valid() -> None:
    predictions = pd.DataFrame([
        _prediction(year=2000, event=True, alert=False),
        _prediction(year=2001, event=False, alert=True),
    ])
    annual = build_annual_alert_cases(predictions)
    false_negatives, false_positives = build_false_case_tables(annual)

    reasons = set(false_negatives["rca_reason_code"]) | set(false_positives["rca_reason_code"])
    assert reasons <= {
        "no_wasde_signal",
        "threshold_too_strict",
        "stage_normalization_issue",
        "missing_driver",
        "revision_streak_overfires",
        "final_outcome_reversal",
        "genuine_temporary_stress",
        "threshold_too_loose",
        "event_definition_too_narrow",
        "benign_final_outcome",
    }


def test_false_positive_classifier_uses_stress_direction() -> None:
    predictions = pd.DataFrame([
        _prediction(
            year=2001,
            event=False,
            alert=True,
            detector="revision_shock",
        )
    ])
    predictions["target_value"] = 0.5
    predictions["target_event_threshold"] = 0.1
    predictions["target_event_direction"] = "lower_is_stress"
    annual = build_annual_alert_cases(predictions)
    _, false_positives = build_false_case_tables(annual)

    assert false_positives.iloc[0]["rca_reason_code"] == "benign_final_outcome"


def test_threshold_stability_report_contains_expected_columns() -> None:
    thresholds = pd.DataFrame([
        {
            "target_key": "psd_stock_to_use_anomaly_pct",
            "detector_id": "revision_streak",
            "fold_id": 0,
            "test_year": 2000,
            "threshold": 0.5,
            "selected_metric": 0.8,
            "train_group_count": 10,
            "candidate_count": 5,
        },
        {
            "target_key": "psd_stock_to_use_anomaly_pct",
            "detector_id": "revision_streak",
            "fold_id": 1,
            "test_year": 2001,
            "threshold": 0.7,
            "selected_metric": 0.9,
            "train_group_count": 12,
            "candidate_count": 5,
        },
    ])

    report = build_threshold_stability_report(thresholds)

    assert len(report) == 1
    assert report.iloc[0]["threshold_min"] == 0.5
    assert report.iloc[0]["threshold_max"] == 0.7


def test_detector_summary_and_reason_summary_feed_decision() -> None:
    fold_metrics = pd.DataFrame([
        {
            "target_key": "psd_stock_to_use_anomaly_pct",
            "detector_id": "revision_streak",
            "fold_id": 0,
            "event_count": 3,
            "true_positive_count": 3,
            "false_negative_count": 0,
            "false_positive_count": 10,
            "alert_group_count": 13,
            "event_recall_any_alert": 1.0,
            "annual_precision_any_alert": 3 / 13,
            "annual_f2_any_alert": 0.6,
            "top_20pct_precision": 0.5,
            "snapshot_alert_rate": 0.4,
        }
    ])
    detector_summary = build_detector_rca_summary(fold_metrics)
    false_negatives = pd.DataFrame(columns=[
        "case_type",
        "target_key",
        "detector_id",
        "rca_reason_code",
    ])
    false_positives = pd.DataFrame([
        {
            "case_type": "false_positive",
            "target_key": "psd_stock_to_use_anomaly_pct",
            "detector_id": "revision_streak",
            "rca_reason_code": "revision_streak_overfires",
        }
    ])
    reason_summary = build_rca_reason_summary(false_negatives, false_positives)
    decision = recommend_phase4_decision(detector_summary, reason_summary)

    assert detector_summary.iloc[0]["mean_recall"] == 1.0
    assert reason_summary.iloc[0]["case_count"] == 1
    assert decision["decision"] == "tune_threshold_policy"
