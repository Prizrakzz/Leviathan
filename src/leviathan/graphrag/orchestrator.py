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
    block = "SILVER NUMBERS (observed values, as-known at asof):\n" + body
    # ESR destination-scope honesty: the numbers agent stamps `scope_note` on export-sales lookups that
    # answered a destination-scoped ask with a national total. The hybrid path consumes CALLS, not the
    # agent's prose, so the agent's reader-facing caveat would be lost here — carry the note into the
    # synthesis prompt so the writer states the national-total limitation instead of presenting the
    # figure as the destination cut. Absent scope_note (every national ask), the block is byte-identical.
    notes = sorted({c.get("scope_note") for c in (calls or []) if isinstance(c, dict) and c.get("scope_note")})
    if notes:
        block += "\nSCOPE NOTE (state this limitation explicitly in the answer): " + " ".join(notes)
    return block


def _footer(cits) -> str:
    return ("\n\n## Sources\n" + cit.render(cits)) if cits else ""


def run_numbers_only(query: str, asof: str, *, client=None, model: str = na.HAIKU, query_fn=None,
                     graph=None, contracts=None) -> dict:
    import time as _time
    _tn = _time.perf_counter()                                      # F0: MsNumbers on the numbers_only route
    out = na.answer_numbers(query, asof, client=client, model=model, query_fn=query_fn)
    _ms_numbers = int((_time.perf_counter() - _tn) * 1000)
    cits = cit.unify(None, out.get("calls"))
    _raw = out.get("answer", "")                                    # DP-6: raw pre-sanitize agent text
    _banned_val = reg.count_valuation_words(_raw)                   # the price-serving lane -- counts must ride trace
    _banned_flow = reg.count_flow_words(_raw)
    body = reg.sanitize((_raw + _footer(cits)).strip())            # strip leaked slugs/tokens from the numbers footer
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
    # W2.5: the agent's honesty-guard keys live only in answer_numbers' return dict (dropped here otherwise);
    # copy them onto the trace so the eval deck can pin them (the ESR destination guard, the price-coverage
    # decline guard, and the year_month period-scoping guard -- task #142, whose value is the NAMED month
    # window 'YYYY-MM' / 'YYYY-MM..YYYY-MM'). Absent (the common case) -> the trace is byte-identical.
    # F0 (latency RCA 2026-07-25): the agent leg is timed on THIS route too. MsNumbers was stamped only by
    # run_hybrid, so it was absent on 237/237 numbers_only turns and ~69% of an 8.0s numbers_only p50 was an
    # unmeasured leg. The two lanes time the same call but differ in MARGINALITY: on hybrid the agent runs in
    # a worker thread parallel with the walk (measured 0 marginal, >=18s of headroom on 335/335 turns), here
    # it IS the critical path. The `intent` EMF dimension separates them -- never pool the two.
    _trace = {"numbers_verifier": nv, "banned_valuation_words": _banned_val, "banned_flow_words": _banned_flow,
              "ms_numbers": _ms_numbers}
    for _gk in ("esr_destination_guard", "price_decline_guard", "pattern_records", "period_mismatch_guard"):
        if out.get(_gk) is not None:
            _trace[_gk] = out[_gk]
    return {"answer": body, "intent": "numbers_only",
            "citations": [c.model_dump() for c in cits], "number_calls": out.get("calls", []),
            "evidence": [], "asof": asof, "structured": None,
            "contract": (mc[0] if mc else None), "contracts": mc,
            "trace": _trace}


def _verify_numbers_answer(answer: str, calls: list) -> dict:
    """Deterministic check: every number the answer STATES must match some looked-up row value
    (scale-aware — '31.4 million' == 31400000). Numbers agents have no citation ledger, so they
    bypassed verify.py entirely; this closes the gap the 0.107-vs-0.3636 fabrication exposed."""
    from leviathan.graphrag import verify as vf
    row_vals = []
    for c in calls:
        metric = str((c.get("query") or {}).get("metric", "")).lower()
        for r in (c.get("rows") or []):
            try:
                v = float(str(r.get("value")).replace(",", ""))
            except (TypeError, ValueError):
                continue
            row_vals.append(v)
            if "bag" in metric:
                # coffee's 60-kg bag standard: a correct bags->tonnes restatement of a looked-up figure
                # is GROUNDED, not fabricated (39,598.4 thousand bags -> 2,375,904 t; the answer's
                # '~2.376 million metric tonnes' fired the caution banner on a correct CONAB serve)
                row_vals.append(v * 60.0)
            # T2b D1/D1b (pattern-records deck skeptic, 2026-07-25): a ledger leg's DENOMINATOR rides the
            # row as `sweeps_total`, never as a `value` -- yet the engine's OWN deterministic preface
            # states it ("firing on 9 of 156 weekly replay asofs"), and so does the in-catalog honest-zero
            # line ("no firing on any of its N sweeps"). Uncollected, the engine's own correct sentence
            # wore the caution banner: the identical false-caution class as the CONAB/futures rows, and on
            # the honest-zero branch it would have become the STEADY STATE once the daily sweep records a
            # decline. The denominator is a looked-up quantity from this very row -> grounded by construction.
            try:
                row_vals.append(float(str(r.get("sweeps_total")).replace(",", "")))
            except (TypeError, ValueError):
                pass
    # Non-VALUE tokens are scrubbed before extraction: ISO dates (2026-06-01), WB release stamps
    # (2026M07), marketing years (2024/25) and [N#] handles all shed numeric fragments (06, 07, 25, 1)
    # that read as "stated figures" -- the pink_sheet provenance stamp made this fire for the first time
    # (W3.7: both CORRECT price answers wore a false caution banner and failed their mismatch pins).
    scrub = re.sub(r"\d{4}-M\d{2}|\d{4}-\d{2}(?:-\d{2})?|\d{4}M\d{2}|\d{4}/\d{2,4}|\[N\d+\]", " ", answer)
    # NEWCAP TRIAGE (2026-07-24, false-caution classes; two rounds, both live-serving bugs): non-VALUE
    # numeral shapes fired the banner on CORRECT answers -- (a) prose dates with OR without a year
    # ('published June 1, 2025', 'the June 5 trading session', '2 February 2026') shed a day-of-month;
    # (b) hyphen-glued unit descriptors ('60-kg bags') read as a stated 60; (c) duration arithmetic
    # ('more than 14 months old') is derived, not looked-up; (d) markdown ordered-list markers ('1. ')
    # read as stated 1.0/2.0/3.0. All are labels/derivations, never data figures. The no-year date form
    # subsumes the with-year one (the residual year token is already skipped by the year filter below).
    _MONTHS = (r"(?:January|February|March|April|May|June|July|August|September|October|November|"
               r"December)")
    scrub = re.sub(rf"{_MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?\b"
                   rf"|\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTHS}", " ", scrub)
    scrub = re.sub(r"\b\d+(?:\.\d+)?-(?=[A-Za-z])", " ", scrub)
    scrub = re.sub(r"\b\d+(?:\.\d+)?\s+(?:month|week|day|year|hour)s?\b", " ", scrub)
    scrub = re.sub(r"(?m)^\s*\d{1,2}\.\s+", " ", scrub)
    stated = [v for v in vf._numbers_in(scrub)
              if abs(v) >= 0.001 and not (1900 <= v <= 2100 and float(v).is_integer())]   # skip years
    mismatched = [v for v in stated if row_vals and not vf._num_matches([v], row_vals)]
    return {"stated": len(stated), "rows": len(row_vals), "mismatched": len(mismatched),
            "mismatch_values": mismatched[:5]}


