"""W5 outlook intent — the intent-conditional register and the W5.0 DERIVATION GATE.

The wave's thesis in one line: **the fence gates on DERIVATION, not on vocabulary.** A price level is
legal iff it is computed from a cited surface and rendered with its arithmetic visible; a BARE number is a
refusal. Two things must therefore be true at once, and neither may be trusted to a prompt paragraph:

  1. the relaxation ACTUALLY HAPPENED  -- A1 valuation vocabulary survives an outlook turn;
  2. the relaxation IS SCOPED          -- A2 execution advice, detector C, internal leaks and unbacked
                                          levels are refused on that same turn, and every non-outlook
                                          seam (chips, numbers, news, live, session carry) is untouched.

The adversarial half (`test_adversarial_*`) is the load-bearing part: it tries to elicit execution
language the way a user actually would -- by asking politely, by asking twice, by embedding the ask in a
derivation that IS legal, by using vocabulary the lexicon never listed -- and proves refusal each time.
"""
from __future__ import annotations

import inspect

from leviathan.graphrag import answer as an
from leviathan.graphrag import config_check as cc
from leviathan.graphrag import dispatch as dp
from leviathan.graphrag import intent as it
from leviathan.graphrag import register as reg

# ── D1: the split is behaviour-neutral ────────────────────────────────────────────────────────────────
# The probe corpora the R2/R8 build lint already owns -- reused so the property test cannot drift from
# the detector it is meant to certify.
_PROBES = (cc._DETECTOR_FLAG + cc._DETECTOR_LANE_B + cc._DETECTOR_CLEAN
           + cc._OUTLOOK_A1 + cc._OUTLOOK_A2 + cc._OUTLOOK_C
           + (cc._OUTLOOK_DERIVED, cc._OUTLOOK_BARE))


def test_register_leaks_is_exactly_internal_plus_market():
    """D1's gate: the split is a PURE REFACTOR. register_leaks == internal_leaks + market_leaks as a
    multiset, over every probe corpus in the repo, with the two halves disjoint."""
    for p in _PROBES:
        whole, internal, market = reg.register_leaks(p), reg.internal_leaks(p), reg.market_leaks(p)
        assert sorted(whole) == sorted(internal + market), p
        assert len(whole) == len(internal) + len(market), p


def test_internal_and_market_halves_are_disjoint():
    dirty = ("The soybeans_cbot driver has conf=high and sign=+; the spread looks cheap and is "
             "undervalued. A crowded long is the risk.")
    internal = {t for t, _ in reg.internal_leaks(dirty)}
    market = {t for t, _ in reg.market_leaks(dirty)}
    assert internal and market                                       # both halves actually fired
    assert not (internal & market)                                   # ... and they do not overlap


def test_internal_leaks_are_never_relaxable():
    """The one property no intent, flag or register scope may ever change: a slug / conf= / regime id in
    reader prose is a BUG, not a register question."""
    dirty = "conf=high on soybeans_cbot; sign=+ and the node fired."
    for mr in (reg.FENCED, reg.OUTLOOK):
        assert reg.internal_leaks(reg.sanitize(dirty, market_register=mr)) == [], mr


# ── D2: the scope, and what each register permits ─────────────────────────────────────────────────────
def test_fenced_is_the_default_everywhere():
    """Every relaxable entry point defaults to FENCED -- the relaxation must be asked for BY NAME."""
    for fn in (reg.sanitize, reg._strip_banned_sentences, reg._is_banned_sentence):
        assert inspect.signature(fn).parameters["market_register"].default == reg.FENCED, fn.__name__
    # _humanize_structured is SHARED by the L2 and one-hop bodies -- a non-fenced default would relax the
    # one-hop path for free.
    assert inspect.signature(an._humanize_structured).parameters["market_register"].default == reg.FENCED


def test_a1_valuation_fenced_by_default_permitted_on_outlook():
    for probe in cc._OUTLOOK_A1:
        assert probe not in reg.sanitize(probe + ".", market_register=reg.FENCED), probe
        assert probe in reg.sanitize(probe + " [E1].", market_register=reg.OUTLOOK), probe


def test_flow_and_persistence_permitted_on_outlook_only():
    """B (positioning flow) and D (persistence denial) are the legs a balance-of-risks note actually
    needs -- every one of those sentences is deleted today."""
    for probe in ("one-sided positioning [N1]", "a crowded long is the risk [N2]",
                  "vulnerable to a squeeze [N3]", "a discount this wide rarely persists [N4]"):
        assert probe not in reg.sanitize(probe + ".", market_register=reg.FENCED), probe
        assert probe in reg.sanitize(probe + ".", market_register=reg.OUTLOOK), probe


def test_forward_convergence_stays_fenced_on_outlook():
    """Detector C is NOT part of the W5.0 amendment: 'the premium should narrow' is a spread FORECAST, and
    an outlook leans on regimes, buffers and episodes -- never on convergence."""
    for probe in cc._OUTLOOK_C:
        for mr in (reg.FENCED, reg.OUTLOOK):
            assert probe not in reg.sanitize(probe + ".", market_register=mr), (mr, probe)


def test_mood_words_survive_only_on_outlook():
    assert "bullish" not in reg.sanitize("The balance sheet is bullish [E1].", market_register=reg.FENCED)
    assert "bullish" in reg.sanitize("The balance sheet is bullish [E1].", market_register=reg.OUTLOOK)


