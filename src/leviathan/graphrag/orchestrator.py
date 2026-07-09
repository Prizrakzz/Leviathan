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
import os
import re
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


def run_numbers_only(query: str, asof: str, *, client=None, model: str = na.HAIKU, query_fn=None,
                     graph=None, contracts=None) -> dict:
    out = na.answer_numbers(query, asof, client=client, model=model, query_fn=query_fn)
    cits = cit.unify(None, out.get("calls"))
    body = reg.sanitize((out.get("answer", "") + _footer(cits)).strip())   # strip leaked slugs/tokens from the numbers footer
    nv = _verify_numbers_answer(out.get("answer", ""), out.get("calls") or [])
    if nv.get("mismatched"):                                       # the citv2b 0.107-vs-0.3636 fabrication class:
        body = ("_[verifier: a value stated below does not match any looked-up row — treat stated "
                "figures with caution]_\n\n" + body)               # the reader is warned, deterministically
    # G12: numeric turns carry the resolved contract(s) so the FE mounts the cascade map (structured stays
    # None — no walk ran). `contracts` arrive from the caller's route_fn/plan resolution; the lexical route
    # is a last resort only when routing produced nothing (a direct/legacy caller with no session).
    mc = [c for c in (contracts or []) if graph is None or c in graph.contracts]
    if not mc and graph is not None:
        try:
            mc = [c for c in an.route(query, graph) if c in graph.contracts][:2]
        except Exception:  # noqa: BLE001 — routing must never break a numbers answer
            mc = []
    return {"answer": body, "intent": "numbers_only",
            "citations": [c.model_dump() for c in cits], "number_calls": out.get("calls", []),
            "evidence": [], "asof": asof, "structured": None,
            "contract": (mc[0] if mc else None), "contracts": mc,
            "trace": {"numbers_verifier": nv}}


def _verify_numbers_answer(answer: str, calls: list) -> dict:
    """Deterministic check: every number the answer STATES must match some looked-up row value
    (scale-aware — '31.4 million' == 31400000). Numbers agents have no citation ledger, so they
    bypassed verify.py entirely; this closes the gap the 0.107-vs-0.3636 fabrication exposed."""
    from leviathan.graphrag import verify as vf
    row_vals = []
    for c in calls:
        for r in (c.get("rows") or []):
            try:
                row_vals.append(float(str(r.get("value")).replace(",", "")))
            except (TypeError, ValueError):
                continue
    stated = [v for v in vf._numbers_in(answer)
              if abs(v) >= 0.001 and not (1900 <= v <= 2100 and float(v).is_integer())]   # skip years
    mismatched = [v for v in stated if row_vals and not vf._num_matches([v], row_vals)]
    return {"stated": len(stated), "rows": len(row_vals), "mismatched": len(mismatched),
            "mismatch_values": mismatched[:5]}


def run_reasoning(query: str, asof: str, *, graph, call=None, retrieve=None, model: str = an.SONNET,
                  planner: str | None = None, extra_context: str | None = None, route_fn=None,
                  near: str | None = None, silver_lookup=None, on_stage=None,
                  focus_driver: str | None = None) -> dict:
    out = an.answer(query, graph=graph, asof=asof, call=call, retrieve=retrieve, model=model, planner=planner,
                    extra_context=extra_context, route_fn=route_fn, near=near, silver_lookup=silver_lookup,
                    on_stage=on_stage, focus_driver=focus_driver)
    out["intent"] = "reasoning"
    out.setdefault("number_calls", [])
    out["asof"] = asof
    return out


