"""D-MW-15 STEP-0 [R7-FINAL] -- the calibration census harness, unit-tested with NO network, NO S3,
NO model load.

The census is a CALIBRATION instrument: its output sizes R7's two per-seed allocations
(`per_seed_budget`, `per_seed_reserve`) under a rule pre-committed before the run. The pre-R7
headroom-vs-displacement fork it was authored against was RETIRED by the R7 amendment (D-MW-15 (i)
DEDICATED-SLOT FIRING) and is not tested here because it no longer exists. What is pinned:

  * `base_admissions` -- the mirror of planner._closure_plan step (1) / the walk's admission loop.
    If this drifts, every number is wrong in the SAME direction and the drift is invisible.
  * THE CALIBRATION RULE at both of its boundaries: the provisional FLOOR (demand below 12/3 does not
    lower the knob) and the RATIFICATION multiple (p75 > 2x provisional flags, never auto-raises).
  * THE NO-VERDICT GATE (review finding 6): a `--limit` or sub-minimum population may not carry a
    quotable calibration.
  * STRATIFICATION by realized seed count (finding 3), and the fact that a demand unit is a
    (walk, seed) pair -- including seeds whose demand is ZERO, which must stay in the distribution.
  * PER-SEED AGGREGATES PUBLISHED ON THE ROW (finding 2): the walk row carries per_seed_kept /
    per_seed_eligible / kept_by_depth, so a completed run answers the calibration by re-reading its
    JSON instead of paying for a second full pass.
  * SEED ATTRIBUTION across a tracked hop -- the per-CONTRACT grouping and the per-SEED rollup are
    different numbers and both are published.
  * BASE-ARITHMETIC HEALTH IN BOTH DIRECTIONS (finding 5): the invariant is one-sided, so the
    over-counting direction is caught by an exactness floor plus a checkable un-instrumented-wave
    explanation.
  * THE DEFAULTS that findings 1 and 4 corrected: seed ceiling 6, hop fence ON.
  * the HOOK on a synthetic walk (exact-cosine embedder, injected driver_slices) in both the at-knobs
    and uncapped-demand postures, plus the byte-identity of the hooked walk against a real
    closure_reserve=0 control.
  * the ANTI-HASH EMBEDDER fence, in both polarities -- a degenerate embedder is exactly what
    produced the number this census exists to re-measure, and the fence has no override.
  * the SIGNATURE-PARITY fence: a drifted planner._closure_plan must refuse the run, not measure
    something else under the same name.
  * `render()` on a full synthetic report, both with a calibration and under the no-verdict gate: the
    report is the artifact a human reads, and a format crash at the end of a 30-minute run is a lost
    run.
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

_HARNESS = Path(__file__).resolve().parents[2] / "scripts" / "graphrag" / "headroom_census.py"
_spec = importlib.util.spec_from_file_location("headroom_census", _HARNESS)
H = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)


def _e(depth):
    """A planner scored-tuple stand-in: only [3] (kind) and [5] (depth) are read by the mirror."""
    return (0, 0.5, "x", "driver", "corn", depth, None, ("driver", "corn", "x"))


def _row(n_seeds, per_seed_kept, per_seed_eligible, *, budget=None, headroom=(0,), capped=False,
         qid="q", hops=1):
    """A published walk row with every field the summary/render blocks read."""
    budget = budget if budget is not None else H.PROVISIONAL_PER_SEED_BUDGET * n_seeds
    kept = sum(per_seed_kept.values())
    return {"qid": qid, "deck": "d", "question": "?", "arm": "at_knobs", "node_budget": budget,
            "seeds": sorted(per_seed_kept), "n_seeds": n_seeds, "kept": kept,
            "per_seed_kept": per_seed_kept, "per_contract_kept": per_seed_kept,
            "unattributed_kept": 0, "kept_by_depth": {"0": n_seeds, "1": kept - n_seeds},
            "n_hop_contracts": hops,
            "per_seed_eligible": per_seed_eligible, "per_contract_eligible": per_seed_eligible,
            "unattributed_eligible": 0, "eligible_capped": capped,
            "end_of_walk_headroom": max(0, budget - kept),
            "seed_scaled_saturated": kept >= H.PROVISIONAL_PER_SEED_BUDGET * n_seeds,
            "n_invocations": len(headroom), "headroom_by_invocation": list(headroom),
            "eligible_by_invocation": [sum(per_seed_eligible.values())] * len(headroom),
            "kept_before_by_invocation": [n_seeds], "base_n_by_invocation": [kept - n_seeds],
            "headroom_positive": any(h > 0 for h in headroom),
            "max_headroom": max(headroom), "eligible_any": any(v > 0 for v in per_seed_eligible.values()),
            "max_eligible": max(list(per_seed_eligible.values()) or [0]),
            "can_fire": any(h > 0 for h in headroom) and any(v > 0 for v in per_seed_eligible.values()),
            "eligible_sample": []}


# -- the base/headroom arithmetic ------------------------------------------------------------------
def test_base_admits_seeds_past_a_full_budget():
    # d==0 is admitted by fiat on both sides of the mirror (planner.py:256 and :508).
    assert len(H.base_admissions([_e(0), _e(0), _e(1)], 10, 10)) == 2


def test_base_stops_exactly_at_the_budget():
    assert len(H.base_admissions([_e(1)] * 8, 6, 10)) == 4


def test_base_empty_wave():
    assert H.base_admissions([], 3, 10) == []


def test_base_is_admissions_not_candidates():
    # the failure mode the mirror exists to avoid: a wide wave counted as if all of it were admitted
    # would report headroom far below zero (clamped to 0) on walks that genuinely have slack.
    assert len(H.base_admissions([_e(1)] * 40, 0, 32)) == 32
    assert len(H.base_admissions([_e(1)] * 20, 0, 32)) == 20


def test_base_under_the_demand_budget_admits_everything():
    """The demand arm's premise: at node_budget 999 the budget cannot bind, so tau is the only filter
    and the admitted count IS demand."""
    assert len(H.base_admissions([_e(1)] * 400, 0, H.DEFAULT_DEMAND_BUDGET)) == 400


def test_headroom_is_the_planner_expression():
    assert H.headroom(20, 6, 32) == 6


def test_headroom_clamps_at_zero():
    assert H.headroom(30, 6, 32) == 0


# -- THE PRE-COMMITTED CALIBRATION RULE ------------------------------------------------------------
def test_the_retired_fork_is_gone():
    """R7 dissolved the headroom-vs-displacement fork (MOAT_WIDTH_WAVE_PLAN.md D-MW-15 (i)). A tool
    that still exported the fork could still be quoted for it."""
    for gone in ("decide", "DECISION_FLOOR", "DECISION_STANDS", "DECISION_DISPLACE"):
        assert not hasattr(H, gone), "%s survived the R7 retrofit" % gone


def test_coverage_percentile_is_the_share_of_demand_units_served():
    assert H.coverage_pct([1, 12, 13, 14], 12) == 50
    assert H.coverage_pct([1, 2, 3, 4], 12) == 100
    assert H.coverage_pct([], 12) == 0


def test_rule_floors_at_the_provisional_when_demand_is_small():
    c = H.calibrate_knob([1, 2, 3, 4], H.PROVISIONAL_PER_SEED_BUDGET)
    assert c["p75_demand"] == 3
    assert c["calibrated"] == H.PROVISIONAL_PER_SEED_BUDGET      # FLOORED, never lowered
    assert c["ratification_flag"] is False


def test_rule_raises_to_p75_between_the_floor_and_the_ratification_multiple():
    c = H.calibrate_knob([20] * 10, H.PROVISIONAL_PER_SEED_BUDGET)
    assert (c["calibrated"], c["ratification_flag"]) == (20, False)


def test_rule_flags_ratification_above_twice_the_provisional_and_never_auto_raises():
    c = H.calibrate_knob([25] * 10, H.PROVISIONAL_PER_SEED_BUDGET)
    assert c["ratification_flag"] is True
    assert c["ratification_threshold"] == 24
    assert c["calibrated"] == 25            # the rule's OUTCOME is reported; the knob is not written


def test_ratification_boundary_is_strictly_greater_than():
    assert H.calibrate_knob([24] * 10, H.PROVISIONAL_PER_SEED_BUDGET)["ratification_flag"] is False
    assert H.calibrate_knob([25] * 10, H.PROVISIONAL_PER_SEED_BUDGET)["ratification_flag"] is True


def test_the_reserve_knob_uses_its_own_provisional_and_its_own_multiple():
    assert H.calibrate_knob([6] * 10, H.PROVISIONAL_PER_SEED_RESERVE)["ratification_flag"] is False
    assert H.calibrate_knob([7] * 10, H.PROVISIONAL_PER_SEED_RESERVE)["ratification_flag"] is True


def test_calibrate_carries_both_knobs_and_names_its_sources():
    cal = H.calibrate([12] * 8, [3] * 8)
    assert cal["per_seed_budget"]["calibrated"] == 12
    assert cal["per_seed_reserve"]["calibrated"] == 3
    assert "per_seed_budget" in cal["sources"] and "per_seed_reserve" in cal["sources"]


# -- THE NO-VERDICT GATE (finding 6) ---------------------------------------------------------------
def test_limit_suppresses_the_calibration():
    g = H.verdict_gate(20, 20, 327)
    assert g["no_verdict"] is True and "NO VERDICT" in g["line"] and "20" in g["line"]


def test_sub_minimum_population_suppresses_the_calibration():
    g = H.verdict_gate(H.MIN_POPULATION - 1, 0, 327)
    assert g["no_verdict"] is True and "NO VERDICT" in g["line"]


def test_a_full_population_passes_the_gate():
    assert H.verdict_gate(288, 0, 327) is None
    assert H.verdict_gate(H.MIN_POPULATION, 0, 327) is None


# -- STRATIFICATION + published per-seed aggregates (findings 2 + 3) -------------------------------
def test_summarize_emits_pooled_and_per_stratum_blocks():
    rows = [_row(1, {"corn": 9}, {"corn": 1}), _row(1, {"corn": 11}, {"corn": 0}),
            _row(3, {"a": 20, "b": 21, "c": 22}, {"a": 4, "b": 5, "c": 6})]
    s = H.summarize(rows)
    assert s["n_seeds_histogram"] == {"1": 2, "3": 1}
    assert set(s["by_n_seeds"]) == {"1", "3"}
    assert s["pooled"]["n_walks"] == 3
    assert s["by_n_seeds"]["1"]["n_walks"] == 2


def test_a_demand_unit_is_a_walk_seed_pair_not_a_walk():
    rows = [_row(1, {"corn": 9}, {"corn": 1}), _row(3, {"a": 20, "b": 21, "c": 22}, {"a": 4, "b": 5, "c": 6})]
    assert H.summarize(rows)["pooled"]["per_seed_cosine_demand"]["n"] == 4


def test_a_stratum_is_not_contaminated_by_the_other_seed_counts():
    """The defect finding 3 named: a pooled fraction moves with the deck's seed mix even when walk
    behaviour is identical."""
    rows = [_row(1, {"corn": 9}, {"corn": 1}), _row(3, {"a": 20, "b": 21, "c": 22}, {"a": 4, "b": 5, "c": 6})]
    s = H.summarize(rows)
    assert s["by_n_seeds"]["1"]["per_seed_cosine_demand"]["max"] == 9
    assert s["by_n_seeds"]["3"]["per_seed_cosine_demand"]["min"] == 20


def test_a_zero_demand_seed_stays_in_the_distribution():
    """D-MW-15 (i): a seed with no eligible ancestors is an INSTRUMENT-DEAD row, 'declared not lost'.
    Dropping it would bias the reserve calibration upward."""
    rows = [_row(2, {"a": 5, "b": 5}, {"a": 0, "b": 4})]
    d = H.summarize(rows)["pooled"]["per_seed_reserve_demand"]
    assert d["n"] == 2 and d["min"] == 0 and d["max"] == 4


def test_per_contract_and_per_seed_groupings_are_both_published():
    rows = [_row(1, {"corn": 9}, {"corn": 1})]
    pooled = H.summarize(rows)["pooled"]
    assert "per_seed_cosine_demand" in pooled and "per_contract_cosine_demand" in pooled
    assert "per_seed_reserve_demand" in pooled and "per_contract_reserve_demand" in pooled


def test_demand_values_flattens_every_group():
    rows = [_row(2, {"a": 3, "b": 4}, {"a": 1, "b": 2})]
    assert sorted(H.demand_values(rows, "per_seed_kept")) == [3, 4]
    assert sorted(H.demand_values(rows, "per_seed_eligible")) == [1, 2]


def test_filled_budget_uses_the_rows_own_budget_not_a_global_one():
    """Seed-scaled budgets mean node_budget varies per walk; a global constant would mis-score."""
    rows = [_row(1, {"corn": 12}, {"corn": 0}), _row(3, {"a": 1, "b": 1, "c": 1}, {"a": 0, "b": 0, "c": 0})]
    assert H.summarize(rows)["pooled"]["filled_budget_walks"] == 1


def test_eligible_capped_is_counted_not_swallowed():
    rows = [_row(1, {"corn": 9}, {"corn": 128}, capped=True), _row(1, {"corn": 9}, {"corn": 2})]
    assert H.summarize(rows)["pooled"]["eligible_capped_walks"] == 1


# -- distributions + cross-tabs --------------------------------------------------------------------
def test_distribution_histogram_and_quantiles():
    d = H.distribution([0, 0, 0, 3])
    assert d["histogram"] == {"0": 3, "3": 1}
    assert (d["min"], d["max"], d["positive"]) == (0, 3, 1)
    assert d["positive_frac"] == 0.25
    assert d["p90"] == 3


def test_distribution_empty_is_not_a_crash():
    d = H.distribution([])
    assert d["n"] == 0 and d["median"] is None and d["positive"] == 0


def test_cross_tab_cells_and_total():
    rows = [_row(1, {"a": 4}, {"a": 1}, headroom=(1,)), _row(1, {"a": 6}, {"a": 0}, headroom=(1,)),
            _row(1, {"a": 6}, {"a": 1}, headroom=(0,)), _row(1, {"a": 6}, {"a": 0}, headroom=(0,))]
    ct = H.cross_tab(rows)
    assert sum(ct.values()) == 4
    assert ct == {"headroom_pos__ancestors_pos": 1, "headroom_pos__ancestors_zero": 1,
                  "headroom_zero__ancestors_pos": 1, "headroom_zero__ancestors_zero": 1}
    assert sum(H.cross_tab_3way(rows).values()) == 4


def test_can_fire_is_per_invocation_not_a_conjunction_of_marginals():
    """headroom>0 and ancestors>=1 can both be true across a walk while the mechanism still cannot
    fire additively -- the census must not conflate them."""
    r = _row(1, {"a": 12}, {"a": 2}, headroom=(2, 0))
    r["can_fire"] = False
    s = H.summarize([r])["pooled"]
    assert s["headroom_positive_frac"] == 1.0 and s["eligible_ancestor_frac"] == 1.0
    assert s["can_fire_frac"] == 0.0


# -- population + arm resolution -------------------------------------------------------------------
def test_default_deck_glob_is_the_prior_census_population():
    decks = H.resolve_decks(None)
    assert decks and all(p.name.startswith("eval_queries") for p in decks)


def test_named_decks_resolve_by_stem():
    decks = H.resolve_decks("eval_queries_judged30")
    assert len(decks) == 1 and decks[0].stem == "eval_queries_judged30"


def test_unknown_deck_refuses():
    with pytest.raises(SystemExit):
        H.resolve_decks("no_such_deck_xyz")


def test_population_dedupes_questions_across_decks(tmp_path):
    (tmp_path / "a.yaml").write_text(
        "queries:\n- id: q1\n  question: same question\n- id: q2\n  question: other\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text(
        "queries:\n- id: q3\n  question: same question\n", encoding="utf-8")
    pop = H.load_population([tmp_path / "a.yaml", tmp_path / "b.yaml"])
    assert [r["qid"] for r in pop] == ["a:q1", "a:q2"]


def test_arms_default_is_demand_plus_at_knobs():
    assert H.resolve_arms(None) == ["demand", "at_knobs"]


def test_arm_names_accept_a_hyphen_and_dedupe():
    assert H.resolve_arms("at-knobs,demand,at_knobs") == ["at_knobs", "demand"]


def test_unknown_arm_refuses():
    with pytest.raises(SystemExit):
        H.resolve_arms("flat32")


# -- THE SEED-SCALED BUDGET (finding 1) ------------------------------------------------------------
class _Args:
    demand_budget = H.DEFAULT_DEMAND_BUDGET
    node_budget = H.DEFAULT_FLAT_BUDGET


def test_at_knobs_budget_scales_with_the_realized_seed_count():
    """The blocker finding: a flat 32 is a knob the max preset no longer has. R7 budgets scale per
    seed, so a 3-seed walk gets 3x the cosine allocation a 1-seed walk gets."""
    assert H.arm_budget("at_knobs", 1, _Args) == H.PROVISIONAL_PER_SEED_BUDGET
    assert H.arm_budget("at_knobs", 3, _Args) == 3 * H.PROVISIONAL_PER_SEED_BUDGET
    assert H.arm_budget("at_knobs", 6, _Args) == 6 * H.PROVISIONAL_PER_SEED_BUDGET


def test_demand_arm_budget_is_seed_independent_and_effectively_uncapped():
    assert H.arm_budget("demand", 1, _Args) == H.arm_budget("demand", 6, _Args) == H.DEFAULT_DEMAND_BUDGET


def test_flat_arm_is_the_retired_pre_r7_constant():
    assert H.arm_budget("flat", 3, _Args) == 32


# -- THE CORRECTED DEFAULTS (findings 1 + 4) -------------------------------------------------------
def test_hop_fence_defaults_on():
    """Finding 4: D-MW-13 ships the second-order-hop fence WITH the preset on BOTH P3-A arms, so the
    unfenced walk is the one P3 will never run."""
    assert H.build_parser().parse_args([]).hop_fence == "on"


def test_seed_ceiling_defaults_to_the_r7_ceiling_of_six():
    assert H.build_parser().parse_args([]).max_seeds == H.DEFAULT_SEED_CEILING == 6


def test_default_arms_and_probe_cap():
    a = H.build_parser().parse_args([])
    assert H.resolve_arms(a.arms) == ["demand", "at_knobs"]
    assert a.eligible_probe_n == H.DEFAULT_PROBE_N >= 128
    assert a.limit == 0


# -- the fences ------------------------------------------------------------------------------------
def _fake_ev(cos_target: float, dim: int = 128):
    """A stand-in evidence module whose embedder places the probe pairs at a chosen cosine."""
    class _EV:
        DEFAULT_BACKEND = "fake"

        @staticmethod
        def embed(texts):
            out = []
            for t in texts:
                # first member of each pair -> e0; second -> cos_target*e0 + sin*e1
                second = t in ("maize", "dry weather")
                v = [0.0] * dim
                if second:
                    v[0], v[1] = cos_target, math.sqrt(max(0.0, 1.0 - cos_target ** 2))
                else:
                    v[0] = 1.0
                out.append(v)
            return out

        @staticmethod
        def _cosine(a, b):
            return sum(x * y for x, y in zip(a, b))
    return _EV


def test_embedder_fence_refuses_a_degenerate_hash_embedder():
    with pytest.raises(SystemExit) as exc:
        H.preflight_embedder(_fake_ev(0.0))
    assert "degenerate" in str(exc.value)


def test_embedder_fence_passes_a_semantic_embedder():
    out = H.preflight_embedder(_fake_ev(0.9))
    assert out["dim"] == 128 and min(out["probe_cosines"].values()) >= 0.45


def test_embedder_fence_refuses_a_toy_dimension():
    with pytest.raises(SystemExit) as exc:
        H.preflight_embedder(_fake_ev(0.9, dim=8))
    assert "dimension" in str(exc.value)


def test_signature_fence_refuses_a_drifted_closure_plan():
    def _drifted(scored, kept, graph, *, node_budget):
        return None
    with pytest.raises(SystemExit) as exc:
        H.assert_signature(_drifted)
    assert "signature drifted" in str(exc.value)


def test_signature_fence_accepts_the_shipped_planner():
    _an, _ev, _gph, pl = H._lev()
    H.assert_signature(pl._closure_plan)              # no raise


def test_store_fence_refuses_without_env_and_accepts_the_override(monkeypatch):
    monkeypatch.delenv("EVIDENCE_S3", raising=False)
    monkeypatch.delenv("EVIDENCE_BACKEND", raising=False)

    class _A:
        allow_no_evidence_store = False
    with pytest.raises(SystemExit):
        H.preflight_store(_A())
    _A.allow_no_evidence_store = True
    H.preflight_store(_A())                            # no raise, and it is stamped in the report


# -- the hook, on a synthetic walk -----------------------------------------------------------------
def _worked_case():
    """The at-knobs posture at budget 6, built with the harness's own fixture factory.

    wave 0: corn seed                 -> kept 1
    wave 1: hop(wheat) + a,b,c        -> base 4, headroom 6-(1+4) = 1   (pa is tau-pruned, eligible)
    wave 2: wheat's w1 (budget bites) -> base 1, headroom 6-(5+1) = 0;  kept 6 -> end-of-walk 0
    """
    drv, embed, build = H._self_test_graph()
    ds = [drv("a", 0.90, parents=["pa"]), drv("b", 0.80), drv("c", 0.70), drv("pa", 0.10)]
    hop = {"wheat": [drv("w1", 0.90), drv("w2", 0.85), drv("w3", 0.80)]}
    return build(ds, hop), embed, ["a", "b", "c", "pa", "w1", "w2", "w3"]


def _run_hooked(graph, embed, slices, probe_n=128, budget=6):
    _an, _ev, _gph, pl = H._lev()
    rec = H.Recorder()
    rec.begin("t")
    with H.census_hook(pl, rec, probe_n=probe_n):
        sg = pl.grounded_subgraph("QQ", graph, depth=2, node_budget=budget, max_seeds=1, tau=0.35,
                                  embed=embed, route_fn=lambda q, g: ["corn"], closure_reserve=3,
                                  driver_slices=slices)
    return sg, rec.end(), pl


def test_hook_measures_per_invocation_headroom_at_each_wave_boundary():
    graph, embed, slices = _worked_case()
    sg, invs, _pl = _run_hooked(graph, embed, slices)
    assert [i["headroom"] for i in invs] == [1, 0]
    assert len(sg.nodes) == 6


def test_headroom_diagnostic_still_separates_from_end_of_walk():
    """Retired as a decision input, retained as a recorded diagnostic: this walk is headroom-positive
    and end-of-walk saturated at the same time, and both readings are published."""
    graph, embed, slices = _worked_case()
    sg, invs, _pl = _run_hooked(graph, embed, slices)
    assert any(i["headroom"] > 0 for i in invs)        # per-invocation: positive
    assert 6 - len(sg.nodes) == 0                      # end-of-walk: zero


def test_hook_is_a_no_op_on_the_walk():
    """Byte-identity against the shipped OFF arm -- the claim the whole design rests on."""
    graph, embed, slices = _worked_case()
    sg, _invs, pl = _run_hooked(graph, embed, slices)
    ctl = pl.grounded_subgraph("QQ", graph, depth=2, node_budget=6, max_seeds=1, tau=0.35,
                               embed=embed, route_fn=lambda q, g: ["corn"], closure_reserve=0,
                               driver_slices=slices)
    assert ctl.trace["kept"] == sg.trace["kept"]
    assert ctl.trace["pruned"] == sg.trace["pruned"]
    assert ctl.trace["visited"] == sg.trace["visited"]
    assert sg.trace["cascade_closure"]["reserved"] == []
    assert sg.trace["cascade_closure"]["headroom_used"] == 0


def test_hook_restores_the_real_function():
    graph, embed, slices = _worked_case()
    _sg, _invs, pl = _run_hooked(graph, embed, slices)
    H.assert_signature(pl._closure_plan)


def test_eligibility_finds_the_tau_pruned_backed_ancestor():
    graph, embed, slices = _worked_case()
    _sg, invs, _pl = _run_hooked(graph, embed, slices)
    assert invs[0]["n_eligible"] == 1
    assert invs[0]["eligible"][0]["id"] == "pa"
    assert invs[0]["eligible"][0]["ancestor_of"] == "a"


def test_eligibility_is_zero_when_the_ancestor_is_unbacked():
    """Scarcity and saturation are separable: same headroom, no eligible ancestor."""
    graph, embed, _slices = _worked_case()
    _sg, invs, _pl = _run_hooked(graph, embed, ["a", "b", "c", "w1", "w2", "w3"])
    assert invs[0]["headroom"] == 1 and invs[0]["n_eligible"] == 0


def test_eligible_list_is_retained_whole_for_the_reserve_calibration():
    """Finding 2: the truncated `eligible[:8]` made per-seed reserve demand unrecoverable. The list is
    the raw material of quantity (B) and it carries the grouping key."""
    graph, embed, slices = _worked_case()
    _sg, invs, _pl = _run_hooked(graph, embed, slices)
    assert invs[0]["eligible"] and len(invs[0]["eligible"]) == invs[0]["n_eligible"]
    assert set(invs[0]["eligible"][0]) >= {"id", "contract", "ancestor_of", "chain_depth"}


def test_eligible_capped_flag_fires_only_when_the_probe_cap_bound():
    graph, embed, slices = _worked_case()
    _sg, invs, _pl = _run_hooked(graph, embed, slices, probe_n=128)
    assert all(i["eligible_capped"] is False for i in invs)
    _sg2, invs2, _pl2 = _run_hooked(graph, embed, slices, probe_n=1)
    assert invs2[0]["eligible_capped"] is True and invs2[0]["n_eligible"] == 1


def test_saturated_walk_reports_zero_headroom_and_zero_ancestors():
    drv, embed, build = H._self_test_graph()
    graph = build([drv("f%d" % i, 0.9 - i * 0.01) for i in range(12)])
    sg, invs, _pl = _run_hooked(graph, embed, ["f%d" % i for i in range(12)])
    assert invs and all(i["headroom"] == 0 for i in invs)
    assert all(i["n_eligible"] == 0 for i in invs)
    assert len(sg.nodes) == 6


# -- the demand arm + seed attribution -------------------------------------------------------------
def test_demand_arm_admits_every_tau_survivor():
    """(A)'s premise: with node_budget out of the way the admitted count is DEMAND. The same graph
    that keeps 6 at the knobs keeps 8 uncapped."""
    graph, embed, slices = _worked_case()
    sg, invs, _pl = _run_hooked(graph, embed, slices, budget=H.DEFAULT_DEMAND_BUDGET)
    assert len(sg.nodes) == 8
    assert all(i["headroom"] > 0 for i in invs)
    assert all(k[2] != "pa" for k in sg.trace["kept"])        # tau still binds; only the budget lifted


def test_per_contract_grouping_splits_the_hop_out():
    graph, embed, slices = _worked_case()
    sg, _invs, _pl = _run_hooked(graph, embed, slices)
    per_contract, _per_seed, _un, _bd = H.aggregate_kept(sg.nodes, ["corn"])
    assert per_contract == {"corn": 4, "wheat": 2}


def test_per_seed_grouping_rolls_the_hop_up_to_its_seed():
    """`per_seed_budget` is multiplied by the realized seed count to form the walk's cosine budget, so
    the demand it must cover is a seed's WHOLE subtree, hop drivers included."""
    graph, embed, slices = _worked_case()
    sg, _invs, _pl = _run_hooked(graph, embed, slices)
    _pc, per_seed, unattributed, by_depth = H.aggregate_kept(sg.nodes, ["corn"])
    assert per_seed == {"corn": 6}
    assert unattributed == 0
    assert by_depth == {"0": 1, "1": 4, "2": 1}


