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


# Evidence store: local jsonl by default; set EVIDENCE_S3=s3://bucket/prefix/ to read+write S3 instead — so the
# cloud build (AWS Batch) writes where serving reads, with no laptop dependency (WS-MS2.1).
def _evid_s3() -> str | None:
    return os.environ.get("EVIDENCE_S3")


def _parse_s3(uri: str):
    b, _, k = uri[len("s3://"):].partition("/")
    return b, k


def _evid_write(node: str, text: str) -> None:
    base = _evid_s3()
    if base:
        import boto3
        bkt, key = _parse_s3(base.rstrip("/") + f"/{node}.jsonl")
        boto3.client("s3").put_object(Bucket=bkt, Key=key, Body=text.encode("utf-8"))
    else:
        p = _EVID_DIR / f"{node}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)            # node may be "drivers/<x>" (a subdir)
        p.write_text(text, encoding="utf-8")


def _evid_read(node: str) -> str:
    base = _evid_s3()
    if base:
        import boto3
        from botocore.exceptions import ClientError
        bkt, key = _parse_s3(base.rstrip("/") + f"/{node}.jsonl")
        try:
            return boto3.client("s3").get_object(Bucket=bkt, Key=key)["Body"].read().decode("utf-8")
        except ClientError:
            return ""
    p = _EVID_DIR / f"{node}.jsonl"
    return p.read_text(encoding="utf-8") if p.exists() else ""
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


# --- source-agnostic sampling: the EDGE is a multi-source corpus, not a USDA-GAIN mirror -----------------
# Sources that discuss MANY commodities (so every node should draw from them, not only its dedicated GAIN source):
_ALL_COMMODITY_SOURCES = frozenset({"wb_cmo_outlook", "usda_wasde", "usda_wap", "usda_gain_grain_monthly", "conab"})
# Specialized NON-GAIN sources keyed by a commodity token (their names don't contain the commodity):
_SPECIALIZED_SOURCES = {"coffee": ("fnc", "usda_fas_coffee_wmt"), "palm": ("mpoc", "mpob")}
_DEDICATED_FRAC = 0.6                                  # dedicated source gets ~60% (depth); the rest is multi-source breadth


def _node_source_terms(node: str) -> list[str]:
    terms = [t for t in node.lower().split("_") if len(t) > 2]   # commodity tokens, NOT the exchange suffix
    return terms + [tok for t in _extra_terms(node) for tok in t.lower().split() if len(tok) > 2]


def covering_sources(node: str, all_sources) -> set[str]:
    """Sources whose docs are CANDIDATES for this node: the dedicated (name-matching) source(s), the
    all-commodity sources (wb_cmo/wasde/wap/...), and any specialized non-GAIN source for the commodity. The
    full-text matcher still decides on-topic at chunk time — this just stops the fat GAIN source from being the
    ONLY thing sampled (which made every rich node ~100% single-source)."""
    toks = _node_source_terms(node)
    cov = set(_ALL_COMMODITY_SOURCES) | {s for s in all_sources if any(t in s.lower() for t in toks)}
    for tok, srcs in _SPECIALIZED_SOURCES.items():
        if tok in toks:
            cov |= set(srcs)
    return cov & set(all_sources)


def _roundrobin(lists: list[list]) -> list:
    out, i = [], 0
    while True:
        added = False
        for ks in lists:
            if i < len(ks):
                out.append(ks[i]); added = True
        if not added:
            return out
        i += 1


