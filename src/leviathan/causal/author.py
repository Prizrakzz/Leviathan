"""Causal-ontology authoring pipeline (GRAPHRAG §10 Phase 1): seed → draft → gap-mine.

  seed(node)      — FREE. A draft skeleton: candidate drivers from the harvested vocab + inter-commodity
                    neighbours from the hierarchy + the available silver names (for wiring `silver_ref`).
  draft(node)     — GATED (Opus, cloud). One forced-tool call turns the seed + the model's domain knowledge
                    into a full, validated `CausalContract` (signs/mechanisms/lags/parents/convergence).
  gap_mine(node)  — FREE. Corpus co-occurrence: vocab drivers that appear near the commodity AND a causal
                    marker but are NOT yet in the contract → "did the curator miss this?" suggestions.

    python -m leviathan.causal.author --seed arabica_coffee
    python -m leviathan.causal.author --gap-mine arabica_coffee --sample 300
    python -m leviathan.causal.author --draft arabica_coffee            # gated (~$3-5 Opus)
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from datetime import date
from pathlib import Path

from leviathan.causal import schema as cs
from leviathan.causal import validate as cval
from leviathan.graphrag import extract as ex
from leviathan.graphrag import harvest as hv

_CAUSAL_DIR = ex._CFG / "causal"
_DRIVER_TYPES = ("climate_driver", "hazard", "beneficial_weather", "policy_event", "instrument", "state_marker")
_TOKEN = re.compile(r"[a-z0-9]+")


# ── seed (free) ───────────────────────────────────────────────────────────────────────
def _tokens(s: str) -> set[str]:
    return {t for t in _TOKEN.findall(ex._normalize(s)) if len(t) > 2}


def _match_silver(driver_id: str, silver: set[str]) -> str | None:
    """Best-effort: a silver feature whose name shares a meaningful token with the driver id."""
    dt = _tokens(driver_id)
    return next((s for s in sorted(silver) if _tokens(s) & dt), None)


def _complex_neighbours(node: str, h: dict) -> list[str]:
    out: list[str] = []
    for members in (h.get("complexes") or {}).values():
        if node in members:
            out += [m for m in members if m != node]
    return sorted(set(out))


def seed(node: str) -> dict:
    """A draft skeleton (not yet a valid CausalContract — `draft` fills sign/mechanism)."""
    v = ex._vocab()
    nodes = v.get("nodes", {})
    silver = cval.available_silver()
    aliases = list(v.get("aliases", {}).get(node, []))
    candidates = []
    for t in _DRIVER_TYPES:
        for did in nodes.get(t) or []:
            ref = _match_silver(did, silver)
            candidates.append({"id": did, "type": t, "silver_ref": ref,
                               "silver_status": "available" if ref else "none"})
    h = cval._CFG and __import__("yaml").safe_load((ex._CFG / "commodity_hierarchy.yaml").read_text(encoding="utf-8"))
    inter = [{"driver_commodity": m, "suggested_relation": "substitutes_for"} for m in _complex_neighbours(node, h or {})]
    return {"contract": node, "aliases": aliases, "target_metrics": ["price"],
            "driver_candidates": candidates, "inter_commodity_candidates": inter,
            "available_silver": sorted(silver), "edge_types": list((v.get("edges") or {}).keys())}


# ── draft (gated Opus) ─────────────────────────────────────────────────────────────────
def _causal_tool() -> dict:
    s = {"type": "string"}
    arr = lambda props: {"type": "array", "items": {"type": "object", "properties": props}}  # noqa: E731
    return {"name": "emit_causal_dag",
            "description": "Emit the curated causal DAG for the commodity contract.",
            "input_schema": {"type": "object", "properties": {
                "target_metrics": {"type": "array", "items": s},
                "drivers": arr({"id": s, "type": s, "sign": s, "mechanism": s, "lag": s, "region": s,
                                "edge_type": s, "target_metric": s, "silver_ref": s, "silver_status": s,
                                "parents": {"type": "array", "items": s}, "evidence_query": s, "confidence": s}),
                "inter_commodity": arr({"driver_commodity": s, "relation": s, "sign": s, "mechanism": s, "lag": s}),
                "convergence": arr({"name": s, "direction": s, "requires_any_n_of": {"type": "integer"},
                                    "drivers": {"type": "array", "items": s},
                                    "interactions": arr({"when": {"type": "array", "items": s}, "effect": s, "note": s}),
                                    "note": s})}}}


def _draft_system() -> str:
    return ("You are a senior commodities fundamental analyst building a CURATED causal graph for one futures "
            "contract. For the TARGET metric (default price), enumerate the drivers that move it, EXHAUSTIVELY "
            "(weather, disease/pest, climate teleconnections, S&D, policy/trade, macro/FX, freight, "
            "substitution). For EACH driver give: sign (+ raises the target, - lowers it, 0 ambiguous), a "
            "one-sentence mechanism, lag (e.g. '0-2 quarters'), region, an edge_type from the provided list, "
            "parents (drivers that drive THIS driver — e.g. La Nina is a parent of Brazil frost), a silver_ref "
            "from the provided available list (else leave null and set silver_status='planned'), an "
            "evidence_query, and confidence. Add cross-commodity edges (substitution/competition/crush). Then "
            "define CONVERGENCE signals: a named confluence (e.g. 'bullish_squeeze') = N aligned drivers, with "
            "optional interactions (X amplifies Y). Be exhaustive but precise; prune irrelevant candidates. "
            "Emit via emit_causal_dag.")


_DRIVER_KEYS = {"id", "type", "sign", "mechanism", "lag", "region", "edge_type", "target_metric",
                "silver_ref", "silver_status", "parents", "evidence_query", "confidence"}
_INTER_KEYS = {"driver_commodity", "relation", "sign", "mechanism", "lag"}
_CONV_KEYS = {"name", "direction", "requires_any_n_of", "drivers", "interactions", "note"}
_INTERACTION_KEYS = {"when", "effect", "note"}
_SIGN, _STATUS, _CONF = {"+", "-", "0"}, {"available", "planned", "none"}, {"high", "medium", "low"}


def _sanitize(out: dict) -> dict:
    """Make the LLM output schema-constructible: keep only known keys, coerce enums, and DROP dangling
    references (parents / convergence drivers / interaction `when` that don't name a declared driver) — the
    model sometimes names a parent it forgot to list. The curator fixes the rest; we never lose a paid draft."""
    drivers = []
    for d in out.get("drivers") or []:
        if isinstance(d, dict) and d.get("id") and d.get("type") and d.get("mechanism"):
            drivers.append({k: v for k, v in d.items() if k in _DRIVER_KEYS})
    ids = {d["id"] for d in drivers}
    for d in drivers:
        d["sign"] = d.get("sign") if d.get("sign") in _SIGN else "0"
        d["silver_status"] = (d.get("silver_status") if d.get("silver_status") in _STATUS
                              else ("available" if d.get("silver_ref") else "none"))
        d["confidence"] = d.get("confidence") if d.get("confidence") in _CONF else "medium"
        d["parents"] = [p for p in (d.get("parents") or []) if p in ids and p != d["id"]]
    inter = []
    for e in out.get("inter_commodity") or []:
        if isinstance(e, dict) and e.get("driver_commodity") and e.get("relation"):
            e = {k: v for k, v in e.items() if k in _INTER_KEYS}
            e["sign"] = e.get("sign") if e.get("sign") in _SIGN else "0"
            inter.append(e)
    conv = []
    for s in out.get("convergence") or []:
        if not isinstance(s, dict) or not s.get("name") or s.get("direction") not in {"+", "-"}:
            continue
        s = {k: v for k, v in s.items() if k in _CONV_KEYS}
        s["drivers"] = [x for x in (s.get("drivers") or []) if x in ids]
        ints = []
        for it in s.get("interactions") or []:
            if isinstance(it, dict):
                it = {k: v for k, v in it.items() if k in _INTERACTION_KEYS}
                it["when"] = [x for x in (it.get("when") or []) if x in ids]
                it["effect"] = it.get("effect") if it.get("effect") in {"amplifies", "dampens"} else "amplifies"
                if it["when"]:
                    ints.append(it)
        s["interactions"] = ints
        if s["drivers"]:
            s["requires_any_n_of"] = max(1, min(int(s.get("requires_any_n_of") or 1), len(s["drivers"])))
            conv.append(s)
    return {"target_metrics": out.get("target_metrics") or ["price"],
            "drivers": drivers, "inter_commodity": inter, "convergence": conv}


def draft(client, node: str, seed_dict: dict, *, model: str = ex.MODEL,
          reuse_raw: bool = False) -> cs.CausalContract:
    raw_path = _CAUSAL_DIR / f"{node}.raw.json"
    if reuse_raw and raw_path.exists():
        out = json.loads(raw_path.read_text(encoding="utf-8"))               # re-assemble without re-paying
    else:
        user = (f"CONTRACT: {node} (aliases: {seed_dict['aliases']}). TARGET metrics: {seed_dict['target_metrics']}.\n"
                f"EDGE TYPES allowed: {seed_dict['edge_types']}\n"
                f"CANDIDATE drivers from our vocab (prune/extend): {json.dumps(seed_dict['driver_candidates'])}\n"
                f"INTER-COMMODITY candidates: {json.dumps(seed_dict['inter_commodity_candidates'])}\n"
                f"AVAILABLE silver feature names (wire silver_ref to these; else status='planned'): "
                f"{seed_dict['available_silver']}")
        out, _usage = ex.call_opus(client, _draft_system(), user, model=model, max_tokens=8192, tool=_causal_tool())
        _CAUSAL_DIR.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")  # never lose a paid draft
    clean = _sanitize(out)
    return cs.CausalContract(contract=node, aliases=seed_dict["aliases"],
                             provenance={"authored_by": model, "date": str(date.today()),
                                         "sources": ["domain prior (Opus draft)", "harvested vocab seed"]},
                             **clean)


# ── gap-mine (free) ─────────────────────────────────────────────────────────────────────
def _driver_forms() -> list[str]:
    """Only DRIVER-concept surface forms (hazards/climate/policy/instruments/markers + their aliases) —
    NOT every vocab alias, so the matcher doesn't fire on country/commodity noise ("us", "usa")."""
    v = ex._vocab()
    aliases = v.get("aliases", {}) or {}
    forms: list[str] = []
    for t in _DRIVER_TYPES:
        members = list(v.get("nodes", {}).get(t) or [])
        forms += members
        for m in members:
            forms += list(aliases.get(m) or [])
    forms += [f.replace("_", " ") for f in list(forms) if "_" in f]
    return [f for f in set(forms) if len(f) > 3]      # drop short noise


def gap_mine(s3, node: str, *, sample: int = 300, existing: set[str] | None = None) -> collections.Counter:
    """Vocab driver terms that co-occur with the node + a causal marker in the corpus but aren't yet drivers."""
    from leviathan.graphrag.corpus_recon import BUCKET, TEXT_PREFIX, _source_of
    v = ex._vocab()
    node_forms = [node, node.replace("_", " ")] + list(v.get("aliases", {}).get(node, []))
    node_m = hv.build_matcher(node_forms)
    drv_m = hv.build_matcher(_driver_forms())
    mrk_m = hv.build_matcher(v.get("causal_markers", []))
    existing = {e.lower() for e in (existing or set())}
    all_keys = [o["Key"] for p in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=TEXT_PREFIX)
                for o in p.get("Contents", []) if o["Key"].endswith("document.json")]
    tok = node.split("_")[-1].lower()                 # e.g. "coffee" — bias the sample to relevant sources
    relevant = [k for k in all_keys if tok in _source_of(k).lower()]
    keys = relevant if len(relevant) >= 20 else all_keys
    import random
    hits: collections.Counter = collections.Counter()
    for k in random.Random(0).sample(keys, min(sample, len(keys))):
        try:
            txt = (json.loads(s3.get_object(Bucket=BUCKET, Key=k)["Body"].read()).get("full_text") or "")[:60000]
        except Exception:  # noqa: BLE001
            continue
        if not node_m.search(txt):
            continue
        for sent in re.split(r"(?<=[.!?])\s+", txt):
            if node_m.search(sent) and mrk_m.search(sent):
                for m in drv_m.findall(sent):
                    term = m.lower()
                    if term not in existing and term not in {n.lower() for n in node_forms}:
                        hits[term] += 1
    return hits


