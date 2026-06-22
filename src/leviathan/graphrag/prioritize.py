"""GraphRAG Stage D — corpus prioritization. Size the Sonnet extraction slice to budget.

Read-only, CPU-only (no LLM spend). Scores every ``text/`` doc on **recency × liquidity ×
narrative-density**, shows the **per-year cost/value curve** so we can pick the year range, and emits the
**doc manifest** the deferred full extraction run consumes. priority = density·liquidity·recency;
est_cost = est_props × usd_per_prop (Sonnet Batch). Tunables live in ``configs/graphrag/params.yaml``.

    python -m leviathan.graphrag.prioritize --sample 40         # fast approximate preview
    python -m leviathan.graphrag.prioritize --budget 1500       # full scan → report + manifest
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import json
import random
import re

import boto3
import yaml

from leviathan.graphrag import batch_extract as bx
from leviathan.graphrag import extract as ex
from leviathan.graphrag.corpus_recon import BUCKET, TEXT_PREFIX, _source_of

_CFG = ex._CFG
_OUT = bx._OUT
_MANIFEST = _CFG / "priority_manifest.json"
_SENT = re.compile(r"[.!?]+")


def _params() -> dict:
    p = yaml.safe_load((_CFG / "params.yaml").read_text(encoding="utf-8")) or {}
    return p.get("prioritize", {})


# ── scoring ──────────────────────────────────────────────────────────────────────
def density(text: str, markers: list[str], w: dict) -> float:
    """0–1 narrative density: prose (alpha-ratio, sentence length, causal markers) up, tables (digits) down."""
    n = len(text)
    if n < 200:
        return 0.0
    alpha_ratio = sum(c.isalpha() for c in text) / n
    digit_ratio = sum(c.isdigit() for c in text) / n
    sents = [s for s in _SENT.split(text) if s.strip()]
    msl = (len(text.split()) / len(sents)) if sents else 0.0
    low = text.lower()
    marker_density = sum(low.count(m.lower()) for m in markers) / (n / 1000.0)
    a, s = alpha_ratio, min(msl / 25.0, 1.0)
    m, d = min(marker_density / 2.0, 1.0), max(0.0, 1.0 - digit_ratio * 4.0)
    score = (w.get("alpha", 0.4) * a + w.get("sentence", 0.2) * s
             + w.get("marker", 0.3) * m + w.get("digit", 0.1) * d)
    return round(min(max(score, 0.0), 1.0), 4)


def recency(year: str, curve: list) -> float:
    if year == "unknown":
        return float(curve[-1][1]) if curve else 0.25
    yi = int(year)
    for cut, wt in curve:
        if yi >= cut:
            return float(wt)
    return float(curve[-1][1]) if curve else 0.25


def liquidity(commodity: str, tiers: dict) -> float:
    return float(tiers.get(commodity, tiers.get("_default", 0.5)))


def _score_doc(key: str, text: str, p: dict, markers: list[str]) -> dict:
    commodity = bx._commodity_of(_source_of(key))
    year = bx._year_of(key)
    alpha_chars = sum(c.isalpha() for c in text)
    dens = density(text, markers, p.get("density_weights", {}))
    liq = liquidity(commodity, p.get("liquidity", {}))
    rec = recency(year, p.get("recency", []))
    est_props = max(1, round(alpha_chars / p.get("chars_per_prop", 130)))
    return {"key": key, "source": _source_of(key), "commodity": commodity, "year": year,
            "era": bx._era_of(key), "chars": len(text), "density": dens, "liquidity": liq,
            "recency": rec, "priority": round(dens * liq * rec, 5),
            "est_props": est_props, "est_cost": round(est_props * p.get("usd_per_prop", 0.0085), 4)}


# ── scan ─────────────────────────────────────────────────────────────────────────
def _all_keys(s3) -> list[str]:
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=TEXT_PREFIX):
        keys += [o["Key"] for o in page.get("Contents", []) if o["Key"].endswith("document.json")]
    return keys


def scan(s3, *, sample: int = 0, workers: int = 24) -> list[dict]:
    keys = _all_keys(s3)
    if sample:
        keys = random.Random(0).sample(keys, min(sample, len(keys)))
    p, markers = _params(), ex._vocab().get("causal_markers", [])

    def fetch(k):
        try:
            doc = json.loads(s3.get_object(Bucket=BUCKET, Key=k)["Body"].read())
        except Exception:  # noqa: BLE001
            return None
        txt = doc.get("full_text") or ""
        return _score_doc(k, txt, p, markers) if txt.strip() else None

    rows = []
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for r in pool.map(fetch, keys):
            if r:
                rows.append(r)
    return rows


# ── selection ────────────────────────────────────────────────────────────────────
def knapsack(rows: list[dict], budget: float) -> tuple[list[dict], float]:
    """Greedy value/$ pick (priority per dollar) until budget exhausted — value-optimal slice."""
    ordered = sorted(rows, key=lambda r: (r["priority"] / r["est_cost"]) if r["est_cost"] else 0.0, reverse=True)
    picked, cost = [], 0.0
    for r in ordered:
        if cost + r["est_cost"] <= budget:
            picked.append(r)
            cost += r["est_cost"]
    return picked, round(cost, 2)


def year_cutoff(rows: list[dict], budget: float, density_floor: float) -> tuple[int | None, list[dict], float]:
    """Largest contiguous newest-first year span (density ≥ floor) whose total est_cost fits budget."""
    elig = [r for r in rows if r["density"] >= density_floor and r["year"] != "unknown"]
    elig.sort(key=lambda r: int(r["year"]), reverse=True)
    chosen, cost, cut = [], 0.0, None
    for r in elig:
        if cost + r["est_cost"] > budget:
            break
        chosen.append(r)
        cost += r["est_cost"]
        cut = int(r["year"])
    return cut, chosen, round(cost, 2)


# ── report + manifest ──────────────────────────────────────────────────────────────
def _coverage(rows: list[dict]) -> str:
    c = collections.Counter(r["commodity"] for r in rows)
    return ", ".join(f"{k}({v})" for k, v in c.most_common())


def report(rows: list[dict], budget: float, density_floor: float, *, sampled: bool) -> None:
    _OUT.mkdir(parents=True, exist_ok=True)
    total_value = sum(r["priority"] for r in rows) or 1.0
    total_cost = sum(r["est_cost"] for r in rows)
    by_year = collections.defaultdict(lambda: {"n": 0, "cost": 0.0, "value": 0.0, "dens": []})
    for r in rows:
        a = by_year[r["year"]]
        a["n"] += 1
        a["cost"] += r["est_cost"]
        a["value"] += r["priority"]
        a["dens"].append(r["density"])
    years = sorted((y for y in by_year if y != "unknown"), key=int, reverse=True)

    L = ["# Stage D — corpus prioritization (which years/commodities to extract)",
         f"\n{'**SAMPLED preview** — counts/cost are not corpus totals.' if sampled else ''}"
         f"{len(rows)} docs | total est_cost **${total_cost:,.0f}** (Sonnet Batch) | "
         f"density_floor={density_floor} | budget=${budget:,.0f}\n",
         "## Per-year cost/value curve (newest→oldest — read down to your budget)",
         "| year | docs | avg density | est cost | cum cost | cum value% |",
         "|---|---:|---:|---:|---:|---:|"]
    cum_c = cum_v = 0.0
    for y in years:
        a = by_year[y]
        cum_c += a["cost"]
        cum_v += a["value"]
        avg_d = sum(a["dens"]) / len(a["dens"]) if a["dens"] else 0.0
        L.append(f"| {y} | {a['n']} | {avg_d:.2f} | ${a['cost']:,.0f} | ${cum_c:,.0f} | {cum_v / total_value:.0%} |")
    if "unknown" in by_year:
        a = by_year["unknown"]
        L.append(f"| unknown | {a['n']} | — | ${a['cost']:,.0f} | — | — |")

    by_com = collections.defaultdict(lambda: {"n": 0, "cost": 0.0, "value": 0.0, "dens": []})
    for r in rows:
        a = by_com[r["commodity"]]
        a["n"] += 1
        a["cost"] += r["est_cost"]
        a["value"] += r["priority"]
        a["dens"].append(r["density"])
    L += ["\n## Per-commodity", "| commodity | liquidity | docs | avg density | est cost | value% |",
          "|---|---:|---:|---:|---:|---:|"]
    liq = _params().get("liquidity", {})
    for com, a in sorted(by_com.items(), key=lambda kv: -kv[1]["value"]):
        avg_d = sum(a["dens"]) / len(a["dens"]) if a["dens"] else 0.0
        L.append(f"| {com} | {liquidity(com, liq):.1f} | {a['n']} | {avg_d:.2f} | ${a['cost']:,.0f} | "
                 f"{a['value'] / total_value:.0%} |")

    kp, kc = knapsack(rows, budget)
    cut, yc, ycost = year_cutoff(rows, budget, density_floor)
    L += [f"\n## Selection for ${budget:,.0f}",
          f"- **Knapsack (value/$ optimal):** {len(kp)} docs, ${kc:,.0f}, "
          f"**{sum(r['priority'] for r in kp) / total_value:.0%} of total value**; years "
          f"{min((int(r['year']) for r in kp if r['year'] != 'unknown'), default='?')}–"
          f"{max((int(r['year']) for r in kp if r['year'] != 'unknown'), default='?')}",
          f"- **Year-cutoff (contiguous, density ≥ {density_floor}):** ≥ **{cut}** → {len(yc)} docs, ${ycost:,.0f}, "
          f"{sum(r['priority'] for r in yc) / total_value:.0%} of value",
          f"- knapsack commodity coverage: {_coverage(kp)}"]
    (_OUT / "prioritization_report.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L), flush=True)
    print(f"\nwrote {_OUT / 'prioritization_report.md'}", flush=True)

    if not sampled:                                   # the actionable slice for the deferred full run
        picked = kp
        _MANIFEST.write_text(json.dumps({"budget": budget, "n_docs": len(picked), "est_cost": kc,
                                         "selection": "knapsack", "docs": picked}, indent=2), encoding="utf-8")
        print(f"wrote {_MANIFEST}  ({len(picked)} docs, ${kc:,.0f})", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="GraphRAG Stage-D corpus prioritization (read-only, no spend).")
    ap.add_argument("--budget", type=float, default=None)
    ap.add_argument("--density-floor", type=float, default=0.3)
    ap.add_argument("--sample", type=int, default=0, help="scan N random docs (fast preview; no manifest)")
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--region", default="us-east-1")
    args = ap.parse_args()
    budget = args.budget if args.budget is not None else _params().get("default_budget", 1500)
    s3 = boto3.client("s3", region_name=args.region)
    rows = scan(s3, sample=args.sample, workers=args.workers)
    print(f"scored {len(rows)} docs{' (sample)' if args.sample else ''}", flush=True)
    report(rows, float(budget), args.density_floor, sampled=bool(args.sample))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
