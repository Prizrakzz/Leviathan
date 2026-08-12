"""D-MW P6 (2026-08-12) -- CROSS-MARKET CASCADE: the reverse index (D-MW-27) + the paid slot (D-MW-28).

THE DIRECTION, stated once so no pin below has to re-derive it: a contract's YAML declares who DRIVES it
(palm_olein_dce lists `rapeseed_oil`: "rapeseed tightness raises palm olein demand"). INVERTING that map
answers the doctrine's missing direction -- for a seed S, WHICH MARKETS S'S SITUATION CASCADES INTO. The
forward map is `graph.cross_links`; `graph.rev_cross_links` is its transpose.

What this file pins, and the measurement or review catch that forced each one:

  THE ALIAS RULE (D-MW-27)   65 of 117 inter_commodity edges name a `driver_commodity` that is NOT a
                             contract id, so a NAIVE inversion covers 52 edges and leaves 20/33 contracts
                             with zero pairs. The RATIFIED rule is two-step -- node_for() first (so a
                             CONTRACT-ID-valued string lands on its node), then the inverted _hier() map,
                             then LEXICOGRAPHIC-FIRST -- and it is pinned here against the STEP-0 census
                             artifact row for row, not against a remembered number.
  THREE BUCKETS              resolved / unresolvable-no-node / unresolvable-no-contract, reported
                             SEPARATELY: 'wheat' names no node at all and is unresolvable BY
                             CONSTRUCTION, which is a different fact from a shortfall.
  INVERSION PARITY           the transpose must be a transpose: every index row is exactly one forward
                             edge and every eligible forward edge is exactly one index row.
  THE BASE-YAML FENCE        `corn` and `soybeans` are base yamls, not tradeable markets, and they
                             byte-duplicate their _cbot variants' declarations -- without the fence the
                             PAID slot can buy a phantom contract block.
  THE PAID SLOT (D-MW-28)    a THIRD admission source, `_cascade_plan`, scored by cos(query, the EDGE
                             MECHANISM) on the walk's own cache, eligibility = backed + slice-distinct,
                             the full audit trail, and cross-market convergence.
  END-OF-WALK, NOT WAVE 0    ROUND-1 BLOCKER (three findings, one redesign). The first cut ran the slot as
                             a wave-0 frontier and was SUBTRACTIVE on reciprocal pairs: a foreign the
                             forward walk reaches ANYWAY (arabica<->robusta, raw<->white sugar, 2 of the 6
                             frozen deck rows) was bought at wave 0, stamped with the cascade reason, and
                             the leaf fence then deleted its whole 31-node driver fan-in. It also read
                             slice-distinctness against wave 0 only, and never stamped `visited`, so a
                             later wave OVERWROTE the kept node's via_edge with the forward edge's. The
                             slot is now offered ONCE, after the last wave, against the FINAL kept set:
                             the ON arm's kept set is a SUPERSET of the OFF arm's BY CONSTRUCTION.
  THE CEILING, HONESTLY      every kept node counts, so the slots are NOT free: the walk ceiling becomes
                             `node_budget + cascade_contract_slots`, and pin 3 re-pinned to it in the
                             same commit (test_dgd_closure_reservation).
  THE FAN-OUT FENCE          STRUCTURAL, and scoped to what the SLOT bought: a node admitted after the
                             last wave has no wave to expand into. Measured fan-out is 30-134 nodes per
                             contract and `is_hop` precedence sorts them ahead of every driver -- one slot
                             would otherwise buy a WAVE, unbudgeted. A foreign the walk reaches on its own
                             is NEVER converted to a leaf.
  KNOB, NOT ENV              a process-global env re-opens the exact defect that forced the reserve into
                             the mode table: every quick/standard turn would pay a ~2.8k-token block. The
                             eight ledger keys likewise stamp only when the knob is present, so a shipped
                             preset's artifact shape is byte-identical to its pre-P6 self.

Pure/offline: injected embed, injected retrieve, no S3, no pg, no LLM, no spend. The graph pins read the
real curated YAMLs + commodity_hierarchy (config reads, no network).
"""
from __future__ import annotations

import json
import math
import pathlib

import pytest
from leviathan.causal import schema as cs
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import graph as g
from leviathan.graphrag import planner as pl
from leviathan.graphrag import reasoning_modes as rm

_CENSUS_PATH = pathlib.Path(__file__).resolve().parents[2] / "data" / "dmw_p6_census.json"


