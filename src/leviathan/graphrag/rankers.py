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

import logging
import os
import re

log = logging.getLogger(__name__)

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
# GRAPHRAG_RERANK_POOL env overrides params (the Stage-L pool sweep varies 60/90/120 per eval arm without
# an image rebuild per arm); unset -> params -> 60, byte-identical default.
RERANK_POOL = int(os.environ.get("GRAPHRAG_RERANK_POOL")
                  or _pr.get("serving.retrieval.rerank_pool", 60))
_reranker = None
_RERANK_LOCK = None                    # ONE rerank at a time, at full thread speed (see _bge_rerank_scores)

# Managed reranker (Bedrock Cohere Rerank) — the production default. The self-hosted CPU cross-encoder added
# ~2-4s/node (~100s across an L2 walk) on GPU-less Fargate; a managed call is sub-second and downloads no
# model. The swap is transparent: scores feed only sort + mmr_select (min-max normalized) — NO absolute-score
# threshold anywhere — so Cohere's 0-1 scale is drop-in. Env flips backend without a rebuild.
_DEFAULT_RERANK_MODEL = "arn:aws:bedrock:us-east-1::foundation-model/cohere.rerank-v3-5:0"
_bedrock_rerank_client = None
# QUOTA (measured 2026-07-05): Cohere Rerank on Bedrock is capped at THREE requests/min, NON-adjustable —
# per-node calls (10/turn) can never fit, parallel or sequential; throttled calls silently degraded to the
# CPU bge fallback (the "45s walk" was a Cohere/bge mixture). One request DOES take 300+ docs in ~2s and
# cross-encoder scoring is pointwise, so batching across nodes is SCORE-IDENTICAL. Hence the coalescer below:
# concurrent rerank calls within a turn merge into ONE Bedrock request (<= _COALESCE_MAX_DOCS docs).
_COALESCE_MAX_DOCS = 1000            # API cap per request (10 nodes x pool 60 = 600, comfortably under)
_COALESCE_IDLE_WINDOW = 0.25         # s — a lone caller (one-hop path) barely waits
_COALESCE_HINT_WINDOW = 4.0          # s — hard cap the leader waits for the hinted batch (env/param tunable)
# QUIESCENCE (raised 0.8 -> 2.5, Phase-2 latency RCA, MEASURED in-VPC job 52e131bb over 20 stubbed + 5 live
# arms): it is a SAFETY NET for an over-counted hint, not the normal closer, and at 0.3-0.8 s it was firing
# as the PRIMARY closer on 10/10 serving-config turns. Real inter-arrival gaps between walk nodes are p50
# 0.142 s but p90 0.760 s with 27.8% of gaps > 0.30 s (n=212) — the pg pool serialises fetches, so a
# legitimate straggler routinely looks "quiet". The count-based closer (`_expect`, now kept accurate by
# rerank_unexpect + a decrement-on-drain) is what should close the batch; quiescence only rescues a hint
# that can never be met. 2.5 s is above the observed max legitimate gap and still bounds the damage.
_COALESCE_QUIESCENCE = 2.5           # s — a quiet gap this long after the last arrival = the hinted stragglers
#                                      (skipped/empty-retrieval nodes) aren't coming; don't burn the full window
# F1b (Phase-2): the Bedrock Rerank quota (3 req/min, L-11512E58, Adjustable=FALSE, user-confirmed permanent)
# means a throttle is a STEADY STATE, not a tail event. An adaptive ladder of 8 attempts burns tens of seconds
# of a turn before the caller-level bge fallback is even reached, and it does so while HOLDING the quota it is
# waiting for. Fail fast (2 attempts = 1 retry) so the fallback is reached in seconds. This is only affordable
# because the fallback got cheap: bge was 10.3 s/60-doc pool on the 1-vCPU taskdef :64; serving is now 4 vCPU.
_RERANK_MAX_ATTEMPTS = 2


def _coalesce_window() -> float:
    """Leader's hard-cap wait for the hinted batch. Env `GRAPHRAG_COALESCE_WINDOW` > params > code default,
    so Stage 5.0/5.4 tunes it on the ECS task WITHOUT a rebuild (mirrors _rerank_backend's override)."""
    return float(os.environ.get("GRAPHRAG_COALESCE_WINDOW")
                 or _pr.get("serving.retrieval.coalesce_window", _COALESCE_HINT_WINDOW))


def _coalesce_quiescence() -> float:
    """Quiet-gap after the last arrival before the leader stops waiting on over-counted stragglers."""
    return float(os.environ.get("GRAPHRAG_COALESCE_QUIESCENCE")
                 or _pr.get("serving.retrieval.coalesce_quiescence", _COALESCE_QUIESCENCE))


