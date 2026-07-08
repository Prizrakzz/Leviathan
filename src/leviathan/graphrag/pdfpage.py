"""6.5 click-to-page resolver: a document citation -> the SOURCE PDF + the page the cited passage came from.

A serving citation's ``source_key`` is the TEXT-LAYER key ``text/.../document.json`` -- NOT the raw PDF. The raw
key lives INSIDE that json (``raw_key``), so recovery is a mandatory 2-hop: GET ``document.json`` -> ``raw_key``
(a BARE key in the SAME bucket) -> presign. Page recovery then branches on how the text was extracted:

  1. NATIVE pdf + OFFSETS ('exact'/'block'): DETERMINISTIC char->page. Re-run pdfplumber page-by-page REPLICATING
     the extractor's exact pipeline (GAIN skips blank + FAS-footer pages; WAP = pages 1-6; WASDE-digital = pages
     1-7; MPOB = pages 1-5 header/footer-cleaned) so the reconstructed ``full_text`` is byte-identical to the one
     the chunker measured char offsets against. Map the stored ``char_start`` (a position into
     ``full_text[:60000]``) through the leading-strip shift + per-page cumulative lengths back to the REAL
     1-indexed pdf page. Replicating the extractor's page FILTER is load-bearing: a skipped blank page shifts
     every following page number, so a naive kept-index would be WRONG.
  2. NATIVE pdf, no offsets (pre-W2.1 props): FUZZY -- whitespace-normalized exact ``find()`` per page, then a
     ``difflib`` longest-contiguous-match ratio >= 0.85; first page that clears wins, else null.
  3. TEXTRACT (scanned WASDE): query-time pdfplumber returns little/no text, so read a ``pages.json`` sidecar
     next to ``document.json`` (per-page OCR text; written by the W1b backfill) and fuzzy-match over it; absent
     sidecar -> null.
  4. NON-pdf raw_key (.html/.txt): page=null, still presign (open the doc, no page nav).

NEVER raises out of the resolver: any page-resolution failure degrades to ``{url, page: None, kind, expires_in}``
(a missing pdfplumber, a fuzzy miss, an S3 blip on the RAW bytes). The ONE hard error is a missing/unreadable
``document.json`` -- with no ``raw_key`` there is nothing to presign -- which raises :class:`PdfDocumentMissing`
for the route to map to 404. This is serving's first presign (900s, user-initiated, single doc).
"""
from __future__ import annotations

import io
import json
import os
from collections import OrderedDict
from difflib import SequenceMatcher
from typing import Optional

from leviathan.graphrag.corpus_recon import BUCKET

_EXPIRES = 900                    # presigned-url TTL (s) -- user-initiated, single doc, public source
_FULLTEXT_CAP = 60000             # mirrors evidence_batch._FULLTEXT_CAP: the chunker only sees full_text[:cap],
#                                   so a char offset >= cap can never have been minted (guard -> null)
_FUZZY_THRESHOLD = 0.85           # difflib longest-contiguous-match / len(snippet) to accept a fuzzy page hit
_WAP_MAX_PAGES = 6                # usda_wap extractor reads pdf.pages[0:6] (narrative; page 6 is the table)
_WASDE_DIGITAL_MAX_PAGES = 7      # wasde_digital reads pdf.pages[0:7] (highlights + ToC)

_DOC_CACHE_MAX = 512              # document.json is immutable per vintage -> cache freely, bounded LRU
_PAGES_CACHE_MAX = 64            # reconstructed per-page text keyed by raw_key (the expensive pdfplumber pass)
_DOC_CACHE: "OrderedDict[str, dict]" = OrderedDict()
_PAGES_CACHE: "OrderedDict[str, tuple]" = OrderedDict()

_S3 = None                        # process-wide boto3 client, lazily built; tests inject a stub via this global


class PdfDocumentMissing(Exception):
    """The ``document.json`` at ``source_key`` is missing or unreadable -- with no ``raw_key`` there is nothing to
    presign, so the route maps this (and ONLY this) to a 404. Every other failure degrades to ``page=null``."""


def _s3():
    """A lazily-built, process-wide boto3 S3 client with the shared adaptive-retry config, so a transient S3
    blip degrades rather than errors. Cached in the module global ``_S3`` (test-swappable)."""
    global _S3
    if _S3 is None:
        import boto3
        from botocore.config import Config
        _S3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"),
                           config=Config(retries={"max_attempts": 5, "mode": "adaptive"}))
    return _S3


