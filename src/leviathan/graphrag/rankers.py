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

import contextlib
import logging
import os
import re
import threading
import time

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
# waiting for. Fail fast (2 attempts = 1 retry) so the fallback is reached in seconds. The fallback is NOT
# cheap — bge measured 13.88 s/60-doc pool even on the 4-vCPU taskdef :67 (Fargate grants torch 2 threads
# regardless of vCPU) — but paying it promptly still beats waiting through the ladder and paying it anyway.
_RERANK_MAX_ATTEMPTS = 2

# NATIVE Cohere (D-MW-1/2, 2026-08-11): `rerank-v3.5` on api.cohere.com is the SAME MODEL as the Bedrock
# ARN above, at the production tier's 1,000 req/min instead of Bedrock's 3 (L-11512E58, Adjustable=FALSE)
# — ~300x, measured (14 calls in 7.5 s, zero 429s). No SDK: `requests` is a core dep, so the seam adds no
# dependency and no rebuild beyond the normal image. The 17-node rerank cliff (16 x pool-60 = 960 docs
# < _COALESCE_MAX_DOCS 1000 < 17 x 60) stops being a quota cliff on this lane and becomes a request-shape
# detail — 1,000 is ALSO the native per-request document cap, so the SAME chunk loop applies unchanged.
_COHERE_RERANK_URL = "https://api.cohere.com/v2/rerank"
_DEFAULT_COHERE_RERANK_MODEL = "rerank-v3.5"
# The coalescer's member wait: every queued caller gives the leader this long before raising
# TimeoutError and falling back to bge. Lifted to a NAMED constant (was a bare literal in submit)
# because the cohere retry ladder below must fit STRICTLY UNDER it — diff review caught the first
# shipped ladder at (5,30)x3 + 3 s backoff = 108 s > 90 s: during a Cohere slowdown every member
# would time out to bge while the leader kept leadership in flight, the exact incident class the
# test_coalescer_cross_turn docstring records for the 8-attempt adaptive ladder. The arithmetic is
# pinned: _COHERE_MAX_ATTEMPTS * sum(_COHERE_TIMEOUT) + sum(_COHERE_BACKOFF) < _COALESCE_MEMBER_WAIT.
_COALESCE_MEMBER_WAIT = 90
# EXPLICIT timeouts (connect, read). The Bedrock leaf never set any — a recorded gotcha: botocore's
# 60 s default read timeout inside a 90 s coalescer member wait leaves no room for the bge fallback.
# (5, 20) not (5, 30): 3 x (5+20) + 1 + 2 = 78 s, under the member wait with margin for the
# 4 s coalesce window. Cohere's measured upstream latency is 51 ms — a 20 s read ceiling is ~400x p50.
_COHERE_TIMEOUT = (5, 20)
# 3 total attempts, backoff 1 s then 2 s, ONLY on 429/5xx/timeout/connection errors. Bedrock keeps its
# fail-fast 2 (that number is quota-rationalized against a ~1-token/20 s bucket; the rationale does NOT
# transfer to a 1,000/min lane, where a retry is cheap and a fallback to a 13.88 s/60-doc CPU pool is not).
_COHERE_MAX_ATTEMPTS = 3
_COHERE_BACKOFF = (1.0, 2.0)


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
    """`bge` (self-hosted CPU cross-encoder), `bedrock` (managed Cohere Rerank) or `cohere` (native
    api.cohere.com). Env overrides params so the ECS task flips it without a rebuild; default `bge` keeps
    offline/tests/eval byte-identical. ANY OTHER STRING runs bge — loudly, once (see rerank_scores)."""
    return (os.environ.get("GRAPHRAG_RERANK_BACKEND")
            or _pr.get("serving.retrieval.rerank_backend", "bge")).strip().lower()


