"""SAGIS CEC (Crop Estimates Committee) -> text/ layer transform (Track B, B2).

Chunk the committee-statement PROSE of the 520 SAGIS CEC releases into the
text/ layer so GraphRAG carries qualitative SA-maize supply/estimate context to
pair with the Lane-A3 numbers.  This is text extraction only -- the numeric
quarantine that governs the raw->bronze parser (task #118, multi-era scope
mislabels) does NOT apply here: prose is faithful regardless of the numeric
parser's scope confusion, so the ~72 quarantined transition docs ARE included
(ratified D10).  Any numbers appearing in the extracted prose are retrieval
CONTEXT, never citable figures (citable numbers come from the numbers lane).

Four physical eras, ONE document.json per raw doc (schema exact, no OCR
confidence -- the raw CEC releases are all digital/typeset, never scanned):

  * .pdf   1999-2004 early + 2008-2026 modern -> pdfplumber, all pages.
  * .doc   2000-2024 OLE WordDocument (CLX piece-table, cp1252/UTF-16LE mixed)
           -> the repaired parser's pure-python ``extract_doc_text`` is REUSED
           verbatim (not duplicated); its \\x07 cell separators are flattened
           to spaces for readable prose.
  * .xls   2002-2004 OLE workbook -> xlrd sheet text.
  * .xlsx  (forward-compat; none in the current raw inventory) -> openpyxl.

The narrative is the committee commentary AROUND the crop x sector tables; the
table text is kept too (downstream chunking handles granularity), so -- as with
the single-topic GAIN reports -- the whole document is one ``full`` section.

PIT: the doc's date stamp is its OWN committee release date, derived by
:func:`derive_release_date`, which REUSES the parser's release-date machinery
(``parse_release_date`` on the printed text, then a filename fallback, then the
D2b conservative-late end-of-report-month bound) -- never the ingest time.  The
document.json itself carries no date field (house schema); the batch task keys
the S3 partition on the derived release date.
"""
from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from typing import Optional

from leviathan.transforms.raw_to_bronze.sagis_cec import (
    _MONTHS,
    _OLE_MAGIC,
    _PDF_MAGIC,
    CecParseError,
    _end_of_month,
    _report_month_from_key,
    extract_doc_text,
    parse_release_date,
)
from leviathan.transforms.raw_to_text.schema import DocumentJson, Section

_ZIP_MAGIC = b"PK\x03\x04"  # .xlsx (Office Open XML is a ZIP container)

# A page/sheet with almost no content is dropped (matches the GAIN blank filter).
_BLANK_THRESHOLD = 30

# Extraction-method tags (tool-name style, matching the house "pdfplumber" /
# "txt_decode" convention).
_METHOD_PDF = "pdfplumber"
_METHOD_DOC = "olefile"
_METHOD_XLS = "xlrd"
_METHOD_XLSX = "openpyxl"


# --------------------------------------------------------------------------- #
# File-type dispatch (magic bytes + OLE stream inspection)
# --------------------------------------------------------------------------- #
_FILETYPE_PDF = "pdf"
_FILETYPE_DOC = "doc"
_FILETYPE_XLS = "xls"
_FILETYPE_XLSX = "xlsx"


def detect_filetype(data: bytes, source_key: str) -> str:
    """Return the physical file type of a raw CEC doc, or raise :class:`CecParseError`.

    Dispatches on magic bytes; an OLE compound file is disambiguated into a Word
    ``.doc`` vs an Excel ``.xls`` by its stream directory (the bronze parser's
    ``Workbook``/``Book`` vs ``WordDocument`` signal).  Fail-closed on an
    unrecognised signature -- never guess an extractor.
    """
    if data.startswith(_PDF_MAGIC):
        return _FILETYPE_PDF
    if data.startswith(_ZIP_MAGIC):
        return _FILETYPE_XLSX
    if data.startswith(_OLE_MAGIC):
        import olefile

        ole = olefile.OleFileIO(io.BytesIO(data))
        try:
            streams = {"/".join(p) for p in ole.listdir()}
        finally:
            ole.close()
        if "Workbook" in streams or "Book" in streams:
            return _FILETYPE_XLS
        if "WordDocument" in streams:
            return _FILETYPE_DOC
        raise CecParseError(
            f"{source_key!r}: OLE file is neither a Word .doc nor an Excel .xls"
        )
    raise CecParseError(
        f"{source_key!r}: unrecognised magic bytes {data[:4]!r} for a CEC text doc"
    )


