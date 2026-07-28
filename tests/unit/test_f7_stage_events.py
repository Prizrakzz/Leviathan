"""F7 streaming partial findings — the content-bearing `stage` kinds (plan / walk / regime / number /
chain / evidence / drafting / verified).

The point of these tests is the CONTRACT, not the cosmetics. Everything the engines decide -- which regimes
fired, which numbers resolved, which chain hops grounded -- is finished and correct long before the writer
starts; F7 relays it as it lands. So what must hold is:

  * every new kind carries EXACTLY the pinned field set, sourced from deterministic engine output;
  * they arrive in engine order (plan -> walk -> evidence/regime -> drafting -> verified), and `verified`
    is what licenses the UI to activate citation handles (the streamed `token` draft is PRE-verifier);
  * on_stage=None is a strict no-op and the payload is byte-identical -- the regression that matters;
  * an emitter that RAISES cannot break or alter a turn;
  * the SSE relay is thread-safe (the numbers thread and the walk emit concurrently);
  * no evidence prose ever rides in a stage payload.

All hermetic: fake embed / injected retrieve + call / stub Anthropic client. No S3, no Athena, no LLM spend.
"""
from __future__ import annotations

import json
import threading

import pytest
from leviathan.causal import schema as cs
from leviathan.graphrag import answer as an
from leviathan.graphrag import graph as g
from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag import planner as pl
from leviathan.graphrag import server as sv
from leviathan.graphrag import store as st

# The pinned event contract (main loop). Field sets are EXACT: a kind that grows a field silently would
# break the FE's forward-compat assumption in the one direction it cannot absorb (extra data it renders).
PINNED = {
    "plan": {"intent", "contracts"},
    "walk": {"nodes", "depth"},
    "regime": {"contract", "regime", "direction", "basis"},
    "number": {"table", "metric", "value", "unit", "asof"},
    "chain": {"chain_id", "hops"},
    "evidence": {"node", "kept"},
    "drafting": set(),
    "verified": {"strips"},
}

# A sentinel that appears ONLY in retrieved evidence text. If it ever shows up in a stage payload, the
# emitters are leaking document prose (invariant 4).
PROSE = "SENTINELPROSE-frost-destroyed-the-cherries"


# ── hermetic fixtures ───────────────────────────────────────────────────────────────────────────────
def _orch_graph() -> g.CausalGraph:
    coffee = cs.CausalContract(contract="arabica_coffee", aliases=["arabica"],
                               drivers=[cs.Driver(id="frost", type="hazard", sign="+",
                                                  mechanism="frost kills trees")])
    corn = cs.CausalContract(contract="corn", aliases=["maize"],
                             drivers=[cs.Driver(id="drought", type="hazard", sign="+",
                                                mechanism="dryness cuts yield")])
    return g.CausalGraph({"arabica_coffee": coffee, "corn": corn}, silver=set())


def _retrieve(q, node, *, k, asof=None, near=None):
    return [{"date": "2024-01-01", "source": "usda_wasde", "source_key": f"s3://{node}", "text": PROSE}]


def _reason_call(system, user, *, model, tool):
    return {"tldr": "x", "mechanism": "y", "diagram_mermaid": "", "sources": []}


def _force(kind):
    return lambda q, call=None: {"intent": kind, "needs_numbers": kind in ("numbers_only", "hybrid"),
                                 "needs_reasoning": kind in ("reasoning", "hybrid")}


# --- fake Anthropic client driving the numbers agent (tool_use -> text), as in test_orchestrator ---
def _numbers_client():
    import types

    def _tu(inp):
        return types.SimpleNamespace(type="tool_use", name="lookup_number", input=inp, id="t1")

    def _tx(t):
        return types.SimpleNamespace(type="text", text=t)

    def _rs(content, stop):
        return types.SimpleNamespace(content=content, stop_reason=stop)

    class _Msgs:
        def __init__(self, outer):
            self.outer = outer

        def create(self, **kw):
            return self.outer.q.pop(0)

    class _Fake:
        def __init__(self, q):
            self.q = list(q)
            self.messages = _Msgs(self)

    return _Fake([_rs([_tu({"table": "silver_psd", "metric": "ending_stocks_mt",
                            "commodity": "corn_cbot", "period": "2023"})], "tool_use"),
                  _rs([_tx("US corn ending stocks were 31,400,000 MT.")], "end_turn")])


