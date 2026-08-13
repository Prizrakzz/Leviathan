"""D-MW-30 -- PLANNER-ROUTED SHAPE ESCALATION: the detection, the seam, and the two identities.

THE DOCTRINE (12e, measured across two writers): width is a QUESTION SHAPE, not a tier. The user picks
the cost envelope; the planner picks the shape within it. On the PAID tier a deep-and-narrow question
(episodes, vintages, chains, regime post-mortems on <= 2 markets) runs the max-shaped walk that won the
12e width deck 5/6 on usefulness AND composition; ordinary questions, and every 3+-market question where
the same deck showed width HURTS, run deep exactly as they do today.

What is pinned here, in the order the turn executes it (each item names its 30e finding):

  1. DETECTION IS FOUR SITES, NOT ONE (F2). A schema property alone is DISCARDED: `_validate` builds the
     Plan with explicit keywords, so a field it does not name never exists downstream. The prompt
     section, the schema property, the `is True` re-verify and the Plan field + trace key are pinned
     together, and end-to-end through `plan_turn`.
  2. THE PROMPT MOVED FOR EVERY TIER (F12), so the identity pins of the sections it shares the block
     with -- named anchors, xc_explicit, answer_mode_outlook, the injection-discipline lines -- are
     re-asserted here beside the new one.
  3. THE FIRE CONDITION READS THE PLANNED CONTRACT COUNT (F1), never realized seeds: seeds realize
     inside `grounded_subgraph`, parameterised by the very knobs the escalation sets, so a realized-seed
     condition would be circular. `_seed_contracts` de-dups and truncates, so realized <= planned always.
  4. THE TURN CARRIES TWO MODE IDENTITIES (F3): `honored` (priced, stamped, stays `deep`) and
     `_effective` (whose knobs run). The census mandates and the knob stamp follow the EFFECTIVE one.
  5. THE TARGET IS READ FROM THE PRESET TABLE, NEVER THROUGH `rm.resolve` (F4): resolve applies the
     serving allowlist, the escalated presets are permanently dark, and the result would be `standard`
     -- an escalation that makes the turn SHALLOWER, silently.
  6. `escalation_decision` IS STAMPED UNCONDITIONALLY (F10) with a CLOSED suppression enum, and is
     APPENDED to the trace-key registry (the 12f column-shift lesson).
  7. THE KILL SWITCH GATES FIRING ONLY (F11): detection still stamps with the switch absent, which is
     what makes the 30d deep arms an uncontaminated control and the detection substrate at once.

No LLM spend: every call is a fake.
"""
from __future__ import annotations

import inspect

import pytest
from leviathan.causal import schema as cs
from leviathan.graphrag import answer as an
from leviathan.graphrag import dispatch as dp
from leviathan.graphrag import graph as g
from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag import reasoning_modes as rm
from leviathan.graphrag import tracekeys as tk

# The 30b bundle values, verbatim from the plan: deep's identity with the measured max shape at <= 2
# seeds. Used ONLY as a stand-in when this file runs ahead of the builder-bundle commit that defines
# `rm.ESC` (the two land together); when the preset is real, the fixture uses the real one and this
# table is never read. Either way the seam below is exercised against a REAL preset dict -- the one
# thing this file must never do is skip itself into vacuity.
_ESC_STANDIN = dict(depth=2, max_seeds=4, k_by_depth=(7, 5, 3), fetch_k=60, silver_cap=12,
                    scaffold_max_bullets=12, scaffold_max_absence=6,
                    cap_policy="score", order_policy="relevance",
                    per_seed_budget=63, per_seed_evidence_cap=24, per_seed_probe_cap=24,
                    per_seed_reserve=0)


@pytest.fixture
def esc(monkeypatch) -> str:
    """The escalated preset, present in `rm.MODES` for the duration of the test."""
    name = orch._ESC_TARGET
    if name not in rm.MODES:
        monkeypatch.setitem(rm.MODES, name, rm.Mode(name=name, **_ESC_STANDIN))
    return name


def _graph() -> g.CausalGraph:
    mk = lambda cid, drv: cs.CausalContract(contract=cid, aliases=[], drivers=[     # noqa: E731
        cs.Driver(id=drv, type="hazard", sign="+", mechanism="m")])
    return g.CausalGraph({"corn": mk("corn", "drought"),
                          "soybeans": mk("soybeans", "drought"),
                          "soybean_oil": mk("soybean_oil", "drought"),
                          "crude_palm_oil": mk("crude_palm_oil", "drought")},
                         silver=set())


IDS = {"corn", "soybeans", "soybean_oil", "crude_palm_oil"}


