"""Unit tests for the MPOB annual summary HTML → bronze transform.

Tests cover the fixed section-prefix extraction logic.  All tests are pure
Python — no S3/AWS dependencies.
"""
from __future__ import annotations

import textwrap

import pandas as pd
import pytest
from leviathan.transforms.raw_to_bronze.mpob_html import extract_mpob_annual

# ---------------------------------------------------------------------------
# Minimal HTML fixture that mimics the real MPOB annual summary structure:
#   - Table 0: data table with empty first <tr> (pandas gets integer columns)
#              and section-header rows using colspan
#   - Table 1: footnote table (2-column, filtered out)
# ---------------------------------------------------------------------------


def _make_annual_html(include_footnote_table: bool = True) -> bytes:
    """Build a minimal MPOB annual summary HTML page."""
    html = textwrap.dedent("""\
        <html><body>
        <table>
          <tr><td></td><td></td><td></td><td></td></tr>
          <tr><td></td><td>Dec 23</td><td>Jan 24</td><td>Feb 24</td></tr>
          <tr><td>PRODUCTION (TONNES)</td><td>PRODUCTION (TONNES)</td>
              <td>PRODUCTION (TONNES)</td><td>PRODUCTION (TONNES)</td></tr>
          <tr><td>Crude Palm Oil (CPO)</td><td>1500000</td><td>1400000</td><td>1300000</td></tr>
          <tr><td>Palm Kernel</td><td>350000</td><td>340000</td><td>320000</td></tr>
          <tr><td>CLOSING STOCK (TONNES)</td><td>CLOSING STOCK (TONNES)</td>
              <td>CLOSING STOCK (TONNES)</td><td>CLOSING STOCK (TONNES)</td></tr>
          <tr><td>Palm Oil</td><td>2000000</td><td>1900000</td><td>1800000</td></tr>
          <tr><td>EXPORT (TONNES)</td><td>EXPORT (TONNES)</td>
              <td>EXPORT (TONNES)</td><td>EXPORT (TONNES)</td></tr>
          <tr><td>Palm Oil (CPO+PPO)</td><td>1200000</td><td>1100000</td><td>1000000</td></tr>
          <tr><td>IMPORT (TONNES)</td><td>IMPORT (TONNES)</td>
              <td>IMPORT (TONNES)</td><td>IMPORT (TONNES)</td></tr>
          <tr><td>Palm Oil (CPO+PPO)</td><td>10000</td><td>11000</td><td>12000</td></tr>
          <tr><td>FFB PRICE (RM/MT)</td><td>FFB PRICE (RM/MT)</td>
              <td>FFB PRICE (RM/MT)</td><td>FFB PRICE (RM/MT)</td></tr>
          <tr><td>FFB</td><td>42.5</td><td>41.0</td><td>39.5</td></tr>
        </table>
    """)
    if include_footnote_table:
        html += textwrap.dedent("""\
            <table>
              <tr><td>Note</td><td>Value</td></tr>
              <tr><td>(r)</td><td>revised</td></tr>
              <tr><td>(p)</td><td>preliminary</td></tr>
            </table>
        """)
    html += "</body></html>"
    return html.encode("utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExtractMpobAnnualSectionPrefixes:
    """Section labels must appear as prefixes in variable names."""

    @pytest.fixture()
    def df(self) -> pd.DataFrame:
        return extract_mpob_annual(_make_annual_html(), year=2024, ingest_date="2024-06-01")

    def test_returns_dataframe(self, df: pd.DataFrame) -> None:
        assert isinstance(df, pd.DataFrame)

    def test_not_empty(self, df: pd.DataFrame) -> None:
        assert not df.empty

    def test_production_prefix(self, df: pd.DataFrame) -> None:
        """CPO production variable must carry 'production__' prefix."""
        assert "production__crude_palm_oil" in df["variable"].values

    def test_closing_stocks_prefix(self, df: pd.DataFrame) -> None:
        assert "closing_stocks__palm_oil" in df["variable"].values

    def test_exports_prefix(self, df: pd.DataFrame) -> None:
        assert "exports__palm_oil" in df["variable"].values

    def test_imports_prefix(self, df: pd.DataFrame) -> None:
        assert "imports__palm_oil" in df["variable"].values

    def test_ffb_price_prefix(self, df: pd.DataFrame) -> None:
        assert "ffb_price__ffb" in df["variable"].values

    def test_no_unknown_prefix(self, df: pd.DataFrame) -> None:
        """After the fix, no variable should start with 'unknown__'."""
        unknown_vars = [v for v in df["variable"].unique() if v.startswith("unknown__")]
        assert unknown_vars == [], f"Unexpected unknown__ variables: {unknown_vars}"

    def test_no_duplicates_per_month_variable(self, df: pd.DataFrame) -> None:
        dupes = df.duplicated(["year", "month", "variable"]).sum()
        assert dupes == 0, f"{dupes} duplicate (year, month, variable) rows found"

    def test_year_and_month_columns_present(self, df: pd.DataFrame) -> None:
        for col in ("year", "month", "variable", "value"):
            assert col in df.columns

    def test_correct_months(self, df: pd.DataFrame) -> None:
        """Fixture data spans Dec 2023, Jan 2024, Feb 2024."""
        assert set(df[df["year"] == 2024]["month"].unique()) >= {1, 2}
        assert 12 in df[df["year"] == 2023]["month"].unique()

    def test_production_cpo_value_dec23(self, df: pd.DataFrame) -> None:
        row = df[
            (df["variable"] == "production__crude_palm_oil")
            & (df["year"] == 2023)
            & (df["month"] == 12)
        ]
        assert len(row) == 1
        assert row["value"].iloc[0] == pytest.approx(1_500_000.0)

    def test_su_ratio_can_be_computed(self, df: pd.DataFrame) -> None:
        """Closing stocks and exports should both be present for Jan 2024."""
        stocks = df[
            (df["variable"] == "closing_stocks__palm_oil")
            & (df["year"] == 2024) & (df["month"] == 1)
        ]["value"].iloc[0]
        exports = df[
            (df["variable"] == "exports__palm_oil")
            & (df["year"] == 2024) & (df["month"] == 1)
        ]["value"].iloc[0]
        su = stocks / exports
        assert su == pytest.approx(1_900_000 / 1_100_000, rel=1e-3)


class TestExtractMpobAnnualWithoutFootnote:
    """Footnote table should be filtered out regardless."""

    def test_only_data_table_used(self) -> None:
        df_with = extract_mpob_annual(
            _make_annual_html(include_footnote_table=True), year=2024, ingest_date="2024-06-01"
        )
        df_without = extract_mpob_annual(
            _make_annual_html(include_footnote_table=False), year=2024, ingest_date="2024-06-01"
        )
        # Both should produce the same variables regardless of footnote table.
        assert sorted(df_with["variable"].unique()) == sorted(df_without["variable"].unique())


class TestExtractMpobAnnualUnderConstruction:
    """Under-construction pages should return empty DataFrame."""

    def test_under_construction_returns_empty(self) -> None:
        html = b"<html><body><p>Under Construction</p></body></html>"
        df = extract_mpob_annual(html, year=2020, ingest_date="2024-06-01")
        assert df.empty