def _emit_numbers(on_stage, calls) -> None:
    """F7 `number`: one event per RESOLVED numbers-agent lookup, projected to the pinned field set
    {table, metric, value, unit, asof}. These are deterministic lookup results, not LLM prose, so they need
    no verifier reconciliation.

    ARRIVAL TIME, precisely: this fires the moment the numbers THREAD completes, which on a hybrid turn is
    strictly before the synthesis-time join (`_resolve`) and typically many seconds before it — the walk is
    the long pole. It is NOT per-individual-lookup: agent.on_call carries only (n_calls, table), and the
    resolved record it would need lives inside numbers/agent.py, outside this lane. A per-lookup `number`
    needs one line there (widen on_call to pass `content`); until then the count-only `numbers` tick keeps
    covering the per-lookup beat.

    `asof` is the ROW's knowledge/data date — the as-KNOWN date of this value, which is what a desk reads —
    and falls back to the spec's PIT cutoff only when the row carries neither. Errored / empty lookups emit
    NOTHING: there is no value to show, and a 'number' event with no number would be junk in the feed."""
    if on_stage is None:
        return
    for c in (calls or []):
        try:
            if not isinstance(c, dict) or c.get("status") == "error":
                continue
            q = c.get("query") or {}
            rows = c.get("rows") or []
            if not rows:
                continue
            r0 = rows[0] or {}
            val = r0.get("value")
            if val in (None, ""):
                continue
            an._emit(on_stage, "number", table=str(q.get("table") or ""), metric=str(q.get("metric") or ""),
                     value=val, unit=(str(r0["unit"]) if r0.get("unit") else None),
                     asof=str(r0.get("knowledge_date") or r0.get("data_date") or q.get("asof") or ""))
        except Exception:  # noqa: BLE001 — a malformed call record can never fail a turn (invariant 1)
            continue


def run_reasoning(query: str, asof: str, *, graph, call=None, retrieve=None, model: str = an.SONNET,
                  planner: str | None = None, extra_context: str | None = None, route_fn=None,
                  near: str | None = None, silver_lookup=None, on_stage=None,
                  focus_driver: str | None = None, qfn=None, xc_request: dict | None = None,
                  outlook: bool = False) -> dict:
    # reroute v2: xc_request rides down to the cascade quantify seam (lane C) ONLY when the gate produced one
    # (flag on + explicit ask). None -> the kwarg is omitted so the answer() call is byte-identical to today.
    _xc = {"xc_request": xc_request} if xc_request is not None else {}
    # W5-D4: the outlook kwarg is OMITTED when False (the `_xc` omit-when-None idiom), so a non-outlook turn's
    # answer() call is byte-identical to pre-W5 and injected answer fakes with the older signature stay valid.
    _ol = {"outlook": True} if outlook else {}
    out = an.answer(query, graph=graph, asof=asof, call=call, retrieve=retrieve, model=model, planner=planner,
                    extra_context=extra_context, route_fn=route_fn, near=near, silver_lookup=silver_lookup,
                    on_stage=on_stage, focus_driver=focus_driver, numbers_lookup=qfn, **_xc, **_ol)
    out["intent"] = "reasoning"
    out.setdefault("number_calls", [])
    out["asof"] = asof
    return out


def run_hybrid(query: str, asof: str, *, graph, call=None, retrieve=None, model: str = an.SONNET,
               client=None, numbers_model: str = na.HAIKU, query_fn=None, planner: str | None = None,
               extra_context: str | None = None, route_fn=None, near: str | None = None,
               silver_lookup=None, on_stage=None, focus_driver: str | None = None,
               xc_request: dict | None = None, outlook: bool = False) -> dict:
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
        import time as _time
        _tn = _time.perf_counter()                                # W6.1-0: numbers-agent duration (MsNumbers)
        try:
            nums = na.answer_numbers(query, asof, client=client, model=numbers_model, query_fn=query_fn,
                                     on_call=on_call)
        except Exception as e:  # noqa: BLE001 — numbers must never take the note down with it
            nums = {"calls": [], "error": str(e)[:200]}
        nums["_ms_numbers"] = int((_time.perf_counter() - _tn) * 1000)
        an._emit(on_stage, "numbers", calls=len(nums.get("calls", [])))   # emitted on COMPLETION
        # F7 `number`: the resolved rows, from THIS worker thread, the moment the agent returns — i.e.
        # BEFORE the synthesis-time join in _resolve() below (the walk is normally the long pole, so this is
        # the earliest a user could be shown a number). Concurrent with the walk's own emitters: the SSE
        # relay is a queue.Queue, whose put() is thread-safe, so the two lanes interleave safely.
        _emit_numbers(on_stage, nums.get("calls"))
        return nums

    pool = cf.ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(_numbers)
    holder: dict = {"calls": []}

    def _resolve() -> tuple[str, list]:
        """The synthesis-time join: bounded wait for the numbers thread; failure -> no-numbers, same as a
        numbers error today."""
        try:
            nums = fut.result(timeout=300)
        except Exception:  # noqa: BLE001
            nums = {}
        calls = nums.get("calls", [])
        # SEAM-C futures levels-only decline on the HYBRID lane (task #144). The agent's own decline preface
        # lives in nums['answer'], which this path never reads, so a curve/named ask arrived here as a bare
        # front-month LEVEL and the reasoner narrated it as the asked-for quote. Neuter those lookups BEFORE
        # the block is built (nothing citable survives) and keep the caveat: the class template rides the
        # calls as the scope note the writer must state, and the preface is prepended to the finished note
        # below. Guard absent — every non-futures turn, plus the servable level/'change' asks — returns the
        # same list and an empty preface, so the join is byte-identical to today.
        _fcls = nums.get("futures_decline_guard")
        calls, _fpref = na.futures_hybrid_decline(_fcls, calls)
        if _fpref:
            holder["futures_decline"], holder["futures_preface"] = _fcls, _fpref
        holder["calls"], holder["resolved"] = calls, True
        # T2b D2 (pattern-records deck skeptic, 2026-07-25): run_numbers_only copies `pattern_records`
        # onto its trace (:77) but the hybrid join never did -- so a persistence question routed hybrid
        # still received the injected ledger leg AND the base-rate preface, with ZERO deterministic
        # observability: no eval pin could read it and no soak telemetry could count it. Same lane
        # asymmetry as the futures decline (#144) and the period guard (#142); carried the same way.
        holder["pattern_records"] = nums.get("pattern_records")
        holder["ms_numbers"] = nums.get("_ms_numbers")            # W6.1-0: numbers-agent duration (MsNumbers)
        return "\n\n".join(x for x in (extra_context, _numbers_block(calls)) if x), calls

    _xc = {"xc_request": xc_request} if xc_request is not None else {}   # reroute v2: omit when None (byte-identical)
    _ol = {"outlook": True} if outlook else {}                           # W5-D4: same omit-when-off idiom
    try:
        out = an.answer(query, graph=graph, asof=asof, call=call, retrieve=retrieve, model=model,
                        extra_resolver=_resolve, planner=planner, route_fn=route_fn,
                        near=near, silver_lookup=silver_lookup, on_stage=on_stage,
                        focus_driver=focus_driver, numbers_lookup=query_fn, **_xc, **_ol)
    finally:
        pool.shutdown(wait=False)
    if not holder.get("resolved"):      # early-return paths (e.g. no contract match) skip synthesis —
        _resolve()                      # still surface the numbers the agent found, as before
    out["intent"] = "hybrid"
    out["number_calls"] = holder["calls"]
    if holder.get("futures_preface"):
        # the DETERMINISTIC half of the SEAM-C hybrid decline (task #144): the caveat is prepended whatever
        # the writer produced, exactly as the numbers_only lane does — the honesty never rides on the prompt.
        # Same shape as answer.py's degraded banner; absent on every turn the guard did not fire.
        out["answer"] = holder["futures_preface"] + (out.get("answer") or "")
        out.setdefault("trace", {})["futures_decline_guard"] = holder["futures_decline"]
    if holder.get("pattern_records") is not None:
        out.setdefault("trace", {})["pattern_records"] = holder["pattern_records"]   # T2b D2, see _resolve
    if holder.get("ms_numbers") is not None:
        out.setdefault("trace", {})["ms_numbers"] = holder["ms_numbers"]   # W6.1-0: surface for the EMF block
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
             context_contracts=None, route_fn=None, qfn=None) -> dict:
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
                            route_fn=route_fn, on_stage=on_stage, qfn=qfn)
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
              extra_context=block, planner=planner, on_stage=on_stage, numbers_lookup=qfn)
    if seeds:
        kw.update(route_fn=lambda q, g: seeds, focus_driver=ev0.driver_id)
    elif route_fn is not None:
        kw.update(route_fn=route_fn)                               # no event seed -> the thread's coreference routes
    out = an.answer(query, **kw)
    header = "**Live context** (external, fetched " + (now or "now") + "): " + "; ".join(
        f"[{e.source}] {e.summary}" for e in events) + \
        "\n\n_Live headlines are context only - the cascade below cites dated corpus evidence._\n\n"
    out["answer"] = reg.sanitize(header) + (out.get("answer") or "")
    _tr = out.setdefault("trace", {})                               # DP-6: fold the live header's RAW valuation/flow
    _tr["banned_valuation_words"] = _tr.get("banned_valuation_words", 0) + reg.count_valuation_words(header)
    _tr["banned_flow_words"] = _tr.get("banned_flow_words", 0) + reg.count_flow_words(header)
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


