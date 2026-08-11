"""D-MW-6: the rerank LANE COLLECTOR — the per-turn instrument every cohere gate clause reads.

THE GAP IT CLOSES: no rerank metric existed at all. A quota fallback — the event that silently turns a
managed ~2 s call into a 13.88 s/60-doc CPU pool, i.e. a ~100 s/walk latency regression — was visible ONLY
by grepping Logs Insights, and NO artifact recorded it, so every "fallbacks == 0" gate clause in the
D-MW-8 draft was UNCOMPUTABLE. EMF cannot close it either: it carries no run/eval_set dimension, so a
fallback in arm N is indistinguishable from any other run sharing the log group. The gate instrument is
this collector, snapshotted onto `trace.rerank_lane`.

The three round-3 pins the plan names, plus the attribution rule they rest on:
  1. a walk whose reranks ALL run in fill workers reports backend == configured + counted docs. The
     collector is a THREAD-LOCAL and reranks run inside the walk's ThreadPoolExecutor, so without explicit
     propagation the stamp reads zero on every real turn. (contextvars does NOT work here — MEASURED: a
     Context copied inside a worker is empty, and one shared Context entered by 4 workers raises.)
  2. a BGE-LANE walk reports backends == ['bge'] and fallbacks == 0 — else Layer B's CONTROL arm cannot
     pass its own pre-flight, and the A/B has no honest baseline. (The fill wrapper used to exist only
     when the coalescer hint was truthy, i.e. never on the bge lane.)
  3. two concurrent turns in one process never see each other's counters — serving threads are POOLED, so
     a leaked collector attributes turn N+1's reranks to turn N.
  4. ATTRIBUTION: coalesced REQUEST counts are leader-attributed (informational). FALLBACKS are
     CALLER-attributed and exact — the leader broadcasts its error to every member and each member
     re-raises it in its OWN thread, which is where rerank_scores catches it. Gate clauses read
     fallbacks + backends, never requests.

Signature-parity discipline (the D-DR stub-lied lesson): every test here drives the REAL seams —
planner._parallel_fill, rankers.rerank_scores, answer._with_rerank_lane — and stubs only the HTTP leaf or
the CrossEncoder weights. Nothing calls the collector's recorders directly to manufacture a snapshot, and
nothing stubs `_cohere_rerank_call` on the managed pins: the lane record lives INSIDE that leaf, so
stubbing it would remove the instrument and leave the pin measuring nothing.
Fully offline: `requests.post` and the cross-encoder are faked at the leaf; no AWS, no model download,
no LLM call.
"""
from __future__ import annotations

import json
import threading

import pytest
import requests
from leviathan.causal import schema as cs
from leviathan.graphrag import answer as an
from leviathan.graphrag import eval as evl
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import graph as gph
from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag import planner as pl
from leviathan.graphrag import rankers as rk
from leviathan.graphrag import tracekeys as tk


class _Resp:
    """The response surface the native leaf reads (it handles status manually, never raise_for_status)."""

    def __init__(self, status: int = 200, payload: dict | None = None, text: str = ""):
        self.status_code, self._payload, self.text = status, payload or {}, text

    def json(self) -> dict:
        return self._payload


def _post_ok(url, headers=None, json=None, timeout=None):
    docs = json["documents"]
    return _Resp(200, {"results": [{"index": i, "relevance_score": 0.6} for i in range(len(docs))]})


def _post_401(url, headers=None, json=None, timeout=None):
    return _Resp(401, text="invalid api token")


class _FakeCE:
    """Stands in for the sentence-transformers CrossEncoder, installed as `rankers._reranker`. The REAL
    `_bge_rerank_scores` then runs — its global mutex, its timing, and its lane record — and only the
    model weights are fake. Stubbing `_bge_rerank_scores` itself would stub out the thing under test."""

    def __init__(self):
        self.pairs = 0
        self._lock = threading.Lock()

    def predict(self, pairs):
        with self._lock:
            self.pairs += len(pairs)
        return [0.5] * len(pairs)


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    """A fixed 4-wide walk pool, a private coalescer, and a neutralised quiescence timer — so the pins
    measure propagation, not the machine's scheduler. The lane slot is cleared on both sides: pytest
    reuses ONE thread, exactly like the serving pool does."""
    rk.clear_lane()
    monkeypatch.setattr(pl, "_WALK_WORKERS", 4)
    monkeypatch.setattr(rk, "_COAL", rk._RerankCoalescer())
    monkeypatch.setattr(rk, "_coalesce_quiescence", lambda: 60.0)
    yield
    rk.clear_lane()


