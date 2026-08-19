"""Anthropic-Batch propositional chunking for the evidence slice (GRAPHRAG_PLAN v2 Phase 2 WS-E).

The inline build (evidence.build_index) calls Bedrock Haiku per block sequentially (~15 min, full price). This
batches the SAME Haiku propositional chunking through the Anthropic Batch API: one batch of per-block requests,
async / server-parallel, ~50% Haiku cost — the path for scaling to 31 contracts. Block splitting
(chunking.chunk_document) and embedding (bge-m3 local) stay local/free; only the LLM chunking is batched.
NO prompt caching (batch_extract measured that concurrent batch requests WRITE the cache at 2x, raising cost).

    python -m leviathan.graphrag.evidence_batch --dry-run --nodes all
    python -m leviathan.graphrag.evidence_batch --run --nodes all --n-docs 40      # submit + poll inline
    python -m leviathan.graphrag.evidence_batch --submit  ... ; --retrieve <bid>   # detached (laptop can close)
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import time

from leviathan.graphrag import chunking as ch
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import extract as ex
from leviathan.graphrag import harvest as hv
from leviathan.graphrag import novelty as nv

_OUT = ex._CFG / "evidence" / "_batches"
_MAX_BLOCK_CHARS = 5000
_FULLTEXT_CAP = 150000           # per-doc full_text head-cut before chunking (law #7: this cut is never silent --
#                                  the W1.2 dark-tally carries the count of docs it truncated).
#                                  D10, ratified 2026-08-19: raised from 60,000. cron_readiness measured the
#                                  raise at +$13.45 ONE-TIME over the whole X2 work set, with residual
#                                  truncation falling to 1.3% of chars (34 documents) -- 26 of 28 sources stop
#                                  truncating entirely; only wb_cmo_outlook (23 docs), conab (9) and one GAIN
#                                  pair still cut. usda_wasde at 150k loses NOTHING at all.
#                                  novelty.FULLTEXT_CAP and pdfpage._FULLTEXT_CAP MIRROR this constant and
#                                  move in lockstep: novelty's tail-novelty flag and pdfpage's "an offset at
#                                  or past the cap can never have been minted" refusal are both statements
#                                  ABOUT this number, and a stale mirror turns each into a wrong answer.
_MAX_OUTPUT_TOKENS = 4096        # per-window output ceiling. Deliberately NOT raised: the truncated class is
#                                  recovered by SPLITTING the window (_retry_lost_windows), which reuses this
#                                  request contract exactly, where a higher ceiling would change the cost
#                                  shape of all 13k requests to buy back 12.5% of them (P0c S2, fix 2 of 3).


def _chunk_version() -> str | None:
    """Corpus-vintage stamp for props minted THIS pass (W2.2). Agent 1 owns the source of truth
    (`evidence.current_chunk_version`); absent in a pre-P3 tree this degrades to None, and version-absence
    itself marks a pre-P3 prop (correction #3). Read at parse time so a mid-pass config change cannot split a
    single batch's vintage across records."""
    fn = getattr(ev, "current_chunk_version", None)
    return fn() if callable(fn) else None


_WS_RUN = re.compile(r"\s+")


def _ws_pattern(needle: str):
    """A pattern matching `needle` in RAW text with ANY whitespace run standing in for each of its own — the
    one-line neighbourhood that closes P0c S3. Haiku's `verbatim_span` is genuinely faithful but it
    NORMALISES WHITESPACE when it copies, and the pdfplumber text layer is full of mid-sentence line breaks,
    so a raw `find` misses spans that are byte-for-byte correct apart from a `\\n` where the model wrote a
    space. None when the needle has no non-space content."""
    parts = [re.escape(p) for p in _WS_RUN.split(needle.strip()) if p]
    return re.compile(r"\s+".join(parts)) if parts else None


def _locate_span(needle: str, block_text: str | None, block_start, block_end, cursor: int):
    """Char offsets for a returned prop within its source block (W2.1). Returns
    (char_start, char_end, offset_kind, next_cursor):

      exact    -- `needle` (the prop's verbatim_span, else its text) is found in block_text at/after `cursor`;
                  offsets are ABSOLUTE doc positions (block_start + local index) and the cursor advances past
                  it, so in-order props on one block never re-match an earlier occurrence (the
                  propositional_chunks find-with-cursor pattern, chunking.py).
      exact_ws -- the raw find missed but a WHITESPACE-TOLERANT match at/after `cursor` is UNIQUE: the same
                  absolute span, recovered through the line breaks. `block_text` is the document substring
                  (see _block_meta), so these offsets address `full_text` exactly like the raw ones.
      block    -- a rewritten prop that does not appear verbatim, OR an AMBIGUOUS whitespace match (more than
                  one occurrence from the cursor on): fall back to [block_start, block_end] (correction #5 --
                  propositional rewrites often floor to the block).
      none     -- no block text available at all (e.g. a pre-W2.1 manifest with no block fields): None offsets.

    WHY THIS IS THE LAST CHEAP MOMENT. Measured over the P0c pilot's 1,141 real props: the raw find alone
    yields `exact` on 25.7%, so 74% of props stored the WHOLE ~5,000-char window as their span; the
    whitespace-tolerant leg lifts locatability to 79.8% with only 50 of 910 hits ambiguous, and the median
    stored span collapses from ~4,900 chars (the window) to ~90 (the sentence). Both `pdfpage._char_to_page`
    and the small-to-big parent retriever want a child span; a 5,000-char span is not a usable offset for
    either. It is chunk-time and NOT backfillable -- the block text lives only in the batch manifest, never
    in `chunks/` -- so the alternative to fixing it here is re-chunking the corpus."""
    if not block_text:
        return None, None, "none", cursor
    bstart = block_start if isinstance(block_start, int) else 0
    bend = block_end if isinstance(block_end, int) else bstart + len(block_text)
    idx = block_text.find(needle, cursor) if needle else -1
    if idx >= 0:
        start = bstart + idx
        return start, start + len(needle), "exact", idx + len(needle)
    pat = _ws_pattern(needle) if needle else None
    if pat is not None:
        hits = []
        for m in pat.finditer(block_text, cursor):
            hits.append(m)
            if len(hits) > 1:                                  # ambiguous: two places it could be, so name neither
                break
        if len(hits) == 1:
            return bstart + hits[0].start(), bstart + hits[0].end(), "exact_ws", hits[0].end()
    return bstart, bend, "block", cursor


_DOC_DROP_REFUSE = 0.01          # a pass that loses more than 1% of its documents is a broken pass, not a pass


class DocReadTally:
    """Per-pass accounting for `_read_doc`: documents attempted, RETRIED, and DROPPED with the reason and the
    key, so an under-covered run says so instead of looking like a smaller corpus.

    P0c section 9: `_read_doc` caught `Exception` and returned None, `_doc_blocks` then returned `[]`, and the
    document vanished from the batch with no tally line anywhere. It fired TWICE in a FOURTEEN-document pilot
    -- both transient S3 blips, both recovered on a retry the pilot had to add itself. At 3,800 documents on a
    Fargate task a silent transient-read rate means the run under-covers the corpus and the only evidence is a
    request count nobody has a baseline for."""

    def __init__(self, *, label: str = "doc_reads"):
        self.label = label
        self.attempted = 0
        self.retried: dict[str, int] = {}                     # source_key -> attempts it took to succeed (>0)
        self.dropped: dict[str, str] = {}                     # source_key -> the last error, ASCII-safe

    def note_read(self, key: str, *, retries: int = 0) -> None:
        self.attempted += 1
        if retries:
            self.retried[key] = retries

    def note_dropped(self, key: str, exc) -> None:
        self.attempted += 1
        self.dropped[key] = str(exc).encode("ascii", "backslashreplace").decode("ascii")[:200]

    def drop_rate(self) -> float:
        return (len(self.dropped) / self.attempted) if self.attempted else 0.0

    def summary(self) -> dict:
        return {"attempted": self.attempted, "recovered_on_retry": len(self.retried),
                "dropped": len(self.dropped), "drop_rate": round(self.drop_rate(), 6),
                "dropped_source_keys": sorted(self.dropped), "retried_source_keys": sorted(self.retried)}

    def report(self) -> None:
        print(f"  doc-reads [{self.label}]: attempted={self.attempted} "
              f"recovered_on_retry={len(self.retried)} DROPPED={len(self.dropped)} "
              f"({self.drop_rate() * 100:.2f}%)")
        for k in sorted(self.dropped)[:10]:
            print(f"    DROPPED {k}: {self.dropped[k]}")
        if len(self.dropped) > 10:
            print(f"    ... and {len(self.dropped) - 10} more dropped documents")

    def raise_if_over(self, threshold: float = _DOC_DROP_REFUSE) -> None:
        """FAIL-CLOSED, the estate's law: a pass that could not read more than `threshold` of its documents
        has silently changed its own population, and every downstream count would be measured against a
        corpus that is not the corpus. Raised BEFORE the batch is created, so a refused pass bills nothing."""
        if self.attempted and self.drop_rate() > threshold:
            raise SystemExit(
                f"REFUSED: {len(self.dropped)} of {self.attempted} documents "
                f"({self.drop_rate() * 100:.2f}%) could not be read after a retry, over the "
                f"{threshold * 100:.0f}% ceiling. Nothing was submitted and nothing was billed. The keys are "
                f"printed above; re-run once S3 is healthy, or pass a doc list that excludes them "
                f"deliberately. A pass that under-covers its corpus is not a smaller pass, it is a wrong one.")


def _read_doc(s3, key: str, *, retries: int = 1, reads: "DocReadTally | None" = None) -> dict | None:
    """ONE S3 GET for a corpus doc (json) -> dict, or None after `retries` retries. Isolated so a caller that
    needs BOTH the novelty-gate full_text and the chunk blocks reads the body ONCE (law #6 -- no double GET
    per doc in the fill loop). `reads`, when given, records the attempt: recovered-on-retry, or DROPPED with
    the error (see DocReadTally -- the drop used to be silent)."""
    from leviathan.graphrag.corpus_recon import BUCKET
    last = None
    for attempt in range(retries + 1):
        try:
            doc = json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())
            if reads is not None:
                reads.note_read(key, retries=attempt)
            return doc
        except Exception as exc:                               # transient S3 blip OR a malformed doc: retry, then COUNT
            last = exc
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))                # short linear backoff; the pilot recovered on retry 1
    if reads is not None:
        reads.note_dropped(key, last)
    return None


def _doc_blocks(s3, node: str, key: str, matcher=None, *, doc: dict | None = None, tally=None,
                reads: "DocReadTally | None" = None) -> list:
    """Deterministic blocks for one doc + its shared metadata (free; no LLM). When a matcher is given, skip
    a doc that doesn't mention the commodity BEFORE chunking — so we don't pay Haiku to chunk off-topic docs
    (the inline build_index already does this; the batch path used to chunk everything then filter props).
    `doc` lets the novelty gate hand back the body it already read (one GET). `tally`, when given, records a
    doc whose full_text exceeded _FULLTEXT_CAP as a head-cut (law #7 -- no silent truncation) AND a doc whose
    `date` is a FLOOR rather than a parsed publication date (P0c S1 -- no silent Jan-1 either).

    Returns (block, shared doc meta, DOCUMENT-SUBSTRING block text) triples -- see _block_meta for why the
    third element is not `blk.verbatim_span`."""
    from leviathan.graphrag.corpus_recon import _source_of
    if doc is None:
        doc = _read_doc(s3, key, reads=reads)
    if doc is None:
        return []
    raw_full = doc.get("full_text") or ""
    if tally is not None and len(raw_full) > _FULLTEXT_CAP:
        tally.note_truncated(key)
    full = raw_full[:_FULLTEXT_CAP]
    if not full.strip() or (matcher is not None and not matcher.search(full)):
        return []
    dt, date_kind, date_layout = ev.doc_date_detail(doc, key)
    # D-XB-5 rider: the batch corpus carries the ORIGINAL language + a translated flag, same
    # semantics as the inline path (chunking._doc_lang: props are English over a non-EN span).
    lang = ch._doc_lang(_source_of(key), doc.get("lang"))
    blocks = ch.chunk_document(full_text=full, source_key=key, source=_source_of(key),
                               document_date=dt, lang=lang,
                               extraction_method=doc.get("extraction_method"), doc_id=key, target_chars=_MAX_BLOCK_CHARS)
    meta = {"contract": node, "source_key": key, "source": _source_of(key), "date": str(dt),
            "date_kind": date_kind, "date_layout": date_layout,
            "lang": lang, "translated": lang != "en"}
    if tally is not None and date_kind not in ("key", "key_month", "doc_field"):
        tally.note_date_floor(key, date_kind, date_layout)
    return [(blk, meta, full[blk.char_start:blk.char_end] or blk.verbatim_span) for blk in blocks]


def _block_meta(meta: dict, blk, block_text: str | None = None) -> dict:
    """Per-block manifest entry: the shared doc meta PLUS the block's text and char span, so retrieve() can
    locate each returned prop's offset within its block (W2.1) at parse time -- the doc body is NOT re-fetched
    on retrieve (law #6), and the block text is the only way to recover an EXACT sub-offset for a verbatim
    prop. Additive: contract/source_key/source/date are untouched, older consumers ignore the new keys.

    `block_text` is now the DOCUMENT SUBSTRING `full_text[char_start:char_end]`, not chunk_document's joined
    window (P0c S5). The window packs atoms with `" "` for every flushed block and `"\\n\\n"` for the last
    one (chunking.py:133/140) while char_start/char_end come from `full_text.find(atom)`, so the window text
    and the span it advertises describe DIFFERENT strings whenever the original inter-atom separator was not
    the join string: only 14 of 72 pilot windows satisfied `full_text[char_start:char_end] == verbatim_span`,
    and 20 of 293 `exact` offsets therefore did not reproduce from the document, one of them by 9,200 chars
    -- far enough to land on the wrong page. Storing the substring makes every offset _locate_span returns
    an offset INTO full_text by construction. The model still reads the joined window; the two differ only
    in inter-atom whitespace, which is exactly what _locate_span's whitespace-tolerant leg is insensitive
    to. Falls back to the window when no substring is supplied (the pre-P0c call shape)."""
    return {**meta, "block_text": block_text if block_text is not None else blk.verbatim_span,
            "block_start": blk.char_start, "block_end": blk.char_end}