def test_seed_root_map_resolves_a_hop_to_its_seed_and_leaves_a_seed_alone():
    graph, embed, slices = _worked_case()
    sg, _invs, _pl = _run_hooked(graph, embed, slices)
    roots = H.seed_root_map(sg.nodes, ["corn"])
    assert roots == {"corn": "corn", "wheat": "corn"}


def test_a_hop_that_is_itself_a_seed_attributes_to_itself():
    graph, embed, slices = _worked_case()
    sg, _invs, _pl = _run_hooked(graph, embed, slices)
    roots = H.seed_root_map(sg.nodes, ["corn", "wheat"])
    assert roots == {"corn": "corn", "wheat": "wheat"}


def test_eligible_ancestors_group_per_contract_and_per_seed():
    graph, embed, slices = _worked_case()
    sg, invs, _pl = _run_hooked(graph, embed, slices)
    per_contract, per_seed, unattributed = H.aggregate_eligible(invs, sg.nodes, ["corn"])
    assert per_contract == {"corn": 1} and per_seed == {"corn": 1} and unattributed == 0


def test_eligible_ancestors_dedupe_across_invocations():
    """The same ancestor eligible in two waves is ONE reserve slot, not two."""
    invs = [{"eligible": [{"id": "pa", "contract": "corn"}]},
            {"eligible": [{"id": "pa", "contract": "corn"}, {"id": "pb", "contract": "corn"}]}]

    class _N:
        kind, contract, depth, via_edge = "driver", "corn", 1, None
    per_contract, per_seed, _u = H.aggregate_eligible(invs, [_N()], ["corn"])
    assert per_contract == {"corn": 2} and per_seed == {"corn": 2}


