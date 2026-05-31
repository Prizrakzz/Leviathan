"""Unit tests for the MPOB overview PDF → bronze/ transform.

Tests are pure Python — no S3/AWS dependencies.  pdfplumber is mocked where
needed; most tests exercise the parsing helpers directly with raw table data.
"""
from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import pytest

from leviathan.transforms.raw_to_bronze.mpob_pdf import (
    _first_numeric,
    _parse_num,
    _parse_stats_table,
    _row_label,
    extract_mpob_overview_annual,
)


# ---------------------------------------------------------------------------
# Minimal realistic table fixture
# (mirrors the 2015 PDF page 6 structure)
# ---------------------------------------------------------------------------

# Rows from the supply/demand table (page index 5).
_SUPPLY_TABLE: list[list[str | None]] = [
    # Section header — PLANTED AREA
    ["", "PLANTED AREA (HECTARES)", None, None, None, None, None, None, None, None, None, None, None, None, ""],
    # Data row — MALAYSIA
    ["MALAYSIA", None, None, "5,642,943", None, None, "5,392,235", None, None, "250,708", None, None, "4.6", None, None],
    # Section header — CPO PRODUCTION
    ["", "CPO PRODUCTION (TONNES)", None, None, None, None, None, None, None, None, None, None, None, None, ""],
    # Data row we want: MALAYSIA
    ["MALAYSIA", None, None, "19,961,581", None, None, "19,672,004", None, None, "289,577", None, None, "1.5", None, None],
    # Section header — CLOSING STOCKS
    ["", "CLOSING STOCKS (TONNES)", None, None, None, None, None, None, None, None, None, None, None, None, ""],
    # Data rows
    ["CRUDE PALM OIL", None, None, "1,593,073", None, None, "2,083,862", None, None, "(490,789)", None, None, "(23.6)", None, None],
    ["PROCESSED PALM OIL", None, None, "1,040,867", None, None, "1,011,547", None, None, "29,320", None, None, "2.9", None, None],
    # Sub-total row (TOTAL PALM OIL) — value at col[4]
    ["", "TOTAL PALM OIL", "", "", "2,633,940", "", "", "3,095,409", "", "", "(461,469)", "", "", "(14.9)", ""],
    # Section header — EXPORT
    ["", "EXPORT (TONNES)", None, None, None, None, None, None, None, None, None, None, None, None, ""],
    # Data rows we care about: PALM OIL (first occurrence)
    ["PALM OIL", None, None, "17,454,213", None, None, "17,306,247", None, None, "147,966", None, None, "0.9", None, None],
    ["PALM KERNEL OIL", None, None, "1,066,694", None, None, "1,077,044", None, None, "(10,350)", None, None, "(1.0)", None, None],
    ["PALM KERNEL CAKE", None, None, "4,266,380", None, None, "4,027,540", None, None, "238,840", None, None, "5.9", None, None],
    # Sub-total
    ["", "TOTAL EXPORTS (TONNES)", "", "", "25,370,229", "", "", "25,072,103", "", "", "298,126", "", "", "1.2", ""],
    # Section header — IMPORT
    ["", "IMPORT (TONNES)", None, None, None, None, None, None, None, None, None, None, None, None, ""],
    # Data row we care about: PALM OIL
    ["PALM OIL", None, None, "1,028,158", None, None, "891,826", None, None, "136,332", None, None, "15.3", None, None],
    ["PALM KERNEL OIL", None, None, "120,462", None, None, "113,453", None, None, "7,009", None, None, "6.2", None, None],
]

# Rows from the price/yield table (page index 6).
_PRICE_TABLE: list[list[str | None]] = [
    # Section header
    ["", "PRICE (RM/TONNE)", None, None, None, None, None, None, None, None, None, None, None, None, ""],
    # Row we want: FFB (MILL GATE)
    ["FFB (MILL GATE)", None, "", "459.00", "", "", "519.00", "", "", "(60.00)", "", "", "(11.6)", "", ""],
    ["CPO (EX-MILL)", None, "", "2,176.14", "", "", "2,410.00", "", "", "(233.86)", "", "", "(9.7)", "", ""],
]


# ---------------------------------------------------------------------------
# Tests: _parse_num
# ---------------------------------------------------------------------------


