from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
from leviathan.training.cv import FoldResult, WalkForwardResult
from leviathan.training.mlflow_artifacts import (
    build_model_replay_sample,
    feature_importance_frame,
    fit_final_model,
    fold_metrics_frame,
    log_experiment_review_bundle,
    log_fitted_model,
    selected_features_frame,
)
from leviathan.training.mlflow_replay import compare_logged_predictions
from sklearn.ensemble import RandomForestRegressor


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


def test_local_mlflow_smoke_logs_psd_review_artifacts(tmp_path) -> None:
    import mlflow
    from mlflow.tracking import MlflowClient

    tracking_uri = f"sqlite:///{(tmp_path / 'mlflow.db').as_posix()}"
    artifact_uri = (tmp_path / "artifacts").as_uri()
    mlflow.set_tracking_uri(tracking_uri)
    client = MlflowClient(tracking_uri=tracking_uri)
    experiment_id = client.create_experiment(
        "phase8_psd_acceptance_smoke",
        artifact_location=artifact_uri,
    )

    train_df = _train_df()
    features = ["feature_a", "feature_b"]
    final_model = fit_final_model(
        RandomForestRegressor(n_estimators=5, random_state=7),
        train_df,
        features,
        "target_value",
    )
    replay_sample = build_model_replay_sample(
        final_model,
        train_df,
        features,
        "target_value",
    )
    predictions = pd.DataFrame({
        "country": ["us", "br"],
        "crop_year": [2021, 2021],
        "y_actual": [0.2, -0.2],
        "y_pred": [0.18, -0.15],
    })
    result = WalkForwardResult(
        folds=[
            FoldResult(
                test_year=2021,
                fold_end_train_year=2020,
                n_train_rows=3,
                n_test_rows=2,
                rmse=0.04,
                mae=0.035,
                directional_accuracy=1.0,
            )
        ],
        predictions=predictions,
        rmse=0.04,
        mae=0.035,
        directional_accuracy=1.0,
        n_folds=1,
    )
    args = SimpleNamespace(
        commodity="corn_cbot",
        model="random_forest",
        feature_set="preseason_physical",
        tier="climate",
        target_key="psd_production_anomaly_pct",
        target="",
        dataset_version=None,
        model_dataset_version="20260627T121215Z_phase5_psd_smoke",
        source_dataset_version="20260626T010217Z_6725de02_phase7_full",
        cv_policy="expanding_full_history",
        min_train_years=3,
        train_start_year=None,
        rolling_window_years=None,
    )

    with mlflow.start_run(
        experiment_id=experiment_id,
        run_name="phase8-local-smoke",
    ) as run:
        log_fitted_model(
            mlflow,
            model=final_model,
            model_family="sklearn",
            train_df=train_df,
            feature_cols=features,
            target_col="target_value",
        )
        log_experiment_review_bundle(
            mlflow,
            result=result,
            predictions=predictions,
            train_df=train_df,
            feature_cols=features,
            target_col="target_value",
            final_model=final_model,
            replay_sample=replay_sample,
            baseline_metrics=pd.DataFrame({
                "baseline_name": ["zero_anomaly"],
                "rmse": [0.05],
                "mae": [0.04],
            }),
            gaps=None,
            args=args,
            run_id=run.info.run_id,
            predictions_uri=None,
            logged_metadata={
                "feature_set_sha": "feature-sha",
                "data_fingerprint": "data-fp",
            },
        )
        run_id = run.info.run_id

    def artifact_paths(path: str = "") -> set[str]:
        out: set[str] = set()
        for item in client.list_artifacts(run_id, path):
            out.add(item.path)
            if item.is_dir:
                out.update(artifact_paths(item.path))
        return out

    paths = artifact_paths()
    assert "metadata/training_summary.json" in paths
    assert "metadata/selected_features.json" in paths
    assert "tables/cv_predictions.parquet" in paths
    assert "tables/fold_metrics.parquet" in paths
    assert "tables/model_replay_sample.parquet" in paths
    assert "logs/training.log" in paths

    run_data = client.get_run(run_id).data
    assert run_data.tags["fitted_model_flavor"] == "sklearn"
