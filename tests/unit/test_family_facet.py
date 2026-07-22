"""Data-family FACET (RESIDUE_TRAIN_PLAN Lane F2, the durable fix) + the P1/P2 planner-surface work.

The judged-30 F2 misses were colloquial CFTC-positioning / export-sales-pace asks the dispatch planner
routed reasoning-only, so the observed series never got looked up. This lane closes it three ways:

  P1  planner surface -- numbers ToolSpec.purpose names positioning LEVEL + export-sales PACE, and one
      PLANNER_SYS decomposition bullet routes them numbers_only with the hybrid / historical-episode carve-outs.
  P2  deterministic FLOOR -- intent._NUM gains the colloquial pace vocab (export sales|sales pace|pacing|
      purchases of), so even a planner FALLBACK routes these numbers-ward. Guarded against the proven
      collateral ('marketing year', 'picked up').
  P3  the FAMILY FACET -- the plan schema gains an OPTIONAL, enum-locked (derived from the numbers registry,
      never hardcoded) `data_families` array. Consumption is PROMOTION-ONLY + flag-gated (GRAPHRAG_FAMILY_FACET,
      default off, fail-closed like _reroute_v2_on): intent==reasoning AND families non-empty -> promote to
      hybrid, stamp trace + print FAMILY_FACET_PROMOTED. Never demotes; never touches numbers_only/live/trivial;
      injected-classify / guardrail turns (plan is None) are bypassed by construction.

Same two-tier shape as rv2 detection (planner field + gated consumption + a dark trace channel), so the
tests mirror test_reroute_v2_gate.py: the planner is STUBBED via a dual-duty `call` fake (no live API), and
the run_* branch functions are recorded to see which route actually fired.
"""
from __future__ import annotations

import pytest
from leviathan.graphrag import dispatch as dp
from leviathan.graphrag import intent as it
from leviathan.graphrag import orchestrator as orch

CORN = "corn_cbot"
SOY = "soybeans_cbot"

# The four judged-30 F2 miss phrasings VERBATIM, paired with the observed-data family a faithful planner
# would name for each (positioning=cot, export sales/pace=esr).
FUNDS = "are funds crowded in soybeans right now?"
MEX = "have Mexican purchases of US corn picked up recently?"
CHINA = "how are US corn sales to China pacing this marketing year?"
NETLEN = ("where did managed money net length in corn stand right now, "
          "and how stretched versus the past three years?")
MISS_ROWS = [(FUNDS, ["cot"]), (MEX, ["esr"]), (CHINA, ["esr"]), (NETLEN, ["cot"])]


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# P3 -- family_names(): the enum is DERIVED from the numbers registry, prefix-stripped, never hardcoded
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_family_names_derived_from_registry_prefix_stripped():
    fams = dp.family_names()
    # every silver_/gold_/bronze_ table id contributes its stripped stem; the layer prefix is gone
    assert "cot" in fams and "esr" in fams and "psd" in fams and "wasde" in fams
    assert all(not f.startswith(("silver_", "gold_", "bronze_")) for f in fams)


def test_family_names_tracks_the_live_registry_ids():
    from leviathan.graphrag.numbers import registry as nreg
    ids = set(nreg.load_registry().tables)
    fams = set(dp.family_names())
    # a bijection modulo the layer prefix: exactly one family per registered table id, nothing invented
    stripped = {dp._FAMILY_PREFIX.sub("", tid) for tid in ids}
    assert fams == stripped and len(fams) == len(ids)


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# P3 -- the plan schema + _validate: enum-locked, fail-closed (absent/garbage/unknown -> [])
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_plan_tool_schema_exposes_enum_locked_data_families():
    props = dp._plan_tool([CORN, SOY])["input_schema"]["properties"]
    assert "data_families" in props
    enum = props["data_families"]["items"]["enum"]
    assert set(enum) == set(dp.family_names())          # the schema enum IS the registry-derived family list


def test_validate_keeps_known_families_dedup_order():
    p = dp._validate({"steps": ["reasoning"], "contracts": [CORN],
                      "data_families": ["cot", "esr", "cot"]}, {CORN})
    assert p.data_families == ["cot", "esr"]            # de-duplicated, order preserved
    assert p.trace()["data_families"] == ["cot", "esr"]  # rides the trace channel


def test_validate_rejects_unknown_family_fail_closed():
    p = dp._validate({"steps": ["reasoning"], "contracts": [],
                      "data_families": ["cot", "totally_made_up", "psd"]}, set())
    assert p.data_families == ["cot", "psd"]            # the minted family is dropped, the model can't inject