def sample_keys(s3, *, node: str, year_windows, n: int, seed: int = 0) -> list[str]:
    """SOURCE-AGNOSTIC doc sampling: ~60% from the dedicated source(s) (depth) + the rest round-robin across the
    OTHER covering sources (breadth), so the index spans wb_cmo/fnc/mpoc/conab/wasde — not 100% GAIN. The chunk-time
    matcher still filters on-topic; retrieval stays source-neutral."""
    from leviathan.graphrag.corpus_recon import BUCKET, TEXT_PREFIX, _source_of
    from leviathan.graphrag import batch_extract as bx
    keys = [o["Key"] for p in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=TEXT_PREFIX)
            for o in p.get("Contents", []) if o["Key"].endswith("document.json")]

    def in_window(k: str) -> bool:
        y = bx._year_of(k)
        return y not in (None, "unknown") and any(lo <= int(y) <= hi for lo, hi in year_windows)

    in_win = [k for k in keys if in_window(k)]
    if not in_win:
        return []
    all_src = {_source_of(k) for k in in_win}
    toks = _node_source_terms(node)
    dedicated = {s for s in all_src if any(t in s.lower() for t in toks)}
    cov = covering_sources(node, all_src)
    rng = random.Random(seed)
    ded_docs = [k for k in in_win if _source_of(k) in dedicated]
    rng.shuffle(ded_docs)
    by_other: dict[str, list] = {}                    # the other covering sources, grouped for round-robin balance
    for k in in_win:
        s = _source_of(k)
        if s in cov and s not in dedicated:
            by_other.setdefault(s, []).append(k)
    for ks in by_other.values():
        rng.shuffle(ks)
    other_balanced = _roundrobin(list(by_other.values()))
    n_ded = round(n * _DEDICATED_FRAC)
    out = ded_docs[:n_ded] + other_balanced[:max(0, n - len(ded_docs[:n_ded]))]
    if len(out) < n:                                  # short -> top up from anything in-window (matcher filters later)
        used = set(out)
        rest = [k for k in in_win if k not in used]
        rng.shuffle(rest)
        out += rest[:n - len(out)]
    rng.shuffle(out)
    return out[:n]


def _prop_record(p, *, key: str) -> dict:
    """Shared fields for a stored prop — incl. the WS-MS6 event_date temporal pair (None when unstated)."""
    return {"date": str(p.document_date), "source": p.source, "source_key": key, "text": p.proposition,
            "event_date": str(p.event_date) if getattr(p, "event_date", None) else None,
            "event_date_precision": getattr(p, "event_date_precision", None)}


def build_index(s3, *, node: str, aliases, year_windows, n_docs: int, backend: str | None = None,
                bedrock=None, chunker=None, max_props: int | None = 400, workers: int = 1,
                aws_region: str | None = None, driver_sink: dict | None = None,
                provider: str = "bedrock", anthropic_client=None) -> int:
    """Sample -> chunk -> keep on-topic props -> embed -> write configs/graphrag/evidence/<node>.jsonl. Billed.

    workers>1 parallelizes the per-doc Bedrock-Haiku chunking over thread-local S3 clients — the cloud-build
    path (build_evidence_task on Fargate); workers=1 is the sequential laptop path. max_props=None lifts the cap.
    driver_sink (WS-MS6): when given, every chunked prop is ALSO routed to driver slices (driver -> [records])
    in-place — the cross-cutting cascade props (B40, freight, FX, El Nino) harvested FREE from the same pass."""
    from leviathan.graphrag.corpus_recon import BUCKET, _source_of
    from leviathan.graphrag import chunking as ch
    backend = backend or DEFAULT_BACKEND
    if provider == "bedrock":
        bedrock = bedrock or _bedrock()              # Haiku chunking via Bedrock (default); 'anthropic' uses the API
    chunker = chunker or ch.propositional_chunks
    matcher = hv.build_matcher([node, node.replace("_", " ")] + list(aliases) + _extra_terms(node))
    keys = sample_keys(s3, node=node, year_windows=year_windows, n=n_docs)

    def _one(key: str, s3c):
        try:
            doc = json.loads(s3c.get_object(Bucket=BUCKET, Key=key)["Body"].read())
            txt = doc.get("full_text") or ""
            if not matcher.search(txt):                   # commodity not actually discussed -> skip (no Haiku spend)
                return [], []
            props = chunker(full_text=txt[:20000], source_key=key, source=_source_of(key), document_date=_doc_date(doc, key),
                            lang=doc.get("lang", "en"), extraction_method=doc.get("extraction_method"), doc_id=key,
                            bedrock=bedrock, provider=provider, anthropic_client=anthropic_client)
        except Exception:                                 # one malformed/unreadable doc must not tank the whole node
            return [], []
        crecs, drecs = [], []
        for p in props:
            base = _prop_record(p, key=key)
            if matcher.search(p.proposition):             # names the commodity -> commodity slice
                crecs.append({"id": p.chunk_id, "contract": node, **base})
            if driver_sink is not None:                   # matches a driver term -> driver slice(s), multi-label
                for dn in driver_slices_for(p.proposition):
                    drecs.append((dn, {"id": p.chunk_id, "driver": dn, **base}))
        return crecs, drecs

    def _absorb(crecs, drecs):
        records.extend(crecs)
        for dn, r in drecs:
            driver_sink.setdefault(dn, []).append(r)

    records: list[dict] = []
    if workers > 1:                                       # cloud: fan the per-doc Haiku chunking across threads
        from concurrent.futures import ThreadPoolExecutor
        from leviathan.storage.s3 import get_thread_local_s3_client
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for crecs, drecs in pool.map(lambda k: _one(k, get_thread_local_s3_client(aws_region)), keys):
                _absorb(crecs, drecs)
    else:
        for k in keys:
            crecs, drecs = _one(k, s3)
            _absorb(crecs, drecs)
            if max_props and len(records) >= max_props:
                break
    if max_props:
        records = records[:max_props]
    for r, v in zip(records, embed([r["text"] for r in records], backend=backend, bedrock=bedrock)):
        r["vector"], r["backend"] = v, backend       # stamp backend so retrieve() embeds queries the same way
    _evid_write(node, "\n".join(json.dumps(r) for r in records))
    return len(records)


