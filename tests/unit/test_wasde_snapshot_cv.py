from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from leviathan.training.wasde_snapshot_cv import (
    collapse_snapshot_predictions,
    ensure_snapshot_cv_columns,
    grouped_walk_forward_splits,
    resolve_snapshot_feature_stack_id,
    run_grouped_walk_forward_cv,
    score_snapshot_predictions,
    select_snapshot_feature_stack,
)
from leviathan.training.wasde_snapshot_smoke import run_wasde_snapshot_training_smoke
from sklearn.dummy import DummyRegressor


def _matrix(
    *,
    start_year: int = 2000,
    n_years: int = 8,
    snapshots_per_group: int = 3,
    event_years: int = 3,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for offset in range(n_years):
        year = start_year + offset
        is_event = offset < event_years
        target_value = -0.20 if is_event else 0.05 + offset / 100.0
        for snap in range(snapshots_per_group):
            month = 5 + snap
            rows.append({
                "dataset_key": "corn_wasde_snapshot_solo",
                "contract_key": "corn_cbot",
                "origin_key": "united_states",
                "target_market_year": year,
                "target_key": "psd_production_anomaly_pct",
                "as_of_date": f"{year}-0{month}-12",
                "snapshot_stage": "preseason" if snap == 0 else "early_season",
                "cv_group": f"corn_cbot|united_states|{year}",
                "cv_time": year,
                "sample_weight": 1.0 / snapshots_per_group,
                "target_value": target_value,
                "is_trainable": True,
                "target_event_label": is_event,
                "target_event_threshold": 0.10,
                "target_event_direction": "lower_is_stress",
                "zero_anomaly_baseline": 0.0,
                "prior_year_anomaly_baseline": -0.15 if is_event else 0.03,
                "wasde_production_latest": 100.0 + offset + snap,
                "wasde_production_mom_revision": float(snap),
                "wasde_all_missing": np.nan,
                "static_dense_feature": float(offset),
                "constant_feature": 1.0,
                "ultra_sparse_feature": 7.0 if offset == 0 and snap == 0 else np.nan,
                "label_bad": 99.0,
                "target_bad": -1.0,
            })
    return pd.DataFrame(rows)


def test_grouped_walk_forward_split_never_splits_annual_group() -> None:
    matrix = _matrix(n_years=8, snapshots_per_group=4)
    folds = grouped_walk_forward_splits(matrix, min_train_years=5)

    assert [fold.test_year for fold in folds] == [2005, 2006, 2007]
    for fold in folds:
        train = matrix.loc[list(fold.train_index)]
        test = matrix.loc[list(fold.test_index)]
        assert train["cv_time"].max() < test["cv_time"].min()
        assert set(train["cv_group"]).isdisjoint(set(test["cv_group"]))
        assert fold.n_test_rows == 4
        assert fold.n_test_groups == 1


def test_fold_sample_weights_sum_to_one_per_test_group() -> None:
    matrix = _matrix(n_years=7, snapshots_per_group=5)
    folds = grouped_walk_forward_splits(matrix, min_train_years=5)

    for fold in folds:
        test = matrix.loc[list(fold.test_index)]
        weights = test.groupby([
            "dataset_key",
            "contract_key",
            "origin_key",
            "target_market_year",
            "target_key",
        ])["sample_weight"].sum()
        assert weights.iloc[0] == pytest.approx(1.0)


def test_ensure_snapshot_cv_columns_derives_missing_group_helpers() -> None:
    matrix = _matrix(n_years=3, snapshots_per_group=4).drop(
        columns=["cv_group", "cv_time", "sample_weight"]
    )

    prepared = ensure_snapshot_cv_columns(matrix)

    assert {"cv_group", "cv_time", "sample_weight"}.issubset(prepared.columns)
    assert prepared["cv_time"].tolist()[:4] == [2000, 2000, 2000, 2000]
    weights = prepared.groupby([
        "dataset_key",
        "contract_key",
        "origin_key",
        "target_market_year",
        "target_key",
    ])["sample_weight"].sum()
    assert weights.tolist() == pytest.approx([1.0, 1.0, 1.0])


def test_feature_stack_selection_prunes_leakage_missing_constant_and_sparse_features() -> None:
    selection = select_snapshot_feature_stack(
        _matrix(),
        feature_stack_id="preseason_static_plus_wasde_revision",
        feature_columns=[
            "wasde_production_latest",
            "wasde_all_missing",
            "static_dense_feature",
            "constant_feature",
            "ultra_sparse_feature",
            "label_bad",
            "target_bad",
        ],
        min_non_null_rate=0.2,
    )

    assert selection.selected_features == ("static_dense_feature", "wasde_production_latest")
    dropped = selection.dropped_features.set_index("feature")
    assert dropped.loc["label_bad", "reason"] == "leakage_like_name"
    assert dropped.loc["target_bad", "reason"] == "leakage_like_name"
    assert dropped.loc["wasde_all_missing", "reason"] == "all_missing"
    assert dropped.loc["constant_feature", "reason"] == "constant"
    assert dropped.loc["ultra_sparse_feature", "reason"] == "too_sparse"


def test_wasde_only_stack_keeps_only_wasde_columns() -> None:
    selection = select_snapshot_feature_stack(
        _matrix(),
        feature_stack_id="wasde_monthly_revision",
        feature_columns=["wasde_production_latest", "static_dense_feature"],
    )

    assert selection.selected_features == ("wasde_production_latest",)
    dropped = selection.dropped_features.set_index("feature")
    assert dropped.loc["static_dense_feature", "reason"] == "not_wasde_revision_feature"


def test_static_snapshot_stack_drops_wasde_columns() -> None:
    selection = select_snapshot_feature_stack(
        _matrix(),
        feature_stack_id="static_snapshot_context",
        feature_columns=["wasde_production_latest", "static_dense_feature"],
    )

    assert selection.selected_features == ("static_dense_feature",)
    dropped = selection.dropped_features.set_index("feature")
    assert dropped.loc["wasde_production_latest", "reason"] == "not_static_snapshot_feature"


def test_resolve_snapshot_feature_stack_from_feature_set() -> None:
    assert resolve_snapshot_feature_stack_id("wasde_monthly_revision") == "wasde_monthly_revision"
    assert (
        resolve_snapshot_feature_stack_id("corn_preseason_core_plus_wasde")
        == "preseason_static_plus_wasde_revision"
    )
    assert resolve_snapshot_feature_stack_id("corn_preseason_core") == "static_snapshot_context"
    assert (
        resolve_snapshot_feature_stack_id("corn_preseason_core", "wasde_monthly_revision")
        == "wasde_monthly_revision"
    )


def test_run_grouped_walk_forward_cv_produces_heldout_predictions() -> None:
    matrix = _matrix(n_years=9, event_years=4)
    result = run_grouped_walk_forward_cv(
        matrix,
        model=DummyRegressor(strategy="mean"),
        feature_stack_id="preseason_static_plus_wasde_revision",
        feature_columns=["wasde_production_latest", "static_dense_feature"],
        min_train_years=5,
    )

    assert len(result.folds) == 4
    assert set(result.predictions["fold_test_year"]) == {2005, 2006, 2007, 2008}
    assert result.snapshot_metrics["n"] == pytest.approx(12.0)
    assert result.annual_metrics["n"] == pytest.approx(4.0)
    assert result.baseline_diagnostics["baseline_name"].isin(["zero_anomaly"]).any()


def test_fold_local_pruning_drops_features_constant_in_early_training_fold() -> None:
    matrix = _matrix(n_years=9, event_years=4)
    matrix["wasde_late_varying_feature"] = np.where(
        matrix["target_market_year"] < 2006,
        1.0,
        matrix["target_market_year"].astype(float),
    )

    result = run_grouped_walk_forward_cv(
        matrix,
        model=DummyRegressor(strategy="mean"),
        feature_stack_id="wasde_monthly_revision",
        feature_columns=["wasde_production_latest", "wasde_late_varying_feature"],
        min_train_years=5,
    )

    first_fold = result.predictions.loc[result.predictions["fold_test_year"] == 2005]
    assert first_fold["fold_feature_count"].unique().tolist() == [1]


def test_score_predictions_reports_false_negatives_for_zero_like_predictions() -> None:
    matrix = _matrix(n_years=4, event_years=2)
    predictions = matrix[[
        "dataset_key",
        "contract_key",
        "origin_key",
        "target_market_year",
        "target_key",
        "as_of_date",
        "snapshot_stage",
        "cv_group",
        "cv_time",
        "sample_weight",
        "target_event_label",
        "target_event_threshold",
        "target_event_direction",
    ]].copy()
    predictions["y_actual"] = matrix["target_value"]
    predictions["y_pred"] = 0.0

    _, annual = score_snapshot_predictions(predictions)

    assert annual["event_count"] == pytest.approx(2.0)
    assert annual["false_negative_count"] == pytest.approx(2.0)
    assert annual["recall"] == pytest.approx(0.0)


def test_collapse_snapshot_predictions_latest_uses_last_snapshot_per_group() -> None:
    matrix = _matrix(n_years=2, snapshots_per_group=3)
    predictions = matrix[[
        "dataset_key",
        "contract_key",
        "origin_key",
        "target_market_year",
        "target_key",
        "as_of_date",
        "snapshot_stage",
    ]].copy()
    predictions["y_actual"] = matrix["target_value"]
    predictions["y_pred"] = np.arange(len(predictions), dtype=float)
    predictions["sample_weight"] = matrix["sample_weight"]

    collapsed = collapse_snapshot_predictions(predictions, policy="latest")

    assert len(collapsed) == 2
    assert collapsed["y_pred"].tolist() == [2.0, 5.0]


def test_smoke_wrapper_skips_training_when_diagnostics_fail() -> None:
    matrix = pd.concat([_matrix(n_years=6), _matrix(n_years=6).iloc[[0]]], ignore_index=True)

    result = run_wasde_snapshot_training_smoke(
        matrix,
        model=DummyRegressor(strategy="mean"),
        feature_stack_id="wasde_monthly_revision",
        feature_columns=["wasde_production_latest"],
        min_train_years=5,
        min_trainable_annual_groups=5,
    )

    assert result.cv_result is None
    assert result.readiness["training_status"] == "skipped_failed_diagnostics"


def test_smoke_wrapper_reports_cv_failure_without_raising() -> None:
    result = run_wasde_snapshot_training_smoke(
        _matrix(n_years=8, event_years=2),
        model=DummyRegressor(strategy="mean"),
        feature_stack_id="wasde_monthly_revision",
        feature_columns=["wasde_all_missing"],
        min_train_years=5,
        min_trainable_annual_groups=5,
        min_event_groups=1,
    )

    assert result.cv_result is None
    assert result.readiness["status"] == "fail"
    assert result.readiness["training_status"] == "failed_cv"
    assert "selected zero usable features" in result.readiness["training_error"]


def test_smoke_wrapper_runs_when_diagnostics_warn_but_do_not_fail() -> None:
    result = run_wasde_snapshot_training_smoke(
        _matrix(n_years=8, event_years=1),
        model=DummyRegressor(strategy="mean"),
        feature_stack_id="wasde_monthly_revision",
        feature_columns=["wasde_production_latest"],
        min_train_years=5,
        min_trainable_annual_groups=5,
        min_event_groups=3,
    )

    assert result.cv_result is not None
    assert result.readiness["training_status"] == "completed"
    assert result.readiness["cv_fold_count"] == 3
    assert result.readiness["selected_feature_count"] == 1
