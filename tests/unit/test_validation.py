"""Unit tests for leviathan.common.validation."""
from __future__ import annotations

import pytest

from leviathan.common.validation import SchemaValidationError, load_schema, validate_raw_df, validate_raw_json


class TestLoadSchema:
    def test_nasa_power_schema_loads(self):
        schema = load_schema("nasa_power")
        assert "required_path" in schema
        assert "required_parameters" in schema

    def test_faostat_qcl_schema_loads(self):
        schema = load_schema("faostat_qcl")
        assert "required_columns" in schema

    def test_unknown_source_raises(self):
        with pytest.raises(SchemaValidationError, match="No schema defined"):
            load_schema("nonexistent_source")


class TestValidateRawJson:
    def test_valid_payload_passes(self, nasa_power_payload):
        schema = load_schema("nasa_power")
        validate_raw_json(nasa_power_payload, schema, context="test")  # should not raise

    def test_missing_required_path_raises(self):
        bad_payload = {"type": "Feature", "geometry": {}, "properties": {}}
        schema = load_schema("nasa_power")
        with pytest.raises(SchemaValidationError, match="Missing required path"):
            validate_raw_json(bad_payload, schema, context="test")

    def test_missing_required_parameter_raises(self, nasa_power_payload):
        schema = load_schema("nasa_power")
        # Remove one of the required parameters
        del nasa_power_payload["properties"]["parameter"]["T2M"]
        with pytest.raises(SchemaValidationError, match="T2M"):
            validate_raw_json(nasa_power_payload, schema, context="test")

    def test_extra_parameters_are_allowed(self, nasa_power_payload):
        schema = load_schema("nasa_power")
        nasa_power_payload["properties"]["parameter"]["EXTRA_PARAM"] = {"20200101": 1.0}
        validate_raw_json(nasa_power_payload, schema, context="test")  # should not raise


class TestValidateRawDf:
    def test_valid_df_passes(self, faostat_bronze_df):
        schema = load_schema("faostat_qcl")
        validate_raw_df(faostat_bronze_df, schema, context="test")  # should not raise

    def test_missing_column_raises(self, faostat_bronze_df):
        schema = load_schema("faostat_qcl")
        df_missing = faostat_bronze_df.drop(columns=["value"])
        with pytest.raises(SchemaValidationError):
            validate_raw_df(df_missing, schema, context="test")

    def test_case_insensitive_column_check(self, faostat_bronze_df):
        schema = load_schema("faostat_qcl")
        # Rename to uppercase — should still pass
        df_upper = faostat_bronze_df.rename(columns=str.upper)
        validate_raw_df(df_upper, schema, context="test")  # should not raise
