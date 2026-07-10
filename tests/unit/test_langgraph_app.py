"""LangGraph conductor — the conditional intent branch routes to the right node (mocked; no spend)."""
from __future__ import annotations

import types

import pytest

pytest.importorskip("langgraph")


def _lg_runtime_ok() -> bool:
    """The installed langgraph 0.1.9 has a pregel/langchain-core version-mismatch bug that fails even a trivial
    graph at invoke time. Probe it; if broken, skip here (orchestrator.respond covers the same branch logic)."""
    try:
        from typing import TypedDict

        from langgraph.graph import END, StateGraph

        class _S(TypedDict, total=False):
            x: int

        gg = StateGraph(_S)
        gg.add_node("a", lambda s: {"x": 1})
        gg.set_entry_point("a")
        gg.add_edge("a", END)
        gg.compile().invoke({})
        return True
    except Exception:  # noqa: BLE001
        return False


if not _lg_runtime_ok():
    pytest.skip("installed langgraph runtime is broken (0.1.9 pregel bug); orchestrator.respond covers the "
                "branch logic — upgrade langgraph (see the [serve] extra) to enable these.",
                allow_module_level=True)

from leviathan.causal import schema as cs  # noqa: E402
from leviathan.graphrag import graph as g  # noqa: E402
from leviathan.graphrag import langgraph_app as lg  # noqa: E402


def _graph():
    corn = cs.CausalContract(contract="corn", aliases=["maize"],
                             drivers=[cs.Driver(id="drought", type="hazard", sign="+", mechanism="m")])
    return g.CausalGraph({"corn": corn}, silver=set())


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
        _rs([types.SimpleNamespace(type="tool_use", name="lookup_number", id="t1",
                                   input={"table": "silver_psd", "metric": "ending_stocks_mt",
                                          "commodity": "corn_cbot", "period": "2023"})], "tool_use"),
        _rs([types.SimpleNamespace(type="text", text="US corn ending stocks were 31,400,000 MT.")], "end_turn")])


def _query_fn(sql):
    return [{"value": "31400000", "knowledge_date": "2024-02-08"}]


def _reason_call(system, user, *, model, tool):
    return {"tldr": "x", "mechanism": "y", "diagram_mermaid": "", "sources": []}


def _retrieve(q, node, *, k, asof=None, near=None):
    return [{"date": "2024-01-01", "source": "usda_wasde", "source_key": f"s3://{node}", "text": "note"}]


def _force(kind):
    return lambda q, call=None: {"intent": kind, "needs_numbers": kind != "reasoning",
                                 "needs_reasoning": kind != "numbers_only"}


def test_langgraph_routes_numbers_branch():
    out = lg.run("what were US corn ending stocks", asof="2024-06-01", classify=_force("numbers_only"),
                 numbers_client=_numbers_client(), query_fn=_query_fn)
    assert out["intent"] == "numbers_only" and out["evidence"] == [] and out["number_calls"]


def test_langgraph_routes_reasoning_branch():
    out = lg.run("why is corn bullish on drought", graph=_graph(), asof="2024-06-01",
                 classify=_force("reasoning"), call=_reason_call, retrieve=_retrieve)
    assert out["intent"] == "reasoning" and out["number_calls"] == []
    assert "[E1]" not in out["answer"]                      # citations v2: no parallel footer numbering
