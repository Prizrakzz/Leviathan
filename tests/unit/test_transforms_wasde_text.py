"""Unit tests for WASDE text extraction — Phase 1.

Tests cover:
- wasde_digital.extract_wasde_digital: section splitting, schema
- wasde_txt.extract_wasde_txt: HDR stripping, section splitting, schema
- writer.document_exists: S3 head_object mock (exists / not-found / error)
- writer.write_document: S3 put_object mock, ContentType, compact JSON
- paths.text_wasde_key: key format
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from leviathan.storage.paths import text_wasde_key
from leviathan.transforms.raw_to_text.wasde_txt import _split_sections, extract_wasde_txt
from leviathan.transforms.raw_to_text.writer import document_exists, write_document

# ---------------------------------------------------------------------------
# paths.text_wasde_key
# ---------------------------------------------------------------------------

def test_text_wasde_key_format() -> None:
    key = text_wasde_key("2026-05-12")
    assert key == "text/source=usda_wasde/release_date=2026-05-12/document.json"


def test_text_wasde_key_historical() -> None:
    key = text_wasde_key("1995-01-12")
    assert key == "text/source=usda_wasde/release_date=1995-01-12/document.json"


# ---------------------------------------------------------------------------
# wasde_txt — section splitting
# ---------------------------------------------------------------------------

_SAMPLE_TXT = """\
WASDE-313 - April 11, 1996

WHEAT:  Projected U.S. 1995/96 wheat ending stocks are raised 15 million
bushels.  Exports are lowered.

COARSE GRAINS:  U.S. 1995/96 corn ending stocks are unchanged at 426 million
bushels.

RICE:  U.S. 1995/96 rice ending stocks are raised to 28.5 million cwt.

OILSEEDS:  U.S. 1995/96 soybean ending stocks are unchanged at 290 million
bushels.

COTTON:  U.S. 1995/96 cotton ending stocks are raised 200,000 bales.

SUGAR:  U.S. 1995/96 sugar ending stocks are projected at 1.650 million short
tons raw value.
"""


def test_txt_extract_sections_count() -> None:
    raw_key = "raw/production/source=usda_wasde/release_date=1996-04-11/wasde0496.txt"
    doc = extract_wasde_txt(_SAMPLE_TXT.encode("latin-1"), raw_key)

    assert len(doc["sections"]) == 6
    names = [s["name"] for s in doc["sections"]]
    assert names == ["wheat", "coarse_grains", "rice", "oilseeds", "cotton", "sugar"]


def test_txt_extract_section_text_content() -> None:
    raw_key = "raw/production/source=usda_wasde/release_date=1996-04-11/wasde0496.txt"
    doc = extract_wasde_txt(_SAMPLE_TXT.encode("latin-1"), raw_key)

    wheat = next(s for s in doc["sections"] if s["name"] == "wheat")
    assert "Projected U.S. 1995/96" in wheat["text"]


def test_txt_extract_schema_fields() -> None:
    raw_key = "raw/production/source=usda_wasde/release_date=1996-04-11/wasde0496.txt"
    doc = extract_wasde_txt(_SAMPLE_TXT.encode("latin-1"), raw_key)

    assert doc["source"] == "usda_wasde"
    assert doc["raw_key"] == raw_key
    assert doc["extraction_method"] == "txt_decode"
    assert doc["extracted_at"].endswith("Z")
    assert len(doc["full_text"]) > 0


def test_txt_extract_full_text_not_empty() -> None:
    raw_key = "raw/production/source=usda_wasde/release_date=1996-04-11/wasde0496.txt"
    doc = extract_wasde_txt(_SAMPLE_TXT.encode("latin-1"), raw_key)
    assert "WHEAT:" in doc["full_text"]


# ---------------------------------------------------------------------------
# wasde_txt — HDR header stripping
# ---------------------------------------------------------------------------

_HDR_TXT = (
    "HDR101380000002          WASDE - NARRATIVE\n"
    + _SAMPLE_TXT
)


def test_txt_strips_hdr_line() -> None:
    raw_key = "raw/production/source=usda_wasde/release_date=1995-01-12/wasde0195.txt"
    doc = extract_wasde_txt(_HDR_TXT.encode("latin-1"), raw_key)

    assert "HDR" not in doc["full_text"].split("\n")[0]
    assert len(doc["sections"]) == 6


def test_txt_no_hdr_unaffected() -> None:
    raw_key = "raw/production/source=usda_wasde/release_date=1996-04-11/wasde0496.txt"
    doc_plain = extract_wasde_txt(_SAMPLE_TXT.encode("latin-1"), raw_key)
    doc_hdr   = extract_wasde_txt(_HDR_TXT.encode("latin-1"), raw_key)

    # Both should produce the same sections regardless of HDR presence
    assert [s["name"] for s in doc_plain["sections"]] == [s["name"] for s in doc_hdr["sections"]]


# ---------------------------------------------------------------------------
# wasde_txt — no-section fallback
# ---------------------------------------------------------------------------

def test_txt_no_sections_returns_empty_list() -> None:
    raw_key = "raw/production/source=usda_wasde/release_date=1996-01-01/wasde0196.txt"
    plain_text = "This file has no commodity headings at all.\n"
    doc = extract_wasde_txt(plain_text.encode("latin-1"), raw_key)

    assert doc["sections"] == []
    assert len(doc["full_text"]) > 0


# ---------------------------------------------------------------------------
# wasde_digital — section splitting (pure text, no PDF needed)
# ---------------------------------------------------------------------------

from leviathan.transforms.raw_to_text.wasde_digital import _split_sections as _split_digital


def test_digital_split_sections_six_commodities() -> None:
    text = """\
