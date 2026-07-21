"""RV-v2 surface lane (D): the reserved '## Cross-commodity' prompt rules (W3.1-W3.3) and the eval-pin
battery (W4.5). Pure/hermetic -- no AWS, no LLM, no pg. Prompt tests read the static _SYSTEM_CASCADE string;
pin tests drive eval._cascade_asserts / _cascade_stats on hand-built out dicts."""
from __future__ import annotations

import os

from leviathan.graphrag import answer as an
from leviathan.graphrag import eval as ev


# -- W3.1/W3.2/W3.3 prompt: the reserved heading rules --------------------------------------------------
def test_cross_commodity_heading_is_injected_only_never_volunteered():
    s = an._SYSTEM_CASCADE
    assert "## Cross-commodity" in s
    # render-gate: emitted ONLY when the engine supplies the block, never from prose (D5 + P9 discipline)
    assert "ONLY when a 'CROSS-COMMODITY' line is present" in s
    assert "never volunteer a cross-commodity comparison from prose" in s
    # a dedicated heading, NOT a reuse of the v1 cross-country fork heading
    assert "NEVER \n'## Where the record disagrees'" in s or "NEVER '## Where the record disagrees'" in s
    # the no-fork backstop now enumerates the cross-commodity line too
    assert "NO CROSS-COMMODITY line" in s


def test_my_disclosure_is_the_usda_aggregate_framing_single_variant():
    """The ADDENDUM kills the aligned/misaligned binary: ONE disclosure for ALL world-basis pairs -- each
    leg's world balance sheet aggregates differing LOCAL marketing years; the comparison holds at the
    marketing-year grain, not a shared calendar."""
    s = an._SYSTEM_CASCADE
    assert "aggregates differing LOCAL marketing years" in s
    assert "marketing-year grain" in s
    # the dead binary's language must be ABSENT (it was a literal falsehood on the flagship pair)
    assert "early-season" not in s and "do not coincide" not in s and "late-season" not in s
    # world-basis ratio comparability + no cross-commodity level deltas
    assert "world basis" in s and "NEVER compare tonnage LEVELS across commodities" in s


def test_price_language_clause_direction_only():
    s = an._SYSTEM_CASCADE
    assert "narrate price DIRECTION" in s
    assert "verbatim quote from a cited [E]" in s
    # W1.5 fence relocation: "no price table" is false post-registration; the force moves to cite-or-silent
    assert "NEVER mint an uncited price figure" in s
    assert "spread/basis MAGNITUDES remain derive-word-only" in s
    assert "cite them with their [N] handle" in s


