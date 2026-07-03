"""graphdev honest eval (GRAPHRAG_PLAN v2 Phase 2 WS-4 / WS-MS5).

Runs configs/graphrag/eval_queries.yaml through answer.answer() and writes a markdown report with a
lightweight auto-rubric (routed-right / expected-drivers-mentioned / regime-named / evidence-cited), an
LLM-judge quality score, and a SOURCE-DIVERSITY panel (distinct sources + trust-tiers cited, trust-ordering,
cross-tier disagreement flagged) — the WS-MS5 multi-source lift. Serving defaults to Sonnet (production),
with an Opus judge. The rubric is approximate — the report + a human read are the real judges.

    python -m leviathan.graphrag.eval --dry-run            # cost estimate, no spend
    python -m leviathan.graphrag.eval --run --model claude-sonnet-4-6
"""
from __future__ import annotations

import argparse

import yaml

from leviathan.graphrag import answer as an
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import extract as ex
from leviathan.graphrag import graph as gph
from leviathan.graphrag import register as reg

_QUERIES = ex._CFG / "eval_queries.yaml"
_OUT = ex._CFG / "eval"


def load_queries(path=_QUERIES) -> list[dict]:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("queries") or []


_NOT_KNOWN = ("not known", "not yet known", "not yet been", "no data", "not available", "wasn't published",
              "was not published", "not published", "not been published", "unavailable")


def score(q: dict, out: dict) -> dict:
    """Approximate auto-rubric + v3 routing/point-in-time checks (expected_intent, leakage-trap)."""
    exp = q.get("expect") or {}
    ans = ex._normalize(out.get("answer") or "")
    drivers = exp.get("drivers") or []
    hit = [d for d in drivers if ex._normalize(d) in ans]
    exp_intent, routed_intent = q.get("expected_intent"), out.get("intent")
    leakage_ok = None
    if exp.get("not_known"):                                          # trap: the tool must SAY the value isn't known at asof
        leakage_ok = any(p in (out.get("answer") or "").lower() for p in _NOT_KNOWN)
    return {"routed_right": out.get("contract") == q["contract"],
            "intent_ok": (routed_intent == exp_intent) if exp_intent else None,
            "routed_intent": routed_intent, "expected_intent": exp_intent, "leakage_ok": leakage_ok,
            "drivers_hit": f"{len(hit)}/{len(drivers)}", "drivers_missed": [d for d in drivers if d not in hit],
            "regime_named": (ex._normalize(exp["regime"]) in ans) if exp.get("regime") else None,
            "evidence_cited": (len(out.get("evidence") or []) > 0) if exp.get("needs_evidence") else None}


def run(graph: gph.CausalGraph, queries: list[dict], *, model: str = an.SONNET, k: int = 5, answer_fn=None,
        via_orchestrator: bool = False, numbers_client=None, call=None, planner: str | None = None,
        workers: int = 1) -> list[dict]:
    """Run each query through answer() (default) or — with via_orchestrator — the full intent branch
    orchestrator.respond() (numbers_only / reasoning / hybrid), passing each question's point-in-time asof.
    `planner='l2'` routes reasoning/hybrid through the deterministic grounded-subgraph walk (A/B vs one-hop).
    `workers>1` answers independent questions concurrently — the per-question chain is dominated by LLM
    network waits, so threads cut wall-clock ~workers-fold at identical API cost (psycopg3 connections,
    torch inference and the Anthropic client are all thread-safe). Row order always matches `queries`."""
    answer_fn = answer_fn or an.answer
    import time as _time

    def _one(q: dict) -> dict:
        t0 = _time.monotonic()
        try:                                                          # one bad answer must NOT abort a billed run
            if via_orchestrator:
                from leviathan.graphrag import orchestrator as orch
                okw = dict(graph=graph, asof=q.get("asof"), model=model, numbers_client=numbers_client, call=call)
                if planner:                                           # keep the call identical for injected fake respond()
                    okw["planner"] = planner
                out = orch.respond(q["question"], **okw)
            else:
                kw = dict(graph=graph, model=model, k=k, asof=q.get("asof"), near=q.get("near"))
                if planner:                                           # keep the call identical for injected fake answer_fns
                    kw["planner"] = planner
                out = answer_fn(q["question"], **kw)
            print(f"  answered {q.get('id')} in {_time.monotonic() - t0:.0f}s", flush=True)
        except Exception as e:  # noqa: BLE001
            out = {"answer": f"(answer failed: {str(e)[:200]})", "contract": None, "structured": None,
                   "evidence": [], "intent": None, "number_calls": [], "citations": [], "model": model,
                   "trace": {"error": str(e)[:300]}}
            print(f"  WARN {q.get('id')}: answer failed -- {str(e)[:120]}", flush=True)
        return {"q": q, "out": out, "rubric": score(q, out)}

    if workers <= 1:
        return [_one(q) for q in queries]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=workers) as pool:              # map preserves input order
        return list(pool.map(_one, queries))


