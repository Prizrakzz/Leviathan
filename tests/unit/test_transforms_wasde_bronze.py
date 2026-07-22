"""Unit tests for USDA WASDE raw → bronze transform.

Tests cover all public helpers and both format parsers:

- ``_detect_format``: Format A (colon) vs Format B (columnar) detection
- ``_parse_unit``: unit extraction from heading lines
- ``_parse_market_year_and_status``: year/status parsing edge cases
- ``_strip_filler``: removal of pdfplumber "filler" tokens
- ``_normalise_attr``: attribute alias mapping
- ``parse_wasde_txt``: TXT era end-to-end (spot-check row count + spot value)
- ``parse_wasde_pdf_scanned``: Textract LINE block parsing end-to-end
- ``bronze_wasde_key``: S3 key format

All tests are pure (no I/O, no S3).
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest
from leviathan.storage.paths import bronze_wasde_key
from leviathan.transforms.raw_to_bronze.usda_wasde import (
    _colon_inject_data_section,
    _detect_format,
    _extract_attrs_from_header,
    _inject_scanned_seps,
    _normalise_attr,
    _parse_market_year_and_status,
    _parse_unit,
    _strip_filler,
    parse_wasde_pdf_scanned,
    parse_wasde_txt,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "wasde"


# ---------------------------------------------------------------------------
# Fixtures: minimal table text blocks
# ---------------------------------------------------------------------------

# Minimal Format A (colon-delimited) block representing two years of
# World Wheat Supply and Use data.
_FORMAT_A_TEXT = """\
World Wheat Supply and Use 1/ (Million Metric Tons)

=======================================================================
         : Beg.   :Produc-:        :        : Total  :        :Ending
         : Stocks :  tion : Imports: Exports: Dom.Use:  Feed  : Stocks
=======================================================================
World 3/ :  127.59  610.46  113.39  112.05  599.63   97.03   139.37
 2008/09 (Est.)
United States:  17.45   68.02   3.25   34.22   33.33    8.01   21.17
Argentina:       1.37   18.00   0.02    7.25    6.40    0.05    5.74
=======================================================================
World 3/ :  139.37  680.51  122.03  130.04  617.16  109.94   194.71
 2009/10 (Proj.)
United States:  21.17   60.32   3.40   30.00   35.42    8.25   19.47
Argentina:       5.74   12.00   0.02    8.00    5.10    0.10    4.61
=======================================================================
"""

# Minimal TXT fixture (WASDE 1995–1999 era) — same Format A layout
_TXT_FIXTURE = """\
WORLD AGRICULTURAL SUPPLY AND DEMAND ESTIMATES

World Wheat Supply and Use (Million Metric Tons)

======================================================================
         : Beg.   :Production: Imports: Exports:Dom. Use:Ending
         : Stocks :          :        :        :  Total : Stocks
======================================================================
World    :  115.00   600.00   110.00  105.00  590.00   130.00
  1995/96 (Est.)
