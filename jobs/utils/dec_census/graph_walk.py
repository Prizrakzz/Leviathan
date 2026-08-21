"""DEC-P0 graph deep-dive: what the ENGINE actually walks.

Reconstructs the real node/edge set from the loaded CausalGraph (the same loader serving uses),
replicates planner.grounded_subgraph's BFS structurally (tau=0, budget=inf) in BOTH cascade
directions, and emits data/dec_p0/graph_walk.{json,md}.
"""
from __future__ import annotations

import collections
import itertools
import json
import os
from pathlib import Path

import yaml

REPO = Path("C:/Users/User/Desktop/Leviathan")
CFG = REPO / "configs" / "graphrag"
OUT = REPO / "data" / "dec_p0"
OUT.mkdir(parents=True, exist_ok=True)

from leviathan.graphrag import graph as gph          # noqa: E402
from leviathan.graphrag import evidence as ev        # noqa: E402
from leviathan.graphrag import display as dp         # noqa: E402
from leviathan.graphrag import planner as pl         # noqa: E402

G = gph.CausalGraph.load()
CONTRACTS = G.contracts
HIER = yaml.safe_load((CFG / "commodity_hierarchy.yaml").read_text(encoding="utf-8")) or {}
HC = HIER.get("contracts") or {}
GROUPS = HIER.get("groups") or {}
COMPLEXES = HIER.get("complexes") or {}
CONTEXT_COMMODITIES = list(HIER.get("context_commodities") or [])
VOCAB = yaml.safe_load((CFG / "entity_vocabulary.yaml").read_text(encoding="utf-8")) or {}
DS_RAW = yaml.safe_load((CFG / "driver_slices.yaml").read_text(encoding="utf-8")) or {}

NODE_OF = {cid: (v.get("node") or cid) for cid, v in HC.items() if isinstance(v, dict)}
ALL_NODES = sorted(set(NODE_OF.values()))
NODE_CONTRACTS = collections.defaultdict(list)
for _c, _n in sorted(NODE_OF.items()):
    NODE_CONTRACTS[_n].append(_c)

HIER_ANCHORS = sorted(c for c in CONTRACTS if c in HC)          # seed-eligible, tradeable
BASE_YAMLS = sorted(c for c in CONTRACTS if c not in HC)        # corn / soybeans base yamls
ALL_ANCHORS = sorted(CONTRACTS)


def node_of(name: str) -> str:
    return NODE_OF.get(name, name)


# ─────────────────────────────────────────────────────────────────────────────
# 1. THE REAL NODE SET + EDGE SET
# ─────────────────────────────────────────────────────────────────────────────
driver_instances = [(cid, d.id) for cid in sorted(CONTRACTS) for d in CONTRACTS[cid].drivers]
distinct_driver_ids = sorted({d for _, d in driver_instances})
parent_edges = [(cid, p, d.id) for cid in sorted(CONTRACTS) for d in CONTRACTS[cid].drivers for p in d.parents]
drv_target_edges = len(driver_instances)
inter_edges = [(cid, e.driver_commodity, e.relation, e.sign, e.lag)
               for cid in sorted(CONTRACTS) for e in CONTRACTS[cid].inter_commodity]
convergence_signals = [(cid, s.name, s.direction, s.requires_any_n_of, list(s.drivers))
                       for cid in sorted(CONTRACTS) for s in CONTRACTS[cid].convergence]

# what the ENGINE'S FORWARD walk can traverse: `tracked` == raw string equality against loaded ids
inter_tracked = [(a, b, r) for (a, b, r, _s, _l) in inter_edges if b in CONTRACTS]
inter_untracked = [(a, b, r) for (a, b, r, _s, _l) in inter_edges if b not in CONTRACTS]
# what the REVERSE index resolves (alias-resolved through the hierarchy)
rev_table = G.rev_cross_link_resolution()
rev_buckets = G.rev_cross_link_buckets()

# node-level, ALIAS-RESOLVED directed edge set (declaring node -> declared/driver node)
resolved_node_edges = set()
resolved_node_edge_rows = []
undefined_endpoints = collections.Counter()
for r in rev_table:
    src = node_of(r["declaring_contract"])
    dst = r["node"]
    if dst is None:
        undefined_endpoints[r["driver_commodity"]] += 1
        continue
    if src == dst:
        continue
    resolved_node_edges.add((src, dst))
    resolved_node_edge_rows.append({"src_node": src, "dst_node": dst,
                                    "declaring_contract": r["declaring_contract"],
                                    "driver_commodity": r["driver_commodity"],
                                    "relation": r["relation"], "sign": r["sign"],
                                    "foreign_tradeable": r["foreign_tradeable"]})
