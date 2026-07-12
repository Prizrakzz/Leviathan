"""Unit tests for leviathan.transforms.bronze_to_silver.faostat_production (SILVER-F022).

The canonical ``silver_production`` body is the 12 registry physical columns -- commodity and year
are the projected partition keys (path-carried), never in the parquet body; ``variable`` is renamed
to ``metric``; ``country`` is the DISPLAY country + ``country_key`` the governed key.
"""
from __future__ import annotations

import pandas as pd
import pytest
from leviathan.transforms.bronze_to_silver.faostat_production import (
    CANONICAL_PHYSICAL_COLUMNS,
    FaostatMappingError,
    SilverProductionLayoutError,
    assert_canonical_production_key,
    transform_faostat_production_silver_df,
)

EXPECTED_COLS = set(CANONICAL_PHYSICAL_COLUMNS)


class TestTransformFaostatProductionSilverDf:
    def test_returns_list_of_year_df_tuples(self, faostat_bronze_df):
        result = transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")
        assert isinstance(result, list) and len(result) > 0
        for year, df in result:
            assert isinstance(year, int)
            assert isinstance(df, pd.DataFrame)

    def test_body_is_exactly_the_12_canonical_columns(self, faostat_bronze_df):
        _, df = transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")[0]
        assert list(df.columns) == CANONICAL_PHYSICAL_COLUMNS   # exact order (INV-2 writer schema)
        # commodity + year are partition keys -> NEVER in the body.
        assert "commodity" not in df.columns
        assert "year" not in df.columns

    def test_uses_metric_not_variable(self, faostat_bronze_df):
        _, df = transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")[0]
        assert "metric" in df.columns
        assert "variable" not in df.columns

    def test_preserves_display_country_and_derives_key(self):
        df = pd.DataFrame({
            "area": ["Cote d'Ivoire"], "item": ["Cocoa beans"], "element": ["Production"],
            "year": [2020], "unit": ["tonnes"], "value": [1.5e6], "flag": [""],
            "ingest_date": ["2024-01-01"],
        })
        _, silver = transform_faostat_production_silver_df(df, commodity="cocoa")[0]
        assert silver["country"].iloc[0] == "Cote d'Ivoire"          # display preserved
        assert silver["country_key"].iloc[0] == "cote_divoire"        # governed key derived

    def test_metric_mapping_capitalizes_and_maps(self):
        df = pd.DataFrame({
            "area": ["Ghana"], "item": ["Cocoa beans"], "element": ["PRODUCTION"],
            "year": [2020], "unit": ["tonnes"], "value": [9e5], "flag": ["A"],
            "ingest_date": ["2024-01-01"],
        })
        _, silver = transform_faostat_production_silver_df(df, commodity="cocoa")[0]
        assert (silver["metric"] == "production_quantity").all()

    def test_provenance_columns_defaulted(self, faostat_bronze_df):
        _, df = transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")[0]
        assert (df["source"] == "faostat").all()
        assert (df["dataset"] == "QCL").all()
        assert df["note"].isna().all()
        assert df["source_file_name"].isna().all()

    def test_is_official_flag_logic(self, faostat_bronze_df):
        _, df = transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")[0]
        flag_a_rows = df[df["flag"] == "A"]
        assert not flag_a_rows["is_official"].any()

    def test_non_official_flag_marked_correctly(self):
        df = pd.DataFrame({
            "area": ["Ghana"], "item": ["Cocoa beans"], "element": ["Production"],
            "year": [2020], "unit": ["tonnes"], "value": [9e5], "flag": ["E"],
            "ingest_date": ["2024-01-01"],
        })
        _, silver = transform_faostat_production_silver_df(df, commodity="cocoa")[0]
        assert not silver["is_official"].iloc[0]

    def test_partition_years_are_ints(self, faostat_bronze_df):
        result = transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")
        assert all(isinstance(y, int) for y, _ in result)

    def test_missing_required_column_raises(self):
        with pytest.raises(ValueError, match="Missing required FAOSTAT bronze columns"):
            transform_faostat_production_silver_df(
                pd.DataFrame({"area": ["Ghana"], "year": [2020]}), commodity="cocoa"
            )

    def test_unknown_elements_are_dropped(self):
        df = pd.DataFrame({
            "area": ["Ghana"], "item": ["Cocoa beans"], "element": ["Some Unrecognized Element"],
            "year": [2020], "unit": ["tonnes"], "value": [1.0], "flag": ["A"],
            "ingest_date": ["2024-01-01"],
        })
        assert transform_faostat_production_silver_df(df, commodity="cocoa") == []

    def test_conflicting_duplicate_value_raises(self):
        df = pd.DataFrame({
            "area": ["Ghana", "Ghana"], "item": ["Cocoa beans", "Cocoa beans"],
            "element": ["Production", "Production"], "year": [2020, 2020],
            "unit": ["tonnes", "tonnes"], "value": [9e5, 8e5], "flag": ["", ""],
            "ingest_date": ["2024-01-01", "2024-01-01"],
        })
        with pytest.raises(FaostatMappingError, match="conflicting duplicate"):
            transform_faostat_production_silver_df(df, commodity="cocoa")

    def test_exact_duplicate_value_collapses(self):
        df = pd.DataFrame({
            "area": ["Ghana", "Ghana"], "item": ["Cocoa beans", "Cocoa beans"],
            "element": ["Production", "Production"], "year": [2020, 2020],
            "unit": ["tonnes", "tonnes"], "value": [9e5, 9e5], "flag": ["", ""],
            "ingest_date": ["2024-01-01", "2024-01-01"],
        })
        _, silver = transform_faostat_production_silver_df(df, commodity="cocoa")[0]
        assert len(silver) == 1


class TestCanonicalKeyGuard:
    def test_accepts_canonical_layout(self):
        key = "silver/production/commodity=cocoa/year=2020/part-000.parquet"
        assert assert_canonical_production_key(key) == key

    @pytest.mark.parametrize("bad", [
        "silver/production/source=faostat/commodity=cocoa/year=2020/part-000.parquet",
        "silver/production/year=2020/part-000.parquet",
        "silver/other/commodity=cocoa/year=2020/p.parquet",
    ])
    def test_refuses_non_canonical(self, bad):
        with pytest.raises(SilverProductionLayoutError):
            assert_canonical_production_key(bad)
