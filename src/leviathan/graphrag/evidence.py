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


def _pub_date(key: str) -> date | None:
    """Exact publication date from the S3 key — `publication_date=YYYYMMDD` (our keys), or an MM-DD-YYYY
    fragment in the document folder name. None when neither is present."""
    import re
    m = re.search(r"publication_date=(\d{4})(\d{2})(\d{2})", key)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            pass
    m = re.search(r"(?<!\d)(\d{2})-(\d{2})-(20\d{2})(?!\d)", key)     # e.g. ...mexico_05-15-2021
    if m:
        try:
            return date(int(m[3]), int(m[1]), int(m[2]))
        except ValueError:
            pass
    return None


def _doc_date(doc: dict, key: str) -> date:
    """Document date: exact publication date from the key, else an explicit doc field, else year->Jan-1."""
    d = _pub_date(key)
    if d:
        return d
    raw = doc.get("document_date") or doc.get("date")
    if raw:
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            pass
    from leviathan.graphrag import batch_extract as bx
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


def _proximity(date_str: str, near: str, *, half_life_days: float = 365.0) -> float:
    """1.0 at `near`, decaying to 0.5 one half-life away — a gentle recency-to-episode bonus in [0,1]."""
    try:
        d = date.fromisoformat(date_str[:10])
        n = date.fromisoformat((near + "-07-01")[:10]) if len(near) == 4 else date.fromisoformat(near[:10])
    except ValueError:
        return 0.0
    return 0.5 ** (abs((d - n).days) / half_life_days)


def retrieve(query: str, node: str, *, k: int = 5, asof: str | None = None, near: str | None = None,
             beta: float = 0.25, bedrock=None, records: list[dict] | None = None) -> list[dict]:
    """Top-k props by cosine to the query, point-in-time filtered (date <= asof). When `near` (an episode
    date/year) is given, blend in a date-proximity bonus: score = cosine + beta*proximity(date, near)."""
    records = load_index(node) if records is None else records
    if asof:
        records = [r for r in records if r["date"] <= asof]
    if not records:
        return []
    qv = embed([query], backend=records[0].get("backend"), bedrock=bedrock)[0]   # same space as the index
    def _score(r):
        return _cosine(qv, r["vector"]) + (beta * _proximity(r["date"], near) if near else 0.0)
    ranked = sorted(records, key=_score, reverse=True)
    return [{"date": r["date"], "source": r["source"], "source_key": r["source_key"], "text": r["text"]}
            for r in ranked[:k]]


def restamp(node: str) -> int:
    """Re-derive each record's date from its stored source_key (precise publication_date) — no re-chunk/embed."""
    recs = load_index(node)
    for r in recs:
        d = _pub_date(r["source_key"])
        if d:
            r["date"] = str(d)
    (_EVID_DIR / f"{node}.jsonl").write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")
    return len(recs)


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
    ap.add_argument("--restamp", metavar="NODE", help="re-derive dates from keys (no spend); id or 'all'")
    ap.add_argument("--n-docs", type=int, default=40)
    ap.add_argument("--backend", default=DEFAULT_BACKEND)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.restamp:
        for node in (list(_WINDOWS) if args.restamp == "all" else [args.restamp]):
            print(f"  {node}: restamped {restamp(node)} props from publication_date keys")
        return 0
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