def _query_fn(sql):
    return [{"value": "31400000", "knowledge_date": "2024-02-08"}]


def _capture():
    """A recording on_stage. Returns (events, callback); events = [(kind, info), ...] in arrival order."""
    events: list = []
    lock = threading.Lock()

    def on_stage(stage, info):
        with lock:                       # the numbers thread and the walk both call this
            events.append((stage, dict(info or {})))
    return events, on_stage


def _turn(kind="reasoning", on_stage=None, **kw):
    return orch.respond("why is arabica bullish on a frost" if kind == "reasoning"
                        else "given low ending stocks is corn a buy",
                        graph=_orch_graph(), asof="2024-06-01", classify=_force(kind),
                        call=_reason_call, retrieve=_retrieve, on_stage=on_stage, **kw)


_WALLCLOCK = ("ground_ms", "ms_quantify", "ms_synth_llm", "ms_numbers", "ms_walk", "ms_total")


def _strip(obj):
    """Drop wall-clock measurements recursively — they differ run to run and are not part of the payload
    contract. EVERYTHING else must match byte for byte."""
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in obj.items()
                if k not in _WALLCLOCK and not (k.startswith("ms_") or k.endswith("_ms"))}
    if isinstance(obj, list):
        return [_strip(v) for v in obj]
    return obj


# ── 1. every new kind carries EXACTLY its pinned field set ──────────────────────────────────────────
def _reasoning_events():
    events, cb = _capture()
    _turn("reasoning", on_stage=cb)
    return events


@pytest.mark.parametrize("kind", ["plan", "walk", "evidence", "drafting", "verified"])
def test_reasoning_lane_emits_kind_with_pinned_fields(kind):
    seen = [i for s, i in _reasoning_events() if s == kind]
    assert seen, f"{kind} was never emitted on a reasoning turn"
    for info in seen:
        assert set(info) == PINNED[kind], f"{kind} field set drifted: {sorted(info)}"


def test_plan_carries_the_dispatched_intent_and_routed_contracts():
    plan = next(i for s, i in _reasoning_events() if s == "plan")
    assert plan["intent"] == "reasoning" and isinstance(plan["contracts"], list)


def test_walk_reports_the_subgraph_shape_before_grounding_costs_anything():
    walk = next(i for s, i in _reasoning_events() if s == "walk")
    assert walk["nodes"] >= 1 and isinstance(walk["depth"], int) and walk["depth"] >= 0


def test_evidence_carries_a_node_slug_and_a_kept_count_never_the_props():
    evs = [i for s, i in _reasoning_events() if s == "evidence"]
    assert evs
    for e in evs:
        assert isinstance(e["kept"], int) and e["kept"] >= 0
        assert ":" in e["node"] and PROSE not in e["node"]        # "kind:contract:id", not prose


def test_verified_reports_the_strip_count_and_is_the_last_engine_event():
    events = _reasoning_events()
    ver = next(i for s, i in events if s == "verified")
    assert isinstance(ver["strips"], int) and ver["strips"] >= 0
    names = [s for s, _ in events]
    # Nothing content-bearing may follow `verified`: it is the signal that licenses the UI to ACTIVATE
    # citation handles, so a later engine event would reopen a settled feed.
    after = set(names[names.index("verified") + 1:]) & set(PINNED)
    assert after == set(), f"engine events emitted after verified: {sorted(after)}"


