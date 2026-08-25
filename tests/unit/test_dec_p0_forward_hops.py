"""D-EC-P0 #68 (2026-08-19) -- THE FORWARD HOP TARGET: `cross_links` resolves the same way the reverse
index does.

THE DEFECT, as data/dec_p0/graph_walk.{md,json} measured it on this estate:

  (a) `cross_links.tracked` was `e.driver_commodity in self.contracts` -- RAW STRING EQUALITY -- so only 52
      of 117 inter-commodity edges were traversable by the FORWARD walk, the direction every serving preset
      runs. 42 of the 65 lost edges resolve to a node with a loaded contract and were ALREADY resolved on
      the reverse side (`rev_cross_links`). Those 42 are the vegoil/meal crush complex almost exactly, so
      the flagship PALM -> SBO -> SBM chain was walkable ONLY downstream -- through the leg with no serving
      home (`cascade_contract_slots` is None on quick/standard/deep).
  (b) 34 of the 52 survivors landed on `corn` / `soybeans`, the two BASE YAMLS this module's own fence
      classifies as non-tradeable duplicates. Two thirds of the surviving cross-market layer was a hop into
      a market no desk can trade.

THE FIX IS ONE RESOLUTION, NOT A SECOND ONE: `_invert_inter_commodity` now records `forward_target` beside
the reverse `seed` -- same two-step node resolution, same lexicographic-first tie-break -- and a declared id
that is itself a loaded, TRADEABLE contract is its own target, so an edge that names the market it means
keeps it and a synthetic graph the hierarchy knows nothing about is untouched.

THE FOUR PROPERTIES THIS FILE PINS (the ratified acceptance, `data/dec_p0/fix68_verify.md`):
  1. NO ANCHOR LOSES A COMMODITY NODE. Per-anchor reachability, all 33 anchors, is a superset at
     commodity-node granularity; every raw key it does drop is keyed to a base yaml, i.e. exactly what
     property 2 mandates dropping. (A literal key-level superset is UNSATISFIABLE alongside property 2 --
     the base yaml's driver keys carry its contract id -- so the two are pinned as the decomposition they
     actually are, not as a claim that cannot hold.)
  2. ZERO forward edges land on `corn` / `soybeans`.
  3. The 23 edges naming no node at all (`wheat`, `sorghum`, `sunflower_oil`, `barley`, `ethanol` -- group
     keys, not nodes) stay UNTRACKED. Resolving those is edge-AUTHORING work (P4), never resolution work.
  4. `graph_version` is a hash of the causal YAML BYTES -- a code change may not move it.

Pure/offline: config reads only, no network, no spend.
"""
from __future__ import annotations

import json
import pathlib

import pytest
from leviathan.causal import schema as cs
from leviathan.graphrag import graph as g

_CENSUS_PATH = pathlib.Path(__file__).resolve().parents[2] / "data" / "dec_p0" / "graph_walk.json"
_BASE_YAMLS = ("corn", "soybeans")
# ⚠ RE-CUT DISCHARGED at the D-EC graph-completion wave's INTEGRATION PASS (2026-08-21), re-derived once
# from the reconciled tree per the owed-block's own procedure. WHAT MOVED IT, in three acts:
#   * LANE C: +15 adjudicated edges, 3 class DAGs (33 yamls -> 36) -- `barley`, `sorghum` and
#     `sunflower_oil` STOP being no-node names because each now has a real causal contract, and `hfcs`,
#     `ddgs`, `fresh_citrus`, `palm_kernel` arrive as D15 context-commodity endpoints of the new edges.
#   * THE INTEGRATION graph fix: `_invert_inter_commodity` now admits loaded causal contracts as nodes in
#     BOTH directions (it was hierarchy-only in reverse, which split tracked/resolved 114 vs 103), so the
#     class DAGs resolve forward AND reverse and tracked == resolved again.
#   * THE FOUR-TIER RE-ADJUDICATION (owner doctrine, frequency floors overturned for named mechanisms):
#     +14 more edges -- cottonseed/peanut/rice on cotton, the rapeseed crush pair, the RD feedstock pair
#     (tallow, used_cooking_oil), hfcs on both sugar boards, the wheat-class reciprocals, sunoil~soyoil --
#     which adds `cottonseed`, `peanut`, `tallow`, `used_cooking_oil` as edge-reached-only context names
#     (`rice`, `rapeseed_oil`, `rapeseed_meal` RESOLVE: rough_rice_cbot and the ZCE boards serve them).
# Every name below is a D15 context commodity or complex key WITHOUT a DAG -- edge-reached-only BY DESIGN.
# The census artifact data/dec_p0/graph_walk.json stays frozen PRE evidence, never re-pinned; the census
# terms in the assertions below are therefore DECOUPLED from the live terms (same shape as the
# graph_version inequality), each pinning the artifact's own PRE number.
_NO_NODE_NAMES = {"wheat", "ethanol", "hfcs", "ddgs", "fresh_citrus", "palm_kernel",
                  "cottonseed", "peanut", "tallow", "used_cooking_oil"}


