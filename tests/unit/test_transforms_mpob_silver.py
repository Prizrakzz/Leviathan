"""Unit tests for the MPOB bronze → silver transform.

Tests are pure Python — no S3/AWS dependencies.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest
from leviathan.transforms.bronze_to_silver.mpob import (
    _VAR_TO_COL,
    OUTPUT_COLUMNS,
    transform_mpob_bronze_to_silver,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_bronze(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal MPOB annual_summary bronze EAV DataFrame."""
    defaults = {
        "year": 2024,
        "month": 1,
        "variable": "production__crude_palm_oil",
        "value": 1_500_000.0,
        "release_type": "annual_summary",
        "source": "mpob",
        "ingest_date": "2024-06-01",
    }
    return pd.DataFrame([{**defaults, **r} for r in rows])


def _three_month_bronze() -> pd.DataFrame:
    """Three months (Jan–Mar 2024) with all five key variables."""
    rows = []
    data = {
        1: {"production__crude_palm_oil": 1_400_000, "closing_stocks__palm_oil": 1_900_000,
            "exports__palm_oil": 1_100_000, "imports__palm_oil": 11_000,
            "ffb_price__ffb": 41.0},
        2: {"production__crude_palm_oil": 1_300_000, "closing_stocks__palm_oil": 1_800_000,
            "exports__palm_oil": 1_200_000, "imports__palm_oil": 12_000,
            "ffb_price__ffb": 39.5},
        3: {"production__crude_palm_oil": 1_500_000, "closing_stocks__palm_oil": 2_000_000,
            "exports__palm_oil": 1_300_000, "imports__palm_oil": 13_000,
            "ffb_price__ffb": 43.0},
    }
    for month, vars_ in data.items():
        for var, val in vars_.items():
            rows.append({"year": 2024, "month": month, "variable": var, "value": val})
    return _make_bronze(rows)


# ---------------------------------------------------------------------------
# Tests: constants and mapping
# ---------------------------------------------------------------------------


class TestVarToColMapping:
    def test_five_mappings(self) -> None:
        assert len(_VAR_TO_COL) == 5

    def test_production_mapping(self) -> None:
        assert _VAR_TO_COL["production__crude_palm_oil"] == "production_cpo_mt"

    def test_closing_stocks_mapping(self) -> None:
        assert _VAR_TO_COL["closing_stocks__palm_oil"] == "closing_stocks_palm_oil_mt"

    def test_exports_mapping(self) -> None:
        assert _VAR_TO_COL["exports__palm_oil"] == "exports_palm_oil_mt"

    def test_imports_mapping(self) -> None:
        assert _VAR_TO_COL["imports__palm_oil"] == "imports_palm_oil_mt"

    def test_ffb_price_mapping(self) -> None:
        assert _VAR_TO_COL["ffb_price__ffb"] == "ffb_price_myr_per_mt"


class TestOutputColumns:
    def test_nine_columns(self) -> None:
        assert len(OUTPUT_COLUMNS) == 9

    def test_date_first(self) -> None:
        assert OUTPUT_COLUMNS[0] == "date"

    def test_metadata_last(self) -> None:
        assert OUTPUT_COLUMNS[-1] == "commodity"
        assert OUTPUT_COLUMNS[-2] == "source"

    def test_su_ratio_present(self) -> None:
        assert "su_ratio" in OUTPUT_COLUMNS


# ---------------------------------------------------------------------------
# Tests: transform behaviour
# ---------------------------------------------------------------------------