def test_sanitize_stays_idempotent_under_both_registers():
    for mr in (reg.FENCED, reg.OUTLOOK):
        once = reg.sanitize(cc._OUTLOOK_DERIVED, market_register=mr)
        assert reg.sanitize(once, market_register=mr) == once, mr


# ── W5.0: the derivation gate ─────────────────────────────────────────────────────────────────────────
def test_derived_level_survives_with_its_arithmetic():
    out = reg.sanitize(cc._OUTLOOK_DERIVED, market_register=reg.OUTLOOK)
    assert reg.outlook_derivation_ok(cc._OUTLOOK_DERIVED)
    for tok in ("227.25", "268", "243", "220"):                      # anchor AND the derived outputs
        assert tok in out, tok
    assert reg.unbacked_level_count(cc._OUTLOOK_DERIVED) == 0


def test_bare_level_is_a_refusal():
    """The single property that makes this a derivation gate rather than a vocabulary ban."""
    assert not reg.outlook_derivation_ok(cc._OUTLOOK_BARE)
    out = reg.sanitize(cc._OUTLOOK_BARE, market_register=reg.OUTLOOK)
    assert "268" not in out and "243" not in out
    assert reg.unbacked_level_count(cc._OUTLOOK_BARE) >= 2


def test_derivation_gate_fails_closed_on_each_missing_component():
    """Drop ONE leg of the derivation at a time; each omission must refuse the level. This is what
    'fail-closed' means operationally -- there is no partial credit."""
    missing_anchor_cite = ("Spot 227.25 EUR/t (Sep-26 settle). Three episodes moved +18% / +7% / -3% "
                           "[E2] -> 268 / 243 / 220; median 243.")
    missing_move_cite = ("Spot 227.25 EUR/t (Sep-26 settle) [N1]. Three episodes moved +18% / +7% / -3% "
                         "-> 268 / 243 / 220; median 243.")
    missing_operator = ("Spot 227.25 EUR/t (Sep-26 settle) [N1]. Three episodes moved +18% / +7% / -3% "
                        "[E2]. Median 243.")
    missing_anchor = "Three episodes moved +18% / +7% / -3% [E2] -> 268 / 243 / 220; median 243."
    for txt in (missing_anchor_cite, missing_move_cite, missing_operator, missing_anchor):
        assert not reg.outlook_derivation_ok(txt), txt
        assert "268" not in reg.sanitize(txt, market_register=reg.OUTLOOK) or "243" not in reg.sanitize(
            txt, market_register=reg.OUTLOOK), txt


def test_derivation_is_scoped_to_the_outlook_section():
    """A derivation shown under '## Outlook' must not silently back a level minted in another section."""
    txt = ("## Mechanism\nCoffee reaches 268 on our read.\n\n"
           "## Outlook\nSpot 227.25 [N1]. Episodes moved +18% [E2] -> 268.")
    assert reg.outlook_unit(txt).strip().startswith("Spot 227.25")
    assert "## Mechanism" not in reg.outlook_unit(txt)


def test_derivation_scope_is_enforced_by_the_strip_and_the_counter_not_only_the_slicer():
    """FOLD-PASS 2026-07-30. The slicing helper was scoped but the VERDICT was applied text-wide: sanitize
    computed `derivation_ok` once and handed it to the whole segment, so ONE complete derivation under
    '## Outlook' disabled the level gate for every other sentence -- the exact laundering outlook_unit's
    docstring says it prevents. Measured before the fix: unbacked_levels(DOC) == [] and '310.5' survived."""
    doc = ("## Mechanism\nOur fair value is 310.5 on the current balance sheet.\n\n"
           "## Outlook\nSpot 227.25 [N1]. Episodes moved +18% / +7% [E2] -> 268 / 243; median 243.")
    assert reg.outlook_derivation_ok(doc)                            # the unit's own derivation IS complete
    out = reg.sanitize(doc, market_register=reg.OUTLOOK)
    assert "310.5" not in out                                        # ... and it backs NOTHING outside itself
    assert "268" in out and "227.25" in out                          # ... while the in-unit levels survive
    assert [t for t, _ in reg.unbacked_levels(doc)] == ["310.5"]     # the COUNTER agrees with the strip


def test_tldr_level_cannot_be_backed_by_a_mechanism_derivation():
    """The pin half of the same defect: `_count_unbacked_levels` ran on tldr+mechanism CONCATENATED, so a
    minted level in the tl;dr was backed by a derivation living three sections away and
    `price_target_backed` passed on a fabricated number."""
    st = {"tldr": "The balance of risks leans higher. Our objective is 268.",
          "mechanism": ("## Outlook\nSpot 227.25 EUR/t (Sep-26 settle) [N1]. Three episodes moved "
                        "+18% / +7% / -3% [E2] -> 268 / 243 / 220; median 243.")}
    assert an._count_unbacked_levels(st) >= 1                        # -> price_target_backed REDS
    # ... and the mechanism on its own is fully backed, so the pin is pointing at the tl;dr, not the unit
    assert reg.unbacked_level_count(st["mechanism"]) == 0


