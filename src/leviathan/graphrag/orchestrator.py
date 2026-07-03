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
                  planner: str | None = None, extra_context: str | None = None, route_fn=None) -> dict:
    out = an.answer(query, graph=graph, asof=asof, call=call, retrieve=retrieve, model=model, planner=planner,
                    extra_context=extra_context, route_fn=route_fn)
    out["intent"] = "reasoning"
    out.setdefault("number_calls", [])
    out["asof"] = asof
    return out


def run_hybrid(query: str, asof: str, *, graph, call=None, retrieve=None, model: str = an.SONNET,
               client=None, numbers_model: str = na.HAIKU, query_fn=None, planner: str | None = None,
               extra_context: str | None = None, route_fn=None) -> dict:
    nums = na.answer_numbers(query, asof, client=client, model=numbers_model, query_fn=query_fn)
    calls = nums.get("calls", [])
    extra = "\n\n".join(x for x in (extra_context, _numbers_block(calls)) if x)
    out = an.answer(query, graph=graph, asof=asof, call=call, retrieve=retrieve, model=model,
                    extra_context=extra, extra_number_calls=calls, planner=planner, route_fn=route_fn)
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
            planner: str | None = None, session_id: Optional[str] = None, session_store=None) -> dict:
    """Classify the query's intent, run the matching branch, and return one fused answer + unified citations.
    `asof` defaults to today. The reasoning/hybrid branches default to the L2 deterministic grounded-subgraph
    walk (v1.1 reached judge parity with one-hop at 0/30 register leaks, and the roadmap — driver-slice
    coverage, regime firing, agentic planner — builds on it). Resolution: explicit `planner` arg wins, then
    the GRAPHRAG_PLANNER env var, then 'l2'; pass 'onehop' (or set GRAPHRAG_PLANNER=onehop) to fall back to
    single-contract retrieval. Inject `classify`/`call`/`retrieve`/`numbers_client`/`query_fn` for tests.

    `session_id` turns on SESSION WORKING MEMORY (plan 7.5, Phases 1+2): structured state — contracts,
    focus driver, as-of, a rolling summary — carries across turns for coreference ("does IT cascade?");
    EVIDENCE never carries (each turn re-fetches under its own as-of; the one cache is keyed by exact SQL,
    which embeds its as-of). An explicit as-of always beats the carried one. GRAPHRAG_SESSIONS=off or a
    store failure degrade to stateless — memory never breaks an answer."""
    import os
    planner = planner or os.environ.get("GRAPHRAG_PLANNER", "l2")

    # ── session load (Phase 1) ────────────────────────────────────────────────────────────────────
    snap, store, ss = None, None, None
    if session_id and os.environ.get("GRAPHRAG_SESSIONS", "on") != "off":
        from leviathan.graphrag import session as ss
        store = session_store or ss.default_store()
        try:
            snap = store.load(session_id)
        except Exception:  # noqa: BLE001 — memory must never break an answer
            store = None
    state = snap.state if snap else None
    asof = asof or (state.asof_latest if state else None) or _today()   # explicit > carried > today
    sblock = ss.state_block(snap) if (snap and (snap.turns or state.contracts)) else None
    route_fn = None
    if state and state.contracts:
        def route_fn(q, g):
            """Anaphora-aware routing: an explicit commodity mention (lexical tier) always wins; a SHORT
            follow-up with no mention ("does it get worse?") resolves from prior-turn contracts — more
            reliable than letting the semantic/LLM tiers guess at a pronoun (plan 7.2)."""
            lex = an.route(q, g)
            if lex:
                return lex
            if len(q) <= 80:
                carried = [c for c in state.contracts if c in g.contracts]
                if carried:
                    return carried
            return an.route_smart(q, g)
    qfn = query_fn
    if state is not None:
        from leviathan.graphrag.numbers import query as Q
        qfn = ss.cached_query_fn(state, query_fn or Q.athena_query_fn())

    # Live branch (section 7.1) — PIT KILL-SWITCH FIRST: a past as-of can never reach the news agent,
    # so backtested answers are physically unable to see today's headlines (ISO strings compare safely).
    if it.is_live(query) and asof >= _today():
        res = run_live(query, asof, graph=graph, call=call, retrieve=retrieve, model=model, planner=planner)
        res["intent_decision"] = {"intent": res["intent"], "live_checked": True}
        return _session_writeback(res, query, asof, session_id, store, state, graph, call)
    decided = (classify or it.classify_intent)(query, call=call)
    kind = decided["intent"]
    if kind == "numbers_only":
        res = run_numbers_only(query, asof, client=numbers_client, model=numbers_model, query_fn=qfn)
    elif kind == "hybrid":
        res = run_hybrid(query, asof, graph=graph, call=call, retrieve=retrieve, model=model,
                         client=numbers_client, numbers_model=numbers_model, query_fn=qfn, planner=planner,
                         extra_context=sblock, route_fn=route_fn)
    else:
        res = run_reasoning(query, asof, graph=graph, call=call, retrieve=retrieve, model=model, planner=planner,
                            extra_context=sblock, route_fn=route_fn)
    res["intent_decision"] = decided
    return _session_writeback(res, query, asof, session_id, store, state, graph, call)


def _session_writeback(res: dict, query: str, asof: str, session_id, store, state, graph, call) -> dict:
    """Append the TurnRecord + roll the Phase-2 summary. Ids and short strings only — the PIT firewall."""
    if not (store and session_id):
        return res
    import time as _time

    from leviathan.graphrag import session as ss
    try:
        tr = (res.get("trace") or {})
        turn = ss.TurnRecord(
            turn=(state.turn_count if state else 0), query=query[:300],
            answer_tldr=str((res.get("structured") or {}).get("tldr") or res.get("answer") or "")[:200],
            contracts=[c for c in (res.get("contracts") or [res.get("contract")]) if c],
            focus_driver=tr.get("focus_driver"), asof=asof,
            fired_regime_names=[r.get("name") for r in tr.get("fired_regimes") or []],
            intent=res.get("intent", ""), ts=_time.time())
        store.append_turn(session_id, turn)
        new_state = ss.roll_summary(state or ss.SessionState(), turn, graph=graph, call=call or an._call_opus)
        store.put_state(session_id, new_state)
        res["session"] = {"id": session_id, "turn": turn.turn}
    except Exception:  # noqa: BLE001 — the answer is already computed; never lose it to a store error
        res["session"] = {"id": session_id, "error": "store_unavailable"}
    return res