# ── LLM-judge: a quant/hedge-fund analyst rates usefulness + exposes gaps ──────────────
def _judge_tool(continuity: bool = False) -> dict:
    n = {"type": "integer"}                                            # 1-5
    arr = {"type": "array", "items": {"type": "string"}}
    props = {"usefulness": n, "convexity": n, "point_in_time": n, "grounding": n, "source_diversity": n,
             "hallucinations": arr, "gaps": arr, "improvements": arr, "verdict": {"type": "string"}}
    required = ["usefulness", "convexity", "point_in_time", "grounding", "source_diversity", "gaps", "verdict"]
    if continuity:                                                     # multi-turn: did it read the conversation right?
        props["continuity"] = n
        required = required + ["continuity"]
    return {"name": "score_answer",
            "description": "A senior quant RESEARCHER's verdict on a fundamental convexity-shock answer.",
            "input_schema": {"type": "object", "properties": props, "required": required}}


_JUDGE_SYS = (
    "You are a SENIOR QUANTITATIVE RESEARCHER pressure-testing a FUNDAMENTAL CONVEXITY-SHOCK research tool (NOT a "
    "trading system). It helps researchers understand HOW supply/demand shocks propagate through commodity balance "
    "sheets and WHERE the price response turns convex (buffer exhaustion, tipping thresholds, regime switches). You "
    "are shown the QUESTION (with any as-of date), the curated causal graph + dated evidence + any OBSERVED NUMBERS "
    "the tool looked up, and the tool's ANSWER. CRITICAL: this is a research tool — do NOT expect or reward position "
    "sizing, price targets, or 'how much to trade'; that is OUT OF SCOPE. Reward mechanism, convexity/regime insight, "
    "point-in-time discipline, and grounding. Be demanding and specific:\n"
    "- usefulness (1-5): does it give a researcher real insight into the shock's STRUCTURE — mechanism, the drivers "
    "that matter, the regime — or is it vague restatement / textbook filler?\n"
    "- convexity (1-5): does it correctly locate WHERE the response is convex vs linear, the buffer/threshold that "
    "makes it tip, and through which channel? 5 = precise convexity mechanism; 1 = ignores convexity or asserts it "
    "with no mechanism. (If the question isn't about convexity, judge the shock-propagation reasoning instead.)\n"
    "- point_in_time (1-5): did it respect the as-of date — use AS-KNOWN values, correctly say a value was 'not "
    "known' when it wasn't yet published, never leak future data? 5 = clean; 1 = leaks/ignores the as-of. If the "
    "question has NO as-of, score 5.\n"
    "- grounding (1-5): are specific claims (drivers, signs, dated observed numbers) backed by the cited evidence, "
    "the looked-up NUMBERS, or the authoritative graph? (Naming the graph's own drivers/regimes/signs is "
    "AUTHORITATIVE, not hallucination.)\n"
    "- source_diversity (1-5): multiple sources across trust tiers (T1 official WASDE/FAS ... T4 macro), "
    "trust-ordered, disagreements flagged? Only high if multiple sources were actually AVAILABLE.\n"
    "- hallucinations: any claim/number/sign/date supported by NEITHER the graph, the evidence, NOR the looked-up "
    "numbers.\n"
    "- gaps: what a researcher would still need — a missing propagation channel, no dated evidence, convexity "
    "asserted without a threshold, a missed regime or cross-commodity leg. Concrete.\n"
    "- improvements: concrete changes.\n- verdict: one blunt sentence.\n"
    "Emit via score_answer.")


def judge(query: dict, out: dict, *, graph=None, client=None, model: str = "claude-opus-4-8", call=None,
          convo_history: str | None = None) -> dict:
    """The quant-researcher persona scores the answer — shown the SAME graph + evidence + looked-up NUMBERS the tool
    had, so it can tell grounded from invented and check point-in-time discipline. With `convo_history` (multi-turn
    eval) the judge also scores CONTINUITY: did the answer interpret the vague/pronoun follow-up correctly given
    the prior turns, and respect THIS turn's as-of rather than a stale one?"""
    call = call or ex.call_opus
    ctx = ""
    if graph is not None:
        from leviathan.graphrag import answer as an
        ctx = "\n\n".join(an._context_block(graph, c) for c in (out.get("contracts") or [out.get("contract")]) if c)
    ev_text = "\n".join(f"- ({e['source']}, {e['date']}) {e.get('text', '')}" for e in out.get("evidence") or [])
    num_text = ""
    for c in out.get("number_calls") or []:                          # the observed values the tool actually looked up
        qy, rws = c.get("query", {}), (c.get("rows") or [])
        val = rws[0].get("value") if rws else "(NOT KNOWN at asof)"
        num_text += (f"- {qy.get('table')}.{qy.get('metric')} {qy.get('commodity','')} {qy.get('period','')} "
                     f"asof {qy.get('asof','')} = {val}\n")
    convo = ""
    if convo_history is not None:
        convo = (f"=== CONVERSATION SO FAR (prior turns; the current question may be vague/pronoun-based and "
                 f"must be read against these) ===\n{convo_history or '(first turn)'}\n\n"
                 "Also score `continuity` (1-5): 5 = the answer correctly resolved what the user meant from the "
                 "conversation AND respected THIS turn's as-of (not a stale one); 1 = it answered the wrong "
                 "referent, ignored the thread, or dragged stale state in.\n\n")
    user = (convo +
            f"QUESTION: {query['question']}\n"
            f"(as-of date: {query.get('asof') or 'none'}; the tool routed intent={out.get('intent')} to "
            f"{out.get('contracts') or out.get('contract')})\n\n"
            f"=== CAUSAL GRAPH THE TOOL COULD CITE (drivers/signs/regimes here are authoritative) ===\n{ctx}\n\n"
            f"=== DATED EVIDENCE THE TOOL WAS SHOWN ===\n{ev_text or '(none retrieved)'}\n\n"
            f"=== OBSERVED NUMBERS THE TOOL LOOKED UP (as-known at asof) ===\n{num_text or '(none)'}\n\n"
            f"=== THE TOOL'S ANSWER ===\n{out.get('answer')}")
    sys_blocks = [{"type": "text", "text": _JUDGE_SYS, "cache_control": {"type": "ephemeral"}}]  # judge calls share it
    scores, _ = call(client, sys_blocks, user, model=model, max_tokens=3200,
                     tool=_judge_tool(continuity=convo_history is not None))  # headroom for adaptive thinking
    return scores


