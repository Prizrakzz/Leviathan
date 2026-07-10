"""Unit tests for leviathan.transforms.bronze_to_silver.chirps_weather."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from leviathan.transforms.bronze_to_silver.chirps_weather import chirps_bronze_to_silver

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_bronze_df(n_days: int = 5, include_none: bool = False) -> pd.DataFrame:
    rows = []
    for day in range(1, n_days + 1):
        rows.append({
            "commodity": "corn_cbot",
            "source": "chirps",
            "country": "united_states",
            "region": "us_corn_iowa",
            "date": date(2020, 6, day).isoformat(),
            "year": 2020,
            "month": 6,
            "day": day,
            "latitude": 42.03,
            "longitude": -93.64,
            "precipitation_mm": None if (include_none and day == 3) else float(day) * 1.5,
            "ingest_date": "2026-05-16",
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestChirpsBronzeToSilver:
    def test_output_columns(self):
        df = _make_bronze_df()
        silver = chirps_bronze_to_silver(df)
        expected = {
            "date", "year", "month", "day", "country", "region",
            "commodity", "source", "ingest_date", "variable", "value",
        }
        assert set(silver.columns) == expected

    def test_latitude_longitude_dropped(self):
        df = _make_bronze_df()
        silver = chirps_bronze_to_silver(df)
        assert "latitude" not in silver.columns
        assert "longitude" not in silver.columns

    def test_variable_column_value(self):
        df = _make_bronze_df()
        silver = chirps_bronze_to_silver(df)
        assert (silver["variable"] == "precipitation_mm").all()

    def test_row_count(self):
        n_days = 5
        df = _make_bronze_df(n_days=n_days)
        silver = chirps_bronze_to_silver(df)
        # One row per day (melt of single variable)
        assert len(silver) == n_days

    def test_values_preserved(self):
        df = _make_bronze_df(n_days=3)
        silver = chirps_bronze_to_silver(df)
        expected_values = [1.5, 3.0, 4.5]
        assert sorted(silver["value"].tolist()) == pytest.approx(sorted(expected_values))

    def test_none_precipitation_dropped(self):
        # Null precipitation is coerced to NaN then dropped post-melt — value is a
        # required non-null silver column, so null rows never reach the partition.
        df = _make_bronze_df(n_days=3, include_none=True)
        silver = chirps_bronze_to_silver(df)
        assert silver["value"].isna().sum() == 0
        assert len(silver) == 2

    def test_raises_on_missing_required_column(self):
        df = _make_bronze_df()
        df = df.drop(columns=["precipitation_mm"])
        with pytest.raises(ValueError, match="precipitation_mm"):
            chirps_bronze_to_silver(df)

    def test_deduplication(self):
        df = _make_bronze_df(n_days=3)
        # Append a duplicate of day 1
        df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
        silver = chirps_bronze_to_silver(df)
        assert len(silver) == 3  # duplicate removed

    def test_date_coercion(self):
        df = _make_bronze_df(n_days=2)
        # Supply dates as strings — should be coerced cleanly
        df["date"] = df["date"].astype(str)
        silver = chirps_bronze_to_silver(df)
        assert len(silver) == 2