def test_a_seed_with_no_eligible_ancestors_is_recorded_as_zero():
    class _N:
        kind, contract, depth, via_edge = "contract", "corn", 0, None
    _pc, per_seed, _u = H.aggregate_eligible([], [_N()], ["corn", "wheat"])
    assert per_seed == {"corn": 0, "wheat": 0}


# -- base-arithmetic health, both directions (finding 5) -------------------------------------------
def test_base_arith_health_flags_an_under_counting_mirror():
    good = [{"qid": "a", "kept_before_by_invocation": [1, 5], "base_n_by_invocation": [4, 1],
             "kept": 6, "n_hop_contracts": 1}]
    bad = [{"qid": "b", "kept_before_by_invocation": [1, 5], "base_n_by_invocation": [9, 1],
            "kept": 6, "n_hop_contracts": 1}]
    assert H.base_arith_health(good)["ok"] is True
    assert H.base_arith_health(good)["exact_matches"] == 2
    assert H.base_arith_health(good)["exact_frac"] == 1.0
    assert H.base_arith_health(bad)["ok"] is False


def test_an_over_counting_boundary_is_explained_only_by_an_uninstrumented_wave():
    """The one-sided invariant passes the drift direction that INFLATES headroom. The escape hatch is
    an un-instrumented wave, and that is checkable PER BOUNDARY (retrofit-review finding 2: the old
    per-WALK predicate -- 'did this walk admit any hop anywhere' -- excused every boundary on ~every
    walk, since 94% of contracts carry a tracked hop and hops sort first): an inexact boundary is
    explained only when its excess is covered by hops admitted BETWEEN its two invocation stamps."""
    explained = [{"qid": "c", "kept_before_by_invocation": [1, 9], "base_n_by_invocation": [4, 1],
                  "hops_before_by_invocation": [0, 4], "kept": 10, "n_hop_contracts": 4}]
    # THE CASE THE PER-WALK PREDICATE GOT WRONG: the walk DID admit hops (3 of them) -- but before
    # invocation 0, not between the inexact pair. Walk-level: excused. Boundary-level: unexplained.
    unexplained = [{"qid": "d", "kept_before_by_invocation": [1, 9], "base_n_by_invocation": [4, 1],
                    "hops_before_by_invocation": [3, 3], "kept": 10, "n_hop_contracts": 3}]
    h1, h2 = H.base_arith_health(explained), H.base_arith_health(unexplained)
    assert h1["n_violations"] == h2["n_violations"] == 0        # neither is an invariant violation
    assert h1["inexact_walks"] == h2["inexact_walks"] == 1
    assert (h1["unexplained_inexact_walks"], h1["ok"]) == (0, True)
    assert (h2["unexplained_inexact_walks"], h2["ok"]) == (1, False)


