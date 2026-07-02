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

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from leviathan.graphrag import evidence as ev
from leviathan.graphrag import graph as gph


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


def grounded_subgraph(query: str, graph: gph.CausalGraph, *, depth: int = 2, node_budget: int = 10,
                      tau: float = 0.35, max_seeds: int = 2, embed=None, route_fn=None) -> Subgraph:
    """Query-conditioned frontier walk. Returns the kept subgraph with the PRIOR leg + mermaid + trace filled;
    evidence/silver/convergence are added by ground(). Deterministic given `embed` (inject a fake in tests)."""
    embed = embed or ev.embed
    if route_fn is None:
        from leviathan.graphrag import answer as _an       # lazy: answer imports planner for the l2 path
        route_fn = _an.route_smart
    qv = embed([query])[0]
    mech: dict = {}

    seeds = _seed_contracts(query, graph, route_fn, max_seeds)
    frontier: deque = deque((c, 0, None, "contract", c) for c in seeds)  # (id, depth, via_edge, kind, contract)
    visited: set = set()
    kept: dict[tuple, GroundedNode] = {}
    pruned: list[dict] = []

    while frontier and len(kept) < node_budget:
        id_, d, via, kind, cid = frontier.popleft()
        key = (kind, cid, id_)
        if key in visited:
            continue
        visited.add(key)

        if d == 0:                                          # seeds always kept
            rel = 1.0
        elif kind == "contract":                            # a cross-commodity hop: score its edge mechanism
            rel = _relevance(qv, (via or {}).get("mechanism", ""), embed, mech)
        else:                                               # a driver: score its mechanism
            rel = _relevance(qv, graph.driver(cid, id_).mechanism, embed, mech)
        if d > 0 and rel < tau:
            pruned.append({"key": list(key), "relevance": round(rel, 3), "depth": d})
            continue

        node = GroundedNode(kind=kind, id=id_, contract=cid, depth=d, relevance=round(rel, 3), via_edge=via)
        node.prior = _prior(graph, node)
        kept[key] = node
        if d >= depth:
            continue

        if kind == "contract":
            for e in graph.cross_links(cid):                # tracked inter-commodity hops FIRST (BFS priority) so a
                if e["tracked"]:                            # contract's driver breadth can't starve the cascade hop —
                    frontier.append((e["driver_commodity"], d + 1, {**e, "_from": cid}, "contract",  # L2's headline
                                     e["driver_commodity"]))
            for drv in graph.contracts[cid].drivers:        # then the driver fan-in of this contract
                frontier.append((drv.id, d + 1, None, "driver", cid))
        else:
            for p in graph.driver(cid, id_).parents:        # upstream cascade (parents cause this driver)
                frontier.append((p, d + 1, None, "driver", cid))

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
def _slice_of(n: GroundedNode) -> str:
    return ev.node_for(n.contract) if n.kind == "contract" else f"drivers/{n.id}"


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
           asof=None, near=None, k_by_depth=(5, 3, 2), evidence_cap: int = 24) -> Subgraph:
    """Fill the evidence + silver legs and fire convergence deterministically. `retrieve`/`silver_lookup` are
    injectable (tests pass fakes; serving passes the real hybrid+rerank+mmr retriever + numbers lookup)."""
    retrieve = retrieve or ev.retrieve
    for n in sg.nodes:                                              # WS-2: per-node evidence, k decays with depth
        k = k_by_depth[min(n.depth, len(k_by_depth) - 1)]
        n.evidence = list(retrieve(query, _slice_of(n), k=k, asof=asof, near=near))
    _dedup_and_cap(sg, evidence_cap)                               # WS-2: dedup cross-node restatement + cap total

    for n in sg.nodes:                                             # WS-5: silver leg (driver nodes only)
        if n.kind == "driver" and silver_lookup and n.prior.get("silver_ref"):
            try:
                n.silver = silver_lookup(n.contract, n.id, asof)
            except Exception:  # noqa: BLE001 — a silver miss must never break the answer
                n.silver = {"ref": n.prior.get("silver_ref"), "live": False}
        n.active = n.kind == "driver" and bool(n.evidence)        # active = dated evidence near the episode exists

    sg.fired_regimes = []                                          # WS-4: deterministic convergence via graph.regimes
    for cid in sorted({n.contract for n in sg.nodes}):
        active = [n.id for n in sg.by_contract(cid) if n.kind == "driver" and n.active]
        for fr in graph.regimes(cid, active):
            sg.fired_regimes.append({"contract": cid, "name": fr.name, "direction": fr.direction,
                                     "matched": fr.matched, "threshold": fr.threshold,
                                     "interactions": fr.interactions, "note": fr.note})
    sg.trace["n_evidence"] = sum(len(n.evidence) for n in sg.nodes)
    sg.trace["active"] = [list(n.key) for n in sg.nodes if n.active]
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
