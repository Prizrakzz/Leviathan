"""D-W6.1-0 stage telemetry + D-W6.1-1 async roll_summary (orchestrator).

No S3/Athena/LLM spend: the reasoning/synthesis/dispatch/numbers/rollup calls are all injected fakes.
Covers: perf_counter stage timers surfaced via trace.timing_ms + the EMF block, the cited-vs-injected
[N] counter, AnswerChars, and the fire-and-forget rollup (both the env off-switch synchronous variant
and the default async variant, joined deterministically via the `_rollup_observer` hook)."""
from __future__ import annotations

import json
import threading
import types

from leviathan.causal import schema as cs
from leviathan.graphrag import graph as g
from leviathan.graphrag import orchestrator as orch


def _graph() -> g.CausalGraph:
    corn = cs.CausalContract(contract="corn", aliases=["maize"],
                             drivers=[cs.Driver(id="drought", type="hazard", sign="+",
                                                mechanism="dryness cuts yield")])
    return g.CausalGraph({"corn": corn}, silver=set())


# ── injected fakes (mirror test_orchestrator.py) ────────────────────────────────────────────────────
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


class FakeAnthropic:
    def __init__(self, q):
        self.q = list(q)
        self.messages = _Msgs(self)


def _numbers_client():
    return FakeAnthropic([
        _rs([_tu({"table": "silver_psd", "metric": "ending_stocks_mt", "commodity": "corn_cbot",
                  "period": "2023"})], "tool_use"),
        _rs([_tx("US corn ending stocks were 31,400,000 MT.")], "end_turn")])


def _query_fn(sql):
    return [{"value": "31400000", "knowledge_date": "2024-02-08"}]


def _reason_call(system, user, *, model, tool, **_kw):
    return {"tldr": "x", "mechanism": "y", "diagram_mermaid": "", "sources": []}


def _dual_call(system, user, *, model, tool, **_kw):
    """Serves BOTH the dispatch planner (set_plan) and the synthesis (emit_answer), keyed on tool name,
    so a classify=None turn exercises the real MsDispatch span."""
    if tool.get("name") == "set_plan":
        return {"steps": ["reasoning"], "contracts": ["corn"]}
    return {"tldr": "x", "mechanism": "y", "diagram_mermaid": "", "sources": []}


def _retrieve(q, node, *, k, asof=None, near=None):
    return [{"date": "2024-01-01", "source": "usda_wasde", "source_key": f"s3://{node}",
             "text": "stocks note"}]


def _force(kind):
    return lambda q, call=None: {"intent": kind, "needs_numbers": kind in ("numbers_only", "hybrid"),
                                 "needs_reasoning": kind in ("reasoning", "hybrid")}


def _capture_emf(monkeypatch) -> dict:
    from leviathan.graphrag import emf
    captured = {}
    monkeypatch.setattr(emf, "emit",
                        lambda metrics, *, dimensions=None, units=None: captured.update(metrics))
    return captured


def _stub_embed(monkeypatch):
    """The L2 walk (planner.grounded_subgraph) embeds the query + mechanisms; the sentence-transformers
    backend is not installed in this unit env, so stub evidence.embed with a constant vector (cosine is
    well-defined and every node clears tau -> the walk reaches synthesis deterministically)."""
    from leviathan.graphrag import evidence as ev
    monkeypatch.setattr(ev, "embed", lambda texts, **kw: [[1.0, 0.0, 0.0, 0.0] for _ in texts])


_TIMING_KEYS = {"total", "fill", "rest", "dispatch", "numbers", "synth_llm", "quantify", "rollup"}


# ── W6.1-0: stage timers populate trace.timing_ms on a stubbed turn ─────────────────────────────────
def test_stage_timers_populate_timing_ms(monkeypatch):
    """A real _respond reasoning turn (classify=None -> dispatch runs) stamps dispatch + synth_llm as ints
    into trace.timing_ms; stages that did NOT run (numbers/quantify/rollup) stay None -- no zero-fill."""
    _stub_embed(monkeypatch)
    res = orch.respond("why is corn bullish", graph=_graph(), asof="2024-06-01",
                       call=_dual_call, retrieve=_retrieve)
    assert res["intent"] == "reasoning"
    tm = res["trace"]["timing_ms"]
    assert set(tm) == _TIMING_KEYS
    assert isinstance(tm["total"], int)
    assert isinstance(tm["dispatch"], int) and tm["dispatch"] >= 0        # MsDispatch span ran
    assert isinstance(tm["synth_llm"], int) and tm["synth_llm"] >= 0      # MsSynthLLM span ran
    assert tm["numbers"] is None and tm["quantify"] is None and tm["rollup"] is None
    # the raw ms_* keys agree with the mirrored timing_ms
    assert res["trace"]["ms_dispatch"] == tm["dispatch"]
    assert res["trace"]["ms_synth_llm"] == tm["synth_llm"]