def _metrics(r: dict) -> dict:
    """Per-row metrics for the grounding-depth + source-diversity aggregation."""
    out, j = r["out"], (r.get("judge") or {})
    cited_srcs = [s.get("source") for s in (out.get("structured") or {}).get("sources") or [] if s.get("source")]
    cited_tiers = [an.source_tier(s) for s in cited_srcs]
    ev_srcs = {e.get("source") for e in (out.get("evidence") or []) if e.get("source")}   # actual corpus sources
    ev_tiers = {an.source_tier(s) for s in ev_srcs}
    ans_l = (out.get("answer") or "").lower()
    leaks = reg.register_leaks(out.get("answer") or "")               # internal tokens that leaked into reader prose
    rb = r["rubric"]
    tr = out.get("trace") or {}                                       # L2 planner traversal trace (when planner=l2)
    kept = tr.get("kept") or []
    dkept = [k for k in kept if k and k[0] == "driver"]
    active = tr.get("active") or []
    return {"commodity": r["q"]["contract"], "category": r["q"].get("category", r["q"].get("type", "")),
            "register_leaks": len(leaks), "register_tokens": [t for t, _ in leaks],
            "is_l2": tr.get("planner") == "l2", "n_kept": len(kept),
            "n_contracts": len({k[1] for k in kept}) if kept else 0,
            "n_regimes": len(tr.get("fired_regimes") or []),
            "leg_grounded": (len(active) / len(dkept)) if dkept else None,
            "routed_ok": rb["routed_right"], "retrieved": len(out.get("evidence") or []), "cited": len(cited_srcs),
            # v3 intent-branch + point-in-time
            "intent_ok": rb.get("intent_ok"), "routed_intent": rb.get("routed_intent"),
            "expected_intent": rb.get("expected_intent"), "leakage_ok": rb.get("leakage_ok"),
            "n_numbers": len(out.get("number_calls") or []),
            "n_number_errors": sum(1 for c in (out.get("number_calls") or []) if c.get("status") == "error"),
            # source-diversity / trust-ranking (the multi-source lift)
            "ev_sources": len(ev_srcs), "ev_tiers": len(ev_tiers), "cited_sources": len(set(cited_srcs)),
            "multi_tier": len(ev_tiers) >= 2,                                  # store offered >=2 trust tiers
            "trust_ordered": len(cited_tiers) > 1 and cited_tiers == sorted(cited_tiers),  # most-trusted first
            "disagreement": any(w in ans_l for w in ("disagree", "conflict", "at odds", "contradict", "diverg")),
            "src_div": j.get("source_diversity"),
            "usefulness": j.get("usefulness"), "convexity": j.get("convexity"),
            "point_in_time": j.get("point_in_time"), "grounding": j.get("grounding"),
            "halluc": len(j.get("hallucinations") or []), "gaps": j.get("gaps") or []}


def source_report(rows: list[dict]) -> list[str]:
    """The multi-source + trust-ranking lift panel — the WS-MS5 headline (was ~single-tier GAIN pre-fill)."""
    import statistics
    m = [_metrics(r) for r in rows]
    n = len(m) or 1

    def avg(key):
        xs = [x[key] for x in m if x.get(key) is not None]
        return round(statistics.mean(xs), 1) if xs else None

    return ["## Source diversity + trust-ranking (multi-source lift)", "",
            f"- retrieved distinct **sources** avg **{avg('ev_sources')}** | distinct **trust-tiers** avg **{avg('ev_tiers')}**",
            f"- **multi-tier answers** (store offered >=2 tiers): **{sum(x['multi_tier'] for x in m)}/{n}**",
            f"- cited distinct sources avg {avg('cited_sources')} | **trust-ordered citations** (T1 first): "
            f"{sum(x['trust_ordered'] for x in m)}/{n}",
            f"- **cross-tier disagreement flagged**: {sum(x['disagreement'] for x in m)}/{n}",
            f"- judge **source_diversity** avg: {avg('src_div')}/5"]