WORLD AGRICULTURAL SUPPLY AND DEMAND ESTIMATES

WHEAT: U.S. wheat supplies for 2026/27 are projected higher.

COARSE GRAINS: U.S. corn supplies for 2026/27 are projected at 16.2 billion.

RICE: U.S. rice supplies for 2026/27 are projected at 296 million cwt.

OILSEEDS: U.S. soybean supplies for 2026/27 are projected at 4.50 billion.

COTTON: U.S. cotton supplies for 2026/27 are projected higher.

SUGAR: U.S. sugar supplies for 2026/27 are projected at 14.2 million short tons.
"""
    sections = _split_digital(text)
    assert len(sections) == 6
    names = [s["name"] for s in sections]
    assert "wheat" in names
    assert "coarse_grains" in names


def test_digital_split_no_headings_returns_empty() -> None:
    sections = _split_digital("No commodity headings in this text.")
    assert sections == []


# ---------------------------------------------------------------------------
# wasde_digital — page window (D14: the 7-page cap is GONE)
# ---------------------------------------------------------------------------
#
# WHY these tests read every page: `_MAX_PAGE = 7` was removed on 2026-08-19 (D14).  Its stated
# premise — "pages 7+ are redundant with PSD CSV data" — was measured false on release 2026-05-12:
# the PDF yields 108,844 extractable chars over 40 pages against a stored full_text of 27,262
# (25.0%), and the livestock / dairy / egg / reliability tables that live past page 7 exist in NO
# other layer (silver/wasde is crops-only).  The same release lost its COTTON *narrative* section to
# the window as well.  A test that pins a 7-page read would pin the defect.

from leviathan.transforms.raw_to_text.wasde_digital import extract_wasde_digital


def _mock_page(text: str) -> MagicMock:
    page = MagicMock()
    page.extract_text.return_value = text
    return page


def _mock_pdf(pages: list) -> MagicMock:
    pdf = MagicMock()
    pdf.pages = pages
    pdf.__enter__ = lambda s: pdf
    pdf.__exit__ = MagicMock(return_value=False)
    return pdf


def _extract_with_pages(pages: list) -> dict:
    with patch("leviathan.transforms.raw_to_text.wasde_digital.pdfplumber") as plumber:
        plumber.open.return_value = _mock_pdf(pages)
        return extract_wasde_digital(b"fake-pdf", "raw/production/source=usda_wasde/"
                                                  "release_date=2026-05-12/wasde0526.pdf")


def test_digital_reads_every_page_past_seven() -> None:
    """D14: a 40-page release is parsed in full — no page is skipped, none is read twice."""
    pages = [_mock_page(f"PAGE {i} body text for the release.") for i in range(40)]
    doc = _extract_with_pages(pages)

    for i, page in enumerate(pages):
        page.extract_text.assert_called_once()
        assert f"PAGE {i} body" in doc["full_text"]


def test_digital_full_text_keeps_the_livestock_block() -> None:
    """The block D14 was ratified to recover: page 31+ tables that are in no other layer."""
    pages = [_mock_page(f"Narrative page {i}.") for i in range(7)]
    pages += [_mock_page("filler") for _ in range(23)]
    pages.append(_mock_page("U.S. Quarterly Animal Product Production\nBeef 6,905 Pork 7,012"))
    pages.append(_mock_page("Reliability Tables\nCorn yield 90-percent interval"))
    doc = _extract_with_pages(pages)

    assert "U.S. Quarterly Animal Product Production" in doc["full_text"]
    assert "Reliability Tables" in doc["full_text"]


def test_digital_sections_survive_a_full_length_document() -> None:
    """_split_sections is heading-driven, so the appendix table zone neither breaks it nor invents a
    section: the six commodity sections still split, and the tables ride whichever section precedes
    them (here the last one; on the real 2026-05-12 release it is `sugar`, with COTTON after)."""
    narrative = [
        _mock_page("WORLD AGRICULTURAL SUPPLY AND DEMAND ESTIMATES"),
        _mock_page("WHEAT: U.S. wheat supplies for 2026/27 are projected higher."),
        _mock_page("COARSE GRAINS: U.S. corn supplies for 2026/27 are raised."),
        _mock_page("RICE: U.S. rice supplies for 2026/27 are lowered."),
        _mock_page("OILSEEDS: U.S. soybean supplies for 2026/27 are unchanged."),
        _mock_page("COTTON: U.S. cotton supplies for 2026/27 are projected higher."),
        _mock_page("SUGAR: U.S. sugar supplies for 2026/27 are raised."),
    ]
    tables = [_mock_page(f"World Wheat Supply and Use  table page {i}\n2025/26 776.1 777.9")
              for i in range(33)]
    doc = _extract_with_pages(narrative + tables)

    names = [s["name"] for s in doc["sections"]]
    assert names == ["wheat", "coarse_grains", "rice", "oilseeds", "cotton", "sugar"]
    sugar = doc["sections"][-1]["text"]
    assert "table page 32" in sugar                      # appendix rides the last section, not lost
    assert len(doc["full_text"]) > len("".join(p.extract_text.return_value for p in narrative))


def test_digital_short_pdf_unaffected() -> None:
    """A 3-page release (the historical short form) still parses — removing the cap is not a floor."""
    doc = _extract_with_pages([_mock_page("WHEAT: supplies are higher."),
                               _mock_page("COTTON: supplies are lower."),
                               _mock_page("")])
    assert [s["name"] for s in doc["sections"]] == ["wheat", "cotton"]
    assert doc["extraction_method"] == "pdfplumber"


# ---------------------------------------------------------------------------
# writer.document_exists
# ---------------------------------------------------------------------------

from botocore.exceptions import ClientError


def _make_s3_mock(*, status_code: int | None = None, raise_exc: bool = False) -> MagicMock:
    """Build a mock S3 client for head_object."""
    s3 = MagicMock()
    if raise_exc:
        error_response = {"Error": {"Code": "500"}, "ResponseMetadata": {"HTTPStatusCode": 500}}
        s3.head_object.side_effect = ClientError(error_response, "HeadObject")
    elif status_code == 404:
        error_response = {"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}}
        s3.head_object.side_effect = ClientError(error_response, "HeadObject")
    else:
        s3.head_object.return_value = {"ContentLength": 100}
    return s3


def test_document_exists_true() -> None:
    s3 = _make_s3_mock()
    assert document_exists(s3, "bucket", "text/source=usda_wasde/release_date=2026-05-12/document.json") is True


def test_document_exists_false_on_404() -> None:
    s3 = _make_s3_mock(status_code=404)
    assert document_exists(s3, "bucket", "text/source=usda_wasde/release_date=2026-05-12/document.json") is False


def test_document_exists_reraises_non_404() -> None:
    s3 = _make_s3_mock(raise_exc=True)
    with pytest.raises(Exception):
        document_exists(s3, "bucket", "text/source=usda_wasde/release_date=2026-05-12/document.json")


# ---------------------------------------------------------------------------
# writer.write_document
# ---------------------------------------------------------------------------

def test_write_document_content_type() -> None:
    s3 = MagicMock()
    doc = {
        "source": "usda_wasde",
        "raw_key": "raw/production/source=usda_wasde/release_date=2026-05-12/wasde0526.pdf",
        "extraction_method": "pdfplumber",
        "extracted_at": "2026-05-28T12:00:00Z",
        "sections": [{"name": "wheat", "text": "U.S. wheat ending stocks..."}],
        "full_text": "WHEAT: U.S. wheat ending stocks...",
    }
    key = "text/source=usda_wasde/release_date=2026-05-12/document.json"

    write_document(s3, "my-bucket", key, doc)

    s3.put_object.assert_called_once()
    call_kwargs = s3.put_object.call_args.kwargs
    assert call_kwargs["ContentType"] == "application/json"
    assert call_kwargs["Bucket"] == "my-bucket"
    assert call_kwargs["Key"] == key


def test_write_document_valid_json() -> None:
    s3 = MagicMock()
    doc = {
        "source": "usda_wasde",
        "raw_key": "some/key.pdf",
        "extraction_method": "pdfplumber",
        "extracted_at": "2026-05-28T12:00:00Z",
        "sections": [],
        "full_text": "hello",
    }
    write_document(s3, "bucket", "key", doc)

    body_bytes = s3.put_object.call_args.kwargs["Body"]
    parsed = json.loads(body_bytes.decode("utf-8"))
    assert parsed["source"] == "usda_wasde"
    assert parsed["full_text"] == "hello"


def test_write_document_compact_no_indent() -> None:
    """Verify compact serialisation — no newlines in the JSON body."""
    s3 = MagicMock()
    doc = {
        "source": "usda_wasde",
        "raw_key": "k",
        "extraction_method": "txt_decode",
        "extracted_at": "2026-05-28T12:00:00Z",
        "sections": [],
        "full_text": "x",
    }
    write_document(s3, "bucket", "key", doc)
    body_bytes = s3.put_object.call_args.kwargs["Body"]
    assert b"\n" not in body_bytes