def _walk(nodes: int, docs_per_node: int, *, before=None) -> None:
    """Drive the REAL fill pool: N nodes, each node reranking `docs_per_node` texts through the real
    `rerank_scores` dispatch. `retrieve` is a sentinel (not ev.retrieve), so the embedding pre-warm and
    the coalescer hint are skipped exactly as they are for any injected test retriever."""
    def fn(n):
        if before is not None:
            before()
        rk.rerank_scores("q", [f"{n}-{j}" for j in range(docs_per_node)])
    pl._parallel_fill([f"n{i}" for i in range(nodes)], fn, "q", object())


# ── PIN 1: the fill workers report the CONFIGURED backend ────────────────────────────────────────────
def test_fill_worker_reranks_report_the_configured_backend_and_count_every_doc(monkeypatch):
    """The managed lane, end to end: 4 nodes x 3 docs, all reranked inside pool workers, all attributed
    to the ONE collector the turn installed on the caller's thread.

    `docs` is exact even though `requests` is not: coalescing changes how many requests carry the docs,
    never how many docs were scored — every doc passes through exactly one fire. That is why the gate
    clauses read backends + fallbacks and treat the request count as informational."""
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "cohere")
    monkeypatch.setenv("COHERE_API", "k-test")
    bge_hits: list[str] = []
    # THE STUB GOES AT THE HTTP LEAF, not at `_cohere_rerank_call`: the lane record lives INSIDE that
    # leaf, so stubbing the leaf would stub out the instrument under test and the pin would pass vacuously
    # while measuring nothing (the D-DR stub-lied class, in miniature).
    monkeypatch.setattr(requests, "post", _post_ok)
    # the bge stub here is a TRIPWIRE, not the instrument: a silent degrade would otherwise pass as a
    # green managed run wearing the right label, which is the exact failure this whole lane exists to see
    monkeypatch.setattr(rk, "_bge_rerank_scores", lambda q, t: (bge_hits.append(q), [0.0] * len(t))[1])
    lane = rk.RerankLaneCollector()
    rk.install_lane(lane)

    _walk(4, 3)

    snap = lane.snapshot()
    assert snap["backends"] == ["cohere"], "the walk's reranks never reached the turn's collector"
    assert snap["fallbacks"] == 0 and bge_hits == []          # a silent bge fallback is the trap, not a pass
    assert snap["docs"] == 12 and snap["requests"] >= 1       # leader-attributed count, exact doc count


def test_a_worker_with_no_parent_lane_still_reranks(monkeypatch):
    """FAIL-OPEN: no collector installed is a VALID state (offline scripts, a bare retrieve). The walk
    must run identically and record nothing — telemetry never breaks a turn."""
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "bge")
    ce = _FakeCE()
    monkeypatch.setattr(rk, "_reranker", ce)
    assert rk.lane_collector() is None
    _walk(4, 3)
    assert ce.pairs == 12 and rk.lane_collector() is None


# ── PIN 2: the BGE lane — Layer B's control arm must be able to pre-flight itself ─────────────────────
def test_bge_lane_walk_reports_bge_only_with_zero_fallbacks(monkeypatch):
    """The control arm's pre-flight IS `backends == ['bge'] and fallbacks == 0`. On the unhinted bge lane
    the fill wrapper used to not exist at all, so this arm would have stamped an empty lane and aborted
    itself. bge does not coalesce, so here the request count is exact too: one per node."""
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "bge")
    ce = _FakeCE()
    monkeypatch.setattr(rk, "_reranker", ce)
    lane = rk.RerankLaneCollector()
    rk.install_lane(lane)

    _walk(4, 3)

    assert lane.snapshot() | {"ms": 0} == {"backends": ["bge"], "requests": 4, "docs": 12,
                                           "fallbacks": 0, "throttles": 0, "short_counts": 0,
                                           "stranded": 0, "ms": 0}
    assert ce.pairs == 12


