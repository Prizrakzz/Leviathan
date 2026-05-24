"""Data quality tests for silver FAOSTAT production invariants.

Validates that the bronze→silver FAOSTAT transform produces DataFrames
satisfying the expected structural and value-range contracts.
"""
from __future__ import annotations

import pandas as pd
import pytest

from leviathan.transforms.bronze_to_silver.faostat_production import (
    ELEMENT_TO_METRIC,
    transform_faostat_production_silver_df,
)


@pytest.fixture()
def silver_faostat_results(faostat_bronze_df: pd.DataFrame):
    """List of (year, silver_df) pairs from the fixture bronze FAOSTAT data."""
    return transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")


@pytest.fixture()
def silver_faostat_df(silver_faostat_results) -> pd.DataFrame:
    """Concatenated silver DataFrame across all years."""
    frames = [df for _, df in silver_faostat_results]
    return pd.concat(frames, ignore_index=True)


class TestSilverFaostatSchema:
    def test_returns_list_of_tuples(self, silver_faostat_results):
        assert isinstance(silver_faostat_results, list)
        for item in silver_faostat_results:
            assert isinstance(item, tuple)
            assert len(item) == 2

    def test_required_columns_present(self, silver_faostat_df):
        expected = {
            "commodity", "source", "country", "variable", "year",
            "unit", "value", "flag", "is_official",
        }
        missing = expected - set(silver_faostat_df.columns)
        assert missing == set(), f"Missing silver columns: {missing}"

    def test_commodity_set_correctly(self, silver_faostat_df):
        assert (silver_faostat_df["commodity"] == "cocoa").all()

    def test_source_is_faostat(self, silver_faostat_df):
        assert (silver_faostat_df["source"] == "faostat").all()

    def test_country_is_lowercased(self, silver_faostat_df):
        for country in silver_faostat_df["country"].unique():
            assert country == country.lower(), f"Country not lowercased: {country!r}"


class TestSilverFaostatVariables:
    def test_variable_values_are_standardized(self, silver_faostat_df):
        valid_vars = set(ELEMENT_TO_METRIC.values())
        actual_vars = set(silver_faostat_df["variable"].unique())
        assert actual_vars.issubset(valid_vars), \
            f"Unexpected variables: {actual_vars - valid_vars}"

    def test_all_three_variables_present(self, silver_faostat_df):
        expected_vars = set(ELEMENT_TO_METRIC.values())
        actual_vars = set(silver_faostat_df["variable"].unique())
        assert actual_vars == expected_vars, \
            f"Missing variables: {expected_vars - actual_vars}"

    def test_no_raw_element_names_in_variable(self, silver_faostat_df):
        """Raw FAO element names should be mapped, not left as-is.

        Mapped values include 'yield' (from ELEMENT_TO_METRIC), so only the
        original capitalized forms ('Yield', 'Production', 'Area harvested')
        are truly invalid raw names.
        """
        # Only the original FAO capitalized forms are invalid; mapped names
        # like 'yield', 'production_quantity', 'area_harvested' are fine.
        capitalized_raw_names = {"Production", "Area harvested", "Yield"}
        for val in silver_faostat_df["variable"].unique():
            assert val not in capitalized_raw_names, f"Unmapped element name: {val!r}"


class TestSilverFaostatValues:
    def test_value_column_is_numeric(self, silver_faostat_df):
        assert pd.api.types.is_numeric_dtype(silver_faostat_df["value"])

    def test_year_column_is_numeric(self, silver_faostat_df):
        assert pd.api.types.is_integer_dtype(silver_faostat_df["year"]) or \
               pd.api.types.is_float_dtype(silver_faostat_df["year"])

    def test_year_in_valid_range(self, silver_faostat_df):
        years = pd.to_numeric(silver_faostat_df["year"], errors="coerce").dropna()
        assert (years >= 1960).all()
        assert (years <= 2100).all()


class TestSilverFaostatIsOfficial:
    def test_is_official_is_boolean(self, silver_faostat_df):
        assert pd.api.types.is_bool_dtype(silver_faostat_df["is_official"])

    def test_flag_a_is_non_official(self, silver_faostat_df):
        """Rows with flag='A' (FAO aggregate) should be marked non-official.

        'A' is in NON_OFFICIAL_FLAGS, so is_official must be False.
        """
        flag_a_rows = silver_faostat_df[silver_faostat_df["flag"] == "A"]
        if not flag_a_rows.empty:
            assert (~flag_a_rows["is_official"]).all()

    def test_no_nulls_in_is_official(self, silver_faostat_df):
        assert silver_faostat_df["is_official"].notna().all()


class TestSilverFaostatYearPartitions:
    def test_each_partition_contains_year(self, silver_faostat_results):
        for year, df in silver_faostat_results:
            year_values = pd.to_numeric(df["year"], errors="coerce").dropna().unique()
            assert year in year_values, \
                f"Partition year={year} not found in df year column: {year_values}"

    def test_fixture_produces_single_year_partition(self, silver_faostat_results):
        # Fixture data has only year=2020
        assert len(silver_faostat_results) == 1
        year, _ = silver_faostat_results[0]
        assert year == 2020