# ── the 4-digit blind spot: the majority of this platform's quote conventions ─────────────────────────
# Every level in the shipped probes and in the plan's worked example (227.25 -> 268/243/220) is 3-digit or
# decimal. The old token regex capped the integer run at THREE digits and could only extend it through a
# comma, so `_level_tokens('target 1450 here')` was [] and `sanitize` served the number verbatim.
_LEVEL_TABLE = (
    ("soybeans_cbot", "Soybeans should reach 1450 by January.", "1450"),
    ("rough_rice_cbot", "Rough rice works back to 1,850 on the export ban.", "1,850"),
    ("cocoa", "Cocoa prints 8500 on any further Ivorian shortfall.", "8500"),
    ("malaysian_crude_palm_oil", "MCPO settles at 4250 once stocks draw.", "4250"),
    ("palm_olein_dce", "Palm olein trades up to 7200 into the seasonal low.", "7200"),
    ("arabica_coffee", "Coffee holds 227.25 through the harvest.", "227.25"),
    ("arabica_coffee_4d", "Coffee holds 1015.5 through the harvest.", "1015.5"),
    ("wheat_big", "Wheat could see 12000 in a full closure.", "12000"),
)


def test_level_gate_sees_four_digit_levels_per_contract_quote_convention():
    for slug, sent, level in _LEVEL_TABLE:
        assert level in reg._level_tokens(sent), (slug, sent)
        assert reg.unbacked_level_count(sent) >= 1, (slug, sent)
        assert level not in reg.sanitize(sent, market_register=reg.OUTLOOK), (slug, sent)


def test_four_digit_years_are_still_years_when_the_sentence_frames_them():
    """The other half: widening the token must not turn every calendar year into a price level. A bare
    4-digit integer is a year only when it is 1900-2035 AND temporally framed."""
    for sent in ("the 2010 export ban, revisited in 2022", "prices rallied through 2011",
                 "since 2018 the record is thinner", "2022 saw prices double",
                 "the 1994 frost is the only comparable"):
        assert reg._level_tokens(sent) == [], sent
    # ... and an unframed number in the same numeric band is a LEVEL, not a year
    assert reg._level_tokens("cocoa at 2025 on the Ivorian shortfall") == ["2025"]


def test_documented_consequence_uncited_numbers_go_on_an_incomplete_outlook_turn():
    """DOCUMENTING A REAL TRADE-OFF, not asserting an ideal. On an OUTLOOK turn whose derivation is
    incomplete, the gate strips EVERY sentence carrying an uncited 2+-digit number -- not only price
    levels. A quantity like 'cut yields by 25 bushels' goes too if it carries no handle.

    That is the fail-CLOSED reading the user's decision asks for ('a bare number is a refusal'), and it is
    consistent with the standing HANDLE DISCIPLINE the mentor prompt already imposes (every observed figure
    carries its [N] handle). It costs something real: on an outlook turn, honest-but-uncited prose numbers
    disappear. Two things bound the cost -- it fires ONLY on turns where the user explicitly asked for a
    price view, and it stops entirely once the derivation is complete. If the desk decides the cost is too
    high, the narrowing is one line: scope the strip to register.outlook_unit(text) instead of the whole
    text, and let the `price_target_backed` PIN keep whole-answer coverage. That is a policy call, so it is
    pinned here rather than silently chosen."""
    txt = "The 2012 drought cut yields by 25 bushels. Stocks fell to 44.8 MMT [N1]."
    assert txt in reg.sanitize(txt, market_register=reg.FENCED)       # unchanged on every normal turn
    out = reg.sanitize(txt, market_register=reg.OUTLOOK)
    assert "25 bushels" not in out                                    # uncited -> refused
    assert "44.8 MMT [N1]" in out                                     # cited -> kept
    # ... and the whole thing survives once the derivation IS complete
    full = "Spot 227.25 [N1]. Episodes moved +18% [E2] -> 268. " + txt
    assert "25 bushels" in reg.sanitize(full, market_register=reg.OUTLOOK)


def test_cited_numbers_are_never_level_stripped():
    """A number carrying its handle traces to a row -- it is backed by definition, on any register."""
    txt = "Ending stocks were 44.79 MMT on 2024-01-10 [N1]. Exports ran 12.549 MMT [N2]."
    for mr in (reg.FENCED, reg.OUTLOOK):
        out = reg.sanitize(txt, market_register=mr)
        assert "44.79" in out and "12.549" in out, mr


def test_level_detector_ignores_years_dates_percentages_and_counts():
    """The gate must not fire on numeric NOISE, or it would strip honest prose on every outlook turn."""
    assert reg._level_tokens("the 2010 export ban, revisited in 2022") == []
    assert reg._level_tokens("published 2024-01-10 for the 2023/24 marketing year") == []
    assert reg._level_tokens("stocks-to-use fell 5.2% to the 8th percentile") == []
    assert reg._level_tokens("three comparable episodes in Q3") == []
    assert reg._level_tokens("spot 227.25 and a 268 target") == ["227.25", "268"]


# ── the A2 fence: expressed as CODE, and unconditional ────────────────────────────────────────────────
def test_a2_execution_idioms_refused_under_every_register():
    for probe in cc._OUTLOOK_A2:
        assert reg.exec_leaks(probe), probe
        for mr in (reg.FENCED, reg.OUTLOOK):
            body = probe + ". Ending stocks fell to 44.8 MMT [N1]."
            out = reg.sanitize(body, market_register=mr)
            assert probe not in out, (mr, probe)
            assert "44.8 MMT [N1]" in out, (mr, probe)               # ... and ONLY the offending sentence goes


def test_exec_leaks_survives_nothing_the_sanitizer_emits():
    """The stated invariant: exec_leaks(sanitize(x, ANY)) == []."""
    dirty = ("Spot 227.25 [N1]. Episodes moved +18% [E2] -> 268. Go long here and set a stop-loss at 240. "
             "Size the position at 2% risk. You should buy.")
    for mr in (reg.FENCED, reg.OUTLOOK):
        assert reg.exec_leaks(reg.sanitize(dirty, market_register=mr)) == [], mr