# ── doc-keyed chunk cache: chunk each unique document ONCE, ever (WS-MS6+) ─────────────────
def _doc_cache_node(source_key: str) -> str:
    """chunks/<md5(doc key)> — a flat, filesystem-safe name for a document's cached propositions."""
    return "chunks/" + hashlib.md5(source_key.encode("utf-8")).hexdigest()


def _cached_hashes() -> set:
    """md5 names of documents already in the chunk cache (list chunks/ once, local or S3)."""
    base = ev._evid_s3()
    if base:
        import boto3
        bkt, prefix = ev._parse_s3(base.rstrip("/") + "/chunks/")
        out = set()
        for p in boto3.client("s3").get_paginator("list_objects_v2").paginate(Bucket=bkt, Prefix=prefix):
            out |= {o["Key"].rsplit("/", 1)[-1][:-6] for o in p.get("Contents", []) if o["Key"].endswith(".jsonl")}
        return out
    d = ev._EVID_DIR / "chunks"
    return {p.stem for p in d.glob("*.jsonl")} if d.exists() else set()


def _write_doc_cache(props_by_doc: dict, *, chunk_version: str | None = None,
                     allow_rechunk: bool = False, manifest=None) -> int:
    """Write chunks/<hash>.jsonl once per doc, deduping props by text (collapses a doc chunked under several
    nodes). Doc-keyed + unembedded — a future build reuses these instead of re-paying Haiku.

    G1a -- THE DOC-CACHE OVERWRITE GUARD. This is seam C3 and it is the highest-volume staler of the three,
    because rebuild_slices re-derives EVERY slice from the whole cache (:396, :412): overwriting ONE document
    silently re-rolls every driver slice that document feeds. On 2026-07-19T22:00Z, 614 objects were
    rewritten here -- at least 352 of them over documents already in the cache -- and the next day's promote
    moved 24,439 driver rows and 48 span endpoints with not one term changing and no run record anywhere.

    The guard: refuse to overwrite a cached document whose props carry a DIFFERENT chunk_version than this
    pass's, unless the caller passes --rechunk. A re-chunk is a legitimate act; a SILENT re-chunk is not.
    Refusal is evaluated over the whole pass and raised BEFORE any object is written, so a refused pass
    leaves the cache byte-identical.

    F11 -- THE SAME-DAY HOLE, CLOSED. `chunk_version` is `<corpus_fingerprint>-<UTC date>`
    (evidence.py:296-306), so TWO PASSES ON THE SAME UTC DAY carry the SAME vintage and the version
    comparison above is silent even though prop ids, text and offsets all move -- and a retried `--retrieve`
    on the day of a re-chunk is the likeliest real instance. The second leg therefore compares the prior TEXT
    SET, which `_read_doc_cache` has already put in hand for free, and refuses when a same-vintage overwrite
    would LOSE prior texts. Losing texts is the re-chunk signature; a pure ADDITION is a top-up (a doc
    re-harvested under another node contributing more props) and stays silent, which is the behaviour
    test_doc_cache_same_vintage_and_new_documents_are_never_refusals pins. `--rechunk` is the same escape
    hatch, so no new threshold and no new flag enter the law.

    Cost, honestly: one LIST of chunks/ (already taken by _cached_hashes elsewhere) plus one GET per
    OVERWRITTEN document -- the vintage lives in the object, not in its metadata, so a head-object cannot
    answer the question the guard asks. At the measured cache size (2,815 objects / 155 MB, ~55 KB per doc)
    the 2026-07-19 pass would have paid ~34 MB of GETs against a Haiku-billed chunking run. Untouched
    documents cost nothing.

    Alternative B in the plan (copy the prior object to chunks/_prior/<hash>.jsonl before overwriting) is the
    only thing that would have made 2026-07-19 REVERSIBLE, and it is recommended for the Wave-R rebuild
    specifically rather than as standing behaviour -- it is not implemented here, and its absence is why
    --rechunk should be paired with a copy-prefix step by whoever passes it."""
    planned: dict[str, list] = {}
    for source_key, props in props_by_doc.items():
        seen, uniq = set(), []
        for p in props:
            if p["text"] in seen:
                continue
            seen.add(p["text"]); uniq.append(p)
        planned[source_key] = uniq
    cached = _cached_hashes()
    refusals: list[str] = []
    transitions: dict[str, int] = {}
    deltas: dict[str, int] = {}
    n_over = 0
    for source_key, uniq in sorted(planned.items()):
        if _doc_cache_node(source_key).split("/")[-1] not in cached:
            continue                                            # a NEW document: a fill, never a re-chunk
        n_over += 1
        prior = _read_doc_cache(source_key)
        deltas[source_key] = len(uniq) - len(prior)
        prior_v = {p.get("chunk_version") for p in prior}
        for pv in sorted(prior_v, key=lambda x: (x is None, str(x))):
            transitions[f"{pv} -> {chunk_version}"] = transitions.get(f"{pv} -> {chunk_version}", 0) + 1
        safe = str(source_key).encode("ascii", "backslashreplace").decode("ascii")
        if prior and prior_v != {chunk_version}:
            refusals.append(f"chunks/{_doc_cache_node(source_key).split('/')[-1]} ({safe}): cached props "
                            f"carry vintage(s) {sorted(str(v) for v in prior_v)} but this pass stamps "
                            f"{chunk_version!r} -- that is a RE-CHUNK of an already-cached document "
                            f"({len(prior)} -> {len(uniq)} props), and rebuild_slices re-derives every "
                            f"driver slice that document feeds")
        elif prior:                                             # F11: same vintage -- compare the TEXT SET
            lost = {p["text"] for p in prior} - {p["text"] for p in uniq}
            if lost:
                refusals.append(f"chunks/{_doc_cache_node(source_key).split('/')[-1]} ({safe}): same vintage "
                                f"{chunk_version!r} on BOTH sides, but this pass DROPS {len(lost)} of "
                                f"{len(prior)} cached prop texts ({len(prior)} -> {len(uniq)} props). A "
                                f"vintage is <fingerprint>-<UTC date>, so two passes on one day share it -- "
                                f"an unchanged vintage does NOT mean unchanged text. Losing cached texts is "
                                f"a RE-CHUNK, and rebuild_slices re-derives every driver slice this document "
                                f"feeds. A pure ADDITION would not be flagged.")
    if manifest is not None:
        manifest.record_docs(written=len(planned), overwritten=n_over, vintage_transitions=transitions,
                             per_doc_delta=deltas)
    if refusals and not allow_rechunk:
        from leviathan.graphrag import write_guard as wg
        head = refusals[:10]
        raise wg.WriteRefused(head + ([f"... and {len(refusals) - 10} more re-chunked documents"]
                                      if len(refusals) > 10 else []) +
                              ["nothing was written. Pass --rechunk to take the re-chunk deliberately -- and "
                               "copy the chunks/ prefix first: this pass is not reversible and bucket "
                               "versioning is Suspended.",
                               "the parsed batch is NOT lost: Anthropic retains batch results for 29 days, so "
                               "`--retrieve <bid> --rechunk` re-runs this pass with no new Haiku spend."])
    if refusals:
        print(f"  NOTE doc-cache: --rechunk set, taking {len(refusals)} deliberate re-chunk(s) "
              f"(vintages {sorted(transitions)[:3]}...)")
    n = 0
    for source_key, uniq in planned.items():
        ev._evid_write(_doc_cache_node(source_key), "\n".join(json.dumps(p) for p in uniq))
        n += len(uniq)
    return n


def _read_doc_cache(source_key: str) -> list:
    return ev.load_index(_doc_cache_node(source_key))


def _gather_by_node(sampling: dict, aliases: dict, *, tally=None) -> dict:
    """contract -> the props of every document that node SAMPLED, each key resolved through the alias map
    first so a document the dedup gate aliased still delivers its twin's props to that node.

    Two things the bare dict comprehension could not do, and both are the read half of the dedup gate's
    liveness law:

      FALLBACK. An alias row is only as good as the canonical behind it, and a batch that was submitted and
      then cancelled or expired leaves rows pointing at documents `chunks/` never received. When the
      canonical resolves to nothing, the sampled key's OWN cache is read instead -- if the twin was later
      chunked on its own account, the node gets its props rather than a stale redirect into emptiness.

      COUNT. A key that still resolves to nothing after that is a whole DOCUMENT lost from the pass, and it
      used to be invisible: `ev._evid_read` returns '' for a missing object, `load_index` yields [], and the
      routing loop printed `SKIPPED (empty)` for a node whose props were never there to begin with. It is
      now a named counter on the tally (`gather_empty_doc_cache`), which is what makes an alias that
      resolves to emptiness LOUD.

    The per-key read is memoized across nodes, so a document sampled by several contracts is read once."""
    memo: dict[str, list] = {}

    def _props(key: str) -> list:
        if key not in memo:
            memo[key] = _read_doc_cache(key)
        return memo[key]

    out: dict[str, list] = {}
    for node, docs in sampling.items():
        recs: list[dict] = []
        for key in docs:
            canon = aliases.get(key, key)
            props = _props(canon)
            if not props and canon != key:                   # a stale alias: the twin's own cache may be live
                props = _props(key)
                if props and tally is not None:
                    tally.note_alias_fallback(node, key, canon)
            if not props:
                if tally is not None:
                    tally.note_empty_gather(node, key, canon)
                continue
            recs.extend({**p, "contract": node} for p in props)
        out[node] = recs
    return out


# ── the chunk-once DEDUP gate: path + content, one alias record (P0c / x2_cost section 4) ─────────────
_ALIAS_NODE = "_index/doc_aliases"        # duplicate source_key -> the canonical twin that was actually chunked
_CONTENT_NODE = "_index/content_hashes"   # sha1(full_text) -> the canonical source_key that carries that text
_SOURCE_SEG = re.compile(r"/source=[^/]+/")


def _path_fingerprint(key: str) -> str:
    """A document's identity ACROSS sources: its key with the `source=<src>/` segment removed. `doc_census`
    verified BY GET that co-filed rows carry byte-identical full_text, so this is a real identity and not a
    naming convention -- 776 of 7,056 rows (11.0%) are co-filings of one document under several GAIN
    families, and 279 of those sit INSIDE the never-chunked set, where `--novelty` cannot see them at all
    because `_cached_hashes` is built ONCE before the run and never learns what the run itself queues."""
    return _SOURCE_SEG.sub("/", key, count=1)


def _content_hash(full_text: str) -> str:
    return hashlib.sha1((full_text or "").encode("utf-8")).hexdigest()


def _load_index_map(node: str, key_field: str, val_field: str) -> dict:
    return {r[key_field]: r[val_field] for r in ev.load_index(node) if key_field in r and val_field in r}


def load_alias_map() -> dict:
    """duplicate source_key -> canonical source_key, from the persisted alias index. Read by retrieve()'s
    per-node gather so an ALIASED document still fans its props out to the node that sampled it."""
    return _load_index_map(_ALIAS_NODE, "source_key", "canonical_key")


def _load_alias_rows() -> dict:
    """The persisted alias index as WHOLE ROWS (source_key -> the record), not just the two fields
    `load_alias_map` needs. `flush()` rewrites the object in full, so a row's provenance -- which LAYER
    caught it, and the derived date of the twin that was folded away -- has to survive being rewritten by a
    later pass, or the record of what was folded evaporates the second time the gate runs."""
    return {r["source_key"]: r for r in ev.load_index(_ALIAS_NODE) if r.get("source_key")}


def _pit_date(key: str):
    """The publication date the PIT filter will read for a document, derived from its KEY alone
    (`evidence.pub_date_layout` -- no corpus document.json carries a date field). None when no rule parses
    the key, which is a documented refusal, never a zero."""
    return ev.pub_date_layout(key)[0]


def _canonical_twin(a: str, b: str) -> str | None:
    """Which of two BYTE-IDENTICAL documents keeps the chunk -- or None when NEITHER DOMINATES and the alias
    must be refused outright.

    THE ESTATE'S RATIFIED KEEPER RULE, mirrored one layer up. `jobs/utils/deduplicate_gain_s3.py` handles
    exactly this population in raw S3 -- one GAIN report filed under two `publication_date=` partitions
    because FAS re-posted it between crawls -- and its rule is: verify the copies are byte-identical, then
    KEEP THE ONE WITH THE LATEST publication_date and delete the older. Same question, same answer.

    WHY FIRST-WRITER-WINS WAS A PIT REGRESSION. sha1(full_text) aliases ACROSS publication_date partitions
    (997 groups / 2,226 rows measured, twins 1-30 days apart), and every prop inherits the `date` of the
    twin that actually got chunked. With first-writer-wins that date was decided by node/sample ITERATION
    ORDER, and it was reproduced in both directions on
    document=coffee_annual_sao_paulo_ato_brazil_06-19-2000 (partitions 20000601 and 20000620): one order
    stamps every prop 19 days EARLY -- leakage-permissive in precisely the field retrieve()'s asof filter
    and the pg WHERE compare. Latest-date-wins is the ratified rule AND the conservative direction, and the
    tie-break on the key itself makes the outcome independent of sampling order rather than merely
    different from it.

    NEITHER DOMINATES -> None, and the caller must then REFUSE THE ALIAS AND CHUNK BOTH. When either key's
    date is unparseable there is no comparison to make: that twin floors to Jan-1 of its year (or the
    epoch), a SENTINEL that can sit on either side of the other twin's real date, so "keep the latest" has
    no meaning over it. CHUNK-ONCE YIELDS TO PIT here -- two Haiku bills, each document carrying its own
    honest date, over one bill carrying a date nobody can defend. The class is small and named:
    `conab_survey_is_not_a_month` and `year_only` are the only refusing layouts left after the D-EC pub-date
    deriver, 62 of 7,056 documents.

    NOT used by the PATH layers, deliberately: `_path_fingerprint` removes only the `source=` segment, so
    two path twins share every date segment of their keys and their derived dates are equal BY
    CONSTRUCTION. Only the content layer can cross a partition boundary, so only the content layer needs
    this."""
    da, db = _pit_date(a), _pit_date(b)
    if da is None or db is None:
        return None
    if da != db:
        return a if da > db else b
    return min(a, b)                       # same date: the smaller key, deterministically -- never the order


