"""SILVER-F023: Pink Sheet reproduces all 36 columns (OP-3 close).

Covers the 9 restored commodity-price series, the governed sugar unit rule, exact 36-column output
against the registry contract, and the bronze fail-closed guard on a missing/ambiguous required
header (a disappeared header must never publish a narrowed table).
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from leviathan.silver.registry import load_registry
from leviathan.transforms.bronze_to_silver.pink_sheet import (
    SILVER_COLUMNS,
    _SERIES_RENAME,
    build_silver,
)
from leviathan.transforms.raw_to_bronze.world_bank_pink_sheet import (
    _REQUIRED_SERIES,
    _SERIES_PATTERNS,
    _match_columns,
)

_NEW_SERIES = {
    "crude_oil_brent_usd_bbl": "brent_crude_usd_bbl",
    "soybeans_usd_mt": "soybeans_usd_t",
    "soybean_oil_usd_mt": "soybean_oil_usd_t",
    "soybean_meal_usd_mt": "soybean_meal_usd_t",
    "palm_oil_usd_mt": "palm_oil_cpo_usd_t",
    "sugar_world_usd_kg": "raw_sugar_world_usd_t",
    "wheat_us_hrw_usd_mt": "wheat_us_hrw_usd_t",
    "wheat_us_srw_usd_mt": "wheat_us_srw_usd_t",
    "rapeseed_oil_usd_mt": "rapeseed_oil_usd_t",
}


def _bronze_all_series(d="2026-01-01", release="2026M05", values=None):
    values = values or {}
    rows = []
    for bronze_name in _SERIES_RENAME:
        rows.append({
            "date": date.fromisoformat(d), "series_name": bronze_name,
            "value_usd": float(values.get(bronze_name, 100.0)),
            "release_ym": release, "source": "world_bank_pink_sheet",
        })
    return pd.DataFrame(rows)


def test_output_is_exactly_the_36_registry_columns():
    contract_cols = [c["name"] for c in load_registry().table("silver_pink_sheet")["physical_columns"]]
    assert SILVER_COLUMNS == contract_cols
    df = build_silver([_bronze_all_series()])
    assert list(df.columns) == contract_cols
    assert len(df.columns) == 36


def test_nine_commodity_series_are_restored():
    assert set(_NEW_SERIES.keys()) <= set(_SERIES_RENAME)
    df = build_silver([_bronze_all_series()])
    for silver_col in _NEW_SERIES.values():
        assert silver_col in df.columns
        # sugar carries the governed x1000 kg->tonne unit rule; the rest are pass-through.
        expected = 100_000.0 if silver_col == "raw_sugar_world_usd_t" else 100.0
        assert df.iloc[0][silver_col] == pytest.approx(expected)


def test_sugar_unit_rule_scales_kg_to_tonne():
    df = build_silver([_bronze_all_series(values={"sugar_world_usd_kg": 0.4})])
    # 0.4 USD/kg -> 400 USD/tonne (governed x1000 rule).
    assert df.iloc[0]["raw_sugar_world_usd_t"] == pytest.approx(400.0)


def test_non_sugar_series_are_pass_through():
    df = build_silver([_bronze_all_series(values={"crude_oil_brent_usd_bbl": 82.5})])
    assert df.iloc[0]["brent_crude_usd_bbl"] == pytest.approx(82.5)


class TestBronzeRequiredSeriesGuard:
    def _headers(self, drop=None, add=None):
        # one header per required pattern (unambiguous), minus `drop`, plus any `add`.
        base = {
            "urea": "Urea", "dap": "DAP", "potassium chloride": "Potassium chloride",
            "natural gas, us": "Natural gas, US", "natural gas, europe": "Natural gas, Europe",
            "phosphate rock": "Phosphate rock", "crude oil, brent": "Crude oil, Brent",
            "soybeans": "Soybeans", "soybean oil": "Soybean oil", "soybean meal": "Soybean meal",
            "palm oil": "Palm oil", "sugar, world": "Sugar, world",
            "wheat, us hrw": "Wheat, US HRW", "wheat, us srw": "Wheat, US SRW",
            "rapeseed oil": "Rapeseed oil",
        }
        if drop:
            base.pop(drop)
        cols = list(base.values())
        if add:
            cols += add
        return cols

    def test_all_required_headers_resolve(self):
        rename = _match_columns(self._headers(), _SERIES_PATTERNS, required=_REQUIRED_SERIES)
        assert set(rename.values()) == set(_REQUIRED_SERIES)

    def test_missing_required_header_fails_closed(self):
        with pytest.raises(ValueError, match="required governed series unresolved"):
            _match_columns(self._headers(drop="crude oil, brent"), _SERIES_PATTERNS,
                           required=_REQUIRED_SERIES)

    def test_ambiguous_required_header_fails_closed(self):
        # a second "Soybeans ..." header makes the `soybeans` pattern ambiguous.
        with pytest.raises(ValueError, match="ambiguous"):
            _match_columns(self._headers(add=["Soybeans (Argentina)"]), _SERIES_PATTERNS,
                           required=_REQUIRED_SERIES)
