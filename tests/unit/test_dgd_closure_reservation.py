"""D-GD-1 (2026-08-08) CASCADE-CLOSURE RESERVATION -- the five constraint pins + the admission-trace pins.

The wave's core walk change: N slots of the walk's EXISTING budget are reserved, inside the wave that
admits them, for the BACKED ancestors of the top-ranked admitted drivers -- decided OUTSIDE the hop-first
comparator, paid for by displacing the lowest-ranked admitted drivers, flagged OFF by default
(GRAPHRAG_CLOSURE_RESERVE) so the D-GD-3 A/B is the thing that flips it.

WHY EACH PIN EXISTS (all five were named as non-negotiable BEFORE the build, and each names a defect that
already happened once in this estate):

  PIN 1  SELF-CANCEL      `_dedup_and_cap` spends one global budget shallowest-first, so a reserved
                          ancestor -- admitted for STRUCTURE, often BELOW the relevance floor its siblings
                          cleared -- sorts to the tail and is retrieved-and-then-zeroed. That is the
                          D-DV-1b uncitable-prompt-window defect, and it would have made the whole
                          reservation buy a node the reader can never cite.
  PIN 2  BYTE-IDENTITY    flag OFF, and flag ON with nothing eligible, must reproduce the shipped walk
                          exactly. Pinned in BOTH polarities so "the flag does nothing" and "the flag does
                          something" are separately provable.
  PIN 3  BUDGET           node count and k identical on both arms, and the post-reservation count may never
                          cross `node_budget`. It was written as "may never cross 16", justified by the
                          17-node rerank cliff (17x60=1,020 docs splits the coalescer at
                          _COALESCE_MAX_DOCS=1000 and burns 2/3 of a 3-req/min non-adjustable quota).
                          D-MW-11 separates the two: the CEILING is the walk's own law and is now
                          parametrized in node_budget; the CLIFF was the BEDROCK lane's, and serving
                          reranks on native cohere (1,000 req/min, caller-boundary packing) since D-MW P1.
  PIN 4  SAME-CONTRACT    a driver's parents are same-contract BY SCHEMA, so no new `_context_block` may
                          render. A new contract block costs ~2.8k tokens (measured 7,071-14,190 chars,
                          median 11,194); the reservation's whole prose claim is that it costs none.
  PIN 5  VISITED/TAU      `visited` stamps at SCORING time, before the tau prune -- so a tau-pruned sibling
                          is permanently unreachable. The reservation is WAVE-LOCAL and RELEASES the tau
                          tombstone it overrides, so every key still carries exactly ONE decision.

Pure/offline: injected embed, injected retrieve, no S3, no pg, no LLM, no spend.
"""
from __future__ import annotations

import math

import pytest
from leviathan.causal import schema as cs
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import graph as g
from leviathan.graphrag import planner as pl

# ── the fixture: an exact-cosine embedder ────────────────────────────────────────────────────────────────
# cos(query, text) is READ OFF A TABLE. Each text maps to the unit vector [r, sqrt(1-r^2)] and the query to
# [1, 0], so cos == r exactly. That is what lets a test say "this ancestor scores 0.10, below tau 0.35" and
# mean it, instead of hoping a keyword-overlap fake lands where the test needs it.
_QUERY = "QQ"
_REL: dict[str, float] = {}


def _embed(texts):
    out = []
    for t in texts:
        r = 1.0 if t == _QUERY else float(_REL.get(t, 0.0))
        r = max(-1.0, min(1.0, r))
        out.append([r, math.sqrt(max(0.0, 1.0 - r * r))])
    return out


def _drv(id_, rel, **kw):
    """A driver whose mechanism string IS its relevance key (so _REL fully controls the admission sort)."""
    mech = f"m::{id_}"
    _REL[mech] = rel
    return cs.Driver(id=id_, type=kw.pop("type", "hazard"), sign=kw.pop("sign", "+"), mechanism=mech, **kw)


def _corn(drivers, hops=()) -> g.CausalGraph:
    corn = cs.CausalContract(contract="corn", aliases=["corn"], drivers=drivers,
                             inter_commodity=[cs.InterCommodityEdge(driver_commodity=h, relation="substitutes_for",
                                                                    sign="-", mechanism=f"x::{h}")
                                              for h in hops])
    out = {"corn": corn}
    for h in hops:
        out[h] = cs.CausalContract(contract=h, drivers=[_drv("h_drv", 0.9)])
    return g.CausalGraph(out, silver=set())


def _chain_graph():
    """One anchor with a 2-link backed chain, one DARK parent, one SAME-SLICE parent, and 9 fillers that
    outrank the chain on cosine -- i.e. exactly the flattening the wave exists to fix."""
    ds = [
        _drv("anchor", 0.95, parents=["mid", "darkp", "twin"]),
        _drv("mid", 0.40, parents=["root"]),      # survives tau (0.35) but loses on budget
        _drv("root", 0.10),                       # BELOW tau -> only a tau-exempt reservation reaches it
        _drv("darkp", 0.30),                      # unbacked -> uncitable -> must never take a slot
        _drv("twin", 0.30),                       # backed but resolves to the ANCHOR's slice -> zero new rows
    ] + [_drv(f"f{i}", 0.90 - i * 0.01) for i in range(9)]
    return _corn(ds)


# alias map for the monkeypatched production resolver: `twin` deliberately shares `anchor`'s slice.
_ALIAS = {"anchor": "anchor_sl", "mid": "mid_sl", "root": "root_sl", "twin": "anchor_sl",
          **{f"f{i}": f"f{i}_sl" for i in range(9)}}


@pytest.fixture()
def alias(monkeypatch):
    monkeypatch.setattr(ev, "backed_dag_ids", lambda: set(_ALIAS))
    monkeypatch.setattr(ev, "slice_for_driver", lambda d: _ALIAS.get(d))
    return _ALIAS


def _walk(graph, **kw):
    kw.setdefault("depth", 1)
    kw.setdefault("node_budget", 8)
    kw.setdefault("tau", 0.35)
    kw.setdefault("max_seeds", 1)
    return pl.grounded_subgraph(_QUERY, graph, embed=_embed, route_fn=lambda q, gr: ["corn"], **kw)


def _keys(sg):
    return [n.key for n in sg.nodes]


def _res_ids(sg):
    return [r["key"][2] for r in sg.trace["cascade_closure"]["reserved"]]


# ══ PIN 2 -- BYTE-IDENTITY, BOTH POLARITIES ══════════════════════════════════════════════════════════════
_PRE_DGD_TRACE_KEYS = {"seeds", "kept", "pruned", "visited", "budget", "params"}


def _walk_state(sg):
    """Everything the ANSWER can see: the nodes, the diagram, and every pre-D-GD trace key. `cascade_closure`
    is deliberately excluded -- it is the ONE additive key, and its additivity is asserted separately."""
    return ([(n.key, n.depth, n.relevance, n.prior, n.via_edge) for n in sg.nodes],
            sg.mermaid, sg.seeds,
            {k: v for k, v in sg.trace.items() if k in _PRE_DGD_TRACE_KEYS})


def test_pin2_flag_off_is_byte_identical_and_the_new_key_is_the_only_delta(alias):
    gr = _chain_graph()
    off = _walk(gr, closure_reserve=0)
    zero = _walk(gr, closure_reserve=None)          # env unset in the suite -> _closure_reserve_n() == 0
    assert _walk_state(off) == _walk_state(zero)
    # the trace gained exactly TWO additive keys over the shipped walk, and nothing else moved.
    # D-MW-13 RE-PIN: `walk_shape` joins `cascade_closure` as an ADDITIVE, both-arms stamp -- four P3
    # RECORDED quantities (seeds, per-depth kept, hop contracts, second-order fences) had no artifact
    # source at all, and a key stamped on one arm only is an uncomparable key (the cascade_closure lesson).
    assert set(off.trace) == _PRE_DGD_TRACE_KEYS | {"cascade_closure", "walk_shape"}
    cc = off.trace["cascade_closure"]
    assert cc["enabled"] is False and cc["reserve_n"] == 0
    assert cc["reserved"] == [] and cc["displaced"] == [] and cc["count_delta"] == 0
    # ...and the census still rides, because it is the two arms' SHARED baseline.
    assert cc["open"] >= 1 and isinstance(cc["closed"], int)


def test_pin2_flag_on_with_no_eligible_ancestor_is_byte_identical(alias, monkeypatch):
    """The second polarity: the flag is ON, the code runs, and nothing is eligible -- the walk must still be
    the shipped one byte for byte. Here NOTHING is backed, so every candidate ancestor is uncitable."""
    monkeypatch.setattr(ev, "backed_dag_ids", set)
    monkeypatch.setattr(ev, "slice_for_driver", lambda d: None)
    gr = _chain_graph()
    off = _walk(gr, closure_reserve=0)
    on = _walk(gr, closure_reserve=3)
    assert _walk_state(off) == _walk_state(on)
    assert on.trace["cascade_closure"]["enabled"] is True
    assert on.trace["cascade_closure"]["reserved"] == []


