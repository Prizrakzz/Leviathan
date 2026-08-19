"""GraphRAG pilot chunker — deterministic windowing over a document's ``full_text``.

Emits ``contracts.Chunk`` rows with prev/next neighbor links (Fix 2 — so the extractor can preserve
cross-sentence relations). This is the *pilot* chunker; production swaps in Haiku propositional
chunking. Deterministic on purpose: it isolates the extraction variable under test.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date

from leviathan.graphrag.contracts import Chunk

_LOG = logging.getLogger(__name__)

# Bedrock Haiku (cross-region `global.` profile, probe-confirmed) — default chunking provider.
HAIKU_MODEL = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
# Anthropic-API Haiku (same model) — the alternative provider, billed to the Anthropic account (prepaid credit)
# instead of AWS Bedrock. Selected via provider="anthropic" + an anthropic.Anthropic client.
ANTHROPIC_HAIKU = "claude-haiku-4-5"

# D13 (ratified 2026-08-19) — the NO-NUMBER clause. The extraction-blindness probe
# (data/dec_p0/extraction_blindness.{md,json}, D-XB-1) measured this prompt as NUMBER-ANCHORED:
# over 1,456 class-tagged sentences a quantified sentence survived into a proposition 60.3% of the
# time, a MECHANISM sentence 40.0%, SUBSTITUTION 32.3%, CONDITIONAL 20.5%, RISK/SCENARIO 20.2% — a 3x
# differential against exactly the classes that ARE the graph's edge evidence. The clause below is the
# probe's amendment VERBATIM, measured on 8 windows in two independent runs (baseline -> run1 / run2):
#   conditional 15.8% -> 78.9% / 52.6%   risk_scenario 22.2% -> 68.9% / 60.0%
#   mechanism   20.0% -> 50.0% / 53.3%   substitution  26.7% -> 53.3% / 60.0%
# It ADDS an ask; every pre-existing instruction (atomicity, verbatim span, event_date discipline,
# boilerplate skip, empty-array refusal) is kept unchanged.
# SIDE-EFFECT, measured and already handled: the extra recall pushes the densest windows onto the
# 4,096-token output ceiling (WASDE livestock 4,030 -> 4,096 tok), where a cut array parses to [] and
# the whole window is lost. The batch path — the one that mints the corpus — gates on `stop_reason`
# and SPLITS the window once (evidence_batch._classify_result / _retry_lost_windows, D-EC Wave 1);
# the inline path below carries the same guard (D-XB-4). Do not ship this clause anywhere that lacks
# one of those two remedies.
_PROP_SYSTEM = (
    "You decompose a passage from an agricultural-commodity report into atomic, self-contained "
    "PROPOSITIONS for a knowledge graph. Return ONLY a JSON array of objects "
    '{"proposition": str, "verbatim_span": str, "event_date": str, "event_date_precision": str}. '
    "Rules: each proposition states ONE fact, rewritten to stand alone (resolve pronouns/ellipsis, keep "
    "commodity+country+year explicit). `verbatim_span` is the EXACT substring of the passage the "
    "proposition is based on — copy it verbatim, do not paraphrase. `event_date` is WHEN THE EVENT "
    "ITSELF OCCURRED OR WILL OCCUR when the passage states or clearly implies it (ISO 8601: YYYY-MM-DD, "
    'or YYYY-MM, or YYYY) — NOT the report\'s own date; use "" when the passage gives no such date. '
    "`event_date_precision` is one of day|month|quarter|year matching event_date's granularity "
    '("" when no date). Skip pure boilerplate (page headers, tables of contents, author/credit lists). '
    "A statement carrying NO number is still a fact: emit propositions for CONDITIONAL statements "
    "(keep the 'if X ... then Y' intact), for RISK / SCENARIO statements (keep 'upside risk'/'could'), "
    "for MECHANISM statements (keep the 'because / driven by / on lower X' clause joining cause to "
    "effect), for SUBSTITUTION and price-relationship statements between two commodities, and for "
    "ATTRIBUTED views (keep who said it). "
    "If the passage has no extractable facts, return []."
)

_EV_ISO = re.compile(r"^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$")
_EV_QTR = re.compile(r"^(\d{4})-?Q([1-4])$", re.I)


def _parse_event_date(raw: str | None, prec: str | None):
    """Best-effort parse of a model-emitted event date → (date|None, precision|None). Accepts YYYY,
    YYYY-MM, YYYY-MM-DD, YYYY-Qn; trusts the model's precision when valid, else infers from granularity.
    Never raises — an unparseable/empty date yields (None, None) so serving falls back to document_date."""
    s = (raw or "").strip()
    if not s:
        return None, None
    p = prec if prec in ("day", "month", "quarter", "year") else None
    m = _EV_QTR.match(s)
    if m:
        return date(int(m.group(1)), (int(m.group(2)) - 1) * 3 + 1, 1), "quarter"
    m = _EV_ISO.match(s)
    if not m:
        return None, None
    y, mo, d = int(m.group(1)), int(m.group(2) or 1), int(m.group(3) or 1)
    if not (1 <= mo <= 12):
        mo = 1
    try:
        dt = date(y, mo, d)
    except ValueError:
        try:
            dt = date(y, mo, 1)
        except ValueError:
            return None, None
    return dt, p or ("day" if m.group(3) else "month" if m.group(2) else "year")

_PARA = re.compile(r"\n\s*\n")  # blank-line paragraph boundaries
_SENT = re.compile(r'(?<=[.!?;])\s+(?=[A-Z0-9"(“])')  # sentence boundary (when no blank lines)
_DEFAULT_TARGET_CHARS = 1500    # ~350 tokens/chunk — small enough to localize a relation

# ── source → ORIGINAL document language (D13 rider / D-XB-5, ratified 2026-08-19) ──────────────────
# The text layer's DocumentJson carries NO `lang` key at all, so every caller passes `doc.get("lang",
# "en")` and the whole corpus was stamped `lang="en", translated=False`. Measured otherwise: `conab`
# (55 docs, Portuguese) and `fnc` (56 docs, Spanish) return ENGLISH propositions over
# ORIGINAL-LANGUAGE verbatim spans — 111 documents where the contract's own field comments
# (`lang` = detected ORIGINAL language, `proposition` = working-language (en) statement) were being
# contradicted silently. This map is the per-source truth the documents themselves do not carry; a
# source absent from it keeps the caller's `lang`.
# `sagis_cec` is deliberately NOT listed: SAGIS publishes bilingual EN/AF documents, so the English
# text IS present in the source and a proposition drawn from it is not a translation. It stays "en"
# until someone measures which half of a SAGIS document the props actually come from.
_SOURCE_LANG = {"conab": "pt", "fnc": "es"}


def _doc_lang(source: str | None, lang: str | None) -> str:
    """ORIGINAL language of *source*'s documents — the map first, then the caller's value, then "en"."""
    return _SOURCE_LANG.get((source or "").strip().lower()) or (lang or "en")


def _atoms(full_text: str, target: int) -> list[str]:
    """Break text into packing units: paragraphs, sub-split by sentence (then hard-split) when an
    atom alone exceeds the target — so a doc with only single-newline breaks can't become one
    giant chunk that de-localizes every relation."""
    out: list[str] = []
    for para in _PARA.split(full_text):
        if not para.strip():
            continue
        if len(para) <= target:
            out.append(para)
            continue
        for sent in _SENT.split(para):
            if not sent.strip():
                continue
            if len(sent) <= target:
                out.append(sent)
            else:
                out.extend(sent[j:j + target] for j in range(0, len(sent), target))
    return out


def _extraction_method(raw: str | None) -> str:
    """Map the text-layer's recorded method to the closed ExtractionMethod enum."""
    r = (raw or "").lower()
    if "textract" in r:
        return "textract"
    if "beautif" in r or "html" in r or "soup" in r:
        return "beautifulsoup"
    return "pdfplumber"


