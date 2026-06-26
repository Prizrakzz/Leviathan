from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from leviathan.model_datasets.baselines import build_trailing_anomaly_targets
from leviathan.model_datasets.builder import build_commodity_model_datasets
from leviathan.model_datasets.targets import TargetDefinition, load_target_definitions
from leviathan.storage.paths import (
    gold_feature_matrix_version_key,
    gold_feature_set_version_key,
    gold_model_ready_baseline_metrics_key,
    gold_model_ready_manifest_key,
    gold_model_ready_matrix_key,
    gold_model_ready_target_key,
)


def _target(label_column: str = "label_production_quantity") -> TargetDefinition:
    return TargetDefinition(
        target_key="production_anomaly_pct",
        dataset_key="annual_physical_anomaly",
        title="Production anomaly",
        label_column=label_column,
        actual_column="production_quantity",
        target_unit="pct_deviation",
        target_type="trailing_trend_pct_anomaly",
        horizon="final_crop_year",
        grain=("commodity", "country", "crop_year"),
        as_of_rule="test",
        min_history_years=3,
        baselines=("zero_anomaly", "prior_year", "trailing_mean", "trailing_linear_trend"),
        compatible_feature_sets=("preseason_physical",),
        target_compatibility=("production_anomaly",),
        allowed_commodities=(),
    )


def _matrix() -> pd.DataFrame:
    years = list(range(2000, 2008))
    values = [10.0, 11.0, 12.0, 20.0, 14.0, 15.0, 16.0, 17.0]
    return pd.DataFrame({
        "country": ["united_states"] * len(years),
        "crop_year": years,
        "feature_a": range(len(years)),
        "feature_b": range(10, 10 + len(years)),
        "label_production_quantity": values,
        "label_yield": [v / 2 for v in values],
        "label_area_harvested": [v * 2 for v in values],
    })


def _membership() -> pd.DataFrame:
    return pd.DataFrame({
        "feature_set_id": ["preseason_physical", "preseason_physical"],
        "feature": ["feature_a", "label_production_quantity"],
        "is_label": [False, True],
    })


def test_target_config_loads_defaults() -> None:
    definitions, config_sha, raw = load_target_definitions()
    assert config_sha
    assert raw["defaults"]["source_dataset_version"]
    assert {d.target_key for d in definitions} >= {
        "production_anomaly_pct",
        "yield_anomaly_pct",
        "area_harvested_anomaly_pct",
    }


def test_trailing_anomaly_uses_only_prior_years() -> None:
    out = build_trailing_anomaly_targets(
        _matrix(),
        _target(),
        commodity="corn_cbot",
        source_dataset_version="gold_v",
    )
    row = out.loc[out["crop_year"] == 2003].iloc[0]

    assert row["history_years"] == 3
    assert row["is_trainable"]
    # Trend from 2000-2002 is 10,11,12 => prediction for 2003 is 13.
    # The current-year spike to 20 must not influence that prediction.
    assert round(float(row["trend_prediction"]), 6) == 13.0
    assert round(float(row["target_value"]), 6) == round((20.0 - 13.0) / 13.0, 6)


def test_builder_excludes_labels_and_materializes_baselines() -> None:
    built = build_commodity_model_datasets(
        _matrix(),
        commodity="corn_cbot",
        source_dataset_version="gold_v",
        target_definitions=[_target()],
        feature_membership=_membership(),
    )

    target_df = built.target_tables["annual_physical_anomaly"]
    matrix_df = built.matrices[("annual_physical_anomaly", "production_anomaly_pct")]

    assert target_df["is_trainable"].sum() > 0
    assert "feature_a" in matrix_df.columns
    assert "label_production_quantity" not in matrix_df.columns
    assert "zero_anomaly_baseline" in matrix_df.columns
    assert set(built.baseline_metrics["baseline_name"]) == {
        "zero_anomaly",
        "prior_year",
        "trailing_mean",
        "trailing_linear_trend",
    }


def test_model_ready_cli_writes_local_version(tmp_path: Path) -> None:
    source_version = "gold_v"
    model_version = "model_v"
    matrix_key = gold_feature_matrix_version_key(source_version, "corn_cbot")
    membership_key = gold_feature_set_version_key(source_version)
    (tmp_path / matrix_key).parent.mkdir(parents=True)
    _matrix().to_parquet(tmp_path / matrix_key, index=False)
    (tmp_path / membership_key).parent.mkdir(parents=True)
    _membership().to_parquet(tmp_path / membership_key, index=False)

    subprocess.run(
        [
            sys.executable,
            "jobs/batch/build_model_ready_datasets.py",
            "--local-root",
            str(tmp_path),
            "--source-dataset-version",
            source_version,
            "--model-dataset-version",
            model_version,
            "--commodities",
            "corn_cbot",
            "--workers",
            "2",
        ],
        check=True,
    )

    assert (tmp_path / gold_model_ready_target_key(
        model_version, "annual_physical_anomaly", "corn_cbot"
    )).exists()
    assert (tmp_path / gold_model_ready_matrix_key(
        model_version, "annual_physical_anomaly", "corn_cbot", "production_anomaly_pct"
    )).exists()
    assert (tmp_path / gold_model_ready_baseline_metrics_key(model_version)).exists()

    manifest_path = tmp_path / gold_model_ready_manifest_key(model_version)
    manifest = json.loads(manifest_path.read_text())
    assert manifest["summary"]["processed_commodity_count"] == 1
    assert manifest["summary"]["built_target_count"] == 3
