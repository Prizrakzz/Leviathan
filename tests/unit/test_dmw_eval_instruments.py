"""D-MW P3 -- THE EVAL-SIDE INSTRUMENTS (plan docs/private/MOAT_WIDTH_WAVE_PLAN.md, D-MW-13..17).

These are the READ-SIDE pins for the four instrument prerequisites D-MW-16 requires to land and freeze
BEFORE either P3 arm runs. Every one of them exists because a RECORDED quantity had no artifact source:

  1. `walk_shape` + `n_evidence_chars` reach the per-answer record (the write side is planner's; here the
     pin is that a stamped key is not silently dropped by the record's hard whitelist -- the C2/U3 class).
  2. `_closure_cited` partitions the citation join on the admission REASON, so a downstream re-admission
     can never be quoted as upstream reach; legacy 3-field rows stay parseable as upstream.
  3. `chain_verdict` PRODUCES the deck's WIRED/TODAY/FAIL instead of leaving it to be eyeballed.
  4. pairwise_judge takes its axes FROM THE CHECKLIST and refuses an unknown one before any spend.
  5. submit_eval forwards --mode/--planner, ending the hand-registered-jobdef era.
"""
from __future__ import annotations

import importlib
import inspect
import sys
import types

import pytest
from leviathan.graphrag import eval as ev
from leviathan.graphrag import pairwise_judge as pj
from leviathan.graphrag import planner as pl
from leviathan.graphrag import tracekeys as tk

DOC, DATE = "s3://wasde/2026-01.pdf", "2026-01-01"


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# 1. THE NEW TRACE KEYS REACH THE ARTIFACT
# ══════════════════════════════════════════════════════════════════════════════════════════════════════
def _turn(trace: dict) -> dict:
    return {"q": {"id": "r1"}, "rubric": {}, "out": {"trace": trace}}


def test_walk_shape_and_n_evidence_chars_are_registered_columns():
    """Registration IS the lift (D-AM-3): a key absent from the registry reaches NO artifact, silently."""
    assert "walk_shape" in tk.TRACE_RECORD_KEYS
    assert "n_evidence_chars" in tk.TRACE_RECORD_KEYS
    assert len(set(tk.TRACE_RECORD_KEYS)) == len(tk.TRACE_RECORD_KEYS)      # no duplicate columns


def test_walk_shape_and_n_evidence_chars_reach_the_rendered_record():
    """The contract SHAPE, not a re-implementation of the stamp: {n_seeds, kept_by_depth, hop_contracts,
    fenced_second_order_hops} + an int char sum must survive verbatim into the per-answer record dict."""
    shape = {"n_seeds": 3, "kept_by_depth": {"0": 3, "1": 18, "2": 7},
             "hop_contracts": 2, "fenced_second_order_hops": 4}
    rec = ev._per_answer_record(_turn({"walk_shape": shape, "n_evidence_chars": 41207}), "single")
    assert rec["walk_shape"] == shape                       # verbatim, not summarised
    assert rec["n_evidence_chars"] == 41207


def test_the_new_columns_are_absent_as_None_on_a_pre_p3_row():
    """Absent-as-None is the registry's contract: every pre-P3 baseline must still render a full record."""
    rec = ev._per_answer_record(_turn({}), "single")
    assert rec["walk_shape"] is None and rec["n_evidence_chars"] is None


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# 2. _closure_cited -- THE UPSTREAM/DOWNSTREAM PARTITION
# ══════════════════════════════════════════════════════════════════════════════════════════════════════
def _out(join: list, resolved: dict, *, reserved: list | None = None) -> dict:
    return {"trace": {"cascade_closure": {
        "enabled": True, "reserve_n": 4, "cited_join": join,
        "reserved": reserved if reserved is not None else [
            {"key": ["driver", "corn_cbot", "urea_cost"], "slice": "drivers/urea",
             "reason": pl.REASON_CLOSURE, "ancestor_of": "fertilizer_input_costs", "chain_depth": 1}],
        "reserved_with_evidence": 1, "count_delta": 0, "displaced": [],
        "open": 0, "closed": 1, "kept": 12},
        "citation_verifier": {"enabled": True, "resolved": resolved}}}


def _resolved(**refs) -> dict:
    return {ref: {"source_key": DOC, "date": DATE, "source": "WASDE", "snippet": snip}
            for ref, snip in refs.items()}


def test_a_legacy_three_field_join_row_parses_as_UPSTREAM():
    """PRE-P3 ARTIFACTS STAY PARSEABLE, and the reading is historically TRUE, not a default: v1's only
    admission reason was closure_reservation, so every stored 3-field row IS an upstream row."""
    got = ev._closure_cited(_out([[DOC, DATE, "gas sets ammonia"]], _resolved(E1="gas sets ammonia")))
    assert got["n_cited"] == 1
    assert got["n_cited_upstream"] == 1 and got["n_cited_downstream"] == 0
    assert got["refs"] == ["E1"] and got["refs_upstream"] == ["E1"]


def test_four_field_rows_SPLIT_on_the_reason_and_the_split_SUMS_to_n_cited():
    """The instrument split, exactly: a downstream citation must be visible AS downstream, and the legacy
    headline must stay the sum so no pre-P3 reader silently changes meaning."""
    join = [[DOC, DATE, "gas sets ammonia", pl.REASON_CLOSURE],
            [DOC, DATE, "corn acres shifted", pl.REASON_DOWNSTREAM],
            [DOC, DATE, "urea import parity", pl.REASON_CLOSURE]]
    got = ev._closure_cited(_out(join, _resolved(E1="gas sets ammonia", E2="corn acres shifted",
                                                 E3="urea import parity", E4="unrelated row")))
    assert got["n_cited_upstream"] == 2 and got["n_cited_downstream"] == 1
    assert got["n_cited"] == got["n_cited_upstream"] + got["n_cited_downstream"] == 3
    assert got["refs_upstream"] == ["E1", "E3"] and got["refs_downstream"] == ["E2"]
    assert got["refs"] == ["E1", "E2", "E3"]                # unchanged shape: sorted distinct handles


def test_a_row_admitted_in_BOTH_lanes_is_counted_once_upstream():
    """One evidence row can survive on an upstream node AND a downstream one. Overlapping tallies would
    double-count the handle and break `n_cited == upstream + downstream`; lanes are EXCLUSIVE, upstream
    winning, so the sum stays the distinct-handle count the D-GD instrument published."""
    join = [[DOC, DATE, "shared row", pl.REASON_CLOSURE],
            [DOC, DATE, "shared row", pl.REASON_DOWNSTREAM]]
    got = ev._closure_cited(_out(join, _resolved(E1="shared row")))
    assert (got["n_cited"], got["n_cited_upstream"], got["n_cited_downstream"]) == (1, 1, 0)


def test_downstream_reach_alone_never_reads_as_upstream_reach():
    """The masking defect the split exists to kill: a chain row whose ONLY structural citation is a
    downstream re-admission must show upstream ZERO -- the gate headline reads n_cited_upstream."""
    got = ev._closure_cited(_out([[DOC, DATE, "sibling row", pl.REASON_DOWNSTREAM]],
                                 _resolved(E1="sibling row")))
    assert got["n_cited"] == 1 and got["n_cited_upstream"] == 0 and got["n_cited_downstream"] == 1


def test_an_unknown_reason_string_parses_as_upstream_not_dropped():
    """Fail-visible, not fail-silent: an unrecognised reason (a cosine-admitted default, a future lane)
    lands in the upstream bucket -- the CONSERVATIVE direction, since a dropped row would understate the
    denominator of a counter the gate reads, and understating is invisible."""
    got = ev._closure_cited(_out([[DOC, DATE, "some row", "cosine"]], _resolved(E1="some row")))
    assert got["n_cited_upstream"] == 1 and got["n_cited_downstream"] == 0


def test_the_reason_partition_reads_planners_constant_not_a_retyped_literal():
    """ONE PRODUCER (planner.py:72-78). A stale literal here would score every downstream citation as
    upstream -- i.e. report the gate's headline as a pass on the wrong mechanism."""
    assert ev._REASON_DOWNSTREAM is pl.REASON_DOWNSTREAM
    assert ev._DOWNSTREAM_REASONS is pl.DOWNSTREAM_REASONS
    assert pl.REASON_DOWNSTREAM in pl._STRUCTURAL_REASONS and pl.REASON_CLOSURE in pl._STRUCTURAL_REASONS


def test_the_P6_cascade_reason_lands_in_the_DOWNSTREAM_lane():
    """D-MW-28 (P6) round-1 BLOCKER. The lane tested EQUALITY against `cascade_downstream`, so the third
    structural reason -- a FOREIGN CONTRACT, downstream by construction -- fell into the UPSTREAM lane: it
    INFLATED the D-MW-16 headline with a mechanism that instrument does not measure, and left the P6 gate's
    own headline clause (`n_cited_downstream >= 1` on a majority of live rows) at 0 BY CONSTRUCTION, whose
    pre-committed consequence is routing the whole wave to D-HP's narration contract on a false read. The
    partition is MEMBERSHIP in planner's set, so the third reason is downstream because planner says so."""
    join = [[DOC, DATE, "palm sets the veg-oil floor", pl.REASON_DOWNSTREAM_CONTRACT],
            [DOC, DATE, "gas sets ammonia", pl.REASON_CLOSURE]]
    got = ev._closure_cited(_out(join, _resolved(E1="palm sets the veg-oil floor",
                                                 E2="gas sets ammonia")))
    assert got["n_cited_downstream"] == 1 and got["refs_downstream"] == ["E1"]
    assert got["n_cited_upstream"] == 1 and got["refs_upstream"] == ["E2"]
    assert got["n_cited"] == 2                                # the sum is still the distinct-handle count
    assert pl.DOWNSTREAM_REASONS == {pl.REASON_DOWNSTREAM, pl.REASON_DOWNSTREAM_CONTRACT}
    assert pl.REASON_CLOSURE not in pl.DOWNSTREAM_REASONS     # upstream stays upstream


def test_the_cascade_admissions_reach_the_id_lists_from_their_OWN_column():
    """THE ADMISSION HALF of the P6 gate's join. planner keeps cascade admissions OUT of `reserved` on
    purpose (the reserve's count_delta identity would stop being assertable), and the id lists read
    `reserved` only -- so `downstream_ids` was structurally EMPTY for P6 and the deck's stated join had
    nothing to read. They now come from BOTH columns, in the producer's own fully-qualified shape:
    `contract:<foreign>:<foreign>`, distinct from `driver:<contract>:<id>` by construction and exactly the
    string the frozen cascade deck names as `foreign_contract_node`."""
    out = _out([], {}, reserved=[{"key": ["driver", "corn_cbot", "urea_cost"], "reason": pl.REASON_CLOSURE}])
    out["trace"]["cascade_closure"]["cascade_contracts"] = [
        {"key": ["contract", "canola_ice", "canola_ice"], "reason": pl.REASON_DOWNSTREAM_CONTRACT,
         "ancestor_of": "soybean_oil_cbot", "chain_depth": -1}]
    got = ev._closure_cited(out)
    assert got["downstream_ids"] == ["contract:canola_ice:canola_ice"]
    assert got["upstream_ids"] == ["driver:corn_cbot:urea_cost"], "the upstream lane cannot move"
    assert got["reserved_ids"] == ["urea_cost"], "the pre-P3 D-GD column stays reserve-only and BARE"