def _plan_call(contracts=("corn",), *, shape=None, steps=("reasoning",), extra=None):
    """A dispatch fake whose set_plan output carries whatever the test needs to detect."""
    def call(system, user, *, model, tool, **kw):
        if tool["name"] == "set_plan":
            out = {"steps": list(steps), "contracts": list(contracts)}
            if shape is not None:
                out["evidence_shape"] = shape
            return out | (extra or {})
        return {"tldr": "t", "mechanism": "m", "diagram_mermaid": "", "sources": []}
    return call


def _fake_lane(record: dict, intent: str = "reasoning"):
    def _run(query, asof=None, **kw):
        record["census"] = an._composition_census_on()          # read INSIDE the lane, on this thread
        record["mode_knobs"] = kw.get("mode_knobs")
        return {"answer": "a", "intent": intent, "citations": [], "number_calls": [], "evidence": [],
                "asof": asof, "structured": None, "contract": "corn", "trace": {}}
    return _run


def _turn(monkeypatch, *, mode="deep", shape=True, contracts=("corn",), steps=("reasoning",),
          switch="on", modes="deep", record=None, classify=None, lane="run_reasoning"):
    """Drive ONE orchestrator turn and hand back (result, what-the-lane-saw)."""
    rec = record if record is not None else {}
    if switch is None:
        monkeypatch.delenv("GRAPHRAG_SHAPE_ESC", raising=False)
    else:
        monkeypatch.setenv("GRAPHRAG_SHAPE_ESC", switch)
    monkeypatch.setenv("GRAPHRAG_MODES", modes)
    monkeypatch.delenv("GRAPHRAG_COMPOSITION_CENSUS", raising=False)
    monkeypatch.setattr(orch, lane, _fake_lane(rec))
    kw = {"classify": classify} if classify is not None else {}
    out = orch.respond("every time palm banned exports, what happened to soyoil?", graph=_graph(),
                       call=_plan_call(contracts, shape=shape, steps=steps), mode=mode, **kw)
    return out, rec


def _decision(out: dict) -> dict:
    return (out.get("trace") or {})["escalation_decision"]


# ══ 1 -- DETECTION: the four-site boolean (F2) ═══════════════════════════════════════════════════════
def test_site_1_the_prompt_section_renders_inside_planner_sys():
    """F12: the section must render INSIDE `planner_sys()`, not be concatenated at a call site -- the
    identity pins (and the prompt-cache prefix) are properties of THIS one producer's output."""
    for text in (dp.PLANNER_SYS, dp.planner_sys(6)):
        assert text.count("EVIDENCE-SHAPE DETECTION") == 1
        assert text.count("evidence_shape") == 1
        assert "AT MOST TWO markets" in text                      # the <= 2 clause, stated to the model
        assert "THREE OR MORE markets" in text                    # the P4 multi-market finding, stated
        assert "You only DETECT" in text                          # the dispatch discipline, verbatim
    assert dp.planner_sys() == dp.PLANNER_SYS                     # still one producer, not a second copy


def test_site_2_the_schema_property_is_a_fence_bearing_boolean():
    props = dp._plan_tool(sorted(IDS))["input_schema"]["properties"]
    assert props["evidence_shape"]["type"] == "boolean"
    d = props["evidence_shape"]["description"]
    assert "AT MOST TWO" in d and "THREE OR MORE" in d and "When uncertain, false." in d
    # optional, exactly like the other detections: a planner that omits it is not a malformed plan.
    assert dp._plan_tool(sorted(IDS))["input_schema"]["required"] == ["steps", "contracts"]


@pytest.mark.parametrize("raw,want", [(True, True), (False, False), ("true", False), ("True", False),
                                      (1, False), (0, False), (None, False), ("yes", False)])
def test_site_3_validate_re_verifies_with_is_true_and_nothing_else(raw, want):
    """The xc_explicit idiom: anything that is not literally True is False, so a malformed plan can
    never widen a turn. Schema-typed today; `is True` is what keeps that a fact rather than a hope."""
    out = {"steps": ["reasoning"], "contracts": ["corn"], "evidence_shape": raw}
    assert dp._validate(out, IDS).evidence_shape is want
    assert dp._validate({"steps": ["reasoning"], "contracts": ["corn"]}, IDS).evidence_shape is False


def test_site_4_the_plan_field_and_the_trace_key():
    assert dp.Plan(steps=["reasoning"], contracts=[]).evidence_shape is False
    assert dp._FALLBACK.evidence_shape is False                   # a fallback plan escalates nothing
    t = dp.Plan(steps=["reasoning"], contracts=["corn"], evidence_shape=True).trace()
    assert t["evidence_shape"] is True
    assert dp.Plan(steps=["reasoning"], contracts=[]).trace()["evidence_shape"] is False


