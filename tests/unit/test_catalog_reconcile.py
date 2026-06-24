"""Tests for safe catalog planning and schema comparison."""
from __future__ import annotations

import io

import pyarrow as pa
import pyarrow.parquet as pq

from leviathan.catalog.aws import athena_has_data_rows
from leviathan.catalog.reconcile import (
    build_catalog_plan,
    desired_table_signature,
    live_table_signature,
    verify_plan_hash,
)
from leviathan.catalog.registry import load_dataset_registry
from leviathan.catalog.schema_probe import PrefixProbe, probe_prefix, schema_mismatches
from scripts.catalog.apply_catalog import drop_table_sql


def _live_from_desired(dataset, bucket):
    desired = desired_table_signature(dataset, bucket)
    return {
        "Name": dataset.athena.table,
        "StorageDescriptor": {
            "Columns": [
                {"Name": item["name"], "Type": item["type"]}
                for item in desired["columns"]
            ],
            "Location": desired["location"],
        },
        "PartitionKeys": [
            {"Name": item["name"], "Type": item["type"]}
            for item in desired["partitions"]
        ],
        "Parameters": desired["properties"],
    }


def test_catalog_plan_is_noop_for_matching_table() -> None:
    registry = load_dataset_registry()
    dataset = registry.by_id()["silver_psd"]
    plan = build_catalog_plan(
        registry,
        {dataset.athena.table: _live_from_desired(dataset, registry.bucket)},
    )
    action = next(item for item in plan["actions"] if item["table"] == "silver_psd")
    assert action["action"] == "noop"
    assert verify_plan_hash(plan)


def test_catalog_plan_replaces_drift_and_retires_legacy() -> None:
    registry = load_dataset_registry()
    dataset = registry.by_id()["silver_psd"]
    live = _live_from_desired(dataset, registry.bucket)
    live["StorageDescriptor"]["Location"] = "s3://wrong-bucket/silver/psd"
    plan = build_catalog_plan(
        registry,
        {
            "silver_psd": live,
            "production_raw": {"Name": "production_raw", "StorageDescriptor": {}},
        },
    )
    actions = {item["table"]: item for item in plan["actions"]}
    assert actions["silver_psd"]["action"] == "replace"
    assert actions["silver_psd"]["reasons"] == ["location"]
    assert actions["production_raw"]["action"] == "retire"


def test_catalog_comparison_ignores_parquet_compression_spelling() -> None:
    registry = load_dataset_registry()
    dataset = registry.by_id()["silver_psd"]
    live = _live_from_desired(dataset, registry.bucket)
    live["Parameters"]["parquet.compress"] = "SNAPPY"
    live["Parameters"].pop("parquet.compression", None)
    assert desired_table_signature(dataset, registry.bucket) == live_table_signature(live)


def test_catalog_drop_uses_athena_identifier_quotes() -> None:
    assert drop_table_sql("leviathan_dev", "silver_psd") == (
        "DROP TABLE IF EXISTS `leviathan_dev`.`silver_psd`"
    )


def test_athena_result_requires_a_row_after_the_header() -> None:
    class Athena:
        def __init__(self, rows):
            self.rows = rows

        def get_query_results(self, **_kwargs):
            return {"ResultSet": {"Rows": self.rows}}

    assert not athena_has_data_rows(Athena([{"Data": []}]), "query")
    assert athena_has_data_rows(
        Athena([{"Data": []}, {"Data": [{"VarCharValue": "value"}]}]),
        "query",
    )


def test_schema_probe_ignores_partition_columns_in_parquet() -> None:
    dataset = load_dataset_registry().by_id()["silver_production"]
    actual = tuple((column.name, column.type) for column in dataset.schema)
    probe = PrefixProbe(
        prefix=dataset.s3_prefix,
        object_count_seen=1,
        sampled_files=("part.parquet",),
        schema_hashes=("hash",),
        schemas=(actual,),
    )
    assert schema_mismatches(dataset, probe) == []


def test_schema_probe_detects_changed_value_type() -> None:
    dataset = load_dataset_registry().by_id()["silver_psd"]
    actual = list((column.name, column.type) for column in dataset.schema)
    actual[5] = (actual[5][0], "string")
    probe = PrefixProbe(
        prefix=dataset.s3_prefix,
        object_count_seen=1,
        sampled_files=("part.parquet",),
        schema_hashes=("hash",),
        schemas=(tuple(actual),),
    )
    assert schema_mismatches(dataset, probe)


def test_schema_probe_accepts_null_for_nullable_parquet_column() -> None:
    dataset = load_dataset_registry().by_id()["gold_feature_catalog"]
    actual = list((column.name, column.type) for column in dataset.schema)
    actual[2] = (actual[2][0], "null")
    probe = PrefixProbe(
        prefix=dataset.s3_prefix,
        object_count_seen=1,
        sampled_files=("part.parquet",),
        schema_hashes=("hash",),
        schemas=(tuple(actual),),
    )
    assert schema_mismatches(dataset, probe) == []


def test_schema_probe_reads_only_parquet_footer_ranges() -> None:
    buffer = io.BytesIO()
    pq.write_table(pa.table({"value": [1.0]}), buffer)
    parquet = buffer.getvalue()

    class Body:
        def __init__(self, value):
            self.value = value

        def read(self):
            return self.value

    class Paginator:
        def paginate(self, **_kwargs):
            return [{"Contents": [{"Key": "silver/x/part.parquet", "Size": len(parquet)}]}]

    class S3:
        def __init__(self):
            self.ranges = []

        def get_paginator(self, _name):
            return Paginator()

        def get_object(self, *, Range, **_kwargs):
            self.ranges.append(Range)
            length = int(Range.removeprefix("bytes=-"))
            return {"Body": Body(parquet[-length:])}

    s3 = S3()
    probe = probe_prefix(s3, bucket="bucket", prefix="silver/x/", max_files=1)
    assert probe.schemas == ((("value", "double"),),)
    assert s3.ranges[0] == "bytes=-8"
    assert len(parquet) > int(s3.ranges[1].removeprefix("bytes=-"))