def _rerank_max_attempts() -> int:
    """botocore total attempts (1 initial + retries) for the managed rerank. Env > params > code default,
    same resolution order as every other serving knob, so the ladder is tunable without a rebuild."""
    return max(1, int(os.environ.get("GRAPHRAG_RERANK_MAX_ATTEMPTS")
                      or _pr.get("serving.retrieval.rerank_max_attempts", _RERANK_MAX_ATTEMPTS)))


def _rerank_backend() -> str:
    """`bge` (self-hosted CPU cross-encoder) or `bedrock` (managed Cohere Rerank). Env overrides params so the
    ECS task flips it without a rebuild; default `bge` keeps offline/tests/eval byte-identical."""
    return (os.environ.get("GRAPHRAG_RERANK_BACKEND")
            or _pr.get("serving.retrieval.rerank_backend", "bge")).strip().lower()


def _bedrock_rerank_call(query: str, docs: list[str]) -> list[float]:
    """ONE raw Bedrock Rerank request (chunked only past the API doc cap). Adaptive client-side retry pacing
    (the 3-req/min quota). Unreturned indices floor to 0.0, aligned to input order."""
    global _bedrock_rerank_client
    if _bedrock_rerank_client is None:
        import boto3
        from botocore.config import Config
        _bedrock_rerank_client = boto3.client(
            "bedrock-agent-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"),
            config=Config(retries={"mode": "adaptive", "max_attempts": _rerank_max_attempts()}))
    model_arn = (os.environ.get("GRAPHRAG_RERANK_MODEL")
                 or _pr.get("serving.retrieval.rerank_model", _DEFAULT_RERANK_MODEL))
    max_chars = int(_pr.get("serving.retrieval.rerank_max_chars", 2000))
    q = (((query or "").strip()) or " ")[:max_chars]
    out: list[float] = []
    for lo in range(0, len(docs), _COALESCE_MAX_DOCS):
        chunk = [(((t or "").strip()) or " ")[:max_chars] for t in docs[lo:lo + _COALESCE_MAX_DOCS]]
        resp = _bedrock_rerank_client.rerank(
            queries=[{"type": "TEXT", "textQuery": {"text": q}}],
            sources=[{"type": "INLINE", "inlineDocumentSource": {"type": "TEXT", "textDocument": {"text": d}}}
                     for d in chunk],
            rerankingConfiguration={
                "type": "BEDROCK_RERANKING_MODEL",
                "bedrockRerankingConfiguration": {
                    "numberOfResults": len(chunk),
                    "modelConfiguration": {"modelArn": model_arn},
                },
            },
        )
        scores = [0.0] * len(chunk)
        for r in resp.get("results", []):
            i = r.get("index")
            if isinstance(i, int) and 0 <= i < len(scores):
                scores[i] = float(r.get("relevanceScore", 0.0))
        out.extend(scores)
    return out


