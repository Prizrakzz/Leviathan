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
import threading
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


def _evid_write(node: str, text: str | bytes) -> None:
    """Write one slice object. Accepts a str OR the utf-8 bytes of one.

    The bytes form is the guarded write path (write_guard.commit_write encodes each payload exactly once and
    hands the SAME bytes object here and to the manifest's after_bytes). Re-encoding it would put a second
    full-size copy of the body alongside the first -- on the 1.03 GB `soybeans` slice that is what OOM-killed
    the 2026-08-02 routing pass. A str is still accepted and encoded here, once, for the direct callers
    (restamp, the doc-cache writer) whose bodies are small."""
    blob = text if isinstance(text, (bytes, bytearray)) else text.encode("utf-8")
    base = _evid_s3()
    if base:
        import boto3
        bkt, key = _parse_s3(base.rstrip("/") + f"/{node}.jsonl")
        boto3.client("s3").put_object(Bucket=bkt, Key=key, Body=blob)
    else:
        p = _EVID_DIR / f"{node}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)            # node may be "drivers/<x>" (a subdir)
        # write_BYTES, not write_text (F6) -- and that is why this function encodes ONCE, up front, and both
        # branches write the SAME `blob`. Path.write_text translates "\n" -> "\r\n" on Windows, so a local
        # slice was ALWAYS larger than the manifest's recorded after_bytes by exactly its newline count
        # (measured: manifest 3201, on disk 3220, delta 19 = the 19 newlines). resolve_prior's stale-mirror
        # fence compares those two numbers for equality, so on the laptop the exact branch NEVER matched:
        # every slice fell to the size estimate, every span went None, and the manifest stamped "-- prior
        # manifest STALE (bytes moved since)" -- telling an operator a later UNGUARDED write invalidated the
        # baseline when in fact nothing had written. The S3 branch already encodes to utf-8 before the PUT,
        # so it was never affected, which is exactly why this hid from cloud testing and bit every dev run.
        # It also removes a silent CRLF/LF difference between the local and S3 stores generally. A bytes
        # argument NEVER goes near write_text either: there is exactly one sink here, and it is bytes.
        p.write_bytes(blob)


# write_guard.commit_write hands a marked write_fn the pre-encoded bytes instead of the str, so the guarded
# path encodes each slice body exactly once (write_guard.BYTES_WRITER_ATTR). Set as a plain attribute rather
# than via write_guard.bytes_writer so this module keeps its lazy, cycle-free import of write_guard; the
# wiring is pinned by test_evidence.test_evid_write_is_marked_as_a_bytes_writer.
_evid_write.accepts_bytes = True


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


_bge_load_lock = threading.Lock()


