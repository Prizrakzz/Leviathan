"""D-MW P3 (2026-08-11) — THE WALK + GRAPH ADMISSION V2 CORE.

What this file pins, and why each pin exists (every one names a defect the plan or its reviews caught):

  SEED-SCALED WIDTH (D-MW-13)   `max_seeds` is a tier CEILING; the walk's budgets scale from the REALIZED
                                seed count. STEP-0 measured per-seed cosine demand at p75 63 and eligible-
                                ancestor supply at p75 4 (plan 12a), so `max` carries 63 + 4 PER SEED. A
                                flat node_budget at 6 seeds would have been the same one-market answer with
                                more siblings -- the number has to multiply or the ceiling is theatre.
  DEDICATED SLOTS (D-MW-15 i)   Graph admission fires into its OWN per-seed allocation, ADDITIVE by
                                construction. The headroom-vs-displacement fork DISSOLVED with R7: cosine
                                and structural admission can no longer displace each other at all. Slots
                                that cannot be filled stay EMPTY -- instrument-dead, declared, NEVER
                                backfilled with cosine (backfilling re-creates the substitution).
  PER-SEED OWNERSHIP (ii)       Seed A's candidates may not consume seed B's slots. Without this the
                                one-market question with a deep DAG eats the whole reserve and the
                                multi-market row -- the entire point of the width -- gets nothing.
  QUERY-SCORED SELECTION        Eligible candidates are ordered by cos(query, mechanism) off the walk's own
                                cache, not by chain position. v1's mis-targeting class.
  DOWNSTREAM (iv)               `cascade_downstream` admissions via the new PUBLIC
                                graph.descendants_by_depth. Honest framing: NOT new reach -- structural
                                RE-ADMISSION of siblings tau or the budget dropped, visible as such in the
                                audit trail. It must clear all three structural guards, or it lands with
                                zero evidence rows: the admitted-but-not-cited defect P3-A exists to prove
                                fixed.
  CONVERGENCE (v)               A candidate >= 2 admitted anchors' chains reach is tagged and counted.
  THE HOP FENCE (D-MW-13)       depth=2 without it ships P6's contract-admission path unbudgeted: a d==1
                                hop contract enqueues its OWN tracked cross_links, and second-order hop
                                CONTRACTS sort ahead of every driver at ~2.8k tokens each. Depth 2 buys hop
                                DRIVERS only. At depth 1 the fence is a no-op BY CONSTRUCTION.
  walk_shape / n_evidence_chars Four P3 RECORDED quantities had no artifact source (D-MW-13), and D-MW-17's
                                token-denominated-budget decision needs a measured char distribution.

Pure/offline: injected embed, injected retrieve, no S3, no pg, no LLM, no spend.
"""
from __future__ import annotations

import math

import pytest
from leviathan.causal import schema as cs
from leviathan.graphrag import graph as g
from leviathan.graphrag import planner as pl

# ── the fixture: an exact-cosine embedder (same device as test_dgd_closure_reservation) ──────────────────
# Each text maps to the unit vector [r, sqrt(1-r^2)] and the query to [1, 0], so cos == r EXACTLY. That is
# what lets a pin say "this candidate scores 0.10, below tau 0.35" and mean it.
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
    mech = f"m::{id_}"
    _REL[mech] = rel
    return cs.Driver(id=id_, type=kw.pop("type", "hazard"), sign=kw.pop("sign", "+"), mechanism=mech, **kw)


def _contract(cid, drivers, hops=()):
    return cs.CausalContract(
        contract=cid, aliases=[cid], drivers=drivers,
        inter_commodity=[cs.InterCommodityEdge(driver_commodity=h, relation="substitutes_for", sign="-",
                                               mechanism=f"x::{cid}::{h}") for h in hops])


def _graph(*contracts) -> g.CausalGraph:
    return g.CausalGraph({c.contract: c for c in contracts}, silver=set())


def _walk(graph, seeds, **kw):
    """Hermetic walk. `driver_slices` makes every driver id its own slice path, so 'backed' and
    'slice-distinct' are both true by construction and the eligibility filters stay out of the way of the
    mechanism these pins are about (test_dgd_closure_reservation owns the eligibility filters)."""
    kw.setdefault("depth", 1)
    kw.setdefault("tau", 0.35)
    kw.setdefault("node_budget", 64)
    kw.setdefault("max_seeds", 6)
    kw.setdefault("driver_slices", {d.id for c in graph.contracts.values() for d in c.drivers})
    return pl.grounded_subgraph(_QUERY, graph, embed=_embed, route_fn=lambda q, gr: list(seeds), **kw)


def _ids(sg):
    return {n.id for n in sg.nodes}


def _cc(sg):
    return sg.trace["cascade_closure"]


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    """Every pin here is about the KWARGS. The env flag is exercised explicitly where it is the subject."""
    monkeypatch.delenv("GRAPHRAG_CLOSURE_RESERVE", raising=False)


# ── the fixtures ────────────────────────────────────────────────────────────────────────────────────────
def _two_market_graph(n_fill=12):
    """Two independent seeds. `alpha` carries a 3-link backed chain of BELOW-tau ancestors (the reserve's
    supply); `beta` carries none at all (the instrument-dead seed)."""
    alpha = _contract("alpha", [_drv("a_anchor", 0.95, parents=["a_p1"]),
                                _drv("a_p1", 0.10, parents=["a_p2"]),
                                _drv("a_p2", 0.10, parents=["a_p3"]),
                                _drv("a_p3", 0.10)]
                      # a shallow decrement so a WIDE fixture (80 fillers) stays entirely above tau --
                      # else the walk ends on supply and the budget derivation is never exercised.
                      + [_drv(f"a_f{i}", 0.90 - i * 0.001) for i in range(n_fill)])
    beta = _contract("beta", [_drv(f"b_f{i}", 0.90 - i * 0.001) for i in range(n_fill)])
    return _graph(alpha, beta)