# engine-forward node edges (only the string-equality tracked ones)
tracked_node_edges = {(node_of(a), node_of(b)) for (a, b, _r) in inter_tracked if node_of(a) != node_of(b)}

undirected_node_edges = {tuple(sorted(e)) for e in resolved_node_edges}


# ─────────────────────────────────────────────────────────────────────────────
# 2. THE WALK — replicated structurally from planner.grounded_subgraph
# ─────────────────────────────────────────────────────────────────────────────
def engine_walk(seed, depth=None):
    """planner.grounded_subgraph's BFS with tau=0 and node_budget=inf.

    contract node -> tracked cross_links (contract, d+1) + EVERY driver of the contract (driver, d+1)
    driver node  -> its .parents (driver, d+1, SAME contract)
    key = (kind, contract, id); `d >= depth` stops expansion.
    """
    visited: dict = {}
    wave = [(seed, 0, "contract", seed)]
    while wave:
        nxt = []
        for id_, d, kind, cid in wave:
            key = (kind, cid, id_)
            if key in visited:
                continue
            visited[key] = d
            if depth is not None and d >= depth:
                continue
            if kind == "contract":
                if cid not in CONTRACTS:
                    continue
                for e in G.cross_links(cid):
                    if e["tracked"]:
                        nxt.append((e["driver_commodity"], d + 1, "contract", e["driver_commodity"]))
                for drv in CONTRACTS[cid].drivers:
                    nxt.append((drv.id, d + 1, "driver", cid))
            else:
                for p in G.driver(cid, id_).parents:
                    nxt.append((p, d + 1, "driver", cid))
        wave = nxt
    return visited


def reverse_walk(seed, depth=None):
    """The DOWNSTREAM leg: graph.rev_cross_links (node-keyed, alias-resolved inverted inter_commodity).
    Serving offers ONE hop and does NOT expand it (structural fan-out fence, _cascade_plan);
    depth=None here is the STRUCTURAL CEILING, depth=1 is what a turn can actually buy."""
    visited: dict = {}
    wave = [(seed, 0)]
    while wave:
        nxt = []
        for c, d in wave:
            if c in visited:
                continue
            visited[c] = d
            if depth is not None and d >= depth:
                continue
            for lk in G.rev_cross_links(c):
                f = lk.get("contract")
                if f and f != c:
                    nxt.append((f, d + 1))
        wave = nxt
    return visited


walk_full = {c: engine_walk(c, depth=None) for c in ALL_ANCHORS}
walk_d2 = {c: engine_walk(c, depth=2) for c in ALL_ANCHORS}      # shipped default (params depth: 2)
walk_d1 = {c: engine_walk(c, depth=1) for c in ALL_ANCHORS}      # deep/seed-scaled presets pin depth=1
rev_full = {c: reverse_walk(c, depth=None) for c in ALL_ANCHORS}
rev_d1 = {c: reverse_walk(c, depth=1) for c in ALL_ANCHORS}


def walk_stats(vis: dict) -> dict:
    depths = collections.Counter(vis.values())
    contracts_ = sorted({k[1] for k in vis if k[0] == "contract"})
    drivers_ = [k for k in vis if k[0] == "driver"]
    return {"n_nodes": len(vis), "n_contract_nodes": len(contracts_), "n_driver_nodes": len(drivers_),
            "contracts": contracts_, "max_depth": max(vis.values()) if vis else 0,
            "by_depth": {str(k): v for k, v in sorted(depths.items())}}


# dead ends inside the walk: a node whose expansion enqueues NOTHING
def dead_ends(seed):
    vis = walk_full[seed]
    out = []
    for (kind, cid, id_), d in vis.items():
        if kind == "driver":
            if not G.driver(cid, id_).parents:
                out.append(f"{cid}:{id_}")
        else:
            if cid in CONTRACTS and not any(e["tracked"] for e in G.cross_links(cid)):
                out.append(f"contract:{cid}")
    return sorted(out)