def store_path_index(s3, cached: set | None = None) -> dict:
    """{path fingerprint -> the source_key ALREADY in chunks/}, from TWO paginated LISTs and ZERO GETs.

    This is the STRADDLER layer: a never-chunked row whose twin IS chunked. `_cached_hashes` is keyed on
    md5(source_key), so it cannot see it -- the twin's key differs by exactly the `source=` segment -- and
    the intra-run path set cannot either, because the twin was chunked in some earlier pass. x2_cost measured
    162 such rows across 162 fingerprints in the X2 work set (69 of usda_gain_soybeans' 70, 31 of
    usda_gain_palm_oil's 36, 29 of usda_gain_rice's 59, 14 of usda_gain_cotton's), all of which want an ALIAS
    rather than a chunking. The join is md5(corpus key) against the chunks/ listing, exactly the way x2_cost
    rebuilt the 7,056/2,815/4,241 split -- so this costs one LIST of `text/` on top of the LIST of `chunks/`
    the pass already takes, and not one GET."""
    from leviathan.graphrag.corpus_recon import BUCKET, TEXT_PREFIX
    cached = _cached_hashes() if cached is None else cached
    out: dict[str, str] = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=TEXT_PREFIX):
        for o in page.get("Contents") or []:
            key = o["Key"]
            if key.endswith("document.json") and hashlib.md5(key.encode("utf-8")).hexdigest() in cached:
                out.setdefault(_path_fingerprint(key), key)
    return out


class DedupGate:
    """`chunk once, ever` as a GATE rather than an aspiration. A PATH layer over two horizons and a CONTENT
    layer, every one of them measured:

    (a) PATH fingerprint, INTRA-RUN. `_cached_hashes()` answers "is this document already in the store?" and
        is built once, before the loop -- so two co-filings of one document sampled in the SAME run both miss
        the cache and both get billed. 279 such rows sit inside the never-chunked work set.

    (a') PATH fingerprint, AGAINST THE STORE (`store_path_index`, 2 LISTs / 0 GETs): the 162 straddlers whose
        twin was chunked in an EARLIER pass. Same layer, different horizon.

    (b) CONTENT hash, sha1(full_text), against this run AND the already-chunked store. The store carries the
        proof that this is not theoretical: `usda_gain_soybean_meal/.../..._05-31-2000` and
        `usda_gain_soybeans/.../` are ONE 35,697-char text, both sit in `chunks/` under different md5 names,
        and they carry 103 and 140 props respectively -- Haiku was paid twice for one document and returned
        two different answers. Billing rows instead of paths costs $61.92 against $53.52 on the X2 work set.

    A deduped document is ALIASED, never dropped: every skip records `dup source_key -> canonical source_key`
    into `_index/doc_aliases.jsonl`, and retrieve()'s per-node gather resolves each sampled key through that
    map before reading the doc cache. So the node that sampled the duplicate still receives the canonical
    document's props -- the dedupe removes the second HAIKU BILL, not the second commodity node. (The
    content index has to be PERSISTED because `chunks/` holds no full_text: the sha1 of a cached document is
    not recomputable from the cache, only from the text layer -- which is also why layer (a') exists, since
    the fingerprint of a cached document IS recoverable from its key alone.)

    THE CONTENT LAYER CARRIES TWO EXTRA OBLIGATIONS THE PATH LAYERS DO NOT, because it is the only one that
    can fold two documents filed under DIFFERENT publication_date partitions into one:

    PIT (see `_canonical_twin`). The canonical is the LATEST-dated twin -- the estate's ratified GAIN keeper
    rule -- with a tie-break on the key, so the surviving `date` no longer depends on sampling order; where
    neither twin's date parses, the alias is REFUSED and both are chunked. The alias row records the folded
    twin's own derived date, so the store says what was folded rather than only that something was.

    LIVENESS. An alias is a promise that the canonical HAS PROPS. `flush()` persists the content index at
    SUBMIT, before a single prop exists, so a cancelled or expired batch used to leave a permanent poison
    row: every future twin of that document was skipped silently, its alias resolved to a `chunks/` object
    that was never written, `ev._evid_read` returned '' and the node saw `SKIPPED (empty)`. The content
    layer therefore fires only when the canonical is ALREADY IN `chunks/` or has been CLAIMED (queued) by
    this same pass -- an unbacked canonical is counted (`unchunked_canonicals`) and the twin is chunked on
    its own account. retrieve()'s gather carries the read-side half of the same law."""

    def __init__(self, *, content_index: dict | None = None, alias_map: dict | None = None,
                 store_paths: dict | None = None, cached: set | None = None):
        self._content = dict(content_index if content_index is not None else
                             _load_index_map(_CONTENT_NODE, "sha1", "source_key"))
        self._paths: dict[str, str] = {}                     # fingerprint -> canonical key claimed THIS run
        self._store_paths = dict(store_paths or {})          # fingerprint -> a key already in chunks/
        self._known_rows = ({k: {"source_key": k, "canonical_key": v} for k, v in alias_map.items()}
                            if alias_map is not None else _load_alias_rows())
        self._known = {k: r["canonical_key"] for k, r in self._known_rows.items() if r.get("canonical_key")}
        self._cache: set | None = set(cached) if cached is not None else None   # md5 names in chunks/ (lazy)
        self._claimed: set = set()                           # keys QUEUED for chunking by this pass
        self.aliases: dict[str, str] = {}                    # NEW aliases minted this run
        self.alias_rows: dict[str, dict] = {}                # ... and their full records (layer + dates)
        self.by_layer: dict[str, int] = {"path": 0, "store_path": 0, "content": 0}
        self.pit_refusals: dict[str, str] = {}               # dup -> the twin it REFUSED to fold into (no PIT order)
        self.unchunked_canonicals: dict[str, str] = {}       # dup -> a canonical with NO props in chunks/
        self.deposed: dict[str, str] = {}                    # old canonical -> the later-dated twin that took over
        self._deposed_sha: dict[str, str] = {}               # sha1 -> the canonical a deposition displaced
        self._new_content: dict[str, str] = {}

    def _cached_md5s(self) -> set:
        """The chunks/ listing, taken ONCE per gate and only if the content layer ever needs it (law #6)."""
        if self._cache is None:
            self._cache = _cached_hashes()
        return self._cache

    def adopt_cache(self, cached: set) -> None:
        """Hand the gate the chunks/ listing the build loop already took, so the liveness check costs no
        second LIST (law #6). First writer wins: an explicitly-constructed cache is never overwritten."""
        if self._cache is None:
            self._cache = set(cached)

    def _has_props(self, key: str) -> bool:
        """True when aliasing INTO `key` is a promise the store can keep: it is already chunked, or this
        pass has queued it and will chunk it in the same batch."""
        return key in self._claimed or _doc_cache_node(key).split("/")[-1] in self._cached_md5s()

    def _record_alias(self, dup: str, canon: str, layer: str) -> None:
        """One alias row, counted ONCE. The by_layer breakdown used to be incremented on every `check()`, so
        a duplicate sampled by two nodes counted twice and the breakdown did not sum to `len(aliases)` in
        report(); the memo in check() plus this single increment site is what makes the two agree."""
        self.aliases[dup] = canon
        self.by_layer[layer] = self.by_layer.get(layer, 0) + 1
        d_dup, lay_dup = ev.pub_date_layout(dup)
        d_can, _lay_can = ev.pub_date_layout(canon)
        self.alias_rows[dup] = {"source_key": dup, "canonical_key": canon, "layer": layer,
                                "folded_date": str(d_dup) if d_dup else None,
                                "folded_date_layout": lay_dup,
                                "canonical_date": str(d_can) if d_can else None}

    def check(self, key: str, full_text: str) -> str | None:
        """The canonical twin of `key` when this document is a duplicate (and the alias is recorded), else
        None. Path layers first: they are free, they are what `_cached_hashes` structurally cannot cover,
        and their twins share a publication_date partition by construction so no PIT question arises."""
        if key in self.aliases:                              # already recorded: one count per DOCUMENT, not
            return self.aliases[key]                         # one per node that sampled it
        fp = _path_fingerprint(key)
        for layer, canon in (("path", self._paths.get(fp)), ("store_path", self._store_paths.get(fp))):
            if canon is None or canon == key:
                continue
            self._record_alias(key, canon, layer)
            return canon
        sha = _content_hash(full_text)
        canon = self._content.get(sha)
        if canon is None or canon == key:
            return None
        keeper = _canonical_twin(key, canon)
        if keeper is None:                                   # neither date dominates: chunk-once yields to PIT
            self.pit_refusals[key] = canon
            return None
        if keeper != canon:
            # THE NEWCOMER IS THE LATER-DATED TWIN, so it -- not the incumbent -- is canonical. Deposing here
            # is what makes the outcome ORDER-INDEPENDENT: whichever of the two the sampler reaches first,
            # the store ends with the same canonical and the same alias row. The adverse order costs one
            # extra Haiku bill (the incumbent was already queued and cannot be un-billed); it never costs a
            # wrong date, and the incumbent's props stay readable through the alias it now carries.
            self._record_alias(canon, key, "content")
            self._content[sha] = key
            self._new_content[sha] = key
            self._deposed_sha.setdefault(sha, canon)
            self.deposed[canon] = key
            return None
        if not self._has_props(canon):                       # an alias into a canonical nothing ever chunked
            self.unchunked_canonicals[key] = canon           # would be a SILENT PERMANENT DROP
            return None
        self._record_alias(key, canon, "content")
        return canon

    def claim(self, key: str, full_text: str) -> None:
        """Record `key` as the canonical carrier of its path fingerprint and its content hash — called only
        once the document is actually QUEUED for chunking, so an off-topic doc never becomes a canonical
        twin nothing will ever chunk. A claim by a LATER-dated twin takes the content hash over from an
        earlier-dated incumbent (the same keeper rule check() applies; belt-and-braces for a caller that
        claims without checking first)."""
        self._paths.setdefault(_path_fingerprint(key), key)
        self._claimed.add(key)
        sha = _content_hash(full_text)
        cur = self._content.get(sha)
        if cur == key:
            return
        if cur is None or _canonical_twin(key, cur) == key:
            self._content[sha] = key
            self._new_content[sha] = key

    def finalize(self) -> None:
        """Withdraw every record whose canonical this pass neither chunked nor found in chunks/. Idempotent,
        and run before anything is reported, summarised or persisted.

        The one path that mints such a record is the PIT deposition itself: `check()` hands the crown to a
        later-dated newcomer, and the build loop only afterwards discovers that the newcomer is OFF-TOPIC
        for the node that read it and never queues it. Persisting that alias would point the incumbent --
        a document that IS chunked -- at one that never will be, i.e. re-open the silent-permanent-drop
        hole from the other side, minted by the fix for the PIT defect. The crown goes back to the
        incumbent, the alias is withdrawn into `unchunked_canonicals`, and the per-layer counts follow."""
        for dup, canon in sorted(self.aliases.items()):
            if self._has_props(canon):
                continue
            self.aliases.pop(dup, None)
            row = self.alias_rows.pop(dup, None)
            if row:
                self.by_layer[row["layer"]] = max(0, self.by_layer.get(row["layer"], 0) - 1)
            self.unchunked_canonicals[dup] = canon
        for sha in sorted(self._new_content):
            key = self._new_content[sha]
            if self._has_props(key):
                continue
            prior = self._deposed_sha.pop(sha, None)         # the canonical this key displaced, if any
            self.deposed.pop(prior, None)
            if prior is not None and self._has_props(prior):
                self._content[sha] = prior                   # hand the crown back: that one WAS chunked
                self._new_content[sha] = prior
                continue
            del self._new_content[sha]
            if prior is not None:
                self._content[sha] = prior
            else:
                self._content.pop(sha, None)

    def flush(self) -> dict:
        """Persist the NEW aliases and content hashes (merge, newest row wins per source_key) and return the
        summary. Idempotent: re-running a pass whose documents are already claimed writes the same two
        objects back. Prior alias rows are merged WHOLE, so the provenance an earlier pass recorded (layer,
        folded date) survives this rewrite. Unbacked records are withdrawn first (see finalize)."""
        self.finalize()
        if self.alias_rows:
            rows = {**self._known_rows, **self.alias_rows}
            ev._evid_write(_ALIAS_NODE, "\n".join(json.dumps(rows[k]) for k in sorted(rows)))
        if self._new_content:
            allc = {**_load_index_map(_CONTENT_NODE, "sha1", "source_key"), **self._new_content}
            ev._evid_write(_CONTENT_NODE, "\n".join(
                json.dumps({"sha1": s, "source_key": allc[s]}) for s in sorted(allc)))
        return self.summary()

    def summary(self) -> dict:
        self.finalize()
        return {"aliased_docs": len(self.aliases), "by_layer": dict(self.by_layer),
                "aliases": {k: self.aliases[k] for k in sorted(self.aliases)},
                "alias_rows": [self.alias_rows[k] for k in sorted(self.alias_rows)],
                "pit_refusals": {k: self.pit_refusals[k] for k in sorted(self.pit_refusals)},
                "unchunked_canonicals": {k: self.unchunked_canonicals[k]
                                         for k in sorted(self.unchunked_canonicals)},
                "deposed_canonicals": {k: self.deposed[k] for k in sorted(self.deposed)}}

    def report(self) -> None:
        self.finalize()                                      # never report an alias flush would withdraw
        if self.aliases:
            print(f"  dedup: {len(self.aliases)} document(s) ALIASED to a twin instead of chunked "
                  f"(path={self.by_layer['path']}, store_path={self.by_layer['store_path']}, "
                  f"content={self.by_layer['content']}) -> {_ALIAS_NODE}.jsonl; "
                  f"their props still route to every node that sampled them")
            for k in sorted(self.aliases)[:5]:
                row = self.alias_rows.get(k) or {}
                print(f"    alias {k} -> {self.aliases[k]} "
                      f"(folded date={row.get('folded_date')}, canonical date={row.get('canonical_date')})")
        if self.deposed:
            print(f"  dedup PIT: {len(self.deposed)} canonical(s) DEPOSED by a later-dated byte-identical "
                  f"twin (the estate's keep-the-latest-publication_date rule; the surviving date no longer "
                  f"depends on sampling order)")
            for k in sorted(self.deposed)[:5]:
                print(f"    deposed {k} -> {self.deposed[k]}")
        if self.pit_refusals:
            print(f"  dedup PIT REFUSALS: {len(self.pit_refusals)} byte-identical twin(s) NOT aliased "
                  f"because neither key carries a parseable publication date -- both are chunked, each "
                  f"keeping its own honest date (chunk-once yields to PIT)")
            for k in sorted(self.pit_refusals)[:5]:
                print(f"    refused-alias {k} (twin {self.pit_refusals[k]})")
        if self.unchunked_canonicals:
            print(f"  dedup WITHHELD: {len(self.unchunked_canonicals)} twin(s) NOT aliased because the "
                  f"canonical has no props in chunks/ (a content-index row from a batch that never "
                  f"retrieved); they are chunked on their own account instead of resolving to emptiness")
            for k in sorted(self.unchunked_canonicals)[:5]:
                print(f"    withheld {k} (canonical {self.unchunked_canonicals[k]} is not chunked)")


