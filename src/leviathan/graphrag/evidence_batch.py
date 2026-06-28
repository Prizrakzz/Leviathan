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
import json
import time

from leviathan.graphrag import chunking as ch
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import extract as ex
from leviathan.graphrag import harvest as hv

_OUT = ex._CFG / "evidence" / "_batches"
_MAX_BLOCK_CHARS = 5000


def _doc_blocks(s3, node: str, key: str) -> list:
    """Deterministic blocks for one doc + its shared metadata (free; no LLM)."""
    from leviathan.graphrag.corpus_recon import BUCKET, _source_of
    doc = json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())
    full = (doc.get("full_text") or "")[:60000]
    if not full.strip():
        return []
    blocks = ch.chunk_document(full_text=full, source_key=key, source=_source_of(key),
                               document_date=ev._doc_date(doc, key), lang=doc.get("lang", "en"),
                               extraction_method=doc.get("extraction_method"), doc_id=key, target_chars=_MAX_BLOCK_CHARS)
    meta = {"contract": node, "source_key": key, "source": _source_of(key), "date": str(ev._doc_date(doc, key))}
    return [(blk, meta) for blk in blocks]


def _build_requests(s3, nodes, n_docs, seed):
    requests, manifest = [], {}
    for node in nodes:
        for key in ev.sample_keys(s3, node=node, year_windows=ev._WINDOWS[node], n=n_docs, seed=seed):
            for blk, meta in _doc_blocks(s3, node, key):
                cid = f"r{len(requests):06d}"                                  # Anthropic custom_id: ^[A-Za-z0-9_-]{1,64}$
                requests.append({"custom_id": cid, "params": {                # no tools, no caching (see header)
                    "model": ex.HAIKU, "max_tokens": 4096, "system": ch._PROP_SYSTEM,
                    "messages": [{"role": "user", "content": blk.verbatim_span}]}})
                manifest[cid] = meta
    return requests, manifest


def submit(s3, client, *, nodes, n_docs, seed: int = 0) -> str:
    requests, manifest = _build_requests(s3, nodes, n_docs, seed)
    if not requests:
        raise SystemExit("no blocks produced — aborting")
    bid = client.messages.batches.create(requests=requests).id
    _OUT.mkdir(parents=True, exist_ok=True)
    (_OUT / f"{bid}.json").write_text(json.dumps({"batch_id": bid, "manifest": manifest}), encoding="utf-8")
    print(f"submitted batch {bid} ({len(requests)} block requests over {len(nodes)} contract(s))")
    print(f"retrieve with:  python -m leviathan.graphrag.evidence_batch --retrieve {bid}")
    return bid


def _text_of(result) -> str:
    return "".join(b.text for b in result.result.message.content if getattr(b, "type", None) == "text")


def retrieve(s3, client, bid: str, *, backend: str | None = None, poll_s: int = 20) -> int:
    manifest = json.loads((_OUT / f"{bid}.json").read_text(encoding="utf-8"))["manifest"]
    while client.messages.batches.retrieve(bid).processing_status != "ended":
        print(f"  batch {bid}: still processing ...")
        time.sleep(poll_s)
    by_node: dict[str, list[dict]] = {}
    for r in client.messages.batches.results(bid):
        if getattr(r.result, "type", None) != "succeeded" or r.custom_id not in manifest:
            continue
        m = manifest[r.custom_id]
        for i, item in enumerate(ch._parse_json_array(_text_of(r))):
            prop = (item.get("proposition") or "").strip()
            if prop:
                by_node.setdefault(m["contract"], []).append(
                    {"id": f"{r.custom_id}#{i}", "contract": m["contract"], "date": m["date"],
                     "source": m["source"], "source_key": m["source_key"], "text": prop})
    backend = backend or ev.DEFAULT_BACKEND
    total = 0
    for node, recs in by_node.items():
        matcher = hv.build_matcher([node, node.replace("_", " ")] + ev._aliases(node))
        recs = [r for r in recs if matcher.search(r["text"])]                  # keep only on-topic props
        for r, v in zip(recs, ev.embed([r["text"] for r in recs], backend=backend)):
            r["vector"], r["backend"] = v, backend
        ev._EVID_DIR.mkdir(parents=True, exist_ok=True)
        (ev._EVID_DIR / f"{node}.jsonl").write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")
        print(f"  {node}: {len(recs)} dated props -> evidence/{node}.jsonl")
        total += len(recs)
    return total


def run(s3, client, *, nodes, n_docs, seed: int = 0) -> int:
    return retrieve(s3, client, submit(s3, client, nodes=nodes, n_docs=n_docs, seed=seed))


def main() -> int:
    ap = argparse.ArgumentParser(description="Batch-API evidence chunking (gated: Haiku batch billed).")
    ap.add_argument("--submit", action="store_true")
    ap.add_argument("--retrieve", metavar="BID")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--nodes", default="all")
    ap.add_argument("--n-docs", type=int, default=40)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    nodes = list(ev._WINDOWS) if args.nodes == "all" else args.nodes.split(",")
    import boto3
    from leviathan.common import config
    config.load_env()
    s3 = boto3.client("s3")
    if args.dry_run:
        reqs, _ = _build_requests(s3, nodes, args.n_docs, 0)
        usd = len(reqs) * (1500 * 0.5 / 1e6 + 500 * 2.5 / 1e6)             # Haiku batch ~$0.50/$2.50 per M
        print(f"DRY-RUN: ~{len(reqs)} block requests over {nodes}; Haiku batch est ~${usd:.2f} (~50% of inline)")
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
