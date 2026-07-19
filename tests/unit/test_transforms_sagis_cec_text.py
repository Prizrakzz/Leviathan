"""Unit tests for SAGIS CEC text extraction (Track B / B2).

Covers the four physical eras (pdf / doc / xls / xlsx) with synthetic in-memory
fixtures -- no S3, no real docs -- plus:

  * ``detect_filetype`` magic-byte + OLE-stream dispatch (fail-closed on junk),
  * ``derive_release_date`` priority (printed text date -> filename -> D2b late),
  * the DocumentJson schema-field contract (matches the house text layer),
  * a "transition"-style multi-season doc extracting in FULL (the numeric
    quarantine of task #118 never gates text -- ratified D10).

A skippable real-doc smoke (``CEC_SMOKE_DIR``) exercises the readers on genuine
raw bytes when a directory of downloaded CEC docs is provided.
"""
from __future__ import annotations

import os

import pytest

from leviathan.transforms.raw_to_bronze.sagis_cec import CecParseError
from leviathan.transforms.raw_to_text import sagis_cec_text
from leviathan.transforms.raw_to_text.sagis_cec_text import (
    _FILETYPE_DOC,
    _FILETYPE_PDF,
    _FILETYPE_XLS,
    _FILETYPE_XLSX,
    _release_date_from_key,
    derive_release_date,
    detect_filetype,
    extract_sagis_cec_text,
)

_PDF_MAGIC = b"%PDF-1.5\n"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_MAGIC = b"PK\x03\x04rest"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
def _fake_pdf(page_texts: list[str]):
    class _Page:
        def __init__(self, t: str) -> None:
            self._t = t

        def extract_text(self) -> str:
            return self._t

    class _Pdf:
        def __init__(self, texts: list[str]) -> None:
            self.pages = [_Page(t) for t in texts]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    return _Pdf(page_texts)


class _FakeOle:
    """Minimal olefile.OleFileIO stand-in exposing a stream directory."""

    def __init__(self, streams: list[str]) -> None:
        self._streams = streams

    def listdir(self):
        return [s.split("/") for s in self._streams]

    def close(self) -> None:
        pass


class _FakeXlrdSheet:
    def __init__(self, grid: list[list]) -> None:
        self._grid = grid
        self.nrows = len(grid)
        self.ncols = max((len(r) for r in grid), default=0)

    def cell_value(self, r: int, c: int):
        row = self._grid[r]
        return row[c] if c < len(row) else ""


class _FakeXlrdBook:
    def __init__(self, sheets: list[list[list]]) -> None:
        self._sheets = [_FakeXlrdSheet(g) for g in sheets]

    def sheets(self):
        return self._sheets


class _FakeWs:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def iter_rows(self, values_only: bool = True):
        yield from self._rows


class _FakeWb:
    def __init__(self, sheets: list[list[tuple]]) -> None:
        self.worksheets = [_FakeWs(r) for r in sheets]

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# detect_filetype
# ---------------------------------------------------------------------------
def test_detect_pdf() -> None:
    assert detect_filetype(_PDF_MAGIC + b"body", "k.pdf") == _FILETYPE_PDF


def test_detect_xlsx_zip() -> None:
    assert detect_filetype(_ZIP_MAGIC, "k.xlsx") == _FILETYPE_XLSX


def test_detect_ole_doc(monkeypatch) -> None:
    import olefile

    monkeypatch.setattr(
        olefile, "OleFileIO", lambda *a, **k: _FakeOle(["WordDocument", "1Table"])
    )
    assert detect_filetype(_OLE_MAGIC, "k.doc") == _FILETYPE_DOC


def test_detect_ole_xls(monkeypatch) -> None:
    import olefile

    monkeypatch.setattr(
        olefile, "OleFileIO", lambda *a, **k: _FakeOle(["Workbook"])
    )
    assert detect_filetype(_OLE_MAGIC, "k.xls") == _FILETYPE_XLS


def test_detect_ole_unknown_raises(monkeypatch) -> None:
    import olefile

    monkeypatch.setattr(
        olefile, "OleFileIO", lambda *a, **k: _FakeOle(["SomethingElse"])
    )
    with pytest.raises(CecParseError):
        detect_filetype(_OLE_MAGIC, "k.bin")


def test_detect_unknown_magic_raises() -> None:
    with pytest.raises(CecParseError):
        detect_filetype(b"junkjunk", "k.???")


