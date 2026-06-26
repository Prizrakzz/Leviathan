from __future__ import annotations

import io
import json
import subprocess
import sys

import pandas as pd

from leviathan.storage.paths import (
    gold_feature_set_version_key,
    gold_model_ready_baseline_metrics_key,
    gold_model_ready_manifest_key,
    gold_model_ready_matrix_key,
)
from leviathan.training.model_ready import (
    attach_model_ready_baselines_to_predictions,
    load_model_ready_training_dataset,
    model_ready_baseline_metrics_for_predictions,
    model_ready_metric_log_values,
    select_model_ready_features,
    training_frame_from_model_ready_matrix,
)


class _FakeS3:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    def get_object(self, *, Bucket: str, Key: str):  # noqa: N803
        return {"Body": io.BytesIO(self.objects[Key])}


def _parquet_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


def _matrix() -> pd.DataFrame:
    return pd.DataFrame({
        "source_dataset_version": ["gold_v"] * 6,
        "dataset_key": ["annual_physical_anomaly"] * 6,
        "commodity": ["corn_cbot"] * 6,
        "target_key": ["production_anomaly_pct"] * 6,
        "country": ["united_states"] * 6,
        "crop_year": [2018, 2019, 2020, 2021, 2022, 2023],
        "target_value": [None, 0.01, -0.02, 0.05, -0.03, 0.02],
        "actual_value": [100, 101, 98, 105, 97, 102],
        "trend_prediction": [None, 100, 100, 100, 100, 100],
        "prior_year_value": [None, 100, 101, 98, 105, 97],
        "trailing_mean_prediction": [None, 100, 100, 100, 100, 100],
        "zero_anomaly_baseline": [0.0] * 6,
        "prior_year_anomaly_baseline": [None, 0.0, 0.01, -0.02, 0.05, -0.03],
        "trailing_mean_anomaly_baseline": [None, 0.0, 0.0, 0.0, 0.0, 0.0],
        "trailing_trend_anomaly_baseline": [0.0] * 6,
        "history_years": [0, 1, 2, 3, 4, 5],
        "is_trainable": [False, False, True, True, True, True],
        "excluded_reason": ["insufficient_history", "insufficient_history", "", "", "", ""],
        "feature_a": [1, 2, 3, 4, 5, 6],
        "feature_b": [10, 20, 30, 40, 50, 60],
        "label_production_quantity": [100, 101, 98, 105, 97, 102],
    })


def _membership() -> pd.DataFrame:
    return pd.DataFrame({
        "dataset_version": ["gold_v"] * 4,
        "feature_set_id": ["preseason_physical"] * 4,
        "feature_set_version": ["1"] * 4,
        "feature_set_sha": ["abc"] * 4,
        "feature": [
            "feature_a",
            "label_production_quantity",
            "target_value",
            "zero_anomaly_baseline",
        ],
        "is_label": [False, True, False, False],
    })


def test_model_ready_feature_selection_excludes_labels_targets_and_baselines() -> None:
    features, meta = select_model_ready_features(
        _matrix(), _membership(), "preseason_physical"
    )

    assert features == ["feature_a"]
    assert meta["feature_set_id"] == "preseason_physical"
    assert meta["feature_set_catalog_sha"] == "abc"


def test_training_frame_filters_trainable_rows_and_uses_target_value() -> None:
    frame = training_frame_from_model_ready_matrix(_matrix(), ["feature_a"])

    assert list(frame.columns) == ["country", "crop_year", "feature_a", "target_value"]
    assert frame["crop_year"].tolist() == [2020, 2021, 2022, 2023]
    assert frame["target_value"].notna().all()


def test_loader_reads_manifest_matrix_feature_sets_and_baselines() -> None:
    model_version = "model_v"
    objects = {
        gold_model_ready_matrix_key(
            model_version, "annual_physical_anomaly", "corn_cbot", "production_anomaly_pct"
        ): _parquet_bytes(_matrix()),
        gold_model_ready_manifest_key(model_version): json.dumps({
            "source_dataset_version": "gold_v",
            "target_config_sha": "target-sha",
        }).encode("utf-8"),
        gold_feature_set_version_key("gold_v"): _parquet_bytes(_membership()),
        gold_model_ready_baseline_metrics_key(model_version): _parquet_bytes(pd.DataFrame({
            "dataset_key": ["annual_physical_anomaly"],
            "commodity": ["corn_cbot"],
            "target_key": ["production_anomaly_pct"],
            "baseline_name": ["zero_anomaly"],
            "n_rows": [4],
            "rmse": [0.03],
            "mae": [0.025],
            "directional_accuracy": [0.5],
        })),
    }

    loaded = load_model_ready_training_dataset(
        _FakeS3(objects),
        bucket="bucket",
        model_dataset_version=model_version,
        dataset_key="annual_physical_anomaly",
        commodity="corn_cbot",
        target_key="production_anomaly_pct",
        feature_set_id="preseason_physical",
    )

    assert loaded.source_dataset_version == "gold_v"
    assert loaded.feature_cols == ["feature_a"]
    assert loaded.target_col == "target_value"
    assert len(loaded.train_df) == 4
    assert loaded.manifest_uri.endswith(gold_model_ready_manifest_key(model_version))
    assert not loaded.baseline_metrics.empty


def test_baseline_metrics_are_fold_aligned_and_logged_flat() -> None:
    predictions = pd.DataFrame({
        "country": ["united_states", "united_states", "united_states"],
        "crop_year": [2021, 2022, 2023],
        "y_actual": [0.05, -0.03, 0.02],
        "y_pred": [0.04, -0.01, 0.01],
    })

    baseline_eval = model_ready_baseline_metrics_for_predictions(predictions, _matrix())
    metrics = model_ready_metric_log_values(predictions, baseline_eval)
    enriched = attach_model_ready_baselines_to_predictions(predictions, _matrix())

    assert set(baseline_eval["baseline_name"]) >= {"zero_anomaly", "trailing_mean"}
    assert "target_space_model_rmse" in metrics
    assert "best_baseline_rmse" in metrics
    assert "model_vs_best_baseline_rmse_delta" in metrics
    assert "zero_anomaly_baseline" in enriched.columns


def test_train_job_definition_exposes_model_ready_parameters() -> None:
    completed = subprocess.run(
        [sys.executable, "jobs/utils/register_train_jobdef.py", "--dry-run"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    command = payload["containerProperties"]["command"]
    params = payload["parameters"]

    assert "--model-dataset-version" in command
    assert "--dataset-key" in command
    assert "--target-key" in command
    assert params["model_dataset_version"] == "none"
    assert params["dataset_key"] == "annual_physical_anomaly"