def chunk_document(
    *,
    full_text: str,
    source_key: str,
    source: str,
    document_date: date,
    lang: str,
    extraction_method: str | None,
    doc_id: str,
    target_chars: int = _DEFAULT_TARGET_CHARS,
) -> list[Chunk]:
    """Pack paragraphs into ~target_chars windows; never split a paragraph across chunks unless it
    alone exceeds the target. Returns contract-valid Chunk rows with prev/next links + char offsets."""
    method = _extraction_method(extraction_method)
    ocr = method == "textract"
    quality = 0.85 if ocr else 0.97  # proxy: no OCR confidence retained in the text layer
    doc_lang = _doc_lang(source, lang)   # D-XB-5: the map, not the (absent) doc field
    # translated stays False here BY CONSTRUCTION: this path's `proposition` IS the verbatim window, so
    # a pt/es document yields pt/es text under a pt/es `lang`. Only the LLM path below translates.

    # build (text, char_start, char_end) windows over the ORIGINAL text so offsets stay exact
    windows: list[tuple[str, int, int]] = []
    parts: list[str] = []
    buf_start: int | None = None
    buf_end: int | None = None
    cursor = 0
    for atom in _atoms(full_text, target_chars):
        idx = full_text.find(atom, cursor)
        if idx >= 0:
            cursor = idx + len(atom)
        start = idx if idx >= 0 else cursor
        end = start + len(atom)
        cur_len = sum(len(p) for p in parts)
        if parts and cur_len + len(atom) > target_chars:
            windows.append((" ".join(parts), buf_start, buf_end))
            parts, buf_start = [], None
        if not parts:
            buf_start = start
        parts.append(atom)
        buf_end = end
    if parts:
        windows.append(("\n\n".join(parts), buf_start, buf_end))

    chunks: list[Chunk] = []
    n = len(windows)
    for i, (text, cstart, cend) in enumerate(windows):
        cid = f"{doc_id}#c{i}"
        chunks.append(Chunk(
            chunk_id=cid,
            proposition=text.strip(),
            verbatim_span=text,
            source_key=source_key,
            page=0,
            char_start=cstart,
            char_end=cend,
            document_date=document_date,
            source=source,
            lang=doc_lang,
            translated=False,
            extraction_method=method,
            ocr=ocr,
            text_quality=quality,
            prev_chunk_id=f"{doc_id}#c{i - 1}" if i > 0 else None,
            next_chunk_id=f"{doc_id}#c{i + 1}" if i < n - 1 else None,
        ))
    return chunks


