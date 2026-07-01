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

_QUERIES = ex._CFG / "eval_queries.yaml"
_OUT = ex._CFG / "eval"


def load_queries(path=_QUERIES) -> list[dict]:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("queries") or []


def score(q: dict, out: dict) -> dict:
    """Approximate auto-rubric: normalize answer text and check expected driver ids / regime name appear."""
    exp = q.get("expect") or {}
    ans = ex._normalize(out.get("answer") or "")
    drivers = exp.get("drivers") or []
    hit = [d for d in drivers if ex._normalize(d) in ans]
    return {"routed_right": out.get("contract") == q["contract"],
            "drivers_hit": f"{len(hit)}/{len(drivers)}", "drivers_missed": [d for d in drivers if d not in hit],
            "regime_named": (ex._normalize(exp["regime"]) in ans) if exp.get("regime") else None,
            "evidence_cited": (len(out.get("evidence") or []) > 0) if exp.get("needs_evidence") else None}


def run(graph: gph.CausalGraph, queries: list[dict], *, model: str = an.SONNET, k: int = 5, answer_fn=None) -> list[dict]:
    answer_fn = answer_fn or an.answer
    rows = []
    for q in queries:
        try:                                                          # one bad answer must NOT abort a billed run
            out = answer_fn(q["question"], graph=graph, model=model, k=k, asof=q.get("asof"), near=q.get("near"))
        except Exception as e:  # noqa: BLE001
            out = {"answer": f"(answer failed: {str(e)[:200]})", "contract": None, "structured": None,
                   "evidence": [], "model": model, "trace": {"error": str(e)[:300]}}
            print(f"  WARN {q.get('id')}: answer failed -- {str(e)[:120]}")
        rows.append({"q": q, "out": out, "rubric": score(q, out)})
    return rows


# ── LLM-judge: a quant/hedge-fund analyst rates usefulness + exposes gaps ──────────────
def _judge_tool() -> dict:
    n = {"type": "integer"}                                            # 1-5
    arr = {"type": "array", "items": {"type": "string"}}
    return {"name": "score_answer",
            "description": "A commodity hedge-fund analyst's verdict on how useful + grounded this answer is.",
            "input_schema": {"type": "object", "properties": {
                "usefulness": n, "grounding": n, "source_diversity": n,
                "hallucinations": arr, "gaps": arr, "improvements": arr, "verdict": {"type": "string"}},
                "required": ["usefulness", "grounding", "source_diversity", "gaps", "verdict"]}}


_JUDGE_SYS = (
    "You are a SENIOR QUANTITATIVE RESEARCHER at a commodities hedge fund, pressure-testing an analyst tool before "
    "the desk relies on it. You are shown the QUESTION, the curated causal graph + dated evidence the tool had "
    "access to, and the tool's ANSWER. Judge it the way a PM would before risking capital — be demanding and "
    "specific, not polite:\n"
    "- usefulness (1-5): is it ACTIONABLE? Does it give a real edge — direction, the drivers that matter, what to "
    "watch — or is it vague restatement of the question / textbook filler? 5 = I'd act on it; 1 = useless.\n"
    "- grounding (1-5): are the specific claims (drivers, signs, magnitudes, dates) backed by the cited dated "
    "evidence or by the authoritative graph? 5 = every claim traceable; 1 = floating assertions. (Naming the "
    "graph's own drivers/regimes/signs is AUTHORITATIVE, not hallucination.)\n"
    "- source_diversity (1-5): did it draw on and cite MULTIPLE sources across trust tiers (official WASDE/FAS T1, "
    "attache GAIN T2, producer bodies T3, macro/price outlook T4) rather than leaning on one? Did it ORDER citations "
    "most-trusted-first and FLAG any cross-tier disagreement? 5 = multi-source, trust-ranked, disagreements surfaced; "
    "1 = single-source or tier-blind (only score high if multiple sources were actually AVAILABLE in the evidence).\n"
    "- hallucinations: list any specific claim, number, sign, or date supported by NEITHER the graph NOR the "
    "evidence.\n"
    "- gaps: what a PM would still need that's missing — a key driver not mentioned, NO dated evidence cited, no "
    "direction/magnitude, no 'what to watch', wrong/!blended commodity, missed a regime or cross-commodity leg. "
    "Be concrete.\n"
    "- improvements: concrete changes that would make it more tradeable.\n"
    "- verdict: one blunt sentence.\n"
    "A fluent answer with no dated evidence or no actionable edge should score LOW on usefulness. Emit via score_answer.")