# ── 2. regime: fires one event per regime, carrying the receipt, projected to {date, source} ────────
def _regime_graph() -> g.CausalGraph:
    arabica = cs.CausalContract(
        contract="arabica", aliases=["arabica"],
        drivers=[cs.Driver(id="frost", type="hazard", sign="+", mechanism="frost damage")],
        convergence=[cs.ConvergenceSignal(name="squeeze", direction="+", requires_any_n_of=1,
                                          drivers=["frost"])])
    return g.CausalGraph({"arabica": arabica}, silver=set())


def _ground_with_firing(on_stage):
    gr = _regime_graph()
    sg = pl.grounded_subgraph("frost", gr, embed=lambda ts: [[1.0] for _ in ts],
                              route_fn=lambda q, graph: ["arabica"], tau=0.0, depth=2)

    def retrieve(q, slice_, *, k, asof=None, near=None):
        if slice_ == "drivers/frost":
            return [{"date": "2021-07-20", "source": "GAIN", "source_key": "s3://f", "text": PROSE}]
        return [{"date": "2021-07-25", "source": "WASDE", "source_key": "s3://a", "text": PROSE}]

    pl.ground(sg, "frost", gr, retrieve=retrieve, asof="2021-08-01", driver_slices={"frost"},
              on_stage=on_stage)
    return sg


def test_regime_event_per_firing_with_the_basis_receipt():
    events, cb = _capture()
    sg = _ground_with_firing(cb)
    regs = [i for s, i in events if s == "regime"]
    assert len(regs) == len(sg.fired_regimes) == 1                 # ONE event per regime that fired
    r = regs[0]
    assert set(r) == PINNED["regime"]
    assert r["contract"] == "arabica" and r["regime"] == "squeeze" and r["direction"] == "+"
    # the receipt: WHY it fired, projected to the pinned {date, source} — never the richer internal basis
    assert r["basis"] == {"frost": {"date": "2021-07-20", "source": "GAIN"}}


def test_regime_basis_never_carries_value_z_or_detail():
    events, cb = _capture()
    _ground_with_firing(cb)
    for _, info in [e for e in events if e[0] == "regime"]:
        for receipt in info["basis"].values():
            assert set(receipt) == {"date", "source"}


def test_no_firing_means_no_regime_events():
    """No as-of anchors 'now' -> nothing fires -> the feed stays honestly empty (no speculative rows)."""
    events, cb = _capture()
    gr = _regime_graph()
    sg = pl.grounded_subgraph("frost", gr, embed=lambda ts: [[1.0] for _ in ts],
                              route_fn=lambda q, graph: ["arabica"], tau=0.0, depth=2)
    pl.ground(sg, "frost", gr, retrieve=lambda q, s, *, k, asof=None, near=None: [],
              asof=None, driver_slices={"frost"}, on_stage=cb)
    assert sg.fired_regimes == [] and [s for s, _ in events if s == "regime"] == []


# ── 3. number: one event per RESOLVED lookup, on both numbers lanes ─────────────────────────────────
@pytest.mark.parametrize("kind", ["hybrid", "numbers_only"])
def test_number_events_carry_the_resolved_row(kind):
    events, cb = _capture()
    _turn(kind, on_stage=cb, numbers_client=_numbers_client(), query_fn=_query_fn)
    nums = [i for s, i in events if s == "number"]
    assert nums, f"no `number` event on the {kind} lane"
    for info in nums:
        assert set(info) == PINNED["number"]
        assert info["table"] and info["metric"]
        assert info["value"] not in (None, "")
        assert info["unit"] is None or isinstance(info["unit"], str)
        assert info["asof"] == "2024-02-08"           # the row's as-KNOWN date, not the PIT cutoff