def _trivial_router_on() -> bool:
    """Trivial-turn router feature flag (F1). Default OFF -> byte-identical to pre-F1 behavior. When ON, a
    pure greeting/smalltalk/meta turn short-circuits to a canned mentor reply (the intent.is_trivial gate),
    saving the dispatch + synthesis Sonnet calls that a greeting otherwise pays for. Deterministic-only and
    fail-open in v1. Rollback = drop the env var (single flag, instant, no redeploy)."""
    return os.environ.get("GRAPHRAG_TRIVIAL_ROUTER", "off").lower() == "on"


def _reroute_v2_on() -> bool:
    """Cross-commodity relative-value fork feature flag (reroute v2). DEFAULT-OFF flip flag, case-insensitive,
    fail-closed (any unrecognized value stays off) -- matches the SUGGEST_CATALOG/GEO_ROUTING convention. When
    OFF the gate never computes a request, so `xc_request` is None and the reasoning/hybrid seam is
    BYTE-IDENTICAL to today (the engine is gated by the ARGUMENT, never by reading this flag itself).
    Rollback = drop the env var (single flag, instant, no redeploy)."""
    return os.environ.get("GRAPHRAG_REROUTE_V2", "off").lower() == "on"


def _family_facet_on() -> bool:
    """Data-family facet consumption kill-switch (F2 durable fix). DEFAULT-OFF, case-insensitive, fail-closed
    (any unrecognized value stays off) -- copies the _reroute_v2_on idiom exactly. When OFF the planner keeps
    emitting plan.data_families dark (soak channel) but the orchestrator NEVER promotes, so the reasoning route
    is byte-identical to today. Consumption is PROMOTION-ONLY (reasoning->hybrid, never a demotion). Rollback =
    drop the env var (single flag, instant, no redeploy)."""
    return os.environ.get("GRAPHRAG_FAMILY_FACET", "off").lower() == "on"


def _xc_llm_detect_on() -> bool:
    """LLM cross-commodity detection tier kill-switch (RV2 D6). DEFAULT-OFF; only a case-insensitive
    on/1/true enables it, and ANY other value (unset, off, typo, 'yes') stays off -- fail-closed, so the
    deterministic regex remains the whole detector unless explicitly flipped. Gates CONSUMPTION only: the
    planner keeps emitting xc_explicit/xc_target dark either way (the D20 soak channel). Rollback = drop
    the env var (single flag, instant, no redeploy) -- byte-identical to the regex-floor behavior."""
    return os.environ.get("GRAPHRAG_XC_LLM_DETECT", "").strip().lower() in ("on", "1", "true")


def xc_detect_two_tier(plan):
    """The SHARED two-tier cross-commodity detector factory (RV2 W2, S3-F6): builds the `detect(q)` closure
    `_xc_request` consumes AND the W3 fence harness scores through -- one module-level symbol, so deck
    attribution can never drift from prod. Tier 1 is the deterministic regex FLOOR: any hit returns
    immediately and the LLM is NEVER consulted (D2 -- the tier adds recall, never suppresses). Tier 2
    consumes the dispatch planner's strict-validated fields only when the kill-switch is on, the plan
    exists (D11: fallback turns are floor-only), the call did not degrade Sonnet->Haiku (D2 amendment:
    the degraded model is never deck-certified), xc_explicit is literally True, and xc_target is NAMED
    (D19: the open-target lane stays regex-only). The closure cannot raise (pure regex + dataclass reads
    -- D8 by construction) and self-records `tier`/`llm_consulted` as attributes for the D7 telemetry
    stamp -- out-of-band, so the (matched, span) seam contract and every injected test fake stay
    byte-identical. `llm_consulted` is True iff tier-2 was actually reachable this call (regex missed,
    flag on, plan present, not degraded) -- consulted-and-declined is distinguishable from flag-off and
    from planner fallback."""
    def detect(q):
        m, span = it.is_cross_commodity_explicit(q)              # tier 1: deterministic floor
        if m:
            detect.tier, detect.llm_consulted = "regex", False   # regex hit -> LLM NEVER consulted (D2)
            return (m, span)
        consulted = (_xc_llm_detect_on() and plan is not None
                     and not getattr(plan, "degraded", False))   # S1-F2: degraded turns are floor-only
        if (consulted and getattr(plan, "xc_explicit", False) is True
                and getattr(plan, "xc_target", None)):           # D19: NAMED targets only
            detect.tier, detect.llm_consulted = "llm", True
            return (True, plan.xc_target)                        # tier 2: adds recall only
        detect.tier, detect.llm_consulted = "none", consulted
        return (False, None)
    detect.tier, detect.llm_consulted = None, False
    return detect


# ── reroute v2 gate helpers (RV-W1.3): produce the cross-commodity request; NO firing logic lives here ────
# The engine (lane C) decides whether the fork fires; the gate only resolves SOURCE + TARGET and selects the
# single curated MATERIAL, census-realizable pair. Everything is fail-closed: any miss -> None (no fork).
def _xc_pair_slugs(pair) -> tuple:
    """The ordered leg slugs of a complex_map pair (interface: `.pair` = tuple of 2 slugs)."""
    pr = getattr(pair, "pair", None)
    if pr and len(pr) == 2:
        return (pr[0], pr[1])
    return (pair.side_a.get("contract"), pair.side_b.get("contract"))   # defensive fallback


def _xc_other(pair, source: str) -> str | None:
    a, b = _xc_pair_slugs(pair)
    if source == a:
        return b
    if source == b:
        return a
    return None


def _xc_find_pair(pairs, a: str, b: str):
    """Order-INSENSITIVE lookup (RV-W1.3 F1 nit: authored ordered, but route() can yield either order).
    Deterministic on the (defensive) duplicate case via pair-id lexical order."""
    key = frozenset((a, b))
    hits = sorted((p for p in pairs if frozenset(_xc_pair_slugs(p)) == key), key=lambda p: p.id)
    return hits[0] if hits else None


def _xc_realizable_default(pair_id: str):
    """Per-PAIR census verdict (RV-W4.2, lane D). Lazily imported so the gate does not hard-depend on the
    census module at import time; an ImportError propagates to the caller's fail-closed guard."""
    from leviathan.graphrag.numbers import cascade_census as cc
    return cc.pair_realizable(pair_id)