# how much does the PARENT layer actually add to the walk? (the D-GD measured claim)
parent_layer_new_nodes = {}
for c in ALL_ANCHORS:
    d1 = set(walk_d1[c])
    full = set(walk_full[c])
    # nodes at depth>=2 that are drivers of the SEED contract (i.e. reached only via .parents)
    new_via_parents = [k for k in full - d1 if k[0] == "driver" and walk_full[c][k] >= 2 and k[1] == c]
    parent_layer_new_nodes[c] = len(new_via_parents)


# ─────────────────────────────────────────────────────────────────────────────
# 3. GAP LISTS
# ─────────────────────────────────────────────────────────────────────────────
backed = ev.backed_dag_ids()
slice_of = ev.slice_for_driver
specs = ev.driver_specs()
all_dag_ids = set(dp.all_driver_ids())
waivers = DS_RAW.get("waivers") or {}

dark_driver_ids = sorted(d for d in distinct_driver_ids if d not in backed)
dark_waived = sorted(d for d in dark_driver_ids if d in waivers)
dark_unwaived = sorted(d for d in dark_driver_ids if d not in waivers)
dark_driver_instances = [f"{c}:{d}" for c, d in driver_instances if d not in backed]

slices_reached = {slice_of(d) for d in distinct_driver_ids if slice_of(d)}
orphan_slices = sorted(s for s in specs if s not in slices_reached)

# reachability from anchors
union_full = set()
for c in HIER_ANCHORS:
    union_full |= set(walk_full[c])
all_driver_keys = {("driver", c, d) for c, d in driver_instances}
all_contract_keys = {("contract", c, c) for c in CONTRACTS}
orphan_driver_instances = sorted(f"{k[1]}:{k[2]}" for k in (all_driver_keys - union_full))
orphan_contract_nodes = sorted(k[1] for k in (all_contract_keys - union_full))

# contracts reachable only as their OWN anchor (isolated in the inter-commodity layer)
inbound_forward = collections.Counter()
for a, b, _r in inter_tracked:
    inbound_forward[b] += 1
outbound_forward = collections.Counter()
for a, b, _r in inter_tracked:
    outbound_forward[a] += 1
isolated_forward = sorted(c for c in CONTRACTS if inbound_forward[c] == 0)
no_forward_out = sorted(c for c in CONTRACTS if outbound_forward[c] == 0)
no_reverse = sorted(c for c in CONTRACTS if not G.rev_cross_links(c))
cross_market_isolated = sorted(c for c in CONTRACTS
                               if inbound_forward[c] == 0 and not G.rev_cross_links(c))

# commodities with no DAG
nodes_with_dag = {node_of(c) for c in CONTRACTS if c in HC}
nodes_no_dag = sorted(n for n in ALL_NODES if n not in nodes_with_dag)
group_members = sorted({m for v in GROUPS.values() for m in v} | {m for v in COMPLEXES.values() for m in v})
group_members_no_dag = sorted(m for m in group_members if m not in nodes_with_dag)
context_no_dag = sorted(m for m in CONTEXT_COMMODITIES if m not in nodes_with_dag)
vocab_nodes = sorted((VOCAB.get("nodes") or {}).keys())

# edges referencing undefined nodes
undefined_edge_rows = sorted(
    [{"declaring_contract": r["declaring_contract"], "driver_commodity": r["driver_commodity"],
      "relation": r["relation"], "sign": r["sign"]}
     for r in rev_table if r["node"] is None],
    key=lambda r: (r["driver_commodity"], r["declaring_contract"]))
undefined_names = sorted(undefined_endpoints.items(), key=lambda kv: (-kv[1], kv[0]))

# forward-untracked but alias-resolvable: edges the ENGINE'S FORWARD WALK cannot traverse
forward_lost = []
for r in rev_table:
    if r["driver_commodity"] in CONTRACTS:
        continue                                    # the forward walk CAN traverse this
    forward_lost.append({"declaring_contract": r["declaring_contract"],
                         "driver_commodity": r["driver_commodity"],
                         "resolved_node": r["node"], "bucket": r["bucket"],
                         "relation": r["relation"],
                         "recoverable": bool(r["node"] and r["tracked_candidates"])})
forward_lost_recoverable = [r for r in forward_lost if r["recoverable"]]

