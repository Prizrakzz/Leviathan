"""Targeted dated-evidence slice for graphdev (GRAPHRAG_PLAN v2 Phase 2 WS-2).

Samples a SMALL set of corpus docs per contract (marquee episode year-windows), turns them into dated
propositions (Haiku via chunking.propositional_chunks), embeds each with Bedrock Titan v2, and stores a tiny
local index. retrieve() returns point-in-time-filtered, dated, sourced props for a query. NOT the whole
corpus — just enough to ground the 10-query eval. The build run is gated (Haiku + Titan = billed)."""
from __future__ import annotations

import argparse
import json
import math
import os
import random
from datetime import date

from leviathan.graphrag import extract as ex
from leviathan.graphrag import harvest as hv

_EVID_DIR = ex._CFG / "evidence"
TITAN_MODEL = "amazon.titan-embed-text-v2:0"
BGE_MODEL = "BAAI/bge-m3"
# default embedder: bge-m3 local (best multilingual retrieval for our PT/ES/FR corpus). The SAME backend must
# embed the index AND the query (one space) — so the index stamps its backend and retrieve() reuses it.
DEFAULT_BACKEND = os.environ.get("EVIDENCE_EMBED_BACKEND", "bge_local")
_bge = None                                          # lazy SentenceTransformer singleton


def _bedrock():
    import boto3
    return boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def _bge_local(texts: list[str]) -> list[list[float]]:
    global _bge
    if _bge is None:
        from sentence_transformers import SentenceTransformer
        _bge = SentenceTransformer(BGE_MODEL)
    return [v.tolist() for v in _bge.encode(texts, normalize_embeddings=True)]


def embed(texts: list[str], *, backend: str | None = None, bedrock=None, model: str = TITAN_MODEL,
          endpoint: str | None = None) -> list[list[float]]:
    """Embed texts with the selected backend: 'bge_local' (sentence-transformers, default), 'titan' (Bedrock
    Titan v2 fallback), or 'bge_endpoint' (a hosted bge-m3 container — the production path)."""
    backend = backend or DEFAULT_BACKEND
    if not texts:
        return []
    if backend == "bge_local":
        return _bge_local(texts)
    if backend == "titan":
        bedrock = bedrock or _bedrock()
        out = []
        for t in texts:
            resp = bedrock.invoke_model(modelId=model, body=json.dumps({"inputText": t[:8000]}))
            out.append(json.loads(resp["body"].read())["embedding"])
        return out
    if backend == "bge_endpoint":
        import urllib.request
        url = endpoint or os.environ["EVIDENCE_EMBED_ENDPOINT"]
        req = urllib.request.Request(url, data=json.dumps({"texts": texts}).encode(),
                                     headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req).read())["embeddings"]
    raise ValueError(f"unknown embed backend {backend!r}")


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _doc_date(doc: dict, key: str) -> date:
    """Best-effort document date: an explicit field, else year-from-key at Jan 1 (coarse but PIT-safe)."""
    from leviathan.graphrag import batch_extract as bx
    raw = doc.get("document_date") or doc.get("date")
    if raw:
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            pass
    y = bx._year_of(key)
    return date(int(y), 1, 1) if y not in (None, "unknown") else date(1970, 1, 1)


def sample_keys(s3, *, node: str, year_windows, n: int, seed: int = 0) -> list[str]:
    """Doc keys in the marquee year-windows, biased to commodity-relevant sources (widen if too few)."""
    from leviathan.graphrag.corpus_recon import BUCKET, TEXT_PREFIX, _source_of
    from leviathan.graphrag import batch_extract as bx
    keys = [o["Key"] for p in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=TEXT_PREFIX)
            for o in p.get("Contents", []) if o["Key"].endswith("document.json")]

    def in_window(k: str) -> bool:
        y = bx._year_of(k)
        return y not in (None, "unknown") and any(lo <= int(y) <= hi for lo, hi in year_windows)

    tok = node.split("_")[-1].lower()
    relevant = [k for k in keys if in_window(k) and tok in _source_of(k).lower()]
    pool = relevant if len(relevant) >= n else [k for k in keys if in_window(k)]
    return random.Random(seed).sample(pool, min(n, len(pool)))


