from __future__ import annotations

import pandas as pd
from sklearn.linear_model import LinearRegression

from leviathan.model_datasets.baselines import BASELINE_COLUMNS
from leviathan.training.certification import (
    CandidateSpec,
    audit_feature_leakage,
    build_candidate_certification_report,
    country_blocked_validation,
    downside_alert_metrics,
)


def _matrix() -> pd.DataFrame:
    rows = []
    for country, offset in [
        ("argentina", -0.2),
        ("brazil", 0.1),
        ("ukraine", -0.1),
        ("united_states", 0.2),
    ]:
        for year in range(2000, 2017):
            x = (year - 2000) / 10.0
            target = 0.4 * x + offset
            row = {
                "country": country,
                "crop_year": year,
                "feature_weather": x,
                "feature_origin_bias": offset,
                "target_value": target,
                "is_trainable": True,
            }
            for baseline_col in BASELINE_COLUMNS.values():
                row[baseline_col] = 0.0
            rows.append(row)
    return pd.DataFrame(rows)


def test_audit_feature_leakage_blocks_labels_targets_and_baselines() -> None:
    audit = audit_feature_leakage([
        "feature_weather",
        "label_production_quantity",
        "target_value",
        "prior_year_anomaly_baseline",
    ])

    assert audit["status"] == "fail"
    reasons = {finding["feature"] for finding in audit["hard_findings"]}
    assert "label_production_quantity" in reasons
    assert "target_value" in reasons
    assert "prior_year_anomaly_baseline" in reasons


def test_country_blocked_validation_scores_each_country() -> None:
    matrix = _matrix()
    out = country_blocked_validation(
        matrix,
        target_col="target_value",
        feature_cols=["feature_weather", "feature_origin_bias"],
        model=LinearRegression(),
    )

    assert {row["country"] for row in out["rows"]} == {
        "argentina", "brazil", "ukraine", "united_states",
    }
    assert out["aggregate"]["n_rows"] == len(matrix)


def test_downside_alert_metrics_are_reported_for_fixed_thresholds() -> None:
    predictions = pd.DataFrame({
        "country": ["a", "b", "c"],
        "crop_year": [2020, 2020, 2020],
        "y_actual": [-0.12, -0.08, 0.03],
        "y_pred": [-0.02, 0.01, -0.01],
    })

    metrics = downside_alert_metrics(
        predictions, thresholds=(-0.05,), min_event_rows=1
    )
    summary = metrics["summary"]

    assert summary["downside_0p05_pred_lt_0_recall"] == 0.5
    assert summary["downside_0p05_pred_lt_0_false_negatives"] == 1


def test_build_candidate_certification_report_flags_unvalidated_extreme_sample() -> None:
    matrix = _matrix()
    spec = CandidateSpec(
        commodity="corn_cbot",
        feature_set_id="preseason_physical",
        dataset_key="psd_snd_anomaly",
        target_key="psd_production_anomaly_pct",
        model_name="linear",
        cv_policy="expanding_post_2000",
        model_dataset_version="test_version",
        min_train_years=5,
    )

    report = build_candidate_certification_report(
        spec=spec,
        matrix=matrix,
        train_df=matrix[[
            "country",
            "crop_year",
            "feature_weather",
            "feature_origin_bias",
            "target_value",
        ]],
        feature_cols=["feature_weather", "feature_origin_bias"],
        target_col="target_value",
        model=LinearRegression(),
        stress_years=(2010, 2012),
        permutation_trials=2,
        random_seed=123,
    )

    assert report["candidate"]["candidate_id"].startswith("corn_cbot__preseason_physical")
    assert report["aggregate_metrics"]["n_folds"] > 0
    assert report["fold_metrics"]
    assert report["extreme_metrics"]["n_extreme_independent_country_years"] < 30
    assert report["bad_production_year_metrics"]["n_bad_year_rows"] > 0
    assert "downside_alert_metrics" in report
    assert "downside_0p05_pred_lt_0_recall" in report["downside_alert_metrics"]["summary"]
    assert report["promotion_gate"]["recommendation"] in {
        "do_not_promote",
        "hold_for_more_validation",
    }
    assert report["leakage_audit"]["status"] == "pass"
    assert "baseline_comparison" in report
    assert "permutation_sanity" in report
    assert report["promotion_questions"]["ready_for_model_registration"] is False
    assert report["candidate"]["model_params_sha"] == "default_params"