class TestParseNum:
    def test_integer_with_commas(self) -> None:
        assert _parse_num("19,961,581") == 19_961_581.0

    def test_decimal(self) -> None:
        assert _parse_num("459.00") == pytest.approx(459.0)

    def test_parenthesized_negative(self) -> None:
        assert _parse_num("(332,602)") == pytest.approx(-332_602.0)

    def test_parenthesized_negative_decimal(self) -> None:
        assert _parse_num("(60.00)") == pytest.approx(-60.0)

    def test_small_decimal(self) -> None:
        assert _parse_num("4.6") == pytest.approx(4.6)

    def test_empty_string_returns_none(self) -> None:
        assert _parse_num("") is None

    def test_whitespace_returns_none(self) -> None:
        assert _parse_num("  ") is None

    def test_text_returns_none(self) -> None:
        assert _parse_num("MALAYSIA") is None

    def test_none_like_string_returns_none(self) -> None:
        assert _parse_num("None") is None

    def test_strips_whitespace(self) -> None:
        assert _parse_num("  1,234  ") == pytest.approx(1234.0)


# ---------------------------------------------------------------------------
# Tests: _row_label
# ---------------------------------------------------------------------------


class TestRowLabel:
    def test_normal_data_row_label(self) -> None:
        row = ["MALAYSIA", None, None, "19,961,581", None]
        label, is_header = _row_label(row)
        assert label == "MALAYSIA"
        assert is_header is False

    def test_section_header_row(self) -> None:
        # No numeric values → is_section_header=True
        row = ["", "CPO PRODUCTION (TONNES)", None, None, None, None, None]
        label, is_header = _row_label(row)
        assert label == "CPO PRODUCTION (TONNES)"
        assert is_header is True

    def test_subtotal_row_is_not_header(self) -> None:
        # Has numeric value → is_section_header=False
        row = ["", "TOTAL PALM OIL", "", "", "2,633,940", "", ""]
        label, is_header = _row_label(row)
        assert label == "TOTAL PALM OIL"
        assert is_header is False

    def test_empty_row_returns_empty_label(self) -> None:
        row = [None, None, None, None]
        label, is_header = _row_label(row)
        assert label == ""
        assert is_header is False

    def test_only_col0_none_col1_none(self) -> None:
        row = [None, None, "1,000"]
        label, is_header = _row_label(row)
        assert label == ""


# ---------------------------------------------------------------------------
# Tests: _first_numeric
# ---------------------------------------------------------------------------


class TestFirstNumeric:
    def test_finds_value_at_col3(self) -> None:
        row = ["MALAYSIA", None, None, "19,961,581", None]
        assert _first_numeric(row) == pytest.approx(19_961_581.0)

    def test_finds_value_at_col4_when_col3_empty(self) -> None:
        row = ["", "TOTAL PALM OIL", "", "", "2,633,940", ""]
        assert _first_numeric(row) == pytest.approx(2_633_940.0)

    def test_returns_none_when_no_numerics(self) -> None:
        row = ["", "SECTION HEADER", None, None, None, None]
        assert _first_numeric(row) is None

    def test_skips_col0_and_col1(self) -> None:
        # col[0]="1000" should not be returned — search starts at index 2
        row = ["1000", None, None, "500"]
        assert _first_numeric(row) == pytest.approx(500.0)

    def test_handles_parenthesized_negative(self) -> None:
        row = ["CRUDE PALM OIL", None, None, "(490,789)", None]
        assert _first_numeric(row) == pytest.approx(-490_789.0)


# ---------------------------------------------------------------------------
# Tests: _parse_stats_table
# ---------------------------------------------------------------------------


