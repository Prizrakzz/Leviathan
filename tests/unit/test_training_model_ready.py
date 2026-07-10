from __future__ import annotations

import io
import json
import subprocess
import sys
from types import SimpleNamespace

import pandas as pd
from leviathan.model_datasets.version_status import ModelDatasetVersionStatus
from leviathan.storage.paths import (
    gold_feature_set_version_key,
    gold_model_ready_baseline_metrics_key,
    gold_model_ready_feature_set_version_key,
    gold_model_ready_manifest_key,
    gold_model_ready_matrix_key,
)
from leviathan.training.cv import walk_forward_cv
from leviathan.training.model_ready import (
    attach_model_ready_baselines_to_predictions,
    load_model_ready_training_dataset,
    model_ready_baseline_metrics_for_predictions,
    model_ready_metric_log_values,
    select_model_ready_features,
    training_frame_from_model_ready_matrix,
)

from jobs.batch.train_commodity import _prediction_model_family, _write_predictions


class _FakeS3:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    def get_object(self, *, Bucket: str, Key: str):  # noqa: N803
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes):  # noqa: N803
        self.objects[Key] = Body
        return {"ETag": '"fake"'}


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


def _snapshot_matrix() -> pd.DataFrame:
    base = _matrix().loc[_matrix()["crop_year"] >= 2019].copy()
    rows = []
    for _, row in base.iterrows():
        for stage, date_value, offset in (
            ("early_inseason", "06-01", 0.0),
            ("midseason", "08-01", 0.5),
        ):
            out = row.copy()
            out["dataset_key"] = "psd_snd_anomaly_snapshot"
            out["target_key"] = "psd_production_anomaly_pct"
            out["snapshot_stage"] = stage
            out["as_of_date"] = f"{int(row['crop_year'])}-{date_value}"
            out["snapshot_policy"] = "named_stages_v1"
            out["feature_a"] = float(out["feature_a"]) + offset
            rows.append(out)
    return pd.DataFrame(rows)


def test_model_ready_feature_selection_excludes_labels_targets_and_baselines() -> None:
    features, meta = select_model_ready_features(
        _matrix(), _membership(), "preseason_physical"
    )

    assert features == ["feature_a"]
    assert meta["feature_set_id"] == "preseason_physical"
    assert meta["feature_set_catalog_sha"] == "abc"


def test_model_ready_feature_selection_prunes_ultra_sparse_dense_weather() -> None:
    matrix = pd.DataFrame({
        "country": ["united_states"] * 6,
        "crop_year": [2018, 2019, 2020, 2021, 2022, 2023],
        "is_trainable": [True] * 6,
        "target_value": [0.1, -0.1, 0.2, -0.2, 0.0, 0.05],
        "weather_dense_precip_z_mean_silking": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        "weather_dense_soil_z_mean_silking": [None, None, 1.0, 2.0, None, None],
        "weather_dense_ndvi_z_coverage_share_silking": [None, None, None, 1.0, None, None],
    })
    membership = pd.DataFrame({
        "dataset_version": ["gold_v"] * 3,
        "feature_set_id": ["inseason_weather_dense"] * 3,
        "feature_set_version": ["1"] * 3,
        "feature_set_sha": ["dense-sha"] * 3,
        "feature": [
            "weather_dense_precip_z_mean_silking",
            "weather_dense_soil_z_mean_silking",
            "weather_dense_ndvi_z_coverage_share_silking",
        ],
        "is_label": [False, False, False],
    })

    features, meta = select_model_ready_features(
        matrix, membership, "inseason_weather_dense"
    )

    assert features == [
        "weather_dense_precip_z_mean_silking",
        "weather_dense_soil_z_mean_silking",
    ]
    assert meta["pruned_feature_count"] == "1"
    assert meta["review_feature_count"] == "1"
    assert meta["pruned_features"] == "weather_dense_ndvi_z_coverage_share_silking"
    assert meta["review_features"] == "weather_dense_soil_z_mean_silking"


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
    assert loaded.model_dataset_status.status == "unknown"