# ── PIN 3: two concurrent turns, two collectors, zero bleed ──────────────────────────────────────────
def test_two_concurrent_turns_never_see_each_others_counters(monkeypatch):
    """Both turns are IN FLIGHT simultaneously (the barrier holds every worker of both walks until all
    four are inside a rerank), which is the only arrangement that can catch a shared-slot bug. Each turn
    counts exactly its own docs; the main thread ends with no lane at all."""
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "bge")
    monkeypatch.setattr(rk, "_reranker", _FakeCE())
    gate = threading.Barrier(4)                      # 2 turns x 2 nodes: nobody reranks alone
    snaps: dict = {}

    def turn(name: str, docs_per_node: int):
        lane = rk.RerankLaneCollector()
        rk.install_lane(lane)                        # what orchestrator._respond does per turn
        try:
            _walk(2, docs_per_node, before=lambda: gate.wait(timeout=20))
            snaps[name] = lane.snapshot()
        finally:
            rk.clear_lane()                          # ...and what its finally does

    ts = [threading.Thread(target=turn, args=("A", 3)), threading.Thread(target=turn, args=("B", 5))]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in ts)

    assert snaps["A"]["requests"] == 2 and snaps["A"]["docs"] == 6      # never 4 requests / 16 docs
    assert snaps["B"]["requests"] == 2 and snaps["B"]["docs"] == 10
    assert snaps["A"]["backends"] == snaps["B"]["backends"] == ["bge"]
    assert rk.lane_collector() is None                                 # no leak onto the pooled thread


def test_a_finished_turn_leaves_no_lane_for_the_next_one(monkeypatch):
    """The clear is what makes the per-turn stamp honest: pool threads are REUSED across turns."""
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "bge")
    monkeypatch.setattr(rk, "_reranker", _FakeCE())
    first = rk.RerankLaneCollector()
    rk.install_lane(first)
    _walk(2, 2)
    rk.clear_lane()
    second = rk.RerankLaneCollector()
    rk.install_lane(second)
    _walk(2, 2)
    assert first.snapshot()["docs"] == 4 and second.snapshot()["docs"] == 4


# ── PIN 4: fallbacks are CALLER-attributed, not leader-attributed ─────────────────────────────────────
def test_a_raising_leaf_charges_the_fallback_to_the_caller_that_suffered_it(monkeypatch):
    """TWO turns share ONE coalesced batch; the leaf raises for exactly one of them. The leader broadcasts
    its error to that group's members only, each member re-raises it in its OWN thread, and rerank_scores
    records the fallback there — so the fallback lands on the turn that actually degraded, whichever turn
    happened to lead. This is the property that makes `sum(rerank_lane.fallbacks) == 0` a real clause.

    The failed turn reads backends == ['bge', 'cohere']: the lane it MEANT to run joins the set even
    though its request never completed, and the bge it actually ran joins it too. The gate rejects that
    row on the fallbacks clause first — `backends` is the diagnosis, `fallbacks` is the verdict."""
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "cohere")
    monkeypatch.setenv("COHERE_API", "k-test")
    monkeypatch.setattr(rk, "_reranker", _FakeCE())

    def post(url, headers=None, json=None, timeout=None):
        # rejected for ONE of the two queries; `_fire` groups by query, so exactly one group dies
        return _Resp(401, text="invalid api token") if json["query"] == "bad" \
            else _post_ok(url, headers=headers, json=json, timeout=timeout)

    monkeypatch.setattr(requests, "post", post)
    snaps, scores = {}, {}

    def turn(name: str, query: str):
        lane = rk.RerankLaneCollector()
        rk.install_lane(lane)
        try:
            scores[name] = rk.rerank_scores(query, ["t1", "t2"])
            snaps[name] = lane.snapshot()
        finally:
            rk.clear_lane()

    rk.rerank_expect(2, window=60.0)                       # both callers land in ONE batch
    ts = [threading.Thread(target=turn, args=("bad", "bad")),
          threading.Thread(target=turn, args=("ok", "good"))]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in ts)

    assert scores["bad"] == [0.5, 0.5] and scores["ok"] == [0.6, 0.6]   # bge floor vs the managed lane
    assert snaps["bad"]["fallbacks"] == 1 and snaps["bad"]["backends"] == ["bge", "cohere"]
    assert snaps["ok"]["fallbacks"] == 0 and "bge" not in snaps["ok"]["backends"]


# ── the serving lane: ONE collector per TURN, stamped onto the trace ─────────────────────────────────
def _graph() -> gph.CausalGraph:
    corn = cs.CausalContract(contract="corn", aliases=["maize"],
                             drivers=[cs.Driver(id="drought", type="hazard", sign="+",
                                                mechanism="dryness cuts yield")])
    return gph.CausalGraph({"corn": corn}, silver=set())