class TestParseStatsTable:
    def test_extracts_cpo_production_malaysia(self) -> None:
        records = _parse_stats_table(_SUPPLY_TABLE, 2015)
        prod = [r for r in records if r["variable"] == "production__crude_palm_oil"]
        assert len(prod) == 1
        assert prod[0]["value"] == pytest.approx(19_961_581.0)
        assert prod[0]["year"] == 2015

    def test_extracts_closing_stocks_total_palm_oil(self) -> None:
        records = _parse_stats_table(_SUPPLY_TABLE, 2015)
        stocks = [r for r in records if r["variable"] == "closing_stocks__palm_oil"]
        assert len(stocks) == 1
        assert stocks[0]["value"] == pytest.approx(2_633_940.0)

    def test_extracts_exports_palm_oil(self) -> None:
        records = _parse_stats_table(_SUPPLY_TABLE, 2015)
        exports = [r for r in records if r["variable"] == "exports__palm_oil"]
        assert len(exports) == 1
        assert exports[0]["value"] == pytest.approx(17_454_213.0)

    def test_extracts_imports_palm_oil(self) -> None:
        records = _parse_stats_table(_SUPPLY_TABLE, 2015)
        imports = [r for r in records if r["variable"] == "imports__palm_oil"]
        assert len(imports) == 1
        assert imports[0]["value"] == pytest.approx(1_028_158.0)

    def test_extracts_ffb_price(self) -> None:
        records = _parse_stats_table(_PRICE_TABLE, 2015)
        price = [r for r in records if r["variable"] == "ffb_price__ffb"]
        assert len(price) == 1
        assert price[0]["value"] == pytest.approx(459.0)

    def test_skips_palm_kernel_oil(self) -> None:
        records = _parse_stats_table(_SUPPLY_TABLE, 2015)
        # Should not produce a record for PALM KERNEL OIL rows
        export_records = [r for r in records if r["variable"] == "exports__palm_oil"]
        assert len(export_records) == 1  # only PALM OIL, not PALM KERNEL OIL

    def test_empty_table_returns_empty(self) -> None:
        assert _parse_stats_table([], 2015) == []

    def test_section_not_matching_produces_no_records(self) -> None:
        unrelated_table = [
            ["", "SOME OTHER SECTION", None, None, None],
            ["DATA ROW", None, None, "999", None],
        ]
        records = _parse_stats_table(unrelated_table, 2015)
        assert records == []


# ---------------------------------------------------------------------------
# Tests: extract_mpob_overview_annual (mocked pdfplumber)
# ---------------------------------------------------------------------------


class TestExtractMpobOverviewAnnual:
    def _make_mock_pdf(self) -> MagicMock:
        page5 = MagicMock()
        page5.extract_tables.return_value = [_SUPPLY_TABLE]
        page6 = MagicMock()
        page6.extract_tables.return_value = [_PRICE_TABLE]
        mock_pdf = MagicMock()
        mock_pdf.pages = [MagicMock()] * 5 + [page5, page6]
        mock_pdf.__enter__ = lambda s: mock_pdf
        mock_pdf.__exit__ = MagicMock(return_value=False)
        return mock_pdf

    def test_returns_five_rows(self) -> None:
        with patch("leviathan.transforms.raw_to_bronze.mpob_pdf.pdfplumber") as mp:
            mp.open.return_value = self._make_mock_pdf()
            df = extract_mpob_overview_annual(b"fake", 2015, "2026-05-31")

        assert len(df) == 5

    def test_output_schema(self) -> None:
        with patch("leviathan.transforms.raw_to_bronze.mpob_pdf.pdfplumber") as mp:
            mp.open.return_value = self._make_mock_pdf()
            df = extract_mpob_overview_annual(b"fake", 2015, "2026-05-31")

        expected_cols = {"year", "variable", "value", "release_type", "source", "ingest_date"}
        assert expected_cols.issubset(set(df.columns))

    def test_release_type_and_source(self) -> None:
        with patch("leviathan.transforms.raw_to_bronze.mpob_pdf.pdfplumber") as mp:
            mp.open.return_value = self._make_mock_pdf()
            df = extract_mpob_overview_annual(b"fake", 2015, "2026-05-31")

        assert (df["release_type"] == "overview_pdf").all()
        assert (df["source"] == "mpob").all()

    def test_all_years_are_2015(self) -> None:
        with patch("leviathan.transforms.raw_to_bronze.mpob_pdf.pdfplumber") as mp:
            mp.open.return_value = self._make_mock_pdf()
            df = extract_mpob_overview_annual(b"fake", 2015, "2026-05-31")

        assert (df["year"] == 2015).all()

    def test_returns_empty_when_no_pages(self) -> None:
        mock_pdf = MagicMock()
        mock_pdf.pages = []
        mock_pdf.__enter__ = lambda s: mock_pdf
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("leviathan.transforms.raw_to_bronze.mpob_pdf.pdfplumber") as mp:
            mp.open.return_value = mock_pdf
            df = extract_mpob_overview_annual(b"fake", 2015, "2026-05-31")

        assert df.empty
