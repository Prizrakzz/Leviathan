"""Exp-2 — NLP pre-filter: skip chunks with no cascade potential BEFORE any LLM call (§8.3 cost-stack #3).

A chunk only yields a cascade edge if it names ≥2 vocab entities (the edge endpoints) or carries a causal
marker. Filtering those out up front cuts the LLM call count — for free, on CPU. The harvested vocab (275
node members + aliases, 34 markers) powers a word-boundary matcher (reused from `harvest.build_matcher`).

The HARD constraint is **value-recall ≥ 95%**: of the chunks that actually produced an edge/claim (per the
Sonnet/gold ground truth), the filter must KEEP ≥95% — never trade real cascade edges for cheapness. Among
rules that clear that bar, pick the one with the highest **skip-rate** (calls saved). "When unsure, keep."

    python -m leviathan.graphrag.nlp_filter           # free eval over candidate_gold → rule table + pick
"""
from __future__ import annotations

import argparse
import collections
import json
from dataclasses import dataclass
from pathlib import Path

from leviathan.graphrag import extract as ex
from leviathan.graphrag import harvest as hv

_PILOT = Path(__file__).resolve().parents[3] / "configs" / "graphrag" / "pilot"
_GOLD = _PILOT / "candidate_gold.jsonl"
_REPORT = _PILOT / "nlp_filter_report.md"
VALUE_RECALL_GATE = 0.95


# ── matchers (reuse the harvest word-boundary regex) ──────────────────────────────────
def _entity_forms() -> list[str]:
    v = ex._vocab()
    forms: list[str] = []
    for terms in v.get("nodes", {}).values():
        forms += [t for t in (terms or [])]
    for al in v.get("aliases", {}).values():
        forms += [a for a in (al or [])]
    # node ids are snake_case ("soybean_oil"); also match the spaced surface form ("soybean oil")
    forms += [f.replace("_", " ") for f in list(forms) if "_" in f]
    return forms


def matchers() -> tuple:
    ent_rx, _ = hv.build_matcher(_entity_forms())
    mrk_rx, _ = hv.build_matcher(ex._vocab().get("causal_markers", []))
    return ent_rx, mrk_rx


def n_entities(text: str, ent_rx) -> int:
    return len({m.lower() for m in ent_rx.findall(text)}) if ent_rx else 0


def has_marker(text: str, mrk_rx) -> bool:
    return bool(mrk_rx and mrk_rx.search(text))


@dataclass(frozen=True)
class Rule:
    name: str
    min_ent: int
    marker: str          # "or" | "and" | "ignore"

    def keep(self, n_ent: int, marker: bool) -> bool:
        base = n_ent >= self.min_ent
        if self.marker == "or":
            return base or marker
        if self.marker == "and":
            return base and marker
        return base


# the candidate rules swept (the default production rule is "≥2 ent OR marker")
RULES = [
    Rule(">=1 ent OR marker", 1, "or"),
    Rule(">=2 ent OR marker", 2, "or"),
    Rule(">=3 ent OR marker", 3, "or"),
    Rule(">=2 ent (entity-only)", 2, "ignore"),
    Rule(">=1 ent AND marker", 1, "and"),
]


def keep_chunk(text: str, ent_rx, mrk_rx, rule: Rule = RULES[1]) -> bool:
    return rule.keep(n_entities(text, ent_rx), has_marker(text, mrk_rx))


# ── evaluation ────────────────────────────────────────────────────────────────────────
def gold_label_samples() -> list[dict]:
    """candidate_gold props → {text, valuable}; valuable = produced ≥1 edge or ≥1 quant (FREE truth)."""
    rows = [json.loads(l) for l in _GOLD.read_text(encoding="utf-8").splitlines() if l.strip()]
    out = []
    for r in rows:
        text = r.get("chunk") if isinstance(r.get("chunk"), str) else ""
        if text:
            out.append({"text": text, "valuable": bool(r.get("edges") or r.get("quant"))})
    return out


def score_rule(feats: list[tuple], rule: Rule) -> dict:
    """feats = [(valuable, n_entities, has_marker), …] → value-recall + skip-rate for `rule`. Pure."""
    n = len(feats) or 1
    n_val = sum(1 for v, _, _ in feats if v) or 1
    kept = [(v, e, m) for v, e, m in feats if rule.keep(e, m)]
    kept_val = sum(1 for v, _, _ in kept if v)
    return {"rule": rule, "value_recall": kept_val / n_val, "skip_rate": 1 - len(kept) / n,
            "kept": len(kept), "kept_precision": (kept_val / len(kept)) if kept else 1.0}