def run_hybrid(query: str, asof: str, *, graph, call=None, retrieve=None, model: str = an.SONNET,
               client=None, numbers_model: str = na.HAIKU, query_fn=None, planner: str | None = None,
               extra_context: str | None = None, route_fn=None, near: str | None = None,
               silver_lookup=None, on_stage=None, focus_driver: str | None = None) -> dict:
    """Hybrid = numbers ∥ walk. The numbers agent has ZERO dependency on the walk (its output is consumed
    only at synthesis: the prompt block + citation unify/verify), so it runs in a worker thread while
    answer() grounds the subgraph; the two join via `extra_resolver` right before prompt assembly —
    pre-synthesis latency = max(numbers, walk), not the sum. Thread-safety: `client` is None in serving,
    so answer_numbers builds its OWN provider client inside the thread (the shared Anthropic client is not
    thread-safe); session state is read-only until the post-answer writeback."""
    import concurrent.futures as cf

    def _numbers() -> dict:
        # Per-lookup progress ticks (5.6 W5): {calls, running, table} while the agent works, then the
        # final completion event below. on_call stays None on non-streamed callers -> byte-identical.
        on_call = ((lambda k, t: an._emit(on_stage, "numbers", calls=k, running=True, table=t))
                   if on_stage is not None else None)
        try:
            nums = na.answer_numbers(query, asof, client=client, model=numbers_model, query_fn=query_fn,
                                     on_call=on_call)
        except Exception as e:  # noqa: BLE001 — numbers must never take the note down with it
            nums = {"calls": [], "error": str(e)[:200]}
        an._emit(on_stage, "numbers", calls=len(nums.get("calls", [])))   # emitted on COMPLETION
        return nums

    pool = cf.ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(_numbers)
    holder: dict = {"calls": []}

    def _resolve() -> tuple[str, list]:
        """The synthesis-time join: bounded wait for the numbers thread; failure -> no-numbers, same as a
        numbers error today."""
        try:
            calls = fut.result(timeout=300).get("calls", [])
        except Exception:  # noqa: BLE001
            calls = []
        holder["calls"], holder["resolved"] = calls, True
        return "\n\n".join(x for x in (extra_context, _numbers_block(calls)) if x), calls

    try:
        out = an.answer(query, graph=graph, asof=asof, call=call, retrieve=retrieve, model=model,
                        extra_resolver=_resolve, planner=planner, route_fn=route_fn,
                        near=near, silver_lookup=silver_lookup, on_stage=on_stage,
                        focus_driver=focus_driver)
    finally:
        pool.shutdown(wait=False)
    if not holder.get("resolved"):      # early-return paths (e.g. no contract match) skip synthesis —
        _resolve()                      # still surface the numbers the agent found, as before
    out["intent"] = "hybrid"
    out["number_calls"] = holder["calls"]
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


# ── typed context attachments (P2): validate FE graph gestures into seeds + a non-citable block ──────
_EMPTY_ATT = {"contracts": [], "focus_driver": None, "block": None, "near": None, "suppressed_note": None}
_ERA_RE = re.compile(r"^\d{4}(-\d{2})?$")