def test_pin2_no_parents_at_all_is_byte_identical(alias):
    gr = _corn([_drv(f"f{i}", 0.9 - i * 0.01) for i in range(12)])
    assert _walk_state(_walk(gr, closure_reserve=0)) == _walk_state(_walk(gr, closure_reserve=3))


# ══ PIN 3 -- THE BUDGET CEILING ══════════════════════════════════════════════════════════════════════════
# R1 #1 AMENDMENT (2026-08-08). Pin 3 was written as `len(kept_on) == len(kept_off)`. That is STRICTLY
# STRONGER than the constraint it was defending (`len(kept) <= node_budget`) and it cost real drivers to
# maintain, so the pin is now the CEILING, which headroom-first satisfies by construction, plus the
# accounting identity `reserved == displaced + headroom_used` as the proof no slot came from nowhere.
#
# D-MW-11 RE-SCOPE (2026-08-11), TWO CORRECTIONS:
#  * THE NUMBERS. The R1 sweep quoted here ("0/198 single-contract and 4/33 three-seed walks ever FILLED
#    node_budget -- tau ends these walks, not the budget") ran a DETERMINISTIC HASH embedder, which
#    centres mechanism cosines on 0.0 so 100% of candidates fall below tau and the budget can never bind.
#    With the real bge-m3, same population and knobs, it is the opposite: 288/288 routed-deck walks FILL
#    node_budget at the deep knobs, 0.0% of reserved slots are headroom-paid, the reservation is ~100%
#    substitution (GUIDED_DEPTH_V2_PLAN.md:141-170). The CEILING pin is unaffected -- it was always the
#    right constraint -- but the sentence justifying it was measuring a fake embedder.
#  * THE NAME. The ceiling is the WALK's budget law, not the rerank cliff. The 17-node cliff belongs to
#    the BEDROCK lane's 3-req/min bucket; serving runs native cohere (1,000/min) since D-MW P1, and
#    D-MW-9 packs rerank requests at caller boundaries, so crossing 1,000 docs now costs one more
#    concurrent request. The bound is parametrized in node_budget accordingly.
def test_pin3_node_count_and_k_are_invariant_under_the_reservation(alias):
    """THE v1 (env/kwarg-driven) POSTURE: same budget, same count, the reservation pays from within.
    Still live code -- GRAPHRAG_CLOSURE_RESERVE and the `closure_reserve` kwarg are untouched by D-MW-15,
    and quick/standard/deep carry no per-seed knobs -- so this pin is neither vacuous nor dead."""
    gr = _chain_graph()                             # 14 drivers + 1 seed vs node_budget 8: heavily oversubscribed
    off, on = _walk(gr, closure_reserve=0), _walk(gr, closure_reserve=3)
    assert len(off.nodes) == 8                      # this fixture is oversubscribed: NO headroom at all
    assert len(on.nodes) == 8                       # so here the reservation still pays by displacement
    assert on.trace["cascade_closure"]["headroom_used"] == 0
    assert on.trace["cascade_closure"]["count_delta"] == 0
    assert on.trace["cascade_closure"]["dedicated_used"] == 0        # v1: NOT the dedicated mechanism
    assert len(on.trace["cascade_closure"]["displaced"]) == len(on.trace["cascade_closure"]["reserved"])
    # k is a function of node.depth only (planner.ground: k_by_depth[min(depth, len-1)]) -- so pinning the
    # depth multiset pins k without needing to run ground().
    assert sorted(n.depth for n in on.nodes) == sorted(n.depth for n in off.nodes)
    # every key still gets exactly ONE decision (kept XOR pruned), on both arms.
    for sg in (off, on):
        decided = [tuple(p["key"]) for p in sg.trace["pruned"]] + _keys(sg)
        assert len(decided) == len(set(decided))


def test_pin3_node_count_under_the_DEDICATED_slot_posture_is_additive_not_invariant(alias):
    """PIN 3, RE-SCOPED FOR D-MW-15 (the plan's enumerated re-scope). Under per-seed DEDICATED slots the
    count invariant is no longer `len(kept_on) == len(kept_off)`: reserve slots are ADDITIVE BY
    CONSTRUCTION, so the ceiling that binds is the COSINE one (`charged <= per_seed_budget * n_seeds`) and
    the node count rises by exactly the number of slots that FILLED. That is the doctrine's "the node
    budget must never bind" -- stated as an assertion instead of as a promise.

    k is still a function of depth only, so the depth multiset of the SHARED nodes is unchanged."""
    gr = _chain_graph()
    off = _walk(gr, per_seed_budget=8, per_seed_reserve=0)     # 0 is a VALUE: reservation OFF outright
    on = _walk(gr, per_seed_budget=8, per_seed_reserve=3)
    cc = on.trace["cascade_closure"]
    assert len(off.nodes) == 8 and cc["dedicated"] is True
    assert cc["reserve_slots"]["filled"] == len(cc["reserved"]) > 0
    assert len(on.nodes) == len(off.nodes) + cc["reserve_slots"]["filled"]
    assert cc["displaced"] == [] and cc["headroom_used"] == 0 and cc["count_delta"] == 0
    assert {n.id for n in off.nodes} < {n.id for n in on.nodes}, "strictly additive: every OFF node survives"
    for sg in (off, on):
        decided = [tuple(p["key"]) for p in sg.trace["pruned"]] + _keys(sg)
        assert len(decided) == len(set(decided))


@pytest.mark.parametrize("budget", [6, 8, 10, 16, 32, 63])
@pytest.mark.parametrize("cc_slots", [None, 0, 2])
def test_pin3_reservation_never_exceeds_node_budget(alias, budget, cc_slots):
    """THE WALK INVARIANT IS `len(kept) <= node_budget + cascade_contract_slots`, PARAMETRIZED IN BOTH
    (D-MW-11 re-scope, then the D-MW-28 re-pin below).

    D-MW-28 RE-PIN (P6, 2026-08-12), STATED HONESTLY: P6 adds a THIRD admission source whose slots are
    additive by construction (a paid foreign contract block is charged to `cascade_contract_slots`, never
    to the cosine budget), so the ceiling this pin defends BECOMES `node_budget + cascade_contract_slots`
    -- the plan refused to call the slots free, and so does this bound. None == 0 == the pre-P6 ceiling,
    which is what every serving preset carries and what the un-parametrized cases below assert.
    NON-VACUITY: this fixture's contracts declare no inter_commodity edges, so the cascade source finds
    nothing to admit here and the raised bound is exercised (not merely stated) in
    test_dmw_p6.py::test_the_ceiling_is_node_budget_plus_the_cascade_slots, on a fixture that FILLS both.

    This pin used to be named for the 17-node rerank cliff and carried a hard `<= 16` beside the budget
    bound. That conflated two different facts. The walk law is the budget: the reservation spends the
    walk's OWN slots -- unspent ones first, displacement for the remainder -- so `kept` can rise toward
    node_budget but never past it, whatever node_budget is. The CLIFF is a BEDROCK-lane quota artifact:
    17 x pool-60 = 1,020 docs > _COALESCE_MAX_DOCS, i.e. a second draw on a 3-req/min non-adjustable
    bucket. Serving reranks on the NATIVE cohere lane (1,000 req/min) since D-MW P1, and D-MW-9 packs
    requests at caller boundaries, so past the cap the walk pays one more concurrent request -- a
    request-shape detail, not a cliff. A hardcoded 16 here would have made this pin FAIL the moment P3
    widens the deep preset, for a reason that no longer exists.

    The 32 case is deliberate: it is the width GUIDED_DEPTH_V2_PLAN.md:141-170 measured as the first
    node_budget at which the median deep walk (tau-survivors median 31) has any headroom at all. The 63
    case is the D-MW STEP-0 calibration (12a): the measured p75 of PER-SEED above-tau cosine demand, i.e.
    the `max` preset's one-seed width."""
    gr = _chain_graph()
    off = _walk(gr, closure_reserve=0, node_budget=budget, cascade_contract_slots=cc_slots)
    on = _walk(gr, closure_reserve=3, node_budget=budget, cascade_contract_slots=cc_slots)
    assert len(on.nodes) <= max(budget, 1) + int(cc_slots or 0)
    assert len(on.nodes) >= len(off.nodes)                   # additive-or-equal, never subtractive
    cc = on.trace["cascade_closure"]
    assert len(cc["reserved"]) == len(cc["displaced"]) + cc["headroom_used"] and cc["count_delta"] == 0
    # THE POT IS DECLARED ON BOTH P6 POLARITIES (an unstamped arm is uncomparable) and on NEITHER shipped
    # one: the knob's ABSENCE gates the eight P6 keys, so a serving preset's artifact shape is byte-
    # identical to its pre-P6 self (P6 round-1 minor). `0` is a value -- the OFF arm of the P6 A/B.
    if cc_slots is None:
        assert "cascade_slots" not in cc and "cascade_contracts" not in cc
    else:
        assert cc["cascade_slots"] == {"total": cc_slots, "filled": 0,
                                       "empty": cc_slots}, "no declared edges here -> nothing to buy"