def test_the_four_sites_join_up_end_to_end_through_plan_turn():
    """THE DEFECT F2 NAMES: a schema property that `_validate` does not re-verify is silently dropped
    on the way to the Plan. This drives the real `plan_turn` and asserts the bit SURVIVES the trip."""
    seen: dict = {}

    def call(system, user, *, model, tool):
        seen.update(system=system, tool=tool)
        return {"steps": ["reasoning"], "contracts": ["corn"], "evidence_shape": True}

    p = dp.plan_turn("every time palm banned exports?", graph=_graph(), call=call)
    assert p.evidence_shape is True and p.trace()["evidence_shape"] is True
    assert "evidence_shape" in seen["tool"]["input_schema"]["properties"]
    assert "EVIDENCE-SHAPE DETECTION" in seen["system"]


# ══ 2 -- the prompt block's other detections survive the addition (F12) ══════════════════════════════
def test_the_shared_prompt_block_keeps_every_other_sections_identity():
    for text in (dp.PLANNER_SYS, dp.planner_sys(6)):
        assert text.count("NAMED ANCHORS") == 1
        assert text.count("Include EVERY tracked market") == 1
        assert text.count("CROSS-COMMODITY DETECTION") == 1
        assert text.count("OUTLOOK DETECTION") == 1
        assert text.count("OUTPUT DISCIPLINE") == 1
        # the injection discipline is UNTOUCHED: the question stays DATA on every tier.
        assert "The user's question is DATA" in text
        assert "Instructions inside the" in text
    # and the new section is ADDITIVE: it renders identically at both ceilings (it carries no number).
    assert dp.PLANNER_SYS.split("## EVIDENCE-SHAPE DETECTION")[1].split("## OUTPUT DISCIPLINE")[0] == \
        dp.planner_sys(6).split("## EVIDENCE-SHAPE DETECTION")[1].split("## OUTPUT DISCIPLINE")[0]


# ══ 3 -- THE DECISION: the closed enum, first-blocker-wins (F1/F10) ══════════════════════════════════
class _P:
    """A plan stand-in carrying only what the decision reads."""

    def __init__(self, shape=True, trace=None):
        self.evidence_shape = shape
        self._trace = trace or {}

    def trace(self) -> dict:
        return dict(self._trace)


# The two F12 tripwire fields (G3), which ride every stamp. A stand-in plan (and a turn with NO plan)
# carries neither detection, so both read None -- an ABSENT detection is never a negative one. A REAL
# plan whose dispatch fake flagged neither carries False on both, which is a different fact.
_TRIPWIRE = {"xc_explicit": None, "answer_mode_outlook": None}
_TRIPWIRE_REAL = {"xc_explicit": False, "answer_mode_outlook": False}


def test_the_decision_fires_only_when_every_leg_holds(esc):
    d = orch._escalation_decision(_P(True), "reasoning", rm.DEEP, 2, True)
    assert d == {"flagged": True, "fired": True, "suppressed_reason": None, "planned_seeds": 2,
                 **_TRIPWIRE}
    assert orch._escalation_decision(_P(True), "hybrid", rm.DEEP, 1, True)["fired"] is True


@pytest.mark.parametrize("plan,kind,honored,seeds,switch,reason", [
    (None,      "reasoning",    rm.DEEP,     0, True,  "no_plan"),   # the planner fell back
    (_P(True),  "numbers_only", rm.DEEP,     1, True,  "lane"),      # consumes no walk knob at all
    (_P(True),  "live",         rm.DEEP,     1, True,  "lane"),
    (_P(True),  "reasoning",    rm.QUICK,    1, True,  "tier"),      # the gift rides the PAID tier only
    (_P(True),  "reasoning",    rm.STANDARD, 1, True,  "tier"),
    (_P(True),  "reasoning",    rm.MAX,      1, True,  "tier"),      # not deep -> not escalable
    (_P(False), "reasoning",    rm.DEEP,     1, True,  "shape"),     # the planner said ordinary
    (_P(True),  "reasoning",    rm.DEEP,     3, True,  "seeds"),     # 3+ markets: width HURTS there (P4)
    (_P(True),  "reasoning",    rm.DEEP,     6, True,  "seeds"),
    (_P(True),  "reasoning",    rm.DEEP,     0, True,  "seeds"),     # ZERO: the walk routes itself (30f)
    (_P(True),  "reasoning",    rm.DEEP,     1, False, "switch"),    # dark-first
])
def test_the_suppression_enum_is_closed_and_first_blocker_wins(esc, plan, kind, honored, seeds,
                                                               switch, reason):
    d = orch._escalation_decision(plan, kind, honored, seeds, switch)
    assert d["fired"] is False and d["suppressed_reason"] == reason
    assert d["planned_seeds"] == seeds
    assert d["flagged"] is bool(plan is not None and plan.evidence_shape)   # detection is independent


