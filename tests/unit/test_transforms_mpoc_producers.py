"""SILVER-F053/F054/F055: the three MPOC bronze/raw -> silver producers.

End-to-end from golden MPOC HTML fixtures through the F052 adapter into each silver grain. Pure
Python -- no S3/AWS.
"""
from __future__ import annotations

import pandas as pd
import pytest

from leviathan.silver.mpoc.adapter import parse_tables
from leviathan.transforms.bronze_to_silver.mpoc_exports_by_country import (
    MpocConflictError,
    MpocDriftError,
    MpocExportsRelease,
    OUTPUT_COLUMNS as EXPORTS_COLS,
    transform_exports_by_country,
)
from leviathan.transforms.bronze_to_silver.mpoc_stock_comparison import (
    MpocConflictError as StockConflictError,
    MpocStockRelease,
    OUTPUT_COLUMNS as STOCK_COLS,
    transform_stock_comparison,
)
from leviathan.transforms.bronze_to_silver.mpoc_trade_stats_monthly import (
    MpocCompletenessError,
    MpocMonthlyRelease,
    OUTPUT_COLUMNS as MONTHLY_COLS,
    transform_trade_stats_monthly,
)


# --------------------------------------------------------------------------- F053 exports-by-country
def _exports_page(year: int) -> str:
    return f"""
    <h3>Exports to Major Countries</h3>
    <table><tr><th>Country</th><th>{year} (Tonnes)</th><th>{year-1} (Tonnes)</th></tr>
    <tr><td>China</td><td>2,500,000</td><td>2,400,000</td></tr>
    <tr><td>India</td><td>1,800,000</td><td>1,700,000</td></tr>
    <tr><td>Others</td><td>500,000</td><td>480,000</td></tr>
    <tr><td>Total</td><td>4,800,000</td><td>4,580,000</td></tr></table>
    """


class TestExportsByCountry:
    def test_schema_and_grain(self):
        df = transform_exports_by_country([MpocExportsRelease(2023, parse_tables(_exports_page(2023)))])
        assert list(df.columns) == EXPORTS_COLS
        assert set(df["country"]) == {"china", "india"}    # Total/Others rollups excluded
        assert df[df.country == "china"].exports_mt.iloc[0] == 2_500_000.0

    def test_picks_the_page_year_column(self):
        df = transform_exports_by_country([MpocExportsRelease(2023, parse_tables(_exports_page(2023)))])
        assert df[df.country == "india"].exports_mt.iloc[0] == 1_800_000.0  # 2023 col, not 2022

    def test_multi_year_concat_sorted(self):
        rels = [MpocExportsRelease(2022, parse_tables(_exports_page(2022))),
                MpocExportsRelease(2023, parse_tables(_exports_page(2023)))]
        df = transform_exports_by_country(rels)
        assert list(df["year"]) == sorted(df["year"])
        assert len(df) == 4  # 2 years x 2 countries

    def test_exact_duplicate_collapsed(self):
        rels = [MpocExportsRelease(2023, parse_tables(_exports_page(2023))),
                MpocExportsRelease(2023, parse_tables(_exports_page(2023)))]
        df = transform_exports_by_country(rels)
        assert len(df) == 2  # identical dup collapsed, not doubled

    def test_conflicting_duplicate_fails_closed(self):
        page_a = _exports_page(2023)
        page_b = page_a.replace("2,500,000", "9,900,000")  # China conflicts
        rels = [MpocExportsRelease(2023, parse_tables(page_a)),
                MpocExportsRelease(2023, parse_tables(page_b))]
        with pytest.raises(MpocConflictError):
            transform_exports_by_country(rels)

    def test_missing_table_is_drift(self):
        with pytest.raises(MpocDriftError):
            transform_exports_by_country([MpocExportsRelease(2023, parse_tables("<p>no table</p>"))])


