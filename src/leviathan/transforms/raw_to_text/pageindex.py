"""Per-page OCR text index for scanned WASDE documents (6.5 click-to-page, W1b).

This module provides the two *pure* helpers that back the ``pages.json`` sidecar
artifact the click-to-page resolver (``graphrag.pdfpage``) consults when a
citation points at a scanned / Textract-extracted document.

Motivation
----------
``extract_wasde_scanned`` (see :mod:`leviathan.transforms.raw_to_text.wasde_scanned`)
joins every Textract ``LINE`` block into a single ``full_text`` string, erasing
page boundaries.  For click-to-page navigation the resolver needs to know *which
1-indexed PDF page* a cited snippet came from, and no such signal survives in
``document.json``.  Re-running the OCR at query time is impossible (Textract is a
paid, async API), so W1b writes an immutable per-vintage ``pages.json`` sidecar
next to ``document.json`` holding the OCR text split by page.

The two helpers here are deliberately I/O-free so they can be imported and unit
tested without ``boto3`` or a live Textract client:

* :func:`build_pages_json` -- regroup a flat Textract ``Blocks`` list into a
  ``{page_count, pages: [{page, text}]}`` structure.  This mirrors the exact
  sort key used by ``extract_wasde_scanned`` (lines 82-89 of ``wasde_scanned``)
  so the per-page text is byte-for-byte consistent with the joined ``full_text``
  the corpus already stores -- the resolver's fuzzy match then behaves the same
  on a page slice as it does on the whole document.
* :func:`sidecar_key` -- derive the ``pages.json`` key that sits next to a given
  ``document.json`` text-layer key.

The async submit/poll loop and all S3 I/O live in
``jobs/batch/wasde_pageindex_task.py``; this module never touches the network.
"""
from __future__ import annotations

from itertools import groupby
from typing import Any, Dict, List

# Basename of the text-layer document written by the extraction pipeline.
_DOCUMENT_BASENAME = "document.json"
# Basename of the per-page sidecar this workstream writes next to it.
_SIDECAR_BASENAME = "pages.json"


def build_pages_json(blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Regroup a flat Textract ``Blocks`` list into per-page OCR text.

    The grouping mirrors ``extract_wasde_scanned`` exactly -- filter to
    ``BlockType == "LINE"``, sort by ``(Page, Geometry.BoundingBox.Top)`` for
    reading order, and join ``Text`` values with newlines -- but instead of
    flattening every page into one string it keeps each page's text separate.
    Because the sort key and the ``if b.get("Text")`` join filter are identical,
    concatenating the per-page ``text`` values with ``"\\n"`` reproduces the same
    ``full_text`` the extractor stores, so the resolver's substring / difflib
    match localises a snippet to the correct 1-indexed page.

    Pages are emitted in ascending page order.  A page that contributes no
    ``LINE`` block is absent from the output (there is no OCR text to index for
    it); ``page`` values therefore carry the *real* 1-indexed Textract page
    number and may be non-contiguous if a page was blank.  ``page_count`` is the
    number of indexed (text-bearing) pages, i.e. ``len(pages)``.

    Args:
        blocks: Flat list of Textract Block dicts collected from all
            ``GetDocumentTextDetection`` response pages.  Only ``LINE`` blocks
            are used; ``PAGE`` / ``WORD`` / ``TABLE`` blocks are ignored.

    Returns:
        A dict ``{"page_count": int, "pages": [{"page": int, "text": str}, ...]}``
        ready to serialise to the ``text/`` layer as ``pages.json``.
    """
    line_blocks = [b for b in blocks if b.get("BlockType") == "LINE"]

    # Same sort key as extract_wasde_scanned: page number, then vertical
    # position within the page.  Python's sort is stable, so lines sharing a Top
    # keep their input order.  groupby below relies on Page being the primary
    # (and therefore contiguous) key after this sort.
    line_blocks.sort(
        key=lambda b: (
            b.get("Page", 0),
            b.get("Geometry", {}).get("BoundingBox", {}).get("Top", 0.0),
        )
    )

    pages: List[Dict[str, Any]] = []
    for page_num, group in groupby(line_blocks, key=lambda b: b.get("Page", 0)):
        text = "\n".join(b["Text"] for b in group if b.get("Text"))
        pages.append({"page": page_num, "text": text})

    return {"page_count": len(pages), "pages": pages}


def sidecar_key(source_key: str) -> str:
    """Return the ``pages.json`` sidecar key that sits next to *source_key*.

    A citation's ``source_key`` is the text-layer document key, e.g.
    ``text/source=usda_wasde/release_date=1976-07-12/document.json``.  The
    sidecar is written into the same "directory", so the derivation swaps the
    trailing ``document.json`` for ``pages.json``:

        text/source=usda_wasde/release_date=1976-07-12/pages.json

    If *source_key* does not end in ``document.json`` (defensive -- callers
    always pass the text-layer key), the sidecar is placed next to whatever the
    final path segment is instead.

    Args:
        source_key: Text-layer ``document.json`` S3 key.

    Returns:
        The sibling ``pages.json`` S3 key.
    """
    if source_key.endswith(_DOCUMENT_BASENAME):
        return source_key[: -len(_DOCUMENT_BASENAME)] + _SIDECAR_BASENAME
    if "/" in source_key:
        return source_key.rsplit("/", 1)[0] + "/" + _SIDECAR_BASENAME
    return _SIDECAR_BASENAME