def routing_report(rows: list[dict]) -> list[str]:
    """v3 new-layers panel: intent-branch routing accuracy + point-in-time discipline + convexity."""
    import collections
    import statistics
    m = [_metrics(r) for r in rows]

    def avg(key):
        xs = [x[key] for x in m if x.get(key) is not None]
        return round(statistics.mean(xs), 1) if xs else None

    intent = [x for x in m if x.get("expected_intent")]
    iok = sum(1 for x in intent if x.get("intent_ok"))
    routed = collections.Counter(x.get("routed_intent") for x in m if x.get("routed_intent"))
    leak = [x for x in m if x.get("leakage_ok") is not None]
    L = ["## Intent routing + point-in-time (new layers)", "",
         f"- **intent routed correctly**: **{iok}/{len(intent) or 1}** (vs expected_intent)",
         f"- routed intents: {dict(routed)}",
         f"- questions that triggered a number lookup: {sum(1 for x in m if x.get('n_numbers'))}/{len(m)}"]
    nerr = sum(x.get("n_number_errors", 0) for x in m)
    if nerr:                                                          # loud flag: data-access failure, NOT point-in-time
        L.append(f"- **number lookups that ERRORED (data-access failure, not 'not known'): {nerr}** <- investigate")
    if leak:
        L.append(f"- **leakage-trap handled** (said 'not known at asof'): {sum(1 for x in leak if x['leakage_ok'])}/{len(leak)}")
    L.append(f"- judge **convexity** avg: {avg('convexity')}/5 | **point_in_time** avg: {avg('point_in_time')}/5")
    return L


def planner_report(rows: list[dict]) -> list[str]:
    """L2 grounded-subgraph panel — the cascade-completeness signal for the l2-vs-one-hop A/B. Empty for one-hop
    runs (no trace.planner)."""
    import statistics
    m = [x for x in (_metrics(r) for r in rows) if x.get("is_l2")]
    if not m:
        return []
    n = len(m)

    def avg(key):
        xs = [x[key] for x in m if x.get(key) is not None]
        return round(statistics.mean(xs), 1) if xs else None

    return ["## L2 planner (deterministic grounded-subgraph walk)", "",
            f"- **L2 answers: {n}/{len(rows)}**",
            f"- avg subgraph: **{avg('n_kept')}** grounded nodes across **{avg('n_contracts')}** contracts "
            f"(>1 contract = a cross-commodity cascade hop was grounded, not just described)",
            f"- avg **convergence regimes fired** (deterministic): {avg('n_regimes')}",
            f"- avg **leg-grounding rate** (kept drivers backed by dated evidence): {avg('leg_grounded')}"]


def register_report(rows: list[dict]) -> list[str]:
    """Output-register panel: how many answers leaked internal tokens (slugs, conf=, (+)/(-), 'the node fired')
    into reader-facing prose — the deterministic complement to the judge's register read."""
    import collections
    m = [_metrics(r) for r in rows]
    n = len(m) or 1
    leaky = [x for x in m if x.get("register_leaks")]
    tally = collections.Counter(t for x in m for t in (x.get("register_tokens") or []))
    L = ["## Output register (leaked internal tokens)", "",
         f"- **answers with leaks: {len(leaky)}/{n}** (clean = reader never sees a raw slug / `conf=` / `(+)` / graph jargon)"]
    if tally:
        top = ", ".join(f"`{t}`x{c}" for t, c in tally.most_common(8))
        L.append(f"- most-leaked tokens: {top}")
    else:
        L.append("- no internal tokens leaked into prose")
    return L


def verifier_panel(traces: list[dict]) -> list[str]:
    """The deterministic citation_violations panel (plan sec 6.6) — counts fabricated attributions
    without a judge. Its absence made the 37->151 hallucination-tally diagnosis slow; never again."""
    vs = [t for t in traces if t and t.get("enabled")]
    if not vs:
        return []
    by: dict = {}
    for v in vs:
        for k, c in (v.get("by_rule") or {}).items():
            by[k] = by.get(k, 0) + c
    rules = ", ".join(f"{k} x{c}" for k, c in sorted(by.items(), key=lambda x: -x[1])) or "(none)"
    return ["", "## Citation verifier (deterministic)", "",
            f"- handles checked: **{sum(v.get('checked', 0) for v in vs)}** | "
            f"stripped: **{sum(v.get('stripped', 0) for v in vs)}** | "
            f"ledger dates corrected: {sum(v.get('corrected', 0) for v in vs)}",
            f"- violations by rule: {rules}",
            f"- answers with >=1 strip: {sum(1 for v in vs if v.get('stripped'))}/{len(vs)}"]


def grounding_report(rows: list[dict]) -> list[str]:
    """Per-commodity grounding-depth table — the decision input for where evidence is thin for real questions."""
    import collections
    import statistics
    by: dict[str, list] = collections.defaultdict(list)
    for r in rows:
        by[r["q"]["contract"]].append(_metrics(r))

    def avg(xs):
        xs = [x for x in xs if x is not None]
        return round(statistics.mean(xs), 1) if xs else None

    L = ["## Per-commodity grounding depth", "",
         "| commodity | Qs | routed | usefulness | grounding | ev.retrieved | ev.cited | halluc |",
         "|---|--|--|--|--|--|--|--|"]
    flags = []
    for c in sorted(by):
        m = by[c]
        g = avg([x["grounding"] for x in m])
        if g is not None and g < 3:
            flags.append(c)
        L.append(f"| {c} | {len(m)} | {sum(x['routed_ok'] for x in m)}/{len(m)} | {avg([x['usefulness'] for x in m])} "
                 f"| {g} | {avg([x['retrieved'] for x in m])} | {avg([x['cited'] for x in m])} "
                 f"| {sum(x['halluc'] for x in m)} |")
    L += ["", f"**Under-grounded (avg grounding < 3) -> candidates for broad-rebuild / corpus gap:** {flags or 'none'}"]
    return L


def _num_line(out: dict) -> str:
    parts = []
    for c in out.get("number_calls") or []:
        qy, rws = c.get("query", {}), (c.get("rows") or [])
        val = rws[0].get("value") if rws else ("ERROR" if c.get("status") == "error" else "(not known)")
        parts.append(f"{qy.get('table','?')}.{qy.get('metric','?')}={val}")
    return ", ".join(parts)