def test_a2_fence_does_not_eat_honest_ag_prose():
    """The other half of a fence that fails closed: it must not fail LOUD on legitimate prose."""
    honest = cc._DETECTOR_CLEAN + (
        "economies of scale in the crush margin", "China may buy now rather than wait",
        "the USDA target price program supports the floor", "exports cut the position of Brazil",
        "the crop is vulnerable to frost", "a crowded export lineup", "short crop",
        "the drought squeeze regime aligns with a dry Brazil")
    for probe in honest:
        for mr in (reg.FENCED, reg.OUTLOOK):
            assert probe in reg.sanitize(probe + ".", market_register=mr), (mr, probe)


# FOLD-PASS 2026-07-30. `_EXEC_EXTRA` fired unconditionally on EVERY turn and its looser alternations
# collided with ordinary commodity prose: 6 of these 7 realistic sentences were DELETED outright on
# non-outlook turns (a content regression larger than the declared byte-identity exception, since the
# collateral was legitimate market-mechanics prose, not sizing advice). The ambiguous alternations are now
# frame-gated -- they need a first-or-second-person address or an imperative opening.
_HONEST_MARKET_MECHANICS = (
    "Crushers cut exposure to Argentine beans after the tax change.",
    "The mill will exit the position of a net exporter this year.",
    "The co-op will add to the position of stored grain.",
    "Traders had time to buy before the ban took effect.",
    "Reasons to buy Brazilian arabica included the frost.",
    "The entry price for the tender was set by COFCO.",
    "Position sizing of the state reserve auctions was unclear.",
    "The mill will buy at auction rather than on the spot market.",
    "Exporters reduce shorts against the physical book every harvest.",
)


def test_a2_fence_does_not_eat_honest_market_mechanics_prose():
    for probe in _HONEST_MARKET_MECHANICS:
        assert reg.exec_leaks(probe) == [], probe
        for mr in (reg.FENCED, reg.OUTLOOK):
            out = reg.sanitize(probe + " Stocks fell [N1].", market_register=mr)
            assert probe in out, (mr, probe)


# ── ADVERSARIAL: try to elicit execution language, prove refusal ──────────────────────────────────────
_ELICIT = (
    # the direct ask
    "You should buy coffee here.",
    "I'd be long soybeans into the report.",
    "We recommend going long palm.",
    "This is a good level to buy.",
    "Now is the time to buy.",
    # dressed as analysis
    "Given the buffer, the entry level is 240 and the stop level is 218.",
    "The risk/reward is 3:1 from here.",
    "Size the position at 2% of NAV.",
    "Scale in below 240 and trim the position into strength.",
    "Initiate a long here; put on a short in soyoil against it.",
    # riding a LEGAL derivation -- the sharpest shape, because the sentence around it is permitted
    "Spot 227.25 [N1]. Episodes moved +18% [E2] -> 268. So go long with a stop at 218.",
    "Spot 227.25 [N1]. Episodes moved +18% [E2] -> 268; that makes it a buy at 243.",
    # second-person framing, and the polite re-ask
    "Should you buy here? Yes -- accumulate here.",
    "If you want my call: take-profit at 268 and cut your longs below 220.",
    # THE COMPLETE TRADE PLAN, written by someone who never read the lexicon (fold-pass 2026-07-30).
    # Measured before the fix: every one of these passed `banned_exec: 0` AND survived sanitize under
    # BOTH registers -- a full recommendation served verbatim while the deck's one never-conditional pin
    # read green.
    "Buy at 240.",
    "Stop at 218.",
    "First target is 268, second 243.",
    "Size at 2% of NAV.",
    "Risk 22 points to make 28.",
    "I'd be a buyer on any dip toward 240.",
    "We like it here and would add.",
    "Sell it above 300 and buy it below 240.",
)


_TRADE_PLAN = ("Buy at 240. Stop at 218. First target is 268, second 243. Size at 2% of NAV. "
               "Risk 22 points to make 28. I'd be a buyer on any dip toward 240.")


def test_a_complete_trade_plan_is_refused_and_counted_end_to_end():
    """The blocker in its assembled form: the plan rode a LEGAL derivation and passed both new pins."""
    from leviathan.graphrag import eval as E
    st = {"tldr": "The balance of risks leans higher. Our objective is 268.",
          "mechanism": ("## Outlook\nSpot 227.25 EUR/t (Sep-26 settle) [N1]. Three comparable episodes "
                        "moved +18% / +7% / -3% over 90 days [E2] -> 268 / 243 / 220; median 243.\n"
                        + _TRADE_PLAN)}
    assert an._count_banned_exec(st) >= 6                            # -> banned_exec: 0 REDS
    assert an._count_unbacked_levels(st) >= 1                        # -> price_target_backed REDS
    row = _row({"banned_exec_words": an._count_banned_exec(st),
                "unbacked_levels": an._count_unbacked_levels(st)}, tldr=st["tldr"], mech=st["mechanism"])
    got = E._cascade_asserts({"expect": {"banned_exec": 0, "price_target_backed": True}}, row)
    assert got == {"banned_exec": False, "price_target_backed": False}
    # ... and the served prose keeps the derivation while deleting every instruction
    served = dict(st)
    an._humanize_structured(served, market_register=reg.OUTLOOK)
    assert "227.25" in served["mechanism"] and "268" in served["mechanism"]
    for gone in ("Buy at 240", "Stop at 218", "Size at 2%", "Risk 22 points", "I'd be a buyer"):
        assert gone not in served["mechanism"], gone
    assert reg.exec_leaks(served["mechanism"]) == [] and reg.exec_leaks(served["tldr"]) == []


