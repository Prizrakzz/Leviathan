"""Causal-ontology validation + the `causal_check` CLI (GRAPHRAG_PLAN §10 Phase 1).

HARD-fails on structural breakage: a cycle in driver `parents` (a DAG must stay acyclic) or an
inter-commodity edge to something that is not a real node. SOFT-warns on silver links not yet in the
`gold.feature_spine` / `node_silver_map` (those are `planned`, never a blocker) and on missing fan-in /
convergence — and emits a **coverage report** that doubles as the feature roadmap for the MLOps track.

    python -m leviathan.causal.validate                      # all YAMLs in configs/graphrag/causal/
    python -m leviathan.causal.validate path/to/coffee.yaml
"""
from __future__ import annotations

import argparse
import collections
from pathlib import Path

import yaml

from leviathan.causal import schema as cs
from leviathan.graphrag import extract as ex

_CFG = ex._CFG                       # configs/graphrag
_CAUSAL_DIR = _CFG / "causal"
_OUT = _CFG / "pilot"


# ── reference surfaces (vocab nodes/edges + the available silver names) ───────────────
def _vocab_nodes_edges() -> tuple[set[str], set[str]]:
    v = ex._vocab()
    nodes = {t for terms in v.get("nodes", {}).values() if terms for t in terms}
    return nodes, set((v.get("edges") or {}).keys())


def available_silver() -> set[str]:
    """Names a driver's `silver_ref` may resolve to TODAY: feature_spine families + node_silver_map metrics."""
    names: set[str] = set()
    feats = _CFG.parent / "features" / "features.yaml"
    if feats.exists():
        for fam in yaml.safe_load(feats.read_text(encoding="utf-8")) or []:
            if isinstance(fam, dict) and fam.get("family"):
                names.add(fam["family"])
    nsm = _CFG / "node_silver_map.yaml"
    if nsm.exists():
        names |= set(((yaml.safe_load(nsm.read_text(encoding="utf-8")) or {}).get("metrics") or {}).keys())
    return names


def _cycle_node(drivers: list[cs.Driver]) -> str | None:
    """Return a driver id involved in a parent cycle, or None (DFS 3-colour)."""
    adj = {d.id: list(d.parents) for d in drivers}
    color: dict[str, int] = {k: 0 for k in adj}          # 0=white 1=grey 2=black

    def dfs(u: str) -> bool:
        color[u] = 1
        for w in adj.get(u, []):
            if color.get(w) == 1 or (color.get(w) == 0 and dfs(w)):
                return True
        color[u] = 2
        return False

    return next((n for n in adj if color[n] == 0 and dfs(n)), None)


# ── checks ────────────────────────────────────────────────────────────────────────────
def check(c: cs.CausalContract, *, nodes: set[str] | None = None, edges: set[str] | None = None,
          silver: set[str] | None = None) -> tuple[list[str], list[str]]:
    if nodes is None or edges is None:
        nodes, edges = _vocab_nodes_edges()
    if silver is None:
        silver = available_silver()
    errors: list[str] = []
    warns: list[str] = []

    cyc = _cycle_node(c.drivers)
    if cyc:
        errors.append(f"cycle in driver parents (involving {cyc!r}) — the DAG must be acyclic")
    for e in c.inter_commodity:
        if e.driver_commodity not in nodes:
            errors.append(f"inter_commodity edge to non-node {e.driver_commodity!r}")

    for d in c.drivers:
        if edges and d.edge_type not in edges:
            warns.append(f"driver {d.id!r}: edge_type {d.edge_type!r} not in the vocab taxonomy")
        if d.silver_ref and d.silver_status == "available" and d.silver_ref not in silver:
            warns.append(f"driver {d.id!r}: silver_ref {d.silver_ref!r} tagged 'available' but not in "
                         "feature_spine/node_silver_map → retag 'planned'")
        if not d.silver_ref and d.silver_status != "none":
            warns.append(f"driver {d.id!r}: silver_status {d.silver_status!r} but no silver_ref")
    if not c.fan_in_drivers():
        warns.append("no fan-in drivers (none have parents) — convergence depth is shallow")
    if not c.convergence:
        warns.append("no convergence signals defined")
    return errors, warns


def coverage(c: cs.CausalContract) -> dict:
    by_status = collections.Counter(d.silver_status for d in c.drivers)
    planned = list(dict.fromkeys(   # dedup, order-preserving: drivers may share one target feature (e.g. biennial)
        d.silver_ref or d.id for d in c.drivers if d.silver_status == "planned"))
    return {"drivers": len(c.drivers),
            "fan_out_roots": sum(1 for d in c.drivers if not d.parents),
            "fan_in": len(c.fan_in_drivers()),
            "inter_commodity": len(c.inter_commodity),
            "convergence": len(c.convergence),
            "silver": dict(by_status),
            "planned_features": planned}


def report(c: cs.CausalContract) -> str:
    cov = coverage(c)
    return "\n".join([
        f"# Causal coverage — {c.contract}", "",
        f"- drivers: **{cov['drivers']}** ({cov['fan_out_roots']} roots / {cov['fan_in']} with parents)",
        f"- inter-commodity edges: {cov['inter_commodity']} | convergence signals: {cov['convergence']}",
        f"- silver status: {cov['silver']}",
        f"- **planned features (MLOps roadmap):** {', '.join(cov['planned_features']) or '(none)'}",
    ])


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate causal-ontology YAMLs (causal_check).")
    ap.add_argument("paths", nargs="*", help="YAML files; default = all of configs/graphrag/causal/*.yaml")
    args = ap.parse_args()
    paths = [Path(p) for p in args.paths] or sorted(_CAUSAL_DIR.glob("*.yaml"))
    if not paths:
        print("no causal YAMLs found"); return 0
    nodes, edges = _vocab_nodes_edges()
    silver = available_silver()
    failures = 0
    for p in paths:
        try:
            c = cs.load(p)
        except Exception as e:  # noqa: BLE001 — schema failure is a hard fail with a readable message
            print(f"FAIL {p.name}: schema -- {str(e)[:200]}"); failures += 1; continue
        errs, warns = check(c, nodes=nodes, edges=edges, silver=silver)
        print(f"{'FAIL' if errs else 'PASS'} {p.name}")
        for e in errs:
            print(f"  - {e}")
        for w in warns:
            print(f"  warn: {w}")
        failures += len(errs)
        _OUT.mkdir(parents=True, exist_ok=True)
        (_OUT / f"causal_coverage_{c.contract}.md").write_text(report(c), encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
