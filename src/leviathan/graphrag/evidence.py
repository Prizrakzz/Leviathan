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
from typing import Optional

from leviathan.graphrag import extract as ex
from leviathan.graphrag import harvest as hv
from leviathan.graphrag import params as _prm

_FETCH_K = int(_prm.get("serving.retrieval.fetch_k", 60))


def fold(s: str) -> str:
    """Accent-FOLD a string: NFKD-decompose then drop combining marks, so El_Nino/La_Nina collapse
    onto their ASCII forms (n~ -> n). NOT NFC — NFC keeps the precomposed n~ and stays byte-disjoint from
    the ASCII slice name; only stripping the combining mark recovers the match (E1 census correction #8).

    Lives here (not e1_census) so driver_alias()'s accent-fold registration and e1_census's fold_recoverable
    metric share ONE implementation. e1_census re-imports it — the reverse (evidence importing e1_census)
    would cycle, since e1_census already imports evidence."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

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


_Q_CACHE: dict[tuple, list[float]] = {}                       # single-text memo: the L2 walk re-embeds the SAME
_Q_CACHE_MAX = 4096                                           # query for every node it grounds (WS-0: 26% of wall)


def embed(texts: list[str], *, backend: str | None = None, bedrock=None, model: str = TITAN_MODEL,
          endpoint: str | None = None) -> list[list[float]]:
    """Embed texts with the selected backend: 'bge_local' (sentence-transformers, default), 'titan' (Bedrock
    Titan v2 fallback), or 'bge_endpoint' (a hosted bge-m3 container — the production path). Single-text calls
    (query/mechanism embeds — retrieval-time) are memoized; bulk build-time calls are not."""
    backend = backend or DEFAULT_BACKEND
    if not texts:
        return []
    if len(texts) == 1:                                       # retrieval-time path: same query across many nodes
        key = (backend, texts[0])
        if key not in _Q_CACHE:
            if len(_Q_CACHE) >= _Q_CACHE_MAX:                 # bound the memo (long-lived serving process)
                _Q_CACHE.clear()
            _Q_CACHE[key] = _embed_raw(texts, backend=backend, bedrock=bedrock, model=model, endpoint=endpoint)[0]
        return [_Q_CACHE[key]]
    return _embed_raw(texts, backend=backend, bedrock=bedrock, model=model, endpoint=endpoint)


def _embed_raw(texts: list[str], *, backend: str, bedrock=None, model: str = TITAN_MODEL,
               endpoint: str | None = None) -> list[list[float]]:
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
    m = re.search(r"release=(\d{4})-(\d{2})", key)                    # wb_cmo_outlook release=YYYY-MM (S6);
    if m:                                                             # `release=` cannot fire on `release_date=`
        try:                                                          # (the char after `release` there is `_`)
            return date(int(m[1]), int(m[2]), 1)
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


def _prop_record(p, *, key: str, chunk_version: str | None = None) -> dict:
    """Shared fields for a stored prop — incl. the WS-MS6 event_date temporal pair (None when unstated).

    chunk_version (P7-P3 W2.2): when a caller passes the current corpus-vintage tag, stamp a `chunk_version`
    field so downstream can tell WHICH corpus pass produced the prop. Default None => the field is OMITTED
    (not written as null), so a pre-P3 slice record stays byte-identical and version-absence itself marks a
    pre-vintage prop. One added field here propagates into the driver slice via `**base` in _one() for free."""
    rec = {"date": str(p.document_date), "source": p.source, "source_key": key, "text": p.proposition,
           "event_date": str(p.event_date) if getattr(p, "event_date", None) else None,
           "event_date_precision": getattr(p, "event_date_precision", None)}
    if chunk_version is not None:
        rec["chunk_version"] = chunk_version
    return rec


def current_chunk_version() -> str | None:
    """The corpus-vintage tag to stamp onto props chunked in THIS pass, or None when unavailable.

    Format: `<corpus_fingerprint>-<UTC-date>` (e.g. `c34d5e6f7a8b-20260707`) — the eval corpus_fingerprint()
    12-hex slice+alias identity joined to a UTC calendar date (time.strftime over gmtime). eval is imported
    LAZILY: eval imports evidence at module load, so a top-level import here would cycle. A fingerprint of
    "unknown" (its documented LIST/import-failure sentinel) or an empty string maps to None so callers OMIT
    the stamp rather than write a meaningless vintage; any other exception path also returns None (a version
    tag must never break a build). Deterministic within a UTC day. evidence_batch.retrieve() calls this ONCE
    per pass and threads the result into _prop_record(..., chunk_version=...)."""
    import time
    try:
        from leviathan.graphrag import eval as gev
        fp = gev.corpus_fingerprint()
    except Exception:                                         # noqa: BLE001 — a vintage tag must never break a build
        return None
    if not fp or fp == "unknown":
        return None
    return f"{fp}-{time.strftime('%Y%m%d', time.gmtime())}"


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
    # P9-A: event_date rides along (WS-MS6 stored it; the answer layer's "; event <date>" rendering and
    # Phase-B window derivation both need it). .get() so a prop lacking the field stays None.
    return [{"date": r["date"], "source": r["source"], "source_key": r["source_key"], "text": r["text"],
             "event_date": r.get("event_date"), "event_date_precision": r.get("event_date_precision")}
            for r in recs]


def retrieve(query: str, node: str, *, k: int = 5, asof: str | None = None, near: str | None = None,
             beta: float = 0.25, bedrock=None, records: list[dict] | None = None,
             mode: str = "dense", rerank: bool = False, mmr: float = 0.0,
             same_source: bool = True, fairness: float = 0.30, fetch_k: int = _FETCH_K) -> list[dict]:
    """Top-k props for the query, point-in-time filtered (date <= asof) — leakage-safe. Default
    (mode='dense', rerank=False, mmr=0) is pure cosine + episode-proximity, UNCHANGED. Opt-in retrieval-quality
    knobs (all in-memory; they curate WHICH dated evidence reaches the LLM, never the reasoning):
      mode='hybrid' -> add a BM25 lexical leg fused via RRF (recall on exact tokens like B40/ZL);
      rerank=True   -> a bge cross-encoder re-orders relevance (precision);
      mmr>0         -> MMR final-select for diversity (guards against rerank narrowing the evidence set).
    EVIDENCE_BACKEND=pg routes candidate fetch to pgvector (one filtered SQL round-trip instead of a full-slice
    scan) with the SAME post-fetch pipeline — see pgstore.pg_retrieve. Explicit `records=` always stays local."""
    if records is None and os.environ.get("EVIDENCE_BACKEND") == "pg":
        from leviathan.graphrag import pgstore
        return pgstore.pg_retrieve(query, node, k=k, asof=asof, near=near, beta=beta, mode=mode, rerank=rerank,
                                   mmr=mmr, same_source=same_source, fairness=fairness, fetch_k=fetch_k)
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
        # Rerank only the fused top RERANK_POOL (~5x k): items the dense+lexical fusion ranked below that
        # never reach the final k anyway, and cross-encoder cost is linear in pool size (60-pair pools were
        # ~40% of the July-3 per-answer latency). Recall stays with the wide fusion; precision with the CE.
        cand = cand[:rk.RERANK_POOL]
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
_DRIVER_ALIAS = None                     # dag_driver_id -> slice_name (identity for exact-name matches)


def _driver_raw() -> dict:
    import yaml
    if not _DRIVER_PATH.exists():
        return {}
    return yaml.safe_load(_DRIVER_PATH.read_text(encoding="utf-8")) or {}


def driver_specs() -> dict:
    """The driver-slice map from driver_slices.yaml ({driver: {category, terms, priority?}}), cached."""
    global _DRIVER_CACHE
    if _DRIVER_CACHE is None:
        _DRIVER_CACHE = _driver_raw().get("drivers") or {}
    return _DRIVER_CACHE


def driver_alias() -> dict:
    """Map a causal-DAG driver id -> the evidence slice that carries its dated text (cached).

    Slice NAMES were curated independently of DAG driver ids, so ground() historically read
    drivers/<dag_id> and resolved only the 13 exact-name matches. This inverts the hand-curated
    `dag_alias` block (slice -> [dag ids]) and folds in identity for every slice whose name IS a
    driver id, so slice_for_driver(dag_id) returns the right drivers/<slice>.jsonl path."""
    global _DRIVER_ALIAS
    if _DRIVER_ALIAS is None:
        specs = driver_specs()
        alias = {name: name for name in specs}                 # exact-name matches resolve by identity
        for slice_name, ids in (_driver_raw().get("dag_alias") or {}).items():
            if slice_name not in specs:                        # alias must point at a real slice
                continue
            for did in ids or []:
                alias.setdefault(did, slice_name)              # first owner wins (curated to be unique)
        # Accent-fold registration: an accented DAG id (El_Nino/La_Nina) is byte-disjoint from its ASCII
        # slice name and would resolve to nothing. Fold the alias keys once, then for any DAG id whose
        # folded form is backed, register the accented id -> that slice — so slice_for_driver("El_Nino")
        # resolves without minting an entry per accented id in the YAML. display is imported LAZILY inside
        # the function (verified cycle-safe: display.py imports evidence only lazily at display.py:113) and
        # guarded so a missing/broken display registry never breaks driver resolution.
        folded_backed = {fold(k): v for k, v in alias.items()}
        try:
            from leviathan.graphrag import display as _dp
            for did in _dp.all_driver_ids():
                if did not in alias and fold(did) != did and fold(did) in folded_backed:
                    alias.setdefault(did, folded_backed[fold(did)])
        except Exception:                                      # noqa: BLE001 — display gone -> return alias so far
            pass
        _DRIVER_ALIAS = alias
    return _DRIVER_ALIAS


def _reset() -> None:
    """Null the three plain module-global caches (_DRIVER_CACHE/_DRIVER_MATCHERS/_DRIVER_ALIAS) so the next
    read re-parses driver_slices.yaml — the hermetic-test reset dedupes the hand-written reset sites in the
    suite. Deliberately does NOT touch display.all_driver_ids.cache_clear() (that lives in display, and
    folding it in would force evidence to import display eagerly — the call sites clear it themselves)."""
    global _DRIVER_CACHE, _DRIVER_MATCHERS, _DRIVER_ALIAS
    _DRIVER_CACHE = _DRIVER_MATCHERS = _DRIVER_ALIAS = None


def slice_for_driver(dag_id: str) -> Optional[str]:
    """The evidence-slice name backing a DAG driver id, or None if the driver has no text slice."""
    return driver_alias().get(dag_id)


def backed_dag_ids() -> set:
    """DAG driver ids that resolve to an evidence slice (exact-name + curated aliases)."""
    return set(driver_alias().keys())


def backed_slice_names() -> set:
    """The INVERSE of backed_dag_ids(): slice names that >=1 backing DAG id resolves to — every value in
    driver_alias() (the identity self-maps for exact-name slices + the curated dag_alias targets + accent-
    folded ids). A driver slice ABSENT from this set is a write-time orphan: no DAG id (exact-name or aliased)
    reaches it, so props written there are unreachable by slice_for_driver()/ground(). Pure config read
    (driver_slices.yaml, cached), non-circular — deliberately does NOT touch display.all_driver_ids()."""
    return set(driver_alias().values())


def check_driver_slices() -> list[str]:
    """Darkness lint over the driver-slice wiring (Phase 7 P2 W2) — the resolver behind config_check's
    ('driver_slices', ...) tuple. Returns one message per HARD problem, empty == clean. Two hard checks over
    the parent-inclusive causal driver set (display.all_driver_ids()):

      (a) DARKNESS   -- every DAG id must either resolve to a slice (backed_dag_ids: identity + dag_alias +
                        accent-fold) OR carry a `waivers:` entry (silver-only crosses / honestly-deferred
                        gaps). An id that is neither is DARK and unaccounted -> error. The exit gate is
                        n_dark <= |waivers|: this makes 'dark but unwaivered' the failing class.
      (b) DUPLICATE-OWNERSHIP -- an id on 2+ DISTINCT slices' RHS is a hard error (a real double-owner
                        regression). An RHS entry whose id EQUALS its own slice name (export_ban, frost) is a
                        benign self-alias — driver_alias()'s setdefault makes it a no-op identity entry, not a
                        second owner — so it is skipped, never flagged.

    The topical-token quality heuristic is deliberately NOT a hard error — see driver_slice_alias_warnings().
    A dag_alias remap is authored under adversarial human review (the curation pass), and a legitimate concept
    alias routinely shares no literal underscore token with its slice ('section301_tariffs' -> 'tariff',
    'port_closure' -> 'freight', 'RenovaBio' -> 'biodiesel_mandate'); making that a hard failure taxes ~1-in-5
    good aliases (P2 plan risk #5). Darkness and double-ownership are the load-bearing invariants; topical
    drift is an advisory a human clears.

    display is imported LAZILY (cycle-safe; guarded) — a clean checkout with no private configs has no causal
    dir, so all_driver_ids() is empty and the lint passes vacuously (this is a pre-ship CLI check, not a CI
    gate; D3 in the parent plan)."""
    from leviathan.graphrag import display as dp
    errs: list[str] = []
    backed = backed_dag_ids()
    waivers = _driver_raw().get("waivers") or {}
    dag_alias = _driver_raw().get("dag_alias") or {}

    # (a) darkness: an id must resolve OR be waived
    for did in sorted(dp.all_driver_ids()):
        if did not in backed and did not in waivers:
            errs.append(f"dark id {did}: no slice, no waiver")

    # (b) duplicate-ownership: an id on 2+ DISTINCT slices' RHS. A RHS==own-slice-name entry is a benign
    #     self-alias (setdefault no-op), NOT an owner, so it is excluded from the owner count.
    owners: dict[str, set[str]] = {}
    for slice_name, ids in dag_alias.items():
        for did in ids or []:
            if did == slice_name:                             # self-alias is not an ownership claim
                continue
            owners.setdefault(did, set()).add(slice_name)
    for did, slices in sorted(owners.items()):
        if len(slices) >= 2:
            errs.append(f"duplicate id {did}: routed to {sorted(slices)}")

    return errs


def driver_slice_alias_warnings() -> list[str]:
    """ADVISORY (non-fatal) topical-token heuristic over dag_alias: each RHS id should share an accent-folded
    underscore token with its target slice (name tokens PRIMARY; the slice's `terms` phrases widen the set).
    Zero overlap flags the urea->area fuzzy class — but ALSO legitimate concept aliases with no shared literal
    token, so a human reviews the list rather than the build failing on it. Empty == every alias shares a token."""
    warns: list[str] = []
    specs = driver_specs()
    dag_alias = _driver_raw().get("dag_alias") or {}
    for slice_name, ids in dag_alias.items():
        if slice_name not in specs:                            # RHS on a non-existent slice is dead config,
            continue                                           # not this heuristic's concern
        slice_tokens = {fold(w.lower()) for w in slice_name.split("_") if w}
        for phrase in (specs[slice_name].get("terms") or []):
            slice_tokens |= {fold(w.lower()) for w in str(phrase).split() if w}
        for did in ids or []:
            if did == slice_name:                             # benign self-alias, skip
                continue
            id_tokens = {fold(t.lower()) for t in did.split("_") if t}
            if not (id_tokens & slice_tokens):
                warns.append(f"alias {did} -> {slice_name}: no shared topical token (review)")
    return warns


# Bare tokens that are NOT commodity head-words: a node's matcher legitimately fails to fire on these and it
# is NOT a vocabulary gap. Exchange grade codes (the 'wheat' head form covers the commodity), varietal/colour/
# origin qualifiers (never a tradeable commodity on their own), and generic co-product/form words that another
# surface form already covers OR that are exactly the bare-generic the urea->area over-fire law forbids adding.
_BARE_NAME_BENIGN = frozenset({
    "hrs", "hrw", "srw",                                      # exchange grade codes -> 'wheat' covers it
    "white", "yellow", "raw", "french",                      # colour/origin qualifiers, not commodities alone
    "oil", "meal", "juice", "soybean",                       # generic co-product/form words another form covers
})


def bare_name_warnings() -> list[str]:
    """ADVISORY (non-fatal) bare-name sweep over all_nodes(): a commodity node whose OWN matcher
    (build_matcher(match_forms(node))) fails to fire on its bare HEAD-commodity token has a vocabulary gap —
    the corpus names the commodity generically ('coffee', 'sugar', 'palm') and the node never catches it (the
    C1 coffee-bug class: 'arabica coffee' the spaced id never fires on bare 'coffee'). The fix is one line in
    evidence_windows.yaml:extra_terms[node].

    Only HEAD-commodity tokens are flagged. Benign classes are suppressed (see _BARE_NAME_BENIGN): grade codes
    (hrs/hrw/srw), colour/origin qualifiers (white/yellow/raw/french) and generic co-product/form words
    (oil/meal/juice/soybean) — each is either already covered by another surface form or is exactly the
    bare-generic the urea->area over-fire law rejects. Empty == every node fires on its own head word.

    Companion to driver_slice_alias_warnings(): both are non-fatal advisories surfaced by config_check.main so
    this vocabulary-gap class is caught by lint, not by a billed shadow rebuild. Pure config read (all_nodes()
    + the per-node match_forms + an in-memory matcher), no S3/network."""
    warns: list[str] = []
    for node in all_nodes():
        matcher = hv.build_matcher(match_forms(node))
        for tok in node.split("_"):
            if tok and tok not in _BARE_NAME_BENIGN and not matcher.search(tok):
                warns.append(f"node {node}: bare head-commodity word {tok!r} does not fire on its own "
                             f"matcher -- add it to evidence_windows.yaml:extra_terms[{node}]")
    return warns


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
                        max_per: int = 4000, warnings: list | None = None) -> int:
    """Embed + write the accumulated driver props to evidence/drivers/<driver>.jsonl. Dedups the re-chunk
    artifact (same prop harvested from the same doc under multiple commodity builds) by (source_key, text),
    KEEPING cross-source / cross-date instances (the persistence + corroboration signal). Returns props written.

    W1.1 write-time orphan guard (P7-P3): before writing, invert backed_dag_ids()/driver_alias() once
    (backed_slice_names() — a cached, non-circular config read, NO per-slice S3 LIST) into the set of slice
    names >=1 DAG id reaches. A sink slice OUTSIDE that set is a stranded write — no DAG id resolves to it, so
    its props would be invisible to slice_for_driver(). The guard RECORDS it (an ASCII WARN line to stdout +
    an append to the optional `warnings` collector) but NEVER refuses: a legitimate E1b flow authors a slice
    before its alias lands, and the doctrine keeps pure-driver props — hard-refusing would clobber a build in
    progress. Pass `warnings=[]` to surface the orphan list to a caller/manifest; write behavior is unchanged."""
    backend = backend or DEFAULT_BACKEND
    backed = backed_slice_names()                            # slice names a DAG id reaches (computed once, cached)
    total = 0
    for driver, recs in driver_sink.items():
        if driver not in backed:                            # stranded-at-write: soft WARN, still written (W1.1)
            safe = str(driver).encode("ascii", "backslashreplace").decode("ascii")   # cp1252-safe stdout
            msg = (f"WARN write_driver_slices: driver slice '{safe}' has no backing DAG id "
                   f"(orphan -- no exact-name/alias resolves to it); writing anyway")
            print(msg)
            if warnings is not None:
                warnings.append(msg)
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