class _RerankCoalescer:
    """Merges concurrent same-query rerank calls into ONE Bedrock request (the 3-req/min quota budget is
    ~one request per TURN). The first caller becomes the leader: it waits until the hinted batch size arrives
    (`expect`, set by the walk) or the window lapses, drains the queue, fires one grouped request per distinct
    query, and routes each caller's slice of scores back. Callers block on their event; leader errors propagate
    to every member so the caller-level bge fallback stays intact."""

    def __init__(self):
        import threading
        self._lock = threading.Lock()
        self._pending: list[dict] = []
        self._leading = False
        self._expect = 0
        self._window = _COALESCE_IDLE_WINDOW
        self._last_arrival = 0.0

    def expect(self, n: int, window: float | None = None) -> None:
        """ACCUMULATE the outstanding hint. It used to ASSIGN, and that is a cross-turn clobber.

        `_expect` lives on a process-global singleton but a hint is per-TURN, so at C>=2 the newest
        hint became the ONLY hint. The damaging direction is a hint that LOWERS the count: turn A hints
        8, six of A's callers are queued, turn B hints 2 -> `_expect` becomes 2, the leader's
        `n >= exp` test passes immediately, it fires a PARTIAL batch, and A's remaining callers form a
        SECOND batch. That is 2 Bedrock requests for one turn against a 3-req/min ACCOUNT-WIDE bucket
        (L-11512E58, Adjustable=false) -- i.e. the clobber is a correctness/quota defect, not the
        "latency-only" one the earlier record claimed. Accumulating makes the number what it always
        should have been: how many promised callers are outstanding PROCESS-WIDE, which is exactly what
        the leader's count-based closer needs. Batches stay per-query (`_fire` groups by distinct
        query), so coalescing two turns never merges their documents.

        Deliberately NOT changed: leadership stays process-global. Per-turn leadership would put N
        leaders against that same 3/min bucket simultaneously (measured burst: 3 of 8 succeed, 4-8
        throttle), and a leader error propagates to every member -> one throttle drops a whole turn to
        the 100x-slower bge path.

        Cost of accumulating: an over-counted hint that is never retracted now leaks into later turns
        instead of being reset by the next `expect`. That is what `unexpect()` is for -- every promised
        caller that cannot reach the reranker retracts (planner on a raising fill, evidence/pgstore on
        an empty candidate set) -- and the residue is bounded anyway by the quiescence safety net
        (_COALESCE_QUIESCENCE) and by the leader's decrement-on-drain.
        """
        with self._lock:
            self._expect += max(0, int(n))
            self._window = float(window) if window is not None else _coalesce_window()

    def unexpect(self, n: int = 1) -> None:
        """RETRACT part of a hint: a promised caller has determined it will never reach the reranker (empty
        candidate set, or its fill raised). Without this the leader waits out the window/quiescence for an
        arrival that cannot come — which is exactly how a count-based closer degrades into a timer-based one.
        `expect` counts nodes that WILL retrieve; only the reranker knows which of them actually score."""
        with self._lock:
            self._expect = max(0, self._expect - max(0, int(n)))

    def submit(self, query: str, texts: list[str]) -> list[float]:
        import threading
        import time
        e = {"q": query, "texts": texts, "ev": threading.Event(), "scores": None, "err": None}
        lead = False
        with self._lock:
            self._pending.append(e)
            self._last_arrival = time.time()
            if not self._leading:
                self._leading = True
                lead = True
        if lead:
            self._lead()
        if not e["ev"].wait(timeout=90):
            raise TimeoutError("rerank coalescer timed out")
        if e["err"] is not None:
            raise e["err"]
        return e["scores"]

    def _lead(self) -> None:
        """Own the queue until it is empty, ONE request in flight at a time.

        Two Phase-2 corrections, both measured (in-VPC jobs 52e131bb / 44e96fc1):
          * leadership is released AFTER the request, not before it. Releasing early let arrivals that landed
            during an in-flight call elect a second leader and fire a SECOND concurrent Bedrock request —
            reproduced at 4 concurrent requests from a single turn when the call was slow (i.e. exactly when
            it was throttled). That is a positive feedback loop against a 3-req/min ceiling, and it is the
            mechanism behind the 410 s worst turn on record. Holding leadership caps in-flight at 1 and turns
            late arrivals into a coalesced follow-up batch instead of a competing request.
          * `_expect` is DECREMENTED by what the batch actually took, never zeroed. Zeroing pinned every batch
            after the first to the hardcoded _COALESCE_IDLE_WINDOW (0.25 s) that no env var can reach —
            measured as the closer on 10/10 serving-config turns.

        The re-lead loop is NOT optional once leadership is held across the request: a caller that arrives
        mid-flight has already passed the `if not self._leading` election, so nobody else will ever serve it.
        Draining until empty is what keeps that queue live. The loop terminates because only the leader
        removes from `_pending` and arrivals per turn are bounded by the node budget.
        """
        import time
        batch: list[dict] = []
        try:
            while True:
                t0 = time.time()
                quiesce = _coalesce_quiescence()
                while True:
                    with self._lock:
                        n, exp, win, last = (len(self._pending), self._expect, self._window,
                                             self._last_arrival)
                    now = time.time()
                    if exp and n >= exp:
                        break                             # everyone the walk promised has arrived
                    if now - t0 >= (win if exp else _COALESCE_IDLE_WINDOW):
                        break                             # hard window cap
                    if exp and n > 0 and now - last >= quiesce:
                        break                             # QUIESCENCE: a quiet gap this long means the hint
                        # over-counted and the stragglers are never coming. With rerank_unexpect() keeping
                        # the count honest this is a safety net, not the normal path — see the constant.
                    time.sleep(0.05)
                with self._lock:
                    batch, self._pending = self._pending, []
                    self._expect = max(0, self._expect - len(batch))   # what's left is still promised
                self._fire(batch)                         # _fire never raises: per-group try/except/finally
                batch = []
                with self._lock:
                    if not self._pending:
                        self._leading = False             # released only once nothing is queued AND nothing
                        return                            # is in flight — at most ONE request per process
        except BaseException:
            # Defensive only (_fire swallows its own errors). A leader that dies while holding the flag
            # would wedge EVERY later rerank in the process behind the 90 s follower timeout, so release
            # the flag and unblock anything taken but unserved before propagating.
            with self._lock:
                stranded, self._pending = [*batch, *self._pending], []
                self._leading = False
            for e in stranded:
                if e["scores"] is None and e["err"] is None:
                    e["err"] = RuntimeError("rerank coalescer leader aborted")
                e["ev"].set()
            raise

    def _fire(self, batch: list[dict]) -> None:
        """One grouped Bedrock request per distinct query; each caller gets its own contiguous score slice.
        Errors propagate to every member of the group so the caller-level bge fallback stays intact."""
        groups: dict[str, list[dict]] = {}
        for e in batch:
            groups.setdefault(e["q"], []).append(e)
        for q, entries in groups.items():
            try:
                flat = [t for e in entries for t in e["texts"]]
                scores = _bedrock_rerank_call(q, flat)
                i = 0
                for e in entries:
                    e["scores"] = scores[i:i + len(e["texts"])]
                    i += len(e["texts"])
            except Exception as err:  # noqa: BLE001 — propagate to every member; callers fall back
                for e in entries:
                    e["err"] = err
            finally:
                for e in entries:
                    e["ev"].set()


