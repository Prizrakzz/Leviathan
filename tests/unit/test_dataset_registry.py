"""Tests for the authoritative dataset registry."""
from __future__ import annotations

from pathlib import Path

import pytest

from leviathan.catalog.registry import DatasetRegistryError, load_dataset_registry


def test_repository_registry_loads_and_is_complete() -> None:
    registry = load_dataset_registry()
    assert len(registry.datasets) == 49
    assert registry.bucket == "leviathan-dev-shahem-001"
    assert len(registry.by_id()) == len(registry.datasets)
    assert len(registry.by_table()) == len(registry.datasets)


def test_registry_contains_corrected_phase1_tables() -> None:
    registry = load_dataset_registry()
    ids = registry.by_id()
    assert "silver_fnc_colombia_monthly" in ids
    assert "silver_fnc_colombia_area_department" in ids
    assert "silver_fnc_colombia_exports_port_type" in ids
    assert "silver_nasa_power" in ids
    assert "silver_chirps" in ids
    assert "silver_cpc_soil" in ids
    assert "silver_unica_biweekly_release_series" in ids
    assert {"production_raw", "silver_fnc_colombia", "silver_weather"} == set(
        registry.retired_tables
    )


def test_registry_expresses_model_eligibility() -> None:
    datasets = load_dataset_registry().by_id()
    assert datasets["silver_conab_coffee"].status == "active"
    assert datasets["silver_conab_coffee"].core_fundamental
    assert datasets["silver_ams_cotton_quality"].status == "active"
    assert datasets["silver_wasde"].core_fundamental
    assert datasets["silver_futures_prices"].status == "diagnostic_only"
    assert datasets["silver_production"].role == "label_source"
    assert datasets["gold_feature_spine"].core_fundamental
    assert datasets["silver_production"].s3_prefix.endswith("commodity=")
    assert datasets["graphrag_entities"].status == "empty_pending_backfill"
    assert datasets["graphrag_causal_edges"].status == "empty_pending_backfill"
    assert datasets["graphrag_forecasts"].status == "empty_pending_backfill"


def test_registry_rejects_duplicate_ids(tmp_path: Path) -> None:
    path = tmp_path / "datasets.yaml"
    path.write_text(
        """
schema_version: 1
bucket: bucket
database: db
datasets:
  - &base
    dataset_id: duplicate
    layer: silver
    role: feature_source
    status: active
    s3_prefix: silver/a/
    format: PARQUET
    schema: [{name: id, type: string}]
    natural_key: [id]
    partitions: []
    core_fundamental: true
    athena: {table: table_a}
  - <<: *base
    s3_prefix: silver/b/
    athena: {table: table_b}
""",
        encoding="utf-8",
    )
    with pytest.raises(DatasetRegistryError, match="duplicate dataset_id"):
        load_dataset_registry(path)


def test_natural_key_must_be_in_schema(tmp_path: Path) -> None:
    path = tmp_path / "datasets.yaml"
    path.write_text(
        """
schema_version: 1
bucket: bucket
database: db
datasets:
  - dataset_id: broken
    layer: silver
    role: feature_source
    status: active
    s3_prefix: silver/a/
    format: PARQUET
    schema: [{name: id, type: string}]
    natural_key: [missing]
    partitions: []
    core_fundamental: true
    athena: {table: broken}
""",
        encoding="utf-8",
    )
    with pytest.raises(DatasetRegistryError, match="natural_key columns"):
        load_dataset_registry(path)


def test_projection_rejects_accidental_yaml_mapping_keys(tmp_path: Path) -> None:
    path = tmp_path / "datasets.yaml"
    path.write_text(
        """
schema_version: 1
bucket: bucket
database: db
datasets:
  - dataset_id: broken
    layer: silver
    role: feature_source
    status: active
    s3_prefix: silver/a/
    format: PARQUET
    schema: [{name: family, type: string}]
    natural_key: [family]
    partitions:
      - name: family
        type: string
        projection: {type: enum, values: first,second}
    core_fundamental: true
    athena: {table: broken}
""",
        encoding="utf-8",
    )
    with pytest.raises(DatasetRegistryError, match="unsupported projection keys"):
        load_dataset_registry(path)