def test_loader_prefers_model_ready_feature_sets_when_manifest_declares_them() -> None:
    model_version = "model_snapshot_v"
    source_version = "gold_v"
    matrix = _snapshot_matrix().assign(
        psd_production_latest_estimate_as_of=[float(i) for i in range(len(_snapshot_matrix()))],
        psd_production_mom_revision=[0.1] * len(_snapshot_matrix()),
    )
    model_ready_membership = pd.DataFrame({
        "dataset_version": [model_version, model_version],
        "feature_set_id": ["psd_monthly_vintage_features"] * 2,
        "feature_set_version": ["1", "1"],
        "feature_set_sha": ["snapshot-sha", "snapshot-sha"],
        "feature": [
            "psd_production_latest_estimate_as_of",
            "psd_production_mom_revision",
        ],
        "feature_family": ["psd_monthly_vintage", "psd_monthly_vintage"],
        "semantic_scope": ["official_revision", "official_revision"],
        "policy": ["fundamental_physical", "fundamental_physical"],
        "mechanism": [
            "official_balance_sheet_vintage_revision",
            "official_balance_sheet_vintage_revision",
        ],
        "sources": ["psd", "psd"],
        "source_cadence": ["monthly", "monthly"],
        "empirical_scope": ["commodity", "commodity"],
        "groups": ["", ""],
        "is_label": [False, False],
        "row_count": [len(matrix), len(matrix)],
        "commodity_count": [1, 1],
        "non_null_rate": [1.0, 1.0],
        "target_compatibility": ["psd_production_anomaly", "psd_production_anomaly"],
        "missingness_policy": ["tree_models_allow_nan", "tree_models_allow_nan"],
        "min_lag_days": [0, 0],
    })
    feature_sets_key = gold_model_ready_feature_set_version_key(model_version)
    objects = {
        gold_model_ready_matrix_key(
            model_version, "psd_snd_anomaly_snapshot", "corn_cbot", "psd_production_anomaly_pct"
        ): _parquet_bytes(matrix),
        gold_model_ready_manifest_key(model_version): json.dumps({
            "source_dataset_version": source_version,
            "outputs": {"model_ready_feature_sets_key": feature_sets_key},
        }).encode("utf-8"),
        feature_sets_key: _parquet_bytes(model_ready_membership),
        gold_feature_set_version_key(source_version): _parquet_bytes(_membership()),
        gold_model_ready_baseline_metrics_key(model_version): _parquet_bytes(pd.DataFrame()),
    }

    loaded = load_model_ready_training_dataset(
        _FakeS3(objects),
        bucket="bucket",
        model_dataset_version=model_version,
        dataset_key="psd_snd_anomaly_snapshot",
        commodity="corn_cbot",
        target_key="psd_production_anomaly_pct",
        feature_set_id="psd_monthly_vintage_features",
    )

    assert loaded.feature_cols == [
        "psd_production_latest_estimate_as_of",
        "psd_production_mom_revision",
    ]
    assert loaded.feature_set_meta["feature_set_catalog_sha"] == "snapshot-sha"