# ── THE RERANK LANE COLLECTOR (D-MW-6) ────────────────────────────────────────────────────
# THE GAP THIS CLOSES: no rerank metric existed at all. A quota fallback — the event that silently turns a
# managed 2 s call into a 13.88 s/60-doc CPU pool, i.e. a ~100 s/walk latency regression — was visible ONLY
# by grepping Logs Insights, and NO artifact recorded it, so every "fallbacks == 0" gate clause was
# UNCOMPUTABLE. Two instruments, deliberately separate:
#   * EMF (below) is the PROD ALARM FEED ONLY. It carries no run/eval_set dimension, so a fallback in arm N
#     is indistinguishable from any other run sharing the log group — it can never be a gate artifact.
#   * this collector is the GATE INSTRUMENT: one object per TURN, snapshotted onto trace.rerank_lane
#     (registered in tracekeys.TRACE_RECORD_KEYS -> lifted into every eval per-answer record).
#
# WHY A THREAD-LOCAL AND NOT contextvars (round-3, MEASURED — the prescription that was WRONG): reranks run
# inside the walk's ThreadPoolExecutor workers. A Context copied INSIDE a worker is empty (the copy happens
# on the wrong thread), and one shared Context entered by 4 workers raises RuntimeError. So the parent's
# collector OBJECT is captured on the caller's thread and installed explicitly into each worker's slot
# (planner._parallel_fill, planner's probe pool, orchestrator._evidence_only — see `adopt_lane`).
#
# ATTRIBUTION (round-3 verified): coalesced REQUEST counts are LEADER-attributed and informational only —
# one leader fires for members of possibly several turns. FALLBACKS are CALLER-attributed and exact: the
# leader's error is broadcast to every member and re-raised in each caller's own thread, which is where
# rerank_scores catches it. Gate clauses therefore read fallbacks + backends, never requests.
_LANE_TL = threading.local()


class RerankLaneCollector:
    """Per-turn rerank telemetry. Lock-guarded because the fill workers share ONE instance.

    `short_counts` is the BEDROCK lane's honesty counter: that leaf keeps its 0.0 floor for unreturned
    indices (round-3 law — never arm a raise on the live lane untested; if Bedrock caps results at
    200-1000 docs, a raise converts today's silent partial scoring into a bge fallback on EVERY production
    turn), so the floor is COUNTED instead. The cohere leaf raises on a short count; that surfaces as a
    fallback, not as a short count."""

    def __init__(self):
        self._lock = threading.Lock()
        self._backends: set[str] = set()
        self._requests = 0
        self._docs = 0
        self._fallbacks = 0
        self._throttles = 0
        self._short = 0
        self._stranded = 0
        self._ms = 0.0

    def record_request(self, backend: str, n_docs: int, ms: float = 0.0) -> None:
        """ONE leaf call = one API request (the chunk loop calls this per chunk). Recorded on the ATTEMPT,
        including a failed one: which lane a turn actually reached for is the fact `backends` exists for."""
        with self._lock:
            if backend:
                self._backends.add(str(backend))
            self._requests += 1
            self._docs += max(0, int(n_docs or 0))
            self._ms += max(0.0, float(ms or 0.0))

    def record_fallback(self, from_backend: str | None = None) -> None:
        """A managed lane failed and this caller is about to run bge instead. `from_backend` joins the
        backend set so a failure BEFORE any request (missing key, unknown host) still names the intent."""
        with self._lock:
            self._fallbacks += 1
            if from_backend:
                self._backends.add(str(from_backend))

    def record_throttle(self) -> None:
        with self._lock:
            self._throttles += 1

    def record_short(self, n: int) -> None:
        with self._lock:
            self._short += max(0, int(n or 0))

    def record_stranded(self, n: int) -> None:
        """Diff-review catch: `_run_probes` shuts its pool down with wait=False, and an already-running
        probe worker keeps a DIRECT reference to this collector — its rerank (including a fallback) can
        land AFTER the turn snapshotted, so `fallbacks == 0` could read clean on a lane that fell back.
        Rather than pretend the count is exact, the strand is COUNTED: any gate reading fallbacks must
        also require stranded == 0 (D-MW-8 pre-flight does)."""
        with self._lock:
            self._stranded += max(0, int(n or 0))

    def snapshot(self) -> dict:
        """The trace stamp. `backends` is a SORTED LIST (JSON/DDB-safe, order-stable across runs) — a set
        would not survive the artifact write, and the gate clause `all(backends == [intended])` needs a
        value it can compare literally."""
        with self._lock:
            return {"backends": sorted(self._backends), "requests": self._requests, "docs": self._docs,
                    "fallbacks": self._fallbacks, "throttles": self._throttles,
                    "short_counts": self._short, "stranded": self._stranded, "ms": int(self._ms)}


