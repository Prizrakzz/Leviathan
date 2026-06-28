"""graphdev 10-query honest eval (GRAPHRAG_PLAN v2 Phase 2 WS-4).

Runs configs/graphrag/eval_queries.yaml through answer.answer() and writes a markdown report with a
lightweight auto-rubric (routed-right / expected-drivers-mentioned / regime-named / evidence-cited). The
rubric is approximate — the report + a human read are the real judges. Serving model defaults to Sonnet
(production), with an optional Opus arm to measure the quality gap.

    python -m leviathan.graphrag.eval --dry-run            # cost estimate, no spend
    python -m leviathan.graphrag.eval --run --model claude-sonnet-4-6
"""
from __future__ import annotations

import argparse

import yaml

from leviathan.graphrag import answer as an
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
        out = answer_fn(q["question"], graph=graph, model=model, k=k, asof=q.get("asof"), near=q.get("near"))
        rows.append({"q": q, "out": out, "rubric": score(q, out)})
    return rows


# ── LLM-judge: quality scores beyond substring matching ───────────────────────────────
def _judge_tool() -> dict:
    n = {"type": "integer"}
    return {"name": "score_answer", "description": "Score a commodity-analysis answer on a 1-5 rubric.",
            "input_schema": {"type": "object", "properties": {
                "groundedness": n, "driver_coverage": n, "evidence_use": n, "overall": n,
                "regime_correct": {"type": "boolean"}, "hallucination": {"type": "boolean"},
                "rationale": {"type": "string"}}}}


_JUDGE_SYS = ("You evaluate an answer grounded in a curated causal graph + dated evidence — BOTH are given to you "
              "below. A claim is GROUNDED if it traces to the graph (its drivers, signs, mechanisms, regimes, "
              "interactions ARE authoritative — naming them is NOT hallucination) OR to the evidence text "
              "(quoted figures/dates from the evidence are fine). Only flag hallucination for claims supported by "
              "NEITHER. Score 1-5: groundedness, driver_coverage (named the right drivers), evidence_use, overall. "
              "regime_correct: did it use the right regime, or true if a regime was reasonable/none needed. "
              "hallucination: true only for genuinely unsupported claims. rationale: one sentence. Emit via score_answer.")


def judge(query: dict, out: dict, *, graph=None, client=None, model: str = "claude-opus-4-8", call=None) -> dict:
    """An independent model scores answer quality — shown the SAME graph context + evidence TEXT the answerer had,
    so it can verify grounding (not just substring). Returns the score dict."""
    call = call or ex.call_opus
    exp = query.get("expect") or {}
    ctx = ""
    if graph is not None:
        from leviathan.graphrag import answer as an
        ctx = "\n\n".join(an._context_block(graph, c) for c in (out.get("contracts") or [out.get("contract")]) if c)
    ev_text = "\n".join(f"- ({e['source']}, {e['date']}) {e.get('text', '')}" for e in out.get("evidence") or [])
    user = (f"QUESTION: {query['question']}\nEXPECTED drivers: {exp.get('drivers')}\nEXPECTED regime: {exp.get('regime')}\n\n"
            f"=== CAUSAL GRAPH THE ANSWER MAY CITE (these drivers/signs/regimes are authoritative) ===\n{ctx}\n\n"
            f"=== DATED EVIDENCE THE ANSWER WAS SHOWN ===\n{ev_text or '(none)'}\n\n"
            f"=== ANSWER ===\n{out.get('answer')}")
    scores, _ = call(client, _JUDGE_SYS, user, model=model, max_tokens=600, tool=_judge_tool())
    return scores


def report(rows: list[dict], *, model: str) -> str:
    routed = sum(r["rubric"]["routed_right"] for r in rows)
    judged = [r["judge"] for r in rows if r.get("judge")]
    lines = [f"# graphdev eval — {model}", "", f"- routed correctly: **{routed}/{len(rows)}**"]
    if judged:
        avg = sum(j.get("overall", 0) for j in judged) / len(judged)
        halluc = sum(1 for j in judged if j.get("hallucination"))
        lines.append(f"- LLM-judge overall: **{avg:.1f}/5** | hallucinations flagged: {halluc}/{len(judged)}")
    lines.append("")
    for r in rows:
        q, out, rb = r["q"], r["out"], r["rubric"]
        lines += [f"## {q['id']}  ({q['type']})", f"**Q:** {q['question']}", "",
                  f"- routed: `{out.get('contract')}` (expected `{q['contract']}`) | "
                  f"drivers: {rb['drivers_hit']} (missed {rb['drivers_missed']}) | "
                  f"regime_named: {rb['regime_named']} | evidence_cited: {rb['evidence_cited']}",
                  f"- evidence: {[ (e['source'], e['date']) for e in out.get('evidence') or [] ]}"]
        if r.get("judge"):
            j = r["judge"]
            lines.append(f"- **judge:** overall {j.get('overall')}/5 | grounded {j.get('groundedness')} | "
                         f"drivers {j.get('driver_coverage')} | evidence {j.get('evidence_use')} | "
                         f"regime_ok {j.get('regime_correct')} | halluc {j.get('hallucination')} — {j.get('rationale')}")
        lines += ["", "**A:**", "", (out.get("answer") or "(no answer)"), ""]
    return "\n".join(lines)


def estimate_cost(queries: list[dict], *, model: str) -> dict:
    # rough: ~3.5K input (graph context + evidence) + ~0.9K output per query
    price = {"claude-sonnet-4-6": (3.0 / 1e6, 15.0 / 1e6), "claude-opus-4-8": (5.0 / 1e6, 25.0 / 1e6)}.get(model, (3.0 / 1e6, 15.0 / 1e6))
    in_tok, out_tok = 3500, 900
    usd = len(queries) * (in_tok * price[0] + out_tok * price[1])
    return {"queries": len(queries), "model": model, "est_usd": round(usd, 2)}


def main() -> int:
    ap = argparse.ArgumentParser(description="graphdev 10-query eval")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--model", default=an.SONNET)
    ap.add_argument("--judge", action="store_true", help="add an independent LLM-judge quality score")
    ap.add_argument("--judge-model", default="claude-opus-4-8")
    ap.add_argument("--k", type=int, default=5)
    args = ap.parse_args()
    queries = load_queries()
    if args.dry_run or not args.run:
        print(f"DRY-RUN cost estimate: {estimate_cost(queries, model=args.model)}"
              + (f" + judge ({args.judge_model})" if args.judge else ""))
        return 0
    from leviathan.common import config
    config.load_env()                                 # load ANTHROPIC_API for the serving (+ judge) model
    graph = gph.CausalGraph.load()
    rows = run(graph, queries, model=args.model, k=args.k)
    if args.judge:
        import anthropic
        from leviathan.graphrag import batch_extract as bx
        client = anthropic.Anthropic(api_key=bx._api_key())
        for r in rows:
            r["judge"] = judge(r["q"], r["out"], graph=graph, client=client, model=args.judge_model)
    _OUT.mkdir(parents=True, exist_ok=True)
    out_path = _OUT / f"report_{args.model}.md"
    out_path.write_text(report(rows, model=args.model), encoding="utf-8")
    routed = sum(r["rubric"]["routed_right"] for r in rows)
    extra = f", judge avg {sum(r['judge'].get('overall',0) for r in rows)/len(rows):.1f}/5" if args.judge else ""
    print(f"eval {args.model}: {len(rows)} queries, routed {routed}/{len(rows)}{extra} -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