def _build_requests(s3, nodes, n_docs, seed, *, reads: "DocReadTally | None" = None,
                    dedup: "DedupGate | None" = None):
    """Cache-aware. Sample docs per node, but Haiku-chunk each unique document only if it isn't ALREADY in
    chunks/ (and only once, not per node). `sampling` records every sampled doc per node so retrieve can gather
    the doc-cache (cached + newly chunked) and route to slices — so a re-build pays only for NEW documents.

    The body is read ONCE per candidate here (law #6) instead of inside `_doc_blocks`, because the dedup gate
    needs sha1(full_text) and the read tally needs the attempt — same number of GETs, three consumers."""
    requests, manifest, sampling = [], {}, {}
    cached = _cached_hashes()
    queued: set = set()
    reads = reads if reads is not None else DocReadTally(label="submit")
    dedup = dedup if dedup is not None else DedupGate()
    dedup.adopt_cache(cached)                                # the liveness check reuses THIS listing, no 2nd LIST
    for node in nodes:
        matcher = hv.build_matcher(ev.match_forms(node))
        keys = list(ev.sample_keys(s3, node=node, year_windows=ev.windows_for(node),
                                   n=ev.n_docs_for(node, n_docs), seed=seed))
        sampling[node] = keys
        for key in keys:
            if _doc_cache_node(key).split("/")[-1] in cached or key in queued:   # reuse cache / already queued
                continue
            doc = _read_doc(s3, key, reads=reads)
            if doc is None:                                                      # counted, never silent (P0c s9)
                continue
            if dedup.check(key, doc.get("full_text") or ""):                     # a twin: aliased, not billed twice
                continue
            blocks = _doc_blocks(s3, node, key, matcher, doc=doc, reads=reads)
            if not blocks:                                                       # off-topic here; another node may chunk it
                continue
            queued.add(key)
            dedup.claim(key, doc.get("full_text") or "")
            for blk, meta, btext in blocks:
                cid = f"r{len(requests):06d}"                                     # custom_id: ^[A-Za-z0-9_-]{1,64}$
                requests.append({"custom_id": cid, "params": {                   # no tools, no caching (see header)
                    "model": ex.HAIKU, "max_tokens": _MAX_OUTPUT_TOKENS, "temperature": 0, "system": ch._PROP_SYSTEM,
                    "messages": [{"role": "user", "content": blk.verbatim_span}]}})
                manifest[cid] = _block_meta(meta, blk, btext)                     # + block span for W2.1 offsets
    return requests, manifest, sampling


def _manifest_s3_uri(bid: str) -> str | None:
    base = ev._evid_s3()
    return base.rstrip("/") + f"/_batches/{bid}.json" if base else None


def _save_manifest(bid: str, payload: dict) -> None:
    """Persist the batch manifest locally AND (when EVIDENCE_S3 is set) to S3, so a Fargate job can retrieve+embed."""
    _OUT.mkdir(parents=True, exist_ok=True)
    (_OUT / f"{bid}.json").write_text(json.dumps(payload), encoding="utf-8")
    uri = _manifest_s3_uri(bid)
    if uri:
        import boto3
        b, k = ev._parse_s3(uri)
        boto3.client("s3").put_object(Bucket=b, Key=k, Body=json.dumps(payload).encode("utf-8"))


def _load_manifest_full(bid: str) -> dict:
    """Read the whole batch payload ({manifest, sampling}) — local _OUT first (laptop), else EVIDENCE_S3/_batches."""
    p = _OUT / f"{bid}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    uri = _manifest_s3_uri(bid)
    if uri:
        import boto3
        b, k = ev._parse_s3(uri)
        return json.loads(boto3.client("s3").get_object(Bucket=b, Key=k)["Body"].read())
    raise SystemExit(f"manifest for {bid} not found (local _OUT or EVIDENCE_S3/_batches/)")


def submit(s3, client, *, nodes, n_docs, seed: int = 0, manifest=None) -> str:
    reads = DocReadTally(label="submit")
    dedup = DedupGate(store_paths=store_path_index(s3))       # 2 LISTs, 0 GETs -- the 162 straddlers
    requests, blocks, sampling = _build_requests(s3, nodes, n_docs, seed, reads=reads, dedup=dedup)
    reads.report()
    reads.raise_if_over()                                    # fail-closed BEFORE the batch exists: bills nothing
    dedup.report()
    if not requests:
        raise SystemExit("all sampled docs are already in the chunk cache (chunks/) — nothing new to chunk; "
                         "re-derive slices for free with --reroute instead of a new batch.")
    bid = client.messages.batches.create(requests=requests).id
    dedup.flush()                                            # the aliases become real once the twins are billed
    #                                                          (a batch that never retrieves leaves rows whose
    #                                                          canonical has no props -- inert now: the gate's
    #                                                          liveness check and the gather's fallback both
    #                                                          refuse to trust an unbacked canonical)
    _save_manifest(bid, {"batch_id": bid, "manifest": blocks, "sampling": sampling})
    if manifest is not None:
        manifest.record_extraction({"doc_reads": reads.summary(), "dedup": dedup.summary()})
    new_docs = len({m["source_key"] for m in blocks.values()})
    print(f"submitted batch {bid} ({len(requests)} blocks over {new_docs} NEW docs; cached docs skipped)")
    print(f"retrieve with:  python -m leviathan.graphrag.evidence_batch --retrieve {bid}")
    return bid


def _text_of(result) -> str:
    return "".join(b.text for b in result.result.message.content if getattr(b, "type", None) == "text")


# ── W-X2 window accounting: every window the pass PAID FOR lands in exactly one named state ────────────
class BatchTally:
    """Per-batch accounting of what each window returned, because "one window in five is billed and
    produces nothing" was invisible until someone counted it by hand.

    `chunking._parse_json_array` returns `[]` on any JSONDecodeError and retrieve() then simply iterates
    nothing for that custom_id -- no counter, no warning, no retry, and no distinction between "the passage
    had no facts" and "the response could not be parsed". The P0c pilot: 15 of 72 windows (20.8%) lost, of
    which 9 were `stop_reason == "max_tokens"` (36,864 output tokens billed and discarded) and 6 were
    `end_turn` with unparseable output. NOT ONE window returned a legitimate `[]`, so today's silent-empty
    path was carrying pure loss. The 20.0 props/window rate over the windows that DID parse reproduces the
    census's published 20.5 to within 2.5% -- i.e. the whole apparent shortfall IS this loss."""

    STATES = ("ok", "empty_legitimate", "truncated", "unparseable", "failed")

    def __init__(self, *, windows_submitted: int = 0, label: str = "retrieve"):
        self.label = label
        self.windows_submitted = windows_submitted
        self.counts = dict.fromkeys(self.STATES, 0)
        self.props_emitted = 0
        self.retries = {"truncated_split": 0, "truncated_recovered": 0, "unparseable_resubmit": 0,
                        "unparseable_recovered": 0, "partial_recovery": 0, "retry_batch_failed": 0}
        self.lost_custom_ids: dict[str, str] = {}            # custom_id -> the state it ended in, after retry
        # THE GATHER-SIDE LOSS CLASS, named because it was the one that could never be seen. A sampled key
        # resolves through the alias map and then through the doc cache; when that lands on an object that
        # was never written (`ev._evid_read` returns '' for a missing key, `_read_doc_cache` yields [] and
        # the node prints `SKIPPED (empty)`), the pass loses a whole DOCUMENT with no line anywhere saying
        # so. That is the read half of the dedup gate's liveness law, and an alias that resolves to
        # emptiness must be LOUD.
        self.gather_empty: dict[str, str] = {}               # "<node> <sampled key>" -> the key it resolved to
        self.gather_alias_fallbacks: dict[str, str] = {}     # "<node> <sampled key>" -> the DEAD canonical

    def note(self, state: str) -> None:
        self.counts[state] = self.counts.get(state, 0) + 1

    def note_lost(self, custom_id: str, state: str) -> None:
        self.lost_custom_ids[custom_id] = state

    def note_recovered(self, custom_id: str, state: str) -> None:
        self.retries["truncated_recovered" if state == "truncated" else "unparseable_recovered"] += 1
        self.lost_custom_ids.pop(custom_id, None)

    def lost(self) -> int:
        return len(self.lost_custom_ids)

    def note_empty_gather(self, node: str, sampled_key: str, resolved_key: str) -> None:
        self.gather_empty[f"{node} {sampled_key}"] = resolved_key

    def note_alias_fallback(self, node: str, sampled_key: str, dead_canonical: str) -> None:
        self.gather_alias_fallbacks[f"{node} {sampled_key}"] = dead_canonical

    def summary(self) -> dict:
        return {"windows_submitted": self.windows_submitted, "counts": dict(self.counts),
                "props_emitted": self.props_emitted, "retries": dict(self.retries),
                "lost_after_retry": self.lost(),
                "lost_custom_ids": {c: self.lost_custom_ids[c] for c in sorted(self.lost_custom_ids)},
                "gather_empty_doc_cache": len(self.gather_empty),
                "gather_empty_keys": {k: self.gather_empty[k] for k in sorted(self.gather_empty)},
                "gather_alias_fallbacks": len(self.gather_alias_fallbacks),
                "gather_alias_fallback_keys": {k: self.gather_alias_fallbacks[k]
                                               for k in sorted(self.gather_alias_fallbacks)}}

    def report(self) -> None:
        c = self.counts
        print(f"  window tally [{self.label}]: submitted={self.windows_submitted} ok={c['ok']} "
              f"props={self.props_emitted} truncated={c['truncated']} unparseable={c['unparseable']} "
              f"empty_legitimate={c['empty_legitimate']} failed={c['failed']}")
        print(f"  window retries: truncated split={self.retries['truncated_split']} "
              f"recovered={self.retries['truncated_recovered']}; "
              f"unparseable resubmit={self.retries['unparseable_resubmit']} "
              f"recovered={self.retries['unparseable_recovered']}; "
              f"PARTIAL={self.retries['partial_recovery']} "
              f"(a resubmit that recovers was TRANSIENT; one that does not is DETERMINISTIC)")
        if self.lost():
            # FAIL-LOUD. Not an exception: the props that DID parse are real and refusing the pass would
            # discard them along with the batch. But a pass that silently drops a fifth of what it bought
            # is the defect this tally exists to end, so the loss is named, counted and carried into the
            # run manifest where the next pass can diff it.
            print(f"  WARNING window loss: {self.lost()} of {self.windows_submitted} windows were BILLED "
                  f"and produced NO props even after one retry -- "
                  f"{sorted(self.lost_custom_ids)[:10]}{' ...' if self.lost() > 10 else ''}")

    def report_gather(self) -> None:
        """The per-node gather's own two counters. Printed after the gather rather than folded into
        report(), because the gather runs AFTER the window tally is already on screen -- and a document
        that resolves to an empty doc cache is a loss of the same kind as a billed window that returned
        nothing, so it gets a line of its own instead of a silent `SKIPPED (empty)` downstream."""
        if self.gather_alias_fallbacks:
            print(f"  gather alias FALLBACK: {len(self.gather_alias_fallbacks)} sampled key(s) resolved "
                  f"through the alias map to a canonical with NO props and were read from their OWN doc "
                  f"cache instead -- {sorted(self.gather_alias_fallbacks)[:5]}")
        if self.gather_empty:
            print(f"  WARNING gather loss: {len(self.gather_empty)} sampled key(s) resolved to an EMPTY doc "
                  f"cache and contributed nothing to their node -- "
                  f"{sorted(self.gather_empty)[:10]}"
                  f"{' ...' if len(self.gather_empty) > 10 else ''}")