# --------------------------------------------------------------------------- F054 monthly trade-stats
def _monthly_page(year: int, months: int = 12) -> str:
    rows = "".join(
        f"<tr><td>{m:02d}</td><td>{1_000_000 + m}</td><td>{50_000 + m}</td></tr>"
        for m in range(1, months + 1)
    )
    return f"""
    <h3>Monthly Palm Oil Exports and Imports {year}</h3>
    <table><tr><th>Month</th><th>Exports (Tonnes)</th><th>Imports (Tonnes)</th></tr>
    {rows}
    <tr><td>Total</td><td>9</td><td>9</td></tr></table>
    """


class TestTradeStatsMonthly:
    def test_schema_and_12_months(self):
        df = transform_trade_stats_monthly([MpocMonthlyRelease(2023, parse_tables(_monthly_page(2023)))])
        assert list(df.columns) == MONTHLY_COLS
        assert list(df["month"]) == list(range(1, 13))         # Total row skipped
        assert df[df.month == 1].exports_mt.iloc[0] == 1_000_001

    def test_imports_column_mapped(self):
        df = transform_trade_stats_monthly([MpocMonthlyRelease(2023, parse_tables(_monthly_page(2023)))])
        assert df[df.month == 3].imports_mt.iloc[0] == 50_003

    def test_require_full_year_passes_on_12(self):
        transform_trade_stats_monthly(
            [MpocMonthlyRelease(2023, parse_tables(_monthly_page(2023, 12)))], require_full_year=True)

    def test_require_full_year_fails_on_partial(self):
        with pytest.raises(MpocCompletenessError):
            transform_trade_stats_monthly(
                [MpocMonthlyRelease(2023, parse_tables(_monthly_page(2023, 8)))], require_full_year=True)

    def test_partial_year_ok_without_flag(self):
        df = transform_trade_stats_monthly(
            [MpocMonthlyRelease(2023, parse_tables(_monthly_page(2023, 8)))])
        assert len(df) == 8


# --------------------------------------------------------------------------- F055 stock-comparison
_STOCK_HTML = """
<h3>Oils and Fats Ending Stocks</h3>
<table><tr><th>Country</th><th>Oil</th><th>Nov 2024</th><th>Dec 2024</th></tr>
<tr><td>China</td><td>Palm</td><td>600</td><td>620</td></tr>
<tr><td>China</td><td>Soybean</td><td>900</td><td>910</td></tr>
<tr><td>India</td><td>Palm</td><td>400</td><td>n.a.</td></tr></table>
"""


class TestStockComparison:
    def test_schema_and_melt(self):
        df = transform_stock_comparison(MpocStockRelease("2026-05-01", parse_tables(_STOCK_HTML)))
        assert list(df.columns) == STOCK_COLS
        # 3 (country,oil) rows x 2 months minus one n.a. cell = 5
        assert len(df) == 5
        row = df[(df.country == "china") & (df.oil_type == "palm_oil") & (df.month == 12)]
        assert row.ending_stocks_mt.iloc[0] == 620.0

    def test_year_month_parsed_from_header(self):
        df = transform_stock_comparison(MpocStockRelease("2026-05-01", parse_tables(_STOCK_HTML)))
        assert set(df["year"]) == {2024}
        assert set(df["month"]) == {11, 12}

    def test_as_of_not_a_row_column(self):
        df = transform_stock_comparison(MpocStockRelease("2026-05-01", parse_tables(_STOCK_HTML)))
        assert "as_of_date" not in df.columns  # provenance is manifest-only (plan L697)

    def test_conflicting_snapshot_cell_fails_closed(self):
        # the SAME (country, oil, year, month) cell appears twice with two different values
        conflict = """
        <h3>Oils and Fats Ending Stocks</h3>
        <table><tr><th>Country</th><th>Oil</th><th>Nov 2024</th></tr>
        <tr><td>China</td><td>Palm</td><td>600</td></tr>
        <tr><td>China</td><td>Palm</td><td>999</td></tr></table>
        """
        with pytest.raises(StockConflictError):
            transform_stock_comparison(MpocStockRelease("2026-05-01", parse_tables(conflict)))

    def test_na_cell_dropped_not_zero(self):
        df = transform_stock_comparison(MpocStockRelease("2026-05-01", parse_tables(_STOCK_HTML)))
        india_dec = df[(df.country == "india") & (df.month == 12)]
        assert india_dec.empty  # 'n.a.' is missing, never 0.0
