"""Unit tests for the MPOB overview PDF → text/ transform.

Tests are pure Python — no S3/AWS dependencies.  pdfplumber is mocked to
avoid requiring real PDF bytes.
"""
from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import pytest
from leviathan.transforms.raw_to_text.mpob_pdf import (
    _MAX_NARRATIVE_PAGES,
    _clean_page,
    extract_mpob_overview,
)

# ---------------------------------------------------------------------------
# Tests: _clean_page
# ---------------------------------------------------------------------------


class TestCleanPage:
    def test_removes_page_header(self) -> None:
        text = "Overview of the Malaysian Oil Palm Industry 2015\n\nSome prose text."
        result = _clean_page(text)
        assert "Overview of the Malaysian Oil Palm Industry" not in result
        assert "Some prose text." in result

    def test_removes_page_header_case_insensitive(self) -> None:
        text = "overview of the malaysian oil palm industry 2012\nContent here."
        result = _clean_page(text)
        assert "overview" not in result.lower().split("\n")[0]

    def test_removes_economics_division_footer(self) -> None:
        text = "Good prose.\n12 Economics & Industry Development Division"
        result = _clean_page(text)
        assert "Economics & Industry Development Division" not in result
        assert "Good prose." in result

    def test_removes_mpob_board_footer(self) -> None:
        text = "Good prose.\nMalaysian Palm Oil Board"
        result = _clean_page(text)
        assert "Malaysian Palm Oil Board" not in result

    def test_removes_month_year_footer(self) -> None:
        text = "Some content.\nFeb 2015"
        result = _clean_page(text)
        assert "Feb 2015" not in result

    def test_collapses_multiple_blank_lines(self) -> None:
        text = "Para 1.\n\n\n\nPara 2."
        result = _clean_page(text)
        # Should not have 3+ consecutive newlines
        assert "\n\n\n" not in result

    def test_empty_string_returns_empty(self) -> None:
        assert _clean_page("") == ""

    def test_preserves_normal_prose(self) -> None:
        text = "The palm oil industry grew significantly in 2015.\nProduction reached record levels."
        result = _clean_page(text)
        assert "palm oil industry" in result
        assert "Production reached record levels" in result


# ---------------------------------------------------------------------------
# Tests: extract_mpob_overview (mocked pdfplumber)
# ---------------------------------------------------------------------------


def _make_mock_page(text: str) -> MagicMock:
    page = MagicMock()
    page.extract_text.return_value = text
    return page


class TestExtractMpobOverview:
    def test_returns_document_json_keys(self) -> None:
        pages = [_make_mock_page(f"Page {i} content with useful text.") for i in range(7)]
        mock_pdf = MagicMock()
        mock_pdf.pages = pages
        mock_pdf.__enter__ = lambda s: mock_pdf
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("leviathan.transforms.raw_to_text.mpob_pdf.pdfplumber") as mock_plumber:
            mock_plumber.open.return_value = mock_pdf
            doc = extract_mpob_overview(b"fake-pdf", "raw/test/overview.pdf")

        assert doc["source"] == "mpob"
        assert doc["raw_key"] == "raw/test/overview.pdf"
        assert doc["extraction_method"] == "pdfplumber"
        assert "extracted_at" in doc
        assert "sections" in doc
        assert "full_text" in doc

    def test_reads_only_first_five_pages(self) -> None:
        pages = [_make_mock_page(f"Content {i}.") for i in range(7)]
        mock_pdf = MagicMock()
        mock_pdf.pages = pages
        mock_pdf.__enter__ = lambda s: mock_pdf
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("leviathan.transforms.raw_to_text.mpob_pdf.pdfplumber") as mock_plumber:
            mock_plumber.open.return_value = mock_pdf
            doc = extract_mpob_overview(b"fake-pdf", "raw/test/overview.pdf")

        # Pages slice is pages[:5]; pages[5] and pages[6] (stats tables) must not be read.
        for i in range(_MAX_NARRATIVE_PAGES):
            pages[i].extract_text.assert_called_once()
        pages[5].extract_text.assert_not_called()
        pages[6].extract_text.assert_not_called()

    def test_single_overview_section(self) -> None:
        pages = [_make_mock_page("Narrative content.") for _ in range(7)]
        mock_pdf = MagicMock()
        mock_pdf.pages = pages
        mock_pdf.__enter__ = lambda s: mock_pdf
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("leviathan.transforms.raw_to_text.mpob_pdf.pdfplumber") as mock_plumber:
            mock_plumber.open.return_value = mock_pdf
            doc = extract_mpob_overview(b"fake-pdf", "raw/test/overview.pdf")

        assert len(doc["sections"]) == 1
        assert doc["sections"][0]["name"] == "overview"

    def test_section_text_matches_full_text(self) -> None:
        pages = [_make_mock_page("Some content.") for _ in range(7)]
        mock_pdf = MagicMock()
        mock_pdf.pages = pages
        mock_pdf.__enter__ = lambda s: mock_pdf
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("leviathan.transforms.raw_to_text.mpob_pdf.pdfplumber") as mock_plumber:
            mock_plumber.open.return_value = mock_pdf
            doc = extract_mpob_overview(b"fake-pdf", "raw/test/overview.pdf")

        assert doc["sections"][0]["text"] == doc["full_text"]

    def test_strips_headers_footers_from_output(self) -> None:
        pages = [
            _make_mock_page(
                "Overview of the Malaysian Oil Palm Industry 2015\n"
                "The industry expanded in 2015.\n"
                "Malaysian Palm Oil Board\nFeb 2015"
            )
            for _ in range(7)
        ]
        mock_pdf = MagicMock()
        mock_pdf.pages = pages
        mock_pdf.__enter__ = lambda s: mock_pdf
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("leviathan.transforms.raw_to_text.mpob_pdf.pdfplumber") as mock_plumber:
            mock_plumber.open.return_value = mock_pdf
            doc = extract_mpob_overview(b"fake-pdf", "raw/test/overview.pdf")

        assert "Overview of the Malaysian Oil Palm Industry" not in doc["full_text"]
        assert "Malaysian Palm Oil Board" not in doc["full_text"]
        assert "The industry expanded" in doc["full_text"]

    def test_empty_pages_produces_empty_sections(self) -> None:
        pages = [_make_mock_page("") for _ in range(7)]
        mock_pdf = MagicMock()
        mock_pdf.pages = pages
        mock_pdf.__enter__ = lambda s: mock_pdf
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("leviathan.transforms.raw_to_text.mpob_pdf.pdfplumber") as mock_plumber:
            mock_plumber.open.return_value = mock_pdf
            doc = extract_mpob_overview(b"fake-pdf", "raw/test/overview.pdf")

        assert doc["sections"] == []
        assert doc["full_text"] == ""

    def test_works_with_fewer_than_five_pages(self) -> None:
        """PDF with only 3 pages should not raise an error."""
        pages = [_make_mock_page("Short doc.") for _ in range(3)]
        mock_pdf = MagicMock()
        mock_pdf.pages = pages
        mock_pdf.__enter__ = lambda s: mock_pdf
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("leviathan.transforms.raw_to_text.mpob_pdf.pdfplumber") as mock_plumber:
            mock_plumber.open.return_value = mock_pdf
            doc = extract_mpob_overview(b"fake-pdf", "raw/test/overview.pdf")

        assert len(doc["sections"]) == 1