def _empty_is_legitimate(text: str) -> bool:
    """True only when the model really did emit `[]` — the state the pilot never once observed. Everything
    else that `_parse_json_array` flattens to `[]` is a parse failure wearing the same clothes."""
    a, b = text.find("["), text.rfind("]")
    if a < 0 or b < a:
        return False
    try:
        return json.loads(text[a:b + 1]) == []
    except json.JSONDecodeError:
        return False


def _classify_result(result) -> tuple[str, list]:
    """(state, parsed items) for one batch result. `stop_reason` decides the TRUNCATED class ahead of the
    parse, because a max_tokens response whose array happens to close on an inner `]` parses into a SILENT
    PARTIAL — the retry's split windows are the honest answer for that whole class."""
    if getattr(result.result, "type", None) != "succeeded":
        return "failed", []
    if getattr(result.result.message, "stop_reason", None) == "max_tokens":
        return "truncated", []
    text = _text_of(result)
    items = ch._parse_json_array(text)
    if items:
        return "ok", items
    return ("empty_legitimate" if _empty_is_legitimate(text) else "unparseable"), []


def _split_block(text: str) -> list[tuple[int, str]]:
    """Halve a window at the nearest paragraph/line/word boundary to its midpoint, as (offset, text) pairs.
    NO character is dropped — the two halves concatenate back to `text` — so each half's absolute span is
    just `block_start + offset` and the recovered props keep addressing `full_text`."""
    mid = len(text) // 2
    lo, hi = mid // 2, mid + mid // 2
    for sep in ("\n\n", "\n", " "):
        cut = text.rfind(sep, lo, hi)
        if cut > 0:
            return [(0, text[:cut]), (cut, text[cut:])]
    return [(0, text[:mid]), (mid, text[mid:])]


def _retry_requests(blocks: dict, lost: dict) -> tuple[list, dict]:
    """ONE retry batch for the lost windows, and its own block manifest keyed by the retry custom_id.

      truncated   -> SPLIT the window in half and submit both halves. A truncated window is deterministic:
                     re-submitting it unchanged fills the same 4,096 output tokens and is cut in the same
                     place. Splitting reuses the request contract exactly (same model, same max_tokens, same
                     system prompt) where raising max_tokens would change the cost shape of every one of the
                     ~13k requests to buy back the 12.5% that truncate.
      unparseable -> RE-SUBMIT AS IS, once. The transient-vs-deterministic split is UNMEASURED (the pilot saw
                     6 and never retried one), so the retry is the measurement: a recovery says transient, a
                     second failure says deterministic, and BatchTally records which."""
    reqs, man = [], {}
    for cid in sorted(lost):
        m = blocks[cid]
        text = m.get("block_text") or ""
        bstart = m.get("block_start") if isinstance(m.get("block_start"), int) else 0
        parts = _split_block(text) if lost[cid] == "truncated" else [(0, text)]
        for j, (off, sub) in enumerate(parts):
            if not sub.strip():
                continue
            rcid = f"{cid}_x{j}"                                       # custom_id: ^[A-Za-z0-9_-]{1,64}$
            reqs.append({"custom_id": rcid, "params": {
                "model": ex.HAIKU, "max_tokens": _MAX_OUTPUT_TOKENS, "temperature": 0, "system": ch._PROP_SYSTEM,
                "messages": [{"role": "user", "content": sub}]}})
            man[rcid] = {**m, "block_text": sub, "block_start": bstart + off,
                         "block_end": bstart + off + len(sub), "retry_of": cid}
    return reqs, man


def _retry_lost_windows(client, blocks: dict, lost: dict, *, tally: "BatchTally", poll_s: int = 20) -> dict:
    """Submit the retry batch, poll it, and return {original custom_id: (block meta, items)} for every window
    it recovered. Sub-window items are concatenated IN ORDER under the ORIGINAL custom_id, so `parent_id` and
    the `#i` prop ids stay stable and a recovered window is indistinguishable downstream from one that never
    truncated. Retried ONCE and once only: the recovered set is not itself re-retried."""
    reqs, rman = _retry_requests(blocks, lost)
    if not reqs:
        return {}
    tally.retries["truncated_split"] = sum(1 for c in lost.values() if c == "truncated")
    tally.retries["unparseable_resubmit"] = sum(1 for c in lost.values() if c == "unparseable")
    rid = client.messages.batches.create(requests=reqs).id
    print(f"  window retry: {len(reqs)} sub-request(s) over {len(lost)} lost window(s) -> batch {rid}")
    while client.messages.batches.retrieve(rid).processing_status != "ended":
        print(f"  retry batch {rid}: still processing ...")
        time.sleep(poll_s)
    submitted = collections.Counter(m["retry_of"] for m in rman.values())
    got: dict[str, list] = {}
    for r in client.messages.batches.results(rid):
        if r.custom_id not in rman:
            continue
        state, items = _classify_result(r)
        if state == "ok":
            got.setdefault(rman[r.custom_id]["retry_of"], []).append((r.custom_id, rman[r.custom_id], items))
    out = {}
    for cid, parts in got.items():
        parts.sort(key=lambda p: p[0])                                 # _x0 before _x1: block order is prop order
        out[cid] = [(meta, items) for _rcid, meta, items in parts]
        # A truncated window split in two whose SECOND half also fails is a PARTIAL recovery, and calling it
        # a recovery would re-open the exact hole this whole tally exists to close: the props are back, some
        # of the props are not, and nothing said so. Counted separately, and there is no second retry.
        if len(parts) < submitted[cid]:
            tally.retries["partial_recovery"] += 1
        tally.note_recovered(cid, lost[cid])
    return out


# ── W1.2 dark-at-birth tally: every prop lands in exactly one named state (no silent fourth state) ──────────
class DarkTally:
    """Per-pass accounting of where every routed prop lands, so 'valuable but invisible' stops being an
    epistemic shrug and becomes a queue with a size. Four mutually-exclusive states per prop:

        both           -- matched a commodity matcher AND has >=1 driver slice
        commodity_only -- matched a commodity, no driver slice
        driver_only    -- matched NO commodity, but has >=1 driver slice
        neither         -- matched no commodity and no driver slice (the E2-clustering queue)

    Props are deduped by (source_key, text) and the commodity/driver signals OR-fold across the (possibly
    multi-node) passes that touch the same prop, so a prop routed under two commodities is counted ONCE. Fed
    only the booleans the routing loop already computed -- pure in-memory, no S3 (law #6). `truncated_docs`
    rides the same manifest: source_keys whose full_text was head-cut at _FULLTEXT_CAP (law #7). So does
    `date_floors`: source_keys whose `date` is a FLOOR (year -> Jan-1) rather than a parsed publication date,
    with the layout that refused -- the same law applied to the PIT field (P0c S1)."""

    def __init__(self, *, label: str = "dark_tally"):
        self.label = label
        self._seen: dict = {}                            # (source_key, text) -> [commodity_hit, driver_hit]
        self.truncated_docs: set = set()                 # source_keys head-cut at _FULLTEXT_CAP (law #7)
        self.date_floors: dict = {}                      # source_key -> "<kind>/<layout>" (P0c S1)

    def add(self, source_key, text, *, commodity_hit: bool, driver_hit: bool) -> None:
        k = (source_key, text)
        cur = self._seen.get(k)
        if cur is None:
            self._seen[k] = [bool(commodity_hit), bool(driver_hit)]
        else:
            cur[0] = cur[0] or bool(commodity_hit)
            cur[1] = cur[1] or bool(driver_hit)

    def note_truncated(self, source_key) -> None:
        self.truncated_docs.add(source_key)

    def note_date_floor(self, source_key, kind: str, layout: str) -> None:
        """A document whose `date` could not be parsed from its key. The floor is leakage-PERMISSIVE (always
        on or before the true release), so it is recorded by KEY and by the layout that refused, never
        aggregated into a single count that hides which source is dark."""
        self.date_floors[source_key] = f"{kind}/{layout}"

    def counts(self) -> dict:
        c = {"both": 0, "commodity_only": 0, "driver_only": 0, "neither": 0}
        for comm, drv in self._seen.values():
            if comm and drv:
                c["both"] += 1
            elif comm:
                c["commodity_only"] += 1
            elif drv:
                c["driver_only"] += 1
            else:
                c["neither"] += 1
        return c

    def neither_keys(self) -> list:
        """source_keys of the `neither` props -- the E2-clustering queue (deduped, sorted for a stable diff)."""
        return sorted({k[0] for k, (comm, drv) in self._seen.items() if not comm and not drv})

    def manifest(self) -> dict:
        return {"tally": self.label, "n_props": len(self._seen), "counts": self.counts(),
                "neither_source_keys": self.neither_keys(),
                # the key name is the LAW, not the number: it stayed `..._60k` through the D10 raise to 150k
                # and that read as a stale artifact, so it now names the constant it reports on.
                "n_docs_truncated_at_cap": len(self.truncated_docs), "fulltext_cap": _FULLTEXT_CAP,
                "truncated_source_keys": sorted(self.truncated_docs),
                "n_docs_date_floored": len(self.date_floors),
                "date_floors": {k: self.date_floors[k] for k in sorted(self.date_floors)}}


def _flush_dark_tally(tally: "DarkTally") -> str:
    """Write the tally manifest (local configs/graphrag/eval/ + optional EVIDENCE_S3/eval/ -- the e0_harness
    write_text+put_object idiom) and print an ASCII summary. Timestamped filename so a rerun never overwrites
    the prior artifact (the census BEFORE-overwrite lesson). Returns the local path."""
    from pathlib import Path
    payload = tally.manifest()
    c = payload["counts"]
    name = f"dark_tally_{tally.label}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    out = ex._CFG / "eval" / name
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    base = ev._evid_s3()
    if base:
        import boto3
        b, k = ev._parse_s3(base.rstrip("/") + f"/eval/{name}")
        boto3.client("s3").put_object(Bucket=b, Key=k, Body=json.dumps(payload).encode("utf-8"))
    print(f"  dark-tally [{tally.label}]: both={c['both']} commodity_only={c['commodity_only']} "
          f"driver_only={c['driver_only']} neither={c['neither']} "
          f"(neither-queue={len(payload['neither_source_keys'])}, "
          f"{_FULLTEXT_CAP}-truncated docs={payload['n_docs_truncated_at_cap']}, "
          f"date-floored docs={payload['n_docs_date_floored']})")
    print(f"  dark-tally manifest -> {out}")
    return str(out)


def _plan_raw_write(raw_by_node: dict, *, manifest=None, allow_churn: float | None = None):
    """F2 -- the `_raw/<node>` archive as a GUARDED LAYER of its own. Returns a write_guard.WritePlan.

    `_raw/` was the fourth wholesale seam and the least visible one: it was written inside
    _route_and_write's node loop, AHEAD of every other guard in the pass, with no churn ratio, no span tuple,
    no empty guard, no manifest line -- and it SURVIVED a refusal, so a refused pass left the store in a
    state where the next `--reroute` derived every commodity and driver slice from new inputs. That is
    structurally C3 one layer up: overwrite one upstream object, silently re-roll everything downstream.
    24 objects / 79,974,491 B, and `reroute` reads exactly it (`ev.load_index(f"_raw/{n}")`).

    span_tuple and resolve_prior work on it unmodified -- a _raw record carries the same date / event_date
    fields as a slice record (it is the slice record minus the vector). The empty-node SKIP matches the
    commodity path exactly: a node that archived nothing keeps its prior archive."""
    from leviathan.graphrag import write_guard as wg
    records = {n: recs for n, recs in raw_by_node.items() if recs}
    skipped = sorted(n for n, recs in raw_by_node.items() if not recs)
    if skipped and manifest is not None:
        manifest.warnings.append(f"_raw: routed 0 props for {skipped} -- prior _raw archive left intact, "
                                 f"NOT rewritten empty (the reroute derivation source)")

    def _payload(node: str):
        def _mk() -> str:                                      # serialize lazily: a refused pass pays nothing
            return "\n".join(json.dumps(r) for r in records[node])
        return _mk

    return wg.plan_write("_raw", "_raw/", {n: _payload(n) for n in records}, records=records,
                         manifest=manifest, allow_churn=allow_churn, write_fn=ev._evid_write,
                         node_of=lambda n: f"_raw/{n}")