# convergence signals whose drivers are dark (cannot be cited)
conv_dark = []
for cid, name, direction, n, drvs in convergence_signals:
    dk = [d for d in drvs if d not in backed]
    if dk:
        conv_dark.append({"contract": cid, "signal": name, "n_drivers": len(drvs),
                          "dark_drivers": sorted(dk), "requires_any_n_of": n,
                          "unsatisfiable_from_text": len(drvs) - len(dk) < n})
conv_unsatisfiable = [c for c in conv_dark if c["unsatisfiable_from_text"]]


# ─────────────────────────────────────────────────────────────────────────────
# 4. COMPLEXES
# ─────────────────────────────────────────────────────────────────────────────
def complex_report(name, members):
    live = [m for m in members if m in nodes_with_dag]
    pairs = list(itertools.combinations(sorted(live), 2))
    present = [p for p in pairs if p in undirected_node_edges]
    missing = [p for p in pairs if p not in undirected_node_edges]
    # connected components over the induced subgraph
    adj = collections.defaultdict(set)
    for u, v in present:
        adj[u].add(v)
        adj[v].add(u)
    seen, comps = set(), []
    for m in sorted(live):
        if m in seen:
            continue
        stack, comp = [m], []
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            comp.append(x)
            stack.extend(adj[x] - seen)
        comps.append(sorted(comp))
    return {"name": name, "members": list(members), "members_with_dag": live,
            "members_without_dag": [m for m in members if m not in nodes_with_dag],
            "n_pairs": len(pairs), "n_pairs_connected": len(present),
            "density": round(len(present) / len(pairs), 3) if pairs else None,
            "connected_pairs": [list(p) for p in present],
            "missing_pairs": [list(p) for p in missing],
            "components": comps, "n_components": len(comps)}


complexes_rpt = [complex_report(k, v) for k, v in COMPLEXES.items()]
groups_rpt = [complex_report(k, v) for k, v in GROUPS.items()]

# directed chains of length >= 2 over the resolved node graph (multi-commodity transmission chains)
adj_dir = collections.defaultdict(set)
for u, v in resolved_node_edges:
    adj_dir[u].add(v)
chains = []
for a in sorted(adj_dir):
    for b in sorted(adj_dir[a]):
        for c_ in sorted(adj_dir.get(b, ())):
            if c_ in (a, b):
                continue
            chains.append([a, b, c_])
chains4 = []
for ch in chains:
    for d_ in sorted(adj_dir.get(ch[2], ())):
        if d_ in ch:
            continue
        chains4.append(ch + [d_])

# reciprocity
reciprocal = sorted({tuple(sorted((u, v))) for (u, v) in resolved_node_edges
                     if (v, u) in resolved_node_edges})
one_way = sorted([[u, v] for (u, v) in resolved_node_edges if (v, u) not in resolved_node_edges])


# ─────────────────────────────────────────────────────────────────────────────
# 5. MISSING-EDGE CANDIDATES
# ─────────────────────────────────────────────────────────────────────────────
# neighborhood of a contract = its own node + every resolved endpoint node it declares
neighborhoods = {}
for cid in sorted(CONTRACTS):
    nb = {node_of(cid)}
    for r in rev_table:
        if r["declaring_contract"] == cid and r["node"]:
            nb.add(r["node"])
    neighborhoods[cid] = nb

pair_cooccur = collections.Counter()
for cid, nb in neighborhoods.items():
    for u, v in itertools.combinations(sorted(nb), 2):
        pair_cooccur[(u, v)] += 1

# common neighbours in the undirected node graph
adj_und = collections.defaultdict(set)
for u, v in undirected_node_edges:
    adj_und[u].add(v)
    adj_und[v].add(u)

# slice fingerprint per node (the driver slices its DAG(s) reach)
node_slices = {}
for n in ALL_NODES:
    s = set()
    for cid in NODE_CONTRACTS[n]:
        if cid not in CONTRACTS:
            continue
        for d in CONTRACTS[cid].drivers:
            sp = slice_of(d.id)
            if sp:
                s.add(sp)
    node_slices[n] = s

member_of = collections.defaultdict(set)
for k, v in COMPLEXES.items():
    for m in v:
        member_of[m].add("complex:" + k)
for k, v in GROUPS.items():
    for m in v:
        member_of[m].add("group:" + k)