@pytest.fixture(scope="module")
def census() -> dict:
    """THE STEP-0 ARTIFACT (data/dmw_p6_census.json), the authority these pins answer to. If it is absent
    the census pins SKIP rather than pass -- a green suite that silently stopped checking the number is
    the C2/U3 class."""
    if not _CENSUS_PATH.exists():
        pytest.skip("STEP-0 census artifact absent")
    return json.loads(_CENSUS_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def real() -> g.CausalGraph:
    return g.CausalGraph.load()


# ══ D-MW-27: THE REVERSE INDEX ═══════════════════════════════════════════════════════════════════════════
def test_the_three_buckets_match_the_step0_census(real, census):
    """THE HEADLINE PIN. The buckets are reported DECOMPOSED so a deck-shrink decision reads three numbers,
    and they are checked against the artifact the deck was authored from -- not against prose."""
    b = real.rev_cross_link_buckets()
    t = census["totals"]
    assert b["edges"] == t["inter_commodity_edges"] == 117
    assert b["resolved"] == t["resolved"] == 94
    assert b["unresolvable-no-node"] == t["unresolvable_no_node"] == 23
    assert b["unresolvable-no-contract"] == t["unresolvable_no_contract"] == 0
    assert b["resolved"] + b["unresolvable-no-node"] + b["unresolvable-no-contract"] == b["edges"]
    assert b["seeds_with_pairs"] == census["summary"]["n_seeds_with_pairs"] == 15


def test_the_resolution_table_reproduces_the_census_row_for_row(real, census):
    """The table is the AUDIT surface: bucket, resolved node, candidate set, tie-break, per edge. A
    resolution nobody can re-read is a resolution nobody can revisit -- so it is pinned whole, not
    sampled."""
    mine = {(r["declaring_contract"], r["idx"]): r for r in real.rev_cross_link_resolution()}
    theirs = {(r["declaring_contract"], r["idx"]): r for r in census["resolution_table"]}
    assert set(mine) == set(theirs)
    for k, want in theirs.items():
        got = mine[k]
        assert got["bucket"] == want["bucket"], k
        assert got["seed"] == want["seed"], k
        assert got["tie_break"] == want["tie_break"], k
        assert got["node"] == want.get("node"), k
        assert got["candidates"] == want["candidates"], k
        assert got["driver_commodity"] == want["driver_commodity"], k


def test_the_alias_rule_is_the_ratified_TWO_STEP_reading(real):
    """THE ROUND-3 CATCH, pinned as behaviour. The plan's prose reads literally as a direct node lookup,
    which STRANDS the 13 edges whose driver_commodity names a CONTRACT ID that is not itself a node
    (corn_cbot x4, soft_red_winter_wheat_cbot x3, ...). The ratified rule resolves node_for() FIRST."""
    by_dc = {}
    for r in real.rev_cross_link_resolution():
        by_dc.setdefault(r["driver_commodity"], []).append(r)
    # (a) a CONTRACT-ID-valued string resolves through its node, then back out to the tracked set
    corn_cbot = by_dc["corn_cbot"][0]
    assert corn_cbot["bucket"] == "resolved" and corn_cbot["node"] == "corn"
    assert corn_cbot["seed"] == "campinas_corn_reference_bmf", "lexicographic-first over the corn set"
    assert corn_cbot["tie_break"] == "lexicographic-first"
    # (b) a NODE-valued multi-contract string: same rule, recorded tie-break
    soyoil = by_dc["soybean_oil"][0]
    assert soyoil["node"] == "soybean_oil" and soyoil["seed"] == "soybean_oil_cbot"
    assert soyoil["candidates"] == sorted(soyoil["candidates"]) and len(soyoil["candidates"]) > 1
    # (c) UNRESOLVABLE BY CONSTRUCTION -- there is no 'wheat' node, so all 10 wheat edges are no-node.
    #     This is the largest alias class and it is NOT a census shortfall.
    assert {r["bucket"] for r in by_dc["wheat"]} == {"unresolvable-no-node"}
    assert len(by_dc["wheat"]) == 10
    assert all(r["seed"] is None and r["node"] is None for r in by_dc["wheat"])
    no_node = {r["driver_commodity"] for r in real.rev_cross_link_resolution()
               if r["bucket"] == "unresolvable-no-node"}
    assert no_node == {"wheat", "sunflower_oil", "sorghum", "barley", "ethanol"}
    # (d) every tie-break is RECORDED, and only those two values exist
    assert {r["tie_break"] for r in real.rev_cross_link_resolution() if r["bucket"] == "resolved"} == \
        {"single-member", "lexicographic-first"}


def test_inversion_parity_against_the_forward_map(real):
    """A TRANSPOSE MUST BE A TRANSPOSE. Both directions: every index row is exactly one declared forward
    edge (same mechanism, same relation, same sign), and every RESOLVED + TRADEABLE forward edge appears
    exactly once in the index. A one-sided check would pass an index that silently dropped rows."""
    fwd = {}
    for cid in real.contracts:
        for i, e in enumerate(real.cross_links(cid)):
            fwd[(cid, i)] = e
    seen = set()
    for row in real.rev_cross_link_resolution():
        if not (row["bucket"] == "resolved" and row["foreign_tradeable"]):
            continue
        idx = real.rev_cross_links(row["seed"])
        hit = [r for r in idx if (r["contract"], r["idx"]) == (row["declaring_contract"], row["idx"])]
        assert len(hit) == 1, row
        e = fwd[(row["declaring_contract"], row["idx"])]
        assert hit[0]["mechanism"] == e["mechanism"] and hit[0]["relation"] == e["relation"]
        assert hit[0]["sign"] == e["sign"] and hit[0]["driver_commodity"] == e["driver_commodity"]
        seen.add((row["declaring_contract"], row["idx"]))
    total = sum(len(real.rev_cross_links(s)) for s in
                {r["seed"] for r in real.rev_cross_link_resolution() if r["seed"]})
    assert total == len(seen), "the index holds NOTHING the forward map does not declare"


def test_the_base_yaml_fence_keeps_a_paid_slot_off_a_phantom_market(real, census):
    """`corn` and `soybeans` are BASE yamls -- absent from commodity_hierarchy (no exchange, no origin) and
    byte-duplicates of their _cbot variants' declarations. They are loaded contracts, so without the fence
    they invert like any other market and the PAID slot buys a block no desk can trade."""
    fenced = [r for r in real.rev_cross_link_resolution()
              if r["bucket"] == "resolved" and not r["foreign_tradeable"]]
    assert {r["declaring_contract"] for r in fenced} == {"corn", "soybeans"}
    assert len(fenced) == real.rev_cross_link_buckets()["untradeable_foreign_edges"] == 7
    for seed, rows in ((r["seed"], real.rev_cross_links(r["seed"])) for r in fenced):
        assert all(x["contract"] not in ("corn", "soybeans") for x in rows), seed
    # AND THE FENCE COSTS NO SEED: the census's 15 seeds survive it (deck_eligible applies it too).
    assert real.rev_cross_link_buckets()["seeds_with_pairs"] == census["summary"]["n_seeds_with_pairs"]


def test_the_censuss_15_qualifying_pairs_are_all_reachable(real, census):
    """THE DECK'S SUBSTRATE. D-MW-29 authors its rows FROM the census; if any of those pairs were
    unreachable through the shipped index the deck would name a mechanism the product cannot produce
    (the 'hog-margin demand' class the plan caught in its own draft)."""
    for pair in census["deck_candidates_one_per_seed"]:
        seed, foreign = pair["seed"], pair["foreign"]
        rows = real.rev_cross_links(seed)
        hit = [r for r in rows if r["contract"] == foreign]
        assert hit, f"{seed} -> {foreign} unreachable"
        assert hit[0]["mechanism"] == pair["mechanism"]
        # eligibility, as the walk will judge it: distinct evidence slices (backed is structural)
        assert real.contract_node(seed) != real.contract_node(foreign) == pair["foreign_node"]


def test_contract_node_is_evidence_node_for_read_off_the_load_time_map(real):
    """ONE PRODUCER. `graph.contract_node` must be `evidence.node_for` -- it exists only so the walk does
    not re-parse the hierarchy YAML per candidate, never to become a second answer."""
    for cid in real.contracts:
        assert real.contract_node(cid) == ev.node_for(cid), cid
    assert real.contract_node("not_a_contract_at_all") == "not_a_contract_at_all"


def test_the_index_is_built_at_LOAD_time_and_the_lookup_reads_no_config(real, monkeypatch):
    """LOAD TIME, not query time: after construction the resolution is a dict read. Proved by BREAKING the
    hierarchy loader afterwards -- the lookup must be unaffected, which it can only be if nothing at query
    time consults it."""
    def _boom():
        raise AssertionError("rev_cross_links must not read the hierarchy at query time")
    monkeypatch.setattr(ev, "_hier", _boom)
    assert real.rev_cross_links("soybean_oil_cbot")
    assert real.rev_cross_link_buckets()["resolved"] == 94
    assert real.contract_node("soybean_oil_cbot") == "soybean_oil"


def test_rev_cross_links_never_raises_and_hands_out_copies(real):
    """`cross_links` may KeyError -- it is a contract lookup. This one is an INDEX read on the walk's hot
    path, so a routing surprise returns [] instead of killing a desk turn. And the rows are fresh dicts:
    a caller that mutates one must not corrupt the graph's own index (the same idiom cross_links uses)."""
    assert real.rev_cross_links("no_such_contract") == []
    assert real.rev_cross_links("wheat") == []               # a NODE, not a contract -> nothing to invert
    rows = real.rev_cross_links("soybean_oil_cbot")
    rows[0]["mechanism"] = "MUTATED"
    assert real.rev_cross_links("soybean_oil_cbot")[0]["mechanism"] != "MUTATED"


def test_the_import_direction_stays_clean():
    """graph <- evidence is the SANCTIONED direction (evidence does not import graph). The hierarchy read
    is a LAZY import inside the builder so `graph` stays importable by the light offline causal tooling
    without dragging the harvest chain in at module import."""
    import ast
    src = pathlib.Path(g.__file__).read_text(encoding="utf-8")
    top = [n for n in ast.parse(src).body if isinstance(n, (ast.Import, ast.ImportFrom))]
    mods = [getattr(n, "module", "") or "" for n in top if isinstance(n, ast.ImportFrom)]
    assert not any("evidence" in m for m in mods), "the evidence import stays lazy/in-function"
    ev_src = pathlib.Path(ev.__file__).read_text(encoding="utf-8")
    assert "graphrag import graph" not in ev_src, "evidence must never import graph -- the cycle"


# ══ D-MW-28: THE PAID SLOT ═══════════════════════════════════════════════════════════════════════════════
# The walk fixture uses REAL contract ids on synthetic drivers. That is deliberate: the alias rule, the
# hierarchy node map and the base-yaml fence are all CONFIG facts, and a fixture of invented ids would
# exercise none of them -- it would pin a mechanism that can never fire on the estate it ships to.
_QUERY = "QQ"
_REL: dict = {}

_SEED = "soybean_oil_cbot"          # node soybean_oil
_CO_NODE = "soybean_oil_dce"        # node soybean_oil -- SAME slice as the seed
_SEED2 = "canola_ice"               # node canola
_F_STRONG = "malaysian_crude_palm_oil_cme"   # node palm_oil
_F_WEAK = "rapeseed_oil_zce"                 # node rapeseed_oil
_F_BOTH = "palm_olein_dce"                   # node palm_olein -- declares BOTH seeds
_BASE_YAML = "soybeans"             # loaded, off-hierarchy, node soybeans (soybeans_cbot serves it too)


def _embed(texts):
    out = []
    for t in texts:
        r = 1.0 if t == _QUERY else float(_REL.get(t, 0.0))
        r = max(-1.0, min(1.0, r))
        out.append([r, math.sqrt(max(0.0, 1.0 - r * r))])
    return out


def _drv(id_, rel, **kw):
    mech = f"m::{id_}"
    _REL[mech] = rel
    return cs.Driver(id=id_, type=kw.pop("type", "hazard"), sign=kw.pop("sign", "+"), mechanism=mech, **kw)


def _mech(cid, dc):
    return f"x::{cid}::{dc}"


def _contract(cid, drivers, declares=()):
    """`declares` = the driver_commodity strings THIS contract names as its own drivers -- the forward
    edges the reverse index inverts."""
    return cs.CausalContract(
        contract=cid, aliases=[cid], drivers=drivers,
        inter_commodity=[cs.InterCommodityEdge(driver_commodity=d, relation="substitutes_for", sign="-",
                                               mechanism=_mech(cid, d)) for d in declares])


def _fixture(seed_drivers=None, extra=()):
    _REL[_mech(_F_STRONG, "soybean_oil")] = 0.90
    _REL[_mech(_F_WEAK, "soybean_oil")] = 0.50
    _REL[_mech(_CO_NODE, "soybean_oil")] = 0.95
    _REL[_mech(_BASE_YAML, "soybean_oil")] = 0.99
    _REL[_mech(_F_BOTH, "soybean_oil")] = 0.40
    _REL[_mech(_F_BOTH, "canola")] = 0.40
    cts = [
        _contract(_SEED, seed_drivers if seed_drivers is not None else [_drv("a1", 0.9), _drv("a2", 0.8)]),
        _contract(_SEED2, [_drv("c1", 0.7)]),
        _contract("soybeans_cbot", [_drv("s1", 0.7)]),          # makes `soybeans` a base-yaml DUPLICATE
        _contract(_F_STRONG, [_drv("f1", 0.7)], declares=["soybean_oil"]),
        _contract(_F_WEAK, [_drv("f2", 0.7)], declares=["soybean_oil"]),
        _contract(_CO_NODE, [_drv("f3", 0.7)], declares=["soybean_oil"]),
        _contract(_BASE_YAML, [_drv("f4", 0.7)], declares=["soybean_oil"]),
        _contract(_F_BOTH, [_drv("f5", 0.7)], declares=["soybean_oil", "canola"]),
    ]
    cts += list(extra)
    return g.CausalGraph({c.contract: c for c in cts}, silver=set())


def _walk(graph, seeds, **kw):
    kw.setdefault("depth", 1)
    kw.setdefault("tau", 0.35)
    kw.setdefault("node_budget", 32)
    kw.setdefault("max_seeds", 6)
    kw.setdefault("driver_slices", {d.id for c in graph.contracts.values() for d in c.drivers})
    return pl.grounded_subgraph(_QUERY, graph, embed=_embed, route_fn=lambda q, gr: list(seeds), **kw)


def _cc(sg):
    return sg.trace["cascade_closure"]


def _retrieve(query, slice_, *, k, asof=None, near=None):
    return [{"date": "2026-01-0%d" % (i + 1), "source": "SRC", "source_key": f"{slice_}#{i}",
             "text": f"{slice_} row {i}"} for i in range(k)]


def test_the_slot_admits_the_foreign_contract_the_QUERY_scores_highest():
    """QUERY-SCORED, like every other hop: cos(query, THE EDGE MECHANISM) off the walk's own `_relevance`
    cache -- no second embedder, no second scale. With one slot and two candidates the 0.90 edge wins and
    the 0.50 edge is simply not bought."""
    sg = _walk(_fixture(), [_SEED], cascade_contract_slots=1)
    cc = _cc(sg)
    assert [r["contract"] for r in cc["cascade_contracts"]] == [_F_STRONG]
    assert cc["cascade_contracts"][0]["relevance_q"] == pytest.approx(0.90, abs=1e-3)
    assert ("contract", _F_STRONG, _F_STRONG) in {n.key for n in sg.nodes}
    assert ("contract", _F_WEAK, _F_WEAK) not in {n.key for n in sg.nodes}
    node = next(n for n in sg.nodes if n.id == _F_STRONG)
    assert node.relevance == pytest.approx(0.90, abs=1e-3), "the REAL cosine, never a synthetic 1.0"
    assert node.depth == 1 and node.via_edge["_from"] == _SEED
    assert node.via_edge["mechanism"] == _mech(_F_STRONG, "soybean_oil")


# The cascade_closure key set at HEAD~ (pre-P6), enumerated rather than derived: a derived expectation
# would move WITH a regression. This is the shape every shipped preset's artifact must keep.
_PRE_P6_CC_KEYS = frozenset({
    "admissions", "budget", "census_population", "closed", "count_delta", "dedicated", "dedicated_used",
    "displaced", "enabled", "headroom_used", "kept", "n_convergence", "n_downstream", "n_seeds", "open",
    "open_edges", "open_edges_lost_with_displaced", "per_seed_budget", "per_seed_reserve", "reserve_n",
    "reserve_slots", "reserved", "skipped", "skipped_counts"})
_P6_CC_KEYS = frozenset({
    "cascade_contracts", "cascade_enabled", "cascade_contract_slots", "cascade_slots", "cascade_skipped",
    "cascade_skipped_counts", "n_cascade_contract", "n_convergence_cross"})


@pytest.mark.parametrize("slots", [None, 0])
def test_off_is_the_pre_p6_walk(slots):
    """None == 0 == OFF for the WALK, and OFF is what every serving preset carries: nothing is bought and
    the kept set is the pre-P6 one, byte for byte."""
    base = _walk(_fixture(), [_SEED])
    off = _walk(_fixture(), [_SEED], cascade_contract_slots=slots)
    assert {n.key for n in off.nodes} == {n.key for n in base.nodes}
    assert off.trace["pruned"] == base.trace["pruned"]
    assert all(n.admission["reason"] != pl.REASON_DOWNSTREAM_CONTRACT for n in off.nodes)


def test_a_SHIPPED_preset_walk_stamps_the_PRE_P6_key_set_exactly():
    """THE ARTIFACT SHAPE OF A SHIPPED TURN DOES NOT MOVE (P6 round-1 minor). `cascade_closure` is
    whitelisted WHOLE into the per-answer record, so stamping the eight P6 keys unconditionally would put a
    new shape on every quick/standard/deep/max artifact -- a diff a downstream consumer reads as a
    regression, for a mechanism that arm did not run. The knob's ABSENCE (None, i.e. every serving preset)
    is what gates them, and 0 -- a P6 arm deliberately set OFF -- still stamps, because an unstamped arm is
    an uncomparable arm (the `open` counter's lesson)."""
    shipped = _cc(_walk(_fixture(), [_SEED]))                       # knob absent == every serving preset
    assert set(shipped) == _PRE_P6_CC_KEYS
    assert not (set(shipped) & _P6_CC_KEYS)
    zero = _cc(_walk(_fixture(), [_SEED], cascade_contract_slots=0))
    assert set(zero) == _PRE_P6_CC_KEYS | _P6_CC_KEYS                # 0 is a VALUE: the OFF arm of the A/B
    assert zero["cascade_enabled"] is False and zero["n_cascade_contract"] == 0
    assert zero["cascade_slots"] == {"total": 0, "filled": 0, "empty": 0}
    assert zero["cascade_contracts"] == [] and zero["n_convergence_cross"] == 0
    assert zero["cascade_skipped"] == [] and zero["cascade_skipped_counts"] == {}
    on = _cc(_walk(_fixture(), [_SEED], cascade_contract_slots=1))
    assert set(on) == _PRE_P6_CC_KEYS | _P6_CC_KEYS                  # ...and the ON arm's shape matches it


def test_the_ceiling_is_node_budget_plus_the_cascade_slots():
    """THE CEILING, STATED HONESTLY (the round-2 catch): every kept node counts against the budget, so
    'never from the 32 slots' is only true if the ceiling RISES. It does, by exactly the slot count -- and
    this fixture SATURATES the cosine budget, so the bound is exercised, not merely stated (the
    parametrized pin in test_dgd_closure_reservation carries the arithmetic at zero slots)."""
    budget = 6
    gr = _fixture(seed_drivers=[_drv(f"w{i}", 0.90 - i * 0.01) for i in range(20)])
    off = _walk(gr, [_SEED], node_budget=budget, cascade_contract_slots=0)
    on = _walk(gr, [_SEED], node_budget=budget, cascade_contract_slots=1)
    assert len(off.nodes) == budget, "fixture must SATURATE or the ceiling pin is vacuous"
    assert len(on.nodes) == budget + 1 <= budget + 1
    assert {n.key for n in off.nodes} < {n.key for n in on.nodes}, "additive: no cosine node is displaced"
    assert _cc(on)["count_delta"] == 0, "the reserve's own accounting identity is untouched"
    # and the COSINE budget itself never moved -- the slot came from its own pot
    assert sum(1 for n in on.nodes if n.admission["reason"] != pl.REASON_DOWNSTREAM_CONTRACT) == budget


def _reciprocal(strong_rel=0.95):
    """A RECIPROCAL PAIR, the shape the round-1 blocker was measured on: the seed declares the foreign as
    one of ITS drivers (so the forward walk reaches it as a tracked hop and expands it) AND the foreign
    declares the seed (so the reverse index offers it to the slot). arabica<->robusta and raw<->white sugar
    are exactly this on the real estate, and they are 2 of the 6 frozen D-MW-29 deck rows."""
    # the FORWARD edge names the CONTRACT ID (that is what makes `cross_links` flag it `tracked`, i.e. a
    # real hop the walk takes); the REVERSE edge names the node string the alias rule resolves.
    _REL[_mech(_SEED, _F_STRONG)] = strong_rel                   # the FORWARD edge: seed -> foreign
    _REL[_mech(_F_STRONG, "soybean_oil")] = 0.90                 # the REVERSE edge: the slot's candidate
    cts = [
        _contract(_SEED, [_drv("a1", 0.9)], declares=[_F_STRONG]),
        _contract(_F_STRONG, [_drv("f1", 0.7), _drv("f2", 0.7), _drv("f3", 0.7)],
                  declares=["soybean_oil"]),
    ]
    return g.CausalGraph({c.contract: c for c in cts}, silver=set())


def test_a_RECIPROCAL_pair_is_ADDITIVE_the_ON_arm_never_loses_a_node():
    """THE ROUND-1 BLOCKER, pinned as the law it broke. The wave-0 design bought the foreign the forward
    walk was about to reach anyway, stamped it `cascade_downstream_contract`, and the leaf fence then fired
    on the ordinary wave-1 re-entry too -- deleting the foreign's ENTIRE driver fan-in (measured: 31 nodes
    lost, 0 gained, on the arabica row at max knobs). The slot is now offered at END-OF-WALK against the
    FINAL kept set, so a foreign already in `kept` is skipped `already_admitted` and keeps expanding by the
    ordinary path.

    THE ASSERTION IS THE SUPERSET, not a count: whatever the slot does or does not buy, the ON arm may
    never hold FEWER nodes than the OFF arm."""
    gr = _reciprocal()
    off = _walk(gr, [_SEED], depth=2, cascade_contract_slots=0)
    on = _walk(gr, [_SEED], depth=2, cascade_contract_slots=1)
    off_keys, on_keys = {n.key for n in off.nodes}, {n.key for n in on.nodes}
    assert ("contract", _F_STRONG, _F_STRONG) in off_keys, "non-vacuity: the OFF arm reaches it FORWARD"
    assert {k for k in off_keys if k[0] == "driver" and k[1] == _F_STRONG}, \
        "non-vacuity: the OFF arm EXPANDS it (this is the fan-in the wave-0 design deleted)"
    assert off_keys <= on_keys, "ADDITIVE-OR-EQUAL: the paid slot may never subtract a node"
    # ...and the reason it is additive: the slot did not buy what the walk already holds
    cc = _cc(on)
    assert [r["contract"] for r in cc["cascade_contracts"]] == []
    assert {s["reason"] for s in cc["cascade_skipped"] if s["id"] == _F_STRONG} == {"already_admitted"}


def test_a_forward_reached_foreign_keeps_its_COSINE_admission_and_its_via_edge():
    """THE OVERWRITE HALF of the same blocker. A cascade key was never added to `visited`, so the wave-1
    forward arrival re-scored and re-stamped the kept node: the artifact's cascade record described a
    reverse edge while the NODE carried the forward one, and the mermaid + the answer's 'REACHED VIA
    CASCADE HOP' line rendered the wrong direction. Under end-of-walk there is one admission per key, and
    a forward-reached foreign is a plain cosine hop -- which is the truth about how it was reached."""
    gr = _reciprocal()
    on = _walk(gr, [_SEED], depth=2, cascade_contract_slots=1)
    node = next(n for n in on.nodes if n.key == ("contract", _F_STRONG, _F_STRONG))
    assert node.admission["reason"] == pl.REASON_COSINE
    assert node.via_edge["mechanism"] == _mech(_SEED, _F_STRONG), "the FORWARD edge it actually came by"
    assert node.relevance == pytest.approx(0.95, abs=1e-3)
    assert _cc(on)["admissions"]["contract:%s:%s" % (_F_STRONG, _F_STRONG)]["reason"] == pl.REASON_COSINE


def test_the_bought_node_is_stamped_visited_exactly_once():
    """No later pass can re-score or re-stamp what the slot bought: it enters `kept` AND `visited` at the
    end of the walk, once. `visited` is the walk's own decision ledger, and a key missing from it is the
    hole the overwrite came through."""
    sg = _walk(_fixture(), [_SEED], cascade_contract_slots=1)
    keys = [n.key for n in sg.nodes]
    assert len(keys) == len(set(keys))
    assert sg.trace["visited"] == len(set(keys)) + len(sg.trace["pruned"]), \
        "visited counts every DECIDED key -- kept (incl. the bought block) + pruned, each exactly once"


def test_the_fan_out_fence_makes_an_admitted_foreign_contract_a_LEAF():
    """THE ROUND-2 CATCH, pinned: an admitted foreign at d==1 would expand -- ALL its drivers and ALL its
    own cross_links into wave 2 (measured fan-out 30-134 per contract), and contract nodes sort AHEAD of
    every driver on `is_hop` precedence. The slot buys ONE block plus its own evidence, never a wave.
    Run at depth=2, where the expansion WOULD otherwise happen. The fence is scoped to what the SLOT
    bought: the reciprocal pin above is the other half, where the walk's own arrival must still expand."""
    onward = _contract("hard_red_winter_wheat_kcbt", [_drv("h1", 0.9)])
    strong = _contract(_F_STRONG, [_drv("f1", 0.95), _drv("f9", 0.95)], declares=["soybean_oil"])
    _REL[_mech(_F_STRONG, "soybean_oil")] = 0.90
    gr = g.CausalGraph({c.contract: c for c in (
        _contract(_SEED, [_drv("a1", 0.9)]), strong, onward,
        # the foreign ALSO declares a tracked hop of its own -- the second-order contract the fence stops
        _contract("x_holder", [_drv("z1", 0.5)]),
    )}, silver=set())
    # give the foreign an outgoing tracked cross_link by re-declaring it with one
    strong2 = cs.CausalContract(
        contract=_F_STRONG, aliases=[_F_STRONG], drivers=strong.drivers,
        inter_commodity=list(strong.inter_commodity) + [
            cs.InterCommodityEdge(driver_commodity="hard_red_winter_wheat_kcbt", relation="competes_with",
                                  sign="+", mechanism=_mech(_F_STRONG, "hrw"))])
    _REL[_mech(_F_STRONG, "hrw")] = 0.99
    gr = g.CausalGraph({**gr.contracts, _F_STRONG: strong2}, silver=set())
    sg = _walk(gr, [_SEED], depth=2, cascade_contract_slots=1,
               driver_slices={d.id for c in gr.contracts.values() for d in c.drivers})
    keys = {n.key for n in sg.nodes}
    assert ("contract", _F_STRONG, _F_STRONG) in keys, "the slot was spent (or this pin is vacuous)"
    assert not [k for k in keys if k[1] == _F_STRONG and k[0] == "driver"], "its DRIVERS never enter"
    assert ("contract", "hard_red_winter_wheat_kcbt", "hard_red_winter_wheat_kcbt") not in keys, \
        "its own cross_links never enter -- not even at 0.99, the strongest edge in the fixture"
    assert all(n.contract != "hard_red_winter_wheat_kcbt" for n in sg.nodes)


def test_eligibility_is_backed_and_SLICE_DISTINCT():
    """RULE 1, at contract granularity. A co-node foreign (soybean_oil_dce beside soybean_oil_cbot) reads
    the SAME evidence slice, so the cross-node dedup would zero it -- one slot in one buying a block that
    cannot be cited. It is skipped `same_slice` WITH the source recorded, and the slot goes to the next
    candidate instead of being burned."""
    sg = _walk(_fixture(), [_SEED], cascade_contract_slots=1)
    cc = _cc(sg)
    assert [r["contract"] for r in cc["cascade_contracts"]] == [_F_STRONG], \
        "the 0.95 co-node candidate outscores it and is STILL skipped"
    skips = cc["cascade_skipped"]
    assert all(s["source"] == pl.REASON_DOWNSTREAM_CONTRACT for s in skips)
    assert {s["id"] for s in skips if s["reason"] == "same_slice"} == {_CO_NODE}
    assert cc["cascade_skipped_counts"].get("same_slice", 0) == 1
    # SUPPLY vs SLOT, decomposed: the weaker candidates were eligible, the POT was spent
    assert cc["cascade_skipped_counts"].get("no_slot", 0) >= 1
    # ...and the P3 reserve's own column is NOT pooled with any of it
    assert cc["skipped_counts"] == {} and cc["skipped"] == []
    # the BASE YAML never even reaches eligibility -- the fence is upstream, in rev_cross_links
    assert _BASE_YAML not in {s["id"] for s in skips}
    assert all(r["contract"] != _BASE_YAML for r in cc["cascade_contracts"])


def test_an_unresolvable_foreign_node_is_skipped_unbacked_never_bought():
    """THE FAIL-CLOSED BRANCH, unit-tested at the seam: a foreign whose evidence node cannot be resolved
    is a block with no rows behind it. Unreachable through the shipped index (the hierarchy fence
    guarantees a node), which is exactly why it is pinned here rather than left as untested prose."""
    gr = _fixture()
    bought, skipped = pl._cascade_plan([_SEED], {}, gr, slots=2, node_of_contract=lambda c: None,
                                       score_text=lambda t: 0.5)
    assert bought == [], "an unresolvable node is never bought"
    assert {s["reason"] for s in skipped} == {"unbacked"} and len(skipped) >= 1
    assert all(s["source"] == pl.REASON_DOWNSTREAM_CONTRACT for s in skipped)


def test_no_slot_is_recorded_only_for_candidates_that_PASSED_every_eligibility_test():
    """THE SUPPLY-vs-SLOT DECOMPOSITION, restored (P6 round-1). The first cut recorded `no_slot` BEFORE the
    eligibility branches, so once the pot was spent every remaining candidate read `no_slot` whatever it
    was -- ~19 of 20 on a real corn-shaped seed -- and the column could no longer separate 'the pot was
    spent' from 'there was nothing to buy'. That is the same first-32-overall defect the P3 round-1 fix
    removed from the reserve's own column, reproduced in the new one. MIXED FIXTURE: one same-slice
    candidate, one bought, and two eligible-but-unfunded."""
    cc = _cc(_walk(_fixture(), [_SEED], cascade_contract_slots=1))
    counts = cc["cascade_skipped_counts"]
    assert [r["contract"] for r in cc["cascade_contracts"]] == [_F_STRONG]
    assert counts.get("same_slice") == 1, "the co-node candidate keeps ITS OWN reason, pot spent or not"
    assert {s["id"] for s in cc["cascade_skipped"] if s["reason"] == "same_slice"} == {_CO_NODE}
    assert counts.get("no_slot") == 2, "exactly the two ELIGIBLE candidates the pot could not fund"
    assert {s["id"] for s in cc["cascade_skipped"] if s["reason"] == "no_slot"} == {_F_WEAK, _F_BOTH}
    assert sum(counts.values()) == len(cc["cascade_skipped"]) == 3


def test_the_audit_trail_is_the_same_record_shape_as_every_structural_admission():
    """AUDITABILITY FROM THE ARTIFACT. One record shape across all three sources: reason /
    ancestor_of (here THE SEED that reached it) / chain_depth (-1: negative IS downstream), plus the
    optional convergence pair. `_STRUCTURAL_REASONS` membership is what carries it through the three
    shipped guards -- a literal comparison would have bypassed all of them."""
    sg = _walk(_fixture(), [_SEED], cascade_contract_slots=1)
    node = next(n for n in sg.nodes if n.id == _F_STRONG)
    assert node.admission == {"reason": pl.REASON_DOWNSTREAM_CONTRACT, "ancestor_of": _SEED,
                              "chain_depth": -1}
    assert pl.REASON_DOWNSTREAM_CONTRACT in pl._STRUCTURAL_REASONS
    adm = _cc(sg)["admissions"]
    assert len(adm) == len(sg.nodes), "every kept node still carries exactly one record"
    assert adm["contract:%s:%s" % (_F_STRONG, _F_STRONG)]["reason"] == pl.REASON_DOWNSTREAM_CONTRACT
    rec = _cc(sg)["cascade_contracts"][0]
    assert {"key", "contract", "ancestor_of", "chain_depth", "slice", "reason", "relevance_q"} <= set(rec)
    assert "_entry" not in rec, "the scored tuple is machinery, not a record"
    assert rec["slice"] == "palm_oil", "the EVIDENCE NODE, so a reader can check slice-distinctness"


def test_cross_market_convergence_is_stamped_and_counted():
    """(v), cross-market: a foreign contract declared by >= 2 admitted SEEDS is reachable from two chains
    and carries the same {convergence, anchors} stamp. `n_convergence_cross` is the census counter the P6
    record reads -- separate from `n_convergence`, which stays the reserve's."""
    sg = _walk(_fixture(), [_SEED, _SEED2], cascade_contract_slots=3)
    cc = _cc(sg)
    both = [r for r in cc["cascade_contracts"] if r["contract"] == _F_BOTH]
    assert both, "the two-seed foreign must be admitted for this pin to mean anything"
    assert both[0]["convergence"] is True and sorted(both[0]["anchors"]) == sorted([_SEED, _SEED2])
    assert cc["n_convergence_cross"] == 1
    assert cc["n_convergence"] == 0, "the reserve's counter is untouched -- two sources, two numbers"
    node = next(n for n in sg.nodes if n.id == _F_BOTH)
    assert node.admission["convergence"] is True and len(node.admission["anchors"]) == 2


def test_the_slot_pot_is_a_PER_WALK_budget_and_the_empties_are_declared():
    """N is 'N slots for this walk'. Unfillable slots stay EMPTY and are DECLARED (instrument-dead made
    readable), never backfilled with a cosine node -- backfilling is how substitution creeps back in."""
    sg = _walk(_fixture(), [_SEED], cascade_contract_slots=1)
    assert _cc(sg)["cascade_slots"] == {"total": 1, "filled": 1, "empty": 0}
    lonely = g.CausalGraph({c.contract: c for c in
                            (_contract(_SEED, [_drv("a1", 0.9)]),)}, silver=set())
    sg2 = _walk(lonely, [_SEED], cascade_contract_slots=2)
    assert _cc(sg2)["cascade_slots"] == {"total": 2, "filled": 0, "empty": 2}
    assert len(sg2.nodes) == 2, "no supply -> no admission, and NO backfill"
    big = _walk(_fixture(), [_SEED, _SEED2], cascade_contract_slots=99)
    assert _cc(big)["cascade_slots"]["filled"] == len(_cc(big)["cascade_contracts"])
    assert _cc(big)["cascade_slots"]["filled"] <= 99


def test_the_paid_block_ends_the_turn_CITABLE():
    """THE ADMITTED-BUT-NOT-CITED DEFECT, on a PAID slot. Under cap_policy='score' a structurally admitted
    node sorts by its own relevance and can draw ceil(cap * share) = 0 rows. Two shipped guards save it,
    and both are membership tests on `_STRUCTURAL_REASONS`: the anchor-adjacency cap-order move (which had
    to learn that a CONTRACT admission hangs off its SEED's (contract,id) key, not its own) and the 1-row
    floor. Run end to end through ground()."""
    gr = _fixture(seed_drivers=[_drv(f"w{i}", 0.90 - i * 0.01) for i in range(12)])
    sg = _walk(gr, [_SEED], node_budget=16, cascade_contract_slots=1)
    pl.ground(sg, _QUERY, gr, retrieve=_retrieve, silver_lookup=lambda *a, **k: None, asof="2026-08-12",
              driver_slices={d.id for c in gr.contracts.values() for d in c.drivers},
              evidence_cap=24, k_by_depth=(7, 5), cap_policy="score")
    node = next(n for n in sg.nodes if n.id == _F_STRONG)
    assert node.evidence, "a PAID slot must buy a citable block"
    assert sum(len(n.evidence) for n in sg.nodes) <= 24, "and the cap total still holds"
    cc = _cc(sg)
    assert cc["cascade_with_evidence"] == 1
    # the join carries the paid rows WITH their reason, so the gate's citation clause is readable
    reasons = {row[3] for row in cc["cited_join"]}
    assert pl.REASON_DOWNSTREAM_CONTRACT in reasons
    assert reasons <= pl._STRUCTURAL_REASONS
    assert cc["reserved_with_evidence"] == 0, "the RESERVE's own counter never moved"


def test_the_cap_order_puts_the_paid_block_beside_its_seed_not_at_the_tail():
    """The order half of the same guard, pinned directly: `_closure_cap_order` moves a structurally
    admitted node next to the ANCHOR that earned it. For a cascade contract the anchor is the SEED, whose
    (contract, id) is (seed, seed) -- the driver-shaped key would match nothing and drop the block to the
    defensive tail, where the cap's trim falls first."""
    sg = _walk(_fixture(), [_SEED], cascade_contract_slots=1)
    order = pl._closure_cap_order(sorted(sg.nodes, key=lambda x: (x.depth, -x.relevance)))
    ids = [n.id for n in order]
    assert ids.index(_F_STRONG) == ids.index(_SEED) + 1, "immediately after its seed, not at the tail"


def test_the_walk_is_deterministic_at_the_slot_boundary():
    """Same query, same graph, same slots -> the same block, every time. The tie-break is (-score, id), so
    two equally scored candidates cannot flip between runs and make an A/B unreproducible."""
    a = _walk(_fixture(), [_SEED, _SEED2], cascade_contract_slots=2)
    b = _walk(_fixture(), [_SEED, _SEED2], cascade_contract_slots=2)
    assert [r["contract"] for r in _cc(a)["cascade_contracts"]] == \
        [r["contract"] for r in _cc(b)["cascade_contracts"]]
    assert {n.key for n in a.nodes} == {n.key for n in b.nodes}


def test_the_mermaid_draws_the_cascade_in_the_SEED_TO_FOREIGN_direction():
    """The rendered edge must point the way the doctrine says: the seed's situation cascades INTO the
    foreign market. `via_edge._from` is the seed, so both the mermaid and answer's 'REACHED VIA CASCADE
    HOP' line read seed --relation--> foreign."""
    sg = _walk(_fixture(), [_SEED], cascade_contract_slots=1)
    node = next(n for n in sg.nodes if n.id == _F_STRONG)
    assert node.via_edge["_from"] == _SEED and node.via_edge["reason"] == pl.REASON_DOWNSTREAM_CONTRACT
    assert node.via_edge["category"] == pl.edge_category("substitutes_for") == "market_structure"
    assert "-->" in sg.mermaid


# ══ THE KNOB (D-MW-28: a Class-1 mode knob, never an env) ════════════════════════════════════════════════
def test_cascade_contract_slots_is_a_class1_knob_threaded_to_the_walk():
    import inspect
    sig = inspect.signature(pl.grounded_subgraph).parameters
    assert "cascade_contract_slots" in sig and sig["cascade_contract_slots"].default is None
    assert "cascade_contract_slots" in rm._WALK_KNOBS
    kn = rm.knobs(rm.MAX_CC1)
    assert kn["cascade_contract_slots"] == 1
    assert rm.walk_kwargs(kn)["cascade_contract_slots"] == 1
    assert "cascade_contract_slots" not in rm.ground_kwargs(kn)


def test_it_is_a_KNOB_and_not_an_ENV(monkeypatch):
    """THE ROUND-2 CATCH: a process-global GRAPHRAG_CASCADE_CONTRACTS re-opens the exact defect that
    forced the reserve into the mode table -- every quick/standard turn on the task would pay a ~2.8k-token
    foreign block. There is no env read anywhere on this path, and setting the obvious name changes
    nothing."""
    import inspect
    src = inspect.getsource(pl)
    assert "GRAPHRAG_CASCADE" not in src
    monkeypatch.setenv("GRAPHRAG_CASCADE_CONTRACTS", "3")
    sg = _walk(_fixture(), [_SEED])                          # no knob -> no pot, and no P6 ledger at all
    assert "cascade_slots" not in _cc(sg) and "cascade_contracts" not in _cc(sg)
    assert all(n.admission["reason"] != pl.REASON_DOWNSTREAM_CONTRACT for n in sg.nodes)
    on = _walk(_fixture(), [_SEED], cascade_contract_slots=1)
    assert _cc(on)["cascade_slots"]["total"] == 1, "the KNOB, and only the knob, opens the pot"


def test_max_cc1_is_max_plus_exactly_one_variable():
    """THE TWO-PRESET ARM PATTERN, third application (max/max_c0, esc/esc_r, max/max_cc1). The P6 gate
    runs `--mode max` vs `--mode max_cc1`, so the arms MUST differ by exactly one field -- and neither arm
    may be built by mixing a preset with a kwarg, because the kwarg beats the preset outright."""
    a, b = rm.MODES[rm.MAX], rm.MODES[rm.MAX_CC1]
    diff = {f for f in rm.KNOB_FIELDS if getattr(a, f) != getattr(b, f)}
    assert diff == {"cascade_contract_slots"}
    assert a.cascade_contract_slots is None and b.cascade_contract_slots == 1
    assert "cascade_contract_slots" not in rm.knobs(rm.MAX), "None is not 0: the OFF arm mints no key"


def test_the_p6_arms_are_symmetric_under_the_composition_census_mandate():
    """THE ONE-VARIABLE LAW, checked across a module boundary. The width-gated composition mandates ride
    `max` (orchestrator._CENSUS_MANDATE_MODES) exactly so the P3 arms differed by one variable; the P6
    arms are `max` vs `max_cc1`, so a mandate set that names one and not the other makes the census a
    SECOND variable and the gate unreadable -- the same reasoning that put max_c0 and esc/esc_r in there.

    This pin used to SKIP with a handoff message while orchestrator.py sat outside the building cluster's
    ownership. Round-1 review called the skip what it was -- a gate launchable while its own arm-symmetry
    check was inert (the C2/U3 class) -- so the entry landed and the pin ARMED."""
    from leviathan.graphrag import orchestrator as orch
    assert rm.MAX in orch._CENSUS_MANDATE_MODES and rm.MAX_CC1 in orch._CENSUS_MANDATE_MODES


def test_the_paid_admission_ROUND_TRIPS_into_the_eval_downstream_join(monkeypatch):
    """THE GATE'S OWN JOIN, END TO END (P6 round-1). The adjudicator asks two questions of each row: was
    the foreign contract ADMITTED (an id list) and was it CITED (a counter). Both were unreadable: the id
    lists were built from `reserved` only -- and planner deliberately keeps cascade admissions OUT of
    `reserved` so the reserve's count_delta identity stays assertable -- while the citation lane partition
    tested EQUALITY against `cascade_downstream`, dropping the P6 reason into the UPSTREAM lane. Pinned
    here on the REAL producer's output, never on a hand-written artifact: walk -> ground -> _closure_cited."""
    from leviathan.graphrag import eval as ev_mod
    gr = _fixture(seed_drivers=[_drv(f"w{i}", 0.90 - i * 0.01) for i in range(12)])
    sg = _walk(gr, [_SEED], node_budget=16, cascade_contract_slots=1)
    pl.ground(sg, _QUERY, gr, retrieve=_retrieve, silver_lookup=lambda *a, **k: None, asof="2026-08-12",
              driver_slices={d.id for c in gr.contracts.values() for d in c.drivers},
              evidence_cap=24, k_by_depth=(7, 5), cap_policy="score")
    cc = _cc(sg)
    row = next(r for r in cc["cited_join"] if r[3] == pl.REASON_DOWNSTREAM_CONTRACT)
    got = ev_mod._closure_cited({"trace": {"cascade_closure": cc, "citation_verifier": {
        "resolved": {"E1": {"source_key": row[0], "date": row[1], "snippet": row[2]}}}}})
    # (1) ADMITTED: the fully-qualified id is present, in the DOWNSTREAM lane, distinct from a driver key
    assert "contract:%s:%s" % (_F_STRONG, _F_STRONG) in got["downstream_ids"]
    assert all(x.startswith("contract:") or x.startswith("driver:") for x in got["downstream_ids"])
    assert "contract:%s:%s" % (_F_STRONG, _F_STRONG) not in got["upstream_ids"]
    # (2) CITED: the P6 gate's headline counter, which the equality partition made 0 by construction
    assert got["n_cited_downstream"] == 1 and got["n_cited_upstream"] == 0
    assert got["refs_downstream"] == ["E1"]
    assert ev_mod._DOWNSTREAM_REASONS is pl.DOWNSTREAM_REASONS, "ONE producer, never a retyped literal"


def test_the_hierarchy_read_is_MEMOIZED_so_graph_construction_is_free_of_it(monkeypatch):
    """`CausalGraph.__init__` now inverts the inter_commodity map, which reads the contract->node
    hierarchy. Uncached that was a full commodity_hierarchy.yaml parse PER CONSTRUCTION (~21 ms, i.e.
    essentially the whole cost of building a synthetic graph) -- invisible in serving, which loads once,
    and paid N times by every eval/config_check/tooling job that builds N graphs. The file is a shipped,
    read-only config, so the memo is invalidation-free."""
    ev._HIER_CACHE.clear()
    calls = {"n": 0}
    import yaml as _yaml
    _real = _yaml.safe_load

    def _spy(*a, **kw):
        calls["n"] += 1
        return _real(*a, **kw)
    monkeypatch.setattr(_yaml, "safe_load", _spy)
    ev._hier()
    assert calls["n"] == 1, "the first read parses"
    g.CausalGraph({}, silver=set())
    g.CausalGraph({}, silver=set())
    assert calls["n"] == 1, "and no construction re-parses it"
    assert ev.node_for("soybean_oil_dce") == "soybean_oil", "the memo still serves the real answer"


def test_the_hierarchy_memo_is_keyed_by_the_RESOLVED_CONFIG_PATH_not_a_constant(monkeypatch, tmp_path):
    """P6 ROUND-2 MINOR, THE MEMO'S ONE HAZARD. `_hier()` reads `ex._CFG / "commodity_hierarchy.yaml"`, and
    `ex._CFG` is a module-level singleton that six unit files repoint at a tmp dir. Keyed on a CONSTANT the
    memo made that repointing invisible in one direction (a test pointing _CFG at a fixture hierarchy
    silently read the REAL one) and poisonous in the other (a test that populated the memo while _CFG
    pointed at a directory that does not exist cached `{}` for every later reader in the process).

    Keyed on the RESOLVED PATH the memo follows the config it actually parsed: repointing misses the old key
    and re-parses, and the real config's entry survives beside the fixture's. Pinned as the reviewer's own
    repro: node_for -> repoint -> node_for reads the NEW mapping."""
    from leviathan.graphrag import extract as ex
    assert ev.node_for("soybean_oil_dce") == "soybean_oil", "the real hierarchy, memoized"
    fake = tmp_path / "cfg"
    fake.mkdir()
    (fake / "commodity_hierarchy.yaml").write_text(
        "contracts:\n  soybean_oil_dce:\n    node: TOTALLY_DIFFERENT\n", encoding="utf-8")
    monkeypatch.setattr(ex, "_CFG", fake)
    assert ev.node_for("soybean_oil_dce") == "TOTALLY_DIFFERENT", "the repointed config, not the stale memo"
    monkeypatch.undo()
    assert ev.node_for("soybean_oil_dce") == "soybean_oil", "and the real entry survived beside it"
    empty = tmp_path / "gone"                                 # the DANGEROUS direction: `{}` must not stick
    monkeypatch.setattr(ex, "_CFG", empty)
    assert ev.node_for("soybean_oil_dce") == "soybean_oil_dce", "no file -> the id resolves to itself"
    monkeypatch.undo()
    assert ev.node_for("soybean_oil_dce") == "soybean_oil", "and the empty parse poisoned nothing"


def _one_row_retriever(row: dict):
    """THE CROSS-MARKET OVERLAP, as a retriever: the SAME dated row comes back for every slice. That is the
    realistic shape for a paid CROSS-MARKET block -- a 'palm oil vs soyoil substitution' piece is filed under
    both commodity slices -- and it is exactly what `_dedup_and_cap` exists to collapse."""
    return lambda query, slice_, *, k, asof=None, near=None: [dict(row)]


def test_the_paid_block_KEEPS_ITS_FLOOR_ROW_when_dedup_empties_it():
    """P6 ROUND-2 MAJOR, REPRODUCED THEN FIXED. `_dedup_and_cap` dedups FIRST, uncapped, and then the quota
    loop early-outs on `if not keep: continue` -- so a structurally admitted node whose rows ALL deduped
    against an EARLIER node reached the 1-row floor never and ended the turn with zero evidence. On a PAID
    slot that is the admitted-but-not-cited defect the floor exists to prevent, self-cancelling exactly on
    the overlap class a cross-market slot is most likely to buy.

    A DUPLICATE RECEIPT IS HONEST: the same dated row cited under two nodes says the two markets share that
    record, which is true. An evidence-less paid block is the recorded defect."""
    gr = _fixture()
    sg = _walk(gr, [_SEED], cascade_contract_slots=1)
    paid = next(n for n in sg.nodes if n.id == _F_STRONG)
    assert paid.admission["reason"] == pl.REASON_DOWNSTREAM_CONTRACT
    row = {"date": "2026-02-02", "source": "SRC", "source_key": "SHARED#0", "text": "the shared row"}
    pl.ground(sg, _QUERY, gr, retrieve=_one_row_retriever(row), silver_lookup=lambda *a, **k: None,
              asof="2026-08-12", driver_slices={d.id for c in gr.contracts.values() for d in c.drivers},
              evidence_cap=24, k_by_depth=(7, 5), cap_policy="score")
    assert [h["source_key"] for h in paid.evidence] == ["SHARED#0"], "the floor row, not zero rows"
    seed_node = next(n for n in sg.nodes if n.key == ("contract", _SEED, _SEED))
    assert seed_node.evidence, "and the node that kept it FIRST still keeps it"
    cc = _cc(sg)
    assert cc["cascade_with_evidence"] == 1
    assert pl.REASON_DOWNSTREAM_CONTRACT in {r[3] for r in cc["cited_join"]}, "citable, so the gate can read it"


def test_the_floor_is_STRUCTURAL_ONLY_a_cosine_node_still_dedups_to_nothing():
    """The other half of the same pin: the floor is a MEMBERSHIP test on `_STRUCTURAL_REASONS`, so it does
    NOT hand every cosine node a duplicate row. A cosine node that dedups away keeps zero rows -- the
    attribution rule for ordinary nodes is unchanged, and only a node whose admission was PAID FOR (or
    reserved) is worth a duplicate receipt."""
    gr = _fixture()
    sg = _walk(gr, [_SEED], cascade_contract_slots=1)
    row = {"date": "2026-02-02", "source": "SRC", "source_key": "SHARED#0", "text": "the shared row"}
    pl.ground(sg, _QUERY, gr, retrieve=_one_row_retriever(row), silver_lookup=lambda *a, **k: None,
              asof="2026-08-12", driver_slices={d.id for c in gr.contracts.values() for d in c.drivers},
              evidence_cap=24, k_by_depth=(7, 5), cap_policy="score")
    cosine = [n for n in sg.nodes
              if (n.admission or {}).get("reason") not in pl._STRUCTURAL_REASONS and n.depth > 0]
    assert cosine, "the fixture must contain cosine nodes for this pin to mean anything"
    assert sum(len(n.evidence) for n in cosine) == 0, "no floor for a cosine node"
    kept_rows = [h["source_key"] for n in sg.nodes for h in n.evidence]
    assert kept_rows.count("SHARED#0") == 2, "exactly two receipts: the first keeper and the paid floor"


def test_no_shipped_preset_carries_the_slot():
    """The width machinery ships DARK. A serving preset that quietly carried a slot would put a
    ~2.8k-token foreign block on every metered turn, unmeasured and unpriced."""
    for name in sorted(rm.serving_names()):
        assert rm.MODES[name].cascade_contract_slots is None, name
        assert "cascade_contract_slots" not in rm.knobs(name), name
    assert rm.MAX_CC1 in rm.DARK_NAMES and rm.MAX_CC1 not in rm.serving_names()


# ══ D-MW-29: THE FROZEN INSTRUMENT, AND ITS LIVENESS PRECONDITION ════════════════════════════════════════
# THE GATE'S DECK CANNOT BE EDITED AFTER AN ARM FIRES, so every property it needs must be checkable BEFORE
# spend. The v1 authoring checked the CENSUS (backed + slice-distinct) and stopped there -- and three of its
# six rows were dead by construction under the STRICTER shipped order, which caps the deck at exactly the
# 3-row instrument-dead floor, i.e. zero margin. The pre-freeze amendment re-authored those three rows and
# these pins make the precondition TESTABLE rather than hoped: a deck row that stops being buyable REDS in
# CI instead of surfacing as an instrument-dead arm after the money is spent.
_CFG_DIR = pathlib.Path(__file__).resolve().parents[2] / "configs" / "graphrag"
_XMC_DECK = _CFG_DIR / "eval_queries_cascade_downstream_v1.yaml"
_XMC_CHECKS = _CFG_DIR / "eval_checklists_cascade_downstream_v1.yaml"
_HAVE_XMC = _XMC_DECK.exists() and _XMC_CHECKS.exists()
_XMC_SKIP = pytest.mark.skipif(not _HAVE_XMC, reason="the P6 instrument pair is gitignored (configs/graphrag/)")


def _deck_rows() -> list[dict]:
    import yaml
    return yaml.safe_load(_XMC_DECK.read_text(encoding="utf-8"))["queries"]


def _project(graph, seed: str, foreign: str) -> str:
    """THE SHIPPED ELIGIBILITY ORDER, PROJECTED -- `_cascade_plan`'s own tests in `_cascade_plan`'s own
    sequence (already_admitted -> unbacked -> same_slice), read against the set a max-shape walk holds when
    the slot is offered: the seed plus its d=1 forward TRACKED cross_links (the D-MW-13 hop fence stops the
    forward contract frontier there), and the commodity nodes those contracts cover -- which is what
    `cov_nodes` is built from, since a driver node carries its parent contract.

    AN UPPER BOUND ON LIVENESS, DECLARED: a realized turn may seed up to 6 contracts, so the covered set can
    only GROW and `same_slice` can only get MORE common. A row this returns dead can never be live; a row it
    returns LIVE is BUYABLE, not guaranteed bought (the pot is one slot for the whole walk)."""
    reached = {seed} | {e["driver_commodity"] for e in graph.cross_links(seed) if e["tracked"]}
    covered = {graph.contract_node(c) for c in reached}
    if foreign in reached:
        return "already_admitted"
    node = graph.contract_node(foreign)
    if not node:
        return "unbacked"
    return "same_slice" if node in covered else "LIVE"


@_XMC_SKIP
def test_every_frozen_deck_row_is_LIVE_BY_CONSTRUCTION_under_the_shipped_eligibility(real):
    """THE PIN THE AMENDMENT EXISTS FOR. 6/6 rows must survive the shipped order -- neither
    forward-TRACKED (which spends no slot and admits the node as `cosine`, a reason liveness does not count)
    nor node-CO-SLICED with the seed or one of its forward hops.

    The two failure shapes this would have caught before the money: arabica->robusta and raw->white are
    RECIPROCAL pairs, so the walk reaches the foreign forward at d=1 and the slot records
    `already_admitted`; soybeans->campinas_corn names a foreign whose node `corn` a forward hop of the seed
    already covers, so the slot records `same_slice`."""
    rows = _deck_rows()
    verdicts = {r["id"]: _project(real, r["cascade_pair"]["seed"], r["cascade_pair"]["foreign"]) for r in rows}
    assert len(rows) == 6
    assert sorted(verdicts.values()) == ["LIVE"] * 6, verdicts
    for r in rows:                                            # and the named foreign is IN the seed's pool
        cp = r["cascade_pair"]
        pool = {lk.get("contract") or lk.get("declaring_contract") for lk in real.rev_cross_links(cp["seed"])}
        assert cp["foreign"] in pool, r["id"]


@_XMC_SKIP
def test_the_deck_pairs_are_CENSUS_REAL_and_the_join_keys_are_the_producers_shape(real, census):
    """PROVENANCE + THE JOIN, on the real files. Every pair is a census `deck_eligible_pairs` row (nothing
    invented, the P6 draft's cautionary tale), every `mechanism` is the graph's edge string VERBATIM, every
    `downstream_nodes` id exists in the FOREIGN contract's own DAG, and `foreign_contract_node` is the
    walk's `contract:<id>:<id>` triple -- byte-identical to what eval._closure_cited emits, which is the
    adjudicator's only join."""
    eligible = {(p["seed"], p["foreign"]) for p in census["deck_eligible_pairs"]}
    seeds, foreigns = set(), set()
    for r in _deck_rows():
        cp = r["cascade_pair"]
        seed, foreign = cp["seed"], cp["foreign"]
        assert (seed, foreign) in eligible, r["id"]
        assert r["contract"] == seed and r["evidence_nodes"] == [cp["seed_node"]], r["id"]
        assert real.contract_node(seed) == cp["seed_node"], r["id"]
        assert real.contract_node(foreign) == cp["foreign_node"], r["id"]
        assert r["foreign_contract_node"] == "contract:%s:%s" % (foreign, foreign), r["id"]
        edge = next(lk for lk in real.rev_cross_links(seed)
                    if (lk.get("contract") or lk.get("declaring_contract")) == foreign)
        assert " ".join(cp["mechanism"].split()) == " ".join(edge["mechanism"].split()), r["id"]
        assert (cp["relation"], str(cp["sign"]), cp["lag"]) == \
               (edge["relation"], str(edge["sign"]), edge["lag"]), r["id"]
        drivers = {d.id for d in real.contracts[foreign].drivers}
        for key in r["downstream_nodes"]:
            kind, cid, did = key.split(":", 2)
            assert (kind, cid) == ("driver", foreign) and did in drivers, (r["id"], key)
        seeds.add(cp["seed_node"])
        foreigns.add(cp["foreign_node"])
    assert len(seeds) == 6 and len(foreigns) == 6, "one row per seed, and no two rows buy the same block"


@_XMC_SKIP
def test_the_instrument_pair_holds_its_authored_shape_and_records_the_amendment():
    """DECK AND CHECKLIST AGREE, AND THE PRE-FREEZE EDIT IS ON THE RECORD IN BOTH. The freeze law allows
    exactly one thing -- an amendment made before any arm fires -- and the only way that stays honest is a
    CHANGELOG in both headers naming the rows it removed and why. Also holds the no-tautology law the deck
    is authored under: no question may name its own foreign market, or the gate measures ROUTING."""
    import re

    from leviathan.graphrag import eval as ev_mod
    from leviathan.graphrag import pairwise_judge as pj
    deck = ev_mod.load_queries(_XMC_DECK)
    cfg = pj.load_checklists(_XMC_CHECKS)
    errs, _ = pj.validate_checklists(cfg, deck)
    assert errs == []
    assert [str(r["id"]) for r in cfg["rows"]] == [str(q["id"]) for q in deck]
    assert all(str(q["id"]).startswith("xmc_") for q in deck)
    for p in (_XMC_DECK, _XMC_CHECKS):
        txt = p.read_text(encoding="utf-8")
        assert txt.isascii(), p.name
        assert "CHANGELOG -- ONE PRE-FREEZE AMENDMENT" in txt, p.name
        for gone in ("xmc_arabica_blend_rotation", "xmc_raw_sugar_refining_pull",
                     "xmc_soybeans_safrinha_window"):
            assert gone in txt, (p.name, gone, "a removed row must be RECORDED, not merely deleted")
        for mode in ("max_cc1", "max"):
            assert f"--mode {mode} --queries configs/graphrag/eval_queries_cascade_downstream_v1.yaml" in txt
    for r in _deck_rows():
        cp = r["cascade_pair"]
        own = set(re.split(r"[^a-z]+", (cp["seed"] + "_" + cp["seed_node"]).lower()))
        tell = {t for t in re.split(r"[^a-z]+", (cp["foreign"] + "_" + cp["foreign_node"]).lower())
                if len(t) > 3} - own
        assert tell, r["id"]
        for t in sorted(tell):
            assert not re.search(r"\b%s\b" % t, r["question"].lower()), (r["id"], t)
        assert "asof" in r and r["asof"] == "2026-08-12", r["id"]
        for absent in ("expect", "expected_intent", "upstream_nodes"):
            assert absent not in r, (r["id"], absent)