def _event_era(date: str | None) -> str | None:
    d = (date or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", d):
        return d[:7]                       # YYYY-MM analogue-era prefix (matches near's YYYY / YYYY-MM shape)
    return d if _ERA_RE.match(d) else None


def _attachment_block(node_edge_lines: list[str], events: list) -> str | None:
    """The labeled, NON-CITABLE block (rides extra_context -> volatile; the verifier strips any citation
    aimed here as fabricated). node/edge = a pointer into the driver model; @event reuses the news
    external-shock wrapper so its injection framing is identical to run_live's."""
    parts = []
    if node_edge_lines:
        parts.append("=== USER-ATTACHED FOCUS (the researcher pointed at these tracked driver-model "
                     "elements; CENTER the analysis here. A POINTER into the driver model, NOT new "
                     "evidence -- cite only dated corpus items) ===\n" + "\n".join(node_edge_lines))
    if events:
        from leviathan.graphrag.news import extract_live as nx
        parts.append(nx.live_context_block(events, "user-attached (not a live fetch)"))
    return "\n\n".join(parts) if parts else None


def _resolve_attachments(context, graph, asof: str) -> dict:
    """Validate typed FE gestures -> {contracts, focus_driver, block, near, suppressed_note}. The client is
    never trusted for ids/mechanisms (driver_id/mechanism are re-derived server-side; unknown ids are
    DROPPED, never raised on). Cap 4 attachments in, 2 walk seeds out."""
    from leviathan.graphrag import api_models as M
    from leviathan.graphrag.news import contracts as nc
    from leviathan.graphrag.news import extract_live as nx
    seeds: list[str] = []
    focus = None
    near = None
    node_edge_lines: list[str] = []
    events: list = []
    suppressed: list[str] = []

    def _seed(cid):
        if cid in graph.contracts and cid not in seeds:
            seeds.append(cid)

    for raw in (context or [])[:4]:
        try:
            a = raw if hasattr(raw, "type") else M.ContextAttachment.model_validate(raw)
        except Exception:  # noqa: BLE001 — a malformed attachment is dropped, never trusted
            continue
        if a.type == "node":
            if a.contract not in graph.contracts:
                continue
            try:
                d = graph.driver(a.contract, a.driver_id)          # validates the driver lives in the contract
            except (KeyError, TypeError):
                continue
            _seed(a.contract)                                      # ALWAYS seed the driver's own contract (else
            focus = focus or a.driver_id                           # the walk force-insert silently no-ops)
            node_edge_lines.append(f"- FOCUS DRIVER: {a.driver_id} in {a.contract} -- "
                                   f"{reg.sanitize(d.mechanism)[:240]}")
        elif a.type == "edge":
            if a.contract not in graph.contracts:
                continue
            drv_ids = {dd.id for dd in graph.contracts[a.contract].drivers}
            src, tgt = a.source, a.target
            if src in drv_ids and (tgt == a.contract or tgt in drv_ids):   # driver->contract OR parent->driver
                mech = graph.driver(a.contract, src).mechanism             # SERVER-side (client value ignored)
                _seed(a.contract)
                focus = focus or src
            elif src == a.contract:                                        # contract -> inter-commodity hop
                xl = next((e for e in graph.cross_links(a.contract) if e["driver_commodity"] == tgt), None)
                if xl is None:
                    continue
                mech = xl.get("mechanism") or ""
                _seed(a.contract)
                if xl.get("tracked"):
                    _seed(tgt)                     # an untracked target can't seed a walk; the block carries it
            else:
                continue
            node_edge_lines.append(f"- CASCADE LINK: {src} --> {tgt} [{a.contract}] -- "
                                   f"{reg.sanitize(mech)[:240]}")
        elif a.type == "event":
            if a.event_type not in nc.EVENT_TYPES:                          # enum-lock; a client can't mint a type
                continue
            if a.date and asof and str(a.date) > str(asof):                 # PIT: a future event is fully withheld
                suppressed.append(f"an attached event dated {a.date} is after the analysis horizon ({asof}) "
                                  f"and was left out; move the as-of to {a.date} or later to include it")
                continue
            comm = a.commodity if a.commodity in graph.contracts else ""
            summ = reg.sanitize(str(a.summary or "")).replace("\n", " ")[:300]
            driver = nx.EVENT_DRIVER.get(a.event_type)                      # CODE-mapped; client driver_id IGNORED
            if a.event_type == "weather_advisory":
                driver = nx._weather_driver(str(a.summary or ""))
            events.append(nc.LiveEvent(event_type=a.event_type, commodity=comm, driver_id=driver,
                                       country=reg.sanitize(str(a.country or ""))[:60], summary=summ,
                                       headline=str(a.summary or "")[:140]))
            if driver:
                for c in contracts_for_driver(graph, driver, prefer=comm):
                    _seed(c)
                focus = focus or driver
            elif comm:
                _seed(comm)
            near = near or _event_era(a.date)
    return {"contracts": seeds[:2], "focus_driver": focus,
            "block": _attachment_block(node_edge_lines, events),
            "near": near, "suppressed_note": ("; ".join(suppressed)) if suppressed else None}


def run_live(query: str, asof: str, *, graph, call=None, retrieve=None, model: str = an.SONNET,
             planner: str | None = None, gather=None, extract=None, on_stage=None,
             context_contracts=None, route_fn=None) -> dict:
    """The section-7.1 live branch: fetch trusted headlines -> typed LiveEvents -> event-rooted cascade.
    Returns a full result dict; when NO verified event is found it degrades to normal reasoning with an
    explicit live-check note (never a silently stale answer). `gather`/`extract` injectable for tests.
    `context_contracts` (the thread's resolved contracts) pin the headline SEARCH when the query itself
    names no commodity — a coreference news ask ("any news related to that?") searches the thread's
    commodities instead of generic probes; `route_fn` keeps that coreference through the no-events
    reasoning fallback and the no-seed cascade (news-agent root-cause fix, part 2)."""
    from leviathan.graphrag.news import extract_live as nx
    from leviathan.graphrag.news import fetch as nf
    gather = gather or nf.gather
    extract = extract or nx.extract_events
    items = gather(_live_search_terms(query, graph, context_contracts))
    nf.snapshot(items)                                             # audit copy (best-effort, never blocks)
    events = extract(items, call=call or an._call_opus, graph=graph) if items else []
    if not events:
        res = run_reasoning(query, asof, graph=graph, call=call, retrieve=retrieve, model=model, planner=planner,
                            route_fn=route_fn, on_stage=on_stage)
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
              extra_context=block, planner=planner, on_stage=on_stage)
    if seeds:
        kw.update(route_fn=lambda q, g: seeds, focus_driver=ev0.driver_id)
    elif route_fn is not None:
        kw.update(route_fn=route_fn)                               # no event seed -> the thread's coreference routes
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