def test_number_skips_errored_and_empty_lookups():
    """A lookup with no usable row has no number to show — emitting one would put junk in the feed."""
    events, cb = _capture()
    orch._emit_numbers(cb, [
        {"query": {"table": "t", "metric": "m", "asof": "2024-01-01"}, "rows": [], "status": "no_rows"},
        {"query": {"table": "t", "metric": "m", "asof": "2024-01-01"}, "status": "error"},
        {"query": {"table": "t", "metric": "m", "asof": "2024-01-01"},
         "rows": [{"value": None}], "status": "ok"},
        {"query": {"table": "silver_psd", "metric": "ending_stocks_mt", "asof": "2024-06-01"},
         "rows": [{"value": 42.0, "unit": "mt", "knowledge_date": "2024-02-08"}], "status": "ok"},
    ])
    assert [i for s, i in events if s == "number"] == [
        {"table": "silver_psd", "metric": "ending_stocks_mt", "value": 42.0, "unit": "mt",
         "asof": "2024-02-08"}]


def test_number_emitter_survives_malformed_call_records():
    events, cb = _capture()
    orch._emit_numbers(cb, [None, "not a dict", 7, {"rows": "not a list"}])
    orch._emit_numbers(None, [{"query": {"table": "t"}, "rows": [{"value": 1}]}])   # None -> strict no-op
    assert [s for s, _ in events if s == "number"] == []


# ── 4. chain: the composers' fired hop path, both engines ───────────────────────────────────────────
class _SG:
    def __init__(self, trace):
        self.trace = trace


def test_chain_event_from_the_vertical_composer():
    events, cb = _capture()
    an._emit_chains(cb, _SG({"quantify_chain": {
        "chain_id": "chain_corn_flagship", "contract": "corn", "window": "2012..2013",
        "hops": [{"hop": 0, "node": "safrinha", "ref": "r", "table": "t", "metric": "m"},
                 {"hop": 1, "node": "Brazil production_mt", "ref": "r", "table": "t", "metric": "m"},
                 {"hop": 2, "collapsed_into": 1}]}}))
    assert [(s, i) for s, i in events] == [
        ("chain", {"chain_id": "chain_corn_flagship", "hops": ["safrinha", "Brazil production_mt"]})]


def test_chain_event_from_the_transmission_composer_dedups_the_shared_node():
    events, cb = _capture()
    an._emit_chains(cb, _SG({"quantify_transmission": {
        "chain_id": "xmit_palm_sbo", "focus": "soybean_oil", "window": "w",
        "links": [{"link": 0, "source": "palm", "target": "soybean_oil"},
                  {"link": 1, "source": "soybean_oil", "target": "soybean_meal"}]}}))
    chain = dict(events)["chain"]
    assert set(chain) == PINNED["chain"]
    assert chain["hops"] == ["palm", "soybean_oil", "soybean_meal"]     # shared node appears ONCE


def test_declines_and_traceless_subgraphs_emit_no_chain():
    events, cb = _capture()
    an._emit_chains(cb, _SG({"quantify_chain_decline": {"chain_id": "c", "reason": "degenerate"},
                             "quantify_transmission_decline": {"chain_id": "x", "reason": "cap"}}))
    an._emit_chains(cb, _SG({}))
    an._emit_chains(cb, _SG({"quantify_chain": "not a dict"}))        # malformed trace: swallowed
    an._emit_chains(None, _SG({"quantify_chain": {"chain_id": "c", "hops": []}}))   # None -> no-op
    assert events == []


# ── 5. ordering: the feed follows the ENGINES, not the writer ───────────────────────────────────────
def test_engine_events_arrive_in_engine_order():
    names = [s for s, _ in _reasoning_events()]
    assert names.index("plan") < names.index("walk")
    assert names.index("walk") < names.index("evidence")           # shape known before any leg lands
    assert names.index("evidence") < names.index("drafting")       # findings precede the writer
    assert names.index("drafting") < names.index("verified")       # and the writer precedes the verifier
    assert names.index("plan") == min(names.index(k) for k in set(names) & set(PINNED))