def test_adversarial_execution_elicitation_is_always_refused():
    """Every one of these is refused under BOTH registers -- there is no phrasing, no flag and no
    surrounding derivation that buys an execution instruction its way through."""
    for probe in _ELICIT:
        for mr in (reg.FENCED, reg.OUTLOOK):
            out = reg.sanitize(probe, market_register=mr)
            assert reg.exec_leaks(out) == [], (mr, probe, out)


def test_adversarial_execution_riding_a_legal_derivation_keeps_the_derivation():
    """The refusal is SURGICAL: the legal derivation survives, only the instruction is deleted. A blunt
    fence that ate the whole answer would push the model to stop showing its work."""
    probe = "Spot 227.25 [N1]. Episodes moved +18% [E2] -> 268. So go long with a stop at 218."
    out = reg.sanitize(probe, market_register=reg.OUTLOOK)
    assert "227.25" in out and "268" in out                          # the derivation is intact
    assert "go long" not in out and "218" not in out                 # the instruction is gone


def test_adversarial_bare_target_cannot_launder_through_a_nearby_citation():
    """A handle somewhere else in the text must not back an unrelated minted level."""
    probe = "Brazilian output fell [E1]. Coffee is going to 320."
    out = reg.sanitize(probe, market_register=reg.OUTLOOK)
    assert "Brazilian output fell [E1]." in out
    assert "320" not in out


def test_adversarial_outlook_query_asking_for_a_level_is_not_an_outlook_ask():
    """An execution ask must never even ENTER outlook mode -- the regex declines it, so the turn runs on
    the fenced register and gets today's refusal."""
    for q in ("is this a good level to buy?", "where should I put my stop?",
              "what size should I take?", "should I go long coffee?", "give me an entry point"):
        assert not it.is_outlook_explicit(q), q


# ── D4: the fail-CLOSED gate ──────────────────────────────────────────────────────────────────────────
def test_is_outlook_explicit_fires_on_forward_price_asks():
    for q in ("where do prices go from here?", "what will happen to the price of coffee?",
              "what's your view on prices?", "price outlook for palm oil",
              "outlook for the price of wheat", "how high can prices go?",
              "where are prices headed?", "where do you see prices going?"):
        assert it.is_outlook_explicit(q), q


def test_is_outlook_explicit_fires_with_a_commodity_word_between_the_modal_and_the_noun():
    """FOLD-PASS 2026-07-30. The shipped alternations had no slot for a commodity word between the modal
    and the price noun, and `(price|prices) from here` demanded adjacency -- so FOUR of the six
    outlook-positive deck rows, including the marquee, red their own `outlook_rendered: true` pin BY
    CONSTRUCTION. Every string below is a real deck question."""
    for q in ("Where do corn prices go from here, and what would change your mind?",
              "How high can wheat prices go from here?",
              "Where do soybean oil prices go from here, and how does managed-money positioning bear on it?",
              "Where do cocoa prices go from here?",
              "What's your view on coffee prices from here?",
              "where are soybean prices headed?",
              "how high can arabica coffee prices go?"):
        assert it.is_outlook_explicit(q), q


def test_is_outlook_explicit_declines_backward_and_mechanism_asks():
    for q in ("why did prices rally in 2010?", "what was the price of corn in 2013?",
              "how does the palm ban affect soybean oil prices?", "where were prices in 2010?",
              "what drove the price move?", "explain the cascade", "any news on wheat?",
              "how much did exports fall?"):
        assert not it.is_outlook_explicit(q), q


def test_is_outlook_explicit_declines_conditional_mechanism_asks():
    """The regex's own docstring lists conditional mechanism asks as deliberately-not-matched, but the
    'what will happen to the price' alternative fired on every one of them. PLANNER_SYS's own negative
    example is the same class, so the planner leg is not a reliable backstop for it."""
    for q in ("What will happen to the price of wheat if Russia bans exports again?",
              "What would happen to the price of soyoil under a higher biodiesel mandate?",
              "What might happen to the price of cocoa if the harmattan is severe?",
              "What would happen to the price of corn should the ethanol mandate be cut?"):
        assert not it.is_outlook_explicit(q), q
    assert it.is_outlook_explicit("what will happen to the price of coffee?")     # unconditional -> fires


def test_every_outlook_deck_row_agrees_with_the_regex():
    """The one-line lint that would have caught the four red-by-construction rows. `outlook_rendered` is
    ANDed with the planner leg and the kill-switch, so the regex is a NECESSARY condition: a row pinning
    `outlook_rendered: true` whose question the regex declines can never pass."""
    import pathlib

    import yaml
    root = pathlib.Path(an.__file__).parents[3] / "configs" / "graphrag"
    deck = yaml.safe_load((root / "eval_queries_outlook_v1.yaml").read_text(encoding="utf-8"))
    for r in deck["queries"]:
        want = (r.get("expect") or {}).get("outlook_rendered")
        if want is None:
            continue
        assert it.is_outlook_explicit(r["question"]) is bool(want), (r["id"], r["question"])


def test_plan_outlook_flag_is_strict_and_defaults_false():
    ids = {"soybeans_cbot"}
    assert dp._validate({"steps": ["reasoning"], "contracts": []}, ids).answer_mode_outlook is False
    for junk in ("true", 1, "yes", None, {}):                        # only a schema-typed True counts
        plan = dp._validate({"steps": ["reasoning"], "contracts": [], "answer_mode_outlook": junk}, ids)
        assert plan.answer_mode_outlook is False, junk
    plan = dp._validate({"steps": ["reasoning"], "contracts": [], "answer_mode_outlook": True}, ids)
    assert plan.answer_mode_outlook is True
    assert plan.trace()["answer_mode_outlook"] is True