def _geo_routing_on() -> bool:
    """Geography routing feature flag (5.8). Default off -> byte-identical to pre-5.8 behavior. Now scoped
    to ONE deterministic behavior: the country-aware live-news search (name a country with no commodity ->
    search that country instead of generic keywords). The fuzzy in-thread topic-shift carry-breaker was
    removed by design — threads are the context boundary (a new thread is a clean session). Rollback = drop
    the env var."""
    return os.environ.get("GRAPHRAG_GEO_ROUTING", "off").lower() == "on"


_EXCHANGE_TOKENS = frozenset({"kcbt", "cbot", "mgex", "cme", "ice", "jse", "zce", "dce", "matif", "nybot"})


def _search_name(contract_id: str) -> str:
    """A contract id as a news-searchable phrase: underscores to spaces, exchange codes dropped
    (hard_red_winter_wheat_kcbt -> "hard red winter wheat"; white_sugar -> "white sugar")."""
    return " ".join(t for t in contract_id.split("_") if t not in _EXCHANGE_TOKENS)


def _live_search_terms(query: str, graph, context_contracts=None) -> list[str]:
    """Search terms for the site-scoped providers: shock keywords found IN the query (else the default
    policy probes from news_sources.yaml) x the query's commodity (word-boundary, incl. head nouns).
    When the query names a COUNTRY but no commodity (e.g. "news on India"), fall back to the country so
    the fetch actually searches it instead of generic keywords (5.8, flag-gated). When the query names
    NEITHER (a coreference — "any news related to that?"), fall back to the THREAD's resolved contracts
    (the news-agent root-cause fix, part 2): the session already knows what "that" is; searching generic
    probe keywords instead of the thread's commodities made coreference news asks return noise."""
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
    if not comm and context_contracts:
        names = [_search_name(c) for c in list(context_contracts)[:3]]
        names = [n for n in names if n]
        if names:
            # one probe keyword per thread commodity (coverage over depth: a cotton+sugar+corn thread
            # should see all three searched), plus a second keyword on the first commodity.
            terms = [f"{kws[0]} {n}".strip() for n in names]
            if len(kws) > 1:
                terms.append(f"{kws[1]} {names[0]}".strip())
    if _geo_routing_on() and not comm and not context_contracts:
        from leviathan.graphrag import geography as geo
        country = geo.resolve_country(query)
        if country:
            label = country.replace("_", " ")
            terms = [f"{k} {label}".strip() for k in kws[:3]] + [label]
    return [t for t in terms if t] or [query[:80]]


_FLOOR_BANNER = ("**Service notice.** The reasoning model tier is temporarily unavailable (retries and "
                 "model fallback exhausted). Below is the retrieved, dated evidence this question would "
                 "have been reasoned over — no synthesized conclusions are included.")


def _guardrail_client():
    """Lazy bedrock-runtime client for ApplyGuardrail (module-level so tests monkeypatch it)."""
    import os

    import boto3
    return boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def _guardrail_check(query: str):
    """Bedrock Guardrail INPUT pre-filter (plan P4): a managed prompt-attack + high-risk-PII gate on the
    raw user query, ahead of the dispatch planner. Defense-in-depth NEXT TO the enum-locked planner /
    spotlighting / PIT kill-switch, never a replacement. INPUT only — output filtering would fight the
    citation verifier. Default OFF (GRAPHRAG_GUARDRAIL unset/off); FAIL-OPEN on any API error
    (availability beats the filter — the structural defenses still gate). Returns a refusal-shaped
    respond() dict on INTERVENED, else None."""
    import os
    gid = os.environ.get("GRAPHRAG_GUARDRAIL", "off")
    if gid in ("", "off"):
        return None
    try:
        resp = _guardrail_client().apply_guardrail(
            guardrailIdentifier=gid,
            guardrailVersion=os.environ.get("GRAPHRAG_GUARDRAIL_VERSION", "DRAFT"),
            source="INPUT", content=[{"text": {"text": query[:5000]}}])
    except Exception:  # noqa: BLE001 — fail-open: a filter outage must never take serving down
        return None
    if resp.get("action") != "GUARDRAIL_INTERVENED":
        return None
    return {"answer": "This query was flagged by the input safety filter and was not processed. "
                      "Please rephrase your research question.",
            "structured": None, "contract": None, "contracts": [], "citations": [], "evidence": [],
            "model": "(guardrail)", "intent": "refused",
            "intent_decision": {"intent": "refused", "guardrail": True},
            "trace": {"guardrail": {"action": "INTERVENED"}}}