def _xc_request(query: str, *, graph, state, detect=None, route=None, resolve_bare=None,
                load_map=None, realizable=None) -> dict | None:
    """Produce the cross-commodity RV request dict {pair_id, target_slug, source_slug} threaded into the
    cascade quantify seam (plus `detect_tier` when the W2 two-tier composite detected -- pure telemetry,
    stamped onto the fired trace in cascade._run_xc), or None (the default and every fail-closed outcome).
    RV-W1.3, extended with the
    D7 open-target PAIR_CAP=1, the C8 target binding, and the D17 target-aware SOURCE binding (a NAMED-target
    ask resolves the target FIRST, then binds SOURCE to the first route hit forming a curated pair with it --
    the old route[0] binding declined nearly every self-contained two-commodity ask, S2-1). Dependencies
    default to the real symbols but are INJECTABLE for hermetic tests (lanes A/D build concurrently). The
    whole body is try-wrapped: any exception -- a raising detector, a missing lane-A/lane-D symbol, a
    cold-cache glob failure -- yields None (fail-closed, C12), never a propagated 500."""
    try:
        detect = detect or it.is_cross_commodity_explicit
        matched, target_span = detect(query)
        if not matched:                                            # gate 1: the narrow explicit-ask matcher
            return None
        # W2 tier telemetry (D7): the two-tier composite self-records which tier matched; a plain/injected
        # detector carries no attribute -> no key (byte-identical dicts on every legacy seam). The engine
        # reads only pair_id/source/target (cascade.py) so the extra key rides inert to the fired trace.
        _tier = getattr(detect, "tier", None)
        _tk = {"detect_tier": _tier} if _tier else {}
        route = route or an.route
        if resolve_bare is None or load_map is None:               # lazy lane-A import (fail-closed on miss);
            from leviathan.graphrag import complex_map as cm       # hoisted above SOURCE binding: D17 needs
            resolve_bare = resolve_bare or cm.resolve_bare_commodity   # the resolved TARGET to pick SOURCE
            load_map = load_map or cm.load_complex_map
        realizable = realizable or _xc_realizable_default
        material = [p for p in getattr(load_map(), "pairs", [])
                    if getattr(p, "materiality_tier", None) == "material"]
        src_hits = [c for c in (route(query, graph) or []) if c in graph.contracts]

        if target_span is None:
            # gate 2 OPEN-target (D7, binding byte-unchanged by D17): SOURCE = this-turn lexical route
            # first hit, else the carried session contract (coreference); then rank SOURCE's pairs.
            source = src_hits[0] if src_hits else (
                state.contracts[0] if (state and state.contracts
                                       and state.contracts[0] in graph.contracts) else None)
            if not source:
                return None
            cands = sorted((p for p in material if source in _xc_pair_slugs(p)), key=lambda p: p.id)
            for p in cands:                                        # PAIR_CAP=1: first realizable in id order
                if realizable(p.id) is True:                       # fail-closed: only an explicit True fires
                    tgt = _xc_other(p, source)
                    if tgt:
                        return {"pair_id": p.id, "source_slug": source, "target_slug": tgt, **_tk}
            return None

        # gate 2 NAMED-target (D17): resolve TARGET first, then bind SOURCE target-aware.
        target = resolve_bare(target_span)
        if not target or target not in graph.contracts:
            return None
        if src_hits:
            # SOURCE = the FIRST route hit forming a CURATED material pair with the resolved target --
            # the allowlist itself is the binding criterion. A hit equal to the target is never a SOURCE
            # candidate, and a target SIBLING (a hit resolving to the target's commodity) forms no curated
            # pair with it (curated pairs are cross-commodity by construction) so it can never bind either.
            # No pair-forming hit -> None: all-hits-are-target is the C8 decline, and a non-pair-forming
            # route declines EXPLICITLY instead of minting an arbitrary decline-shaped SOURCE.
            source = next((c for c in src_hits
                           if c != target and _xc_find_pair(material, c, target) is not None), None)
        else:                                                      # empty route: carried session contract,
            source = (state.contracts[0]                           # exactly as before -- normal gates run
                      if (state and state.contracts and state.contracts[0] in graph.contracts) else None)
        if not source or source == target:                         # C8: a state-carried SOURCE may equal target
            return None
        pair = _xc_find_pair(material, source, target)             # gate 3: curated + material (order-insensitive)
        if pair is None or realizable(pair.id) is not True:        # + per-pair census FIRES (fail-closed)
            return None
        return {"pair_id": pair.id, "source_slug": source, "target_slug": target, **_tk}
    except Exception:  # noqa: BLE001 -- a detector/resolver/census failure disables v2 this turn, never 500s
        return None


# Canned mentor-register replies (F1) — one per is_trivial class. 1-2 lines, lead-with-the-point desk voice;
# NEVER bullish/bearish, NO internal slugs/ids, NO fabricated numbers (they MUST score 0 on register.register_
# leaks AND register._MOOD — pinned by tests/unit/test_trivial_router.py). Each names a few example question
# TYPES in prose; the data-scoped starter CHIPS are the live suggester's job (trace.trivial.starters flags the
# FE to render them from the warm convergence matrix — F1 never mints or fabricates chips itself).
_TRIVIAL_REPLIES = {
    "greeting": (
        "Hi -- I'm your commodities research desk. Ask me what's driving a market, how a shock propagates "
        "through a balance sheet and where the price response turns convex, or for a specific observed figure "
        "like exports, ending stocks, or a spot level at a point in time."),
    "smalltalk": (
        "Anytime -- I'm here whenever you want to trace what's moving a market, follow a shock through the "
        "supply chain, or pull an observed figure. Just name a market or an event to pick up the thread."),
    "meta": (
        "I'm a commodities research desk covering the tracked agricultural complex -- grains, oilseeds, softs, "
        "and the weather, policy, macro and logistics drivers behind them. I explain what's driving a market "
        "and how a shock cascades and compounds, and I look up observed levels (exports, stocks, production, "
        "prices, FX, ENSO) as they were known at any point in time. Name a market or a shock to start."),
}


def _trivial_answer(query: str, klass: str) -> dict:
    """A respond()-shaped canned reply for a trivial social turn (mirrors _guardrail_check's early-return
    shape). No LLM call, no data path, no session write. `trace.trivial.starters=True` is the FE hint to render
    the live suggester's data-scoped starter chips (server.py starter path); F1 does NOT call /v1/suggest."""
    return {"answer": _TRIVIAL_REPLIES.get(klass, _TRIVIAL_REPLIES["greeting"]),
            "structured": None, "contract": None, "contracts": [], "citations": [], "evidence": [],
            "number_calls": [], "model": "(canned)", "intent": "social",
            "intent_decision": {"intent": "social", "trivial": klass},
            "trace": {"trivial": {"class": klass, "starters": True}}}


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


# ── F4a: the deterministic floor, made VISIBLE (latency RCA 2026-07-25) ─────────────────────────────
# 135 floor turns in 3 days -- 17.6% of all turns, p50 242.6s / p95 1163.6s, each delivering a 279-char
# service notice -- carried no metric at all: the exception rode `trace.error` to the caller and the [floor]
# print carried raw exception text that nothing could group or alarm on. These slugs are a CLOSED set: a
# `cause` DIMENSION over raw exception text would mint a new billed dimension value per distinct message.
# The floor is NOT single-cause (the reason a dimension is required, not optional): the 7d log carries pg
# statement timeouts under RDS credit/EBS starvation AND a bge model-download OSError against huggingface.co.
#
# W8 adds the 5th class, `llm_unavailable`, and it is the one the metric existed for. The floor's OWN
# definition is "every LLM attempt has failed" (providers.py: backoff ladder -> one degraded-model attempt
# -> raise), so a provider outage is the floor's most likely cause -- and until now it landed in `other`,
# indistinguishable from a code bug. The 2026-07-19 incident cost hours because "the model tier is down"
# and "our retrieval is broken" produced the same telemetry. These are TYPE-and-message classifications
# over the anthropic SDK's own availability errors (providers.RETRYABLE = RateLimitError,
# APIConnectionError, InternalServerError -- 529 overloaded arrives as InternalServerError), which reach
# the floor UNWRAPPED: serving_call re-raises the original exception after the degraded attempt fails.
_FLOOR_CAUSES = ("pg_statement_timeout", "pg_operational", "model_download", "llm_unavailable", "other")