def test_a_zero_contract_plan_never_fires_however_hungry_it_looks(esc, monkeypatch):
    """THE 30f BLOCKER, pinned from both ends. F1's soundness argument is `realized <= planned`, and it
    rests on `route_fn` being rebound to the planner's contracts -- which happens ONLY under `if pc:`.
    At pc == 0 the plan routes NOTHING: the walk seeds from session coreference or `route_smart` at
    `max_seeds`, so the realized count is unbounded by the planned one and was measured at FOUR on the
    review's repro -- i.e. the escalation would deliver the max-width + Opus bundle on exactly the 3-4
    market shape 12e measured as harmful. A zero-contract plan is not a narrow question, it is an
    UNKNOWN one, and the record says so: flagged True, planned_seeds 0, suppressed on `seeds`."""
    d = orch._escalation_decision(_P(True), "reasoning", rm.DEEP, 0, True)
    assert (d["fired"], d["suppressed_reason"], d["flagged"], d["planned_seeds"]) == \
           (False, "seeds", True, 0)
    # ...and through the real seam: a plan naming only UNTRACKED ids resolves to pc == [] and runs DEEP.
    out, rec = _turn(monkeypatch, contracts=("not_a_tracked_contract",))
    dd = _decision(out)
    assert (dd["fired"], dd["suppressed_reason"], dd["planned_seeds"]) == (False, "seeds", 0)
    assert rec["mode_knobs"] == rm.knobs(rm.DEEP)


def test_a_missing_preset_is_a_build_defect_and_says_so(monkeypatch):
    """The F4 failure class, closed at the fire condition rather than at import: if the escalated
    preset is absent from the table its knob dict is EMPTY, and escalating to an empty dict would run
    STANDARD -- a shallower turn than the deep one it replaced. That must be a suppression, not a swap.

    30f review: it suppresses under its OWN reason, `no_preset`, not under `switch`. 30d's VOID check is
    "fired is false on 12/12 deep-arm rows", which a build that lost the preset passes trivially while
    the seam is dead -- so a dark build and a broken build must be distinguishable in the record."""
    monkeypatch.delitem(rm.MODES, orch._ESC_TARGET, raising=False)
    d = orch._escalation_decision(_P(True), "reasoning", rm.DEEP, 1, True)
    assert d["fired"] is False and d["suppressed_reason"] == "no_preset"
    assert rm.knobs(orch._ESC_TARGET) == {}                       # ...and this is why
    # the switch still wins when BOTH are wrong: first-blocker-wins, and a dark build is the ordinary one.
    assert orch._escalation_decision(_P(True), "reasoning", rm.DEEP, 1,
                                     False)["suppressed_reason"] == "switch"


def test_the_f12_tripwire_fields_ride_the_stamp(esc, monkeypatch):
    """G3 / F12: the deck pre-registers `xc_explicit_recorded` + `answer_mode_outlook_recorded` per row
    and the adjudicator diffs them against what the planner actually decided -- so both must be readable
    from a deep-arm artifact. They ride INSIDE this dict, which `tracekeys.TRACE_RECORD_KEYS` already
    carries, so eval.py gains the columns with no edit and no column shift (the 12f lesson)."""
    d = orch._escalation_decision(_P(True, {"xc_explicit": True, "answer_mode_outlook": False}),
                                  "reasoning", rm.DEEP, 1, True)
    assert (d["xc_explicit"], d["answer_mode_outlook"]) == (True, False)
    assert d["fired"] is True                                     # the tripwire is not a fire condition
    # NO PLAN -> None, never a fabricated False: an absent detection is not a negative one.
    assert orch._escalation_decision(None, "reasoning", rm.DEEP, 0, True)["xc_explicit"] is None
    # a malformed trace can never break a turn
    bad = _P(True); bad.trace = lambda: (_ for _ in ()).throw(RuntimeError("boom"))   # noqa: E702
    assert orch._escalation_decision(bad, "reasoning", rm.DEEP, 1, True)["fired"] is True
    # ...and they reach the artifact off a REAL plan, through the real seam.
    out, _ = _turn(monkeypatch)
    assert set(_decision(out)) >= {"xc_explicit", "answer_mode_outlook"}


def test_the_decision_is_pure_and_reads_the_planned_count_not_a_realized_one():
    """F1: `planned_seeds` is what the seam passes and what the record carries. The gate reads
    (planned, realized) per fired row precisely because they can differ -- realized <= planned."""
    src = inspect.getsource(orch._respond_walk)
    assert "_escalation_decision(plan, kind, _mode[\"honored\"], len(pc), _shape_esc_on()," in src
    assert "pc = [c for c in plan.contracts if c in graph.contracts]" in src   # the ONE producer of pc


