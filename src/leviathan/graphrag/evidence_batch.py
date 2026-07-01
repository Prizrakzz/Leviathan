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
    manifest, sampling, doclist = payload["manifest"], payload.get("sampling"), payload.get("doclist", False)
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
    if doclist:                                                      # a targeted fill: only grow the cache; route later
        print(f"  doc-list fill cached — run --rebuild-slices to route these {len(props_by_doc)} docs into slices")
        return ncache
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


def rebuild_slices(*, backend: str | None = None, drivers: bool = True) -> int:
    """Re-derive ALL slices from the whole chunks/ doc-cache (WS-MS7) — the doc-cache is the master. Routes each
    prop to EVERY matching commodity slice (all 24 matchers) AND, independently over the WHOLE cache, to its
    driver slices — so multi-commodity docs (a WASDE) land in each commodity and pure-driver props (B40/freight)
    are NOT lost to the commodity filter. Deliberately does NOT touch the _raw archive: the cache is a superset of
    it, and _raw is keyed per contract (pure-driver props live under a doc's contract there). Free: no Anthropic."""
    backend = backend or ev.DEFAULT_BACKEND
    nodes = ev.all_nodes()
    matchers = {n: hv.build_matcher(ev.match_forms(n)) for n in nodes}
    by_node: dict[str, list[dict]] = {n: [] for n in nodes}
    driver_sink: dict[str, list[dict]] | None = {} if drivers else None
    ndocs = 0
    for h in _cached_hashes():
        recs = ev.load_index(f"chunks/{h}")
        if recs:
            ndocs += 1
        for p in recs:
            for n in nodes:                                        # every matching commodity slice (multi-label)
                if matchers[n].search(p["text"]):
                    by_node[n].append({**p, "contract": n})
            if driver_sink is not None:                            # driver slices over the WHOLE cache, commodity-independent
                for dn in ev.driver_slices_for(p["text"]):
                    driver_sink.setdefault(dn, []).append({**p, "driver": dn})
    if not ndocs:
        raise SystemExit("chunks/ doc-cache is empty — run a --retrieve first.")
    print(f"rebuild-slices: routing props from {ndocs} cached docs into commodity + driver slices")
    total = 0
    for n, recs in by_node.items():
        if not recs:                                               # don't clobber a node's slice with an empty file
            continue
        for r, v in zip(recs, ev.embed([r["text"] for r in recs], backend=backend)):
            r["vector"], r["backend"] = v, backend
        ev._evid_write(n, "\n".join(json.dumps(r) for r in recs))
        print(f"  {n}: {len(recs)} props -> evidence/{n}.jsonl")
        total += len(recs)
    if driver_sink:
        dtotal = ev.write_driver_slices(driver_sink, backend=backend)
        print(f"  drivers: {dtotal} props across {len(driver_sink)} slices -> evidence/drivers/*.jsonl")
    return total


# ── targeted doc-list fills (WS-MS7): chunk a specific set of docs, cache-aware ────────────
_YEAR_RE = __import__("re").compile(r"(?:release_date|release_month|publication_date|year|crop_year)=(\d{4})")


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


def _build_requests_from_docs(s3, doc_keys):
    """Cache-aware batch requests for a specific doc list (no per-node sampling; chunk the WHOLE doc, no matcher
    pre-filter — the fill targets these docs on purpose)."""
    requests, manifest = [], {}
    cached = _cached_hashes()
    for key in dict.fromkeys(doc_keys):                     # dedupe, preserve order
        if _doc_cache_node(key).split("/")[-1] in cached:
            continue
        for blk, meta in _doc_blocks(s3, "_docs", key, matcher=None):
            cid = f"r{len(requests):06d}"
            requests.append({"custom_id": cid, "params": {
                "model": ex.HAIKU, "max_tokens": 4096, "system": ch._PROP_SYSTEM,
                "messages": [{"role": "user", "content": blk.verbatim_span}]}})
            manifest[cid] = meta
    return requests, manifest


def submit_docs(s3, client, doc_keys) -> str:
    requests, manifest = _build_requests_from_docs(s3, doc_keys)
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
    srcs = [s for s in args.sources.split(",") if s]
    # ── free modes (no Anthropic call) ────────────────────────────────────────────
    if args.rebuild_slices:                                            # route the whole chunks/ cache -> slices
        rebuild_slices()
        return 0
    if args.reroute:                                                   # re-derive from the _raw archive
        print(f"reroute {len(nodes)} node(s) from _raw archive -> commodity + driver slices")
        reroute(nodes=nodes)
        return 0
    if args.measure_orphan_drivers:                                    # Gap-2 sizing
        print("orphan-driver measurement:", measure_orphan_drivers(s3, srcs))
        return 0
    if args.fill:                                                      # select a doc-list; --dry-run sizes blocks + cost
        keys = select_docs(srcs, before_year=args.before, after_year=args.after)
        print(f"FILL selection: {len(keys)} uncached docs from {srcs} (before={args.before}, after={args.after})")
        if not keys:
            return 0
        if args.dry_run:                                               # chunk locally (free) to size the real block count
            reqs, manifest = _build_requests_from_docs(s3, keys)
            ndocs = len({m["source_key"] for m in manifest.values()})
            lo, hi = len(reqs) * 0.002, len(reqs) * 0.007              # naive vs empirical (output tokens dominate; $70 lesson)
            print(f"FILL dry-run: {len(reqs)} blocks over {ndocs} NEW docs; Haiku batch est ~${lo:.0f}-{hi:.0f}")
            return 0
        import anthropic
        from leviathan.graphrag import batch_extract as bx
        submit_docs(s3, anthropic.Anthropic(api_key=bx._api_key()), keys)
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
        retrieve(s3, client, args.retrieve)
    elif args.submit:
        submit(s3, client, nodes=nodes, n_docs=args.n_docs)
    elif args.run:
        run(s3, client, nodes=nodes, n_docs=args.n_docs)
    else:
        print("specify --dry-run / --submit / --retrieve <bid> / --run / --fill / --rebuild-slices")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
