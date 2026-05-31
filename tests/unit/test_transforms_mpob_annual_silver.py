"""Unit tests for the MPOB overview_pdf bronze → annual silver transform.

Tests are pure Python — no S3/AWS dependencies.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from leviathan.transforms.bronze_to_silver.mpob_annual import (
    OUTPUT_COLUMNS,
    _VAR_TO_COL,
    transform_mpob_annual_bronze_to_silver,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_bronze(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal MPOB overview_pdf annual bronze EAV DataFrame."""
    defaults = {
        "year": 2015,
        "variable": "production__crude_palm_oil",
        "value": 19_961_581.0,
        "release_type": "overview_pdf",
        "source": "mpob",
        "ingest_date": "2026-05-31",
    }
    return pd.DataFrame([{**defaults, **r} for r in rows])


def _full_year_bronze(year: int, prod: float, stocks: float, exports: float,
                      imports: float, ffb: float) -> list[dict]:
    return [
        {"year": year, "variable": "production__crude_palm_oil", "value": prod},
        {"year": year, "variable": "closing_stocks__palm_oil",   "value": stocks},
        {"year": year, "variable": "exports__palm_oil",          "value": exports},
        {"year": year, "variable": "imports__palm_oil",          "value": imports},
        {"year": year, "variable": "ffb_price__ffb",             "value": ffb},
    ]


def _multi_year_bronze() -> pd.DataFrame:
    rows = []
    data = {
        2013: (18_204_537, 2_151_989, 15_874_014, 899_678, 527.0),
        2014: (19_666_020, 1_931_133, 16_513_667, 891_826, 527.0),
        2015: (19_961_581, 2_633_940, 17_454_213, 1_028_158, 459.0),
    }
    for year, (prod, stocks, exports, imports, ffb) in data.items():
        rows.extend(_full_year_bronze(year, prod, stocks, exports, imports, ffb))
    defaults = {
        "release_type": "overview_pdf",
        "source": "mpob",
        "ingest_date": "2026-05-31",
    }
    return pd.DataFrame([{**defaults, **r} for r in rows])


# ---------------------------------------------------------------------------
# Tests: constants and mapping
# ---------------------------------------------------------------------------


class TestVarToColMapping:
    def test_five_mappings(self) -> None:
        assert len(_VAR_TO_COL) == 5

    def test_production_maps_to_production_cpo_mt(self) -> None:
        assert _VAR_TO_COL["production__crude_palm_oil"] == "production_cpo_mt"

    def test_closing_stocks_maps_correctly(self) -> None:
        assert _VAR_TO_COL["closing_stocks__palm_oil"] == "closing_stocks_palm_oil_mt"

    def test_exports_maps_correctly(self) -> None:
        assert _VAR_TO_COL["exports__palm_oil"] == "exports_palm_oil_mt"

    def test_imports_maps_correctly(self) -> None:
        assert _VAR_TO_COL["imports__palm_oil"] == "imports_palm_oil_mt"

    def test_ffb_price_maps_correctly(self) -> None:
        assert _VAR_TO_COL["ffb_price__ffb"] == "ffb_price_myr_per_mt"


class TestOutputColumns:
    def test_output_columns_defined(self) -> None:
        assert len(OUTPUT_COLUMNS) == 9

    def test_year_is_first_column(self) -> None:
        assert OUTPUT_COLUMNS[0] == "year"

    def test_no_date_column(self) -> None:
        assert "date" not in OUTPUT_COLUMNS

    def test_no_month_column(self) -> None:
        assert "month" not in OUTPUT_COLUMNS

    def test_su_ratio_present(self) -> None:
        assert "su_ratio" in OUTPUT_COLUMNS

    def test_source_and_commodity_present(self) -> None:
        assert "source" in OUTPUT_COLUMNS
        assert "commodity" in OUTPUT_COLUMNS


# ---------------------------------------------------------------------------
# Tests: transform_mpob_annual_bronze_to_silver
# ---------------------------------------------------------------------------