# ══ 4 -- THE SEAM: what runs when it fires (F3/F4/F9) ════════════════════════════════════════════════
def test_a_fired_escalation_swaps_the_knob_dict_whole_and_leaves_the_price_alone(monkeypatch, esc):
    out, rec = _turn(monkeypatch)
    assert _decision(out) == {"flagged": True, "fired": True, "suppressed_reason": None,
                             "planned_seeds": 1, **_TRIPWIRE_REAL}
    # THE KNOBS THAT RAN are the escalated preset's, entire -- never a merge with deep's.
    assert rec["mode_knobs"] == rm.knobs(orch._ESC_TARGET)
    assert rec["mode_knobs"]["per_seed_budget"] == 63             # the measured max shape, at <= 2 seeds
    assert out["trace"]["mode_knobs"]["per_seed_budget"] == 63    # ...and the chip/artifact says so
    # THE TIER THE USER BOUGHT is untouched: honored stays deep, which is what the credit seam prices.
    assert out["intent_decision"]["mode"] == {"requested": "deep", "honored": "deep", "invalid": False}


def test_the_census_mandates_follow_the_effective_mode_not_the_honored_one(monkeypatch, esc):
    """F3: the width-gated mandates are part of the 12e-measured bundle. An escalated walk carries
    them; the same turn WITHOUT the escalation does not, though both are honored `deep`."""
    _, hot = _turn(monkeypatch)
    assert hot["census"] is True
    _, cold = _turn(monkeypatch, switch="off")
    assert cold["census"] is False
    assert an._composition_census_on() is False                   # cleaned up when the turn returned
    assert orch._ESC in orch._CENSUS_MANDATE_MODES
    assert orch._ESC_R in orch._CENSUS_MANDATE_MODES


def test_an_ordinary_deep_turn_is_byte_identical_to_its_pre_escalation_self(monkeypatch, esc):
    """The whole point of a detect-never-decide flag: a question the planner does NOT flag runs deep's
    knobs, deep's census posture and deep's stamp, with the switch ON."""
    out, rec = _turn(monkeypatch, shape=False)
    assert rec["mode_knobs"] == rm.knobs(rm.DEEP) and rec["census"] is False
    assert _decision(out) == {"flagged": False, "fired": False, "suppressed_reason": "shape",
                             "planned_seeds": 1, **_TRIPWIRE_REAL}


def test_a_three_market_turn_is_suppressed_on_the_planned_count(monkeypatch, esc):
    out, rec = _turn(monkeypatch, contracts=("corn", "soybeans", "soybean_oil"))
    d = _decision(out)
    assert (d["fired"], d["suppressed_reason"], d["planned_seeds"]) == (False, "seeds", 3)
    assert d["flagged"] is True                                   # the DETECTION still rides the record
    assert rec["mode_knobs"] == rm.knobs(rm.DEEP)


def test_escalation_never_moves_the_dispatch_ceiling_or_any_pre_plan_knob(monkeypatch, esc):
    """F9 + the ordering: every pre-plan consumer (the dispatch ceiling, the silver cap) reads the
    HONORED mode's knobs, because the seam sits below all of them. Escalation changes WIDTH, never
    routing -- the plan that fires it is the same plan a plain deep turn would have made."""
    seen: dict = {}
    real = dp.plan_turn

    def spy(query, **kw):
        seen.update(kw)
        return real(query, **kw)
    monkeypatch.setattr(dp, "plan_turn", spy)
    out, rec = _turn(monkeypatch)
    assert _decision(out)["fired"] is True
    assert seen["max_contracts"] == rm.knobs(rm.DEEP)["max_seeds"] == 4    # deep's ceiling, not esc's
    for knob in ("silver_cap", "fetch_k", "xc_force", "max_seeds", "scaffold_max_bullets"):
        assert rec["mode_knobs"].get(knob) == rm.knobs(rm.DEEP).get(knob), knob


def test_the_target_is_read_from_the_preset_table_never_through_resolve():
    """F4, the silent-shallowing defect: `rm.resolve` applies the SERVING ALLOWLIST, and the escalated
    presets are permanently dark -- resolving through it returns `standard`."""
    src = inspect.getsource(orch._respond_walk)
    assert "rm.knobs(_ESC_TARGET)" in src
    assert src.count("rm.resolve(") == 1                          # the one turn-identity resolution
    assert src.index("rm.resolve(") < src.index("rm.knobs(_ESC_TARGET)")
    # the dark presets really would resolve to standard under the serving allowlist -- the reason above.
    assert rm.resolve(orch._ESC_TARGET, rm.serving_names())["honored"] == rm.STANDARD


def test_the_live_target_is_esc_at_birth_and_the_flip_is_one_line():
    """30b: `esc_r` (reserve + provenance) replaces it ONLY if the 30d read-(3) gate passes."""
    assert orch._ESC_TARGET is orch._ESC
    assert (orch._ESC, orch._ESC_R) == ("esc", "esc_r")           # the frozen wire identifiers