def _bge_local(texts: list[str]) -> list[list[float]]:
    """Double-checked locking on the lazy model load: N eval workers racing the FIRST
    SentenceTransformer(...) construction half-materialize it off meta tensors ("Cannot copy out of
    meta tensor") and wedge EVERY subsequent embed -- the 2026-07-12 all-rows eval crash. Serving
    never hit this only because server.py pre-warms single-threaded before traffic."""
    global _bge
    if _bge is None:
        with _bge_load_lock:
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
# "maize" (not "corn") keys sagis_cec so SA white/yellow maize nodes gain the committee narrative
# while US corn_cbot (token "corn") does not -- the CEC covers South Africa only (Track B, 2026-07-19).
_SPECIALIZED_SOURCES = {
    "coffee": ("fnc", "usda_fas_coffee_wmt"),
    "palm": ("mpoc", "mpob"),
    "cocoa": ("icco_qbcs_summary", "icco_ewg_stocks"),
    "maize": ("sagis_cec",),
}
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
    from leviathan.graphrag import batch_extract as bx
    from leviathan.graphrag.corpus_recon import BUCKET, TEXT_PREFIX, _source_of
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
                provider: str = "bedrock", anthropic_client=None,
                manifest=None, allow_churn: float | None = None) -> int:
    """Sample -> chunk -> keep on-topic props -> embed -> write configs/graphrag/evidence/<node>.jsonl. Billed.

    workers>1 parallelizes the per-doc Bedrock-Haiku chunking over thread-local S3 clients — the cloud-build
    path (build_evidence_task on Fargate); workers=1 is the sequential laptop path. max_props=None lifts the cap.
    driver_sink (WS-MS6): when given, every chunked prop is ALSO routed to driver slices (driver -> [records])
    in-place — the cross-cutting cascade props (B40, freight, FX, El Nino) harvested FREE from the same pass.

    F3 — THIS IS THE LIVE PRODUCTION COMMODITY WRITE, and until this fix it was the one wholesale seam with
    no guard at all. `jobs/batch/build_evidence_task.py` calls it per node against jobdef
    `leviathan-dev-evidence-build` on the LIVE prefix, writing the same 24 top-level slices
    `_commodity_guarded_write` protects — so the wave shipped a store where one path refused a collapse and
    another rewrote the same object silently. It now goes through write_guard, and its `records[:max_props]`
    cut is deterministic and recorded (see the G5a note at the cut). `manifest` / `allow_churn` are
    keyword-only with defaults, so every existing call site is unchanged."""
    from leviathan.graphrag import chunking as ch
    from leviathan.graphrag.corpus_recon import BUCKET, _source_of
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
    # F3 -- the truncation gets the G5a treatment. `records[:max_props]` was an unrecorded cut over a list
    # whose order is whatever `sample_keys` + the per-doc chunker produced -- the exact defect G5a closed for
    # the driver side and nothing more. Order deterministically (most recent `date` first, ties by
    # source_key/id), THEN cut, THEN say so. The ordering is applied whether or not the cap bites, so the
    # slice body is byte-deterministic for a given record set: that is what makes the manifest's after_bytes
    # a usable fence rather than a number that churns on re-derivation. Like every other G5a effect, the
    # code lands in Wave G and the bytes only move at the ONE Wave-R rebuild.
    truncated_n = 0
    records = _truncation_order(records)                     # ALWAYS, cap or no cap (see below)
    if max_props and len(records) > max_props:
        truncated_n = len(records) - max_props
        records = records[:max_props]
        msg = (f"WARN build_index: node '{node}' TRUNCATED {truncated_n} props at max_props={max_props} "
               f"(kept the {max_props} most recent by date, ties by source_key/id)")
        print(msg)
        if manifest is not None:
            manifest.warnings.append(msg)
    if not records:
        # The empty-node SKIP, matching evidence_batch's commodity guard exactly: a node that routed nothing
        # keeps its prior file rather than being clobbered with an empty object. Refusing a whole multi-node
        # build over one empty node would be a regression, not a guard.
        msg = f"build_index: node '{node}' routed 0 props -- prior slice left intact, NOT rewritten empty"
        print(f"  {msg}")
        if manifest is not None:
            manifest.warnings.append(msg)
        return 0

    def _payload() -> str:                                   # embed LAZILY: a refused pass pays no embed
        for r, v in zip(records, embed([r["text"] for r in records], backend=backend, bedrock=bedrock)):
            r["vector"], r["backend"] = v, backend   # stamp backend so retrieve() embeds queries the same way
        return "\n".join(json.dumps(r) for r in records)

    # F3 -- the LIVE cloud commodity write goes through the guard. This is the seam
    # jobs/batch/build_evidence_task.py drives against jobdef leviathan-dev-evidence-build: the same 24
    # top-level slices _commodity_guarded_write protects, previously with no churn ratio, no span tuple, no
    # empty guard and no manifest line. One slice per call is fine -- the layer line then measures this node
    # against the store's other 23, which is what a per-node build actually is.
    from leviathan.graphrag import write_guard as wg
    return wg.guarded_write("commodity", "", {node: _payload}, records={node: records}, manifest=manifest,
                            allow_churn=allow_churn, write_fn=_evid_write, node_of=lambda n: n,
                            truncated={node: truncated_n})


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