def _plan_commodity_write(kept_by_node: dict, *, backend: str, manifest=None,
                          allow_churn: float | None = None):
    """G1d's plan half -- everything _commodity_guarded_write does except the write. Returns a WritePlan.

    F1: _route_and_write and rebuild_slices both write more than one layer, so they must plan every layer
    before committing any of them; this is the commodity plan they union.

    LANE-C DETERMINISM -- THE COMMODITY TWIN OF G5a. rebuild_slices builds `kept_by_node` by iterating
    `for h in _cached_hashes()` (:614) and _cached_hashes returns a SET of md5 hex strings. PYTHONHASHSEED
    is set nowhere in docker/, jobs/, src/, infra/, scripts/ or in the production jobdef environment, so str
    hashing is per-process randomized and the ROW ORDER this function serialized moved on every run -- the
    24 top-level slices are 11,119,127,224 bytes and NONE of them was byte-reproducible. The driver layer
    has been immune since G5a because plan_driver_slices runs every slice through ev._truncation_order
    before serializing (evidence.py:1126); this layer serialized whatever order the set handed it.

    ONE DOCTRINE, ONE CALL: ev._truncation_order itself -- date DESC, ties by (source_key, id) ASC -- and
    deliberately the function, not a re-typed copy of its key, so the two layers cannot drift apart. The
    commodity layer has no cap, so this is ORDERING ONLY. The population is identical and the quantities the
    guard actually trips on are order-invariant: write_guard.span_tuple's n and its min/max endpoints, and
    the object's TOTAL byte size, which permuting whole JSONL lines conserves exactly. Because the bytes are
    conserved, resolve_prior's manifest branch still matches on after_bytes, so the prior census is read from
    the manifest and not re-estimated. (The one order-sensitive read in the store is resolve_prior's FALLBACK
    `nbytes / first-line length` estimate, reached only when no manifest entry matches -- and it is an
    estimate that already moves with any content change, not a guard input this reorder newly disturbs.)

    What DOES move is the byte SEQUENCE inside each slice object, so the next --rebuild-slices pass rewrites
    all 24 commodity slices with their rows in the new order and RE-BASELINES the write-guard manifests.
    That is BY DESIGN and it is one-time: from that pass onward two runs over the same doc-cache produce
    byte-identical commodity slices, which is the property the manifests are supposed to be asserting."""
    from leviathan.graphrag import write_guard as wg
    records = {n: ev._truncation_order(recs) for n, recs in kept_by_node.items() if recs}
    skipped = sorted(n for n, recs in kept_by_node.items() if not recs)
    if skipped and manifest is not None:
        manifest.warnings.append(f"commodity: routed 0 props for {skipped} -- prior slice files left intact "
                                 f"(the evidence_batch.py:433 empty guard), NOT rewritten empty")

    def _payload(node: str):
        def _mk() -> str:                                      # embed LAZILY: a refused pass pays no embed
            recs = records[node]
            for r, v in zip(recs, ev.embed([r["text"] for r in recs], backend=backend)):
                r["vector"], r["backend"] = v, backend
            return "\n".join(json.dumps(r) for r in recs)
        return _mk

    return wg.plan_write("commodity", "", {n: _payload(n) for n in records}, records=records,
                         manifest=manifest, allow_churn=allow_churn, write_fn=ev._evid_write,
                         node_of=lambda n: n)


def _commodity_guarded_write(kept_by_node: dict, *, backend: str, manifest=None,
                             allow_churn: float | None = None) -> int:
    """G1d -- the COMMODITY wholesale write, guarded. Shared by _route_and_write and rebuild_slices.

    Revision 1 of the wave plan cited evidence_batch.py:433's `if not recs: continue` as the TEMPLATE for the
    driver-slice empty guard and never proposed coverage FOR the commodity path itself. The gap is not small:
    those 24 top-level slices are 11,119,127,224 bytes -- LARGER than the entire drivers/ layer (1.361 GB) --
    and they contribute 24 of the artifact's 125 nodes, including `arabica_coffee`, `robusta_coffee` and
    `cocoa`, which carry the three sentinel episodes and ground both of the deck's MUST re-probe rows. After
    the driver-side guard landed, a --rebuild-slices pass could still have silently re-rolled all of them.

    The empty-node SKIP is preserved exactly (a node that routed nothing is omitted, so its prior file
    survives -- refusing the whole pass over one empty node would be a regression); every other leg of the
    driver guard applies. Prior population comes from ONE non-recursive LIST of the top-level *.jsonl.

    SINGLE-LAYER entry point, retained for callers that write only the commodity layer. The two multi-layer
    callers plan through _plan_commodity_write instead (F1)."""
    from leviathan.graphrag import write_guard as wg
    plan = _plan_commodity_write(kept_by_node, backend=backend, manifest=manifest, allow_churn=allow_churn)
    wg.raise_if_refused(plan)
    return wg.commit_write(plan)


def _route_and_write(by_node: dict, *, backend: str | None = None, drivers: bool = True,
                     tally: "DarkTally | None" = None, manifest=None,
                     allow_churn: float | None = None) -> int:
    """Write the _raw/<node> archive (EVERY prop, unembedded) + route to commodity & driver slices (embed the
    routed). Shared by retrieve (props from the batch) and reroute (props from the persisted _raw archive). The
    archive is the future-proofing: re-deriving slices after the driver YAML grows NEVER re-chunks — chunk once,
    route forever. Pure-driver props (B40/freight/FX/El Nino/metals) are routed to driver slices, not dropped.
    When a `tally` is passed (W1.2, opt-in), each prop is also classified into the four dark-at-birth states and
    a manifest is written at the end — the routing output itself is byte-identical either way.

    F1/F2 — ALL THREE LAYERS ARE PLANNED BEFORE ANY OF THEM COMMITS. The `_raw/` archive used to be written
    inside this loop, ahead of every guard; the commodity layer used to complete all 24 writes before the
    driver guard was ever evaluated. Both are gone: the loop only ROUTES now, then the three layers are
    planned, their refusals are unioned and raised once by write_guard.raise_if_refused, and only then do the
    commit loops run. A refusal anywhere leaves _raw/, the 24 commodity slices AND the 101 driver slices
    byte-identical -- which is what the module docstring always claimed and what the 2026-07-20 shape
    (commodity fine, drivers collapse) would otherwise land in."""
    from leviathan.graphrag import write_guard as wg
    backend = backend or ev.DEFAULT_BACKEND
    driver_sink: dict[str, list[dict]] | None = {} if drivers else None
    kept_by_node: dict[str, list[dict]] = {}
    raw_by_node: dict[str, list[dict]] = {}
    for node, recs in by_node.items():
        raw = [{k: v for k, v in r.items() if k != "vector"} for r in recs]    # archive: text+date+source+event_date, no vector
        raw_by_node[node] = raw                                                # written below, past the guard
        if driver_sink is not None:                                            # multi-label, independent of the commodity filter
            for r in raw:
                for dn in ev.driver_slices_for(r["text"]):
                    driver_sink.setdefault(dn, []).append({**r, "driver": dn})
        matcher = hv.build_matcher(ev.match_forms(node))
        kept = [dict(r) for r in raw if matcher.search(r["text"])]             # commodity slice: on-topic props
        kept_by_node[node] = kept                                              # embed+write below, past the guard
        dest = f"evidence/{node}.jsonl" if kept else "SKIPPED (empty -- prior slice left intact)"
        print(f"  {node}: {len(kept)} props -> {dest}  ({len(raw)} to archive in _raw/)")
        if tally is not None:                                                  # in-memory reclassification (no S3)
            for r in raw:
                tally.add(r["source_key"], r["text"], commodity_hit=bool(matcher.search(r["text"])),
                          driver_hit=bool(ev.driver_slices_for(r["text"])))
    plans = [_plan_raw_write(raw_by_node, manifest=manifest, allow_churn=allow_churn),                # F2
             _plan_commodity_write(kept_by_node, backend=backend, manifest=manifest,                  # G1d
                                   allow_churn=allow_churn)]
    if driver_sink:
        plans.append(ev.plan_driver_slices(driver_sink, backend=backend, manifest=manifest,           # C2
                                           allow_churn=allow_churn))
    wg.raise_if_refused(*plans)                                                # ONE raise, nothing written yet
    written = wg.commit_all(*plans)
    total = written.get("commodity", 0)
    print(f"  _raw: {written.get('_raw', 0)} props archived across "
          f"{len(plans[0].records)} nodes -> evidence/_raw/*.jsonl")
    if driver_sink:
        print(f"  drivers: {written.get('drivers', 0)} props across {len(driver_sink)} slices "
              f"-> evidence/drivers/*.jsonl")
    if tally is not None:
        _flush_dark_tally(tally)
    return total


def retrieve(s3, client, bid: str, *, backend: str | None = None, poll_s: int = 20, drivers: bool = True,
             tally: bool = False, manifest=None, allow_churn: float | None = None,
             rechunk: bool = False, retry_lost: bool = True) -> int:
    """Poll the batch, parse every prop (with event_date + W2.1 char offsets + chunk_version), write the
    doc-keyed chunk cache (chunks/<doc>), then route via _route_and_write (_raw archive + commodity + driver
    slices). Pure-driver props are KEPT. With a cache-aware `sampling` manifest, each node's props are gathered
    from the doc-cache (newly chunked + already cached) — so a re-build only paid Haiku for new docs. The offset
    fields ride the `base` dict, so they propagate into the cache AND every slice via **base for free. `tally`
    (opt-in) runs the W1.2 dark-at-birth classification over the routed props.

    Every window now lands in a NAMED state (BatchTally) and the two loss classes get ONE retry each
    (`retry_lost=False` turns that off, and the states are still counted): a truncated window is re-submitted
    as two halves, an unparseable one as itself. The per-node gather (`_gather_by_node`) resolves each
    sampled key through the alias map first, so a document the dedup gate aliased still delivers its twin's
    props to that node -- and a key that resolves to an EMPTY doc cache is counted and printed rather than
    disappearing into a downstream `SKIPPED (empty)`."""
    payload = _load_manifest_full(bid)
    # NB `blocks` is the BATCH block manifest (custom_id -> block meta); `manifest` is the G1c RunManifest
    # kwarg. Two different manifests, deliberately disambiguated after the names collided.
    blocks, sampling, doclist = payload["manifest"], payload.get("sampling"), payload.get("doclist", False)
    while client.messages.batches.retrieve(bid).processing_status != "ended":
        print(f"  batch {bid}: still processing ...")
        time.sleep(poll_s)
    cv = _chunk_version()                                            # one vintage stamp for the whole pass
    props_by_doc: dict[str, list[dict]] = {}                          # source_key -> props (for the doc cache)
    by_node: dict[str, list[dict]] = {}                              # contract -> props (old-manifest path)
    wt = BatchTally(windows_submitted=len(blocks))
    order: list[str] = []                                            # custom_ids in result order (a stable cache write)
    parsed: dict[str, list] = {}                                     # custom_id -> [(block meta, items), ...]
    lost: dict[str, str] = {}                                        # custom_id -> the loss class to retry
    for r in client.messages.batches.results(bid):
        if r.custom_id not in blocks:
            continue
        order.append(r.custom_id)
        state, items = _classify_result(r)
        wt.note(state)
        if state == "ok":
            parsed[r.custom_id] = [(blocks[r.custom_id], items)]
        elif state in ("truncated", "unparseable"):
            lost[r.custom_id] = state
            wt.note_lost(r.custom_id, state)
    if lost and retry_lost:
        try:
            parsed.update(_retry_lost_windows(client, blocks, lost, tally=wt, poll_s=poll_s))
        except Exception as exc:                                     # noqa: BLE001
            # DEGRADE, do not crash. The first batch is already BILLED and `parsed` already holds every
            # window that returned cleanly; letting an API error on the recovery leg throw would discard
            # all of them and leave the pass with nothing to show for the spend. The windows stay counted
            # as lost, and the failure is named in the summary rather than swallowed.
            print(f"  WARNING window retry FAILED ({str(exc).encode('ascii', 'backslashreplace').decode()[:200]})"
                  f" -- {len(lost)} lost window(s) stay lost; the {len(parsed)} that parsed are unaffected")
            wt.retries["retry_batch_failed"] = 1
    for cid in order:
        i = 0                                                        # prop index runs ACROSS a retried window's
        for m, items in parsed.get(cid, ()):                         # two halves: `{cid}#{i}` stays unique
            block_text, block_start, block_end = m.get("block_text"), m.get("block_start"), m.get("block_end")
            cursor = 0                                               # per-block find cursor (props arrive in block order)
            for item in items:
                idx, i = i, i + 1                                     # advances on EVERY item, empty ones
                prop = (item.get("proposition") or "").strip()        # included: the old enumerate() numbering
                if not prop:                                          # is preserved for an un-retried window
                    continue
                ev_dt, ev_prec = ch._parse_event_date(item.get("event_date"), item.get("event_date_precision"))
                span = (item.get("verbatim_span") or "").strip()     # prefer the verbatim span for an EXACT hit
                cstart, cend, okind, cursor = _locate_span(span or prop, block_text, block_start, block_end, cursor)
                base = {"date": m["date"], "source": m["source"], "source_key": m["source_key"], "text": prop,
                        "event_date": str(ev_dt) if ev_dt else None, "event_date_precision": ev_prec,
                        "char_start": cstart, "char_end": cend, "offset_kind": okind, "chunk_version": cv,
                        "date_kind": m.get("date_kind"), "date_layout": m.get("date_layout")}
                rid = f"{cid}#{idx}"
                props_by_doc.setdefault(m["source_key"], []).append({"id": rid, **base})
                by_node.setdefault(m["contract"], []).append({"id": rid, "contract": m["contract"], **base})
                wt.props_emitted += 1
    wt.report()
    ncache = _write_doc_cache(props_by_doc, chunk_version=cv, allow_rechunk=rechunk,   # G1a
                              manifest=manifest)                     # doc-keyed cache: chunk once, reuse forever
    print(f"  doc cache: {ncache} props over {len(props_by_doc)} docs -> chunks/")
    if doclist:                                                      # a targeted fill: only grow the cache; route later
        if manifest is not None:
            manifest.record_extraction({"windows": wt.summary()})
        print(f"  doc-list fill cached -- run --rebuild-slices to route these {len(props_by_doc)} docs into slices")
        return ncache
    if sampling:                                                     # cache-aware: gather cached+new per node
        aliases = load_alias_map()                                   # a deduped doc still routes, via its twin
        by_node = _gather_by_node(sampling, aliases, tally=wt)       # ... and an EMPTY resolution is counted
        wt.report_gather()
    if manifest is not None:                                         # recorded AFTER the gather: its two
        manifest.record_extraction({"windows": wt.summary()})        # counters ride the same run manifest
    dt = DarkTally(label="retrieve") if tally else None
    return _route_and_write(by_node, backend=backend, drivers=drivers, tally=dt, manifest=manifest,
                            allow_churn=allow_churn)


