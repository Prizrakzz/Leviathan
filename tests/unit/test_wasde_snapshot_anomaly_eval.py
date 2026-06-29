from __future__ import annotations

import pandas as pd
import pytest

from leviathan.model_datasets.wasde_snapshot_anomaly_eval import (
    aggregate_snapshot_detector_scores,
    build_rolling_year_splits,
    evaluate_wasde_snapshot_anomaly_scores,
    prepare_score_evaluation_frame,
    select_alert_threshold,
    validate_snapshot_weights,
)
from leviathan.model_datasets.wasde_snapshot_targets import GROUP_KEY as TARGET_GROUP_KEY


def _matrix_row(
    year: int,
    *,
    score: float,
    event: bool,
    snapshot: str = "06-12",
    origin: str = "united_states",
) -> dict[str, object]:
    as_of = f"{year}-{snapshot}"
    return {
        "dataset_key": "corn_wasde_snapshot_solo",
        "contract_key": "corn_cbot",
        "origin_key": origin,
        "target_market_year": year,
        "target_key": "psd_stock_to_use_anomaly_pct",
        "as_of_date": as_of,
        "snapshot_stage": "preseason",
        "target_event_label": event,
        "target_value": -0.2 if event else 0.1,
        "target_event_threshold": 0.1,
        "target_event_direction": "lower_is_stress",
        "is_trainable": True,
        "sample_weight": 1.0,
        "cv_group": f"corn_cbot|{origin}|{year}",
        "cv_time": year,
        "zero_anomaly_baseline": 0.0,
        "prior_year_anomaly_baseline": -0.2 if event else 0.1,
        "trailing_mean_anomaly_baseline": 0.0,
        "trailing_trend_anomaly_baseline": 0.0,
        "_score": score,
    }


def _score_row(matrix_row: dict[str, object], *, score: float | None = None) -> dict[str, object]:
    return {
        "dataset_key": matrix_row["dataset_key"],
        "contract_key": matrix_row["contract_key"],
        "origin_key": matrix_row["origin_key"],
        "target_market_year": matrix_row["target_market_year"],
        "target_key": matrix_row["target_key"],
        "as_of_date": matrix_row["as_of_date"],
        "snapshot_stage": matrix_row["snapshot_stage"],
        "detector_id": "composite_balance_sheet_stress",
        "score_name": "wasde_composite_balance_sheet_stress",
        "source_feature": "multiple",
        "source_attribute": "balance_sheet",
        "source_transform": "equal_weight_components",
        "raw_value": None,
        "score_value": matrix_row["_score"] if score is None else score,
        "stress_direction": "higher_is_stress",
        "prior_observation_count": 10,
        "normalization_group_used": "contract_origin_stage",
        "component_count": 3,
        "score_null_reason": "",
    }


def _frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = [
        _matrix_row(2000, score=0.05, event=False),
        _matrix_row(2001, score=0.85, event=True),
        _matrix_row(2002, score=0.10, event=False),
        _matrix_row(2003, score=0.90, event=True),
        _matrix_row(2004, score=0.15, event=False),
    ]
    matrix = pd.DataFrame(rows).drop(columns=["_score"])
    scores = pd.DataFrame([_score_row(row) for row in rows])
    return scores, matrix


def test_grouped_eval_keeps_annual_group_together() -> None:
    scores, matrix = _frames()
    joined = prepare_score_evaluation_frame(scores, matrix)
    snapshot_scores = aggregate_snapshot_detector_scores(joined)
    folds = build_rolling_year_splits(snapshot_scores, min_train_years=2)

    assert folds
    for fold in folds:
        train_groups = set(
            map(tuple, snapshot_scores.loc[fold["train_index"], TARGET_GROUP_KEY].to_numpy())
        )
        test_groups = set(
            map(tuple, snapshot_scores.loc[fold["test_index"], TARGET_GROUP_KEY].to_numpy())
        )
        assert train_groups.isdisjoint(test_groups)
        assert snapshot_scores.loc[fold["train_index"], "target_market_year"].max() < fold["test_year"]


def test_alert_threshold_fit_on_train_only() -> None:
    scores, matrix = _frames()
    joined = prepare_score_evaluation_frame(scores, matrix)
    snapshot_scores = aggregate_snapshot_detector_scores(joined)
    train = snapshot_scores.loc[snapshot_scores["target_market_year"] <= 2002]
    threshold, metric, candidate_count = select_alert_threshold(train)

    with_future = pd.concat([
        train,
        snapshot_scores.loc[snapshot_scores["target_market_year"] > 2002].assign(score_value=999.0),
    ])
    threshold_again, metric_again, candidate_count_again = select_alert_threshold(train)

    assert threshold_again == pytest.approx(threshold)
    assert metric_again == pytest.approx(metric, nan_ok=True)
    assert candidate_count_again == candidate_count
    assert with_future["score_value"].max() == 999.0


def test_event_recall_any_alert() -> None:
    scores, matrix = _frames()
    result = evaluate_wasde_snapshot_anomaly_scores(
        scores,
        matrix,
        min_train_years=2,
        candidate_quantiles=(0.50, 0.80),
    )

    assert not result.fold_metrics.empty
    assert result.fold_metrics["event_count"].sum() >= 1
    assert result.fold_metrics["event_recall_any_alert"].dropna().max() >= 0.0
    assert set(result.baseline_comparison["baseline_name"]) >= {
        "zero_anomaly",
        "prior_year",
    }


def test_snapshot_weights_sum_to_one_per_annual_group() -> None:
    scores, matrix = _frames()
    two_snapshots = matrix.copy()
    two_snapshots.loc[:, "sample_weight"] = 0.5
    later = two_snapshots.copy()
    later["as_of_date"] = later["target_market_year"].astype(str) + "-07-12"
    later["snapshot_stage"] = "early_season"
    matrix = pd.concat([two_snapshots, later], ignore_index=True)
    scores = pd.concat([
        pd.DataFrame([_score_row(row) for row in two_snapshots.assign(_score=[0.1, 0.8, 0.1, 0.9, 0.1]).to_dict("records")]),
        pd.DataFrame([_score_row(row) for row in later.assign(_score=[0.2, 0.9, 0.2, 0.95, 0.2]).to_dict("records")]),
    ], ignore_index=True)
    joined = prepare_score_evaluation_frame(scores, matrix)
    snapshot_scores = aggregate_snapshot_detector_scores(joined)

    bad = validate_snapshot_weights(snapshot_scores)

    assert bad.empty
