from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from leviathan.model_datasets.psd_model_ready import (
    PSD_DATASET_KEY,
    PSD_MATRIX_ID_COLUMNS,
    build_psd_commodity_model_datasets,
)
from leviathan.model_datasets.psd_target_builder import build_psd_target_panel
from leviathan.storage.paths import (
    gold_feature_matrix_version_key,
    gold_feature_set_version_key,
    gold_model_ready_baseline_metrics_key,
    gold_model_ready_manifest_key,
    gold_model_ready_matrix_key,
    gold_model_ready_target_key,
)
from leviathan.training.model_ready import select_model_ready_features


def _feature_matrix(years: list[int] | None = None) -> pd.DataFrame:
    years = years or list(range(2000, 2006))
    return pd.DataFrame({
        "country": ["united_states"] * len(years),
        "crop_year": years,
        "feature_a": [float(i) for i in range(len(years))],
        "feature_b": [float(i + 10) for i in range(len(years))],
        "label_production_quantity": [100.0 + i for i in range(len(years))],
    })


def _membership() -> pd.DataFrame:
    return pd.DataFrame({
        "feature_set_id": [
            "preseason_physical",
            "preseason_physical",
            "preseason_physical",
        ],
        "feature": ["feature_a", "feature_b", "label_production_quantity"],
        "is_label": [False, False, True],
        "feature_set_version": ["1", "1", "1"],
        "feature_set_sha": ["sha", "sha", "sha"],
        "dataset_version": ["gold_v", "gold_v", "gold_v"],
    })


def _psd_source(values: list[float] | None = None) -> pd.DataFrame:
    values = values or [10.0, 11.0, 12.0, 13.0, 14.0, 18.0]
    rows = []
    for idx, value in enumerate(values):
        year = 2000 + idx
        rows.append({
            "leviathan_slug": "corn_cbot",
            "country": "United States",
            "market_year": year,
            "release_date": f"{year + 1}-02-01",
            "production_mt": value,
            "ending_stocks_mt": value + 20.0,
            "su_ratio": value / 100.0,
            "exports_mt": value + 30.0,
            "imports_mt": value + 40.0,
            "consumption_mt": value + 50.0,
        })
    return pd.DataFrame(rows)


def _psd_targets() -> pd.DataFrame:
    return build_psd_target_panel(
        _psd_source(),
        source_dataset_version="gold_v",
        commodities=["corn_cbot"],
    )


def test_psd_model_ready_builds_matrices_and_baselines() -> None:
    built = build_psd_commodity_model_datasets(
        _feature_matrix(),
        _psd_targets(),
        commodity="corn_cbot",
        feature_membership=_membership(),
        target_keys=("psd_production_anomaly_pct",),
    )

    assert set(built.target_tables) == {PSD_DATASET_KEY}
    assert set(built.matrices) == {(PSD_DATASET_KEY, "psd_production_anomaly_pct")}
    matrix = built.matrices[(PSD_DATASET_KEY, "psd_production_anomaly_pct")]

    assert set(PSD_MATRIX_ID_COLUMNS).issubset(matrix.columns)
    assert "feature_a" in matrix.columns
    assert "feature_b" in matrix.columns
    assert "label_production_quantity" not in matrix.columns
    assert matrix.loc[matrix["crop_year"] == 2005, "is_trainable"].iloc[0]
    assert set(built.baseline_metrics["baseline_name"]) == {
        "zero_anomaly",
        "prior_year",
        "trailing_mean",
        "trailing_linear_trend",
    }
    assert built.summaries[0]["target_source"] == "psd"
    assert built.summaries[0]["target_attribute"] == "production_mt"


def test_psd_model_ready_marks_missing_feature_rows() -> None:
    built = build_psd_commodity_model_datasets(
        _feature_matrix(years=list(range(2000, 2005))),
        _psd_targets(),
        commodity="corn_cbot",
        feature_membership=_membership(),
        target_keys=("psd_production_anomaly_pct",),
    )
    matrix = built.matrices[(PSD_DATASET_KEY, "psd_production_anomaly_pct")]
    row = matrix.loc[matrix["crop_year"] == 2005].iloc[0]

    assert not row["is_trainable"]
    assert row["excluded_reason"] == "missing_features"


def test_psd_model_ready_rejects_duplicate_feature_keys() -> None:
    duplicated = pd.concat([_feature_matrix(), _feature_matrix().iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate feature matrix keys"):
        build_psd_commodity_model_datasets(
            duplicated,
            _psd_targets(),
            commodity="corn_cbot",
            feature_membership=_membership(),
            target_keys=("psd_production_anomaly_pct",),
        )


def test_psd_model_ready_rejects_duplicate_target_keys() -> None:
    targets = _psd_targets()
    duplicate = targets.loc[
        targets["target_key"] == "psd_production_anomaly_pct"
    ].iloc[[0]]
    bad_targets = pd.concat([targets, duplicate], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate PSD target keys"):
        build_psd_commodity_model_datasets(
            _feature_matrix(),
            bad_targets,
            commodity="corn_cbot",
            feature_membership=_membership(),
            target_keys=("psd_production_anomaly_pct",),
        )


def test_training_feature_selection_excludes_psd_metadata() -> None:
    built = build_psd_commodity_model_datasets(
        _feature_matrix(),
        _psd_targets(),
        commodity="corn_cbot",
        feature_membership=_membership(),
        target_keys=("psd_production_anomaly_pct",),
    )
    matrix = built.matrices[(PSD_DATASET_KEY, "psd_production_anomaly_pct")]

    feature_cols, _ = select_model_ready_features(matrix, _membership(), "preseason_physical")

    assert feature_cols == ["feature_a", "feature_b"]


def test_model_ready_cli_writes_local_psd_version(tmp_path: Path) -> None:
    source_version = "gold_v"
    model_version = "model_psd_v"
    matrix_key = gold_feature_matrix_version_key(source_version, "corn_cbot")
    membership_key = gold_feature_set_version_key(source_version)
    psd_key = "silver/psd/part-000.parquet"
    (tmp_path / matrix_key).parent.mkdir(parents=True)
    _feature_matrix().to_parquet(tmp_path / matrix_key, index=False)
    (tmp_path / membership_key).parent.mkdir(parents=True)
    _membership().to_parquet(tmp_path / membership_key, index=False)
    (tmp_path / psd_key).parent.mkdir(parents=True)
    _psd_source().to_parquet(tmp_path / psd_key, index=False)

    subprocess.run(
        [
            sys.executable,
            "jobs/batch/build_model_ready_datasets.py",
            "--local-root",
            str(tmp_path),
            "--target-source",
            "psd",
            "--source-dataset-version",
            source_version,
            "--model-dataset-version",
            model_version,
            "--commodities",
            "corn_cbot",
            "--target-keys",
            "psd_production_anomaly_pct",
            "--workers",
            "2",
        ],
        check=True,
    )

    assert (tmp_path / gold_model_ready_target_key(
        model_version, PSD_DATASET_KEY, "corn_cbot"
    )).exists()
    assert (tmp_path / gold_model_ready_matrix_key(
        model_version, PSD_DATASET_KEY, "corn_cbot", "psd_production_anomaly_pct"
    )).exists()
    assert (tmp_path / gold_model_ready_baseline_metrics_key(model_version)).exists()

    manifest = json.loads((tmp_path / gold_model_ready_manifest_key(model_version)).read_text())
    assert manifest["target_source"] == "psd"
    assert manifest["psd_mapping_sha"]
    assert manifest["summary"]["built_target_count"] == 1
    assert manifest["summary"]["matrix_count"] == 1