def install_lane(collector) -> None:
    """Install `collector` as THIS thread's lane. The public seam — orchestrator installs one per turn,
    the worker wrappers install the parent's object into each pool thread."""
    _LANE_TL.current = collector


def clear_lane() -> None:
    """Remove this thread's lane. Pool threads are REUSED across turns, so a leak would attribute turn
    N+1's reranks to turn N's collector — the clear is what makes the per-turn stamp honest."""
    try:
        del _LANE_TL.current
    except AttributeError:
        pass


def lane_collector():
    """This thread's collector, or None. None is a valid state everywhere: all recording is fail-open."""
    return getattr(_LANE_TL, "current", None)


@contextlib.contextmanager
def adopt_lane(collector):
    """Run a block with `collector` installed on THIS thread — NESTED-SAFE: a thread that already carries
    a lane keeps it (the sequential branches of the fill/probe pools run on the CALLER's thread, and
    clearing there would strip the turn's own collector mid-walk). Fail-open end to end."""
    own = False
    try:
        own = collector is not None and lane_collector() is None
        if own:
            install_lane(collector)
    except Exception:  # noqa: BLE001 — telemetry must never break a walk
        own = False
    try:
        yield
    finally:
        if own:
            try:
                clear_lane()
            except Exception:  # noqa: BLE001
                pass


def _lane_emf(metrics: dict, units: dict | None = None) -> None:
    """One EMF line per leaf event, on the existing `Leviathan/Serving` lane dims (source +
    rerank_backend). LAZY import: emf resolves the active backend THROUGH rankers._rerank_backend, so a
    top-level import here would close the cycle. Fail-open — telemetry never breaks a turn."""
    try:
        from leviathan.graphrag import emf
        emf.emit(metrics, units=units)
    except Exception:  # noqa: BLE001
        pass


def _lane_record_request(backend: str, n_docs: int, ms: float) -> None:
    c = lane_collector()
    if c is not None:
        try:
            c.record_request(backend, n_docs, ms)
        except Exception:  # noqa: BLE001
            pass
    _lane_emf({"RerankRequests": 1, "RerankDocs": int(n_docs or 0), "RerankLatencyMs": int(ms or 0)},
              units={"RerankRequests": "Count", "RerankDocs": "Count", "RerankLatencyMs": "Milliseconds"})


def _lane_record_throttle() -> None:
    c = lane_collector()
    if c is not None:
        try:
            c.record_throttle()
        except Exception:  # noqa: BLE001
            pass
    _lane_emf({"RerankThrottles": 1}, units={"RerankThrottles": "Count"})


def _lane_record_fallback(from_backend: str | None = None) -> None:
    c = lane_collector()
    if c is not None:
        try:
            c.record_fallback(from_backend)
        except Exception:  # noqa: BLE001
            pass
    _lane_emf({"RerankFallbacks": 1}, units={"RerankFallbacks": "Count"})


def _lane_record_short(n: int) -> None:
    c = lane_collector()
    if c is not None:
        try:
            c.record_short(n)
        except Exception:  # noqa: BLE001
            pass
    _lane_emf({"RerankShortCount": int(n or 0)}, units={"RerankShortCount": "Count"})


