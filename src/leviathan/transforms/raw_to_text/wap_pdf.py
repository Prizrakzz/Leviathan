"""WAP PDF → text/ layer transform (Phase 3, sources A and B).

Handles both source eras:
- Source A (2002-08 → present): FAS portal PDFs downloaded directly to S3.
- Source B (1988 → 2002-07): Archive.org PDFs, same S3 prefix as A.

Both are native digital PDFs (not scanned) and are extracted with pdfplumber.
Pages 0–5 contain commodity narrative highlights; page 6 is Table 01 (handled
separately by wap_table01.py).

The archive.org era (pre-2002) has reversed text on page 6 only — the narrative
pages 0–5 are clean and need no special handling here.

Sections are split on the same commodity headings as WASDE digital PDFs because
the WAP circular uses identical section headers (WHEAT, COARSE GRAINS, etc.).
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

import pdfplumber

from leviathan.transforms.raw_to_text.schema import DocumentJson, Section
from leviathan.transforms.raw_to_text.wasde_digital import _split_sections

# Pages 0–5 are commodity narrative; page 6 is Table 01 (separate pipeline).
# Page 7+ (if any) are supplementary tables — skip.
_NARRATIVE_PAGE_RANGE = slice(0, 6)


def _is_archiveorg_era(release_month: str) -> bool:
    """Return True for Archive.org era PDFs (release_month year < 2002).

    Args:
        release_month: YYYY-MM string, e.g. "2001-09".
    """
    year = int(release_month[:4])
    return year < 2002


def extract_wap_pdf(pdf_bytes: bytes, raw_key: str, release_month: str) -> DocumentJson:
    """Extract text from a WAP PDF (source A or B).

    Reads pages 0–5 with pdfplumber and splits the concatenated text into
    named commodity sections.

    Args:
        pdf_bytes:     Raw PDF bytes from S3.
        raw_key:       S3 key of the source PDF (used for lineage).
        release_month: YYYY-MM, e.g. "2026-05".  Used for archiveorg era check
                       and to label the output.

    Returns:
        A :class:`DocumentJson` dict ready to write to the text/ layer.
    """
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages = pdf.pages[_NARRATIVE_PAGE_RANGE]
        page_texts = [p.extract_text() or "" for p in pages]

    full_text = "\n".join(page_texts).strip()
    sections = _split_sections(full_text)

    return DocumentJson(
        source="usda_wap",
        raw_key=raw_key,
        extraction_method="pdfplumber",
        extracted_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        sections=sections,
        full_text=full_text,
    )