@pytest.mark.parametrize("per_seed", [4, 8, 16, 63])
def test_pin3_the_ceiling_is_SEED_SCALED_under_per_seed_budget(alias, per_seed):
    """THE SEED-SCALED SHAPE of the same ceiling (D-MW-13). `node_budget` is no longer a flat number: it
    is `per_seed_budget x the REALIZED seed count`, and the kwarg/default is ignored outright when the
    per-seed knob is present. One seed here (route_fn returns ['corn']), so the derived ceiling is the
    per-seed value itself -- test_dmw_walk pins the multi-seed derivation."""
    gr = _chain_graph()
    sg = _walk(gr, node_budget=999, per_seed_budget=per_seed)   # 999 must be IGNORED
    assert sg.trace["budget"] == per_seed * 1
    assert sg.trace["params"]["node_budget"] == per_seed
    assert len(sg.nodes) <= per_seed
    assert sg.trace["walk_shape"]["n_seeds"] == 1


@pytest.mark.parametrize("budget", [16, 32])
def test_pin3_the_ceiling_binds_at_p3_width_too(monkeypatch, budget):
    """NON-VACUITY FOR THE WIDE END. `_chain_graph` holds 15 nodes, so a 32-budget walk there can never
    reach its ceiling -- the parametrized pin above proves the accounting at that width, not the bound.
    This fixture is OVERSUBSCRIBED at 32 (43 drivers, all above tau), which is the shape P3's wider preset
    creates and the reason the bound had to stop being a hardcoded 16 in the first place."""
    ds = [_drv("anchor", 0.95, parents=["mid"]), _drv("mid", 0.40, parents=["root"]), _drv("root", 0.10)]
    ds += [_drv(f"w{i}", 0.90 - i * 0.005) for i in range(40)]
    amap = {"anchor": "anchor_sl", "mid": "mid_sl", "root": "root_sl",
            **{f"w{i}": f"w{i}_sl" for i in range(40)}}
    monkeypatch.setattr(ev, "backed_dag_ids", lambda: set(amap))
    monkeypatch.setattr(ev, "slice_for_driver", lambda d: amap.get(d))
    gr = _corn(ds)
    off = _walk(gr, closure_reserve=0, node_budget=budget)
    on = _walk(gr, closure_reserve=3, node_budget=budget)
    assert len(off.nodes) == budget, "fixture must SATURATE the budget or the ceiling pin is vacuous"
    assert len(on.nodes) == budget                       # the ceiling binds; the reservation pays from within
    cc = on.trace["cascade_closure"]
    assert cc["headroom_used"] == 0 and len(cc["displaced"]) == len(cc["reserved"]) > 0
    assert cc["count_delta"] == 0


def test_pin3_reservation_is_a_per_walk_budget_not_per_wave(alias):
    """N is 'N of the WALK's slots'. With depth=2 the loop runs a second wave; the reservation must not
    spend N again there."""
    gr = _chain_graph()
    on = _walk(gr, closure_reserve=2, depth=2, node_budget=8)
    assert len(on.trace["cascade_closure"]["reserved"]) <= 2


# ══ PIN 4 -- SAME-CONTRACT INVARIANT (no new prose block) ════════════════════════════════════════════════
def test_pin4_no_new_contract_block_can_render(alias):
    """`answer._l2_blocks` emits one `_context_block` per DISTINCT CONTRACT of the walk, iterating exactly
    `dict.fromkeys(n.contract for n in nodes)` (answer.py:1657). Pinning that sequence pins the block count
    -- and the reservation may only ever admit a driver of a contract the walk already carries, because the
    schema forces every `driver.parents` entry to be a driver id of the SAME contract."""
    gr = _chain_graph()
    off, on = _walk(gr, closure_reserve=0), _walk(gr, closure_reserve=3)
    seq = lambda sg: list(dict.fromkeys(n.contract for n in sg.nodes))  # noqa: E731
    assert seq(on) == seq(off)
    assert _res_ids(on)                                     # the pin is vacuous if nothing was reserved
    assert {r["contract"] for r in on.trace["cascade_closure"]["reserved"]} <= set(seq(off))


def test_pin4_holds_when_a_tracked_hop_is_in_the_walk(alias):
    gr = _chain_graph()
    gr.contracts["corn"].inter_commodity = [cs.InterCommodityEdge(driver_commodity="soy", relation="substitutes_for",
                                                                  sign="-", mechanism="x::soy")]
    gr.contracts["soy"] = cs.CausalContract(contract="soy", drivers=[_drv("s1", 0.9)])
    gr._idx = {k: g._index(v) for k, v in gr.contracts.items()}
    _REL["x::soy"] = 0.99
    off, on = _walk(gr, closure_reserve=0), _walk(gr, closure_reserve=3)
    seq = lambda sg: list(dict.fromkeys(n.contract for n in sg.nodes))  # noqa: E731
    assert seq(on) == seq(off) and "soy" in seq(off)
    # a tracked hop sorts strictly ahead of every driver and the reservation is computed OUTSIDE that
    # comparator: it may neither reserve a hop nor pay for a slot with one.
    hop = ("contract", "soy", "soy")
    assert hop in _keys(on)
    assert all(tuple(d["key"]) != hop for d in on.trace["cascade_closure"]["displaced"])
    assert all(r["key"][0] == "driver" for r in on.trace["cascade_closure"]["reserved"])


def test_pin4_a_seed_is_never_displaced(alias):
    on = _walk(_chain_graph(), closure_reserve=3)
    assert ("contract", "corn", "corn") in _keys(on)
    assert all(d["depth"] > 0 for d in on.trace["cascade_closure"]["displaced"])


# ══ PIN 5 -- VISITED-BEFORE-TAU ═════════════════════════════════════════════════════════════════════════
def test_pin5_tau_exempt_admission_releases_its_tombstone_and_resurrects_nothing_else(alias):
    """`root` scores 0.10 against tau 0.35. It is reachable ONLY as a tau-exempt reservation, and admitting
    it must leave the ledger a PARTITION: the key carries one decision, not a tau prune AND an admission.
    Nothing else that tau pruned may come back, and `visited` must not move (the reservation is wave-local:
    it never reaches into an earlier wave's tombstones, which is the aggravator the recon flagged)."""
    gr = _chain_graph()
    off, on = _walk(gr, closure_reserve=0), _walk(gr, closure_reserve=3)
    key = ("driver", "corn", "root")
    off_tau = {tuple(p["key"]) for p in off.trace["pruned"] if p["reason"] == "tau"}
    assert key in off_tau and key not in _keys(off)         # today: unreachable at any budget
    assert key in _keys(on)                                 # wired: admitted by the reservation
    rec = next(r for r in on.trace["cascade_closure"]["reserved"] if tuple(r["key"]) == key)
    assert rec["tau_exempt"] is True and rec["relevance"] < 0.35
    # (a) the tau tombstone was RELEASED, not left beside the admission
    assert key not in {tuple(p["key"]) for p in on.trace["pruned"]}
    # (b) exactly one decision per key
    decided = [tuple(p["key"]) for p in on.trace["pruned"]] + _keys(on)
    assert len(decided) == len(set(decided))
    # (c) no OTHER tau-pruned sibling was resurrected
    on_tau = {tuple(p["key"]) for p in on.trace["pruned"] if p["reason"] == "tau"}
    assert off_tau - on_tau == {key}
    assert on_tau <= off_tau
    # (d) the visited tombstone set is untouched -- the reservation adds no scoring decision
    assert on.trace["visited"] == off.trace["visited"]


def test_pin5_a_tau_survivor_dropped_by_budget_is_not_marked_tau_exempt(alias):
    """`mid` clears tau at 0.40 and is dropped by BUDGET. Reserving it is not a tau override and must not be
    stamped as one -- the two admission stories are different and the ledger keeps them apart."""
    on = _walk(_chain_graph(), closure_reserve=3)
    rec = next(r for r in on.trace["cascade_closure"]["reserved"] if r["key"][2] == "mid")
    assert rec["tau_exempt"] is False and rec["relevance"] >= 0.35


