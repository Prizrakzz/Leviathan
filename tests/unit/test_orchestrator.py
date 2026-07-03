"""Serving orchestrator — the intent branch fusing numbers + reasoning (mocked; no S3/Athena/LLM spend)."""
from __future__ import annotations

import types

from leviathan.causal import schema as cs
from leviathan.graphrag import graph as g
from leviathan.graphrag import orchestrator as orch


def _graph() -> g.CausalGraph:
    coffee = cs.CausalContract(contract="arabica_coffee", aliases=["arabica"],
                               drivers=[cs.Driver(id="frost", type="hazard", sign="+", mechanism="frost kills trees")])
    corn = cs.CausalContract(contract="corn", aliases=["maize"],
                             drivers=[cs.Driver(id="drought", type="hazard", sign="+", mechanism="dryness cuts yield")])
    return g.CausalGraph({"arabica_coffee": coffee, "corn": corn}, silver=set())


# --- fake Anthropic client that drives the numbers agent (tool_use -> text) ---
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
        _rs([_tu({"table": "silver_psd", "metric": "ending_stocks_mt", "commodity": "corn_cbot", "period": "2023"})], "tool_use"),
        _rs([_tx("US corn ending stocks were 31,400,000 MT.")], "end_turn")])


def _query_fn(sql):
    return [{"value": "31400000", "knowledge_date": "2024-02-08"}]


def _reason_call(system, user, *, model, tool):
    _reason_call.user = user
    return {"tldr": "x", "mechanism": "y", "diagram_mermaid": "", "sources": []}


def _retrieve(q, node, *, k, asof=None, near=None):
    return [{"date": "2024-01-01", "source": "usda_wasde", "source_key": f"s3://{node}", "text": "stocks note"}]


def _force(kind):
    return lambda q, call=None: {"intent": kind, "needs_numbers": kind in ("numbers_only", "hybrid"),
                                 "needs_reasoning": kind in ("reasoning", "hybrid")}


def test_numbers_only_runs_numbers_skips_graph():
    out = orch.respond("what were US corn ending stocks", graph=_graph(), asof="2024-06-01",
                       classify=_force("numbers_only"), numbers_client=_numbers_client(), query_fn=_query_fn)
    assert out["intent"] == "numbers_only"
    assert out["evidence"] == [] and out["number_calls"]                 # numbers ran; the graph path did NOT
    assert "## Sources" in out["answer"] and "[N1]" in out["answer"]
    assert out["citations"][0]["kind"] == "number"


def test_reasoning_runs_graph_skips_numbers():
    out = orch.respond("why is arabica bullish on a frost", graph=_graph(), asof="2024-06-01",
                       classify=_force("reasoning"), call=_reason_call, retrieve=_retrieve)
    assert out["intent"] == "reasoning" and out["number_calls"] == []
    assert out["citations"][0]["kind"] == "evidence"                  # machine citations intact (v2: the
    assert "[E1]" not in out["answer"]                                # parallel [E1] footer no longer renders)


def test_hybrid_injects_numbers_and_unifies_citations():
    out = orch.respond("given low ending stocks is corn a buy", graph=_graph(), asof="2024-06-01",
                       classify=_force("hybrid"), call=_reason_call, retrieve=_retrieve,
                       numbers_client=_numbers_client(), query_fn=_query_fn)
    assert out["intent"] == "hybrid"
    assert {c["kind"] for c in out["citations"]} == {"evidence", "number"}   # machine list spans both
    assert "SILVER NUMBERS" in _reason_call.user                             # numbers injected into the reasoning prompt
    assert "[E1]" not in out["answer"]                                       # v2: no parallel footer numbering
