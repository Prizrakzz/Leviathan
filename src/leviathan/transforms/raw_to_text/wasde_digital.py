from __future__ import annotations

import io
import re
from datetime import datetime, timezone

import pdfplumber

from leviathan.transforms.raw_to_text.schema import DocumentJson, Section

# Commodity section markers as they appear at the start of a paragraph in WASDE
# digital PDFs (2000–2026).  The colon is part of the marker.
_SECTION_RE = re.compile(
    r"(?m)^(WHEAT|COARSE GRAINS|RICE|OILSEEDS|COTTON|SUGAR):"
)

# Pages to extract.  Pages 0–6 contain the narrative highlights and the table
# of contents.  Pages 7+ are fixed-width ASCII supply-use tables that are
# redundant with PSD CSV data — skip entirely.
_MAX_PAGE = 7


def extract_wasde_digital(pdf_bytes: bytes, raw_key: str) -> DocumentJson:
    """Extract text from a WASDE digital PDF (2000–2026 era, Section D).

    Reads pages 0 through min(6, last_page) with pdfplumber and splits the
    concatenated text into named sections on commodity headings.

    Args:
        pdf_bytes: Raw PDF bytes from S3.
        raw_key:   S3 key of the source PDF (used for lineage in output).

    Returns:
        A :class:`DocumentJson` dict ready to write to the text/ layer.
    """
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages_to_read = pdf.pages[: min(_MAX_PAGE, len(pdf.pages))]
        page_texts = [p.extract_text() or "" for p in pages_to_read]

    full_text = "\n".join(page_texts).strip()

    sections = _split_sections(full_text)

    return DocumentJson(
        source="usda_wasde",
        raw_key=raw_key,
        extraction_method="pdfplumber",
        extracted_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        sections=sections,
        full_text=full_text,
    )


def _split_sections(text: str) -> list[Section]:
    """Split *text* on commodity headings; return a list of Section dicts.

    If no headings are found (edge case, malformed PDF) returns an empty list
    so the caller can still use ``full_text``.
    """
    parts = _SECTION_RE.split(text)
    # split() with a capturing group returns [pre, name1, body1, name2, body2, ...]
    if len(parts) < 3:  # no matches
        return []

    sections: list[Section] = []
    # parts[0] is text before the first heading (cover/intro); skip it
    for i in range(1, len(parts) - 1, 2):
        name = parts[i].strip().lower().replace(" ", "_")
        body = parts[i + 1].strip()
        sections.append(Section(name=name, text=body))

    return sections
