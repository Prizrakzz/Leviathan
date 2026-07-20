"""Reroute v2 -- THE GATE (lane B): the deterministic detector + the orchestrator LAW that produces the
cross-commodity `xc_request` threaded into the cascade quantify seam. No engine here -- these tests pin the
GATE only: the narrow explicit-ask matcher (RV-W1.1), the C8 target binding, the D7 open-target PAIR_CAP=1,
the D-case hard negatives (RV-W1.4), fail-closed on a raising detector (C12), and byte-identical behavior
when GRAPHRAG_REROUTE_V2 is off. Lanes A (complex_map) and C (engine) build concurrently, so the gate's
lane-A/lane-D dependencies are INJECTED as stubs and the quantify seam is exercised with a recording
`an.answer` -- no real complex_map / census / engine import is required to run this file.
"""
from __future__ import annotations

import types

import pytest
from leviathan.graphrag import dispatch as dp
from leviathan.graphrag import intent as it
from leviathan.graphrag import orchestrator as orch

# canonical loaded-contract slugs (verbatim, as the plan's pair table writes them)
PALM = "malaysian_crude_palm_oil_cme"
SOY = "soybean_oil_cbot"
RAPE = "rapeseed_oil_zce"
CORN = "corn_cbot"
WHEAT = "soft_red_winter_wheat_cbot"
MEAL = "soybean_meal_cbot"


# ── fakes for lane A (complex_map) ────────────────────────────────────────────────────────────────────
class _Pair:
    def __init__(self, pid, a, b, tier="material", complex_name="vegoil_substitution"):
        self.id = pid
        self.pair = (a, b)
        self.complex_name = complex_name
        self.shared_event = "soyoil_palm_premium"
        self.side_a = {"contract": a, "ref": "psd_ending_stock_su_ratio", "country_rule": "world"}
        self.side_b = {"contract": b, "ref": "psd_ending_stock_su_ratio", "country_rule": "world"}
        self.direction = "opposing"
        self.focus_rule = "query"
        self.materiality_tier = tier


class _Map:
    def __init__(self, pairs):
        self.pairs = pairs


def _graph(*slugs):
    return types.SimpleNamespace(contracts={s: None for s in slugs}, version="test")


def _gate(query, *, graph, state=None, detect, route, pairs, resolve=None, realizable=None):
    """Call the gate producer with fully-injected lane-A/lane-D stubs."""
    return orch._xc_request(
        query, graph=graph, state=state,
        detect=detect,
        route=(route if callable(route) else (lambda q, g: list(route))),
        resolve_bare=resolve,
        load_map=lambda: _Map(pairs),
        realizable=(realizable if realizable is not None else (lambda pid: True)))


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# RV-W1.1 -- the detector (is_cross_commodity_explicit): (matched, target_span)
# ════════════════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("q,span", [
    ("palm export ban -- what does that do to soyoil?", "soyoil"),
    ("what does this mean for rapeseed oil?", "rapeseed oil"),
    ("the palm ban's impact on soybean oil?", "soybean oil"),
    ("how does that affect soyoil?", "soyoil"),
    ("does it help or hurt palm?", "palm"),
    ("what about soybean meal?", "soybean meal"),
    ("and soyoil?", "soyoil"),                                    # short typed follow-up (D3)
    ("relative to palm, is soyoil tighter?", "palm"),
    ("read-across to rapeseed oil?", "rapeseed oil"),
])
def test_detector_named_target_captures_x(q, span):
    matched, target = it.is_cross_commodity_explicit(q)
    assert matched is True and target == span


@pytest.mark.parametrize("q", [
    "what else does this affect?",
    "any knock-on effects?",
    "spillover?",
    "what other commodities does this move?",
    "any other commodity affected?",
])
def test_detector_open_target_is_matched_none(q):
    matched, target = it.is_cross_commodity_explicit(q)
    assert matched is True and target is None


def test_detector_relative_value_returns_second_leg():
    # SOURCE resolves via route() in the gate; the detector returns the SECOND named leg as the target span.
    assert it.is_cross_commodity_explicit("soyoil vs palm, which tightens?") == (True, "palm")
    assert it.is_cross_commodity_explicit("which tightens more, soyoil or palm?") == (True, "palm")


@pytest.mark.parametrize("q,span", [
    # 2026-07-19 clean-window positive-pin failure: possessive markers made EVERY shape miss (the capture
    # class excludes apostrophes and _XC_TERM had no apostrophe terminator). The capture must terminate
    # cleanly AT the apostrophe, yielding the bare name. First row is the v4-deck query VERBATIM.
    ("Palm export ban -- what does that do to soybean oil's world stocks-to-use versus palm's?", "palm"),
    ("how does that affect soyoil's stocks-to-use?", "soyoil"),
    ("what's the impact on soybean oil's balance sheet?", "soybean oil"),
    ("what does that do to palm's stocks?", "palm"),
])
def test_detector_possessive_commodity_terminates_at_apostrophe(q, span):
    assert it.is_cross_commodity_explicit(q) == (True, span)


def test_detector_vs_shape_wins_over_named_do_to():
    # "do to X versus Y" must bind Y (the second leg): X is usually the SOURCE itself, and binding X
    # C8-declines the whole ask (target==source). VS is tried before NAMED for exactly this reason.
    assert it.is_cross_commodity_explicit(
        "Palm export ban -- what does that do to soybean oil versus palm?") == (True, "palm")


@pytest.mark.parametrize("q", [
    "how is palm doing today?",                                  # single-commodity status
    "what were corn exports in 2023?",                           # a numbers question
    "corn and soybeans both rallied hard",                       # mid-sentence 'and', not a follow-up ask
    "what does the ban do to palm prices?",                      # subject is not this/that/it -> not matched
    "why did palm rally?",
    "",
])
def test_detector_rejects_non_cross_commodity(q):
    assert it.is_cross_commodity_explicit(q) == (False, None)


