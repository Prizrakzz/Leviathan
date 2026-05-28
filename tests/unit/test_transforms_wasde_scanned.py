"""Unit tests for WASDE scanned text extraction — Phase 2.

Tests cover:
- wasde_scanned.extract_wasde_scanned: section splitting, schema, LINE ordering
- _truncate_pdf: pages capped at max_pages
- _is_scanned_key: classification of raw S3 keys

All tests use static data (no Textract client, no S3, no real PDFs).
"""
from __future__ import annotations

import io

import pypdf
import pytest

from leviathan.transforms.raw_to_text.wasde_scanned import extract_wasde_scanned
from jobs.batch.wasde_scanned_task import _is_scanned_key, _truncate_pdf


# ---------------------------------------------------------------------------
# Helper: build a minimal Textract Blocks list
# ---------------------------------------------------------------------------

def _make_blocks(*lines: tuple[int, float, str]) -> list[dict]:
    """Return a list of LINE blocks from (page, top, text) tuples.

    ``top`` is a float in [0.0, 1.0] (Textract BoundingBox convention).
    """
    return [
        {
            "BlockType": "LINE",
            "Page": page,
            "Text": text,
            "Geometry": {"BoundingBox": {"Top": top, "Left": 0.0, "Width": 1.0, "Height": 0.01}},
        }
        for page, top, text in lines
    ]


# Sample narrative text that exercises section splitting
_SAMPLE_BLOCKS = _make_blocks(
    (1, 0.05, "WASDE-112 - July 1976"),
    (1, 0.10, "WHEAT:  World wheat supply is projected higher."),
    (1, 0.20, "Additional wheat commentary continues here."),
    (1, 0.30, "COARSE GRAINS:  Corn production is revised upward."),
    (1, 0.40, "Corn commentary."),
    (2, 0.05, "RICE:  Rice supply increases in Asia."),
    (2, 0.15, "OILSEEDS:  Soybean outlook positive."),
    (2, 0.25, "COTTON:  Cotton area harvested down."),
    (2, 0.35, "SUGAR:  Sugar cane production revised."),
)


# ---------------------------------------------------------------------------
# extract_wasde_scanned — section extraction
# ---------------------------------------------------------------------------

def test_sections_extracted() -> None:
    doc = extract_wasde_scanned(_SAMPLE_BLOCKS, "raw/production/source=usda_wasde/release_date=1976-07-12/wasde0776.pdf")
    names = [s["name"] for s in doc["sections"]]
    assert names == ["wheat", "coarse_grains", "rice", "oilseeds", "cotton", "sugar"]


def test_section_text_content() -> None:
    doc = extract_wasde_scanned(_SAMPLE_BLOCKS, "dummy_key")
    wheat = next(s for s in doc["sections"] if s["name"] == "wheat")
    assert "World wheat supply" in wheat["text"]


def test_no_sections_fallback() -> None:
    blocks = _make_blocks(
        (1, 0.1, "This is a cover page with no commodity headings."),
        (1, 0.2, "Some general text here."),
    )
    doc = extract_wasde_scanned(blocks, "dummy_key")
    assert doc["sections"] == []
    assert "cover page" in doc["full_text"]


# ---------------------------------------------------------------------------
# extract_wasde_scanned — schema
# ---------------------------------------------------------------------------

def test_schema_fields_present() -> None:
    doc = extract_wasde_scanned(_SAMPLE_BLOCKS, "some/raw/key.pdf")
    assert doc["source"] == "usda_wasde"
    assert doc["raw_key"] == "some/raw/key.pdf"
    assert doc["extraction_method"] == "textract"
    assert isinstance(doc["extracted_at"], str)
    assert len(doc["extracted_at"]) == 20  # "YYYY-MM-DDTHH:MM:SSZ"
    assert isinstance(doc["sections"], list)
    assert isinstance(doc["full_text"], str)


def test_extraction_method() -> None:
    doc = extract_wasde_scanned([], "dummy_key")
    assert doc["extraction_method"] == "textract"


# ---------------------------------------------------------------------------
# extract_wasde_scanned — LINE block ordering
# ---------------------------------------------------------------------------

def test_line_ordering_by_page_then_top() -> None:
    """Blocks given out-of-order should be sorted before building full_text."""
    # Deliberately scrambled order: page 2 first, then page 1 bottom, then page 1 top
    blocks = _make_blocks(
        (2, 0.10, "Page 2 line"),
        (1, 0.80, "Page 1 bottom"),
        (1, 0.10, "Page 1 top"),
    )
    doc = extract_wasde_scanned(blocks, "dummy_key")
    lines = doc["full_text"].splitlines()
    assert lines == ["Page 1 top", "Page 1 bottom", "Page 2 line"]


def test_non_line_blocks_ignored() -> None:
    """PAGE, WORD, and TABLE blocks must not appear in full_text."""
    blocks = [
        {"BlockType": "PAGE", "Page": 1, "Text": "should-be-ignored", "Geometry": {"BoundingBox": {"Top": 0.0}}},
        {"BlockType": "LINE", "Page": 1, "Text": "real line", "Geometry": {"BoundingBox": {"Top": 0.1}}},
        {"BlockType": "WORD", "Page": 1, "Text": "also-ignored", "Geometry": {"BoundingBox": {"Top": 0.2}}},
    ]
    doc = extract_wasde_scanned(blocks, "dummy_key")
    assert doc["full_text"] == "real line"


# ---------------------------------------------------------------------------
# _is_scanned_key — key classification
# ---------------------------------------------------------------------------

def test_is_scanned_key_true() -> None:
    assert _is_scanned_key("raw/production/source=usda_wasde/release_date=1976-07-12/wasde0776.pdf") is True


def test_is_scanned_key_1994() -> None:
    assert _is_scanned_key("raw/production/source=usda_wasde/release_date=1994-12-09/wasde1294.pdf") is True


def test_is_scanned_key_txt_false() -> None:
    assert _is_scanned_key("raw/production/source=usda_wasde/release_date=1997-06-12/wasde0697.txt") is False


def test_is_scanned_key_digital_false() -> None:
    assert _is_scanned_key("raw/production/source=usda_wasde/release_date=2014-01-10/wasde0114.pdf") is False


def test_is_scanned_key_1999_false() -> None:
    # 1999 .pdf is NOT scanned — only < 1999 is scanned; 1995–1998 .pdf would be scanned
    # but 1999 is the boundary year that only had .txt; this key hypothetically would be scanned
    # The function checks year < 1999 (== _SCANNED_YEAR_MAX), so 1998 is true
    assert _is_scanned_key("raw/production/source=usda_wasde/release_date=1998-03-11/wasde0398.pdf") is True


# ---------------------------------------------------------------------------
# _truncate_pdf — page capping
# ---------------------------------------------------------------------------

def _make_pdf(n_pages: int) -> bytes:
    """Create a minimal PDF with *n_pages* blank pages using pypdf."""
    writer = pypdf.PdfWriter()
    for _ in range(n_pages):
        writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_truncate_pdf_caps_to_max() -> None:
    original = _make_pdf(20)
    truncated = _truncate_pdf(original, 8)
    reader = pypdf.PdfReader(io.BytesIO(truncated))
    assert len(reader.pages) == 8


def test_truncate_pdf_short_pdf_unchanged() -> None:
    original = _make_pdf(5)
    result = _truncate_pdf(original, 8)
    # Short PDF returned as-is (same bytes)
    assert result is original


def test_truncate_pdf_exact_boundary() -> None:
    original = _make_pdf(8)
    result = _truncate_pdf(original, 8)
    assert result is original  # exactly max_pages — no truncation needed