def test_drafting_precedes_every_token_and_verified_follows_them_all():
    """The half-measure guard (RCA F7c): `token` is PRE-verifier draft prose. `drafting` opens prose mode and
    `verified` closes it — a handle activated between them could still be stripped."""
    events, cb = _capture()

    def streaming_call(system, user, *, model, tool, on_token=None):
        if on_token:
            on_token("draft [1] ")
        return _reason_call(system, user, model=model, tool=tool)

    # the real serving call streams tokens; the injected fake mirrors its signature
    orch.respond("why is arabica bullish on a frost", graph=_orch_graph(), asof="2024-06-01",
                 classify=_force("reasoning"), call=streaming_call, retrieve=_retrieve, on_stage=cb)
    names = [s for s, _ in events]
    if "token" in names:                                            # only when the call path streams
        assert names.index("drafting") < names.index("token")
        assert names.index("verified") > max(i for i, s in enumerate(names) if s == "token")


# ── 6. THE regression that matters: on_stage=None is a strict no-op ─────────────────────────────────
@pytest.mark.parametrize("kind", ["reasoning", "hybrid", "numbers_only"])
def test_on_stage_none_emits_nothing_and_payload_is_byte_identical(kind):
    kw = {"numbers_client": _numbers_client(), "query_fn": _query_fn} if kind != "reasoning" else {}
    base = _turn(kind, on_stage=None, **kw)
    kw2 = {"numbers_client": _numbers_client(), "query_fn": _query_fn} if kind != "reasoning" else {}
    events, cb = _capture()
    streamed = _turn(kind, on_stage=cb, **kw2)
    assert events, "the streamed arm emitted nothing — the test would pass vacuously"
    assert json.dumps(_strip(base), sort_keys=True, default=str) == \
        json.dumps(_strip(streamed), sort_keys=True, default=str)


def test_none_path_builds_no_payload_at_all(monkeypatch):
    """REGRESSION (caught by test_reroute_v2_engine's duck-typed _FakeSG): a stage payload must be built
    INSIDE the None guard, never as an eager kwarg. `_emit(on_stage, "walk", depth=max(n.depth ...))` looks
    like a no-op when on_stage is None, but Python evaluates the argument FIRST — so a node without .depth
    raised straight through the walk on the non-streamed path. on_stage=None must cost nothing and risk
    nothing, which is invariant 2."""
    from leviathan.graphrag.numbers import cascade as cq

    class _NodeWithoutDepth:                                    # exactly the eval/test duck type
        contract, id, prior, evidence = "corn", "corn_seed", {}, []

    class _SGWithoutDepth:
        nodes, seeds, fired_regimes, mermaid, trace = [_NodeWithoutDepth()], ["corn"], [], "", {}

    reached: dict = {}
    monkeypatch.setattr(pl, "grounded_subgraph", lambda *a, **k: _SGWithoutDepth())
    monkeypatch.setattr(pl, "ground", lambda *a, **k: None)
    monkeypatch.setattr(an, "_l2_blocks", lambda *a, **k: ([], []))
    monkeypatch.setattr(an, "_pgnumbers_live", lambda: True)
    monkeypatch.setattr(cq, "quantify", lambda *a, **k: (reached.setdefault("quantify", True), None, None))
    try:
        an._answer_l2("q", _orch_graph(), model=an.SONNET, asof="2026-06-01", near=None,
                      call=lambda *a, **k: {"tldr": "x", "mechanism": "y", "sources": []},
                      retrieve=lambda *a, **k: [], routed=["corn"], numbers_lookup=lambda sql: [],
                      on_stage=None)
    except Exception:  # noqa: BLE001 — render scaffolding is incomplete; the WALK seam ran first
        pass
    assert reached.get("quantify"), "the None path raised before the quantify seam — a payload was built eagerly"


def test_emitters_are_the_only_difference_no_stage_helper_fires_on_none():
    """Belt + braces at the helper level: both _emit idioms and both F7 helpers are strict no-ops on None."""
    an._emit(None, "plan", intent="reasoning")
    pl._emit_stage(None, "regime", contract="c")
    an._emit_chains(None, _SG({"quantify_chain": {"chain_id": "c", "hops": [{"node": "n"}]}}))
    orch._emit_numbers(None, [{"query": {"table": "t", "metric": "m"}, "rows": [{"value": 1}]}])