# Bounded, and matched against the TYPE NAME only -- never raw message text, so no user/provider string can
# mint a dimension value. Bedrock's InvokeModel throttle/unavailability names are included because serving
# is provider-routable (GRAPHRAG_PROVIDER=bedrock uses AnthropicBedrock over bedrock-runtime).
_LLM_UNAVAILABLE_TYPES = (
    "ratelimiterror",             # 429, both providers
    # Every entry must match a name that ACTUALLY EXISTS -- substring matching does NOT follow the class
    # hierarchy. anthropic.APITimeoutError subclasses APIConnectionError, but its NAME is
    # "apitimeouterror", which does not contain "apiconnectionerror", so the subclass needs its own row.
    # Verified against the installed SDK's exports (2026-07-28), not from memory: APIConnectionError,
    # APITimeoutError, InternalServerError, OverloadedError, RateLimitError all exist under these names.
    "apiconnectionerror",         # anthropic.APIConnectionError -- connection refused/reset/DNS
    "apitimeouterror",            # anthropic.APITimeoutError (a SUBCLASS of the above; distinct name)
    "internalservererror",        # >=500 incl. 529 overloaded_error
    "overloadederror",
    "serviceunavailable",         # botocore: ServiceUnavailableException
    "throttlingexception",        # botocore: bedrock-runtime throttle
    "modelnotready",              # botocore: ModelNotReadyException
)


def _floor_cause(exc: BaseException) -> str:
    """One of `_FLOOR_CAUSES`, from the exception's TYPE NAME *and* its message. Both, because the same
    failure surfaces differently by driver: psycopg raises `QueryCanceled` while a wrapper re-raises the
    identical "canceling statement due to statement timeout" text as `OperationalError`, and the model
    download arrives as a bare `OSError` whose message is the ONLY signal. The timeout test runs before the
    generic pg one so a QueryCanceled can never land in `pg_operational`.

    ORDER MATTERS and the LLM test is deliberately LAST before `other`: an availability error raised while
    a pg statement was timing out is still a pg incident, and `model_download` (bge, the rerank fallback)
    is a retrieval-side outage, not an LLM-tier one. Only what nothing else claims can be llm_unavailable.
    """
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "querycanceled" in name or "statement timeout" in msg or "canceling statement" in msg:
        return "pg_statement_timeout"
    if "huggingface" in msg or ("couldn't connect to" in msg and "load the files" in msg):
        return "model_download"
    if "operationalerror" in name or "operationalerror" in msg or "psycopg" in msg:
        return "pg_operational"
    if any(t in name for t in _LLM_UNAVAILABLE_TYPES):
        return "llm_unavailable"
    return "other"