@pytest.mark.parametrize("q", [
    # adversarial finding 1: the second commodity appears ONLY inside a DECLARATIVE context/read-across clause;
    # the user's actual ASK is single-commodity ('why did palm rally/move'). The DOES-NOT-DO fence forbids the
    # fork here -- the unanchored impact/read-across/relative-to shapes must NOT fire on a context clause.
    # --- STRONG-boundary variants (period / dash): closed by the original fix ---
    "Palm surged even though the USDA flagged a bigger impact on soybean oil. Why did palm rally?",
    "Palm rallied hard despite the bearish impact on soybean oil demand -- why did palm move?",
    "Palm is up 8%. There's an obvious read-across to soybean oil. Anyway, why did palm rally?",
    "Palm is cheap relative to soybean oil. Why did palm rally?",
    "Soyoil is in surplus with a clear spillover to palm. Why did palm rally?",
    # --- round-2 finding: WEAK boundaries the strong-only splitter missed. A declarative context clause joined
    # to the ask by a COMMA + coordinating conjunction (", so/but/yet/and/then"), or a leading subordinator
    # FRAME ("Given.../With.../Amid.../Because..., <ask>"), is NOT terminated by a strong boundary, so the
    # unanchored impact/read-across/spillover/relative-to shape used to capture the context commodity. The
    # palm<->soyoil pair is the flagship, and "Given X, why did Y" is a very natural single-commodity shape. ---
    "Palm rallied despite the bearish impact on soybean oil, so why did palm move?",       # comma + 'so'
    "Palm rallied hard given the read-across to soybean oil, but why did palm rally?",      # comma + 'but'
    "The read-across to soybean oil is obvious, and why did palm rally?",                   # comma + 'and'
    "Palm broke out, the impact on soybean oil is priced, yet why did palm rally?",         # comma + 'yet'
    "Given the obvious spillover to soybean oil, why did palm rally?",                      # leading 'Given ,'
    "With the read-across to soybean oil, why did palm rally?",                             # leading 'With ,'
    "Amid the spillover to soybean oil, why did palm rally?",                               # leading 'Amid ,'
    "Because of the impact on soybean oil, why did palm rally?",                            # leading 'Because ,'
    # --- round-3 finding (verify-wave recheck): TRAILING subordinate/context clauses. The leading strip only
    # fires on a LEADING frame and the comma split only on coordinating conjunctions, so a context clause
    # TRAILING the ask ("why did palm rally GIVEN ..."), or comma-joined by a subordinator (", with/given/
    # despite/amid ..."), still reached the matcher. _XC_TRAIL_CONTEXT now cuts it (fail-closed: over-cutting
    # merely declines). ---
    "Why did palm rally given the read-across to soybean oil?",                             # bare trailing 'given'
    "Why did palm rally, with the read-across to soybean oil?",                             # comma + 'with the'
    "Why did palm move, despite the bearish impact on soybean oil?",                        # comma + 'despite'
    "Why did palm rally, given the spillover to soybean oil?",                              # comma + 'given'
    "Palm rallied because of the read-across to soybean oil, why?",                         # mid-clause 'because'
    "Why did palm rally amid the spillover to soybean oil?",                                # bare trailing 'amid'
])
def test_detector_context_clause_second_commodity_not_captured(q):
    assert it.is_cross_commodity_explicit(q) == (False, None)


@pytest.mark.parametrize("q,span", [
    # GUARD (round-3): the trailing-context cut must NOT eat legitimate asks. A trailing subordinate clause
    # AFTER the captured object is dropped harmlessly (the capture already terminated at _XC_TERM); 'with' is
    # cut only when followed by a determiner, so the substitut-entry preposition survives.
    ("what does that do to palm given the soyoil glut?", "palm"),
    ("what's the impact on soybean oil, given the palm ban?", "soybean oil"),
    ("how does that affect soybean oil while palm is banned?", "soybean oil"),
    ("could we substitute with palm oil?", "palm oil"),
])
def test_detector_trailing_context_cut_preserves_legit_asks(q, span):
    assert it.is_cross_commodity_explicit(q) == (True, span)


@pytest.mark.parametrize("q,span", [
    # GUARD (round-2): the weak-boundary fence must NOT over-split legitimate RV asks whose second leg sits
    # before a comma. "relative to <X>" is a first-class comparison anchor (NOT a subordinator frame); the
    # "vs / or" relative-value shapes carry a comma the fence must leave intact ("or" is excluded from the
    # split conjunctions; a bare comma before a non-conjunction never splits).
    ("relative to palm, is soyoil tighter?", "palm"),
    ("soyoil vs palm, which tightens?", "palm"),
    ("which tightens more, soyoil or palm?", "palm"),
])
def test_detector_weak_boundary_fence_preserves_legit_rv_asks(q, span):
    assert it.is_cross_commodity_explicit(q) == (True, span)