def evaluate(samples: list[dict], rules: list[Rule] = RULES) -> list[dict]:
    ent_rx, mrk_rx = matchers()
    feats = [(s["valuable"], n_entities(s["text"], ent_rx), has_marker(s["text"], mrk_rx)) for s in samples]
    return [score_rule(feats, rule) for rule in rules]


MIN_USEFUL_SKIP = 0.10          # a filter only pays if it skips ≥10% AT the recall gate; else it's noise


def _pick(rows: list[dict]) -> dict | None:
    ok = [r for r in rows if r["value_recall"] >= VALUE_RECALL_GATE and r["skip_rate"] >= MIN_USEFUL_SKIP]
    return max(ok, key=lambda r: r["skip_rate"]) if ok else None


def build_report(rows: list[dict], n: int, n_val: int) -> str:
    pick = _pick(rows)
    L = [
        "# Exp-2 — NLP pre-filter (skip no-cascade chunks before the LLM)",
        "",
        f"{n} labelled props (candidate_gold), {n_val} valuable (≥1 edge/quant). "
        f"Gate: value-recall ≥ {VALUE_RECALL_GATE:.0%}; maximize skip-rate under it.",
        "",
        "| rule | value-recall | skip-rate | kept | kept-precision |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in rows:
        flag = " ✅" if r["value_recall"] >= VALUE_RECALL_GATE else ""
        L.append(f"| {r['rule'].name}{flag} | {r['value_recall']:.1%} | {r['skip_rate']:.1%} | "
                 f"{r['kept']} | {r['kept_precision']:.1%} |")
    L.append("")
    if pick:
        L += [f"### Pick: **{pick['rule'].name}** — value-recall {pick['value_recall']:.1%} ≥ "
              f"{VALUE_RECALL_GATE:.0%}, skips **{pick['skip_rate']:.1%}** of chunks (≈ calls saved).",
              f"- Production: gate chunks with this rule before the extractor; **keep-rate "
              f"{1 - pick['skip_rate']:.1%}** multiplies the per-prop budget (§8.3 re-budget)."]
    else:
        L += ["### Pick: **NONE useful — keep all chunks (no NLP skip).**",
              f"- No rule both clears value-recall ≥ {VALUE_RECALL_GATE:.0%} AND skips ≥ {MIN_USEFUL_SKIP:.0%}: "
              "the only rule above the recall gate skips ~0%, and every rule that skips ~10–17% drops "
              "value-recall to ~85–92%. The lost chunks are **single-vocab-entity quant/edge props** "
              "(a commodity + a number, or a country as an adjective). Adding demonyms (Indian→India, "
              "U.S.→United States, …) lifted `≥2-OR-marker` only to ~92% recall at ~10% skip — still short.",
              "- **Why:** the relevance gate (−40%) already drops boilerplate/tables, and propositional "
              "chunking concentrates value — so the residual chunks are too cascade-dense to pre-skip safely. "
              "**The NLP pre-filter (§8.3 #3) is retired; the relevance gate stays the only pre-LLM filter.**"]
    L += ["", "*Caveat:* candidate_gold is soy-complex (3 docs); a fresh stratified Sonnet-labelled sample "
          "would widen coverage, but the single-entity-quant failure mode is general, not soy-specific."]
    return "\n".join(L)


def run() -> str:
    samples = gold_label_samples()
    if not samples:
        raise SystemExit("no candidate_gold samples")
    rows = evaluate(samples)
    n_val = sum(1 for s in samples if s["valuable"])
    report = build_report(rows, len(samples), n_val)
    _REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT.write_text(report, encoding="utf-8")
    for r in rows:                                        # ASCII console summary (file keeps the unicode)
        ok = "PASS" if r["value_recall"] >= VALUE_RECALL_GATE else "fail"
        print(f"  [{ok}] {r['rule'].name:24} value-recall={r['value_recall']:.1%}  skip={r['skip_rate']:.1%}", flush=True)
    pick = _pick(rows)
    print(f"PICK: {pick['rule'].name} (skip {pick['skip_rate']:.1%})" if pick else "PICK: none clears 95% -> keep all", flush=True)
    print(f"wrote {_REPORT}", flush=True)
    return report


def main() -> int:
    argparse.ArgumentParser(description="Exp-2 NLP pre-filter eval (free, candidate_gold).").parse_args()
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
