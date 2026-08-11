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
    assert pl.REASON_DOWNSTREAM in pl._STRUCTURAL_REASONS and pl.REASON_CLOSURE in pl._STRUCTURAL_REASONS


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
