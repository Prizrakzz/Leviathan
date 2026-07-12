"""Integration tests for bronze → silver transform pipeline.

Tests transform functions end-to-end using fixture DataFrames from conftest.
No AWS calls; all transforms run in-process.
"""
from __future__ import annotations

import pandas as pd
import pytest
from leviathan.transforms.bronze_to_silver.chirps_weather import chirps_bronze_to_silver
from leviathan.transforms.bronze_to_silver.faostat_production import (
    transform_faostat_production_silver_df,
)
from leviathan.transforms.bronze_to_silver.nasa_power_weather import nasa_power_bronze_to_silver
from leviathan.transforms.raw_to_bronze.nasa_power import nasa_power_payload_to_daily_dataframe

# ---------------------------------------------------------------------------
# NASA POWER: raw payload → bronze → silver
# ---------------------------------------------------------------------------

class TestNasaPowerRawToBronzeToSilver:
    def test_payload_to_bronze_returns_dataframe(self, nasa_power_payload):
        df = nasa_power_payload_to_daily_dataframe(
            payload=nasa_power_payload,
            source_file_name="sample.json",
            commodity="cocoa",
            country="ghana",
            region="gh_main",
            ingest_date="2024-01-01",
        )
        assert isinstance(df, pd.DataFrame)
        assert not df.empty

    def test_bronze_has_expected_identity_columns(self, nasa_power_payload):
        df = nasa_power_payload_to_daily_dataframe(
            payload=nasa_power_payload,
            source_file_name="sample.json",
            commodity="cocoa",
            country="ghana",
            region="gh_main",
            ingest_date="2024-01-01",
        )
        for col in ("date", "year", "month", "day", "source", "commodity", "country", "region"):
            assert col in df.columns, f"Missing bronze column: {col}"

    def test_bronze_to_silver_produces_wide_format(self, weather_bronze_wide_df):
        # SILVER-F021: nasa_power silver is WIDE (measurement columns, no variable/value melt).
        silver = nasa_power_bronze_to_silver(weather_bronze_wide_df)
        assert "variable" not in silver.columns
        assert "value" not in silver.columns
        assert "temperature_2m_max_c" in silver.columns
        # One wide row per date, not one per (date x variable).
        assert len(silver) == weather_bronze_wide_df["date"].nunique()

    def test_silver_wide_required_columns_present(self, weather_bronze_wide_df):
        from leviathan.transforms.bronze_to_silver._weather_quality import WIDE_REQUIRED_COLUMNS

        silver = nasa_power_bronze_to_silver(weather_bronze_wide_df)
        missing = [c for c in WIDE_REQUIRED_COLUMNS if c not in silver.columns]
        assert missing == [], f"Missing wide silver columns: {missing}"

    def test_silver_date_column_is_date_type(self, weather_bronze_wide_df):
        silver = nasa_power_bronze_to_silver(weather_bronze_wide_df)
        assert silver["date"].notna().all()

    def test_full_pipeline_payload_to_silver(self, nasa_power_payload):
        """End-to-end: raw payload -> bronze -> WIDE silver."""
        bronze = nasa_power_payload_to_daily_dataframe(
            payload=nasa_power_payload,
            source_file_name="sample.json",
            commodity="cocoa",
            country="ghana",
            region="gh_main",
            ingest_date="2024-01-01",
        )
        silver = nasa_power_bronze_to_silver(bronze)
        assert not silver.empty
        assert "temperature_2m_max_c" in silver.columns
        assert "source_file_name" in silver.columns


# ---------------------------------------------------------------------------
# CHIRPS: bronze → silver
# ---------------------------------------------------------------------------

class TestChirpsBronzeToSilver:
    def _make_chirps_bronze(self) -> pd.DataFrame:
        """Minimal CHIRPS bronze DataFrame in wide format.

        chirps_bronze_to_silver expects 'precipitation_mm' (already renamed
        from raw 'prectotcorr') plus all SILVER_WEATHER_ID_COLS.
        """
        return pd.DataFrame({
            "date": ["2020-01-01", "2020-01-02"],
            "year": [2020, 2020],
            "month": [1, 1],
            "day": [1, 2],
            "source": ["chirps", "chirps"],
            "commodity": ["cocoa", "cocoa"],
            "country": ["ghana", "ghana"],
            "region": ["gh_main", "gh_main"],
            "ingest_date": ["2024-01-01", "2024-01-01"],
            "precipitation_mm": [3.2, 0.0],
        })

    def test_returns_dataframe(self):
        df = self._make_chirps_bronze()
        result = chirps_bronze_to_silver(df)
        assert isinstance(result, pd.DataFrame)

    def test_silver_has_variable_and_value_columns(self):
        df = self._make_chirps_bronze()
        result = chirps_bronze_to_silver(df)
        assert "variable" in result.columns or len(result.columns) > 0

    def test_raises_on_missing_required_columns(self):
        bad_df = pd.DataFrame({"date": ["2020-01-01"], "prectotcorr": [1.0]})
        with pytest.raises((ValueError, KeyError)):
            chirps_bronze_to_silver(bad_df, source_label="test")


# ---------------------------------------------------------------------------
# FAOSTAT: bronze → silver
# ---------------------------------------------------------------------------

class TestFaostatBronzeToSilver:
    def test_returns_year_df_pairs(self, faostat_bronze_df):
        result = transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")
        assert isinstance(result, list)
        assert len(result) >= 1
        year, df = result[0]
        assert isinstance(year, int)
        assert isinstance(df, pd.DataFrame)

    # F022 reshaped the silver contract to source-faithful long/tidy (faostat_production.py
    # CANONICAL_PHYSICAL_COLUMNS): `metric` replaced `variable`; `country` is now the DISPLAY name
    # with the governed lowercase key in `country_key`; commodity is the partition axis, not a
    # physical column (matching the partitioned silver_production layout).
    def test_silver_commodity_is_partition_only(self, faostat_bronze_df):
        result = transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")
        _, df = result[0]
        assert "commodity" not in df.columns

    def test_silver_has_metric_column(self, faostat_bronze_df):
        result = transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")
        _, df = result[0]
        assert "metric" in df.columns

    def test_silver_metrics_are_standardized(self, faostat_bronze_df):
        result = transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")
        _, df = result[0]
        valid = {"production_quantity", "area_harvested", "yield"}
        assert set(df["metric"].unique()).issubset(valid)

    def test_country_display_and_governed_key(self, faostat_bronze_df):
        result = transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")
        _, df = result[0]
        assert "country" in df.columns and "country_key" in df.columns
        assert (df["country"] == "Ghana").all()          # display form preserved
        assert (df["country_key"] == "ghana").all()      # governed lowercase key

    def test_raises_if_required_columns_missing(self):
        bad_df = pd.DataFrame({"area": ["Ghana"], "item": ["Cocoa"]})
        with pytest.raises(ValueError, match="Missing required FAOSTAT bronze columns"):
            transform_faostat_production_silver_df(bad_df, commodity="cocoa")