def report(rows: list[dict], *, model: str) -> str:
    routed = sum(r["rubric"]["routed_right"] for r in rows)
    judged = [r["judge"] for r in rows if r.get("judge")]
    intent_rows = [r for r in rows if r["rubric"].get("expected_intent")]
    lines = [f"# graphdev eval v3 — {model}", "", f"- contract routed correctly: **{routed}/{len(rows)}**"]
    if intent_rows:
        iok = sum(1 for r in intent_rows if r["rubric"].get("intent_ok"))
        lines.append(f"- **intent routed correctly: {iok}/{len(intent_rows)}** (numbers_only / reasoning / hybrid)")
    if judged:
        j_avg = lambda key: sum(j.get(key, 0) for j in judged) / len(judged)  # noqa: E731
        halluc = sum(len(j.get("hallucinations") or []) for j in judged)
        lines.append(f"- judge **usefulness {j_avg('usefulness'):.1f}** · **convexity {j_avg('convexity'):.1f}** · "
                     f"**point_in_time {j_avg('point_in_time'):.1f}** · grounding {j_avg('grounding'):.1f} /5 · "
                     f"hallucinated claims: {halluc}")
    lines.append("")
    lines += routing_report(rows) + [""]                               # v3 new-layers panel
    if any((r["out"].get("trace") or {}).get("planner") == "l2" for r in rows):
        lines += planner_report(rows) + [""]                           # L2 grounded-subgraph cascade panel
    lines += register_report(rows) + [""]                              # output-register discipline (leaked internal tokens)
    lines += verifier_panel([(r["out"].get("trace") or {}).get("citation_verifier") for r in rows]) + [""]
    lines += source_report(rows) + [""]                                # multi-source lift (deterministic + judge)
    if judged:
        lines += grounding_report(rows) + [""]
    for r in rows:
        q, out, rb = r["q"], r["out"], r["rubric"]
        nums = _num_line(out)
        lines += [f"## {q['id']}  ({q.get('category', q.get('type', ''))})", f"**Q:** {q['question']}", "",
                  f"- intent: `{out.get('intent')}` (expected `{q.get('expected_intent')}`) | routed: "
                  f"`{out.get('contract')}` | evidence: {len(out.get('evidence') or [])} | "
                  f"numbers: {len(out.get('number_calls') or [])}"
                  + (f" [{rb.get('leakage_ok') and 'leakage OK' or 'LEAKAGE MISS'}]" if rb.get("leakage_ok") is not None else ""),
                  f"- evidence: {[(e['source'], e['date']) for e in out.get('evidence') or []][:6]}"]
        if nums:
            lines.append(f"- numbers looked up: {nums}")
        leaks = reg.register_leaks(out.get("answer") or "")
        if leaks:                                                      # surface the exact leaked tokens + context
            lines.append(f"- **register leaks ({len(leaks)}):** "
                         + "; ".join(f"`{t}` (…{c}…)" for t, c in leaks[:6]))
        if r.get("judge"):
            j = r["judge"]
            lines += [f"- **judge:** usefulness {j.get('usefulness')}/5 · convexity {j.get('convexity')}/5 · "
                      f"point_in_time {j.get('point_in_time')}/5 · grounding {j.get('grounding')}/5 — "
                      f"_{j.get('verdict')}_",
                      f"  - gaps: {j.get('gaps')}",
                      f"  - hallucinations: {j.get('hallucinations') or 'none'}",
                      f"  - improvements: {j.get('improvements') or '—'}"]
        lines += ["", "**A:**", "", (out.get("answer") or "(no answer)"), ""]
    return "\n".join(lines)


_PRICE = {"claude-sonnet-4-6": (3.0 / 1e6, 15.0 / 1e6), "claude-opus-4-8": (5.0 / 1e6, 25.0 / 1e6),
          "claude-haiku-4-5": (1.0 / 1e6, 5.0 / 1e6)}


def estimate_cost(queries: list[dict], *, model: str, judge_model: str | None = None,
                  via_orchestrator: bool = False) -> dict:
    # rough: answer ~3.5K input (graph + evidence) + ~0.9K out; judge ~5K input (+ numbers) + ~0.9K out
    ap = _PRICE.get(model, _PRICE["claude-sonnet-4-6"])
    usd = len(queries) * (3500 * ap[0] + 900 * ap[1])
    out = {"queries": len(queries), "model": model, "answer_usd": round(usd, 2), "est_usd": round(usd, 2)}
    if via_orchestrator:                                          # numbers agent (Haiku): ~2 tool-loop calls per numbers/hybrid Q
        hp = _PRICE["claude-haiku-4-5"]
        nq = sum(1 for q in queries if q.get("expected_intent") in ("numbers_only", "hybrid"))
        nusd = nq * 2 * (2500 * hp[0] + 400 * hp[1])
        usd += nusd
        out.update(numbers_haiku_usd=round(nusd, 2), est_usd=round(usd, 2))
    if judge_model:
        jp = _PRICE.get(judge_model, _PRICE["claude-opus-4-8"])
        jusd = len(queries) * (5000 * jp[0] + 900 * jp[1])
        out.update(judge_model=judge_model, judge_usd=round(jusd, 2), total_usd=round(usd + jusd, 2),
                   est_usd=round(usd + jusd, 2))
    return out