CACHE_INDEX = os.environ.get("EVIDENCE_INDEX_CACHE") == "1"   # eval sets ev.CACHE_INDEX=True so big slices load once
_INDEX_CACHE: dict[str, list[dict]] = {}


def load_index(node: str) -> list[dict]:
    """Load a slice's records. With CACHE_INDEX on (multi-query eval over the now-large 15-23K-prop slices) a
    node's records download from S3 once and are reused — the flat-file stopgap until pgvector."""
    if CACHE_INDEX and node in _INDEX_CACHE:
        return _INDEX_CACHE[node]
    recs = [json.loads(ln) for ln in _evid_read(node).splitlines() if ln.strip()]
    if CACHE_INDEX:
        _INDEX_CACHE[node] = recs
    return recs


def _proximity(date_str: str, near: str, *, half_life_days: float = 365.0) -> float:
    """1.0 at `near`, decaying to 0.5 one half-life away — a gentle recency-to-episode bonus in [0,1]."""
    try:
        d = date.fromisoformat(date_str[:10])
        n = date.fromisoformat((near + "-07-01")[:10]) if len(near) == 4 else date.fromisoformat(near[:10])
    except ValueError:
        return 0.0
    return 0.5 ** (abs((d - n).days) / half_life_days)


def _out(recs: list[dict]) -> list[dict]:
    return [{"date": r["date"], "source": r["source"], "source_key": r["source_key"], "text": r["text"]} for r in recs]


def retrieve(query: str, node: str, *, k: int = 5, asof: str | None = None, near: str | None = None,
             beta: float = 0.25, bedrock=None, records: list[dict] | None = None,
             mode: str = "dense", rerank: bool = False, mmr: float = 0.0,
             same_source: bool = True, fairness: float = 0.30, fetch_k: int = 60) -> list[dict]:
    """Top-k props for the query, point-in-time filtered (date <= asof) — leakage-safe. Default
    (mode='dense', rerank=False, mmr=0) is pure cosine + episode-proximity, UNCHANGED. Opt-in retrieval-quality
    knobs (all in-memory; they curate WHICH dated evidence reaches the LLM, never the reasoning):
      mode='hybrid' -> add a BM25 lexical leg fused via RRF (recall on exact tokens like B40/ZL);
      rerank=True   -> a bge cross-encoder re-orders relevance (precision);
      mmr>0         -> MMR final-select for diversity (guards against rerank narrowing the evidence set)."""
    all_records = load_index(node) if records is None else records
    recs = [r for r in all_records if r["date"] <= asof] if asof else list(all_records)   # leakage filter FIRST
    if not recs:
        return []
    qv = embed([query], backend=recs[0].get("backend"), bedrock=bedrock)[0]   # same space as the index

    def _dense(r):
        return _cosine(qv, r["vector"]) + (beta * _proximity(r["date"], near) if near else 0.0)

    dense_ranked = sorted(recs, key=_dense, reverse=True)
    if mode == "dense" and not rerank and mmr <= 0:                # fast path == today's behavior, byte-for-byte
        return _out(dense_ranked[:k])

    from leviathan.graphrag import rankers as rk
    cand = (rk.hybrid_candidates(query, node, all_records, asof, dense_ranked, fetch_k)   # RECALL
            if mode == "hybrid" else dense_ranked[:fetch_k])
    relevance = [_dense(r) for r in cand]
    if rerank and cand:                                            # PRECISION: cross-encoder re-order
        relevance = rk.rerank_scores(query, [r["text"] for r in cand])
        order = sorted(range(len(cand)), key=lambda i: relevance[i], reverse=True)
        cand, relevance = [cand[i] for i in order], [relevance[i] for i in order]
    top = (rk.mmr_select(cand, relevance, k, mmr, same_source=same_source, fairness=fairness)
           if (mmr > 0 and len(cand) > k) else cand[:k])                       # DIVERSITY (source-aware)
    return _out(top)