def _is_throttle(err: BaseException) -> bool:
    """Caller-visible throttling: botocore's ThrottlingException/TooManyRequestsException (raised only
    AFTER the adaptive ladder is exhausted, which is exactly the event worth counting)."""
    name = type(err).__name__
    code = ""
    try:
        code = str(((getattr(err, "response", None) or {}).get("Error") or {}).get("Code") or "")
    except Exception:  # noqa: BLE001
        code = ""
    return any(s in name or s in code for s in ("Throttl", "TooManyRequests"))


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
        _t0 = time.perf_counter()
        try:
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
        except BaseException as err:
            if _is_throttle(err):
                _lane_record_throttle()     # the 3/min bucket, finally countable per turn (D-MW-6)
            raise
        finally:
            _lane_record_request("bedrock", len(chunk), (time.perf_counter() - _t0) * 1000)
        scores = [0.0] * len(chunk)
        filled: set[int] = set()
        for r in resp.get("results", []):
            i = r.get("index")
            if isinstance(i, int) and 0 <= i < len(scores):
                scores[i] = float(r.get("relevanceScore", 0.0))
                filled.add(i)
        # RESPONSE-COUNT HANDLING, SPLIT BY LANE (D-MW-2, round-2 catch). This LIVE leaf KEEPS its 0.0
        # floor: arming a raise here rests on an unverified assumption about Bedrock's response contract
        # at 200-1000 docs, and if Bedrock caps results the raise converts today's silent partial scoring
        # into a bge fallback on every production turn. So the floor is MEASURED instead — counted into
        # the turn's lane stamp and logged once per short chunk. The cohere leaf, which is new and
        # probe-verified before it carries traffic, raises.
        missing = len(chunk) - len(filled)
        if missing:
            log.warning("bedrock rerank returned %d of %d results; %d indices floored to 0.0",
                        len(filled), len(chunk), missing)
            _lane_record_short(missing)
        out.extend(scores)
    return out