def judge(query: dict, out: dict, *, graph=None, client=None, model: str = "claude-opus-4-8", call=None) -> dict:
    """A quant-analyst persona scores the answer — shown the SAME graph context + evidence TEXT the answerer had,
    so it can tell grounded from invented. Returns {usefulness, grounding, hallucinations[], gaps[], improvements[],
    verdict}."""
    call = call or ex.call_opus
    ctx = ""
    if graph is not None:
        from leviathan.graphrag import answer as an
        ctx = "\n\n".join(an._context_block(graph, c) for c in (out.get("contracts") or [out.get("contract")]) if c)
    ev_text = "\n".join(f"- ({e['source']}, {e['date']}) {e.get('text', '')}" for e in out.get("evidence") or [])
    user = (f"QUESTION: {query['question']}\n"
            f"(the tool routed this to: {out.get('contracts') or out.get('contract')})\n\n"
            f"=== CAUSAL GRAPH THE TOOL COULD CITE (drivers/signs/regimes here are authoritative) ===\n{ctx}\n\n"
            f"=== DATED EVIDENCE THE TOOL WAS SHOWN ===\n{ev_text or '(none retrieved)'}\n\n"
            f"=== THE TOOL'S ANSWER ===\n{out.get('answer')}")
    scores, _ = call(client, _JUDGE_SYS, user, model=model, max_tokens=3200, tool=_judge_tool())  # headroom for adaptive thinking
    return scores