def _reset_caches() -> None:
    """Drop the document.json + per-raw-key page-text caches (test hook; also usable if a vintage is re-written)."""
    _DOC_CACHE.clear()
    _PAGES_CACHE.clear()


def _cache_get(cache: "OrderedDict", key: str):
    if key in cache:
        cache.move_to_end(key)
        return cache[key]
    return None


def _cache_put(cache: "OrderedDict", key: str, val, maxn: int) -> None:
    cache[key] = val
    cache.move_to_end(key)
    while len(cache) > maxn:
        cache.popitem(last=False)                                 # evict the least-recently-used entry


def _norm(s: Optional[str]) -> str:
    """Whitespace-normalize a snippet/page for fuzzy matching: drop the ``from_evidence`` 140-char '...' truncation
    marker, then collapse every run of whitespace to a single space. Both sides of a match are normalized so a
    line-wrap or double-space in the extracted text never blocks an otherwise-exact hit."""
    s = (s or "").strip()
    if s.endswith("..."):
        s = s[:-3]
    return " ".join(s.split())


def _kind_of(raw_key: str) -> str:
    """The raw document's kind from its extension, so the FE picks a viewer: pdf -> pdf.js, html/txt -> open link,
    other -> download. Drives NOTHING in page resolution (branch 4 keys off '.pdf' too), purely a UI hint."""
    low = (raw_key or "").lower()
    if low.endswith(".pdf"):
        return "pdf"
    if low.endswith(".html") or low.endswith(".htm"):
        return "html"
    if low.endswith(".txt"):
        return "txt"
    return "other"


def _load_document(source_key: str) -> dict:
    """2-hop step 1: GET + parse ``document.json`` (cached by source_key). Raises :class:`PdfDocumentMissing` on a
    missing/unreadable/malformed body -- the only failure that becomes a 404, since without it there is no
    ``raw_key`` to presign."""
    hit = _cache_get(_DOC_CACHE, source_key)
    if hit is not None:
        return hit
    try:
        body = _s3().get_object(Bucket=BUCKET, Key=source_key)["Body"].read()
    except Exception as e:  # noqa: BLE001 -- NoSuchKey / access / transport: the doc is not readable -> 404
        raise PdfDocumentMissing(source_key) from e
    try:
        doc = json.loads(body)
    except Exception as e:  # noqa: BLE001 -- a corrupt document.json is as good as gone
        raise PdfDocumentMissing(source_key) from e
    _cache_put(_DOC_CACHE, source_key, doc, _DOC_CACHE_MAX)
    return doc


def _presign(raw_key: str) -> str:
    """Presign a 900s GET of the RAW document (same bucket, bare key). Local signing -- no network -- so it never
    blocks; an empty/absent raw_key or an unexpected signing error yields '' (the FE then hides the affordance)."""
    if not raw_key:
        return ""
    try:
        return _s3().generate_presigned_url(
            "get_object", Params={"Bucket": BUCKET, "Key": raw_key}, ExpiresIn=_EXPIRES)
    except Exception:  # noqa: BLE001 -- presign is local; a failure here must still not 500
        return ""


