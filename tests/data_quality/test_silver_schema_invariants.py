"""Data quality tests for the WIDE silver weather schema (SILVER-F021 / F046).

The canonical silver_nasa_power is WIDE; validated by the wide-schema quality gate
(``run_wide_weather_quality_checks``). The long-melt invariants were retired with the long producer.
The LONG chirps/cpc silver stays validated by the shared long quality runner and is covered by the
chirps/cpc transform tests.
"""
from __future__ import annotations

import pandas as pd
import pytest

from leviathan.transforms.bronze_to_silver._weather_quality import (
    WIDE_NATURAL_KEY,
    WIDE_REQUIRED_COLUMNS,
    run_wide_weather_quality_checks,
)
from leviathan.transforms.bronze_to_silver.nasa_power_weather import nasa_power_bronze_to_silver


@pytest.fixture()
def silver_weather_wide_df(weather_bronze_wide_df: pd.DataFrame) -> pd.DataFrame:
    return nasa_power_bronze_to_silver(weather_bronze_wide_df)


class TestWideRequiredColumns:
    def test_all_required_columns_present(self, silver_weather_wide_df):
        missing = [c for c in WIDE_REQUIRED_COLUMNS if c not in silver_weather_wide_df.columns]
        assert missing == [], f"Missing wide silver columns: {missing}"

    def test_quality_gate_passes(self, silver_weather_wide_df):
        report = run_wide_weather_quality_checks(silver_weather_wide_df, "cocoa", "nasa_power")
        assert report["passed"], report["hard_failures"]


class TestWideRequiredNonNull:
    def test_key_id_columns_have_no_nulls(self, silver_weather_wide_df):
        for col in ("date", "year", "month", "day", "country", "region", "source"):
            assert silver_weather_wide_df[col].notna().all(), col


class TestWideDtypes:
    def test_year_month_day_integer(self, silver_weather_wide_df):
        for col in ("year", "month", "day"):
            assert pd.api.types.is_integer_dtype(silver_weather_wide_df[col]), col

    def test_measures_numeric(self, silver_weather_wide_df):
        assert pd.api.types.is_numeric_dtype(silver_weather_wide_df["temperature_2m_mean_c"])


class TestWideNaturalKeyUniqueness:
    def test_no_duplicate_natural_keys(self, silver_weather_wide_df):
        dupes = silver_weather_wide_df.duplicated(subset=WIDE_NATURAL_KEY).sum()
        assert dupes == 0


class TestWideIdColValues:
    def test_year_in_range(self, silver_weather_wide_df):
        assert (silver_weather_wide_df["year"] >= 1980).all()
        assert (silver_weather_wide_df["year"] <= 2100).all()

    def test_month_in_range(self, silver_weather_wide_df):
        assert silver_weather_wide_df["month"].between(1, 12).all()

    def test_source_is_nasa_power(self, silver_weather_wide_df):
        assert (silver_weather_wide_df["source"] == "nasa_power").all()


class TestWideQualityGateCatchesRegressions:
    def test_missing_measure_column_hard_fails(self, silver_weather_wide_df):
        broken = silver_weather_wide_df.drop(columns=["precipitation_mm"])
        report = run_wide_weather_quality_checks(broken, "cocoa", "nasa_power")
        assert not report["passed"]
        assert "precipitation_mm" in report["hard_failures"]["missing_columns"]

    def test_duplicate_key_hard_fails(self, silver_weather_wide_df):
        dup = pd.concat([silver_weather_wide_df, silver_weather_wide_df.iloc[[0]]], ignore_index=True)
        report = run_wide_weather_quality_checks(dup, "cocoa", "nasa_power")
        assert not report["passed"]
        assert "duplicate_natural_keys" in report["hard_failures"]
