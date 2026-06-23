"""WS-B — compact-output schema experiment: cut OUTPUT tokens (Exp-1's 72%-of-cost term) without losing recall.

Exp-1 showed the warm extraction call is ~72% output tokens (uncached — caching can't touch them). The
existing ``lean=True`` only shrinks the (already-cached) input prefix. The real output cost is (a) per-item
field-name repetition and (b) the ``verbatim`` source spans echoed per edge/claim/entity. This harness
A/B/C-tests three output schemas on the SAME gated propositions, scoring **edge/entity/quant recall +
precision** against the hand-corrected ``candidate_gold`` (absolute truth) and against the FULL arm
(relative), plus **output tokens + warm $/call**:

  • FULL       — current production (full schema + verbatim) — the recall reference.
  • SLIM       — semantic keys, OMIT verbatim/canonical_name/mapped (provenance → chunk level).
  • SHORT      — SLIM + shortened keys (more saving, higher model-comprehension risk).

Decision: adopt the cheapest arm whose **edge-recall ≥ 98% of FULL** with precision steady; else keep FULL.
Sonnet 4.6, cached (prime-then-warm). ~$2-4 at the default --n 120 × 3 arms. candidate_gold is soy-complex
(3 docs) — a schema go/no-go, not a domain-coverage claim.

    python -m leviathan.graphrag.schema_probe --dry-run
    python -m leviathan.graphrag.schema_probe --n 120
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean

from leviathan.graphrag import batch_extract as bx
from leviathan.graphrag import extract as ex

MODEL = ex.SONNET
_PILOT = Path(__file__).resolve().parents[3] / "configs" / "graphrag" / "pilot"
_GOLD = _PILOT / "candidate_gold.jsonl"
_REPORT = _PILOT / "schema_experiment_report.md"
USD_PER_PROP_SLICE_PROPS = 165_000          # 2020–26 gated props (pre-WS-A recount) — for projection


# ── gold-aligned sampling ─────────────────────────────────────────────────────────────
def gold_samples(n: int) -> list[dict]:
    """N rows from candidate_gold: the prop text (as a user message with prev/next context) + its
    hand-corrected edges/entities/quant for absolute scoring."""
    rows = [json.loads(l) for l in _GOLD.read_text(encoding="utf-8").splitlines() if l.strip()]
    props = [(r.get("chunk") if isinstance(r.get("chunk"), str) else "") for r in rows]
    out = []
    for i, r in enumerate(rows[:n]):
        if not props[i]:
            continue
        msg = ex.build_user_message(props[i - 1] if i > 0 else "", props[i],
                                    props[i + 1] if i < len(rows) - 1 else "")
        out.append({"msg": msg, "edges": r.get("edges") or [], "entities": r.get("entities") or [],
                    "quant": r.get("quant") or []})
    return out


# ── scoring ─────────────────────────────────────────────────────────────────────────
def _n(s) -> str:
    return (str(s) if s is not None else "").strip().lower()


def _edges_x(x) -> set:
    return {(_n(r.src), _n(r.relation_type), _n(r.dst), _n(r.metric), _n(r.sign))
            for r in x.relationships if r.src and r.dst}


def _edges_gold(g: list) -> set:
    return {(_n(e.get("src")), _n(e.get("rel")), _n(e.get("dst")), _n(e.get("metric")), _n(e.get("sign")))
            for e in g if e.get("src") and e.get("dst")}


def _ents_x(x) -> set:
    return {(_n(e.id), _n(e.type)) for e in x.entities if e.id}


def _ents_gold(g: list) -> set:
    return {(_n(e.get("id")), _n(e.get("type"))) for e in g if e.get("id")}


def _quant_x(x) -> set:
    return {(_n(q.metric), _n(q.direction)) for q in x.quantitative_claims if q.metric}


def _quant_gold(g: list) -> set:
    return {(_n(q.get("metric")), _n(q.get("direction"))) for q in g if q.get("metric")}


# ── arms ────────────────────────────────────────────────────────────────────────────
_ARMS = {
    "FULL": dict(system=lambda: ex.build_system_prompt(), tool=lambda: ex.extraction_tool(),
                 parse=lambda ti: ex.parse_extraction(ti)),
    "SLIM": dict(system=lambda: ex.build_system_prompt(slim=True), tool=lambda: ex.compact_output_tool(short=False),
                 parse=lambda ti: ex.parse_compact(ti, short=False)),
    "SHORT": dict(system=lambda: ex.build_system_prompt(slim=True), tool=lambda: ex.compact_output_tool(short=True),
                  parse=lambda ti: ex.parse_compact(ti, short=True)),
}


@dataclass
class ArmResult:
    name: str
    extractions: list = field(default_factory=list)     # parsed ChunkExtraction per sample
    usages: list = field(default_factory=list)

    def warm_per_call(self) -> float:
        warm = [u for u in self.usages if u.cache_read > 0]
        return mean(u.cost_for(MODEL, "5m") for u in warm) if warm else (
            mean(u.cost_for(MODEL, "5m") for u in self.usages) if self.usages else 0.0)

    def mean_out(self) -> float:
        return mean(u.output_tokens for u in self.usages) if self.usages else 0.0


def run_arm(client, name: str, samples: list[dict]) -> ArmResult:
    spec = _ARMS[name]
    system, tool = spec["system"](), spec["tool"]()
    res = ArmResult(name=name)
    for s in samples:
        ti, u = ex.call_extract(client, system, s["msg"], model=MODEL, cache=True, tool=tool)
        try:
            res.extractions.append(spec["parse"](ti))
        except Exception:  # noqa: BLE001 — a malformed item scores as a miss, never sinks the arm
            res.extractions.append(ex.ChunkExtraction())
        res.usages.append(u)
    return res


# ── aggregate recall/precision ────────────────────────────────────────────────────────
def _micro(pairs: list[tuple[set, set]]) -> tuple[float, float]:
    """pairs = [(test, ref), …] → (recall, precision) micro-averaged across samples."""
    inter = sum(len(t & r) for t, r in pairs)
    nref = sum(len(r) for _, r in pairs)
    ntest = sum(len(t) for t, _ in pairs)
    recall = inter / nref if nref else 1.0
    precision = inter / ntest if ntest else 1.0
    return recall, precision


def score(arm: ArmResult, samples: list[dict], ref: ArmResult | None) -> dict:
    edges_gold = [(_edges_x(x), _edges_gold(s["edges"])) for x, s in zip(arm.extractions, samples)]
    ents_gold = [(_ents_x(x), _ents_gold(s["entities"])) for x, s in zip(arm.extractions, samples)]
    quant_gold = [(_quant_x(x), _quant_gold(s["quant"])) for x, s in zip(arm.extractions, samples)]
    out = {"edge_g": _micro(edges_gold), "ent_g": _micro(ents_gold), "quant_g": _micro(quant_gold)}
    if ref is not None:
        out["edge_f"] = _micro([(_edges_x(x), _edges_x(rx)) for x, rx in zip(arm.extractions, ref.extractions)])
    return out


# ── report ──────────────────────────────────────────────────────────────────────────
def _pct(t: tuple[float, float]) -> str:
    return f"{t[0]:.0%}/{t[1]:.0%}"


def build_report(arms: dict[str, ArmResult], scores: dict[str, dict], n: int) -> str:
    full = arms["FULL"]
    full_out, full_cost = full.mean_out(), full.warm_per_call()
    full_edge_g = scores["FULL"]["edge_g"][0]
    rows = []
    for name in ("FULL", "SLIM", "SHORT"):
        a, sc = arms[name], scores[name]
        out_save = (1 - a.mean_out() / full_out) if full_out else 0.0
        cost_save = (1 - a.warm_per_call() / full_cost) if full_cost else 0.0
        rel = sc.get("edge_f", (1.0, 1.0))[0]
        rel_full = rel / 1.0 if name == "FULL" else (sc["edge_g"][0] / full_edge_g if full_edge_g else 1.0)
        rows.append(f"| {name} | {a.mean_out():.0f} | {_pct(sc['edge_g'])} | {_pct(sc['ent_g'])} | "
                    f"{_pct(sc['quant_g'])} | {rel:.0%} | ${a.warm_per_call():.5f} | {out_save:+.0%} | {cost_save:+.0%} |")
    # decision: cheapest arm with edge-recall ≥ 98% of FULL (vs gold) and precision not worse by >3pts
    pick = "FULL"
    for name in ("SHORT", "SLIM"):
        sc = scores[name]
        rel = sc["edge_g"][0] / full_edge_g if full_edge_g else 1.0
        prec_ok = sc["edge_g"][1] >= scores["FULL"]["edge_g"][1] - 0.03
        if rel >= 0.98 and prec_ok:
            pick = name
            break
    L = [
        "# WS-B — compact-output schema (cut OUTPUT tokens without losing recall)",
        "",
        f"Model **{MODEL}**, n={n} gold props (candidate_gold, soy-complex), cached. Recall/precision are "
        "micro-averaged; `edge vs gold` is absolute, `edge vs FULL` is the schema's relative fidelity.",
        "",
        "| arm | out tok | edge R/P (gold) | ent R/P | quant R/P | edge vs FULL | warm $/call | out save | $ save |",
        "|---|---:|---|---|---|---:|---:|---:|---:|",
        *rows,
        "",
        f"### Decision: **{pick}**",
        f"- Rule: cheapest arm with edge-recall ≥ 98% of FULL (vs gold) and precision within 3 pts.",
    ]
    if pick != "FULL":
        a = arms[pick]
        save = (1 - a.warm_per_call() / full_cost) if full_cost else 0.0
        slice_full = full_cost * USD_PER_PROP_SLICE_PROPS
        slice_pick = a.warm_per_call() * USD_PER_PROP_SLICE_PROPS
        L += [f"- **{pick}** cuts output {1 - a.mean_out() / full_out:.0%}, warm $/call ${full_cost:.5f}→"
              f"${a.warm_per_call():.5f} (**{save:.0%}**). 2020–26 slice (~{USD_PER_PROP_SLICE_PROPS // 1000}K props): "
              f"${slice_full:,.0f}→**${slice_pick:,.0f}** (before WS-A prop recount).",
              f"- Production: switch the extractor to `compact_output_tool(short={pick == 'SHORT'})` + "
              f"`build_system_prompt(slim=True)` + `parse_compact`. Provenance drops to chunk-level."]
    else:
        L.append("- No compact arm held recall — **keep FULL** (verbatim/full schema). Output stays the floor.")
    return "\n".join(L)


# ── orchestration ─────────────────────────────────────────────────────────────────────
def run(client, *, n: int) -> str:
    samples = gold_samples(n)
    if not samples:
        raise SystemExit("no gold samples — candidate_gold.jsonl missing/empty")
    n = len(samples)
    print(f"{n} gold props × 3 arms (FULL/SLIM/SHORT), cached…", flush=True)
    arms = {name: run_arm(client, name, samples) for name in ("FULL", "SLIM", "SHORT")}
    scores = {name: score(arms[name], samples, arms["FULL"] if name != "FULL" else None)
              for name in arms}
    report = build_report(arms, scores, n)
    _REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT.write_text(report, encoding="utf-8")
    spent = sum(u.cost_for(MODEL, "5m") for a in arms.values() for u in a.usages)
    print(f"\nwrote {_REPORT}\nbilled ~ ${spent:.4f} over {sum(len(a.usages) for a in arms.values())} calls", flush=True)
    return report


def main() -> int:
    import anthropic
    ap = argparse.ArgumentParser(description="WS-B compact-output schema cost/recall experiment (Sonnet).")
    ap.add_argument("--n", type=int, default=120, help="gold props per arm (caps spend; ~$2-4 at 120×3)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.dry_run:
        calls = args.n * 3
        print(f"DRY-RUN -- FULL / SLIM / SHORT over {args.n} gold props = {calls} Sonnet calls")
        print(f"  projected spend ~ ${calls * 0.011:.2f} (warm; FULL ~$0.008, SLIM/SHORT cheaper)")
        return 0
    from leviathan.common import config
    config.load_env()
    client = anthropic.Anthropic(api_key=bx._api_key())
    run(client, n=args.n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
