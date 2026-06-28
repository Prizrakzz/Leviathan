from __future__ import annotations

from leviathan.training.certification_summary import (
    certification_ranking_frame,
    flatten_certification_report,
)


def _report(candidate_id: str, status: str, rmse: float, delta: float) -> dict:
    return {
        "candidate": {
            "candidate_id": candidate_id,
            "commodity": "corn_cbot",
            "feature_set_id": "preseason_physical",
            "dataset_key": "psd_snd_anomaly",
            "target_key": "psd_production_anomaly_pct",
            "model_name": "lightgbm",
            "model_params_sha": "default_params",
            "cv_policy": "expanding_post_2000",
            "model_dataset_version": "v1",
            "source_dataset_version": "gold1",
            "min_train_years": 10,
        },
        "aggregate_metrics": {
            "rmse": rmse,
            "mae": 0.1,
            "directional_accuracy": 0.7,
            "n_folds": 3,
            "n_prediction_rows": 12,
        },
        "extreme_metrics": {
            "directional_accuracy": 0.8,
            "n_extreme_independent_country_years": 4,
            "validated": 0.0,
        },
        "bad_production_year_metrics": {
            "bad_year_negative_recall": 0.75,
            "bad_year_sign_accuracy": 0.75,
            "validated": 0.0,
        },
        "downside_alert_metrics": {
            "summary": {
                "downside_0p05_pred_lt_0_recall": 0.6,
                "downside_0p05_pred_lt_0_precision": 0.5,
                "downside_0p05_pred_lt_0_false_negatives": 2,
                "downside_0p05_pred_lt_0_f2_score": 0.57,
                "downside_0p1_pred_lt_0_recall": 0.4,
                "downside_0p1_pred_lt_0_precision": 0.8,
                "downside_0p1_pred_lt_0_false_negatives": 3,
                "downside_0p1_pred_lt_0_f2_score": 0.44,
            }
        },
        "baseline_comparison": {
            "metrics": {
                "best_baseline_rmse": 0.4,
                "model_vs_best_baseline_rmse_delta": delta,
                "best_baseline_mae": 0.2,
                "model_vs_best_baseline_mae_delta": -0.1,
            }
        },
        "leakage_audit": {"status": "pass"},
        "permutation_sanity": {"status": "pass"},
        "promotion_gate": {"status": status, "recommendation": "review"},
        "promotion_questions": {
            "ready_for_model_registration": status == "pass",
            "beats_zero_baseline_rmse": True,
            "beats_prior_year_baseline_rmse": False,
        },
        "inputs": {"certification_report_uri": f"s3://bucket/{candidate_id}.json"},
    }


def test_flatten_certification_report_keeps_promotion_fields() -> None:
    row = flatten_certification_report(_report("c1", "pass", 0.3, -0.1))

    assert row["candidate_id"] == "c1"
    assert row["promotion_gate_status"] == "pass"
    assert row["ready_for_model_registration"] is True
    assert row["model_vs_best_baseline_rmse_delta"] == -0.1
    assert row["downside_5pct_pred_lt_0_recall"] == 0.6
    assert row["downside_10pct_pred_lt_0_false_negatives"] == 3
    assert row["certification_report_uri"] == "s3://bucket/c1.json"


def test_certification_ranking_sorts_pass_before_fail_then_metric() -> None:
    df = certification_ranking_frame([
        _report("fail_good_rmse", "fail", 0.2, -0.2),
        _report("pass_worse_rmse", "pass", 0.4, 0.1),
        _report("pass_best_rmse", "pass", 0.3, -0.1),
    ])

    assert list(df["candidate_id"]) == [
        "pass_best_rmse",
        "pass_worse_rmse",
        "fail_good_rmse",
    ]