@pytest.fixture(scope="module")
def real() -> g.CausalGraph:
    return g.CausalGraph.load()


@pytest.fixture(scope="module")
def census() -> dict:
    """THE P0 ARTIFACT. Absent -> SKIP, never a silent pass: a pin that stopped checking its number is
    the same class of green as no pin at all."""
    if not _CENSUS_PATH.exists():
        pytest.skip("D-EC-P0 census artifact absent")
    return json.loads(_CENSUS_PATH.read_text(encoding="utf-8"))


# ── the walk, replicated structurally (tau=0, budget=inf) ────────────────────────────────────────────
def _legacy_hops(gr, cid):
    """The PRE-fix forward hop set: raw string equality against loaded contract ids."""
    return [e.driver_commodity for e in gr.contracts[cid].inter_commodity
            if e.driver_commodity in gr.contracts]


def _engine_hops(gr, cid):
    """The SHIPPED forward hop set, read off `cross_links` exactly as `planner.grounded_subgraph` does."""
    return [e["target_contract"] for e in gr.cross_links(cid) if e["tracked"]]


def _reach(gr, anchor, hops) -> set:
    """(kind, contract, id) keys reachable from `anchor` at the STRUCTURAL ceiling -- contract expands to
    its tracked hops + every driver, driver expands to its `.parents` (same contract). This is
    `planner.grounded_subgraph` with tau=0 and node_budget=inf; data/dec_p0/graph_walk.md S0 states the
    same model, and the harness that wrote fix68_verify.json reproduces the census row for row."""
    seen: set = set()
    wave = [(anchor, 0, "contract", anchor)]
    while wave:
        nxt = []
        for id_, d, kind, cid in wave:
            key = (kind, cid, id_)
            if key in seen:
                continue
            seen.add(key)
            if kind == "contract":
                nxt.extend((t, d + 1, "contract", t) for t in hops(gr, cid))
                nxt.extend((drv.id, d + 1, "driver", cid) for drv in gr.contracts[cid].drivers)
            else:
                nxt.extend((p, d + 1, "driver", cid) for p in gr.driver(cid, id_).parents)
        wave = nxt
    return seen


# ── 1. reachability: additive at node granularity, and every drop is a base yaml ─────────────────────
def test_no_anchor_loses_a_reachable_commodity_node(real):
    """PROPERTY 1, all 33 anchors. The fix may only ever ADD reach: the set of commodity NODES an anchor
    can walk to is a superset of what raw string equality reached. Node granularity is the honest
    identity here -- `corn` (base yaml) and `campinas_corn_reference_bmf` are the same commodity node, and
    the walk's own seed de-dup (`planner._seed_contracts`) has always treated the NODE as the identity."""
    for a in sorted(real.contracts):
        old = {real.contract_node(k[1]) for k in _reach(real, a, _legacy_hops) if k[0] == "contract"}
        new = {real.contract_node(k[1]) for k in _reach(real, a, _engine_hops) if k[0] == "contract"}
        assert old <= new, (a, sorted(old - new))