# ══ SEED-SCALED BUDGET DERIVATION (D-MW-13) ══════════════════════════════════════════════════════════════
@pytest.mark.parametrize("per_seed,n_seeds", [(63, 1), (63, 2), (12, 2), (4, 2)])
def test_the_cosine_budget_is_per_seed_budget_times_the_REALIZED_seed_count(per_seed, n_seeds):
    """`node_budget` becomes `per_seed_budget x n`, where n is the seed count the router REALIZED -- never
    `max_seeds`, which is only the ceiling. The flat `node_budget` kwarg is IGNORED outright when the
    per-seed knob is present: two producers of one number is how they drift apart."""
    gr = _two_market_graph(n_fill=80)
    seeds = ["alpha", "beta"][:n_seeds]
    sg = _walk(gr, seeds, node_budget=999, per_seed_budget=per_seed, max_seeds=6)
    assert sg.trace["walk_shape"]["n_seeds"] == n_seeds
    assert sg.trace["budget"] == per_seed * n_seeds
    assert sg.trace["params"]["node_budget"] == per_seed * n_seeds
    assert len(sg.nodes) == per_seed * n_seeds, "the fixture must SATURATE, else the derivation is untested"


def test_the_ceiling_is_the_ceiling_not_the_realized_count():
    """max_seeds 6 with a router that returns 2 -> the budget scales from 2, not from 6. The R7 change is
    that the CEILING stops being the fan-in number; a walk that scaled from the ceiling would buy 4 seeds'
    worth of slots for a two-market question."""
    gr = _two_market_graph(n_fill=80)
    sg = _walk(gr, ["alpha", "beta"], per_seed_budget=10, max_seeds=6)
    assert sg.trace["budget"] == 20 and len(sg.seeds) == 2


def test_the_reserve_is_per_seed_reserve_times_the_realized_seed_count_and_is_ADDITIVE():
    """63 cosine + 4 reserve per seed is the RATIFIED `max` shape (plan 12a). The reserve is spent on TOP
    of the cosine budget -- `charged <= budget` is the law, `len(kept)` may exceed it by the filled slots,
    and count_delta stays 0 because every slot is paid for by a DEDICATED allocation."""
    gr = _two_market_graph(n_fill=40)
    off = _walk(gr, ["alpha", "beta"], per_seed_budget=8, per_seed_reserve=0)
    on = _walk(gr, ["alpha", "beta"], per_seed_budget=8, per_seed_reserve=4)
    cc = _cc(on)
    assert len(off.nodes) == 16, "both arms run at IDENTICAL width -- that is the one-variable law"
    assert cc["reserve_slots"]["total"] == 4 * 2 == 8
    assert cc["dedicated"] is True and cc["per_seed_reserve"] == 4 and cc["n_seeds"] == 2
    assert cc["reserve_slots"]["filled"] == len(cc["reserved"]) == cc["dedicated_used"] > 0
    assert len(on.nodes) == len(off.nodes) + cc["reserve_slots"]["filled"]
    assert cc["displaced"] == [] and cc["headroom_used"] == 0 and cc["count_delta"] == 0
    assert _ids(off) < _ids(on), "strictly additive: cosine admission cannot be displaced by the reserve"


# ══ PER-SEED OWNERSHIP + THE EMPTY SLOT (D-MW-15 i/ii) ═══════════════════════════════════════════════════
def test_seed_As_ancestors_cannot_consume_seed_Bs_slots():
    """THE OWNERSHIP LAW. `alpha` has a 3-link chain of eligible below-tau ancestors; `beta` has none. With
    2 slots per seed the walk may fill AT MOST 2 from alpha -- alpha's third ancestor is eligible, scores
    above beta's non-existent supply, and must STILL be refused, because the slot it wants belongs to beta.
    A pooled reserve would hand the whole allocation to whichever market has the deeper DAG."""
    gr = _two_market_graph()
    on = _walk(gr, ["alpha", "beta"], per_seed_budget=8, per_seed_reserve=2)
    cc = on.trace["cascade_closure"]
    assert cc["reserve_slots"]["total"] == 4
    by_seed = cc["reserve_slots"]["by_seed"]
    assert by_seed["alpha"] == {"total": 2, "filled": 2}
    assert by_seed["beta"] == {"total": 2, "filled": 0}
    assert {r["origin"] for r in cc["reserved"]} == {"alpha"}
    assert all(r["contract"] == "alpha" for r in cc["reserved"])
    # the refused third link is RECORDED as a slot decision, not silently dropped
    assert any(s["reason"] == "no_slot" and s["origin"] == "alpha" for s in cc["skipped"])