def test_system_cascade_appended_under_quant_flag(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_MENTOR_VOICE", "on")
    monkeypatch.setenv("GRAPHRAG_CASCADE_QUANT", "on")
    assert "## Cross-commodity" in an._system()
    monkeypatch.setenv("GRAPHRAG_CASCADE_QUANT", "off")
    assert "## Cross-commodity" not in an._system()                  # quant off -> no cascade addendum at all


# -- W4.5 eval pins: trace.quantify_reroute_v2 (ENGINE-written), judge-free ------------------------------
def _out(*, v2=0, heading=False, planner="llm", xc_tier=None):
    """A minimal eval out dict. v2 = number of fired cross-commodity pairs in the engine-written trace key;
    heading = whether '## Cross-commodity' rendered in the mechanism; planner = the dispatch decision;
    xc_tier (W2) = intent_decision.xc_detect.tier when the orchestrator stamped one (None = pre-W2 shape)."""
    mech = ("## Cross-commodity\n- [N1] World soybean-oil stocks-to-use MY2025: 8.1%"
            if heading else "## Mechanism\nplain prose, no reserved heading")
    dec = {"planner": planner}
    if xc_tier is not None:
        dec["xc_detect"] = {"tier": xc_tier, "llm_consulted": True, "target_span": "palm"}
    return {"trace": {"quantify": [], "quantify_reroute_v2": [{"pair_id": "veg_oil_soy_palm"}] * v2},
            "structured": {"tldr": "", "mechanism": mech}, "citations": [],
            "intent_decision": dec}


def test_cascade_stats_counts_reroute_v2_pairs():
    assert ev._cascade_stats(_out(v2=0))["reroute_v2_pairs"] == 0
    assert ev._cascade_stats(_out(v2=2))["reroute_v2_pairs"] == 2


def test_positive_pin_passes_when_fired_under_heading():
    q = {"expect": {"reroute_v2_expected": True}}
    assert ev._cascade_asserts(q, _out(v2=1, heading=True))["reroute_v2_expected"] is True
    # positive pin FAILS if the engine fired but no reserved heading rendered
    assert ev._cascade_asserts(q, _out(v2=1, heading=False))["reroute_v2_expected"] is False


def test_negative_pin_passes_when_no_fire_no_heading():
    q = {"expect": {"reroute_v2_expected": False}}
    assert ev._cascade_asserts(q, _out(v2=0, heading=False))["reroute_v2_expected"] is True
    # the HARD gate: a negative pin FAILS if the engine fired (single-commodity/context-mention leaked)
    assert ev._cascade_asserts(q, _out(v2=1, heading=True))["reroute_v2_expected"] is False
    # ...and FAILS if the reserved heading rendered even with an empty trace key (a manufactured heading)
    assert ev._cascade_asserts(q, _out(v2=0, heading=True))["reroute_v2_expected"] is False


def test_negative_pin_fails_on_dispatch_fallback():
    """C11c: a p.fallback turn skips the v2 predicate entirely, so a negative pin must NOT false-green -- the
    pin requires the dispatch planner actually ran (planner=='llm') on the pinned turn."""
    q = {"expect": {"reroute_v2_expected": False}}
    assert ev._cascade_asserts(q, _out(v2=0, heading=False, planner=None))["reroute_v2_expected"] is False
    assert ev._cascade_asserts(q, _out(v2=0, heading=False, planner="llm"))["reroute_v2_expected"] is True


def test_absent_trace_key_reads_as_not_fired():
    """A turn whose trace never carried the key (engine off / older path) -> reroute_v2_pairs 0, so a negative
    pin passes (no fire) and a positive pin fails (no fire)."""
    out = {"trace": {"quantify": []}, "structured": {"tldr": "", "mechanism": "## Mechanism\nprose"},
           "citations": [], "intent_decision": {"planner": "llm"}}
    assert ev._cascade_asserts({"expect": {"reroute_v2_expected": False}}, out)["reroute_v2_expected"] is True
    assert ev._cascade_asserts({"expect": {"reroute_v2_expected": True}}, out)["reroute_v2_expected"] is False


def test_byte_identical_when_pin_absent():
    """A query that declares NO reroute_v2_expected key gets no such assert -- the new branch is inert on
    every existing pin (the flag-off fence at the eval surface)."""
    q = {"expect": {"cascade_fired": False}}
    res = ev._cascade_asserts(q, _out(v2=1, heading=True))            # v2 fired, but the pin is absent
    assert "reroute_v2_expected" not in res
    assert res == {"cascade_fired": True}                             # unchanged: trace.quantify empty -> not fired


# -- W2 (D15 amended): the detection_tier pin -- planner AND-guard, False-never-KeyError ------------------
def test_detection_tier_pin_true_and_false():
    q = {"expect": {"detection_tier": "llm"}}
    assert ev._cascade_asserts(q, _out(xc_tier="llm"))["detection_tier"] is True
    assert ev._cascade_asserts(q, _out(xc_tier="regex"))["detection_tier"] is False
    assert ev._cascade_asserts({"expect": {"detection_tier": "regex"}},
                               _out(xc_tier="regex"))["detection_tier"] is True
    assert ev._cascade_asserts({"expect": {"detection_tier": "none"}},
                               _out(xc_tier="none"))["detection_tier"] is True


def test_detection_tier_pin_fails_on_dispatch_fallback():
    """The C11c AND-guard: a fallback turn never exercised the composite, so even a 'matching' tier stamp
    FAILS the pin rather than false-greening (mirrors reroute_v2_expected)."""
    q = {"expect": {"detection_tier": "llm"}}
    assert ev._cascade_asserts(q, _out(xc_tier="llm", planner=None))["detection_tier"] is False


def test_detection_tier_pin_fails_without_xc_detect_stamp():
    # a pre-W2 / flag-off-image turn: planner ran but no xc_detect key -> False, not a KeyError
    q = {"expect": {"detection_tier": "llm"}}
    assert ev._cascade_asserts(q, _out())["detection_tier"] is False


def test_detection_tier_non_orchestrator_out_false_never_keyerror():
    """D15 stated limit: the default answer.answer() eval path has no intent_decision at all -- the pin
    must yield False (meaningful only on --via-orchestrator runs), never raise."""
    q = {"expect": {"detection_tier": "llm"}}
    out = {"answer": "prose", "citations": []}
    assert ev._cascade_asserts(q, out)["detection_tier"] is False


def test_detection_tier_unknown_expect_keys_still_dropped():
    q = {"expect": {"detection_tier_v9": "llm", "detection_tier": "llm"}}
    res = ev._cascade_asserts(q, _out(xc_tier="llm"))
    assert set(res) == {"detection_tier"}                             # whitelist: unknown keys silently dropped


# -- W2 (D15): reroute_v2_pairs + detection_tier ride the per-answer record -------------------------------
def test_per_answer_record_carries_reroute_v2_pairs_and_tier():
    out = {"answer": "a", "structured": None, "intent": "reasoning", "citations": [],
           "trace": {"quantify_reroute_v2": [{"pair_id": "p"}]},
           "intent_decision": {"planner": "llm", "xc_detect": {"tier": "llm", "llm_consulted": True,
                                                               "target_span": "palm"}}}
    rec = ev._per_answer_record({"q": {"id": "x1"}, "out": out, "rubric": {}}, "single")
    assert rec["reroute_v2_pairs"] == 1 and rec["detection_tier"] == "llm"


def test_per_answer_record_tier_none_on_non_orchestrator_row():
    rec = ev._per_answer_record({"q": {"id": "x2"}, "out": {"answer": ""}}, "single")
    assert rec["reroute_v2_pairs"] == 0 and rec["detection_tier"] is None