def reroute(*, nodes=None, backend: str | None = None, drivers: bool = True, tally: bool = False,
            manifest=None, allow_churn: float | None = None) -> int:
    """Re-derive commodity + driver slices from the persisted _raw archive — NO re-chunk, NO Anthropic call.
    Run after expanding driver_slices.yaml (or commodity terms) to capture newly-defined nodes for free.
    `tally` (opt-in) runs the W1.2 dark-at-birth classification over the rerouted props."""
    nodes = nodes or ev.all_nodes()
    by_node = {n: recs for n in nodes if (recs := ev.load_index(f"_raw/{n}"))}
    if not by_node:
        raise SystemExit("no _raw/ archive found — run --retrieve first (it writes the _raw archive).")
    dt = DarkTally(label="reroute") if tally else None
    return _route_and_write(by_node, backend=backend, drivers=drivers, tally=dt, manifest=manifest,
                            allow_churn=allow_churn)


def rebuild_slices(*, backend: str | None = None, drivers: bool = True, tally: bool = False,
                   manifest=None, allow_churn: float | None = None, dry_run: bool = False) -> int:
    """Re-derive ALL slices from the whole chunks/ doc-cache (WS-MS7) — the doc-cache is the master. Routes each
    prop to EVERY matching commodity slice (all 24 matchers) AND, independently over the WHOLE cache, to its
    driver slices — so multi-commodity docs (a WASDE) land in each commodity and pure-driver props (B40/freight)
    are NOT lost to the commodity filter. Deliberately does NOT touch the _raw archive: the cache is a superset of
    it, and _raw is keyed per contract (pure-driver props live under a doc's contract there). Free: no Anthropic.
    `tally` (opt-in) runs the W1.2 dark-at-birth classification GLOBALLY (commodity_hit = ANY matcher fires) --
    the `neither` bucket here is the genuinely dark-at-birth queue. The chunks/ cache holds no full_text, so the
    60k-truncation count is 0 on a pure rebuild (it is measured at chunk time; see _build_requests_from_docs).

    G3a -- `dry_run` ROUTES AND CLASSIFIES BUT WRITES NOTHING. This is the code change the wave plan asks for
    ahead of ever arming --dark-tally, and it exists because the flag was mis-classified as read-only. Its
    own help text says it "applies to --retrieve/--reroute/--rebuild-slices"; there is no standalone read
    mode; and `_flush_dark_tally` runs AFTER the writes, so arming it on a rebuild means re-embedding ~107K
    vectors, clobbering all 24 commodity slices and re-rolling all 125 -- which, with PYTHONHASHSEED unset
    (5,809 of 16,000 capped-slice rows swapped at the last pass), is a POPULATION CHANGE and therefore inside
    the sequencing law that says such changes stale timeline/episodes.json and ride ONE bundle. The booleans
    the tally needs are already computed before any write (:426-427); only the flush coupled it to a pass.
    With `dry_run` the baseline manifest -- and there has never been one, `eval/dark_tally*` returns zero
    objects -- can be established for free. Nothing to compare it against: the first armed run ESTABLISHES
    the baseline, it does not check one."""
    backend = backend or ev.DEFAULT_BACKEND
    nodes = ev.all_nodes()
    matchers = {n: hv.build_matcher(ev.match_forms(n)) for n in nodes}
    by_node: dict[str, list[dict]] = {n: [] for n in nodes}
    driver_sink: dict[str, list[dict]] | None = {} if drivers else None
    dt = DarkTally(label="rebuild") if tally else None
    ndocs = 0
    for h in _cached_hashes():
        recs = ev.load_index(f"chunks/{h}")
        if recs:
            ndocs += 1
        for p in recs:
            comm_hit = False
            for n in nodes:                                        # every matching commodity slice (multi-label)
                if matchers[n].search(p["text"]):
                    by_node[n].append({**p, "contract": n})
                    comm_hit = True
            drv_slices = ev.driver_slices_for(p["text"]) if driver_sink is not None else []
            if driver_sink is not None:                            # driver slices over the WHOLE cache, commodity-independent
                for dn in drv_slices:
                    driver_sink.setdefault(dn, []).append({**p, "driver": dn})
            if dt is not None:
                dt.add(p.get("source_key"), p["text"], commodity_hit=comm_hit, driver_hit=bool(drv_slices))
    if not ndocs:
        raise SystemExit("chunks/ doc-cache is empty — run a --retrieve first.")
    print(f"rebuild-slices: routing props from {ndocs} cached docs into commodity + driver slices")
    if dry_run:                                                    # G3a: route + classify, write NOTHING
        total = sum(len(recs) for recs in by_node.values())
        # F14 -- the banner used to say "NOTHING WRITTEN" while _flush_dark_tally put an object on the LIVE
        # prefix. No SLICE moves and nothing is embedded, which is the property that matters for the
        # sequencing law, but "nothing written" was not literally true and the one artifact it does write
        # goes unnamed. Both are stated now.
        print(f"DRY-RUN rebuild-slices: routed {total} commodity props across "
              f"{sum(1 for r in by_node.values() if r)} nodes and "
              f"{sum(len(v) for v in (driver_sink or {}).values())} props across "
              f"{len(driver_sink or {})} driver slices. NO SLICE WRITTEN, NOTHING EMBEDDED, no _raw and no "
              f"doc-cache object touched -- no population change, so this pass is outside the sequencing "
              f"law." + (" The ONE object it writes is the tally manifest named below "
                         "(configs/graphrag/eval/ + <EVIDENCE_S3>/eval/dark_tally_rebuild_*.json)."
                         if dt is not None else ""))
        if dt is not None:
            _flush_dark_tally(dt)
        return total
    for n, recs in by_node.items():
        if recs:
            print(f"  {n}: {len(recs)} props -> evidence/{n}.jsonl")
    # F1 -- plan BOTH layers, union the refusals, raise once, then commit. Before this, the 24 commodity
    # slices (11,119,127,224 B, larger than the whole drivers/ layer) were fully rewritten before the driver
    # guard was ever consulted, so a driver-layer refusal was a refusal of nothing.
    from leviathan.graphrag import write_guard as wg
    plans = [_plan_commodity_write(by_node, backend=backend, manifest=manifest,    # G1d (empty nodes skipped)
                                   allow_churn=allow_churn)]
    if driver_sink:
        plans.append(ev.plan_driver_slices(driver_sink, backend=backend, manifest=manifest,
                                           allow_churn=allow_churn))
    wg.raise_if_refused(*plans)
    written = wg.commit_all(*plans)
    total = written.get("commodity", 0)
    if driver_sink:
        print(f"  drivers: {written.get('drivers', 0)} props across {len(driver_sink)} slices "
              f"-> evidence/drivers/*.jsonl")
    if dt is not None:
        _flush_dark_tally(dt)
    return total


# ── targeted doc-list fills (WS-MS7): chunk a specific set of docs, cache-aware ────────────
_YEAR_RE = __import__("re").compile(
    r"(?:release_date|release_month|publication_date|year|crop_year|release)=(\d{4})")   # `release=` = wb_cmo (S6)


def _key_year(key: str):
    d = ev._pub_date(key)                                   # publication_date=YYYYMMDD / MM-DD-YYYY in the key
    if d:
        return d.year
    m = _YEAR_RE.search(key)
    return int(m.group(1)) if m else None


def select_docs(sources, *, before_year=None, after_year=None, exclude_cached: bool = True) -> list[str]:
    """Corpus doc keys for the given sources filtered by era, minus docs already in chunks/ — the selector for
    a fill (e.g. all pre-2000 usda_wasde/usda_wap not yet chunked)."""
    from leviathan.graphrag.corpus_recon import BUCKET
    from leviathan.storage.s3 import list_s3_keys
    cached = _cached_hashes() if exclude_cached else set()
    out = []
    for src in sources:
        for key in list_s3_keys(BUCKET, f"text/source={src}/", suffix="document.json"):
            y = _key_year(key)
            if y is None or (before_year and y >= before_year) or (after_year and y < after_year):
                continue
            if exclude_cached and _doc_cache_node(key).split("/")[-1] in cached:
                continue
            out.append(key)
    return out


def _build_novelty_gate(*, threshold: float = nv.DEFAULT_THRESHOLD) -> "nv.NoveltyGate":
    """Seed a NoveltyGate from the chunks/ cache ONCE (list chunks/ once, load each cached doc's props once --
    a one-time setup cost analogous to make_uncached_count_fn, NEVER inside the candidate loop; law #6).
    Prop-space signatures only (the cache holds no full_text)."""
    props_by_doc = {h: ev.load_index(f"chunks/{h}") for h in _cached_hashes()}
    props_by_doc = {h: ps for h, ps in props_by_doc.items() if ps}
    return nv.NoveltyGate(nv.corpus_signatures(props_by_doc), threshold=threshold)


def _build_requests_from_docs(s3, doc_keys, *, gate=None, ledger: list | None = None, tally=None,
                              reads: "DocReadTally | None" = None, dedup: "DedupGate | None" = None):
    """Cache-aware batch requests for a specific doc list (no per-node sampling; chunk the WHOLE doc, no matcher
    pre-filter — the fill targets these docs on purpose). The KEY-based skip gate (_cached_hashes) makes re-runs
    safe (prop ids are batch-relative — a re-chunk would re-number them). When a `gate` (W2.3 novelty) is given,
    each candidate body is near-dup-checked and either chunked or skipped-with-a-logged-reason (into `ledger`)
    — an over-cap doc is flagged partial and never auto-skipped on tail novelty. `tally` records cap head-cuts
    and date floors (law #7). The body is read ONCE per candidate on EVERY path now (not only the novelty one),
    because the dedup gate needs sha1(full_text) — still one GET per doc, since `doc=` is handed straight to
    `_doc_blocks`."""
    requests, manifest = [], {}
    cached = _cached_hashes()
    reads = reads if reads is not None else DocReadTally(label="fill")
    dedup = dedup if dedup is not None else DedupGate()
    dedup.adopt_cache(cached)                               # the liveness check reuses THIS listing, no 2nd LIST
    for key in dict.fromkeys(doc_keys):                     # dedupe, preserve order
        if _doc_cache_node(key).split("/")[-1] in cached:   # the idempotency skip gate (correction #2)
            continue
        doc = _read_doc(s3, key, reads=reads)
        if doc is None:                                     # counted, never silent (P0c s9)
            continue
        if gate is not None:                                # novelty pass: body already in hand, one GET
            verdict = gate.check(key, doc.get("full_text") or "")
            if verdict["skip"]:
                if ledger is not None:
                    ledger.append(verdict)
                continue
        if dedup.check(key, doc.get("full_text") or ""):    # a twin: aliased, not billed twice
            continue
        blocks = _doc_blocks(s3, "_docs", key, matcher=None, doc=doc, tally=tally, reads=reads)
        if blocks:
            dedup.claim(key, doc.get("full_text") or "")
        for blk, meta, btext in blocks:
            cid = f"r{len(requests):06d}"
            requests.append({"custom_id": cid, "params": {
                "model": ex.HAIKU, "max_tokens": _MAX_OUTPUT_TOKENS, "temperature": 0, "system": ch._PROP_SYSTEM,
                "messages": [{"role": "user", "content": blk.verbatim_span}]}})
            manifest[cid] = _block_meta(meta, blk, btext)   # + block span for W2.1 offsets
    return requests, manifest


def _flush_novelty_ledger(ledger: list, tally: "DarkTally | None" = None) -> str:
    """Write the W2.3 skip ledger — every skipped candidate {source_key, reason, score, partial_60k_flag} plus
    the 60k-partial count — to configs/graphrag/eval/ + optional EVIDENCE_S3/eval/ (the e0_harness idiom). Law
    #7: no silent skip. Timestamped so a rerun never clobbers the prior ledger."""
    from pathlib import Path
    payload = {"ledger": "novelty_skips", "n_skipped": len(ledger), "skips": ledger,
               "fulltext_cap": _FULLTEXT_CAP,
               "n_docs_truncated_at_cap": len(tally.truncated_docs) if tally else 0,
               "truncated_source_keys": sorted(tally.truncated_docs) if tally else []}
    name = f"novelty_ledger_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    out = ex._CFG / "eval" / name
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    base = ev._evid_s3()
    if base:
        import boto3
        b, k = ev._parse_s3(base.rstrip("/") + f"/eval/{name}")
        boto3.client("s3").put_object(Bucket=b, Key=k, Body=json.dumps(payload).encode("utf-8"))
    print(f"  novelty ledger: {len(ledger)} skips, {payload['n_docs_truncated_at_cap']} "
          f"{_FULLTEXT_CAP}-truncated docs -> {out}")
    return str(out)


def submit_docs(s3, client, doc_keys, *, novelty: bool = False) -> str:
    gate = _build_novelty_gate() if novelty else None
    ledger: list | None = [] if novelty else None
    tly = DarkTally(label="novelty_fill") if novelty else None
    reads = DocReadTally(label="fill")
    dedup = DedupGate(store_paths=store_path_index(s3))      # 2 LISTs, 0 GETs -- the 162 straddlers
    requests, manifest = _build_requests_from_docs(s3, doc_keys, gate=gate, ledger=ledger, tally=tly,
                                                   reads=reads, dedup=dedup)
    if novelty:
        _flush_novelty_ledger(ledger, tly)
    reads.report()
    reads.raise_if_over()                                   # fail-closed BEFORE the batch exists: bills nothing
    dedup.report()
    if not requests:
        raise SystemExit("all requested docs already in the chunk cache — run --rebuild-slices (no new chunking).")
    bid = client.messages.batches.create(requests=requests).id
    dedup.flush()                                           # the aliases become real once the twins are billed
    _save_manifest(bid, {"batch_id": bid, "manifest": manifest, "doclist": True})
    ndocs = len({m["source_key"] for m in manifest.values()})
    print(f"submitted doc-list batch {bid} ({len(requests)} blocks over {ndocs} NEW docs)")
    print(f"retrieve with:  python -m leviathan.graphrag.evidence_batch --retrieve {bid}   (then --rebuild-slices)")
    return bid