def test_an_unfillable_slot_stays_EMPTY_and_is_never_backfilled_with_cosine():
    """INSTRUMENT-DEAD, DECLARED. `beta`'s two slots have no eligible candidate at all. They must stay
    empty and be readable as empty -- and the walk must NOT hand them to cosine, which would re-create the
    substitution the dedicated slots exist to remove (and would make the P3-A arms differ by node COUNT
    as well as by admission, i.e. by two variables)."""
    gr = _two_market_graph()
    off = _walk(gr, ["alpha", "beta"], per_seed_budget=8, per_seed_reserve=2)
    cc = off.trace["cascade_closure"]
    assert cc["reserve_slots"]["empty"] == 2 == cc["reserve_slots"]["total"] - cc["reserve_slots"]["filled"]
    # the cosine population is IDENTICAL to the reservation-off arm: nothing backfilled the dead slots.
    base = _walk(gr, ["alpha", "beta"], per_seed_budget=8, per_seed_reserve=0)
    cosine_on = {n.id for n in off.nodes
                 if (n.admission or {}).get("reason") not in pl._STRUCTURAL_REASONS}
    assert cosine_on == _ids(base)


def test_a_wave_1_reserve_admission_does_not_eat_wave_2s_COSINE_budget():
    """THE ADDITIVITY LAW WHERE IT ACTUALLY BINDS -- ACROSS WAVES (found by a mutation check: charging the
    reserve to the cosine budget is INERT in a single-wave fixture, because that wave's admissions were
    already decided by the plan's own `final` set; the substitution only shows up in the NEXT wave).

    Here wave 1 admits a tracked hop + 3 drivers and fills 2 reserve slots; wave 2 then wants all 4 of the
    hop contract's drivers and the cosine budget covers exactly that. If the reserve were charged to the
    cosine budget, two of wave 2's hop drivers would be silently displaced by graph admission -- the exact
    depth-2 substitution the plan's round-2 review flagged as invisible to count_delta."""
    _REL["x::alpha::beta"] = 0.99
    gr = _graph(_contract("alpha", [_drv("anchor", 0.95, parents=["p1"]),
                                    _drv("p1", 0.10, parents=["p2"]), _drv("p2", 0.10),
                                    _drv("f1", 0.90), _drv("f2", 0.89)], hops=["beta"]),
                _contract("beta", [_drv(f"b{i}", 0.90 - i * 0.01) for i in range(4)]))
    off = _walk(gr, ["alpha"], depth=2, per_seed_budget=9, per_seed_reserve=0)
    on = _walk(gr, ["alpha"], depth=2, per_seed_budget=9, per_seed_reserve=2)
    cc = _cc(on)
    assert cc["reserve_slots"]["filled"] == 2, "the fixture must fill its slots in WAVE 1"
    assert {n.id for n in off.nodes if n.depth == 2} == {"b0", "b1", "b2", "b3"}, \
        "the OFF arm's wave 2 must be FULL, else the pin cannot see a displacement"
    cosine_on = {n.id for n in on.nodes
                 if (n.admission or {}).get("reason") not in pl._STRUCTURAL_REASONS}
    assert cosine_on == _ids(off), "wave 2 lost nothing: the reserve is charged to its own allocation"
    assert on.trace["walk_shape"]["kept_by_depth"]["2"] == 4


# ══ THE KWARG-WINS PIN (D-MW-13: 0 is a VALUE, not None) ════════════════════════════════════════════════
def test_per_seed_reserve_zero_forces_the_reservation_OFF_even_with_the_env_SET(monkeypatch):
    """THE `max_c0` CONSTRUCTIBILITY PIN. The closure kwarg beats the env OUTRIGHT (a shipped precedence),
    so "max with admission OFF" has to be expressible as a VALUE. `0` must survive `knobs()` filtering and
    kill the reservation while every other knob stays at max's width -- that is what makes the two P3-A
    arms differ by exactly ONE variable."""
    monkeypatch.setenv("GRAPHRAG_CLOSURE_RESERVE", "3")
    gr = _two_market_graph()
    c0 = _walk(gr, ["alpha", "beta"], per_seed_budget=8, per_seed_reserve=0)
    assert _cc(c0)["reserved"] == [] and _cc(c0)["enabled"] is False
    assert _cc(c0)["reserve_n"] == 0 and _cc(c0)["dedicated"] is False
    # ...and with the dedicated knob ON, the DEDICATED size wins over the env's 3 as well.
    on = _walk(gr, ["alpha", "beta"], per_seed_budget=8, per_seed_reserve=2)
    assert _cc(on)["reserve_n"] == 4 and _cc(on)["dedicated"] is True
    # the one-variable law, asserted as an identity: the two arms' COSINE populations are the same set.
    cosine_on = {n.id for n in on.nodes
                 if (n.admission or {}).get("reason") not in pl._STRUCTURAL_REASONS}
    assert cosine_on == _ids(c0)


def test_both_none_is_the_legacy_walk_byte_for_byte(monkeypatch):
    """PIN 2's D-MW twin. With both per-seed kwargs absent the walk is the shipped v1 one, env path and
    all -- so quick/standard/deep (which carry neither knob) cannot move by a byte when P3 ships."""
    gr = _two_market_graph()

    def state(sg):
        return ([(n.key, n.depth, n.relevance, n.prior, n.via_edge) for n in sg.nodes], sg.mermaid,
                sg.seeds, {k: v for k, v in sg.trace.items()
                           if k in ("seeds", "kept", "pruned", "visited", "budget", "params")})
    plain = _walk(gr, ["alpha", "beta"], node_budget=12)
    nones = _walk(gr, ["alpha", "beta"], node_budget=12, per_seed_budget=None, per_seed_reserve=None)
    assert state(plain) == state(nones)
    assert _cc(nones)["dedicated"] is False and _cc(nones)["reserve_slots"]["by_seed"] == {}
    # the v1 env path still drives the walk when the per-seed knob is ABSENT (it is not disabled, it is
    # superseded only when declared).
    monkeypatch.setenv("GRAPHRAG_CLOSURE_RESERVE", "2")
    env_on = _walk(gr, ["alpha", "beta"], node_budget=12)
    assert len(_cc(env_on)["reserved"]) == 2 and _cc(env_on)["dedicated"] is False
    assert _cc(env_on)["dedicated_used"] == 0


