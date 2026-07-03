"""L2 structured multi-hop — a deterministic grounded-subgraph walk over the curated causal DAG (GraphRAG v2).

Replaces answer()'s one-hop "route -> dump text -> one LLM call" with a query-conditioned frontier walk: seed on
the routed contract(s), expand across driver fan-in (`Driver.parents`) and TRACKED inter-commodity edges to
`depth`, and keep a node only if cos(query, its mechanism) >= `tau` (seeds always kept) within `node_budget`.

The WALK is deterministic (WHICH nodes/hops the answer covers) — it follows the curated edges instead of letting
the LLM improvise the causal path, so the answer's causal skeleton is guaranteed to match the vetted graph.
Retrieval (WHAT evidence) and the reasoner (HOW it reads) stay generative — see `ground()` (evidence + silver +
convergence) and answer(planner="l2"). This module is the pure core: only `embed` is external, and it's injectable,
so the traversal / prune / budget logic is unit-testable with no S3, no Athena, no LLM.

WS-1 here = the walk + prior leg + mermaid + trace. The I/O legs (evidence, silver, convergence firing) land in
`ground()` (WS-2/4/5)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from leviathan.graphrag import evidence as ev
from leviathan.graphrag import graph as gph
from leviathan.graphrag import params as _pr

# Serving knobs read from params.yaml (section 9.1: no knob hardcoded); the literals here are the
# authoritative fallbacks for a public clone without the private config.
_TAU = float(_pr.get("serving.walk.tau", 0.35))
_NODE_BUDGET = int(_pr.get("serving.walk.node_budget", 10))
_DEPTH = int(_pr.get("serving.walk.depth", 2))
_MAX_SEEDS = int(_pr.get("serving.walk.max_seeds", 2))
_RECENCY_DAYS = int(_pr.get("serving.ground.recency_days", 548))
_PROBE_CAP = int(_pr.get("serving.ground.probe_cap", 24))
_EVIDENCE_CAP = int(_pr.get("serving.ground.evidence_cap", 24))
_K_BY_DEPTH = tuple(_pr.get("serving.ground.k_by_depth", (5, 3, 2)))


# ── edge-category map (code-level; NO YAML re-curation) ──────────────────────────────────────────────────────
# Classifies the EXISTING relation/edge_type vocabulary so grounding expectations differ by kind:
#   transformation  = accounting identities (a crush margin exists by construction) -> true WITHOUT dated
#                     evidence; never counts against leg-grounding.
#   market_structure= substitution/competition links -> probabilistic but market-level.
#   causal          = physical/economic cause-effect (weather->yield) -> the kind that NEEDS dated evidence.
_EDGE_CATEGORY = {
    "crushed_into": "transformation", "feedstock_for": "transformation", "processed_into": "transformation",
    "produces": "transformation", "byproduct_of": "transformation", "co_product_of": "transformation",
    "substitutes_for": "market_structure", "competes_with": "market_structure",
    "leads_lags": "market_structure", "hedged_with": "market_structure",
}


def edge_category(relation: str) -> str:
    return _EDGE_CATEGORY.get(relation or "", "causal")


@dataclass
class GroundedNode:
    kind: str                                   # "contract" | "driver"
    id: str                                     # contract id (contract node) or driver id (driver node)
    contract: str                               # owning contract (== id for a contract node)
    depth: int
    relevance: float                            # cos(query, mechanism); 1.0 for a seed
    prior: dict = field(default_factory=dict)   # sign/lag/mechanism/confidence (driver) or target/edge (contract)
    evidence: list = field(default_factory=list)     # dated props (filled by ground())
    silver: Optional[dict] = None               # {ref,value,unit,knowledge_date,live} or {ref,live:False}
    active: bool = False                        # driver "active" = evidence leg non-empty near the episode
    via_edge: Optional[dict] = None             # the inter-commodity edge that reached this contract node

    @property
    def key(self) -> tuple:
        return (self.kind, self.contract, self.id)


@dataclass
class Subgraph:
    seeds: list[str]
    nodes: list[GroundedNode]
    fired_regimes: list[dict] = field(default_factory=list)
    mermaid: str = ""
    trace: dict = field(default_factory=dict)

    def by_contract(self, cid: str) -> list[GroundedNode]:
        return [n for n in self.nodes if n.contract == cid]


def _relevance(qv, text: str, embed, cache: dict) -> float:
    if not text:
        return 0.0
    if text not in cache:
        cache[text] = embed([text])[0]
    return ev._cosine(qv, cache[text])


def _seed_contracts(query, graph, route_fn, max_seeds: int) -> list[str]:
    """Route, then keep distinct commodity NODES (siblings share an evidence slice) — mirrors answer()."""
    seeds, seen = [], set()
    for c in route_fn(query, graph):
        if c not in graph.contracts:
            continue
        nd = ev.node_for(c)
        if nd in seen:
            continue
        seen.add(nd)
        seeds.append(c)
        if len(seeds) >= max_seeds:
            break
    return seeds


def grounded_subgraph(query: str, graph: gph.CausalGraph, *, depth: int = _DEPTH, node_budget: int = _NODE_BUDGET,
                      tau: float = _TAU, max_seeds: int = _MAX_SEEDS, embed=None, route_fn=None) -> Subgraph:
    """Query-conditioned frontier walk. Returns the kept subgraph with the PRIOR leg + mermaid + trace filled;
    evidence/silver/convergence are added by ground(). Deterministic given `embed` (inject a fake in tests)."""
    embed = embed or ev.embed
    if route_fn is None:
        from leviathan.graphrag import answer as _an       # lazy: answer imports planner for the l2 path
        route_fn = _an.route_smart
    qv = embed([query])[0]
    mech: dict = {}

    seeds = _seed_contracts(query, graph, route_fn, max_seeds)
    visited: set = set()
    kept: dict[tuple, GroundedNode] = {}
    pruned: list[dict] = []

    # Wave-by-wave BFS: at each depth, SCORE every candidate and admit the most relevant under the budget,
    # instead of FIFO in YAML-curation order (v1.1's walk kept whichever drivers came first, so 70% of
    # regime-required drivers were never visited and the reasoner saw an arbitrary slice). tau stays a floor;
    # tracked cross-commodity hops rank ahead of drivers at the same depth so the cascade can't be starved.
    wave = [(c, 0, None, "contract", c) for c in seeds]     # (id, depth, via_edge, kind, contract)
    while wave and len(kept) < node_budget:
        scored = []
        for id_, d, via, kind, cid in wave:
            key = (kind, cid, id_)
            if key in visited:
                continue
            visited.add(key)
            if d == 0:                                      # seeds always kept
                rel = 1.0
            elif kind == "contract":                        # a cross-commodity hop: score its edge mechanism
                rel = _relevance(qv, (via or {}).get("mechanism", ""), embed, mech)
            else:                                           # a driver: score its mechanism
                rel = _relevance(qv, graph.driver(cid, id_).mechanism, embed, mech)
            if d > 0 and rel < tau:
                pruned.append({"key": list(key), "relevance": round(rel, 3), "depth": d, "reason": "tau"})
                continue
            is_hop = 1 if (kind == "contract" and d > 0) else 0    # tracked hop priority (L2's headline)
            scored.append((is_hop, round(rel, 3), id_, kind, cid, d, via, key))

        scored.sort(key=lambda x: (-x[0], -x[1], x[2]))     # hop-first, then relevance desc, id asc (deterministic)
        nxt = []
        for is_hop, rel, id_, kind, cid, d, via, key in scored:
            if d > 0 and len(kept) >= node_budget:          # budget spent on higher-ranked candidates
                pruned.append({"key": list(key), "relevance": rel, "depth": d, "reason": "budget"})
                continue
            node = GroundedNode(kind=kind, id=id_, contract=cid, depth=d, relevance=rel, via_edge=via)
            node.prior = _prior(graph, node)
            kept[key] = node
            if d >= depth:
                continue
            if kind == "contract":
                for e in graph.cross_links(cid):            # tracked inter-commodity hops -> next wave
                    if e["tracked"]:
                        nxt.append((e["driver_commodity"], d + 1,
                                    {**e, "_from": cid, "category": edge_category(e["relation"])},
                                    "contract", e["driver_commodity"]))
                for drv in graph.contracts[cid].drivers:    # driver fan-in of this contract -> next wave
                    nxt.append((drv.id, d + 1, None, "driver", cid))
            else:
                for p in graph.driver(cid, id_).parents:    # upstream cascade (parents cause this driver)
                    nxt.append((p, d + 1, None, "driver", cid))
        wave = nxt

    nodes = list(kept.values())
    sg = Subgraph(seeds=seeds, nodes=nodes,
                  trace={"seeds": seeds, "kept": [list(n.key) for n in nodes], "pruned": pruned,
                         "visited": len(visited), "budget": node_budget,
                         "params": {"depth": depth, "tau": tau, "node_budget": node_budget, "max_seeds": max_seeds}})
    sg.mermaid = graph_to_mermaid(sg, graph)
    return sg


def _prior(graph: gph.CausalGraph, n: GroundedNode) -> dict:
    if n.kind == "driver":
        d = graph.driver(n.contract, n.id)
        return {"sign": d.sign, "lag": d.lag, "mechanism": d.mechanism, "confidence": d.confidence,
                "target_metric": d.target_metric, "silver_ref": d.silver_ref, "silver_status": d.silver_status}
    c = graph.contracts[n.contract]
    return {"target_metrics": list(c.target_metrics), "via_edge": n.via_edge}


# ── ground(): the I/O legs — evidence (WS-2), silver (WS-5), convergence firing (WS-4) ───────────────────────
def _slice_of(n: GroundedNode, slice_path) -> Optional[str]:
    """Evidence-slice path for a node. Contract -> its commodity slice; driver -> drivers/<slice> resolved
    through the alias map (None when the driver has no text slice)."""
    return ev.node_for(n.contract) if n.kind == "contract" else slice_path(n.id)


def _dedup_and_cap(sg: Subgraph, cap: int) -> None:
    """A prop retrieved under several nodes is attributed to the SHALLOWEST (most-relevant) node only, and the
    subgraph's total evidence is capped (depth-2 unions explode) — shallow nodes first."""
    seen: set = set()
    budget = cap
    for n in sorted(sg.nodes, key=lambda x: (x.depth, -x.relevance)):
        keep = []
        for h in n.evidence:
            sig = (h.get("source_key"), h.get("date"), (h.get("text") or "")[:80])
            if sig in seen or budget <= 0:
                continue
            seen.add(sig)
            keep.append(h)
            budget -= 1
        n.evidence = keep