def _evidence_only(query: str, asof: str, *, graph, kind: str, exc: Exception,
                   route_fn=None, near: Optional[str] = None) -> dict:
    """The DETERMINISTIC FLOOR (plan: production fallback chain, last resort). When every LLM attempt —
    backoff retries, then the degraded model — has failed, serve the parts of the stack that need no
    model at all: lexical routing + hybrid retrieval + the citation formatter. An honest banner replaces
    synthesis; the UI gets a respond()-shaped dict instead of a 500. No LLM call is permitted here (the
    tiered router's LLM leg would just fail again), and a retrieval failure degrades further to the
    banner alone — the floor itself must be unable to raise."""
    import functools

    from leviathan.graphrag import citations as cit
    from leviathan.graphrag import evidence as ev
    contracts: list = []
    try:
        contracts = [c for c in (route_fn(query, graph) if route_fn else []) if c in graph.contracts]
    except Exception:  # noqa: BLE001 — a session route_fn may itself reach for the dead LLM tier
        contracts = []
    if not contracts:
        contracts = [c for c in an.route(query, graph) if c in graph.contracts]   # lexical tier only
    contracts = contracts[:2]
    retr = functools.partial(ev.retrieve, **an._RETRIEVAL)
    evidence, seen = [], set()
    for c in contracts:
        try:
            hits = retr(query, c, k=5, asof=asof, near=near)
        except Exception:  # noqa: BLE001 — evidence store down too -> banner-only floor
            hits = []
        for h in hits:
            sk = h.get("source_key")
            if sk and sk in seen:
                continue
            seen.add(sk)
            evidence.append({**h, "contract": c})
    lines = [f"- [{h.get('date', '?')}] {h.get('source', h.get('source_key', '?'))}: "
             f"{str(h.get('text', ''))[:220]}" for h in evidence[:8]]
    try:
        cits = [c.model_dump() for c in cit.unify(evidence, None)]
    except Exception:  # noqa: BLE001
        cits = []
    body = _FLOOR_BANNER + ("\n\n**Retrieved evidence (as-of " + asof + "):**\n" + "\n".join(lines)
                            if lines else "\n\n(No evidence could be retrieved either.)")
    return {"answer": body, "structured": None, "contract": contracts[0] if contracts else None,
            "contracts": contracts, "citations": cits, "evidence": evidence, "model": "(unavailable)",
            "intent": kind,
            "trace": {"floor": "evidence_only", "error": f"{type(exc).__name__}: {str(exc)[:200]}"}}