# ══ PIN 1 -- THE SELF-CANCEL TRAP ═══════════════════════════════════════════════════════════════════════
def _mk(id_, rel, depth=1, adm=None, n=3):
    node = pl.GroundedNode(kind="driver", id=id_, contract="corn", depth=depth, relevance=rel)
    node.admission = adm or dict(pl._ADMIT_COSINE)
    node.evidence = [{"source_key": f"s3://{id_}/{i}", "date": f"2026-01-0{i + 1}",
                      "text": f"{id_} row {i}"} for i in range(n)]
    return node


def test_pin1_reserved_ancestor_at_the_cap_boundary_is_retrieved_AND_scored():
    """The trap, both sides. Under the shipped FIFO order a reserved ancestor's LOW relevance sorts it to the
    tail and the cap zeroes every row it just paid to retrieve. With the closure-aware order it draws budget
    as its anchor's peer instead."""
    anchor = _mk("anchor", 0.95)
    filler = [_mk(f"f{i}", 0.90 - i * 0.01) for i in range(3)]
    reserved = _mk("root", 0.10, adm={"reason": "closure_reservation", "ancestor_of": "anchor", "chain_depth": 2})
    nodes = [anchor, *filler, reserved]
    cap = 12                                                 # 4 nodes x 3 rows = the boundary exactly

    sg = pl.Subgraph(seeds=["corn"], nodes=list(nodes))
    pl._dedup_and_cap(sg, cap)
    assert len(reserved.evidence) == 3, "the reserved ancestor must survive the cap"
    assert sum(len(n.evidence) for n in nodes) == cap, "and the TOTAL must not grow -- it displaces, never adds"

    # the control: strip the admission stamp and the same cap zeroes it (this is what pin 1 is guarding).
    for n in nodes:
        n.evidence = [{"source_key": f"s3://{n.id}/{i}", "date": f"2026-01-0{i + 1}",
                       "text": f"{n.id} row {i}"} for i in range(3)]
    reserved.admission = dict(pl._ADMIT_COSINE)
    pl._dedup_and_cap(pl.Subgraph(seeds=["corn"], nodes=list(nodes)), cap)
    assert reserved.evidence == [], "control: plain FIFO retrieves the reserved node and then zeroes it"


def test_pin1_closure_order_is_a_strict_noop_without_a_reserved_node():
    order = [_mk("a", 0.9), _mk("b", 0.5), _mk("c", 0.1)]
    assert pl._closure_cap_order(order) is order


def test_pin1_closure_order_places_the_chain_after_its_anchor_nearest_parent_first():
    anchor, other = _mk("anchor", 0.95), _mk("z", 0.80)
    p1 = _mk("mid", 0.40, adm={"reason": "closure_reservation", "ancestor_of": "anchor", "chain_depth": 1})
    p2 = _mk("root", 0.10, adm={"reason": "closure_reservation", "ancestor_of": "anchor", "chain_depth": 2})
    out = pl._closure_cap_order([anchor, other, p1, p2])
    assert [n.id for n in out] == ["anchor", "mid", "root", "z"]


def test_pin1_score_cap_policy_also_keeps_the_reserved_node_citable():
    anchor = _mk("anchor", 0.95)
    reserved = _mk("root", 0.05, adm={"reason": "closure_reservation", "ancestor_of": "anchor", "chain_depth": 1})
    nodes = [anchor, *[_mk(f"f{i}", 0.9 - i * 0.01) for i in range(3)], reserved]
    pl._dedup_and_cap(pl.Subgraph(seeds=["corn"], nodes=list(nodes)), 12,
                      cap_policy="score", k_by_depth=(7, 5))
    assert reserved.evidence, "the ceil()-overshoot trim is paid from the TAIL; a reserved node is not tail"


# ══ ELIGIBILITY -- a slot may only buy a node that can actually be cited ════════════════════════════════
def test_a_dark_parent_never_takes_a_slot(alias):
    on = _walk(_chain_graph(), closure_reserve=3)
    assert "darkp" not in _res_ids(on)
    assert any(s["id"] == "darkp" and s["reason"] == "unbacked" for s in on.trace["cascade_closure"]["skipped"])


def test_a_same_slice_parent_never_takes_a_slot(alias):
    """23.1% of the estate's parent edges reach a dark parent and 4.2% reach one resolving to a slice already
    in the walk, where the cross-node dedup collapses it to zero rows. Without both filters ~1 slot in 4
    buys a node that can never be cited (recon V6)."""
    on = _walk(_chain_graph(), closure_reserve=3)
    assert "twin" not in _res_ids(on)
    assert any(s["id"] == "twin" and s["reason"] == "same_slice" for s in on.trace["cascade_closure"]["skipped"])


def test_the_chain_is_closed_nearest_parent_first(alias):
    on = _walk(_chain_graph(), closure_reserve=3)
    assert _res_ids(on) == ["mid", "root"]                   # anchor -> mid -> root, in chain order
    recs = {r["key"][2]: r for r in on.trace["cascade_closure"]["reserved"]}
    assert recs["mid"]["chain_depth"] == 1 and recs["root"]["chain_depth"] == 2
    assert recs["mid"]["ancestor_of"] == recs["root"]["ancestor_of"] == "anchor"


def test_n_bounds_the_reservation(alias):
    assert len(_res_ids(_walk(_chain_graph(), closure_reserve=1))) == 1
    assert _res_ids(_walk(_chain_graph(), closure_reserve=0)) == []


def test_an_anchor_is_never_displaced_by_its_own_chain(alias):
    on = _walk(_chain_graph(), closure_reserve=3)
    anchors = {r["ancestor_of"] for r in on.trace["cascade_closure"]["reserved"]}
    assert anchors and anchors <= {n.id for n in on.nodes}
    assert not anchors & {d["key"][2] for d in on.trace["cascade_closure"]["displaced"]}


def test_displacement_takes_the_LOWEST_ranked_admitted_drivers(alias):
    gr = _chain_graph()
    off, on = _walk(gr, closure_reserve=0), _walk(gr, closure_reserve=3)
    kept_off = [n for n in off.nodes if n.kind == "driver"]
    tail = sorted(kept_off, key=lambda n: n.relevance)[:len(on.trace["cascade_closure"]["displaced"])]
    assert {d["key"][2] for d in on.trace["cascade_closure"]["displaced"]} == {n.id for n in tail}


def test_the_reservation_is_trimmed_not_overdrawn_when_the_wave_cannot_pay(alias):
    """A wave with only the anchor to displace must not overdraw the budget. The node count is an INVARIANT,
    never a target."""
    gr = _corn([_drv("anchor", 0.95, parents=["mid"]), _drv("mid", 0.40, parents=["root"]), _drv("root", 0.36)])
    off, on = _walk(gr, closure_reserve=3, node_budget=2), _walk(gr, closure_reserve=0, node_budget=2)
    assert len(off.nodes) == len(on.nodes) == 2
    assert off.trace["cascade_closure"]["count_delta"] == 0


# ══ THE ADMISSION RECORD -- auditability from the artifact ══════════════════════════════════════════════
# D-MW-15: 'cascade_downstream' joins the enum (the second STRUCTURAL reason), and the record shape
# becomes a required-SUPERSET check -- the convergence pair {convergence, anchors} is present only on a
# candidate >= 2 admitted anchors' chains reached, and an exact-set assertion would have made the
# optional pair unshippable. `_STRUCTURAL_REASONS` is the module's own set, read here so the test and the
# three guard sites can never disagree about what "structural" means.
# D-MW-28 (P6): `cascade_downstream_contract` joins the enum -- the THIRD structural reason and the first
# that admits a CONTRACT node. Its record carries the same three required fields (`ancestor_of` is the
# SEED that reached it, `chain_depth` is -1, the negative-is-downstream convention) plus the same optional
# convergence pair, so every reader of this enum keeps reading one shape.
_REASONS = {pl.REASON_COSINE, pl.REASON_CLOSURE, pl.REASON_DOWNSTREAM, pl.REASON_DOWNSTREAM_CONTRACT,
            "focus_driver"}
_REC_REQUIRED = {"reason", "ancestor_of", "chain_depth"}
_REC_OPTIONAL = {"convergence", "anchors"}


def test_every_admitted_node_carries_an_admission_record_on_both_arms(alias):
    for n_res in (0, 3):
        sg = _walk(_chain_graph(), closure_reserve=n_res)
        adm = sg.trace["cascade_closure"]["admissions"]
        assert len(adm) == len(sg.nodes)                      # TOTAL over sg.nodes, not a subset
        for node in sg.nodes:
            rec = adm[":".join(str(p) for p in node.key)]
            assert rec is node.admission
            assert _REC_REQUIRED <= set(rec) <= (_REC_REQUIRED | _REC_OPTIONAL)
            assert rec["reason"] in _REASONS
            assert isinstance(rec["chain_depth"], int)