def test_every_dropped_walk_key_is_a_base_yaml_key(real):
    """PROPERTY 1, the DECOMPOSITION -- and the honest statement of what property 2 costs. A raw-key
    superset cannot coexist with 'zero base-yaml targets' (a base yaml's driver keys carry ITS contract
    id), so what is pinned is the exact shape of the difference: nothing is lost but the phantom markets
    and their drivers, on every anchor."""
    dropped_contracts = set()
    for a in sorted(real.contracts):
        lost = _reach(real, a, _legacy_hops) - _reach(real, a, _engine_hops)
        assert all(k[1] in _BASE_YAMLS for k in lost), (a, sorted(k for k in lost if k[1] not in _BASE_YAMLS))
        dropped_contracts |= {k[1] for k in lost}
    assert dropped_contracts == set(_BASE_YAMLS), "non-vacuity: the phantom hop really was being walked"


def test_the_42_recoverable_edges_are_recovered_and_the_crush_complex_walks_forward(real):
    """THE PRODUCT FACT the census led with. The vegoil/meal complex is the bulk of the 42, and the
    flagship chain must now be walkable in the direction production actually runs."""
    def _targets(cid):
        return {t for t in _engine_hops(real, cid)}
    assert "soybean_oil_cbot" in _targets("malaysian_crude_palm_oil_cme"), "PALM -> SBO"
    assert "soybean_meal_cbot" in _targets("soybean_oil_cbot"), "SBO -> SBM"
    assert {real.contract_node(t) for t in _targets("soybean_oil_cbot")} >= \
        {"corn", "palm_oil", "rapeseed_oil", "soybean_meal", "soybeans"}, \
        "soybean_oil's node-level neighbourhood, which the string test cut to {corn, soybeans}"


# ── 2. the base-yaml fence, now applied FORWARD as well as in reverse ────────────────────────────────
def test_no_forward_edge_lands_on_a_base_yaml_contract(real):
    """PROPERTY 2. `corn` and `soybeans` are loaded contracts absent from commodity_hierarchy whose node a
    hierarchy contract already serves -- the same relative fence `rev_cross_links` applies to the paid
    slot. Before the fix 34 of 52 traversable forward edges pointed at them."""
    landings = [(cid, e["target_contract"]) for cid in real.contracts
                for e in real.cross_links(cid) if e["tracked"]]
    assert [x for x in landings if x[1] in _BASE_YAMLS] == []
    # ...and the 34 edges are not lost, they are RE-AIMED at a tradeable contract of the same node --
    # since the #68 AMENDMENT (owner word 2026-08-19) that contract is the DECLARED canonical twin
    # (_CANONICAL_SEED), so bare `corn` lands on corn_cbot, not the lexicographic accident campinas.
    rows = [r for r in real.rev_cross_link_resolution() if r["driver_commodity"] in _BASE_YAMLS]
    assert len(rows) == 34
    assert {r["forward_target"] for r in rows} == {"corn_cbot", "soybeans_cbot"}
    for r in rows:
        assert real.contract_node(r["forward_target"]) == r["driver_commodity"]


def test_a_declared_contract_id_is_its_own_target(real):
    """THE PRECEDENCE RULE, pinned as behaviour. An edge that names a loaded TRADEABLE contract means that
    market: `corn_cbot` may not be re-aimed at its node's lexicographic-first sibling, or the fix would
    silently move 5 edges that were already correct (4 corn_cbot + 1 soybeans_no_2_dce)."""
    named = {r["driver_commodity"]: r for r in real.rev_cross_link_resolution()
             if r["driver_commodity"] in real.contracts and r["driver_commodity"] not in _BASE_YAMLS}
    assert "corn_cbot" in named and "soybeans_no_2_dce" in named, "non-vacuity"
    for dc, r in named.items():
        assert r["forward_target"] == dc, dc