def test_hybrid_turn_populates_ms_numbers(monkeypatch):
    """The hybrid path threads the numbers-agent worker duration into trace as MsNumbers; the L2 synthesis
    is still timed on the same turn."""
    _stub_embed(monkeypatch)
    res = orch.respond("given low ending stocks is corn a buy", graph=_graph(), asof="2024-06-01",
                       classify=_force("hybrid"), call=_reason_call, retrieve=_retrieve,
                       numbers_client=_numbers_client(), query_fn=_query_fn)
    assert res["intent"] == "hybrid"
    tm = res["trace"]["timing_ms"]
    assert isinstance(tm["numbers"], int) and tm["numbers"] >= 0
    assert res["trace"]["ms_numbers"] == tm["numbers"]
    assert isinstance(tm["synth_llm"], int)
    assert tm["dispatch"] is None            # classify given -> dispatch skipped, absent (no zero-fill)


# ── W6.1-0: the EMF payload carries the new keys ────────────────────────────────────────────────────
def test_emf_payload_contains_stage_keys(monkeypatch):
    captured = _capture_emf(monkeypatch)
    canned = {"intent": "hybrid", "model": "m",
              "answer": "pace high [N1] and stocks fell [N2]; see [N1] again.",
              "trace": {"ms_dispatch": 120, "ms_numbers": 3400, "ms_synth_llm": 60000,
                        "ms_quantify": 800, "ms_rollup": 250, "injected_n": 5}}
    monkeypatch.setattr(orch, "_respond", lambda *a, **k: canned)
    res = orch.respond("q", graph=None)
    assert captured["MsDispatch"] == 120 and captured["MsNumbers"] == 3400
    assert captured["MsSynthLLM"] == 60000 and captured["MsQuantify"] == 800
    assert captured["MsRollup"] == 250
    assert captured["InjectedN"] == 5
    assert captured["CitedN"] == 2                          # {N1, N2} distinct; the repeated [N1] not doubled
    assert captured["AnswerChars"] == len(canned["answer"])
    # mirrored into trace.timing_ms for eval visibility
    assert res["trace"]["timing_ms"]["dispatch"] == 120
    assert res["trace"]["timing_ms"]["synth_llm"] == 60000


def test_emf_omits_stages_that_did_not_run(monkeypatch):
    """A stage that did not run passes None -> the real emf.emit drops it. CitedN/InjectedN keep the
    0-semantics of CascadeFired (always present)."""
    captured = _capture_emf(monkeypatch)
    canned = {"intent": "numbers_only", "model": "m", "answer": "no handles here", "trace": {}}
    monkeypatch.setattr(orch, "_respond", lambda *a, **k: canned)
    orch.respond("q", graph=None)
    assert captured["MsDispatch"] is None and captured["MsNumbers"] is None
    assert captured["MsSynthLLM"] is None and captured["MsQuantify"] is None
    assert captured["MsRollup"] is None
    assert captured["CitedN"] == 0 and captured["InjectedN"] == 0


def test_emf_json_line_drops_none_stage_keys(monkeypatch, capsys):
    """End-to-end through the REAL emf.emit: absent stages are omitted from the emitted JSON (no zero-fill)
    while the stages that ran + the cited/injected counters are present."""
    canned = {"intent": "reasoning", "model": "m", "answer": "cite [N1] here",
              "trace": {"ms_synth_llm": 5000, "injected_n": 1}}
    monkeypatch.setattr(orch, "_respond", lambda *a, **k: canned)
    orch.respond("q", graph=None)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("{")]
    doc = json.loads(lines[-1])
    assert doc["MsSynthLLM"] == 5000
    assert "MsDispatch" not in doc and "MsNumbers" not in doc and "MsQuantify" not in doc
    assert "MsRollup" not in doc                            # rollup did not run -> dropped
    assert doc["CitedN"] == 1 and doc["InjectedN"] == 1
    assert doc["AnswerChars"] == len(canned["answer"])