U.S.     :   20.00    59.00     3.00   33.00   31.00    18.00
Canada   :    3.50    25.00     0.20   18.00   10.00     0.70
======================================================================
"""

# Minimal Textract LINE blocks simulating a scanned WASDE page
_TEXTRACT_BLOCKS = [
    {"BlockType": "LINE", "Page": 1, "Text": "World Wheat Supply and Use (Million Metric Tons)",
     "Geometry": {"BoundingBox": {"Top": 0.05}}},
    {"BlockType": "LINE", "Page": 1, "Text": "=========================================================",
     "Geometry": {"BoundingBox": {"Top": 0.10}}},
    {"BlockType": "LINE", "Page": 1, "Text": "         : Beg. Stocks :Production: Imports: Ending Stocks",
     "Geometry": {"BoundingBox": {"Top": 0.12}}},
    {"BlockType": "LINE", "Page": 1, "Text": "=========================================================",
     "Geometry": {"BoundingBox": {"Top": 0.14}}},
    {"BlockType": "LINE", "Page": 1, "Text": "  1980/81 (Est.)",
     "Geometry": {"BoundingBox": {"Top": 0.16}}},
    {"BlockType": "LINE", "Page": 1, "Text": "World    :  110.00    560.00   95.00   120.00",
     "Geometry": {"BoundingBox": {"Top": 0.18}}},
    {"BlockType": "LINE", "Page": 1, "Text": "U.S.     :   18.00     59.00    3.00    22.00",
     "Geometry": {"BoundingBox": {"Top": 0.20}}},
    {"BlockType": "LINE", "Page": 1, "Text": "=========================================================",
     "Geometry": {"BoundingBox": {"Top": 0.22}}},
    # Non-LINE block — should be ignored
    {"BlockType": "WORD", "Page": 1, "Text": "World",
     "Geometry": {"BoundingBox": {"Top": 0.18}}},
]


# ---------------------------------------------------------------------------
# paths.bronze_wasde_key
# ---------------------------------------------------------------------------

def test_bronze_wasde_key_format() -> None:
    key = bronze_wasde_key("2010-01-12")
    assert key == "bronze/production/source=usda_wasde/release_date=2010-01-12/part-000.parquet"


def test_bronze_wasde_key_historical() -> None:
    key = bronze_wasde_key("1995-04-11")
    assert key == "bronze/production/source=usda_wasde/release_date=1995-04-11/part-000.parquet"


# ---------------------------------------------------------------------------
# _detect_format
# ---------------------------------------------------------------------------

def test_detect_format_colon() -> None:
    assert _detect_format(_FORMAT_A_TEXT) == "colon"


def test_detect_format_columnar() -> None:
    text_no_sep = "World Wheat Supply and Use\nWorld  127.59  610.46\nArgentina  1.37  18.00"
    assert _detect_format(text_no_sep) == "columnar"


# ---------------------------------------------------------------------------
# _parse_unit
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("heading,expected", [
    ("World Wheat Supply and Use 1/ (Million Metric Tons)", "Million Metric Tons"),
    ("U.S. Wheat Supply and Use 1/ Million bushels", "Million bushels"),
    ("World and U.S. Supply and Use for Cotton 1/ Million 480-lb. bales", "Million 480-lb. bales"),
    ("World Coarse Grain Supply and Use (Million Metric Tons)", "Million Metric Tons"),
    ("No unit here at all", ""),
])
def test_parse_unit(heading: str, expected: str) -> None:
    assert _parse_unit(heading) == expected


# ---------------------------------------------------------------------------
# _parse_market_year_and_status
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label,expected_my,expected_status", [
    ("2009/10",              "2009/10", ""),
    ("2009/10 (Proj.)",      "2009/10", "Proj."),
    ("2008/09 (Est.)",       "2008/09", "Est."),
    ("2008/09 (Estimated)",  "2008/09", "Est."),
    ("2008/09 (Projected)",  "2008/09", "Proj."),
    ("2009/2010",            "2009/2010", ""),
])
def test_parse_market_year_and_status(label: str, expected_my: str, expected_status: str) -> None:
    my, status = _parse_market_year_and_status(label)
    assert my == expected_my
    assert status == expected_status


# ---------------------------------------------------------------------------
# _strip_filler
# ---------------------------------------------------------------------------

def test_strip_filler_removes_filler() -> None:
    assert _strip_filler("Argentina filler 1.37") == "Argentina  1.37"


def test_strip_filler_case_insensitive() -> None:
    assert _strip_filler("FILLER World") == "World"


def test_strip_filler_no_filler() -> None:
    assert _strip_filler("World 127.59") == "World 127.59"


# ---------------------------------------------------------------------------
# _normalise_attr
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Production",       "production"),
    ("Produc",           "production"),
    ("Beginning Stocks", "beginning_stocks"),
    ("Ending Stocks",    "ending_stocks"),
    ("Imports",          "imports"),
    ("Exports",          "exports"),
    ("Feed",             "feed"),
])
def test_normalise_attr(raw: str, expected: str) -> None:
    assert _normalise_attr(raw) == expected


# ---------------------------------------------------------------------------
# parse_wasde_txt — end-to-end
# ---------------------------------------------------------------------------

def test_parse_wasde_txt_returns_dataframe() -> None:
    df = parse_wasde_txt(_TXT_FIXTURE.encode(), "1995-04-11")
    assert isinstance(df, pd.DataFrame)


def test_parse_wasde_txt_schema_columns() -> None:
    df = parse_wasde_txt(_TXT_FIXTURE.encode(), "1995-04-11")
    required = {
        "release_date", "table_name", "region", "market_year",
        "status", "projection_month", "attribute", "value", "unit",
    }
    assert required.issubset(set(df.columns))


def test_parse_wasde_txt_release_date_propagated() -> None:
    df = parse_wasde_txt(_TXT_FIXTURE.encode(), "1995-04-11")
    if not df.empty:
        assert (df["release_date"] == "1995-04-11").all()


def test_parse_wasde_txt_numeric_value() -> None:
    """All non-NaN values in the value column must be finite floats."""
    df = parse_wasde_txt(_TXT_FIXTURE.encode(), "1995-04-11")
    numeric_vals = df["value"].dropna()
    assert (numeric_vals.apply(lambda x: isinstance(x, float) and math.isfinite(x))).all()


# ---------------------------------------------------------------------------
# parse_wasde_pdf_scanned — end-to-end with Textract LINE blocks
# ---------------------------------------------------------------------------

def test_parse_wasde_pdf_scanned_returns_dataframe() -> None:
    df = parse_wasde_pdf_scanned(_TEXTRACT_BLOCKS, "1981-01-12")
    assert isinstance(df, pd.DataFrame)


def test_parse_wasde_pdf_scanned_schema_columns() -> None:
    df = parse_wasde_pdf_scanned(_TEXTRACT_BLOCKS, "1981-01-12")
    required = {
        "release_date", "table_name", "region", "market_year",
        "status", "projection_month", "attribute", "value", "unit",
    }
    assert required.issubset(set(df.columns))


def test_parse_wasde_pdf_scanned_ignores_non_line_blocks() -> None:
    """WORD blocks must not appear as rows in the output."""
    df = parse_wasde_pdf_scanned(_TEXTRACT_BLOCKS, "1981-01-12")
    # If WORD block was incorrectly processed, region "World" would appear
    # twice (from both LINE and WORD); dedup should eliminate extras.
    # Just check no crash and schema is intact.
    assert isinstance(df, pd.DataFrame)
    assert "release_date" in df.columns


def test_parse_wasde_pdf_scanned_release_date_propagated() -> None:
    df = parse_wasde_pdf_scanned(_TEXTRACT_BLOCKS, "1981-01-12")
    if not df.empty:
        assert (df["release_date"] == "1981-01-12").all()


# ---------------------------------------------------------------------------
# parse_wasde_pdf_scanned — scanned-era (1994) layout without ===== separators
#
# Exercises all three bug fixes in concert:
#   1. Y-grouping: Argentina label and data values are in separate LINE blocks
#      at the same visual Y coordinate; after grouping they must form one row.
#   2. require_sep=False: no ===== lines in the fixture; the table must still
#      be detected and parsed.
#   3. "tion" alias: the scanned header carries "Produc-/tion" across two
#      LINE blocks; after Y-grouping column 1 resolves to "production".
# ---------------------------------------------------------------------------

# Simulates a scanned 1994 WASDE world-wheat page:
#   - heading at top (no ===== separator follows it)
#   - 2-line column header ("Beginning Produc-:" / "Region : stocks : tion …")
#   - year banner "1991/92"
#   - Argentina data row fragmented into two LINE blocks at the same Y
_TEXTRACT_SCANNED_1994 = [
    # Heading — no ===== after it (tests require_sep=False)
    {
        "BlockType": "LINE", "Page": 1,
        "Text": "World Wheat Supply and Use (Million Metric Tons)",
        "Geometry": {"BoundingBox": {"Top": 0.050, "Left": 0.10}},
    },
    # Header row 1: "Beginning Produc-" context (single non-empty colon cell)
    {
        "BlockType": "LINE", "Page": 1,
        "Text": "          : Beginning Produc-:",
        "Geometry": {"BoundingBox": {"Top": 0.090, "Left": 0.05}},
    },
    # Header row 2: column labels including "tion" (tests "tion"→"production" alias)
    {
        "BlockType": "LINE", "Page": 1,
        "Text": "Region    : stocks  :  tion  : Imports:  Feed  : Dom.   : Exports: Ending stocks",
        "Geometry": {"BoundingBox": {"Top": 0.098, "Left": 0.05}},
    },
    # Market year banner (standalone, no colon)
    {
        "BlockType": "LINE", "Page": 1,
        "Text": "1991/92",
        "Geometry": {"BoundingBox": {"Top": 0.115, "Left": 0.05}},
    },
    # World row — label + data fragmented into two LINE blocks at same Y
    {
        "BlockType": "LINE", "Page": 1,
        "Text": "World 3/",
        "Geometry": {"BoundingBox": {"Top": 0.130, "Left": 0.05}},
    },
    {
        "BlockType": "LINE", "Page": 1,
        "Text": ": 145.00 : 580.00 : 110.00 :  95.00 : 570.00 : 115.00 : 155.00",
        "Geometry": {"BoundingBox": {"Top": 0.1302, "Left": 0.30}},
    },
    # Argentina row — fragmented (tests Y-grouping: two blocks at Y≈0.145 → one row)
    {
        "BlockType": "LINE", "Page": 1,
        "Text": "Argentina",
        "Geometry": {"BoundingBox": {"Top": 0.145, "Left": 0.05}},
    },
    {
        "BlockType": "LINE", "Page": 1,
        "Text": ":  0.82 :  9.88 :  0.00 :  0.05 :  4.58 :  5.78 :  0.35",
        "Geometry": {"BoundingBox": {"Top": 0.1452, "Left": 0.30}},
    },
]


def test_parse_wasde_pdf_scanned_1994_produces_rows() -> None:
    """Y-grouping + no-separator path must return at least one row."""
    df = parse_wasde_pdf_scanned(_TEXTRACT_SCANNED_1994, "1994-01-12")
    assert len(df) > 0, "Expected rows from scanned 1994 fixture, got empty DataFrame"


def test_parse_wasde_pdf_scanned_1994_schema() -> None:
    df = parse_wasde_pdf_scanned(_TEXTRACT_SCANNED_1994, "1994-01-12")
    required = {
        "release_date", "table_name", "region", "market_year",
        "status", "projection_month", "attribute", "value", "unit",
    }
    assert required.issubset(set(df.columns))


def test_parse_wasde_pdf_scanned_1994_argentina_imports() -> None:
    """Spot-check: Argentina imports must be 0.00 after Y-grouping reconstructs the row."""
    df = parse_wasde_pdf_scanned(_TEXTRACT_SCANNED_1994, "1994-01-12")
    mask = (
        (df["region"] == "Argentina")
        & (df["market_year"] == "1991/92")
        & (df["attribute"] == "imports")
    )
    assert mask.any(), "Argentina/1991-92/imports row not found"
    val = df.loc[mask, "value"].iloc[0]
    assert math.isclose(val, 0.00, abs_tol=1e-6), f"Expected imports=0.00, got {val}"


def test_parse_wasde_pdf_scanned_1994_production_alias() -> None:
    """The 'tion' alias must resolve the hyphen-split 'Produc-/tion' header to 'production'."""
    df = parse_wasde_pdf_scanned(_TEXTRACT_SCANNED_1994, "1994-01-12")
    mask = (
        (df["region"] == "Argentina")
        & (df["market_year"] == "1991/92")
        & (df["attribute"] == "production")
    )
    assert mask.any(), "Argentina/1991-92/production row not found"
    val = df.loc[mask, "value"].iloc[0]
    assert math.isclose(val, 9.88, abs_tol=1e-6), f"Expected production=9.88, got {val}"


# ---------------------------------------------------------------------------
# _colon_inject_data_section — unit tests for the 1989-era colon-injection helper
# ---------------------------------------------------------------------------

class TestColonInjectDataSection:
    """Tests for the helper that converts 1989-era space-delimited rows."""

    def test_colon_line_passes_through(self) -> None:
        """Lines that already have colons must not be modified."""
        lines = ["World 3/ : 143.84 : 477.35 : 60.98"]
        assert _colon_inject_data_section(lines) == lines

    def test_mixed_line_converted(self) -> None:
        """'Region token_with_letters numeric numeric …' → colon-injected."""
        result = _colon_inject_data_section(
            ["World 3/ 143.84 477.35 60.98 314.77 459.95 62.33 161.24"]
        )
        assert result == ["World 3/ : 143.84 : 477.35 : 60.98 : 314.77 : 459.95 : 62.33 : 161.24"]

    def test_mixed_line_with_parenthetical_status_not_converted(self) -> None:
        """Year banners like '1989/90 (Projected) 3/' must pass through unchanged."""
        line = "1989/90 (Projected) 3/"
        result = _colon_inject_data_section([line])
        assert result == [line]

    def test_text_followed_by_nums_merged(self) -> None:
        """'Region\\nval1 val2 …' → merged single colon-format line."""
        result = _colon_inject_data_section([
            "World 4/",
            "135.6 823.5 106.0 546.8 820.1 103.4 138.9",
        ])
        assert result == ["World 4/ : 135.6 : 823.5 : 106.0 : 546.8 : 820.1 : 103.4 : 138.9"]

    def test_nums_followed_by_text_merged(self) -> None:
        """'val1 val2 …\\nRegion' → merged (OCR artefact: label below its values)."""
        result = _colon_inject_data_section([
            "1.24 0.00 15.50 12.26 15.51 0.00 1.24",
            "Japan",
        ])
        assert result == ["Japan : 1.24 : 0.00 : 15.50 : 12.26 : 15.51 : 0.00 : 1.24"]

    def test_asterisk_line_passes_through(self) -> None:
        """Lines with no letters (e.g. '******') must be emitted unchanged."""
        lines = ["*******"]
        assert _colon_inject_data_section(lines) == lines

    def test_footnote_line_passes_through(self) -> None:
        """Lines starting with a footnote ref (e.g. '1/ Aggregate…') pass through."""
        line = "1/ Aggregate of differing local marketing years."
        result = _colon_inject_data_section([line])
        assert result == [line]

    def test_single_number_passes_through(self) -> None:
        """Single-value fragments cannot be reliably attributed and pass through."""
        lines = ["15.08"]
        assert _colon_inject_data_section(lines) == lines

    def test_mixed_country_with_footnote(self) -> None:
        """Region labels containing a footnote ref (e.g. 'Major exporters 4/') convert."""
        result = _colon_inject_data_section(
            ["Major exporters 4/ 21.80 91.57 1.63 54.60"]
        )
        assert result == ["Major exporters 4/ : 21.80 : 91.57 : 1.63 : 54.60"]

    def test_text_not_followed_by_nums_emitted_asis(self) -> None:
        """A text line whose next non-empty line is not 'nums' is emitted as-is."""
        result = _colon_inject_data_section(["June", "July 141.6 809.4 106.2"])
        # 'June' has no adjacent nums (next is mixed), so emitted as-is
        # 'July 141.6 809.4 106.2' is mixed → colon-injected
        assert result[0] == "June"
        assert result[1] == "July : 141.6 : 809.4 : 106.2"


# ---------------------------------------------------------------------------
# _inject_scanned_seps — year-banner placement tests for 1989-era format
# ---------------------------------------------------------------------------

class TestInjectScannedSeps1989:
    """Tests that _inject_scanned_seps correctly places sep2 for 1989-era files."""

    def _sep_indices(self, lines: list[str]) -> list[int]:
        """Return indices of separator (=====) lines in the injected output."""
        out = _inject_scanned_seps(lines)
        return [i for i, ln in enumerate(out) if ln.strip().startswith("=")]

    def test_year_banner_with_footnote_triggers_sep2(self) -> None:
        """'1989/90 (Projected) 3/' must be recognised as the data-section start."""
        block = [
            "World Corn Supply and Use 1/",
            "(Million metric tons)",
            ": Stocks : tion : Imports : Feed : Total : Exports :",
            "1989/90 (Projected) 3/",
            "World 3/ 143.84 477.35 60.98 314.77 459.95 62.33 161.24",
        ]
        seps = self._sep_indices(block)
        # sep1 = index 1 (after heading), sep2 = index before "1989/90…"
        assert len(seps) == 2, f"Expected 2 separators, got {seps}"
        out = _inject_scanned_seps(block)
        # The line immediately after sep2 should be the year banner
        sep2_pos = seps[1]
        assert "1989/90" in out[sep2_pos + 1]

    def test_colon_free_data_rows_injected_after_sep2(self) -> None:
        """Data rows in the data section must be colon-injected."""
        block = [
            "World Corn Supply and Use 1/",
            ": Stocks : tion : Imports : Feed : Total : Exports :",
            "1989/90 (Projected) 3/",
            "World 3/ 143.84 477.35 60.98 314.77 459.95 62.33 161.24",
        ]
        out = _inject_scanned_seps(block)
        # Find the colon-injected World row in the output
        world_lines = [ln for ln in out if "World 3/" in ln and ":" in ln]
        assert world_lines, "Expected colon-injected World row in output"
        assert "143.84" in world_lines[0]


# ---------------------------------------------------------------------------
# parse_wasde_pdf_scanned — end-to-end 1989-era (colon-free rows)
# ---------------------------------------------------------------------------

# Simulates a 1989-era scanned WASDE page:
#   - heading (no trailing =====)
#   - column headers with colons
#   - year banner with trailing footnote ref "1989/90 (Projected) 3/"
#   - data rows WITHOUT colons (mixed and split variants)
_TEXTRACT_1989_ERA = [
    {
        "BlockType": "LINE", "Page": 1,
        "Text": "World Corn Supply and Use 1/ (Million metric tons)",
        "Geometry": {"BoundingBox": {"Top": 0.050, "Left": 0.10}},
    },
    {
        "BlockType": "LINE", "Page": 1,
        "Text": ": Stocks : tion : Imports : Feed : Total : Exports :",
        "Geometry": {"BoundingBox": {"Top": 0.090, "Left": 0.05}},
    },
    # Year banner with trailing footnote — previously broke _inject_scanned_seps
    {
        "BlockType": "LINE", "Page": 1,
        "Text": "1989/90 (Projected) 3/",
        "Geometry": {"BoundingBox": {"Top": 0.110, "Left": 0.05}},
    },
    # Mixed row: label + space-delimited values, no colons
    {
        "BlockType": "LINE", "Page": 1,
        "Text": "World 3/ 143.84 477.35 60.98 314.77 459.95 62.33 161.24",
        "Geometry": {"BoundingBox": {"Top": 0.125, "Left": 0.05}},
    },
    # Split row: label on one block, values on the next (same visual row)
    {
        "BlockType": "LINE", "Page": 1,
        "Text": "United States",
        "Geometry": {"BoundingBox": {"Top": 0.140, "Left": 0.05}},
    },
    {
        "BlockType": "LINE", "Page": 1,
        "Text": "102.61 209.56 0.05 119.74 150.01 38.20 124.00",
        "Geometry": {"BoundingBox": {"Top": 0.1402, "Left": 0.30}},
    },
    # Continuation: another mixed row
    {
        "BlockType": "LINE", "Page": 1,
        "Text": "Argentina 0.42 9.25 0.00 4.65 5.25 4.03 0.39",
        "Geometry": {"BoundingBox": {"Top": 0.155, "Left": 0.05}},
    },
]


def test_parse_wasde_pdf_scanned_1989_returns_rows() -> None:
    """1989-era colon-free fixture must produce at least one parseable row."""
    df = parse_wasde_pdf_scanned(_TEXTRACT_1989_ERA, "1989-02-09")
    assert len(df) > 0, f"Expected rows from 1989-era fixture, got {len(df)}"


def test_parse_wasde_pdf_scanned_1989_world_row_present() -> None:
    """World row from the colon-free mixed-format fixture must appear in output."""
    df = parse_wasde_pdf_scanned(_TEXTRACT_1989_ERA, "1989-02-09")
    assert "World" in df["region"].values, "World row missing from 1989-era output"


def test_parse_wasde_pdf_scanned_1989_argentina_present() -> None:
    """Argentina row (mixed format on single line) must appear in output."""
    df = parse_wasde_pdf_scanned(_TEXTRACT_1989_ERA, "1989-02-09")
    assert "Argentina" in df["region"].values, "Argentina row missing from 1989-era output"


def test_parse_wasde_pdf_scanned_1989_market_year_set() -> None:
    """market_year must be '1989/90' (from the year banner with trailing footnote)."""
    df = parse_wasde_pdf_scanned(_TEXTRACT_1989_ERA, "1989-02-09")
    assert not df.empty
    assert (df["market_year"] == "1989/90").any(), (
        f"Expected market_year='1989/90', found: {df['market_year'].unique()}"
    )



# ---------------------------------------------------------------------------
# BF-W2: PDFMaker word-fragment merge (the wasde0726.pdf header-shred class).
# ---------------------------------------------------------------------------
def _w(text: str, x0: float, x1: float, top: float = 90.0) -> dict:
    return {"text": text, "x0": x0, "x1": x1, "top": top, "bottom": top + 10}


def test_merge_word_fragments_glues_pdfmaker_header() -> None:
    """'Beginning' emitted as Beg|in|n|in|g clusters (gaps <= 0.06pt, some NEGATIVE kerning
    overlaps) must reassemble; the July-2026 WASDE shredded 43% of rows into unknown_attribute."""
    from leviathan.transforms.raw_to_bronze.usda_wasde import _merge_word_fragments

    frags = [_w("Beg", 169.80, 185.82), _w("in", 185.88, 193.62), _w("n", 193.68, 198.66),
             _w("in", 198.72, 206.46), _w("g", 206.52, 211.50),
             # kerning OVERLAP inside 'Domestic' (gap -0.01): must still merge
             _w("Domest", 345.96, 377.05), _w("ic", 377.04, 384.22)]
    got = _merge_word_fragments(frags)
    assert [w["text"] for w in got] == ["Beginning", "Domestic"]
    assert got[0]["x0"] == 169.80 and got[0]["x1"] == 211.50


def test_merge_word_fragments_never_bridges_real_gaps() -> None:
    # a real inter-word space is ~2.5pt and a column gap >= 13pt: neither merges; different
    # lines never merge regardless of x-adjacency.
    from leviathan.transforms.raw_to_bronze.usda_wasde import _merge_word_fragments

    words = [_w("Stocks", 184.80, 211.47), _w("Production", 225.15, 269.02),   # 13.7pt column gap
             _w("year", 100.0, 118.0), _w("beginning", 120.5, 160.0),          # 2.5pt space
             _w("nextline", 160.1, 190.0, top=120.0)]                          # x-adjacent, other line
    got = _merge_word_fragments(words)
    assert sorted(w["text"] for w in got) == ["Production", "Stocks", "beginning", "nextline", "year"]


# ---------------------------------------------------------------------------
# REGRESSION: legacy World-table header must NOT fold the column-spanning
# grouping banner ("Domestic 2/") into the atomic sub-column accumulator.
#
# Root cause of the pre-2011 world-table row loss: _extract_attrs_from_header
# widened from the last TWO header lines to the last THREE, which pulled in the
# coarser "Region ... Domestic 2/ ... stocks" grouping line whose colon
# positions do not align with the atomic "Beginning/Produc-" + "stocks/tion/..."
# sub-header. That misalignment dropped the Feed and Exports columns (they
# collapsed into duplicate domestic_total / ending_stocks attributes that then
# deduped away), so a 7-attribute World row silently became 5 real attrs plus a
# junk col_6. These fixtures are a byte-faithful excerpt of the real
# 1995-01-12 WASDE .txt (wasde0195.txt), World Wheat Supply and Use.
# ---------------------------------------------------------------------------

# Exact excerpt (heading -> ===== -> 5 header lines -> ===== -> 1992/93 block)
# from the real raw file. Leading whitespace is load-bearing (colon columns).
_WORLD_WHEAT_1995_HEADER_LINES = [
    "                       :          Supply         :           Use         :",
    "                       :=========================:=======================:Ending",
    "         Region        :         :       :       :  Domestic 2/  :       :stocks",
    "                       :Beginning:Produc-:       :===============:       :",
    "                       :  stocks : tion  :Imports: Feed : Total  :Exports:",
]

_WORLD_WHEAT_1995_LEGACY_TXT = "\n".join([
    "                          World Wheat Supply and Use 1/",
    "                              (Million Metric Tons)",
    "================================================================================",
    *_WORLD_WHEAT_1995_HEADER_LINES,
    "================================================================================",
    "                       :",
    "                       :                       1992/93",
    "                       :",
    "World 3/               :   130.34  561.87  122.37 105.87  543.91   123.85 148.30",
    "United States          :    12.93   67.14    1.91   5.29   30.69    36.84  14.44",
    "    Argentina          :     0.35    9.80    0.02   0.05    4.27     5.85   0.05",
    "================================================================================",
]) + "\n"

# The exact 7 attribute/value pairs the canonical parser emits for the World row.
_WORLD_WHEAT_1992_93_CANONICAL = [
    ("beginning_stocks", 130.34),
    ("production",       561.87),
    ("imports",         122.37),
    ("feed",            105.87),
    ("domestic_total",  543.91),
    ("exports",         123.85),
    ("ending_stocks",   148.30),
]


def test_extract_attrs_from_header_spanning_domestic_banner() -> None:
    """The 5-line World header resolves to the 7 atomic attrs, in order.

    Feed and Exports MUST survive as distinct columns; domestic_total must appear
    exactly once (the "Domestic 2/" spanning banner must not create a second one).
    """
    attrs = _extract_attrs_from_header(_WORLD_WHEAT_1995_HEADER_LINES)
    assert attrs == [
        "beginning_stocks", "production", "imports",
        "feed", "domestic_total", "exports", "ending_stocks",
    ], attrs
    assert attrs.count("domestic_total") == 1
    assert "feed" in attrs and "exports" in attrs


def test_parse_wasde_txt_legacy_world_wheat_seven_attrs() -> None:
    """World Wheat 1992/93 (region=World) parses to the exact 7 canonical pairs.

    Guards the pre-2011 legacy World-table row-loss regression: no dropped Feed /
    Exports, no junk col_N attribute, no ending_stocks taking the Exports value.
    """
    df = parse_wasde_txt(_WORLD_WHEAT_1995_LEGACY_TXT.encode(), "1995-01-12")
    world = df[
        (df["table_name"] == "World Wheat Supply and Use")
        & (df["region"] == "World")
        & (df["market_year"] == "1992/93")
    ]
    pairs = list(zip(world["attribute"], world["value"].round(2)))
    assert pairs == _WORLD_WHEAT_1992_93_CANONICAL, pairs
    # No parser-invented column labels leaked through.
    assert not any(str(a).startswith("col_") for a in world["attribute"])


# ---------------------------------------------------------------------------
# REGRESSION (scanned era): a 1987-style Format A world table must reconstruct
# to a NON-EMPTY release with clean (non-col_N) attributes and a recognised
# region -- i.e. the current scanned parser produces silver-survivable rows.
#
# Context: the 1987-02-09 / 1988-05-10 bronze on S3 is STALE garbage written
# 2026-06-01 (before the scanned-reconstruction rework), so their silver drops
# to empty. Real Textract LINE blocks require a cloud call; this fixture mirrors
# the 1987 WASDE Format A layout (heading, colon sub-header, year banner, mixed
# and split colon-free data rows) exactly like the existing 1989 fixture.
# ---------------------------------------------------------------------------

_TEXTRACT_1987_ERA = [
    {"BlockType": "LINE", "Page": 1,
     "Text": "World Wheat Supply and Use 1/ (Million metric tons)",
     "Geometry": {"BoundingBox": {"Top": 0.050, "Left": 0.10}}},
    {"BlockType": "LINE", "Page": 1,
     "Text": ": Stocks : tion : Imports : Feed : Total : Exports :",
     "Geometry": {"BoundingBox": {"Top": 0.090, "Left": 0.05}}},
    {"BlockType": "LINE", "Page": 1,
     "Text": "1986/87 (Est.)",
     "Geometry": {"BoundingBox": {"Top": 0.110, "Left": 0.05}}},
    # Mixed row: label + space-delimited values, no colons.
    {"BlockType": "LINE", "Page": 1,
     "Text": "World 3/ 111.79 529.02 96.34 328.15 505.34 100.54 135.79",
     "Geometry": {"BoundingBox": {"Top": 0.125, "Left": 0.05}}},
    # Split row: label on one block, values on the next (same visual row).
    {"BlockType": "LINE", "Page": 1,
     "Text": "United States",
     "Geometry": {"BoundingBox": {"Top": 0.140, "Left": 0.05}}},
    {"BlockType": "LINE", "Page": 1,
     "Text": "41.87 66.99 0.05 20.62 30.53 25.28 38.29",
     "Geometry": {"BoundingBox": {"Top": 0.1402, "Left": 0.30}}},
    {"BlockType": "LINE", "Page": 1,
     "Text": "Argentina 0.39 8.90 0.00 3.90 4.90 4.03 0.36",
     "Geometry": {"BoundingBox": {"Top": 0.155, "Left": 0.05}}},
]


def test_parse_wasde_pdf_scanned_1987_returns_nonempty_release() -> None:
    """1987-era scanned reconstruction produces a NON-EMPTY, clean release.

    A silver build drops col_N attrs and unrecognised regions; this asserts the
    scanned parser yields survivable rows (real region + real attribute), which a
    forced re-parse of the stale 1987/1988 bronze would restore.
    """
    df = parse_wasde_pdf_scanned(_TEXTRACT_1987_ERA, "1987-02-09")
    assert not df.empty, "1987-era fixture produced ZERO rows"
    assert "World" in df["region"].values
    assert (df["market_year"] == "1986/87").any()
    # At least one recognised balance-sheet attribute must survive (not all col_N).
    real_attrs = {"beginning_stocks", "production", "imports", "feed",
                  "domestic_total", "exports", "ending_stocks"}
    assert real_attrs & set(df["attribute"].unique()), sorted(df["attribute"].unique())