class TestTransformMpobAnnualBronzeToSilver:
    def test_single_year_produces_one_row(self) -> None:
        df = _make_bronze(_full_year_bronze(2015, 19_961_581, 2_633_940, 17_454_213, 1_028_158, 459.0))
        result = transform_mpob_annual_bronze_to_silver(df)
        assert len(result) == 1

    def test_three_years_produces_three_rows(self) -> None:
        result = transform_mpob_annual_bronze_to_silver(_multi_year_bronze())
        assert len(result) == 3

    def test_output_columns_match(self) -> None:
        result = transform_mpob_annual_bronze_to_silver(_multi_year_bronze())
        assert list(result.columns) == OUTPUT_COLUMNS

    def test_sorted_by_year_ascending(self) -> None:
        # Feed years in reverse order
        rows = []
        for year in [2015, 2013, 2014]:
            rows.extend(_full_year_bronze(year, 1_000_000, 500_000, 800_000, 10_000, 450.0))
        defaults = {"release_type": "overview_pdf", "source": "mpob", "ingest_date": "2026-05-31"}
        df = pd.DataFrame([{**defaults, **r} for r in rows])
        result = transform_mpob_annual_bronze_to_silver(df)
        assert list(result["year"]) == [2013, 2014, 2015]

    def test_production_value_correct(self) -> None:
        df = _make_bronze(_full_year_bronze(2015, 19_961_581, 2_633_940, 17_454_213, 1_028_158, 459.0))
        result = transform_mpob_annual_bronze_to_silver(df)
        assert result.iloc[0]["production_cpo_mt"] == pytest.approx(19_961_581.0)

    def test_su_ratio_computed_correctly(self) -> None:
        # stocks=2,633,940 / exports=17,454,213 ≈ 0.1509
        df = _make_bronze(_full_year_bronze(2015, 19_961_581, 2_633_940, 17_454_213, 1_028_158, 459.0))
        result = transform_mpob_annual_bronze_to_silver(df)
        expected = 2_633_940.0 / 17_454_213.0
        assert result.iloc[0]["su_ratio"] == pytest.approx(expected)

    def test_su_ratio_null_when_exports_zero(self) -> None:
        df = _make_bronze(_full_year_bronze(2015, 1_000_000, 500_000, 0.0, 10_000, 450.0))
        result = transform_mpob_annual_bronze_to_silver(df)
        assert math.isnan(result.iloc[0]["su_ratio"])

    def test_source_is_mpob(self) -> None:
        result = transform_mpob_annual_bronze_to_silver(_multi_year_bronze())
        assert (result["source"] == "mpob").all()

    def test_commodity_is_malaysian_crude_palm_oil_cme(self) -> None:
        result = transform_mpob_annual_bronze_to_silver(_multi_year_bronze())
        assert (result["commodity"] == "malaysian_crude_palm_oil_cme").all()

    def test_missing_required_column_raises(self) -> None:
        df = _multi_year_bronze().drop(columns=["year"])
        with pytest.raises(ValueError, match="missing columns"):
            transform_mpob_annual_bronze_to_silver(df)

    def test_empty_on_no_matching_variables(self) -> None:
        df = _make_bronze([{"variable": "unknown__variable", "value": 999.0}])
        result = transform_mpob_annual_bronze_to_silver(df)
        assert result.empty
        assert list(result.columns) == OUTPUT_COLUMNS

    def test_deduplicates_on_year_variable(self) -> None:
        # Two rows for the same (year, variable) → should keep only one
        row1 = {"year": 2015, "variable": "production__crude_palm_oil", "value": 19_961_581.0}
        row2 = {"year": 2015, "variable": "production__crude_palm_oil", "value": 99_999_999.0}
        # Fill in the other 4 variables once each
        other_rows = _full_year_bronze(2015, 0, 500_000, 800_000, 10_000, 450.0)[1:]  # skip prod
        defaults = {"release_type": "overview_pdf", "source": "mpob", "ingest_date": "2026-05-31"}
        all_rows = [row1, row2] + other_rows
        df = pd.DataFrame([{**defaults, **r} for r in all_rows])
        result = transform_mpob_annual_bronze_to_silver(df)
        assert len(result) == 1
        assert result.iloc[0]["production_cpo_mt"] == pytest.approx(19_961_581.0)  # first wins

    def test_missing_variable_produces_nan_column(self) -> None:
        # Omit ffb_price__ffb → ffb_price_myr_per_mt should be NaN
        rows = _full_year_bronze(2015, 19_961_581, 2_633_940, 17_454_213, 1_028_158, 459.0)
        rows = [r for r in rows if r["variable"] != "ffb_price__ffb"]
        defaults = {"release_type": "overview_pdf", "source": "mpob", "ingest_date": "2026-05-31"}
        df = pd.DataFrame([{**defaults, **r} for r in rows])
        result = transform_mpob_annual_bronze_to_silver(df)
        assert math.isnan(result.iloc[0]["ffb_price_myr_per_mt"])