# ---------------------------------------------------------------------------
# extract_sagis_cec_text -- per-era readers (synthetic)
# ---------------------------------------------------------------------------
def test_extract_pdf(monkeypatch) -> None:
    body = (
        "CROP ESTIMATES COMMITTEE\n"
        "The eighth production forecast for maize is 15,2 million tonnes,\n"
        "up on the previous forecast as favourable rains lifted the crop.\n"
        "Total Maize RSA 3 615 650 15 200 000\n"
    )
    monkeypatch.setattr(sagis_cec_text, "detect_filetype", lambda *a, **k: _FILETYPE_PDF)
    monkeypatch.setattr("pdfplumber.open", lambda *a, **k: _fake_pdf([body, "  "]))

    doc = extract_sagis_cec_text(_PDF_MAGIC, "raw/production/source=sagis_cec/CEC-2025-08.pdf")
    assert doc["source"] == "sagis_cec"
    assert doc["extraction_method"] == "pdfplumber"
    assert doc["raw_key"].endswith("CEC-2025-08.pdf")
    assert len(doc["sections"]) == 1
    assert doc["sections"][0]["name"] == "full"
    assert doc["sections"][0]["text"] == doc["full_text"]
    assert "eighth production forecast" in doc["full_text"]
    assert "Total Maize RSA" in doc["full_text"]  # table text is kept


def test_extract_pdf_blank_pages_dropped(monkeypatch) -> None:
    monkeypatch.setattr(sagis_cec_text, "detect_filetype", lambda *a, **k: _FILETYPE_PDF)
    substantive = "Commercial maize deliveries rose sharply in the latest committee report cycle."
    monkeypatch.setattr("pdfplumber.open", lambda *a, **k: _fake_pdf(["x", substantive, ""]))
    doc = extract_sagis_cec_text(_PDF_MAGIC, "k.pdf")
    assert doc["full_text"] == substantive


def test_extract_doc_reuses_parser_reader(monkeypatch) -> None:
    # \x07 = Word table-cell separator; must flatten to a space in the prose.
    raw = "COMMITTEE COMMENTARY\nWit mielies\x07985 000\x074 200 000\nCommercial delivery narrative."
    monkeypatch.setattr(sagis_cec_text, "detect_filetype", lambda *a, **k: _FILETYPE_DOC)
    monkeypatch.setattr(sagis_cec_text, "extract_doc_text", lambda data: raw)

    doc = extract_sagis_cec_text(_OLE_MAGIC, "raw/production/source=sagis_cec/CEC-2003-05.doc")
    assert doc["extraction_method"] == "olefile"
    assert "\x07" not in doc["full_text"]
    assert "Wit mielies 985 000 4 200 000" in doc["full_text"]
    assert "COMMITTEE COMMENTARY" in doc["full_text"]


def test_extract_xls(monkeypatch) -> None:
    import xlrd

    grid = [
        ["CROP ESTIMATES COMMITTEE", "", ""],
        ["19 September 2002", "", ""],
        ["Kommersieel / Commercial:", "", ""],
        ["Koring / Wheat", 811000, 1548000],
    ]
    monkeypatch.setattr(sagis_cec_text, "detect_filetype", lambda *a, **k: _FILETYPE_XLS)
    monkeypatch.setattr(xlrd, "open_workbook", lambda *a, **k: _FakeXlrdBook([grid]))

    doc = extract_sagis_cec_text(_OLE_MAGIC, "raw/production/source=sagis_cec/CEC_2002_-_1909w.xls")
    assert doc["extraction_method"] == "xlrd"
    assert "CROP ESTIMATES COMMITTEE" in doc["full_text"]
    assert "Koring / Wheat" in doc["full_text"]
    assert "811000" in doc["full_text"]


def test_extract_xlsx(monkeypatch) -> None:
    import openpyxl

    sheet = [
        ("CROP ESTIMATES COMMITTEE", None, None),
        ("Total Maize RSA", 3615650, 15200000),
        (None, None, None),
    ]
    monkeypatch.setattr(sagis_cec_text, "detect_filetype", lambda *a, **k: _FILETYPE_XLSX)
    monkeypatch.setattr(openpyxl, "load_workbook", lambda *a, **k: _FakeWb([sheet]))

    doc = extract_sagis_cec_text(_ZIP_MAGIC, "raw/production/source=sagis_cec/CEC-2026-02.xlsx")
    assert doc["extraction_method"] == "openpyxl"
    assert "Total Maize RSA" in doc["full_text"]
    assert "3615650" in doc["full_text"]


def test_empty_document_yields_no_sections(monkeypatch) -> None:
    monkeypatch.setattr(sagis_cec_text, "detect_filetype", lambda *a, **k: _FILETYPE_PDF)
    monkeypatch.setattr("pdfplumber.open", lambda *a, **k: _fake_pdf(["", "   ", "\n"]))
    doc = extract_sagis_cec_text(_PDF_MAGIC, "k.pdf")
    assert doc["sections"] == []
    assert doc["full_text"] == ""