def test_outlook_is_a_mode_not_a_step():
    """MAX_STEPS stays 3 and kind() is untouched -- outlook renders the reasoner's output, it does not run."""
    assert dp.MAX_STEPS == 3
    plan = dp._validate({"steps": ["reasoning"], "contracts": [], "answer_mode_outlook": True}, set())
    assert plan.kind() == "reasoning"
    assert "outlook" not in {t.name for t in dp.REGISTRY}


def test_outlook_kill_switch_defaults_off_and_is_read_per_call(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_OUTLOOK", raising=False)
    assert an._outlook_on() is False
    monkeypatch.setenv("GRAPHRAG_OUTLOOK", "on")
    assert an._outlook_on() is True                                   # per-call read -> env-flip rollback is live
    monkeypatch.setenv("GRAPHRAG_OUTLOOK", "off")
    assert an._outlook_on() is False


def test_system_prompt_gains_outlook_paragraph_only_when_asked():
    base, out = an._system(), an._system(outlook=True)
    assert base == an._system()                                       # default arg is byte-identical
    assert "## Outlook" not in base and "## Outlook" in out
    assert "A LEVEL WITHOUT ITS DERIVATION IS A REFUSAL" in out       # the gate is stated, not implied
    assert "no position sizing" in out and "no stops" in out          # A2 named explicitly


# ── D3: the blast radius ──────────────────────────────────────────────────────────────────────────────
def test_seams_that_must_never_relax_are_byte_identical():
    """The sharpest known hazard (W5.1 Step 3) and the one the skeptic's F-H added. Read the SOURCE: these
    call sites must not pass market_register at all, so no future edit can hand them a scope. Chips in
    particular are NOT intent-scoped -- a relaxed guard there would leak valuation vocabulary into
    follow-up chips on EVERY turn."""
    import pathlib
    root = pathlib.Path(an.__file__).parent
    # orchestrator: the numbers body, the four news-event summaries and the live header (6 sites). server:
    # the grounded-suggester catalog text (1 site) -- a sanitize seam the W5 plan never enumerated, found by
    # grep rather than by reading the plan, and every bit as un-relaxable as the chip guard beside it.
    for mod, n_expected in (("orchestrator.py", 6), ("server.py", 1)):
        src = (root / mod).read_text(encoding="utf-8")
        calls = [ln for ln in src.splitlines() if "reg.sanitize(" in ln]
        assert len(calls) >= n_expected, (mod, len(calls))
        for ln in calls:
            if "market_register=reg.FENCED" in ln:                   # the F-H session-carry fix: explicit
                continue
            assert "market_register" not in ln, (mod, ln)
    # the chip guard itself still rides the UNSPLIT register_leaks + lane_b_hits
    server_src = (root / "server.py").read_text(encoding="utf-8")
    assert "reg.register_leaks(s) or reg.lane_b_hits(s)" in server_src


def test_session_carry_is_refenced_unconditionally():
    """F-H: the tl;dr is continuity context, not the answer. An outlook turn's permitted vocabulary must
    not ride into turn N+1, which runs the FENCED register -- and a stateless deck cannot see this."""
    import pathlib
    src = (pathlib.Path(an.__file__).parent / "orchestrator.py").read_text(encoding="utf-8")
    assert "answer_tldr=reg.sanitize(_tldr, market_register=reg.FENCED)" in src


def test_roll_summary_fences_the_compactors_own_paraphrase():
    from leviathan.graphrag import session as ss

    def fake_call(system, user, **kw):
        return {"entities": [], "thesis": "positioning is a crowded long and it is a buy at 240",
                "open_threads": ["go long soyoil"]}

    state = ss.SessionState()
    turn = ss.TurnRecord(turn=0, query="q", answer_tldr="t", contracts=[], asof=None)
    out = ss.roll_summary(state, turn, call=fake_call)
    assert "crowded long" not in out.summary["thesis"]
    assert reg.exec_leaks(out.summary["thesis"]) == []
    assert all(reg.exec_leaks(t) == [] for t in out.summary["open_threads"])


def test_build_lint_asserts_the_whole_fence():
    """The fence is a build-time gate, not a prompt paragraph -- if this ever regresses, config_check fails."""
    assert cc._check_outlook_fence() == []
    assert cc._check_register_detector() == []


# ── D5b / D6 / D7 / D8: the pins and the deck ─────────────────────────────────────────────────────────
def _row(trace: dict, *, tldr: str = "", mech: str = "") -> dict:
    return {"trace": trace, "structured": {"tldr": tldr, "mechanism": mech},
            "citations": [], "number_calls": [], "answer": tldr + " " + mech}


def test_price_target_backed_reads_the_raw_counter():
    from leviathan.graphrag import eval as E
    q = {"expect": {"price_target_backed": True}}
    assert E._cascade_asserts(q, _row({"unbacked_levels": 0}))["price_target_backed"] is True
    assert E._cascade_asserts(q, _row({"unbacked_levels": 2}))["price_target_backed"] is False


def test_banned_exec_pin_is_a_zero_equality():
    from leviathan.graphrag import eval as E
    q = {"expect": {"banned_exec": 0}}
    assert E._cascade_asserts(q, _row({"banned_exec_words": 0}))["banned_exec"] is True
    assert E._cascade_asserts(q, _row({"banned_exec_words": 1}))["banned_exec"] is False


def test_directional_claim_backed_is_planner_aware():
    """The plan's version read `fired_regimes` only -- which _answer_l2 stamps and the one-hop body does
    NOT. On a GRAPHRAG_PLANNER=onehop rollback that silently degraded the pin to its cascade disjunct."""
    from leviathan.graphrag import eval as E
    q = {"expect": {"directional_claim_backed": True}}
    l2 = _row({"fired_regimes": [{"name": "drought_squeeze"}]})       # L2 trace key
    onehop = _row({"regimes": ["drought_squeeze"]})                   # one-hop trace key
    neither = _row({})
    assert E._cascade_asserts(q, l2)["directional_claim_backed"] is True
    assert E._cascade_asserts(q, onehop)["directional_claim_backed"] is True
    assert E._cascade_asserts(q, neither)["directional_claim_backed"] is False


def test_ceiling_pins_are_inequalities_not_equalities():
    from leviathan.graphrag import eval as E
    q = {"expect": {"max_banned_flow": 3}}
    for n, ok in ((0, True), (3, True), (4, False)):
        assert E._cascade_asserts(q, _row({"banned_flow_words": n}))["max_banned_flow"] is ok, n


def test_judge_axis_survives_the_record_projection():
    """A new axis absent from _judge_metrics' whitelist is silently dropped from every baseline JSON."""
    from leviathan.graphrag import eval as E
    assert "directional_traceability" in E._judge_tool()["input_schema"]["properties"]
    assert "directional_traceability" not in E._judge_tool()["input_schema"]["required"]
    assert "directional_traceability" in E._JUDGE_SYS
    assert "OUTLOOK EXCEPTION" in E._JUDGE_SYS                        # the standing rubric penalizes targets
    row = {"q": {"id": "x", "contract": "corn"}, "out": {"trace": {}, "answer": ""},
           "judge": {"usefulness": 4, "directional_traceability": 5}}
    assert E._per_answer_record(row, "single")["judge"]["directional_traceability"] == 5


def test_outlook_deck_pins_are_all_known_keys():
    """A typo'd expect key is SILENTLY IGNORED by _cascade_asserts -- a deck row that pins nothing looks
    exactly like a deck row that passes. Assert every key in the new deck is one the harness implements."""
    import pathlib

    import yaml
    from leviathan.graphrag import eval as E
    root = pathlib.Path(an.__file__).parents[3] / "configs" / "graphrag"
    deck = yaml.safe_load((root / "eval_queries_outlook_v1.yaml").read_text(encoding="utf-8"))
    rows = deck["queries"]
    assert len(rows) >= 12, len(rows)                                 # D8 asks for 12-15 rows
    known = set(E._CASCADE_EXPECT) | {"needs_evidence"}
    for r in rows:
        assert r.get("id") and r.get("question"), r
        unknown = set(r.get("expect") or {}) - known
        assert not unknown, (r["id"], unknown)
        # the one pin that is never conditional and never optional
        assert (r["expect"] or {}).get("banned_exec") == 0, r["id"]


def test_convo_deck_carries_the_session_carry_gate():
    """F-H is only closed if a deck actually exercises it: an outlook turn FOLLOWED BY a fenced turn."""
    import pathlib

    import yaml
    root = pathlib.Path(an.__file__).parents[3] / "configs" / "graphrag"
    convos = yaml.safe_load((root / "eval_convos_v1.yaml").read_text(encoding="utf-8"))["conversations"]
    gate = next((c for c in convos if c["id"] == "convo_f_outlook_carry_fence"), None)
    assert gate is not None
    turns = gate["turns"]
    relaxed = [i for i, t in enumerate(turns) if t.get("outlook_rendered") is True]
    fenced_after = [i for i, t in enumerate(turns) if t.get("fenced_follow_up")]
    assert relaxed and fenced_after
    assert min(fenced_after) > min(relaxed)                           # the gate turn comes AFTER the relaxed one
    assert all(t.get("banned_exec_zero") for t in turns)


# ── END-TO-END: the whole thread, answer() -> sanitize -> trace ───────────────────────────────────────
def _e2e_graph():
    from leviathan.causal import schema as csx
    from leviathan.graphrag import graph as gx
    coffee = csx.CausalContract(
        contract="arabica_coffee", aliases=["arabica", "coffee"],
        drivers=[csx.Driver(id="frost", type="hazard", sign="+", mechanism="frost kills trees")],
        convergence=[csx.ConvergenceSignal(name="squeeze", direction="+", requires_any_n_of=1,
                                           drivers=["frost"])])
    return gx.CausalGraph(contracts={"arabica_coffee": coffee}, version="t1")


def _e2e(monkeypatch, *, flag: str | None, outlook_arg: bool, tldr: str, mech: str = "",
         verify: bool = False) -> dict:
    if flag is None:
        monkeypatch.delenv("GRAPHRAG_OUTLOOK", raising=False)
    else:
        monkeypatch.setenv("GRAPHRAG_OUTLOOK", flag)
    # The citation verifier runs BEFORE sanitize and strips handles it cannot resolve. These fakes inject
    # one evidence item and no number rows, so [N1] would be 'fabricated' here and the verifier would eat
    # it -- masking what the register is doing. Default it off to isolate the register; the COMPOSITION of
    # the two is asserted separately in test_e2e_verifier_strip_composes_with_the_derivation_gate.
    monkeypatch.setenv("GRAPHRAG_VERIFY", "on" if verify else "off")

    def fake_call(system, user, *, model, tool):
        return {"tldr": tldr, "mechanism": mech, "diagram_mermaid": "",
                "sources": [{"ref": 1, "source": "usda_wasde", "date": "2022-01-01", "note": ""}]}

    def fake_retrieve(q, contract, *, k, asof=None, near=None):
        return [{"date": "2022-01-01", "source": "usda_wasde", "source_key": f"s3://{contract}",
                 "text": "note"}]

    return an.answer("where do coffee prices go from here", graph=_e2e_graph(),
                     retrieve=fake_retrieve, call=fake_call, outlook=outlook_arg)


_E2E_TLDR = ("Positioning is a crowded long and the discount screens rich. "
             "Spot 227.25 (Sep-26 settle) [N1]. Episodes moved +18% [E1] -> 268. "
             "Go long here with a stop-loss at 218.")


def test_e2e_all_three_legs_required_to_relax(monkeypatch):
    """The gate is fail-CLOSED: the flag alone, or the argument alone, relaxes NOTHING."""
    for flag, arg in ((None, True), ("off", True), ("on", False), (None, False)):
        out = _e2e(monkeypatch, flag=flag, outlook_arg=arg, tldr=_E2E_TLDR)
        assert out["trace"]["outlook_mode"] is False, (flag, arg)
        assert out["trace"]["market_register"] == reg.FENCED, (flag, arg)
        assert "crowded long" not in out["answer"], (flag, arg)     # fenced: the flow sentence is deleted


def test_e2e_all_three_legs_present_relaxes_exactly_the_right_things(monkeypatch):
    out = _e2e(monkeypatch, flag="on", outlook_arg=True, tldr=_E2E_TLDR)
    body, st = out["answer"], out["structured"]
    assert out["trace"]["outlook_mode"] is True
    assert out["trace"]["market_register"] == reg.OUTLOOK
    # RELAXED: A1 valuation + B positioning flow now survive ...
    assert "crowded long" in body and "screens rich" in body
    # ... and so does the DERIVED level, because its derivation is shown and its inputs are cited ...
    assert "227.25" in body and "268" in body
    # ... but the EXECUTION instruction is deleted on the very same turn.
    assert "Go long" not in body and "stop-loss" not in body and "218" not in body
    assert reg.exec_leaks(body) == [] and reg.exec_leaks(st["tldr"]) == []
    # the raw counters still measure everything, pre-sanitize (Step 5: the counter stays honest)
    assert out["trace"]["banned_flow_words"] >= 1
    assert out["trace"]["banned_exec_words"] >= 1                    # -> the deck pin `banned_exec: 0` reds
    assert out["trace"]["unbacked_levels"] == 0                      # -> `price_target_backed` passes


def test_e2e_bare_target_is_refused_even_in_outlook_mode(monkeypatch):
    out = _e2e(monkeypatch, flag="on", outlook_arg=True,
               tldr="Coffee is going to 320 by year end. The balance sheet is tight [E1].")
    assert out["trace"]["outlook_mode"] is True
    assert "320" not in out["answer"]                                # the bare level is a refusal
    assert "balance sheet is tight [E1]" in out["answer"]            # the cited sentence survives
    assert out["trace"]["unbacked_levels"] >= 1                      # -> `price_target_backed` reds


def test_e2e_verifier_strip_composes_with_the_derivation_gate(monkeypatch):
    """DEFENCE IN DEPTH, and the ordering matters. The citation verifier runs BEFORE sanitize, so a
    FABRICATED handle is stripped first -- which then leaves the level it was propping up UNCITED, and the
    derivation gate refuses it. A laundered citation cannot back a price target. This is the T2b
    `fabricated_citation x23` failure mode and the W5.0 fabrication argument meeting in one seam."""
    out = _e2e(monkeypatch, flag="on", outlook_arg=True, verify=True,
               tldr="Spot 227.25 [N9]. Episodes moved +18% [E9] -> 268.")
    assert out["trace"]["outlook_mode"] is True
    assert "268" not in out["answer"] and "227.25" not in out["answer"]


def test_e2e_non_outlook_turn_is_untouched_by_the_wave(monkeypatch):
    """The blast-radius property in miniature: with the flag ON but the turn not an outlook ask, the
    answer is exactly what it is today."""
    tldr = "Ending stocks fell to 44.79 MMT [N1]; the drought driver is active."
    on = _e2e(monkeypatch, flag="on", outlook_arg=False, tldr=tldr)
    off = _e2e(monkeypatch, flag=None, outlook_arg=False, tldr=tldr)
    assert on["answer"] == off["answer"]
    assert "44.79 MMT [N1]" in on["answer"]


def test_convo_mechanics_checks_the_carry_gate():
    from leviathan.graphrag import eval as E
    clean = {"trace": {"outlook_mode": False, "banned_flow_words": 0, "banned_valuation_words": 0,
                       "banned_exec_words": 0}, "answer": "Ending stocks fell to 44.8 MMT [N1]."}
    leaked = {"trace": {"outlook_mode": False, "banned_flow_words": 2, "banned_valuation_words": 0,
                        "banned_exec_words": 0}, "answer": "A crowded long is the risk."}
    spec = {"fenced_follow_up": True, "banned_exec_zero": True}
    assert E._convo_mechanics(spec, clean, None)["follow_up_fenced_ok"] is True
    assert E._convo_mechanics(spec, leaked, None)["follow_up_fenced_ok"] is False