def _floor_log(kind: str, exc: BaseException) -> str:
    """ONE structured ASCII line per floor turn, emitted AT the seam -- before the floor's own retrieval
    runs, so it lands even when that retrieval is the thing hanging -- and returns the cause slug for the
    trace + the `FloorTurns` dimension. The format is APPEND-ONLY: `kind=` and the trailing raw
    `cause=<Type>: <message>` are unchanged from the pre-F4a line (the 137 `[floor]` records the RCA read
    stay greppable), with the bounded `cause_class=` inserted between them. The raw tail is newline-stripped
    and ascii-replaced so a multi-line/UTF-8 driver message cannot split the record or kill a cp1252 stdout."""
    slug = _floor_cause(exc)
    raw = str(exc)[:200].replace("\n", " ").replace("\r", " ").encode("ascii", "replace").decode()
    print(f"[floor] kind={kind} cause_class={slug} cause={type(exc).__name__}: {raw}", flush=True)
    return slug


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
    # an._RETRIEVAL carries rerank=True, so a SERIAL loop over the <=2 contracts issued TWO uncoalesced
    # Bedrock requests against a 3-req/min ceiling — on the population that is already the slowest in the
    # fleet (floor turns: p50 242.6 s, p95 1,163.6 s). Hint the coalescer and overlap the contracts so the
    # floor costs ONE request. Results are re-assembled in CONTRACT order below, so the dedup order, the
    # citation order and the banner body are byte-identical to the sequential loop.
    from leviathan.graphrag import rankers as rk

    def _hits(c):
        try:
            return retr(query, c, k=5, asof=asof, near=near)
        except Exception:  # noqa: BLE001 — evidence store down too -> banner-only floor
            try:
                rk.rerank_unexpect()               # a promised arrival that died; don't strand the leader
            except Exception:  # noqa: BLE001
                pass
            return []

    if len(contracts) > 1:
        try:
            if rk._rerank_backend() == "bedrock":
                rk.rerank_expect(len(contracts))
        except Exception:  # noqa: BLE001 — a hint miss only costs latency, never correctness
            pass
        import concurrent.futures as _cf
        with _cf.ThreadPoolExecutor(max_workers=len(contracts)) as _pool:
            per_contract = list(_pool.map(_hits, contracts))
    else:
        per_contract = [_hits(c) for c in contracts]
    evidence, seen = [], set()
    for c, hits in zip(contracts, per_contract):
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
        # W6.1-0 stage attribution: mirror every per-stage timer the branches stamped into trace (a stage
        # that did NOT run leaves its key absent -> None here, no zero-fill) so the eval sees the breakdown.
        tr["timing_ms"] = {"total": total, "fill": gm.get("fill"), "rest": gm.get("rest"),
                           "dispatch": tr.get("ms_dispatch"), "numbers": tr.get("ms_numbers"),
                           "synth_llm": tr.get("ms_synth_llm"), "quantify": tr.get("ms_quantify"),
                           "rollup": tr.get("ms_rollup")}
        stripped = int((tr.get("citation_verifier") or {}).get("stripped", 0) or 0)
        # print() (not logging) so the line reaches CloudWatch even though the app root logger sits at WARNING
        # under uvicorn — ASCII-only, flushed. Human-readable companion to the EMF metric line below.
        print(f"[timing] total_ms={total} intent={res.get('intent')} model={res.get('model')} "
              f"ms_fill={gm.get('fill')} ms_rest={gm.get('rest')} stripped={stripped}", flush=True)
        # Stage 5.3 R3: emit the same numbers as CloudWatch EMF -> auto-extracted metrics (Leviathan/Serving)
        # feeding the serving dashboard. StripCount ties the primary quality signal (verifier strips) into ops.
        # RF-6 NOW batch: cascade firing-rate counters off the per-node quantify trace (count metrics only —
        # no values, no PIT exposure); they price whether reroute polish (Option B visual) is ever worth it.
        qt = [t for t in (tr.get("quantify") or []) if isinstance(t, dict)]
        # RF-6 batch 2: reroute counters ride the PAIR-level quantify_reroute trace, which carries FIRED
        # (opposite-sign) pairs ONLY -- so RerouteFired counts turns with a real cross-country fork, and
        # MultiCountryTurn counts turns whose FIRED pairs span >=2 countries (not candidacy; no candidate
        # trace exists by design). These price whether the Option-B bespoke visual is ever worth building.
        rt = [t for t in (tr.get("quantify_reroute") or []) if isinstance(t, dict)]
        rt_countries = {c for t in rt for c in (t.get("countryA"), t.get("countryB")) if c}
        # W6.1-0 cited-vs-injected [N]: distinct handles in the FINAL answer vs rows injected into the
        # prompt. If CitedN << InjectedN most cascade rows are injected-but-uncited, so CASCADE_CAP can
        # drop with near-zero loss. Both carry 0-semantics (always present, like CascadeFired).
        # OutputTokens is NOT available: providers.serving_call DISCARDS usage (`out, _ = ...`), so the
        # synthesis result exposes no token count without new plumbing -> AnswerChars is the honest proxy.
        _ans = res.get("answer") or ""
        injected_n = int(tr.get("injected_n") or 0)
        cited_n = len(set(re.findall(r"\[N\d+\]", _ans)))
        # RV2 W2 dark observables (S3-F1, S2-4): XcLlmWouldFire counts planner would-fires REGARDLESS of
        # the GRAPHRAG_XC_LLM_DETECT flag (the D20 counted-soak channel -- response dicts alone are not a
        # queryable surface); PlannerFallback is 1 iff dispatch actually RAN (ms_dispatch stamped) and no
        # llm plan resulted (the W4 hard-bound metric -- injected-classify and trivial/guardrail turns
        # never count). The ASCII log line is the Logs Insights grep surface for per-turn user disposition
        # (scripts/xc_soak_scan.py); the span is model output, so it is ascii-replaced defensively.
        dec = res.get("intent_decision") or {}
        xc_would = 1 if dec.get("xc_explicit") is True else 0
        planner_fb = 1 if (tr.get("ms_dispatch") is not None and dec.get("planner") != "llm") else 0
        if xc_would:
            _sess = res.get("session") or {}
            _tid = f"{_sess.get('id')}/{_sess.get('turn')}" if _sess.get("id") else "-"
            _tgt = str(dec.get("xc_target") or "").encode("ascii", "replace").decode()
            print(f"XC_DETECT_DARK turn={_tid} target={_tgt}", flush=True)
        from leviathan.graphrag import emf
        # Stage timers (Ms*) pass None when the stage did not run; emf.emit drops None -> NO zero-fill.
        emf.emit({"TurnLatencyMs": total, "MsFill": gm.get("fill"), "MsRest": gm.get("rest"),
                  "MsDispatch": tr.get("ms_dispatch"), "MsNumbers": tr.get("ms_numbers"),
                  "MsSynthLLM": tr.get("ms_synth_llm"), "MsQuantify": tr.get("ms_quantify"),
                  "MsRollup": tr.get("ms_rollup"),
                  "StripCount": stripped, "CascadeFired": 1 if qt else 0, "CascadeNodes": len(qt),
                  "DivergenceNodes": sum(1 for t in qt if t.get("divergence")),
                  "RerouteFired": 1 if rt else 0,
                  "MultiCountryTurn": 1 if len(rt_countries) >= 2 else 0,
                  "CitedN": cited_n, "InjectedN": injected_n, "AnswerChars": len(_ans),
                  # F1 counter: 1 on a trivial-router short-circuit (trace.trivial stamped by _trivial_answer),
                  # else 0. Social turns emit under intent="social"/model="(canned)" -- a fresh dimension
                  # bucket that never pollutes the reasoning/hybrid/numbers strip metrics (0-semantics, like
                  # CascadeFired). Always 0 when GRAPHRAG_TRIVIAL_ROUTER is off (no turn stamps trace.trivial).
                  "TrivialShortCircuit": 1 if tr.get("trivial") else 0,
                  "XcLlmWouldFire": xc_would, "PlannerFallback": planner_fb},
                 dimensions={"intent": res.get("intent"), "model": res.get("model")},
                 units={"TurnLatencyMs": "Milliseconds", "MsFill": "Milliseconds",
                        "MsRest": "Milliseconds", "MsDispatch": "Milliseconds", "MsNumbers": "Milliseconds",
                        "MsSynthLLM": "Milliseconds", "MsQuantify": "Milliseconds", "MsRollup": "Milliseconds",
                        "StripCount": "Count", "CascadeFired": "Count",
                        "CascadeNodes": "Count", "DivergenceNodes": "Count", "RerouteFired": "Count",
                        "MultiCountryTurn": "Count", "CitedN": "Count", "InjectedN": "Count",
                        "AnswerChars": "Count", "TrivialShortCircuit": "Count",
                        "XcLlmWouldFire": "Count", "PlannerFallback": "Count"})
        if tr.get("floor"):
            # F4a: floor turns are COUNTED, split by the bounded cause slug. A SEPARATE EMF line on purpose:
            # folding `cause` into the block above would re-dimension every metric in it and fork the
            # per-(intent, model) series the 5.2 dashboard reads. No 0-semantics either -- FloorTurns is
            # ABSENT on healthy turns, so any non-zero sum is a real failure and SUM alarms need no filter.
            emf.emit({"FloorTurns": 1},
                     dimensions={"intent": res.get("intent"), "cause": tr.get("floor_cause") or "other"},
                     units={"FloorTurns": "Count"})
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

    # ── trivial-turn router (F1) ──────────────────────────────────────────────────────────────────
    # Short-circuit a pure greeting/smalltalk/meta turn to a canned mentor reply BEFORE session load and the
    # dispatch planner, saving two Sonnet calls. Placed EARLIEST (mirrors the guardrail early-return, and
    # # v1 default (plan D9): earliest wins): a greeting is never persisted to thread history and never wipes
    # coreference/as-of carry -- it returns ABOVE session load AND above _session_writeback, so session state
    # is untouched BY CONSTRUCTION. is_trivial is deterministic-only (# v1 default (plan D2): NO Haiku fallback
    # -- an ambiguous turn returns None and falls through). Off-topic-but-real questions also fall through
    # (# v1 default (plan D8): canned scope-reply is for pure-social turns only). FAIL-OPEN: any classifier
    # error -> None -> normal pipeline (parity with the guardrail). Quota is unchanged (# v1 default (plan D4):
    # a short-circuit saves Bedrock spend but does NOT refund the daily turn counter, which increments at the
    # route dependency before respond() runs -- making greetings quota-free is the D4 route-gate follow-up).
    if _trivial_router_on():
        try:
            _klass = it.is_trivial(query)
        except Exception:  # noqa: BLE001 — the router must NEVER break an answer (guardrail parity)
            _klass = None
        if _klass is not None:
            an._emit(on_stage, "social", klass=_klass)   # one stage tick so SSE relays it as a normal turn
            return _trivial_answer(query, _klass)         # never touches session state (returns above load)

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
    elif call is None:                                                       # real serving, no session: still
        from leviathan.graphrag.numbers import query as Q  # give the cascade loop a pg-routed
        qfn = query_fn or Q.default_query_fn()                               # qfn (mirrors silver_lookup's guard)

    # Silver leg (F4): OBSERVED driver values feed regime firing. Built only on the REAL serving path
    # (call is None) so injected-fake tests stay hermetic; GRAPHRAG_SILVER=off is the rollback.
    silver_lookup = None
    if call is None and os.environ.get("GRAPHRAG_SILVER", "on") != "off":
        from leviathan.graphrag import silverleg as slv
        # T1: GRAPHRAG_CONVERGENCE_INTENSITY is read at THIS seam and threaded as a kwarg (the
        # GRAPHRAG_COMOVE idiom); silverleg itself never reads the env. Default-off => byte-identical.
        silver_lookup = slv.make_silver_lookup(graph, qfn, intensity=an._intensity_on())

    # ── dispatch tier (planner v1) ────────────────────────────────────────────────────────────────
    # One enum-locked planning call resolves {steps, contracts, asof, near} with the session state in
    # view — the fix for the state-blind classifier (convo eval: pronoun follow-ups misrouted to
    # numbers before coreference ran). An injected `classify` (tests) or any planner failure keeps the
    # legacy path below byte-for-byte. The plan NEVER overrides the caller's explicit as-of, and a
    # live step still runs behind the as-of kill-switch — the plan is advice, the guards are law.
    plan, decided, near = None, None, None
    _ms_dispatch = None
    if classify is None:
        import time as _time
        from leviathan.graphrag import dispatch as dp
        _t_disp = _time.perf_counter()                             # W6.1-0 stage timer (MsDispatch)
        p = dp.plan_turn(query, graph=graph, state_block=sblock, today=_today(),
                         state_contracts=(state.contracts if state else None), call=call)
        _ms_dispatch = int((_time.perf_counter() - _t_disp) * 1000)
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
            an._emit(on_stage, "plan", intent="live", contracts=[])   # F7: the legacy-path twin of the tick above
            _ctx = [c for c in ((state.contracts if state else None) or []) if c in graph.contracts] or None
            try:
                res = run_live(query, asof, graph=graph, call=call, retrieve=retrieve, model=model, planner=planner,
                               on_stage=on_stage, context_contracts=_ctx, route_fn=route_fn, qfn=qfn)
            except Exception as e:  # noqa: BLE001 — deterministic floor: a UI turn must never 500
                _cause = _floor_log("live", e)      # F4a: this seam logged NOTHING at all before
                an._emit(on_stage, "floor")
                res = _evidence_only(query, asof, graph=graph, kind="live", exc=e, route_fn=route_fn)
                res.setdefault("trace", {})["floor_cause"] = _cause   # bounded slug -> FloorTurns dimension
            res["intent_decision"] = {"intent": res["intent"], "live_checked": True}
            return _session_writeback(res, query, asof, session_id, store, state, graph, call,
                                      ms_dispatch=_ms_dispatch)
        decided = (classify or it.classify_intent)(query, call=call)
        kind = decided["intent"]

    # W2.5/W3.7 routing tiebreak -- covers BOTH the planner and the classify paths (the first placement
    # sat only on the classify fallback, so every planner-routed turn bypassed it and the W3.7 rerun
    # proved the decline rows still landed on reasoning). A price ask naming a NONE-tier commodity
    # (robusta, JSE maize, the fenced US farm price, ...) resolves to no tracked contract, so intent
    # lands on reasoning/hybrid -- but the deterministic decline preface only fires on the pure-numbers
    # path, and a reasoning-lane answer would improvise around a price series we do not govern. The
    # guard detector IS the router here: if it fires, the honest lane is numbers_only by construction.
    # Live turns are exempt (a NONE-tier price ask never legitimately routes live anyway; if the planner
    # said live, the news path owns it).
    if kind in ("reasoning", "hybrid"):
        try:
            from leviathan.graphrag.numbers.agent import price_coverage_scope
            if price_coverage_scope(query):
                kind = "numbers_only"
                decided = {**decided, "intent": "numbers_only", "price_decline_reroute": True}
        except Exception:  # noqa: BLE001 -- the tiebreak must never break a turn
            pass

    # ── data-family facet (F2 durable fix): PROMOTION-ONLY reasoning->hybrid ─────────────────────────────
    # The judged-30 misses were colloquial positioning/pace asks the dispatch planner routed reasoning-only,
    # so the observed series never got looked up. This is the two-tier shape of rv2 detection: the planner
    # emits plan.data_families (strict-validated against the registry enum, dark by default), and consumption
    # is gated + promotion-only. It fires ONLY when: the plan exists (injected-classify/guardrail/trivial turns
    # leave plan=None and are BYPASSED by construction -- mirrors the rv2 gate's plan-scoped read), the LLM
    # route was reasoning (never numbers_only/live -- those already reach numbers or the news path; never a
    # demotion), families are non-empty, and the kill-switch is on. Fail-closed like _reroute_v2_on: flag off
    # => no-op => byte-identical to today. The deterministic _NUM vocab remains the independent floor.
    if (kind == "reasoning" and plan is not None and plan.data_families and _family_facet_on()):
        kind = "hybrid"
        decided = (decided or {}) | {"intent": "hybrid", "family_facet_promoted": True,
                                     "family_facet_families": list(plan.data_families)}
        print("FAMILY_FACET_PROMOTED families=" + ",".join(plan.data_families))  # ASCII soak-grep surface

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
    # F7 `plan`: the SAME decision, in the content-bearing contract — dispatch has resolved intent + the
    # routed contracts, and this is the first thing in a turn the user could be shown. `kind` rides
    # VERBATIM: the pinned enum names the three engine intents, but "live" is a real fourth outcome and
    # inventing a substitute here would be a lie about what the dispatcher decided (the FE ignores kinds
    # it does not know — invariant 3).
    an._emit(on_stage, "plan", intent=kind, contracts=_tick_contracts)

    # ── reroute v2 gate (RV-W1.3): the deterministic LAW that produces the cross-commodity request. It runs
    # ONLY on the two branches that reach the cascade quantify seam (reasoning/hybrid), ONLY when the flag is
    # on, and is fully fail-closed (any error -> None). The env flag gates whether the gate may compute a
    # request at all; the ENGINE (lane C) is gated by the xc_request ARGUMENT, never by reading the flag --
    # so a mis-plumbed enable can never fire the fork on an unasked turn (C9). Flag off => None => the
    # reasoning/hybrid call is byte-identical to today.
    # W2 (D7): detection is ATTRIBUTED on every reasoning/hybrid turn, incl. DECLINED and v2-flag-off ones
    # -- the gate returns bare None, so this is the only place a decline is attributable. The shared
    # composite (built here, plan in scope) rides the EXISTING detect= seam so the LAW body is untouched;
    # the direct call below is idempotent with the gate's own (pure regex + dataclass reads, cannot raise).
    xc_request = None
    if kind in ("reasoning", "hybrid"):
        _xc_det = xc_detect_two_tier(plan)
        _, _xc_span = _xc_det(query)
        decided = (decided or {}) | {"xc_detect": {"tier": _xc_det.tier or "none",
                                                   "llm_consulted": bool(_xc_det.llm_consulted),
                                                   "target_span": _xc_span}}
        if _reroute_v2_on():
            xc_request = _xc_request(query, graph=graph, state=state, detect=_xc_det)
    # ── W5-D4: the outlook gate, TWO-TIER and FAIL-CLOSED ────────────────────────────────────────────────
    # outlook fires IFF plan.answer_mode_outlook (the LLM detection) AND intent.is_outlook_explicit(query)
    # (a deterministic regex NECESSARY condition) -- the RV2 `_xc_request` shape, which requires both tiers
    # and returns nothing on any failure. The third leg, the GRAPHRAG_OUTLOOK kill-switch, is ANDed at the
    # answer.py seam so the engine is gated by the ARGUMENT, never by a flag read deep in the stack.
    #
    # Why this one inverts the usual asymmetry: every other misroute here is fail-OPEN and that is correct
    # -- a numbers question misrouted to reasoning still gets a grounded answer. If a plain mechanism
    # question landed in outlook, the market register would relax on a turn that never asked for it, which
    # is the exact failure the fence exists to prevent. A MISSED outlook ask degrades to today's answer.
    # Restricted to reasoning/hybrid: outlook is a rendering mode over the REASONER's output, so a
    # numbers_only/live/trivial turn (plan is None on the guardrail paths) can never carry it.
    outlook_mode = False
    if kind in ("reasoning", "hybrid") and plan is not None and plan.answer_mode_outlook:
        outlook_mode = it.is_outlook_explicit(query)
        decided = (decided or {}) | {"outlook_gate": {"plan": True, "regex": outlook_mode}}
    try:
        if kind == "live":
            # Thread coreference reaches the news SEARCH ("any news related to that?"): the plan's
            # resolved contracts first, else the session's carried contracts (root-cause fix, part 2).
            _ctx = [c for c in ((list(plan.contracts) if plan else None)
                                or (state.contracts if state else None) or []) if c in graph.contracts] or None
            res = run_live(query, asof, graph=graph, call=call, retrieve=retrieve, model=model, planner=planner,
                           on_stage=on_stage, context_contracts=_ctx, route_fn=route_fn, qfn=qfn)
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
            _emit_numbers(on_stage, res.get("number_calls"))       # F7 `number`: the numbers-only lane's twin
        elif kind == "hybrid":
            res = run_hybrid(query, asof, graph=graph, call=call, retrieve=retrieve, model=model,
                             client=numbers_client, numbers_model=numbers_model, query_fn=qfn, planner=planner,
                             extra_context=sblock, route_fn=route_fn, near=near, silver_lookup=silver_lookup,
                             on_stage=on_stage, focus_driver=att["focus_driver"], xc_request=xc_request,
                             outlook=outlook_mode)
        else:
            res = run_reasoning(query, asof, graph=graph, call=call, retrieve=retrieve, model=model,
                                planner=planner, extra_context=sblock, route_fn=route_fn, near=near,
                                silver_lookup=silver_lookup, on_stage=on_stage,
                                focus_driver=att["focus_driver"], qfn=qfn, xc_request=xc_request,
                                outlook=outlook_mode)
    except Exception as e:  # noqa: BLE001 — deterministic floor: a UI turn must never 500
        # The floor's CAUSE must be visible in logs: the 2026-07-19 incident spent hours attributing
        # an Anthropic-tier outage to a feature flag because the swallowed exception was never logged
        # (trace.error carries it to the caller, but batch/eval logs only showed the floor).
        # F4a: the same line, now carrying a BOUNDED cause_class the FloorTurns metric can be split by.
        _cause = _floor_log(kind, e)
        an._emit(on_stage, "floor")
        res = _evidence_only(query, asof, graph=graph, kind=kind, exc=e, route_fn=route_fn, near=near)
        res.setdefault("trace", {})["floor_cause"] = _cause   # additive: trace.error keeps the raw string
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
    return _session_writeback(res, query, asof, session_id, store, state, graph, call,
                              ms_dispatch=_ms_dispatch)


