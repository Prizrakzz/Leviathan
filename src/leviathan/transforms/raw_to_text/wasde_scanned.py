"""Extract text from WASDE scanned PDFs via AWS Textract (1973–1994, Section F).

This module is intentionally free of I/O: it accepts the flat ``Blocks`` list
returned by ``GetDocumentTextDetection`` (after all ``NextToken`` pages have been
collected) and returns a :class:`~leviathan.transforms.raw_to_text.schema.DocumentJson`.
The Textract submit/poll loop lives in ``jobs/batch/wasde_scanned_task.py``.
"""
from __future__ import annotations

from datetime import datetime, timezone

from leviathan.transforms.raw_to_text.schema import DocumentJson
from leviathan.transforms.raw_to_text.wasde_digital import _split_sections


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
