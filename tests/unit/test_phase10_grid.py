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
        include_hypotheses=["psd_vintage_signal"],
        bucket="bucket",
        aws_region="us-east-1",
        permutation_trials=3,
    )

    assert tasks
    assert {task["hypothesis_id"] for task in tasks} == {"psd_vintage_signal"}
    assert {task["dataset_key"] for task in tasks} == {"psd_snd_anomaly_snapshot"}
    assert {task["feature_set"] for task in tasks} == {
        "psd_monthly_vintage_features",
        "preseason_physical_plus_psd_vintage",
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