# Test/observability hook (W6.1-1): when set to a callable, it receives the daemon Thread that each async
# roll_summary spawns, so a test can join it deterministically. None in production -> strict no-op.
_rollup_observer = None


def _spawn_rollup(base_state, turn, graph, call, store, session_id, tr, *, intent=None):
    """Fire-and-forget the Phase-2 summary roll onto a daemon thread so its Haiku forced-tool round-trip
    leaves the turn's critical path (W6.1-1). FAIL-OPEN: every error is swallowed (parity with the
    synchronous path's try/except). THREAD-SAFETY: `call` (an._call_opus) builds its OWN provider client
    per invocation, so no client instance is shared with the main thread; the store client (boto3 or the
    in-memory dict store) is touched ONLY here, post-handoff; and `base_state`/`turn` are no longer read
    by the main thread once the HTTP response has been returned. The rollup's own duration is timed INSIDE
    the thread and emitted as a STANDALONE EMF line -- it is necessarily absent from this turn's EMF block
    (already emitted by the time the thread finishes), the accepted W6.1-1 tradeoff."""
    import threading
    import time as _time

    from leviathan.graphrag import session as ss

    def _run():
        try:
            _t = _time.perf_counter()
            new_state = ss.roll_summary(base_state, turn, graph=graph, call=call)
            store.put_state(session_id, new_state)
            ms = int((_time.perf_counter() - _t) * 1000)
            tr["ms_rollup"] = ms                                  # recorded for holders/tests (post-EMF; benign)
            try:
                from leviathan.graphrag import emf
                emf.emit({"MsRollup": ms}, dimensions={"intent": intent},
                         units={"MsRollup": "Milliseconds"})      # keeps async-rollup latency observable
            except Exception:  # noqa: BLE001 — telemetry must never surface
                pass
        except Exception:  # noqa: BLE001 — async rollup must never surface an error
            pass

    th = threading.Thread(target=_run, name="graphrag-rollup", daemon=True)
    th.start()
    if _rollup_observer is not None:
        try:
            _rollup_observer(th)
        except Exception:  # noqa: BLE001 — the observer is a test hook; it can never fail a turn
            pass
    return th


