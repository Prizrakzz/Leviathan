"""Unit tests for the 6.5 click-to-page resolver (graphrag/pdfpage.py).

Hermetic: no real S3, no real DAG/slice IP. A fake S3 stub serves in-memory ``document.json`` / ``pages.json``
bodies and a SYNTHETIC multi-page PDF hand-built in-test (pdfplumber round-trips it, so the deterministic
char->page arithmetic and the extractor page-filter replication are exercised against real pdfplumber output).
Skipped wholesale if pdfplumber is unavailable (it lives in the serve/batch extras).

Coverage: the GAIN blank+boilerplate filter replication (a skipped page must NOT shift the reported page
number), the 60k cap + past-text truncated tails, native fuzzy hit/difflib/miss->null, the non-pdf branch, the
textract sidecar branch (with + without the sidecar), a missing-document 404 signal, and the never-raises
property under S3 failures.
"""
from __future__ import annotations

import io
import json

import pytest

pytest.importorskip("pdfplumber")                                # native branches re-extract with pdfplumber

from leviathan.graphrag import pdfpage  # noqa: E402 -- imported after the importorskip guard
from leviathan.transforms.raw_to_text.gain_pdf import extract_gain_pdf  # noqa: E402


# ── synthetic PDF + fake S3 ─────────────────────────────────────────────────────────────────────────
def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _make_pdf(pages: list[list[str]]) -> bytes:
    """A minimal, valid multi-page PDF from ``pages`` (list of per-page line lists). Hand-rolled (no writer lib
    is installed); pdfplumber extracts each page's lines joined by '\\n', matching the raw_to_text extractors."""
    objs: list[tuple[int, str]] = []
    n = len(pages)
    font_obj = 3 + 2 * n
    page_ids = [3 + 2 * i for i in range(n)]
    content_ids = [4 + 2 * i for i in range(n)]
    objs.append((1, "<< /Type /Catalog /Pages 2 0 R >>"))
    objs.append((2, f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] /Count {n} >>"))
    for i, lines in enumerate(pages):
        objs.append((page_ids[i], f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                                  f"/Resources << /Font << /F1 {font_obj} 0 R >> >> /Contents {content_ids[i]} 0 R >>"))
        buf = ["BT", "/F1 12 Tf", "72 720 Td", "14 TL"]
        for j, ln in enumerate(lines):
            buf.append(f"({_esc(ln)}) Tj" if j == 0 else f"T* ({_esc(ln)}) Tj")
        buf.append("ET")
        stream = "\n".join(buf)
        objs.append((content_ids[i], f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"))
    objs.append((font_obj, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"))
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for oid, body in sorted(objs):
        offsets[oid] = out.tell()
        out.write(f"{oid} 0 obj\n{body}\nendobj\n".encode("latin-1"))
    xref_pos = out.tell()
    max_id = max(offsets)
    out.write(f"xref\n0 {max_id + 1}\n".encode("latin-1"))
    out.write(b"0000000000 65535 f \n")
    for oid in range(1, max_id + 1):
        out.write(f"{offsets.get(oid, 0):010d} 00000 n \n".encode("latin-1"))
    out.write(f"trailer\n<< /Size {max_id + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("latin-1"))
    return out.getvalue()


class _FakeS3:
    """Minimal boto3-S3 stand-in: get_object over an in-memory {key: bytes} map (missing key raises, like S3),
    and a local presign that never needs the key to exist (mirrors real presign = pure local signing)."""

    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = dict(objects)
        self.raise_on_presign = False

    def get_object(self, Bucket: str, Key: str) -> dict:          # noqa: N803 -- boto3 kwarg names
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": io.BytesIO(self.objects[Key])}

    def generate_presigned_url(self, op: str, Params=None, ExpiresIn=None) -> str:  # noqa: N803
        if self.raise_on_presign:
            raise RuntimeError("presign boom")
        return f"https://s3.example/{Params['Key']}?e={ExpiresIn}"


def _install(monkeypatch, objects: dict[str, bytes]) -> _FakeS3:
    fake = _FakeS3(objects)
    monkeypatch.setattr(pdfpage, "_S3", fake)
    pdfpage._reset_caches()                                       # per-test isolation (doc + page-text LRUs)
    return fake


# GAIN fixture: page 2 is blank (< _BLANK_THRESHOLD) and page 4 is the FAS-footer boilerplate, so the extractor
# keeps REAL pdf pages 1 and 3. The cited MARKER lives on real page 3 -- a filter-blind resolver would call it
# page 2. This is the recon's "biggest gotcha" pinned as a test.
_GAIN_PAGES = [
    ["Global coffee markets remain tight this crop season across origins.",
     "Brazilian arabica output narrative continues on page one here today."],
    ["   "],                                                      # blank -> dropped, shifts page numbers
    ["Frost struck the arabica belt in July causing severe crop damage.",
     "MARKER BRAVO the cited passage lives on real page three of the report."],
    ["USDA Foreign Agricultural Service"],                        # FAS boilerplate -> dropped
]
_GAIN_SK = "text/source=usda_gain_coffee/country=BR/publication_date=20260401/document.json"
_GAIN_RK = "raw/production/source=usda_gain_coffee/country=BR/publication_date=20260401/Brazil_Coffee_Annual.pdf"


def _gain_doc() -> dict:
    return {"source": "usda_gain_coffee", "raw_key": _GAIN_RK, "extraction_method": "pdfplumber",
            "sections": [], "full_text": ""}


def _gain_env(monkeypatch):
    """Install the GAIN fixture and return (fake, pdf_bytes, canonical_full_text)."""
    pdf_bytes = _make_pdf(_GAIN_PAGES)
    fake = _install(monkeypatch, {_GAIN_SK: json.dumps(_gain_doc()).encode(), _GAIN_RK: pdf_bytes})
    canon = extract_gain_pdf(pdf_bytes, _GAIN_RK, "usda_gain_coffee")["full_text"]
    return fake, pdf_bytes, canon


# ── branch 1: deterministic offsets (GAIN filter replication + shape) ───────────────────────────────
def test_offsets_exact_maps_to_real_page_past_filtered_pages(monkeypatch):
    _fake, _pdf, canon = _gain_env(monkeypatch)
    char_start = canon.index("MARKER BRAVO")                     # offset the chunker would have stored
    res = pdfpage.resolve_pdf_page(_GAIN_SK, snippet="MARKER BRAVO", char_start=char_start, offset_kind="exact")
    assert res["page"] == 3                                       # REAL page 3, not the kept-index 2
    assert res["kind"] == "pdf"
    assert res["url"].startswith("https://") and res["url"].endswith("e=900")
    assert res["expires_in"] == 900


def test_offsets_exact_first_page(monkeypatch):
    _fake, _pdf, canon = _gain_env(monkeypatch)
    res = pdfpage.resolve_pdf_page(_GAIN_SK, char_start=canon.index("Global coffee"), offset_kind="exact")
    assert res["page"] == 1                                       # the leading-strip shift lands page 1 correctly


def test_offsets_block_kind_also_deterministic(monkeypatch):
    # offset_kind='block' still carries a real absolute offset (the block's start) -> deterministic, not fuzzy.
    _fake, _pdf, canon = _gain_env(monkeypatch)
    res = pdfpage.resolve_pdf_page(_GAIN_SK, char_start=canon.index("Frost struck"), offset_kind="block")
    assert res["page"] == 3


def test_offsets_truncated_tail_returns_null(monkeypatch):
    _fake, _pdf, canon = _gain_env(monkeypatch)
    # (a) at/over the 60k chunker cap: an offset that could never have been minted.
    assert pdfpage.resolve_pdf_page(_GAIN_SK, char_start=pdfpage._FULLTEXT_CAP, offset_kind="exact")["page"] is None
    # (b) below the cap but past the reconstructed text (a version/pipeline mismatch) -> null, never a wrong page.
    over = len(canon) + 100
    assert pdfpage.resolve_pdf_page(_GAIN_SK, char_start=over, offset_kind="exact")["page"] is None


# ── branch 2: native fuzzy (no offsets) ─────────────────────────────────────────────────────────────
def test_fuzzy_exact_substring_hit(monkeypatch):
    _gain_env(monkeypatch)
    res = pdfpage.resolve_pdf_page(_GAIN_SK, snippet="Frost struck the arabica belt in July")
    assert res["page"] == 3                                       # whitespace-normalized exact find, first hit


def test_fuzzy_difflib_near_match_hit(monkeypatch):
    _gain_env(monkeypatch)
    # 'Julyy' (inserted char) defeats exact substring but the best-window ratio stays well above 0.85.
    res = pdfpage.resolve_pdf_page(
        _GAIN_SK, snippet="Frost struck the arabica belt in Julyy causing severe crop damage")
    assert res["page"] == 3


def test_fuzzy_miss_returns_null(monkeypatch):
    # The original build's page=None defect gets an explicit fixture: nothing clears -> null (open at top).
    _gain_env(monkeypatch)
    res = pdfpage.resolve_pdf_page(_GAIN_SK, snippet="semiconductor fabrication yields in Taiwan")
    assert res["page"] is None
    assert res["url"].startswith("https://") and res["kind"] == "pdf"


# ── branch 4: non-pdf raw_key ───────────────────────────────────────────────────────────────────────
def test_non_pdf_branch_null_page_but_presigns(monkeypatch):
    sk = "text/source=usda_wap/release_month=1999-05/document.json"
    rk = "raw/production/source=usda_wap/release_month=1999-05/wap_199905.html"
    doc = {"source": "usda_wap", "raw_key": rk, "extraction_method": "beautifulsoup"}
    _install(monkeypatch, {sk: json.dumps(doc).encode()})        # no raw bytes needed: no re-extract for non-pdf
    res = pdfpage.resolve_pdf_page(sk, snippet="anything at all")
    assert res["page"] is None and res["kind"] == "html"
    assert res["url"].startswith("https://")


# ── branch 3: textract sidecar ──────────────────────────────────────────────────────────────────────
_WASDE_SK = "text/source=usda_wasde/release_date=19850612/document.json"
_WASDE_RK = "raw/production/source=usda_wasde/release_date=19850612/wasde_198506.pdf"
_WASDE_SIDE = "text/source=usda_wasde/release_date=19850612/pages.json"


def _wasde_doc() -> bytes:
    return json.dumps({"source": "usda_wasde", "raw_key": _WASDE_RK, "extraction_method": "textract"}).encode()


def _wasde_sidecar() -> bytes:
    return json.dumps({"page_count": 3, "pages": [
        {"page": 1, "text": "cover page and table of contents"},
        {"page": 2, "text": "wheat world supply and demand balance"},
        {"page": 3, "text": "soybean crush margins improved sharply this month"}]}).encode()


def test_textract_sidecar_fuzzy_hit(monkeypatch):
    _install(monkeypatch, {_WASDE_SK: _wasde_doc(), _WASDE_SIDE: _wasde_sidecar()})
    res = pdfpage.resolve_pdf_page(_WASDE_SK, snippet="soybean crush margins improved")
    assert res["page"] == 3 and res["kind"] == "pdf"


def test_textract_without_sidecar_null_but_presigns(monkeypatch):
    _install(monkeypatch, {_WASDE_SK: _wasde_doc()})             # backfill hasn't reached this doc yet
    res = pdfpage.resolve_pdf_page(_WASDE_SK, snippet="soybean crush margins improved")
    assert res["page"] is None
    assert res["url"].startswith("https://") and res["kind"] == "pdf"


# ── error contracts: 404-worthy missing doc + never-raises degradation ──────────────────────────────
def test_missing_document_raises_pdf_document_missing(monkeypatch):
    _install(monkeypatch, {})                                    # document.json genuinely gone
    with pytest.raises(pdfpage.PdfDocumentMissing):
        pdfpage.resolve_pdf_page("text/source=x/nope/document.json")


def test_malformed_document_json_raises_missing(monkeypatch):
    _install(monkeypatch, {_GAIN_SK: b"{ this is not json"})
    with pytest.raises(pdfpage.PdfDocumentMissing):
        pdfpage.resolve_pdf_page(_GAIN_SK)


def test_never_raises_when_raw_bytes_unreadable(monkeypatch):
    # document.json present (presign works) but the RAW pdf get_object fails -> page=null, url still set.
    _install(monkeypatch, {_GAIN_SK: json.dumps(_gain_doc()).encode()})   # raw_key absent from the store
    res = pdfpage.resolve_pdf_page(_GAIN_SK, char_start=100, offset_kind="exact")
    assert res["page"] is None
    assert res["url"].startswith("https://") and res["kind"] == "pdf"


def test_never_raises_when_pdfplumber_import_fails(monkeypatch):
    # An image built without the serve-extra dep must degrade to page=null, never ImportError the request.
    import sys
    _gain_env(monkeypatch)
    monkeypatch.setitem(sys.modules, "pdfplumber", None)         # forces `import pdfplumber` to ImportError
    pdfpage._reset_caches()
    res = pdfpage.resolve_pdf_page(_GAIN_SK, char_start=10, offset_kind="exact")
    assert res["page"] is None
    assert res["url"].startswith("https://")


def test_never_raises_when_presign_fails(monkeypatch):
    fake = _install(monkeypatch, {_GAIN_SK: json.dumps(_gain_doc()).encode(), _GAIN_RK: _make_pdf(_GAIN_PAGES)})
    fake.raise_on_presign = True
    res = pdfpage.resolve_pdf_page(_GAIN_SK, snippet="MARKER BRAVO")
    assert res["url"] == "" and res["kind"] == "pdf" and res["expires_in"] == 900