live_nodes = sorted(nodes_with_dag)
cands = []
for u, v in itertools.combinations(live_nodes, 2):
    if (u, v) in undirected_node_edges:
        continue
    shared_groups = sorted(member_of[u] & member_of[v])
    cn = len(adj_und[u] & adj_und[v])
    co = pair_cooccur.get((u, v), 0)
    ssl = len(node_slices[u] & node_slices[v])
    jac = round(ssl / max(1, len(node_slices[u] | node_slices[v])), 3)
    if not shared_groups and cn == 0 and co == 0:
        continue
    cands.append({"a": u, "b": v, "shared_groups": shared_groups,
                  "common_neighbors": cn, "dag_neighborhood_cooccurrence": co,
                  "shared_driver_slices": ssl, "slice_jaccard": jac,
                  "score": round(3.0 * len(shared_groups) + 1.0 * cn + 1.5 * co + 0.25 * ssl, 3)})
cands.sort(key=lambda r: (-r["score"], -r["common_neighbors"], r["a"], r["b"]))


# ─────────────────────────────────────────────────────────────────────────────
# 6. S3 evidence reality check (ONE paginated LIST, no per-object GETs)
# ─────────────────────────────────────────────────────────────────────────────
s3_nodes, s3_driver_slices, s3_err = set(), set(), None
try:
    import boto3
    cli = boto3.client("s3")
    for page in cli.get_paginator("list_objects_v2").paginate(
            Bucket="leviathan-dev-shahem-001", Prefix="graphrag_evidence/"):
        for o in page.get("Contents", []):
            k = o["Key"][len("graphrag_evidence/"):]
            if k.endswith(".jsonl") and "/" not in k:
                s3_nodes.add(k[:-6])
            elif k.startswith("drivers/") and k.endswith(".jsonl") and k.count("/") == 1:
                s3_driver_slices.add(k[len("drivers/"):-6])
except Exception as exc:  # noqa: BLE001
    s3_err = f"{type(exc).__name__}: {exc}"

nodes_no_evidence_file = sorted(n for n in ALL_NODES if s3_nodes and n not in s3_nodes)
evidence_files_no_node = sorted(n for n in s3_nodes if n not in ALL_NODES)
slices_no_file = sorted(s for s in specs if s3_driver_slices and s not in s3_driver_slices)
files_no_slice = sorted(s for s in s3_driver_slices if s not in specs)


# ─────────────────────────────────────────────────────────────────────────────
# ARTIFACT
# ─────────────────────────────────────────────────────────────────────────────
walkability = []
for c in ALL_ANCHORS:
    f, d2, d1 = walk_stats(walk_full[c]), walk_stats(walk_d2[c]), walk_stats(walk_d1[c])
    rf, r1 = rev_full[c], rev_d1[c]
    rf_nodes = sum(1 + len(CONTRACTS[x].drivers) for x in rf if x in CONTRACTS and x != c)
    walkability.append({
        "anchor": c, "node": node_of(c), "in_hierarchy": c in HC,
        "n_drivers": len(CONTRACTS[c].drivers),
        "n_inter_commodity_edges": len(CONTRACTS[c].inter_commodity),
        "n_inter_tracked": sum(1 for e in G.cross_links(c) if e["tracked"]),
        "n_convergence": len(CONTRACTS[c].convergence),
        "upstream_full_nodes": f["n_nodes"], "upstream_full_contracts": f["n_contract_nodes"],
        "upstream_full_drivers": f["n_driver_nodes"], "upstream_max_depth": f["max_depth"],
        "upstream_by_depth": f["by_depth"],
        "upstream_d2_nodes": d2["n_nodes"], "upstream_d2_contracts": d2["n_contract_nodes"],
        "upstream_d1_nodes": d1["n_nodes"],
        "new_nodes_from_parent_layer": parent_layer_new_nodes[c],
        "downstream_1hop_contracts": max(0, len(r1) - 1),
        "downstream_full_contracts": max(0, len(rf) - 1),
        "downstream_full_max_depth": max(rf.values()) if rf else 0,
        "downstream_1hop_node_ceiling": rf_nodes if False else sum(
            1 + len(CONTRACTS[x].drivers) for x in r1 if x in CONTRACTS and x != c),
        "downstream_contracts": sorted(x for x in r1 if x != c),
        "n_dead_end_drivers": sum(1 for d in CONTRACTS[c].drivers if not d.parents),
        "n_dark_drivers": sum(1 for d in CONTRACTS[c].drivers if d.id not in backed),
    })