# ── W6.1-0: cited-vs-injected [N] counting on a synthetic answer with known handles ─────────────────
def test_cited_vs_injected_counting(monkeypatch):
    captured = _capture_emf(monkeypatch)
    # 4 distinct cited handles (N1,N2,N3,N10); N2 repeats; a bare "[N" and an [X1] must NOT count
    ans = "a [N1] b [N2] c [N3] d [N2] e [N10] f bare-[N g [X1]"
    canned = {"intent": "hybrid", "model": "m", "answer": ans, "trace": {"injected_n": 12}}
    monkeypatch.setattr(orch, "_respond", lambda *a, **k: canned)
    orch.respond("q", graph=None)
    assert captured["CitedN"] == 4
    assert captured["InjectedN"] == 12                     # denominator = rows injected into the prompt
    assert captured["CitedNSolitary"] == 4                 # ...the pre-D-HP series, unchanged on this shape


def test_cited_n_counts_grouped_citations_and_keeps_the_old_series_beside_it(monkeypatch):
    """D-HP-20 (H2). `[N13, N14]` is TWO citations and the shipped solitary regex saw ZERO of them, so the
    cited-vs-injected ratio would have RISEN across the D-HP boundary for a reason that is pure grammar --
    handle-prose converts grouped citations into solitary slot handles with no behaviour change at all.
    `CitedN` is the honest count now; `CitedNSolitary` carries the pre-D-HP arithmetic byte-identical
    beside it, so the historical panel series has a live continuation instead of a silent redefinition
    (the widget restatement itself is the infra owner's item, R14)."""
    captured = _capture_emf(monkeypatch)
    ans = "crush [N13, N14] and stocks [N2]; again [N2]; sibling [N1, N1b]; not a handle [X1]"
    canned = {"intent": "hybrid", "model": "m", "answer": ans, "trace": {"injected_n": 20}}
    monkeypatch.setattr(orch, "_respond", lambda *a, **k: canned)
    orch.respond("q", graph=None)
    assert captured["CitedN"] == 5                         # N13, N14, N2, N1, N1b -- ROWS, not tokens
    assert captured["CitedNSolitary"] == 1                 # ...what the old regex saw: [N2] alone


# -- A6: the NOT-firing counters (NUMBERS_FIRING_PLAN section 3) -------------------------------------
# The dashboard could see everything the engine DID and nothing it declined to do. CascadeFired=0 was one
# undifferentiated bucket; these split it and make the decline lanes queryable outside the eval harness.
def _emf_via(monkeypatch, canned) -> dict:
    captured = _capture_emf(monkeypatch)
    monkeypatch.setattr(orch, "_respond", lambda *a, **k: canned)
    orch.respond("q", graph=None)
    return captured


def test_dark_ref_nodes_rides_the_engine_written_trace(monkeypatch):
    """DarkRefNodes is ENGINE-written (cascade counts nodes whose silver ref mapped to nothing) and only
    READ here -- the orchestrator can never invent a number the walk did not produce."""
    captured = _emf_via(monkeypatch, {"intent": "reasoning", "model": "m", "answer": "a",
                                      "trace": {"quantify_dark_refs": 3}})
    assert captured["DarkRefNodes"] == 3


def test_dark_ref_nodes_absent_when_the_walk_never_quantified(monkeypatch):
    """A turn with no quantify seam passes None -> the metric is ABSENT (the FloorTurns precedent). Zero-
    filling it would let every numbers_only and social turn dilute the very rate it exists to measure."""
    captured = _emf_via(monkeypatch, {"intent": "numbers_only", "model": "m", "answer": "a", "trace": {}})
    assert captured["DarkRefNodes"] is None


def test_dark_ref_nodes_zero_is_emitted_not_dropped(monkeypatch):
    """0 dark refs on a turn that DID quantify is a real measurement (the walk grounded and every ref
    mapped) and must survive -- only the absent key means 'not measured'."""
    captured = _emf_via(monkeypatch, {"intent": "hybrid", "model": "m", "answer": "a",
                                      "trace": {"quantify_dark_refs": 0}})
    assert captured["DarkRefNodes"] == 0