def _force(kind):
    return lambda q, call=None: {"intent": kind, "needs_numbers": kind in ("numbers_only", "hybrid"),
                                 "needs_reasoning": kind in ("reasoning", "hybrid")}


def _reason_call(system, user, *, model, tool):
    return {"tldr": "x", "mechanism": "y", "diagram_mermaid": "", "sources": []}


def test_a_walk_turn_carries_the_lane_stamp(monkeypatch):
    """The turn's collector is minted in `_respond` and snapshotted onto `trace.rerank_lane`. The stamp is
    UNCONDITIONAL on every turn that reranks or could have -- `backends == ['bge'], fallbacks == 0` IS the
    control-arm measurement, so the usual absent-when-default idiom would leave the A/B's baseline
    uncomparable (the same both-polarities rule `cascade_closure` ships under)."""
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "bge")
    monkeypatch.setattr(rk, "_reranker", _FakeCE())
    monkeypatch.setattr(ev, "embed", lambda x, **k: [[1.0, 0.0]])   # never load bge-m3 for a lane pin

    def _retrieve(q, node, *, k, asof=None, near=None):
        rk.rerank_scores(q, ["note"])                  # the injected retriever reranks, as serving's does
        return [{"date": "2024-01-01", "source": "usda_wasde", "source_key": f"s3://{node}",
                 "text": "note"}]

    out = orch.respond("why is corn bid on a drought", graph=_graph(), asof="2024-06-01",
                       classify=_force("reasoning"), call=_reason_call, retrieve=_retrieve)
    lane = out["trace"]["rerank_lane"]
    assert lane["backends"] == ["bge"] and lane["fallbacks"] == 0 and lane["requests"] >= 1
    assert rk.lane_collector() is None                 # cleared in the finally: the thread is POOLED


def test_a_trivial_turn_mints_no_collector_and_carries_no_stamp(monkeypatch):
    """The guardrail and trivial lanes return ABOVE the collector and rerank nothing -- an empty lane is
    not a measurement, and a zero row in the artifact would dilute every rate computed over it."""
    monkeypatch.setenv("GRAPHRAG_TRIVIAL_ROUTER", "on")
    monkeypatch.setattr(ev, "embed", lambda x, **k: [[1.0, 0.0]])
    out = orch.respond("hi", graph=_graph())
    assert "rerank_lane" not in (out.get("trace") or {})
    assert rk.lane_collector() is None


# ── the eval lane: a DIRECT answer() call owns its own turn ───────────────────────────────────────────
@an._with_rerank_lane
def _fake_answer(**_kw) -> dict:
    """Stands in for `answer()` at the decorator seam: it reranks once and returns an answer-shaped dict.
    The decorator is the unit under test, so the body must be the only thing faked."""
    rk.rerank_scores("q", ["a", "b"])
    return {"answer": "x", "trace": {"timing_ms": 3}}


def test_a_direct_answer_call_mints_its_own_lane_and_stamps_the_trace(monkeypatch):
    """eval.py's non-orchestrator rows call answer() directly and would otherwise produce rows with NO
    `rerank_lane` column — i.e. exactly the arms the parity gate reads."""
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "bge")
    monkeypatch.setattr(rk, "_reranker", _FakeCE())
    out = _fake_answer()
    assert out["trace"]["rerank_lane"]["backends"] == ["bge"]
    assert out["trace"]["rerank_lane"]["requests"] == 1 and out["trace"]["rerank_lane"]["docs"] == 2
    assert out["trace"]["timing_ms"] == 3                  # the pre-existing trace is not replaced
    assert rk.lane_collector() is None                     # and the eval worker thread is left clean


def test_the_answer_wrapper_is_a_pass_through_when_the_turn_already_owns_the_lane(monkeypatch):
    """NESTED-SAFE: an orchestrator turn keeps ONE collector for the whole turn and the stamp keeps ONE
    owner. The inner call must neither stamp its own snapshot nor clear the turn's lane mid-walk."""
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "bge")
    monkeypatch.setattr(rk, "_reranker", _FakeCE())
    outer = rk.RerankLaneCollector()
    rk.install_lane(outer)
    out = _fake_answer()
    assert "rerank_lane" not in out["trace"]               # the orchestrator stamps it, once
    assert rk.lane_collector() is outer                    # ...and the turn's lane survives the call
    assert outer.snapshot()["requests"] == 1               # the work still counted onto the turn


