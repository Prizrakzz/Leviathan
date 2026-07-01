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

_OUT = ex._CFG / "evidence" / "_batches"
_MAX_BLOCK_CHARS = 5000


def _doc_blocks(s3, node: str, key: str, matcher=None) -> list:
    """Deterministic blocks for one doc + its shared metadata (free; no LLM). When a matcher is given, skip
    a doc that doesn't mention the commodity BEFORE chunking — so we don't pay Haiku to chunk off-topic docs
    (the inline build_index already does this; the batch path used to chunk everything then filter props)."""
    from leviathan.graphrag.corpus_recon import BUCKET, _source_of
    try:
        doc = json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())
    except Exception:                                          # skip a malformed/unreadable doc (don't crash the run)
        return []
    full = (doc.get("full_text") or "")[:60000]
    if not full.strip() or (matcher is not None and not matcher.search(full)):
        return []
    blocks = ch.chunk_document(full_text=full, source_key=key, source=_source_of(key),
                               document_date=ev._doc_date(doc, key), lang=doc.get("lang", "en"),
                               extraction_method=doc.get("extraction_method"), doc_id=key, target_chars=_MAX_BLOCK_CHARS)
    meta = {"contract": node, "source_key": key, "source": _source_of(key), "date": str(ev._doc_date(doc, key))}
    return [(blk, meta) for blk in blocks]


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


def _write_doc_cache(props_by_doc: dict) -> int:
    """Write chunks/<hash>.jsonl once per doc, deduping props by text (collapses a doc chunked under several
    nodes). Doc-keyed + unembedded — a future build reuses these instead of re-paying Haiku."""
    n = 0
    for source_key, props in props_by_doc.items():
        seen, uniq = set(), []
        for p in props:
            if p["text"] in seen:
                continue
            seen.add(p["text"]); uniq.append(p)
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
                manifest[cid] = meta
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


def _route_and_write(by_node: dict, *, backend: str | None = None, drivers: bool = True) -> int:
    """Write the _raw/<node> archive (EVERY prop, unembedded) + route to commodity & driver slices (embed the
    routed). Shared by retrieve (props from the batch) and reroute (props from the persisted _raw archive). The
    archive is the future-proofing: re-deriving slices after the driver YAML grows NEVER re-chunks — chunk once,
    route forever. Pure-driver props (B40/freight/FX/El Nino/metals) are routed to driver slices, not dropped."""
    backend = backend or ev.DEFAULT_BACKEND
    driver_sink: dict[str, list[dict]] | None = {} if drivers else None
    total = 0
    for node, recs in by_node.items():
        raw = [{k: v for k, v in r.items() if k != "vector"} for r in recs]    # archive: text+date+source+event_date, no vector
        ev._evid_write(f"_raw/{node}", "\n".join(json.dumps(r) for r in raw))
        if driver_sink is not None:                                            # multi-label, independent of the commodity filter
            for r in raw:
                for dn in ev.driver_slices_for(r["text"]):
                    driver_sink.setdefault(dn, []).append({**r, "driver": dn})
        matcher = hv.build_matcher(ev.match_forms(node))
        kept = [dict(r) for r in raw if matcher.search(r["text"])]             # commodity slice: on-topic props
        for r, v in zip(kept, ev.embed([r["text"] for r in kept], backend=backend)):
            r["vector"], r["backend"] = v, backend
        ev._evid_write(node, "\n".join(json.dumps(r) for r in kept))
        print(f"  {node}: {len(kept)} props -> evidence/{node}.jsonl  ({len(raw)} archived to _raw/)")
        total += len(kept)
    if driver_sink:
        dtotal = ev.write_driver_slices(driver_sink, backend=backend)
        print(f"  drivers: {dtotal} props across {len(driver_sink)} slices -> evidence/drivers/*.jsonl")
    return total