# ── 7. an emitter that RAISES can never break or alter a turn ───────────────────────────────────────
@pytest.mark.parametrize("kind", ["reasoning", "hybrid"])
def test_raising_emitter_cannot_break_the_turn(kind):
    kw = {"numbers_client": _numbers_client(), "query_fn": _query_fn} if kind != "reasoning" else {}
    base = _turn(kind, on_stage=None, **kw)
    seen: list = []

    def boom(stage, info):
        seen.append(stage)
        raise ValueError(f"callback blew up on {stage}")

    kw2 = {"numbers_client": _numbers_client(), "query_fn": _query_fn} if kind != "reasoning" else {}
    out = _turn(kind, on_stage=boom, **kw2)
    assert set(seen) & set(PINNED), "the raising callback never saw a new kind"
    assert json.dumps(_strip(base), sort_keys=True, default=str) == \
        json.dumps(_strip(out), sort_keys=True, default=str)


# ── 8. the SSE relay is thread-safe (numbers thread ∥ walk) ─────────────────────────────────────────
def test_relay_drops_nothing_under_concurrent_emitters(monkeypatch):
    """The parallel-lane hazard: run_hybrid's numbers pool emits while the walk emits on the caller, and
    planner.ground's fill pool emits from N workers. The relay is a queue.Queue (put() is synchronized), so
    every event must survive. 4 threads x 50 events = 200, none lost, none duplicated."""
    from fastapi.testclient import TestClient

    n_threads, per_thread = 4, 50

    def fake_respond(query, *, graph, asof=None, session_id=None, on_stage=None, **kw):
        def lane(t):
            for i in range(per_thread):
                on_stage("number", {"table": f"t{t}", "metric": f"m{i}", "value": i,
                                    "unit": None, "asof": "2024-01-01"})
        ths = [threading.Thread(target=lane, args=(t,)) for t in range(n_threads)]
        for th in ths:
            th.start()
        for th in ths:
            th.join()
        return {"answer": "done", "intent": "hybrid"}

    monkeypatch.setitem(sv._STATE, "graph", _orch_graph())
    monkeypatch.setitem(sv._STATE, "store", st.InMemoryStore())
    monkeypatch.setattr(orch, "respond", fake_respond)
    with TestClient(sv.app).stream("GET", "/v1/respond/stream", params={"question": "q"}) as r:
        text = "".join(chunk for chunk in r.iter_text())
    assert text.count("event: stage") == n_threads * per_thread + 1        # +1 = the immediate "accepted"
    for t in range(n_threads):                                             # every lane fully represented
        assert text.count(f'"table": "t{t}"') == per_thread
    assert "event: result" in text


def test_relay_serialises_the_new_kinds_as_one_line_each(monkeypatch):
    """Each stage event must be ONE `data:` line — a raw newline inside the JSON would split the SSE frame."""
    from fastapi.testclient import TestClient

    def fake_respond(query, *, graph, asof=None, session_id=None, on_stage=None, **kw):
        on_stage("plan", {"intent": "hybrid", "contracts": ["corn"]})
        on_stage("walk", {"nodes": 7, "depth": 2})
        on_stage("regime", {"contract": "corn", "regime": "squeeze", "direction": "+",
                            "basis": {"drought": {"date": "2024-05-01", "source": "NOAA"}}})
        on_stage("number", {"table": "silver_psd", "metric": "ending_stocks_mt", "value": 31400000,
                            "unit": None, "asof": "2024-02-08"})
        on_stage("chain", {"chain_id": "c1", "hops": ["a", "b"]})
        on_stage("evidence", {"node": "driver:corn:drought", "kept": 3})
        on_stage("drafting", {})
        on_stage("verified", {"strips": 2})
        return {"answer": "done", "intent": "hybrid"}

    monkeypatch.setitem(sv._STATE, "graph", _orch_graph())
    monkeypatch.setitem(sv._STATE, "store", st.InMemoryStore())
    monkeypatch.setattr(orch, "respond", fake_respond)
    with TestClient(sv.app).stream("GET", "/v1/respond/stream", params={"question": "q"}) as r:
        text = "".join(chunk for chunk in r.iter_text())
    frames = [b for b in text.split("\n\n") if b.startswith("event: stage")]
    kinds = set()
    for f in frames:
        lines = f.split("\n")
        assert len(lines) == 2 and lines[1].startswith("data: ")       # exactly event: + data:, no splits
        kinds.add(json.loads(lines[1][len("data: "):])["stage"])
    assert set(PINNED) <= kinds