# ── Haiku propositional chunking (the production path; Bedrock) ────────────────────
def _parse_json_array(text: str) -> list[dict]:
    a, b = text.find("["), text.rfind("]")
    if a < 0 or b < a:
        return []
    try:
        out = json.loads(text[a:b + 1])
        return [d for d in out if isinstance(d, dict)]
    except json.JSONDecodeError:
        return []


_MAX_OUTPUT_TOKENS = 4096   # per-window output ceiling; mirrors evidence_batch._MAX_OUTPUT_TOKENS

# D13 rider / D-XB-4 (ratified 2026-08-19) — the inline path's truncation tally. A response cut at the
# output ceiling has no closing `]`, `_parse_json_array` returns [], and `propositional_chunks` used to
# substitute the ENTIRE ~5,000-char block as one "proposition" — embedded, stored, retrieved badly, and
# counted NOWHERE. The batch path guards this on `stop_reason` and splits the window once; this counter
# plus the split-retry below is that same remedy on the sync path. Read it after a run
# (`chunking.INLINE_TRUNCATIONS`); a non-zero `windows_truncated` means the corpus paid the D-XB-4 tax.
INLINE_TRUNCATIONS = {
    "windows_truncated": 0,        # windows whose FIRST call hit max_tokens
    "halves_retried": 0,           # halves submitted by the split-retry
    "halves_still_truncated": 0,   # halves that hit the ceiling AGAIN (one split is all we do)
    "blocks_fallback_whole": 0,    # windows that ended with the whole-block fallback (loss, from any cause)
}


