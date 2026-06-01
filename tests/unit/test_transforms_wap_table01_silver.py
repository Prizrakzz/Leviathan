"""Unit tests for WAP Table 01 silver transforms.

Tests are grouped by function:
    TestNormalizeRowLabel   — normalize_row_label (4 tests)
    TestParseRowLabel       — parse_row_label (6 tests)
    TestDeriveMarketingYear — _derive_marketing_year_for_months (4 tests)
    TestMeltToLong          — melt_to_long (5 tests)
    TestBuildLongTable      — build_long_table integration (3 tests)
    TestBuildRevisionTable  — build_revision_table (6 tests)
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from leviathan.transforms.bronze_to_silver.wap_table01 import (
    MODERN_COUNTRY_COLUMNS,
    REVISION_COLUMNS,
    SILVER_COLUMNS,
    _derive_marketing_year_for_months,
    build_long_table,
    build_revision_table,
    melt_to_long,
    normalize_row_label,
    parse_row_label,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_bronze_row(
    release_month: str = "2024-05",
    commodity: str = "wheat",
    row_label: str = "2024/25 proj.",
    **country_values,
) -> dict:
    """Minimal bronze row with all modern country cols defaulting to 0."""
    row: dict = {"release_month": release_month, "commodity": commodity, "row_label": row_label}
    for col in MODERN_COUNTRY_COLUMNS:
        row[col] = country_values.get(col, 0.0)
    return row


def _make_bronze_df(*rows) -> pd.DataFrame:
    """Build a DataFrame from dicts returned by _make_bronze_row."""
    return pd.DataFrame(list(rows))


# ---------------------------------------------------------------------------
# TestNormalizeRowLabel
# ---------------------------------------------------------------------------

class TestNormalizeRowLabel:
    def test_july_normalized(self):
        assert normalize_row_label("July") == "Jul"

    def test_aug_period_normalized(self):
        assert normalize_row_label("Aug.") == "Aug"

    def test_jan_unchanged(self):
        assert normalize_row_label("Jan") == "Jan"

    def test_noise_unchanged(self):
        assert normalize_row_label("Oilseeds 2/") == "Oilseeds 2/"


# ---------------------------------------------------------------------------
# TestParseRowLabel
# ---------------------------------------------------------------------------

class TestParseRowLabel:
    def test_year_prel(self):
        result = parse_row_label("2023/24 prel.")
        assert result["vintage_type"] == "year"
        assert result["marketing_year"] == "2023/24"
        assert result["vintage_status"] == "prel."
        assert result["month_abbr"] is None

    def test_year_proj(self):
        result = parse_row_label("2024/25 proj.")
        assert result["vintage_type"] == "year"
        assert result["marketing_year"] == "2024/25"
        assert result["vintage_status"] == "proj."

    def test_bare_year(self):
        # e.g. "2001/02" with no status suffix
        result = parse_row_label("2001/02")
        assert result["vintage_type"] == "year"
        assert result["marketing_year"] == "2001/02"
        assert result["vintage_status"] == ""

    def test_month_jan(self):
        result = parse_row_label("Jan")
        assert result["vintage_type"] == "month"
        assert result["month_abbr"] == "Jan"
        assert result["marketing_year"] is None

    def test_month_jul(self):
        result = parse_row_label("Jul")
        assert result["vintage_type"] == "month"
        assert result["month_abbr"] == "Jul"

    def test_noise(self):
        result = parse_row_label("Oilseeds 2/")
        assert result["vintage_type"] == "noise"
        assert result["marketing_year"] is None
        assert result["month_abbr"] is None


# ---------------------------------------------------------------------------
# TestDeriveMarketingYear
# ---------------------------------------------------------------------------

class TestDeriveMarketingYear:
    def _base_df(self) -> pd.DataFrame:
        """Two-row df: one proj. year row + one month row for wheat/2024-05."""
        rows = [
            {
                "release_month": "2024-05",
                "commodity": "wheat",
                "row_label": "2024/25 proj.",
                "vintage_type": "year",
                "vintage_status": "proj.",
                "marketing_year": "2024/25",
                "month_abbr": None,
            },
            {
                "release_month": "2024-05",
                "commodity": "wheat",
                "row_label": "May",
                "vintage_type": "month",
                "vintage_status": None,
                "marketing_year": None,
                "month_abbr": "May",
            },
        ]
        return pd.DataFrame(rows)

    def test_month_row_gets_marketing_year(self):
        df = _derive_marketing_year_for_months(self._base_df())
        month_row = df[df["vintage_type"] == "month"].iloc[0]
        assert month_row["marketing_year"] == "2024/25"

    def test_year_row_unchanged(self):
        df = _derive_marketing_year_for_months(self._base_df())
        year_row = df[df["vintage_type"] == "year"].iloc[0]
        assert year_row["marketing_year"] == "2024/25"

    def test_no_proj_row_leaves_none(self):
        """When there is no proj. row, month marketing_year stays None."""
        rows = [
            {
                "release_month": "2024-05",
                "commodity": "wheat",
                "row_label": "May",
                "vintage_type": "month",
                "vintage_status": None,
                "marketing_year": None,
                "month_abbr": "May",
            },
        ]
        df = _derive_marketing_year_for_months(pd.DataFrame(rows))
        assert df.iloc[0]["marketing_year"] is None

    def test_multi_commodity_independent(self):
        """Two commodities must not bleed marketing_year into each other."""
        rows = [
            {
                "release_month": "2024-05", "commodity": "wheat",
                "vintage_type": "year", "vintage_status": "proj.",
                "marketing_year": "2024/25", "month_abbr": None, "row_label": "2024/25 proj.",
            },
            {
                "release_month": "2024-05", "commodity": "wheat",
                "vintage_type": "month", "vintage_status": None,
                "marketing_year": None, "month_abbr": "May", "row_label": "May",
            },
            {
                "release_month": "2024-05", "commodity": "rice",
                "vintage_type": "year", "vintage_status": "proj.",
                "marketing_year": "2024/25", "month_abbr": None, "row_label": "2024/25 proj.",
            },
            {
                "release_month": "2024-05", "commodity": "rice",
                "vintage_type": "month", "vintage_status": None,
                "marketing_year": None, "month_abbr": "May", "row_label": "May",
            },
        ]
        df = _derive_marketing_year_for_months(pd.DataFrame(rows))
        # Both month rows should have marketing_year filled
        month_rows = df[df["vintage_type"] == "month"]
        assert list(month_rows["marketing_year"]) == ["2024/25", "2024/25"]


# ---------------------------------------------------------------------------
# TestMeltToLong
# ---------------------------------------------------------------------------

class TestMeltToLong:
    def _pre_melt_df(self) -> pd.DataFrame:
        """Minimal DataFrame in the expected pre-melt form."""
        row = {
            "release_month": "2024-05",
            "commodity": "wheat",
            "row_label": "2024/25 proj.",
            "marketing_year": "2024/25",
            "vintage_type": "year",
            "vintage_status": "proj.",
            "month_abbr": None,
        }
        for col in MODERN_COUNTRY_COLUMNS:
            row[col] = 100.0
        return pd.DataFrame([row])

    def test_columns_match_silver_columns(self):
        df = melt_to_long(self._pre_melt_df())
        assert list(df.columns) == SILVER_COLUMNS

    def test_all_countries_present(self):
        df = melt_to_long(self._pre_melt_df())
        assert set(df["country"].unique()) == set(MODERN_COUNTRY_COLUMNS)

    def test_nan_value_rows_dropped(self):
        row = {
            "release_month": "2024-05", "commodity": "wheat",
            "row_label": "2024/25 proj.", "marketing_year": "2024/25",
            "vintage_type": "year", "vintage_status": "proj.", "month_abbr": None,
        }
        for col in MODERN_COUNTRY_COLUMNS:
            row[col] = 100.0
        row["russia"] = float("nan")  # simulate cotton pattern
        df = melt_to_long(pd.DataFrame([row]))
        assert "russia" not in df["country"].values

    def test_noise_rows_dropped(self):
        row = {
            "release_month": "2024-05", "commodity": "wheat",
            "row_label": "Oilseeds 2/", "marketing_year": None,
            "vintage_type": "noise", "vintage_status": None, "month_abbr": None,
        }
        for col in MODERN_COUNTRY_COLUMNS:
            row[col] = 0.0
        df = melt_to_long(pd.DataFrame([row]))
        assert len(df) == 0

    def test_value_preserved(self):
        row = {
            "release_month": "2024-05", "commodity": "wheat",
            "row_label": "2024/25 proj.", "marketing_year": "2024/25",
            "vintage_type": "year", "vintage_status": "proj.", "month_abbr": None,
        }
        for col in MODERN_COUNTRY_COLUMNS:
            row[col] = 0.0
        row["us"] = 42.5
        df = melt_to_long(pd.DataFrame([row]))
        us_row = df[df["country"] == "us"]
        assert len(us_row) == 1
        assert us_row.iloc[0]["value_mmt"] == pytest.approx(42.5)


# ---------------------------------------------------------------------------
# TestBuildLongTable
# ---------------------------------------------------------------------------

class TestBuildLongTable:
    def _modern_df(self, release_month: str = "2024-05") -> pd.DataFrame:
        rows = [
            _make_bronze_row(release_month, "wheat", "2024/25 prel.", us=100.0),
            _make_bronze_row(release_month, "wheat", "2024/25 proj.", us=101.0),
        ]
        return _make_bronze_df(*rows)

    def _legacy_df(self) -> pd.DataFrame:
        """Legacy-era df — has old "eu" column instead of eu27."""
        df = self._modern_df("2003-01")
        df = df.drop(columns=["eu27"])
        df["eu"] = 50.0
        return df

    def test_excludes_legacy_eu_frames(self):
        df_long = build_long_table([self._modern_df(), self._legacy_df()])
        assert "2003-01" not in df_long["release_month"].values

    def test_includes_no_eu27_modern_frames(self):
        """2015-2016 files lack eu27 but are modern (no 'eu' column); include them."""
        df_no_eu27 = self._modern_df("2015-06").drop(columns=["eu27"])
        df_long = build_long_table([df_no_eu27])
        assert "2015-06" in df_long["release_month"].values
        # eu27 simply not present as a country value for those rows
        assert "eu27" not in df_long["country"].values

    def test_drops_oilseeds_noise_row(self):
        noise_row = _make_bronze_row("2024-05", "coarse_grains", "Oilseeds 2/")
        df = _make_bronze_df(*[
            _make_bronze_row("2024-05", "wheat", "2024/25 proj."),
            noise_row,
        ])
        df_long = build_long_table([df])
        assert "Oilseeds 2/" not in df_long["row_label"].values

    def test_empty_input_returns_empty(self):
        df_long = build_long_table([])
        assert list(df_long.columns) == SILVER_COLUMNS
        assert len(df_long) == 0


# ---------------------------------------------------------------------------
# TestBuildRevisionTable
# ---------------------------------------------------------------------------

class TestBuildRevisionTable:
    def _long_two_releases(self) -> pd.DataFrame:
        """Two release months for wheat/us, same marketing_year."""
        rows = []
        for rm, val in [("2024-04", 100.0), ("2024-05", 102.0)]:
            rows.append({
                "release_month": rm,
                "commodity": "wheat",
                "row_label": "2024/25 proj.",
                "marketing_year": "2024/25",
                "vintage_type": "year",
                "vintage_status": "proj.",
                "month_abbr": None,
                "country": "us",
                "value_mmt": val,
            })
        return pd.DataFrame(rows, columns=SILVER_COLUMNS)

    def test_first_release_has_nan_revision(self):
        df_rev = build_revision_table(self._long_two_releases())
        first = df_rev[df_rev["release_month"] == "2024-04"].iloc[0]
        assert math.isnan(first["revision_mmt"])

    def test_second_release_has_correct_delta(self):
        df_rev = build_revision_table(self._long_two_releases())
        second = df_rev[df_rev["release_month"] == "2024-05"].iloc[0]
        assert second["revision_mmt"] == pytest.approx(2.0)

    def test_prior_release_month_set_correctly(self):
        df_rev = build_revision_table(self._long_two_releases())
        second = df_rev[df_rev["release_month"] == "2024-05"].iloc[0]
        assert second["prior_release_month"] == "2024-04"

    def test_positive_revision(self):
        df_rev = build_revision_table(self._long_two_releases())
        second = df_rev[df_rev["release_month"] == "2024-05"].iloc[0]
        assert second["revision_mmt"] > 0

    def test_negative_revision(self):
        rows = [
            {
                "release_month": "2024-04", "commodity": "wheat",
                "row_label": "2024/25 proj.", "marketing_year": "2024/25",
                "vintage_type": "year", "vintage_status": "proj.",
                "month_abbr": None, "country": "us", "value_mmt": 105.0,
            },
            {
                "release_month": "2024-05", "commodity": "wheat",
                "row_label": "2024/25 proj.", "marketing_year": "2024/25",
                "vintage_type": "year", "vintage_status": "proj.",
                "month_abbr": None, "country": "us", "value_mmt": 102.0,
            },
        ]
        df_long = pd.DataFrame(rows, columns=SILVER_COLUMNS)
        df_rev = build_revision_table(df_long)
        second = df_rev[df_rev["release_month"] == "2024-05"].iloc[0]
        assert second["revision_mmt"] == pytest.approx(-3.0)

    def test_output_columns_match(self):
        df_rev = build_revision_table(self._long_two_releases())
        assert list(df_rev.columns) == REVISION_COLUMNS

    def test_empty_input_returns_empty(self):
        df_rev = build_revision_table(pd.DataFrame(columns=SILVER_COLUMNS))
        assert list(df_rev.columns) == REVISION_COLUMNS
        assert len(df_rev) == 0