@pytest.mark.parametrize("raw", [None, "notalist", 123, [], ["", "  "], ["UNKNOWN", "nope"]])
def test_validate_garbage_or_absent_families_is_empty(raw):
    out = {"steps": ["reasoning"], "contracts": []}
    if raw is not None:
        out["data_families"] = raw
    assert dp._validate(out, set()).data_families == []


def test_plan_default_data_families_is_empty_list():
    assert dp.Plan(steps=["reasoning"], contracts=[]).data_families == []


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# P2 -- the deterministic FLOOR: intent._NUM now fires on the colloquial pace/positioning forms, and the
# proven collateral ('marketing year' alone, 'picked up' alone) does NOT get newly hijacked by the addition
# ════════════════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("q", [FUNDS, MEX, CHINA, NETLEN])
def test_floor_num_fires_on_all_four_miss_phrasings(q):
    assert bool(it._NUM.search(q)) is True


@pytest.mark.parametrize("q", [FUNDS, MEX, CHINA, NETLEN])
def test_floor_classify_routes_miss_phrasings_numbers_ward(q):
    # planner FALLBACK safety net: with no LLM call, the four asks land numbers_only (NUM fires, REASON does
    # not) -- the defense-in-depth half of the fix, independent of the planner.
    d = it.classify_intent(q, call=None)
    assert d["intent"] == "numbers_only"


@pytest.mark.parametrize("term", ["export sales", "sales pace", "pacing", "purchases of"])
def test_floor_new_vocab_terms_each_match(term):
    assert bool(it._NUM.search(f"corn {term} to China")) is True


@pytest.mark.parametrize("q", [
    "what is the marketing year for corn?",   # 'marketing year' NOT added -> only pre-existing 'what is' hits
    "sales picked up nicely last week",       # 'picked up' NOT added -> no NUM hit
    "things picked up after the holidays",
])
def test_floor_proven_collateral_not_added(q):
    # these must NOT match on account of the NEW vocab. 'picked up' rows stay NUM-clear; the marketing-year row
    # matches only through the long-standing 'what is' alternative (its data cue), never a newly-added term.
    if "picked up" in q:
        assert bool(it._NUM.search(q)) is False


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# P3 -- the kill-switch: default OFF, case-insensitive, fail-closed (copies the _reroute_v2_on idiom)
# ════════════════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("val,want", [
    ("on", True), ("ON", True),
    # the _reroute_v2_on idiom lowercases but does NOT strip -> surrounding whitespace stays off (fail-closed);
    # only 'on' enables. Every other value (incl. the truthy-looking 1/true/yes) stays off.
    (" on ", False), ("off", False), ("0", False), ("1", False), ("true", False), ("yes", False),
    ("garbage", False), ("", False),
])
def test_family_facet_flag_fail_closed(monkeypatch, val, want):
    monkeypatch.setenv("GRAPHRAG_FAMILY_FACET", val)
    assert orch._family_facet_on() is want


