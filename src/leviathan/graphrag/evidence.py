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

    terms = [t for t in node.lower().split("_") if len(t) > 2]   # commodity tokens, NOT the contract's exchange suffix
    terms += [tok for t in _extra_terms(node) for tok in t.lower().split() if len(tok) > 2]  # parent-source bias too
    in_win = [k for k in keys if in_window(k)]
    relevant = [k for k in in_win if any(t in _source_of(k).lower() for t in terms)]
    rng = random.Random(seed)
    if len(relevant) >= n:
        return rng.sample(relevant, n)
    # KEEP every source-relevant doc, then top up from the rest of the in-window pool. (Old code abandoned the
    # relevance bias entirely when relevant < n, diluting a thin commodity's few real docs in a random draw.)
    rest = [k for k in in_win if k not in set(relevant)]
    out = relevant + rng.sample(rest, min(n - len(relevant), len(rest)))
    rng.shuffle(out)
    return out


def build_index(s3, *, node: str, aliases, year_windows, n_docs: int, backend: str | None = None,
                bedrock=None, chunker=None, max_props: int = 400) -> int:
    """Sample -> chunk -> keep on-topic props -> embed -> write configs/graphrag/evidence/<node>.jsonl. Billed."""
    from leviathan.graphrag.corpus_recon import BUCKET, _source_of
    from leviathan.graphrag import chunking as ch
    backend = backend or DEFAULT_BACKEND
    bedrock = bedrock or _bedrock()                  # still needed for Haiku chunking even when embedding is local
    chunker = chunker or ch.propositional_chunks
    matcher = hv.build_matcher([node, node.replace("_", " ")] + list(aliases) + _extra_terms(node))
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


# ── contract -> commodity node resolution (variants share one evidence slice) ──────────
def _hier() -> dict:
    import yaml
    p = ex._CFG / "commodity_hierarchy.yaml"
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def node_for(contract: str) -> str:
    """The commodity NODE whose evidence/<node>.jsonl serves this contract — so soybean_meal_cbot and
    soybean_meal_dce share one `soybean_meal` slice. Unknown/already-a-node ids return unchanged."""
    spec = (_hier().get("contracts") or {}).get(contract)
    return spec["node"] if isinstance(spec, dict) and spec.get("node") else contract


def all_nodes() -> list[str]:
    """The distinct commodity nodes across the 31 contracts (~24)."""
    contracts = _hier().get("contracts") or {}
    return sorted({(v.get("node") or k) for k, v in contracts.items() if isinstance(v, dict)})


def covered_nodes() -> set[str]:
    return {p.stem for p in _EVID_DIR.glob("*.jsonl")} if _EVID_DIR.exists() else set()


def new_nodes() -> list[str]:
    """Nodes with no evidence/<node>.jsonl yet — the build target when scaling."""
    return [n for n in all_nodes() if n not in covered_nodes()]


# ── build CLI (gated: Haiku chunking is billed) ───────────────────────────────────────
_WINDOWS = {                                          # baked-in pilot defaults (public); the rest live in the config
    "arabica_coffee": [(2021, 2021), (2014, 2014)],
    "corn": [(2012, 2012), (2022, 2022)],
    "soybeans": [(2012, 2012), (2018, 2018), (2024, 2024)],
}
_WINDOWS_PATH = ex._CFG / "evidence_windows.yaml"     # marquee shock-year windows for all nodes (gitignored IP)
_BROAD = [(1973, 2026)]                               # fallback: sample across the FULL corpus (back to 1973)


def _windows() -> dict:
    if not _WINDOWS_PATH.exists():
        return {}
    import yaml
    raw = yaml.safe_load(_WINDOWS_PATH.read_text(encoding="utf-8")) or {}
    return {k: [tuple(w) for w in v] for k, v in (raw.get("windows") or {}).items()}


def windows_for(node: str) -> list:
    """Marquee episode windows for a node: the config first, then the baked-in pilot default, then broad."""
    return _windows().get(node) or _WINDOWS.get(node) or _BROAD


def _extra_terms(node: str) -> list[str]:
    """Parent-commodity match terms for sub-nodes the global corpus only names generically (white_maize ->
    'maize'/'corn', the wheat classes -> 'wheat'). From evidence_windows.yaml `extra_terms`."""
    if not _WINDOWS_PATH.exists():
        return []
    import yaml
    raw = yaml.safe_load(_WINDOWS_PATH.read_text(encoding="utf-8")) or {}
    return [str(t) for t in ((raw.get("extra_terms") or {}).get(node) or [])]


def match_forms(node: str) -> list[str]:
    """Every surface form the on-topic matcher should fire on for a node: the id, the spaced id, its vocab/
    contract aliases, and any parent-commodity extra_terms."""
    return [node, node.replace("_", " ")] + _aliases(node) + _extra_terms(node)


def n_docs_for(node: str, default: int) -> int:
    """Per-node doc-sample override (config `n_docs`) — corpus-sparse nodes (cocoa, orange_juice) that aren't
    key-identifiable need WIDER random sampling to hit enough on-topic docs."""
    if not _WINDOWS_PATH.exists():
        return default
    import yaml
    raw = yaml.safe_load(_WINDOWS_PATH.read_text(encoding="utf-8")) or {}
    return int((raw.get("n_docs") or {}).get(node, default))


def _aliases(node: str) -> list[str]:
    """Surface forms for the node's matcher — from the harvested vocab (keyed by commodity node), plus any
    contract YAML aliases if a YAML happens to share the node's name."""
    al = list((ex._vocab().get("aliases") or {}).get(node) or [])
    p = ex._CFG / "causal" / f"{node}.yaml"
    if p.exists():
        from leviathan.causal import schema as cs
        al += [a for a in cs.load(p).aliases if a not in al]
    return al


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the dated-evidence slice (gated: Haiku chunking billed).")
    ap.add_argument("--build", metavar="NODE", help="contract/node id, 'all', or 'new' (uncovered nodes)")
    ap.add_argument("--restamp", metavar="NODE", help="re-derive dates from keys (no spend); id, 'all', or 'new'")
    ap.add_argument("--n-docs", type=int, default=40)
    ap.add_argument("--backend", default=DEFAULT_BACKEND)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    def _resolve(sel: str) -> list[str]:
        if sel == "all":
            return all_nodes()
        if sel == "new":
            return new_nodes()
        return [node_for(sel)]                                # a contract id maps to its commodity node

    if args.restamp:
        targets = covered_nodes() if args.restamp == "all" else _resolve(args.restamp)
        for node in sorted(targets):
            print(f"  {node}: restamped {restamp(node)} props from publication_date keys")
        return 0
    nodes = _resolve(args.build) if args.build else []
    if args.dry_run or not args.build:
        emb = "local/free" if args.backend.startswith("bge_local") else "billed (tiny)"
        print(f"DRY-RUN: build {len(nodes)} node(s) {nodes}, ~{args.n_docs} docs each, backend={args.backend} "
              f"(embed {emb}); Haiku chunking is billed.")
        return 0
    import boto3
    from leviathan.common import config
    config.load_env()
    s3 = boto3.client("s3")
    for node in nodes:
        n = build_index(s3, node=node, aliases=_aliases(node), year_windows=windows_for(node),
                        n_docs=n_docs_for(node, args.n_docs), backend=args.backend)
        print(f"  {node}: {n} dated props -> evidence/{node}.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