def test_the_structural_reason_set_is_the_one_producer_of_the_three_guards():
    """THE FINDING THIS PINS (D-MW-15): three shipped guards compared the LITERAL 'closure_reservation' --
    the 1-row score floor, the cap-order anchor-adjacency move, and the census exclusion -- so a
    'cascade_downstream' node would have bypassed all three silently and landed with ZERO evidence rows,
    the exact admitted-but-not-cited defect P3-A exists to prove fixed. All three are membership tests on
    this one set now, and the reason literals have ONE producer."""
    import inspect
    # D-MW-28 RE-PIN (P6): `cascade_downstream_contract` joins the set in the commit that mints it -- the
    # first STRUCTURAL reason that admits a CONTRACT, and the guards below are exactly what stop a
    # ~2.8k-token paid foreign block from landing with zero evidence rows.
    assert pl._STRUCTURAL_REASONS == {"closure_reservation", "cascade_downstream",
                                      "cascade_downstream_contract"}
    assert pl.REASON_CLOSURE in pl._STRUCTURAL_REASONS and pl.REASON_DOWNSTREAM in pl._STRUCTURAL_REASONS
    assert pl.REASON_DOWNSTREAM_CONTRACT in pl._STRUCTURAL_REASONS
    assert pl.REASON_COSINE not in pl._STRUCTURAL_REASONS
    assert pl._ADMIT_COSINE["reason"] == pl.REASON_COSINE
    src = inspect.getsource(pl)
    # the reason strings appear as LITERALS only where they are minted (the constants) and in prose.
    assert src.count('"closure_reservation"') == 1, "the reason literal must be minted in exactly one place"
    assert src.count('"cascade_downstream"') == 1
    assert src.count('"cascade_downstream_contract"') == 1
    for fn in (pl._closure_cap_order, pl._dedup_and_cap, pl._closure_census):
        assert "_STRUCTURAL_REASONS" in inspect.getsource(fn), \
            "%s must test MEMBERSHIP, not a literal" % fn.__name__


def test_the_admission_records_partition_the_kept_set(alias):
    sg = _walk(_chain_graph(), closure_reserve=3)
    res = [n for n in sg.nodes if n.admission["reason"] == "closure_reservation"]
    assert {n.id for n in res} == set(_res_ids(sg))
    for n in res:
        assert n.admission["ancestor_of"] and n.admission["chain_depth"] >= 1
    for n in sg.nodes:
        if n.admission["reason"] == "cosine":
            assert n.admission["ancestor_of"] is None and n.admission["chain_depth"] == 0


def test_admission_records_are_not_shared_objects(alias):
    """A shared dict would let one node's record rewrite every other node's -- the whole audit, silently."""
    sg = _walk(_chain_graph(), closure_reserve=3)
    ids = [id(n.admission) for n in sg.nodes]
    assert len(ids) == len(set(ids))
    assert pl._ADMIT_COSINE == {"reason": "cosine", "ancestor_of": None, "chain_depth": 0}


def test_the_open_closed_census_is_stamped_on_both_arms_and_is_embedding_free(alias):
    gr = _chain_graph()
    off, on = _walk(gr, closure_reserve=0), _walk(gr, closure_reserve=3)
    # `anchor` is kept on both arms; its backed distinct-slice parent `mid` is OPEN on the OFF arm and
    # CLOSED on the ON arm. `darkp` (unbacked) and `twin` (same slice) are counted on NEITHER side --
    # they are ineligible for the reservation, so charging the walk for them would be unmovable.
    assert ["corn", "anchor", "mid"] in off.trace["cascade_closure"]["open_edges"]
    assert ["corn", "anchor", "mid"] not in on.trace["cascade_closure"]["open_edges"]
    assert on.trace["cascade_closure"]["closed"] > off.trace["cascade_closure"]["closed"]
    for arm in (off, on):
        flat = [e[2] for e in arm.trace["cascade_closure"]["open_edges"]]
        assert "darkp" not in flat and "twin" not in flat


# ══ THE FLAG ════════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("val,want", [
    (None, 0), ("", 0), ("off", 0), ("OFF", 0), ("false", 0), ("no", 0), ("0", 0),
    ("on", pl._CLOSURE_RESERVE), ("true", pl._CLOSURE_RESERVE), ("yes", pl._CLOSURE_RESERVE),
    ("1", 1), ("2", 2), ("5", 5), ("-3", 0), ("banana", 0), ("3.5", 0),
])
def test_the_flag_defaults_off_and_fails_closed(monkeypatch, val, want):
    monkeypatch.delenv("GRAPHRAG_CLOSURE_RESERVE", raising=False)
    if val is not None:
        monkeypatch.setenv("GRAPHRAG_CLOSURE_RESERVE", val)
    assert pl._closure_reserve_n() == want