def _cohere_api_key() -> str:
    """The dual-name read (batch_extract._api_key's exact idiom, batch_extract.py:53-57): the local .env
    carries COHERE_API while the ECS/Batch secret injects COHERE_API_KEY, and one code path must satisfy
    both lanes. RAISES when unset so the caller-level try/except turns it into a warning + bge fallback —
    a missing key must degrade a turn's latency, never break the turn. The key is never logged, never
    stamped on a trace, and never reaches EMF."""
    key = (os.environ.get("COHERE_API") or os.environ.get("COHERE_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("COHERE_API / COHERE_API_KEY is unset; the cohere rerank backend needs a key")
    return key


def _cohere_post(headers: dict, body: dict) -> dict:
    """ONE chunk request with the D-MW-2 retry ladder: 3 total attempts, backoff 1 s then 2 s, retrying
    ONLY 429 / 5xx / read-connect timeouts / connection errors. Anything else (401, 400, a malformed
    body) raises IMMEDIATELY — retrying a rejected request just delays the bge fallback."""
    import requests
    last: BaseException | None = None
    for attempt in range(_COHERE_MAX_ATTEMPTS):
        try:
            resp = requests.post(_COHERE_RERANK_URL, headers=headers, json=body, timeout=_COHERE_TIMEOUT)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last = e
        else:
            code = int(getattr(resp, "status_code", 0) or 0)
            if code == 429:
                _lane_record_throttle()
            if code == 429 or code >= 500:
                last = RuntimeError(f"cohere rerank HTTP {code}: {str(getattr(resp, 'text', ''))[:200]}")
            elif code >= 400:
                raise RuntimeError(f"cohere rerank HTTP {code}: {str(getattr(resp, 'text', ''))[:200]}")
            else:
                return resp.json()
        if attempt + 1 >= _COHERE_MAX_ATTEMPTS:
            break
        time.sleep(_COHERE_BACKOFF[min(attempt, len(_COHERE_BACKOFF) - 1)])
    raise last if last is not None else RuntimeError("cohere rerank failed")


def _cohere_rerank_call(query: str, docs: list[str]) -> list[float]:
    """ONE raw native Cohere Rerank request per chunk, SHAPE-MIRRORED on `_bedrock_rerank_call` — same
    rerank_max_chars truncation, same empty->" " guard, same _COALESCE_MAX_DOCS chunk loop (1,000 is also
    the native per-request document cap), same index realignment to INPUT order.

    The ONE deliberate asymmetry is the short-count: an incomplete result set here RAISES (-> one warning
    -> bge fallback) rather than silently flooring, because a truncated response yields a floored, mostly
    TIED score vector — retrieval that looks like it ran and did not. See the bedrock leaf for why the
    live lane keeps its floor instead."""
    key = _cohere_api_key()
    model = (os.environ.get("GRAPHRAG_RERANK_MODEL_COHERE")
             or _pr.get("serving.retrieval.rerank_model_cohere", _DEFAULT_COHERE_RERANK_MODEL))
    max_chars = int(_pr.get("serving.retrieval.rerank_max_chars", 2000))
    q = (((query or "").strip()) or " ")[:max_chars]
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    out: list[float] = []
    for lo in range(0, len(docs), _COALESCE_MAX_DOCS):
        chunk = [(((t or "").strip()) or " ")[:max_chars] for t in docs[lo:lo + _COALESCE_MAX_DOCS]]
        body = {"model": model, "query": q, "documents": chunk, "top_n": len(chunk)}
        _t0 = time.perf_counter()
        try:
            payload = _cohere_post(headers, body)
        finally:
            _lane_record_request("cohere", len(chunk), (time.perf_counter() - _t0) * 1000)
        results = (payload or {}).get("results") or []
        if len(results) != len(chunk):
            raise RuntimeError(f"cohere rerank returned {len(results)} results for {len(chunk)} documents")
        scores = [0.0] * len(chunk)
        for r in results:
            i = r.get("index")
            if isinstance(i, int) and 0 <= i < len(scores):
                scores[i] = float(r.get("relevance_score", 0.0))
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
        if not e["ev"].wait(timeout=_COALESCE_MEMBER_WAIT):
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
        """One grouped managed request per distinct query; each caller gets its own contiguous score slice.
        Errors propagate to every member of the group so the caller-level bge fallback stays intact.

        D-MW-2 (the review catch that would otherwise have shipped the whole seam dark): this leaf used to
        name `_bedrock_rerank_call` LITERALLY, so a `cohere` branch in rerank_scores alone would still have
        sent every COALESCED request — i.e. every walk rerank — to Bedrock's 3/min bucket. The leaf is now
        DISPATCHED, resolved ONCE per fire so a mid-fire env flip cannot split one batch across two vendors.
        Leadership, windows, quiescence and expect/unexpect are what stay unchanged."""
        call = _cohere_rerank_call if _rerank_backend() == "cohere" else _bedrock_rerank_call
        groups: dict[str, list[dict]] = {}
        for e in batch:
            groups.setdefault(e["q"], []).append(e)
        for q, entries in groups.items():
            try:
                flat = [t for e in entries for t in e["texts"]]
                scores = call(q, flat)
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


def _cohere_rerank_scores(query: str, texts: list[str]) -> list[float]:
    """Relevance per (query, text) via NATIVE Cohere Rerank, aligned to INPUT order. Same coalescer as the
    Bedrock lane (fewer, larger requests is still better; it is just no longer load-bearing for quota
    survival at 1,000 req/min) — `_fire` dispatches the leaf, so this is the same submit path with a
    different vendor at the bottom."""
    return _COAL.submit(query, texts)


def _bge_rerank_scores(query: str, texts: list[str], record: bool = True) -> list[float]:
    """Self-hosted bge cross-encoder (sentence-transformers), same family as bge-m3, multilingual for the
    PT/ES/FR corpus. Deterministic (fixed weights).

    CONCURRENCY: the cross-encoder is the heaviest CPU op in serving. N eval workers each running it on
    cores/N torch threads was the July-3 slowdown (~8-16 min/answer) — thread-starved passes contending
    for the same cores. A global lock serializes reranks so each runs at FULL thread speed: same total
    CPU, no contention, ~10x per-op latency. Callers stay concurrent for everything else (LLM waits, pg).

    `record=False` is the WARMUP lane only (server._warm_startup): the boot-time cold load is ~13-14 s,
    and recording it would publish a fabricated latency sample onto the ACTIVE backend's alarm series
    on every task start (diff-review catch — the sample would land dimensioned `cohere` on the flipped
    task and dominate any p95 alarm on a low-traffic series)."""
    global _reranker, _RERANK_LOCK
    if _RERANK_LOCK is None:
        _RERANK_LOCK = threading.Lock()
    _t0 = time.perf_counter()
    try:
        with _RERANK_LOCK:
            if _reranker is None:
                from sentence_transformers import CrossEncoder
                _reranker = CrossEncoder(RERANKER_MODEL)
            return [float(s) for s in _reranker.predict([(query, t) for t in texts])]
    finally:
        # D-MW-6: the bge lane records too, or Layer B's CONTROL arm has no lane stamp to pre-flight
        # against (`backends == ['bge'] and fallbacks == 0` is what makes a control arm honest). Recorded
        # OUTSIDE the global lock: the EMF line is cheap, but nothing that isn't the cross-encoder itself
        # belongs inside the one mutex every rerank in the process queues on.
        if record:
            _lane_record_request("bge", len(texts), (time.perf_counter() - _t0) * 1000)


# ONE warning per distinct unknown backend string, per process. Before D-MW-1 a typo in
# GRAPHRAG_RERANK_BACKEND was a SILENT ~100 s/walk latency regression with zero signal — the recon's worst
# trap, because the fallback it degrades into is the same code path a healthy bge deployment runs.
_UNKNOWN_BACKENDS_WARNED: set[str] = set()


def _warn_unknown_backend(backend: str) -> None:
    if backend in _UNKNOWN_BACKENDS_WARNED:
        return
    _UNKNOWN_BACKENDS_WARNED.add(backend)
    log.warning("GRAPHRAG_RERANK_BACKEND=%r is not a known rerank backend (bge|bedrock|cohere); "
                "running the self-hosted bge cross-encoder instead", backend)


def rerank_scores(query: str, texts: list[str]) -> list[float]:
    """Cross-encoder relevance for (query, text) pairs — PRECISION. Dispatches to the configured backend
    (`cohere` native Rerank in production, `bedrock` managed Rerank, `bge` self-hosted offline). A managed
    failure falls back to bge so a turn never breaks — and logs EVERY failed request (a once-only warning
    hid a silent Cohere/bge mixture during the Jul-5 throttling incident; with coalescing it's <=1-2
    requests/turn, so this can't spam). A missing COHERE_API key raises inside the leaf and lands here as
    exactly that: one warning, one fallback, never a broken turn.

    The fallback is recorded on the CALLER's thread and that is the load-bearing detail (D-MW-6): the
    coalescer leader broadcasts its error to every member and each member re-raises it here, so a
    fallback is attributed to the turn that suffered it, not to whichever turn happened to lead."""
    if not texts:
        return []
    backend = _rerank_backend()
    if backend == "bedrock":
        try:
            return _bedrock_rerank_scores(query, texts)
        except Exception as e:                                          # noqa: BLE001 — never break a turn
            log.warning("bedrock rerank failed (%s: %s); falling back to bge", type(e).__name__, e)
            _lane_record_fallback("bedrock")
    elif backend == "cohere":
        try:
            return _cohere_rerank_scores(query, texts)
        except Exception as e:                                          # noqa: BLE001 — never break a turn
            log.warning("cohere rerank failed (%s: %s); falling back to bge", type(e).__name__, e)
            _lane_record_fallback("cohere")
    elif backend != "bge":
        _warn_unknown_backend(backend)
    return _bge_rerank_scores(query, texts)
