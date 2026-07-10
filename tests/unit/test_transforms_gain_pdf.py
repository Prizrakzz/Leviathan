"""Unit tests for GAIN PDF text extraction.

Tests cover:
- extract_gain_pdf: schema fields, blank page filtering, boilerplate filtering,
  no page-range cap, single "full" section output

All tests use static in-memory data (no S3, no real PDFs).
"""
from __future__ import annotations

import pytest
from leviathan.transforms.raw_to_text.gain_pdf import (
    _BLANK_THRESHOLD,
    _is_boilerplate,
    extract_gain_pdf,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_pdf(page_texts: list[str]):
    """Return a context-manager mock that yields a fake pdfplumber PDF."""

    class _FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class _FakePdf:
        def __init__(self, texts: list[str]) -> None:
            self.pages = [_FakePage(t) for t in texts]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    return _FakePdf(page_texts)


# ---------------------------------------------------------------------------
# _is_boilerplate
# ---------------------------------------------------------------------------

def test_boilerplate_pure_footer() -> None:
    """A page containing only the FAS footer is boilerplate."""
    assert _is_boilerplate("USDA Foreign Agricultural Service") is True


def test_boilerplate_footer_with_whitespace() -> None:
    assert _is_boilerplate("  USDA Foreign Agricultural Service  \n") is True


def test_boilerplate_substantive_page() -> None:
    """A page with real content is not boilerplate even if footer appears."""
    text = (
        "Brazil Grain and Feed Annual\n"
        "Production is forecast to rise 5% due to favourable rainfall.\n"
        "USDA Foreign Agricultural Service\n"
    )
    assert _is_boilerplate(text) is False


# ---------------------------------------------------------------------------
# extract_gain_pdf — schema fields
# ---------------------------------------------------------------------------

def test_schema_fields(monkeypatch) -> None:
    """extract_gain_pdf returns all required DocumentJson fields."""
    page_text = (
        "Brazil: Corn and Soybean Annual\n"
        "Corn production is forecast at 127 MMT, up 3% from last year.\n"
        "Favourable weather during the second crop window supported yields.\n"
    )
    monkeypatch.setattr(
        "pdfplumber.open", lambda *a, **kw: _make_pdf([page_text])
    )

    raw_key = (
        "raw/production/source=usda_gain_corn/"
        "country=BR/publication_date=20260401/Brazil_Grain_and_Feed_Annual.pdf"
    )
    doc = extract_gain_pdf(b"fake", raw_key, "usda_gain_corn")

    assert doc["source"] == "usda_gain_corn"
    assert doc["raw_key"] == raw_key
    assert doc["extraction_method"] == "pdfplumber"
    assert isinstance(doc["extracted_at"], str)
    assert len(doc["extracted_at"]) == 20  # "YYYY-MM-DDTHH:MM:SSZ"
    assert isinstance(doc["sections"], list)
    assert isinstance(doc["full_text"], str)
    assert len(doc["full_text"]) > 0


# ---------------------------------------------------------------------------
# extract_gain_pdf — blank page filtering
# ---------------------------------------------------------------------------

def test_blank_page_filtered(monkeypatch) -> None:
    """Pages with fewer than _BLANK_THRESHOLD stripped characters are excluded."""
    short = "x" * (_BLANK_THRESHOLD - 1)  # just below threshold
    substantive = "A" * 200 + " Brazil corn production is rising strongly."
    monkeypatch.setattr(
        "pdfplumber.open", lambda *a, **kw: _make_pdf([short, substantive, short])
    )

    doc = extract_gain_pdf(b"fake", "dummy_key", "usda_gain_corn")
    # Only the substantive page text should appear
    assert short not in doc["full_text"]
    assert "Brazil corn production" in doc["full_text"]


def test_fully_blank_pdf_returns_empty_sections(monkeypatch) -> None:
    """A PDF with only blank pages produces empty sections and empty full_text."""
    monkeypatch.setattr(
        "pdfplumber.open", lambda *a, **kw: _make_pdf(["   ", "", "  \n  "])
    )

    doc = extract_gain_pdf(b"fake", "dummy_key", "usda_gain_wheat")
    assert doc["sections"] == []
    assert doc["full_text"] == ""


# ---------------------------------------------------------------------------
# extract_gain_pdf — boilerplate footer filtering
# ---------------------------------------------------------------------------

def test_boilerplate_footer_filtered(monkeypatch) -> None:
    """A last page that is only the FAS footer is excluded from full_text."""
    substantive = "Ukraine wheat production is revised downward due to dry conditions."
    footer = "USDA Foreign Agricultural Service"
    monkeypatch.setattr(
        "pdfplumber.open", lambda *a, **kw: _make_pdf([substantive, footer])
    )

    doc = extract_gain_pdf(b"fake", "dummy_key", "usda_gain_wheat")
    assert "USDA Foreign Agricultural Service" not in doc["full_text"]
    assert "Ukraine wheat" in doc["full_text"]


# ---------------------------------------------------------------------------
# extract_gain_pdf — no page-range cap
# ---------------------------------------------------------------------------

def test_all_pages_read(monkeypatch) -> None:
    """All 12 pages of a fake PDF are attempted — no artificial page cap."""
    read_indices: list[int] = []

    class _TrackedPage:
        def __init__(self, idx: int) -> None:
            self._idx = idx

        def extract_text(self) -> str:
            read_indices.append(self._idx)
            return "A" * 200 + f" page {self._idx} content narrative text here."

    class _TrackedPdf:
        pages = [_TrackedPage(i) for i in range(12)]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("pdfplumber.open", lambda *a, **kw: _TrackedPdf())

    extract_gain_pdf(b"fake", "dummy_key", "usda_gain_coffee")
    assert len(read_indices) == 12
    assert max(read_indices) == 11


# ---------------------------------------------------------------------------
# extract_gain_pdf — single "full" section
# ---------------------------------------------------------------------------

def test_single_full_section(monkeypatch) -> None:
    """sections always contains exactly one entry with name=="full"."""
    page_text = (
        "France: Wheat Annual\n"
        "Soft wheat area harvested is expected to decline 4% as farmers "
        "switch to rapeseed in response to higher crush margins.\n"
    )
    monkeypatch.setattr(
        "pdfplumber.open", lambda *a, **kw: _make_pdf([page_text])
    )

    doc = extract_gain_pdf(b"fake", "dummy_key", "usda_gain_wheat")
    assert len(doc["sections"]) == 1
    assert doc["sections"][0]["name"] == "full"
    assert doc["sections"][0]["text"] == doc["full_text"]