def test_a_raising_answer_is_invoked_exactly_once_and_the_cause_propagates(monkeypatch):
    """THE DIFF-REVIEW BLOCKER PIN: the first shipped wrapper put the pass-through call inside a try
    whose handler ALSO called fn -- so every raising answer() (the deterministic-floor population) ran
    the whole walk + synthesis TWICE, replayed SSE ticks, and replaced the floor's recorded cause with
    the retry's exception. fn must run EXACTLY ONCE, from outside any handler, and the ORIGINAL
    exception must reach the caller -- on BOTH branches (lane already owned / lane self-minted)."""
    calls = {"n": 0}

    @an._with_rerank_lane
    def _boom(**kwargs):
        calls["n"] += 1
        raise RuntimeError("walk blew up")

    # Branch 1: the turn already owns a lane (the serving path).
    outer = rk.RerankLaneCollector()
    rk.install_lane(outer)
    try:
        with pytest.raises(RuntimeError, match="walk blew up"):
            _boom()
        assert calls["n"] == 1
    finally:
        rk.clear_lane()
    # Branch 2: no lane installed (the direct-call eval path) -- the wrapper mints one, and a raise
    # must still mean exactly one invocation with the lane cleared afterwards.
    calls["n"] = 0
    with pytest.raises(RuntimeError, match="walk blew up"):
        _boom()
    assert calls["n"] == 1
    assert rk.lane_collector() is None                     # no leak onto the caller's thread


def test_adopt_lane_never_strips_a_lane_the_thread_already_owns():
    """The sequential branches of the fill/probe pools run on the CALLER's thread, where an
    install-and-clear would strip the turn's own collector mid-walk."""
    own = rk.RerankLaneCollector()
    rk.install_lane(own)
    other = rk.RerankLaneCollector()
    with rk.adopt_lane(other):
        assert rk.lane_collector() is own
    assert rk.lane_collector() is own
    with rk.adopt_lane(None):                              # fail-open on a missing parent
        assert rk.lane_collector() is own


# ── the artifact seam: registered == lifted ───────────────────────────────────────────────────────────
def test_rerank_lane_is_registered_and_reaches_the_per_answer_record(monkeypatch):
    """D-AM-3's contract: registering in tracekeys IS the artifact registration (eval builds these
    columns by LOOPING the registry). Pinned END TO END, not just as membership — the C2/U3 class is
    'a trace key that reaches no artifact, silently', and only the lift proves it doesn't."""
    assert "rerank_lane" in tk.TRACE_RECORD_KEYS
    assert len(set(tk.TRACE_RECORD_KEYS)) == len(tk.TRACE_RECORD_KEYS)        # no duplicate columns
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "bge")
    monkeypatch.setattr(rk, "_reranker", _FakeCE())
    out = _fake_answer()
    rec = evl._per_answer_record({"q": {"id": "row1"}, "out": out, "rubric": {}}, "single")
    assert rec["rerank_lane"] == out["trace"]["rerank_lane"]
    # ...and a row that never reranked still carries the column (absent-as-None), so a gate can tell an
    # unmeasured row from a clean one instead of reading a missing key as a pass.
    assert evl._per_answer_record({"q": {"id": "row2"}, "out": {}, "rubric": {}}, "single")["rerank_lane"] is None


def test_the_snapshot_survives_an_artifact_write(monkeypatch):
    """`backends` is a SORTED LIST, not a set: a set does not survive the JSONL/DDB write, and the gate
    clause `backends == ['cohere']` needs a value it can compare literally and reproducibly."""
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "cohere")
    monkeypatch.setenv("COHERE_API", "k-test")
    monkeypatch.setattr(rk, "_reranker", _FakeCE())
    monkeypatch.setattr(requests, "post", _post_401)      # rejected, not transient: no ladder, no sleeps
    lane = rk.RerankLaneCollector()
    rk.install_lane(lane)
    _walk(2, 2)
    snap = lane.snapshot()
    assert json.loads(json.dumps(snap)) == snap
    assert snap["backends"] == ["bge", "cohere"] and snap["fallbacks"] == 2
    assert isinstance(snap["ms"], int)