# ── 3. unresolvable-by-construction stays unresolvable ───────────────────────────────────────────────
def test_the_23_no_node_edges_stay_untracked(real, census):
    """PROPERTY 3. `wheat` is a COMPLEX KEY with no DAG, not a node. Resolving these by picking a class
    (complex_map's curated table does exactly that, for a different purpose) would invent an edge the
    curator never authored. RE-CUT 2026-08-21 (integration): 23 -> 24 rows over the 10 context names in
    _NO_NODE_NAMES -- the wave resolved barley/sorghum/sunflower_oil (class DAGs) and rice/rapeseed_oil/
    rapeseed_meal (served by rough_rice_cbot and the ZCE boards), while the four-tier edges added new
    context endpoints. The census term is DECOUPLED: the artifact records the PRE graph's 23."""
    untracked = [(cid, e["driver_commodity"]) for cid in real.contracts
                 for e in real.cross_links(cid) if not e["tracked"]]
    assert len(untracked) == 24
    assert census["reverse_index_buckets"]["unresolvable-no-node"] == 23, "the PRE number, from the artifact"
    assert {dc for _c, dc in untracked} == _NO_NODE_NAMES
    assert all(e["target_contract"] is None for cid in real.contracts
               for e in real.cross_links(cid) if not e["tracked"])


# ── 4. the totals, against the census artifact ───────────────────────────────────────────────────────
def test_the_forward_count_is_the_reverse_indexs_own_resolved_count(real, census):
    """THE HEADLINE NUMBER. 52 -> 94 (fix #68), then 94 -> 122 (graph-completion wave: lane C's 15 edges +
    the four-tier 14 + the class DAGs + the both-directions node fix). 122 is not a new number: it is
    `resolved`, what the reverse index has answered since D-MW-27. ONE map, read twice, agreeing -- and the
    integration fix is what made it agree again after the class DAGs split it 114 vs 103. The census terms
    are DECOUPLED: the artifact records the PRE graph (117 edges, 52 tracked forward)."""
    tracked = sum(1 for cid in real.contracts for e in real.cross_links(cid) if e["tracked"])
    b = real.rev_cross_link_buckets()
    assert tracked == b["resolved"] == 122
    assert tracked + 24 == b["edges"] == 146
    assert census["totals"]["inter_commodity_edges"] == 117, "the PRE number, from the artifact"
    assert census["totals"]["inter_commodity_tracked_forward"] == 52, "the PRE number, from the artifact"


