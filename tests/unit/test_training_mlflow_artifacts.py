from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

from leviathan.training.cv import FoldResult, WalkForwardResult
from leviathan.training.mlflow_artifacts import (
    build_model_replay_sample,
    feature_importance_frame,
    fit_final_model,
    fold_metrics_frame,
    selected_features_frame,
)
from leviathan.training.mlflow_replay import compare_logged_predictions


def _train_df() -> pd.DataFrame:
    return pd.DataFrame({
        "country": ["us", "us", "br", "br", "ar", "ar"],
        "crop_year": [2020, 2021, 2020, 2021, 2020, 2021],
        "feature_a": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        "feature_b": [6.0, 5.0, 4.0, 3.0, 2.0, 1.0],
        "target_value": [0.1, 0.2, -0.1, -0.2, 0.3, 0.4],
    })


def test_fold_metrics_frame_keeps_one_row_per_fold() -> None:
    result = WalkForwardResult(
        folds=[
            FoldResult(
                test_year=2021,
                fold_end_train_year=2020,
                n_train_rows=4,
                n_test_rows=2,
                rmse=0.1,
                mae=0.08,
                directional_accuracy=0.5,
            )
        ],
        predictions=pd.DataFrame(),
        rmse=0.1,
        mae=0.08,
        directional_accuracy=0.5,
        n_folds=1,
    )

    out = fold_metrics_frame(result)

    assert out.loc[0, "test_year"] == 2021
    assert out.loc[0, "rmse"] == 0.1
    assert out.loc[0, "directional_accuracy"] == 0.5


def test_selected_features_frame_is_ranked() -> None:
    out = selected_features_frame(["feature_b", "feature_a"])

    assert out.to_dict(orient="records") == [
        {"feature_rank": 1, "feature": "feature_b"},
        {"feature_rank": 2, "feature": "feature_a"},
    ]


def test_final_model_replay_sample_contains_logged_predictions() -> None:
    df = _train_df()
    features = ["feature_a", "feature_b"]
    model = fit_final_model(
        RandomForestRegressor(n_estimators=5, random_state=1),
        df,
        features,
        "target_value",
    )

    sample = build_model_replay_sample(model, df, features, "target_value")
    replayed = model.predict(sample[features])

    assert set(["country", "crop_year", "target_value", "y_pred_logged"]).issubset(sample.columns)
    assert np.allclose(sample["y_pred_logged"], replayed)


def test_feature_importance_frame_sorts_descending() -> None:
    df = _train_df()
    features = ["feature_a", "feature_b"]
    model = fit_final_model(
        RandomForestRegressor(n_estimators=5, random_state=1),
        df,
        features,
        "target_value",
    )

    out = feature_importance_frame(model, features)

    assert set(out.columns) == {"feature", "importance"}
    assert out["importance"].is_monotonic_decreasing


def test_compare_logged_predictions_applies_tolerance() -> None:
    status, max_error, mean_error = compare_logged_predictions(
        pd.Series([1.0, 2.0]),
        pd.Series([1.0, 2.000000001]),
        tolerance=1e-6,
    )

    assert status == "pass"
    assert max_error < 1e-6
    assert mean_error < 1e-6

    failed, _, _ = compare_logged_predictions(
        pd.Series([1.0]),
        pd.Series([1.01]),
        tolerance=1e-6,
    )
    assert failed == "fail"
