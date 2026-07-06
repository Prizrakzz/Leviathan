from __future__ import annotations

from jobs.batch import feature_catalog_task
from leviathan.features import spine
from leviathan.model_datasets import (
    baselines,
    builder,
    psd_model_ready,
    psd_target_builder,
    schema_columns,
    wasde_snapshot_targets,
)


def test_annual_model_dataset_columns_are_shared() -> None:
    assert baselines.TARGET_COLUMNS is schema_columns.TARGET_COLUMNS
    assert baselines.BASELINE_COLUMNS is schema_columns.BASELINE_COLUMNS
    assert builder.MATRIX_ID_COLUMNS is schema_columns.MATRIX_ID_COLUMNS


def test_psd_model_dataset_columns_are_shared() -> None:
    assert psd_target_builder.PSD_TARGET_COLUMNS is schema_columns.PSD_TARGET_COLUMNS
    assert psd_model_ready.PSD_TARGET_COLUMNS is schema_columns.PSD_TARGET_COLUMNS
    assert psd_model_ready.PSD_MATRIX_ID_COLUMNS is schema_columns.PSD_MATRIX_ID_COLUMNS
    assert psd_model_ready.PSD_SNAPSHOT_COLUMNS is schema_columns.PSD_SNAPSHOT_COLUMNS
    assert (
        psd_model_ready.PSD_SNAPSHOT_MATRIX_ID_COLUMNS
        is schema_columns.PSD_SNAPSHOT_MATRIX_ID_COLUMNS
    )
    assert psd_model_ready.PSD_SNAPSHOT_TARGET_COLUMNS is schema_columns.PSD_SNAPSHOT_TARGET_COLUMNS


def test_wasde_snapshot_target_columns_are_shared() -> None:
    assert (
        wasde_snapshot_targets.WASDE_SNAPSHOT_TARGET_COLUMNS
        is schema_columns.WASDE_SNAPSHOT_TARGET_COLUMNS
    )
    assert wasde_snapshot_targets.NATURAL_KEY is schema_columns.WASDE_SNAPSHOT_NATURAL_KEY
    assert wasde_snapshot_targets.GROUP_KEY is schema_columns.WASDE_SNAPSHOT_GROUP_KEY


def test_feature_catalog_uses_spine_column_contract() -> None:
    assert feature_catalog_task.SPINE_COLUMNS is spine.SPINE_COLUMNS