# ── multi-turn conversation eval (session memory, all intents, all agents) ────────────────────────────────
def load_convos(path) -> list[dict]:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("conversations") or []


class _UsageTap:
    """Thread-local capture of Anthropic usage (cache reads = the caching headline). Convos run one-per-
    thread with sequential turns, so a threading.local ring is exact per turn."""

    def __init__(self):
        import threading
        self.local = threading.local()
        self._orig = None

    def start(self):
        import anthropic
        self._orig = anthropic.resources.messages.Messages.create
        tap = self

        def create(inner_self, **kw):
            resp = tap._orig(inner_self, **kw)
            u = getattr(resp, "usage", None)
            rec = getattr(tap.local, "records", None)
            if u is not None and rec is not None:
                rec.append({"read": getattr(u, "cache_read_input_tokens", 0) or 0,
                            "write": getattr(u, "cache_creation_input_tokens", 0) or 0,
                            "input": getattr(u, "input_tokens", 0) or 0,
                            "output": getattr(u, "output_tokens", 0) or 0})
            return resp
        anthropic.resources.messages.Messages.create = create

    def begin_turn(self) -> list:
        self.local.records = []
        return self.local.records

    def stop(self):
        if self._orig is not None:
            import anthropic
            anthropic.resources.messages.Messages.create = self._orig


def _convo_mechanics(spec: dict, out: dict, prev_out: dict | None) -> dict:
    """Deterministic session-mechanics checks from the turn's expectations (the machine-checkable half;
    the continuity judge covers the semantic half)."""
    checks: dict = {}
    routed = [c for c in (out.get("contracts") or [out.get("contract")]) if c]
    if spec.get("expected_intent"):
        exp = spec["expected_intent"]                              # str OR list: hybrid/reasoning are not
        exp = exp if isinstance(exp, list) else [exp]              # mutually exclusive on quantitative turns
        checks["intent_ok"] = out.get("intent") in exp
    if spec.get("contracts_any_of"):
        checks["contract_ok"] = any(c in routed for c in spec["contracts_any_of"])
    if spec.get("carries_contracts") and prev_out is not None:
        prevc = {c for c in (prev_out.get("contracts") or [prev_out.get("contract")]) if c}
        checks["carry_contracts_ok"] = bool(set(routed) & prevc)
    if spec.get("carries_asof") and prev_out is not None:
        checks["carry_asof_ok"] = out.get("asof") == prev_out.get("asof")
    if spec.get("overrides_asof"):
        checks["override_asof_ok"] = out.get("asof") == str(spec.get("asof"))
    if spec.get("not_known"):
        checks["not_known_ok"] = any(p in (out.get("answer") or "").lower() for p in _NOT_KNOWN)
    if spec.get("uses_state"):
        checks["resolved_ok"] = bool(routed)
    return checks


def run_conversations(graph, convos: list[dict], *, model: str = an.SONNET, workers: int = 5,
                      numbers_client=None, call=None, respond_fn=None, store=None) -> list[dict]:
    """Turns are SEQUENTIAL within a conversation (state dependency); CONVERSATIONS parallelize — the speed
    structure that makes 25 turns ~ one conversation's wall-clock. Each convo gets its own session_id; the
    session store is the real serving one (Dynamo in-container via rev-7 env, in-memory locally)."""
    import time as _time
    import uuid

    from leviathan.graphrag import orchestrator as orch
    from leviathan.graphrag import session as ssn
    respond_fn = respond_fn or orch.respond
    store = store or ssn.default_store()
    tap = _UsageTap()
    tap.start()
    run_tag = uuid.uuid4().hex[:6]

    def _one_convo(cv: dict) -> list[dict]:
        rows, prev = [], None
        sid = f"eval-{cv['id']}-{run_tag}"
        for i, spec in enumerate(cv["turns"]):
            rec = tap.begin_turn()
            t0 = _time.monotonic()
            try:
                out = respond_fn(spec["q"], graph=graph, asof=spec.get("asof"), model=model,
                                 numbers_client=numbers_client, call=call,
                                 session_id=sid, session_store=store)
            except Exception as e:  # noqa: BLE001 — one bad turn must not abort a billed run
                out = {"answer": f"(turn failed: {str(e)[:200]})", "intent": None, "contract": None,
                       "contracts": [], "asof": spec.get("asof"), "evidence": [], "number_calls": [],
                       "structured": None, "trace": {"error": str(e)[:300]}}
                print(f"  WARN {cv['id']} turn {i}: {str(e)[:120]}", flush=True)
            dt = _time.monotonic() - t0
            usage = {k: sum(r[k] for r in rec) for k in ("read", "write", "input", "output")} if rec else \
                {"read": 0, "write": 0, "input": 0, "output": 0}
            print(f"  {cv['id']} turn {i} in {dt:.0f}s (cache_read {usage['read']})", flush=True)
            rows.append({"convo": cv["id"], "turn": i, "spec": spec, "out": out,
                         "mech": _convo_mechanics(spec, out, prev), "secs": round(dt, 1), "usage": usage})
            prev = out
        return rows

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(convos)))) as pool:
        all_rows = [r for rows in pool.map(_one_convo, convos) for r in rows]
    tap.stop()
    return all_rows


