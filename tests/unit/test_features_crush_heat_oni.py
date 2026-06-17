"""Unit tests for crush_margin_z, heat_stress_z, and oni_lag families."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from leviathan.features.calendar import CropCalendar
from leviathan.features.computations.base import FeatureContext
from leviathan.features.computations.macro_climate import compute_oni_lag
from leviathan.features.computations.sd_balance import compute_crush_margin_z
from leviathan.features.computations.weather_stage import compute_heat_stress_z

CORN = CropCalendar(
    commodity="corn_cbot", crop_year_start_month=5, mkt_year_offset=-1,
    stages={"planting": (5, 5), "silking": (7, 7), "grain_fill": (8, 8)},
    gdd_window=("planting", "grain_fill"),
)
PARAMS = {
    "baselines": {"window_years": 30, "min_years": 3},
    "heat_stress": {"default": {"threshold_c": 35.0},
                    "per_commodity": {"corn_cbot": {"threshold_c": 35.0}}},
    "crush": {"meal_coef": 0.022, "oil_coef": 0.11, "bean_coef": 0.01},
}


def _ctx(commodity, calendar, inputs, crop_years, country="united_states"):
    return FeatureContext(
        commodity=commodity, crop_years=crop_years, countries=[country],
        calendar=calendar, inputs=inputs, params=PARAMS,
    )


# ---------------------------------------------------------------------------
# crush margin
# ---------------------------------------------------------------------------

def _futures(years):
    rows = []
    for i, yr in enumerate(years):
        # One Jan obs per year; crush rises over time so the z trends up.
        beans, meal, oil = 1000.0, 300.0 + i * 5, 50.0 + i
        for slug, close in [("soybeans_cbot", beans), ("soybean_meal_cbot", meal),
                            ("soybean_oil_cbot", oil)]:
            rows.append({"date": pd.Timestamp(f"{yr}-01-15"), "leviathan_slug": slug, "close": close})
    return pd.DataFrame(rows)


def test_crush_margin_z_hand_computed() -> None:
    years = list(range(2000, 2012))
    fut = _futures(years)
    # crop_year_start_month=1 → cutoff Jan 1; latest crush before cutoff is the
    # PRIOR year's Jan obs.
    cal = CropCalendar(commodity="soybeans_cbot", crop_year_start_month=1,
                       mkt_year_offset=-1, stages={}, gdd_window=None)
    ctx = _ctx("soybeans_cbot", cal, {"futures_prices": fut}, [2011])
    out = compute_crush_margin_z(ctx, None)
    row = out.loc[out["feature"] == "crush_margin_z"]
    assert len(row) == 1
    # Reconstruct the annual crush series and expected trailing z for 2011.
    crush = {yr: 0.022 * (300 + i * 5) + 0.11 * (50 + i) - 0.01 * 1000
             for i, yr in enumerate(years)}
    annual = {cy: crush[cy - 1] for cy in range(2001, 2012)}  # latest-before-Jan-1
    s = pd.Series(annual).sort_index()
    base = s.loc[2001:2010]
    expected = (s.loc[2011] - base.mean()) / base.std(ddof=1)
    assert row["value"].iloc[0] == pytest.approx(expected)


def test_crush_margin_z_only_for_soy_complex() -> None:
    cal = CropCalendar(commodity="corn_cbot", crop_year_start_month=1,
                       mkt_year_offset=-1, stages={}, gdd_window=None)
    ctx = _ctx("corn_cbot", cal, {"futures_prices": _futures(range(2000, 2012))}, [2011])
    assert compute_crush_margin_z(ctx, None).empty


# ---------------------------------------------------------------------------
# heat stress
# ---------------------------------------------------------------------------

def _tmax_frame(year_to_hotdays: dict[int, int]) -> pd.DataFrame:
    """Daily tmax across the GDD window (Jul–Aug, so the window is complete);
    the first `hot` July days are 40°C (silking heat), everything else 20°C."""
    rows = []
    for year, hot in year_to_hotdays.items():
        days = pd.date_range(f"{year}-07-01", f"{year}-08-31", freq="D")
        for d in days:
            is_hot = d.month == 7 and d.day <= hot
            rows.append({
                "date": d, "year": year, "month": d.month, "day": d.day,
                "country": "united_states", "region": "us_corn_belt",
                "source": "nasa_power", "variable": "temperature_2m_max_c",
                "value": 40.0 if is_hot else 20.0,
            })
    return pd.DataFrame(rows)


def test_heat_stress_z_counts_threshold_days() -> None:
    hotdays = {2000: 2, 2001: 4, 2002: 3, 2003: 12}
    df = _tmax_frame(hotdays)
    ctx = _ctx("corn_cbot", CORN, {"weather:nasa_power": df}, [2003])
    out = compute_heat_stress_z(ctx, None)
    row = out.loc[out["feature"] == "heat_stress_z_us_corn_belt"]
    assert len(row) == 1
    base = [hotdays[2000], hotdays[2001], hotdays[2002]]
    expected = (hotdays[2003] - np.mean(base)) / np.std(base, ddof=1)
    assert row["value"].iloc[0] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# ONI lag
# ---------------------------------------------------------------------------

def _oni_frame() -> pd.DataFrame:
    rows = []
    for year in range(1998, 2005):
        for month in range(1, 13):
            rows.append({
                "year": year, "month": month,
                "oni_lag3": -0.5, "oni_lag6": 0.3,
                "la_nina_brazil_flag": 1.0, "argentina_la_nina_flag": 0.0,
            })
    return pd.DataFrame(rows)


def test_oni_lag_emits_lags_and_routes_region_flags() -> None:
    oni = _oni_frame()
    # corn (start month 5) → Argentina flag, no Brazil flag
    ctx_corn = _ctx("corn_cbot", CORN, {"oni": oni}, [2003])
    feats_corn = set(compute_oni_lag(ctx_corn, None)["feature"])
    assert "oni_lag3_prior" in feats_corn and "oni_lag6_prior" in feats_corn
    assert "oni_la_nina_argentina_flag" in feats_corn
    assert "oni_la_nina_brazil_flag" not in feats_corn

    # arabica (Brazil origin) → Brazil flag, no Argentina flag
    arabica_cal = CropCalendar(commodity="arabica_coffee", crop_year_start_month=4,
                               mkt_year_offset=-1, stages={}, gdd_window=None)
    ctx_arab = _ctx("arabica_coffee", arabica_cal, {"oni": oni}, [2003], country="brazil")
    feats_arab = set(compute_oni_lag(ctx_arab, None)["feature"])
    assert "oni_la_nina_brazil_flag" in feats_arab
    assert "oni_la_nina_argentina_flag" not in feats_arab
