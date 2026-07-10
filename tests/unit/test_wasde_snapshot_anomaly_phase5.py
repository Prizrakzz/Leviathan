from __future__ import annotations

import pandas as pd
import pytest
from leviathan.model_datasets.wasde_snapshot_anomaly_phase5 import (
    add_target_severity_bands,
    build_event_label_audit,
    build_false_positive_severity_cases,
    build_revision_streak_audit,
    build_score_scale_audit,
    build_stage_normalization_audit,
    build_threshold_tradeoff_audit,
    recommend_phase5_decision,
)


def _annual_case(
    *,
    year: int,
    detector: str,
    event: bool,
    alert: bool,
    target_value: float,
    threshold: float = 0.10,
    score: float = 1.0,
) -> dict[str, object]:
    return {
        "dataset_key": "corn_wasde_snapshot_solo",
        "contract_key": "corn_cbot",
        "origin_key": "united_states",
        "target_market_year": year,
        "target_key": "psd_stock_to_use_anomaly_pct",
        "detector_id": detector,
        "target_event_label": event,
        "any_alert": alert,
        "first_alert_date": f"{year}-08-12" if alert else pd.NaT,
        "first_alert_stage": "midseason" if alert else "",
        "max_score": score,
        "max_score_stage": "midseason",
        "threshold": 0.8,
        "score_threshold_margin": score - 0.8,
        "target_value": target_value,
        "target_event_threshold": threshold,
        "target_event_direction": "lower_is_stress",
        "snapshot_count": 2,
        "alert_snapshot_count": 1 if alert else 0,
    }


def _oof_row(
    *,
    year: int,
    detector: str,
    event: bool,
    alert: bool,
    raw_alert: bool | None = None,
    score: float = 1.0,
    date: str = "08-12",
) -> dict[str, object]:
    return {
        "dataset_key": "corn_wasde_snapshot_solo",
        "contract_key": "corn_cbot",
        "origin_key": "united_states",
        "target_market_year": year,
        "target_key": "psd_stock_to_use_anomaly_pct",
        "as_of_date": f"{year}-{date}",
        "snapshot_stage": "midseason",
        "detector_id": detector,
        "fold_id": 0,
        "threshold_policy": "precision_guarded_f2",
        "threshold": 0.8,
        "score_value": score,
        "raw_alert": alert if raw_alert is None else raw_alert,
        "alert": alert,
        "target_event_label": event,
        "target_value": -0.2 if event else -0.08,
        "sample_weight": 1.0,
    }


def test_target_severity_bands_identify_soft_near_miss() -> None:
    cases = pd.DataFrame([
        _annual_case(
            year=2000,
            detector="stage_level_percentile",
            event=False,
            alert=True,
            target_value=-0.08,
        )
    ])

    out = add_target_severity_bands(cases)

    assert out.iloc[0]["stress_ratio_to_hard_threshold"] == pytest.approx(0.8)
    assert out.iloc[0]["target_severity_band"] == "soft_stress_near_miss"


def test_event_label_audit_flags_narrow_event_definition() -> None:
    cases = pd.DataFrame([
        _annual_case(
            year=2000,
            detector="stage_level_percentile",
            event=False,
            alert=True,
            target_value=-0.08,
        ),
        _annual_case(
            year=2001,
            detector="stage_level_percentile",
            event=True,
            alert=True,
            target_value=-0.20,
        ),
    ])

    audit = build_event_label_audit(cases)

    assert audit.iloc[0]["soft_stress_false_positive_count"] == 1
    assert audit.iloc[0]["event_definition_diagnosis"] == "event_definition_may_be_too_narrow"


def test_false_positive_severity_cases_only_returns_false_positives() -> None:
    cases = pd.DataFrame([
        _annual_case(
            year=2000,
            detector="revision_shock",
            event=False,
            alert=True,
            target_value=-0.06,
        ),
        _annual_case(
            year=2001,
            detector="revision_shock",
            event=True,
            alert=True,
            target_value=-0.20,
        ),
    ])

    fp = build_false_positive_severity_cases(cases)

    assert len(fp) == 1
    assert fp.iloc[0]["target_market_year"] == 2000


