"""SILVER-F053/F054/F055: the three MPOC bronze/raw -> silver producers.

End-to-end from golden MPOC HTML fixtures through the F052 adapter into each silver grain. Pure
Python -- no S3/AWS.

Two fixture families are covered per producer:
  * synthetic minimal tables (the original intent tests: schema/grain/dedup/conflict/completeness);
  * REAL trimmed excerpts of the LIVE MPOC tab-widget layout (section headings absent, two-row
    year sub-headers, per-country stock grids), which the fixture-only heuristics silently
    mis-resolved (F053/54/55 MpocDriftError on the live pages).
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
    MpocDriftError as StockDriftError,
    MpocStockRelease,
    OUTPUT_COLUMNS as STOCK_COLS,
    transform_stock_comparison,
)
from leviathan.transforms.bronze_to_silver.mpoc_trade_stats_monthly import (
    MpocCompletenessError,
    MpocDriftError as MonthlyDriftError,
    MpocMonthlyRelease,
    OUTPUT_COLUMNS as MONTHLY_COLS,
    transform_trade_stats_monthly,
)


# =========================================================================== REAL live-layout excerpts
# Trimmed straight from the pages fetched 2026-07-16 (S3 raw/production/source=mpoc/...). Section
# headings are gone; tables must be resolved by header signature. Page order mirrors the live site:
# monthly Exports/Imports -> Exports to Major Countries -> Monthly Average Prices (CPO) -> full
# destination list. The CPO table carries the '4. Monthly Average Prices' heading -- the historical
# 'monthly'-identity trap that mis-resolved the monthly producer onto the CPO-price table.
_LIVE_MONTHLY_EI = """
<table><tbody>
<tr><th></th><th colspan="2"><strong>Exports</strong></th><th colspan="2"><strong>Imports</strong></th></tr>
<tr><th></th><th>2023</th><th>2022</th><th>2023</th><th>2022</th></tr>
<tr><td>Jan</td><td>1,136,027</td><td>1,155,826</td><td>144,937</td><td>70,596</td></tr>
<tr><td>Feb</td><td>1,126,127</td><td>1,111,507</td><td>52,446</td><td>149,833</td></tr>
<tr><td>Jan-Dec</td><td>15,097,572</td><td>15,712,071</td><td>874,371</td><td>1,060,538</td></tr>
</tbody></table>
"""

_LIVE_MAJOR = """
<table><tbody>
<tr><th>COUNTRY</th><th>JAN – DEC 2023</th><th>JAN – DEC 2022</th><th>CHANGE (MT)</th><th>CHANGE (%)</th></tr>
<tr><td>INDIA</td><td>2,809,956</td><td>2,891,422</td><td>(81,466)</td><td>(2.82)</td></tr>
<tr><td>CHINA</td><td>1,466,864</td><td>1,763,640</td><td>(296,777)</td><td>(16.83)</td></tr>
<tr><td>TOTAL</td><td>9,018,807</td><td>9,565,130</td><td>(546,323)</td><td>(5.71)</td></tr>
</tbody></table>
"""

_LIVE_CPO = """
<h4>4. Monthly Average Prices</h4>
<table><tbody>
<tr><th></th><th colspan="2">CPO Local Prices</th></tr>
<tr><th></th><th>2023</th><th>2022</th></tr>
<tr><td>Jan</td><td>3,924</td><td>5,359</td></tr>
</tbody></table>
"""

# Full-destination list: a SECOND country-headed table, later on the page, carrying a country
# (SPAIN) absent from the major-countries table -- proves the producer picks the FIRST country table.
_LIVE_FULL_DEST = """
<table><tbody>
<tr><th>COUNTRY</th><th>JAN – DEC 2023</th><th>JAN – DEC 2022</th><th>CHANGE (MT)</th><th>CHANGE (%)</th></tr>
<tr><td>INDIA</td><td>2,809,956</td><td>2,891,422</td><td>(81,466)</td><td>(2.82)</td></tr>
<tr><td>SPAIN</td><td>84,902</td><td>161,688</td><td>(76,786)</td><td>(47.49)</td></tr>
<tr><td>GRAND TOTAL</td><td>15,097,552</td><td>15,712,071</td><td>(614,520)</td><td>(3.91)</td></tr>
</tbody></table>
"""

_LIVE_TRADE_PAGE = _LIVE_MONTHLY_EI + _LIVE_MAJOR + _LIVE_CPO + _LIVE_FULL_DEST

# 2009 archive monthly table: prior year (2008) is listed FIRST, so the page-year column must be
# resolved from the year sub-header, not by fixed position.
_LIVE_MONTHLY_EI_2009 = """
<table><tbody>
<tr><th></th><th colspan="2">Exports</th><th colspan="2">Imports</th></tr>
<tr><th></th><th>2008</th><th>2009</th><th>2008</th><th>2009</th></tr>
<tr><td>Jan</td><td>1,037,468</td><td>1,353,686</td><td>52,868</td><td>29,863</td></tr>
<tr><td>Feb</td><td>1,065,491</td><td>1,257,482</td><td>28,789</td><td>27,423</td></tr>
</tbody></table>
"""


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

    # --- live tab-widget layout (headings absent; two country tables on the page) ---
    def test_live_layout_resolves_major_countries(self):
        df = transform_exports_by_country([MpocExportsRelease(2023, parse_tables(_LIVE_TRADE_PAGE))])
        assert list(df.columns) == EXPORTS_COLS
        # first COUNTRY-headed table (Exports to Major Countries), NOT the trailing full list:
        assert set(df["country"]) == {"india", "china"}   # SPAIN (full-list only) absent; TOTAL out
        assert df[df.country == "india"].exports_mt.iloc[0] == 2_809_956.0   # 2023 column
        assert df[df.country == "china"].exports_mt.iloc[0] == 1_466_864.0

    def test_live_layout_missing_country_table_is_drift(self):
        # only the monthly + CPO tables (no COUNTRY-headed table) -> fail closed
        page = _LIVE_MONTHLY_EI + _LIVE_CPO
        with pytest.raises(MpocDriftError):
            transform_exports_by_country([MpocExportsRelease(2023, parse_tables(page))])


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

    # --- live tab-widget layout (two-row header; year sub-header; CPO 'monthly' trap present) ---
    def test_live_layout_two_row_header_page_year_columns(self):
        df = transform_trade_stats_monthly([MpocMonthlyRelease(2023, parse_tables(_LIVE_TRADE_PAGE))])
        assert list(df["month"]) == [1, 2]                     # Jan, Feb (Jan-Dec total skipped)
        # 2023 columns picked (exports col 1, imports col 3) -- NOT the adjacent 2022 columns:
        assert df[df.month == 1].exports_mt.iloc[0] == 1_136_027.0
        assert df[df.month == 1].imports_mt.iloc[0] == 144_937.0

    def test_live_layout_avoids_monthly_average_prices_trap(self):
        # the CPO 'Monthly Average Prices' table must never be resolved: if it were, the header has
        # no export/import column and the result would be empty / wrong. Verify real numbers land.
        df = transform_trade_stats_monthly([MpocMonthlyRelease(2023, parse_tables(_LIVE_TRADE_PAGE))])
        assert not df.empty
        assert df[df.month == 2].exports_mt.iloc[0] == 1_126_127.0

    def test_live_layout_prior_year_first_resolves_page_year(self):
        # 2009 archive lists 2008 before 2009; the page-year column is read from the year sub-header
        df = transform_trade_stats_monthly(
            [MpocMonthlyRelease(2009, parse_tables(_LIVE_MONTHLY_EI_2009))])
        assert df[df.month == 1].exports_mt.iloc[0] == 1_353_686.0   # 2009 exports, not 2008
        assert df[df.month == 1].imports_mt.iloc[0] == 29_863.0       # 2009 imports, not 2008

    def test_live_layout_only_cpo_table_is_drift(self):
        # a page with only the CPO 'Monthly Average Prices' table -> no export/import table -> drift
        with pytest.raises(MonthlyDriftError):
            transform_trade_stats_monthly([MpocMonthlyRelease(2023, parse_tables(_LIVE_CPO))])


# --------------------------------------------------------------------------- F055 stock-comparison
# Real per-country grids (China + USA) trimmed from the live Stock Comparison page. oil_type is a
# column GROUP, the year is a sub-header, and the month is the row label. Sunflower is all '-' for
# China (missing, not zero); China 2026 has a blank July; USA labels carry footnote asterisks.
_STOCK_CHINA = """
<table><tbody>
<tr><th colspan="13">Country : China</th></tr>
<tr><th colspan="13">Oils and Fats Ending Stocks</th></tr>
<tr><th></th><th colspan="2">Palm Oil (MT)</th><th colspan="2">Soybean Oil (MT)</th><th colspan="2">Sunflower Oil (MT)</th><th colspan="2">Rapeseed Oil (MT)</th><th colspan="2">Other Oils (MT)</th><th colspan="2">Total Ending Stocks (MT)</th></tr>
<tr><th></th><th>2026</th><th>2025</th><th>2026</th><th>2025</th><th>2026</th><th>2025</th><th>2026</th><th>2025</th><th>2026</th><th>2024</th><th>2026</th><th>2025</th></tr>
<tr><td>January</td><td>709,200</td><td>418,900</td><td>883,300</td><td>757,300</td><td>-</td><td>-</td><td>242,000</td><td>551,000</td><td>-</td><td>-</td><td>1,834,500</td><td>1,727,200</td></tr>
<tr><td>July</td><td></td><td>585,500</td><td></td><td>989,300</td><td>-</td><td>-</td><td></td><td>673,000</td><td>-</td><td>-</td><td></td><td>2,247,800</td></tr>
</tbody></table>
"""

_STOCK_USA = """
<table><tbody>
<tr><th colspan="13">Country : USA</th></tr>
<tr><th colspan="13">Oils and Fats Ending Stocks</th></tr>
<tr><th></th><th colspan="2">Palm Oil (MT)</th><th colspan="2">Soybean Oil (MT)*</th><th colspan="2">Sunflower Oil (MT)*</th><th colspan="2">Rapeseed Oil (MT)</th><th colspan="2">Other Oils (MT)</th><th colspan="2">Total Ending Stocks (MT)*</th></tr>
<tr><th></th><th>2026</th><th>2025</th><th>2026</th><th>2025</th><th>2026</th><th>2025</th><th>2026</th><th>2025</th><th>2026</th><th>2025</th><th>2026</th><th>2025</th></tr>
<tr><td>January</td><td>159,000</td><td>159,000</td><td>795,000</td><td>694,000</td><td>29,000</td><td>26,000</td><td>57,000</td><td>55,000</td><td>121,000</td><td>126,000</td><td>1,161,000</td><td>1,060,000</td></tr>
</tbody></table>
"""

_STOCK_PAGE = _STOCK_CHINA + _STOCK_USA


class TestStockComparison:
    def test_schema_and_melt(self):
        df = transform_stock_comparison(MpocStockRelease("2026-07-16", parse_tables(_STOCK_PAGE)))
        assert list(df.columns) == STOCK_COLS
        assert set(df["country"]) == {"china", "usa"}
        # only the four canonical oils survive; 'Other Oils' + 'Total Ending Stocks' are dropped
        assert set(df["oil_type"]) <= {"palm_oil", "soybean_oil", "sunflower_oil", "rapeseed_oil"}
        row = df[(df.country == "china") & (df.oil_type == "palm_oil")
                 & (df.year == 2026) & (df.month == 1)]
        assert row.ending_stocks_mt.iloc[0] == 709_200.0

    def test_year_and_month_from_subheaders(self):
        df = transform_stock_comparison(MpocStockRelease("2026-07-16", parse_tables(_STOCK_PAGE)))
        assert set(df["year"]) == {2025, 2026}
        # China palm: Jan+Jul for 2025 (both present), only Jan for 2026 (July 2026 is blank)
        china_palm = df[(df.country == "china") & (df.oil_type == "palm_oil")]
        assert set(china_palm[china_palm.year == 2025].month) == {1, 7}
        assert set(china_palm[china_palm.year == 2026].month) == {1}

    def test_asterisked_oil_labels_normalized(self):
        df = transform_stock_comparison(MpocStockRelease("2026-07-16", parse_tables(_STOCK_USA)))
        usa_soy = df[(df.country == "usa") & (df.oil_type == "soybean_oil")
                     & (df.year == 2026) & (df.month == 1)]      # label was 'Soybean Oil (MT)*'
        assert usa_soy.ending_stocks_mt.iloc[0] == 795_000.0

    def test_blank_and_dash_cells_dropped_not_zero(self):
        df = transform_stock_comparison(MpocStockRelease("2026-07-16", parse_tables(_STOCK_CHINA)))
        # China sunflower is all '-' -> no rows at all (missing, never 0.0)
        assert df[(df.country == "china") & (df.oil_type == "sunflower_oil")].empty
        # China palm July 2026 is a blank cell -> dropped (only 2025 July survives)
        assert df[(df.country == "china") & (df.oil_type == "palm_oil")
                  & (df.year == 2026) & (df.month == 7)].empty

    def test_as_of_not_a_row_column(self):
        df = transform_stock_comparison(MpocStockRelease("2026-07-16", parse_tables(_STOCK_PAGE)))
        assert "as_of_date" not in df.columns  # provenance is manifest-only (plan L697)

    def test_conflicting_snapshot_cell_fails_closed(self):
        # the SAME (country, oil, year, month) cell appears twice with two different values
        conflict = """
        <table><tbody>
        <tr><th colspan="5">Country : China</th></tr>
        <tr><th colspan="5">Oils and Fats Ending Stocks</th></tr>
        <tr><th></th><th colspan="2">Palm Oil (MT)</th><th colspan="2">Soybean Oil (MT)</th></tr>
        <tr><th></th><th>2026</th><th>2025</th><th>2026</th><th>2025</th></tr>
        <tr><td>January</td><td>600</td><td>-</td><td>-</td><td>-</td></tr>
        <tr><td>January</td><td>999</td><td>-</td><td>-</td><td>-</td></tr>
        </tbody></table>
        """
        with pytest.raises(StockConflictError):
            transform_stock_comparison(MpocStockRelease("2026-07-16", parse_tables(conflict)))

    def test_no_country_table_is_drift(self):
        with pytest.raises(StockDriftError):
            transform_stock_comparison(MpocStockRelease("2026-07-16", parse_tables("<p>no stock</p>")))

    def test_country_table_without_oil_grid_is_drift(self):
        # a 'Country : X' header + ending-stock marker but no oil/year grid beneath it -> fail closed
        broken = """
        <table><tbody>
        <tr><th colspan="3">Country : China</th></tr>
        <tr><th colspan="3">Oils and Fats Ending Stocks</th></tr>
        <tr><th>Foo</th><th>Bar</th><th>Baz</th></tr>
        <tr><td>x</td><td>1</td><td>2</td></tr>
        </tbody></table>
        """
        with pytest.raises(StockDriftError):
            transform_stock_comparison(MpocStockRelease("2026-07-16", parse_tables(broken)))

    def test_country_table_without_ending_stock_marker_is_drift(self):
        # a 'Country : X' header present but the ending-stocks page marker is absent -> fail closed
        no_marker = """
        <table><tbody>
        <tr><th colspan="3">Country : China</th></tr>
        <tr><th>Foo</th><th>Bar</th><th>Baz</th></tr>
        <tr><td>x</td><td>1</td><td>2</td></tr>
        </tbody></table>
        """
        with pytest.raises(StockDriftError):
            transform_stock_comparison(MpocStockRelease("2026-07-16", parse_tables(no_marker)))
