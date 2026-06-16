"""Unit tests for weather-stage and capacity computations (synthetic frames)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from leviathan.features.calendar import CropCalendar
from leviathan.features.computations.base import (
    FeatureContext,
    max_consecutive_true,
    trailing_baseline_z,
)
from leviathan.features.computations.capacity import compute_capacity_recovery_index
from leviathan.features.computations.weather_stage import (
    compute_drought_z,
    compute_frost_event_flag,
    compute_gdd_z,
    compute_stage_precip_z,
)

CORN = CropCalendar(
    commodity="corn_cbot", crop_year_start_month=5, mkt_year_offset=-1,
    stages={"planting": (5, 5), "silking": (7, 7), "grain_fill": (8, 8)},
    gdd_window=("planting", "grain_fill"),
)
ARABICA = CropCalendar(
    commodity="arabica_coffee", crop_year_start_month=4, mkt_year_offset=-1,
    stages={"frost_risk": (6, 7), "grain_fill": (11, 3)},
)

PARAMS = {
    "baselines": {"window_years": 30, "min_years": 3},
    "drought": {"dry_percentile": 20.0},
    "frost": {"severity_thresholds_c": [-2.0, -4.0, -6.0]},
    "capacity_recovery": {
        "half_life_years": 3.0,
        "min_carryforward_severity": 2,
        "tree_crops": ["arabica_coffee"],
    },
    "gdd": {"default": {"base_c": 10.0, "cap_c": 30.0},
            "per_commodity": {"corn_cbot": {"base_c": 10.0, "cap_c": 30.0}}},
}


def weather_frame(
    dates: pd.DatetimeIndex, values, variable: str,
    country: str = "united_states", region: str = "us_corn_belt",
) -> pd.DataFrame:
    return pd.DataFrame({
        "date": dates,
        "year": dates.year,
        "month": dates.month,
        "day": dates.day,
        "country": country,
        "region": region,
        "source": "chirps" if variable == "precipitation_mm" else "nasa_power",
        "variable": variable,
        "value": values,
    })


def july_days(year: int) -> pd.DatetimeIndex:
    return pd.date_range(f"{year}-07-01", f"{year}-07-31", freq="D")


def ctx_for(calendar: CropCalendar, inputs: dict, crop_years: list[int],
            commodity: str | None = None, country: str = "united_states") -> FeatureContext:
    return FeatureContext(
        commodity=commodity or calendar.commodity,
        crop_years=crop_years,
        countries=[country],
        calendar=calendar,
        inputs=inputs,
        params=PARAMS,
    )


# ---------------------------------------------------------------------------
# trailing_baseline_z / max_consecutive_true
# ---------------------------------------------------------------------------

def test_trailing_baseline_z_uses_only_prior_years() -> None:
    yearly = pd.Series({2000: 10.0, 2001: 10.0, 2002: 10.0, 2003: 16.0})
    z = trailing_baseline_z(yearly, window_years=30, min_years=3)
    # 2003 baseline = {10, 10, 10} -> std 0 -> NaN; with min_years=2:
    z2 = trailing_baseline_z(
        pd.Series({2000: 10.0, 2001: 12.0, 2002: 11.0, 2003: 16.0}),
        window_years=30, min_years=3,
    )
    mean = np.mean([10.0, 12.0, 11.0])
    std = np.std([10.0, 12.0, 11.0], ddof=1)
    assert z2.loc[2003] == pytest.approx((16.0 - mean) / std)
    assert np.isnan(z.loc[2003])          # zero variance -> NaN, not inf
    assert np.isnan(z2.loc[2001])         # only 1 prior year < min_years


def test_max_consecutive_true() -> None:
    assert max_consecutive_true(np.array([], dtype=bool)) == 0
    assert max_consecutive_true(np.array([True, True, False, True])) == 2
    assert max_consecutive_true(np.array([False, False])) == 0


# ---------------------------------------------------------------------------
# stage precip z
# ---------------------------------------------------------------------------

def test_stage_precip_z_hand_computed() -> None:
    """Constant daily precip per July -> stage mean == that constant."""
    frames, means = [], {2000: 3.0, 2001: 5.0, 2002: 4.0, 2003: 8.0}
    for year, mean in means.items():
        days = july_days(year)
        frames.append(weather_frame(days, [mean] * len(days), "precipitation_mm"))
    # Data must extend past the last window end for completeness
    df = pd.concat(frames, ignore_index=True)

    ctx = ctx_for(CORN, {"weather:chirps": df}, [2003])
    result = compute_stage_precip_z(ctx, None)

    row = result.loc[result["feature"] == "chirps_precip_z_us_corn_belt_silking"]
    assert len(row) == 1
    baseline = [3.0, 5.0, 4.0]
    expected = (8.0 - np.mean(baseline)) / np.std(baseline, ddof=1)
    assert row["value"].iloc[0] == pytest.approx(expected)


def test_stage_precip_z_incomplete_window_suppressed() -> None:
    """A stage window cut short by the end of data must not emit a value."""
    frames = []
    for year in (2000, 2001, 2002):
        days = july_days(year)
        frames.append(weather_frame(days, [4.0] * len(days), "precipitation_mm"))
    # 2003: data stops July 10 — window incomplete
    partial = pd.date_range("2003-07-01", "2003-07-10", freq="D")
    frames.append(weather_frame(partial, [0.0] * len(partial), "precipitation_mm"))
    df = pd.concat(frames, ignore_index=True)

    ctx = ctx_for(CORN, {"weather:chirps": df}, [2003])
    result = compute_stage_precip_z(ctx, None)
    assert result.loc[
        result["feature"] == "chirps_precip_z_us_corn_belt_silking"
    ].empty


# ---------------------------------------------------------------------------
# frost flag
# ---------------------------------------------------------------------------

def test_frost_flag_fires_and_clears() -> None:
    """Arabica frost window Jun-Jul: -3°C in 2001 -> 1; clean 2002 -> 0."""
    frames = []
    for year, tmin in ((2001, -3.0), (2002, 5.0)):
        days = pd.date_range(f"{year}-06-01", f"{year}-07-31", freq="D")
        values = [tmin] + [10.0] * (len(days) - 1)
        frames.append(weather_frame(
            days, values, "temperature_2m_min_c", country="brazil", region="sul_de_minas",
        ))
    df = pd.concat(frames, ignore_index=True)

    ctx = ctx_for(ARABICA, {"weather:nasa_power": df}, [2001, 2002], country="brazil")
    result = compute_frost_event_flag(ctx, None)
    by_year = result.set_index("crop_year")["value"]
    assert by_year.loc[2001] == 1.0
    assert by_year.loc[2002] == 0.0


def test_frost_flag_early_one_allowed_early_zero_suppressed() -> None:
    """Frost observed mid-window -> 1 immediately; no frost yet -> NaN, not 0."""
    days = pd.date_range("2001-06-01", "2001-06-15", freq="D")  # window ends Jul 31
    frost = weather_frame(days, [-3.0] * len(days), "temperature_2m_min_c",
                          country="brazil", region="frosty")
    clean = weather_frame(days, [10.0] * len(days), "temperature_2m_min_c",
                          country="brazil", region="clean")
    df = pd.concat([frost, clean], ignore_index=True)

    ctx = ctx_for(ARABICA, {"weather:nasa_power": df}, [2001], country="brazil")
    result = compute_frost_event_flag(ctx, None)
    features = set(result["feature"])
    assert "frost_event_flag_frosty" in features          # early 1 emitted
    assert "frost_event_flag_clean" not in features       # early 0 suppressed


# ---------------------------------------------------------------------------
# GDD
# ---------------------------------------------------------------------------

def test_gdd_z_hand_computed_with_caps() -> None:
    """Annual capped GDD over the May-Aug window, z-scored vs the 3 prior years.

    Per-day GDD = (min(Tmax, 30) + max(Tmin, 10))/2 - 10.  With Tmin pinned at
    the base (10), GDD/day collapses to (min(Tmax, 30) - 10) / 2, so each year's
    annual GDD is a clean function of its Tmax.
    """
    per_year_tmax = {2000: 20.0, 2001: 24.0, 2002: 22.0, 2003: 30.0}
    frames = []
    for year, tmax in per_year_tmax.items():
        days = pd.date_range(f"{year}-05-01", f"{year}-08-31", freq="D")
        frames.append(weather_frame(days, [tmax] * len(days), "temperature_2m_max_c"))
        frames.append(weather_frame(days, [10.0] * len(days), "temperature_2m_min_c"))
    df = pd.concat(frames, ignore_index=True)

    ctx = ctx_for(CORN, {"weather:nasa_power": df}, [2003])
    result = compute_gdd_z(ctx, None)
    row = result.loc[result["feature"] == "gdd_z_us_corn_belt"]
    assert len(row) == 1

    annual = {
        year: ((min(tmax, 30.0) - 10.0) / 2.0)
        * len(pd.date_range(f"{year}-05-01", f"{year}-08-31", freq="D"))
        for year, tmax in per_year_tmax.items()
    }
    baseline = [annual[2000], annual[2001], annual[2002]]
    expected = (annual[2003] - np.mean(baseline)) / np.std(baseline, ddof=1)
    assert row["value"].iloc[0] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# drought z (run-length of dry days, z-scored)
# ---------------------------------------------------------------------------

def test_drought_z_hand_computed() -> None:
    """Annual longest dry-day run, z-scored vs the trailing run-count baseline.

    Wet baseline (2000-2002, 10 mm/day) sets the 20th-percentile dry threshold
    at 10, so the lone block of 0 mm days in each later year is the only dry
    run.  Its length per year drives the z-score emitted for the target year.
    """
    dry_len = {2003: 5, 2004: 8, 2005: 6, 2006: 20}
    frames = []
    for year in (2000, 2001, 2002):  # wet baseline establishes the threshold
        days = july_days(year)
        frames.append(weather_frame(days, [10.0] * len(days), "precipitation_mm"))
    for year, dl in dry_len.items():
        days = july_days(year)
        values = [10.0] * 5 + [0.0] * dl + [10.0] * (len(days) - 5 - dl)
        frames.append(weather_frame(days, values, "precipitation_mm"))
    df = pd.concat(frames, ignore_index=True)

    ctx = ctx_for(CORN, {"weather:chirps": df}, [2006])
    result = compute_drought_z(ctx, None)
    row = result.loc[result["feature"] == "drought_z_us_corn_belt_silking"]
    assert len(row) == 1
    runs = pd.Series({year: float(dl) for year, dl in dry_len.items()})
    expected = trailing_baseline_z(runs, 30, 3).loc[2006]
    assert row["value"].iloc[0] == pytest.approx(expected)


def test_drought_z_insufficient_baseline_years_emits_nothing() -> None:
    days = july_days(2001)
    df = weather_frame(days, [0.0] * len(days), "precipitation_mm")
    ctx = ctx_for(CORN, {"weather:chirps": df}, [2001])
    result = compute_drought_z(ctx, None)
    assert result.loc[
        result["feature"] == "drought_z_us_corn_belt_silking"
    ].empty


# ---------------------------------------------------------------------------
# capacity recovery index
# ---------------------------------------------------------------------------

def test_capacity_recovery_decay_formula() -> None:
    """Severity-2 frost (Tmin -5) in crop 2000: capacity(Y) = 1 - (2/3)*0.5^(dt/3)."""
    frames = []
    for year, tmin in ((1999, 8.0), (2000, -5.0), (2001, 9.0), (2002, 9.0)):
        days = pd.date_range(f"{year}-06-01", f"{year}-07-31", freq="D")
        values = [tmin] + [10.0] * (len(days) - 1)
        frames.append(weather_frame(
            days, values, "temperature_2m_min_c", country="brazil", region="sul",
        ))
    df = pd.concat(frames, ignore_index=True)

    ctx = ctx_for(ARABICA, {"weather:nasa_power": df}, [2001, 2002],
                  commodity="arabica_coffee", country="brazil")
    result = compute_capacity_recovery_index(ctx, None)
    cap = result.loc[result["feature"] == "capacity_recovery_index_sul"]
    by_year = cap.set_index("crop_year")["value"]
    assert by_year.loc[2001] == pytest.approx(1 - (2 / 3) * 0.5 ** (1 / 3))
    assert by_year.loc[2002] == pytest.approx(1 - (2 / 3) * 0.5 ** (2 / 3))
    # Lookback truncation flag present in early years (< 2*half_life of history)
    flags = result.loc[result["feature"] == "capacity_lookback_truncated_sul"]
    assert flags.set_index("crop_year")["value"].loc[2001] == 1.0


def test_capacity_recovery_only_severe_events_carry_forward() -> None:
    """Severity-1 frost (-3°C, cherry-kill) must NOT depress later capacity."""
    frames = []
    for year, tmin in ((1999, 8.0), (2000, -3.0), (2001, 9.0)):
        days = pd.date_range(f"{year}-06-01", f"{year}-07-31", freq="D")
        values = [tmin] + [10.0] * (len(days) - 1)
        frames.append(weather_frame(
            days, values, "temperature_2m_min_c", country="brazil", region="sul",
        ))
    df = pd.concat(frames, ignore_index=True)

    ctx = ctx_for(ARABICA, {"weather:nasa_power": df}, [2001],
                  commodity="arabica_coffee", country="brazil")
    result = compute_capacity_recovery_index(ctx, None)
    cap = result.loc[result["feature"] == "capacity_recovery_index_sul"]
    assert cap["value"].iloc[0] == 1.0


def test_capacity_recovery_non_tree_crop_skipped() -> None:
    ctx = ctx_for(CORN, {"weather:nasa_power": pd.DataFrame()}, [2001],
                  commodity="corn_cbot")
    assert compute_capacity_recovery_index(ctx, None).empty