def _reconstruct_pages(source: str, pdf) -> tuple:
    """Replicate the raw_to_text extractor's page pipeline for ``source``, returning ``([(real_page, text), ...],
    sep)`` -- the KEPT pages (with their REAL 1-indexed pdf page numbers) and the join separator, so both the
    deterministic offset map and the fuzzy search see EXACTLY the text that produced ``full_text``.

    The extractor symbols (``_BLANK_THRESHOLD``/``_is_boilerplate``/``_clean_page``) are imported INSIDE this
    function: those modules import pdfplumber at module top, and this function only runs once pdfplumber is
    already loaded (in ``_page_texts``). Families:
      * usda_gain* -- all pages, skip blank (< _BLANK_THRESHOLD stripped chars) + FAS-footer boilerplate; '\\n'.
      * mpob       -- pages 1-5, header/footer-cleaned, drop pages that clean to empty; '\\n\\n'.
      * usda_wap   -- pages 1-6, no per-page filter (empty pages kept, as the extractor does); '\\n'.
      * usda_wasde -- pages 1-7 (DIGITAL; textract WASDE never reaches here), no filter; '\\n'.
      * else       -- generic native fallback: all pages, no filter; '\\n'.
    """
    src = source or ""
    if src.startswith("usda_gain"):
        from leviathan.transforms.raw_to_text.gain_pdf import _BLANK_THRESHOLD, _is_boilerplate
        pages = []
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if len(text.strip()) < _BLANK_THRESHOLD:
                continue                                          # blank page -- extractor drops it (shifts numbers)
            if _is_boilerplate(text):
                continue                                          # FAS-footer-only page -- dropped
            pages.append((i, text))
        return pages, "\n"
    if src == "mpob":
        from leviathan.transforms.raw_to_text.mpob_pdf import _MAX_NARRATIVE_PAGES, _clean_page
        pages = []
        limit = min(_MAX_NARRATIVE_PAGES, len(pdf.pages))
        for i in range(limit):
            cleaned = _clean_page(pdf.pages[i].extract_text() or "")
            if cleaned:                                           # extractor joins only truthy cleaned pages
                pages.append((i + 1, cleaned))
        return pages, "\n\n"
    if src == "usda_wap":
        limit = min(_WAP_MAX_PAGES, len(pdf.pages))
        return [(i + 1, pdf.pages[i].extract_text() or "") for i in range(limit)], "\n"
    if src == "usda_wasde":
        limit = min(_WASDE_DIGITAL_MAX_PAGES, len(pdf.pages))
        return [(i + 1, pdf.pages[i].extract_text() or "") for i in range(limit)], "\n"
    return [(i, page.extract_text() or "") for i, page in enumerate(pdf.pages, start=1)], "\n"


def _page_texts(raw_key: str, source: str) -> Optional[tuple]:
    """2-hop step 2 for native PDFs: fetch the RAW bytes and reconstruct the extractor's kept per-page text
    (cached by raw_key -- the expensive step). Returns ``(pages, sep)`` or None on ANY failure (pdfplumber
    absent, S3 error on the bytes, unparseable PDF) so the caller degrades to page=null. Lazy pdfplumber import
    so an image without it never ImportErrors the request."""
    cached = _cache_get(_PAGES_CACHE, raw_key)
    if cached is not None:
        return cached
    try:
        import pdfplumber
    except ImportError:
        return None                                               # image lacks the serve-extra dep -> page=null
    try:
        body = _s3().get_object(Bucket=BUCKET, Key=raw_key)["Body"].read()
    except Exception:  # noqa: BLE001 -- raw bytes unreadable -> no page, url still presigns
        return None
    try:
        with pdfplumber.open(io.BytesIO(body)) as pdf:
            result = _reconstruct_pages(source, pdf)
    except Exception:  # noqa: BLE001 -- corrupt/encrypted PDF -> page=null
        return None
    _cache_put(_PAGES_CACHE, raw_key, result, _PAGES_CACHE_MAX)
    return result


def _char_to_page(pages: list, sep: str, char_start: int) -> Optional[int]:
    """Map an absolute ``char_start`` (a position into the STORED ``full_text``, itself ``full_text[:60000]`` from
    the chunker's view) to the REAL 1-indexed pdf page. Reconstructs the pre-strip ``joined = sep.join(texts)``,
    shifts by the leading-whitespace strip (``full_text = joined.strip()``), then walks per-page cumulative
    lengths (a separator counts with the page BEFORE it). Out-of-range (>= cap, or past the reconstructed text --
    a version/pipeline mismatch) -> None, never a wrong page."""
    if char_start is None or char_start < 0 or char_start >= _FULLTEXT_CAP or not pages:
        return None
    joined = sep.join(t for _, t in pages)
    lead = len(joined) - len(joined.lstrip())                     # chars the extractor's final .strip() removed
    pos = char_start + lead
    if pos >= len(joined):
        return None                                               # offset beyond reconstructed text -> mismatch
    cum, n, seplen = 0, len(pages), len(sep)
    for j, (real_page, text) in enumerate(pages):
        seg = len(text) + (seplen if j < n - 1 else 0)            # attribute the join separator to the page before it
        if pos < cum + seg:
            return real_page
        cum += seg
    return pages[-1][0]                                           # unreachable given the guard; clamp defensively


