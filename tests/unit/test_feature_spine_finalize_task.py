from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from jobs.batch.feature_spine_finalize_task import FinalizeOptions, finalize_dataset
from leviathan.storage.paths import (
    gold_feature_catalog_version_key,
    gold_feature_matrix_version_key,
    gold_feature_spine_commodity_manifest_key,
    gold_feature_spine_manifest_key,
    gold_feature_spine_version_key,
    gold_training_windows_version_key,
)


def _write_parquet(root: Path, key: str, df: pd.DataFrame) -> None:
    path = root / key
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False, engine="pyarrow", compression="snappy")


def _write_json(root: Path, key: str, payload: dict) -> None:
    path = root / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_commodity(
    root: Path,
    *,
    dataset_version: str,
    commodity: str,
    features: dict[str, float],
    passed: bool = True,
) -> None:
    spine_key = gold_feature_spine_version_key(dataset_version, commodity)
    matrix_key = gold_feature_matrix_version_key(dataset_version, commodity)
    manifest_key = gold_feature_spine_commodity_manifest_key(dataset_version, commodity)

    spine = pd.DataFrame(
        [
            {
                "country": "united_states",
                "crop_year": 2024,
                "feature": feature,
                "value": value,
                "is_label": feature.startswith("label_"),
                "event_time": "2024-12-31",
            }
            for feature, value in features.items()
        ]
    )
    matrix = pd.DataFrame(
        [{
            "country": "united_states",
            "crop_year": 2024,
            **features,
        }]
    )

    _write_parquet(root, spine_key, spine)
    _write_parquet(root, matrix_key, matrix)
    _write_json(
        root,
        manifest_key,
        {
            "task": "feature_spine_task",
            "commodity": commodity,
            "dataset_version": dataset_version,
            "built_at": "2026-06-25T12:00:00+00:00",
            "git_sha": "abc123",
            "crop_years": [2024, 2024],
            "spine_version_key": spine_key,
            "matrix_version_key": matrix_key,
            "versioned_only": True,
            "inputs": [{"source": "psd", "num_files": 1, "num_rows": 10}],
            "report": {
                "passed": passed,
                "row_count": len(spine),
                "feature_count": len(features),
                "label_row_count": int(spine["is_label"].sum()),
                "hard_failures": [] if passed else ["boom"],
                "soft_warnings": [],
            },
        },
    )


def _write_training_windows(root: Path, dataset_version: str) -> None:
    parquet_key = gold_training_windows_version_key(dataset_version)
    markdown_key = gold_training_windows_version_key(dataset_version, "training_windows.md")
    _write_parquet(
        root,
        parquet_key,
        pd.DataFrame([
            {
                "commodity": "corn_cbot",
                "tier": "core",
                "n_features": 10,
                "label_first_year": 2020,
                "label_last_year": 2024,
                "n_label_years": 5,
                "dense_start_year": 2021,
                "dense_window_years": 4,
                "present_families": "psd",
            },
            {
                "commodity": "soybeans_cbot",
                "tier": "core",
                "n_features": 8,
                "label_first_year": 2020,
                "label_last_year": 2024,
                "n_label_years": 5,
                "dense_start_year": 2022,
                "dense_window_years": 3,
                "present_families": "psd",
            },
        ]),
    )
    path = root / markdown_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Training windows\n", encoding="utf-8")


