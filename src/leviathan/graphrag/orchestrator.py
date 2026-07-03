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


def run_reasoning(query: str, asof: str, *, graph, call=None, retrieve=None, model: str = an.SONNET,
                  planner: str | None = None) -> dict:
    out = an.answer(query, graph=graph, asof=asof, call=call, retrieve=retrieve, model=model, planner=planner)
    out["intent"] = "reasoning"
    out.setdefault("number_calls", [])
    out["asof"] = asof
    return out


def run_hybrid(query: str, asof: str, *, graph, call=None, retrieve=None, model: str = an.SONNET,
               client=None, numbers_model: str = na.HAIKU, query_fn=None, planner: str | None = None) -> dict:
    nums = na.answer_numbers(query, asof, client=client, model=numbers_model, query_fn=query_fn)
    calls = nums.get("calls", [])
    out = an.answer(query, graph=graph, asof=asof, call=call, retrieve=retrieve, model=model,
                    extra_context=_numbers_block(calls), extra_number_calls=calls, planner=planner)
    out["intent"] = "hybrid"
    out["number_calls"] = calls
    out["asof"] = asof
    return out


def contracts_for_driver(graph, driver_id: str, prefer: str = "") -> list[str]:
    """The tracked contracts whose causal DAG carries this driver — the event-rooted cascade seeds. The
    event's own commodity (when resolved) leads so the walk starts where the shock landed."""
    cids = [cid for cid, c in graph.contracts.items() if any(d.id == driver_id for d in c.drivers)]
    if prefer and prefer in cids:
        cids = [prefer] + [c for c in cids if c != prefer]
    elif prefer and prefer in graph.contracts:
        cids = [prefer] + cids
    return cids[:2]


def run_live(query: str, asof: str, *, graph, call=None, retrieve=None, model: str = an.SONNET,
             planner: str | None = None, gather=None, extract=None) -> dict:
    """The section-7.1 live branch: fetch trusted headlines -> typed LiveEvents -> event-rooted cascade.
    Returns a full result dict; when NO verified event is found it degrades to normal reasoning with an
    explicit live-check note (never a silently stale answer). `gather`/`extract` injectable for tests."""
    from leviathan.graphrag.news import extract_live as nx
    from leviathan.graphrag.news import fetch as nf
    gather = gather or nf.gather
    extract = extract or nx.extract_events
    items = gather(_live_search_terms(query, graph))
    nf.snapshot(items)                                             # audit copy (best-effort, never blocks)
    events = extract(items, call=call or an._call_opus, graph=graph) if items else []
    if not events:
        res = run_reasoning(query, asof, graph=graph, call=call, retrieve=retrieve, model=model, planner=planner)
        res["answer"] += ("\n\n_Live check: no verified shock headline from trusted sources at answer time; "
                          "the analysis above rests on the dated archive._")
        res["live_events"] = []
        return res
    ev0 = events[0]
    seeds = contracts_for_driver(graph, ev0.driver_id, prefer=ev0.commodity) if ev0.driver_id else (
        [ev0.commodity] if ev0.commodity in graph.contracts else [])
    now = items[0].get("fetched_at", "") if items else ""
    block = nx.live_context_block(events, now)
    kw = dict(graph=graph, asof=asof, call=call, retrieve=retrieve, model=model,
              extra_context=block, planner=planner)
    if seeds:
        kw.update(route_fn=lambda q, g: seeds, focus_driver=ev0.driver_id)
    out = an.answer(query, **kw)
    header = "**Live context** (external, fetched " + (now or "now") + "): " + "; ".join(
        f"[{e.source}] {e.summary}" for e in events) + \
        "\n\n_Live headlines are context only - the cascade below cites dated corpus evidence._\n\n"
    out["answer"] = reg.sanitize(header) + (out.get("answer") or "")
    out["intent"] = "live"
    out.setdefault("number_calls", [])
    out["asof"] = asof
    out["live_events"] = [e.model_dump() for e in events]
    return out


def _live_search_terms(query: str, graph) -> list[str]:
    """Search terms for the site-scoped providers: shock keywords found IN the query (else the default
    policy probes from news_sources.yaml) x the query's commodity (word-boundary, incl. head nouns)."""
    from leviathan.graphrag import harvest as hv
    from leviathan.graphrag.news import extract_live as nx
    from leviathan.graphrag.news import fetch as nf
    cfg = nf.news_cfg()
    km = hv.build_matcher([str(k) for k in (cfg.get("keywords") or [])])
    kws = (km.findall(query) if km else []) or [str(k) for k in (cfg.get("default_probe_keywords") or [])][:3]
    cm, _ = nx._commodity_matcher(graph)
    hits = cm.findall(query) if cm else []
    comm = hits[0] if hits else ""
    terms = [f"{k} {comm}".strip() for k in kws[:3]]
    return [t for t in terms if t] or [query[:80]]


def respond(query: str, *, graph, asof: Optional[str] = None, call=None, retrieve=None, model: str = an.SONNET,
            numbers_client=None, numbers_model: str = na.HAIKU, query_fn=None, classify=None,
            planner: str | None = None) -> dict:
    """Classify the query's intent, run the matching branch, and return one fused answer + unified citations.
    `asof` defaults to today. The reasoning/hybrid branches default to the L2 deterministic grounded-subgraph
    walk (v1.1 reached judge parity with one-hop at 0/30 register leaks, and the roadmap — driver-slice
    coverage, regime firing, agentic planner — builds on it). Resolution: explicit `planner` arg wins, then
    the GRAPHRAG_PLANNER env var, then 'l2'; pass 'onehop' (or set GRAPHRAG_PLANNER=onehop) to fall back to
    single-contract retrieval. Inject `classify`/`call`/`retrieve`/`numbers_client`/`query_fn` for tests."""
    import os
    planner = planner or os.environ.get("GRAPHRAG_PLANNER", "l2")
    asof = asof or _today()
    # Live branch (section 7.1) — PIT KILL-SWITCH FIRST: a past as-of can never reach the news agent,
    # so backtested answers are physically unable to see today's headlines (ISO strings compare safely).
    if it.is_live(query) and asof >= _today():
        res = run_live(query, asof, graph=graph, call=call, retrieve=retrieve, model=model, planner=planner)
        res["intent_decision"] = {"intent": res["intent"], "live_checked": True}
        return res
    decided = (classify or it.classify_intent)(query, call=call)
    kind = decided["intent"]
    if kind == "numbers_only":
        res = run_numbers_only(query, asof, client=numbers_client, model=numbers_model, query_fn=query_fn)
    elif kind == "hybrid":
        res = run_hybrid(query, asof, graph=graph, call=call, retrieve=retrieve, model=model,
                         client=numbers_client, numbers_model=numbers_model, query_fn=query_fn, planner=planner)
    else:
        res = run_reasoning(query, asof, graph=graph, call=call, retrieve=retrieve, model=model, planner=planner)
    res["intent_decision"] = decided
    return res