def test_upstream_and_downstream_reserved_ids_partition_the_reserved_set():
    """ONE JOIN SHAPE. The lane lists carry FULLY-QUALIFIED `driver:<contract>:<id>` GroundedNode keys --
    the shape the deck's `upstream_nodes` names and the shape `cascade_closure.admissions` already
    publishes. Emitting the bare id here made chain_verdict's join empty by construction. `reserved_ids`
    stays BARE: it is the pre-P3 D-GD column and a stored baseline must keep re-reading."""
    reserved = [{"key": ["driver", "corn_cbot", "urea_cost"], "reason": pl.REASON_CLOSURE},
                {"key": ["driver", "corn_cbot", "planted_area"], "reason": pl.REASON_DOWNSTREAM},
                {"key": ["driver", "corn_cbot", "natural_gas"]}]          # legacy record: no reason
    got = ev._closure_cited(_out([], {}, reserved=reserved))
    assert got["upstream_ids"] == ["driver:corn_cbot:urea_cost", "driver:corn_cbot:natural_gas"]
    assert got["downstream_ids"] == ["driver:corn_cbot:planted_area"]
    assert got["reserved_ids"] == ["urea_cost", "planted_area", "natural_gas"]
    # the lanes still PARTITION the reserved set -- read on the tail of the qualified key.
    assert sorted(k.rsplit(":", 1)[-1] for k in got["upstream_ids"] + got["downstream_ids"]) \
        == sorted(got["reserved_ids"])


def test_a_pre_dgd_row_still_yields_the_empty_record():
    assert ev._closure_cited({"trace": {}}) == {}


def test_the_split_reaches_the_per_answer_record_and_the_report_panel():
    join = [[DOC, DATE, "gas sets ammonia", pl.REASON_CLOSURE],
            [DOC, DATE, "corn acres shifted", pl.REASON_DOWNSTREAM]]
    out = _out(join, _resolved(E1="gas sets ammonia", E2="corn acres shifted"))
    rec = ev._per_answer_record({"q": {"id": "r1"}, "rubric": {}, "out": out}, "single")
    assert rec["closure_cited"]["n_cited_upstream"] == 1
    panel = "\n".join(ev.closure_panel([{"q": {"id": "r1"}, "out": out}]))
    assert "upstream **1**" in panel and "downstream 1" in panel


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# 3. chain_verdict -- WIRED / TODAY / FAIL, PRODUCED
# ══════════════════════════════════════════════════════════════════════════════════════════════════════
_Q = {"id": "dgd_chain_gas_urea_acres",
      # the deck's ONE machine-readable join key, in the ONE shape both sides speak
      "upstream_nodes": ["driver:corn_cbot:urea_cost", "driver:corn_cbot:natural_gas"],
      # ...and the author-prose fields, present exactly as the frozen deck carries them, so the pins below
      # also assert that NEITHER of them feeds the join any more.
      "depth2_evidence": [{"node": "driver:corn_cbot:urea_cost"},
                          {"node": "driver:corn_cbot:natural_gas"}]}


def _rec(**cc) -> dict:
    base = {"enabled": True, "n_reserved": 2, "n_cited_upstream": 0, "n_cited_downstream": 0,
            "upstream_ids": [], "downstream_ids": []}
    return {"closure_cited": {**base, **cc}}


def test_WIRED_needs_all_three_conjuncts():
    v = ev.chain_verdict(_Q, _rec(n_cited_upstream=1, upstream_ids=["driver:corn_cbot:urea_cost"]),
                         checklist_pass=True)
    assert v["verdict"] == "WIRED"
    assert v["basis"]["named_admitted"] == ["driver:corn_cbot:urea_cost"]
    assert v["basis"]["join"] == "id_granular"              # the honesty label, never quotable as more


@pytest.mark.parametrize("kw,why", [
    (dict(checklist_pass=False), "checklist item failed"),
    (dict(checklist_pass=None), "row was never judged"),
])
def test_a_failed_or_missing_checklist_item_can_never_be_WIRED(kw, why):
    rec = _rec(n_cited_upstream=1, upstream_ids=["driver:corn_cbot:urea_cost"])
    assert ev.chain_verdict(_Q, rec, **kw)["verdict"] == "TODAY", why


def test_upstream_citation_alone_is_TODAY_when_it_lands_off_the_named_nodes():
    """Reach that converted somewhere ELSE is not this row's chain leg -- the deck names the nodes."""
    rec = _rec(n_cited_upstream=2, upstream_ids=["driver:corn_cbot:export_pace"])
    assert ev.chain_verdict(_Q, rec, checklist_pass=True)["verdict"] == "TODAY"


def test_downstream_citations_alone_are_TODAY_never_WIRED():
    """The whole point of the instrument split, restated as a verdict pin."""
    rec = _rec(n_cited_downstream=3, upstream_ids=["driver:corn_cbot:urea_cost"],
               downstream_ids=["driver:corn_cbot:planted_area"])
    assert ev.chain_verdict(_Q, rec, checklist_pass=True)["verdict"] == "TODAY"


def test_FAIL_is_an_input_and_outranks_everything():
    """A fail is a DEFECT CLASS, not an arm result: it is adjudicated from the deck's `fail` clauses and
    is never derived from an artifact field -- so a would-be WIRED row still reads FAIL."""
    rec = _rec(n_cited_upstream=1, upstream_ids=["driver:corn_cbot:urea_cost"])
    v = ev.chain_verdict(_Q, rec, checklist_pass=True, defect=True)
    assert v["verdict"] == "FAIL" and v["basis"]["defect"] is True


def test_instrument_dead_is_flagged_in_the_basis_and_is_not_a_fourth_state():
    """`n_reserved == 0` on an ON arm measured NOTHING: the caller excludes the row from the denominator
    (the dv_episode_lanina_arg discipline). It never becomes a loss and never becomes a verdict."""
    v = ev.chain_verdict(_Q, _rec(n_reserved=0), checklist_pass=True)
    assert v["verdict"] == "TODAY" and v["basis"]["instrument_dead"] is True
    assert v["verdict"] in ev.CHAIN_VERDICTS and len(ev.CHAIN_VERDICTS) == 3


def test_a_row_naming_no_upstream_nodes_cannot_be_WIRED():
    rec = _rec(n_cited_upstream=5, upstream_ids=["driver:corn_cbot:urea_cost"])
    v = ev.chain_verdict({"id": "x"}, rec, checklist_pass=True)
    assert v["verdict"] == "TODAY" and v["basis"]["named_nodes"] == 0


def test_named_upstream_reads_ONLY_the_decks_machine_readable_key():
    """ONE AUTHOR KEY, ONE READER. `upstream_nodes` was built by the deck author as "the flat,
    machine-readable join key the WIRED verdict names" and the first cut never touched it -- it parsed
    `depth2_evidence` plus `conversion` instead, and `conversion` is PROSE ("orphan slice `subsidy` -> dag
    id `producer_subsidy`"), so on 3 of the 8 frozen v2 rows a provenance note was counted as a node id and
    `basis.named_nodes` was wrong. A prose field cannot be a join key; a second reader of the same fact is
    how the two drift."""
    assert ev.chain_named_upstream(_Q) == ["driver:corn_cbot:urea_cost", "driver:corn_cbot:natural_gas"]
    assert ev.chain_named_upstream({}) == []
    # the two author-prose fields are INERT, including the exact conversion string the frozen deck carries
    assert ev.chain_named_upstream({"depth2_evidence": [{"node": "driver:corn_cbot:urea_cost"}]}) == []
    assert ev.chain_named_upstream(
        {"conversion": "orphan slice `subsidy` -> dag id `producer_subsidy` (D-GD-2 tranche 2)",
         "upstream_nodes": ["driver:cotton:producer_subsidy"]}) == ["driver:cotton:producer_subsidy"]


def test_the_verdict_reads_no_artifact_field_beyond_the_named_three():
    """D-MW-16: "No other artifact field feeds the verdict." Anything else in the record -- strips, judge
    axes, count_delta, open/closed -- must be inert to it."""
    rec = _rec(n_cited_upstream=1, upstream_ids=["driver:corn_cbot:urea_cost"])
    noisy = {**rec, "strips": 9, "judge": {"usefulness": 1}, "chain_fired": False}
    noisy["closure_cited"] = {**rec["closure_cited"], "count_delta": -7, "open": 44, "n_displaced": 3}
    assert ev.chain_verdict(_Q, noisy, checklist_pass=True)["verdict"] == "WIRED"


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# 3b. THE ROUND TRIP -- the REAL producer's output, fed to the REAL reader
# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# WHY THIS BLOCK EXISTS. Every WIRED pin above is hand-fed. In round 1 the hand-fed value was a shape the
# producer PROVABLY NEVER EMITTED (qualified in the fixture, bare from `_closure_cited`), so the whole
# verdict block was vacuous with respect to production and a structurally-unreachable WIRED shipped green
# -- while a pin twenty lines away asserted the true, contradictory shape. A fixture may state a shape; it
# may not be the only thing that states it. Here the walk, the ground stamp, `_closure_cited` and
# `chain_verdict` are all the shipped ones, and the deck-side id is a LITERAL so the shape is pinned from
# outside both halves.
def _mini_graph():
    """One contract, one anchor, one BELOW-tau backed parent, three fillers. Deterministic exact-cosine
    embedder (same device as test_dmw_walk): each text maps to [r, sqrt(1-r^2)], the query to [1, 0]."""
    from leviathan.causal import schema as cs
    from leviathan.graphrag import graph as g

    def _drv(id_, rel, **kw):
        _REL[f"m::{id_}"] = rel
        return cs.Driver(id=id_, type="hazard", sign="+", mechanism=f"m::{id_}", **kw)

    c = cs.CausalContract(contract="alpha", aliases=["alpha"],
                          drivers=[_drv("anchor", 0.95, parents=["par"]), _drv("par", 0.10)]
                          + [_drv(f"f{i}", 0.90 - i * 0.01) for i in range(3)])
    return g.CausalGraph({"alpha": c}, silver=set())


_QUERY, _REL = "QQ", {}


def _mini_embed(texts):
    out = []
    for t in texts:
        r = 1.0 if t == _QUERY else float(_REL.get(t, 0.0))
        out.append([r, (max(0.0, 1.0 - r * r)) ** 0.5])
    return out


def _mini_retrieve(query, slice_, *, k, asof=None, near=None):
    return [{"date": "2026-01-0%d" % (i + 1), "source": "SRC", "source_key": f"{slice_}#{i}",
             "text": f"{slice_} row {i}"} for i in range(k)]


def _real_closure_cited() -> dict:
    """Run the SHIPPED producer end to end and return `_closure_cited`'s genuine output. The only fixture
    is the citation verifier's `resolved` map, which is built FROM the walk's own `cited_join` -- i.e. the
    turn cited what it retrieved, which is the case the verdict is about."""
    gr = _mini_graph()
    sg = pl.grounded_subgraph(_QUERY, gr, embed=_mini_embed, route_fn=lambda q, g_: ["alpha"],
                              depth=1, tau=0.35, max_seeds=2,
                              driver_slices={d.id for d in gr.contracts["alpha"].drivers},
                              per_seed_budget=8, per_seed_reserve=1)
    pl.ground(sg, _QUERY, gr, retrieve=_mini_retrieve, silver_lookup=lambda *a, **k: None,
              asof="2026-08-11", driver_slices={d.id for d in gr.contracts["alpha"].drivers},
              evidence_cap=24, k_by_depth=(7, 5), cap_policy="score")
    cc = sg.trace["cascade_closure"]
    up_row = next(r for r in cc["cited_join"] if str(r[3]) == pl.REASON_CLOSURE)
    resolved = {"E1": {"source_key": up_row[0], "date": up_row[1], "source": "SRC", "snippet": up_row[2]}}
    return ev._closure_cited({"trace": {"cascade_closure": cc,
                                        "citation_verifier": {"enabled": True, "resolved": resolved}}})


def test_the_producers_upstream_ids_are_fully_qualified_node_keys():
    """THE SHAPE PIN, on the producer's own output: `driver:<contract>:<id>`, never the bare id."""
    import re
    cc = _real_closure_cited()
    assert cc["upstream_ids"] == ["driver:alpha:par"]
    assert all(re.match(r"^driver:[a-z0-9_]+:", x) for x in cc["upstream_ids"] + cc["downstream_ids"])


