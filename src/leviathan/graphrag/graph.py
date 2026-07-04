"""In-memory causal graph over the curated contracts (GRAPHRAG_PLAN v2 Phase 2 — graphdev thin spine).

Loads configs/graphrag/causal/*.yaml into a queryable structure and exposes the deterministic primitives the
answer orchestrator reasons over — cascade fan-in/out (driver.parents), convergence regime firing, inter-
commodity hops, and silver-status resolution against the live registry. Pure + offline: no LLM, no spend.

The cascade direction: `driver.parents` are UPSTREAM causes, so `ancestors(d)` walks toward root causes
("what caused this driver") and `descendants(d)` walks toward effects ("what this driver drives")."""
from __future__ import annotations

from dataclasses import dataclass

from leviathan.causal import schema as cs
from leviathan.causal import validate as cval
from leviathan.graphrag import extract as ex

_CAUSAL_DIR = ex._CFG / "causal"


def load_contracts(paths=None) -> dict[str, cs.CausalContract]:
    """Load the curated YAMLs -> {contract_id: CausalContract} (defaults to all of configs/graphrag/causal/)."""
    paths = paths or sorted(_CAUSAL_DIR.glob("*.yaml"))
    out: dict[str, cs.CausalContract] = {}
    for p in paths:
        c = cs.load(p)
        out[c.contract] = c
    return out


def causal_graph_version(paths=None) -> str:
    """A stable 12-hex content hash of the curated causal YAMLs — the graph's identity for audit and
    reproducibility (which graph produced an answer / an eval). Deterministic from the YAML BYTES, so it's
    independent of the build/image; the same files always hash the same, and any edge/threshold edit
    changes it. Returns 'nograph' if nothing loads. This is the cheap tier of graph versioning; a per-edge
    effective_date + as-of graph loader is deferred (build-plan Phase 6) until a backtest demands it."""
    import hashlib
    paths = paths or sorted(_CAUSAL_DIR.glob("*.yaml"))
    h, any_read = hashlib.sha256(), False
    for p in sorted(paths, key=lambda x: str(x)):
        try:
            data = open(p, "rb").read()                      # read FIRST — a missing file contributes nothing
        except OSError:
            continue
        h.update(str(getattr(p, "name", p)).encode())
        h.update(b"\0")
        h.update(data)
        h.update(b"\0")
        any_read = True
    return h.hexdigest()[:12] if any_read else "nograph"


@dataclass
class _Index:
    contract: cs.CausalContract
    by_id: dict[str, cs.Driver]
    children: dict[str, list[str]]       # driver_id -> ids that list it as a parent (reverse of .parents)


def _index(c: cs.CausalContract) -> _Index:
    by_id = {d.id: d for d in c.drivers}
    children: dict[str, list[str]] = {d.id: [] for d in c.drivers}
    for d in c.drivers:
        for p in d.parents:
            if p in children:                # parent validity is guaranteed by the schema, but stay defensive
                children[p].append(d.id)
    return _Index(c, by_id, children)


@dataclass
class FiredRegime:
    name: str
    direction: str                          # '+' bullish / '-' bearish
    matched: list[str]                      # the active drivers that count toward this regime
    threshold: int                          # requires_any_n_of
    interactions: list[dict]                # the amplifier interactions whose `when` is fully active
    note: str


