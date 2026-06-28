from __future__ import annotations

from leviathan.training.phase10_grid import (
    expand_phase10_grid,
    load_phase10_grid_config,
    phase10_grid_summary,
)


def test_phase10_grid_config_expands_controlled_candidates() -> None:
    config = load_phase10_grid_config()

    tasks = expand_phase10_grid(
        config,
        include_hypotheses=["wasde_revision_signal"],
        bucket="bucket",
        aws_region="us-east-1",
        permutation_trials=3,
    )

    assert tasks
    assert {task["hypothesis_id"] for task in tasks} == {"wasde_revision_signal"}
    assert {task["dataset_key"] for task in tasks} == {"psd_snd_anomaly_snapshot"}
    assert {task["feature_set"] for task in tasks} == {
        "wasde_monthly_revision",
        "preseason_physical_plus_wasde_revision",
    }
    assert {task["permutation_trials"] for task in tasks} == {"3"}
    assert all(task["bucket"] == "bucket" for task in tasks)
    assert all(task["model_params_json"].startswith("{") for task in tasks)


def test_phase10_grid_skips_model_incompatible_profiles() -> None:
    config = {
        "schema_version": 1,
        "defaults": {
            "commodities": ["corn_cbot"],
            "feature_sets": ["preseason_physical"],
            "dataset_keys": ["psd_snd_anomaly"],
            "target_keys": ["psd_production_anomaly_pct"],
            "models": ["xgboost"],
            "cv_policies": ["expanding_post_2000"],
            "stress_years": [2012],
        },
        "model_param_profiles": [
            {"id": "lightgbm_only", "models": ["lightgbm"], "params": {"max_depth": 2}},
            {"id": "xgb_only", "models": ["xgboost"], "params": {"max_depth": 3}},
        ],
        "hypotheses": [
            {
                "id": "h1",
                "model_param_profiles": ["lightgbm_only", "xgb_only"],
            }
        ],
    }

    tasks = expand_phase10_grid(config, bucket="bucket", aws_region="us-east-1")

    assert len(tasks) == 1
    assert tasks[0]["model_param_profile"] == "xgb_only"
    assert '"max_depth":3' in tasks[0]["model_params_json"]


def test_phase10_grid_summary_lists_key_axes() -> None:
    config = load_phase10_grid_config()
    tasks = expand_phase10_grid(
        config,
        include_hypotheses=["baseline_hardening_reference"],
        bucket="bucket",
        aws_region="us-east-1",
    )

    summary = phase10_grid_summary(tasks)

    assert summary["task_count"] == 1
    assert summary["hypotheses"] == ["baseline_hardening_reference"]
    assert summary["models"] == ["lightgbm"]


def test_phase10_grid_expands_corn_composite_feature_stacks() -> None:
    config = load_phase10_grid_config()
    tasks = expand_phase10_grid(
        config,
        include_hypotheses=["corn_composite_feature_stacks"],
        bucket="bucket",
        aws_region="us-east-1",
        permutation_trials=5,
    )

    assert len(tasks) == 15
    assert {task["dataset_key"] for task in tasks} == {"psd_snd_anomaly"}
    assert {task["commodity"] for task in tasks} == {"corn_cbot"}
    assert {task["feature_set"] for task in tasks} == {
        "corn_preseason_core",
        "corn_preseason_core_plus_weather_dense",
        "corn_preseason_core_plus_flow",
        "corn_weather_flow",
        "corn_full_fundamental_stack",
    }
    assert {task["permutation_trials"] for task in tasks} == {"5"}


def test_phase10_grid_expands_corn_snapshot_wasde_stacks() -> None:
    config = load_phase10_grid_config()
    tasks = expand_phase10_grid(
        config,
        include_hypotheses=["corn_wasde_snapshot_feature_stacks"],
        bucket="bucket",
        aws_region="us-east-1",
    )

    assert len(tasks) == 9
    assert {task["dataset_key"] for task in tasks} == {"psd_snd_anomaly_snapshot"}
    assert {task["feature_set"] for task in tasks} == {
        "corn_preseason_core",
        "corn_preseason_core_plus_wasde",
        "preseason_physical_plus_wasde_revision",
    }