def test_gate_context_only_comma_conjunction_clause_declines_end_to_end():
    # round-2 finding, end-to-end: a declarative 'impact on soybean oil' context clause joined by ', so' must
    # produce NO xc_request even with faithful stubs (palm routes as focus, soyoil resolves as the resolver
    # would, flagship pair realizable).
    out = _gate("Palm rallied despite the bearish impact on soybean oil, so why did palm move?",
                graph=_graph(PALM, SOY),
                detect=it.is_cross_commodity_explicit,
                route=[PALM], resolve=lambda s: SOY,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out is None


def test_gate_leading_subordinator_frame_clause_declines_end_to_end():
    # round-2 finding, end-to-end: a leading "Given ... , <ask>" frame that names soyoil only as context.
    out = _gate("Given the obvious spillover to soybean oil, why did palm rally?",
                graph=_graph(PALM, SOY),
                detect=it.is_cross_commodity_explicit,
                route=[PALM], resolve=lambda s: SOY,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out is None


def test_gate_context_only_impact_clause_declines_end_to_end():
    # end-to-end through the REAL detector + gate with faithful stubs (palm routes first as the focus, soyoil
    # resolves exactly as the resolver would, flagship pair realizable): the declarative 'impact on soybean
    # oil' context clause must produce NO xc_request.
    out = _gate("Palm surged even though the USDA flagged a bigger impact on soybean oil. Why did palm rally?",
                graph=_graph(PALM, SOY),
                detect=it.is_cross_commodity_explicit,
                route=[PALM], resolve=lambda s: SOY,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out is None


def test_detector_context_commodity_is_never_the_captured_object():
    # C8: a background commodity present only as CONTEXT must not become the target -- the grammatical
    # object of "impact on" is palm (the SOURCE), soyoil is only context.
    matched, target = it.is_cross_commodity_explicit(
        "Palm's export ban -- with soyoil already in surplus -- what's the impact on palm?")
    assert matched is True and target == "palm"                  # NOT soyoil


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# RV-W1.3 -- the gate producer (_xc_request): positive asks
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_gate_named_ask_fires_the_pair():
    out = _gate("palm ban -- what does that do to soyoil?",
                graph=_graph(PALM, SOY),
                detect=lambda q: (True, "soyoil"),
                route=[PALM],
                resolve=lambda s: SOY,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out == {"pair_id": "soyoil_palm_vegoil", "source_slug": PALM, "target_slug": SOY}


def test_gate_pair_key_is_order_insensitive():
    # authored (SOY, PALM); this turn's SOURCE=PALM, TARGET=SOY -> the same curated row must resolve.
    out = _gate("what does that do to soyoil?",
                graph=_graph(PALM, SOY),
                detect=lambda q: (True, "soyoil"),
                route=[PALM], resolve=lambda s: SOY,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out is not None and out["pair_id"] == "soyoil_palm_vegoil"


def test_gate_clicked_chip_phrasing_fires():
    # a clicked suggester chip re-enters as an ordinary query and must re-pass the LAW (C15).
    out = _gate("How does soybean oil's balance sheet compare relative to palm?",
                graph=_graph(PALM, SOY),
                detect=it.is_cross_commodity_explicit,       # exercise the REAL detector on chip prose
                route=[SOY], resolve=lambda s: PALM,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out == {"pair_id": "soyoil_palm_vegoil", "source_slug": SOY, "target_slug": PALM}


def test_gate_source_falls_back_to_carried_state():
    # no lexical route hit this turn -> SOURCE = the carried session contract (coreference).
    out = _gate("what does that do to soyoil?",
                graph=_graph(PALM, SOY),
                state=types.SimpleNamespace(contracts=[PALM]),
                detect=lambda q: (True, "soyoil"),
                route=[], resolve=lambda s: SOY,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out is not None and out["source_slug"] == PALM


def test_gate_open_target_picks_single_most_material_by_id():
    # D7 open-target, PAIR_CAP=1: the first realizable curated pair for SOURCE in pair-id lexical order.
    out = _gate("what else does this affect?",
                graph=_graph(PALM, SOY, RAPE),
                detect=lambda q: (True, None),
                route=[PALM], resolve=lambda s: None,
                pairs=[_Pair("z_palm_rape", PALM, RAPE), _Pair("a_palm_soy", PALM, SOY)])
    assert out == {"pair_id": "a_palm_soy", "source_slug": PALM, "target_slug": SOY}


def test_gate_open_target_skips_unrealizable_pairs():
    out = _gate("any knock-on effects?",
                graph=_graph(PALM, SOY, RAPE),
                detect=lambda q: (True, None),
                route=[PALM], resolve=lambda s: None,
                pairs=[_Pair("a_palm_soy", PALM, SOY), _Pair("b_palm_rape", PALM, RAPE)],
                realizable=lambda pid: pid == "b_palm_rape")     # 'a' not realizable -> pick 'b'
    assert out is not None and out["pair_id"] == "b_palm_rape"


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# D17 (W0.a) -- target-aware SOURCE binding: a NAMED-target ask resolves the target FIRST, then binds
# SOURCE to the first route hit forming a curated material pair with it. Under the old route[0] binding
# every self-contained two-commodity ask declined (S2-1): the first hit was an exchange sibling in no
# curated pair, or the target itself.
# ════════════════════════════════════════════════════════════════════════════════════════════════════
SOYDCE = "soybean_oil_dce"        # exchange sibling: routes FIRST on soyoil queries, in NO curated pair


def _resolve_vegoil(s):
    """A faithful vegoil bare-name resolver (what complex_map's curated table returns for these spans)."""
    t = s.strip().lower()
    if "palm" in t:
        return PALM
    if "soy" in t:
        return SOY
    return None


@pytest.mark.parametrize("q,route,src,tgt", [
    # the four S2-1 repro phrasings, REAL detector: each declined under route[0] binding (sibling-first
    # route, or the target routing first -> C8); D17 binds the pair-forming hit and the fork fires.
    ("Palm export ban -- what does that do to soybean oil's world stocks-to-use versus palm's?",
     [SOYDCE, SOY, PALM], SOY, PALM),
    ("how does soybean oil's balance sheet compare versus palm's?",
     [SOYDCE, SOY, PALM], SOY, PALM),
    ("palm ban -- what does that do to soyoil?",
     [SOY, PALM], PALM, SOY),                        # target routes FIRST: old code C8-declined here
    ("How does soybean oil's balance sheet compare relative to palm?",
     [SOYDCE, SOY], SOY, PALM),
])
def test_gate_d17_self_contained_two_commodity_asks_fire(q, route, src, tgt):
    out = _gate(q, graph=_graph(PALM, SOY, SOYDCE),
                detect=it.is_cross_commodity_explicit,
                route=route, resolve=_resolve_vegoil,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out == {"pair_id": "soyoil_palm_vegoil", "source_slug": src, "target_slug": tgt}


def test_gate_d17_exchange_sibling_route_first_binds_curated_leg():
    # route yields the DCE sibling first; only the CBOT leg is in the curated pair -> SOURCE binds the
    # CBOT leg (the allowlist itself is the binding criterion), never the sibling.
    out = _gate("what does that do to palm?",
                graph=_graph(PALM, SOY, SOYDCE),
                detect=lambda q: (True, "palm"),
                route=[SOYDCE, SOY], resolve=_resolve_vegoil,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out == {"pair_id": "soyoil_palm_vegoil", "source_slug": SOY, "target_slug": PALM}


def test_gate_d17_route_hits_but_none_pair_forming_declines():
    # hits exist but NONE forms a curated pair with the target -> explicit fail-closed decline; the old
    # arbitrary route[0] SOURCE is never minted.
    out = _gate("what does that do to palm?",
                graph=_graph(PALM, CORN, SOYDCE),
                detect=lambda q: (True, "palm"),
                route=[SOYDCE, CORN], resolve=_resolve_vegoil,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out is None


def test_gate_d17_all_route_hits_are_target_c8_declines():
    # every hit IS the resolved target -> no SOURCE candidate -> C8 decline.
    out = _gate("what does that do to palm?",
                graph=_graph(PALM, SOY),
                detect=lambda q: (True, "palm"),
                route=[PALM, PALM], resolve=_resolve_vegoil,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out is None


def test_gate_d17_open_target_source_binding_unchanged_route_first():
    # OPEN asks are untouched by D17: SOURCE stays the route FIRST hit even when a later hit would have
    # curated pairs -- the sibling binds, has none, and the gate declines (D7 semantics preserved).
    out = _gate("what else does this affect?",
                graph=_graph(PALM, SOY, SOYDCE),
                detect=lambda q: (True, None),
                route=[SOYDCE, SOY], resolve=_resolve_vegoil,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out is None


def test_gate_d17_empty_route_state_fallback_uncurated_still_declines():
    # empty route -> carried session contract EXACTLY as before, then the normal gates run: a state
    # SOURCE in no curated pair with the target still declines at gate 3.
    out = _gate("what does that do to soyoil?",
                graph=_graph(CORN, SOY),
                state=types.SimpleNamespace(contracts=[CORN]),
                detect=lambda q: (True, "soyoil"),
                route=[], resolve=_resolve_vegoil,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out is None


def test_gate_d17_empty_route_state_fallback_equal_target_c8_declines():
    # a state-carried SOURCE equal to the resolved target still C8-declines (the check D17 preserved).
    out = _gate("what does that do to soyoil?",
                graph=_graph(PALM, SOY),
                state=types.SimpleNamespace(contracts=[SOY]),
                detect=lambda q: (True, "soyoil"),
                route=[], resolve=_resolve_vegoil,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out is None


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# RV-W1.4 -- the D-cases (hard negatives): a context/pronoun/same-commodity turn NEVER produces xc_request
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_dcase_same_commodity_object_declines():
    # "impact on palm" with palm = SOURCE: resolve(<X>) == SOURCE -> decline (C8), even though soyoil is
    # lexically present as context.
    out = _gate("with soyoil in surplus, what's the impact on palm?",
                graph=_graph(PALM, SOY),
                detect=it.is_cross_commodity_explicit,
                route=[PALM], resolve=lambda s: PALM if s.strip() == "palm" else SOY,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out is None


def test_dcase_pronoun_only_followup_declines():
    # a pronoun-only follow-up is not an explicit cross-commodity ask -> detector False -> no request.
    out = _gate("and what happens next?",
                graph=_graph(PALM, SOY),
                detect=it.is_cross_commodity_explicit,
                route=[PALM], resolve=lambda s: SOY,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out is None


def test_dcase_single_commodity_question_declines():
    out = _gate("why did palm rally after the ban?",
                graph=_graph(PALM, SOY),
                detect=it.is_cross_commodity_explicit,
                route=[PALM], resolve=lambda s: SOY,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out is None


def test_dcase_context_only_second_commodity_never_promoted():
    # cross_links surfacing palm->soyoil in the walk is irrelevant: the gate only sees the query, and the
    # query names no effect-on-soyoil. Same-commodity object -> decline.
    out = _gate("palm export ban given the soyoil glut -- what happens to palm?",
                graph=_graph(PALM, SOY),
                detect=it.is_cross_commodity_explicit,
                route=[PALM], resolve=lambda s: SOY,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out is None


def test_gate_uncurated_pair_declines():
    out = _gate("what does that do to corn?",
                graph=_graph(PALM, CORN),
                detect=lambda q: (True, "corn"),
                route=[PALM], resolve=lambda s: CORN,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])   # no (palm, corn) pair
    assert out is None


def test_gate_non_material_pair_declines():
    out = _gate("what does that do to soyoil?",
                graph=_graph(PALM, SOY),
                detect=lambda q: (True, "soyoil"),
                route=[PALM], resolve=lambda s: SOY,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM, tier="excluded")])
    assert out is None


@pytest.mark.parametrize("verdict", [False, None, "maybe", 1])
def test_gate_non_realizable_pair_declines_fail_closed(verdict):
    # gate 3: only an explicit True from pair_realizable fires; every other verdict (False/None/UNKNOWN)
    # fails closed.
    out = _gate("what does that do to soyoil?",
                graph=_graph(PALM, SOY),
                detect=lambda q: (True, "soyoil"),
                route=[PALM], resolve=lambda s: SOY,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)],
                realizable=lambda pid: verdict)
    assert out is None


def test_gate_target_not_a_loaded_contract_declines():
    out = _gate("what does that do to sunflower oil?",
                graph=_graph(PALM, SOY),                          # sunoil not loaded
                detect=lambda q: (True, "sunflower oil"),
                route=[PALM], resolve=lambda s: "sunflower_oil_x",
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out is None


def test_gate_target_resolves_to_source_declines():
    out = _gate("what does that do to palm?",
                graph=_graph(PALM, SOY),
                detect=lambda q: (True, "palm"),
                route=[PALM], resolve=lambda s: PALM,             # target == source
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out is None


def test_gate_no_source_declines():
    out = _gate("what does that do to soyoil?",
                graph=_graph(PALM, SOY),
                detect=lambda q: (True, "soyoil"),
                route=[], resolve=lambda s: SOY,                  # no lexical hit, no carried state
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out is None


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# C12 -- fail-closed: a raising dependency disables v2 this turn, never propagates
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _boom(*a, **k):
    raise RuntimeError("detector blew up")


def test_gate_raising_detector_fails_closed():
    out = _gate("what does that do to soyoil?",
                graph=_graph(PALM, SOY),
                detect=_boom, route=[PALM], resolve=lambda s: SOY,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out is None


def test_gate_raising_resolver_fails_closed():
    out = _gate("what does that do to soyoil?",
                graph=_graph(PALM, SOY),
                detect=lambda q: (True, "soyoil"), route=[PALM], resolve=_boom,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out is None


def test_gate_raising_load_map_fails_closed():
    def _raise_map():
        raise RuntimeError("cold-cache glob failed")
    out = orch._xc_request("what does that do to soyoil?", graph=_graph(PALM, SOY), state=None,
                           detect=lambda q: (True, "soyoil"), route=lambda q, g: [PALM],
                           resolve_bare=lambda s: SOY, load_map=_raise_map, realizable=lambda pid: True)
    assert out is None


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# RV-W1.2 -- threading: xc_request rides into the cascade quantify seam, omitted (byte-identical) when None
# ════════════════════════════════════════════════════════════════════════════════════════════════════
class _Recorder:
    """Stand-in for an.answer that records the kwargs it was handed."""
    def __init__(self):
        self.kwargs = None

    def __call__(self, query, **kw):
        self.kwargs = kw
        return {"answer": "stub", "structured": None, "evidence": [], "citations": []}


def test_run_reasoning_threads_xc_request(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(orch.an, "answer", rec)
    req = {"pair_id": "soyoil_palm_vegoil", "source_slug": PALM, "target_slug": SOY}
    orch.run_reasoning("q", "2026-06-01", graph=_graph(PALM, SOY), xc_request=req)
    assert rec.kwargs["xc_request"] == req


def test_run_reasoning_omits_kwarg_when_none(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(orch.an, "answer", rec)
    orch.run_reasoning("q", "2026-06-01", graph=_graph(PALM, SOY), xc_request=None)
    assert "xc_request" not in rec.kwargs             # byte-identical: the kwarg is not passed at all


def test_run_hybrid_threads_xc_request(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(orch.an, "answer", rec)
    monkeypatch.setattr(orch.na, "answer_numbers", lambda *a, **k: {"calls": []})
    req = {"pair_id": "soyoil_palm_vegoil", "source_slug": PALM, "target_slug": SOY}
    orch.run_hybrid("q", "2026-06-01", graph=_graph(PALM, SOY), xc_request=req)
    assert rec.kwargs["xc_request"] == req


def test_run_hybrid_omits_kwarg_when_none(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(orch.an, "answer", rec)
    monkeypatch.setattr(orch.na, "answer_numbers", lambda *a, **k: {"calls": []})
    orch.run_hybrid("q", "2026-06-01", graph=_graph(PALM, SOY), xc_request=None)
    assert "xc_request" not in rec.kwargs


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# D3 -- the flag: OFF => xc_request None => the quantify seam is byte-identical; ON => the gate may fire
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _force(kind):
    return lambda q, call=None: {"intent": kind, "needs_numbers": kind in ("numbers_only", "hybrid"),
                                 "needs_reasoning": kind in ("reasoning", "hybrid")}


def _respond_graph():
    from leviathan.causal import schema as cs
    from leviathan.graphrag import graph as g
    palm = cs.CausalContract(contract=PALM, aliases=["palm", "palm oil"],
                             drivers=[cs.Driver(id="export_ban", type="policy", sign="+", mechanism="ban")])
    soy = cs.CausalContract(contract=SOY, aliases=["soyoil", "soybean oil"],
                            drivers=[cs.Driver(id="crush", type="demand", sign="+", mechanism="crush")])
    return g.CausalGraph({PALM: palm, SOY: soy}, silver=set())


def test_respond_flag_off_omits_xc_request(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(orch.an, "answer", rec)
    monkeypatch.delenv("GRAPHRAG_REROUTE_V2", raising=False)      # default off
    out = orch.respond("what does that do to soyoil?", graph=_respond_graph(), asof="2026-06-01",
                       classify=_force("reasoning"))
    assert out["intent"] == "reasoning"
    assert "xc_request" not in rec.kwargs                         # BYTE-IDENTICAL: the seam is untouched


def test_respond_flag_on_but_gate_declines_omits_xc_request(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(orch.an, "answer", rec)
    monkeypatch.setenv("GRAPHRAG_REROUTE_V2", "on")
    # a single-commodity question: the real gate declines (no complex_map import reached), xc_request None.
    orch.respond("why did palm rally?", graph=_respond_graph(), asof="2026-06-01",
                 classify=_force("reasoning"))
    assert "xc_request" not in rec.kwargs


def test_respond_flag_on_and_gate_fires_threads_request(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(orch.an, "answer", rec)
    monkeypatch.setenv("GRAPHRAG_REROUTE_V2", "on")
    req = {"pair_id": "soyoil_palm_vegoil", "source_slug": PALM, "target_slug": SOY}
    monkeypatch.setattr(orch, "_xc_request", lambda *a, **k: req)  # decouple from lanes A/D
    orch.respond("what does that do to soyoil?", graph=_respond_graph(), asof="2026-06-01",
                 classify=_force("reasoning"))
    assert rec.kwargs["xc_request"] == req


def test_respond_numbers_branch_never_computes_xc_request(monkeypatch):
    # the gate runs ONLY on reasoning/hybrid; a numbers_only turn must never even call the producer.
    called = {"n": 0}
    monkeypatch.setenv("GRAPHRAG_REROUTE_V2", "on")
    monkeypatch.setattr(orch, "_xc_request", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    monkeypatch.setattr(orch, "run_numbers_only", lambda *a, **k: {"answer": "n", "number_calls": [],
                                                                   "intent": "numbers_only", "contract": None,
                                                                   "contracts": [], "structured": None,
                                                                   "evidence": [], "citations": []})
    orch.respond("what were palm exports?", graph=_respond_graph(), asof="2026-06-01",
                 classify=_force("numbers_only"))
    assert called["n"] == 0


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# RV2 W2 -- the LLM detection tier: kill-switch, the shared two-tier composite, tier telemetry,
# dark observables. The existing respond() pins inject `classify` (dispatch skipped, plan None), so
# ordering/recall behavior is pinned on the MODULE SYMBOL directly (S2-6), plus ONE call-injected
# respond() integration test exercising the flag-on plan-span path end-to-end.
# ════════════════════════════════════════════════════════════════════════════════════════════════════
_XC_MISS_Q = "how does a palm export ban affect soybean oil?"     # the S2-1 recall shape the regex misses


def _mkplan(target="palm", explicit=True, degraded=False):
    return dp.Plan(steps=["reasoning"], contracts=[], xc_explicit=explicit, xc_target=target,
                   degraded=degraded)


@pytest.mark.parametrize("val,want", [
    ("on", True), ("ON", True), ("1", True), ("true", True), ("TRUE", True), (" on ", True),
    ("off", False), ("0", False), ("yes", False), ("enabled", False), ("garbage", False), ("", False),
])
def test_xc_llm_detect_flag_fail_closed(monkeypatch, val, want):
    monkeypatch.setenv("GRAPHRAG_XC_LLM_DETECT", val)
    assert orch._xc_llm_detect_on() is want


def test_xc_llm_detect_flag_default_off(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_XC_LLM_DETECT", raising=False)
    assert orch._xc_llm_detect_on() is False


def test_composite_regex_hit_wins_and_plan_span_ignored(monkeypatch):
    # D2 ordering: any floor hit returns immediately -- the plan span is NEVER read on a regex hit.
    monkeypatch.setenv("GRAPHRAG_XC_LLM_DETECT", "on")
    det = orch.xc_detect_two_tier(_mkplan(target="palm"))
    assert det("palm ban -- what does that do to soyoil?") == (True, "soyoil")   # regex span, NOT "palm"
    assert det.tier == "regex" and det.llm_consulted is False    # LLM never consulted on a floor hit


def test_composite_gate_regex_span_beats_c8_declining_plan_span(monkeypatch):
    # the plan span ("palm") would resolve to SOURCE and C8-decline the whole ask; the regex span
    # ("soyoil") fires it. Ordering is load-bearing, so it is pinned END-TO-END through the gate.
    monkeypatch.setenv("GRAPHRAG_XC_LLM_DETECT", "on")
    det = orch.xc_detect_two_tier(_mkplan(target="palm"))
    out = _gate("palm ban -- what does that do to soyoil?", graph=_graph(PALM, SOY),
                detect=det, route=[PALM], resolve=_resolve_vegoil,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out == {"pair_id": "soyoil_palm_vegoil", "source_slug": PALM, "target_slug": SOY,
                   "detect_tier": "regex"}


def test_composite_recall_add_named_span(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_XC_LLM_DETECT", "on")
    det = orch.xc_detect_two_tier(_mkplan(target="soybean oil"))
    assert it.is_cross_commodity_explicit(_XC_MISS_Q) == (False, None)   # honest premise: a REAL tier-1 miss
    assert det(_XC_MISS_Q) == (True, "soybean oil")
    assert det.tier == "llm" and det.llm_consulted is True


def test_composite_open_span_not_consumed(monkeypatch):
    # D19: xc_explicit=true with a null target is emitted+traced but NEVER routed (no LLM open lane).
    monkeypatch.setenv("GRAPHRAG_XC_LLM_DETECT", "on")
    det = orch.xc_detect_two_tier(_mkplan(target=None))
    assert det(_XC_MISS_Q) == (False, None)
    assert det.tier == "none" and det.llm_consulted is True      # consulted-and-declined, attributable


def test_composite_plan_none_is_floor_only(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_XC_LLM_DETECT", "on")
    det = orch.xc_detect_two_tier(None)                          # dispatch fallback (D11)
    assert det(_XC_MISS_Q) == (False, None)
    assert det.tier == "none" and det.llm_consulted is False


def test_composite_degraded_plan_not_consumed(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_XC_LLM_DETECT", "on")
    det = orch.xc_detect_two_tier(_mkplan(target="soybean oil", degraded=True))
    assert det(_XC_MISS_Q) == (False, None)                      # D2: never the deck-uncertified model
    assert det.tier == "none" and det.llm_consulted is False


@pytest.mark.parametrize("flagval", [None, "off", "0", "yes", "enabled", "on extra"])
def test_composite_flag_off_or_unrecognized_tier2_unreachable(monkeypatch, flagval):
    if flagval is None:
        monkeypatch.delenv("GRAPHRAG_XC_LLM_DETECT", raising=False)
    else:
        monkeypatch.setenv("GRAPHRAG_XC_LLM_DETECT", flagval)
    det = orch.xc_detect_two_tier(_mkplan(target="soybean oil"))
    assert det(_XC_MISS_Q) == (False, None)
    assert det.tier == "none" and det.llm_consulted is False


def test_gate_llm_tier_span_reaches_the_law(monkeypatch):
    # recall-add through the REAL gate: the plan span binds via resolve_bare + curated-pair LAW exactly
    # like a regex span, and the fired request carries detect_tier="llm" (the 4th, engine-inert key).
    monkeypatch.setenv("GRAPHRAG_XC_LLM_DETECT", "on")
    det = orch.xc_detect_two_tier(_mkplan(target="soybean oil"))
    out = _gate(_XC_MISS_Q, graph=_graph(PALM, SOY),
                detect=det, route=[PALM], resolve=_resolve_vegoil,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert out == {"pair_id": "soyoil_palm_vegoil", "source_slug": PALM, "target_slug": SOY,
                   "detect_tier": "llm"}


def test_gate_injected_detector_request_stays_three_key():
    # a plain injected detector has no tier attribute -> no detect_tier key: every legacy seam and the
    # engine's 3-key contract are byte-identical (the existing exact-equality pins above stay honest).
    out = _gate("what does that do to soyoil?", graph=_graph(PALM, SOY),
                detect=lambda q: (True, "soyoil"), route=[PALM], resolve=lambda s: SOY,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)])
    assert set(out) == {"pair_id", "source_slug", "target_slug"}


# ── D7 tier telemetry at the respond() level (stamped for reasoning/hybrid turns incl. DECLINED ones) ──
def test_respond_stamps_xc_detect_regex_tier_even_with_v2_off(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(orch.an, "answer", rec)
    monkeypatch.delenv("GRAPHRAG_REROUTE_V2", raising=False)
    monkeypatch.delenv("GRAPHRAG_XC_LLM_DETECT", raising=False)
    out = orch.respond("palm ban -- what does that do to soyoil?", graph=_respond_graph(),
                       asof="2026-06-01", classify=_force("reasoning"))
    assert out["intent_decision"]["xc_detect"] == {"tier": "regex", "llm_consulted": False,
                                                   "target_span": "soyoil"}
    assert "xc_request" not in rec.kwargs             # v2 off: the seam stays byte-identical (routing)


def test_respond_stamps_xc_detect_none_tier_on_declined_turn(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(orch.an, "answer", rec)
    monkeypatch.setenv("GRAPHRAG_REROUTE_V2", "on")
    monkeypatch.delenv("GRAPHRAG_XC_LLM_DETECT", raising=False)
    out = orch.respond("why did palm rally?", graph=_respond_graph(), asof="2026-06-01",
                       classify=_force("reasoning"))
    assert out["intent_decision"]["xc_detect"] == {"tier": "none", "llm_consulted": False,
                                                   "target_span": None}
    assert "xc_request" not in rec.kwargs             # gate declined -> no request (unchanged)


def test_respond_flag_on_but_plan_none_tier2_unreachable(monkeypatch):
    # extends the flag pins: injected classify skips dispatch -> plan None -> even with the flag ON the
    # tier-2 branch is unreachable and llm_consulted stays False (fallback distinguishable from flag-off
    # only through the planner key, which is absent here).
    rec = _Recorder()
    monkeypatch.setattr(orch.an, "answer", rec)
    monkeypatch.setenv("GRAPHRAG_REROUTE_V2", "on")
    monkeypatch.setenv("GRAPHRAG_XC_LLM_DETECT", "on")
    out = orch.respond(_XC_MISS_Q, graph=_respond_graph(), asof="2026-06-01",
                       classify=_force("reasoning"))
    assert out["intent_decision"]["xc_detect"] == {"tier": "none", "llm_consulted": False,
                                                   "target_span": None}
    assert "xc_request" not in rec.kwargs


def test_respond_fallback_dispatch_stamps_none_tier(monkeypatch):
    # dispatch RAN and fell back (raising set_plan) -> legacy classifier path; the turn still stamps
    # xc_detect (regex floor attribution) and carries no planner key (the eval AND-guard reads that).
    rec = _Recorder()
    monkeypatch.setattr(orch.an, "answer", rec)
    monkeypatch.setenv("GRAPHRAG_XC_LLM_DETECT", "on")

    def call(system, user, *, model, tool, **kw):
        if tool["name"] == "set_plan":
            raise RuntimeError("dispatch down")
        return {"tldr": "t", "mechanism": "m", "diagram_mermaid": "", "sources": []}
    out = orch.respond("why did palm rally?", graph=_respond_graph(), asof="2026-06-01", call=call)
    assert out["intent"] == "reasoning"
    assert "planner" not in out["intent_decision"]
    assert out["intent_decision"]["xc_detect"] == {"tier": "none", "llm_consulted": False,
                                                   "target_span": None}


def test_respond_numbers_turn_has_no_xc_detect(monkeypatch):
    monkeypatch.setattr(orch, "run_numbers_only", lambda *a, **k: {
        "answer": "n", "number_calls": [], "intent": "numbers_only", "contract": None,
        "contracts": [], "structured": None, "evidence": [], "citations": []})
    out = orch.respond("what were palm exports?", graph=_respond_graph(), asof="2026-06-01",
                       classify=_force("numbers_only"))
    assert "xc_detect" not in (out.get("intent_decision") or {})   # D7 covers reasoning/hybrid only


# ── the ONE call-injected respond() integration test (S2-6): dual-duty fake call, flag-on plan span ──
def test_respond_llm_tier_end_to_end_dual_duty_call(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_REROUTE_V2", "on")
    monkeypatch.setenv("GRAPHRAG_XC_LLM_DETECT", "on")
    from leviathan.graphrag import evidence as ev
    monkeypatch.setattr(ev, "embed", lambda texts, **kw: [[1.0, 0.0, 0.0, 0.0] for _ in texts])

    def call(system, user, *, model, tool, **kw):                  # answers set_plan AND the synthesis tool
        if tool["name"] == "set_plan":
            return {"steps": ["reasoning"], "contracts": [PALM],
                    "xc_explicit": True, "xc_target": "soybean oil"}
        return {"tldr": "t", "mechanism": "m", "diagram_mermaid": "", "sources": []}

    def retrieve(q, node, *, k, asof=None, near=None):
        return [{"date": "2024-01-01", "source": "usda_wasde", "source_key": f"s3://{node}",
                 "text": "note"}]

    seen = {}
    real = orch._xc_request

    def spy(q, **kw):                                              # REAL gate, hermetic lane-A/D stubs
        seen["req"] = real(q, **kw, resolve_bare=_resolve_vegoil,
                           load_map=lambda: _Map([_Pair("soyoil_palm_vegoil", SOY, PALM)]),
                           realizable=lambda pid: True)
        return seen["req"]
    monkeypatch.setattr(orch, "_xc_request", spy)

    out = orch.respond(_XC_MISS_Q, graph=_respond_graph(), asof="2026-06-01",
                       call=call, retrieve=retrieve)
    assert out["intent"] == "reasoning"
    # the regex misses this shape; the request exists ONLY because the plan span was consumed (tier 2)
    assert seen["req"] == {"pair_id": "soyoil_palm_vegoil", "source_slug": PALM, "target_slug": SOY,
                           "detect_tier": "llm"}
    assert out["intent_decision"]["xc_detect"] == {"tier": "llm", "llm_consulted": True,
                                                   "target_span": "soybean oil"}
    assert out["intent_decision"]["xc_explicit"] is True           # the W1 dark channel still rides trace()


# ── R3/D10 attachment-ordering pin: the planner (and thus detection input) runs BEFORE the concat ──
def test_plan_computed_before_attachment_concat(monkeypatch):
    seen = {}

    def call(system, user, *, model, tool, **kw):
        if tool["name"] == "set_plan":
            seen["planner_user"] = user
            return {"steps": ["reasoning"], "contracts": [PALM]}
        return {"tldr": "t", "mechanism": "m", "diagram_mermaid": "", "sources": []}
    rec = _Recorder()
    monkeypatch.setattr(orch.an, "answer", rec)
    out = orch.respond("what is driving palm?", graph=_respond_graph(), asof="2026-06-01", call=call,
                       context=[{"type": "node", "contract": PALM, "driver_id": "export_ban"}])
    assert "USER-ATTACHED FOCUS" not in seen["planner_user"]       # attachments can't shape xc fields
    assert "USER-ATTACHED FOCUS" in rec.kwargs["extra_context"]    # ...but the turn still carried them
    assert out["intent_decision"]["attachments"]["focus_driver"] == "export_ban"


# ── detect_tier rides into the FIRED trace via cascade._run_xc (stamped AFTER the call, S2-2) ──
def test_run_xc_stamps_detect_tier_on_fired_trace(monkeypatch):
    from leviathan.graphrag.numbers import cascade as casc
    calls = []
    monkeypatch.setattr(casc, "_load_pair_row", lambda pid: object())
    monkeypatch.setattr(casc, "_xc_focus_windows", lambda *a: ["w"])
    monkeypatch.setattr(casc, "_reroute_xc",
                        lambda pair_row, source, target, *a: (
                            calls.append((source, target))
                            or (["line"], {"pair_id": "p", "reroute_v2": True})))
    req = {"pair_id": "p", "source_slug": PALM, "target_slug": SOY, "detect_tier": "llm"}
    block, fired = casc._run_xc(req, None, None, [], None, "2026-06-01", None, [])
    assert block == ["line"] and fired["detect_tier"] == "llm"
    # 3-key request (legacy/injected shape): the engine consumes the SAME 3 keys, tier stamps None
    req3 = {"pair_id": "p", "source_slug": PALM, "target_slug": SOY}
    _, fired3 = casc._run_xc(req3, None, None, [], None, "2026-06-01", None, [])
    assert fired3["detect_tier"] is None
    assert calls == [(PALM, SOY), (PALM, SOY)]        # extra-key inertness: identical engine invocation


def test_run_xc_decline_path_unaffected_by_detect_tier(monkeypatch):
    from leviathan.graphrag.numbers import cascade as casc
    monkeypatch.setattr(casc, "_load_pair_row", lambda pid: object())
    monkeypatch.setattr(casc, "_xc_focus_windows", lambda *a: ["w"])
    monkeypatch.setattr(casc, "_reroute_xc", lambda *a: ([], None))
    req = {"pair_id": "p", "source_slug": PALM, "target_slug": SOY, "detect_tier": "regex"}
    assert casc._run_xc(req, None, None, [], None, "2026-06-01", None, []) == ([], None)


# ── W2 dark observables in the respond() EMF block (XcLlmWouldFire / PlannerFallback / dark line) ──
def _capture_emf(monkeypatch) -> dict:
    from leviathan.graphrag import emf
    captured = {}
    monkeypatch.setattr(emf, "emit",
                        lambda metrics, *, dimensions=None, units=None: captured.update(metrics))
    return captured


def test_emf_xc_would_fire_and_dark_line(monkeypatch, capsys):
    monkeypatch.delenv("GRAPHRAG_XC_LLM_DETECT", raising=False)   # emitted REGARDLESS of the flag (D20)
    captured = _capture_emf(monkeypatch)
    canned = {"answer": "a", "intent": "reasoning", "model": "m",
              "intent_decision": {"planner": "llm", "xc_explicit": True, "xc_target": "palm oil"},
              "trace": {"ms_dispatch": 120}, "session": {"id": "s1", "turn": 3}}
    monkeypatch.setattr(orch, "_respond", lambda *a, **k: canned)
    orch.respond("q", graph=None)
    assert captured["XcLlmWouldFire"] == 1 and captured["PlannerFallback"] == 0
    assert "XC_DETECT_DARK turn=s1/3 target=palm oil" in capsys.readouterr().out


def test_emf_no_would_fire_no_dark_line(monkeypatch, capsys):
    captured = _capture_emf(monkeypatch)
    canned = {"answer": "a", "intent": "reasoning", "model": "m",
              "intent_decision": {"planner": "llm", "xc_explicit": False, "xc_target": None},
              "trace": {"ms_dispatch": 120}}
    monkeypatch.setattr(orch, "_respond", lambda *a, **k: canned)
    orch.respond("q", graph=None)
    assert captured["XcLlmWouldFire"] == 0
    assert "XC_DETECT_DARK" not in capsys.readouterr().out


def test_emf_planner_fallback_only_when_dispatch_ran(monkeypatch, capsys):
    captured = _capture_emf(monkeypatch)
    fb = {"answer": "a", "intent": "reasoning", "model": "m",
          "intent_decision": {"intent": "reasoning"}, "trace": {"ms_dispatch": 33}}
    monkeypatch.setattr(orch, "_respond", lambda *a, **k: fb)
    orch.respond("q", graph=None)
    assert captured["PlannerFallback"] == 1 and captured["XcLlmWouldFire"] == 0
    assert "XC_DETECT_DARK" not in capsys.readouterr().out        # a fallback turn emits no plan fields
    # injected-classify / trivial / guardrail turns never stamp ms_dispatch -> never counted as fallback
    nofb = {"answer": "a", "intent": "reasoning", "model": "m",
            "intent_decision": {"intent": "reasoning"}, "trace": {}}
    monkeypatch.setattr(orch, "_respond", lambda *a, **k: nofb)
    orch.respond("q", graph=None)
    assert captured["PlannerFallback"] == 0