def retrieve(s3, client, bid: str, *, backend: str | None = None, poll_s: int = 20, drivers: bool = True) -> int:
    """Poll the batch, parse every prop (with event_date), write the doc-keyed chunk cache (chunks/<doc>), then
    route via _route_and_write (_raw archive + commodity + driver slices). Pure-driver props are KEPT. With a
    cache-aware `sampling` manifest, each node's props are gathered from the doc-cache (newly chunked + already
    cached) — so a re-build only paid Haiku for new docs."""
    payload = _load_manifest_full(bid)
    manifest, sampling = payload["manifest"], payload.get("sampling")
    while client.messages.batches.retrieve(bid).processing_status != "ended":
        print(f"  batch {bid}: still processing ...")
        time.sleep(poll_s)
    props_by_doc: dict[str, list[dict]] = {}                          # source_key -> props (for the doc cache)
    by_node: dict[str, list[dict]] = {}                              # contract -> props (old-manifest path)
    for r in client.messages.batches.results(bid):
        if getattr(r.result, "type", None) != "succeeded" or r.custom_id not in manifest:
            continue
        m = manifest[r.custom_id]
        for i, item in enumerate(ch._parse_json_array(_text_of(r))):
            prop = (item.get("proposition") or "").strip()
            if not prop:
                continue
            ev_dt, ev_prec = ch._parse_event_date(item.get("event_date"), item.get("event_date_precision"))
            base = {"date": m["date"], "source": m["source"], "source_key": m["source_key"], "text": prop,
                    "event_date": str(ev_dt) if ev_dt else None, "event_date_precision": ev_prec}
            rid = f"{r.custom_id}#{i}"
            props_by_doc.setdefault(m["source_key"], []).append({"id": rid, **base})
            by_node.setdefault(m["contract"], []).append({"id": rid, "contract": m["contract"], **base})
    ncache = _write_doc_cache(props_by_doc)                           # doc-keyed cache: chunk once, reuse forever
    print(f"  doc cache: {ncache} props over {len(props_by_doc)} docs -> chunks/")
    if sampling:                                                     # cache-aware: gather cached+new per node
        by_node = {node: [{**p, "contract": node} for key in docs for p in _read_doc_cache(key)]
                   for node, docs in sampling.items()}
    return _route_and_write(by_node, backend=backend, drivers=drivers)


def reroute(*, nodes=None, backend: str | None = None, drivers: bool = True) -> int:
    """Re-derive commodity + driver slices from the persisted _raw archive — NO re-chunk, NO Anthropic call.
    Run after expanding driver_slices.yaml (or commodity terms) to capture newly-defined nodes for free."""
    nodes = nodes or ev.all_nodes()
    by_node = {n: recs for n in nodes if (recs := ev.load_index(f"_raw/{n}"))}
    if not by_node:
        raise SystemExit("no _raw/ archive found — run --retrieve first (it writes the _raw archive).")
    return _route_and_write(by_node, backend=backend, drivers=drivers)


def run(s3, client, *, nodes, n_docs, seed: int = 0) -> int:
    return retrieve(s3, client, submit(s3, client, nodes=nodes, n_docs=n_docs, seed=seed))


def main() -> int:
    ap = argparse.ArgumentParser(description="Batch-API evidence chunking (gated: Haiku batch billed).")
    ap.add_argument("--submit", action="store_true")
    ap.add_argument("--retrieve", metavar="BID")
    ap.add_argument("--reroute", action="store_true",
                    help="re-derive slices from the persisted _raw archive (free; after expanding driver_slices.yaml)")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--nodes", default="all")
    ap.add_argument("--n-docs", type=int, default=40)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
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
    if args.dry_run:
        import collections
        reqs, manifest, _sampling = _build_requests(s3, nodes, args.n_docs, 0)
        per = collections.Counter(manifest[r["custom_id"]]["contract"] for r in reqs)
        usd = len(reqs) * (1500 * 0.5 / 1e6 + 500 * 2.5 / 1e6)             # Haiku batch ~$0.50/$2.50 per M
        print(f"DRY-RUN: {len(reqs)} ON-TOPIC block requests over {len(nodes)} node(s); Haiku batch est ~${usd:.2f}")
        for n in nodes:
            print(f"  {n}: {per.get(n, 0)} blocks" + ("   <-- THIN" if per.get(n, 0) < 30 else ""))
        return 0
    if args.reroute:                                                   # free: no Anthropic call, re-derive from _raw
        print(f"reroute {len(nodes)} node(s) from _raw archive -> commodity + driver slices")
        reroute(nodes=nodes)
        return 0
    import anthropic
    from leviathan.graphrag import batch_extract as bx
    client = anthropic.Anthropic(api_key=bx._api_key())
    if args.retrieve:
        retrieve(s3, client, args.retrieve)
    elif args.submit:
        submit(s3, client, nodes=nodes, n_docs=args.n_docs)
    elif args.run:
        run(s3, client, nodes=nodes, n_docs=args.n_docs)
    else:
        print("specify --dry-run / --submit / --retrieve <bid> / --run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