def _out(recs: list[dict], scores: dict | None = None) -> list[dict]:
    # P9-A: event_date rides along (WS-MS6 stored it; the answer layer's "; event <date>" rendering and
    # Phase-B window derivation both need it). .get() so a prop lacking the field stays None.
    # D-DV-2: `score` -- the retrieval relevance this row was RANKED on -- crosses the retrieve boundary
    # too. Purely ADDITIVE: it filters nothing here, and every consumer (_ev_block, citations.unify,
    # verify) reads named keys, so an extra one is inert. `scores` is keyed by id() of the SAME record
    # objects, so a row the ranker reordered (mmr_select) still carries its own value.
    return [{"date": r["date"], "source": r["source"], "source_key": r["source_key"], "text": r["text"],
             "event_date": r.get("event_date"), "event_date_precision": r.get("event_date_precision"),
             "score": (scores or {}).get(id(r))}
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
        if rerank:
            # counted in the walk's coalescer hint but never scoring — retract, exactly as
            # pgstore.pg_retrieve does at its own empty-candidate return
            from leviathan.graphrag import rankers as rk
            rk.rerank_unexpect()
        return []
    qv = embed([query], backend=recs[0].get("backend"), bedrock=bedrock)[0]   # same space as the index

    def _dense(r):
        return _cosine(qv, r["vector"]) + (beta * _proximity(r["date"], near) if near else 0.0)

    dense_ranked = sorted(recs, key=_dense, reverse=True)
    if mode == "dense" and not rerank and mmr <= 0:                # fast path: same rows, same order (D-DV-2
        top = dense_ranked[:k]                                    # adds the additive `score` key, nothing else)
        return _out(top, {id(r): _dense(r) for r in top})

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
    return _out(top, {id(r): s for r, s in zip(cand, relevance)})


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
    folded ids). Pure config read (driver_slices.yaml, cached), non-circular — deliberately does NOT touch
    display.all_driver_ids().

    G7.1 CORRECTION -- this set is NOT a reachability test and must not be used as one. driver_alias() seeds
    `alias = {name: name for name in specs}` (:612, "exact-name matches resolve by identity"), so EVERY
    configured slice name is a value by construction: measured at HEAD, set(driver_specs()) -
    backed_slice_names() == [] over 109 slices. The W1.1 write-time orphan guard tested against this set and
    was therefore structurally unfireable -- it read as coverage in every review and could never trigger for
    any slice, because driver_sink's keys come only from driver_matchers() built off driver_specs(). The
    write guard now tests dag_backed_slice_names() instead. Kept because it is still the honest answer to
    "which slice names appear in the alias map" (e1_census inverts the map itself)."""
    return set(driver_alias().values())


def dag_backed_slice_names() -> set:
    """Slice names a REAL causal-DAG driver id reaches — driver_alias() inverted and INTERSECTED with
    display.all_driver_ids(), which is what makes it a reachability test rather than an identity restatement
    (G7.1). This is the set planner._fill can actually reach: an id must be in all_driver_ids() to be in
    backed_dag_ids() at planner.py:320, which gates the n.episodes assignment at :334.

    The intersection is exactly the one e1_census.slice_census already performs (`if dag_id in real`) for its
    n_dag_ids column — the two now agree by construction. display is imported LAZILY and guarded, matching
    driver_alias()/check_driver_slices(): a clean checkout with no causal dir has an empty all_driver_ids(),
    and rather than declaring every slice dark we fall back to backed_slice_names() so a config-less tree
    keeps the old vacuous-pass behaviour instead of emitting 109 spurious orphan warnings."""
    alias = driver_alias()
    try:
        from leviathan.graphrag import display as _dp
        real = set(_dp.all_driver_ids())
    except Exception:                                          # noqa: BLE001 — display gone
        real = set()
    if not real:                                               # no causal dir -> vacuous, not "all dark"
        return set(alias.values())
    return {slice_name for did, slice_name in alias.items() if did in real}


# G7.2 -- the 29 configured driver slices no REAL DAG id reaches, so planner._fill can never reach them and
# no episode line can ever be injected for them on any contract. MEASURED at plan time over 109 configured
# specs against display.all_driver_ids() (361 ids). Pinned here as a standing census number so nobody
# re-derives a subset by hand again -- the deck author had already measured five of them
# (suez/panama/baltic/mississippi/vessel_lineups) at eval_queries_playbooks_v1.yaml:1130-1140.
# Drift from this pin is a lint finding, not a silent fact: check_driver_slices() hard-fails on a NEW
# read-dark slice and advises when a pinned one has since been wired up.
READ_DARK_SLICES_PIN = frozenset({
    "baltic_dry_freight", "barley_yellow_dwarf_virus", "cattle_cycle_herd_size", "cattle_on_feed", "dap",
    "diesel", "egypt_gasc_tenders", "global_rice_export_policy", "idr_fx", "index_roll_flows",
    "indian_ocean_dipole", "inr_fx", "madden_julian_oscillation", "metals", "mississippi_river_levels",
    "myr_fx", "natural_rubber", "panama_canal_constraints", "potash", "real_yields_rates", "subsidy",
    "suez_redsea_disruption", "sunflower_oil_balance", "sustainable_aviation_fuel", "urea",
    "veg_oil_substitution_spreads", "vessel_lineups_export_basis", "west_africa_weather", "wheat_blast",
})


# G7.4 -- the 8 configured driver slices that were NEVER WRITTEN to S3 at all (109 configured specs, 101
# objects under drivers/). MEASURED at plan time by joining yaml.safe_load(driver_slices.yaml) against one
# LIST of the drivers/ prefix. Pinned here for the same reason READ_DARK_SLICES_PIN is: the handoff's "101
# slices" is the S3 FILE count, not the config count, and the 8-slice gap was a hand-derived number in a
# document with nothing in code holding it. This is a DIFFERENT set from READ_DARK_SLICES_PIN, which is
# read-darkness (no real DAG id reaches it); a slice can be write-dark, read-dark, both or neither. Overlap
# as pinned: barley_yellow_dwarf_virus, index_roll_flows, madden_julian_oscillation,
# veg_oil_substitution_spreads are in both.
#
# ADVISORY ONLY, and that is load-bearing (F12): write-darkness is STORE state, not config state, and a
# config lint that cannot see the store must never fail on it. The only thing checkable without S3 is that
# every pinned name still EXISTS as a configured spec -- a pinned name that has since been deleted from the
# config makes the pin stale, and a stale census pin is how "101 vs 109" became folklore in the first place.
NEVER_WRITTEN_SLICES_PIN = frozenset({
    "barley_yellow_dwarf_virus", "corn_southern_rust", "corn_tar_spot", "index_roll_flows",
    "india_import_duty", "madden_julian_oscillation", "managed_money_positioning",
    "veg_oil_substitution_spreads",
})


def never_written_slice_warnings() -> list[str]:
    """ADVISORY (non-fatal) G7.4 census pin: the 8 configured slices that have never been written to S3.

    Two lines, both cheap and both config-only:
      * the standing census number itself, so the 109-specs-vs-101-files gap is stated in code rather than
        re-derived by hand from a plan document;
      * a staleness check -- a pinned name that is no longer a configured spec means the pin has drifted
        and must be re-measured against a LIST of drivers/.

    It deliberately does NOT check the store. Verifying write-darkness needs one list_objects_v2 of
    <EVIDENCE_S3>/drivers/, which is exactly what e1_census already does on its own schedule; a $0 config
    lint that reaches for the network to answer a census question is how a lint becomes a thing people
    disable. Empty on a clean checkout with no private vocabulary (vacuous)."""
    specs = driver_specs()
    if not specs:
        return []
    out = [f"never-written census (G7.4): {len(NEVER_WRITTEN_SLICES_PIN)} of {len(specs)} configured slices "
           f"have no object under drivers/ at all -- the handoff's \"101 slices\" is the S3 FILE count, not "
           f"the config count: " + ", ".join(sorted(NEVER_WRITTEN_SLICES_PIN))]
    gone = sorted(NEVER_WRITTEN_SLICES_PIN - set(specs))
    if gone:
        out.append(f"never-written pin STALE: {', '.join(gone)} no longer configured -- re-measure the pin "
                   f"against one LIST of <EVIDENCE_S3>/drivers/ and shrink it (advisory)")
    return out


def read_dark_slices() -> set:
    """Configured driver slices that NO real DAG id resolves to — computed live, the complement of
    dag_backed_slice_names() over driver_specs(). Empty on a clean checkout with no causal dir (vacuous)."""
    backed = dag_backed_slice_names()
    return {name for name in driver_specs() if name not in backed}


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
      (c) READ-DARK DRIFT (G7.2) -- a configured slice no REAL DAG id reaches can never have an episode line
                        injected (planner.py:320/:334). 29 such slices were MEASURED and pinned in
                        READ_DARK_SLICES_PIN. A slice that is read-dark and is neither pinned nor named by a
                        `waivers:` entry is a NEW unaccounted gap -> hard error. A pinned slice that has
                        since been wired up is an advisory line telling you to shrink the pin (an
                        improvement must not fail a build). Vacuous when there is no causal dir.
      (d) MANIFEST MIRROR (G2 / D-EI-1) -- driver_slices.yaml is gitignored whole-directory
                        (.gitignore:49) with an EMPTY git log, so a term edit leaves no reviewable diff
                        anywhere. The tracked mirror configs/graphrag/driver_slices_manifest.yaml carries a
                        per-slice sha256 of the sorted term list (never a term), and a drift between the
                        live config and the mirror is a LINT-TIME failure instead of a post-rebuild
                        discovery. This is the only guard in the wave that fires BEFORE any compute is spent.

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

    # (c) read-dark drift against the pinned census (G7.2). Only meaningful when a causal DAG exists.
    if dp.all_driver_ids():
        dark = read_dark_slices()
        for name in sorted(dark - READ_DARK_SLICES_PIN - set(waivers)):
            errs.append(f"read-dark slice {name}: no REAL DAG id resolves to it, so planner._fill can never "
                        f"reach it and no episode line can ever be injected -- and it is neither in "
                        f"READ_DARK_SLICES_PIN nor named by a waivers: entry. Wire it to a DAG id, or "
                        f"waive it as an honestly-deferred gap, or add it to the pin.")
        for name in sorted(READ_DARK_SLICES_PIN - dark):
            if name in driver_specs():                        # a pinned slice that is now reachable: good news,
                print(f"NOTE read-dark pin: {name} now resolves from a real DAG id -- shrink "   # never a failure
                      f"READ_DARK_SLICES_PIN (advisory)")

    # (d) manifest mirror (G2 / D-EI-1) -- delegated to the generator so `--check` and the lint agree.
    from leviathan.graphrag import driver_slices_manifest as dsm
    errs += dsm.check_manifest()

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


def term_collision_warnings() -> list[str]:
    """ADVISORY (non-fatal) CROSS-FIRE detector over the driver term lists (G8) — the class that had no
    standing detector at all.

    The shape: one slice's term is a proper substring of another slice's term ON A WORD BOUNDARY, so every
    prop the longer term claims is ALSO claimed by the shorter one. "leaf rust" inside "coffee leaf rust"
    is the instance Wave R repairs; "ferrugem" inside "ferrugem asiatica" is the same shape in Portuguese.
    driver_slices_for() is multi-label (`[d for d, m in driver_matchers().items() if m.search(text)]`), so a
    collision is not an error by itself — it is a routing fact somebody chose or did not notice.

    Why check_driver_slices' two hard checks cannot see this: (a) darkness and (b) duplicate-ownership both
    read the dag_alias ID map, and a term collision lives in the TERM lists, which that map never touches.
    G2's manifest lint hashes term SETS, so it detects that an edit HAPPENED, never that two slices claim the
    same prop.

    Deliberately STATIC and O(terms^2) over ~638 terms — pure config arithmetic, milliseconds, zero S3. It
    would have caught both the R1 and the R2 defects before either was authored. It REPORTS ONLY: the term
    deletion itself is a routing change and therefore a Wave-R act, never a lint's to make. Self-pairs and
    same-slice pairs are skipped; comparison is over ex._normalize'd forms, the same normalization
    harvest._Matcher applies, so an accent or case difference never hides a collision."""
    import re as _re
    specs = driver_specs()
    norm: list[tuple[str, str, str]] = []                      # (normalized term, original term, slice)
    for name in sorted(specs):
        for t in (specs[name].get("terms") or []):
            nf = ex._normalize(str(t))
            if nf and len(nf) > 1:
                norm.append((nf, str(t), name))
    warns: list[str] = []
    for short_nf, short_t, short_s in norm:
        rx = _re.compile(r"\b" + _re.escape(short_nf) + r"\b")
        for long_nf, long_t, long_s in norm:
            if long_s == short_s or long_nf == short_nf or len(long_nf) <= len(short_nf):
                continue
            if rx.search(long_nf):
                warns.append(f"cross-fire {short_s}:{short_t!r} is a word-boundary substring of "
                             f"{long_s}:{long_t!r} -- every prop {long_s} claims via that term is ALSO "
                             f"claimed by {short_s} (review: intended multi-label, or a silent collision?)")
    return sorted(warns)


def read_dark_slice_warnings() -> list[str]:
    """ADVISORY (non-fatal) roll-up of the G7.2 read-dark census: how many configured slices no real DAG id
    reaches, and which of those are explicitly WAIVED as honestly-deferred gaps versus merely pinned.

    The distinction is the whole point of D-EI-4's ratified disposition for `indian_ocean_dipole`: a waiver
    is a curator saying "known, deferred, on purpose"; the pin is only a measurement saying "this is how the
    wiring stands". Note honestly what a waiver does and does not do here — `waivers:` is keyed by DAG ID and
    the hard darkness check at (a) iterates display.all_driver_ids(), so an entry naming a slice that is not
    a DAG id (which is exactly the IOD case) is inert in THAT check. It is load-bearing in check (c) and it
    is what this advisory reads, and it becomes load-bearing in (a) the moment the id is ever registered."""
    dark = read_dark_slices()
    if not dark:
        return []
    waivers = _driver_raw().get("waivers") or {}
    waived = sorted(n for n in dark if n in waivers)
    unwaived = sorted(n for n in dark if n not in waivers)
    out = [f"read-dark census: {len(dark)} of {len(driver_specs())} configured slices have NO real DAG id "
           f"and can never render an episode line (pin={len(READ_DARK_SLICES_PIN)})"]
    if waived:
        out.append("read-dark WAIVED (honestly-deferred gaps): " + ", ".join(waived))
    if unwaived:
        out.append("read-dark unwaived (measured, pinned): " + ", ".join(unwaived))
    return out


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


def slice_cap(driver: str, default: int) -> int | None:
    """The prop cap for one driver slice: its declared `max_props` (G5c / D-EI-3) else the pass default.

    D-EI-3 ratified: KEEP 4,000 as the default and declare it explicitly, per slice, for the four slices that
    are actually at the cap (`tariff`, `feed_grain_substitution`, `textile_apparel_demand`,
    `wasde_stocks_to_use`) — because a cap nobody declared and nobody printed is how 5,809 rows swapped
    behind four frozen `4000` counts. Raising the cap was priced and rejected: at 20,000 those four slices
    alone go to ~465 MB each and roughly double the 1.361 GB driver layer. `max_props: null` in a spec means
    UNCAPPED and is honoured. The spec dict already carried {category, priority, terms}, so this is a new
    optional field, not a schema change."""
    spec = driver_specs().get(driver) or {}
    if "max_props" in spec:
        raw = spec.get("max_props")
        return None if raw is None else int(raw)
    return default


def _truncation_order(recs: list[dict]) -> list[dict]:
    """G5a — the deterministic selection order applied BEFORE the cap. Most recent `date` first; ties broken
    by (source_key, id) ascending. Two stable sorts, so the result is a total order with no dependence on
    dict/set iteration order.

    WHY this is not cosmetic. `rebuild_slices` iterates `for h in _cached_hashes()` and `_cached_hashes()`
    returns a SET of md5 hex strings; PYTHONHASHSEED is set nowhere in docker/, jobs/, src/, infra/, scripts/
    or in the production jobdef environment, so str hashing is per-process randomized and the surviving
    `max_per` props differed on EVERY run. Measured at the 2026-07-20 promote: 5,809 of the 16,000 rows in
    the four capped slices (36%) were swapped for a different 5,809 with both counts frozen at exactly 4000 —
    `feed_grain_substitution` replaced 2,127, `tariff` 1,971, `wasde_stocks_to_use` 1,454,
    `textile_apparel_demand` 257. No delta guard built on counts or bytes can see that; only determinism
    closes it. Sorting by date also repairs the meaningless spans those slices carried, because the survivors
    become the N most recent rather than an arbitrary sample.

    SEQUENCING (section 3.2 of the wave plan, and it is a law, not a preference): this changes WHICH props
    survive in the four capped slices, which is a population change, which stales timeline/episodes.json.
    The CODE lands in Wave G; its EFFECT materializes at the ONE Wave-R rebuild. Nothing here triggers a
    rebuild, and until that rebuild runs, no deck pin grounded on the four capped slices is reproducible."""
    out = sorted(recs, key=lambda r: (str(r.get("source_key") or ""), str(r.get("id") or "")))
    out.sort(key=lambda r: str(r.get("date") or ""), reverse=True)
    return out


def plan_driver_slices(driver_sink: dict, *, backend: str | None = None, bedrock=None,
                       max_per: int = 4000, warnings: list | None = None,
                       manifest=None, allow_churn: float | None = None):
    """Everything write_driver_slices does EXCEPT the write: dedup, deterministic order, per-slice cap,
    prior census, guard verdict. Returns a write_guard.WritePlan.

    F1: a multi-layer caller (_route_and_write, rebuild_slices, build_evidence_task) must evaluate EVERY
    layer before committing ANY of them, or a driver refusal lands after the 11.1 GB commodity layer has
    already been rewritten. Those callers plan through here; single-layer callers keep using
    write_driver_slices, which is this plus raise + commit."""
    from leviathan.graphrag import write_guard as wg
    backend = backend or DEFAULT_BACKEND
    backed = dag_backed_slice_names()                        # G7.1: reachability, not identity
    records: dict[str, list] = {}
    truncated: dict[str, int] = {}
    for driver, recs in driver_sink.items():
        safe = str(driver).encode("ascii", "backslashreplace").decode("ascii")       # cp1252-safe stdout
        if driver not in backed:                            # stranded-at-write: soft WARN, still written (W1.1)
            msg = (f"WARN write_driver_slices: driver slice '{safe}' has no backing DAG id "
                   f"(orphan -- no REAL causal driver id resolves to it); writing anyway")
            print(msg)
            if warnings is not None:
                warnings.append(msg)
            if manifest is not None:
                manifest.warnings.append(msg)
        seen, uniq = set(), []
        for r in recs:
            k = (r.get("source_key"), r["text"])
            if k in seen:
                continue
            seen.add(k)
            uniq.append(r)
        uniq = _truncation_order(uniq)                       # G5a: deterministic BEFORE the cap
        cap = slice_cap(driver, max_per)
        if cap is not None and len(uniq) > cap:
            dropped = len(uniq) - cap                        # G5b: the truncation is never silent again
            uniq = uniq[:cap]
            truncated[driver] = dropped
            msg = (f"WARN write_driver_slices: slice '{safe}' TRUNCATED {dropped} props at max_props={cap} "
                   f"(kept the {cap} most recent by date, ties by source_key/id)")
            print(msg)
            if warnings is not None:
                warnings.append(msg)
            if manifest is not None:
                manifest.warnings.append(msg)
        records[driver] = uniq

    def _payload(name: str):
        def _mk() -> str:                                    # embed LAZILY: a refused pass pays no embed
            recs = records[name]
            for r, v in zip(recs, embed([r["text"] for r in recs], backend=backend, bedrock=bedrock)):
                r["vector"], r["backend"] = v, backend
            return "\n".join(json.dumps(r) for r in recs)
        return _mk

    return wg.plan_write("drivers", "drivers/", {n: _payload(n) for n in records}, records=records,
                         manifest=manifest, allow_churn=allow_churn, write_fn=_evid_write,
                         node_of=lambda n: f"drivers/{n}", truncated=truncated, warnings=warnings)


def write_driver_slices(driver_sink: dict, *, backend: str | None = None, bedrock=None,
                        max_per: int = 4000, warnings: list | None = None,
                        manifest=None, allow_churn: float | None = None) -> int:
    """Embed + write the accumulated driver props to evidence/drivers/<driver>.jsonl. Dedups the re-chunk
    artifact (same prop harvested from the same doc under multiple commodity builds) by (source_key, text),
    KEEPING cross-source / cross-date instances (the persistence + corroboration signal). Returns props written.

    W1.1 write-time orphan guard (P7-P3), REPAIRED in G7.1: the predicate now tests dag_backed_slice_names()
    — driver_alias() inverted and intersected with the REAL causal driver ids — instead of
    backed_slice_names(), which is identity-seeded and therefore contains every configured slice by
    construction, which is why the guard could never fire for anything. It still RECORDS (an ASCII WARN line
    + an append to the optional `warnings` collector) and still NEVER refuses: a legitimate E1b flow authors
    a slice before its alias lands, and hard-refusing would clobber a build in progress. Expect it to be
    LOUD now — 29 configured slices are read-dark (READ_DARK_SLICES_PIN); that is the true state, and a
    guard that says so is worth more than one that reads green because it cannot speak.

    G1b/G1c/G5b, the wholesale-write guard (this is C2, one of the FIVE silent seams): the pass is
    now computed IN FULL — dedup, deterministic order, per-slice cap — before ANY byte is written, the
    before/after census is straddled across the single write, and a population drop past
    write_guard.SLICE_DROP_REFUSE refuses the whole pass with nothing written and nothing embedded. Delta,
    truncation counts and span endpoints ride the `warnings` collector and the run manifest; the `int` return
    and all three call sites are unchanged.

    THIS ENTRY POINT IS SINGLE-LAYER (F1). It plans, raises on its own refusals, and commits. A caller that
    also writes the commodity or _raw layer in the same pass must NOT use it — plan every layer through
    plan_driver_slices / _plan_commodity_write / _plan_raw_write, union the refusals with
    write_guard.raise_if_refused, and only then commit. Two guarded entry points in sequence is exactly the
    defect where a driver refusal landed after 11.1 GB of commodity slices had already been rewritten.

    `manifest` (a write_guard.RunManifest) and `allow_churn` (a FRACTION naming the drop you expect) are
    keyword-only with defaults, so the call sites need no edit."""
    from leviathan.graphrag import write_guard as wg
    plan = plan_driver_slices(driver_sink, backend=backend, bedrock=bedrock, max_per=max_per,
                              warnings=warnings, manifest=manifest, allow_churn=allow_churn)
    wg.raise_if_refused(plan)
    return wg.commit_write(plan)


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