# ══ THE HOP FENCE (D-MW-13) ═════════════════════════════════════════════════════════════════════════════
def _hop_chain_graph():
    """alpha -> beta -> gamma, every edge TRACKED. At depth 2 the beta->gamma enqueue is the second-order
    hop the fence exists to stop (measured: 19/33 walks reach >= 1 at d==2)."""
    _REL["x::alpha::beta"] = 0.99
    _REL["x::beta::gamma"] = 0.99
    return _graph(_contract("alpha", [_drv("a1", 0.90)], hops=["beta"]),
                  _contract("beta", [_drv("b1", 0.88)], hops=["gamma"]),
                  _contract("gamma", [_drv("c1", 0.99)]))


def test_the_fence_skips_a_second_order_hop_and_counts_it():
    """Depth 2 buys hop DRIVERS (~216 chars on an already-paid contract block), never a second hop
    CONTRACT (~2.8k tokens, and it sorts AHEAD of every driver on the is_hop comparator). `gamma` must be
    absent, `beta`'s own driver must be present, and the skip must be COUNTED -- an unrecorded fence is
    indistinguishable from an empty graph at the P3 record."""
    sg = _walk(_hop_chain_graph(), ["alpha"], depth=2, per_seed_budget=32)
    keys = {(n.kind, n.contract) for n in sg.nodes}
    assert ("contract", "beta") in keys, "the FIRST-order hop still lands"
    assert ("contract", "gamma") not in keys, "the SECOND-order hop contract is fenced"
    assert "b1" in _ids(sg), "and depth 2 still buys the hop contract's DRIVERS -- the whole point"
    assert "c1" not in _ids(sg)
    assert sg.trace["walk_shape"]["fenced_second_order_hops"] == 1
    assert sg.trace["walk_shape"]["hop_contracts"] == 1


def test_the_fence_is_a_noop_at_depth_1():
    """BYTE-IDENTITY WHERE IT SHIPS. Every serving preset today walks depth 1, where a d==0 seed's hop
    lands at d==1 and `d >= depth` stops the expansion before any cross_links call -- so the fence cannot
    fire, and the counter proves it rather than the docstring asserting it."""
    sg = _walk(_hop_chain_graph(), ["alpha"], depth=1, per_seed_budget=32)
    assert sg.trace["walk_shape"]["fenced_second_order_hops"] == 0
    assert ("contract", "beta", "beta") in {n.key for n in sg.nodes}, "the first-order hop is untouched"
    assert "c1" not in _ids(sg) and "b1" not in _ids(sg)


def test_the_fence_leaves_the_DEFAULT_walk_alone_and_fires_only_on_the_seed_scaled_one():
    """THE MISSING INVARIANCE PIN (P3 round-1). The SHIPPED DEFAULT depth is 2 -- `planner._DEPTH`, from
    configs/graphrag/params.yaml -- and `standard`/unmoded turns carry all-None knobs, so an UNCONDITIONAL
    fence re-cut the default product path: measured over the 33 curated DAGs at shipped defaults, 7/33
    walks fired it and 2/33 moved `visited`/`pruned`. This runs the module-DEFAULT depth (never a literal
    2 -- if the default moves, this pin must move with it) and asserts the fenced-vs-shipped comparison
    both ways: with `per_seed_budget` ABSENT the second-order hop contract is admitted exactly as pre-P3
    and the counter is 0; with it PRESENT the fence fires. Both P3-A arms carry the per-seed budget, so the
    fence still rides both."""
    assert pl._DEPTH >= 2, "this pin is about the DEFAULT walk reaching depth 2"
    gr = _hop_chain_graph()
    legacy = pl.grounded_subgraph(_QUERY, gr, embed=_embed, route_fn=lambda q, g_: ["alpha"],
                                  node_budget=32, tau=0.35,
                                  driver_slices={d.id for c in gr.contracts.values() for d in c.drivers})
    assert legacy.trace["params"]["depth"] == pl._DEPTH
    assert legacy.trace["walk_shape"]["fenced_second_order_hops"] == 0
    assert ("contract", "gamma", "gamma") in {n.key for n in legacy.nodes}, \
        "UNFENCED: the pre-P3 walk admits the second-order hop contract, and this wave may not move it"
    assert legacy.trace["walk_shape"]["hop_contracts"] == 2      # beta at d==1 AND gamma at d==2
    # ...and the same walk WITH the seed-scaled budget is the fenced one.
    fenced = pl.grounded_subgraph(_QUERY, gr, embed=_embed, route_fn=lambda q, g_: ["alpha"],
                                  per_seed_budget=32, tau=0.35,
                                  driver_slices={d.id for c in gr.contracts.values() for d in c.drivers})
    assert fenced.trace["walk_shape"]["fenced_second_order_hops"] == 1
    assert ("contract", "gamma", "gamma") not in {n.key for n in fenced.nodes}