def test_graph_version_hashes_the_configs_not_the_code(real, census):
    """PROPERTY 4, verified rather than asserted in prose: `causal_graph_version` reads YAML BYTES, so a
    resolution change cannot move a stamped answer's graph identity. Re-derived here from the files.

    RE-CUT TWICE on 2026-08-20 for D-EC XC-2/XC-5, and each re-cut is the property working, not the property
    lapsing. Both were CONFIG edits, so the hash MUST move, and the pin is what proves it did:

      482c0e2554e6 -> bfbae71b43b8   the ENSO merge: 110 driver-id reference lines across 18 of the 33 DAGs
                                     (`El_Niño`->`El_Nino` on 15, `La_Niña`->`La_Nina` on 14,
                                     `china_state_reserves`->`China_state_reserves` on 3)
      bfbae71b43b8 -> 7030c21badfc   the XC-5 tail: 6 lines across 2 DAGs (`cny_fx`->`CNY_FX` on
                                     rapeseed_meal_zce, `US_export_pace`->`us_export_pace` on cotton)

    The second move is worth its own line because it is BYTE-NEUTRAL -- both renames are case-only, so the
    33 files weigh exactly what they weighed before and only the hash can tell you anything happened. That
    is the whole argument for hashing bytes rather than counting them.

    The census artifact is NOT re-pinned to the new value and must not be: `data/dec_p0/graph_walk.json` is
    frozen evidence of the PRE-merge graph (it is what fix #68's 52 -> 94 was measured against), and a
    measurement file edited to agree with the code it measures has stopped being evidence. The inequality is
    asserted instead, which pins strictly MORE than the old chained equality did: a code-only change still
    cannot move `real.version` (that is the third assert), and the artifact still records the graph it was
    taken on."""
    import hashlib
    paths = sorted(g._CAUSAL_DIR.glob("*.yaml"), key=str)
    h = hashlib.sha256()
    for p in paths:
        h.update(p.name.encode())
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    # RE-CUT 2026-08-21 (integration pass), the third line of the chain:
    #   7030c21badfc -> c9d10c662810   the D-EC graph-completion wave, reconciled: 31 incumbent DAGs edited
    #                                  + 3 class DAGs authored (33 -> 36 yamls), lane C's 15 adjudicated
    #                                  edges + the four-tier re-adjudication's 14, the XC-6 parent edges,
    #                                  the policy/FX/livestock nodes, and every written refusal block.
    #   c9d10c662810 -> f6cf1f5db711   the census fallout re-cut, same evening: sorghum's drought /
    #                                  heat_stress / export_pace flipped available -> planned (the class
    #                                  DAG copied incumbents' refs, but availability is PER-COMMODITY --
    #                                  gold_weather_z and silver_esr carry no sorghum axis; the first
    #                                  post-wave cascade census read all three legs dark).
    #   f6cf1f5db711 -> fe7cd796e02f   the GN-1 MPOB split (owner word 2026-08-22): mpob_fundamentals ->
    #                                  mpob_ending_stocks + mpob_production on the palm board, the
    #                                  basket-ref split the register's un-defer gate demanded.
    #   fe7cd796e02f -> ddbbc7022b77   the projection wave's Lane 0 + Lane 1 config batch (2026-08-25):
    #                                  W0-7's global_token: skip on two cascade rows + the sorghum
    #                                  export_pace un-plan (planned -> available, the esr_exports
    #                                  commodity_aliases re-key) + FX-4's ten currency keys + the D-3
    #                                  United Kingdom row + FX-6's Argentina key deletion + FX-5's three
    #                                  DAG token re-keys (matif EUR legs Global/EU;Global -> EU, cocoa
    #                                  GBP_cross Global -> United Kingdom).
    assert real.version == h.hexdigest()[:12] == "ddbbc7022b77"     # POST-projection-Lane-0/1, re-derived from bytes
    assert census["graph_version"] == "482c0e2554e6"                # the frozen PRE-XC-2 artifact, untouched
    assert real.version != census["graph_version"], \
        "a CONFIG edit must move the hash -- that is what 'hashes the configs, not the code' means"


# ── the synthetic-graph no-op (the property the relative fence was written for) ──────────────────────
def _syn(*, declares_bare: bool) -> g.CausalGraph:
    """A hermetic two-contract graph on ids the real hierarchy has never heard of."""
    def _c(cid, dc=None):
        inter = [cs.InterCommodityEdge(driver_commodity=dc, relation="substitutes_for", sign="-")] if dc else []
        return cs.CausalContract(contract=cid, drivers=[cs.Driver(id=f"{cid}_d", type="hazard", sign="+",
                                                                  mechanism="m")], inter_commodity=inter)
    tgt = "some_bare_name" if declares_bare else "zz_other"
    return g.CausalGraph({"zz_seed": _c("zz_seed", tgt), "zz_other": _c("zz_other")}, silver=set())


def test_a_synthetic_graph_the_hierarchy_never_heard_of_is_untouched():
    """THE NO-OP PROPERTY, the reason the fence is defined RELATIVELY. Every hermetic walk fixture in the
    suite declares real-looking ids on invented drivers; if the resolution could re-aim or drop a hop on a
    graph with no hierarchy behind it, every one of those fixtures would be measuring a different walk."""
    e = _syn(declares_bare=False).cross_links("zz_seed")[0]
    assert (e["tracked"], e["target_contract"]) == (True, "zz_other"), "a loaded id is its own target"
    e2 = _syn(declares_bare=True).cross_links("zz_seed")[0]
    assert (e2["tracked"], e2["target_contract"]) == (False, None), "an unknown name resolves to nothing"


def test_cross_links_still_raises_on_an_unknown_contract(real):
    """UNCHANGED CONTRACT: `cross_links` is a contract lookup and may KeyError; `rev_cross_links` is the
    index read on the hot path that must never raise. The fix moves neither."""
    with pytest.raises(KeyError):
        real.cross_links("not_a_contract_at_all")
    assert real.rev_cross_links("not_a_contract_at_all") == []