def test_a_REAL_closure_cited_output_reaches_WIRED_through_chain_verdict():
    """THE ROUND TRIP, and the single assertion that would have caught the round-1 blocker: the deck's
    named node and the artifact's admitted node must MEET. Both halves shipped; only the deck id is a
    literal here."""
    cc = _real_closure_cited()
    q = {"id": "synthetic_chain_row", "upstream_nodes": ["driver:alpha:par"]}
    assert set(ev.chain_named_upstream(q)) & set(cc["upstream_ids"]), "the join must be NON-EMPTY"
    v = ev.chain_verdict(q, {"closure_cited": cc}, checklist_pass=True)
    assert v["verdict"] == "WIRED"
    assert v["basis"]["named_admitted"] == ["driver:alpha:par"]
    assert v["basis"]["n_cited_upstream"] >= 1 and v["basis"]["n_reserved"] >= 1


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# 4. pairwise_judge -- AXES FROM THE CHECKLIST
# ══════════════════════════════════════════════════════════════════════════════════════════════════════
def test_no_checklist_axes_key_keeps_the_module_default():
    assert pj.resolve_axes({}) == pj.AXES
    assert pj.resolve_axes({"rows": []}) == pj.AXES
    assert pj.resolve_axes(None) == pj.AXES


def test_the_checklist_axes_key_selects_the_run_axes():
    ax = pj.resolve_axes({"axes": ["usefulness", "grounding", "upstream_evidence"]})
    assert ax == ("usefulness", "grounding", "upstream_evidence")
    assert "composition_completeness" not in ax             # replaced, not appended


def test_the_shipped_dgd_checklist_resolves_its_frozen_axes():
    """The instrument this unblocks: the D-GD checklist froze `upstream_evidence` on 2026-08-08 and
    NOTHING read the key. Reading the real file is the pin -- a fixture would not have caught that."""
    import pathlib
    p = pathlib.Path(__file__).resolve().parents[2] / "configs" / "graphrag" / \
        "eval_checklists_dgd_chain_v1.yaml"
    cfg = pj.load_checklists(p)
    assert pj.resolve_axes(cfg) == ("usefulness", "grounding", "upstream_evidence")


def _cfg_dir():
    import pathlib
    return pathlib.Path(__file__).resolve().parents[2] / "configs" / "graphrag"


_V2_DECK = _cfg_dir() / "eval_queries_dgd_chain_v2.yaml"
_V2_CHECKS = _cfg_dir() / "eval_checklists_dgd_chain_v2.yaml"
_HAVE_V2 = _V2_DECK.exists() and _V2_CHECKS.exists()


@pytest.mark.skipif(not _HAVE_V2, reason="the P3-A instrument pair is gitignored (configs/graphrag/)")
def test_the_FROZEN_p3a_instrument_pair_parses_and_holds_its_authored_shape():
    """THE FROZEN INSTRUMENT, HELD BY CI. Reading the real files is the pin (a fixture would not have
    caught it): before this, the P3-A deck+checklist pair had ZERO coverage -- the only file-reading pin in
    the suite loads the v1 checklist, and every 'chain_v2' string in tests/ is a label or an argv token that
    is never loaded. A row-id drift between deck and checklist, an axes typo, or an un-qualified
    `upstream_nodes` id surfaces only at arm time, i.e. AFTER spend.

    What is asserted is what is AUTHORED -- including the FOURTH axis. v2 added `composition_completeness`
    deliberately (the census mandates ride both arms at max, so composition is a measurable property of
    these bodies rather than a constant); the wave's hypothesis is still `upstream_evidence`."""
    deck = ev.load_queries(_V2_DECK)
    cfg = pj.load_checklists(_V2_CHECKS)
    assert len(deck) == 8
    # 1. THE JOIN SHAPE, on the deck side of the same join the producer's shape pin holds.
    import re
    raw = __import__("yaml").safe_load(_V2_DECK.read_text(encoding="utf-8"))["queries"]
    for row in raw:
        named = ev.chain_named_upstream(row)
        assert named, "every P3-A row must NAME its upstream nodes -- an unnamed row can never be WIRED"
        for n in named:
            assert re.match(r"^driver:[a-z0-9_]+:", n), (row["id"], n)
    # 2. THE AXES, as authored, and the deck/checklist row sets agree.
    assert pj.resolve_axes(cfg) == ("usefulness", "grounding", "composition_completeness",
                                    "upstream_evidence")
    errs, _ = pj.validate_checklists(cfg, deck)
    assert errs == []
    assert [str(r["id"]) for r in cfg["rows"]] == [str(q["id"]) for q in deck]
    # 3. THE ITEM LAW: the upstream-evidence item FIRST, or an explicit verdict_item override.
    for r in cfg["rows"]:
        assert r.get("verdict_item") or str(r["items"][0]["id"]).endswith("_has_its_own_handle"), r["id"]
    # 4. THE TWO ARM COMMANDS, verbatim, in BOTH headers (the checklist restates them to be self-sufficient).
    for p in (_V2_DECK, _V2_CHECKS):
        txt = p.read_text(encoding="utf-8")
        for mode in ("max_c0", "max"):
            assert f"--mode {mode} --queries configs/graphrag/eval_queries_dgd_chain_v2.yaml" in txt, p.name


@pytest.mark.parametrize("bad", [["usefulness", "vibes"], ["upstream_evidence", "convexity"], ["nope"]])
def test_an_unknown_axis_REFUSES_LOUDLY_before_any_spend(bad):
    """Silently dropping it would run a paid instrument that is NOT the pre-registered one, and the report
    would look complete while missing the axis the wave exists to measure."""
    with pytest.raises(ValueError) as e:
        pj.resolve_axes({"axes": bad})
    assert "unknown judged axis" in str(e.value)


@pytest.mark.parametrize("bad", [["usefulness", "usefulness"], ["usefulness", "  "]])
def test_a_malformed_axes_list_raises_too(bad):
    with pytest.raises(ValueError):
        pj.resolve_axes({"axes": bad})


def test_validate_checklists_turns_an_unknown_axis_into_an_ABORTING_error():
    """main() refuses to judge against a mismatched instrument -- the axis error must ride that same gate,
    not a warning."""
    cfg = {"checklist_version": "v", "deck": "d", "axes": ["vibes"],
           "rows": [{"id": "r1", "items": [{"id": f"i{n}", "ask": "?"} for n in range(3)]}]}
    errs, _ = pj.validate_checklists(cfg, [{"id": "r1"}])
    assert any("unknown judged axis" in e for e in errs)


def test_the_tool_schema_forces_exactly_the_resolved_axes():
    ax = ("usefulness", "grounding", "upstream_evidence")
    t = pj._pairwise_tool([{"id": "i1", "ask": "?"}], ax)
    for a in ax:
        assert t["input_schema"]["properties"][a]["enum"] == ["ANSWER_1", "ANSWER_2", "tie"]
        assert a in t["input_schema"]["required"] and f"{a}_rationale" in t["input_schema"]["required"]
    assert "composition_completeness" not in t["input_schema"]["properties"]


def test_the_default_axes_leave_the_system_template_BYTE_IDENTICAL():
    """The pre-registration law: a later deck may not rewrite the frozen template every recorded D-CC run
    was judged under."""
    assert pj.system_text() is pj._PAIRWISE_SYS
    assert pj.system_text(pj.AXES) is pj._PAIRWISE_SYS


def test_a_non_default_axis_set_appends_its_FROZEN_text():
    s = pj.system_text(("usefulness", "grounding", "upstream_evidence"))
    assert s.startswith(pj._PAIRWISE_SYS)                   # the frozen template is never edited, only added to
    assert "AXES FOR THIS RUN" in s
    assert "naming the absence is upstream honesty" in s    # the checklist yaml's frozen wording, verbatim
    assert "usefulness, grounding, upstream_evidence" in s


def test_the_judged_call_carries_the_resolved_axes_end_to_end():
    seen: dict = {}

    def fake_call(client, system, user, *, model, max_tokens, tool, **kw):
        seen.update(system=system, tool=tool)
        return ({"usefulness": "ANSWER_1", "usefulness_rationale": "a",
                 "grounding": "tie", "grounding_rationale": "b",
                 "upstream_evidence": "ANSWER_2", "upstream_evidence_rationale": "c",
                 "checklist": [{"item_id": "i1", "answer_1": True, "answer_2": False}]}, None)

    ax = ("usefulness", "grounding", "upstream_evidence")
    plan = [{"id": "r1", "question": "Q?", "asof": "2026-08-08",
             "order": {"first": "A", "second": "B"}, "text": {"A": "one", "B": "two"},
             "provenance": {"A": "answer", "B": "answer"},
             "items": [{"id": "i1", "ask": "?"}], "beyond_quick_sources": [], "width_class": None}]
    rows = pj.run_rows(plan, call=fake_call, axes=ax)
    assert set(rows[0]["verdicts"]) == set(ax)
    assert rows[0]["verdicts"]["upstream_evidence"]["winner"] == "B"
    assert "upstream_evidence" in seen["tool"]["input_schema"]["required"]
    assert "AXES FOR THIS RUN" in seen["system"][0]["text"]

    rep = pj.build_report(rows, arms={"A": {}, "B": {}}, deck="dgd_chain_v2",
                          checklist_version="v2", model=pj.MODEL, salt="s", axes=ax)
    assert rep["axes"] == list(ax) and set(rep["totals"]) == set(ax)
    md = pj.report_md(rep)
    assert "| upstream_evidence |" in md                    # the tally table renders the run's own axes
    assert "composition_completeness" not in md.split("## Rationales")[0].split("| axis |")[1]


def test_a_pre_dmw_report_json_still_renders_on_the_default_axes():
    """report_md reads the axes the REPORT was built on, falling back to the default -- a stored D-CC
    report json must keep rendering after this change."""
    rows = [{"id": "r1", "order": {"first": "A", "second": "B"},
             "provenance": {"A": "answer", "B": "answer"},
             "verdicts": {ax: {"winner": "A", "rationale": "r"} for ax in pj.AXES},
             "checklist": [], "conversion": {a: {"cited_hits": 0, "n_documented": 0,
                                                 "has_sources_block": True} for a in pj.ARMS}}]
    rep = pj.build_report(rows, arms={"A": {}, "B": {}}, deck="d", checklist_version="v",
                          model=pj.MODEL, salt="s")
    rep.pop("axes")                                          # a report json written before the key existed
    assert "composition_completeness" in pj.report_md(rep)


def test_no_AXES_consumer_was_left_reading_the_module_constant():
    """The enumerated seams (plan D-MW-16): tool schema, tally, run_rows, build_report, report_md. A
    consumer still closing over the module constant would emit a report whose axes disagree with the
    schema the judge answered under."""
    for fn in (pj._pairwise_tool, pj._tally, pj.run_rows, pj.build_report, pj.judge_pair, pj.system_text):
        assert "axes" in inspect.signature(fn).parameters, fn.__name__
    src = inspect.getsource(pj.report_md)
    assert "rep.get(\"axes\")" in src and "for ax in AXES" not in src


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# 4b. THE VERDICT IS PRODUCED WHERE BOTH HALVES EXIST -- pairwise_judge (checklist + closure record)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════
_UP = "driver:corn_cbot:urea_cost"


def _closure(**kw) -> dict:
    return {"enabled": True, "n_reserved": 2, "n_cited_upstream": 0, "n_cited_downstream": 0,
            "upstream_ids": [], "downstream_ids": [], **kw}


def _judge_call(**checked):
    def call(client, system, user, *, model, max_tokens, tool, **kw):
        return ({"usefulness": "ANSWER_1", "usefulness_rationale": "a",
                 "grounding": "tie", "grounding_rationale": "b",
                 "composition_completeness": "tie", "composition_completeness_rationale": "c",
                 "checklist": [{"item_id": "up_item", "answer_1": checked.get("first", False),
                                "answer_2": checked.get("second", False)}]}, None)
    return call