# ══ walk_shape (D-MW-13) ════════════════════════════════════════════════════════════════════════════════
def test_walk_shape_is_stamped_on_every_walk_and_its_counts_reconcile():
    gr = _two_market_graph()
    sg = _walk(gr, ["alpha", "beta"], per_seed_budget=6, per_seed_reserve=2)
    ws = sg.trace["walk_shape"]
    assert set(ws) == {"n_seeds", "kept_by_depth", "hop_contracts", "fenced_second_order_hops"}
    assert ws["n_seeds"] == 2 == len(sg.seeds)
    assert sum(ws["kept_by_depth"].values()) == len(sg.nodes)
    assert ws["kept_by_depth"]["0"] == 2, "the seeds are the depth-0 nodes"
    assert ws["kept_by_depth"]["1"] == len(sg.nodes) - 2
    assert all(isinstance(k, str) for k in ws["kept_by_depth"]), "JSON-stable keys (this rides an artifact)"
    assert ws["hop_contracts"] == 0 and ws["fenced_second_order_hops"] == 0


def test_walk_shape_is_registered_in_the_trace_key_registry():
    """The C2/U3 class: a stamped key that eval never lifts reaches NO artifact, silently -- and every P3
    RECORDED clause (seed distribution, wave-2 hop-driver count, the fence count) reads THIS key."""
    from leviathan.graphrag import tracekeys as tk
    assert "walk_shape" in tk.TRACE_RECORD_KEYS
    assert "n_evidence_chars" in tk.TRACE_RECORD_KEYS


# ══ CONVERGENCE TAGGING (D-MW-15 v) ═════════════════════════════════════════════════════════════════════
def _convergent_graph():
    """Two admitted anchors whose chains MEET at `shared` -- the convergence the doctrine says must be
    surfaced. `shared` is below tau, so only a structural admission reaches it."""
    return _graph(_contract("alpha", [_drv("anchor1", 0.95, parents=["shared"]),
                                      _drv("anchor2", 0.94, parents=["shared"]),
                                      _drv("solo", 0.93, parents=["only1"]),
                                      _drv("shared", 0.10), _drv("only1", 0.10)]))


def test_a_candidate_two_anchors_reach_is_tagged_convergent_and_counted():
    sg = _walk(_convergent_graph(), ["alpha"], per_seed_budget=8, per_seed_reserve=2)
    cc = _cc(sg)
    rec = next(r for r in cc["reserved"] if r["key"][2] == "shared")
    assert rec.get("convergence") is True
    assert sorted(rec["anchors"]) == ["anchor1", "anchor2"]
    assert rec["ancestor_of"] == "anchor1", "ancestor_of is the HIGHEST-RANKED anchor that reached it"
    node = next(n for n in sg.nodes if n.id == "shared")
    assert node.admission["convergence"] is True and node.admission["anchors"] == rec["anchors"]
    # a single-anchor admission carries NEITHER optional field -- the record shape stays minimal.
    solo = next(r for r in cc["reserved"] if r["key"][2] == "only1")
    assert "convergence" not in solo and "anchors" not in solo
    assert cc["n_convergence"] == 1


def test_n_convergence_is_stamped_zero_on_the_off_arm():
    """Both arms stamp it, same reason `open` is stamped on both: an unstamped arm is an uncomparable arm
    (the served_rows lesson -- an adjudication that needs a re-run is not an adjudication)."""
    sg = _walk(_convergent_graph(), ["alpha"], per_seed_budget=8, per_seed_reserve=0)
    assert _cc(sg)["n_convergence"] == 0 and _cc(sg)["n_downstream"] == 0


# ══ QUERY-SCORED SELECTION (D-MW-15 ii) ═════════════════════════════════════════════════════════════════
def test_eligible_ancestors_are_ordered_by_the_QUERY_not_by_chain_position():
    """v1 spent its slots NEAREST-PARENT-FIRST, so the slot bought whatever the chain happened to start
    with. Here the DEEPEST ancestor (`p3`, chain_depth 3) is the one the query is about and the direct
    parent (`p1`) is nearly irrelevant; with one slot the query must win. The scores come off the walk's
    OWN `_relevance` cache -- same embedder, same scale, no second cache to drift."""
    gr = _graph(_contract("alpha", [_drv("anchor", 0.95, parents=["p1"]),
                                    _drv("p1", 0.05, parents=["p2"]),
                                    _drv("p2", 0.10, parents=["p3"]),
                                    _drv("p3", 0.34)]))          # below tau (0.35), but the best of the three
    sg = _walk(gr, ["alpha"], per_seed_budget=8, per_seed_reserve=1)
    assert [r["key"][2] for r in _cc(sg)["reserved"]] == ["p3"]
    assert _cc(sg)["reserved"][0]["relevance_q"] == pytest.approx(0.34, abs=1e-3)
    # v1's rule, for contrast: nearest-parent-first would have bought `p1` (chain_depth 1).
    v1 = _walk(gr, ["alpha"], node_budget=8, closure_reserve=1)
    assert [r["key"][2] for r in _cc(v1)["reserved"]] == ["p1"]


# ══ DOWNSTREAM ADMISSION (D-MW-15 iv) + graph.descendants_by_depth ══════════════════════════════════════
def _downstream_graph():
    """`anchor` has NO parents (no upstream supply at all) and one below-tau CHILD. The only thing a
    reserve slot can buy here is the downstream re-admission."""
    return _graph(_contract("alpha", [_drv("anchor", 0.95),
                                      _drv("kid", 0.10, parents=["anchor"]),
                                      _drv("grandkid", 0.10, parents=["kid"])]
                            + [_drv(f"f{i}", 0.90 - i * 0.01) for i in range(6)]))


