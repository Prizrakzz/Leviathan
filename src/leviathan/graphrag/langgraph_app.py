"""LangGraph conductor for the serving orchestrator (Phase 5, WS-C).

A THIN wrapper: ``classify`` -> conditional edge -> one of {``numbers`` | ``reasoning`` | ``hybrid``} -> END,
where each node is a one-line call into orchestrator.py. LangGraph provides the conditional branch (and is the
substrate for future streaming / checkpointed session memory); the orchestrator functions stay framework-neutral
so this is swappable, not load-bearing. The langgraph import is LAZY so the package doesn't hard-depend on it.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from leviathan.graphrag import intent as it
from leviathan.graphrag import orchestrator as orch


def build_app(*, classify=None):
    """Compile the intent-branch graph. `classify` overridable for tests (force an intent without an LLM)."""
    from typing import TypedDict

    from langgraph.graph import END, StateGraph

    class State(TypedDict, total=False):
        query: str
        asof: Optional[str]
        graph: Any
        call: Any
        retrieve: Any
        model: str
        numbers_client: Any
        numbers_model: str
        query_fn: Any
        intent: str
        result: dict

    _classify = classify or it.classify_intent

    def classify_node(s: dict) -> dict:
        return {"intent": _classify(s["query"], call=s.get("call"))["intent"],
                "asof": s.get("asof") or _dt.date.today().isoformat()}

    def numbers_node(s: dict) -> dict:
        return {"result": orch.run_numbers_only(s["query"], s["asof"], client=s.get("numbers_client"),
                                                model=s.get("numbers_model", orch.na.HAIKU), query_fn=s.get("query_fn"))}

    def reasoning_node(s: dict) -> dict:
        return {"result": orch.run_reasoning(s["query"], s["asof"], graph=s.get("graph"), call=s.get("call"),
                                            retrieve=s.get("retrieve"), model=s.get("model", orch.an.SONNET))}

    def hybrid_node(s: dict) -> dict:
        return {"result": orch.run_hybrid(s["query"], s["asof"], graph=s.get("graph"), call=s.get("call"),
                                         retrieve=s.get("retrieve"), model=s.get("model", orch.an.SONNET),
                                         client=s.get("numbers_client"),
                                         numbers_model=s.get("numbers_model", orch.na.HAIKU), query_fn=s.get("query_fn"))}

    g = StateGraph(State)
    g.add_node("classify", classify_node)
    g.add_node("numbers", numbers_node)
    g.add_node("reasoning", reasoning_node)
    g.add_node("hybrid", hybrid_node)
    g.set_entry_point("classify")
    g.add_conditional_edges("classify", lambda s: s["intent"],
                            {"numbers_only": "numbers", "reasoning": "reasoning", "hybrid": "hybrid"})
    for node in ("numbers", "reasoning", "hybrid"):
        g.add_edge(node, END)
    return g.compile()


def run(query: str, *, graph=None, asof: Optional[str] = None, call=None, retrieve=None, model: Optional[str] = None,
        numbers_client=None, numbers_model: Optional[str] = None, query_fn=None, classify=None) -> dict:
    """Invoke the compiled graph; returns the orchestrator result dict (same shape as orchestrator.respond)."""
    app = build_app(classify=classify)
    state: dict = {"query": query, "asof": asof or _dt.date.today().isoformat(), "graph": graph, "call": call,
                   "retrieve": retrieve, "numbers_client": numbers_client, "query_fn": query_fn}
    if model:
        state["model"] = model
    if numbers_model:
        state["numbers_model"] = numbers_model
    return app.invoke(state)["result"]