def test_exactness_above_the_floor_tolerates_an_unexplained_boundary():
    """The floor is what makes the check proportionate: a single odd boundary in a large exact
    population is not an abort."""
    rows = [{"qid": "ok%d" % i, "kept_before_by_invocation": [1, 5], "base_n_by_invocation": [4, 1],
             "kept": 6, "n_hop_contracts": 1} for i in range(30)]
    rows.append({"qid": "odd", "kept_before_by_invocation": [1, 9], "base_n_by_invocation": [4, 1],
                 "kept": 10, "n_hop_contracts": 0})
    h = H.base_arith_health(rows)
    assert h["exact_frac"] >= H.BASE_ARITH_EXACT_FLOOR and h["unexplained_inexact_walks"] == 1
    assert h["ok"] is True


# -- the hop-fence (finding 4: ON by default, off is the sensitivity arm) ---------------------------
def test_hop_fence_expands_only_seed_contracts():
    """D-MW-13's not-yet-built second-order-hop fence, applied from outside: at depth 2 the fence is
    exactly 'only a SEED contract expands its cross_links', because a contract node reaches the walk
    only as a seed (d==0) or as a hop child (d>=1)."""
    graph, _embed, _slices = _worked_case()
    fenced = H._HopFencedGraph(graph, ["corn"])
    assert [e["driver_commodity"] for e in fenced.cross_links("corn")] == ["wheat"]
    assert fenced.cross_links("wheat") == []
    assert graph.cross_links("corn")[0]["tracked"] is True     # unfenced graph is untouched