def _convo_history(rows: list[dict], row: dict) -> str:
    prior = [r for r in rows if r["convo"] == row["convo"] and r["turn"] < row["turn"]]
    return "\n".join(
        f"turn {r['turn']}: Q: {r['spec']['q']} (as-of {r['out'].get('asof')}) -> A(tl;dr): "
        + str((r['out'].get('structured') or {}).get('tldr') or r['out'].get('answer') or '')[:180]
        for r in sorted(prior, key=lambda x: x["turn"]))


def convo_report(rows: list[dict], *, model: str) -> str:
    import collections
    import statistics
    tally: dict = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        for k, ok in r["mech"].items():
            tally[k][1] += 1
            tally[k][0] += bool(ok)
    judged = [r["judge"] for r in rows if r.get("judge")]

    def javg(key):
        xs = [j.get(key) for j in judged if j.get(key) is not None]
        return round(statistics.mean(xs), 1) if xs else None
    later = [r for r in rows if r["turn"] > 0]
    cache_hit_turns = sum(1 for r in later if r["usage"]["read"] > 0)
    tot_read = sum(r["usage"]["read"] for r in rows)
    tot_in = sum(r["usage"]["input"] for r in rows)
    secs = [r["secs"] for r in rows]
    lines = [f"# conversation eval v1 — {model}", "",
             "## Session mechanics (deterministic)", ""]
    for k in sorted(tally):
        ok, n = tally[k]
        lines.append(f"- **{k}**: {ok}/{n}")
    lines += ["", "## Caching + speed", "",
              f"- turns 2+ with a prompt-cache HIT: **{cache_hit_turns}/{len(later)}**",
              f"- input tokens served from cache: **{tot_read:,}** vs {tot_in:,} uncached "
              f"({100 * tot_read / max(1, tot_read + tot_in):.0f}% of prompt volume)",
              f"- per-turn seconds: avg {statistics.mean(secs):.0f}, max {max(secs):.0f}"]
    if judged:
        lines += ["", "## Judge", "",
                  f"- usefulness {javg('usefulness')} | convexity {javg('convexity')} | "
                  f"point_in_time {javg('point_in_time')} | grounding {javg('grounding')} | "
                  f"**continuity {javg('continuity')}** /5",
                  f"- hallucinated claims: {sum(len(j.get('hallucinations') or []) for j in judged)}"]
    lines += verifier_panel([(r["out"].get("trace") or {}).get("citation_verifier") for r in rows])
    for cid in dict.fromkeys(r["convo"] for r in rows):
        lines += ["", f"## {cid}", ""]
        for r in [x for x in rows if x["convo"] == cid]:
            j = r.get("judge") or {}
            mech = " ".join(f"{k}={'Y' if v else 'N'}" for k, v in r["mech"].items())
            lines += [f"### turn {r['turn']}: {r['spec']['q']}",
                      f"- intent `{r['out'].get('intent')}` | routed {r['out'].get('contracts') or r['out'].get('contract')} "
                      f"| asof {r['out'].get('asof')} | {r['secs']}s | cache_read {r['usage']['read']}",
                      f"- mechanics: {mech or '(none)'}"]
            vfr = (r["out"].get("trace") or {}).get("citation_verifier") or {}
            if vfr.get("stripped"):
                lines.append(f"- verifier: stripped {vfr['stripped']} ({', '.join(sorted(vfr.get('by_rule') or {}))})")
            if j:
                lines.append(f"- judge: usefulness {j.get('usefulness')} continuity {j.get('continuity')} "
                             f"PIT {j.get('point_in_time')} — _{j.get('verdict')}_")
            lines += ["", str(r["out"].get("answer") or "(no answer)"), ""]
    return "\n".join(lines)