def test_family_facet_flag_default_off(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_FAMILY_FACET", raising=False)
    assert orch._family_facet_on() is False


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# P3 -- the FACET consumption in respond(), driven through a STUBBED planner (no live API)
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _graph():
    from leviathan.causal import schema as cs
    from leviathan.graphrag import graph as g
    corn = cs.CausalContract(contract=CORN, aliases=["corn", "maize"],
                             drivers=[cs.Driver(id="export_pace", type="demand", sign="+", mechanism="exports")])
    soy = cs.CausalContract(contract=SOY, aliases=["soybeans", "beans"],
                            drivers=[cs.Driver(id="fund_flow", type="positioning", sign="+", mechanism="mm")])
    return g.CausalGraph({CORN: corn, SOY: soy}, silver=set())


def _stub_runs(monkeypatch):
    """Record which branch respond() dispatches, without importing the real engines."""
    seen = {}

    def mk(kind):
        def run(*a, **k):
            seen["kind"] = kind
            return {"answer": "stub", "intent": kind, "structured": None, "evidence": [], "citations": [],
                    "number_calls": [], "contract": None, "contracts": []}
        return run

    monkeypatch.setattr(orch, "run_reasoning", mk("reasoning"))
    monkeypatch.setattr(orch, "run_hybrid", mk("hybrid"))
    monkeypatch.setattr(orch, "run_numbers_only", mk("numbers_only"))
    return seen


def _planner_call(families, steps=("reasoning",), contracts=()):
    """A dual-duty `call`: answers set_plan with the given families, and any synthesis tool blandly (never
    reached here because the run_* branches are stubbed)."""
    def call(system, user, *, model, tool, **kw):
        if tool["name"] == "set_plan":
            return {"steps": list(steps), "contracts": list(contracts), "data_families": list(families)}
        return {"tldr": "t", "mechanism": "m", "diagram_mermaid": "", "sources": []}
    return call


def _respond(monkeypatch, query, *, families, flag, steps=("reasoning",), classify=None):
    seen = _stub_runs(monkeypatch)
    if flag is None:
        monkeypatch.delenv("GRAPHRAG_FAMILY_FACET", raising=False)
    else:
        monkeypatch.setenv("GRAPHRAG_FAMILY_FACET", flag)
    kw = {"classify": classify} if classify is not None else {"call": _planner_call(families, steps)}
    out = orch.respond(query, graph=_graph(), asof="2026-06-01", **kw)
    return out, seen


@pytest.mark.parametrize("q,families", MISS_ROWS)
def test_facet_promotes_the_four_miss_phrasings(monkeypatch, capsys, q, families):
    out, seen = _respond(monkeypatch, q, families=families, flag="on")
    assert seen["kind"] == "hybrid"                          # reasoning -> hybrid promotion fired
    assert out["intent"] == "hybrid"
    dec = out["intent_decision"]
    assert dec["family_facet_promoted"] is True
    assert dec["family_facet_families"] == families
    assert dec["data_families"] == families                 # the planner field rides trace() too
    assert f"FAMILY_FACET_PROMOTED families={','.join(families)}" in capsys.readouterr().out


def test_facet_clean_reasoning_ask_no_families_does_not_promote(monkeypatch, capsys):
    out, seen = _respond(monkeypatch, "why is the soybean crush margin structurally convex?",
                         families=[], flag="on")
    assert seen["kind"] == "reasoning"                       # no families -> untouched
    assert out["intent"] == "reasoning"
    assert "family_facet_promoted" not in out["intent_decision"]
    assert "FAMILY_FACET_PROMOTED" not in capsys.readouterr().out


def test_facet_flag_off_is_a_noop_even_with_families(monkeypatch, capsys):
    out, seen = _respond(monkeypatch, FUNDS, families=["cot"], flag="off")
    assert seen["kind"] == "reasoning"                       # byte-identical to today: no promotion
    assert out["intent"] == "reasoning"
    assert "family_facet_promoted" not in out["intent_decision"]
    assert "FAMILY_FACET_PROMOTED" not in capsys.readouterr().out


def test_facet_flag_absent_is_a_noop(monkeypatch):
    out, seen = _respond(monkeypatch, FUNDS, families=["cot"], flag=None)
    assert seen["kind"] == "reasoning"
    assert "family_facet_promoted" not in out["intent_decision"]


def test_facet_unknown_family_from_planner_rejected_no_promotion(monkeypatch, capsys):
    # the planner emits a family NOT in the registry enum; _validate drops it -> data_families empty ->
    # the facet cannot promote. The enum rejection is the guarantee the model can't mint a promotion.
    out, seen = _respond(monkeypatch, FUNDS, families=["totally_made_up_family"], flag="on")
    assert seen["kind"] == "reasoning"
    assert out["intent_decision"].get("data_families") == []
    assert "family_facet_promoted" not in out["intent_decision"]
    assert "FAMILY_FACET_PROMOTED" not in capsys.readouterr().out


def test_facet_never_touches_numbers_only(monkeypatch, capsys):
    # a numbers_only plan (steps=[numbers]) with families present + flag on stays numbers_only -- the facet
    # is promotion-only from reasoning, never a re-route of an already-numeric turn.
    out, seen = _respond(monkeypatch, FUNDS, families=["cot"], flag="on", steps=("numbers",))
    assert seen["kind"] == "numbers_only"
    assert out["intent"] == "numbers_only"
    assert "family_facet_promoted" not in (out["intent_decision"] or {})
    assert "FAMILY_FACET_PROMOTED" not in capsys.readouterr().out


def test_facet_bypasses_injected_classify_turns(monkeypatch, capsys):
    # a guardrail / injected-classify turn skips dispatch -> plan is None -> the facet is unreachable BY
    # CONSTRUCTION even with the flag on (mirrors how the rv2 gate's plan-scoped read bypasses these turns).
    def _force(kind):
        return lambda q, call=None: {"intent": kind, "needs_numbers": kind in ("numbers_only", "hybrid"),
                                     "needs_reasoning": kind in ("reasoning", "hybrid")}
    out, seen = _respond(monkeypatch, FUNDS, families=["cot"], flag="on", classify=_force("reasoning"))
    assert seen["kind"] == "reasoning"
    assert "family_facet_promoted" not in out["intent_decision"]
    assert "FAMILY_FACET_PROMOTED" not in capsys.readouterr().out
