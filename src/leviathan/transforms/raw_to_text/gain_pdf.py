"""GAIN PDF → text/ layer transform.

Handles all USDA FAS GAIN country attaché report PDFs across all commodity
groups (wheat, corn, soybeans, coffee, cotton, sugar, palm_oil, etc.).

All GAIN PDFs are native digital (not scanned) and are extracted with
pdfplumber at zero OCR cost.

Unlike WASDE or WAP, GAIN reports are single-commodity single-country
documents ("Brazil Grain and Feed Annual", "Ukraine Wheat Update", etc.).
There are no multi-section commodity headings to split on.  The entire
document is returned as one section named "full".

Page filtering:
  - Blank pages (< 50 stripped characters) are skipped.
  - Last-page boilerplate footer ("USDA Foreign Agricultural Service" alone
    on the page) is skipped.
  - Page 0 is always included — it contains country name, commodity, report
    date, and attaché post header that are critical for GraphRAG entity
    extraction.
"""
from __future__ import annotations

import io
import re
from datetime import datetime, timezone

import pdfplumber

from leviathan.transforms.raw_to_text.schema import DocumentJson, Section

# A page whose entire visible content is the FAS contact footer is useless.
# The pattern matches a line that is ONLY the footer text (with nothing else
# substantial on the page).
_BOILERPLATE_RE = re.compile(
    r"usda\s+foreign\s+agricultural\s+service\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_BLANK_THRESHOLD = 50  # stripped character count below which a page is skipped


def _is_boilerplate(text: str) -> bool:
    """Return True if the page is nothing but the FAS footer boilerplate.

    Removes the footer pattern from the page text and checks whether anything
    substantial remains.  This correctly handles pages that contain only the
    FAS contact footer while leaving substantive pages (which may also end
    with the footer line) untouched.
    """
    without_footer = _BOILERPLATE_RE.sub("", text)
    return len(without_footer.strip()) < _BLANK_THRESHOLD


def extract_gain_pdf(
    pdf_bytes: bytes,
    raw_key: str,
    source_name: str,
) -> DocumentJson:
    """Extract narrative text from a USDA FAS GAIN report PDF.

    Reads all pages with pdfplumber, applies blank and boilerplate filters,
    and returns the concatenated text as a single "full" section.

    Args:
        pdf_bytes:   Raw PDF bytes from S3.
        raw_key:     S3 key of the source PDF (used for lineage).
        source_name: Source identifier, e.g. ``"usda_gain_wheat"``.

    Returns:
        A :class:`DocumentJson` dict ready to write to the text/ layer.
    """
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page_texts: list[str] = []
        for page in pdf.pages:
            text = page.extract_text() or ""
            if len(text.strip()) < _BLANK_THRESHOLD:
                continue
            if _is_boilerplate(text):
                continue
            page_texts.append(text)

    full_text = "\n".join(page_texts).strip()
    sections: list[Section] = []
    if full_text:
        sections = [Section(name="full", text=full_text)]

    return DocumentJson(
        source=source_name,
        raw_key=raw_key,
        extraction_method="pdfplumber",
        extracted_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        sections=sections,
        full_text=full_text,
    )
