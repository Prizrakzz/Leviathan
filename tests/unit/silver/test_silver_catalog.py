"""SILVER-F012/F013 shared: Glue-catalog normalization + hashing ignore AWS noise but catch real
managed-field changes. AWS-free."""
from __future__ import annotations

from leviathan.silver import catalog


def _table(location="s3://leviathan-test/silver/x", cols=None, params=None, ddl="111"):
    return {
        "Name": "silver_x",
        "TableType": "EXTERNAL_TABLE",
        "PartitionKeys": [{"Name": "y", "Type": "int"}],
        "Parameters": {"EXTERNAL": "TRUE", "transient_lastDdlTime": ddl, **(params or {})},
        "StorageDescriptor": {
            "Columns": cols or [{"Name": "a", "Type": "string"}, {"Name": "b", "Type": "double"}],
            "Location": location,
            "InputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
            "OutputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
            "SerdeInfo": {"SerializationLibrary": "serde", "Parameters": {"serialization.format": "1"}},
            "Parameters": {},
        },
    }


def test_transient_ddl_time_is_noise():
    a, b = _table(ddl="111"), _table(ddl="999")
    assert catalog.hash_table(a) == catalog.hash_table(b)
    assert catalog.diff_table(a, b) == []


def test_trailing_slash_location_is_equal():
    a = _table(location="s3://leviathan-test/silver/x")
    b = _table(location="s3://leviathan-test/silver/x/")
    assert catalog.hash_table(a) == catalog.hash_table(b)


def test_column_change_is_detected():
    a = _table()
    b = _table(cols=[{"Name": "a", "Type": "string"}, {"Name": "b", "Type": "bigint"}])
    assert catalog.hash_table(a) != catalog.hash_table(b)
    diffs = catalog.diff_table(a, b)
    assert any("columns" in d for d in diffs)


def test_column_reordering_is_a_real_change():
    a = _table(cols=[{"Name": "a", "Type": "string"}, {"Name": "b", "Type": "double"}])
    b = _table(cols=[{"Name": "b", "Type": "double"}, {"Name": "a", "Type": "string"}])
    assert catalog.hash_table(a) != catalog.hash_table(b)


def test_managed_param_change_detected_but_noise_param_not():
    base = _table()
    noisy = _table(params={"numRows": "42"})  # noise param
    assert catalog.diff_table(base, noisy) == []
    real = _table(params={"projection.enabled": "true"})
    assert any("parameters" in d for d in catalog.diff_table(base, real))


def test_storage_descriptor_location_diff():
    a = {"Location": "s3://leviathan-test/silver/x", "Columns": [{"Name": "a", "Type": "string"}]}
    b = {"Location": "s3://leviathan-test/silver/y", "Columns": [{"Name": "a", "Type": "string"}]}
    diffs = catalog.diff_storage_descriptor(a, b)
    assert any("location" in d for d in diffs)
    assert catalog.hash_storage_descriptor(a) != catalog.hash_storage_descriptor(b)