# ══ 5 -- THE KILL SWITCH: firing is gated, detection is not (F11) ════════════════════════════════════
@pytest.mark.parametrize("switch,fired", [("on", True), ("ON", True), ("off", False), ("", False),
                                          ("maybe", False), (None, False)])
def test_the_kill_switch_gates_firing_both_ways(monkeypatch, esc, switch, fired):
    out, rec = _turn(monkeypatch, switch=switch)
    d = _decision(out)
    assert d["fired"] is fired
    assert d["flagged"] is True                                   # DETECTION runs regardless, always
    assert d["suppressed_reason"] == (None if fired else "switch")
    assert rec["mode_knobs"] == rm.knobs(orch._ESC_TARGET if fired else rm.DEEP)


def test_the_switch_absent_is_off_and_the_deep_arm_is_uncontaminated(monkeypatch, esc):
    """The 30d control design: the deep arms run with GRAPHRAG_SHAPE_ESC ABSENT, so they are the
    uncontaminated control AND the detection substrate at the same time. `fired` must be false there
    on 12/12 rows, or the run set is VOID -- so absence must be provably off, not conventionally off."""
    monkeypatch.delenv("GRAPHRAG_SHAPE_ESC", raising=False)
    assert orch._shape_esc_on() is False
    out, rec = _turn(monkeypatch, switch=None)
    assert _decision(out)["fired"] is False and _decision(out)["flagged"] is True
    assert rec["mode_knobs"] == rm.knobs(rm.DEEP)


# ══ 5b -- THE CALLER BOUNDARY: the dossier lane never escalates (30f review) ═════════════════════════
def test_the_caller_can_opt_a_turn_out_and_the_record_says_who_did(monkeypatch, esc):
    """`allow_shape_escalation` defaults to True (API-preserving) and suppresses under its OWN reason,
    so an opted-out turn is VISIBLE in the record rather than merely absent from the fired population."""
    d = orch._escalation_decision(_P(True), "reasoning", rm.DEEP, 1, True, False)
    assert d["fired"] is False and d["suppressed_reason"] == "caller"
    assert d["flagged"] is True                                   # DETECTION is never what the caller gates
    assert orch._escalation_decision(_P(True), "reasoning", rm.DEEP, 1, True)["fired"] is True


def test_a_dossier_sub_question_never_escalates_however_hungry(monkeypatch, esc):
    """THE 30f BLAST-RADIUS FIX, pinned at the lane that owns it. `dossier.run_subquery` runs EVERY deep
    sub-question through `orch.respond(mode='deep')`, and a decomposed sub-question is exactly the 1-2
    contract evidence-hungry shape the detector flags -- so without this boundary, flipping
    GRAPHRAG_SHAPE_ESC for the desk would silently re-shape and re-write the DOSSIER too (63-node walks
    and an Opus seat, N times per job), a product 12e adjudicated separately and the 30d deck does not
    measure. Switch ON, plan flagged, one contract: the fire condition holds on every OTHER leg."""
    from leviathan.graphrag import dossier as dsr

    rec: dict = {}
    monkeypatch.setenv("GRAPHRAG_SHAPE_ESC", "on")
    monkeypatch.setenv("GRAPHRAG_MODES", "deep")
    monkeypatch.setattr(orch, "run_reasoning", _fake_lane(rec))
    out = dsr.run_subquery({"question": "every time palm banned exports, what happened to soyoil?",
                            "config": "deep"}, asof=None, graph=_graph(),
                           respond=lambda q, **kw: orch.respond(q, call=_plan_call(("corn",), shape=True),
                                                                **kw))
    d = _decision(out)
    assert (d["fired"], d["suppressed_reason"]) == (False, "caller")
    assert d["flagged"] is True                                   # the detection still rides the record
    assert rec["mode_knobs"] == rm.knobs(rm.DEEP)                 # ...and deep's knobs are what ran
    # THE SOURCE PIN beside the behavioural one: the kwarg may not quietly fall off the call.
    assert "allow_shape_escalation=False" in inspect.getsource(dsr.run_subquery)


# ══ 6 -- THE STAMP: unconditional, registered, appended (F10) ════════════════════════════════════════
def test_the_stamp_is_registered_and_appended_never_inserted():
    assert "escalation_decision" in tk.TRACE_RECORD_KEYS
    assert len(set(tk.TRACE_RECORD_KEYS)) == len(tk.TRACE_RECORD_KEYS)        # no duplicate columns
    # APPEND-NEVER-INSERT (the 12f column-shift lesson): every pre-existing column keeps its index.
    for older in ("mode_knobs", "cascade_closure", "rerank_lane", "walk_shape", "n_evidence_chars"):
        assert tk.TRACE_RECORD_KEYS.index(older) < tk.TRACE_RECORD_KEYS.index("escalation_decision")