def _chain_plan(a_closure: dict, b_closure: dict, **kw) -> list[dict]:
    return [{"id": "dgd_chain_gas_urea_acres", "question": "Q?", "asof": "2026-08-08",
             "order": {"first": "A", "second": "B"}, "text": {"A": "one", "B": "two"},
             "provenance": {"A": "answer", "B": "answer"},
             "items": [{"id": "up_item", "ask": "?"}, {"id": "other", "ask": "?"}],
             "beyond_quick_sources": [], "width_class": None,
             "chain_named": [_UP], "verdict_item": kw.get("verdict_item"),
             "closure": {"A": a_closure, "B": b_closure}}]


def test_build_plan_carries_both_halves_of_the_verdict():
    q = {"id": "r1", "question": "Q?", "upstream_nodes": [_UP]}
    plan = pj.build_plan([q], {"r1": {"id": "r1", "answer": "a", "closure_cited": _closure()}},
                         {"r1": {"id": "r1", "answer": "b", "closure_cited": _closure(n_reserved=0)}},
                         {"rows": [{"id": "r1", "items": [{"id": "up_item", "ask": "?"}]}]})
    assert plan[0]["chain_named"] == [_UP]
    assert plan[0]["closure"]["B"]["n_reserved"] == 0


def test_a_deck_naming_no_upstream_nodes_produces_no_verdict_at_all():
    """Every non-chain deck (the width deck, the tier deck) must be untouched by this instrument."""
    plan = pj.build_plan([{"id": "r1", "question": "Q?"}], {}, {}, {"rows": []})
    assert plan[0]["chain_named"] == []
    assert "chain_verdict" not in pj.run_rows(plan, call=_judge_call())[0]


def test_run_rows_produces_WIRED_only_for_the_arm_that_earned_it():
    plan = _chain_plan(_closure(n_cited_upstream=1, upstream_ids=[_UP]),
                       _closure(n_cited_upstream=0, upstream_ids=[_UP]))
    cv = pj.run_rows(plan, call=_judge_call(first=True, second=True))[0]["chain_verdict"]
    assert cv["A"]["verdict"] == "WIRED"                     # cited upstream, on a NAMED node, item passed
    assert cv["B"]["verdict"] == "TODAY"                     # admitted but upstream-uncited


def test_the_checklist_half_really_gates_the_verdict():
    plan = _chain_plan(_closure(n_cited_upstream=1, upstream_ids=[_UP]),
                       _closure(n_cited_upstream=1, upstream_ids=[_UP]))
    cv = pj.run_rows(plan, call=_judge_call(first=False, second=True))[0]["chain_verdict"]
    assert cv["A"]["verdict"] == "TODAY" and cv["B"]["verdict"] == "WIRED"


def test_the_verdict_item_defaults_to_the_first_and_is_overridable_by_id():
    """The chain checklist's item law puts the upstream-evidence item first; a row whose ordering differs
    says so with `verdict_item:` rather than having this instrument guess."""
    items = [{"id": "up_item", "ask": "?"}, {"id": "other", "ask": "?"}]
    cl = [{"item_id": "up_item", "A": True, "B": False}, {"item_id": "other", "A": False, "B": True}]
    assert pj._verdict_item_pass(items, cl, "A", None) is True
    assert pj._verdict_item_pass(items, cl, "A", "other") is False
    assert pj._verdict_item_pass(items, cl, "B", "other") is True
    assert pj._verdict_item_pass(items, [], "A", None) is None          # unanswered != failed
    assert pj._verdict_item_pass([], cl, "A", None) is None


def test_a_failed_judge_call_still_records_the_deterministic_half():
    """One bad row must not lose the rest, and it must not silently lose its own closure counters either."""
    def boom(*a, **k):
        raise RuntimeError("429")
    row = pj.run_rows(_chain_plan(_closure(n_cited_upstream=1, upstream_ids=[_UP]), _closure()),
                      call=boom)[0]
    assert row["error"].startswith("429")
    assert row["chain_verdict"]["A"]["verdict"] == "TODAY"   # unjudged -> no evidence either way
    assert row["chain_verdict"]["A"]["basis"]["n_cited_upstream"] == 1


def test_the_report_denominator_is_ONE_live_set_taken_from_the_ON_arm():
    """THE DENOMINATOR IS THE DECK'S OWN: "a row is LIVE iff closure_cited.n_reserved > 0 ON THE ON ARM".

    THE DEFECT THIS PINS (P3 round-1): liveness was computed per arm, and the OFF arm (`max_c0`) stamps
    `cascade_closure.enabled: False`, so NO OFF-arm row can ever read instrument-dead -- its denominator was
    the whole deck, forever, while the ON arm's was the live subset. The gate's ">= 3 live rows" floor and
    its "majority of live rows" headline would then have been read off two different numbers.

    The fixture is built so the two rules DISAGREE: row `r2` reserved nothing on the ON arm (A), and the
    OFF arm (B, enabled False) would count BOTH rows live."""
    plan = _chain_plan(_closure(n_cited_upstream=1, upstream_ids=[_UP]),
                       _closure(enabled=False, n_reserved=0))
    dead = _chain_plan(_closure(n_reserved=0), _closure(enabled=False, n_reserved=0))
    dead[0]["id"] = "dgd_chain_dead_row"
    rows = pj.run_rows(plan + dead, call=_judge_call(first=True, second=True))
    tot = pj._verdict_totals(rows)
    assert tot["live_arm"] == "A", "the ON arm is the one whose rows reserved anything"
    assert tot["A"] == {"WIRED": 1, "TODAY": 0, "FAIL": 0, "live": 1, "instrument_dead": 1}
    assert tot["B"]["live"] == 1, "ONE live set: the OFF arm may not carry the whole deck as denominator"
    assert tot["B"]["instrument_dead"] == 1 and tot["B"]["TODAY"] == 1
    assert tot["B"]["WIRED"] == 0

    rep = pj.build_report(rows, arms={"A": {}, "B": {}}, deck="dgd_chain_v2", checklist_version="v2",
                          model=pj.MODEL, salt="s")
    md = pj.report_md(rep)
    assert "## Chain verdict" in md and "| A | 1 | 0 | 0 | 1 | 1 |" in md
    assert "ON arm (A)" in md, "the report names WHICH arm supplied the denominator"


def test_no_arm_reserving_anything_leaves_the_denominator_EMPTY():
    """The honest reading of a deck where the mechanism never fired: zero live rows on both arms, never a
    fallback to len(rows) (which would score every row as a TODAY loss)."""
    rows = pj.run_rows(_chain_plan(_closure(n_reserved=0), _closure(enabled=False, n_reserved=0)),
                       call=_judge_call(first=True, second=True))
    tot = pj._verdict_totals(rows)
    assert tot["live_arm"] is None
    assert tot["A"]["live"] == 0 and tot["B"]["live"] == 0
    assert tot["A"]["TODAY"] == 0 and tot["A"]["instrument_dead"] == 1

    # And the REPORT declares the dead gate instead of suppressing the section (P3 verify-round catch:
    # the total-failure mode rendered identically to a non-chain deck, hiding the instrument-dead read).
    rep = pj.build_report(rows, arms={"A": {}, "B": {}}, deck="dgd_chain_v2", checklist_version="v2",
                          model=pj.MODEL, salt="s")
    md = pj.report_md(rep)
    assert "INSTRUMENT-DEAD GATE" in md, "a total-failure chain run must render as a DECLARED dead gate"
    assert "measured NOTHING" in md


