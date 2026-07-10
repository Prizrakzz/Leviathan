"""Unit tests for WAP Table 01 bronze extraction — Phase 3.

Tests cover:
- _unreverse_table_text: line-level character reversal
- _unreverse_table: cell-level reversal on 2D table array
- _parse_table01_rows: DataFrame shape, dtypes, commodity detection
- extract_table01: None fallback, archiveorg era routing
- table01_exists / write_table01: S3 interaction stubs

All tests use static in-memory data (no S3, no real PDFs).
"""
from __future__ import annotations

import io
import unittest.mock as mock

import pandas as pd
import pytest
from leviathan.transforms.raw_to_bronze.wap_table01 import (
    COUNTRY_COLUMNS,
    _parse_table01_rows,
    _try_float,
    _unreverse_table,
    _unreverse_table_text,
    extract_table01,
    table01_exists,
    write_table01,
)

# ---------------------------------------------------------------------------
# _unreverse_table_text
# ---------------------------------------------------------------------------

def test_unreverse_table_text_basic() -> None:
    text = "1 ELBAT\nyrammuS"
    result = _unreverse_table_text(text)
    assert result == "TABLE 1\nSummary"


def test_unreverse_table_text_roundtrip() -> None:
    original = "WHEAT\n100.5\nCoarse Grains"
    reversed_text = "\n".join(line[::-1] for line in original.splitlines())
    assert _unreverse_table_text(reversed_text) == original


def test_unreverse_table_text_empty() -> None:
    assert _unreverse_table_text("") == ""


def test_unreverse_table_text_single_line() -> None:
    assert _unreverse_table_text("TAEHW") == "WHEAT"


# ---------------------------------------------------------------------------
# _unreverse_table
# ---------------------------------------------------------------------------

def test_unreverse_table_cells() -> None:
    raw = [["TAEHW", "100,1", None], ["lebal", "5.001"]]
    result = _unreverse_table(raw)
    assert result[0][0] == "WHEAT"
    assert result[0][1] == "1,001"  # "100,1" reversed = "1,001"
    assert result[0][2] is None  # None preserved
    assert result[1][0] == "label"
    assert result[1][1] == "100.5"


def test_unreverse_table_preserves_none() -> None:
    raw = [[None, None]]
    result = _unreverse_table(raw)
    assert result == [[None, None]]


# ---------------------------------------------------------------------------
# _try_float
# ---------------------------------------------------------------------------

def test_try_float_plain() -> None:
    assert _try_float("100.5") == pytest.approx(100.5)


def test_try_float_with_comma() -> None:
    assert _try_float("1,000") == pytest.approx(1000.0)


def test_try_float_empty() -> None:
    assert _try_float("") is None


def test_try_float_text() -> None:
    assert _try_float("n/a") is None