def test_a_downstream_child_is_admitted_with_the_cascade_downstream_reason_and_a_negative_depth():
    sg = _walk(_downstream_graph(), ["alpha"], per_seed_budget=8, per_seed_reserve=2)
    cc = _cc(sg)
    got = {r["key"][2]: r for r in cc["reserved"]}
    assert set(got) == {"kid", "grandkid"}
    assert all(r["reason"] == pl.REASON_DOWNSTREAM for r in got.values())
    assert got["kid"]["chain_depth"] == -1 and got["grandkid"]["chain_depth"] == -2, "negative = downstream"
    assert cc["n_downstream"] == 2
    node = next(n for n in sg.nodes if n.id == "kid")
    assert node.admission["reason"] == pl.REASON_DOWNSTREAM and node.admission["ancestor_of"] == "anchor"
    # HONEST FRAMING (the plan's own): these are siblings tau dropped, RE-admitted -- not new reach.
    assert ("driver", "alpha", "kid") in {tuple(p["key"]) for p in
                                          _walk(_downstream_graph(), ["alpha"], per_seed_budget=8,
                                                per_seed_reserve=0).trace["pruned"]}


def test_upstream_is_taken_before_downstream_when_both_are_eligible():
    """The gate headline reads n_cited_UPSTREAM; a flood of re-admitted siblings may not starve it. With
    one slot and both directions available, upstream takes it."""
    gr = _graph(_contract("alpha", [_drv("anchor", 0.95, parents=["par"]),
                                    _drv("par", 0.10),
                                    _drv("kid", 0.30, parents=["anchor"])]))   # scores HIGHER than `par`
    sg = _walk(gr, ["alpha"], per_seed_budget=8, per_seed_reserve=1)
    assert [r["key"][2] for r in _cc(sg)["reserved"]] == ["par"]
    assert _cc(sg)["reserved"][0]["reason"] == pl.REASON_CLOSURE


def test_a_cascade_downstream_node_ends_the_turn_with_at_least_one_evidence_row():
    """THE ADMITTED-BUT-NOT-CITED DEFECT CLASS, closed. Three shipped guards compared the LITERAL
    'closure_reservation' -- the 1-row score floor, the cap-order anchor-adjacency move, the census
    exclusion -- so a downstream node would have sorted to the tail of `_dedup_and_cap`, drawn a
    ceil(cap * ~0)=0 quota, and landed with ZERO rows: a slot spent on a node the reader can never cite.
    Run under cap_policy='score' (the `max` preset's policy) end to end."""
    gr = _downstream_graph()
    sg = _walk(gr, ["alpha"], per_seed_budget=8, per_seed_reserve=2)
    slices = {d.id for d in gr.contracts["alpha"].drivers}
    pl.ground(sg, _QUERY, gr, retrieve=_retrieve, silver_lookup=lambda *a, **k: None, asof="2026-08-11",
              driver_slices=slices, evidence_cap=24, k_by_depth=(7, 5), cap_policy="score")
    kid = next(n for n in sg.nodes if n.id == "kid")
    assert kid.admission["reason"] == pl.REASON_DOWNSTREAM
    assert kid.evidence, "a spent slot must buy a CITABLE node -- the 1-row floor is reason-set-scoped"
    assert sum(len(n.evidence) for n in sg.nodes) <= 24, "and the cap total still holds"


def test_a_downstream_node_that_would_draw_a_ZERO_quota_still_gets_one_row():
    """THE 1-ROW SCORE FLOOR, PINNED BEHAVIOURALLY (P3 round-1: it had NO behavioural pin at all -- only a
    source-text grep, which a mutation that keeps the token and restores the defect passes).

    THE STATE IT GUARDS. A `cascade_downstream` node is tau-EXEMPT, and when the walk carries no tombstone
    for it (it was never scored in this wave) its relevance is EXACTLY 0.0 -- so under cap_policy='score'
    its share is 0, `q = ceil(cap * 0) = 0`, and the slot buys a node with zero evidence rows: the
    admitted-but-not-cited defect P3-A exists to prove fixed. The cap is CONTENDED here (5 nodes x 3 rows
    against a cap of 12), so the quota is what decides, not headroom.

    The end-to-end walk pin below cannot see this: `_downstream_graph`'s `kid` inherits a 0.10 tombstone,
    so its share is non-zero and the anchor-adjacency move alone keeps it citable. The control is the same
    node WITHOUT the structural admission, which must end with nothing."""
    def _mk(id_, rel, adm=None):
        n = pl.GroundedNode(kind="driver", id=id_, contract="alpha", depth=1, relevance=rel)
        n.admission = adm or dict(pl._ADMIT_COSINE)
        n.evidence = [{"source_key": f"s3://{id_}/{i}", "date": f"2026-01-0{i + 1}",
                       "text": f"{id_} row {i}"} for i in range(3)]
        return n

    down = _mk("kid", 0.0, adm={"reason": pl.REASON_DOWNSTREAM, "ancestor_of": "anchor", "chain_depth": -1})
    nodes = [_mk("anchor", 0.95), *[_mk(f"f{i}", 0.9 - i * 0.01) for i in range(3)], down]
    pl._dedup_and_cap(pl.Subgraph(seeds=["alpha"], nodes=list(nodes)), 12,
                      cap_policy="score", k_by_depth=(7, 5))
    assert down.evidence, "a spent slot must buy a CITABLE node -- the floor is REASON-SET-scoped"
    assert sum(len(n.evidence) for n in nodes) <= 12, "and the cap total still holds"

    # THE CONTROL: identical node, plain cosine admission -> the quota really is 0 without the floor.
    plain = _mk("kid", 0.0)
    ctl = [_mk("anchor", 0.95), *[_mk(f"f{i}", 0.9 - i * 0.01) for i in range(3)], plain]
    pl._dedup_and_cap(pl.Subgraph(seeds=["alpha"], nodes=list(ctl)), 12,
                      cap_policy="score", k_by_depth=(7, 5))
    assert plain.evidence == [], "control: a zero-relevance node draws ceil(cap*0)=0 rows"


