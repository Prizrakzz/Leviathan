from __future__ import annotations

import pandas as pd

from leviathan.training.certification import downside_alert_metrics
from leviathan.training.phase8_alerts import (
    baseline_alert_metrics_frame,
    target_reframe_audit_frame,
)


def _matrix() -> pd.DataFrame:
    return pd.DataFrame({
        "country": ["us", "us", "br", "br"],
        "crop_year": [2020, 2021, 2020, 2021],
        "target_value": [-0.12, -0.04, 0.02, -0.08],
        "prior_year_anomaly_baseline": [-0.02, -0.03, 0.01, 0.01],
        "zero_anomaly_baseline": [0.0, 0.0, 0.0, 0.0],
        "trailing_mean_anomaly_baseline": [-0.10, -0.01, 0.01, -0.02],
        "trailing_trend_anomaly_baseline": [-0.05, -0.01, 0.01, -0.01],
        "is_trainable": [True, True, True, True],
    })


def test_downside_alert_metrics_counts_false_negatives() -> None:
    predictions = pd.DataFrame({
        "country": ["us", "us", "br", "br"],
        "crop_year": [2020, 2021, 2020, 2021],
        "y_actual": [-0.12, -0.04, 0.02, -0.08],
        "y_pred": [-0.01, -0.02, -0.03, 0.01],
    })

    out = downside_alert_metrics(predictions, thresholds=(-0.05,), min_event_rows=1)
    row = next(
        item for item in out["rows"]
        if item["threshold"] == -0.05 and item["alert_policy"] == "pred_lt_0"
    )

    assert row["n_events"] == 2
    assert row["true_positives"] == 1
    assert row["false_negatives"] == 1
    assert row["false_positives"] == 2
    assert row["recall"] == 0.5
    assert row["validated"] is True


def test_target_reframe_audit_reports_fixed_downside_events() -> None:
    audit = target_reframe_audit_frame(_matrix())
    trainable = audit.loc[audit["scope"] == "trainable_rows"].iloc[0]

    assert trainable["row_count"] == 4
    assert trainable["downside_0p05_event_count"] == 2
    assert trainable["worsened_vs_prior_year_count"] == 3


def test_baseline_alert_metrics_scores_materialized_baselines() -> None:
    metrics = baseline_alert_metrics_frame(
        _matrix(),
        baseline_columns=("prior_year_anomaly_baseline",),
        thresholds=(-0.05,),
    )
    row = metrics.loc[metrics["alert_policy"] == "pred_lt_0"].iloc[0]

    assert row["baseline_name"] == "prior_year"
    assert row["n_events"] == 2
    assert row["n_alerts"] == 2
    assert row["false_negatives"] == 1