class CausalGraph:
    """Queryable view over one or more loaded contracts. `silver` (the live feature names) is injected for
    tests; in production it resolves from the feature_spine registry + node_silver_map via validate."""

    def __init__(self, contracts: dict[str, cs.CausalContract], *, silver: set[str] | None = None,
                 version: str | None = None):
        self.contracts = contracts
        self._idx = {k: _index(v) for k, v in contracts.items()}
        self._silver = cval.available_silver() if silver is None else set(silver)
        # graph identity for audit/reproducibility (trace.graph_version, /healthz, eval headers). A
        # production load computes it from the YAML bytes; synthetic test graphs pass 'test' or None.
        self.version = version

    @classmethod
    def load(cls, paths=None) -> "CausalGraph":
        return cls(load_contracts(paths), version=causal_graph_version(paths))

    def _ix(self, contract: str) -> _Index:
        if contract not in self._idx:
            raise KeyError(f"unknown contract {contract!r}")
        return self._idx[contract]

    # ── cascade ───────────────────────────────────────────────────────────────────────
    def driver(self, contract: str, driver_id: str) -> cs.Driver:
        return self._ix(contract).by_id[driver_id]

    def roots(self, contract: str) -> list[str]:
        """Drivers with no parents — the exogenous roots of the cascade (climate, macro, policy)."""
        return [d.id for d in self.contracts[contract].drivers if not d.parents]

    def ancestors(self, contract: str, driver_id: str) -> list[str]:
        """Transitive upstream causes of a driver (the .parents closure) — 'what caused this'."""
        ix = self._ix(contract)
        seen: set[str] = set()
        stack = list(ix.by_id[driver_id].parents)
        while stack:
            n = stack.pop()
            if n in seen or n not in ix.by_id:
                continue
            seen.add(n)
            stack.extend(ix.by_id[n].parents)
        return sorted(seen)

    def descendants(self, contract: str, driver_id: str) -> list[str]:
        """Transitive downstream effects (drivers this one is a parent of) — 'what this drives'."""
        ix = self._ix(contract)
        if driver_id not in ix.by_id:
            raise KeyError(f"{driver_id!r} not in {contract!r}")
        seen: set[str] = set()
        stack = list(ix.children.get(driver_id, []))
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack.extend(ix.children.get(n, []))
        return sorted(seen)

    # ── convergence ───────────────────────────────────────────────────────────────────
    def regimes(self, contract: str, active) -> list[FiredRegime]:
        """Which convergence signals fire given a set of active driver ids: a regime fires when at least
        `requires_any_n_of` of its drivers are active; an interaction fires when ALL of its `when` are active."""
        active = set(active)
        fired: list[FiredRegime] = []
        for s in self.contracts[contract].convergence:
            matched = [d for d in s.drivers if d in active]
            if len(matched) >= s.requires_any_n_of:
                ints = [{"when": list(it.when), "effect": it.effect, "note": it.note}
                        for it in s.interactions if set(it.when) <= active]
                fired.append(FiredRegime(s.name, s.direction, matched, s.requires_any_n_of, ints, s.note))
        return fired

    # ── inter-commodity ───────────────────────────────────────────────────────────────
    def cross_links(self, contract: str) -> list[dict]:
        """Inter-commodity edges, flagged `tracked` when the target is itself a loaded contract (a real hop)."""
        return [{"driver_commodity": e.driver_commodity, "relation": e.relation, "sign": e.sign,
                 "mechanism": e.mechanism, "lag": e.lag, "tracked": e.driver_commodity in self.contracts}
                for e in self.contracts[contract].inter_commodity]

    # ── silver resolution (the decoupling seam) ───────────────────────────────────────
    def silver_status(self, contract: str, driver_id: str) -> dict:
        """Resolve a driver's silver link: `declared` is the YAML status; `live` is whether the named feature
        actually exists in the registry today (so graphdev runs whether or not MLOps has built it yet)."""
        d = self.driver(contract, driver_id)
        return {"silver_ref": d.silver_ref, "declared": d.silver_status,
                "live": bool(d.silver_ref) and d.silver_ref in self._silver}

    def silver_summary(self, contract: str) -> dict:
        c = self.contracts[contract]
        live = [d.id for d in c.drivers if d.silver_ref and d.silver_ref in self._silver]
        planned = [d.id for d in c.drivers if d.silver_status == "planned"]
        return {"drivers": len(c.drivers), "live": len(live), "planned": len(planned),
                "live_ids": sorted(live), "planned_ids": sorted(planned)}

    # ── flat export (debug / QA / L2 mermaid substrate) ───────────────────────────────
    def to_edge_list(self) -> list[dict]:
        """Flatten every contract into a canonical edge list — the THREE edge kinds as uniform rows:
        driver->target (the causal prior), parent-driver->driver (fan-in), and contract->inter-commodity node
        (cascade hop). Pure/offline. `sign` on a parent edge is None (the schema stores no sign for the
        parent link — we don't invent one). Feeds debugging, QA, and the L2 graph_to_mermaid renderer."""
        _COLS = ("source", "source_kind", "edge_type", "target", "target_metric", "sign", "lag",
                 "mechanism", "confidence", "silver_ref", "silver_status")
        rows: list[dict] = []

        def _row(**kw):
            rows.append({c: kw.get(c) for c in _COLS})

        for cid, c in self.contracts.items():
            tgt0 = c.target_metrics[0] if c.target_metrics else "price"
            for d in c.drivers:
                _row(source=d.id, source_kind=d.type, edge_type=d.edge_type, target=cid,
                     target_metric=d.target_metric or tgt0, sign=d.sign, lag=d.lag, mechanism=d.mechanism,
                     confidence=d.confidence, silver_ref=d.silver_ref, silver_status=d.silver_status)
                for p in d.parents:                                    # parent-driver -> driver (fan-in)
                    _row(source=p, source_kind="driver", edge_type="drives", target=d.id)
            for e in c.inter_commodity:                                # contract -> inter-commodity node (cascade hop)
                _row(source=cid, source_kind="commodity", edge_type=e.relation, target=e.driver_commodity,
                     sign=e.sign, lag=e.lag, mechanism=e.mechanism)
        return rows


def main() -> int:
    import argparse
    import csv
    import json
    import sys

    ap = argparse.ArgumentParser(description="Causal graph utilities (pure/offline).")
    ap.add_argument("--edge-list", action="store_true", help="print the canonical flat edge list")
    ap.add_argument("--csv", action="store_true", help="with --edge-list: CSV instead of JSONL")
    args = ap.parse_args()
    g = CausalGraph.load()
    if args.edge_list:
        rows = g.to_edge_list()
        if args.csv and rows:
            w = csv.DictWriter(sys.stdout, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        else:
            for r in rows:
                print(json.dumps(r))                                   # ensure_ascii -> cp1252-safe stdout
        return 0
    print(f"{len(g.contracts)} contracts, {len(g.to_edge_list())} edges")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
