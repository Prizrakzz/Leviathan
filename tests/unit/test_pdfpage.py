"""Unit tests for the 6.5 click-to-page resolver (graphrag/pdfpage.py).

Hermetic: no real S3, no real DAG/slice IP. A fake S3 stub serves in-memory ``document.json`` / ``pages.json``
bodies and a SYNTHETIC multi-page PDF hand-built in-test (pdfplumber round-trips it, so the deterministic
char->page arithmetic and the extractor page-filter replication are exercised against real pdfplumber output).
Skipped wholesale if pdfplumber is unavailable (it lives in the serve/batch extras).

Coverage: the GAIN blank+boilerplate filter replication (a skipped page must NOT shift the reported page
number), the 60k cap + past-text truncated tails, native fuzzy hit/difflib/miss->null, the non-pdf branch, the
textract sidecar branch (with + without the sidecar), the fnc TEXT-LAYER page map (branch 0: exact pages with
zero pdf I/O, unnamed sections -> honest null, a broken join property -> null rather than the generic replay's
confident wrong page), a missing-document 404 signal, and the never-raises property under S3 failures.
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


# ── branch 0: the fnc TEXT-LAYER page map ───────────────────────────────────────────────────────────
# Mirrors the live corpus shape (verified against 3 real docs + all 56 text-layer objects): one section per
# pdf page, the REAL 1-indexed page in the section NAME, '\n\n'.join(sections) == full_text byte-for-byte, and
# the first pdf page(s) absent (informe_mensual starts at page 02, exportaciones at page 03 behind an unnamed
# 'resumen_general'). The SYNTHETIC PDF below is deliberately present in S3 and deliberately DISAGREES with the
# text layer, so any test that still answers the named page proves the map came from document.json.
_FNC_SK = ("text/source=fnc/monthly_reports/report_type=cifras/publisher=fnc_informe_mensual/"
           "publication_date=2025-01-01/document.json")
_FNC_RK = ("raw/production/source=fnc/monthly_reports/report_type=cifras/upload_year=2026/upload_month=03/"
           "1.-Informe-mensual-enero-p.pdf")
_FNC_SECTION_TEXTS = [
    "Resumen ejecutivo\nEl precio interno de referencia subio durante el mes de enero.",
    "1.3 Contrato KC\nEl contrato KC de Nueva York cerro el mes con una prima notable.",
    "1.4 Precio ICO\nMARCADOR DELTA el indicador compuesto de la OIC cedio frente a diciembre.",
    "2.1 Tasa de cambio (TRM)\nLa TRM promedio del mes se ubico por debajo del promedio anual.",
    "2.2 Indice de Precios\nLa produccion de cafe de enero fue la mas alta de los ultimos anos.",
]
_FNC_PAGES = [2, 3, 4, 5, 6]                                      # pdf page 1 (the cover) has no section

# What the GENERIC replay would see if the fnc branch were missing: every pdf page, joined with '\n'. Page 1
# carries text here, so the generic answer is off by a page AND by one char per boundary -- the L1-G4 defect.
_FNC_PDF_PAGES = [["Portada Informe Mensual enero"]] + [t.splitlines() for t in _FNC_SECTION_TEXTS]


def _fnc_doc(sections=None) -> dict:
    secs = sections if sections is not None else [
        {"name": "fnc_informe_mensual_page_%02d" % p, "text": t}
        for p, t in zip(_FNC_PAGES, _FNC_SECTION_TEXTS)]
    return {"source": "fnc", "raw_key": _FNC_RK, "extraction_method": "pdfplumber", "sections": secs,
            "full_text": "\n\n".join((s.get("text") or "") for s in secs)}


def _fnc_env(monkeypatch, doc=None, with_raw=True):
    """Install an fnc fixture; ``with_raw`` also stores a DISAGREEING synthetic pdf under the raw key."""
    doc = doc if doc is not None else _fnc_doc()
    objects = {_FNC_SK: json.dumps(doc).encode()}
    if with_raw:
        objects[_FNC_RK] = _make_pdf(_FNC_PDF_PAGES)
    _install(monkeypatch, objects)
    return doc


def test_fnc_offset_maps_to_the_page_named_in_the_section(monkeypatch):
    doc = _fnc_env(monkeypatch)
    start = doc["full_text"].index("MARCADOR DELTA")             # sits in the section named ..._page_04
    res = pdfpage.resolve_pdf_page(_FNC_SK, char_start=start, offset_kind="exact")
    assert res["page"] == 4                                       # the REAL pdf page, not the 3rd kept section
    assert res["kind"] == "pdf" and res["expires_in"] == 900


def test_fnc_offset_correct_at_every_section_boundary(monkeypatch):
    # The '\n\n' separator is worth exactly one char more per boundary than the generic '\n' replay, so a
    # first/last-char probe is where an off-by-one shows up. Every span end must still name its own page.
    doc = _fnc_env(monkeypatch)
    cur = 0
    for page, text in zip(_FNC_PAGES, _FNC_SECTION_TEXTS):
        for off in (cur, cur + len(text) // 2, cur + len(text) - 1):
            got = pdfpage.resolve_pdf_page(_FNC_SK, char_start=off, offset_kind="exact")["page"]
            assert got == page, "char %d should be pdf page %d, got %r" % (off, page, got)
        cur += len(text) + 2                                      # + the '\n\n' the join inserted


def test_fnc_resolves_with_no_raw_pdf_and_no_pdfplumber(monkeypatch):
    # The whole point of branch 0: the map is in document.json, so the raw bytes are never fetched. Absent raw
    # object AND a dead pdfplumber import must still yield the exact page (the pdf leg would give null here).
    import sys
    doc = _fnc_env(monkeypatch, with_raw=False)
    monkeypatch.setitem(sys.modules, "pdfplumber", None)
    start = doc["full_text"].index("MARCADOR DELTA")
    assert pdfpage.resolve_pdf_page(_FNC_SK, char_start=start, offset_kind="exact")["page"] == 4


def test_fnc_unnamed_section_yields_null_not_a_guessed_page(monkeypatch):
    # fnc_exportaciones opens with 'resumen_general', which covers the pdf pages BEFORE the first named one.
    # An offset inside it is genuinely unknowable -> null; the pages AFTER it must still be exact, which only
    # holds if the unnamed section's length is counted in the prefix sum.
    secs = [{"name": "resumen_general", "text": "Extracto\nResumen general de las exportaciones del mes."}]
    secs += [{"name": "fnc_exportaciones_page_%02d" % p, "text": t}
             for p, t in zip((3, 4, 5), _FNC_SECTION_TEXTS[:3])]
    doc = _fnc_env(monkeypatch, doc=_fnc_doc(sections=secs))
    assert pdfpage.resolve_pdf_page(_FNC_SK, char_start=5, offset_kind="exact")["page"] is None
    start = doc["full_text"].index("MARCADOR DELTA")              # third named section -> pdf page 5
    assert pdfpage.resolve_pdf_page(_FNC_SK, char_start=start, offset_kind="exact")["page"] == 5


def test_fnc_broken_join_property_yields_null_not_the_generic_replay(monkeypatch):
    # If '\n\n'.join(sections) != full_text for THIS doc the map cannot be trusted. The raw pdf IS available,
    # so a fall-through would answer confidently -- and wrongly. The honest answer is 'page unknown'.
    doc = _fnc_doc()
    doc["full_text"] = doc["full_text"].replace("\n\n", "\n", 1)  # one boundary re-joined the wrong way
    _fnc_env(monkeypatch, doc=doc)
    res = pdfpage.resolve_pdf_page(_FNC_SK, char_start=doc["full_text"].index("MARCADOR DELTA"),
                                   offset_kind="exact")
    assert res["page"] is None
    assert res["url"].startswith("https://") and res["kind"] == "pdf"


def test_fnc_sections_without_any_page_suffix_yield_null(monkeypatch):
    _fnc_env(monkeypatch, doc=_fnc_doc(sections=[{"name": "resumen_general", "text": "Extracto del mes."},
                                                 {"name": "cuerpo", "text": "MARCADOR DELTA sin pagina."}]))
    assert pdfpage.resolve_pdf_page(_FNC_SK, char_start=25, offset_kind="exact")["page"] is None


def test_fnc_malformed_sections_never_raise_and_yield_null(monkeypatch):
    for secs in ([], "not-a-list", ["fnc_informe_mensual_page_02"],             # section that is not a dict
                 [{"name": "fnc_informe_mensual_page_02"}],                     # section with no text
                 [{"name": "fnc_informe_mensual_page_02", "text": None}]):
        doc = _fnc_doc()
        doc["sections"] = secs
        _fnc_env(monkeypatch, doc=doc)
        res = pdfpage.resolve_pdf_page(_FNC_SK, char_start=3, offset_kind="exact")
        assert res["page"] is None and res["url"].startswith("https://")


def test_fnc_fuzzy_without_offsets_uses_the_section_pages(monkeypatch):
    # 31.78% of fnc props carry no offset (chunk_coverage: 431/1,356) and land on the fuzzy leg, which now
    # searches the section texts rather than the generic pdf replay.
    _fnc_env(monkeypatch)
    assert pdfpage.resolve_pdf_page(_FNC_SK, snippet="el indicador compuesto de la OIC cedio")["page"] == 4
    assert pdfpage.resolve_pdf_page(_FNC_SK, snippet="semiconductor fabrication yields")["page"] is None


# ── guard: nothing outside the fnc family changes ───────────────────────────────────────────────────
def test_section_page_map_does_not_leak_to_other_sources(monkeypatch):
    # A GAIN doc carrying fnc-shaped page-named sections must STILL go through the pdfplumber replay: the
    # branch keys off the source family, never off the section shape.
    doc = _gain_doc()
    doc["sections"] = [{"name": "usda_gain_coffee_page_%02d" % p, "text": t}
                       for p, t in zip(_FNC_PAGES, _FNC_SECTION_TEXTS)]
    doc["full_text"] = "\n\n".join(_FNC_SECTION_TEXTS)
    pdf_bytes = _make_pdf(_GAIN_PAGES)
    _install(monkeypatch, {_GAIN_SK: json.dumps(doc).encode(), _GAIN_RK: pdf_bytes})
    canon = extract_gain_pdf(pdf_bytes, _GAIN_RK, "usda_gain_coffee")["full_text"]
    res = pdfpage.resolve_pdf_page(_GAIN_SK, char_start=canon.index("MARKER BRAVO"), offset_kind="exact")
    assert res["page"] == 3                                       # the GAIN filter replication, unchanged


def test_reconstruct_pages_family_table_is_unchanged(monkeypatch):
    # Pins the pre-fix (pages, sep) contract of every non-fnc branch against the raw pdfplumber pages, so a
    # future edit to the family table cannot silently move a page number for any other source.
    import pdfplumber
    pdf_bytes = _make_pdf([["page %d narrative line one, comfortably past the GAIN blank threshold" % i,
                            "page %d narrative line two, likewise well past it" % i] for i in range(1, 10)])
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        raw = [(i, p.extract_text() or "") for i, p in enumerate(pdf.pages, start=1)]
        assert pdfpage._reconstruct_pages("", pdf) == (raw, "\n")                 # generic fallback
        assert pdfpage._reconstruct_pages("icco_qbcs_summary", pdf) == (raw, "\n")
        assert pdfpage._reconstruct_pages("fnc", pdf) == (raw, "\n")              # unreachable, but unchanged
        assert pdfpage._reconstruct_pages("usda_wap", pdf) == (raw[:6], "\n")
        # D14 (2026-08-19): wasde_digital parses ALL pages now; the replay mirrors it unbounded
        # (the old 7-page window discarded 75% of every WASDE and kept recovered offsets dark).
        assert pdfpage._reconstruct_pages("usda_wasde", pdf) == (raw, "\n")
        assert pdfpage._reconstruct_pages("usda_gain_coffee", pdf) == (raw, "\n")  # nothing blank/boilerplate
        assert pdfpage._reconstruct_pages("mpob", pdf)[1] == "\n\n"
        assert [p for p, _ in pdfpage._reconstruct_pages("mpob", pdf)[0]] == [1, 2, 3, 4, 5]


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


# ── Task #73: verify-and-repair (Phase F, 2026-08-21) + the D12 span/sentence response fields ───────
# These run with a doc whose full_text IS the canonical extraction — the shape the live store holds.
# Every pre-#73 test above keeps full_text: "" and is untouched: an unrecoverable span skips
# verification by design (that None path is load-bearing).
def _gain_env_with_text(monkeypatch):
    pdf_bytes = _make_pdf(_GAIN_PAGES)
    canon = extract_gain_pdf(pdf_bytes, _GAIN_RK, "usda_gain_coffee")["full_text"]
    doc = {**_gain_doc(), "full_text": canon}
    fake = _install(monkeypatch, {_GAIN_SK: json.dumps(doc).encode(), _GAIN_RK: pdf_bytes})
    return fake, canon


def _span_bounds(canon: str, needle: str) -> tuple[int, int]:
    s = canon.index(needle)
    return s, s + len(needle)


def test_verify_keeps_a_correct_arithmetic_page(monkeypatch):
    _fake, canon = _gain_env_with_text(monkeypatch)
    s, e = _span_bounds(canon, "MARKER BRAVO the cited passage")
    res = pdfpage.resolve_pdf_page(_GAIN_SK, char_start=s, char_end=e, offset_kind="exact")
    assert res["page"] == 3                                       # arithmetic was right; verification agrees


def test_verify_repairs_a_wrong_arithmetic_page(monkeypatch):
    """The wb_cmo shape (15/15 measured misses): arithmetic names a NEIGHBOURING page; the span is
    searched candidate-first then outward and the true page wins."""
    _fake, canon = _gain_env_with_text(monkeypatch)
    s, e = _span_bounds(canon, "MARKER BRAVO the cited passage")
    monkeypatch.setattr(pdfpage, "_char_to_page", lambda pages, sep, cs: 1)   # deliberately wrong
    res = pdfpage.resolve_pdf_page(_GAIN_SK, char_start=s, char_end=e, offset_kind="exact")
    assert res["page"] == 3


def test_verify_recovers_when_arithmetic_says_none(monkeypatch):
    """The D14 class: a doc re-extracted under stored offsets makes the arithmetic refuse (out of range);
    the span search still finds the true page — right, or honestly null, never confidently wrong."""
    _fake, canon = _gain_env_with_text(monkeypatch)
    s, e = _span_bounds(canon, "Frost struck the arabica belt")
    monkeypatch.setattr(pdfpage, "_char_to_page", lambda pages, sep, cs: None)
    res = pdfpage.resolve_pdf_page(_GAIN_SK, char_start=s, char_end=e, offset_kind="exact")
    assert res["page"] == 3


def test_verify_nulls_a_span_present_on_no_page(monkeypatch):
    """A span that exists in full_text but on no reconstructed page (replay mismatch) -> None, never the
    arithmetic guess."""
    pdf_bytes = _make_pdf(_GAIN_PAGES)
    canon = extract_gain_pdf(pdf_bytes, _GAIN_RK, "usda_gain_coffee")["full_text"]
    phantom = "PHANTOM SPAN THAT NO RECONSTRUCTED PAGE CONTAINS ANYWHERE"
    doc = {**_gain_doc(), "full_text": canon + "\n" + phantom}
    _install(monkeypatch, {_GAIN_SK: json.dumps(doc).encode(), _GAIN_RK: pdf_bytes})
    s = (canon + "\n").__len__()
    monkeypatch.setattr(pdfpage, "_char_to_page", lambda pages, sep, cs: 1)   # confidently wrong arithmetic
    res = pdfpage.resolve_pdf_page(_GAIN_SK, char_start=s, char_end=s + len(phantom), offset_kind="exact")
    assert res["page"] is None


def test_block_offsets_are_not_verified(monkeypatch):
    """The gate: a block span is the whole parent window and straddles pages — verifying it would null the
    arithmetic answer across the largest offset-carrying cohort. block keeps today's pure arithmetic."""
    _fake, canon = _gain_env_with_text(monkeypatch)
    monkeypatch.setattr(pdfpage, "_char_to_page", lambda pages, sep, cs: 1)
    res = pdfpage.resolve_pdf_page(_GAIN_SK, char_start=0, char_end=len(canon), offset_kind="block")
    assert res["page"] == 1                                       # arithmetic survives, unverified


