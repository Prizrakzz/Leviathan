"""WS-C — Haiku-vs-Sonnet extraction bake-off: can the ~3.6×-cheaper model hold edge-recall?

Stage C bake-off'd only *Bedrock* Kimi/Qwen (rejected, 0–6% chain-recall); it never tested **Anthropic
Haiku 4.5** ($1/$5 vs Sonnet $3/$15 per Mtok → warm ~$0.0022 vs $0.0079/call). The bet: the Phase-1 harvest
(275 vocab members, 34 markers) lifted deterministic capture enough that Haiku can fill the FULL schema at
acceptable recall. Same gold + scoring as `schema_probe`; arms SONNET (reference) vs HAIKU, FULL schema,
cached. If Haiku holds, the 2020–26 slice drops from ~$1.41K toward ~$0.4K.

Decision: Haiku edge-recall ≥ 95% of Sonnet (precision steady) → ADOPT; 85–95% → cost/quality tradeoff
(user call); < 85% → keep Sonnet. ~$2 at the default --n 150. Haiku's min cacheable prefix is 4,096 tok and
ours is 4,187 — the run asserts `cache_creation>0` (a silent miss would erase the saving).

    python -m leviathan.graphrag.model_probe --dry-run
    python -m leviathan.graphrag.model_probe --n 150
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from statistics import mean

from leviathan.graphrag import batch_extract as bx
from leviathan.graphrag import extract as ex
from leviathan.graphrag import schema_probe as sp

_REPORT = sp._PILOT / "model_probe_report.md"
SLICE_PROPS = 178_000          # 2020–26 gated props (WS-A); FULL corpus ≈ 486K
MODELS = {"SONNET": ex.SONNET, "HAIKU": ex.HAIKU}


@dataclass
class Res:
    name: str
    model: str
    extractions: list = field(default_factory=list)        # duck-types schema_probe.ArmResult for sp.score
    usages: list = field(default_factory=list)

    def warm_per_call(self) -> float:
        warm = [u for u in self.usages if u.cache_read > 0]
        pool = warm or self.usages
        return mean(u.cost_for(self.model, "5m") for u in pool) if pool else 0.0

    def mean_out(self) -> float:
        return mean(u.output_tokens for u in self.usages) if self.usages else 0.0

    def cache_writes(self) -> int:
        return sum(1 for u in self.usages if u.cache_creation > 0)


def run_model(client, name: str, samples: list[dict]) -> Res:
    model = MODELS[name]
    system, tool = ex.build_system_prompt(), ex.extraction_tool()
    res = Res(name=name, model=model)
    for s in samples:
        ti, u = ex.call_extract(client, system, s["msg"], model=model, cache=True, tool=tool)
        try:
            res.extractions.append(ex.parse_extraction(ti))
        except Exception:  # noqa: BLE001
            res.extractions.append(ex.ChunkExtraction())
        res.usages.append(u)
    return res


def _pct(t: tuple) -> str:
    return f"{t[0]:.0%}/{t[1]:.0%}"


def build_report(results: dict[str, Res], scores: dict[str, dict], n: int) -> str:
    son, hai = results["SONNET"], results["HAIKU"]
    son_e, hai_e = scores["SONNET"]["edge_g"][0], scores["HAIKU"]["edge_g"][0]
    rel = hai_e / son_e if son_e else 1.0
    prec_ok = scores["HAIKU"]["edge_g"][1] >= scores["SONNET"]["edge_g"][1] - 0.03
    verdict = ("ADOPT HAIKU" if rel >= 0.95 and prec_ok
               else "TRADEOFF — user call" if rel >= 0.85 else "KEEP SONNET")
    cost_save = (1 - hai.warm_per_call() / son.warm_per_call()) if son.warm_per_call() else 0.0
    rows = []
    for name in ("SONNET", "HAIKU"):
        r, sc = results[name], scores[name]
        relc = "—" if name == "SONNET" else f"{(sc['edge_g'][0] / son_e if son_e else 1):.0%}"
        rows.append(f"| {name} | {r.mean_out():.0f} | {_pct(sc['edge_g'])} | {_pct(sc['ent_g'])} | "
                    f"{_pct(sc['quant_g'])} | {relc} | ${r.warm_per_call():.5f} | "
                    f"${r.warm_per_call() * SLICE_PROPS:,.0f} |")
    miss = hai.cache_writes() == 0
    L = [
        "# WS-C — Haiku vs Sonnet extraction (can the cheap model hold recall?)",
        "",
        f"Model arms over n={n} gold props (candidate_gold, soy-complex), FULL schema, cached. "
        "Recall/precision micro-averaged; `edge vs gold` absolute; `edge vs Sonnet` = relative fidelity.",
        "",
        "| model | out tok | edge R/P (gold) | ent R/P | quant R/P | edge vs Sonnet | warm $/call | 2020–26 proj |",
        "|---|---:|---|---|---|---:|---:|---:|",
        *rows,
        "",
        f"### Decision: **{verdict}**",
        f"- Haiku edge-recall = **{rel:.0%} of Sonnet** (precision {'steady' if prec_ok else 'DOWN >3pts'}); "
        f"Haiku is **{cost_save:.0%} cheaper** (${son.warm_per_call():.5f}→${hai.warm_per_call():.5f}/call).",
        f"- 2020–26 slice: Sonnet ${son.warm_per_call() * SLICE_PROPS:,.0f} vs Haiku "
        f"${hai.warm_per_call() * SLICE_PROPS:,.0f}.",
        f"- Haiku cache: **{'SILENT MISS — cache_creation=0 (prefix < 4,096?)' if miss else 'OK (cache wrote)'}**.",
    ]
    if verdict == "ADOPT HAIKU":
        L.append("- Switch the production extractor to `model=HAIKU` (Anthropic API, same cached path). "
                 "Re-budget §8.3 at the Haiku rate.")
    elif verdict.startswith("TRADEOFF"):
        L.append(f"- Recall {rel:.0%} of Sonnet for {cost_save:.0%} savings — a **quality/cost call for the "
                 "user**: adopt Haiku (cheaper, some recall loss) or keep Sonnet (full recall).")
    else:
        L.append("- Haiku loses too much recall — **keep Sonnet**. Cost stays at the Sonnet rate.")
    L += ["", "*Caveat:* candidate_gold is soy-complex (3 docs); a fresh broader gold would confirm a "
          "borderline call. Both arms share the same FULL prompt/schema, so the delta is the model."]
    return "\n".join(L)


def run(client, *, n: int) -> str:
    samples = sp.gold_samples(n)
    if not samples:
        raise SystemExit("no gold samples — candidate_gold.jsonl missing/empty")
    n = len(samples)
    print(f"{n} gold props × {{SONNET, HAIKU}} (FULL schema, cached)…", flush=True)
    results = {name: run_model(client, name, samples) for name in ("SONNET", "HAIKU")}
    scores = {name: sp.score(results[name], samples, results["SONNET"] if name != "SONNET" else None)
              for name in results}
    report = build_report(results, scores, n)
    _REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT.write_text(report, encoding="utf-8")
    spent = sum(u.cost_for(r.model, "5m") for r in results.values() for u in r.usages)
    print(f"\nwrote {_REPORT}\nbilled ~ ${spent:.4f} over {sum(len(r.usages) for r in results.values())} calls", flush=True)
    return report


def main() -> int:
    import anthropic
    ap = argparse.ArgumentParser(description="WS-C Haiku-vs-Sonnet extraction bake-off.")
    ap.add_argument("--n", type=int, default=150, help="gold props per model (caps spend; ~$2 at 150)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.dry_run:
        calls = args.n * 2
        print(f"DRY-RUN -- SONNET + HAIKU over {args.n} gold props = {calls} calls")
        print(f"  projected spend ~ ${args.n * (0.0079 + 0.0022):.2f} (Sonnet ~$0.008 + Haiku ~$0.002 per prop)")
        return 0
    from leviathan.common import config
    config.load_env()
    client = anthropic.Anthropic(api_key=bx._api_key())
    run(client, n=args.n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