_COAL = _RerankCoalescer()


def rerank_expect(n: int, window: float | None = None) -> None:
    """Hint from the walk: ~n rerank calls are about to arrive — coalesce them into one Bedrock request.
    `window=None` -> the env/param-tunable default (_coalesce_window). ADDITIVE across concurrent turns
    (see `_RerankCoalescer.expect`): this raises the outstanding count, it does not replace it.

    CONTRACT (Phase-2): the hint is a PROMISE the caller must be able to keep. It is only satisfiable if the
    caller can hold all `n` retrieves in flight simultaneously — a walk pool narrower than `n` blocks the last
    arrivals BEHIND the very request they were supposed to join, so the floor becomes ceil(n/workers) requests
    at any timer setting (measured). See planner._parallel_fill, which sizes its pool from this count."""
    _COAL.expect(n, window)


def rerank_unexpect(n: int = 1) -> None:
    """Retract `n` from the outstanding hint — a promised caller that will never reach the reranker (empty
    candidate set, or a fill that raised). Cheap, lock-guarded, and a no-op when nothing is expected."""
    _COAL.unexpect(n)


def _bedrock_rerank_scores(query: str, texts: list[str]) -> list[float]:
    """Relevance per (query, text) via Bedrock managed Rerank, aligned to INPUT order — coalesced across
    concurrent callers (see _RerankCoalescer). Network-bound — no CPU lock."""
    return _COAL.submit(query, texts)


def _bge_rerank_scores(query: str, texts: list[str]) -> list[float]:
    """Self-hosted bge cross-encoder (sentence-transformers), same family as bge-m3, multilingual for the
    PT/ES/FR corpus. Deterministic (fixed weights).

    CONCURRENCY: the cross-encoder is the heaviest CPU op in serving. N eval workers each running it on
    cores/N torch threads was the July-3 slowdown (~8-16 min/answer) — thread-starved passes contending
    for the same cores. A global lock serializes reranks so each runs at FULL thread speed: same total
    CPU, no contention, ~10x per-op latency. Callers stay concurrent for everything else (LLM waits, pg)."""
    global _reranker, _RERANK_LOCK
    if _RERANK_LOCK is None:
        import threading
        _RERANK_LOCK = threading.Lock()
    with _RERANK_LOCK:
        if _reranker is None:
            from sentence_transformers import CrossEncoder
            _reranker = CrossEncoder(RERANKER_MODEL)
        return [float(s) for s in _reranker.predict([(query, t) for t in texts])]


def rerank_scores(query: str, texts: list[str]) -> list[float]:
    """Cross-encoder relevance for (query, text) pairs — PRECISION. Dispatches to the configured backend
    (`bedrock` managed Rerank in production, `bge` self-hosted offline). A Bedrock failure falls back to bge so
    a turn never breaks — and logs EVERY failed request (a once-only warning hid a silent Cohere/bge mixture
    during the Jul-5 throttling incident; with coalescing it's <=1-2 requests/turn, so this can't spam)."""
    if not texts:
        return []
    if _rerank_backend() == "bedrock":
        try:
            return _bedrock_rerank_scores(query, texts)
        except Exception as e:                                          # noqa: BLE001 — never break a turn
            log.warning("bedrock rerank failed (%s: %s); falling back to bge", type(e).__name__, e)
    return _bge_rerank_scores(query, texts)