def test_try_float_none_input() -> None:
    assert _try_float(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _parse_table01_rows
# ---------------------------------------------------------------------------

def _make_raw_table(n_rows_per_commodity: int = 3) -> list[list[str | None]]:
    """Build a synthetic 2D table matching WAP Table 01 structure."""
    commodities = ["WHEAT", "COARSE GRAINS", "RICE", "TOTAL GRAINS", "OILSEEDS", "COTTON"]
    table: list[list[str | None]] = []

    # Header rows (ignored by parser)
    table.append(["Commodity", "World", "Total Foreign", "US"] + [""] * (len(COUNTRY_COLUMNS) - 3))

    for commodity in commodities:
        table.append([commodity] + [None] * len(COUNTRY_COLUMNS))
        for i in range(n_rows_per_commodity):
            row_label = f"2024/25 {'Jun' if i == 0 else 'Jul'}"
            values = [str(100.0 + i + j * 10.0) for j in range(len(COUNTRY_COLUMNS))]
            table.append([row_label] + values)

    return table


def test_parse_table01_rows_shape() -> None:
    raw_table = _make_raw_table(n_rows_per_commodity=3)
    df = _parse_table01_rows(raw_table, "2026-05", "raw/key.pdf")
    assert df is not None
    # 6 commodities × 3 rows each = 18 rows
    assert len(df) == 18
    assert set(COUNTRY_COLUMNS).issubset(df.columns)


def test_parse_table01_rows_columns() -> None:
    raw_table = _make_raw_table()
    df = _parse_table01_rows(raw_table, "2026-05", "raw/key.pdf")
    assert df is not None
    assert "release_month" in df.columns
    assert "raw_key" in df.columns
    assert "commodity" in df.columns
    assert "row_label" in df.columns


def test_parse_table01_rows_metadata() -> None:
    raw_table = _make_raw_table()
    df = _parse_table01_rows(raw_table, "2026-05", "raw/production/source=usda_wap/release_month=2026-05/production.pdf")
    assert df is not None
    assert (df["release_month"] == "2026-05").all()
    assert df["raw_key"].iloc[0] == "raw/production/source=usda_wap/release_month=2026-05/production.pdf"


def test_parse_table01_rows_commodity_slugs() -> None:
    raw_table = _make_raw_table()
    df = _parse_table01_rows(raw_table, "2026-05", "key")
    assert df is not None
    assert set(df["commodity"].unique()) == {"wheat", "coarse_grains", "rice", "total_grains", "oilseeds", "cotton"}


def test_parse_table01_rows_numeric_dtypes() -> None:
    raw_table = _make_raw_table()
    df = _parse_table01_rows(raw_table, "2026-05", "key")
    assert df is not None
    for col in COUNTRY_COLUMNS:
        assert pd.api.types.is_float_dtype(df[col])


def test_parse_table01_rows_none_on_empty() -> None:
    result = _parse_table01_rows([], "2026-05", "key")
    assert result is None


def test_parse_table01_rows_none_when_no_commodities() -> None:
    # Table with no recognizable commodity headers
    raw = [["Area Harv.", "100", "95", "5"] + ["0"] * (len(COUNTRY_COLUMNS) - 3)]
    result = _parse_table01_rows(raw, "2026-05", "key")
    assert result is None


# ---------------------------------------------------------------------------
# extract_table01 — None fallbacks
# ---------------------------------------------------------------------------

def test_extract_table01_returns_none_when_pdfplumber_finds_no_table(monkeypatch) -> None:
    class _FakePage:
        def extract_text(self):
            # Return text that contains all TABLE01_MARKERS so the page is found,
            # then extract_table returns None → function must return None.
            return "Wheat Coarse Grains Oilseeds Cotton World Production"

        def extract_table(self):
            return None

    class _FakePdf:
        pages = [_FakePage()] * 8

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("pdfplumber.open", lambda *a, **kw: _FakePdf())
    result = extract_table01(b"fake", "2026-05", "key")
    assert result is None


def test_extract_table01_returns_none_when_too_few_pages(monkeypatch) -> None:
    class _FakePdf:
        pages = []  # empty PDF

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("pdfplumber.open", lambda *a, **kw: _FakePdf())
    result = extract_table01(b"fake", "2026-05", "key")
    assert result is None


def test_extract_table01_archiveorg_era_applies_unreverse(monkeypatch) -> None:
    """For pre-2002 PDFs, cell text is un-reversed before parsing."""
    # Build a table where all text is reversed
    raw_table = [
        ["TAEHW"] + [None] * len(COUNTRY_COLUMNS),
        ["lebaL"] + ["5.001"] * len(COUNTRY_COLUMNS),
    ]

    class _FakePage:
        def extract_table(self):
            return raw_table

    class _FakePdf:
        pages = [object()] * 6 + [_FakePage()]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("pdfplumber.open", lambda *a, **kw: _FakePdf())
    result = extract_table01(b"fake", "2001-09", "key")
    assert result is not None
    assert result.iloc[0]["commodity"] == "wheat"
    assert result.iloc[0]["world"] == pytest.approx(100.5)


# ---------------------------------------------------------------------------
# table01_exists / write_table01 — S3 stubs
# ---------------------------------------------------------------------------

def test_table01_exists_true() -> None:
    s3 = mock.Mock()
    s3.head_object.return_value = {}
    assert table01_exists(s3, "my-bucket", "some/key.parquet") is True
    s3.head_object.assert_called_once_with(Bucket="my-bucket", Key="some/key.parquet")


def test_table01_exists_false() -> None:
    from botocore.exceptions import ClientError

    s3 = mock.Mock()
    s3.head_object.side_effect = ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
    assert table01_exists(s3, "my-bucket", "some/key.parquet") is False


def test_write_table01_calls_put_object() -> None:
    s3 = mock.Mock()
    df = pd.DataFrame({"release_month": ["2026-05"], "world": [100.0]})
    write_table01(s3, "my-bucket", "some/key.parquet", df)
    s3.put_object.assert_called_once()
    call_kwargs = s3.put_object.call_args[1]
    assert call_kwargs["Bucket"] == "my-bucket"
    assert call_kwargs["Key"] == "some/key.parquet"
    assert isinstance(call_kwargs["Body"], bytes)
    assert len(call_kwargs["Body"]) > 0