def test_missing_full_text_skips_verification(monkeypatch):
    """The legacy shape (every fixture above): no recoverable span -> no verification -> arithmetic as-is."""
    _fake, _pdf, canon = _gain_env(monkeypatch)                   # full_text: ""
    monkeypatch.setattr(pdfpage, "_char_to_page", lambda pages, sep, cs: 1)
    res = pdfpage.resolve_pdf_page(_GAIN_SK, char_start=canon.index("MARKER"), char_end=canon.index("MARKER") + 40,
                                   offset_kind="exact")
    assert res["page"] == 1


def test_straddling_span_falls_back_to_a_prefix(monkeypatch):
    """A span crossing the page-1 -> page-3 join is found whole on no page; the span[:40] prefix retry
    anchors on its head page instead of conceding None."""
    _fake, canon = _gain_env_with_text(monkeypatch)
    s = canon.index("Brazilian arabica output")                   # page 1, with >40 chars before the join
    e = min(len(canon), s + 150)                                  # runs across the join into page 3's text
    monkeypatch.setattr(pdfpage, "_char_to_page", lambda pages, sep, cs: None)
    res = pdfpage.resolve_pdf_page(_GAIN_SK, char_start=s, char_end=e, offset_kind="exact")
    assert res["page"] == 1                                       # span[:40] lives whole on page 1