def test_the_kwarg_wins_over_the_env(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_CLOSURE_RESERVE", "9")
    assert pl._closure_reserve_n(0) == 0 and pl._closure_reserve_n(2) == 2


def test_the_env_flag_drives_the_walk(alias, monkeypatch):
    monkeypatch.setenv("GRAPHRAG_CLOSURE_RESERVE", "on")
    assert _res_ids(_walk(_chain_graph())) == ["mid", "root"]
    monkeypatch.setenv("GRAPHRAG_CLOSURE_RESERVE", "off")
    assert _res_ids(_walk(_chain_graph())) == []


# ══ graph.ancestors_by_depth ════════════════════════════════════════════════════════════════════════════
def test_ancestors_by_depth_matches_ancestors_on_the_whole_curated_estate():
    """Set parity with the shipped helper, over all 33 curated DAGs -- so the reservation can never spend a
    slot on a node `ancestors()` would not have named."""
    gr = g.CausalGraph.load()
    assert len(gr.contracts) >= 30
    seen_depth2 = 0
    for cid, c in gr.contracts.items():
        for d in c.drivers:
            byd = gr.ancestors_by_depth(cid, d.id)
            assert set(byd) == set(gr.ancestors(cid, d.id))
            assert all(v >= 1 for v in byd.values())
            seen_depth2 += sum(1 for v in byd.values() if v >= 2)
    assert seen_depth2 > 0, "the estate's parent DAG is 3-8 links deep; a flat result would be a defect"


def test_ancestors_by_depth_keeps_the_shallowest_path_and_survives_a_cycle():
    a = cs.Driver(id="a", type="hazard", sign="+", mechanism="m", parents=["b", "c"])
    b = cs.Driver(id="b", type="hazard", sign="+", mechanism="m", parents=["c"])
    c = cs.Driver(id="c", type="hazard", sign="+", mechanism="m")
    gr = g.CausalGraph({"k": cs.CausalContract(contract="k", drivers=[a, b, c])}, silver=set())
    assert gr.ancestors_by_depth("k", "a") == {"b": 1, "c": 1}     # c reachable at 1 and 2 -> 1 wins


# ══ ground() -> the citation join the D-GD-3 adjudicator counts from ════════════════════════════════════
def _retrieve(query, slice_, *, k, asof=None, near=None):
    return [{"date": "2026-01-0%d" % (i + 1), "source": "SRC", "source_key": f"{slice_}#{i}",
             "text": f"{slice_} row {i}"} for i in range(k)]


def test_ground_stamps_the_post_cap_citation_join(alias):
    sg = _walk(_chain_graph(), closure_reserve=3)
    pl.ground(sg, _QUERY, _chain_graph(), retrieve=_retrieve, silver_lookup=lambda *a, **k: None,
              asof="2026-08-08", driver_slices=set(_ALIAS), evidence_cap=48, k_by_depth=(5, 3))
    cc = sg.trace["cascade_closure"]
    assert cc["reserved_with_evidence"] == len(cc["reserved"]) >= 1
    assert cc["cited_join"], "the join must be POST-cap: a pre-cap join scores slots the cap already zeroed"
    # The first three join fields are exactly what verify's `report['resolved'][ref]` projects -- which is
    # what lets the counter exist with verify.py entirely untouched. R1 #2: the third field (verify's own
    # `snippet`) is what makes the key ROW-granular; source_key alone is a DOCUMENT key.
    # D-MW-15 RE-PIN: a FOURTH field carries the admission REASON, so eval can split n_cited into
    # upstream/downstream. The first three are byte-identical, so the join stays a pure read of verify.
    node = next(n for n in sg.nodes if n.id == "root")
    assert [h["source_key"] for h in node.evidence]
    for h in node.evidence:
        _t = h.get("text") or ""
        assert [h["source_key"], h["date"], _t[:140] + ("..." if len(_t) > 140 else ""),
                pl.REASON_CLOSURE] in cc["cited_join"]
    assert all(len(row) == 4 for row in cc["cited_join"])
    assert {row[3] for row in cc["cited_join"]} <= pl._STRUCTURAL_REASONS
    for r in cc["reserved"]:
        assert "_entry" not in r and r["n_evidence"] >= 0


def test_eval_counts_citations_landing_on_closure_admitted_nodes():
    from leviathan.graphrag import eval as ee
    out = {"trace": {
        "cascade_closure": {"enabled": True, "reserve_n": 3, "kept": 8, "count_delta": 0,
                            "closed": 2, "open": 1, "reserved_with_evidence": 1,
                            "reserved": [{"key": ["driver", "corn", "root"], "slice": "drivers/root_sl"}],
                            "displaced": [{"key": ["driver", "corn", "f8"]}],
                            "cited_join": [["s3://root/0", "2026-01-01", "root row 0"]]},
        "citation_verifier": {"enabled": True, "resolved": {
            "E1": {"source_key": "s3://root/0", "date": "2026-01-01T00:00:00", "source": "SRC",
                   "snippet": "root row 0"},
            "E2": {"source_key": "s3://anchor/0", "date": "2026-01-01", "source": "SRC",
                   "snippet": "anchor row 0"},
            # R1 #2: same DOCUMENT + same DATE as the reserved node's row, different PROPOSITION --
            # a cosine node's row that the 2-field join counted as a closure citation.
            "E3": {"source_key": "s3://root/0", "date": "2026-01-01", "source": "SRC",
                   "snippet": "a different proposition of the same document"}}}}}
    c = ee._closure_cited(out)
    assert c["n_cited"] == 1 and c["refs"] == ["E1"]          # E2/E3 landed on cosine rows -- not counted
    assert c["n_reserved"] == 1 and c["n_displaced"] == 1 and c["count_delta"] == 0
    assert c["open"] == 1 and c["closed"] == 2 and c["reserved_ids"] == ["root"]
    rec = ee._per_answer_record({"q": {"id": "r1"}, "out": out, "rubric": {}}, "single")
    assert rec["closure_cited"]["n_cited"] == 1              # ...and it REACHES the artifact
    assert rec["cascade_closure"]["open"] == 1               # ...as does the raw trace column (tracekeys)


def test_closure_cited_is_absent_shaped_on_a_pre_dgd_row():
    from leviathan.graphrag import eval as ee
    assert ee._closure_cited({"trace": {}}) == {}
    assert ee.closure_panel([{"q": {"id": "x"}, "out": {"trace": {}}}]) == []


def test_the_report_panel_names_an_instrument_dead_row():
    from leviathan.graphrag import eval as ee
    rows = [{"q": {"id": "dead"}, "out": {"trace": {"cascade_closure": {
        "enabled": True, "reserve_n": 3, "reserved": [], "displaced": [], "count_delta": 0,
        "open": 4, "closed": 0, "cited_join": []}}}}]
    txt = "\n".join(ee.closure_panel(rows))
    assert "INSTRUMENT-DEAD" in txt and "dead" in txt and "open edges **4**" in txt


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# R1 REGRESSION PINS (build review 2026-08-08) -- one per finding the reviewer BLOCKED on. Each reproduces
# the reviewer's own probe against the FIXED code; each fails if the fix is reverted.
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
def _wide_graph(n_fillers: int):
    """An UNDER-subscribed wave: an anchor with a 2-link backed chain plus a handful of fillers that all
    clear tau. At node_budget 16 the shipped walk keeps far fewer than 16 -- i.e. the case the reviewer
    measured as ~99% of real walks (tau, not the budget, is what ends them)."""
    return _corn([_drv("anchor", 0.95, parents=["mid"]), _drv("mid", 0.40, parents=["root"]),
                  _drv("root", 0.10)] + [_drv(f"f{i}", 0.90 - i * 0.01) for i in range(n_fillers)])


@pytest.fixture()
def alias_wide(monkeypatch):
    amap = {"anchor": "anchor_sl", "mid": "mid_sl", "root": "root_sl", "deep": "deep_sl",
            **{f"f{i}": f"f{i}_sl" for i in range(9)}}
    monkeypatch.setattr(ev, "backed_dag_ids", lambda: set(amap))
    monkeypatch.setattr(ev, "slice_for_driver", lambda d: amap.get(d))
    return amap


# ── R1 #1 -- HEADROOM FIRST: the reservation may not displace while the walk has an unspent slot ─────────
def test_r1_1_a_wave_with_free_budget_displaces_NOTHING(alias_wide):
    """THE BLOCKER, exactly. v1 paid for every reserved slot unconditionally, so the ON arm was the shipped
    walk MINUS 1-3 cosine-admitted drivers with 7-12 slots left idle, and a judged D-GD-3 delta would have
    conflated `+ancestors` with `-top drivers`. Under headroom-first a wave with spare slots displaces
    nothing at all and the ON arm is purely additive."""
    gr = _wide_graph(4)                                  # 1 seed + 5 above-tau drivers vs budget 16
    off = _walk(gr, closure_reserve=0, node_budget=16)
    on = _walk(gr, closure_reserve=3, node_budget=16)
    cc = on.trace["cascade_closure"]
    assert len(off.nodes) < 16, "fixture must leave real headroom, else the pin is vacuous"
    assert cc["reserved"], "and the reservation must actually fire"
    assert cc["displaced"] == [], "FREE budget was available -- nothing may be displaced"
    assert cc["headroom_used"] == len(cc["reserved"])
    assert {n.id for n in off.nodes} < {n.id for n in on.nodes}, "strictly additive: every OFF node survives"
    assert len(on.nodes) == len(off.nodes) + len(cc["reserved"]) <= 16


@pytest.mark.parametrize("budget", [4, 5, 6, 7, 8, 10, 16])
def test_r1_1_the_ceiling_holds_and_the_slots_always_balance(alias_wide, budget):
    """Sweep the boundary where headroom runs out mid-reservation: some slots come free, the rest displace.
    The ceiling is never crossed and every reserved slot is paid for exactly once."""
    gr = _wide_graph(6)
    base = _walk(gr, closure_reserve=0, node_budget=budget)
    on = _walk(gr, closure_reserve=3, node_budget=budget)
    assert _walk_state(on) == _walk_state(_walk(gr, closure_reserve=3, node_budget=budget))
    cc = on.trace["cascade_closure"]
    assert len(on.nodes) <= budget
    assert len(on.nodes) >= len(base.nodes)
    assert cc["count_delta"] == 0
    assert len(cc["reserved"]) == len(cc["displaced"]) + cc["headroom_used"]


# DELETED 2026-08-11, D-MW-15 (plan MOAT_WIDTH_WAVE_PLAN.md:591-604, the enumerated test re-scope):
#   test_r1_1_a_FULL_wave_still_pays_by_displacement
# The R7 amendment DISSOLVED the headroom-vs-displacement fork it was the other half of: under per-seed
# DEDICATED slots the reservation fires into its OWN allocation and displacement is not reached at all, so
# "a full wave still pays by displacement" is no longer a rule the shipped product has. The v1 env-driven
# path that DOES displace is still live and still pinned -- by
# test_pin3_node_count_and_k_are_invariant_under_the_reservation (full wave, headroom 0, displaced ==
# reserved), test_pin3_the_ceiling_binds_at_p3_width_too and
# test_displacement_takes_the_LOWEST_ranked_admitted_drivers -- so this deletion removes a duplicate of a
# retired rule, not the coverage of live code. The dedicated-slot posture it is replaced by is
# test_pin3_node_count_under_the_DEDICATED_slot_posture_is_additive_not_invariant.


# ── R1 #2 -- THE EVAL JOIN KEY IS ROW-GRANULAR, NOT DOCUMENT-GRANULAR ────────────────────────────────────
def _grounded_join(nodes):
    """Reproduce planner.ground()'s cited_join stamp over an already-capped node list."""
    join = []
    for n in nodes:
        if (n.admission or {}).get("reason") != "closure_reservation":
            continue
        for h in (n.evidence or []):
            t = h.get("text") or ""
            join.append([h.get("source_key"), str(h.get("date") or "")[:10],
                         t[:140] + ("..." if len(t) > 140 else "")])
    return join


def test_r1_2_a_citation_on_a_COSINE_row_of_a_SHARED_document_is_not_counted():
    """THE BLOCKER, exactly (reviewer case A1). `source_key` is a DOCUMENT key and `_dedup_and_cap`
    attributes each ROW once, not each DOCUMENT once -- so two propositions of one WASDE pdf legitimately
    survive on two different nodes. The 2-field key counted a citation on the COSINE node's row as a
    closure citation, and because the OFF arm has no reserved nodes (cited_join empty, n_cited structurally
    0) the miscount could only ever INFLATE THE TREATMENT."""
    from leviathan.graphrag import eval as ee
    DOC, DATE = "s3://wasde/2026-01.pdf", "2026-01-01"
    closure = _mk("root", 0.10, adm={"reason": "closure_reservation", "ancestor_of": "anchor",
                                     "chain_depth": 2}, n=0)
    closure.evidence = [{"source_key": DOC, "date": DATE, "text": "corn ending stocks fell"}]
    cosine = _mk("anchor", 0.95, n=0)
    cosine.evidence = [{"source_key": DOC, "date": DATE, "text": "soybean crush margin widened"}]
    pl._dedup_and_cap(pl.Subgraph(seeds=["corn"], nodes=[cosine, closure]), 24)
    assert cosine.evidence and closure.evidence, "both rows survive dedup -- its sig carries text[:80]"
    join = _grounded_join([cosine, closure])

    def _out(snippet):
        return {"trace": {"cascade_closure": {"enabled": True, "reserve_n": 3, "cited_join": join,
                                              "reserved": [{"key": ["driver", "corn", "root"],
                                                            "slice": "drivers/root_sl", "n_evidence": 1}],
                                              "reserved_with_evidence": 1, "count_delta": 0,
                                              "displaced": [], "open": 0, "closed": 1, "kept": 2},
                          "citation_verifier": {"enabled": True, "resolved": {
                              "E1": {"source_key": DOC, "date": DATE, "source": "WASDE",
                                     "snippet": snippet}}}}}
    # the model cited the COSINE node's row: same document, same date, DIFFERENT proposition.
    assert ee._closure_cited(_out("soybean crush margin widened"))["n_cited"] == 0
    # and the real thing still counts.
    assert ee._closure_cited(_out("corn ending stocks fell"))["n_cited"] == 1


def test_r1_2_the_join_snippet_is_verify_pys_own_projection_byte_for_byte():
    """The join may not invent a projection: it stamps EXACTLY what verify.py writes into
    report['resolved'][ref]['snippet'], so verify.py stays frozen (long text -> 140 chars + '...')."""
    import inspect

    from leviathan.graphrag import verify as vf
    assert '"snippet": txt[:140] + ("..." if len(txt) > 140 else "")' in inspect.getsource(vf), \
        "verify.py's snippet projection moved -- planner.ground's cited_join stamp must move WITH it"
    long = "x" * 300
    node = _mk("root", 0.1, adm={"reason": "closure_reservation", "ancestor_of": "a", "chain_depth": 1}, n=0)
    node.evidence = [{"source_key": "s3://d/0", "date": "2026-01-01", "text": long}]
    assert _grounded_join([node]) == [["s3://d/0", "2026-01-01", long[:140] + "..."]]


def test_r1_2_a_pre_fix_two_field_join_row_is_dropped_not_matched():
    """An artifact written before the fix is NOT silently re-interpreted document-granularly."""
    from leviathan.graphrag import eval as ee
    out = {"trace": {"cascade_closure": {"enabled": True, "reserve_n": 3,
                                         "cited_join": [["s3://d/0", "2026-01-01"]],
                                         "reserved": [{"key": ["driver", "corn", "root"]}],
                                         "displaced": [], "count_delta": 0},
                     "citation_verifier": {"resolved": {"E1": {"source_key": "s3://d/0",
                                                               "date": "2026-01-01", "snippet": "z"}}}}}
    assert ee._closure_cited(out)["n_cited"] == 0


# ── R1 #3 -- THE CENSUS POPULATION IS FIXED, SO `open` MOVES ONLY BY THE MECHANISM ───────────────────────
def _hub_graph():
    return _corn([_drv("anchor", 0.95, parents=["p1"]), _drv("p1", 0.20),
                  _drv("hub", 0.36, parents=[f"u{i}" for i in range(5)])]
                 + [_drv(f"u{i}", 0.10) for i in range(5)]
                 + [_drv(f"f{i}", 0.90 - i * 0.01) for i in range(4)])


@pytest.fixture()
def alias_hub(monkeypatch):
    amap = {"anchor": "a_sl", "p1": "p1_sl", "hub": "hub_sl",
            **{f"u{i}": f"u{i}_sl" for i in range(5)}, **{f"f{i}": f"f{i}_sl" for i in range(4)}}
    monkeypatch.setattr(ev, "backed_dag_ids", lambda: set(amap))
    monkeypatch.setattr(ev, "slice_for_driver", lambda d: amap.get(d))
    return amap


@pytest.mark.parametrize("budget", [6, 7, 8])
def test_r1_3_open_may_never_fall_by_more_than_the_edges_actually_closed(alias_hub, budget):
    """THE BLOCKER, exactly (reviewer case A3). `hub` is a LOW-ranked admitted driver carrying FIVE backed,
    slice-distinct, below-tau parents -- the maximal-open-edge node, which is exactly what
    lowest-ranked-first displacement targets. v1 counted the census over `kept`, so displacing `hub`
    DELETED all of its open edges while closing one: `open 6 -> 0`, a 6x overstatement of the wave's
    headline judge-free number. The population is fixed now, so a displaced driver's edges are still
    charged on BOTH arms."""
    off = _walk(_hub_graph(), closure_reserve=0, node_budget=budget)
    on = _walk(_hub_graph(), closure_reserve=1, node_budget=budget)
    a, b = off.trace["cascade_closure"], on.trace["cascade_closure"]
    assert (a["open"] - b["open"]) <= (b["closed"] - a["closed"]), (
        "budget=%d: open fell %d but only %d edges were closed -- census population leak"
        % (budget, a["open"] - b["open"], b["closed"] - a["closed"]))


def test_r1_3_a_displaced_drivers_open_edges_stay_in_the_census(alias_hub, monkeypatch):
    """RE-SCOPED TO A SYNTHETIC DISPLACED LIST (D-MW-15's enumerated re-scope). The pin's SUBJECT is
    `_closure_census`'s population rule -- 'a displaced driver's open parent edges are still charged' --
    and the original fixture reached it only through a walk that happened to displace. Under the
    dedicated-slot mechanism displacement is not reached at all, so a walk-shaped fixture would make the
    census rule untestable for the reason that has nothing to do with the census. The census is a pure
    function; it is now fed the displaced list directly, which also makes the pin exact rather than
    fixture-dependent.

    `hub` is the maximal-open-edge node (five backed, slice-distinct, below-tau parents) -- exactly what
    lowest-ranked-first displacement targeted, and exactly the case v1's kept-set population mis-measured
    at a 6x overstatement."""
    amap = alias_hub
    gr = _hub_graph()
    backed, slice_of = set(amap), (lambda d: amap.get(d))
    # the kept set AFTER a displacement: `hub` is gone, everything else stayed.
    nodes = [pl.GroundedNode(kind="driver", id=i, contract="corn", depth=1, relevance=0.5)
             for i in ["anchor", "p1"] + [f"f{k}" for k in range(4)]]
    for n in nodes:
        n.admission = dict(pl._ADMIT_COSINE)
    displaced = [{"key": ["driver", "corn", "hub"], "relevance": 0.36, "depth": 1}]
    with_disp = pl._closure_census(nodes, gr, backed, slice_of, displaced)
    without = pl._closure_census(nodes, gr, backed, slice_of, [])
    assert [e for e in with_disp["open_edges"] if e[1] == "hub"], "its open edges must still be charged"
    assert with_disp["open_edges_lost_with_displaced"] == 5   # published, not left to be re-derived
    assert with_disp["open"] - without["open"] == 5, "the whole 6x-overstatement class, as a number"
    assert with_disp["census_population"] == len(nodes) + 1   # the displaced driver IS in the population
    # ...and a STRUCTURALLY admitted node is on NEITHER side of the ledger (D-MW-15: both reasons).
    for reason in (pl.REASON_CLOSURE, pl.REASON_DOWNSTREAM):
        extra = pl.GroundedNode(kind="driver", id="hub", contract="corn", depth=1, relevance=0.0)
        extra.admission = {"reason": reason, "ancestor_of": "anchor", "chain_depth": 1}
        assert pl._closure_census(nodes + [extra], gr, backed, slice_of, [])["census_population"] \
            == without["census_population"], "a structural admission may not join the census population"


def test_r1_3_a_reserved_node_does_not_bring_its_OWN_parent_edges_into_the_census(alias_wide):
    """The other direction of the same population question: the treatment may not be charged (or credited)
    for edges that exist only because it admitted a node."""
    gr = _corn([_drv("anchor", 0.95, parents=["mid"]), _drv("mid", 0.40, parents=["root"]),
                _drv("root", 0.10, parents=["deep"]), _drv("deep", 0.05)]
               + [_drv(f"f{i}", 0.90 - i * 0.01) for i in range(3)])
    on = _walk(gr, closure_reserve=2, node_budget=16)
    cc = on.trace["cascade_closure"]
    assert "root" in {r["key"][2] for r in cc["reserved"]}
    assert not [e for e in cc["open_edges"] if e[1] == "root"], \
        "root is a closure admission, so root->deep is not a census edge on either arm"


# ── R1 #4 -- A CHAIN INTERIOR IS NEVER DISPLACED ─────────────────────────────────────────────────────────
def test_r1_4_an_already_admitted_intermediate_parent_is_never_displaced(alias_wide):
    """THE FINDING, exactly (reviewer case A2). `mid` clears tau, IS cosine-admitted, is skipped
    `already_admitted` by the reservation -- and was then the lowest-ranked driver available to displace.
    v1 kept the grandparent while deleting the link that earned it: `closed` went 1 -> 0 and `anchor->mid`
    became NEWLY OPEN, i.e. the reservation made its own metric strictly worse on the exact structure it
    targets."""
    gr = _corn([_drv("anchor", 0.95, parents=["mid"]), _drv("mid", 0.36, parents=["root"]),
                _drv("root", 0.10)] + [_drv(f"f{i}", 0.90 - i * 0.01) for i in range(6)])
    off = _walk(gr, closure_reserve=0, node_budget=8)
    on = _walk(gr, closure_reserve=1, node_budget=8)
    a, b = off.trace["cascade_closure"], on.trace["cascade_closure"]
    assert "mid" in {n.id for n in on.nodes}, "the chain interior must survive: it earns the grandparent"
    assert "mid" not in {d["key"][2] for d in b["displaced"]}
    assert b["closed"] >= a["closed"], "the reservation may never LOSE a closed edge"
    assert not (set(map(tuple, b["open_edges"])) - set(map(tuple, a["open_edges"]))), \
        "and no edge may become NEWLY open"


def test_r1_4_the_whole_ancestor_chain_of_an_anchor_is_protected_at_any_depth(alias_wide):
    """Protection is the FULL `ancestors_by_depth` closure of every anchor, not just the top anchor and not
    just its direct parents. Here `root` is a DEPTH-2 chain interior (anchor -> mid -> root -> deep) that
    clears tau, is cosine-admitted, and is the LOWEST-ranked driver in the wave -- so the unprotected rule
    picks exactly it, admits `deep`, and leaves the grandparent it just bought hanging off a deleted link."""
    gr = _corn([_drv("anchor", 0.95, parents=["mid"]), _drv("mid", 0.88, parents=["root"]),
                _drv("root", 0.36, parents=["deep"]), _drv("deep", 0.10)]
               + [_drv("f0", 0.90), _drv("f1", 0.89), _drv("f2", 0.87), _drv("f3", 0.86)])
    off = _walk(gr, closure_reserve=0, node_budget=8)
    on = _walk(gr, closure_reserve=3, node_budget=8)
    cc = on.trace["cascade_closure"]
    disp = {d["key"][2] for d in cc["displaced"]}
    assert "root" in {n.id for n in off.nodes}, "the fixture must cosine-admit the depth-2 interior"
    assert "deep" in {r["key"][2] for r in cc["reserved"]}, "and the reservation must reach past it"
    assert disp, "and it must have had to pay by displacement, else the pin is vacuous"
    assert not ({"anchor", "mid", "root", "deep"} & disp), \
        "no driver on an anchor's ancestor chain may be displaced, at any depth"


# ── R1 #5 -- focus_driver IS DISPLACEMENT-PROTECTED (the post-walk re-inject can't cross the ceiling) ────
def test_r1_5_the_focus_driver_is_never_displaced(alias_wide):
    """THE FINDING, exactly (reviewer case A6). answer._answer_l2 re-injects `focus_driver` post-walk with
    NO budget accounting, so a reservation that displaced it grew the turn's node count on the ON arm only
    -- past the `len(kept) <= node_budget` ceiling pin 3 exists to hold (the 17-node number was the
    BEDROCK lane's quota cliff, retired as a walk law by D-MW-11). It now rides into the walk as a
    displacement fence."""
    gr = _wide_graph(6)
    victims = [d["key"][2] for d in _walk(gr, closure_reserve=3,
                                          node_budget=8).trace["cascade_closure"]["displaced"]]
    assert victims, "fixture must displace something when unfenced, else the pin is vacuous"
    focus = victims[0]
    off = _walk(gr, closure_reserve=0, node_budget=8, focus_driver=focus)
    on = _walk(gr, closure_reserve=3, node_budget=8, focus_driver=focus)
    assert focus not in {d["key"][2] for d in on.trace["cascade_closure"]["displaced"]}
    assert any(n.id == focus for n in on.nodes), "so the post-walk re-inject never fires on the ON arm"

    def _inject(sg):                                     # answer.py:1876, verbatim in shape
        if not any(n.kind == "driver" and n.id == focus for n in sg.nodes):
            sg.nodes.append(pl.GroundedNode(kind="driver", id=focus, contract="corn", depth=1,
                                            relevance=1.0))
    _inject(off)
    _inject(on)
    assert len(off.nodes) == len(on.nodes) <= 8


def test_r1_5_focus_driver_is_a_strict_noop_when_the_reservation_is_off(alias_wide):
    gr = _wide_graph(6)
    assert _walk_state(_walk(gr, closure_reserve=0)) == \
        _walk_state(_walk(gr, closure_reserve=0, focus_driver="f3"))


def test_r1_5_answer_threads_the_focus_driver_into_the_walk(monkeypatch):
    """The fence is only real if the SERVING call passes it -- the reviewer's probe failed precisely
    because the walk call did not. Captured at the seam, not grepped: with a focus_driver the walk call
    carries it, and WITHOUT one the walk call is byte-identical (omit-when-empty, the house idiom that
    `test_dam_modes.test_walk_and_ground_kwargs_are_untouched_on_standard_and_dark` pins)."""
    import types

    from leviathan.graphrag import answer as an

    class _Stop(Exception):
        pass

    def _capture(focus):
        seen = {}

        def _gs(query, graph, **kw):
            seen.update(kw)
            return types.SimpleNamespace(nodes=[], seeds=[], trace={}, fired_regimes=[], mermaid="")

        def _ground(sg, query, graph, **kw):
            raise _Stop
        monkeypatch.setattr(pl, "grounded_subgraph", _gs)
        monkeypatch.setattr(pl, "ground", _ground)
        gr = _corn([_drv("d0", 0.9)])
        kw = {"focus_driver": focus} if focus else {}
        with pytest.raises(_Stop):
            an.answer("why is corn bid", graph=gr, asof="2026-08-08", planner="l2",
                      call=lambda *a, **k: {"tldr": "x", "mechanism": "y", "sources": []},
                      route_fn=lambda q, gg: ["corn"], **kw)
        return seen

    assert _capture("d0").get("focus_driver") == "d0", \
        "answer._answer_l2 must thread focus_driver into pl.grounded_subgraph"
    assert set(_capture(None)) == {"route_fn"}, \
        "and must add NO kwarg on a turn with no live-event root"


# ── R1 #6 -- A ZERO-RELEVANCE RESERVED NODE STILL GETS A ROW UNDER cap_policy='score' ────────────────────
@pytest.mark.parametrize("rel", [0.0, 0.05])
def test_r1_6_a_reserved_node_with_zero_relevance_is_still_citable_under_the_score_policy(rel):
    """`share = max(rel,0)/tot_rel` -> `q = ceil(cap*share) = 0` for rel EXACTLY 0.0, which is what a
    tau-exempt reserved node with no wave tombstone carries (planner._closure_plan:297). Pin 1's
    score-policy twin only ever tested 0.05, so the self-cancel was reopened through the QUOTA instead of
    through the ORDER."""
    anchor = _mk("anchor", 0.95)
    reserved = _mk("root", rel, adm={"reason": "closure_reservation", "ancestor_of": "anchor",
                                     "chain_depth": 1})
    nodes = [anchor, *[_mk(f"f{i}", 0.9 - i * 0.01) for i in range(3)], reserved]
    pl._dedup_and_cap(pl.Subgraph(seeds=["corn"], nodes=list(nodes)), 12,
                      cap_policy="score", k_by_depth=(7, 5))
    assert reserved.evidence, "a slot was spent; the node must be citable (rel=%r)" % rel
    assert sum(len(n.evidence) for n in nodes) <= 12, "and the cap total still holds"


def test_r1_6_the_floor_does_not_apply_to_a_plain_cosine_node():
    """The floor is scoped to the admission reason -- it is not a general 'every node gets a row' change."""
    zero = _mk("z", 0.0)
    nodes = [_mk("anchor", 0.95, n=12), zero]
    pl._dedup_and_cap(pl.Subgraph(seeds=["corn"], nodes=list(nodes)), 12,
                      cap_policy="score", k_by_depth=(0,))
    assert zero.evidence == []
