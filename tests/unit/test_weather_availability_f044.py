"""SILVER-F044 (narrowed): CHIRPS typed availability. A physical partition exists ONLY when >= 1 valid
source observation exists; a 404/empty date is a typed availability result, never a null-filled map.
"""
from __future__ import annotations

import pandas as pd

from leviathan.transforms.bronze_to_silver.chirps_weather import (
    WeatherAvailability,
    chirps_bronze_to_silver,
    classify_availability,
)


def _bronze(precip):
    n = len(precip)
    return pd.DataFrame({
        "date": [f"2020-01-{i+1:02d}" for i in range(n)],
        "year": [2020] * n, "month": [1] * n, "day": list(range(1, n + 1)),
        "source": ["chirps"] * n, "commodity": ["cocoa"] * n,
        "country": ["ghana"] * n, "region": ["gh_main"] * n,
        "ingest_date": ["2026-06-16"] * n, "precipitation_mm": precip,
    })


class TestClassifyAvailability:
    def test_none_is_not_published(self):
        assert classify_availability(None) is WeatherAvailability.NOT_PUBLISHED

    def test_empty_is_no_valid_obs(self):
        empty = chirps_bronze_to_silver(_bronze([float("nan"), float("nan")]))
        assert empty.empty
        assert classify_availability(empty) is WeatherAvailability.EMPTY_NO_VALID_OBS

    def test_real_data_is_available(self):
        silver = chirps_bronze_to_silver(_bronze([3.2, 0.0]))
        assert classify_availability(silver) is WeatherAvailability.AVAILABLE


class TestNoNullFilledPartition:
    def test_all_nan_precip_yields_no_rows(self):
        """An all-missing bronze must NOT produce a null-filled partition -- it melts to empty so the
        writer creates no object (F044 existence rule)."""
        silver = chirps_bronze_to_silver(_bronze([float("nan"), float("nan"), float("nan")]))
        assert len(silver) == 0

    def test_zero_precip_is_a_real_observation(self):
        """A valid 0.0 mm dry day is a real observation and is retained (not treated as missing)."""
        silver = chirps_bronze_to_silver(_bronze([0.0, 0.0]))
        assert len(silver) == 2
        assert (silver["value"] == 0.0).all()

    def test_partial_missing_keeps_only_valid(self):
        silver = chirps_bronze_to_silver(_bronze([3.0, float("nan"), 1.5]))
        assert len(silver) == 2
        assert set(silver["value"]) == {3.0, 1.5}
