"""Unit tests for the ESR bronze → silver transform.

Tests are pure Python — no S3/AWS dependencies.
The transform function is called with pre-built DataFrames that mimic what the
bronze Parquet loader returns from real S3 data (probe-verified 2026-05-24).

Actual bronze schema (11 cols):
  commodity_code (Int16), country_code (Int16), week_ending_date (date),
  outstanding_sales (float32), weekly_exports (float32),
  gross_new_sales (float32), unit_id (Int16), changes (float32),
  as_of_date (str), ingest_date (str), source (str)

Silver adds: commodity_name (str), market_year (Int16)
Silver renames quantity cols with _1000mt suffix and renames unit_id → source_unit_id.
"""
from __future__ import annotations

import datetime

import pandas as pd
import pytest
from leviathan.transforms.bronze_to_silver.usda_esr import transform_esr_bronze_to_silver

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MARKET_YEAR = 2024


def _make_bronze_df(**overrides) -> pd.DataFrame:
    """Return a minimal two-row bronze ESR DataFrame."""
    data = {
        "commodity_code":   pd.array([401, 401], dtype="Int16"),
        "country_code":     pd.array([1220, 351], dtype="Int16"),
        "week_ending_date": [datetime.date(2024, 9, 12), datetime.date(2024, 9, 19)],
        "outstanding_sales": pd.array([50000.0, 120000.0], dtype="float32"),
        "weekly_exports":    pd.array([25000.0, 60000.0], dtype="float32"),
        "gross_new_sales":   pd.array([30000.0, 80000.0], dtype="float32"),
        "changes":           pd.array([0.0, 500.0], dtype="float32"),
        "unit_id":           pd.array([1, 1], dtype="Int16"),
        "as_of_date":        ["20260524", "20260524"],
        "ingest_date":       ["2026-05-24", "2026-05-24"],
        "source":            ["usda_esr", "usda_esr"],
    }
    data.update(overrides)
    return pd.DataFrame(data)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_returns_dataframe(self) -> None:
        df = transform_esr_bronze_to_silver(_make_bronze_df(), MARKET_YEAR)
        assert isinstance(df, pd.DataFrame)

    def test_row_count_preserved(self) -> None:
        bronze = _make_bronze_df()
        silver = transform_esr_bronze_to_silver(bronze, MARKET_YEAR)
        assert len(silver) == len(bronze)

    def test_commodity_name_corn(self) -> None:
        silver = transform_esr_bronze_to_silver(_make_bronze_df(), MARKET_YEAR)
        assert (silver["commodity_name"] == "corn_cbot").all()

    def test_market_year_column_added(self) -> None:
        silver = transform_esr_bronze_to_silver(_make_bronze_df(), MARKET_YEAR)
        assert "market_year" in silver.columns
        assert (silver["market_year"] == MARKET_YEAR).all()

    def test_unit_conversion_weekly_exports(self) -> None:
        """25,000 MT ÷ 1000 = 25.0 (1000 MT)."""
        silver = transform_esr_bronze_to_silver(_make_bronze_df(), MARKET_YEAR)
        assert "weekly_exports_1000mt" in silver.columns
        assert abs(float(silver["weekly_exports_1000mt"].iloc[0]) - 25.0) < 0.01

    def test_unit_conversion_outstanding_sales(self) -> None:
        """50,000 MT ÷ 1000 = 50.0 (1000 MT)."""
        silver = transform_esr_bronze_to_silver(_make_bronze_df(), MARKET_YEAR)
        assert abs(float(silver["outstanding_sales_1000mt"].iloc[0]) - 50.0) < 0.01

    def test_original_quantity_cols_dropped(self) -> None:
        silver = transform_esr_bronze_to_silver(_make_bronze_df(), MARKET_YEAR)
        for col in ("outstanding_sales", "weekly_exports", "gross_new_sales", "changes"):
            assert col not in silver.columns

    def test_unit_id_renamed_to_source_unit_id(self) -> None:
        silver = transform_esr_bronze_to_silver(_make_bronze_df(), MARKET_YEAR)
        assert "unit_id" not in silver.columns
        assert "source_unit_id" in silver.columns

    def test_1000mt_columns_are_float32(self) -> None:
        silver = transform_esr_bronze_to_silver(_make_bronze_df(), MARKET_YEAR)
        for col in silver.columns:
            if col.endswith("_1000mt"):
                assert silver[col].dtype == "float32", f"{col} should be float32"

    def test_output_column_order(self) -> None:
        silver = transform_esr_bronze_to_silver(_make_bronze_df(), MARKET_YEAR)
        cols = list(silver.columns)
        assert cols[0] == "commodity_code"
        assert cols[1] == "commodity_name"
        assert cols[2] == "market_year"
        assert cols[3] == "country_code"
        assert cols[4] == "week_ending_date"

    def test_metadata_cols_preserved(self) -> None:
        silver = transform_esr_bronze_to_silver(_make_bronze_df(), MARKET_YEAR)
        assert silver["as_of_date"].iloc[0] == "20260524"
        assert silver["ingest_date"].iloc[0] == "2026-05-24"
        assert silver["source"].iloc[0] == "usda_esr"


