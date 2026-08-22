from __future__ import annotations

import math

import pytest

from leviathan.eda.models import (
    Exactness,
    Metric,
    SourceBoundaryError,
    TableSpec,
    deterministic_json,
)
from leviathan.silver.registry import load_registry


def _contract(**overrides):
    contract = {
        "table_name": "silver_test_source",
        "layer": "silver",
        "domain": "weather",
        "lifecycle_class": "source",
        "s3_root": "s3://leviathan-dev-shahem-001/silver/test_source",
        "physical_columns": [
            {"name": "date", "target_arrow_type": "date32[day]", "nullable": False},
            {"name": "value", "target_arrow_type": "float64", "nullable": True},
        ],
        "partition_keys": [{"name": "commodity", "glue_type": "string"}],
        "natural_key": ["commodity", "date"],
        "required_nonnull": ["commodity", "date"],
        "value_columns": ["value"],
        "min_nonnull_frac": 0.5,
        "knowledge_date_col": None,
        "knowledge_semantics": None,
        "freshness_sla": {"cadence": "daily"},
    }
    contract.update(overrides)
    return contract


def test_table_spec_accepts_every_registry_silver_and_rejects_gold():
    registry = load_registry()
    silvers = [contract for contract in registry.tables.values() if contract["layer"] == "silver"]

    specs = [TableSpec.from_contract(contract) for contract in silvers]

    assert len(specs) == 42
    assert all(spec.table_name.startswith("silver_") for spec in specs)
    assert TableSpec.from_contract(registry.table("silver_model_predictions")).is_output_plane
    with pytest.raises(SourceBoundaryError):
        TableSpec.from_contract(registry.table("gold_weather_z"))


@pytest.mark.parametrize(
    "overrides",
    [
        {"layer": "gold", "table_name": "gold_test"},
        {"s3_root": "s3://leviathan-dev-shahem-001/gold/legacy"},
        {"s3_root": "s3://leviathan-dev-shahem-001/model-ready/train"},
    ],
)
def test_table_spec_hard_rejects_non_silver_sources(overrides):
    with pytest.raises(SourceBoundaryError):
        TableSpec.from_contract(_contract(**overrides))


def test_table_spec_routes_and_hash_are_deterministic():
    first = TableSpec.from_contract(_contract())
    second = TableSpec.from_contract(_contract())

    assert first.contract_hash == second.contract_hash
    assert first.declared_columns == ("date", "value", "commodity")
    assert "time_series" in first.analyzer_routes
    assert first.to_dict() == second.to_dict()


def test_metric_and_json_serialization_are_exactness_labelled_and_stable():
    metric = Metric("distribution", {"finite": 2.0, "nan": math.nan}, Exactness.SAMPLED)

    assert metric.to_dict() == {
        "exactness": "sampled",
        "name": "distribution",
        "value": {"finite": 2.0, "nan": None},
    }
    assert deterministic_json(metric) == deterministic_json(metric)