def test_hop_fence_proxy_delegates_everything_else():
    graph, _embed, _slices = _worked_case()
    fenced = H._HopFencedGraph(graph, ["corn"])
    assert set(fenced.contracts) == {"corn", "wheat"}
    assert fenced.driver("corn", "a").id == "a"
    assert fenced.ancestors_by_depth("corn", "a") == {"pa": 1}


# -- the report a human reads ----------------------------------------------------------------------
def _report(calibration):
    rows = [_row(1, {"corn": 9}, {"corn": 1}, qid="a"),
            _row(1, {"corn": 14}, {"corn": 0}, qid="b"),
            _row(3, {"a": 20, "b": 21, "c": 22}, {"a": 4, "b": 5, "c": 6}, qid="c")]

    def _arm(name):
        return {"arm": name, "budget_rule": "rule", "wall_clock_s": 1.0,
                "population": {"n_routed": 3, "n_unrouted": 1, "unrouted_qids": []},
                "instrument": {"n_invocations": 3, "walks_with_zero_invocations": 0,
                               "parity_checked": 2, "parity_mismatches": 0, "parity_qids": [],
                               "base_arith": H.base_arith_health(rows), "probe_errors": 0},
                "summary": H.summarize(rows), "walks": rows}
    return {"run": {}, "population": {"decks": ["d"], "n_questions": 4, "n_unique_total": 4,
                                      "router": "lexical", "limit": 0},
            "knobs": {"arms": ["demand", "at_knobs"], "max_seeds": 6, "depth": 2, "tau": 0.35,
                      "reserve_n": 3, "hop_fence": "on", "eligible_probe_n": 128,
                      "embedder": {"backend": "bge", "dim": 1024, "probe_cosines": {"a~b": 0.8}}},
            "calibration": calibration,
            "arms": {"demand": _arm("demand"), "at_knobs": _arm("at_knobs")}}, rows


