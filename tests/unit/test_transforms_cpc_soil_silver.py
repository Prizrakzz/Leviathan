"""Unit tests for leviathan.transforms.bronze_to_silver.cpc_soil."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from leviathan.transforms.bronze_to_silver.cpc_soil import cpc_soil_bronze_to_silver

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_bronze_df(n_days: int = 5, include_none: bool = False) -> pd.DataFrame:
    rows = []
    for day in range(1, n_days + 1):
        rows.append({
            "commodity":        "corn_cbot",
            "source":           "cpc_soil",
            "variable":         "w",          # CPC variable code — dropped in silver
            "country":          "united_states",
            "region":           "us_corn_iowa",
            "date":             date(2020, 6, day).isoformat(),
            "year":             2020,
            "month":            6,
            "day":              day,
            "latitude":         42.03,
            "longitude":        -93.64,
            "soil_moisture_mm": None if (include_none and day == 3) else float(day) * 10.5,
            "ingest_date":      "2026-05-24",
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCpcSoilBronzeToSilver:
    def test_output_columns(self):
        df = _make_bronze_df()
        silver = cpc_soil_bronze_to_silver(df)
        expected = {
            "date", "year", "month", "day", "country", "region",
            "commodity", "source", "ingest_date", "variable", "value",
        }
        assert set(silver.columns) == expected

    def test_latitude_longitude_dropped(self):
        df = _make_bronze_df()
        silver = cpc_soil_bronze_to_silver(df)
        assert "latitude" not in silver.columns
        assert "longitude" not in silver.columns

    def test_cpc_variable_column_dropped(self):
        # Bronze has variable="w" (CPC code); silver must not carry it forward
        df = _make_bronze_df()
        silver = cpc_soil_bronze_to_silver(df)
        # The silver "variable" column should contain the measurement name, not "w"
        assert "w" not in silver["variable"].values

    def test_variable_column_value(self):
        df = _make_bronze_df()
        silver = cpc_soil_bronze_to_silver(df)
        assert (silver["variable"] == "soil_moisture_mm").all()

    def test_row_count(self):
        n_days = 5
        df = _make_bronze_df(n_days=n_days)
        silver = cpc_soil_bronze_to_silver(df)
        # One silver row per bronze row (single-variable melt)
        assert len(silver) == n_days

    def test_values_preserved(self):
        df = _make_bronze_df(n_days=3)
        silver = cpc_soil_bronze_to_silver(df)
        expected = [10.5, 21.0, 31.5]
        assert sorted(silver["value"].tolist()) == pytest.approx(sorted(expected))

    def test_none_dropped(self):
        # Null soil moisture is coerced to NaN then dropped post-melt — value is a
        # required non-null silver column, so null rows never reach the partition.
        df = _make_bronze_df(n_days=3, include_none=True)
        silver = cpc_soil_bronze_to_silver(df)
        assert silver["value"].isna().sum() == 0
        assert len(silver) == 2

    def test_raises_on_missing_required_column(self):
        df = _make_bronze_df()
        df = df.drop(columns=["soil_moisture_mm"])
        with pytest.raises(ValueError, match="soil_moisture_mm"):
            cpc_soil_bronze_to_silver(df)

    def test_deduplication(self):
        df = _make_bronze_df(n_days=3)
        # Append a duplicate of day 1
        df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
        silver = cpc_soil_bronze_to_silver(df)
        assert len(silver) == 3  # duplicate removed

    def test_date_coercion(self):
        df = _make_bronze_df(n_days=2)
        # Supply dates as strings — should be coerced cleanly
        df["date"] = df["date"].astype(str)
        silver = cpc_soil_bronze_to_silver(df)
        assert len(silver) == 2