def test_transition_doc_extracts_in_full(monkeypatch) -> None:
    """The numeric quarantine (task #118 scope-mislabel) never gates TEXT (D10).

    A multi-season "transition" release whose numeric parse would quarantine
    (winter + summer sections with different ordinals) still yields its full
    committee prose -- no CecCollapseError / quarantine path is on the text
    lane.
    """
    body = (
        "WINTERGEWASSE: FINALE PRODUKSIESKATTING VIR 1999/2000\n"
        "The fifth and final winter cereals forecast is released herewith.\n"
        "SUMMER FIELD CROPS - PRELIMINARY AREA PLANTED ESTIMATE: 2000/01\n"
        "The first summer crop intentions follow.\n"
    )
    monkeypatch.setattr(sagis_cec_text, "detect_filetype", lambda *a, **k: _FILETYPE_PDF)
    monkeypatch.setattr("pdfplumber.open", lambda *a, **k: _fake_pdf([body]))
    doc = extract_sagis_cec_text(_PDF_MAGIC, "raw/production/source=sagis_cec/CEC-2000-01-Summer.pdf")
    assert "WINTERGEWASSE" in doc["full_text"]
    assert "SUMMER FIELD CROPS" in doc["full_text"]


# ---------------------------------------------------------------------------
# derive_release_date -- PIT stamp priority
# ---------------------------------------------------------------------------
def test_derive_prefers_printed_text_date() -> None:
    # printed committee date wins over the (coarser) month-only filename
    text = "CROP ESTIMATES COMMITTEE\nconditions as at 21 February 2000\nWINTERGEWASSE ..."
    rd = derive_release_date(b"", "raw/production/source=sagis_cec/CEC-2000-02.doc", full_text=text)
    assert rd == "2000-02-21"


def test_derive_bilingual_printed_date() -> None:
    text = "soos op 20 Mei/ May 2002 ... produksieskatting"
    rd = derive_release_date(b"", "CEC-2002-05.xls", full_text=text)
    assert rd == "2002-05-20"


def test_derive_falls_back_to_filename_iso() -> None:
    # no parseable printed date -> the YYYY-MM-DD in the filename
    rd = derive_release_date(
        b"", "raw/production/source=sagis_cec/CEC-1999-10-20.pdf", full_text="no date here at all"
    )
    assert rd == "1999-10-20"


def test_derive_filename_ddmonyyyy() -> None:
    rd = derive_release_date(b"", "CEC-13-Feb-2025.pdf", full_text="no printed date")
    assert rd == "2025-02-13"


def test_derive_filename_month_only_is_late_bound() -> None:
    # month-only filename -> D2b conservative LATE bound (end of month), never early
    rd = derive_release_date(b"", "CEC-2000-02.doc", full_text="no printed date")
    assert rd == "2000-02-29"  # 2000 is a leap year


def test_derive_fail_closed() -> None:
    with pytest.raises(CecParseError):
        derive_release_date(b"", "CEC-no-date-here.doc", full_text="no printed date")


def test_release_date_from_key_forms() -> None:
    assert _release_date_from_key("x/CEC-2000-09-20intentions.pdf") == "2000-09-20"
    assert _release_date_from_key("x/CEC-13-Feb-2025.pdf") == "2025-02-13"
    assert _release_date_from_key("x/CEC-1999-10.pdf") == "1999-10-31"
    assert _release_date_from_key("x/CEC-garbage.pdf") is None


# ---------------------------------------------------------------------------
# Schema-field contract
# ---------------------------------------------------------------------------
def test_schema_fields(monkeypatch) -> None:
    monkeypatch.setattr(sagis_cec_text, "detect_filetype", lambda *a, **k: _FILETYPE_PDF)
    monkeypatch.setattr(
        "pdfplumber.open",
        lambda *a, **k: _fake_pdf(["The committee reports a firm maize crop this season here."]),
    )
    doc = extract_sagis_cec_text(_PDF_MAGIC, "raw/production/source=sagis_cec/CEC-2025-08.pdf")
    assert set(doc.keys()) == {
        "source", "raw_key", "extraction_method", "extracted_at", "sections", "full_text",
    }
    assert len(doc["extracted_at"]) == 20  # "YYYY-MM-DDTHH:MM:SSZ"
    assert isinstance(doc["sections"], list)
    assert isinstance(doc["full_text"], str)


# ---------------------------------------------------------------------------
# Real-doc smoke (skippable offline)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not os.environ.get("CEC_SMOKE_DIR"),
    reason="set CEC_SMOKE_DIR to a directory of real raw CEC docs to run the smoke",
)
def test_real_doc_smoke() -> None:
    smoke_dir = os.environ["CEC_SMOKE_DIR"]
    files = [f for f in os.listdir(smoke_dir) if f.lower().endswith((".pdf", ".doc", ".xls", ".xlsx"))]
    assert files, f"no CEC docs in {smoke_dir}"
    for fn in files:
        with open(os.path.join(smoke_dir, fn), "rb") as fh:
            data = fh.read()
        key = f"raw/production/source=sagis_cec/{fn}"
        doc = extract_sagis_cec_text(data, key)
        assert doc["source"] == "sagis_cec"
        assert doc["full_text"], f"{fn}: empty extraction"
        rd = derive_release_date(data, key, full_text=doc["full_text"])
        assert rd[:4].isdigit() and len(rd) == 10, f"{fn}: bad release date {rd!r}"