# ── CLI ─────────────────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="Causal-ontology authoring (seed / draft / gap-mine).")
    ap.add_argument("--seed", metavar="NODE")
    ap.add_argument("--draft", metavar="NODE")
    ap.add_argument("--gap-mine", dest="gap", metavar="NODE")
    ap.add_argument("--sample", type=int, default=300)
    args = ap.parse_args()

    if args.seed:
        sk = seed(args.seed)
        print(f"seed {args.seed}: {len(sk['driver_candidates'])} candidate drivers, "
              f"{len(sk['inter_commodity_candidates'])} inter-commodity, {len(sk['available_silver'])} silver names")
        print(json.dumps(sk, indent=2)[:4000])
        return 0
    if args.gap:
        import boto3
        from leviathan.common import config
        config.load_env()
        s3 = boto3.client("s3")
        hits = gap_mine(s3, args.gap, sample=args.sample)
        print(f"gap-mine {args.gap} (sample {args.sample}): top co-occurring drivers (marker-bearing sentences)")
        for term, n in hits.most_common(25):
            print(f"  {n:4d}  {term}")
        return 0
    if args.draft:
        import anthropic
        from leviathan.common import config
        from leviathan.graphrag import batch_extract as bx
        config.load_env()
        client = anthropic.Anthropic(api_key=bx._api_key())
        c = draft(client, args.draft, seed(args.draft))
        errs, warns = cval.check(c)
        _CAUSAL_DIR.mkdir(parents=True, exist_ok=True)
        out = _CAUSAL_DIR / f"{args.draft}.yaml"
        cs.dump(c, out)
        print(f"drafted {args.draft}: {len(c.drivers)} drivers, {len(c.convergence)} convergence signals -> {out}")
        print(f"causal_check: {'FAIL' if errs else 'PASS'}")
        for e in errs:
            print(f"  - {e}")
        for w in warns:
            print(f"  warn: {w}")
        return 0
    ap.error("one of --seed / --draft / --gap-mine is required")


if __name__ == "__main__":
    raise SystemExit(main())