def test_the_walk_and_the_cap_order_a_MIXED_group_identically():
    """ONE ORDERING KEY for a reserved group, shared by the two places that order it: `_closure_plan`'s seq
    insertion (walk emission) and `_closure_cap_order` (evidence-cap order). They DISAGREED after admission
    v2 -- cap order sorted by abs(chain_depth), seq by the RAW depth -- so a downstream node at -2 was
    emitted AHEAD of an upstream node at +1 and placed BEHIND it at cap time, and the cap's tail-trim then
    fell on a different member of the group than the walk's own order implies.

    The fixture is built so the two rules DISAGREE: `up` at chain_depth +1, `down2` at -2. Raw depth orders
    down2 first; |depth| orders `up` first. `kid` is withheld from `driver_slices` so it is skipped
    `unbacked` and the only downstream candidate left is its child at -2."""
    gr = _graph(_contract("alpha", [_drv("anchor", 0.95, parents=["up"]),
                                    _drv("up", 0.10),
                                    _drv("kid", 0.20, parents=["anchor"]),
                                    _drv("down2", 0.10, parents=["kid"])]
                          + [_drv(f"f{i}", 0.90 - i * 0.01) for i in range(4)]))
    sg = _walk(gr, ["alpha"], per_seed_budget=8, per_seed_reserve=2,
               driver_slices={d.id for d in gr.contracts["alpha"].drivers} - {"kid"})
    res = {r["key"][2]: r for r in _cc(sg)["reserved"]}
    assert set(res) == {"up", "down2"}, "the fixture must reserve ONE of each direction"
    assert (res["up"]["chain_depth"], res["down2"]["chain_depth"]) == (1, -2), "...at DISAGREEING depths"

    emitted = [k[2] for k in (list(n.key) for n in sg.nodes) if k[2] in ("anchor", "up", "down2")]
    capped = [n.id for n in pl._closure_cap_order(
        sorted(sg.nodes, key=lambda x: (x.depth, -x.relevance))) if n.id in ("anchor", "up", "down2")]
    assert emitted == capped == ["anchor", "up", "down2"], \
        "|chain_depth| in BOTH places: nearest LINK first, in either cascade direction"


def test_cited_join_rows_carry_the_fourth_reason_field_for_both_directions():
    """The instrument split (n_cited_upstream / n_cited_downstream) is UNCOMPUTABLE from a 3-field join.
    The write side stamps the reason; eval partitions on it and reads legacy 3-field rows as upstream."""
    gr = _graph(_contract("alpha", [_drv("anchor", 0.95, parents=["par"]),
                                    _drv("par", 0.10),
                                    _drv("kid", 0.10, parents=["anchor"])]
                          + [_drv(f"f{i}", 0.9 - i * 0.01) for i in range(4)]))
    sg = _walk(gr, ["alpha"], per_seed_budget=8, per_seed_reserve=2)
    slices = {d.id for d in gr.contracts["alpha"].drivers}
    pl.ground(sg, _QUERY, gr, retrieve=_retrieve, silver_lookup=lambda *a, **k: None, asof="2026-08-11",
              driver_slices=slices, evidence_cap=48, k_by_depth=(7, 5), cap_policy="score")
    join = _cc(sg)["cited_join"]
    assert join and all(len(row) == 4 for row in join)
    assert {row[3] for row in join} == {pl.REASON_CLOSURE, pl.REASON_DOWNSTREAM}


# ══ graph.descendants_by_depth (D-MW-15 iv) ═════════════════════════════════════════════════════════════
def test_descendants_by_depth_matches_descendants_on_the_whole_curated_estate():
    """SET PARITY over all 33 curated DAGs -- the exact pin pattern the ancestors BFS carries, so a
    downstream slot can never be spent on a node `descendants()` would not have named."""
    gr = g.CausalGraph.load()
    assert len(gr.contracts) >= 30
    seen_depth2, seen_any = 0, 0
    for cid, c in gr.contracts.items():
        for d in c.drivers:
            byd = gr.descendants_by_depth(cid, d.id)
            assert set(byd) == set(gr.descendants(cid, d.id))
            assert all(v <= -1 for v in byd.values()), "the negative-depth convention IS the direction"
            seen_any += len(byd)
            seen_depth2 += sum(1 for v in byd.values() if v <= -2)
    assert seen_any > 0 and seen_depth2 > 0, "the estate's child DAG is 3-8 links deep; flat would be a bug"


def test_descendants_by_depth_keeps_the_shallowest_path_and_survives_a_cycle():
    a = cs.Driver(id="a", type="hazard", sign="+", mechanism="m")
    b = cs.Driver(id="b", type="hazard", sign="+", mechanism="m", parents=["a"])
    c = cs.Driver(id="c", type="hazard", sign="+", mechanism="m", parents=["a", "b"])
    gr = _graph(cs.CausalContract(contract="k", drivers=[a, b, c]))
    assert gr.descendants_by_depth("k", "a") == {"b": -1, "c": -1}   # c reachable at 1 and 2 -> 1 wins
    assert gr.descendants_by_depth("k", "c") == {}
    with pytest.raises(KeyError):
        gr.descendants_by_depth("k", "nope")


