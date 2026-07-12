"""SILVER-V002 -- common/quality.py value-nonnull + flat-range + freshness helpers."""
from __future__ import annotations

import pandas as pd

from leviathan.common.quality import (
    check_flat_value_ranges,
    check_freshness,
    check_value_nonnull,
)


def test_check_value_nonnull_flags_all_nan():
    df = pd.DataFrame({"value": [None, None, None]})
    below = check_value_nonnull(df, ["value"], 0.5)
    assert below == {"value": 0.0}


def test_check_value_nonnull_flags_below_floor():
    df = pd.DataFrame({"value": [1.0, None, None, None]})  # 0.25
    below = check_value_nonnull(df, ["value"], 0.5)
    assert set(below) == {"value"}
    assert below["value"] == 0.25


def test_check_value_nonnull_passes_healthy():
    df = pd.DataFrame({"value": [1.0, 2.0, None, 4.0]})  # 0.75
    assert check_value_nonnull(df, ["value"], 0.5) == {}


def test_check_flat_value_ranges_negative_production():
    df = pd.DataFrame({"production_mt": [10.0, -5.0, 20.0]})
    v = check_flat_value_ranges(df)
    assert "production_mt" in v
    assert v["production_mt"]["out_of_range_count"] == 1


def test_check_flat_value_ranges_ok():
    df = pd.DataFrame({"brl_usd": [5.0, 5.1, 5.2]})
    assert check_flat_value_ranges(df) == {}


def test_check_freshness():
    assert check_freshness("2026-05-16", "2026-06-16") is False   # stale (CHIRPS)
    assert check_freshness("2026-06-16", "2026-06-16") is True    # benign re-ingest (AV-12)
    assert check_freshness("2026-06-20", "2026-06-16") is True    # fresh
    assert check_freshness(None, "2026-06-16") is True            # not evaluable
    assert check_freshness("2026-06-16", None) is True