def _convos_main(args, path) -> int:
    """The --convos entry: run the multi-turn session eval end to end."""
    convos = load_convos(path)
    n_turns = sum(len(c["turns"]) for c in convos)
    if args.dry_run or not args.run:
        est = n_turns * 0.10 + (n_turns * 0.06 if args.judge else 0)   # sonnet answers (cache-discounted) + opus judges
        print(f"DRY-RUN: {len(convos)} conversations, {n_turns} turns; est ~${est:.2f} "
              f"(judge={'on' if args.judge else 'off'})")
        return 0
    from leviathan.common import config
    config.load_env()
    ev.CACHE_INDEX = True
    graph = gph.CausalGraph.load()
    import anthropic

    from leviathan.graphrag import batch_extract as bx
    client = anthropic.Anthropic(api_key=bx._api_key())
    rows = run_conversations(graph, convos, model=args.model, workers=args.workers,
                             numbers_client=client, call=an._call_opus)
    if args.judge:
        def _judge_row(r: dict) -> None:
            try:
                r["judge"] = judge({"question": r["spec"]["q"], "asof": r["out"].get("asof")}, r["out"],
                                   graph=graph, client=client, model=args.judge_model,
                                   convo_history=_convo_history(rows, r))
                print(f"  judged {r['convo']} turn {r['turn']}", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"  WARN judge {r['convo']} t{r['turn']} failed -- {str(e)[:120]}", flush=True)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            list(pool.map(_judge_row, rows))
    _OUT.mkdir(parents=True, exist_ok=True)
    from pathlib import Path
    out_path = _OUT / f"report_convos_{Path(str(path)).stem}.md"
    out_path.write_text(convo_report(rows, model=args.model), encoding="utf-8")
    s3uri = ev._evid_s3()
    if s3uri:
        import boto3
        b, k = ev._parse_s3(s3uri.rstrip("/") + f"/eval/report_convos_{Path(str(path)).stem}_{args.model}.md")
        boto3.client("s3").put_object(Bucket=b, Key=k, Body=out_path.read_bytes())
        print(f"  report -> s3://{b}/{k}")
    mech_ok = sum(sum(bool(v) for v in r["mech"].values()) for r in rows)
    mech_n = sum(len(r["mech"]) for r in rows)
    print(f"convo eval: {len(convos)} convos / {len(rows)} turns; mechanics {mech_ok}/{mech_n} -> {out_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="graphdev eval (routing + judge + source-diversity lift)")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--model", default=an.SONNET)
    ap.add_argument("--judge", action="store_true", help="add an independent LLM-judge quality score")
    ap.add_argument("--judge-model", default="claude-opus-4-8")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--queries", default=None, help="queries yaml path (default configs/graphrag/eval_queries.yaml)")
    ap.add_argument("--via-orchestrator", action="store_true",
                    help="route each query through the intent branch (orchestrator.respond) — numbers/reasoning/hybrid")
    ap.add_argument("--planner", default=None, choices=[None, "l2", "onehop"],
                    help="reasoning engine: default = serving default (L2 via orchestrator; answer() alone stays "
                         "one-hop); 'onehop' forces the single-contract baseline for A/Bs")
    ap.add_argument("--workers", type=int, default=4,
                    help="concurrent questions (answer + judge phases; LLM-network-bound so cost is identical; "
                         "1 = legacy sequential)")
    ap.add_argument("--convos", default=None,
                    help="conversation yaml -> multi-turn session eval (turns sequential per convo, convos "
                         "parallel; mechanics + continuity judge + cache/speed panels)")
    args = ap.parse_args()
    from pathlib import Path
    if args.convos:
        return _convos_main(args, Path(args.convos))
    queries = load_queries(Path(args.queries)) if args.queries else load_queries()
    if args.dry_run or not args.run:
        print(f"DRY-RUN cost estimate: {estimate_cost(queries, model=args.model, via_orchestrator=args.via_orchestrator, judge_model=args.judge_model if args.judge else None)}")
        import collections
        cats = collections.Counter(q.get("category", q.get("type", "?")) for q in queries)
        intents = collections.Counter(q.get("expected_intent") for q in queries if q.get("expected_intent"))
        print(f"  {len(queries)} questions across {len(set(q['contract'] for q in queries))} contracts; "
              f"categories: {dict(cats)}; expected_intent: {dict(intents)}")
        return 0
    from leviathan.common import config
    config.load_env()                                 # load ANTHROPIC_API for the serving (+ judge) model
    # No torch thread cap here: rankers.rerank_scores serializes the heavy cross-encoder behind a global
    # lock, so each rerank gets ALL cores instead of N workers thrashing at cores/N threads. The old
    # cpu//workers cap under the lock would have crippled every rerank to 2 threads.
    ev.CACHE_INDEX = True                             # the now-large slices load from S3 once, reused across queries
    graph = gph.CausalGraph.load()
    client = None
    if args.via_orchestrator or args.judge:           # one shared Anthropic client (numbers agent + judge)
        import anthropic
        from leviathan.graphrag import batch_extract as bx
        client = anthropic.Anthropic(api_key=bx._api_key())
    rows = run(graph, queries, model=args.model, k=args.k, via_orchestrator=args.via_orchestrator,
               numbers_client=client if args.via_orchestrator else None,
               call=an._call_opus if args.via_orchestrator else None, planner=args.planner, workers=args.workers)
    if args.judge:
        def _judge_row(r: dict) -> None:
            try:                                                      # a judge failure must not lose the whole run
                r["judge"] = judge(r["q"], r["out"], graph=graph, client=client, model=args.judge_model)
                print(f"  judged {r['q'].get('id')}", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"  WARN judge {r['q'].get('id')} failed -- {str(e)[:120]}", flush=True)
        if args.workers > 1:                                          # judges are independent too — same pool width
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                list(pool.map(_judge_row, rows))
        else:
            for r in rows:
                _judge_row(r)
    _OUT.mkdir(parents=True, exist_ok=True)
    out_path = _OUT / f"report_{args.model}.md"
    out_path.write_text(report(rows, model=args.model), encoding="utf-8")
    s3uri = ev._evid_s3()
    if s3uri:                                                     # persist so a Fargate run's report survives the container
        import boto3
        stem = Path(args.queries).stem if args.queries else "default"
        b, k = ev._parse_s3(s3uri.rstrip("/") + f"/eval/report_{args.model}_{stem}.md")
        boto3.client("s3").put_object(Bucket=b, Key=k, Body=out_path.read_bytes())
        print(f"  report -> s3://{b}/{k}")
    routed = sum(r["rubric"]["routed_right"] for r in rows)
    extra = ""
    if args.judge:
        use = sum((r.get("judge") or {}).get("usefulness", 0) for r in rows) / len(rows)
        gnd = sum((r.get("judge") or {}).get("grounding", 0) for r in rows) / len(rows)
        halluc = sum(len((r.get("judge") or {}).get("hallucinations") or []) for r in rows)
        extra = f", judge usefulness {use:.1f}/5 grounding {gnd:.1f}/5 ({halluc} halluc)"
    print(f"eval {args.model}: {len(rows)} queries, routed {routed}/{len(rows)}{extra} -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
