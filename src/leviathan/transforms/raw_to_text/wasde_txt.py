from __future__ import annotations

import re
from datetime import datetime, timezone

from leviathan.transforms.raw_to_text.schema import DocumentJson, Section

# WASDE TXT files (1995–1999) use the same commodity headings as the digital
# PDF era but in plain text form.  The heading appears at the start of a line.
_SECTION_RE = re.compile(
    r"(?m)^(WHEAT|COARSE GRAINS|RICE|OILSEEDS|COTTON|SUGAR|LIVESTOCK):"
)

# HDR header line present in some 1995-era TXT files.
# Example: "HDR101380000002          WASDE - NARRATIVE"
_HDR_PREFIX = "HDR"


def extract_wasde_txt(txt_bytes: bytes, raw_key: str) -> DocumentJson:
    """Extract text from a WASDE TXT file (1995–1999 era, Section E).

    Decodes as latin-1 (1990s USDA TXT convention), strips the HDR header
    line if present, then splits on commodity section headings.

    Args:
        txt_bytes: Raw TXT bytes from S3.
        raw_key:   S3 key of the source file (used for lineage in output).

    Returns:
        A :class:`DocumentJson` dict ready to write to the text/ layer.
    """
    text = txt_bytes.decode("latin-1")

    # Strip HDR header line present in some 1995 files
    if text.lstrip().startswith(_HDR_PREFIX):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1:]

    full_text = text.strip()
    sections = _split_sections(full_text)

    return DocumentJson(
        source="usda_wasde",
        raw_key=raw_key,
        extraction_method="txt_decode",
        extracted_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        sections=sections,
        full_text=full_text,
    )


def _split_sections(text: str) -> list[Section]:
    """Split *text* on commodity headings; return a list of Section dicts.

    Returns an empty list if no headings are found.
    """
    parts = _SECTION_RE.split(text)
    if len(parts) < 3:
        return []

    sections: list[Section] = []
    for i in range(1, len(parts) - 1, 2):
        name = parts[i].strip().lower().replace(" ", "_")
        body = parts[i + 1].strip()
        sections.append(Section(name=name, text=body))

    return sections
