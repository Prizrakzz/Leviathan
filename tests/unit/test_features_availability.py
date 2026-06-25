from __future__ import annotations

import pandas as pd
import pytest

from leviathan.features.availability import AvailabilityError, normalize_availability


def test_nass_crop_progress_available_on_observation_date() -> None:
    out = normalize_availability(
        "nass_crop_progress",
        pd.DataFrame({"date": ["2024-06-30"], "pct_good_excellent": [62.0]}),
    )
    assert out["feature_available_at"].iloc[0] == pd.Timestamp("2024-06-30")
    assert out["source_vintage"].iloc[0] == "nass_crop_progress:2024-06-30"


def test_fgis_weekly_defaults_to_week_ending_plus_seven_days() -> None:
    out = normalize_availability(
        "fgis",
        pd.DataFrame({"week_ending_date": ["2024-09-05"], "exports_mt_weekly": [1.0]}),
    )
    assert out["feature_available_at"].iloc[0] == pd.Timestamp("2024-09-12")


def test_pink_sheet_monthly_available_month_end_plus_fifteen_days() -> None:
    out = normalize_availability(
        "pink_sheet",
        pd.DataFrame({"year": [2024], "month": [5], "brent_crude_usd_bbl_zscore_5yr": [0.4]}),
    )
    assert out["observation_date"].iloc[0] == pd.Timestamp("2024-05-31")
    assert out["feature_available_at"].iloc[0] == pd.Timestamp("2024-06-15")


def test_futures_prices_available_next_day() -> None:
    out = normalize_availability(
        "futures_prices",
        pd.DataFrame({"date": ["2024-01-10"], "leviathan_slug": ["soybeans_cbot"], "close": [1200]}),
    )
    assert out["feature_available_at"].iloc[0] == pd.Timestamp("2024-01-11")


def test_oni_monthly_available_month_end_plus_fifteen_days() -> None:
    out = normalize_availability(
        "oni",
        pd.DataFrame({"year": [2024], "month": [6], "oni_anom": [0.8]}),
    )
    assert out["observation_date"].iloc[0] == pd.Timestamp("2024-06-30")
    assert out["feature_available_at"].iloc[0] == pd.Timestamp("2024-07-15")


def test_fred_fx_available_next_day() -> None:
    out = normalize_availability(
        "fred_fx",
        pd.DataFrame({"date": ["2024-07-19"], "brl_usd_pct_change_90d": [0.03]}),
    )
    assert out["feature_available_at"].iloc[0] == pd.Timestamp("2024-07-20")


def test_unknown_source_rejected() -> None:
    with pytest.raises(AvailabilityError, match="unsupported"):
        normalize_availability("mystery_source", pd.DataFrame({"date": ["2024-01-01"]}))