def measure_orphan_drivers(s3, sources, *, n: int = 60, seed: int = 0) -> dict:
    """Gap-2 sizing (free): of `sources` docs, how many mention a DRIVER term but NO commodity (pure-macro
    chapters the commodity sampler never captures)?"""
    import random

    from leviathan.graphrag.corpus_recon import BUCKET
    from leviathan.storage.s3 import list_s3_keys
    node_matcher = hv.build_matcher(sum((ev.match_forms(x) for x in ev.all_nodes()), []))
    total, orphan, examples = 0, 0, []
    for src in sources:
        keys = list(list_s3_keys(BUCKET, f"text/source={src}/", suffix="document.json"))
        random.Random(seed).shuffle(keys)
        for key in keys[:n]:
            try:
                txt = json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()).get("full_text") or ""
            except Exception:
                continue
            total += 1
            if txt and not node_matcher.search(txt) and ev.driver_slices_for(txt):
                orphan += 1
                if len(examples) < 5:
                    examples.append(key)
    return {"sampled": total, "orphan_driver_docs": orphan, "examples": examples}


def run(s3, client, *, nodes, n_docs, seed: int = 0, manifest=None, allow_churn: float | None = None,
        rechunk: bool = False, retry_lost: bool = True) -> int:
    return retrieve(s3, client, submit(s3, client, nodes=nodes, n_docs=n_docs, seed=seed, manifest=manifest),
                    manifest=manifest, allow_churn=allow_churn, rechunk=rechunk, retry_lost=retry_lost)


def main() -> int:
    ap = argparse.ArgumentParser(description="Batch-API evidence chunking (gated: Haiku batch billed).")
    ap.add_argument("--submit", action="store_true")
    ap.add_argument("--retrieve", metavar="BID")
    ap.add_argument("--reroute", action="store_true",
                    help="re-derive slices from the persisted _raw archive (free; after expanding driver_slices.yaml)")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--nodes", default="all")
    ap.add_argument("--n-docs", type=int, default=40)
    ap.add_argument("--rebuild-slices", action="store_true",
                    help="re-derive ALL slices from the whole chunks/ doc-cache (free; after a fill)")
    ap.add_argument("--fill", action="store_true",
                    help="chunk a targeted doc-list fill selected by --sources/--before/--after (cache-aware; billed)")
    ap.add_argument("--measure-orphan-drivers", action="store_true",
                    help="free Gap-2 sizing: docs matching a driver term but NO commodity (needs --sources)")
    ap.add_argument("--sources", default="", help="comma-separated source names for --fill / --measure-orphan-drivers")
    ap.add_argument("--before", type=int, default=None, help="fill: keep only docs with year < N")
    ap.add_argument("--after", type=int, default=None, help="fill: keep only docs with year >= N")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dark-tally", action="store_true",
                    help="W1.2: classify every routed prop into {both,commodity_only,driver_only,neither} + write "
                         "a manifest (opt-in; applies to --retrieve/--reroute/--rebuild-slices)")
    ap.add_argument("--novelty", action="store_true",
                    help="W2.3: near-dup gate on a --fill (skip docs already covered; every skip logged)")
    ap.add_argument("--dark-tally-dry-run", action="store_true",
                    help="G3a: route the whole chunks/ cache and write the dark-tally manifest WITHOUT "
                         "writing a single slice (no embed, no population change). This is how the tally "
                         "baseline gets established without riding a routing pass -- arming --dark-tally on "
                         "a real --rebuild-slices is a population change and rides the artifact bundle.")
    ap.add_argument("--allow-churn", type=float, default=None, metavar="PCT",
                    help="G1b escape hatch: permit a per-slice population DROP up to PCT percent (e.g. "
                         "--allow-churn 25). REQUIRES a magnitude on purpose -- 'I expect churn' is not a "
                         "claim anyone can be wrong about, 'I expect up to 25%%' is. Without it any drop at "
                         "or over 10%% REFUSES the pass with nothing written.")
    ap.add_argument("--no-retry-lost", dest="retry_lost", action="store_false", default=True,
                    help="X2: do NOT re-submit the windows this batch lost (truncated at max_tokens, or "
                         "unparseable). The per-window tally still counts and REPORTS them -- the pilot "
                         "measured 20.8%% of windows billed and silently producing nothing -- but the ~12.5%% "
                         "truncated class is not re-run at a halved window and stays lost.")
    ap.add_argument("--rechunk", action="store_true",
                    help="G1a escape hatch: permit overwriting cached chunks/<doc>.jsonl objects whose props "
                         "carry a DIFFERENT chunk_version than this pass (a re-chunk). Copy the chunks/ "
                         "prefix first -- this is not reversible and bucket versioning is Suspended.")
    ap.add_argument("--run-manifest", action="store_true", default=True,
                    help="G1c: emit the per-pass write manifest to configs/graphrag/eval/ and "
                         "<EVIDENCE_S3>/eval/ (default ON; --no-run-manifest to suppress)")
    ap.add_argument("--no-run-manifest", dest="run_manifest", action="store_false")
    ap.add_argument("--seed-manifest", metavar="LAYERS", nargs="?", const="drivers", default=None,
                    help="F4/G1b leg 2 BOOTSTRAP, READ-ONLY: stream the slices already in the store and "
                         "emit the write_manifest_seed_*.json the span guard needs as its baseline. Without "
                         "it, resolve_prior has no exact prior and no prior SPAN on the first guarded pass "
                         "-- which is the Wave-R rebuild -- so the endpoint leg (potash -25y, "
                         "mississippi_river_levels -3y) cannot fire on the one pass the wave is built "
                         "around. Comma-separated layers from {drivers,commodity,_raw} or 'all'; default "
                         "'drivers' (~1.361 GB; commodity adds ~11.1 GB). Writes NO slice -- the only "
                         "object it creates is its own manifest under eval/. Idempotent: rerun it and the "
                         "same store yields the same numbers.")
    args = ap.parse_args()
    if args.allow_churn is not None and float(args.allow_churn) <= 0:
        # F15 -- `--allow-churn 0` used to leave the drop line armed while silently downgrading EVERY span
        # contraction to a warn: the opposite of what the caller meant, with no message saying so. The
        # verdict now gates both legs on a nonzero magnitude, and the flag itself refuses the value rather
        # than quietly meaning "no declaration".
        ap.error("--allow-churn 0 declares no churn at all -- OMIT the flag instead. The flag exists to "
                 "name a drop you EXPECT (e.g. --allow-churn 25); zero is not such a claim, and passing it "
                 "used to disarm the span-contraction guard silently.")
    allow_churn = None if args.allow_churn is None else max(0.0, float(args.allow_churn)) / 100.0
    if args.nodes == "all":
        nodes = ev.all_nodes()
    elif args.nodes == "new":
        nodes = ev.new_nodes()
    else:
        nodes = list(dict.fromkeys(ev.node_for(n) for n in args.nodes.split(",")))   # contract ids -> nodes, deduped
    import boto3

    from leviathan.common import config
    config.load_env()
    s3 = boto3.client("s3")
    srcs = [s for s in args.sources.split(",") if s]

    from leviathan.graphrag import write_guard as wg

    def _manifest(label: str):                                         # G1c: one manifest per write pass
        if not args.run_manifest:
            return None
        return wg.RunManifest(label, chunk_version=_chunk_version(), allow_churn=allow_churn)

    def _guarded(label: str, fn):
        """Run a write pass under its manifest; a guard refusal is a clean nonzero exit, not a traceback."""
        mf = _manifest(label)
        try:
            fn(mf)
        except wg.WriteRefused as exc:
            print("REFUSED: the write guard stopped this pass before anything was written.")
            for line in exc.lines:
                print(f"  - {line}")
            if mf is not None:
                mf.warnings.append("REFUSED: " + " | ".join(exc.lines))
                mf.flush()
            return 2
        if mf is not None:
            mf.flush()
        return 0

    # ── free modes (no Anthropic call) ────────────────────────────────────────────
    if args.seed_manifest:                                             # F4: READ-ONLY baseline bootstrap
        layers = (tuple(wg.SEED_LAYERS) if str(args.seed_manifest).strip().lower() == "all"
                  else tuple(x.strip() for x in str(args.seed_manifest).split(",") if x.strip()))
        unknown = [x for x in layers if x not in wg.SEED_LAYERS]
        if unknown:
            print(f"--seed-manifest: unknown layer(s) {unknown}; known: {sorted(wg.SEED_LAYERS)}")
            return 2
        print(f"seed-manifest: streaming layer(s) {list(layers)} READ-ONLY to establish the span-guard "
              f"baseline. No slice is written; the only object created is the manifest below.")
        print(f"  seed-manifest -> {wg.seed_manifest(layers)}")
        return 0
    if args.dark_tally_dry_run:                                        # G3a: routing DRY-RUN, zero writes
        rebuild_slices(tally=True, dry_run=True)
        return 0
    if args.rebuild_slices:                                            # route the whole chunks/ cache -> slices
        return _guarded("rebuild", lambda mf: rebuild_slices(tally=args.dark_tally, manifest=mf,
                                                             allow_churn=allow_churn))
    if args.reroute:                                                   # re-derive from the _raw archive
        print(f"reroute {len(nodes)} node(s) from _raw archive -> commodity + driver slices")
        return _guarded("reroute", lambda mf: reroute(nodes=nodes, tally=args.dark_tally, manifest=mf,
                                                      allow_churn=allow_churn))
    if args.measure_orphan_drivers:                                    # Gap-2 sizing
        print("orphan-driver measurement:", measure_orphan_drivers(s3, srcs))
        return 0
    if args.fill:                                                      # select a doc-list; --dry-run sizes blocks + cost
        keys = select_docs(srcs, before_year=args.before, after_year=args.after)
        print(f"FILL selection: {len(keys)} uncached docs from {srcs} (before={args.before}, after={args.after})")
        if not keys:
            return 0
        if args.dry_run:                                               # chunk locally (free) to size the real block count
            gate = _build_novelty_gate() if args.novelty else None
            ledger: list | None = [] if args.novelty else None
            tly = DarkTally(label="novelty_fill") if args.novelty else None
            reads = DocReadTally(label="fill_dry_run")
            dedup = DedupGate(store_paths=store_path_index(s3))         # size what the real fill would skip
            reqs, manifest = _build_requests_from_docs(s3, keys, gate=gate, ledger=ledger, tally=tly,
                                                       reads=reads, dedup=dedup)
            if args.novelty:
                _flush_novelty_ledger(ledger, tly)
            reads.report()                                             # sizing a fill also sizes its read losses
            dedup.report()                                             # ... and the twins it would have paid for
            ndocs = len({m["source_key"] for m in manifest.values()})
            lo, hi = len(reqs) * 0.002, len(reqs) * 0.007              # naive vs empirical (output tokens dominate; $70 lesson)
            print(f"FILL dry-run: {len(reqs)} blocks over {ndocs} NEW docs; Haiku batch est ~${lo:.0f}-{hi:.0f}")
            return 0
        import anthropic

        from leviathan.graphrag import batch_extract as bx
        submit_docs(s3, anthropic.Anthropic(api_key=bx._api_key()), keys, novelty=args.novelty)
        return 0
    if args.dry_run:                                                   # node-sampling dry-run (cost estimate)
        reads = DocReadTally(label="dry_run")
        dedup = DedupGate(store_paths=store_path_index(s3))             # size what the real submit would skip
        reqs, manifest, _sampling = _build_requests(s3, nodes, args.n_docs, 0, reads=reads, dedup=dedup)
        reads.report()
        dedup.report()                                                  # the estimate must not price the twins
        per = collections.Counter(manifest[r["custom_id"]]["contract"] for r in reqs)
        # x2_cost.json / x2_cost_check: the OUTPUT constant was 500 tok/request and is MEASURED at ~1,537 --
        # 19.44 props/request (258,300 projected props over 13,289 requests) x 79.1 output tokens/prop, the
        # latter from `count_tokens` over reconstructed real output JSON. At 500 this estimator was a ~3.4x
        # UNDERestimate ($27 against the corrected $61.71 on the X2 work set) and it sat directly under the
        # "$70 lesson" comment on the fill band below. Input stays at 1,500 (measured 1,600, within band).
        usd = len(reqs) * (1500 * 0.5 / 1e6 + 1537 * 2.5 / 1e6)            # Haiku batch ~$0.50/$2.50 per M
        print(f"DRY-RUN: {len(reqs)} ON-TOPIC block requests over {len(nodes)} node(s); Haiku batch est ~${usd:.2f}")
        for n in nodes:
            print(f"  {n}: {per.get(n, 0)} blocks" + ("   <-- THIN" if per.get(n, 0) < 30 else ""))
        return 0
    # ── billed node paths ─────────────────────────────────────────────────────────
    import anthropic

    from leviathan.graphrag import batch_extract as bx
    client = anthropic.Anthropic(api_key=bx._api_key())
    if args.retrieve:
        return _guarded("retrieve", lambda mf: retrieve(s3, client, args.retrieve, tally=args.dark_tally,
                                                        manifest=mf, allow_churn=allow_churn,
                                                        rechunk=args.rechunk, retry_lost=args.retry_lost))
    elif args.submit:
        submit(s3, client, nodes=nodes, n_docs=args.n_docs)
    elif args.run:
        return _guarded("run", lambda mf: run(s3, client, nodes=nodes, n_docs=args.n_docs, manifest=mf,
                                              allow_churn=allow_churn, rechunk=args.rechunk,
                                              retry_lost=args.retry_lost))
    else:
        print("specify --dry-run / --submit / --retrieve <bid> / --run / --fill / --rebuild-slices")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