def _metrics(r: dict) -> dict:
    """Per-row metrics for the grounding-depth + source-diversity aggregation."""
    out, j = r["out"], (r.get("judge") or {})
    cited_srcs = [s.get("source") for s in (out.get("structured") or {}).get("sources") or [] if s.get("source")]
    cited_tiers = [an.source_tier(s) for s in cited_srcs]
    ev_srcs = {e.get("source") for e in (out.get("evidence") or []) if e.get("source")}   # actual corpus sources
    ev_tiers = {an.source_tier(s) for s in ev_srcs}
    ans_l = (out.get("answer") or "").lower()
    return {"commodity": r["q"]["contract"], "category": r["q"].get("category", r["q"].get("type", "")),
            "routed_ok": r["rubric"]["routed_right"], "retrieved": len(out.get("evidence") or []),
            "cited": len(cited_srcs),
            # source-diversity / trust-ranking (the multi-source lift)
            "ev_sources": len(ev_srcs), "ev_tiers": len(ev_tiers), "cited_sources": len(set(cited_srcs)),
            "multi_tier": len(ev_tiers) >= 2,                                  # store offered >=2 trust tiers
            "trust_ordered": len(cited_tiers) > 1 and cited_tiers == sorted(cited_tiers),  # most-trusted first
            "disagreement": any(w in ans_l for w in ("disagree", "conflict", "at odds", "contradict", "diverg")),
            "src_div": j.get("source_diversity"),
            "usefulness": j.get("usefulness"), "grounding": j.get("grounding"),
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


def report(rows: list[dict], *, model: str) -> str:
    routed = sum(r["rubric"]["routed_right"] for r in rows)
    judged = [r["judge"] for r in rows if r.get("judge")]
    lines = [f"# graphdev eval — {model}", "", f"- routed correctly: **{routed}/{len(rows)}**"]
    if judged:
        use = sum(j.get("usefulness", 0) for j in judged) / len(judged)
        gnd = sum(j.get("grounding", 0) for j in judged) / len(judged)
        halluc = sum(len(j.get("hallucinations") or []) for j in judged)
        lines.append(f"- judge **usefulness {use:.1f}/5** · **grounding {gnd:.1f}/5** · "
                     f"hallucinated claims: {halluc}")
    lines.append("")
    lines += source_report(rows) + [""]                                # multi-source lift (deterministic + judge)
    if judged:
        lines += grounding_report(rows) + [""]
    for r in rows:
        q, out, rb = r["q"], r["out"], r["rubric"]
        lines += [f"## {q['id']}  ({q.get('category', q.get('type', ''))})", f"**Q:** {q['question']}", "",
                  f"- routed: `{out.get('contract')}` (expected `{q['contract']}`) | "
                  f"drivers: {rb['drivers_hit']} | evidence retrieved: {len(out.get('evidence') or [])}",
                  f"- evidence: {[(e['source'], e['date']) for e in out.get('evidence') or []][:6]}"]
        if r.get("judge"):
            j = r["judge"]
            lines += [f"- **judge:** usefulness {j.get('usefulness')}/5 · grounding {j.get('grounding')}/5 — "
                      f"_{j.get('verdict')}_",
                      f"  - gaps: {j.get('gaps')}",
                      f"  - hallucinations: {j.get('hallucinations') or 'none'}",
                      f"  - improvements: {j.get('improvements') or '—'}"]
        lines += ["", "**A:**", "", (out.get("answer") or "(no answer)"), ""]
    return "\n".join(lines)


_PRICE = {"claude-sonnet-4-6": (3.0 / 1e6, 15.0 / 1e6), "claude-opus-4-8": (5.0 / 1e6, 25.0 / 1e6)}


def estimate_cost(queries: list[dict], *, model: str, judge_model: str | None = None) -> dict:
    # rough: answer ~3.5K input (graph + evidence) + ~0.9K out; judge ~4.5K input (graph + evidence + answer) + ~0.8K out
    ap = _PRICE.get(model, _PRICE["claude-sonnet-4-6"])
    usd = len(queries) * (3500 * ap[0] + 900 * ap[1])
    out = {"queries": len(queries), "model": model, "answer_usd": round(usd, 2), "est_usd": round(usd, 2)}
    if judge_model:
        jp = _PRICE.get(judge_model, _PRICE["claude-opus-4-8"])
        jusd = len(queries) * (4500 * jp[0] + 800 * jp[1])
        out.update(judge_model=judge_model, judge_usd=round(jusd, 2), total_usd=round(usd + jusd, 2),
                   est_usd=round(usd + jusd, 2))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="graphdev eval (routing + judge + source-diversity lift)")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--model", default=an.SONNET)
    ap.add_argument("--judge", action="store_true", help="add an independent LLM-judge quality score")
    ap.add_argument("--judge-model", default="claude-opus-4-8")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--queries", default=None, help="queries yaml path (default configs/graphrag/eval_queries.yaml)")
    args = ap.parse_args()
    from pathlib import Path
    queries = load_queries(Path(args.queries)) if args.queries else load_queries()
    if args.dry_run or not args.run:
        print(f"DRY-RUN cost estimate: {estimate_cost(queries, model=args.model, judge_model=args.judge_model if args.judge else None)}")
        import collections
        cats = collections.Counter(q.get("category", q.get("type", "?")) for q in queries)
        print(f"  {len(queries)} questions across {len(set(q['contract'] for q in queries))} contracts; categories: {dict(cats)}")
        return 0
    from leviathan.common import config
    config.load_env()                                 # load ANTHROPIC_API for the serving (+ judge) model
    ev.CACHE_INDEX = True                             # the now-large slices load from S3 once, reused across queries
    graph = gph.CausalGraph.load()
    rows = run(graph, queries, model=args.model, k=args.k)
    if args.judge:
        import anthropic
        from leviathan.graphrag import batch_extract as bx
        client = anthropic.Anthropic(api_key=bx._api_key())
        for r in rows:
            try:                                                      # a judge failure must not lose the whole run
                r["judge"] = judge(r["q"], r["out"], graph=graph, client=client, model=args.judge_model)
            except Exception as e:  # noqa: BLE001
                print(f"  WARN judge {r['q'].get('id')} failed -- {str(e)[:120]}")
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