def ground(sg: Subgraph, query: str, graph: gph.CausalGraph, *, retrieve=None, silver_lookup=None,
           asof=None, near=None, k_by_depth=_K_BY_DEPTH, evidence_cap: int = _EVIDENCE_CAP, driver_slices=None,
           probe_cap: int = _PROBE_CAP, recency_days: int = _RECENCY_DAYS, probe_retrieve=None) -> Subgraph:
    """Fill the evidence + silver legs and fire convergence deterministically. `retrieve`/`silver_lookup` are
    injectable (tests pass fakes; serving passes the real hybrid+rerank+mmr retriever + numbers lookup).

    Two things resolve the v1.1 A/B blockers (regimes fired 0.0, leg-grounding 0.2):
      * driver evidence now reads drivers/<SLICE> via the alias map (ev.slice_for_driver) — slice NAMES were
        curated apart from DAG driver ids, so the old drivers/<id> path resolved only the 13 exact-name
        matches; the alias unlocks ~40+ ids (incl. the top regime drivers heat_stress / *_su_ratio / crude /
        USD_index / cot positioning). Tests still inject `driver_slices` (a set) to stay hermetic: then the
        driver id IS treated as its own slice path, as before.
      * regime firing is DECOUPLED from the walk: a regime is evaluated over its FULL required-driver list,
        not just the drivers the budget-limited walk happened to keep (70% of required drivers were never
        even visited). A required driver missing from the walk gets a cheap activity PROBE (k=2, asof-guarded,
        cached per (contract, driver), capped) — active if its slice has dated evidence at the asof, or it is
        named in the contract's own evidence."""
    retrieve = retrieve or ev.retrieve
    if driver_slices is not None:                                  # hermetic tests: the id IS the slice path
        backed = set(driver_slices)
        def slice_path(did):  # noqa: E306
            return f"drivers/{did}"
    else:                                                          # serving: resolve dag id -> curated slice
        backed = ev.backed_dag_ids()
        def slice_path(did):  # noqa: E306
            s = ev.slice_for_driver(did)
            return f"drivers/{s}" if s else None

    for n in sg.nodes:                                             # per-node evidence, k decays with depth
        sp = _slice_of(n, slice_path)
        if n.kind == "driver" and (n.id not in backed or sp is None):
            continue                                               # no slice -> prior-only node (no empty fetch)
        k = k_by_depth[min(n.depth, len(k_by_depth) - 1)]
        n.evidence = list(retrieve(query, sp, k=k, asof=asof, near=near))
    _dedup_and_cap(sg, evidence_cap)                              # dedup cross-node restatement + cap total

    ctx_text: dict[str, str] = {}                                 # contract -> its own evidence text (for active)
    for n in sg.nodes:
        if n.kind == "contract" and n.evidence:
            ctx_text[n.contract] = " ".join((h.get("text") or "").lower() for h in n.evidence)

    for n in sg.nodes:                                            # silver leg (driver nodes only)
        if n.kind == "driver" and silver_lookup and n.prior.get("silver_ref"):
            try:
                n.silver = silver_lookup(n.contract, n.id, asof)
            except Exception:  # noqa: BLE001 — a silver miss must never break the answer
                n.silver = {"ref": n.prior.get("silver_ref"), "live": False}
        if n.kind == "driver":
            named = n.id.replace("_", " ").lower() in ctx_text.get(n.contract, "")
            n.active = bool(n.evidence) or named              # slice evidence OR named in the contract's evidence

    # ── regime firing DECOUPLED from the walk — but only MEANINGFUL firing ───────────────────────────────
    # The first regime-fix eval taught us the hard way (PIT 4.1->3.7, halluc 61->72): firing off "the driver
    # is mentioned somewhere in history" made the reasoner assert live regime state the evidence never
    # supported. A regime may now count a driver ONLY on dated slice evidence WITHIN `recency_days` BEFORE
    # the as-of (receipt recorded: {date, source}); no as-of -> nothing to anchor "now" -> nothing fires
    # (regime definitions still reach the reasoner as structure); a driver merely NAME-DROPPED in the
    # contract's evidence keeps its display `active` flag but never fires a regime.
    sg.fired_regimes = []
    regime_basis: dict[str, dict] = {}
    vetoed: dict[str, dict] = {}                                   # contract -> {driver: normal silver reading}
    budget = {"left": probe_cap}
    asof_s = str(asof)[:10] if asof else None
    floor = None
    if asof_s:
        import datetime as _dt
        try:
            floor = (_dt.date.fromisoformat(asof_s) - _dt.timedelta(days=recency_days)).isoformat()
        except ValueError:
            asof_s = None                                          # unparseable as-of -> treat as none

    if asof_s and floor:
        def _recent(props):
            """Newest prop dated within [asof - recency_days, asof], as a receipt — or None."""
            best = None
            for h in props or []:
                d = str(h.get("date") or "")[:10]
                if d and floor <= d <= asof_s and (best is None or d > best["date"]):
                    best = {"date": d, "source": h.get("source", "")}
            return best

        probe_cache: dict[tuple, Optional[dict]] = {}
        for n in sg.nodes:                                         # reuse walk evidence when it already qualifies
            if n.kind == "driver":
                b = _recent(n.evidence)
                if b:
                    probe_cache[(n.contract, n.id)] = b

        # Probes are EXISTENCE checks ("any dated prop in the window?"), not quality retrieval — they must
        # never pay the CPU cross-encoder reranker (24 probes x ~2-4s of rerank per answer was the second
        # slowdown of the July-3 evals; a cheap dense/lex fetch is ~10x faster with identical semantics).
        probe = probe_retrieve or retrieve

        def _basis(cid: str, did: str):
            key = (cid, did)
            if key in probe_cache:
                return probe_cache[key]
            # SILVER FIRST (F4): an OBSERVED anomalous value at the as-of vintage is the strongest
            # receipt; a live-and-NORMAL value VETOES the driver — documented chatter cannot fire a
            # regime the observed data contradicts. Inconclusive/miss -> the text semantics decide.
            if silver_lookup is not None:
                sv = silver_lookup(cid, did, asof)
                if sv and sv.get("live"):
                    if sv.get("verdict") == "observed":
                        probe_cache[key] = {"kind": "observed", "date": sv.get("knowledge_date", ""),
                                            "source": sv.get("ref", "silver"), "value": sv.get("value"),
                                            "unit": sv.get("unit", ""), "z": sv.get("z"),
                                            "detail": sv.get("detail", "")}
                        return probe_cache[key]
                    if sv.get("verdict") == "normal":
                        vetoed.setdefault(cid, {})[did] = {"value": sv.get("value"), "z": sv.get("z"),
                                                           "unit": sv.get("unit", ""),
                                                           "source": sv.get("ref", "silver"),
                                                           "date": sv.get("knowledge_date", "")}
                        probe_cache[key] = None
                        return None
            sp = slice_path(did) if did in backed else None
            if sp and budget["left"] > 0:                          # asof-guarded slice probe, recency-tested
                budget["left"] -= 1
                probe_cache[key] = _recent(list(probe(query, sp, k=2, asof=asof, near=near)))
            else:
                probe_cache[key] = None
            return probe_cache[key]

        for cid in sorted({n.contract for n in sg.nodes}):
            if cid not in graph.contracts:
                continue
            required = {d for s in graph.contracts[cid].convergence for d in s.drivers}
            bases = {}
            for d in sorted(required):
                b = _basis(cid, d)
                if b:
                    bases[d] = b
            regime_basis[cid] = bases
            for fr in graph.regimes(cid, sorted(bases)):
                sg.fired_regimes.append({"contract": cid, "name": fr.name, "direction": fr.direction,
                                         "matched": fr.matched, "threshold": fr.threshold,
                                         "basis": {d: bases[d] for d in fr.matched if d in bases},
                                         "interactions": fr.interactions, "note": fr.note})
    sg.trace["n_evidence"] = sum(len(n.evidence) for n in sg.nodes)
    sg.trace["active"] = [list(n.key) for n in sg.nodes if n.active]
    sg.trace["regime_basis"] = regime_basis
    sg.trace["n_probes"] = probe_cap - budget["left"]
    sg.trace["silver_veto"] = vetoed                               # drivers observed NORMAL (excluded from firing)
    return sg