def _fuzzy_page(pages: list, snippet: Optional[str]) -> Optional[int]:
    """Locate a normalized ``snippet`` by page when no offset exists (pre-W2.1 props, or sidecar OCR text). Two
    passes over the pages in order: (1) whitespace-normalized exact substring; (2) a ``difflib`` ratio >=
    _FUZZY_THRESHOLD against the BEST WINDOW of the page (the window is anchored on the longest common run and
    sized to the snippet, so a page far longer than the snippet doesn't dilute the ratio, yet a mid-string OCR
    wobble still clears). First page that hits wins; nothing clears -> None (the honest 'page unknown, open at
    top' floor -- a rewritten proposition often has no verbatim home in the PDF)."""
    needle = _norm(snippet)
    if not needle:
        return None
    hays = [(real_page, _norm(text)) for real_page, text in pages]
    for real_page, hay in hays:                                   # pass 1: exact substring (fast, preferred)
        if hay and needle in hay:
            return real_page
    for real_page, hay in hays:                                   # pass 2: best-window difflib ratio
        if not hay:
            continue
        m = SequenceMatcher(None, needle, hay, autojunk=False).find_longest_match(0, len(needle), 0, len(hay))
        if not m.size:
            continue
        lo = max(0, m.b - m.a)                                    # align the window so needle[0] ~ hay[lo]
        window = hay[lo: lo + len(needle)]
        if SequenceMatcher(None, needle, window, autojunk=False).ratio() >= _FUZZY_THRESHOLD:
            return real_page
    return None


def _sidecar_pages(source_key: str) -> Optional[list]:
    """Read the ``pages.json`` sidecar next to ``document.json`` (the W1b scanned-WASDE per-page OCR index),
    returning ``[(page, text), ...]`` or None when absent/malformed. Schema: ``{page_count, pages:[{page,
    text}]}`` with 1-indexed Textract page numbers."""
    if not source_key.endswith("document.json"):
        return None
    sidecar_key = source_key[: -len("document.json")] + "pages.json"
    try:
        data = json.loads(_s3().get_object(Bucket=BUCKET, Key=sidecar_key)["Body"].read())
    except Exception:  # noqa: BLE001 -- no sidecar yet (backfill hasn't reached this doc) -> null page
        return None
    out = []
    for p in (data.get("pages") or []):
        try:
            out.append((int(p["page"]), str(p.get("text") or "")))
        except (KeyError, TypeError, ValueError):
            continue
    return out or None


def _resolve_page(doc: dict, source_key: str, snippet: Optional[str], char_start: Optional[int],
                  offset_kind: Optional[str]) -> Optional[int]:
    """Pick the best 1-indexed page (or None) for the citation. Branches BEFORE any pdfplumber work: a textract
    doc uses the sidecar; a non-pdf raw_key has no page. Native PDFs go deterministic when an offset is present,
    else fuzzy. Raises nothing meaningful -- the caller wraps this so any surprise degrades to None."""
    raw_key = doc.get("raw_key") or ""
    method = (doc.get("extraction_method") or "").lower()
    source = doc.get("source") or ""
    if method == "textract":                                      # scanned: pdfplumber would return ~nothing
        sc = _sidecar_pages(source_key)
        return _fuzzy_page(sc, snippet) if sc else None
    if _kind_of(raw_key) != "pdf":                                # .html / .txt / other -> open the doc, no page nav
        return None
    got = _page_texts(raw_key, source)                            # native pdf: re-extract (cached) or None
    if got is None:
        return None
    pages, sep = got
    want_offset = char_start is not None and (offset_kind is None or offset_kind.lower() != "none")
    if want_offset:
        return _char_to_page(pages, sep, char_start)              # deterministic offsets-first (W2.1 props)
    return _fuzzy_page(pages, snippet)                            # pre-W2.1 props: snippet fuzzy-match


def resolve_pdf_page(source_key: str, snippet: Optional[str] = None, char_start: Optional[int] = None,
                     offset_kind: Optional[str] = None) -> dict:
    """Resolve a document citation to ``{url, page, kind, expires_in}``: a presigned URL to the source document,
    the best-guess 1-indexed page (None when unresolvable -- open at top), the raw kind (pdf/html/txt/other), and
    the 900s presign TTL. NEVER raises except :class:`PdfDocumentMissing` (document.json gone) -- every other
    failure returns page=None with the url still populated."""
    doc = _load_document(source_key)                              # raises PdfDocumentMissing -> route 404
    raw_key = doc.get("raw_key") or ""
    kind = _kind_of(raw_key)
    url = _presign(raw_key)
    try:
        page = _resolve_page(doc, source_key, snippet, char_start, offset_kind)
    except Exception:  # noqa: BLE001 -- page recovery is best-effort; the open must still work
        page = None
    return {"url": url, "page": page, "kind": kind, "expires_in": _EXPIRES}
