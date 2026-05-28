"""Unit tests for WAP PDF text extraction — Phase 3 (sources A and B).

Tests cover:
- extract_wap_pdf: section extraction, schema fields, empty-section fallback
- _is_archiveorg_era: era classification based on release_month year

All tests use static in-memory data (no S3, no real PDFs).
"""
from __future__ import annotations

import io

import pdfplumber
import pytest
from pypdf import PdfWriter

from leviathan.transforms.raw_to_text.wap_pdf import (
    _is_archiveorg_era,
    extract_wap_pdf,
)


# ---------------------------------------------------------------------------
# _is_archiveorg_era
# ---------------------------------------------------------------------------

def test_archiveorg_era_1988() -> None:
    assert _is_archiveorg_era("1988-05") is True


def test_archiveorg_era_2001() -> None:
    assert _is_archiveorg_era("2001-12") is True


def test_archiveorg_era_2002() -> None:
    assert _is_archiveorg_era("2002-08") is False


def test_archiveorg_era_2026() -> None:
    assert _is_archiveorg_era("2026-05") is False


# ---------------------------------------------------------------------------
# Helpers: build a minimal in-memory PDF with text pages
# ---------------------------------------------------------------------------

def _make_pdf_bytes(page_texts: list[str]) -> bytes:
    """Return bytes for a minimal PDF with one text layer per page.

    Uses pypdf PdfWriter with blank pages; the text content is not embedded
    as a searchable text layer (pypdf doesn't support adding text streams to
    blank pages in this API).  For tests that rely on pdfplumber text
    extraction we use a different approach: patch ``pdfplumber.open``.
    """
    writer = PdfWriter()
    for _ in page_texts:
        writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# extract_wap_pdf — schema fields
# ---------------------------------------------------------------------------

def test_schema_fields(monkeypatch) -> None:
    """extract_wap_pdf returns all required DocumentJson fields."""
    page_text = (
        "WHEAT:  U.S. wheat production is revised upward by 50 million bushels.\n"
        "Export demand remains firm.\n"
        "COARSE GRAINS:  Corn production in Ukraine is reduced.\n"
        "RICE:  Thailand exports unchanged.\n"
    )

    class _FakePage:
        def extract_text(self):
            return page_text

    class _FakePdf:
        pages = [_FakePage()] * 7

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("pdfplumber.open", lambda *a, **kw: _FakePdf())

    doc = extract_wap_pdf(b"fake", "raw/production/source=usda_wap/release_month=2026-05/production.pdf", "2026-05")

    assert doc["source"] == "usda_wap"
    assert doc["raw_key"] == "raw/production/source=usda_wap/release_month=2026-05/production.pdf"
    assert doc["extraction_method"] == "pdfplumber"
    assert isinstance(doc["extracted_at"], str)
    assert len(doc["extracted_at"]) == 20  # "YYYY-MM-DDTHH:MM:SSZ"
    assert isinstance(doc["sections"], list)
    assert isinstance(doc["full_text"], str)


def test_sections_split(monkeypatch) -> None:
    """Sections are correctly split from page text."""
    page_texts = [
        "WHEAT:  World wheat supply is projected higher for 2026/27.\n",
        "COARSE GRAINS:  Corn production in Brazil is raised.\n",
        "RICE:  Rice ending stocks are tightened.\n",
        "",
        "",
        "",
    ]

    class _FakePage:
        def __init__(self, text):
            self._text = text

        def extract_text(self):
            return self._text

    class _FakePdf:
        pages = [_FakePage(t) for t in page_texts]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("pdfplumber.open", lambda *a, **kw: _FakePdf())

    doc = extract_wap_pdf(b"fake", "dummy_key", "2026-05")
    names = [s["name"] for s in doc["sections"]]
    assert "wheat" in names
    assert "coarse_grains" in names
    assert "rice" in names


def test_sections_empty_fallback(monkeypatch) -> None:
    """When no commodity headings found, sections is empty but full_text populated."""

    class _FakePage:
        def extract_text(self):
            return "Cover page with no commodity sections."

    class _FakePdf:
        pages = [_FakePage()] * 7

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("pdfplumber.open", lambda *a, **kw: _FakePdf())

    doc = extract_wap_pdf(b"fake", "dummy_key", "2026-05")
    assert doc["sections"] == []
    assert "Cover page" in doc["full_text"]


def test_pages_limited_to_six(monkeypatch) -> None:
    """Only pages 0–5 (6 pages) are extracted; page 6+ is not read."""
    read_pages: list[int] = []

    class _FakePage:
        def __init__(self, idx):
            self._idx = idx

        def extract_text(self):
            read_pages.append(self._idx)
            return ""

    class _FakePdf:
        pages = [_FakePage(i) for i in range(20)]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("pdfplumber.open", lambda *a, **kw: _FakePdf())

    extract_wap_pdf(b"fake", "dummy_key", "2026-05")
    assert max(read_pages) <= 5
    assert len(read_pages) == 6