def test_stage_normalization_audit_flags_absurd_z_threshold() -> None:
    thresholds = pd.DataFrame([
        {
            "target_key": "psd_stock_to_use_anomaly_pct",
            "detector_id": "stage_level_z",
            "fold_id": 0,
            "test_year": 2000,
            "threshold": 109.0,
            "selected_metric": 0.5,
            "train_group_count": 10,
            "candidate_count": 5,
        }
    ])

    audit = build_stage_normalization_audit(thresholds)

    assert audit.iloc[0]["absurd_threshold_count"] == 1
    assert audit.iloc[0]["normalization_diagnosis"] == "unstable_threshold_scale"


def test_score_scale_audit_flags_extreme_scores() -> None:
    oof = pd.DataFrame([
        _oof_row(
            year=2000,
            detector="revision_shock",
            event=False,
            alert=True,
            score=433.0,
        )
    ])

    audit = build_score_scale_audit(oof)

    assert audit.iloc[0]["extreme_score_count"] == 1
    assert audit.iloc[0]["score_scale_diagnosis"] == "extreme_scores_present"


def test_revision_streak_audit_detects_benign_overfire() -> None:
    cases = pd.DataFrame([
        _annual_case(
            year=2000 + idx,
            detector="revision_streak",
            event=False,
            alert=True,
            target_value=0.01,
        )
        for idx in range(15)
    ])
    oof = pd.DataFrame([
        _oof_row(
            year=2000 + idx,
            detector="revision_streak",
            event=False,
            alert=True,
        )
        for idx in range(15)
    ])

    audit = build_revision_streak_audit(oof, cases)

    assert audit.iloc[0]["benign_false_positive_count"] == 15
    assert audit.iloc[0]["revision_streak_diagnosis"] == "magnitude_filter_needed"


def test_revision_streak_audit_demotes_low_footprint_low_recall() -> None:
    cases = pd.DataFrame([
        _annual_case(
            year=2000,
            detector="revision_streak",
            event=False,
            alert=True,
            target_value=0.01,
        ),
        _annual_case(
            year=2001,
            detector="revision_streak",
            event=True,
            alert=False,
            target_value=-0.20,
        ),
        _annual_case(
            year=2002,
            detector="revision_streak",
            event=True,
            alert=False,
            target_value=-0.22,
        ),
    ])
    oof = pd.DataFrame([
        _oof_row(year=2000, detector="revision_streak", event=False, alert=True),
        _oof_row(year=2001, detector="revision_streak", event=True, alert=False, raw_alert=True),
        _oof_row(year=2002, detector="revision_streak", event=True, alert=False, raw_alert=True),
    ])

    audit = build_revision_streak_audit(oof, cases)

    assert audit.iloc[0]["false_positive_count"] == 1
    assert audit.iloc[0]["false_negative_count"] == 2
    assert audit.iloc[0]["revision_streak_diagnosis"] == "diagnostic_only_low_recall"


def test_threshold_tradeoff_audit_flags_recall_loss() -> None:
    fold_metrics = pd.DataFrame([
        {
            "target_key": "psd_stock_to_use_anomaly_pct",
            "detector_id": "revision_shock",
            "fold_id": 0,
            "event_recall_any_alert": 0.5,
            "annual_precision_any_alert": 0.8,
            "annual_f2_any_alert": 0.55,
            "false_positive_count": 1,
            "false_negative_count": 3,
        }
    ])
    thresholds = pd.DataFrame([
        {
            "target_key": "psd_stock_to_use_anomaly_pct",
            "detector_id": "revision_shock",
            "fold_id": 0,
            "selected_recall": 0.6,
            "selected_precision": 0.8,
            "selected_false_positive_rate": 0.1,
        }
    ])

    audit = build_threshold_tradeoff_audit(fold_metrics, thresholds)

    assert audit.iloc[0]["threshold_policy_diagnosis"] == "recall_loss"


def test_phase5_decision_prioritizes_stage_repairs() -> None:
    event_audit = pd.DataFrame([
        {
            "event_definition_diagnosis": "event_definition_may_be_too_narrow",
        }
    ])
    stage_audit = pd.DataFrame([
        {
            "normalization_diagnosis": "unstable_threshold_scale",
        }
    ])
    streak_audit = pd.DataFrame([
        {
            "revision_streak_diagnosis": "magnitude_filter_needed",
        }
    ])
    threshold_audit = pd.DataFrame([
        {
            "threshold_policy_diagnosis": "recall_loss",
        }
    ])

    decision = recommend_phase5_decision(
        event_audit,
        stage_audit,
        streak_audit,
        threshold_audit,
    )

    assert decision["decision"] == "fix_stage_level_z_before_more_sweeps"
    assert "repair_stage_normalization" in decision["blockers"]