def _reset_inline_truncations() -> None:
    """Zero the tally (per-run accounting; tests and long-lived processes call this first)."""
    for k in INLINE_TRUNCATIONS:
        INLINE_TRUNCATIONS[k] = 0


def _split_block(text: str) -> list[str]:
    """Halve a window at the nearest paragraph/line/word boundary to its midpoint. NO character is
    dropped — the halves concatenate back to *text* — so span re-location downstream is unchanged.
    Mirrors evidence_batch._split_block (kept local: evidence_batch imports THIS module, not vice versa)."""
    mid = len(text) // 2
    lo, hi = mid // 2, mid + mid // 2
    for sep in ("\n\n", "\n", " "):
        cut = text.rfind(sep, lo, hi)
        if cut > 0:
            return [text[:cut], text[cut:]]
    return [text[:mid], text[mid:]]


def _haiku_propositions(bedrock, text: str, model: str) -> tuple[list[dict], bool]:
    """One Bedrock Haiku call → (list of {proposition, verbatim_span}, truncated). Empty on any failure
    (caller falls back to the deterministic block), so a bad block never crashes the run. `truncated` is
    True when the response hit the output ceiling (`stopReason == "max_tokens"`): the array is then cut
    mid-object, parses to [], and the caller must SPLIT rather than accept the loss (D-XB-4)."""
    try:
        resp = bedrock.converse(
            modelId=model, system=[{"text": _PROP_SYSTEM}],
            messages=[{"role": "user", "content": [{"text": text}]}],
            inferenceConfig={"maxTokens": _MAX_OUTPUT_TOKENS, "temperature": 0},
        )
        truncated = (resp.get("stopReason") if hasattr(resp, "get") else None) == "max_tokens"
        return _parse_json_array(resp["output"]["message"]["content"][0]["text"]), truncated
    except Exception:  # noqa: BLE001 — Bedrock/throttle/parse errors all degrade to fallback
        return [], False


def _anthropic_propositions(client, text: str, model: str) -> tuple[list[dict], bool]:
    """One Anthropic-API Haiku call → (propositions, truncated), billed to the Anthropic account. Empty
    on failure (caller falls back to the block). The client carries its own retry/backoff for rate
    limits. `truncated` reads `stop_reason == "max_tokens"` — same gate as the batch path."""
    try:
        resp = client.messages.create(model=model, max_tokens=_MAX_OUTPUT_TOKENS, temperature=0,
                                       system=_PROP_SYSTEM, messages=[{"role": "user", "content": text}])
        out = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        return _parse_json_array(out), getattr(resp, "stop_reason", None) == "max_tokens"
    except Exception:  # noqa: BLE001 — rate-limit/overload/parse all degrade to fallback
        return [], False