def test_finalize_writes_catalog_and_dataset_manifest(tmp_path: Path) -> None:
    version = "v1"
    _write_commodity(
        tmp_path,
        dataset_version=version,
        commodity="corn_cbot",
        features={"common_z": 1.0, "corn_only": 2.0, "label_production": 3.0},
    )
    _write_commodity(
        tmp_path,
        dataset_version=version,
        commodity="soybeans_cbot",
        features={"common_z": 4.0, "soy_only": 5.0, "label_production": 6.0},
    )

    manifest = finalize_dataset(
        FinalizeOptions(
            dataset_version=version,
            commodities=["corn_cbot", "soybeans_cbot"],
            local_root=tmp_path,
        )
    )

    catalog_key = gold_feature_catalog_version_key(version)
    manifest_key = gold_feature_spine_manifest_key(version)
    assert (tmp_path / catalog_key).exists()
    assert (tmp_path / manifest_key).exists()

    catalog = pd.read_parquet(tmp_path / catalog_key)
    scopes = dict(zip(catalog["feature"], catalog["scope"], strict=True))
    assert scopes["common_z"] == "universal"
    assert scopes["label_production"] == "universal"
    assert scopes["corn_only"] == "commodity"
    assert scopes["soy_only"] == "commodity"
    assert bool(catalog.loc[catalog["feature"] == "label_production", "is_label"].iloc[0])

    assert manifest["dataset_version"] == version
    assert manifest["summary"]["commodity_count"] == 2
    assert manifest["summary"]["total_spine_rows"] == 6
    assert manifest["summary"]["total_matrix_rows"] == 2
    assert manifest["summary"]["feature_count"] == 4
    assert manifest["summary"]["hard_failure_count"] == 0
    assert manifest["summary"]["training_windows_available"] is False
    assert manifest["source_summary"]["psd"]["seen_in_commodities"] == 2


def test_finalize_fails_when_expected_commodity_is_missing(tmp_path: Path) -> None:
    version = "v1"
    _write_commodity(
        tmp_path,
        dataset_version=version,
        commodity="corn_cbot",
        features={"common_z": 1.0},
    )

    with pytest.raises(FileNotFoundError, match="soybeans_cbot"):
        finalize_dataset(
            FinalizeOptions(
                dataset_version=version,
                commodities=["corn_cbot", "soybeans_cbot"],
                local_root=tmp_path,
            )
        )

    assert not (tmp_path / gold_feature_catalog_version_key(version)).exists()


def test_finalize_fails_when_commodity_report_failed(tmp_path: Path) -> None:
    version = "v1"
    _write_commodity(
        tmp_path,
        dataset_version=version,
        commodity="corn_cbot",
        features={"common_z": 1.0},
        passed=False,
    )

    with pytest.raises(ValueError, match="did not pass"):
        finalize_dataset(
            FinalizeOptions(
                dataset_version=version,
                commodities=["corn_cbot"],
                local_root=tmp_path,
            )
        )


def test_finalize_refuses_to_overwrite_by_default(tmp_path: Path) -> None:
    version = "v1"
    _write_commodity(
        tmp_path,
        dataset_version=version,
        commodity="corn_cbot",
        features={"common_z": 1.0},
    )
    options = FinalizeOptions(
        dataset_version=version,
        commodities=["corn_cbot"],
        local_root=tmp_path,
    )
    finalize_dataset(options)

    with pytest.raises(FileExistsError, match="feature_catalog"):
        finalize_dataset(options)


def test_finalize_can_overwrite_when_enabled(tmp_path: Path) -> None:
    version = "v1"
    _write_commodity(
        tmp_path,
        dataset_version=version,
        commodity="corn_cbot",
        features={"common_z": 1.0},
    )
    finalize_dataset(
        FinalizeOptions(
            dataset_version=version,
            commodities=["corn_cbot"],
            local_root=tmp_path,
        )
    )

    manifest = finalize_dataset(
        FinalizeOptions(
            dataset_version=version,
            commodities=["corn_cbot"],
            local_root=tmp_path,
            fail_if_exists=False,
        )
    )

    assert manifest["summary"]["commodity_count"] == 1


def test_finalize_includes_training_windows_when_present(tmp_path: Path) -> None:
    version = "v1"
    _write_commodity(
        tmp_path,
        dataset_version=version,
        commodity="corn_cbot",
        features={"common_z": 1.0},
    )
    _write_commodity(
        tmp_path,
        dataset_version=version,
        commodity="soybeans_cbot",
        features={"common_z": 2.0},
    )
    _write_training_windows(tmp_path, version)

    manifest = finalize_dataset(
        FinalizeOptions(
            dataset_version=version,
            commodities=["corn_cbot", "soybeans_cbot"],
            local_root=tmp_path,
        )
    )

    assert manifest["summary"]["training_windows_available"] is True
    assert manifest["summary"]["training_windows_row_count"] == 2
    assert manifest["summary"]["training_windows_commodity_count"] == 2
    assert manifest["training_windows"]["tier_count"] == 1
    assert manifest["outputs"]["training_windows_key"] == gold_training_windows_version_key(
        version
    )