def test_render_prints_the_calibration_line_and_the_stratified_table():
    _rep, rows = _report(None)
    cal = H.calibrate(H.demand_values(rows, "per_seed_kept"), H.demand_values(rows, "per_seed_eligible"))
    rep, _ = _report(cal)
    out = "\n".join(H.render(rep))
    assert out.isascii(), "the cp1252 console cannot print this report"
    assert "STRATIFIED BY REALIZED SEED COUNT" in out
    assert "per_seed_budget=12 covers p" in out and "per_seed_reserve=3 covers p" in out
    assert "RULE OUTCOME" in out
    assert "base_arith:" in out                    # finding 5: printed on the instrument line
    assert "DECISION" not in out                   # the retired fork never reappears


def test_render_labels_each_quantity_with_the_arm_that_can_answer_it():
    """A capped arm's admitted count is NOT demand, and an uncapped arm's eligibility is suppressed by
    its own larger covered set. Both are printed, and neither may be quoted for the other's question."""
    rep, _rows = _report(H.calibrate([12] * 8, [3] * 8))
    out = "\n".join(H.render(rep))
    assert "PER-SEED COSINE DEMAND -- CALIBRATION SOURCE for per_seed_budget" in out
    assert "PER-SEED RESERVE DEMAND -- CALIBRATION SOURCE for per_seed_reserve" in out
    assert "NOT demand (the budget bound it)" in out
    assert "SENSITIVITY READING ONLY" in out


