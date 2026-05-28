from __future__ import annotations

from typing import List

from typing_extensions import TypedDict


class Section(TypedDict):
    """One named section of a source document."""

    name: str
    text: str


class DocumentJson(TypedDict):
    """Schema for document.json written to the text/ S3 layer.

    One file per source document, regardless of extraction method.
    """

    source: str
    raw_key: str
    extraction_method: str
    extracted_at: str
    sections: List[Section]
    full_text: str
