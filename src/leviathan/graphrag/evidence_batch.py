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
import hashlib
import json
import time

from leviathan.graphrag import chunking as ch
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import extract as ex
from leviathan.graphrag import harvest as hv
from leviathan.graphrag import novelty as nv

_OUT = ex._CFG / "evidence" / "_batches"
_MAX_BLOCK_CHARS = 5000
_FULLTEXT_CAP = 60000            # per-doc full_text head-cut before chunking (law #7: this cut is never silent --
#                                  the W1.2 dark-tally carries the count of docs it truncated)


def _chunk_version() -> str | None:
    """Corpus-vintage stamp for props minted THIS pass (W2.2). Agent 1 owns the source of truth
    (`evidence.current_chunk_version`); absent in a pre-P3 tree this degrades to None, and version-absence
    itself marks a pre-P3 prop (correction #3). Read at parse time so a mid-pass config change cannot split a
    single batch's vintage across records."""
    fn = getattr(ev, "current_chunk_version", None)
    return fn() if callable(fn) else None


def _locate_span(needle: str, block_text: str | None, block_start, block_end, cursor: int):
    """Char offsets for a returned prop within its source block (W2.1). Returns
    (char_start, char_end, offset_kind, next_cursor):

      exact -- `needle` (the prop's verbatim_span, else its text) is found in block_text at/after `cursor`;
               offsets are ABSOLUTE doc positions (block_start + local index) and the cursor advances past it,
               so in-order props on one block never re-match an earlier occurrence (the propositional_chunks
               find-with-cursor pattern, chunking.py).
      block -- a rewritten prop that does not appear verbatim, but the block's own span is known: fall back to
               [block_start, block_end] (correction #5 -- propositional rewrites often floor to the block).
      none  -- no block text available at all (e.g. a pre-W2.1 manifest with no block fields): offsets are None.
    """
    if not block_text:
        return None, None, "none", cursor
    bstart = block_start if isinstance(block_start, int) else 0
    bend = block_end if isinstance(block_end, int) else bstart + len(block_text)
    idx = block_text.find(needle, cursor) if needle else -1
    if idx >= 0:
        start = bstart + idx
        return start, start + len(needle), "exact", idx + len(needle)
    return bstart, bend, "block", cursor


def _read_doc(s3, key: str) -> dict | None:
    """ONE S3 GET for a corpus doc (json) -> dict, or None on any read/parse error. Isolated so a caller that
    needs BOTH the novelty-gate full_text and the chunk blocks reads the body ONCE (law #6 -- no double GET
    per doc in the fill loop)."""
    from leviathan.graphrag.corpus_recon import BUCKET
    try:
        return json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())
    except Exception:                                          # skip a malformed/unreadable doc (don't crash the run)
        return None


def _doc_blocks(s3, node: str, key: str, matcher=None, *, doc: dict | None = None, tally=None) -> list:
    """Deterministic blocks for one doc + its shared metadata (free; no LLM). When a matcher is given, skip
    a doc that doesn't mention the commodity BEFORE chunking — so we don't pay Haiku to chunk off-topic docs
    (the inline build_index already does this; the batch path used to chunk everything then filter props).
    `doc` lets the novelty gate hand back the body it already read (one GET). `tally`, when given, records a
    doc whose full_text exceeded _FULLTEXT_CAP as a 60k head-cut (law #7 -- no silent truncation)."""
    from leviathan.graphrag.corpus_recon import _source_of
    if doc is None:
        doc = _read_doc(s3, key)
    if doc is None:
        return []
    raw_full = doc.get("full_text") or ""
    if tally is not None and len(raw_full) > _FULLTEXT_CAP:
        tally.note_truncated(key)
    full = raw_full[:_FULLTEXT_CAP]
    if not full.strip() or (matcher is not None and not matcher.search(full)):
        return []
    blocks = ch.chunk_document(full_text=full, source_key=key, source=_source_of(key),
                               document_date=ev._doc_date(doc, key), lang=doc.get("lang", "en"),
                               extraction_method=doc.get("extraction_method"), doc_id=key, target_chars=_MAX_BLOCK_CHARS)
    meta = {"contract": node, "source_key": key, "source": _source_of(key), "date": str(ev._doc_date(doc, key))}
    return [(blk, meta) for blk in blocks]


