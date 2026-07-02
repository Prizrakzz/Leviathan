from __future__ import annotations

from leviathan.training.snapshot_candidate_grid import (
    expand_snapshot_candidate_grid,
    load_snapshot_candidate_grid_config,
    snapshot_candidate_grid_summary,
)


def test_snapshot_candidate_grid_config_expands_smoke_candidates() -> None:
    config = load_snapshot_candidate_grid_config()

    tasks = expand_snapshot_candidate_grid(
        config,
        include_hypotheses=["corn_snapshot_grouped_cv_smoke"],
        bucket="bucket",
        aws_region="us-east-1",
    )

    assert len(tasks) == 4
    assert {task["hypothesis_id"] for task in tasks} == {"corn_snapshot_grouped_cv_smoke"}
    assert {task["dataset_key"] for task in tasks} == {"psd_snd_anomaly_snapshot"}
    assert {task["commodity"] for task in tasks} == {"corn_cbot"}
    assert {task["target_key"] for task in tasks} == {
        "psd_stock_to_use_anomaly_pct",
        "psd_ending_stocks_anomaly_pct",
    }
    assert {task["feature_set"] for task in tasks} == {
        "preseason_physical_plus_wasde_revision",
    }
    assert {task["feature_stack"] for task in tasks} == {
        "preseason_static_plus_wasde_revision",
    }
    assert "psd_production_anomaly_pct" not in {task["target_key"] for task in tasks}
    assert "wasde_monthly_revision" not in {task["feature_set"] for task in tasks}
    assert {task["bucket"] for task in tasks} == {"bucket"}
    assert all(task["model_params_json"].startswith("{") for task in tasks)


def test_snapshot_candidate_grid_skips_incompatible_profiles() -> None:
    config = {
        "schema_version": 1,
        "defaults": {
            "commodities": ["corn_cbot"],
            "feature_sets": ["wasde_monthly_revision"],
            "dataset_keys": ["psd_snd_anomaly_snapshot"],
            "target_keys": ["psd_production_anomaly_pct"],
            "models": ["xgboost"],
        },
        "model_param_profiles": [
            {"id": "lightgbm_only", "models": ["lightgbm"], "params": {"max_depth": 2}},
            {"id": "xgb_only", "models": ["xgboost"], "params": {"max_depth": 3}},
        ],
        "hypotheses": [
            {"id": "h1", "model_param_profiles": ["lightgbm_only", "xgb_only"]},
        ],
    }

    tasks = expand_snapshot_candidate_grid(config, bucket="bucket", aws_region="us-east-1")

    assert len(tasks) == 1
    assert tasks[0]["model_param_profile"] == "xgb_only"
    assert '"max_depth":3' in tasks[0]["model_params_json"]


def test_snapshot_candidate_grid_summary_lists_axes() -> None:
    config = load_snapshot_candidate_grid_config()
    tasks = expand_snapshot_candidate_grid(
        config,
        include_hypotheses=["corn_snapshot_grouped_cv_smoke"],
        bucket="bucket",
        aws_region="us-east-1",
    )

    summary = snapshot_candidate_grid_summary(tasks)

    assert summary["task_count"] == 4
    assert summary["hypotheses"] == ["corn_snapshot_grouped_cv_smoke"]
    assert summary["dataset_keys"] == ["psd_snd_anomaly_snapshot"]
    assert summary["collapse_policies"] == ["latest"]