def test_agent_zero_call_turns_splits_declined_from_never_ran(monkeypatch):
    """The split MsNumbers cannot make: the agent RAN and looked nothing up (1) vs the agent ran and looked
    something up (0) vs the agent never ran at all (absent)."""
    declined = _emf_via(monkeypatch, {"intent": "hybrid", "model": "m", "answer": "a", "number_calls": [],
                                      "trace": {"ms_numbers": 900}})
    assert declined["AgentZeroCallTurns"] == 1
    fired = _emf_via(monkeypatch, {"intent": "hybrid", "model": "m", "answer": "a",
                                   "number_calls": [{"query": {"table": "silver_psd"}, "rows": [{"value": 1}]}],
                                   "trace": {"ms_numbers": 900}})
    assert fired["AgentZeroCallTurns"] == 0
    never = _emf_via(monkeypatch, {"intent": "reasoning", "model": "m", "answer": "a", "trace": {}})
    assert never["AgentZeroCallTurns"] is None


def test_positioning_fired_on_an_agent_lookup(monkeypatch):
    captured = _emf_via(monkeypatch, {
        "intent": "numbers_only", "model": "m", "answer": "a",
        "number_calls": [{"query": {"table": "silver_cot", "metric": "mm_net"},
                          "rows": [{"value": "12345"}], "status": "ok"}],
        "trace": {"ms_numbers": 10}})
    assert captured["PositioningFired"] == 1


def test_positioning_not_fired_on_an_errored_or_empty_cot_lookup(monkeypatch):
    """'Reached the panel' means ROWS reached the panel. An errored or empty lookup put no number in front
    of a reader, and counting it would report the anti-correlation as fixed while nothing changed."""
    for call in ({"query": {"table": "silver_cot"}, "rows": [], "status": "ok"},
                 {"query": {"table": "silver_cot"}, "rows": [{"value": "1"}], "status": "error"}):
        captured = _emf_via(monkeypatch, {"intent": "numbers_only", "model": "m", "answer": "a",
                                          "number_calls": [call], "trace": {"ms_numbers": 10}})
        assert captured["PositioningFired"] == 0


def test_positioning_fired_on_a_cascade_leg(monkeypatch):
    """The cascade lane counts too: a positioning ref that reaches the panel as a pace leg is a CFTC number
    in front of a reader whether or not the agent ever looked one up."""
    captured = _emf_via(monkeypatch, {
        "intent": "reasoning", "model": "m", "answer": "a",
        "trace": {"quantify_pace": [{"table": "silver_cot", "metric": "mm_net", "grain": "week"}]}})
    assert captured["PositioningFired"] == 1


def test_positioning_tables_come_from_the_lint_definition():
    """One definition, so the counter can never drift from what R9/R10 actually fence."""
    from leviathan.graphrag import config_check as cc
    assert orch._positioning_tables() == tuple(cc.POSITIONING_TABLES)
    assert "silver_cot" in orch._positioning_tables()


def test_engine_firing_booleans_promoted_from_the_trace(monkeypatch):
    """pace / chain / transmission / price-leg / co-move were readable ONLY through the eval harness, so
    five engines had no production firing rate. ENGINE-written, present-iff-fired, bool'd here."""
    captured = _emf_via(monkeypatch, {"intent": "reasoning", "model": "m", "answer": "a",
                                      "trace": {"quantify_pace": [{"table": "silver_esr"}],
                                                "quantify_chain": {"hops": [1]},
                                                "quantify_transmission": {"links": [1]},
                                                "quantify_price_leg": {"commodity": "corn"},
                                                "quantify_comove": {"pair": "x"}}})
    assert captured["PaceFired"] == 1 and captured["ChainFired"] == 1
    assert captured["TransmissionFired"] == 1 and captured["PriceLegFired"] == 1
    assert captured["ComoveFired"] == 1


def test_engine_firing_booleans_zero_semantics(monkeypatch):
    """Absent trace key -> 0, never absent: these are firing RATES (the CascadeFired precedent), so the
    denominator has to be every turn."""
    captured = _emf_via(monkeypatch, {"intent": "reasoning", "model": "m", "answer": "a", "trace": {}})
    for k in ("PaceFired", "ChainFired", "TransmissionFired", "PriceLegFired", "ComoveFired",
              "PositioningFired"):
        assert captured[k] == 0