# ---------------------------------------------------------------------------
# Commodity name mapping
# ---------------------------------------------------------------------------

class TestCommodityNameMapping:
    @pytest.mark.parametrize("code,expected_name", [
        (101, "hard_red_winter_wheat_kcbt"),
        (102, "soft_red_winter_wheat_cbot"),
        (103, "hard_red_spring_wheat_mgex"),
        (104, "white_wheat"),
        (107, "all_wheat"),
        (401, "corn_cbot"),
        (701, "grain_sorghum"),
        (801, "soybeans_cbot"),
        (901, "soybean_meal_cbot"),
        (902, "soybean_oil_cbot"),
    ])
    def test_known_code_maps_correctly(self, code: int, expected_name: str) -> None:
        bronze = _make_bronze_df(
            commodity_code=pd.array([code], dtype="Int16"),
            country_code=pd.array([351], dtype="Int16"),
            week_ending_date=[datetime.date(2024, 9, 12)],
            outstanding_sales=pd.array([1000.0], dtype="float32"),
            weekly_exports=pd.array([500.0], dtype="float32"),
            gross_new_sales=pd.array([600.0], dtype="float32"),
            changes=pd.array([0.0], dtype="float32"),
            unit_id=pd.array([1], dtype="Int16"),
            as_of_date=["20260524"],
            ingest_date=["2026-05-24"],
            source=["usda_esr"],
        )
        silver = transform_esr_bronze_to_silver(bronze, MARKET_YEAR)
        assert silver["commodity_name"].iloc[0] == expected_name

    def test_unknown_code_becomes_unknown(self) -> None:
        """Commodity code not in the mapping → 'unknown' (no raise)."""
        bronze = _make_bronze_df(
            commodity_code=pd.array([999], dtype="Int16"),
            country_code=pd.array([351], dtype="Int16"),
            week_ending_date=[datetime.date(2024, 9, 12)],
            outstanding_sales=pd.array([1000.0], dtype="float32"),
            weekly_exports=pd.array([500.0], dtype="float32"),
            gross_new_sales=pd.array([600.0], dtype="float32"),
            changes=pd.array([0.0], dtype="float32"),
            unit_id=pd.array([1], dtype="Int16"),
            as_of_date=["20260524"],
            ingest_date=["2026-05-24"],
            source=["usda_esr"],
        )
        silver = transform_esr_bronze_to_silver(bronze, MARKET_YEAR)
        assert silver["commodity_name"].iloc[0] == "unknown"


# ---------------------------------------------------------------------------
# Unit conversion edge cases
# ---------------------------------------------------------------------------

