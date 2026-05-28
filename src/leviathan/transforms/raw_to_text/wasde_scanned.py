"""Extract text from WASDE scanned PDFs via AWS Textract (1973–1994, Section F).

This module is intentionally free of I/O: it accepts the flat ``Blocks`` list
returned by ``GetDocumentTextDetection`` (after all ``NextToken`` pages have been
collected) and returns a :class:`~leviathan.transforms.raw_to_text.schema.DocumentJson`.
The Textract submit/poll loop lives in ``jobs/batch/wasde_scanned_task.py``.

Pure helper utilities used by both the task and the test suite
(``_is_scanned_key``, ``_truncate_pdf``) also live here so they can be
imported without pulling in boto3 or other job-level dependencies.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

import pypdf

from leviathan.storage.paths import parse_hive_key
from leviathan.transforms.raw_to_text.schema import DocumentJson
from leviathan.transforms.raw_to_text.wasde_digital import _split_sections

_SCANNED_YEAR_MAX = 1999  # .pdf + year < 1999 → scanned era (1973–1998)
_MAX_NARRATIVE_PAGES = 8


def _is_scanned_key(key: str) -> bool:
    """Return True if *key* points to a scanned-era WASDE PDF (1973–1998).

    Classification rule: file ends with ``.pdf`` **and** ``release_date``
    year < 1999.  (1999 WASDE files were published as ``.txt``.)
    """
    if not key.endswith(".pdf"):
        return False
    release_date = parse_hive_key(key, "release_date")
    if not release_date:
        return False
    try:
        year = int(release_date[:4])
    except ValueError:
        return False
    return year < _SCANNED_YEAR_MAX


def _truncate_pdf(pdf_bytes: bytes, max_pages: int) -> bytes:
    """Return a new PDF containing only the first *max_pages* pages.

    Uses ``pypdf`` in-memory — no disk I/O.  If the source has fewer pages
    than *max_pages*, the original bytes are returned unchanged (avoids an
    unnecessary re-serialisation cost).
    """
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    if len(reader.pages) <= max_pages:
        return pdf_bytes
    writer = pypdf.PdfWriter()
    for page in reader.pages[:max_pages]:
        writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def extract_wasde_scanned(blocks: list[dict], raw_key: str) -> DocumentJson:
    """Build a :class:`DocumentJson` from Textract ``LINE`` blocks.

    Filters to ``BlockType == "LINE"`` only (ignoring PAGE, WORD, etc.), sorts
    by ``(Page, Geometry.BoundingBox.Top)`` to enforce reading order, then joins
    all ``Text`` values with newlines.  Section splitting reuses the same
    commodity-heading regex as the digital PDF era.

    Args:
        blocks:  Flat list of Textract Block dicts collected from all
                 ``GetDocumentTextDetection`` response pages.
        raw_key: S3 key of the source PDF (used for lineage in output).

    Returns:
        A :class:`DocumentJson` dict ready to write to the ``text/`` layer.
    """
    line_blocks = [b for b in blocks if b.get("BlockType") == "LINE"]

    # Sort by page number then vertical position for correct reading order.
    line_blocks.sort(
        key=lambda b: (
            b.get("Page", 0),
            b.get("Geometry", {}).get("BoundingBox", {}).get("Top", 0.0),
        )
    )

    full_text = "\n".join(b["Text"] for b in line_blocks if b.get("Text"))

    sections = _split_sections(full_text)

    return DocumentJson(
        source="usda_wasde",
        raw_key=raw_key,
        extraction_method="textract",
        extracted_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        sections=sections,
        full_text=full_text,
    )
