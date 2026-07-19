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