def test_a6_counters_reach_the_real_emf_json_line(monkeypatch, capsys):
    """End-to-end through the REAL emf.emit: the units map covers every new metric and the absent ones are
    dropped rather than zero-filled."""
    canned = {"intent": "hybrid", "model": "m", "answer": "a",
              "number_calls": [{"query": {"table": "silver_cot"}, "rows": [{"value": "1"}], "status": "ok"}],
              "trace": {"ms_numbers": 10, "quantify_dark_refs": 2, "quantify_pace": [{"table": "silver_cot"}]}}
    monkeypatch.setattr(orch, "_respond", lambda *a, **k: canned)
    orch.respond("q", graph=None)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("{")]
    doc = json.loads(lines[-1])
    assert doc["DarkRefNodes"] == 2 and doc["PositioningFired"] == 1 and doc["PaceFired"] == 1
    assert doc["AgentZeroCallTurns"] == 0
    names = {m["Name"]: m["Unit"] for m in doc["_aws"]["CloudWatchMetrics"][0]["Metrics"]}
    for k in ("DarkRefNodes", "AgentZeroCallTurns", "PositioningFired", "PaceFired", "ChainFired",
              "TransmissionFired", "PriceLegFired", "ComoveFired"):
        assert names[k] == "Count"                              # every new metric carries a unit


def test_positioning_scan_survives_a_trace_mutated_concurrently(monkeypatch):
    """The async roll_summary daemon writes tr['ms_rollup'] into the SAME dict this scan walks. A dict that
    grows mid-iteration raises, and the whole EMF block is fail-open -- so the cost would be a silently
    dropped metric line rather than a visible error."""
    captured = _capture_emf(monkeypatch)
    tr = {"quantify_pace": [{"table": "silver_cot"}]}

    class _Growing(dict):
        def items(self):                                        # a stand-in for the racing rollup writer
            self["ms_rollup"] = 7
            return super().items()

    canned = {"intent": "reasoning", "model": "m", "answer": "a", "trace": _Growing(tr)}
    monkeypatch.setattr(orch, "_respond", lambda *a, **k: canned)
    orch.respond("q", graph=None)
    assert captured["PositioningFired"] == 1                    # scanned to completion, metric intact


def test_a6_counters_never_break_a_turn(monkeypatch):
    """Telemetry is fail-open by construction: a malformed number_calls / trace shape must cost the metric,
    never the answer."""
    canned = {"intent": "hybrid", "model": "m", "answer": "a", "number_calls": ["not-a-dict", None],
              "trace": {"ms_numbers": 1, "quantify_pace": "not-a-list"}}
    monkeypatch.setattr(orch, "_respond", lambda *a, **k: canned)
    res = orch.respond("q", graph=None)
    assert res["answer"] == "a"


# ── W6.1-1: async roll_summary ──────────────────────────────────────────────────────────────────────
def _summary_ok(thesis="t"):
    def call(system, user, *, model, tool, **_kw):
        return {"entities": [], "thesis": thesis, "open_threads": []}
    return call


def test_rollup_sync_mode_records_ms_rollup(monkeypatch):
    """GRAPHRAG_ROLLUP_ASYNC=off restores the synchronous path: roll_summary runs inline, ms_rollup is
    timed in-block, and the state is persisted before _session_writeback returns."""
    monkeypatch.setenv("GRAPHRAG_ROLLUP_ASYNC", "off")
    from leviathan.graphrag import session as ss
    store = ss.InMemoryStore()
    seen = []

    def summary_call(system, user, *, model, tool, **_kw):
        seen.append(model)
        return {"entities": [], "thesis": "sync-thesis", "open_threads": []}

    res = {"intent": "reasoning", "answer": "a", "structured": {"tldr": "x"},
           "contracts": ["corn"], "trace": {}}
    out = orch._session_writeback(res, "q", "2024-06-01", "sess1", store, None, _graph(),
                                  summary_call, ms_dispatch=42)
    assert out["trace"]["ms_dispatch"] == 42
    assert isinstance(out["trace"]["ms_rollup"], int)          # SYNC: recorded in-block
    assert out["session"] == {"id": "sess1", "turn": 0}
    assert seen == ["claude-haiku-4-5"]                        # roll_summary ran synchronously
    assert store.load("sess1").state.summary["thesis"] == "sync-thesis"