def test_loader_attaches_configured_model_dataset_status() -> None:
    model_version = "20260627T121215Z_phase5_psd_smoke"
    objects = {
        gold_model_ready_matrix_key(
            model_version, "annual_physical_anomaly", "corn_cbot", "production_anomaly_pct"
        ): _parquet_bytes(_matrix()),
        gold_model_ready_manifest_key(model_version): json.dumps({
            "source_dataset_version": "gold_v",
            "target_config_sha": "target-sha",
        }).encode("utf-8"),
        gold_feature_set_version_key("gold_v"): _parquet_bytes(_membership()),
        gold_model_ready_baseline_metrics_key(model_version): _parquet_bytes(pd.DataFrame()),
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

    assert loaded.model_dataset_status.status == "active"
    assert loaded.model_dataset_status.target_source == "psd"


def test_prediction_model_family_routes_psd_legacy_and_snapshot_outputs() -> None:
    active = SimpleNamespace(
        model_dataset_status=ModelDatasetVersionStatus(
            dataset_version="active_v",
            status="active",
            default_discovery_allowed=True,
        )
    )
    legacy = SimpleNamespace(
        model_dataset_status=ModelDatasetVersionStatus(
            dataset_version="legacy_v",
            status="legacy",
            default_discovery_allowed=False,
        )
    )

    assert _prediction_model_family(
        SimpleNamespace(dataset_key="psd_snd_anomaly"),
        {"target_source": "psd", "target_family": "psd_production_anomaly"},
        active,
    ) == "psd_production_anomaly"
    assert _prediction_model_family(
        SimpleNamespace(dataset_key="psd_snd_anomaly_snapshot"),
        {"target_source": "psd", "target_family": "psd_production_anomaly"},
        active,
    ) == "psd_snd_anomaly_snapshot"
    assert _prediction_model_family(
        SimpleNamespace(dataset_key="annual_physical_anomaly"),
        {},
        legacy,
    ) == "legacy_faostat_annual_anomaly"


def test_prediction_writer_keys_include_cv_policy_to_preserve_sweep_variants() -> None:
    s3 = _FakeS3({})
    args = SimpleNamespace(
        commodity="corn_cbot",
        feature_set="preseason_physical",
        tier=None,
        target_key="psd_production_anomaly_pct",
        target=None,
        model_dataset_version="model_v",
        dataset_key="psd_snd_anomaly",
        source_dataset_version="gold_v",
        model="xgboost",
        cv_policy="rolling_25y",
        prediction_model_family="psd_production_anomaly",
    )
    predictions = pd.DataFrame({
        "country": ["united_states"],
        "crop_year": [2024],
        "y_actual": [0.01],
        "y_pred": [0.02],
    })

    uri = _write_predictions(s3, "bucket", args, predictions, "run-1", "sha-1")

    assert uri is not None
    assert uri.endswith(
        "corn_cbot__preseason_physical__psd_snd_anomaly__"
        "psd_production_anomaly_pct__xgboost__rolling_25y.parquet"
    )
    key = uri.removeprefix("s3://bucket/")
    written = pd.read_parquet(io.BytesIO(s3.objects[key]))
    assert written.loc[0, "cv_policy"] == "rolling_25y"
    assert written.loc[0, "model_dataset_version"] == "model_v"


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


def test_snapshot_model_ready_training_frame_preserves_row_identity() -> None:
    matrix = _snapshot_matrix()
    frame = training_frame_from_model_ready_matrix(matrix, ["feature_a"])

    assert {"snapshot_stage", "as_of_date"}.issubset(frame.columns)
    assert len(frame) == 8
    assert frame.duplicated(
        ["country", "crop_year", "snapshot_stage", "as_of_date"]
    ).sum() == 0


def test_snapshot_predictions_join_baselines_on_snapshot_identity() -> None:
    from sklearn.dummy import DummyRegressor

    matrix = _snapshot_matrix()
    frame = training_frame_from_model_ready_matrix(matrix, ["feature_a"])
    result = walk_forward_cv(
        frame,
        "target_value",
        ["feature_a"],
        DummyRegressor(strategy="mean"),
        min_train_years=2,
    )
    enriched = attach_model_ready_baselines_to_predictions(result.predictions, matrix)

    assert {"snapshot_stage", "as_of_date"}.issubset(result.predictions.columns)
    assert len(enriched) == len(result.predictions)
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
    assert "--cv-policy" in command
    assert "--register-model" in command
    assert params["model_dataset_version"] == "none"
    assert params["dataset_key"] == "annual_physical_anomaly"
    assert params["cv_policy"] == "expanding_full_history"
    assert params["register_model"] == "false"