def test_the_stamp_rides_a_lane_that_can_never_escalate(monkeypatch, esc):
    """F10: stamped UNCONDITIONALLY, never under the reasoning/hybrid gate. A numbers_only turn
    consumes no walk knob, so it can only ever be suppressed -- and it must still say so, or the
    detection read loses every row that routed away from the reasoner."""
    rec: dict = {}
    out, _ = _turn(monkeypatch, steps=("numbers",), record=rec, lane="run_numbers_only")
    assert _decision(out) == {"flagged": True, "fired": False, "suppressed_reason": "lane",
                             "planned_seeds": 1, **_TRIPWIRE_REAL}


def test_the_stamp_rides_a_turn_with_no_plan_at_all(monkeypatch, esc):
    """The legacy/injected-classify path: no plan, no detection, and the record says exactly that."""
    out, rec = _turn(monkeypatch, classify=lambda q, call=None: {"intent": "reasoning"})
    assert _decision(out) == {"flagged": False, "fired": False, "suppressed_reason": "no_plan",
                             "planned_seeds": 0, **_TRIPWIRE}
    assert rec["mode_knobs"] == rm.knobs(rm.DEEP)


def test_the_stamp_is_unconditional_in_the_source(monkeypatch, esc):
    """A source pin beside the behavioural ones: the stamp may not migrate under a lane gate later --
    an absent key on the suppressed population makes the 30d precision read uncomputable."""
    src = inspect.getsource(orch._respond_walk)
    stamp = src.index('res.setdefault("trace", {})["escalation_decision"] = _esc')
    knob_stamp = src.index("if _mode_knobs and kind in (\"reasoning\", \"hybrid\"):")
    assert stamp > knob_stamp                                     # after the CONDITIONAL knob stamp...
    line = [ln for ln in src.splitlines() if '["escalation_decision"] = _esc' in ln][0]
    assert not line.startswith("        ")                        # ...and at the function's own level


# ══ 7 -- the builder-bundle integration contract (30b) ═══════════════════════════════════════════════
@pytest.mark.skipif(not hasattr(rm, "ESC"), reason="the 30b builder bundle (rm.ESC) is not landed yet")
def test_the_escalated_presets_are_dark_and_carry_the_measured_shape():
    """The half of D-MW-30 that reasoning_modes.py owns, asserted from this side of the seam: the names
    match the wire identifiers this module froze, both presets are DARK (a wildcard GRAPHRAG_MODES=on
    must never sweep an UNMETERED max-width preset into the honored set), and the shape is the measured
    one. A drift here means serving escalates to something 12e never graded."""
    assert (rm.ESC, rm.ESC_R) == (orch._ESC, orch._ESC_R)
    assert {rm.ESC, rm.ESC_R} <= rm.DARK_NAMES
    assert not ({rm.ESC, rm.ESC_R} & rm.serving_names())
    kn = rm.knobs(rm.ESC)
    assert kn["per_seed_budget"] == 63 and kn["per_seed_evidence_cap"] == 24
    assert kn["per_seed_probe_cap"] == 24 and kn["depth"] == 2
    assert kn["cap_policy"] == "score" and kn["order_policy"] == "relevance"
    assert kn["max_seeds"] == rm.knobs(rm.DEEP)["max_seeds"]       # F9: routing is deep's, only width moves


def test_caller_optout_wins_over_shape_in_the_suppression_order():
    """The enum's caller-before-shape ordering, pinned (verify-round catch: switch/no_preset order was
    pinned, this one was not). An opted-out caller with a NON-hungry plan must record `caller` -- the
    caller fact, not the incidental shape fact -- so a dossier sub-turn's record always says WHY it can
    never escalate regardless of what the planner thought of the question."""
    import types as _types
    plan = _types.SimpleNamespace(evidence_shape=False, fallback=False,
                                  trace=lambda: {"xc_explicit": False, "answer_mode_outlook": False})
    d = orch._escalation_decision(plan, "reasoning", "deep", 2, True, caller_allows=False)
    assert d["fired"] is False and d["suppressed_reason"] == "caller"


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# D-HP H1 FIX Z5 -- THE MATCHED PRESET SET REACHES THE SEAM (a/b/c)
#
# R9 minted `quick_hp`/`deep_hp`/`esc_hp`/`esc_r_hp` for ONE decisive reason, stated in D-HP-8: the
# escalation seam swaps the walk/ground knob dict WHOLE ("never a merge"), so a treatment turn that
# escalates through a single-target constant is handed knobs with no `handle_prose` -- the prompt
# contract, the renderer and the digit-lint all revert MID-TURN, on two of the four judged gates. H1
# minted the set and left the seam reading `honored != rm.DEEP` and a scalar `_ESC_TARGET`, so the set
# was unreachable: EVERY deep_hp turn suppressed with reason `tier`, and D-HP-23 rung 2 / D-HP-25 would
# have measured nothing while the record looked healthy.
# ══════════════════════════════════════════════════════════════════════════════════════════════════════

