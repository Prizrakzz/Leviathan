"""Unit tests for the canonical WIDE NASA POWER silver producer (SILVER-F021).

C-WRONG-7 / F021: the live silver_nasa_power is WIDE (one measurement column per variable,
source_file_name retained, commodity is a path-only partition). The prior long-melt transform is
retired; these tests assert the exact wide contract, sentinel scrubbing, unknown-parameter fail-close,
and conflicting-duplicate-key rejection.
"""
from __future__ import annotations

import pandas as pd
import pyarrow as pa
import pytest

from leviathan.transforms.bronze_to_silver._weather_schema import NASA_POWER_WIDE_SCHEMA
from leviathan.transforms.bronze_to_silver.nasa_power_weather import (
    WIDE_OUTPUT_COLS,
    ConflictingWeatherKeys,
    clean_one_weather_df,
    nasa_power_bronze_to_silver,
)

# The canonical wide output = R0 baseline arrow_columns minus the path-only ``commodity``.
EXPECTED_WIDE_COLS = [
    "date", "year", "month", "day", "country", "region", "source", "ingest_date", "source_file_name",
    "temperature_2m_mean_c", "temperature_2m_max_c", "temperature_2m_min_c",
    "precipitation_mm", "relative_humidity_2m_pct", "wind_speed_2m_m_s",
]


class TestWideContract:
    def test_exact_ordered_columns(self, weather_bronze_wide_df):
        result = nasa_power_bronze_to_silver(weather_bronze_wide_df)
        assert list(result.columns) == EXPECTED_WIDE_COLS == WIDE_OUTPUT_COLS

    def test_no_long_columns(self, weather_bronze_wide_df):
        result = nasa_power_bronze_to_silver(weather_bronze_wide_df)
        assert "variable" not in result.columns
        assert "value" not in result.columns

    def test_commodity_is_path_only(self, weather_bronze_wide_df):
        """commodity is a partition dir, NOT a wide silver column (matches the 15-col live layout)."""
        result = nasa_power_bronze_to_silver(weather_bronze_wide_df)
        assert "commodity" not in result.columns

    def test_source_file_name_preserved(self, weather_bronze_wide_df):
        result = nasa_power_bronze_to_silver(weather_bronze_wide_df)
        assert "source_file_name" in result.columns
        assert (result["source_file_name"] == "sample.json").all()

    def test_solar_radiation_excluded(self, weather_bronze_wide_df):
        """allsky_sfc_sw_dwn is not a declared column -- excluded (separate additive-schema decision)."""
        result = nasa_power_bronze_to_silver(weather_bronze_wide_df)
        assert "solar_radiation_mj_m2_day" not in result.columns

    def test_one_row_per_date(self, weather_bronze_wide_df):
        result = nasa_power_bronze_to_silver(weather_bronze_wide_df)
        assert len(result) == weather_bronze_wide_df["date"].nunique()

    def test_measure_values_carried(self, weather_bronze_wide_df):
        result = nasa_power_bronze_to_silver(weather_bronze_wide_df).sort_values("date")
        assert result["temperature_2m_max_c"].tolist() == [30.2, 31.0, 29.5]
        assert result["precipitation_mm"].tolist() == [2.5, 0.0, 1.1]

    def test_conforms_to_pinned_arrow_schema(self, weather_bronze_wide_df):
        from leviathan.transforms.bronze_to_silver._weather_schema import enforce_arrow_schema
        result = nasa_power_bronze_to_silver(weather_bronze_wide_df)
        table = enforce_arrow_schema(result, NASA_POWER_WIDE_SCHEMA)
        assert table.schema.equals(NASA_POWER_WIDE_SCHEMA)


class TestSentinelScrub:
    def test_minus_999_becomes_nan(self, weather_bronze_wide_df):
        df = weather_bronze_wide_df.copy()
        df.loc[0, "t2m"] = -999.0
        result = nasa_power_bronze_to_silver(df).sort_values("date").reset_index(drop=True)
        assert pd.isna(result.loc[0, "temperature_2m_mean_c"])

    def test_zero_precip_is_kept(self, weather_bronze_wide_df):
        """A real 0.0 mm dry day is NOT a sentinel and must survive."""
        result = nasa_power_bronze_to_silver(weather_bronze_wide_df)
        assert (result["precipitation_mm"] == 0.0).any()


class TestFailClosed:
    def test_unknown_parameter_raises(self, weather_bronze_wide_df):
        df = weather_bronze_wide_df.copy()
        df["mystery_param"] = 1.0
        with pytest.raises(ValueError, match="Unknown NASA POWER parameter"):
            nasa_power_bronze_to_silver(df)

    def test_unknown_parameter_tolerated_when_not_strict(self, weather_bronze_wide_df):
        df = weather_bronze_wide_df.copy()
        df["mystery_param"] = 1.0
        result = nasa_power_bronze_to_silver(df, strict_params=False)
        assert "mystery_param" not in result.columns

    def test_missing_required_col_raises(self, weather_bronze_wide_df):
        df_bad = weather_bronze_wide_df.drop(columns=["country"])
        with pytest.raises(ValueError, match="country"):
            nasa_power_bronze_to_silver(df_bad)

    def test_conflicting_duplicate_keys_rejected(self, weather_bronze_wide_df):
        dup = weather_bronze_wide_df.iloc[[0]].copy()
        dup["t2m_max"] = 99.9  # same key, different measurement -> conflict
        df = pd.concat([weather_bronze_wide_df, dup], ignore_index=True)
        with pytest.raises(ConflictingWeatherKeys):
            nasa_power_bronze_to_silver(df)

    def test_exact_duplicate_rows_collapse(self, weather_bronze_wide_df):
        df = pd.concat([weather_bronze_wide_df, weather_bronze_wide_df], ignore_index=True)
        result = nasa_power_bronze_to_silver(df)
        assert len(result) == weather_bronze_wide_df["date"].nunique()

    def test_long_melt_entrypoint_is_retired(self, weather_bronze_wide_df):
        with pytest.raises(NotImplementedError, match="SILVER-F021"):
            clean_one_weather_df(weather_bronze_wide_df)
