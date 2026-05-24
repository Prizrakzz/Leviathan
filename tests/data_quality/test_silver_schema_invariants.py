"""Data quality tests for silver weather schema invariants.

Validates that silver DataFrames produced by the bronze→silver transforms
always satisfy the structural contracts defined in leviathan.common.quality.
"""
from __future__ import annotations

import pandas as pd
import pytest

from leviathan.common.quality import (
    SILVER_NATURAL_KEY,
    SILVER_REQUIRED_COLUMNS,
    SILVER_REQUIRED_NON_NULL,
    check_required_columns,
)
from leviathan.common.constants import SILVER_WEATHER_ID_COLS
from leviathan.transforms.bronze_to_silver.nasa_power_weather import clean_one_weather_df


@pytest.fixture()
def silver_weather_df(weather_bronze_wide_df: pd.DataFrame) -> pd.DataFrame:
    """Silver DataFrame derived from the shared weather_bronze_wide_df fixture."""
    return clean_one_weather_df(weather_bronze_wide_df)


class TestSilverRequiredColumns:
    def test_all_required_columns_present(self, silver_weather_df):
        missing = check_required_columns(silver_weather_df)
        assert missing == [], f"Missing required silver columns: {missing}"

    def test_silver_weather_id_cols_subset_of_silver_columns(self, silver_weather_df):
        for col in SILVER_WEATHER_ID_COLS:
            assert col in silver_weather_df.columns, f"ID column missing: {col}"

    def test_variable_column_present(self, silver_weather_df):
        assert "variable" in silver_weather_df.columns

    def test_value_column_present(self, silver_weather_df):
        assert "value" in silver_weather_df.columns


class TestSilverRequiredNonNull:
    def test_no_nulls_in_required_non_null_columns(self, silver_weather_df):
        for col in SILVER_REQUIRED_NON_NULL:
            if col in silver_weather_df.columns:
                null_count = silver_weather_df[col].isna().sum()
                assert null_count == 0, f"Column {col!r} has {null_count} nulls"

    def test_date_column_has_no_nulls(self, silver_weather_df):
        assert silver_weather_df["date"].notna().all()

    def test_commodity_column_has_no_nulls(self, silver_weather_df):
        assert silver_weather_df["commodity"].notna().all()


class TestSilverDtypes:
    def test_year_is_numeric(self, silver_weather_df):
        assert pd.api.types.is_integer_dtype(silver_weather_df["year"]) or \
               pd.api.types.is_float_dtype(silver_weather_df["year"])

    def test_month_is_numeric(self, silver_weather_df):
        assert pd.api.types.is_integer_dtype(silver_weather_df["month"]) or \
               pd.api.types.is_float_dtype(silver_weather_df["month"])

    def test_value_is_numeric(self, silver_weather_df):
        assert pd.api.types.is_numeric_dtype(silver_weather_df["value"])


class TestSilverNaturalKeyUniqueness:
    def test_no_duplicate_natural_keys(self, silver_weather_df):
        key_cols = [c for c in SILVER_NATURAL_KEY if c in silver_weather_df.columns]
        if len(key_cols) == len(SILVER_NATURAL_KEY):
            dupes = silver_weather_df.duplicated(subset=key_cols).sum()
            assert dupes == 0, f"Found {dupes} duplicate rows on natural key"

    def test_silver_has_multiple_variables(self, silver_weather_df):
        # After melt, there should be more than one distinct variable
        assert silver_weather_df["variable"].nunique() > 1


class TestSilverIdColValues:
    def test_year_in_valid_range(self, silver_weather_df):
        assert (silver_weather_df["year"] >= 1980).all()
        assert (silver_weather_df["year"] <= 2100).all()

    def test_month_in_valid_range(self, silver_weather_df):
        assert (silver_weather_df["month"] >= 1).all()
        assert (silver_weather_df["month"] <= 12).all()

    def test_day_in_valid_range(self, silver_weather_df):
        assert (silver_weather_df["day"] >= 1).all()
        assert (silver_weather_df["day"] <= 31).all()

    def test_source_is_nasa_power(self, silver_weather_df):
        assert (silver_weather_df["source"] == "nasa_power").all()

    def test_commodity_consistent(self, silver_weather_df):
        # All rows should share the same commodity (fixture uses "cocoa")
        assert silver_weather_df["commodity"].nunique() == 1