def build_index(s3, *, node: str, aliases, year_windows, n_docs: int, backend: str | None = None,
                bedrock=None, chunker=None, max_props: int = 400) -> int:
    """Sample -> chunk -> keep on-topic props -> embed -> write configs/graphrag/evidence/<node>.jsonl. Billed."""
    from leviathan.graphrag.corpus_recon import BUCKET, _source_of
    from leviathan.graphrag import chunking as ch
    backend = backend or DEFAULT_BACKEND
    bedrock = bedrock or _bedrock()                  # still needed for Haiku chunking even when embedding is local
    chunker = chunker or ch.propositional_chunks
    matcher = hv.build_matcher([node, node.replace("_", " ")] + list(aliases))
    records: list[dict] = []
    for k in sample_keys(s3, node=node, year_windows=year_windows, n=n_docs):
        doc = json.loads(s3.get_object(Bucket=BUCKET, Key=k)["Body"].read())
        txt = doc.get("full_text") or ""
        if not matcher.search(txt):                       # commodity not actually discussed -> skip
            continue
        props = chunker(full_text=txt[:20000], source_key=k, source=_source_of(k), document_date=_doc_date(doc, k),
                        lang=doc.get("lang", "en"), extraction_method=doc.get("extraction_method"), doc_id=k,
                        bedrock=bedrock)
        for p in props:
            if matcher.search(p.proposition):             # keep only props that mention the commodity
                records.append({"id": p.chunk_id, "contract": node, "date": str(p.document_date),
                                "source": p.source, "source_key": k, "text": p.proposition})
        if len(records) >= max_props:
            break
    records = records[:max_props]
    for r, v in zip(records, embed([r["text"] for r in records], backend=backend, bedrock=bedrock)):
        r["vector"], r["backend"] = v, backend       # stamp backend so retrieve() embeds queries the same way
    _EVID_DIR.mkdir(parents=True, exist_ok=True)
    (_EVID_DIR / f"{node}.jsonl").write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    return len(records)


def load_index(node: str) -> list[dict]:
    p = _EVID_DIR / f"{node}.jsonl"
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def retrieve(query: str, node: str, *, k: int = 5, asof: str | None = None, bedrock=None,
             records: list[dict] | None = None) -> list[dict]:
    """Top-k props by cosine to the query, point-in-time filtered (date <= asof). Returns date+source+text."""
    records = load_index(node) if records is None else records
    if asof:
        records = [r for r in records if r["date"] <= asof]
    if not records:
        return []
    qv = embed([query], backend=records[0].get("backend"), bedrock=bedrock)[0]   # same space as the index
    ranked = sorted(records, key=lambda r: _cosine(qv, r["vector"]), reverse=True)
    return [{"date": r["date"], "source": r["source"], "source_key": r["source_key"], "text": r["text"]}
            for r in ranked[:k]]


# ── build CLI (gated: Haiku chunking is billed) ───────────────────────────────────────
_WINDOWS = {                                          # marquee episode year-windows per contract
    "arabica_coffee": [(2021, 2021), (2014, 2014)],
    "corn": [(2012, 2012), (2022, 2022)],
    "soybeans": [(2012, 2012), (2018, 2018), (2024, 2024)],
}


def _aliases(node: str) -> list[str]:
    from leviathan.causal import schema as cs
    p = ex._CFG / "causal" / f"{node}.yaml"
    return list(cs.load(p).aliases) if p.exists() else []


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the dated-evidence slice (gated: Haiku chunking billed).")
    ap.add_argument("--build", metavar="NODE", help="contract id or 'all'")
    ap.add_argument("--n-docs", type=int, default=40)
    ap.add_argument("--backend", default=DEFAULT_BACKEND)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    nodes = list(_WINDOWS) if args.build == "all" else [args.build]
    if args.dry_run or not args.build:
        emb = "local/free" if args.backend.startswith("bge_local") else "billed (tiny)"
        print(f"DRY-RUN: build {nodes}, ~{args.n_docs} docs each, backend={args.backend} "
              f"(embed {emb}); Haiku chunking is billed (~$2-5 total).")
        return 0
    import boto3
    from leviathan.common import config
    config.load_env()
    s3 = boto3.client("s3")
    for node in nodes:
        n = build_index(s3, node=node, aliases=_aliases(node), year_windows=_WINDOWS[node],
                        n_docs=args.n_docs, backend=args.backend)
        print(f"  {node}: {n} dated props -> evidence/{node}.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
