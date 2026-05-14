"""Unit tests for leviathan.transforms.bronze_to_silver.nasa_power_weather."""
from __future__ import annotations

import pandas as pd
import pytest

from leviathan.transforms.bronze_to_silver.nasa_power_weather import (
    WEATHER_RENAME_MAP,
    clean_one_weather_df,
)


EXPECTED_LONG_COLS = {
    "date", "year", "month", "day",
    "country", "region", "commodity", "source",
    "ingest_date", "variable", "value",
}
ALL_VARIABLES = set(WEATHER_RENAME_MAP.values())


class TestCleanOneWeatherDf:
    def test_returns_long_format(self, weather_bronze_wide_df):
        result = clean_one_weather_df(weather_bronze_wide_df)
        assert "variable" in result.columns
        assert "value" in result.columns
        # Wide weather columns must NOT be in output
        for wide_col in WEATHER_RENAME_MAP.keys():
            assert wide_col not in result.columns

    def test_exact_columns(self, weather_bronze_wide_df):
        result = clean_one_weather_df(weather_bronze_wide_df)
        assert set(result.columns) == EXPECTED_LONG_COLS

    def test_row_count_is_dates_times_variables(self, weather_bronze_wide_df):
        result = clean_one_weather_df(weather_bronze_wide_df)
        n_dates = weather_bronze_wide_df["date"].nunique()
        n_variables = len(ALL_VARIABLES)
        assert len(result) == n_dates * n_variables

    def test_variable_values_are_known(self, weather_bronze_wide_df):
        result = clean_one_weather_df(weather_bronze_wide_df)
        assert set(result["variable"].unique()) == ALL_VARIABLES

    def test_dedup_removes_duplicate_rows(self, weather_bronze_wide_df):
        doubled = pd.concat([weather_bronze_wide_df, weather_bronze_wide_df], ignore_index=True)
        result = clean_one_weather_df(doubled)
        # Dedup on (date, country, region, source) before melt — same count as single input
        single = clean_one_weather_df(weather_bronze_wide_df)
        assert len(result) == len(single)

    def test_missing_weather_col_is_skipped(self, weather_bronze_wide_df):
        df_partial = weather_bronze_wide_df.drop(columns=["t2m"])
        result = clean_one_weather_df(df_partial)
        # t2m maps to temperature_2m_mean_c; it should be absent from variable column
        assert "temperature_2m_mean_c" not in result["variable"].values
        # All other 6 variables should still be present
        expected_vars = ALL_VARIABLES - {"temperature_2m_mean_c"}
        assert set(result["variable"].unique()) == expected_vars

    def test_missing_required_col_raises(self, weather_bronze_wide_df):
        df_bad = weather_bronze_wide_df.drop(columns=["country"])
        with pytest.raises(ValueError, match="country"):
            clean_one_weather_df(df_bad)