class TestUnitConversion:
    def test_known_unit_id_applies_factor(self) -> None:
        """1,000,000 MT × 0.001 = 1,000.0 (1000 MT)."""
        bronze = _make_bronze_df(
            weekly_exports=pd.array([1_000_000.0], dtype="float32"),
            commodity_code=pd.array([401], dtype="Int16"),
            country_code=pd.array([351], dtype="Int16"),
            week_ending_date=[datetime.date(2024, 9, 12)],
            outstanding_sales=pd.array([0.0], dtype="float32"),
            gross_new_sales=pd.array([0.0], dtype="float32"),
            changes=pd.array([0.0], dtype="float32"),
            unit_id=pd.array([1], dtype="Int16"),
            as_of_date=["20260524"],
            ingest_date=["2026-05-24"],
            source=["usda_esr"],
        )
        silver = transform_esr_bronze_to_silver(bronze, MARKET_YEAR)
        assert abs(float(silver["weekly_exports_1000mt"].iloc[0]) - 1000.0) < 0.1

    def test_unknown_unit_id_raises(self) -> None:
        """unit_id not in _UNIT_TO_1000MT_FACTOR must raise ValueError."""
        bronze = _make_bronze_df(
            unit_id=pd.array([99, 99], dtype="Int16"),
        )
        with pytest.raises(ValueError, match="unrecognised unit_id"):
            transform_esr_bronze_to_silver(bronze, MARKET_YEAR)


# ---------------------------------------------------------------------------
# Null / empty handling
# ---------------------------------------------------------------------------

class TestNullHandling:
    def test_null_week_ending_date_rows_dropped(self) -> None:
        bronze = _make_bronze_df()
        bronze.loc[0, "week_ending_date"] = None
        silver = transform_esr_bronze_to_silver(bronze, MARKET_YEAR)
        assert len(silver) == 1

    def test_missing_required_column_raises(self) -> None:
        bronze = _make_bronze_df().drop(columns=["unit_id"])
        with pytest.raises(ValueError, match="missing required columns"):
            transform_esr_bronze_to_silver(bronze, MARKET_YEAR)


# ---------------------------------------------------------------------------
# SILVER-F030 ADR: changes_1000mt is deprecated + never synthesized (INV-4)
# ---------------------------------------------------------------------------

class TestChangesNeverSynthesized:
    def test_null_bronze_changes_stays_null_in_silver(self) -> None:
        """A null bronze 'changes' propagates to a null 'changes_1000mt' -- never 0.0 (INV-4)."""
        import numpy as np
        bronze = _make_bronze_df(
            changes=pd.array([np.nan, 500.0], dtype="float32"),
        )
        silver = transform_esr_bronze_to_silver(bronze, MARKET_YEAR)
        assert silver["changes_1000mt"].isna().sum() == 1
        # the present revision survives its unit conversion (500 MT -> 0.5 kMT).
        assert abs(float(silver["changes_1000mt"].dropna().iloc[0]) - 0.5) < 1e-6

    def test_all_null_changes_stays_all_null(self) -> None:
        import numpy as np
        bronze = _make_bronze_df(
            changes=pd.array([np.nan, np.nan], dtype="float32"),
        )
        silver = transform_esr_bronze_to_silver(bronze, MARKET_YEAR)
        assert silver["changes_1000mt"].isna().all()
        assert (silver["changes_1000mt"] == 0.0).sum() == 0


# ---------------------------------------------------------------------------
# SILVER-F030 ADR: ending-year market-year convention (stored = FAS start year)
# ---------------------------------------------------------------------------

class TestMarketYearConvention:
    def test_stored_market_year_is_the_start_year_param(self) -> None:
        """The stored market_year is the FAS START year passed in; the numbers layer derives the
        ending-year label as market_year+1 (period_offset:+1). The transform never fabricates a
        next marketing year."""
        silver = transform_esr_bronze_to_silver(_make_bronze_df(), 2023)
        assert (silver["market_year"] == 2023).all()
        # no next-MY (2024) row is synthesized from the 2023 bronze frame.
        assert set(silver["market_year"].unique()) == {2023}

    def test_usda_grouping_codes_stay_source_faithful(self) -> None:
        """USDA grouping codes (all_wheat=107, grain_sorghum=701, white_wheat=104) are NOT contract
        slugs but the canonical transform still maps them (source-faithful); the esr_exports slug
        boundary is enforced downstream, not by dropping rows here."""
        for code, name in ((107, "all_wheat"), (701, "grain_sorghum"), (104, "white_wheat")):
            bronze = _make_bronze_df(
                commodity_code=pd.array([code, code], dtype="Int16"),
            )
            silver = transform_esr_bronze_to_silver(bronze, MARKET_YEAR)
            assert (silver["commodity_name"] == name).all()