def _session_writeback(res: dict, query: str, asof: str, session_id, store, state, graph, call,
                       *, ms_dispatch: Optional[int] = None) -> dict:
    """Append the TurnRecord + roll the Phase-2 summary. Ids and short strings only — the PIT firewall.
    W6.1-0: stamp MsDispatch here (the single choke point). W6.1-1: by default the summary roll fires onto
    a daemon thread (GRAPHRAG_ROLLUP_ASYNC, default on) so its Haiku round-trip leaves the critical path;
    'off' restores the exact synchronous pre-W6.1-1 behavior."""
    import os

    tr = res.setdefault("trace", {})
    # Graph identity stamp (audit/reproducibility): every real answer records WHICH causal graph produced
    # it. Done here — the single choke point both the main branch and the live early-return pass through —
    # and BEFORE the no-session early return, so it lands whether or not a session is active.
    tr["graph_version"] = getattr(graph, "version", None)
    if ms_dispatch is not None:
        tr["ms_dispatch"] = ms_dispatch                          # W6.1-0 stage timer (dispatch.plan_turn)
    if not (store and session_id):
        return res
    import time as _time

    from leviathan.graphrag import session as ss
    try:
        # W5 F-H (the session-carry seam). The tl;dr is CONTINUITY CONTEXT, not the answer: session.py
        # renders it into the next turn's state block and roll_summary() bakes it into durable state. An
        # outlook turn's permitted A1/flow/mood vocabulary would therefore be carried into turn N+1 -- a
        # plain mechanism question running the FENCED register -- as prompt context, and a stateless
        # regression deck structurally cannot see it. So this is sanitized market_register="fenced"
        # UNCONDITIONALLY, whatever register produced the turn. The served answer keeps its own register;
        # only what CROSSES INTO THE NEXT TURN is re-fenced.
        _tldr = str((res.get("structured") or {}).get("tldr") or res.get("answer") or "")
        turn = ss.TurnRecord(
            turn=(state.turn_count if state else 0), query=query[:300],
            answer_tldr=reg.sanitize(_tldr, market_register=reg.FENCED)[:200],
            contracts=[c for c in (res.get("contracts") or [res.get("contract")]) if c],
            focus_driver=tr.get("focus_driver"), asof=asof,
            fired_regime_names=[r.get("name") for r in tr.get("fired_regimes") or []],
            intent=res.get("intent", ""), ts=_time.time())
        store.append_turn(session_id, turn)
        base_state = state or ss.SessionState()
        rcall = call or an._call_opus
        if os.environ.get("GRAPHRAG_ROLLUP_ASYNC", "on").lower() == "off":
            _t_roll = _time.perf_counter()                       # SYNC: exact pre-W6.1-1 behavior, timed inline
            new_state = ss.roll_summary(base_state, turn, graph=graph, call=rcall)
            store.put_state(session_id, new_state)
            tr["ms_rollup"] = int((_time.perf_counter() - _t_roll) * 1000)   # in-block (respond reads it)
        else:
            _spawn_rollup(base_state, turn, graph, rcall, store, session_id, tr,
                          intent=res.get("intent"))              # ASYNC: off the critical path (default)
        res["session"] = {"id": session_id, "turn": turn.turn}
    except Exception:  # noqa: BLE001 — the answer is already computed; never lose it to a store error
        res["session"] = {"id": session_id, "error": "store_unavailable"}
    return res
