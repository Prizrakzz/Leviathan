"""Retrieval-quality rankers for the evidence layer (GRAPHRAG_PLAN WS-MS retrieval A/B).

Three OPT-IN, composable knobs layered on the dense cosine retrieve() — all in-memory over the flat-file
slices, NO DB (they port to pgvector later; only the candidate source changes, not this logic):

  - hybrid  (RECALL):    a BM25 lexical leg fused with dense via Reciprocal Rank Fusion -> surfaces the exact
                         tokens (B40, ZL, CIF, tickers) that dense embeddings smear together.
  - rerank  (PRECISION): a bge cross-encoder re-scores query<->prop relevance.
  - mmr     (DIVERSITY): SOURCE-AWARE Maximal Marginal Relevance final-select -> thins a source RESTATING
                         itself but KEEPS cross-source corroboration, and balances slots across sources so no
                         single high-volume source dominates the top-k (guards the LLM's lateral reasoning).

Pure + deterministic (BM25/RRF/MMR are math; the cross-encoder is a fixed model in eval mode) -> reproducible
A/B + audit. The reasoning LLM is untouched: these only curate WHICH dated evidence reaches it.
"""
from __future__ import annotations

import re

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens — keeps finance codes intact as ONE token (b40, zl, cif, kc), which is the
    whole point of the lexical leg (dense retrieval splits/smears them)."""
    return _TOKEN.findall((text or "").lower())


# ── BM25 lexical index (memoized per node, built over the FULL slice) ─────────────────────
_BM25_CACHE: dict = {}


def bm25_index(node: str, records: list[dict]):
    """BM25Okapi over a slice's prop texts, memoized by node. Built over the full slice (asof-independent);
    callers asof-filter the CANDIDATES, so no future prop is returned. (2nd-order caveat: IDF is over the full
    slice — affects term weighting only, never injects future evidence; true per-asof IDF is a later refinement.)"""
    if node in _BM25_CACHE:
        return _BM25_CACHE[node]
    from rank_bm25 import BM25Okapi
    idx = BM25Okapi([tokenize(r["text"]) for r in records]) if records else None
    _BM25_CACHE[node] = (idx, records)
    return idx, records


def rrf_fuse(ranked_lists: list[list], c: int = 60) -> list:
    """Reciprocal Rank Fusion: score(item) = sum_l 1/(c + rank_l). Fuses by object identity; returns the merged
    items best-first. Standard c=60."""
    score, ref = {}, {}
    for lst in ranked_lists:
        for rank, item in enumerate(lst):
            key = id(item)
            score[key] = score.get(key, 0.0) + 1.0 / (c + rank)
            ref[key] = item
    return [ref[key] for key in sorted(score, key=score.get, reverse=True)]


def hybrid_candidates(query: str, node: str, all_records: list[dict], asof, dense_top: list[dict],
                      fetch_k: int) -> list[dict]:
    """RECALL pool = RRF(dense_top, bm25_top). BM25 ranks the full slice (so it can surface an exact-token prop
    the dense leg missed), asof-filtered before selection."""
    idx, full = bm25_index(node, all_records)
    if idx is None:
        return dense_top[:fetch_k]
    scores = idx.get_scores(tokenize(query))
    bm_top: list[dict] = []
    for i in sorted(range(len(full)), key=lambda j: scores[j], reverse=True):
        r = full[i]
        if asof and r["date"] > asof:                              # leakage-safe: never a future-dated candidate
            continue
        bm_top.append(r)
        if len(bm_top) >= fetch_k:
            break
    return rrf_fuse([dense_top[:fetch_k], bm_top])[:fetch_k]


# ── MMR diversity ─────────────────────────────────────────────────────────────────────────
def _cos(a, b) -> float:
    import numpy as np
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(a @ b / (na * nb)) if na and nb else 0.0


def mmr_select(cands: list[dict], relevance: list[float], k: int, lam: float, *,
               same_source: bool = True, fairness: float = 0.30, trust: list[float] | None = None) -> list[dict]:
    """Source-aware Maximal Marginal Relevance. Iteratively pick argmax:

        lam*rel_i - (1-lam)*max_sim(i, picked SAME-SOURCE) - fairness*picked_count[source_i] (+ trust_i)

    `relevance` is aligned to `cands`; each cand carries ['vector'] and ['source']. Three levers:
      - same_source=True: the novelty penalty compares i ONLY to already-picked props FROM THE SAME SOURCE, so a
        source restating itself is thinned but a near-identical prop from a DIFFERENT source (independent
        corroboration) is NOT penalized. same_source=False = classic source-agnostic MMR (escape hatch).
      - fairness>0: a per-source saturation penalty (grows with how many props from that source are already
        picked) -> one high-volume source can't dominate the top-k by count even when its props are distinct.
      - trust (optional, aligned to cands; higher = more credible): a light additive bias. Default None keeps
        retrieval credibility-NEUTRAL (trust ordering is applied at OUTPUT, not selection).
    lam=1 -> pure relevance; smaller lam -> more within-source diversity."""
    if not cands:
        return []
    lo, hi = min(relevance), max(relevance)
    rng = (hi - lo) or 1.0
    rel = [(x - lo) / rng for x in relevance]                        # normalize for stable mixing with cosine sim
    tw = trust if trust is not None else [0.0] * len(cands)
    src = [(c.get("source") or "") for c in cands]
    picked, picked_i, remaining = [], [], list(range(len(cands)))
    src_count: dict = {}
    while remaining and len(picked) < k:
        best_i, best_v = remaining[0], -1e18
        for i in remaining:
            div = max((_cos(cands[i]["vector"], cands[j]["vector"])
                       for j in picked_i if not same_source or src[j] == src[i]), default=0.0)  # SAME-source novelty
            sat = fairness * src_count.get(src[i], 0)               # balance: diminishing returns per source
            v = lam * rel[i] - (1 - lam) * div - sat + tw[i]
            if v > best_v:
                best_v, best_i = v, i
        picked.append(cands[best_i]); picked_i.append(best_i); remaining.remove(best_i)
        src_count[src[best_i]] = src_count.get(src[best_i], 0) + 1
    return picked


# ── bge cross-encoder reranker (lazy self-hosted singleton) ──────────────────────────────
from leviathan.graphrag import params as _pr

RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
# CE pool = full fetch_k. MEASURED (2026-07-03 ablation, 18 serving retrieves x 10 v3 queries): 41.7% of
# final picks under pool-60 come from fusion ranks 25-60 — the CE rescues deep candidates constantly, so
# capping the pool materially changes retrieval. Speed comes from the rerank lock below, not the pool.
RERANK_POOL = int(_pr.get("serving.retrieval.rerank_pool", 60))
_reranker = None
_RERANK_LOCK = None                    # ONE rerank at a time, at full thread speed (see rerank_scores)


def rerank_scores(query: str, texts: list[str]) -> list[float]:
    """Cross-encoder relevance for (query, text) pairs — PRECISION. Self-hosted (sentence-transformers
    CrossEncoder), same family as bge-m3, multilingual for the PT/ES/FR corpus. Deterministic (fixed weights).

    CONCURRENCY: the cross-encoder is the heaviest CPU op in serving. N eval workers each running it on
    cores/N torch threads was the July-3 slowdown (~8-16 min/answer) — thread-starved passes contending
    for the same cores. A global lock serializes reranks so each runs at FULL thread speed: same total
    CPU, no contention, ~10x per-op latency. Callers stay concurrent for everything else (LLM waits, pg)."""
    global _reranker, _RERANK_LOCK
    if not texts:
        return []
    if _RERANK_LOCK is None:
        import threading
        _RERANK_LOCK = threading.Lock()
    with _RERANK_LOCK:
        if _reranker is None:
            from sentence_transformers import CrossEncoder
            _reranker = CrossEncoder(RERANKER_MODEL)
        return [float(s) for s in _reranker.predict([(query, t) for t in texts])]
