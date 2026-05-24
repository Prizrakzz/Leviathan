"""Unit tests for leviathan.transforms.bronze_to_silver.faostat_production."""
from __future__ import annotations

import pandas as pd
import pytest

from leviathan.transforms.bronze_to_silver.faostat_production import (
    transform_faostat_production_silver_df,
)

EXPECTED_COLS = {
    "commodity", "source", "country", "variable",
    "year", "unit", "value", "flag", "is_official", "ingest_date",
}


class TestTransformFaostatProductionSilverDf:
    def test_returns_list_of_year_df_tuples(self, faostat_bronze_df):
        result = transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")
        assert isinstance(result, list)
        assert len(result) > 0
        for item in result:
            assert isinstance(item, tuple)
            assert len(item) == 2
            year, df = item
            assert isinstance(year, int)
            assert isinstance(df, pd.DataFrame)

    def test_correct_output_columns(self, faostat_bronze_df):
        result = transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")
        _, df = result[0]
        assert set(df.columns) == EXPECTED_COLS

    def test_uses_variable_not_metric(self, faostat_bronze_df):
        result = transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")
        _, df = result[0]
        assert "variable" in df.columns
        assert "metric" not in df.columns

    def test_uses_country_not_country_key(self, faostat_bronze_df):
        result = transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")
        _, df = result[0]
        assert "country" in df.columns
        assert "country_key" not in df.columns

    def test_capitalize_normalization(self):
        """Mixed-case element strings must all be recognized via str.capitalize()."""
        df = pd.DataFrame(
            {
                "area": ["Ghana"],
                "item": ["Cocoa beans"],
                "element": ["PRODUCTION"],  # all-caps — capitalize → "Production"
                "year": [2020],
                "unit": ["tonnes"],
                "value": [900_000.0],
                "flag": ["A"],
                "ingest_date": ["2024-01-01"],
            }
        )
        result = transform_faostat_production_silver_df(df, commodity="cocoa")
        assert len(result) == 1
        _, silver_df = result[0]
        assert (silver_df["variable"] == "production_quantity").all()

    def test_is_official_flag_logic(self, faostat_bronze_df):
        result = transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")
        _, df = result[0]
        # Flag "A" IS in NON_OFFICIAL_FLAGS → is_official == False for those rows
        flag_a_rows = df[df["flag"] == "A"]
        assert not flag_a_rows["is_official"].any()

    def test_non_official_flag_marked_correctly(self):
        df = pd.DataFrame(
            {
                "area": ["Ghana"],
                "item": ["Cocoa beans"],
                "element": ["Production"],
                "year": [2020],
                "unit": ["tonnes"],
                "value": [900_000.0],
                "flag": ["E"],  # "E" is a non-official estimate flag
                "ingest_date": ["2024-01-01"],
            }
        )
        result = transform_faostat_production_silver_df(df, commodity="cocoa")
        _, silver_df = result[0]
        assert not silver_df["is_official"].iloc[0]

    def test_partitioned_by_year(self, faostat_bronze_df):
        result = transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")
        years = [year for year, _ in result]
        assert all(isinstance(y, int) for y in years)
        # All rows in a partition should match the partition year
        for year, df in result:
            assert (df["year"] == year).all()

    def test_missing_required_column_raises(self):
        bad_df = pd.DataFrame({"area": ["Ghana"], "year": [2020]})
        with pytest.raises(ValueError, match="Missing required FAOSTAT bronze columns"):
            transform_faostat_production_silver_df(bad_df, commodity="cocoa")

    def test_unknown_elements_are_dropped(self):
        df = pd.DataFrame(
            {
                "area": ["Ghana"],
                "item": ["Cocoa beans"],
                "element": ["Some Unrecognized Element"],
                "year": [2020],
                "unit": ["tonnes"],
                "value": [1.0],
                "flag": ["A"],
                "ingest_date": ["2024-01-01"],
            }
        )
        result = transform_faostat_production_silver_df(df, commodity="cocoa")
        assert result == []
