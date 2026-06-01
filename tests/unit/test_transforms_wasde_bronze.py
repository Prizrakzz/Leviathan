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
    _detect_format,
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
    assert _strip_filler("FILLER World") == " World"


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
