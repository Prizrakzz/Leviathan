"""Unit tests for leviathan.common.validation."""
from __future__ import annotations

import pytest
from leviathan.common.validation import (
    SchemaValidationError,
    load_schema,
    validate_bronze_df,
    validate_raw_df,
    validate_raw_json,
)


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


class TestValidateBronzeDf:
    def test_valid_chirps_df_passes(self):
        import pandas as pd

        schema = load_schema("chirps")
        df = pd.DataFrame(
            {
                "commodity":       ["cocoa"],
                "source":          ["chirps"],
                "country":         ["ghana"],
                "region":          ["gh_main"],
                "date":            ["2020-01-01"],
                "year":            [2020],
                "month":           [1],
                "day":             [1],
                "latitude":        [7.0],
                "longitude":       [-1.0],
                "precipitation_mm": [3.5],
                "ingest_date":     ["2024-01-01"],
            }
        )
        result = validate_bronze_df(df, schema, source="chirps", context="test")
        assert result["year_range"]["min"] == 2020
        assert result["new_columns"] == []

    def test_empty_df_raises(self):
        import pandas as pd

        schema = load_schema("chirps")
        with pytest.raises(SchemaValidationError, match="empty"):
            validate_bronze_df(pd.DataFrame(), schema)

    def test_missing_required_column_raises(self):
        import pandas as pd

        schema = load_schema("chirps")
        df = pd.DataFrame({"country": ["ghana"], "year": [2020]})
        with pytest.raises(SchemaValidationError, match="Missing required bronze columns"):
            validate_bronze_df(df, schema)

    def test_year_range_returned(self):
        import pandas as pd

        schema = load_schema("chirps")
        df = pd.DataFrame(
            {
                "commodity":       ["cocoa", "cocoa"],
                "source":          ["chirps", "chirps"],
                "country":         ["ghana", "ghana"],
                "region":          ["r1", "r1"],
                "date":            ["2019-01-01", "2021-01-01"],
                "year":            [2019, 2021],
                "month":           [1, 1],
                "day":             [1, 1],
                "latitude":        [7.0, 7.0],
                "longitude":       [-1.0, -1.0],
                "precipitation_mm": [1.0, 2.0],
                "ingest_date":     ["2024-01-01", "2024-01-01"],
            }
        )
        result = validate_bronze_df(df, schema, source="chirps")
        assert result["year_range"]["min"] == 2019
        assert result["year_range"]["max"] == 2021

    def test_schema_drift_new_columns_reported(self):
        import pandas as pd

        schema = load_schema("chirps")
        df = pd.DataFrame(
            {
                "commodity":       ["cocoa"],
                "source":          ["chirps"],
                "country":         ["ghana"],
                "region":          ["gh_main"],
                "date":            ["2020-01-01"],
                "year":            [2020],
                "month":           [1],
                "day":             [1],
                "latitude":        [7.0],
                "longitude":       [-1.0],
                "precipitation_mm": [3.5],
                "ingest_date":     ["2024-01-01"],
                "extra_new_col":   ["unexpected"],
            }
        )
        result = validate_bronze_df(df, schema, source="chirps")
        assert "extra_new_col" in result["new_columns"]

    def test_null_counts_returned(self):
        import pandas as pd

        schema = load_schema("chirps")
        df = pd.DataFrame(
            {
                "commodity":       ["cocoa"],
                "source":          ["chirps"],
                "country":         ["ghana"],
                "region":          ["gh_main"],
                "date":            ["2020-01-01"],
                "year":            [2020],
                "month":           [1],
                "day":             [1],
                "latitude":        [None],  # null
                "longitude":       [-1.0],
                "precipitation_mm": [None],  # null
                "ingest_date":     ["2024-01-01"],
            }
        )
        result = validate_bronze_df(df, schema, source="chirps")
        assert result["null_counts"].get("latitude") == 1
        assert result["null_counts"].get("precipitation_mm") == 1


class TestOptionalColumns:
    """BF-W1: a schema optional_column is neither required nor drift (nasa solar)."""

    def _base(self):
        import pandas as pd
        return pd.DataFrame({
            "commodity": ["cocoa"], "source": ["nasa_power"], "country": ["ghana"],
            "region": ["gh"], "date": ["1983-02-01"], "year": [1983], "month": [2],
            "day": [1], "t2m": [27.0], "t2m_max": [30.0], "t2m_min": [22.0],
            "prectotcorr": [3.2], "rh2m": [80.0], "ws2m": [1.1],
            "ingest_date": ["2026-07-14"], "source_file_name": ["f.json"],
        })

    def test_historical_bronze_without_solar_passes(self):
        from leviathan.common.validation import load_schema, validate_bronze_df
        schema = load_schema("nasa_power_bronze")
        # no allsky_sfc_sw_dwn column (pre-2025 era) -- must not raise
        validate_bronze_df(self._base(), schema, source="nasa_power", context="1983")

    def test_current_bronze_with_solar_is_not_drift(self, caplog):
        import logging
        from leviathan.common.validation import load_schema, validate_bronze_df
        df = self._base()
        df["allsky_sfc_sw_dwn"] = [18.5]     # 2025+ era carries solar
        with caplog.at_level(logging.WARNING):
            validate_bronze_df(df, load_schema("nasa_power_bronze"), source="nasa_power")
        assert "schema drift" not in caplog.text.lower()

    def test_genuine_drift_still_warns(self, caplog):
        import logging
        from leviathan.common.validation import load_schema, validate_bronze_df
        df = self._base()
        df["mystery_param"] = [1.0]
        with caplog.at_level(logging.WARNING):
            validate_bronze_df(df, load_schema("nasa_power_bronze"), source="nasa_power")
        assert "mystery_param" in caplog.text
