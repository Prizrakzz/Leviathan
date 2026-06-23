"""Tests for deterministic system inventory normalization."""
from __future__ import annotations

from leviathan.audit.system_inventory import (
    inventory_content_sha256,
    json_document,
    normalize_inventory,
    parquet_rows,
)


def _content() -> dict:
    return {
        "s3_datasets": [
            {"layer": "silver", "prefix": "silver/z/", "schemas": [{"b": 2}]},
            {"layer": "gold", "prefix": "gold/a/", "schemas": [{"a": 1}]},
        ],
        "glue_tables": [
            {"database": "db", "name": "z"},
            {"database": "db", "name": "a"},
        ],
        "batch_job_definitions": [
            {"name": "train", "revision": 2},
            {"name": "train", "revision": 1},
        ],
    }


def test_inventory_hash_is_stable_under_record_reordering() -> None:
    content = _content()
    reversed_content = {
        key: list(reversed(value)) for key, value in content.items()
    }
    assert inventory_content_sha256(content) == inventory_content_sha256(reversed_content)


def test_normalize_inventory_sorts_known_sections() -> None:
    normalized = normalize_inventory(_content())
    assert normalized["s3_datasets"][0]["prefix"] == "gold/a/"
    assert normalized["glue_tables"][0]["name"] == "a"
    assert normalized["batch_job_definitions"][0]["revision"] == 1


def test_json_document_keeps_run_metadata_outside_logical_hash() -> None:
    first = json_document(run_id="one", generated_at="t1", content=_content())
    second = json_document(run_id="two", generated_at="t2", content=_content())
    assert first["logical_content_sha256"] == second["logical_content_sha256"]


def test_inventory_hash_ignores_cloudwatch_observation_timestamp() -> None:
    first = _content()
    first["s3_bucket_metrics"] = {
        "number_of_objects": {
            "timestamp": "2026-06-21T13:00:00+00:00",
            "average": 100,
            "unit": "Count",
        }
    }
    second = _content()
    second["s3_bucket_metrics"] = {
        "number_of_objects": {
            "timestamp": "2026-06-21T13:04:00+00:00",
            "average": 100,
            "unit": "Count",
        }
    }
    assert inventory_content_sha256(first) == inventory_content_sha256(second)


def test_inventory_hash_keeps_cloudwatch_metric_value() -> None:
    first = _content()
    first["s3_bucket_metrics"] = {
        "number_of_objects": {"timestamp": "t1", "average": 100, "unit": "Count"}
    }
    second = _content()
    second["s3_bucket_metrics"] = {
        "number_of_objects": {"timestamp": "t1", "average": 101, "unit": "Count"}
    }
    assert inventory_content_sha256(first) != inventory_content_sha256(second)


def test_parquet_rows_serializes_nested_values() -> None:
    rows = parquet_rows(_content())
    assert isinstance(rows[0]["schemas"], str)