def test_a_non_chain_report_renders_without_a_chain_verdict_section():
    rows = pj.run_rows([{"id": "r1", "question": "Q?", "asof": None,
                         "order": {"first": "A", "second": "B"}, "text": {"A": "x", "B": "y"},
                         "provenance": {"A": "answer", "B": "answer"}, "items": [],
                         "beyond_quick_sources": [], "width_class": None}], call=_judge_call())
    rep = pj.build_report(rows, arms={"A": {}, "B": {}}, deck="d", checklist_version=None,
                          model=pj.MODEL, salt="s")
    assert rep["chain_verdicts"]["A"]["live"] == 0
    assert "## Chain verdict" not in pj.report_md(rep)


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# 5. submit_eval -- --mode / --planner threading (string assembly only; no AWS, no boto client)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════
def _submit_eval():
    """Import the submit script by path (jobs/ is not a package) with boto3 stubbed -- these pins are
    pure argv assembly and must never construct a client or touch credentials."""
    import pathlib
    p = pathlib.Path(__file__).resolve().parents[2] / "jobs" / "submit" / "submit_eval.py"
    if "boto3" not in sys.modules:
        sys.modules["boto3"] = types.SimpleNamespace(client=lambda *a, **k: None)  # type: ignore[assignment]
    spec = importlib.util.spec_from_file_location("_submit_eval_under_test", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_BASE = dict(queries="configs/graphrag/eval_queries_dgd_chain_v2.yaml", convos=None,
             model="claude-sonnet-4-6", judge=False, judge_model="claude-opus-4-8", k=5)


def test_mode_and_planner_reach_the_container_command():
    cmd = _submit_eval().build_command(**_BASE, via_orchestrator=True, mode="max", planner="l2")
    assert cmd[cmd.index("--mode") + 1] == "max"
    assert cmd[cmd.index("--planner") + 1] == "l2"
    assert "--via-orchestrator" in cmd


def test_the_two_p3_arms_differ_by_exactly_one_token():
    """One variable at identical width (D-MW-13's two-preset design) -- if the submitter mutated anything
    else between the arms, the gate's whole attribution claim would be false."""
    mk = _submit_eval().build_command
    on = mk(**_BASE, via_orchestrator=True, mode="max")
    off = mk(**_BASE, via_orchestrator=True, mode="max_c0")
    assert len(on) == len(off)
    assert [a for a, b in zip(on, off) if a != b] == ["max"]


def test_omitting_the_flags_leaves_the_command_byte_identical_to_the_pre_p3_one():
    """Additive by construction: every already-submitted eval recipe keeps producing its exact argv."""
    mk = _submit_eval().build_command
    assert mk(**_BASE, via_orchestrator=True) == mk(**_BASE, via_orchestrator=True, mode=None, planner=None)
    assert "--mode" not in mk(**_BASE, via_orchestrator=True)


def test_the_flags_are_parsed_by_the_cli_and_named_the_same_as_evals():
    """The flag names must match `leviathan.graphrag.eval`'s own, or the arm is submitted under a name the
    container rejects."""
    mod = _submit_eval()
    src = inspect.getsource(mod.main)
    assert '"--mode"' in src and '"--planner"' in src
    assert "mode=args.mode" in src and "planner=args.planner" in src
    esrc = inspect.getsource(ev.main)
    assert '"--mode"' in esrc and '"--planner"' in esrc


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# 6. D-HP-17 / D-HP-19 / D-HP-20 -- THE SUCCESSOR METRIC FAMILY AND ITS COUNTERS
#
# D5: THE INSTRUMENT IS PART OF THE CLAIM. Four of nine strip classes go to zero BY CONSTRUCTION under
# handle-prose, so a metric family that silently absorbs that is not measuring D-HP, it is congratulating
# it. These pins hold the family to the shape the plan froze BEFORE any arm runs: one producer for the
# arithmetic, named denominators, the honesty rider's three numbers together, and BLINDED never read as
# KILLED.
# ══════════════════════════════════════════════════════════════════════════════════════════════════════
from leviathan.graphrag import emf as emfmod                                  # noqa: E402


def _hp_trace(by_rule: dict | None = None, **over) -> dict:
    tr = {"citation_verifier": {"enabled": True, "stripped": 4, "claim_count": 20, "checked": 9,
                                "by_rule": dict(by_rule or {})},
          "number_handles": {"substituted": 7, "handles_dropped": 0, "sentences_dropped": 1,
                             "unresolvable": 2},
          "prose_handles": {"substituted": 3, "handles_dropped": 0, "sentences_dropped": 0,
                            "unresolvable": 1},
          "wrong_slot_audit": {"scope_checked": 10, "scope_mismatch": 2,
                               "direction_checked": 4, "direction_mismatch": 1},
          "bare_digit_count": 5}
    tr.update(over)
    return tr


def test_wrong_slot_audit_is_a_registered_column_at_the_tail():
    """D-HP-14's census is the ONLY instrument for the wave's #1 risk, and registration IS the lift: a key
    absent from the registry reaches NO artifact, silently (the C2/U3 class). It appends at the TAIL --
    eval.py splats the registry IN ORDER, so an insert shifts every later column in every stored record.

    RE-ANCHORED (H1 FIX W2, finding NF-2): `slot_orphan_dropped` was APPENDED after this column, so the
    tail moved by one -- which is what the law licenses and what this pin exists to police. The invariant
    asserted is unchanged: `wrong_slot_audit` must still be AFTER every older key and must never have been
    INSERTED ahead of one.

    RE-ANCHORED AGAIN (H1b, D-HP-15): `episode_spans_validated` was APPENDED after THAT, so the tail moved
    by one more. Same law, same one-line re-anchor, same unchanged invariant.

    RE-ANCHORED A THIRD TIME (D-HP G1 AMENDMENT A3, 2026-08-14): `plan_tokens` -- the popped planning
    region's SIZE, never its text -- was APPENDED after THAT. Tail moved by one more; nothing else.

    RE-ANCHORED A FOURTH TIME (D-HP G1 REMEDIATION D2(b), 2026-08-14): `evidence_slot_dropped` -- clause
    (2b)'s remedy census -- was APPENDED after THAT. Tail moved by one more; nothing else.

    RE-ANCHORED A FIFTH TIME (D-HP-25 V2, 2026-08-15, plan 10.30.6): `evidence_geo_dropped` -- the [E]
    geo-containment census -- was APPENDED after THAT. Tail moved by one more; nothing else. NOTE WHAT
    NEEDED NO LINE HERE: V1's `geo_checked` / `geo_mismatch` ride INSIDE `number_handles` and register no
    top-level key, so they shift no column at all.

    RE-ANCHORED A SIXTH TIME (D-LD Sitting-A, 2026-08-18): `tables_queried` -- the per-table usage census,
    the first per-table record production has ever had -- was APPENDED after THAT. Tail moved by one more;
    nothing else, and the invariant this pin polices is again unchanged.
    RE-ANCHORED A SEVENTH TIME (Q-0 S0, 2026-08-28): `timing_ms` -- latency as a first-class per-row
    column -- was APPENDED after THAT. Tail moved by one more; the invariant is again unchanged.
    RE-ANCHORED AN EIGHTH TIME (2026-09-01): four keys APPENDED after THAT -- xc_open_pair +
    xc_open_decline (the D-XT build, 08-29), then xc_regional_decline + quantify_rv_reading_fenced
    (the RV lane, 08-29). Tail moved by four; the invariant is again unchanged."""
    assert tk.TRACE_RECORD_KEYS[-17] == "wrong_slot_audit"
    assert tk.TRACE_RECORD_KEYS[-16] == "slot_orphan_dropped"
    assert tk.TRACE_RECORD_KEYS[-15] == "episode_spans_validated"
    assert tk.TRACE_RECORD_KEYS[-14] == "plan_tokens"
    assert tk.TRACE_RECORD_KEYS[-13] == "evidence_slot_dropped"
    assert tk.TRACE_RECORD_KEYS[-12] == "evidence_geo_dropped"
    assert tk.TRACE_RECORD_KEYS[-11] == "tables_queried"
    assert tk.TRACE_RECORD_KEYS[-10] == "timing_ms"
    assert tk.TRACE_RECORD_KEYS[-9] == "xc_open_pair"
    assert tk.TRACE_RECORD_KEYS[-8] == "xc_open_decline"
    assert tk.TRACE_RECORD_KEYS[-7] == "xc_regional_decline"
    assert tk.TRACE_RECORD_KEYS[-6] == "quantify_rv_reading_fenced"
    assert tk.TRACE_RECORD_KEYS[-5] == "quantify_derived_fenced"    # D-DA append, 09-01
    assert tk.TRACE_RECORD_KEYS[-4] == "quantify_cascade_walk"     # walk charter, 09-01 (10th 12f application)
    assert tk.TRACE_RECORD_KEYS[-3] == "quantify_wave_reads"      # A2 wave counter, same commit
    for older in ("number_handles", "rerank_lane", "walk_shape", "citation_resolved"):
        assert tk.TRACE_RECORD_KEYS.index(older) < tk.TRACE_RECORD_KEYS.index("wrong_slot_audit")
    assert len(set(tk.TRACE_RECORD_KEYS)) == len(tk.TRACE_RECORD_KEYS)
    rec = ev._per_answer_record(_turn(_hp_trace()), "single")
    assert rec["wrong_slot_audit"] == {"scope_checked": 10, "scope_mismatch": 2,
                                       "direction_checked": 4, "direction_mismatch": 1}
    assert ev._per_answer_record(_turn({}), "single")["wrong_slot_audit"] is None   # absent-as-None


def test_the_strip_class_tuples_are_the_verifiers_own_spellings():
    """A CONTRACT WITH verify.py, pinned because its failure mode is silent: a class renamed at the verify
    seam and not here reads as 0 forever -- which is exactly the "metric family that congratulates the
    wave" D5 forbids. `number_unbacked` is deliberately in BOTH the killed and the blinded tuple: it is
    killed by a NEW FENCE (the digit-lint) and blinded by the ORDERING, and reporting it in one place only
    would hide one of the two mechanisms."""
    assert emfmod.KILLED_CLASSES == ("fabricated_citation", "ledger_cascade", "number_unbacked",
                                     "undeclared_unsupported")
    assert emfmod.RESIDUAL_CLASSES == ("no_lexical_overlap", "quote_mismatch", "foreign_regime_name",
                                       "index_out_of_range")
    assert emfmod.BLINDED_CLASSES == ("number_mismatch", "number_unbacked")
    # D-HP-25 RE-PIN (2026-08-15, plan 10.30.6): the BINDING VERIFIER's two classes join, because a
    # receipt naming the wrong GEOGRAPHY is a wrong receipt exactly as one naming the wrong PERIOD is.
    # Excluding them would count the finds and not the finding, and 10.30.6 pre-refused that before any
    # number existed to argue about. THEY THEREFORE CONSUME R11's FROZEN CEILING OF 15 POOLED PER
    # TREATMENT ARM, and the 15 does not move to accommodate them.
    assert emfmod.MIS_BOUND_CLASSES == ("slot_scope_mismatch", "direction_sign_mismatch",
                                        "geo_mismatch", "evidence_geo_contradiction")
    # THE PROJECTION DEDUP IS UNCHANGED AND STAYS EXACT: `MIS_BOUND_PROJECTION` mirrors element [0] only,
    # and `answer._resolve_number_handles` seats the geo check inside the direction check's `else`, so
    # ONE HANDLE CAN CHARGE AT MOST ONE of the three [N] classes -- no handle contributes a scope term
    # and a geo term, so nothing is double-counted.
    assert emfmod.MIS_BOUND_PROJECTION == "scope_mismatch"
    assert emfmod.MIS_BOUND_CLASSES[0] == "slot_scope_mismatch"
    assert emfmod.BARE_DIGIT_CLASS == "bare_digit"
    # CONFLICT 4: `number_mismatch` is NOT a mis-binding term. Under handle-prose it goes to zero by
    # ORDERING (the verifier sees prose with no digits), so counting it as mis-binding would report an
    # instrument artifact as the wave's #1 risk.
    assert "number_mismatch" not in emfmod.MIS_BOUND_CLASSES
    assert "number_mismatch" in emfmod.BLINDED_CLASSES


def test_the_successor_family_is_derived_once_and_reaches_the_row():
    """ONE PRODUCER: the artifact column and the CloudWatch counter read the SAME arithmetic, so a
    dashboard and a gate readout can never disagree about the same turn."""
    by = {"fabricated_citation": 2, "ledger_cascade": 1, "number_unbacked": 3, "undeclared_unsupported": 1,
          "no_lexical_overlap": 4, "quote_mismatch": 1, "number_mismatch": 6, "bare_digit": 2,
          "slot_scope_mismatch": 1, "direction_sign_mismatch": 1}
    rec = ev._per_answer_record(_turn(_hp_trace(by)), "single")
    q = rec["dhp_successor"]
    assert q == emfmod.quality_counters(_hp_trace(by))
    assert q["unconstructible_count"] == 7                       # 2 + 1 + 3 + 1
    assert q["residual_strips"] == 5                             # 4 + 1 (+0 +0: two classes NEVER fired)
    assert q["blinded_class_count"] == 9                         # number_mismatch 6 + number_unbacked 3
    # H1 FIX Z1 RE-PIN -- ALL THREE TERMS, WITH THE PROJECTION DEDUPLICATED. `wrong_slot_audit` is built
    # FROM the same two counters (`answer._wrong_slot_audit`), so summing it verbatim counted the SCOPE
    # class twice; the rule at `emf.MIS_BOUND_CLASSES` adds only its EXCESS over its own mirror. The
    # fixture above is deliberately INCOHERENT (by_rule scope 1 vs projection 2) to prove the excess leg
    # still reports a pre-mirror artifact's scope events instead of dropping them: 1 + 1 + (2 - 1) = 3.
    assert q["mis_bound_count"] == 3
    # ...and on a COHERENT row -- the only shape a live turn can produce, since the folder writes both --
    # all three classes present pool to scope + direction, in the artifact AND in emf, from ONE producer.
    coherent = _hp_trace({"slot_scope_mismatch": 4, "direction_sign_mismatch": 7, "bare_digit": 2},
                         wrong_slot_audit={"scope_checked": 12, "scope_mismatch": 4,
                                           "direction_checked": 11, "direction_mismatch": 7})
    assert emfmod.quality_counters(coherent)["mis_bound_count"] == 11
    assert ev._per_answer_record(_turn(coherent), "single")["dhp_successor"]["mis_bound_count"] == 11
    assert q["bare_digit_strips"] == 2 and q["bare_digit_escapes"] == 5   # CONVICTIONS vs ESCAPES
    assert q["handles_unresolvable"] == 3                        # [N] 2 + [E] 1
    assert q["substitution_load"] == 10                          # [N] 7 + [E] 3


def test_a_clean_row_reads_zero_and_never_raises_a_keyerror():
    """THE READING RULE (folded review G21): `by_rule` accrues by `get(rule, 0) + 1`, so a CLEAN ROW STORES
    `{}` and a direct subscript would raise on precisely the rows a gate hopes for."""
    q = emfmod.quality_counters(_hp_trace({}))
    assert q["unconstructible_count"] == 0 and q["residual_strips"] == 0 and q["blinded_class_count"] == 0


def test_the_non_reasoning_lane_is_excluded_by_name_not_zero_filled():
    """D-HP-17's DENOMINATOR ACCOUNTING (the CYCLE-8 "no silent denominators" rule). numbers_only / live
    turns are verified by `orchestrator._verify_numbers_answer` and carry `enabled` False; D-HP's contract
    does not bind them in the first build, so a fake 0 from that lane would dilute every counter it pools
    into. G1 clause (5) reads the excluded ids."""
    assert emfmod.quality_counters({"citation_verifier": {"enabled": False, "by_rule": {}}}) is None
    assert emfmod.quality_counters({}) is None and emfmod.quality_counters(None) is None
    rows = [_turn(_hp_trace({"fabricated_citation": 2})),
            {"q": {"id": "numbers_row"}, "rubric": {},
             "out": {"trace": {"citation_verifier": {"enabled": False}}}}]
    b = ev._baseline_json(rows, run_kind="single", model="m", judged=False, eval_set="s",
                          graph_version="v", corpus_fp="f", mode="deep_hp")
    tot = b["dhp_successor"]
    assert tot["rows_counted"] == 1 and tot["rows_excluded"] == ["numbers_row"]
    assert tot["unconstructible_count"] == 2


def test_the_honesty_rider_ships_as_three_numbers_in_one_dict():
    """PRE-REGISTERED AND READ TOGETHER, NEVER APART: `unconstructible_count` is satisfiable by RENAMING a
    class, so the gate reports it beside `bare_digit_strips` (the class D-HP-12 routes those sentences
    into) and RAW `strips`. All three on the SAME live-row denominator -- `total_strips` above pools the
    excluded lane too, which is why this dict carries its own."""
    rows = [_turn(_hp_trace({"bare_digit": 3})), _turn(_hp_trace({"bare_digit": 1}))]
    tot = ev._baseline_json(rows, run_kind="single", model="m", judged=False, eval_set="s",
                            graph_version="v", corpus_fp="f", mode="deep_hp")["dhp_successor"]
    assert tot["unconstructible_count"] == 0 and tot["bare_digit_strips"] == 4 and tot["strips"] == 8
    # ...and the number-avoidance instrument, denominated per ANSWER against the census's 19.8 mean.
    assert tot["substitution_load"] == 20 and tot["substitution_load_mean"] == 10.0


def test_the_r11_per_row_tripwire_records_ids_not_a_verdict():
    """R11: any single row at `mis_bound_count >= 3` (~3 of ~21 rendered figures = ~14%) is recorded BY ID.
    This is why `wrong_slot_audit.scope_mismatch` had to be a PER-ROW column: a per-run census alone makes
    the ceiling uncheckable at the row level it is written at."""
    # H1 FIX Z1 RE-PIN: the row is written COHERENTLY (the folder mirrors the render census into `by_rule`,
    # and `wrong_slot_audit` projects the same counters), so the tripwire fires on scope + direction and
    # the projection adds nothing -- which is the whole point of the dedup rule.
    hot = _turn(_hp_trace({"slot_scope_mismatch": 2, "direction_sign_mismatch": 2},
                          wrong_slot_audit={"scope_checked": 6, "scope_mismatch": 2,
                                            "direction_checked": 4, "direction_mismatch": 2}))
    cold = _turn(_hp_trace({}, wrong_slot_audit={"scope_checked": 9, "scope_mismatch": 0,
                                                 "direction_checked": 2, "direction_mismatch": 0}))
    cold["q"] = {"id": "cold"}
    tot = ev._baseline_json([hot, cold], run_kind="single", model="m", judged=False, eval_set="s",
                            graph_version="v", corpus_fp="f", mode="deep_hp")["dhp_successor"]
    assert tot["mis_bound_rows_ge_3"] == ["r1"] and tot["mis_bound_count"] == 4
    # ...and the DIRECTION term is visible at all, which it was not: every one of its convictions deleted a
    # sentence while `mis_bound_count`, `mis_bound_rows_ge_3` and the MisBound counter all read 0.
    only_dir = _hp_trace({"direction_sign_mismatch": 5},
                         wrong_slot_audit={"scope_checked": 5, "scope_mismatch": 0,
                                           "direction_checked": 5, "direction_mismatch": 5})
    assert emfmod.quality_counters(only_dir)["mis_bound_count"] == 5


def test_the_emf_counters_are_fleet_dimensioned_only(monkeypatch):
    """R14 (ratified): a CloudWatch dimension bills per DISTINCT COMBINATION, so five always-on counters on
    the turn emitter's (intent x model x mode) set is a recurring monthly bill for a cut Logs Insights can
    already produce from the lane fields. They ride their OWN emit call with `dimensions=None` -- which is
    also why this is one line to change if the decision is ever revisited.

    `emit()` still attaches the LANE set (source / rerank_backend), so `source=serving` stays filterable --
    the same dimension D-HP-20 change (1) needs the WIDGET to start using, and the reason that change is a
    panel edit rather than a code edit."""
    seen: list = []
    monkeypatch.setattr(emfmod, "emit", lambda metrics, **kw: seen.append((metrics, kw)))
    emfmod.emit_quality(_hp_trace({"fabricated_citation": 1, "no_lexical_overlap": 2}))
    assert len(seen) == 1
    metrics, kw = seen[0]
    assert kw["dimensions"] is None                              # NEVER the turn emitter's dimension set
    assert set(metrics) == {"Unconstructible", "ResidualStrips", "BareDigits", "HandlesUnresolvable",
                            "MisBound"}                          # exactly the five R14 priced
    assert metrics["Unconstructible"] == 1 and metrics["ResidualStrips"] == 2
    assert metrics["BareDigits"] == 5 and metrics["MisBound"] == 2
    assert all(u == "Count" for u in kw["units"].values())
    seen.clear()
    emfmod.emit_quality({"citation_verifier": {"enabled": False}})
    assert seen == []                                            # the numbers lane never touches the panel


def test_emit_quality_is_fail_open_like_every_other_emit():
    """Telemetry must never break or slow a turn -- the module's opening law. A malformed trace returns
    None / emits nothing rather than raising into the serving path."""
    assert emfmod.quality_counters({"citation_verifier": {"enabled": True, "by_rule": "not-a-dict"}}) is None
    emfmod.emit_quality({"citation_verifier": "garbage"})         # no exception


def test_the_composition_census_denominator_boundary_is_recorded_where_it_is_read():
    """H0-FOLD RESIDUAL 2 (10.9), discharged. `composition_census.n_evidence` CHANGED DENOMINATOR at the
    H0 hoist on the desk lanes -- pre-dedup evidence appearances -> deduped DOCUMENTS (`uniq`), the same
    population the rendered menu and `n_ev` bind to. Nothing gates on the column (D-MW-17 recorded-only),
    so no gate clause moves; what would have broken is a later wave pooling both definitions in one read.
    The boundary is recorded in the REGISTRY -- the one place every consumer of the column already looks --
    and pinned here so it cannot be tidied away."""
    src = inspect.getsource(tk)
    head = src.split('"composition_census"')[1].split('"number_handles"')[0]
    assert "82b213a0" in head and "deduped" in head and "source_key" in head


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# 7. H2 (D-HP-17/18/20) -- THE METRIC TRANSITION: THE CLASS SCAN, THE REFUSAL SURFACE, THE CitedN FIX
#
# Section 2 names THE CLASS SCAN -- never a band -- as the regression detector, and D-HP-18's derivation
# (data/dhp_h2_residual_band.json) records the residual band UNUSABLE, so after this boundary the scan is
# the only pre-D-HP instrument that survives. These pins hold it to being a PRODUCED SURFACE with one
# producer, a named denominator, and an intersection law that a single run cannot satisfy.
# ══════════════════════════════════════════════════════════════════════════════════════════════════════
from leviathan.graphrag import verify as vfmod                                # noqa: E402


def test_the_declared_set_is_every_class_the_ledger_can_charge():
    """G1 clause (4) fails on a class OUTSIDE the declared set, so a set that is not exhaustive over the
    seam's own spellings is a clause pre-registered to fail on the wave's own remedies (the `slot_orphan`
    and `episode_span_unbacked` precedents, plan 10.11 / 10.13). Enumerated in the clause's own order.

    D-HP G1 REMEDIATION D2(b) (2026-08-14) adds the SIXTEENTH, `evidence_handle_in_slot`: clause (2b)'s
    remedy (`answer._drop_evidence_value_slot`) folds its removals into the same ledger, so the class is
    declared in the same change or clause (4) is pre-registered to fail on it. Plan 10.18.2 carries the
    standing obligation that the CLAUSE'S OWN TEXT names it at the re-freeze.

    D-HP-25 (2026-08-15, plan 10.30.6) adds the SEVENTEENTH and EIGHTEENTH, the binding verifier's own:
    `geo_mismatch` (V1, folded via `answer._fold_render_classes`) and `evidence_geo_contradiction` (V2,
    folded via `answer._fold_ledger_class` at both serving bodies). MANDATORY, on the identical argument
    the two precedents above carry: clause (4) is a CLASS SCAN over `by_rule`, so an undeclared class
    FAILS THE CLAUSE ON ITS OWN REMEDY -- a verifier that breaks the gate by WORKING is a defect, not a
    result. The same standing obligation applies: the clause's own text must name both at the
    re-freeze."""
    assert emfmod.G1_DECLARED_CLASSES == (
        "fabricated_citation", "ledger_cascade", "no_lexical_overlap", "number_mismatch", "number_unbacked",
        "quote_mismatch", "index_out_of_range", "foreign_regime_name",
        "undeclared_unsupported",
        "bare_digit", "direction_sign_mismatch", "slot_scope_mismatch",
        "grouped_in_slot", "slot_orphan", "episode_span_unbacked", "evidence_handle_in_slot",
        "geo_mismatch", "evidence_geo_contradiction")
    assert len(set(emfmod.G1_DECLARED_CLASSES)) == len(emfmod.G1_DECLARED_CLASSES)
    # every class named by ANY successor tuple is declared -- otherwise a counter could count a class the
    # class scan would fail the gate on.
    for tup in (emfmod.KILLED_CLASSES, emfmod.RESIDUAL_CLASSES, emfmod.BLINDED_CLASSES,
                emfmod.MIS_BOUND_CLASSES, emfmod.ARM_EXCLUSIVE_CLASSES, (emfmod.BARE_DIGIT_CLASS,)):
        for cls in tup:
            assert cls in emfmod.G1_DECLARED_CLASSES
    # THE SEAM CONTRACT: every spelling verify.py can charge is in the set (a rename there that is not
    # mirrored here reads as an UNDECLARED class and would fail clause (4) on an instrument change).
    vsrc = inspect.getsource(vfmod)
    for cls in ("fabricated_citation", "ledger_cascade", "undeclared_unsupported", "quote_mismatch",
                "foreign_regime_name", "bare_digit", "number_mismatch", "number_unbacked",
                "no_lexical_overlap", "index_out_of_range"):
        assert '"' + cls + '"' in vsrc and cls in emfmod.G1_DECLARED_CLASSES


def test_the_arm_exclusive_count_is_nine_and_it_is_arithmetic_not_a_sentence():
    """G1 clause (3)'s caution: the treatment arm's RAW `stripped` carries classes with NO control-arm
    counterpart, so a raw stripped DELTA is not like-for-like. NF-6 said three, X5 corrected it to five,
    H2 corrected it to SIX -- `episode_span_unbacked` (H1b) folds into the same ledger and its pass
    MUTATES ONLY under `handle_prose` -- and the G1 REMEDIATION corrects it to SEVEN on the identical
    argument: `evidence_handle_in_slot`'s pass is treatment-gated and its census key is not even minted on
    a control turn. The count is read off the tuple instead of re-counted by hand in prose, which is why
    each correction has been one line.

    D-HP-25 (2026-08-15, plan 10.30.6) corrects it to NINE on the identical argument, for the binding
    verifier's two classes: V1's counters are minted only inside the `handle_prose` branch (a control
    census still carries the pinned FOUR keys byte-for-byte) and V2's pass is not called at all on a
    control turn, so neither has a control-arm counterpart."""
    assert emfmod.ARM_EXCLUSIVE_CLASSES == ("bare_digit", "slot_scope_mismatch", "direction_sign_mismatch",
                                            "grouped_in_slot", "slot_orphan", "episode_span_unbacked",
                                            "evidence_handle_in_slot",
                                            "geo_mismatch", "evidence_geo_contradiction")
    assert len(emfmod.ARM_EXCLUSIVE_CLASSES) == 9
    # ...and each one is a RENDER/lint-side class, never one of the verifier's own nine survivors.
    for cls in emfmod.ARM_EXCLUSIVE_CLASSES:
        assert cls not in emfmod.RESIDUAL_CLASSES and cls not in emfmod.KILLED_CLASSES


def test_the_class_scan_reads_rows_and_names_the_undeclared():
    """ONE RUN, and per class BOTH the events and the ROWS charged -- 30.8% of the pre-D-HP corpus's strips
    sat in the worst 10% of answers, so a pooled count alone cannot say whether a class is a spread or a
    single bad row."""
    scan = emfmod.class_scan([{"no_lexical_overlap": 2, "bare_digit": 1},
                              {"no_lexical_overlap": 1},
                              {},                                     # a CLEAN row stores {}
                              {"totally_new_rule": 4}])
    assert scan["rows"] == 4 and scan["total_events"] == 8
    assert scan["pooled"] == {"bare_digit": 1, "no_lexical_overlap": 3, "totally_new_rule": 4}
    assert scan["rows_charged"] == {"bare_digit": 1, "no_lexical_overlap": 2, "totally_new_rule": 1}
    assert scan["undeclared"] == ["totally_new_rule"]
    assert scan["arm_exclusive"] == {"bare_digit": 1} and scan["arm_exclusive_total"] == 1
    assert scan["classes_present"] == ["bare_digit", "no_lexical_overlap", "totally_new_rule"]
    # never raises: junk rows are skipped, not fatal (an instrument is never worth a billed run)
    assert emfmod.class_scan([None, "junk", {"bare_digit": 1}])["pooled"] == {"bare_digit": 1}
    assert emfmod.class_scan(None)["pooled"] == {} and emfmod.class_scan([])["rows"] == 0


def test_the_intersection_law_is_arithmetic_and_one_run_cannot_satisfy_it():
    """Section 2: a new class BLOCKS only if it reproduces in BOTH runs. Pooling the two runs into one scan
    would satisfy the law by ADDITION, which is the shape it exists to refuse -- so the law lives in a
    function that takes TWO scans and `class_scan` deliberately takes one run's rows."""
    a = emfmod.class_scan([{"weird_rule": 1, "other_new": 2}])
    b = emfmod.class_scan([{"weird_rule": 1}])
    assert emfmod.blocking_classes(a, b) == ["weird_rule"]            # reproduced -> blocks
    assert emfmod.blocking_classes(a, emfmod.class_scan([{}])) == []  # once only -> RECORDED, never a block
    assert emfmod.blocking_classes({}, {}) == []


def test_the_class_scan_reaches_the_artifact_with_its_denominator_named():
    """The clause a gate FAILS on used to be computed by a human reading `_verifier_panel`'s markdown line.
    It is a produced column now, on the same rows as `dhp_successor` (CYCLE-8 FIX 4: the non-reasoning lane
    is excluded BY ID, never zero-filled) and from the same producer as the EMF counters."""
    rows = [_turn(_hp_trace({"no_lexical_overlap": 2, "slot_orphan": 1})),
            {"q": {"id": "numbers_row"}, "rubric": {},
             "out": {"trace": {"citation_verifier": {"enabled": False, "by_rule": {"never_read": 9}}}}}]
    b = ev._baseline_json(rows, run_kind="single", model="m", judged=False, eval_set="s",
                          graph_version="v", corpus_fp="f", mode="deep_hp")
    scan = b["dhp_class_scan"]
    assert scan["rows"] == 1 and scan["rows_excluded"] == ["numbers_row"]
    assert scan["pooled"] == {"no_lexical_overlap": 2, "slot_orphan": 1}
    assert scan["undeclared"] == []                       # both are in the frozen declared set
    assert scan["arm_exclusive"] == {"slot_orphan": 1}    # ...and the arm-exclusive half is itemised
    once = emfmod.class_scan([{"no_lexical_overlap": 2, "slot_orphan": 1}])
    once["rows_excluded"] = ["numbers_row"]
    assert scan == once                                   # ONE producer: no second arithmetic anywhere


def test_the_refusal_surface_is_pooled_and_its_budget_question_is_raised_not_decided():
    """`binding_refused` (H1 FIX Z2) is the ONLY record anywhere that a D-HP-13/D-HP-14 refusal fired and
    removed prose, and plan 10.11 records the OPEN QUESTION: it is budgeted by NO G1 clause while the two
    class counters beside it are budgeted at 15 pooled by R11. H2 makes the number readable BEFORE the
    freeze and says so in the artifact -- inventing a ceiling for it would be a builder deciding a
    ratification question."""
    hot = _hp_trace({}, number_handles={"substituted": 4, "handles_dropped": 1, "sentences_dropped": 2,
                                        "unresolvable": 0, "grouped_in_slot": 1,
                                        "direction_sign_mismatch": 2, "slot_scope_mismatch": 1,
                                        "scope_checked": 9, "direction_checked": 7, "binding_refused": 3})
    b = ev._baseline_json([_turn(hot)], run_kind="single", model="m", judged=False, eval_set="s",
                          graph_version="v", corpus_fp="f", mode="deep_hp")
    ref = b["dhp_refusals"]
    assert ref["binding_refused"] == 3                                   # the HANDLES a refusal removed
    assert ref["scope_checked"] == 9 and ref["direction_checked"] == 7   # ...with its own denominators
    assert ref["rows_with_treatment_keys"] == 1
    assert "RAISED, NOT BUDGETED" in ref["refusal_budget_status"]
    # R4's proposed budget is REPORTED, never scored: the mean rides BOTH handle halves ([N] 2 + [E] 0).
    assert ref["sentences_dropped"] == 2 and ref["sentences_dropped_mean"] == 2.0
    # A CONTROL row stamps the four-key census only, so the six treatment keys are ABSENT (not zero) and
    # the two shapes stay distinguishable in the pooled readout.
    ctl = ev._baseline_json([_turn(_hp_trace({}))], run_kind="single", model="m", judged=False,
                            eval_set="s", graph_version="v", corpus_fp="f", mode="deep")["dhp_refusals"]
    assert ctl["rows_with_treatment_keys"] == 0 and ctl["binding_refused"] == 0


def test_the_refusal_census_pools_the_treatment_lane_by_id_and_reports_its_denominator():
    """H2 FOLD 1 (K4). D-HP-17's own H2 sentence says BOTH new header keys reach the artifact "with the
    non-reasoning lane excluded BY ID". `dhp_class_scan` did it; `dhp_refusals` iterated EVERY row and
    then divided by a live-row count it never wrote down -- a numerator and a denominator from two
    different populations, on the ONE number E.5 item 2 asks the owner to ratify a budget against.

    THE DEFENCE THAT EXISTED LIVED IN ANOTHER MODULE: both handle censuses are stamped only inside
    `if verifier.get("enabled")`, so no serving path today produces the polluting row. An instrument
    whose correctness depends on a caller two files away is not an instrument -- and
    `citation_verifier_ran` is the SAME membership test `_class_scan` uses, so there is one rule."""
    hot = _hp_trace({}, number_handles={"substituted": 4, "sentences_dropped": 2, "binding_refused": 3,
                                        "scope_checked": 9, "direction_checked": 7})
    # a NUMBERS-LANE row that (illegally, but not impossibly) carries handle keys: excluded BY ID, and
    # its 5 dropped sentences reach neither the pooled numerator nor the `> 3` id list.
    numbers = {"q": {"id": "numbers_row"}, "rubric": {},
               "out": {"trace": {"citation_verifier": {"enabled": False},
                                 "number_handles": {"binding_refused": 11, "sentences_dropped": 5},
                                 "prose_handles": {"sentences_dropped": 0}}}}
    b = ev._baseline_json([_turn(hot), numbers], run_kind="single", model="m", judged=False,
                          eval_set="s", graph_version="v", corpus_fp="f", mode="deep_hp")
    ref = b["dhp_refusals"]
    assert ref["rows_pooled"] == 1 and ref["rows_excluded"] == ["numbers_row"]
    assert ref["binding_refused"] == 3                      # the excluded lane's 11 is NOT pooled
    assert ref["sentences_dropped"] == 2                    # ...nor its 5 dropped sentences
    assert ref["sentences_dropped_mean"] == 2.0             # numerator and denominator, one population
    assert ref["rows_sentences_dropped_gt_3"] == []         # the excluded row cannot be named here
    # the denominator is in the ARTIFACT, not only in the arithmetic (the CYCLE-8 "no silent
    # denominators" rule) and it is the SAME pair `dhp_class_scan` already carries.
    scan = b["dhp_class_scan"]
    assert (ref["rows_pooled"], ref["rows_excluded"]) == (scan["rows"], scan["rows_excluded"])


def test_the_cited_n_counter_stops_undercounting_grouped_citations():
    """D-HP-20 (H2). The shipped `CitedN` regex is SOLITARY-ONLY, so it counted `[N13, N14]` as ZERO
    citations; handle-prose converts grouped citations into solitary slot handles, which would INFLATE the
    cited-vs-injected ratio for a reason that is pure grammar and no behaviour change at all. `CitedN` is
    the honest count now and `CitedNSolitary` carries the pre-D-HP arithmetic byte-identical beside it, so
    the historical series has a live continuation instead of a silent redefinition."""
    import re as _re
    from leviathan.graphrag import orchestrator as orch
    ans = "The crush ran hot [N13, N14] while stocks fell [N2]. Again [N2] and the sibling [N1, N1b]."
    assert len(set(_re.findall(r"\[N\d+\]", ans))) == 1               # the OLD arithmetic: only [N2]
    assert orch._cited_n_ordinals(ans, 1) == 5                        # 13, 14, 2, 1, 1b -- rows, not tokens
    # the (index, suffix) PAIR is the identity: a headline and its sibling are two DIFFERENT rows, and
    # collapsing them is the mis-binding `answer._n_handle_pairs` exists to prevent.
    assert orch._cited_n_ordinals("[N1] and [N1b]", 0) == 2
    assert orch._cited_n_ordinals("", 0) == 0 and orch._cited_n_ordinals(None, 0) == 0
    assert orch._cited_n_ordinals(object(), 7) == 7                   # fail-open to the caller's count


def test_the_cited_n_counters_ride_the_same_emf_line_with_units():
    """Both counters are emitted, both as Counts. The WIDGET restatement is the infra owner's item (R14) --
    terraform is a co-tenant path this wave does not touch -- so the code side must at minimum make the
    honest series exist before D-HP's own arms move the panel."""
    from leviathan.graphrag import orchestrator as orch
    src = inspect.getsource(orch.respond)
    assert '"CitedN": cited_n, "CitedNSolitary": cited_n_solitary' in src
    assert '"CitedNSolitary": "Count"' in src
    assert "_cited_n_ordinals(_ans, cited_n_solitary)" in src


def test_clause_2b_finally_has_an_instrument():
    """G1 clause (2b) pre-registers `bare_handle_escapes == 0` and, until H2, the name appeared in NO
    module, trace key or column -- a clause of a frozen gate that no artifact could answer (the C2/U3
    class). It catches exactly what clause (2) cannot: a FULLY RESOLVED grouped token in a value slot,
    which the renderer leaves untouched BY DESIGN, so `unresolvable` reads 0 while the reader receives
    `[N13, N14]` where a figure belongs.

    Computed at the `register_leaks` seam off the ASSEMBLED BODY -- nothing in the serving renderer moves
    for a gate readout -- and RECORDED ON BOTH ARMS, because a zero-bar clause with no measured control-arm
    noise floor is not a measurement."""
    out = {"answer": "Stocks fell to [N13, N14] and use of [E2] rose. Crush was 3.2 [N5]. See [E1].",
           "trace": {"citation_verifier": {"enabled": True, "by_rule": {}, "stripped": 0,
                                           "claim_count": 3, "checked": 2}}}
    assert ev._bare_handle_escapes(out) == 2          # `to [N13, N14]` and `of [E2]`: cue + surviving token
    # NOT an escape: a token standing beside a figure the model typed, or with no value cue in front of it.
    assert ev._bare_handle_escapes({"answer": "Crush was 3.2 [N5]. See [E1]."}) == 0
    assert ev._bare_handle_escapes({}) == 0 and ev._bare_handle_escapes({"answer": None}) == 0
    assert ev._bare_handle_escapes({"answer": object()}) == 0                     # never raises
    rec = ev._per_answer_record({"q": {"id": "r1"}, "rubric": {}, "out": out}, "single")
    assert rec["bare_handle_escapes"] == 2
    assert list(rec)[-1] == "bare_handle_escapes"     # APPENDED at the tail, never interleaved
    tot = ev._baseline_json([{"q": {"id": "r1"}, "rubric": {}, "out": out}], run_kind="single", model="m",
                            judged=False, eval_set="s", graph_version="v", corpus_fp="f",
                            mode="deep_hp")["dhp_successor"]
    assert tot["bare_handle_escapes"] == 2 and tot["bare_handle_escape_rows"] == ["r1"]


def test_clause_8_has_a_produced_denominator_and_it_is_the_extractor_the_clause_names():
    """H2 FOLD 1 (K1). Clause (8) carried the MIRROR of the clause-(2b) defect H2 had just closed: the
    NUMERATOR (`substitution_load_mean`) shipped as a column while the bar it is read against -- 0.6 x
    the CONTROL arm's mean typed-numeral count per answer on the same deck -- had no shipped producer,
    so the one clause that fails G1 "regardless of the strip classes" was not computable from the
    artifacts.

    NO SECOND EXTRACTOR IS MINTED, which is the whole of D-HP-3: the count IS the already-pooled
    `bare_digit_escapes` = `trace["bare_digit_count"]` = `answer._count_bare_digits`, i.e.
    `verify._mask_handles` + `_claim_numbers_with_decimals` over the PRE-VERIFY `tldr` + `mechanism` --
    the text `raw_draft.preverify_*` snapshots, and the extractor `dhp_census.json` itself ran, which is
    what makes the census anchor of 19.8 numerals per answer commensurable with this column at all."""
    # ONE PRODUCER for the factor and the multiply, so the eval column, a gate reader and a later
    # re-read of the stored corpus cannot disagree about the bar.
    assert emfmod.SUBSTITUTION_FLOOR_FACTOR == 0.6
    assert emfmod.substitution_floor(19.8) == 11.88               # the census anchor through the bar
    assert emfmod.substitution_floor(0) == 0.0 and emfmod.substitution_floor(None) == 0.0
    assert emfmod.substitution_floor(object()) == 0.0             # never raises
    # ...and the count really is the extractor the clause names, on the text the clause names.
    from leviathan.graphrag import answer as _an
    assert _an._count_bare_digits({"tldr": "Crush ran 12.4 and 3.2 [N1].",
                                   "mechanism": "Stocks fell 7 percent."}) == 3
    # BOTH ARMS, on the SAME live-row denominator as the numerator it is read against.
    rows = [_turn(_hp_trace({})), _turn(_hp_trace({}))]
    for arm in ("deep_hp", "deep"):
        tot = ev._baseline_json(rows, run_kind="single", model="m", judged=False, eval_set="s",
                                graph_version="v", corpus_fp="f", mode=arm)["dhp_successor"]
        assert tot["rows_counted"] == 2 and tot["bare_digit_escapes"] == 10   # 5 typed numerals x 2
        assert tot["typed_numeral_mean"] == 5.0
        assert tot["substitution_floor"] == 3.0                   # 0.6 x 5.0 -- the CONTROL arm's bar
        assert tot["substitution_floor"] == emfmod.substitution_floor(tot["typed_numeral_mean"])
        # the clause stays a TWO-ARTIFACT read: the instrument produces both halves and compares
        # neither (10.0 >= 3.0 is the gate owner's reading across two runs on ONE deck).
        assert tot["substitution_load_mean"] == 10.0


# ======================================================================================================
# 8. D-HP B2 (plan E.6) -- --only-ids: THE ROW FILTER A PRE-REGISTERED NAMED SUBSET EXECUTES THROUGH
#
# THE DEFECT THIS CLOSES: E.5-R item 1 froze G1's shape_esc arm at the 30g 7-row HUNGRY split and REJECTED
# the 12-row reading BY NAME -- and nothing in the tree could run 7 rows. Every prior shape_esc artifact
# records n_answers = 12 because the restriction was applied at READ time, i.e. the artifact described a
# different experiment from the one the packet froze. These pins hold the mechanism to three laws: an
# unknown id is a HARD ERROR that names it (never a silent skip, which would shrink a pre-registered
# denominator quietly); the rows come out in DECK order (so the split is a function of the deck alone);
# and the filter is RECORDED in the artifact while `eval_set` stays the deck's canonical stem.
# ======================================================================================================
_DECK = [{"id": "a", "q": "?"}, {"id": "b", "q": "?"}, {"id": "c", "q": "?"}, {"id": "d", "q": "?"}]

# E.5-R item 1 / data/dhp_g1/manifest_d1.json -- VERBATIM, in the manifest's order (which is the deck's).
_G1_HUNGRY_SEVEN = ["shape_esc_episode_us_drought", "shape_esc_episode_cocoa_harmattan",
                    "shape_esc_vintage_brazil_soy", "shape_esc_vintage_palm_stocks",
                    "shape_esc_chain_sugar_ethanol", "shape_esc_regime_oilshare",
                    "shape_esc_ctx_orange_juice"]


def test_only_ids_selects_exactly_the_named_rows_and_never_reorders_the_deck():
    """The rows are the named ones and ONLY the named ones; the ORDER is the deck's, not the argument's,
    so two invocations of the same split are the same run."""
    assert [q["id"] for q in ev.select_queries(_DECK, "c,a")] == ["a", "c"]
    assert [q["id"] for q in ev.select_queries(_DECK, "d,b,a,c")] == ["a", "b", "c", "d"]
    assert [q["id"] for q in ev.select_queries(_DECK, " b , c ")] == ["b", "c"]   # whitespace tolerated
    assert [q["id"] for q in ev.select_queries(_DECK, "b,b")] == ["b"]            # a repeat is not a dup row
    assert [q["id"] for q in ev.select_queries(_DECK, ["a", "d"])] == ["a", "d"]  # list form, same law


def test_an_unknown_id_is_a_HARD_ERROR_THAT_NAMES_IT_never_a_silent_skip():
    """The fail-open shape a frozen gate cannot survive: a typo'd id silently dropped runs a SMALLER
    population than the one pre-registered while the artifact still claims the deck."""
    with pytest.raises(ValueError) as e:
        ev.select_queries(_DECK, "a,zzz_not_in_deck,c")
    assert "zzz_not_in_deck" in str(e.value)                  # the id itself, not just a count
    assert "a" in str(e.value) or "ABSENT" in str(e.value)
    with pytest.raises(ValueError) as e2:                     # every missing id is named, not just the first
        ev.select_queries(_DECK, "nope1,nope2")
    assert "nope1" in str(e2.value) and "nope2" in str(e2.value)


@pytest.mark.parametrize("bad", ["", "   ", ",", " , , "])
def test_an_empty_filter_refuses_rather_than_reading_as_the_whole_deck(bad):
    with pytest.raises(ValueError):
        ev.select_queries(_DECK, bad)


def test_the_G1_FROZEN_SEVEN_select_seven_rows_of_the_SHIPPED_shape_esc_deck():
    """The packet's own ids against the deck file as it ships: 7 of 12, and the seven are exactly the
    deck's `expected_shape: true` rows post-30g(a). If a deck edit ever renames one of these, THIS pin
    reddens rather than the arm running six rows and calling itself the split."""
    import pathlib

    import yaml as _yaml
    p = (pathlib.Path(__file__).resolve().parents[2] / "configs" / "graphrag"
         / "eval_queries_shape_esc_v1.yaml")
    deck = (_yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("queries") or []
    assert len(deck) == 12                                    # the whole deck, the 12-row reading E.5-R rejects
    picked = ev.select_queries(deck, ",".join(_G1_HUNGRY_SEVEN))
    assert len(picked) == 7
    assert [q["id"] for q in picked] == _G1_HUNGRY_SEVEN       # deck order == the manifest's order
    assert all(q.get("expected_shape") for q in picked)        # the 30g hungry half, by the deck's own key


def test_the_row_filter_key_is_ABSENT_from_an_unfiltered_artifact():
    """Byte-shape: an unfiltered run's baseline is exactly what it was before this flag existed -- the key
    is ABSENT, not null and not empty, so no stored reader and no stored artifact's key set moves."""
    import json as _json
    kw = dict(run_kind="single", model="m", judged=False, eval_set="s", graph_version="v", corpus_fp="f")
    plain = ev._baseline_json([], **kw)
    assert "row_filter" not in plain
    assert _json.dumps(ev._baseline_json([], **kw, row_filter=None)) == _json.dumps(plain)
    assert list(ev._baseline_json([], **kw, row_filter=None)) == list(plain)


def test_the_row_filter_key_carries_the_SORTED_ids_and_the_count_and_leaves_eval_set_ALONE():
    """`eval_set` stays the DECK's canonical stem -- a subset must not rename the arm -- and the subset is
    stated in the one place a clause population is read from."""
    rows = [{"q": {"id": "b"}, "rubric": {}, "out": {}}, {"q": {"id": "a"}, "rubric": {}, "out": {}}]
    rf = ev._row_filter_record([q["q"] for q in rows])
    assert rf == {"ids": ["a", "b"], "count": 2}               # SORTED, and the count is of the id list
    doc = ev._baseline_json(rows, run_kind="single", model="m", judged=False,
                            eval_set="eval_queries_shape_esc_v1", graph_version="v", corpus_fp="f",
                            row_filter=rf)
    assert doc["eval_set"] == "eval_queries_shape_esc_v1"      # NOT renamed by the subset
    assert doc["row_filter"] == {"ids": ["a", "b"], "count": 2}
    assert doc["n_answers"] == 2                              # the clause populations read the FILTERED count
    assert list(doc).index("row_filter") < list(doc).index("per_answer")


def test_the_record_is_computed_from_the_rows_that_SURVIVED_not_from_the_argument():
    """A record built from the argument could describe a selection the run did not make."""
    picked = ev.select_queries(_DECK, "d,a")
    assert ev._row_filter_record(picked) == {"ids": ["a", "d"], "count": 2}


def test_the_filter_is_applied_in_main_BEFORE_the_dry_run_and_BEFORE_run_spawns_workers():
    """A filter applied inside a worker would be a per-row SKIP, not a population -- and the dry-run cost
    estimate would price rows that never run."""
    src = inspect.getsource(ev.main)
    assert '"--only-ids"' in src
    assert src.index("select_queries(") < src.index("args.dry_run")
    assert src.index("select_queries(") < src.index("rows = run(")
    assert "row_filter=row_filter" in src                      # ...and it reaches the artifact
    assert "only_ids" in inspect.getsource(ev.select_queries)


def test_submit_eval_forwards_only_ids_and_omitting_it_stays_byte_identical():
    mk = _submit_eval().build_command
    cmd = mk(**_BASE, via_orchestrator=True, only_ids="r1,r2")
    assert cmd[cmd.index("--only-ids") + 1] == "r1,r2"         # forwarded VERBATIM, unparsed
    assert cmd.index("--only-ids") == cmd.index("--queries") + 2     # it rides the deck it restricts
    assert mk(**_BASE, via_orchestrator=True) == mk(**_BASE, via_orchestrator=True, only_ids=None)
    assert "--only-ids" not in mk(**_BASE, via_orchestrator=True)
    mod = _submit_eval()
    assert '"--only-ids"' in inspect.getsource(mod.main) and "only_ids=args.only_ids" in \
        inspect.getsource(mod.main)


def test_only_ids_with_a_convo_deck_refuses_on_BOTH_sides_rather_than_being_ignored():
    """The eval CLI and the submitter refuse the same pairing: a convo deck has no ROW ids, and a flag
    quietly ignored is the silent-skip defect wearing a different hat."""
    with pytest.raises(ValueError):
        _submit_eval().build_command(queries=None, convos="configs/graphrag/eval_convos_v1.yaml",
                                     model="m", judge=False, judge_model="j", k=5, only_ids="r1")
    esrc = inspect.getsource(ev.main)
    assert "--only-ids selects rows of a --queries deck" in esrc