def test_response_carries_span_and_sentence_for_exact_kinds(monkeypatch):
    _fake, canon = _gain_env_with_text(monkeypatch)
    s, e = _span_bounds(canon, "MARKER BRAVO the cited passage")
    res = pdfpage.resolve_pdf_page(_GAIN_SK, char_start=s, char_end=e, offset_kind="exact")
    assert res["span"] == "MARKER BRAVO the cited passage"
    assert res["sentence"] is not None and "MARKER BRAVO" in res["sentence"]
    assert res["sentence"].endswith("report.")                    # expanded to the containing sentence
    assert "crop damage" not in res["sentence"]                   # ...and NOT into the previous one


def test_response_span_is_null_for_block_and_missing_offsets(monkeypatch):
    _fake, canon = _gain_env_with_text(monkeypatch)
    blocky = pdfpage.resolve_pdf_page(_GAIN_SK, char_start=0, char_end=len(canon), offset_kind="block")
    assert blocky["span"] is None and blocky["sentence"] is None
    bare = pdfpage.resolve_pdf_page(_GAIN_SK, snippet="MARKER BRAVO")
    assert bare["span"] is None and bare["sentence"] is None


def test_response_span_is_null_for_textract_docs(monkeypatch):
    """D4: a scanned doc's full_text came from a DIFFERENT extraction pass than its page sidecar — its
    offsets cannot legally address what the viewer shows. Page-jump only, span null."""
    doc = {"source": "usda_wasde", "raw_key": _GAIN_RK, "extraction_method": "textract",
           "sections": [], "full_text": "some textract full text with A CITED SPAN inside it."}
    _install(monkeypatch, {_GAIN_SK: json.dumps(doc).encode(), _GAIN_RK: _make_pdf(_GAIN_PAGES)})
    res = pdfpage.resolve_pdf_page(_GAIN_SK, char_start=34, char_end=46, offset_kind="exact")
    assert res["span"] is None and res["sentence"] is None


def test_fulltext_cap_mirror_law():
    """Three hand-maintained mirrors of one constant; a stale one silently nulls legitimate offsets in the
    60k-150k band (pdfpage's own comment). No test enforced it until Phase F."""
    from leviathan.graphrag import evidence_batch as eb
    from leviathan.graphrag import novelty as nv
    assert pdfpage._FULLTEXT_CAP == eb._FULLTEXT_CAP == nv.FULLTEXT_CAP
