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

# Pages to extract: ALL of them (D14, ratified 2026-08-19).
#
# The premise that used to live here — `_MAX_PAGE = 7`, "pages 7+ are fixed-width ASCII supply-use
# tables that are redundant with PSD CSV data — skip entirely" — was MEASURED FALSE
# (data/dec_p0/extraction_blindness.{md,json}, D-XB-7):
#   * release 2026-05-12 yields 108,844 extractable chars over 40 pages (108,883 through this
#     function after the change — the probe measured pages directly); the stored full_text was
#     27,262 — 25.0% of the document.  30 of the 40 pages are numeric-dense.  Pages 9, 13, 21 and 31
#     were verified absent.  All 616 usda_wasde documents were cut the same way.
#   * what the cut dropped is NOT in PSD: U.S. Quarterly Animal Product Production and Prices (p31),
#     U.S. Meats Supply and Use (p32), U.S. Egg and Milk Supply and Use (p33), U.S. Dairy Prices
#     (p34) and the Reliability Tables (p35-37).  silver/wasde carries crops only
#     (barley…wheat, table_type us|world) — no meat, no dairy, no eggs, no reliability bands — so the
#     livestock/dairy layer had numeric backing in NO layer of the platform.
#   * the cut is not even stable for the narrative it was meant to keep: the 2026-05-12 release lost
#     its COTTON section to the 7-page window entirely (recipe-hardening lane,
#     data/dec_p0/recipe_hardening.md).
#
# The 150,000-char head-cut downstream (evidence_batch._FULLTEXT_CAP, mirrored by novelty and
# pdfpage) accommodates the full document: 108,844 < 150,000, so nothing is re-truncated later.


def extract_wasde_digital(pdf_bytes: bytes, raw_key: str) -> DocumentJson:
    """Extract text from a WASDE digital PDF (2000–2026 era, Section D).

    Reads EVERY page with pdfplumber (D14 — the old 7-page window is gone; see the module comment
    for the measurement that overturned it) and splits the concatenated text into named sections on
    commodity headings.  The narrative sections keep their meaning; the appendix table zone carries
    no ``^COMMODITY:`` heading of its own, so it rides inside whichever narrative section precedes
    it.  Verified on release 2026-05-12: full_text 27,262 -> 108,883 chars, sections 5 -> 6 (COTTON
    recovered — its narrative physically follows the tables in that release), with the tables riding
    the `sugar` section.

    Args:
        pdf_bytes: Raw PDF bytes from S3.
        raw_key:   S3 key of the source PDF (used for lineage in output).

    Returns:
        A :class:`DocumentJson` dict ready to write to the text/ layer.
    """
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page_texts = [p.extract_text() or "" for p in pdf.pages]

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

    D14 note — this now runs over the WHOLE document (40+ pages), not a 7-page head.  The splitter is
    heading-driven and length-agnostic, so that is not a behaviour change: the six-commodity regex
    still yields one section per heading occurrence, and the appendix table zone (which carries no
    ``^COMMODITY:`` heading of its own) rides inside the section that precedes it — on 2026-05-12
    that is ``sugar`` at 90,114 chars, followed by the ``cotton`` narrative the old window had cut.
    A heading that recurs in the appendix would open another section of the same name — allowed, not
    an error; the designated table-zone treatment is the parse-contract lane's business
    (data/dec_p0/recipe_hardening.md), deliberately NOT implemented here.
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