def restamp(node: str) -> int:
    """Re-derive each record's date from its stored source_key (precise publication_date) — no re-chunk/embed."""
    recs = load_index(node)
    for r in recs:
        d = _pub_date(r["source_key"])
        if d:
            r["date"] = str(d)
    _evid_write(node, "\n".join(json.dumps(r) for r in recs))
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
    """Commodity nodes with an evidence/<node>.jsonl — driver slices (evidence/drivers/*) are NOT nodes."""
    base = _evid_s3()
    if base:
        import boto3
        bkt, prefix = _parse_s3(base.rstrip("/") + "/")
        out = set()
        for p in boto3.client("s3").get_paginator("list_objects_v2").paginate(Bucket=bkt, Prefix=prefix):
            for o in p.get("Contents", []):
                key = o["Key"][len(prefix):]                     # path relative to the evidence base
                if key.endswith(".jsonl") and "/" not in key:    # top-level only -> skips drivers/<x>.jsonl
                    out.add(key[:-6])
        return out
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


# ── driver-keyed evidence slices (WS-MS6) ─────────────────────────────────────────────────
_DRIVER_PATH = ex._CFG / "driver_slices.yaml"
_DRIVER_CACHE = None
_DRIVER_MATCHERS = None


def driver_specs() -> dict:
    """The driver-slice map from driver_slices.yaml ({driver: {category, terms, priority?}}), cached."""
    global _DRIVER_CACHE
    if _DRIVER_CACHE is None:
        if not _DRIVER_PATH.exists():
            _DRIVER_CACHE = {}
        else:
            import yaml
            raw = yaml.safe_load(_DRIVER_PATH.read_text(encoding="utf-8")) or {}
            _DRIVER_CACHE = raw.get("drivers") or {}
    return _DRIVER_CACHE


def driver_matchers() -> dict:
    """One on-topic matcher per driver slice (cached), built from each driver's terms."""
    global _DRIVER_MATCHERS
    if _DRIVER_MATCHERS is None:
        _DRIVER_MATCHERS = {d: hv.build_matcher([str(t) for t in (spec.get("terms") or [])])
                            for d, spec in driver_specs().items()}
    return _DRIVER_MATCHERS


def driver_slices_for(text: str) -> list[str]:
    """The driver slices a proposition belongs to — every driver whose terms it mentions. A pure-driver prop
    ('Pacific freight doubled') that names no commodity still lands here; a prop can join several drivers."""
    return [d for d, m in driver_matchers().items() if m.search(text)]


def write_driver_slices(driver_sink: dict, *, backend: str | None = None, bedrock=None,
                        max_per: int = 4000) -> int:
    """Embed + write the accumulated driver props to evidence/drivers/<driver>.jsonl. Dedups the re-chunk
    artifact (same prop harvested from the same doc under multiple commodity builds) by (source_key, text),
    KEEPING cross-source / cross-date instances (the persistence + corroboration signal). Returns props written."""
    backend = backend or DEFAULT_BACKEND
    total = 0
    for driver, recs in driver_sink.items():
        seen, uniq = set(), []
        for r in recs:
            k = (r.get("source_key"), r["text"])
            if k in seen:
                continue
            seen.add(k)
            uniq.append(r)
        uniq = uniq[:max_per]
        for r, v in zip(uniq, embed([r["text"] for r in uniq], backend=backend, bedrock=bedrock)):
            r["vector"], r["backend"] = v, backend
        _evid_write(f"drivers/{driver}", "\n".join(json.dumps(r) for r in uniq))
        total += len(uniq)
    return total


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