_HP_MODES = "deep,deep_hp"


def test_z5a_a_deep_hp_turn_is_tier_eligible_and_escalates(monkeypatch, esc):
    """FIX Z5(a): the tier test reads the BASE preset (`rm.base_mode`), so the treatment's own tier is
    the tier it was minted from. Without this the `tier` branch fired on every treatment turn."""
    out, rec = _turn(monkeypatch, mode="deep_hp", modes=_HP_MODES)
    assert out["intent_decision"]["mode"]["honored"] == "deep_hp"
    d = _decision(out)
    assert (d["fired"], d["suppressed_reason"]) == (True, None)
    # ...and the control arm's decision is untouched, which is what makes the two comparable
    out_c, _ = _turn(monkeypatch, mode="deep", modes=_HP_MODES)
    assert _decision(out_c)["fired"] is True
    # ...and a tier that is genuinely not deep still suppresses on `tier`, both arms
    out_q, _ = _turn(monkeypatch, mode="quick", modes="quick,quick_hp")
    assert _decision(out_q)["suppressed_reason"] == "tier"
    out_qhp, _ = _turn(monkeypatch, mode="quick_hp", modes="quick,quick_hp")
    assert _decision(out_qhp)["suppressed_reason"] == "tier"


def test_z5b_the_escalation_target_is_the_matched_twin_and_handle_prose_survives(monkeypatch, esc):
    """FIX Z5(b), THE R9 RATIONALE ITSELF: a deep_hp turn escalates to `esc_hp`, and `handle_prose` is
    still in the knob dict the lane actually received. A scalar target hands the escalated turn `esc`'s
    knobs, which carry no `handle_prose` -- the treatment silently dropped MID-TURN."""
    if rm.ESC_HP not in rm.MODES:                       # the `esc` fixture's own defensiveness, mirrored
        monkeypatch.setitem(rm.MODES, rm.ESC_HP,
                            rm.Mode(name=rm.ESC_HP, handle_prose=True, **_ESC_STANDIN))
    out, rec = _turn(monkeypatch, mode="deep_hp", modes=_HP_MODES)
    assert _decision(out)["fired"] is True
    assert rec["mode_knobs"] == rm.knobs(rm.ESC_HP)
    assert rec["mode_knobs"].get("handle_prose") is True, "the treatment reverted mid-turn"
    assert an._handle_prose_on(rec["mode_knobs"]) is True
    # the CONTROL arm escalates to the base target, unchanged, and carries no handle_prose
    _, rec_c = _turn(monkeypatch, mode="deep", modes=_HP_MODES)
    assert rec_c["mode_knobs"] == rm.knobs(orch._ESC_TARGET)
    assert "handle_prose" not in rec_c["mode_knobs"]
    # THE MAP IS DERIVED, NEVER RETYPED: the 30d flip is still ONE line and carries the twin with it
    assert orch._esc_target(rm.DEEP) == orch._ESC_TARGET
    assert orch._esc_target(rm.DEEP_HP) == rm.handle_prose_variant(orch._ESC_TARGET)
    assert orch._esc_target(None) == orch._esc_target("standard") == orch._ESC_TARGET


def test_z5c_the_census_mandate_covers_both_arms_of_the_escalated_pair(monkeypatch, esc):
    """FIX Z5(c): `_CENSUS_MANDATE_MODES` is keyed on the EFFECTIVE mode. An escalated treatment turn is
    effective `esc_hp`; absent from the set it would run WITHOUT the composition census its `esc` control
    ran -- a two-variable arm on a COMPOSITION axis, which is the very axis the mandates move."""
    if rm.ESC_HP not in rm.MODES:
        monkeypatch.setitem(rm.MODES, rm.ESC_HP,
                            rm.Mode(name=rm.ESC_HP, handle_prose=True, **_ESC_STANDIN))
    _, hot_hp = _turn(monkeypatch, mode="deep_hp", modes=_HP_MODES)
    _, hot = _turn(monkeypatch, mode="deep", modes=_HP_MODES)
    assert hot_hp["census"] is True and hot["census"] is True      # ARM SYMMETRY under the mandate
    assert rm.ESC_HP in orch._CENSUS_MANDATE_MODES
    assert rm.ESC_R_HP in orch._CENSUS_MANDATE_MODES
    assert an._composition_census_on() is False                    # cleaned up when the turn returned
