"""Retrieval-quality rankers for the evidence layer (GRAPHRAG_PLAN WS-MS retrieval A/B).

Three OPT-IN, composable knobs layered on the dense cosine retrieve() — all in-memory over the flat-file
slices, NO DB (they port to pgvector later; only the candidate source changes, not this logic):

  - hybrid  (RECALL):    a BM25 lexical leg fused with dense via Reciprocal Rank Fusion -> surfaces the exact
                         tokens (B40, ZL, CIF, tickers) that dense embeddings smear together.
  - rerank  (PRECISION): a bge cross-encoder re-scores query<->prop relevance.
  - mmr     (DIVERSITY): Maximal Marginal Relevance final-select -> guards against rerank narrowing the
                         evidence set and starving the LLM's lateral reasoning.

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


def mmr_select(cands: list[dict], relevance: list[float], k: int, lam: float) -> list[dict]:
    """Maximal Marginal Relevance: iteratively pick argmax [lam*rel - (1-lam)*max_sim_to_picked]. `relevance`
    is aligned to `cands`; each cand carries ['vector']. Trades relevance for novelty so rerank can't collapse
    the top-k onto near-duplicates. lam=1 -> pure relevance; smaller lam -> more diversity."""
    if not cands:
        return []
    lo, hi = min(relevance), max(relevance)
    rng = (hi - lo) or 1.0
    rel = [(x - lo) / rng for x in relevance]                        # normalize for stable mixing with cosine sim
    picked, picked_i, remaining = [], [], list(range(len(cands)))
    while remaining and len(picked) < k:
        best_i, best_v = remaining[0], -1e18
        for i in remaining:
            div = max((_cos(cands[i]["vector"], cands[j]["vector"]) for j in picked_i), default=0.0)
            v = lam * rel[i] - (1 - lam) * div
            if v > best_v:
                best_v, best_i = v, i
        picked.append(cands[best_i]); picked_i.append(best_i); remaining.remove(best_i)
    return picked


# ── bge cross-encoder reranker (lazy self-hosted singleton) ──────────────────────────────
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
_reranker = None


def rerank_scores(query: str, texts: list[str]) -> list[float]:
    """Cross-encoder relevance for (query, text) pairs — PRECISION. Self-hosted (sentence-transformers
    CrossEncoder), same family as bge-m3, multilingual for the PT/ES/FR corpus. Deterministic (fixed weights)."""
    global _reranker
    if not texts:
        return []
    if _reranker is None:
        from sentence_transformers import CrossEncoder
        _reranker = CrossEncoder(RERANKER_MODEL)
    return [float(s) for s in _reranker.predict([(query, t) for t in texts])]