class TestTransformMpobBronzeToSilver:
    @pytest.fixture()
    def silver(self) -> pd.DataFrame:
        return transform_mpob_bronze_to_silver(_three_month_bronze())

    def test_returns_dataframe(self, silver: pd.DataFrame) -> None:
        assert isinstance(silver, pd.DataFrame)

    def test_three_rows(self, silver: pd.DataFrame) -> None:
        assert len(silver) == 3

    def test_output_columns(self, silver: pd.DataFrame) -> None:
        assert list(silver.columns) == OUTPUT_COLUMNS

    def test_date_format(self, silver: pd.DataFrame) -> None:
        """Date should be ISO YYYY-MM-DD first-of-month strings."""
        assert set(silver["date"]) == {"2024-01-01", "2024-02-01", "2024-03-01"}

    def test_sorted_by_date(self, silver: pd.DataFrame) -> None:
        assert list(silver["date"]) == sorted(silver["date"])

    def test_production_cpo_jan(self, silver: pd.DataFrame) -> None:
        row = silver[silver["date"] == "2024-01-01"]
        assert row["production_cpo_mt"].iloc[0] == pytest.approx(1_400_000.0)

    def test_closing_stocks_feb(self, silver: pd.DataFrame) -> None:
        row = silver[silver["date"] == "2024-02-01"]
        assert row["closing_stocks_palm_oil_mt"].iloc[0] == pytest.approx(1_800_000.0)

    def test_su_ratio_jan(self, silver: pd.DataFrame) -> None:
        """su_ratio = closing_stocks / exports = 1_900_000 / 1_100_000."""
        row = silver[silver["date"] == "2024-01-01"]
        expected = 1_900_000 / 1_100_000
        assert row["su_ratio"].iloc[0] == pytest.approx(expected, rel=1e-4)

    def test_su_ratio_no_nulls(self, silver: pd.DataFrame) -> None:
        assert silver["su_ratio"].isna().sum() == 0

    def test_source_column(self, silver: pd.DataFrame) -> None:
        assert (silver["source"] == "mpob").all()

    def test_commodity_column(self, silver: pd.DataFrame) -> None:
        assert (silver["commodity"] == "malaysian_crude_palm_oil_cme").all()

    def test_ffb_price_present(self, silver: pd.DataFrame) -> None:
        row = silver[silver["date"] == "2024-03-01"]
        assert row["ffb_price_myr_per_mt"].iloc[0] == pytest.approx(43.0)


class TestTransformDeduplication:
    def test_cross_year_overlap_deduplicated(self) -> None:
        """Dec 2023 appearing twice (from year=2023 and year=2024 files) is deduped."""
        dec23_a = {"year": 2023, "month": 12, "variable": "production__crude_palm_oil",
                   "value": 1_500_000.0}
        dec23_b = {"year": 2023, "month": 12, "variable": "production__crude_palm_oil",
                   "value": 1_500_000.0}
        # Add the other required variables to avoid missing-column issues.
        extras = [
            {"year": 2023, "month": 12, "variable": "closing_stocks__palm_oil", "value": 2_000_000.0},
            {"year": 2023, "month": 12, "variable": "exports__palm_oil", "value": 1_100_000.0},
            {"year": 2023, "month": 12, "variable": "imports__palm_oil", "value": 10_000.0},
            {"year": 2023, "month": 12, "variable": "ffb_price__ffb", "value": 40.0},
        ]
        df = _make_bronze([dec23_a, dec23_b] + extras)
        silver = transform_mpob_bronze_to_silver(df)
        assert len(silver) == 1
        assert silver["date"].iloc[0] == "2023-12-01"


class TestTransformEdgeCases:
    def test_missing_required_column_raises(self) -> None:
        df = _make_bronze([{}]).drop(columns=["variable"])
        with pytest.raises(ValueError, match="missing columns"):
            transform_mpob_bronze_to_silver(df)

    def test_no_matching_variables_returns_empty(self) -> None:
        df = _make_bronze([{"variable": "unrelated__col", "value": 1.0}])
        silver = transform_mpob_bronze_to_silver(df)
        assert silver.empty

    def test_su_ratio_null_when_exports_zero(self) -> None:
        rows = [
            {"variable": "production__crude_palm_oil", "value": 1_000_000.0},
            {"variable": "closing_stocks__palm_oil", "value": 500_000.0},
            {"variable": "exports__palm_oil", "value": 0.0},
            {"variable": "imports__palm_oil", "value": 5_000.0},
            {"variable": "ffb_price__ffb", "value": 40.0},
        ]
        df = _make_bronze(rows)
        silver = transform_mpob_bronze_to_silver(df)
        assert len(silver) == 1
        assert math.isnan(silver["su_ratio"].iloc[0])