def test_rollup_async_off_critical_path(monkeypatch):
    """Default (async on): _session_writeback returns WITHOUT waiting on the Haiku round-trip. The rollup
    thread is captured via _rollup_observer, blocked on a gate so the race is deterministic, then released
    and joined -- ms_rollup is recorded INSIDE the thread and the state lands after the join."""
    monkeypatch.delenv("GRAPHRAG_ROLLUP_ASYNC", raising=False)   # default = on
    from leviathan.graphrag import session as ss
    store = ss.InMemoryStore()
    threads = []
    monkeypatch.setattr(orch, "_rollup_observer", threads.append)
    gate = threading.Event()

    def gated_call(system, user, *, model, tool, **_kw):
        gate.wait(5)                                            # hold the rollup until the test releases it
        return {"entities": [], "thesis": "async-thesis", "open_threads": []}

    res = {"intent": "reasoning", "answer": "a", "structured": {"tldr": "x"},
           "contracts": ["corn"], "trace": {}}
    out = orch._session_writeback(res, "q", "2024-06-01", "sess2", store, None, _graph(), gated_call)
    # returned while the rollup thread is still blocked -> off the critical path
    assert out["session"] == {"id": "sess2", "turn": 0}
    assert "ms_rollup" not in out["trace"]                      # not yet: the thread has not finished
    assert len(threads) == 1 and threads[0].is_alive()
    gate.set()
    threads[0].join(timeout=5)
    assert not threads[0].is_alive()
    assert isinstance(out["trace"]["ms_rollup"], int)          # timed inside the thread
    assert store.load("sess2").state.summary["thesis"] == "async-thesis"


def test_rollup_async_default_when_env_unset(monkeypatch):
    """With the env var unset the rollup is async by default: a thread is spawned (observer fires)."""
    monkeypatch.delenv("GRAPHRAG_ROLLUP_ASYNC", raising=False)
    from leviathan.graphrag import session as ss
    store = ss.InMemoryStore()
    threads = []
    monkeypatch.setattr(orch, "_rollup_observer", threads.append)
    res = {"intent": "reasoning", "answer": "a", "structured": {"tldr": "x"},
           "contracts": ["corn"], "trace": {}}
    orch._session_writeback(res, "q", "2024-06-01", "sessD", store, None, _graph(), _summary_ok())
    assert len(threads) == 1                                    # spawned a daemon thread
    threads[0].join(timeout=5)


def test_rollup_async_failopen_on_store_error(monkeypatch):
    """A store failure inside the async rollup is swallowed -- the turn is already returned and intact,
    and the thread exits cleanly without recording ms_rollup."""
    monkeypatch.delenv("GRAPHRAG_ROLLUP_ASYNC", raising=False)
    from leviathan.graphrag import session as ss
    threads = []
    monkeypatch.setattr(orch, "_rollup_observer", threads.append)

    class BadStore(ss.InMemoryStore):
        def put_state(self, sid, st):
            raise RuntimeError("dynamo down")

    store = BadStore()
    res = {"intent": "reasoning", "answer": "a", "structured": {"tldr": "x"},
           "contracts": ["corn"], "trace": {}}
    out = orch._session_writeback(res, "q", "2024-06-01", "sess3", store, None, _graph(), _summary_ok())
    assert out["session"] == {"id": "sess3", "turn": 0}         # append_turn succeeded; writeback clean
    threads[0].join(timeout=5)
    assert not threads[0].is_alive()                            # error swallowed inside the thread
    assert "ms_rollup" not in out["trace"]                      # never recorded (put_state raised first)


def test_rollup_async_emits_standalone_emf(monkeypatch):
    """The async rollup keeps its latency observable via a standalone MsRollup EMF line carrying intent."""
    monkeypatch.delenv("GRAPHRAG_ROLLUP_ASYNC", raising=False)
    from leviathan.graphrag import emf
    from leviathan.graphrag import session as ss
    emitted = []
    monkeypatch.setattr(emf, "emit",
                        lambda metrics, *, dimensions=None, units=None: emitted.append((metrics, dimensions)))
    store = ss.InMemoryStore()
    threads = []
    monkeypatch.setattr(orch, "_rollup_observer", threads.append)
    res = {"intent": "hybrid", "answer": "a", "structured": {"tldr": "x"},
           "contracts": ["corn"], "trace": {}}
    orch._session_writeback(res, "q", "2024-06-01", "sess5", store, None, _graph(), _summary_ok())
    threads[0].join(timeout=5)
    assert any("MsRollup" in m and (d or {}).get("intent") == "hybrid" for m, d in emitted)


def test_no_session_still_stamps_ms_dispatch(monkeypatch):
    """MsDispatch is stamped at the writeback choke point even when there is no session (no store)."""
    res = {"intent": "reasoning", "answer": "a", "structured": {"tldr": "x"},
           "contracts": ["corn"], "trace": {}}
    out = orch._session_writeback(res, "q", "2024-06-01", None, None, None, _graph(), None,
                                  ms_dispatch=17)
    assert out["trace"]["ms_dispatch"] == 17
    assert "session" not in out                                 # no store -> no writeback, but timer lands
