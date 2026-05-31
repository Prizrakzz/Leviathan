"""Text extraction for MPOB Overview of the Malaysian Oil Palm Industry PDFs.

Reads pages 0–4 (narrative prose), strips running headers/footers, and returns
a DocumentJson with a single "overview" section.  Pages 5–6 contain the
statistics tables and are handled by the bronze pipeline (mpob_pdf.py in
raw_to_bronze/).

Design notes
------------
* All 7 overview PDFs (2010–2016) are digital/typeset — pdfplumber extracts
  clean text without OCR.  No Textract needed.

* Running header (every page):
      "Overview of the Malaysian Oil Palm Industry YYYY"

* Running footer lines (every page):
      "<digit(s)> Economics & Industry Development Division"
      "Malaysian Palm Oil Board"
      "Feb YYYY"  (or Jan / Mar, etc.)

* Output: single "overview" section containing the concatenated prose of all
  five narrative pages separated by a blank line.
"""
from __future__ import annotations

import io
import re
from datetime import datetime, timezone

import pdfplumber

from leviathan.transforms.raw_to_text.schema import DocumentJson, Section

# Pages 0–4 contain the narrative overview; pages 5–6 are the stats tables.
_MAX_NARRATIVE_PAGES = 5

# Running page header pattern.
_PAGE_HEADER_RE = re.compile(
    r"Overview of the Malaysian Oil Palm Industry\s+\d{4}\s*",
    re.IGNORECASE,
)

# Running page footer lines.
_PAGE_FOOTER_RE = re.compile(
    r"\d+\s+Economics\s*&\s*Industry\s+Development\s+Division\s*"
    r"|Malaysian Palm Oil Board\s*"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}\s*",
    re.IGNORECASE,
)


def extract_mpob_overview(pdf_bytes: bytes, raw_key: str) -> DocumentJson:
    """Extract narrative text from an MPOB Overview of Industry PDF.

    Args:
        pdf_bytes: Raw PDF bytes from S3.
        raw_key:   S3 key of the source PDF (stored for lineage).

    Returns:
        A :class:`~leviathan.transforms.raw_to_text.schema.DocumentJson`
        with ``source="mpob"``, ``extraction_method="pdfplumber"``, and a
        single section ``{"name": "overview", "text": ...}``.
    """
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages_to_read = pdf.pages[: min(_MAX_NARRATIVE_PAGES, len(pdf.pages))]
        raw_texts = [p.extract_text() or "" for p in pages_to_read]

    cleaned = [_clean_page(t) for t in raw_texts]
    full_text = "\n\n".join(t for t in cleaned if t).strip()

    sections: list[Section] = []
    if full_text:
        sections = [Section(name="overview", text=full_text)]

    return DocumentJson(
        source="mpob",
        raw_key=raw_key,
        extraction_method="pdfplumber",
        extracted_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        sections=sections,
        full_text=full_text,
    )


def _clean_page(text: str) -> str:
    """Remove running header and footer lines from a single page's extracted text."""
    text = _PAGE_HEADER_RE.sub("", text)
    text = _PAGE_FOOTER_RE.sub("", text)
    # Collapse runs of 3+ blank lines down to one.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
