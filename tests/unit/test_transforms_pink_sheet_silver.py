"""Unit tests for Pink Sheet bronze → silver transforms."""
from __future__ import annotations

import math
from datetime import date

import pandas as pd
import pytest
from leviathan.transforms.bronze_to_silver.pink_sheet import (
    _NPK_COLS,
    _SERIES_RENAME,
    _ZSCORE_VALID_FROM,
    SILVER_COLUMNS,
    build_silver,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ALL_SERIES = list(_SERIES_RENAME.keys())


def _make_bronze_row(
    d: str,
    series_name: str,
    value_usd: float | None,
    release_ym: str = "2026M05",
) -> dict:
    return {
        "date": date.fromisoformat(d),
        "series_name": series_name,
        "value_usd": float(value_usd) if value_usd is not None else float("nan"),
        "release_ym": release_ym,
        "source": "world_bank_pink_sheet",
    }


def _make_full_month(
    d: str,
    release_ym: str = "2026M05",
    urea: float = 400.0,
    dap: float = 600.0,
    potassium: float = 350.0,
    gas_us: float = 3.5,
    gas_eu: float = 10.0,
    phosphate: float = 150.0,
) -> list[dict]:
    """Return 6 bronze rows (one complete month) with all series populated."""
    values = {
        "urea_e_europe_bulk_spot_usd_mt":  urea,
        "dap_spot_usd_mt":                 dap,
        "potassium_chloride_std_usd_mt":   potassium,
        "natural_gas_us_usd_mmbtu":        gas_us,
        "natural_gas_europe_usd_mmbtu":    gas_eu,
        "phosphate_rock_usd_mt":           phosphate,
    }
    return [_make_bronze_row(d, s, v, release_ym) for s, v in values.items()]


def _months_df(start: str, n: int, release_ym: str = "2026M05") -> pd.DataFrame:
    """Build a DataFrame of n consecutive months (starting at 'start') with
    all 6 series populated, using varying values so rolling std is non-zero."""
    rows: list[dict] = []
    yr, mo = int(start[:4]), int(start[5:7])
    for i in range(n):
        d = date(yr, mo, 1).isoformat()
        rows.extend(_make_full_month(
            d, release_ym,
            urea=float(100 + i),
            dap=float(300 + i * 2),
            potassium=float(200 + i),
            gas_us=float(2.0 + i * 0.05),
            gas_eu=float(5.0 + i * 0.1),
            phosphate=float(80 + i * 0.5),
        ))
        mo += 1
        if mo > 12:
            mo = 1
            yr += 1
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# TestDedup
# ---------------------------------------------------------------------------

class TestDedup:
    def test_keeps_latest_release(self):
        """When two releases cover the same date, the newer one wins."""
        old_rows = _make_full_month("2026-01-01", release_ym="2026M01", urea=300.0)
        new_rows = _make_full_month("2026-01-01", release_ym="2026M05", urea=420.0)
        df = build_silver([pd.DataFrame(old_rows), pd.DataFrame(new_rows)])
        row = df[df["date"] == pd.Timestamp("2026-01-01")]
        assert len(row) == 1
        assert row.iloc[0]["urea_usd_mt"] == pytest.approx(420.0)

    def test_does_not_lose_dates_only_in_older_release(self):
        """Dates present only in the older release must survive dedup."""
        old_rows = (
            _make_full_month("2025-12-01", release_ym="2025M12")
            + _make_full_month("2026-01-01", release_ym="2025M12")
        )
        new_rows = _make_full_month("2026-01-01", release_ym="2026M01")
        df = build_silver([pd.DataFrame(old_rows), pd.DataFrame(new_rows)])
        dates = set(df["date"].dt.date)
        assert date(2025, 12, 1) in dates
        assert date(2026, 1, 1) in dates

    def test_single_release_produces_correct_row_count(self):
        """Single-release path: one row per date."""
        rows: list[dict] = []
        for m in range(1, 4):
            rows.extend(_make_full_month(f"2026-0{m}-01"))
        df = build_silver([pd.DataFrame(rows)])
        assert len(df) == 3


# ---------------------------------------------------------------------------
# TestPivotAndRename
# ---------------------------------------------------------------------------

class TestPivotAndRename:
    def _silver(self) -> pd.DataFrame:
        rows = _make_full_month("2026-01-01")
        return build_silver([pd.DataFrame(rows)])

    def test_pivot_produces_6_value_columns(self):
        df = self._silver()
        for silver_col in _SERIES_RENAME.values():
            assert silver_col in df.columns, f"Missing column: {silver_col}"

    def test_column_renaming_applied(self):
        df = self._silver()
        # Names that differ between bronze and silver must not appear as bronze names.
        for bronze_name, silver_name in _SERIES_RENAME.items():
            if bronze_name != silver_name:
                assert bronze_name not in df.columns, f"Bronze name leaked: {bronze_name}"
            assert silver_name in df.columns, f"Silver name missing: {silver_name}"

    def test_natural_gas_eu_renamed(self):
        df = self._silver()
        assert "natural_gas_eu_usd_mmbtu" in df.columns
        assert "natural_gas_europe_usd_mmbtu" not in df.columns

    def test_no_duplicate_dates(self):
        rows: list[dict] = []
        for m in range(1, 4):
            rows.extend(_make_full_month(f"2026-0{m}-01"))
        df = build_silver([pd.DataFrame(rows)])
        assert df["date"].duplicated().sum() == 0


# ---------------------------------------------------------------------------
# TestDateDerivation
# ---------------------------------------------------------------------------

class TestDateDerivation:
    def test_year_month_derived(self):
        rows = _make_full_month("1967-03-01")
        df = build_silver([pd.DataFrame(rows)])
        row = df.iloc[0]
        assert row["year"] == 1967
        assert row["month"] == 3

    def test_date_is_datetime64(self):
        rows = _make_full_month("2026-01-01")
        df = build_silver([pd.DataFrame(rows)])
        assert pd.api.types.is_datetime64_any_dtype(df["date"])


# ---------------------------------------------------------------------------
# TestBlendedNPKIndex
# ---------------------------------------------------------------------------

class TestBlendedNPKIndex:
    def test_equal_weight_calculation(self):
        rows = _make_full_month("2026-01-01", urea=300.0, dap=600.0, potassium=300.0)
        df = build_silver([pd.DataFrame(rows)])
        assert df.iloc[0]["blended_npk_index"] == pytest.approx(400.0)

    def test_nan_when_dap_null(self):
        """Pre-1967 months have no DAP data; blended_npk_index must be NaN."""
        rows = [
            _make_bronze_row("1960-01-01", "urea_e_europe_bulk_spot_usd_mt", 50.0),
            _make_bronze_row("1960-01-01", "dap_spot_usd_mt", None),          # NaN
            _make_bronze_row("1960-01-01", "potassium_chloride_std_usd_mt", 25.0),
            _make_bronze_row("1960-01-01", "natural_gas_us_usd_mmbtu", 0.2),
            _make_bronze_row("1960-01-01", "natural_gas_europe_usd_mmbtu", 0.4),
            _make_bronze_row("1960-01-01", "phosphate_rock_usd_mt", 12.0),
        ]
        df = build_silver([pd.DataFrame(rows)])
        assert math.isnan(df.iloc[0]["blended_npk_index"])

    def test_not_nan_when_all_components_present(self):
        rows = _make_full_month("2026-01-01", urea=400.0, dap=600.0, potassium=350.0)
        df = build_silver([pd.DataFrame(rows)])
        assert not math.isnan(df.iloc[0]["blended_npk_index"])


# ---------------------------------------------------------------------------
# TestZScores
# ---------------------------------------------------------------------------

class TestZScores:
    def test_zscore_columns_present(self):
        df = _months_df("2020-01", 12)
        result = build_silver([df])
        for col in _SERIES_RENAME.values():
            assert f"{col}_zscore_5yr" in result.columns
        assert "blended_npk_index_zscore_5yr" in result.columns

    def test_zscore_nulled_before_valid_from(self):
        """nat gas EU z-score must be NaN for years before 1991."""
        # Build 60+ months ending in 1990 so the rolling window is saturated
        # but all dates are before the 1991 floor.
        df = _months_df("1985-01", 72)  # 1985-01 → 1990-12
        result = build_silver([df])
        z_col = "natural_gas_eu_usd_mmbtu_zscore_5yr"
        assert result[z_col].isna().all(), (
            "Expected all z-scores before 1991 to be NaN for nat gas EU"
        )

    def test_zscore_not_null_after_valid_from_with_enough_data(self):
        """nat gas EU z-score should be non-NaN once past the floor with
        enough history (min_periods=36)."""
        # 36 months starting 1991-01 → last date is 1994-01 (past min_periods)
        df = _months_df("1991-01", 40)
        result = build_silver([df])
        z_col = "natural_gas_eu_usd_mmbtu_zscore_5yr"
        # Last rows (with 36+ in window) should be non-NaN
        tail = result.tail(5)
        assert tail[z_col].notna().any(), (
            "Expected non-NaN z-scores after 1991 with ≥36 months"
        )

    def test_zscore_nan_below_min_periods(self):
        """Within-valid-from period but fewer than 36 months → NaN z-score."""
        df = _months_df("1991-01", 10)   # only 10 months, below min_periods=36
        result = build_silver([df])
        z_col = "natural_gas_eu_usd_mmbtu_zscore_5yr"
        assert result[z_col].isna().all()

    def test_phosphate_zscore_valid_from_1960(self):
        """Phosphate floor is 1960, so z-scores should not be blanket-nulled."""
        df = _months_df("1960-01", 40)
        result = build_silver([df])
        z_col = "phosphate_rock_usd_mt_zscore_5yr"
        # Some rows will be NaN (below min_periods), but the column must exist
        # and not be entirely masked by the valid-from logic.
        # With 40 rows, the last few should have valid z-scores.
        tail = result.tail(5)
        assert tail[z_col].notna().any()


# ---------------------------------------------------------------------------
# TestLatestReleaseYm
# ---------------------------------------------------------------------------

class TestLatestReleaseYm:
    def test_latest_release_ym_column_present(self):
        df = build_silver([pd.DataFrame(_make_full_month("2026-01-01"))])
        assert "latest_release_ym" in df.columns

    def test_latest_release_ym_correct_single_release(self):
        df = build_silver([pd.DataFrame(_make_full_month("2026-01-01", release_ym="2026M05"))])
        assert df.iloc[0]["latest_release_ym"] == "2026M05"

    def test_latest_release_ym_reflects_newer_release(self):
        old = pd.DataFrame(_make_full_month("2026-01-01", release_ym="2026M01"))
        new = pd.DataFrame(_make_full_month("2026-01-01", release_ym="2026M05"))
        df = build_silver([old, new])
        row = df[df["date"] == pd.Timestamp("2026-01-01")]
        assert row.iloc[0]["latest_release_ym"] == "2026M05"


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_input_returns_empty(self):
        df = build_silver([])
        assert list(df.columns) == SILVER_COLUMNS
        assert len(df) == 0

    def test_empty_dataframe_in_list(self):
        df = build_silver([pd.DataFrame(columns=["date", "series_name", "value_usd", "release_ym", "source"])])
        assert list(df.columns) == SILVER_COLUMNS
        assert len(df) == 0

    def test_silver_columns_exact_and_ordered(self):
        rows = _make_full_month("2026-01-01")
        df = build_silver([pd.DataFrame(rows)])
        assert list(df.columns) == SILVER_COLUMNS
