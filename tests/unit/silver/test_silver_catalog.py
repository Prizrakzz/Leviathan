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


# --------------------------------------------------------------------------- is_schema_widen (F047)
_WIDE = "s3://leviathan-test/silver/weather/source=nasa_power/commodity=cocoa/year=1981/"
_C_NARROW = [{"Name": "date", "Type": "date"}, {"Name": "value", "Type": "double"}]
_C_WIDE = _C_NARROW + [
    {"Name": "country", "Type": "string"},
    {"Name": "region", "Type": "string"},
    {"Name": "month", "Type": "bigint"},
]


def _sd_cols(cols, location=_WIDE):
    return {
        "Columns": cols, "Location": location,
        "InputFormat": "if", "OutputFormat": "of",
        "SerdeInfo": {"SerializationLibrary": "serde", "Parameters": {"serialization.format": "1"}},
        "Parameters": {},
    }


def test_is_schema_widen_trailing_append_same_location():
    # the exact weather-trio drift: partition SD is the leading prefix; table SD appended cols.
    assert catalog.is_schema_widen(_sd_cols(_C_NARROW), _sd_cols(_C_WIDE)) is True


def test_is_schema_widen_trailing_slash_insensitive_location():
    assert catalog.is_schema_widen(_sd_cols(_C_NARROW, _WIDE.rstrip("/")),
                                   _sd_cols(_C_WIDE, _WIDE)) is True


def test_is_schema_widen_false_on_location_diff():
    other = _WIDE.replace("year=1981", "year=1999")
    assert catalog.is_schema_widen(_sd_cols(_C_NARROW), _sd_cols(_C_WIDE, other)) is False


def test_is_schema_widen_false_on_reorder():
    reordered = [_C_WIDE[1], _C_WIDE[0]] + _C_WIDE[2:]  # existing not a prefix of desired
    assert catalog.is_schema_widen(_sd_cols(reordered), _sd_cols(_C_WIDE)) is False


def test_is_schema_widen_false_on_retype():
    retyped = [{"Name": "date", "Type": "date"}, {"Name": "value", "Type": "string"}]  # value retyped
    assert catalog.is_schema_widen(_sd_cols(retyped), _sd_cols(_C_WIDE)) is False


def test_is_schema_widen_false_on_narrowing_or_equal():
    assert catalog.is_schema_widen(_sd_cols(_C_WIDE), _sd_cols(_C_NARROW)) is False  # narrowing
    assert catalog.is_schema_widen(_sd_cols(_C_WIDE), _sd_cols(_C_WIDE)) is False    # equal, not a widen


def test_is_schema_widen_false_on_serde_or_format_diff():
    desired = _sd_cols(_C_WIDE)
    desired["InputFormat"] = "different_if"
    assert catalog.is_schema_widen(_sd_cols(_C_NARROW), desired) is False
