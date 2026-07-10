from __future__ import annotations

import pandas as pd
from leviathan.training.phase7_root_cause import (
    baseline_audit_frame,
    certification_comparison_frame,
    feature_set_quality_frame,
    tail_recall_audit_frame,
    target_health_frame,
)


def _report(candidate_id: str = "c1") -> dict:
    return {
        "candidate": {
            "candidate_id": candidate_id,
            "commodity": "corn_cbot",
            "feature_set_id": "corn_preseason_core",
            "dataset_key": "psd_snd_anomaly",
            "target_key": "psd_production_anomaly_pct",
            "model_name": "lightgbm",
            "model_params_sha": "params_a",
            "cv_policy": "expanding_post_2000",
            "model_dataset_version": "v1",
            "source_dataset_version": "gold_v1",
            "min_train_years": 10,
        },
        "aggregate_metrics": {
            "rmse": 0.4,
            "mae": 0.3,
            "directional_accuracy": 0.6,
            "n_folds": 3,
            "n_prediction_rows": 12,
        },
        "bad_production_year_metrics": {
            "bad_year_threshold_actual": -0.1,
            "n_bad_year_rows": 5,
            "n_bad_year_independent_country_years": 5,
            "bad_year_negative_recall": 0.4,
            "bad_year_sign_accuracy": 0.6,
            "validated": False,
        },
        "extreme_metrics": {
            "directional_accuracy": 1.0,
            "n_extreme_independent_country_years": 5,
            "validated": False,
        },
        "baseline_comparison": {
            "metrics": {
                "best_baseline_rmse": 0.35,
                "model_vs_best_baseline_rmse_delta": 0.05,
                "best_baseline_mae": 0.25,
                "model_vs_best_baseline_mae_delta": 0.05,
            },
            "rows": [
                {"baseline_name": "zero_anomaly", "rmse": 0.5, "mae": 0.35, "sign_accuracy": 0.0},
                {"baseline_name": "prior_year", "rmse": 0.35, "mae": 0.25, "sign_accuracy": 0.8},
            ],
        },
        "leakage_audit": {"status": "pass", "hard_findings": [], "warnings": []},
        "permutation_sanity": {
            "status": "fail",
            "actual_extreme_directional_accuracy": 1.0,
            "null_extreme_directional_accuracy_mean": 0.9,
            "null_extreme_directional_accuracy_p95": 1.0,
        },
        "promotion_gate": {"status": "fail", "recommendation": "do_not_promote"},
        "promotion_questions": {
            "beats_zero_baseline_rmse": True,
            "beats_prior_year_baseline_rmse": False,
        },
    }


def test_certification_comparison_filters_versions() -> None:
    other = _report("c2")
    other["candidate"]["model_dataset_version"] = "other"

    df = certification_comparison_frame([_report(), other], model_dataset_versions=["v1"])

    assert list(df["candidate_id"]) == ["c1"]
    assert float(df["aggregate_mae"].iloc[0]) == 0.3


def test_target_health_counts_bad_events_by_scope() -> None:
    matrix = pd.DataFrame({
        "country": ["a", "a", "b", "b"],
        "crop_year": [2000, 2001, 2000, 2001],
        "target_value": [-0.2, 0.1, -0.05, 0.2],
        "is_trainable": [True, True, True, False],
    })

    out = target_health_frame(matrix, thresholds=(-0.10,))
    overall = out.loc[out["scope_type"] == "overall"].iloc[0]

    assert int(overall["row_count"]) == 3
    assert int(overall["target_le_neg_0p1_count"]) == 1
    assert set(out["scope_type"]) >= {"overall", "country", "decade", "country_decade"}


def test_baseline_and_tail_audits_explain_failure() -> None:
    baseline = baseline_audit_frame([_report()])
    tail = tail_recall_audit_frame([_report()])

    prior = baseline.loc[baseline["baseline_name"] == "prior_year"].iloc[0]
    assert bool(prior["beats_baseline_rmse"]) is False
    assert float(prior["model_minus_baseline_rmse"]) > 0
    assert float(tail["estimated_false_negative_count"].iloc[0]) == 3.0
    assert tail["permutation_status"].iloc[0] == "fail"


def test_feature_set_quality_flags_review_for_sparse_features() -> None:
    inventory = pd.DataFrame({
        "feature": ["a", "b"],
        "null_rate": [0.0, 0.95],
        "is_numeric": [True, True],
        "is_constant": [False, False],
        "is_all_missing": [False, False],
    })
    train_df = pd.DataFrame({"target_value": [0.1, -0.2, 0.3]})

    out = feature_set_quality_frame(
        mode="snapshot",
        feature_set_id="wasde",
        train_df=train_df,
        inventory=inventory,
        correlation_pairs=pd.DataFrame(),
    )

    assert out["gate"].iloc[0] == "REVIEW"
    assert int(out["missing_gt80"].iloc[0]) == 1
