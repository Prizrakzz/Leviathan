"""Unit tests for FAOSTAT production features, labels, and PSD S/D features."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from leviathan.features.calendar import CropCalendar
from leviathan.features.computations.base import FeatureContext
from leviathan.features.computations.production import (
    compute_faostat_available,
    compute_faostat_labels,
    compute_faostat_production_trend_dev,
    compute_faostat_production_yoy,
)
from leviathan.features.computations.sd_balance import (
    compute_psd_available,
    compute_psd_ending_stock_su_ratio,
)

CORN = CropCalendar(
    commodity="corn_cbot", crop_year_start_month=5, mkt_year_offset=-1,
    stages={"planting": (5, 5)},
)

PARAMS = {"production": {"trend_years": 10, "trend_min_years": 5}}


def faostat_frame(production: dict[int, float], country: str = "brazil") -> pd.DataFrame:
    rows = []
    for year, value in production.items():
        rows.append({"country": country, "variable": "production_quantity",
                     "year": year, "value": value})
        rows.append({"country": country, "variable": "yield",
                     "year": year, "value": value / 100.0})
    return pd.DataFrame(rows)


def ctx_for(inputs: dict, crop_years: list[int], country: str = "brazil") -> FeatureContext:
    return FeatureContext(
        commodity="corn_cbot", crop_years=crop_years, countries=[country],
        calendar=CORN, inputs=inputs, params=PARAMS,
    )


# ---------------------------------------------------------------------------
# FAOSTAT features
# ---------------------------------------------------------------------------

def test_yoy_uses_prior_two_years_never_observation_year() -> None:
    """yoy for crop year Y is the Y-2 -> Y-1 change; Y's own value must not matter."""
    base = {2007: 100.0, 2008: 110.0, 2009: 121.0}
    with_y = dict(base)
    with_y[2010] = 999.0  # observation year's own outcome
    ctx_a = ctx_for({"production:faostat": faostat_frame(base)}, [2010])
    ctx_b = ctx_for({"production:faostat": faostat_frame(with_y)}, [2010])

    val_a = compute_faostat_production_yoy(ctx_a, None)["value"].iloc[0]
    val_b = compute_faostat_production_yoy(ctx_b, None)["value"].iloc[0]
    assert val_a == pytest.approx((121.0 - 110.0) / 110.0)
    assert val_a == val_b  # Y's outcome invisible to Y's feature


def test_trend_dev_zero_on_perfectly_linear_history() -> None:
    production = {year: 1000.0 + 50.0 * (year - 2000) for year in range(2000, 2010)}
    ctx = ctx_for({"production:faostat": faostat_frame(production)}, [2010])
    result = compute_faostat_production_trend_dev(ctx, None)
    assert result["value"].iloc[0] == pytest.approx(0.0, abs=1e-9)


def test_trend_dev_requires_min_points() -> None:
    ctx = ctx_for({"production:faostat": faostat_frame({2008: 1.0, 2009: 2.0})}, [2010])
    assert compute_faostat_production_trend_dev(ctx, None).empty


def test_labels_emit_observation_year_outcomes() -> None:
    ctx = ctx_for({"production:faostat": faostat_frame({2009: 100.0, 2010: 137.0})}, [2010])
    result = compute_faostat_labels(ctx, None)
    labels = result.set_index("feature")["value"]
    assert labels.loc["label_production_quantity"] == 137.0
    assert labels.loc["label_yield"] == pytest.approx(1.37)


def test_availability_flag() -> None:
    ctx = ctx_for({"production:faostat": faostat_frame({2009: 100.0})}, [2010, 2005])
    result = compute_faostat_available(ctx, None)
    by_year = result.set_index("crop_year")["value"]
    assert by_year.loc[2010] == 1.0   # 2009 visible
    assert by_year.loc[2005] == 0.0   # nothing before 2005


# ---------------------------------------------------------------------------
# PSD features
# ---------------------------------------------------------------------------

def psd_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "leviathan_slug": ["corn_cbot"] * 4,
        "country": ["united_states"] * 4,
        "market_year": [2023, 2023, 2023, 2024],
        "wasde_release_month": [2, 4, 6, 4],
        "release_date": ["2024-02-08", "2024-04-11", "2024-06-12", "2024-04-11"],
        "su_ratio": [0.10, 0.12, 0.14, 0.99],
        "su_ratio_yoy_delta": [np.nan, -0.01, 0.0, 0.5],
        "production_mt_revision": [1.0, 2.0, 3.0, 4.0],
        "ending_stocks_mt_revision": [0.1, 0.2, 0.3, 0.4],
    })


def test_su_ratio_takes_planting_time_vintage_of_prior_marketing_year() -> None:
    ctx = ctx_for({"psd": psd_frame()}, [2024], country="united_states")
    result = compute_psd_ending_stock_su_ratio(ctx, None)
    assert result["value"].iloc[0] == pytest.approx(0.12)


def test_psd_available_reflects_point_in_time_vintage() -> None:
    ctx = ctx_for({"psd": psd_frame()}, [2024, 1990], country="united_states")
    result = compute_psd_available(ctx, None)
    by_year = result.set_index("crop_year")["value"]
    assert by_year.loc[2024] == 1.0
    assert by_year.loc[1990] == 0.0  # no vintage exists before 1990 planting


def test_psd_missing_input_emits_zero_availability_only() -> None:
    ctx = ctx_for({}, [2024], country="united_states")
    assert compute_psd_ending_stock_su_ratio(ctx, None).empty
    avail = compute_psd_available(ctx, None)
    assert avail["value"].iloc[0] == 0.0
