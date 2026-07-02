"""Serving orchestrator (Phase 5) — intent branch fusing the numbers agent, the causal-reasoning answer, and
their hybrid into ONE answer with unified citations.

Framework-neutral on purpose: ``respond()`` runs WITHOUT LangGraph (``langgraph_app.py`` is a thin conductor
over these same functions, so the graph framework is swappable, not load-bearing). Branches:

  numbers_only -> the SQL agent only (no graph, no reasoner LLM) + a numbers citation footer.
  reasoning    -> answer() (graph + dated evidence), already carrying its evidence citation footer.
  hybrid       -> the SQL agent, then INJECT its numbers as an evidence block into answer(); the reasoning model
                  weaves them in and the footer merges evidence + number citations.

The same ``asof`` (point-in-time cutoff) flows to BOTH the numbers agent and evidence retrieval, so the whole
answer is leakage-consistent.
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

from leviathan.graphrag import answer as an
from leviathan.graphrag import citations as cit
from leviathan.graphrag import intent as it
from leviathan.graphrag import register as reg
from leviathan.graphrag.numbers import agent as na


def _today() -> str:
    return _dt.date.today().isoformat()


def _numbers_block(calls: list) -> str:
    body = cit.render(cit.unify(None, calls)) or "(none retrieved)"
    return "SILVER NUMBERS (observed values, as-known at asof):\n" + body


def _footer(cits) -> str:
    return ("\n\n## Sources\n" + cit.render(cits)) if cits else ""


def run_numbers_only(query: str, asof: str, *, client=None, model: str = na.HAIKU, query_fn=None) -> dict:
    out = na.answer_numbers(query, asof, client=client, model=model, query_fn=query_fn)
    cits = cit.unify(None, out.get("calls"))
    body = reg.sanitize((out.get("answer", "") + _footer(cits)).strip())   # strip leaked slugs/tokens from the numbers footer
    return {"answer": body, "intent": "numbers_only",
            "citations": [c.model_dump() for c in cits], "number_calls": out.get("calls", []),
            "evidence": [], "asof": asof, "structured": None, "contract": None}


def run_reasoning(query: str, asof: str, *, graph, call=None, retrieve=None, model: str = an.SONNET) -> dict:
    out = an.answer(query, graph=graph, asof=asof, call=call, retrieve=retrieve, model=model)
    out["intent"] = "reasoning"
    out.setdefault("number_calls", [])
    out["asof"] = asof
    return out


def run_hybrid(query: str, asof: str, *, graph, call=None, retrieve=None, model: str = an.SONNET,
               client=None, numbers_model: str = na.HAIKU, query_fn=None) -> dict:
    nums = na.answer_numbers(query, asof, client=client, model=numbers_model, query_fn=query_fn)
    calls = nums.get("calls", [])
    out = an.answer(query, graph=graph, asof=asof, call=call, retrieve=retrieve, model=model,
                    extra_context=_numbers_block(calls), extra_number_calls=calls)
    out["intent"] = "hybrid"
    out["number_calls"] = calls
    out["asof"] = asof
    return out


def respond(query: str, *, graph, asof: Optional[str] = None, call=None, retrieve=None, model: str = an.SONNET,
            numbers_client=None, numbers_model: str = na.HAIKU, query_fn=None, classify=None) -> dict:
    """Classify the query's intent, run the matching branch, and return one fused answer + unified citations.
    `asof` defaults to today. Inject `classify`/`call`/`retrieve`/`numbers_client`/`query_fn` for tests."""
    asof = asof or _today()
    decided = (classify or it.classify_intent)(query, call=call)
    kind = decided["intent"]
    if kind == "numbers_only":
        res = run_numbers_only(query, asof, client=numbers_client, model=numbers_model, query_fn=query_fn)
    elif kind == "hybrid":
        res = run_hybrid(query, asof, graph=graph, call=call, retrieve=retrieve, model=model,
                         client=numbers_client, numbers_model=numbers_model, query_fn=query_fn)
    else:
        res = run_reasoning(query, asof, graph=graph, call=call, retrieve=retrieve, model=model)
    res["intent_decision"] = decided
    return res