# ══ D-MW-14: THE FILL POOL IS BOUNDED ═══════════════════════════════════════════════════════════════════
def _fill_workers(monkeypatch, n_nodes: int) -> int:
    """Run `_parallel_fill` with the real widening logic and capture the pool width it asks for. Every
    outside edge is stubbed: no embedder, no rerank backend, no threads."""
    import concurrent.futures as cf

    from leviathan.graphrag import evidence as gev
    from leviathan.graphrag import rankers as rk
    seen: dict = {}

    class _Pool:
        def __init__(self, max_workers=None):
            seen["workers"] = max_workers

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def map(self, fn, items):
            return [fn(i) for i in items]

    monkeypatch.setattr(cf, "ThreadPoolExecutor", _Pool)
    monkeypatch.setattr(gev, "embed", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(rk, "_rerank_backend", lambda: "cohere")
    monkeypatch.setattr(rk, "rerank_expect", lambda n: None)
    pl._parallel_fill(list(range(n_nodes)), lambda n: None, _QUERY, gev.retrieve, expected=n_nodes)
    return seen["workers"]


def test_the_hint_satisfiability_widening_is_capped_at_MAX_FILL_POOL(monkeypatch):
    """THE FAN-OUT BOUND (P3 round-1). `_parallel_fill` widens its pool to the coalescer's promised batch
    so the batch can physically arrive -- measured when the widest preset walked 16 nodes, i.e. a ~24-thread
    ceiling. The seed-scaled budget makes that promise the eligible-node count of a 63-per-seed walk:
    measured 252 at 4 realized seeds, 378 + 24 reserve at the 6-seed ceiling, on a 4-vCPU serving task whose
    SQL still queues on EVIDENCE_PG_POOL. A 400-thread pool is not what the mechanism was measured for."""
    assert pl.MAX_FILL_POOL == 64
    assert _fill_workers(monkeypatch, 400) == pl.MAX_FILL_POOL


def test_every_SHIPPED_width_keeps_the_pools_arithmetic_byte_identical(monkeypatch):
    """The cap may only ever bind ABOVE the shipped widths (<= ~48 nodes), and it may never NARROW the
    un-widened `min(_WALK_WORKERS, len(nodes))` floor -- so P3-B still measures the widening's real wall
    clock instead of measuring this constant."""
    assert _fill_workers(monkeypatch, 16) == 16
    assert _fill_workers(monkeypatch, 48) == 48
    assert _fill_workers(monkeypatch, pl.MAX_FILL_POOL) == pl.MAX_FILL_POOL
    assert _fill_workers(monkeypatch, 2) == max(2, min(pl._WALK_WORKERS, 2))


# ══ D-MW-15: THE SKIPPED CENSUS IS SEPARABLE ════════════════════════════════════════════════════════════
def test_the_skipped_column_carries_FULL_per_reason_counts_and_a_per_reason_sample():
    """THE SUPPLY-vs-SLOT READ, RESTORED (P3 round-1). `skipped` used to be the first 32 entries overall,
    and at max width `already_admitted` dominates the ordered candidate pool by construction -- so on a real
    4-seed walk all 32 sampled entries were that one reason and `no_slot`, the reason the code records
    specifically to separate "no supply" from "no slot", never reached the artifact at all. Counts are over
    the FULL list and are never truncated; the SAMPLE is capped per reason, so every reason that fired is
    visible and the column still cannot become a dump."""
    gr = _two_market_graph(n_fill=40)
    cc = _cc(_walk(gr, ["alpha", "beta"], per_seed_budget=8, per_seed_reserve=2))
    counts, sample = cc["skipped_counts"], cc["skipped"]
    assert counts["no_slot"] >= 1, "alpha's third eligible ancestor is refused for want of a SLOT"
    assert set(counts) <= {"already_admitted", "unbacked", "no_slice", "same_slice", "no_slot"}
    assert sum(counts.values()) >= len(sample), "counts are over the FULL list, the sample is a sample"
    assert {s["reason"] for s in sample} == set(counts), "every reason that fired is visible in the sample"
    from collections import Counter
    assert max(Counter(s["reason"] for s in sample).values()) <= 8, "...and each is capped at 8"


# ══ D-MW-17: the token-denominated-budget measurement ═══════════════════════════════════════════════════
def _retrieve(query, slice_, *, k, asof=None, near=None):
    return [{"date": "2026-01-0%d" % (i + 1), "source": "SRC", "source_key": f"{slice_}#{i}",
             "text": f"{slice_} row {i}"} for i in range(k)]


def test_n_evidence_chars_tallies_the_post_cap_rows():
    """RECORDED, NEVER A BEHAVIOR INPUT (D-MW-17). The walk's budget is denominated in ROWS; a
    chain-intermediate node with 1-2 receipts and a fat evidence node cost the prompt window wildly
    different amounts. This is the number that would decide a token-denominated budget in a later wave.
    Tallied on the POST-cap rows -- the ones that actually reach the prompt, same denominator as
    n_evidence."""
    gr = _two_market_graph(n_fill=4)
    sg = _walk(gr, ["alpha", "beta"], per_seed_budget=8, per_seed_reserve=2)
    slices = {d.id for c in gr.contracts.values() for d in c.drivers}
    pl.ground(sg, _QUERY, gr, retrieve=_retrieve, silver_lookup=lambda *a, **k: None, asof="2026-08-11",
              driver_slices=slices, evidence_cap=24, k_by_depth=(7, 5), cap_policy="score")
    want = sum(len(h.get("text") or "") for n in sg.nodes for h in (n.evidence or []))
    assert sg.trace["n_evidence_chars"] == want > 0
    assert sg.trace["n_evidence"] == sum(len(n.evidence or []) for n in sg.nodes)