# ── serving reality: which shipped preset can walk what ──────────────────────
from leviathan.graphrag import reasoning_modes as rm     # noqa: E402
serving_names = sorted(rm.serving_names())
modes_tbl = []
for n in sorted(rm.MODES):
    m = rm.MODES[n]
    modes_tbl.append({"mode": n, "serving": n in rm.serving_names(),
                      "depth": m.depth if m.depth is not None else pl._DEPTH,
                      "depth_declared": m.depth,
                      "max_seeds": m.max_seeds if m.max_seeds is not None else pl._MAX_SEEDS,
                      "node_budget": m.node_budget, "per_seed_budget": m.per_seed_budget,
                      "per_seed_reserve": m.per_seed_reserve,
                      "cascade_contract_slots": m.cascade_contract_slots})
serving_cascade_on = [r["mode"] for r in modes_tbl if r["serving"] and r["cascade_contract_slots"]]

serving_pool = []
for c in ALL_ANCHORS:
    ntr = sum(1 for e in G.cross_links(c) if e["tracked"])
    pool_d1 = 1 + len(CONTRACTS[c].drivers) + ntr          # what depth=1 can even SEE from one seed
    serving_pool.append({"anchor": c, "d1_candidate_pool": pool_d1,
                         "quick_budget": 12, "deep_budget": 32,
                         "quick_pool_over_budget": max(0, pool_d1 - 1 - 12),
                         "deep_pool_over_budget": max(0, pool_d1 - 1 - 32),
                         "structural_ceiling_full_depth": len(walk_full[c])})

agg_depth = collections.Counter()
for c in ALL_ANCHORS:
    for d in walk_full[c].values():
        agg_depth[d] += 1

tracked_hist = collections.Counter(b for (_a, b, _r) in inter_tracked)
untracked_hist = collections.Counter(b for (_a, b, _r) in inter_untracked)
base_landing = sum(v for k, v in tracked_hist.items() if k in set(BASE_YAMLS))

dark_detail = [{"driver_id": d, "waiver_category": (waivers.get(d) or {}).get("category"),
                "n_contracts": sum(1 for c, x in driver_instances if x == d)}
               for d in dark_driver_ids]

