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
        out = answer_fn(q["question"], graph=graph, model=model, k=k, asof=q.get("asof"))
        rows.append({"q": q, "out": out, "rubric": score(q, out)})
    return rows


def report(rows: list[dict], *, model: str) -> str:
    n = len(rows) or 1
    routed = sum(r["rubric"]["routed_right"] for r in rows)
    lines = [f"# graphdev eval — {model}", "",
             f"- routed correctly: **{routed}/{len(rows)}**", ""]
    for r in rows:
        q, out, rb = r["q"], r["out"], r["rubric"]
        lines += [f"## {q['id']}  ({q['type']})", f"**Q:** {q['question']}", "",
                  f"- routed: `{out.get('contract')}` (expected `{q['contract']}`) | "
                  f"drivers: {rb['drivers_hit']} (missed {rb['drivers_missed']}) | "
                  f"regime_named: {rb['regime_named']} | evidence_cited: {rb['evidence_cited']}",
                  f"- evidence: {[ (e['source'], e['date']) for e in out.get('evidence') or [] ]}", "",
                  "**A:**", "", (out.get("answer") or "(no answer)"), ""]
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
    ap.add_argument("--k", type=int, default=5)
    args = ap.parse_args()
    queries = load_queries()
    if args.dry_run or not args.run:
        print(f"DRY-RUN cost estimate: {estimate_cost(queries, model=args.model)}")
        return 0
    from leviathan.common import config
    config.load_env()                                 # load ANTHROPIC_API for the serving model
    graph = gph.CausalGraph.load()
    rows = run(graph, queries, model=args.model, k=args.k)
    _OUT.mkdir(parents=True, exist_ok=True)
    out_path = _OUT / f"report_{args.model}.md"
    out_path.write_text(report(rows, model=args.model), encoding="utf-8")
    routed = sum(r["rubric"]["routed_right"] for r in rows)
    print(f"eval {args.model}: {len(rows)} queries, routed {routed}/{len(rows)} -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
