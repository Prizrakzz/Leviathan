"""F0 stage attribution (latency RCA 2026-07-25): MsNumbers on the numbers_only route, and WHY MsRollup
has never been emitted.

Two of the RCA's telemetry holes:
  * `MsNumbers` was stamped only by `run_hybrid`, so it was absent on 237/237 numbers_only turns -- ~69% of
    an 8.0s numbers_only p50 (the agent leg) had no attribution at all. `run_numbers_only` now times it.
  * `MsRollup` is wired end to end (`orchestrator.respond` passes `tr.get("ms_rollup")` into the EMF block)
    yet has 0 samples in 30d. These pins show the wiring is COMPLETE and locate the gap where it actually
    is: the SYNC branch (`GRAPHRAG_ROLLUP_ASYNC=off`, which taskdef :64 sets) stamps `trace.ms_rollup`
    in-block, and `_session_writeback` returns BEFORE any rollup when there is no session -- which is every
    eval turn. Nothing to add; a second stamp would double-count the same Haiku call.
Mocked end to end (fake numbers client, injected query_fn, fake summary call). No LLM/AWS spend.
"""
from __future__ import annotations

import json
import types

from leviathan.causal import schema as cs
from leviathan.graphrag import graph as g
from leviathan.graphrag import orchestrator as orch


def _graph() -> g.CausalGraph:
    corn = cs.CausalContract(contract="corn", aliases=["maize"],
                             drivers=[cs.Driver(id="drought", type="hazard", sign="+",
                                                mechanism="dryness cuts yield")])
    return g.CausalGraph({"corn": corn}, silver=set())


# ── fakes (mirror test_orchestrator.py) ─────────────────────────────────────────────────────────────
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


def _retrieve(q, node, *, k, asof=None, near=None):
    return [{"date": "2024-01-01", "source": "usda_wasde", "source_key": f"s3://{node}",
             "text": "stocks note"}]


def _force(kind):
    return lambda q, call=None: {"intent": kind, "needs_numbers": kind in ("numbers_only", "hybrid"),
                                 "needs_reasoning": kind in ("reasoning", "hybrid")}


def _emf_docs(capsys) -> list[dict]:
    return [json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.startswith("{")]


# ── MsNumbers on the numbers_only route ─────────────────────────────────────────────────────────────
def test_numbers_only_turn_emits_ms_numbers(capsys):
    """The route the RCA could not attribute: dispatch was 31% of an 8.0s turn and the rest was dark."""
    res = orch.respond("what were US corn ending stocks", graph=_graph(), asof="2024-06-01",
                       classify=_force("numbers_only"), numbers_client=_numbers_client(),
                       query_fn=_query_fn)
    assert res["intent"] == "numbers_only"
    ms = res["trace"]["ms_numbers"]
    assert isinstance(ms, int) and ms >= 0
    assert res["trace"]["timing_ms"]["numbers"] == ms          # mirrored for the eval report
    doc = next(d for d in _emf_docs(capsys) if "TurnLatencyMs" in d)
    assert doc["MsNumbers"] == ms and doc["intent"] == "numbers_only"


def test_run_numbers_only_times_the_agent_call_itself(monkeypatch):
    """The span brackets `answer_numbers` only -- not the verifier/sanitize work around it."""
    from leviathan.graphrag.numbers import agent as na
    monkeypatch.setattr(na, "answer_numbers", lambda *a, **k: {"answer": "31,400,000 MT.", "calls": []})
    out = orch.run_numbers_only("q", "2024-06-01", graph=_graph())
    assert isinstance(out["trace"]["ms_numbers"], int) and out["trace"]["ms_numbers"] >= 0
    assert "numbers_verifier" in out["trace"]                  # pre-existing keys still ride


def test_reasoning_turn_still_omits_ms_numbers(monkeypatch, capsys):
    """No zero-fill: a route with no numbers agent must leave MsNumbers ABSENT, not 0 (which would drag
    every percentile on the metric down)."""
    monkeypatch.setenv("GRAPHRAG_PLANNER", "onehop")

    def call(system, user, *, model, tool, **_kw):
        return {"tldr": "t", "mechanism": "m", "diagram_mermaid": "", "sources": []}

    orch.respond("why is corn bullish", graph=_graph(), asof="2024-06-01", call=call,
                 retrieve=_retrieve, classify=_force("reasoning"))
    doc = next(d for d in _emf_docs(capsys) if "TurnLatencyMs" in d)
    assert "MsNumbers" not in doc


# ── MsRollup: wired, and the gap is the session-less eval lane ───────────────────────────────────────
def _summary_call(system, user, *, model, tool, **_kw):
    return {"entities": [], "thesis": "t", "open_threads": []}


def test_sync_rollup_stamp_reaches_the_emf_block(monkeypatch, capsys):
    """GRAPHRAG_ROLLUP_ASYNC=off (taskdef :64) -> `_session_writeback` times roll_summary IN-BLOCK and
    respond() forwards the same trace key to EMF. The two seams compose today: nothing to add."""
    monkeypatch.setenv("GRAPHRAG_ROLLUP_ASYNC", "off")
    from leviathan.graphrag import session as ss
    res = {"intent": "reasoning", "model": "m", "answer": "a", "structured": {"tldr": "x"},
           "contracts": ["corn"], "trace": {}}
    out = orch._session_writeback(res, "q", "2024-06-01", "sess-f0", ss.InMemoryStore(), None, _graph(),
                                  _summary_call)
    ms = out["trace"]["ms_rollup"]
    assert isinstance(ms, int)                                  # SYNC branch stamps it
    monkeypatch.setattr(orch, "_respond", lambda *a, **k: out)
    orch.respond("q", graph=None)
    doc = next(d for d in _emf_docs(capsys) if "TurnLatencyMs" in d)
    assert doc["MsRollup"] == ms                                # ... and the EMF block carries it


def test_sessionless_turn_records_no_rollup(capsys):
    """The whole explanation for 0 MsRollup samples in 30d: the eval lane passes no session_id, so the
    writeback returns before roll_summary -- the metric is absent because the CALL never happens."""
    res = {"intent": "reasoning", "model": "m", "answer": "a", "structured": {"tldr": "x"},
           "contracts": ["corn"], "trace": {}}
    out = orch._session_writeback(res, "q", "2024-06-01", None, None, None, _graph(), _summary_call,
                                  ms_dispatch=2_777)
    assert "ms_rollup" not in out["trace"] and out["trace"]["ms_dispatch"] == 2_777
    assert "session" not in out