def _block_meta(meta: dict, blk) -> dict:
    """Per-block manifest entry: the shared doc meta PLUS the block's text and char span, so retrieve() can
    locate each returned prop's offset within its block (W2.1) at parse time -- the doc body is NOT re-fetched
    on retrieve (law #6), and the block text is the only way to recover an EXACT sub-offset for a verbatim
    prop. Additive: contract/source_key/source/date are untouched, older consumers ignore the new keys."""
    return {**meta, "block_text": blk.verbatim_span,
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


def _build_requests(s3, nodes, n_docs, seed):
    """Cache-aware. Sample docs per node, but Haiku-chunk each unique document only if it isn't ALREADY in
    chunks/ (and only once, not per node). `sampling` records every sampled doc per node so retrieve can gather
    the doc-cache (cached + newly chunked) and route to slices — so a re-build pays only for NEW documents."""
    requests, manifest, sampling = [], {}, {}
    cached = _cached_hashes()
    queued: set = set()
    for node in nodes:
        matcher = hv.build_matcher(ev.match_forms(node))
        keys = list(ev.sample_keys(s3, node=node, year_windows=ev.windows_for(node),
                                   n=ev.n_docs_for(node, n_docs), seed=seed))
        sampling[node] = keys
        for key in keys:
            if _doc_cache_node(key).split("/")[-1] in cached or key in queued:   # reuse cache / already queued
                continue
            blocks = _doc_blocks(s3, node, key, matcher)
            if not blocks:                                                       # off-topic here; another node may chunk it
                continue
            queued.add(key)
            for blk, meta in blocks:
                cid = f"r{len(requests):06d}"                                     # custom_id: ^[A-Za-z0-9_-]{1,64}$
                requests.append({"custom_id": cid, "params": {                   # no tools, no caching (see header)
                    "model": ex.HAIKU, "max_tokens": 4096, "system": ch._PROP_SYSTEM,
                    "messages": [{"role": "user", "content": blk.verbatim_span}]}})
                manifest[cid] = _block_meta(meta, blk)                            # + block span for W2.1 offsets
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


def submit(s3, client, *, nodes, n_docs, seed: int = 0) -> str:
    requests, manifest, sampling = _build_requests(s3, nodes, n_docs, seed)
    if not requests:
        raise SystemExit("all sampled docs are already in the chunk cache (chunks/) — nothing new to chunk; "
                         "re-derive slices for free with --reroute instead of a new batch.")
    bid = client.messages.batches.create(requests=requests).id
    _save_manifest(bid, {"batch_id": bid, "manifest": manifest, "sampling": sampling})
    new_docs = len({m["source_key"] for m in manifest.values()})
    print(f"submitted batch {bid} ({len(requests)} blocks over {new_docs} NEW docs; cached docs skipped)")
    print(f"retrieve with:  python -m leviathan.graphrag.evidence_batch --retrieve {bid}")
    return bid


def _text_of(result) -> str:
    return "".join(b.text for b in result.result.message.content if getattr(b, "type", None) == "text")


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
    rides the same manifest: source_keys whose full_text was 60k head-cut (law #7)."""

    def __init__(self, *, label: str = "dark_tally"):
        self.label = label
        self._seen: dict = {}                            # (source_key, text) -> [commodity_hit, driver_hit]
        self.truncated_docs: set = set()                 # source_keys 60k head-cut at chunk time (law #7)

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
                "n_docs_truncated_60k": len(self.truncated_docs),
                "truncated_source_keys": sorted(self.truncated_docs)}


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
          f"(neither-queue={len(payload['neither_source_keys'])}, 60k-truncated docs={payload['n_docs_truncated_60k']})")
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
    before committing any of them; this is the commodity plan they union."""
    from leviathan.graphrag import write_guard as wg
    records = {n: recs for n, recs in kept_by_node.items() if recs}
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
             rechunk: bool = False) -> int:
    """Poll the batch, parse every prop (with event_date + W2.1 char offsets + chunk_version), write the
    doc-keyed chunk cache (chunks/<doc>), then route via _route_and_write (_raw archive + commodity + driver
    slices). Pure-driver props are KEPT. With a cache-aware `sampling` manifest, each node's props are gathered
    from the doc-cache (newly chunked + already cached) — so a re-build only paid Haiku for new docs. The offset
    fields ride the `base` dict, so they propagate into the cache AND every slice via **base for free. `tally`
    (opt-in) runs the W1.2 dark-at-birth classification over the routed props."""
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
    for r in client.messages.batches.results(bid):
        if getattr(r.result, "type", None) != "succeeded" or r.custom_id not in blocks:
            continue
        m = blocks[r.custom_id]
        block_text, block_start, block_end = m.get("block_text"), m.get("block_start"), m.get("block_end")
        cursor = 0                                                   # per-block find cursor (props arrive in block order)
        for i, item in enumerate(ch._parse_json_array(_text_of(r))):
            prop = (item.get("proposition") or "").strip()
            if not prop:
                continue
            ev_dt, ev_prec = ch._parse_event_date(item.get("event_date"), item.get("event_date_precision"))
            span = (item.get("verbatim_span") or "").strip()        # prefer the verbatim span for an EXACT hit
            cstart, cend, okind, cursor = _locate_span(span or prop, block_text, block_start, block_end, cursor)
            base = {"date": m["date"], "source": m["source"], "source_key": m["source_key"], "text": prop,
                    "event_date": str(ev_dt) if ev_dt else None, "event_date_precision": ev_prec,
                    "char_start": cstart, "char_end": cend, "offset_kind": okind, "chunk_version": cv}
            rid = f"{r.custom_id}#{i}"
            props_by_doc.setdefault(m["source_key"], []).append({"id": rid, **base})
            by_node.setdefault(m["contract"], []).append({"id": rid, "contract": m["contract"], **base})
    ncache = _write_doc_cache(props_by_doc, chunk_version=cv, allow_rechunk=rechunk,   # G1a
                              manifest=manifest)                     # doc-keyed cache: chunk once, reuse forever
    print(f"  doc cache: {ncache} props over {len(props_by_doc)} docs -> chunks/")
    if doclist:                                                      # a targeted fill: only grow the cache; route later
        print(f"  doc-list fill cached -- run --rebuild-slices to route these {len(props_by_doc)} docs into slices")
        return ncache
    if sampling:                                                     # cache-aware: gather cached+new per node
        by_node = {node: [{**p, "contract": node} for key in docs for p in _read_doc_cache(key)]
                   for node, docs in sampling.items()}
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


def _build_requests_from_docs(s3, doc_keys, *, gate=None, ledger: list | None = None, tally=None):
    """Cache-aware batch requests for a specific doc list (no per-node sampling; chunk the WHOLE doc, no matcher
    pre-filter — the fill targets these docs on purpose). The KEY-based skip gate (_cached_hashes) makes re-runs
    safe (prop ids are batch-relative — a re-chunk would re-number them). When a `gate` (W2.3 novelty) is given,
    each candidate body is read ONCE, near-dup-checked, and either chunked or skipped-with-a-logged-reason (into
    `ledger`) — a >60k doc is flagged partial and never auto-skipped on tail novelty. `tally` records 60k
    head-cuts (law #7). gate=None keeps the path byte-identical (no extra reads)."""
    requests, manifest = [], {}
    cached = _cached_hashes()
    for key in dict.fromkeys(doc_keys):                     # dedupe, preserve order
        if _doc_cache_node(key).split("/")[-1] in cached:   # the idempotency skip gate (correction #2)
            continue
        doc = _read_doc(s3, key) if gate is not None else None
        if gate is not None:                                # novelty pass: body already in hand, one GET
            if doc is None:
                continue
            verdict = gate.check(key, doc.get("full_text") or "")
            if verdict["skip"]:
                if ledger is not None:
                    ledger.append(verdict)
                continue
        for blk, meta in _doc_blocks(s3, "_docs", key, matcher=None, doc=doc, tally=tally):
            cid = f"r{len(requests):06d}"
            requests.append({"custom_id": cid, "params": {
                "model": ex.HAIKU, "max_tokens": 4096, "system": ch._PROP_SYSTEM,
                "messages": [{"role": "user", "content": blk.verbatim_span}]}})
            manifest[cid] = _block_meta(meta, blk)          # + block span for W2.1 offsets
    return requests, manifest


def _flush_novelty_ledger(ledger: list, tally: "DarkTally | None" = None) -> str:
    """Write the W2.3 skip ledger — every skipped candidate {source_key, reason, score, partial_60k_flag} plus
    the 60k-partial count — to configs/graphrag/eval/ + optional EVIDENCE_S3/eval/ (the e0_harness idiom). Law
    #7: no silent skip. Timestamped so a rerun never clobbers the prior ledger."""
    from pathlib import Path
    payload = {"ledger": "novelty_skips", "n_skipped": len(ledger), "skips": ledger,
               "n_docs_truncated_60k": len(tally.truncated_docs) if tally else 0,
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
    print(f"  novelty ledger: {len(ledger)} skips, {payload['n_docs_truncated_60k']} 60k-truncated docs -> {out}")
    return str(out)


def submit_docs(s3, client, doc_keys, *, novelty: bool = False) -> str:
    gate = _build_novelty_gate() if novelty else None
    ledger: list | None = [] if novelty else None
    tly = DarkTally(label="novelty_fill") if novelty else None
    requests, manifest = _build_requests_from_docs(s3, doc_keys, gate=gate, ledger=ledger, tally=tly)
    if novelty:
        _flush_novelty_ledger(ledger, tly)
    if not requests:
        raise SystemExit("all requested docs already in the chunk cache — run --rebuild-slices (no new chunking).")
    bid = client.messages.batches.create(requests=requests).id
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
        rechunk: bool = False) -> int:
    return retrieve(s3, client, submit(s3, client, nodes=nodes, n_docs=n_docs, seed=seed),
                    manifest=manifest, allow_churn=allow_churn, rechunk=rechunk)


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
            reqs, manifest = _build_requests_from_docs(s3, keys, gate=gate, ledger=ledger, tally=tly)
            if args.novelty:
                _flush_novelty_ledger(ledger, tly)
            ndocs = len({m["source_key"] for m in manifest.values()})
            lo, hi = len(reqs) * 0.002, len(reqs) * 0.007              # naive vs empirical (output tokens dominate; $70 lesson)
            print(f"FILL dry-run: {len(reqs)} blocks over {ndocs} NEW docs; Haiku batch est ~${lo:.0f}-{hi:.0f}")
            return 0
        import anthropic

        from leviathan.graphrag import batch_extract as bx
        submit_docs(s3, anthropic.Anthropic(api_key=bx._api_key()), keys, novelty=args.novelty)
        return 0
    if args.dry_run:                                                   # node-sampling dry-run (cost estimate)
        import collections
        reqs, manifest, _sampling = _build_requests(s3, nodes, args.n_docs, 0)
        per = collections.Counter(manifest[r["custom_id"]]["contract"] for r in reqs)
        usd = len(reqs) * (1500 * 0.5 / 1e6 + 500 * 2.5 / 1e6)             # Haiku batch ~$0.50/$2.50 per M
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
                                                        rechunk=args.rechunk))
    elif args.submit:
        submit(s3, client, nodes=nodes, n_docs=args.n_docs)
    elif args.run:
        return _guarded("run", lambda mf: run(s3, client, nodes=nodes, n_docs=args.n_docs, manifest=mf,
                                              allow_churn=allow_churn, rechunk=args.rechunk))
    else:
        print("specify --dry-run / --submit / --retrieve <bid> / --run / --fill / --rebuild-slices")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