# ── mermaid: the cascade diagram FROM THE GRAPH (not the LLM) ─────────────────────────────────────────────────
def _mid(kind: str, contract: str, id_: str) -> str:
    import re
    return re.sub(r"[^0-9a-zA-Z_]", "_", f"{kind[0]}_{contract}_{id_}")


def graph_to_mermaid(sg: Subgraph, graph: gph.CausalGraph) -> str:
    """Deterministic cascade skeleton over the KEPT nodes: parent-driver -> driver -> contract price, plus
    tracked cross-commodity hops. Signs ride in the labels. Overrides the LLM's diagram at serving time."""
    kept = {n.key for n in sg.nodes}
    lines = ["flowchart LR"]
    price = {}                                             # one price node per contract in the subgraph
    for n in sg.nodes:
        if n.kind == "contract":
            pid = _mid("p", n.contract, "price")
            price[n.contract] = pid
            lines.append(f'{pid}["{n.contract.replace("_", " ")} price"]')
    for n in sg.nodes:
        if n.kind != "driver":
            continue
        did = _mid("driver", n.contract, n.id)
        sign = n.prior.get("sign", "")
        lines.append(f'{did}["{n.id.replace("_", " ")} {sign}"]')
        tgt = price.get(n.contract) or _mid("p", n.contract, "price")
        lines.append(f"{did} --> {tgt}")
        for p in graph.driver(n.contract, n.id).parents:   # upstream cascade edge, if the parent was kept
            if ("driver", n.contract, p) in kept:
                lines.append(f'{_mid("driver", n.contract, p)} --> {did}')
    for n in sg.nodes:                                     # cross-commodity hops between kept contracts
        if n.kind == "contract" and n.via_edge:
            frm = n.via_edge.get("_from")
            if frm and frm in price:
                lines.append(f'{price[frm]} -->|{n.via_edge.get("relation","")} {n.via_edge.get("sign","")}| '
                             f'{price.get(n.contract, _mid("p", n.contract, "price"))}')
    return "\n".join(lines)