def respond(*args, **kwargs) -> dict:
    """Per-turn TIMING wrapper (Stage 5.0/5.4 latency diagnostic): times `_respond`, stamps
    `trace.timing_ms` = {total, fill, rest}, and logs one INFO line so the warm-turn phase breakdown is
    visible in CloudWatch (also seeds 5.3's structured logs). Fully transparent — the real logic is
    `_respond`; instrumentation is try-guarded and never alters or breaks an answer."""
    import time
    _t0 = time.perf_counter()
    res = _respond(*args, **kwargs)
    try:
        tr = res.setdefault("trace", {})
        gm = tr.get("ground_ms") or {}
        total = int((time.perf_counter() - _t0) * 1000)
        tr["timing_ms"] = {"total": total, "fill": gm.get("fill"), "rest": gm.get("rest")}
        stripped = int((tr.get("citation_verifier") or {}).get("stripped", 0) or 0)
        # print() (not logging) so the line reaches CloudWatch even though the app root logger sits at WARNING
        # under uvicorn — ASCII-only, flushed. Human-readable companion to the EMF metric line below.
        print(f"[timing] total_ms={total} intent={res.get('intent')} model={res.get('model')} "
              f"ms_fill={gm.get('fill')} ms_rest={gm.get('rest')} stripped={stripped}", flush=True)
        # Stage 5.3 R3: emit the same numbers as CloudWatch EMF -> auto-extracted metrics (Leviathan/Serving)
        # feeding the serving dashboard. StripCount ties the primary quality signal (verifier strips) into ops.
        from leviathan.graphrag import emf
        emf.emit({"TurnLatencyMs": total, "MsFill": gm.get("fill"), "MsRest": gm.get("rest"),
                  "StripCount": stripped},
                 dimensions={"intent": res.get("intent"), "model": res.get("model")},
                 units={"TurnLatencyMs": "Milliseconds", "MsFill": "Milliseconds",
                        "MsRest": "Milliseconds", "StripCount": "Count"})
    except Exception:  # noqa: BLE001 — instrumentation must never break an answer
        pass
    return res


