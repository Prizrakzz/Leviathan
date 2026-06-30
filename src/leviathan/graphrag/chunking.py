"""GraphRAG pilot chunker — deterministic windowing over a document's ``full_text``.

Emits ``contracts.Chunk`` rows with prev/next neighbor links (Fix 2 — so the extractor can preserve
cross-sentence relations). This is the *pilot* chunker; production swaps in Haiku propositional
chunking. Deterministic on purpose: it isolates the extraction variable under test.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date

from leviathan.graphrag.contracts import Chunk

# Bedrock Haiku (cross-region `global.` profile, probe-confirmed) — default chunking provider.
HAIKU_MODEL = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
# Anthropic-API Haiku (same model) — the alternative provider, billed to the Anthropic account (prepaid credit)
# instead of AWS Bedrock. Selected via provider="anthropic" + an anthropic.Anthropic client.
ANTHROPIC_HAIKU = "claude-haiku-4-5"

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
            lang=lang,
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


def _haiku_propositions(bedrock, text: str, model: str) -> list[dict]:
    """One Bedrock Haiku call → list of {proposition, verbatim_span}. Empty on any failure (caller
    falls back to the deterministic block), so a bad block never crashes the run."""
    try:
        resp = bedrock.converse(
            modelId=model, system=[{"text": _PROP_SYSTEM}],
            messages=[{"role": "user", "content": [{"text": text}]}],
            inferenceConfig={"maxTokens": 4096, "temperature": 0},
        )
        return _parse_json_array(resp["output"]["message"]["content"][0]["text"])
    except Exception:  # noqa: BLE001 — Bedrock/throttle/parse errors all degrade to fallback
        return []


def _anthropic_propositions(client, text: str, model: str) -> list[dict]:
    """One Anthropic-API Haiku call → propositions (billed to the Anthropic account). Empty on failure
    (caller falls back to the block). The client carries its own retry/backoff for rate limits."""
    try:
        resp = client.messages.create(model=model, max_tokens=4096, temperature=0,
                                       system=_PROP_SYSTEM, messages=[{"role": "user", "content": text}])
        out = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        return _parse_json_array(out)
    except Exception:  # noqa: BLE001 — rate-limit/overload/parse all degrade to fallback
        return []


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
    Falls back to the deterministic block when Haiku yields nothing, so output is always contract-valid."""
    method = _extraction_method(extraction_method)
    ocr = method == "textract"
    quality = 0.85 if ocr else 0.97
    if provider == "bedrock" and bedrock is None:
        import boto3
        bedrock = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))

    blocks = chunk_document(
        full_text=full_text, source_key=source_key, source=source, document_date=document_date,
        lang=lang, extraction_method=extraction_method, doc_id=f"{doc_id}_blk", target_chars=max_block_chars)

    props: list[tuple] = []   # (proposition, verbatim_span, char_start, event_date, event_date_precision)
    cursor = 0
    for blk in blocks:
        if provider == "anthropic":
            raw = _anthropic_propositions(anthropic_client, blk.verbatim_span, anthropic_model)
        else:
            raw = _haiku_propositions(bedrock, blk.verbatim_span, model)
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
            lang=lang, translated=False, extraction_method=method, ocr=ocr, text_quality=quality,
            event_date=ev_dt, event_date_precision=ev_prec,
            prev_chunk_id=f"{doc_id}#p{i - 1}" if i > 0 else None,
            next_chunk_id=f"{doc_id}#p{i + 1}" if i < n - 1 else None))
    return chunks