def test_render_prints_the_uncapped_arms_reserve_reading_beside_the_rule():
    cal = H.calibrate([12] * 8, [4] * 8)
    cal["per_seed_reserve_uncapped_arm_reading"] = H.calibrate_knob([0] * 8, H.PROVISIONAL_PER_SEED_RESERVE)
    rep, _rows = _report(cal)
    out = "\n".join(H.render(rep))
    assert "the uncapped arm's reserve reading, NOT the rule" in out
    assert "slice-distinct" in out


def test_render_flags_ratification_when_demand_doubles_the_provisional():
    rep, _rows = _report(H.calibrate([30] * 8, [3] * 8))
    out = "\n".join(H.render(rep))
    assert "RATIFICATION FLAG: demand p75 exceeds 2x provisional" in out
    assert "user's call" in out


def test_render_under_the_no_verdict_gate_prints_no_calibration():
    rep, _rows = _report(H.verdict_gate(20, 20, 327))
    out = "\n".join(H.render(rep))
    assert "NO VERDICT: truncated population" in out
    assert "RULE OUTCOME" not in out and "covers p" not in out


# -- the harness's own self-test path --------------------------------------------------------------
def test_self_test_mode_is_green():
    """--self-test is the census's offline conscience; a red one must fail the suite, not the run."""
    assert H.self_test() == 0


def test_main_self_test_returns_zero():
    assert H.main(["--self-test"]) == 0
