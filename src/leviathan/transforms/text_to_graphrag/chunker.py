"""Chunker: splits a DocumentJson into bounded text chunks for extraction.

WASDE and WAP documents arrive with named commodity sections (WHEAT:,
OILSEEDS:, SUGAR:, etc.) already split by the raw_to_text extractors.
Each section becomes one chunk.  Sections longer than MAX_CHARS are split
further on paragraph (double-newline) boundaries so no chunk exceeds the
≈512-token context target for Haiku.

Documents without named sections (sources ingested in the future) fall back
to paragraph-level splitting of full_text.
"""
from __future__ import annotations

from typing import List

from leviathan.transforms.raw_to_text.schema import DocumentJson

# ~450 tokens at ~4 chars/token.  Generous enough to capture most
# single-section text without hitting Haiku's effective reasoning limit.
MAX_CHARS = 1_800


def chunk_document(doc: DocumentJson) -> List[dict]:
    """Return a list of chunk dicts for a single DocumentJson.

    Each chunk dict has:
        text          (str)  — the text to send to the extractor
        section_name  (str)  — commodity section label or "full"
        chunk_index   (int)  — 0-based index within the document

    Args:
        doc: A DocumentJson loaded from S3 (text/ layer).

    Returns:
        Non-empty list of chunk dicts.  Empty sections are skipped.
    """
    chunks: list[dict] = []

    if doc["sections"]:
        for section in doc["sections"]:
            text = (section.get("text") or "").strip()
            if not text:
                continue
            name = section.get("name") or "full"
            for sub_text in _split_if_large(text):
                chunks.append({
                    "text": sub_text,
                    "section_name": name,
                    "chunk_index": len(chunks),
                })
    else:
        # Fallback: sources without named sections (future GAIN, CONAB, etc.)
        full = (doc.get("full_text") or "").strip()
        if full:
            for sub_text in _split_on_paragraphs(full):
                chunks.append({
                    "text": sub_text,
                    "section_name": "full",
                    "chunk_index": len(chunks),
                })

    return chunks


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _split_if_large(text: str) -> List[str]:
    """Return the text as-is if small enough; paragraph-split if too large."""
    if len(text) <= MAX_CHARS:
        return [text]
    return _split_on_paragraphs(text)


def _split_on_paragraphs(text: str) -> List[str]:
    """Split text on double-newlines and merge short fragments.

    Paragraphs shorter than 80 chars are merged with the preceding paragraph
    to avoid sending near-empty chunks to Haiku.
    """
    raw_paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    merged: list[str] = []

    for para in raw_paras:
        if merged and len(para) < 80:
            # Merge short trailer into preceding paragraph
            merged[-1] = merged[-1] + " " + para
        elif merged and len(merged[-1]) + len(para) + 2 <= MAX_CHARS:
            # Pack into the current chunk if it still fits
            merged[-1] = merged[-1] + "\n\n" + para
        else:
            merged.append(para)

    return merged if merged else [text]