art = {
    "generated": "2026-08-19",
    "graph_version": G.version,
    "loader": "leviathan.graphrag.graph.CausalGraph.load() (the serving loader)",
    "walk_model": {
        "source": "src/leviathan/graphrag/planner.py::grounded_subgraph",
        "expansion_contract": "tracked cross_links (driver_commodity in loaded contract ids, RAW STRING EQUALITY) + EVERY driver of the contract",
        "expansion_driver": "Driver.parents (same contract only)",
        "downstream": "graph.rev_cross_links (node-keyed, alias-resolved) offered ONCE at end-of-walk, fan-out fenced (no expansion)",
        "shipped_defaults": {"depth": pl._DEPTH, "tau": pl._TAU, "node_budget": pl._NODE_BUDGET,
                             "max_seeds": pl._MAX_SEEDS, "closure_reserve": pl._CLOSURE_RESERVE},
    },
    "totals": {
        "contracts_loaded": len(CONTRACTS),
        "contracts_in_hierarchy": len(HIER_ANCHORS),
        "base_yaml_contracts": BASE_YAMLS,
        "commodity_nodes": len(ALL_NODES), "commodity_nodes_list": ALL_NODES,
        "driver_instances": len(driver_instances),
        "distinct_driver_ids": len(distinct_driver_ids),
        "distinct_driver_ids_display": len(all_dag_ids),
        "parent_edges": len(parent_edges),
        "driver_to_target_edges": drv_target_edges,
        "inter_commodity_edges": len(inter_edges),
        "inter_commodity_tracked_forward": len(inter_tracked),
        "inter_commodity_untracked_forward": len(inter_untracked),
        "convergence_signals": len(convergence_signals),
        "total_edges": drv_target_edges + len(parent_edges) + len(inter_edges),
        "resolved_node_level_edges": len(resolved_node_edges),
        "reciprocal_node_pairs": len(reciprocal),
        "one_way_node_edges": len(one_way),
        "driver_slices_configured": len(specs),
        "backed_dag_ids": len(backed),
    },
    "reverse_index_buckets": rev_buckets,
    "serving_reality": {
        "serving_presets": serving_names,
        "modes": modes_tbl,
        "serving_presets_with_downstream_cascade": serving_cascade_on,
        "downstream_leg_live_in_serving": bool(serving_cascade_on),
        "note": ("cascade_contract_slots is the ONLY seam that admits a downstream (rev_cross_links) "
                 "market; it is None on quick/standard/deep, so the doctrine's downstream direction "
                 "is structurally OFF in production. deep_cc1 / max_cc1 carry it and are both DARK."),
        "per_anchor_pool": serving_pool,
    },
    "path_length_distribution": {"aggregate_over_33_anchors": {str(k): v for k, v in sorted(agg_depth.items())}},
    "inter_commodity_target_histograms": {
        "tracked_forward": [{"target": k, "n": v} for k, v in tracked_hist.most_common()],
        "untracked_forward": [{"target": k, "n": v} for k, v in untracked_hist.most_common()],
        "tracked_edges_landing_on_base_yaml": base_landing,
        "tracked_edges_total": len(inter_tracked),
    },
    "walkability": walkability,
    "gaps": {
        "orphan_driver_instances": orphan_driver_instances,
        "orphan_contract_nodes": orphan_contract_nodes,
        "cross_market_isolated_contracts": cross_market_isolated,
        "contracts_no_inbound_forward_edge": isolated_forward,
        "contracts_no_outbound_forward_edge": no_forward_out,
        "contracts_no_reverse_edge": no_reverse,
        "dark_driver_ids_unwaived": dark_unwaived,
        "dark_driver_ids_waived": dark_waived,
        "dark_driver_ids_detail": dark_detail,
        "n_dark_driver_instances": len(dark_driver_instances),
        "orphan_slices_no_dag_id": orphan_slices,
        "edges_referencing_undefined_nodes": undefined_edge_rows,
        "undefined_endpoint_names": [{"name": k, "n_edges": v} for k, v in undefined_names],
        "commodity_nodes_without_dag": nodes_no_dag,
        "group_complex_members_without_dag": group_members_no_dag,
        "context_commodities_without_dag": context_no_dag,
        "forward_walk_untraversable_edges": forward_lost,
        "forward_walk_untraversable_recoverable": forward_lost_recoverable,
        "convergence_signals_with_dark_drivers": conv_dark,
        "convergence_signals_unsatisfiable_from_text": conv_unsatisfiable,
        "s3": {"error": s3_err, "node_slices_on_s3": len(s3_nodes),
               "driver_slices_on_s3": len(s3_driver_slices),
               "nodes_without_evidence_file": nodes_no_evidence_file,
               "evidence_files_without_node": evidence_files_no_node,
               "configured_slices_without_file": slices_no_file,
               "slice_files_without_config": files_no_slice},
    },
    "complexes": {"complexes": complexes_rpt, "groups": groups_rpt,
                  "reciprocal_node_pairs": [list(p) for p in reciprocal],
                  "one_way_node_edges": one_way,
                  "chains_len3": chains, "chains_len4": chains4[:200],
                  "n_chains_len3": len(chains), "n_chains_len4": len(chains4)},
    "missing_edge_candidates": cands,
    "node_level_edges": sorted([list(e) for e in resolved_node_edges]),
    "engine_forward_node_edges": sorted([list(e) for e in tracked_node_edges]),
}

(OUT / "graph_walk.json").write_text(json.dumps(art, indent=1, sort_keys=False), encoding="utf-8")
print("wrote", OUT / "graph_walk.json")
print(json.dumps(art["totals"], indent=1))
print("rev buckets", rev_buckets)
print("orphan drivers", len(orphan_driver_instances), "orphan contracts", orphan_contract_nodes)
print("dark unwaived", len(dark_unwaived), "orphan slices", len(orphan_slices))
print("undefined names", undefined_names)
print("chains3", len(chains), "chains4", len(chains4))
print("cands top10", [(c["a"], c["b"], c["score"]) for c in cands[:10]])
print("s3", s3_err, len(s3_nodes), len(s3_driver_slices))