def propositional_chunks(
    *,
    full_text: str,
    source_key: str,
    source: str,
    document_date: date,
    lang: str,
    extraction_method: str | None,
    doc_id: str,
    bedrock=None,
    model: str = HAIKU_MODEL,
    provider: str = "bedrock",
    anthropic_client=None,
    anthropic_model: str = ANTHROPIC_HAIKU,
    max_block_chars: int = 5000,
) -> list[Chunk]:
    """Production chunking: block the doc, then have Haiku decompose each block into atomic propositions
    (each keeping its verbatim source span). provider='bedrock' (default) calls Bedrock Haiku via the task
    IAM role; provider='anthropic' calls the Anthropic API (prepaid credit) with the given anthropic_client.
    Falls back to the deterministic block when Haiku yields nothing, so output is always contract-valid.

    D-XB-4: a window cut at the output ceiling is SPLIT ONCE and both halves are re-submitted (the batch
    path's remedy, mirrored here); every truncation, retry and whole-block fallback is logged and tallied
    in ``INLINE_TRUNCATIONS`` — the loss is never silent, which is what it used to be."""
    method = _extraction_method(extraction_method)
    ocr = method == "textract"
    quality = 0.85 if ocr else 0.97
    doc_lang = _doc_lang(source, lang)                 # D-XB-5: pt/es sources are not "en"
    translated = doc_lang != "en"                      # the LLM returns ENGLISH props over an original-language span
    if provider == "bedrock" and bedrock is None:
        import boto3
        bedrock = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))

    blocks = chunk_document(
        full_text=full_text, source_key=source_key, source=source, document_date=document_date,
        lang=lang, extraction_method=extraction_method, doc_id=f"{doc_id}_blk", target_chars=max_block_chars)

    def _call(text: str) -> tuple[list[dict], bool]:
        if provider == "anthropic":
            return _anthropic_propositions(anthropic_client, text, anthropic_model)
        return _haiku_propositions(bedrock, text, model)

    props: list[tuple] = []   # (proposition, verbatim_span, char_start, event_date, event_date_precision)
    cursor = 0
    for blk in blocks:
        raw, truncated = _call(blk.verbatim_span)
        if truncated:
            # D-XB-4: max_tokens ⇒ the array is cut mid-object ⇒ [] ⇒ the whole window would silently
            # become one 5,000-char "proposition". Split once (the batch path's remedy) and retry both
            # halves; no character is dropped, so the recovered props address `full_text` unchanged.
            INLINE_TRUNCATIONS["windows_truncated"] += 1
            _LOG.warning("chunking: block %s (%d chars) hit the %d-token output ceiling — splitting once "
                         "and retrying both halves (D-XB-4)", blk.chunk_id, len(blk.verbatim_span),
                         _MAX_OUTPUT_TOKENS)
            recovered: list[dict] = []
            for half in _split_block(blk.verbatim_span):
                if not half.strip():
                    continue
                INLINE_TRUNCATIONS["halves_retried"] += 1
                items_h, trunc_h = _call(half)
                if trunc_h:
                    INLINE_TRUNCATIONS["halves_still_truncated"] += 1
                    _LOG.warning("chunking: half of block %s (%d chars) truncated AGAIN — not re-split; "
                                 "this half's props are lost (D-XB-4)", blk.chunk_id, len(half))
                recovered.extend(items_h)
            raw = recovered
        if not raw:
            INLINE_TRUNCATIONS["blocks_fallback_whole"] += 1
            _LOG.warning("chunking: block %s yielded no propositions — falling back to the whole "
                         "%d-char block as ONE proposition (truncated=%s)", blk.chunk_id,
                         len(blk.verbatim_span), truncated)
        items = raw or [{"proposition": blk.proposition, "verbatim_span": blk.verbatim_span}]
        for it in items:
            span = (it.get("verbatim_span") or "").strip()
            prop = (it.get("proposition") or span).strip()
            if not prop:
                continue
            idx = full_text.find(span, cursor) if span else -1
            start = idx if idx >= 0 else blk.char_start
            if idx >= 0:
                cursor = idx + len(span)
            ev_dt, ev_prec = _parse_event_date(it.get("event_date"), it.get("event_date_precision"))
            props.append((prop, span or prop, start, ev_dt, ev_prec))

    chunks: list[Chunk] = []
    n = len(props)
    for i, (prop, span, start, ev_dt, ev_prec) in enumerate(props):
        cid = f"{doc_id}#p{i}"
        chunks.append(Chunk(
            chunk_id=cid, proposition=prop, verbatim_span=span, source_key=source_key, page=0,
            char_start=start, char_end=start + len(span), document_date=document_date, source=source,
            lang=doc_lang, translated=translated, extraction_method=method, ocr=ocr, text_quality=quality,
            event_date=ev_dt, event_date_precision=ev_prec,
            prev_chunk_id=f"{doc_id}#p{i - 1}" if i > 0 else None,
            next_chunk_id=f"{doc_id}#p{i + 1}" if i < n - 1 else None))
    return chunks