def _respond(query: str, *, graph, asof: Optional[str] = None, call=None, retrieve=None, model: str = an.SONNET,
             numbers_client=None, numbers_model: str = na.HAIKU, query_fn=None, classify=None,
             planner: str | None = None, session_id: Optional[str] = None, session_store=None,
             on_stage=None, context=None) -> dict:
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

    refused = _guardrail_check(query)                 # input pre-filter (default off, fail-open)
    if refused is not None:
        return refused                                # refused turns never touch session state

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
    asof_explicit = asof is not None                                    # the caller's arg outranks everything
    asof = asof or (state.asof_latest if state else None) or _today()   # explicit > carried > today
    live_pit_suppressed = False   # set when an EXPLICIT news ask is vetoed by the PIT kill-switch (note below)
    sblock = ss.state_block(snap) if (snap and (snap.turns or state.contracts)) else None
    # ── typed context attachments (P2), part 1: a cheap PRESENCE flag only. The legacy live early-return
    # consults it (an attached turn never enters run_live — it would overwrite extra_context and drop the
    # block). The actual RESOLVE happens after dispatch, where asof is FINAL — the PIT date>asof check must
    # compare against the final horizon or a future event leaks past a plan-set cutoff (⚠verified subtlety).
    _att_present = bool(context) and os.environ.get("GRAPHRAG_CONTEXT_ATTACH", "on").lower() == "on"
    route_fn = None
    if state and state.contracts:                                       # a thread carries its own contracts; threads
        def route_fn(q, g):                                             # are the context boundary (5.8: no in-thread
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
        qfn = ss.cached_query_fn(state, query_fn or Q.default_query_fn())   # routed: pg mirror when flagged

    # Silver leg (F4): OBSERVED driver values feed regime firing. Built only on the REAL serving path
    # (call is None) so injected-fake tests stay hermetic; GRAPHRAG_SILVER=off is the rollback.
    silver_lookup = None
    if call is None and os.environ.get("GRAPHRAG_SILVER", "on") != "off":
        from leviathan.graphrag import silverleg as slv
        silver_lookup = slv.make_silver_lookup(graph, qfn)

    # ── dispatch tier (planner v1) ────────────────────────────────────────────────────────────────
    # One enum-locked planning call resolves {steps, contracts, asof, near} with the session state in
    # view — the fix for the state-blind classifier (convo eval: pronoun follow-ups misrouted to
    # numbers before coreference ran). An injected `classify` (tests) or any planner failure keeps the
    # legacy path below byte-for-byte. The plan NEVER overrides the caller's explicit as-of, and a
    # live step still runs behind the as-of kill-switch — the plan is advice, the guards are law.
    plan, decided, near = None, None, None
    if classify is None:
        from leviathan.graphrag import dispatch as dp
        p = dp.plan_turn(query, graph=graph, state_block=sblock, today=_today(),
                         state_contracts=(state.contracts if state else None), call=call)
        plan = None if p.fallback else p
    if plan is not None:
        if plan.asof and not asof_explicit:
            asof = plan.asof                                           # the turn's own stated cutoff
        pc = [c for c in plan.contracts if c in graph.contracts]
        if pc:
            def route_fn(q, g, _pc=pc):                                # planner did the coreference
                return _pc
        near = plan.near
        kind = plan.kind()
        if kind == "live" and asof < _today():
            kind = "reasoning"                                         # PIT kill-switch (executor half)
            live_pit_suppressed = it.is_news_explicit(query)           # ...but never SILENTLY (root-cause fix)
        elif kind != "live" and it.is_news_explicit(query) and asof >= _today():
            # Deterministic promotion: an EXPLICIT news ask at a today as-of routes live, full stop — the
            # dispatch prompt already states this rule; this makes it law when the LLM misroutes. Narrow
            # matcher only (is_news_explicit): ambient "today"/"right now" stays routable to numbers/
            # reasoning (a blanket is_live promotion would hijack "corn exports today?").
            kind = "live"
        decided = plan.trace() | {"intent": kind}
    else:
        # Legacy path — PIT KILL-SWITCH FIRST: a past as-of can never reach the news agent, so
        # backtested answers are physically unable to see today's headlines (ISO strings compare safely).
        if it.is_news_explicit(query) and asof < _today():
            live_pit_suppressed = True                                 # explicit ask vetoed by PIT -> note below
        # P2 (⚠verified): the attachment guard on this EARLY-RETURN is half of the "an attached turn never
        # triggers the live network fetch" guarantee — run_live would overwrite extra_context and drop the
        # attachment block. The other half is the kind demotion in the override block below.
        if it.is_live(query) and asof >= _today() and not _att_present:
            an._emit(on_stage, "planning", intent="live", contracts=[])
            _ctx = [c for c in ((state.contracts if state else None) or []) if c in graph.contracts] or None
            try:
                res = run_live(query, asof, graph=graph, call=call, retrieve=retrieve, model=model, planner=planner,
                               on_stage=on_stage, context_contracts=_ctx, route_fn=route_fn)
            except Exception as e:  # noqa: BLE001 — deterministic floor: a UI turn must never 500
                an._emit(on_stage, "floor")
                res = _evidence_only(query, asof, graph=graph, kind="live", exc=e, route_fn=route_fn)
            res["intent_decision"] = {"intent": res["intent"], "live_checked": True}
            return _session_writeback(res, query, asof, session_id, store, state, graph, call)
        decided = (classify or it.classify_intent)(query, call=call)
        kind = decided["intent"]

    # ── typed context attachments (P2), part 2: RESOLVE (asof is final here — plan.asof already applied)
    # then override the resolved route. Placed after BOTH route_fn bindings (session coreference + planner)
    # so the explicit gesture wins — this must stay the LAST route_fn binding before branch dispatch. The
    # block CONCATENATES onto sblock because run_hybrid multiplexes only extra_context (a competing param
    # would be silently dropped). Fail-soft: attachments are additive and must never break a turn.
    att = _EMPTY_ATT
    if _att_present:
        try:
            att = _resolve_attachments(context, graph, asof)
        except Exception:  # noqa: BLE001
            att = _EMPTY_ATT
    _att_active = bool(att["contracts"] or att["block"] or att["focus_driver"] or att["suppressed_note"])
    if _att_active:
        if att["contracts"]:
            def route_fn(q, g, _c=att["contracts"]):
                return [c for c in _c if c in g.contracts]
        if att["near"] and not near:
            near = att["near"]                    # analogue-era retrieval: "has this happened before?"
        if att["block"]:
            sblock = "\n\n".join(x for x in (sblock, att["block"]) if x)
        if kind == "live":
            kind = "reasoning"                    # a user-attached event NEVER triggers the live fetch
        decided = (decided or {}) | {"intent": kind,
                                     "attachments": {"contracts": att["contracts"],
                                                     "focus_driver": att["focus_driver"]}}

    # 5.8: a live turn re-routes off the news event and ignores plan.contracts, so don't display the
    # carried contracts on its planning tick (the misleading soybeans/wheat under an India question).
    _tick_contracts = [] if (_geo_routing_on() and kind == "live") else \
        [c for c in (list(plan.contracts) if plan else []) if c in graph.contracts]
    an._emit(on_stage, "planning", intent=kind, contracts=_tick_contracts)   # staged-pipeline (P1.1)
    try:
        if kind == "live":
            # Thread coreference reaches the news SEARCH ("any news related to that?"): the plan's
            # resolved contracts first, else the session's carried contracts (root-cause fix, part 2).
            _ctx = [c for c in ((list(plan.contracts) if plan else None)
                                or (state.contracts if state else None) or []) if c in graph.contracts] or None
            res = run_live(query, asof, graph=graph, call=call, retrieve=retrieve, model=model, planner=planner,
                           on_stage=on_stage, context_contracts=_ctx, route_fn=route_fn)
        elif kind == "numbers_only":
            hints = list(plan.contracts) if plan else []
            if plan and plan.country:
                hints.append(plan.country)                         # "And exports?" after Brazil = BRAZIL exports
            nq = query if not hints else f"{query}\n(conversation context: this refers to {', '.join(hints)})"
            # G12: mount the cascade map on numeric turns too. Key it off the SAME routing the reasoning
            # branch uses (planner pc / session coreference via route_fn), NOT a fresh lexical route —
            # a coreference numeric turn ("and its exports?") lexically routes to nothing. RAW `query` on
            # purpose: route_fn's short-follow-up coreference gate keys on len(query) (<=80).
            try:
                _mc = [c for c in route_fn(query, graph) if c in graph.contracts] if route_fn else []
            except Exception:  # noqa: BLE001 — a session route_fn may reach a dead tier; never break the answer
                _mc = []
            if not _mc and plan is not None:
                _mc = [c for c in plan.contracts if c in graph.contracts]
            res = run_numbers_only(nq, asof, client=numbers_client, model=numbers_model, query_fn=qfn,
                                   graph=graph, contracts=_mc)
            an._emit(on_stage, "numbers", calls=len(res.get("number_calls", [])))
        elif kind == "hybrid":
            res = run_hybrid(query, asof, graph=graph, call=call, retrieve=retrieve, model=model,
                             client=numbers_client, numbers_model=numbers_model, query_fn=qfn, planner=planner,
                             extra_context=sblock, route_fn=route_fn, near=near, silver_lookup=silver_lookup,
                             on_stage=on_stage, focus_driver=att["focus_driver"])
        else:
            res = run_reasoning(query, asof, graph=graph, call=call, retrieve=retrieve, model=model,
                                planner=planner, extra_context=sblock, route_fn=route_fn, near=near,
                                silver_lookup=silver_lookup, on_stage=on_stage,
                                focus_driver=att["focus_driver"])
    except Exception as e:  # noqa: BLE001 — deterministic floor: a UI turn must never 500
        an._emit(on_stage, "floor")
        res = _evidence_only(query, asof, graph=graph, kind=kind, exc=e, route_fn=route_fn, near=near)
    if att["suppressed_note"]:
        # A future-dated attached event is refused VISIBLY (mirrors the news-agent silence fix). C1: the
        # note travels as trace.attachment_note — the FE renders it as a banner on ALL turn types (an
        # answer-append is invisible on structured turns). Server-owned static prose; no client string.
        res.setdefault("trace", {})["attachment_note"] = att["suppressed_note"]
        decided = (decided or {}) | {"attachment_suppressed_pit": True}
    if live_pit_suppressed:
        # The root-cause fix (news-agent silence): the user LITERALLY asked for news but the PIT
        # kill-switch vetoed the live route (historical as-of). Say so — mirrors run_live's no-events
        # note; an archive answer masquerading as a news answer is the failure mode this closes.
        res["answer"] = (res.get("answer") or "") + (
            f"\n\n_Live check: you asked for news, but live headlines are disabled at a historical "
            f"as-of (horizon = {asof}). Set the as-of horizon to today for current headlines; the "
            f"analysis above draws on the dated archive only._")
        decided = (decided or {}) | {"live_suppressed_pit": True}
    res["intent_decision"] = decided
    return _session_writeback(res, query, asof, session_id, store, state, graph, call)


def _session_writeback(res: dict, query: str, asof: str, session_id, store, state, graph, call) -> dict:
    """Append the TurnRecord + roll the Phase-2 summary. Ids and short strings only — the PIT firewall."""
    # Graph identity stamp (audit/reproducibility): every real answer records WHICH causal graph produced
    # it. Done here — the single choke point both the main branch and the live early-return pass through —
    # and BEFORE the no-session early return, so it lands whether or not a session is active.
    res.setdefault("trace", {})["graph_version"] = getattr(graph, "version", None)
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