# --------------------------------------------------------------------------- #
# Per-format text readers
# --------------------------------------------------------------------------- #
def _normalise(text: str) -> str:
    """Flatten cell separators and collapse runaway whitespace into readable prose.

    Word ``.doc`` cells arrive on ``\\x07`` and Excel cells are joined per row;
    both become single spaces so committee commentary and table rows read as flat
    text.  Blank lines are preserved (paragraph structure) but never stacked more
    than two deep."""
    text = text.replace("\x07", " ").replace("\t", " ")
    # collapse runs of spaces/tabs, but keep newlines (paragraph boundaries)
    text = re.sub(r"[  ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [ln.strip() for ln in text.split("\n")]
    return "\n".join(lines).strip()


def _read_pdf_text(data: bytes) -> str:
    """Concatenate every page's text (narrative + tables) from a CEC PDF."""
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        parts = []
        for page in pdf.pages:
            t = page.extract_text() or ""
            if len(t.strip()) < _BLANK_THRESHOLD:
                continue
            parts.append(t)
    return _normalise("\n".join(parts))


def _read_doc_text(data: bytes) -> str:
    """Extract .doc prose via the repaired parser's pure-python OLE reader (REUSED)."""
    return _normalise(extract_doc_text(data))


def _read_xls_text(data: bytes) -> str:
    """Join every sheet's cell text of a legacy .xls workbook (row -> line)."""
    import xlrd

    book = xlrd.open_workbook(file_contents=data)
    lines: list[str] = []
    for sheet in book.sheets():
        for r in range(sheet.nrows):
            cells = [
                str(sheet.cell_value(r, c)).strip()
                for c in range(sheet.ncols)
            ]
            row = " ".join(cell for cell in cells if cell)
            if row:
                lines.append(row)
    return _normalise("\n".join(lines))


def _read_xlsx_text(data: bytes) -> str:
    """Join every sheet's cell text of an .xlsx workbook (row -> line)."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    lines: list[str] = []
    try:
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                cells = [str(v).strip() for v in row if v is not None]
                joined = " ".join(cell for cell in cells if cell)
                if joined:
                    lines.append(joined)
    finally:
        wb.close()
    return _normalise("\n".join(lines))


_READERS = {
    _FILETYPE_PDF: (_read_pdf_text, _METHOD_PDF),
    _FILETYPE_DOC: (_read_doc_text, _METHOD_DOC),
    _FILETYPE_XLS: (_read_xls_text, _METHOD_XLS),
    _FILETYPE_XLSX: (_read_xlsx_text, _METHOD_XLSX),
}


# --------------------------------------------------------------------------- #
# Publication-date derivation (PIT stamp) -- reuses the parser's date machinery
# --------------------------------------------------------------------------- #
# Filename date forms observed in the raw inventory:
#   CEC-1999-10-20.pdf / CEC-2000-09-20intentions.pdf   -> YYYY-MM-DD
#   CEC-13-Feb-2025.pdf                                  -> DD-Mon-YYYY
#   CEC-1999-10.pdf / CEC-2000-02.doc                    -> YYYY-MM (month only)
_KEY_ISO_RE = re.compile(r"((?:19|20)\d{2})-(\d{2})-(\d{2})")
_KEY_DMONY_RE = re.compile(r"(\d{1,2})-([A-Za-z]{3,})-((?:19|20)\d{2})")
_KEY_YM_RE = re.compile(r"((?:19|20)\d{2})-(\d{2})(?!\d)")


def _release_date_from_key(source_key: str) -> Optional[str]:
    """Derive an ISO ``YYYY-MM-DD`` release date from the filename, or None.

    Prefers a full ``YYYY-MM-DD`` stamp, then ``DD-Mon-YYYY``, then a
    month-only ``YYYY-MM`` (imputed to the D2b conservative-late end of that
    month).  Fail-soft: returns None when the filename carries no parseable date
    so the caller can fall back further."""
    stem = source_key.rsplit("/", 1)[-1]

    m = _KEY_ISO_RE.search(stem)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"

    m = _KEY_DMONY_RE.search(stem)
    if m:
        day = int(m.group(1))
        month = _MONTHS.get(m.group(2).lower())
        year = int(m.group(3))
        if month is not None and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"

    m = _KEY_YM_RE.search(stem)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12:
            return _end_of_month(year, month)

    return None


def derive_release_date(
    data: bytes,
    source_key: str,
    *,
    full_text: Optional[str] = None,
) -> str:
    """Derive the CEC doc's OWN committee release date -> ISO ``YYYY-MM-DD``.

    Reuses the parser's date logic in the same priority the raw->bronze
    ``_build_meta`` applies:

      1. the printed release/meeting date on the document (``parse_release_date``
         -- prefers the "conditions as at / soos op" meeting date), then
      2. the date encoded in the filename (``_release_date_from_key``), then
      3. the D2b conservative-LATE bound: the last day of the report month
         inferred from the ``...YYYY-MM...`` filename (never an EARLY bound -- an
         early publication date is a PIT lookahead leak).

    Fail-closed: a doc whose date cannot be established by ANY of the three
    raises :class:`CecParseError` (the batch task marks it errored rather than
    stamping ingest time).

    ``full_text`` may be passed (the already-extracted document text) to avoid
    re-parsing the raw bytes a second time.
    """
    if full_text is None:
        filetype = detect_filetype(data, source_key)
        reader, _ = _READERS[filetype]
        full_text = reader(data)

    iso = parse_release_date(full_text)
    if iso:
        return iso

    iso = _release_date_from_key(source_key)
    if iso:
        return iso

    month = _report_month_from_key(source_key)
    year_m = re.search(r"(19|20)\d{2}", source_key.rsplit("/", 1)[-1])
    if month is not None and year_m is not None:
        return _end_of_month(int(year_m.group()), month)

    raise CecParseError(
        f"{source_key!r}: cannot establish a CEC release date from text or filename"
    )


# --------------------------------------------------------------------------- #
# Public entrypoint
# --------------------------------------------------------------------------- #
def extract_sagis_cec_text(data: bytes, source_key: str) -> DocumentJson:
    """Extract committee narrative + table text from one raw CEC doc.

    Dispatches on the physical file type (pdf / doc / xls / xlsx), reuses the
    repaired parser's ``.doc`` reader, and returns the whole document as a single
    ``full`` section (as with the single-topic GAIN reports) -- downstream
    chunking handles granularity.

    Args:
        data:       Raw document bytes from S3.
        source_key: S3 key of the source doc (stored for lineage).

    Returns:
        A :class:`DocumentJson` dict ready to write to the text/ layer.
    """
    filetype = detect_filetype(data, source_key)
    reader, method = _READERS[filetype]
    full_text = reader(data)

    sections: list[Section] = []
    if full_text:
        sections = [Section(name="full", text=full_text)]

    return DocumentJson(
        source="sagis_cec",
        raw_key=source_key,
        extraction_method=method,
        extracted_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        sections=sections,
        full_text=full_text,
    )