# ── 9. POST /v1/respond stays a silent single-shot JSON contract ────────────────────────────────────
def test_post_respond_passes_no_on_stage_and_returns_the_payload_verbatim(monkeypatch):
    """Invariant 2 at the route: POST must not stream, and the new emitters must not change its body."""
    from fastapi.testclient import TestClient

    body = {"answer": "note", "structured": {"tldr": "t"}, "asof": "2026-01-01", "citations": [],
            "contracts": ["arabica_coffee"], "intent": "reasoning", "model": "m",
            "trace": {"graph_version": "gv1"}}
    seen: dict = {}

    def fake_respond(query, *, graph, asof=None, session_id=None, **kw):
        seen.update(kw)
        seen["_called"] = True
        return body

    monkeypatch.setitem(sv._STATE, "graph", _orch_graph())
    monkeypatch.setitem(sv._STATE, "store", st.InMemoryStore())
    monkeypatch.setattr(orch, "respond", fake_respond)
    r = TestClient(sv.app).post("/v1/respond", json={"question": "why is arabica bullish"})
    assert r.status_code == 200
    assert seen.get("_called") and seen.get("on_stage") is None       # never wired -> strict no-op inside
    assert r.json() == body                                          # body relayed verbatim


def test_post_and_stream_produce_the_same_payload_for_the_same_turn():
    """The end-to-end statement of invariant 2, at the orchestrator (where the payload is produced): the
    POST lane (on_stage=None) and the SSE lane (on_stage wired) return the SAME answer."""
    post_like = _turn("reasoning", on_stage=None)
    events, cb = _capture()
    stream_like = _turn("reasoning", on_stage=cb)
    assert [s for s, _ in events]                                    # the SSE lane really did emit
    assert _strip(post_like)["answer"] == _strip(stream_like)["answer"]
    assert _strip(post_like)["structured"] == _strip(stream_like)["structured"]


# ── 10. no PII / evidence prose in any stage payload ────────────────────────────────────────────────
@pytest.mark.parametrize("kind", ["reasoning", "hybrid"])
def test_no_evidence_prose_rides_in_any_stage_payload(kind):
    kw = {"numbers_client": _numbers_client(), "query_fn": _query_fn} if kind != "reasoning" else {}
    events, cb = _capture()
    out = _turn(kind, on_stage=cb, **kw)
    # the sentinel really IS in this turn's retrieved evidence — otherwise the assertion below is vacuous
    assert PROSE in json.dumps(out.get("evidence", []), default=str)
    blob = json.dumps([(s, i) for s, i in events if s in PINNED], default=str)
    assert PROSE not in blob, "an emitter leaked retrieved document text into the feed"
    assert "s3://" not in blob, "an emitter leaked a source_key into the feed"


def test_walk_regime_evidence_payloads_are_slugs_numbers_and_dates_only():
    """Positive statement of invariant 4: every value in a new payload is a slug, a count or a date —
    nothing free-form enough to carry a document."""
    events, cb = _capture()
    _ground_with_firing(cb)
    _turn("reasoning", on_stage=cb)
    for stage, info in [e for e in events if e[0] in ("walk", "regime", "evidence", "verified", "plan")]:
        for v in json.loads(json.dumps(info, default=str)).values():
            flat = v if isinstance(v, str) else json.dumps(v)
            assert len(flat) < 400, f"{stage} carries an implausibly long field: {flat[:80]}"
