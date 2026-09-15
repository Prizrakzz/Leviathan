"""Output-register linter — deterministic, no spend.

Guards that internal representation (raw slugs, `conf=`, a bare `(+)`, graph jargon) is caught when it leaks
into reader prose, and — just as important — that a clean researcher-register answer trips NOTHING (false
positives would make the eval metric noise).
"""
from __future__ import annotations

from leviathan.graphrag import evidence as ev
from leviathan.graphrag import register as reg
from leviathan.graphrag.state import render as _rd  # the REAL producer of a board call (S7b fixes)


def _tokens(text: str) -> set[str]:
    return {t for t, _ in reg.register_leaks(text)}


def test_internal_markers_flagged():
    toks = _tokens("The drought driver has conf=high and sign=+ per silver_ref=silver_psd, any_n_of=2.")
    assert {"conf=", "sign=", "silver_ref", "any_n_of"} <= toks


def test_bare_sign_symbols_flagged():
    toks = {t for t, _ in reg.register_leaks("Frost (+) and a strong dollar (-) net out (+/-) here.")}
    assert "(+)" in toks and "(-)" in toks and "(+/-)" in toks


def test_graph_jargon_flagged():
    toks = _tokens("Once the drought threshold is crossed the node fired and the node propagates to price.")
    assert "the node fired" in toks or "the node" in toks


def test_clean_researcher_prose_has_no_leaks():
    clean = ("Soybeans point to higher prices into 2021: the drought driver is active, confirmed by the 2021-07 "
             "WASDE cut to Brazilian output. The price response turns convex once ending stocks fall below the "
             "buffer, a classic tail-risk regime. A strong dollar is a price-pressuring offset. Stocks-to-use "
             "fell 5-10%. This is outside the tracked driver model; a real-time read isn't available and the "
             "observed data is silent.")
    assert reg.register_leaks(clean) == []                            # register-approved phrasing trips nothing


def test_internal_architecture_prose_flagged():
    toks = _tokens("This link is outside the mapped graph; the causal graph lacks it and the live-feature layer "
                   "isn't here. No dated evidence item covers it in the silver numbers layer.")
    assert {"mapped graph", "causal graph", "live-feature layer", "dated evidence item",
            "silver numbers layer"} <= toks                          # P1.1: internal-layer prose is a leak


def test_sanitize_rewrites_architecture_prose(monkeypatch):
    _hier_stub(monkeypatch)
    try:
        dirty = ("The signal is outside the mapped graph; the causal graph lacks it, the live-feature layer isn't "
                 "here, and no dated evidence item exists in the silver numbers layer.")
        clean = reg.sanitize(dirty)
        assert reg.register_leaks(clean) == []                        # the load-bearing property
        assert "tracked driver model" in clean and "driver model" in clean and "real-time data" in clean
        assert "observed data" in clean and "dated source" in clean
        assert "mapped graph" not in clean and "causal graph" not in clean and "live-feature layer" not in clean
    finally:
        reg._slugs.cache_clear()
        reg._display_map.cache_clear()


def test_mermaid_signs_are_not_prose_leaks():
    md = ('The frost points to higher prices for arabica.\n\n```mermaid\nflowchart LR\n frost["frost (+)"] --> price\n```\n')
    assert reg.register_leaks(md) == []                               # signs live in the diagram, not the prose


def test_ranges_and_signed_numbers_are_not_leaks():
    assert reg.register_leaks("Output fell (-5%) to 44.8 MMT, a swing of -2.3 MMT vs the prior 2023-24 print.") == []


def test_multitoken_slug_flagged_single_word_ok(monkeypatch):
    monkeypatch.setattr(ev, "_hier", lambda: {"contracts": {"soybeans_no_2_dce": {}, "corn": {}, "arabica_coffee": {}}})
    reg._slugs.cache_clear()
    try:
        toks = _tokens("Watch soybeans_no_2_dce and arabica_coffee; corn stays rangebound.")
        assert "soybeans_no_2_dce" in toks and "arabica_coffee" in toks   # raw underscored slugs leaked
        assert "corn" not in toks                                         # single-word id is fine in prose
    finally:
        reg._slugs.cache_clear()


def _hier_stub(monkeypatch):
    monkeypatch.setattr(ev, "_hier", lambda: {"contracts": {
        "soybeans_cbot": {"node": "soybeans", "exchange": "CBOT"},
        "soybean_oil_dce": {"node": "soybean_oil", "exchange": "DCE"},
        "corn": {"node": "corn", "exchange": "CBOT"}}})
    reg._slugs.cache_clear()
    reg._display_map.cache_clear()


def test_sanitize_rewrites_tokens_and_leaves_no_leaks(monkeypatch):
    _hier_stub(monkeypatch)
    try:
        dirty = ("The drought driver has conf=high and sign=+; soybeans_cbot is bullish (+), soybean_oil_dce "
                 "bearish (-), net (+/-). silver_ref=silver_psd. The node fired.")
        clean = reg.sanitize(dirty)
        assert reg.register_leaks(clean) == []                            # the load-bearing property
        assert "high confidence" in clean and "points to higher prices" in clean and "(mixed)" in clean
        assert "(upward price pressure)" in clean and "(downward price pressure)" in clean
        assert "price-supportive" in clean                                # bare 'bullish' -> _MOOD safety net
        assert "bullish" not in clean and "bearish" not in clean          # mood words never survive sanitize
        assert "CBOT soybeans" in clean and "DCE soybean oil" in clean    # slug -> reader name
        assert "conf=" not in clean and "sign=" not in clean and "silver_ref" not in clean
        assert "soybeans_cbot" not in clean and "the node" not in clean.lower()
    finally:
        reg._slugs.cache_clear()
        reg._display_map.cache_clear()


def test_sanitize_preserves_mermaid_citations_numbers(monkeypatch):
    _hier_stub(monkeypatch)
    try:
        txt = ("Ending stocks were 44.79 MMT on 2024-01-10, bearish [E1][N2].\n\n"
               "```mermaid\nflowchart LR\n a[\"frost (+)\"] --> b\n```\n")
        out = reg.sanitize(txt)
        assert "44.79 MMT" in out and "2024-01-10" in out and "[E1][N2]" in out   # numbers/dates/citations intact
        assert '```mermaid\nflowchart LR\n a["frost (+)"] --> b\n```' in out       # diagram (with its sign) untouched
    finally:
        reg._slugs.cache_clear()
        reg._display_map.cache_clear()


def test_sanitize_idempotent(monkeypatch):
    _hier_stub(monkeypatch)
    try:
        dirty = "conf=low frost; soybeans_cbot (+); the node fired."
        once = reg.sanitize(dirty)
        assert reg.sanitize(once) == once                                # stable under re-application
    finally:
        reg._slugs.cache_clear()
        reg._display_map.cache_clear()


def test_regime_id_flagged_as_leak():
    toks = _tokens("A bullish_drought_squeeze needs three drivers; watch for a bearish_glut.")
    assert "bullish_drought_squeeze" in toks and "bearish_glut" in toks    # raw regime ids are internal


def test_sanitize_humanizes_regime_ids(monkeypatch):
    _hier_stub(monkeypatch)
    try:
        dirty = "The bullish_drought_squeeze aligns with drought; a bearish_glut is the offset."
        clean = reg.sanitize(dirty)
        assert "bullish_drought_squeeze" not in clean and "bearish_glut" not in clean
        assert "drought squeeze (price-supportive)" in clean and "supply glut (price-pressuring)" in clean
        assert reg.register_leaks(clean) == []                             # humanized -> no leak remains
    finally:
        reg._slugs.cache_clear()
        reg._display_map.cache_clear()


def test_eval_metric_and_panel_pick_up_leaks(monkeypatch):
    from leviathan.graphrag import eval as E
    monkeypatch.setattr(ev, "_hier", lambda: {"contracts": {}})
    reg._slugs.cache_clear()
    rows = [
        {"q": {"contract": "soybeans", "id": "q1"},
         "out": {"answer": "Soybeans are bullish; the driver is active.", "evidence": [], "structured": {}},
         "rubric": {"routed_right": True}},
        {"q": {"contract": "corn", "id": "q2"},
         "out": {"answer": "Corn has conf=high and the node fired (+).", "evidence": [], "structured": {}},
         "rubric": {"routed_right": True}},
    ]
    assert E._metrics(rows[0])["register_leaks"] == 0
    assert E._metrics(rows[1])["register_leaks"] >= 2                 # conf= + (+) + jargon
    panel = "\n".join(E.register_report(rows))
    assert "Output register" in panel and "answers with leaks: 1/2" in panel
    # this test populates reg._slugs()/_display_map() under the empty-contracts stub; monkeypatch restores
    # _hier at teardown but NOT the lru_cache -> without this, () leaks forward and later tests that rely on
    # sanitize() humanizing real slugs (e.g. test_suggester_catalog) fail depending on collection order.
    reg._slugs.cache_clear(); reg._display_map.cache_clear()


# -- PRICE_OBSERVABILITY W0.1/W0.3 -- price/positioning register fence ------------------------------------
_LANE_A_VALUATION = (
    "raise the price target", "take-profit here", "a stop-loss below", "go long soyoil", "buy the dip",
    "fade the rally", "worth fading", "the spread looks cheap", "a relative value trade", "undervalued",
    "overvalued", "mispriced", "dislocated", "overdone", "overshot", "at attractive levels", "fair value",
    "it screens rich")
_LANE_A_FLOW = (
    "squeeze potential", "vulnerable to a squeeze", "a short squeeze", "a pain trade", "forced liquidation",
    "forced covering", "capitulation", "shorts would need to chase", "a crowded long", "one-sided positioning",
    "offside", "a coiled spring", "dry powder", "stretched positioning", "if funds cover")
# every S1.F4 evasion sentence -- the class fence, not the word list. These are the plan's (W0.3) EXACT bare
# strings; do NOT strengthen them to easier-to-flag variants (S1.F3) -- the detector must catch the plan form.
_CLASS_POSITIVES = (
    "the discount has room to normalize", "spreads this wide rarely persist",
    "due for a correction", "mean reversion favors the discount narrowing",
    "squeeze potential", "forced liquidation", "shorts would need to chase",
    "the premium should converge next quarter", "this premium is unsustainable",
    "the basis cannot last at these levels")
# ag prose that collides with the fence vocabulary but is honest fundamentals -- must all pass clean
_MUST_NOT_FLAG = (
    "the spread narrowed in 2016", "the premium averaged $250 [N1]", "stocks are rich relative to use",
    "the crop is vulnerable to frost", "a crowded export lineup", "short crop", "long-term outlook",
    "the drought squeeze regime aligns with a dry Brazil", "a supply squeeze in the balance sheet")


def test_lane_a_valuation_and_flow_phrases_flagged():
    for t in _LANE_A_VALUATION:
        assert reg.register_leaks(t), t                              # Lane A rides register_leaks (chip-safe)
        assert reg.count_valuation_words(t) >= 1, t
    for t in _LANE_A_FLOW:
        assert reg.register_leaks(t), t
        assert reg.count_flow_words(t) >= 1, t


def test_class_rule_positives_flagged():
    for t in _CLASS_POSITIVES:
        assert reg.register_leaks(t), t                              # forward-convergence / persistence-denial


def test_price_fence_must_not_flag_ag_prose():
    for t in _MUST_NOT_FLAG:
        assert reg.register_leaks(t) == [], t
        assert reg.count_valuation_words(t) == 0, t
        assert reg.count_flow_words(t) == 0, t


def test_lane_b_windowed_words_and_excluded_nouns():
    # bare mood adjective + a window noun (or a relative-value comparison) fires Lane B ...
    assert reg.lane_b_hits("the premium looks cheap") >= 1
    assert reg.lane_b_hits("positioning looks stretched") >= 1
    assert reg.lane_b_hits("net length looks rich") >= 1
    assert reg.lane_b_hits("Is palm cheap vs soyoil?") >= 1          # comparison marker is the window here
    # ... but an ag-collision noun suppresses it, and a bare adjective with no window is legal
    assert reg.lane_b_hits("stocks are rich relative to use") == 0
    assert reg.lane_b_hits("the crop is vulnerable to frost") == 0
    assert reg.lane_b_hits("a crowded export lineup") == 0
    assert reg.lane_b_hits("coffee is cheap this year") == 0         # no window noun -> not Lane B
    # SINGULAR "supply" excludes like its plural (the 2026-08-04 one-token defect: the pattern
    # carried "supplies" only, so honest FX/cost statements about supply counted as valuation --
    # all three of that day's banned_valuation deck reds traced to this token)
    assert reg.lane_b_hits("a strong dollar makes US wheat expensive for buyers who lost Black Sea supply") == 0
    assert reg.lane_b_hits("supplies are stretched into the new crop year") == 0
    assert reg.lane_b_hits("the supply picture is vulnerable to a second failure") == 0


def test_raw_counters_split_valuation_from_flow():
    assert reg.count_valuation_words("undervalued and mispriced") == 2 and reg.count_flow_words("undervalued") == 0
    assert reg.count_flow_words("a short squeeze and forced liquidation") == 2
    assert reg.count_valuation_words("the discount should normalize soon") == 1   # class rule counts as valuation
    assert reg.count_valuation_words("stocks-to-use fell 5-10% into 2021") == 0   # honest fundamentals


def test_sanitize_strips_price_sentences_invariant_and_idempotent():
    dirty = ("Ending stocks fell to 44.8 MMT [N1]. The spread looks cheap and is undervalued. "
             "The discount has room to normalize. Is palm cheap vs soyoil?")
    clean = reg.sanitize(dirty)
    assert "44.8 MMT" in clean and "[N1]" in clean                   # the honest dated sentence survives
    assert reg.register_leaks(clean) == []                           # the load-bearing invariant (DP-6 strip)
    assert reg.count_valuation_words(clean) == 0 and reg.count_flow_words(clean) == 0
    assert "undervalued" not in clean and "room to normalize" not in clean
    assert reg.sanitize(clean) == clean                              # idempotent under re-application


def test_sanitize_strip_never_paraphrases_regime_squeeze(monkeypatch):
    _hier_stub(monkeypatch)
    try:
        # the FUNDAMENTAL drought-squeeze regime vocabulary must survive the strip (only positioning squeezes go)
        clean = reg.sanitize("The drought squeeze tightens the balance sheet; forced liquidation is a risk.")
        assert "drought squeeze" in clean                            # fundamental regime word kept
        assert "forced liquidation" not in clean                    # positioning-flow sentence stripped
        assert reg.register_leaks(clean) == []
    finally:
        reg._slugs.cache_clear()
        reg._display_map.cache_clear()


# -- S1.F1: the forward-convergence verbs must NOT match the -ly ADVERBS (open \w* stems were the bug) --------
_CONVERGE_ADVERB_CLEAN = (
    "The premium should be watched closely.",
    "The basis will be monitored closely by the desk.",
    "The spread is narrowly defined and will be reported.",
    "The premium should be interpreted correctly.")


def test_convergence_verbs_do_not_false_flag_adverbs():
    for t in _CONVERGE_ADVERB_CLEAN:
        assert reg.register_leaks(t) == [], t                        # 'closely'/'narrowly'/'correctly' are honest
        assert reg.count_valuation_words(t) == 0, t
        # and the honest sentence is NOT silently stripped out of an answer
        combined = t + " Ending stocks fell to 1.2 bt [N1]."
        clean = reg.sanitize(combined)
        assert t.split(".")[0] in clean, t                           # the first clause survives sanitize
        assert "1.2 bt [N1]" in clean, t


def test_convergence_verbs_still_flag_real_verb_forms():
    # the anchored forms must still catch genuine convergence verbs with a spread noun + futurity
    for t in ("the spread should narrow", "the premium will close the gap next quarter",
              "the discount is due to narrow", "the basis should correct"):
        assert reg.register_leaks(t), t


# -- S1.F2/W0-1: register_leaks(sanitize(x)) == [] must hold across bare-newline (bulleted) class-rule prose ---
_NEWLINE_LEAK_PROSE = (
    "The premium is wide today\nand it should narrow before year end",
    "The premium is wide\nand it should narrow soon.",
    "Prices look fine but the premium is wide\nand should narrow soon in the note.",
    "- The soy/palm premium is at multi-year highs\n- it should compress as palm output recovers",
    "Drivers:\n- premium wide\n- likely to narrow into Q4")


def test_newline_spanning_class_rule_invariant_holds():
    for x in _NEWLINE_LEAK_PROSE:
        assert reg.register_leaks(x), x                              # the scanner DOES flag the line-wrapped triple
        assert reg.register_leaks(reg.sanitize(x)) == [], x          # ... and the strip removes exactly that unit


# -- S1.F4/W0-2/R8: positioning/timing squeeze evasions flag; the fundamental regime squeeze stays clean -------
_SQUEEZE_POSITIONING = (
    "primed for a squeeze", "ripe for a squeeze", "positioning is set up for a squeeze",
    "the market could squeeze higher", "a violent squeeze higher looks likely",
    "a squeeze is coming", "shorts are trapped and a squeeze looms", "shorts are getting squeezed",
    "expect a squeeze soon", "a squeeze could send prices higher")
_SQUEEZE_FUNDAMENTAL_CLEAN = (
    "the drought squeeze regime aligns with a dry Brazil", "a supply squeeze in the balance sheet",
    "the China demand squeeze tightens the balance sheet", "a delivery squeeze in the physical market",
    "the feedstock squeeze supports crush margins")


def test_positioning_squeeze_evasions_flag():
    for t in _SQUEEZE_POSITIONING:
        assert reg.register_leaks(t), t
        assert reg.count_flow_words(t) >= 1, t


def test_fundamental_regime_squeeze_stays_clean():
    for t in _SQUEEZE_FUNDAMENTAL_CLEAN:
        assert reg.register_leaks(t) == [], t
        assert reg.count_flow_words(t) == 0, t


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# S7b R1 -- THE LICENSED-ADJECTIVE FENCE. Every case below is a sentence from, or a controlled
# variant of, the 2026-09-10 register census (scratchpad/recon_s8/REGISTER_CENSUS.md): 22 documents,
# 1,051 sentences, 11 charged, 11 of 11 STRUCK, and exactly ONE of the eleven a present-tense verdict.
# ══════════════════════════════════════════════════════════════════════════════════════════════════
from leviathan.graphrag import verify as _vf  # noqa: E402 -- the verdict producer under test


def _cot_calls(pct, n_before=24):
    """The banked s6b COT triple as SERVED CALLS ([N25] level, [N26] sigma, [N27] percentile), in
    `state.render.sb_call`'s own shape -- the records the writer's handles were numbered against."""
    q = {"table": "silver_cot", "metric": "mm_net", "commodity": "soybeans", "country": "US",
         "period": "2026-09-04", "asof": "2026-09-07"}

    def mk(v, u):
        return {"query": dict(q), "rows": [{"value": v, "unit": u}], "status": "ok"}
    return [{"query": {}, "rows": []}] * n_before + [mk(31584, "contracts"), mk(-0.8, "sigma"),
                                                    mk(pct, "percentile")]


_LIC = ("Managed-money positioning is crowded -- funds hold 31584 contracts [N25], -2.4 sigma on 156 "
        "weeks [N26], 4th percentile of its own record [N27].")
_WEAK = ("Managed-money positioning is crowded -- funds hold 31584 contracts [N25], -0.8 sigma on 156 "
         "weeks [N26], 28th percentile of its own record [N27].")
_BARE = "Positioning looks crowded here."


def test_licensed_and_bare_no_longer_score_identically():
    """THE CENSUS' ONE-LINE FINDING, pinned: at HEAD both sentences score val=0 flow=1 laneB=1 and BOTH
    are struck -- three [N] handles, a value in its own unit, a z on a named window and a 4th-percentile
    tail buy NOTHING. The verdict producer is what tells them apart."""
    assert _vf.bar_adjective_verdict(_LIC, _cot_calls(4)) == "licensed"
    assert _vf.bar_adjective_verdict(_BARE, []) == "unbound_adjective"
    assert _vf.bar_adjective_verdict(_WEAK, _cot_calls(28)) == "weak_adjective"
    # ...and at HEAD's own counters they stay indistinguishable, which is why the licence lives on the
    # STRIP DECISION and not on a counter.
    assert reg.count_flow_words(_LIC) == reg.count_flow_words(_BARE) == 1


def test_the_licence_is_asked_only_about_the_strip():
    """RO-7: `register_leaks` is the suggester's chip guard AND the eval metric, and the module fences
    Lane B and the exec lanes out of it so it CANNOT be relaxed. The licence must not move a counter."""
    def lic(s):
        return _vf.bar_adjective_verdict(s, _cot_calls(4))
    for t in (_LIC, _WEAK, _BARE):
        def read():
            return (len(reg.register_leaks(t)), len(reg.internal_leaks(t)), len(reg.market_leaks(t)),
                    len(reg.exec_leaks(t)), reg.count_valuation_words(t), reg.count_flow_words(t),
                    reg.lane_b_hits(t))
        before = read()
        reg.sanitize(t, bar_licence=lic)
        assert before == read(), t


def test_flag_off_is_head_byte_for_byte():
    """The whole dark contract in one assertion: with no licence threaded, every one of these sentences
    is struck exactly as it is at HEAD."""
    for t in (_LIC, _WEAK, _BARE):
        assert reg._is_banned_sentence(t) is True, t
        assert t not in reg.sanitize(t), t


def test_the_licence_never_strikes_any_of_the_four_verdicts():
    """The ruling is categorical -- never strike the sentence. `weak_adjective` and `unbound_adjective`
    are CHARGED, and their remedy is a correcting clause upstream, never a deletion here."""
    for t, calls in ((_LIC, _cot_calls(4)), (_WEAK, _cot_calls(28)), (_BARE, [])):
        def lic(s, c=calls):
            return _vf.bar_adjective_verdict(s, c)
        assert reg._is_banned_sentence(t, bar_licence=lic) is False, t
        assert t in reg.sanitize(t, bar_licence=lic), t


# The ELEVEN, verbatim from recon_s8/_charged.txt, with the speech act the census read on each.
_CENSUS_11 = (
    ("COND", "Palm reaches soybean oil through substitution: palm is the price-setting swing oil in the "
             "world edible-oil pool, so when palm tightens, price-sensitive buyers in India and China "
             "are pushed back toward soyoil, and when palm is cheap they switch away from it [E2][E4]."),
    ("DATED", "Dated substitution history in the corpus, for context and clearly historical: in April "
              "2020 sunflower oil became more expensive while palm, soy and rapeseed oil prices "
              "declined [E2];"),
    ("COND", "- **Feed-ration substitution (the actual linkage).** Corn's model carries a wheat-corn "
             "spread driver: when wheat is cheap relative to corn, rations swap wheat in and corn feed "
             "demand falls."),
    ("PRESENT", "A governed spread series is not yet served, so I will characterise the gap only in "
                "words: soyoil prints above palm, and soyoil is the more stretched of the two against "
                "its own five-year mean."),
    ("DATED", "- Textual conditions near the as-of are consistent with a palm supply-squeeze setup - El "
              "Nino (reported 2026-04-16) [E9], heat stress, an ending-stocks item, and the biennial "
              "low-yield cycle - but these are text-only receipts, not verified against levels;"),
    ("COND", "- **The gate is a relative price, not a level.** The model's wheat-corn spread driver is "
             "signed ambiguous on flat price precisely because it is a ration-economics switch: when "
             "wheat is cheap versus corn, rations swap toward wheat;"),
    ("DATED", "USDA attache reporting in December 2024 documented feeders cutting feed-wheat imports in "
              "favour of corn [E84], and in January 2024 that wheat was not expected to be "
              "price-competitive with corn in rations for the rest of MY2023/24 as corn prices fell "
              "[E92] - the corn-cheap leg."),
    ("DATED", "Against that, July 2025 attache reporting had Chinese feed demand for wheat rising unless "
              "corn prices dropped significantly [E81], and the June 2021 WASDE framed US wheat feed and "
              "residual use as rising IF wheat priced competitively with corn [E3] - the wheat-cheap "
              "leg."),
    ("NEG", "Positioning is not stretched either - funds held 31584 contracts [N25], -0.8 sigma on 156 "
            "weeks [N26], 28th percentile [N27] - which the row itself flags as history, not a cause;"),
    ("NEG", "That is history, not a cause the graph declares - and it means there is no crowded long to "
            "unwind, which removes one source of downside air pocket."),
    ("COND", "Several of those are exactly the drivers a supply squeeze would need, so their absence is "
             "a blind spot, not a benign reading."),
)


def test_the_eleven_census_sentences_verdicts():
    """MEASURED 2026-09-10 and pinned VERBATIM. Ten of the eleven are conditional/mechanism rules,
    receipted dated history, or explicit denials backed by their own rows; ONE is a present verdict, and
    it is one with no served spread series -- which is why the census' own remedy for it is a decline
    that keeps its honest first clause, not a deletion that takes the clause with it."""
    got = {}
    for act, s in _CENSUS_11:
        calls = _cot_calls(28) if "[N25]" in s else []
        v = _vf.bar_adjective_verdict(s, calls)
        got[v] = got.get(v, 0) + 1
        assert v == ("unbound_adjective" if act == "PRESENT" else "not_a_verdict"), (act, s[:60], v)
    assert got == {"not_a_verdict": 10, "unbound_adjective": 1}


def test_the_eleven_are_struck_at_head_and_none_are_struck_under_the_licence():
    """B-11: 11 of 11 STRUCK today -> 0 struck, with 2,302 characters and 11 bound handles (3 [N],
    8 [E]) kept over the 22-document corpus."""
    struck_off = struck_on = 0
    for _act, s in _CENSUS_11:
        calls = _cot_calls(28) if "[N25]" in s else []

        def lic(x, c=calls):
            return _vf.bar_adjective_verdict(x, c)
        struck_off += int(reg._is_banned_sentence(s))
        struck_on += int(reg._is_banned_sentence(s, bar_licence=lic))
    assert (struck_off, struck_on) == (11, 0)


def test_negation_is_clause_scoped_not_sentence_scoped():
    """THE MEASURED REASON: the census' ONE present verdict carries a `not` ninety characters and two
    clause boundaries before its adjective. A sentence-wide negation test would read that sentence as a
    denial and exempt the one sentence the fence exists for."""
    present = _CENSUS_11[3][1]
    denial = _CENSUS_11[8][1]
    assert _vf.bar_adjective_verdict(present, []) == "unbound_adjective"
    assert _vf.bar_adjective_verdict(denial, _cot_calls(28)) == "not_a_verdict"


def test_only_the_kept_column_survives_the_licence():
    """ROUND 4, WORDS ARE FREE (owner ruling 2026-09-15 16:30Z). The licence retires the valuation /
    flow-WORD strike; what it may never touch is the KEPT column, and each row below names the rule
    rather than the sentence -- A2 execution, the two structural class rules, the reversion idiom, and
    the two Lane-A members that name a FIGURE. `licence_kept_charge` is asked beside the strip so the
    two can never disagree about WHY a sentence is still struck."""
    def always(_s):
        return "licensed"
    for t, why in (("Positioning is crowded, so go long here.", "a2_execution"),
                   ("Take profits here; positioning is crowded.", "a2_execution"),
                   ("The premium is rich and should narrow from here.", "forecast_convergence"),
                   ("The spread is rich and that discount cannot last.", "forecast_persistence"),
                   ("The crush spread is rich and due for a correction.", "forecast_reversion"),
                   ("Positioning is crowded and the price target is 512.", "unbacked_figure_claim"),
                   ("Positioning is crowded and fair value is 430.", "unbacked_figure_claim")):
        assert reg._is_banned_sentence(t, bar_licence=always) is True, t
        assert reg.licence_kept_charge(t) == why, t
    # ...and the RETIRED column, which is the freedom the ruling returns: a flow noun the fence used to
    # delete for its words alone now ships, and the classification says nothing is left to charge.
    for t in ("Positioning is crowded and this is a pain trade.",
              "Positioning is crowded and one-sided positioning always unwinds."):
        assert reg._is_banned_sentence(t) is True, t                       # HEAD strikes it
        assert reg._is_banned_sentence(t, bar_licence=always) is False, t  # the ruling frees it
        assert reg.licence_kept_charge(t) == "", t


def test_the_strike_no_longer_asks_the_verdict_anything():
    """ROUND 4. Rounds 1-3 threaded a CALLABLE and asked it whether a figure backed the adjective; the
    owner's ruling retires the strike for the WORD, so the kwarg is read as a FLAG and the verdict has
    exactly one job left -- the correcting clause. Pinned on a sentence the verdict producer returns
    None for (it carries no bar adjective at all): HEAD strikes it for its flow words, and every
    licence, whatever it answers, frees it."""
    t = "This is one-sided positioning heading into the December expiry."
    assert _vf.bar_adjective_verdict(t, []) is None
    assert reg._is_banned_sentence(t) is True
    for lic in (lambda _s: None, lambda _s: "licensed", lambda _s: "unbound_adjective"):
        assert reg._is_banned_sentence(t, bar_licence=lic) is False, lic


def test_the_strip_never_calls_the_licence_at_all():
    """ROUND 4, and it is the cleanest statement of the ruling: a licence that RAISES when called cannot
    fail this strip, because the strip never calls it. The decision is the CLASSIFICATION's, and the
    callable is a flag -- which is also why no try/except is needed where one used to be."""
    def boom(_s):
        raise RuntimeError("licence exploded")
    assert reg._is_banned_sentence(_BARE, bar_licence=boom) is False
    assert reg._is_banned_sentence(_BARE) is True
    assert reg._is_banned_sentence("Positioning is crowded, so go long here.", bar_licence=boom) is True


def test_the_positioning_squeeze_licence_leaves_the_regime_vocabulary_alone():
    """RO-3, measured: the display registry humanises the convergence-regime ids INTO 'drought / supply /
    China demand / delivery / crush / feedstock / premium squeeze' prose, and `_FLOW_PHRASES` is written
    so a bare squeeze stem never reaches it. The licence inherits that scope by construction -- it is
    only ever ASKED about sentences the shipped fence already charged -- and this pins it."""
    def lic(s):
        return _vf.bar_adjective_verdict(s, [])
    ids = reg._regime_ids()
    assert len(ids) > 20, "the display registry served no regime ids -- this pin measures nothing"
    for rid in ids:
        probe = "The " + reg._regime_label(rid) + " held into the quarter [N1]."
        assert reg.sanitize(probe, bar_licence=lic) == reg.sanitize(probe), rid


def test_the_licence_is_idempotent():
    """RA-3: `sanitize` is declared idempotent, and a licence that changed on a second pass would make a
    re-render a different page."""
    def lic(s):
        return _vf.bar_adjective_verdict(s, _cot_calls(4))
    for t in (_LIC, _WEAK, _BARE, _CENSUS_11[3][1]):
        once = reg.sanitize(t, bar_licence=lic)
        assert reg.sanitize(once, bar_licence=lic) == once, t


def test_the_bars_come_from_the_shipped_registry_and_never_from_this_module():
    """RO-2: only the two families `state_conventions.yaml` already declares ship. Every PROPOSAL bar in
    the census -- overbought, oversold, and every invented absolute band -- is owed to the owner and
    shipped by nobody."""
    assert _vf._bar_bands("positioning") == (10.0, 90.0)
    assert _vf._bar_bands("level_decile") == (10.0, 90.0)
    assert set(w for w, _f, _s in _vf.BAR_ADJECTIVES) == {
        "crowded", "stretched", "vulnerable", "squeeze", "cheap", "rich", "expensive"}
    conv = _vf._bar_conventions()
    for fam, refs in _vf.BAR_FAMILY_REFS.items():
        for ref in refs:
            assert (conv.get(ref) or {}).get("kind") == "percentile_bands", ref
    for _w, fam, _side in _vf.BAR_ADJECTIVES:
        assert fam in _vf.BAR_FAMILY_REFS


def test_a_row_outside_the_family_licenses_nothing():
    """The licence joins on the SERVED CALL's own (table, metric), through the board's own roster. A
    percentile from a different family is not a bar for this word."""
    q = {"table": "silver_psd", "metric": "su_ratio", "commodity": "soybeans", "country": "US",
         "period": "2026", "asof": "2026-09-07"}
    calls = [{"query": q, "rows": [{"value": 4, "unit": "percentile"}], "status": "ok"}]
    assert _vf.bar_adjective_verdict("Positioning is crowded [N1].", calls) == "unbound_adjective"


def test_an_unreadable_registry_makes_every_bar_unresolvable_and_never_raises():
    """Fail-closed on the CHARGE and fail-open on the reader's page: with no bands, every present verdict
    is `unbound_adjective`, whose remedy is a decline clause and never a deletion."""
    assert _vf._bar_bands("positioning", {}) == ()
    assert _vf.bar_adjective_verdict(_LIC, _cot_calls(4), conventions={}) == "unbound_adjective"


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# S7b R2 -- THE DESK REGISTER. MEASURED 2026-09-11 over the NINE banked real-seat answers
# (scratchpad/lingo_leaks.py): 195 internal-vocabulary hits, 21.7 per answer, of which
# scratchpad/s7b/lingo_context.py classifies 20 as ordinary MARKET English a bare token count charges.
# ══════════════════════════════════════════════════════════════════════════════════════════════════
_DESK_INSTRUMENT = (
    "Reading the board at 2026-09-07, the loudest thing on ICE cocoa is West African weather.",
    "The graph carries this in the same direction as price at high confidence.",
    "Two loud rows have already spent their knowledge date.",
    "That is a driver-state read, not a live market read.",
    "The board flags these two as one series read under two names.",
    "The board carries no receipt for this leg.",
    "The series key resolves to the national card.",
)
# The four estate literals plus the market collisions the census names. Each is EXEMPT BY PHRASE and
# each carries the measured reason in `register.DESK_REGISTER_EXEMPT`.
_DESK_MARKET = (
    "The board price tape runs through 2026-09-04.",
    "It sits at the 17th percentile of its own record and past the line the desk convention calls tight.",
    "A wide board crush means processors bid for beans to capture oil-plus-meal value.",
    "Net read: the CBOT soybean board tilts modestly toward higher prices over the next two quarters.",
    "Board crush prints the identical reading under a second name.",
    "The row crops went in late across the eastern belt.",
    "Registered receipts at the delivery points fell again this week.",
    "By market convention the front month is quoted in cents per bushel.",
    "The ICE cocoa board settled higher on the day.",
)


def test_the_desk_lint_charges_the_instrument_and_not_the_market():
    for s in _DESK_INSTRUMENT:
        assert reg.count_desk_register(s) >= 1, s
    for s in _DESK_MARKET:
        assert reg.count_desk_register(s) == 0, (s, reg.desk_register_hits(s))


def test_the_desk_lint_reads_outside_the_citation_handles():
    """The ruling's own scope. A handle is an address the reader clicks, not prose."""
    s = "The record shows 118432 contracts [N25], -0.8 sigma [N26], 28th percentile [N27]."
    assert reg.count_desk_register(s) == 0


def test_driver_is_not_a_desk_register_token():
    """`register._JARGON_SUBS` REWRITES 'the node' INTO 'the driver' -- a lint charging the word would
    charge the estate's own repair, and the 2026-09-11 context census scored it 0 INSTRUMENT / 3 MARKET
    on all three occurrences in the nine answers."""
    assert all(n != "driver" for n, _p, _r in reg.DESK_REGISTER_TOKENS)
    assert reg.count_desk_register("The drought driver is price-supportive here.") == 0


def test_the_desk_lint_is_a_separate_population_from_internal_leaks():
    """DR-11: `internal_leaks` catches a BUG (a slug, a `conf=`) and is NEVER RELAXABLE; this catches
    well-formed English that names the instrument and has a CORRECTING remedy. Folding one into the
    other would make the chip guard relaxable by the back door."""
    for s in _DESK_INSTRUMENT:
        assert reg.internal_leaks(s) == [], s
        assert reg.register_leaks(s) == [], s
    assert reg.count_desk_register("The drought driver has conf=high per silver_ref=silver_psd.") == 0


def test_every_replacement_word_is_itself_register_clean():
    """A mandate that taught a fenced word would be the convention registry's own 2026-09-11 collision
    re-enacted in the prompt (yaml:15-21: revision 1 proposed `crowded` / `stretched` and they failed
    this file's own lint)."""
    for n, _p, repl in reg.DESK_REGISTER_TOKENS:
        assert not reg._LANE_B_ADJ.search(repl), n
        assert reg.count_flow_words(repl) == 0, n
        assert reg.count_valuation_words(repl) == 0, n
        assert reg.register_leaks(repl) == [], n


def test_the_offending_sentence_unit_matches_the_strip_unit():
    """The rewrite may touch OFFENDING SENTENCES and nothing else, and the unit is
    `register._SENT_ITER`'s -- the same split every other pass in this module uses."""
    text = "The board is loud here. The market rallied on the day. Two rows carry no knowledge date."
    sents = reg.desk_register_sentences(text)
    assert len(sents) == 2
    assert "The market rallied on the day." not in sents


def test_the_restructured_strip_decision_is_head_s_truth_table_exhaustively():
    """The licence needed ONE place to be asked, so `_is_banned_sentence`'s FENCED tail was restructured
    -- HEAD read `if LaneA: True` / `if persistence: True` / `return bool(LaneB)`. A restructure of a
    fence is the kind of change that is right by argument and wrong by one row, so it is proved rather
    than argued: HEAD's own expression is reconstructed here and both are run over every combination of
    three fragment positions drawn from a twelve-member vocabulary that realises each predicate --
    6,912 probes across both registers and both derivation states, ZERO divergences."""
    import itertools

    def head(sent, market_register=reg.FENCED, derivation_ok=False):
        outlook = (market_register == reg.OUTLOOK)
        if reg._EXEC_PHRASES.search(sent) or reg._exec_extra_hits(sent):
            return True
        if reg._REVERSION_PHRASES.search(sent):
            return True
        if (reg._SPREAD_NOUN.search(sent) and reg._CONVERGE_VERB.search(sent)
                and reg._FUTURITY.search(sent)):
            return True
        if not outlook:
            if reg._VALUATION_PHRASES.search(sent) or reg._FLOW_PHRASES.search(sent):
                return True
            if reg._PERSISTENCE.search(sent) and reg._PRICE_SPREAD_NOUN.search(sent):
                return True
            return bool(reg._lane_b_in_sentence(sent, reg._LANE_B_VAL_RX)
                        or reg._lane_b_in_sentence(sent, reg._LANE_B_FLOW_RX))
        if derivation_ok:
            return False
        if reg._CIT_HANDLE.search(sent) and not reg._deriv_output(sent):
            return False
        return bool(reg._level_tokens(sent))

    frag = ("", "price targets ", "crowded long ", "the spread is unsustainable ",
            "positioning looks crowded ", "prices ", "stocks ", "the premium should narrow ",
            "go long here ", "due for a correction ", "stocks fell 12 percent [N1] ", "settle 1450 ")
    probes = 0
    for combo in itertools.product(frag, repeat=3):
        sent = "".join(combo).strip() + "."
        for mr in (reg.FENCED, reg.OUTLOOK):
            for deriv in (False, True):
                probes += 1
                assert head(sent, mr, deriv) == reg._is_banned_sentence(
                    sent, market_register=mr, derivation_ok=deriv), (mr, deriv, sent)
    assert probes == 6912


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# S7b REVIEW FIXES (2026-09-11) -- the seven MAJORs the adversarial read measured, each pinned by the
# probe that reproduced it. Every one of these went RED before the fix and GREEN after.
# ══════════════════════════════════════════════════════════════════════════════════════════════════
# `state.render` is imported AT THE TOP with the rest: a mid-file import block is a ruff I001 the lane
# introduced (baseline 29de55eb carries none in this deck), and `_sb` wants the real producer anyway.


def _sb(**kw):
    return _rd.sb_call(period="2026-09", asof="2026-09-07", **kw)


def _pos(commodity, country, pct, kd="2026-09-05"):
    return _sb(table="silver_cot", metric="mm_net", commodity=commodity, country=country,
               value=pct, unit="percentile", knowledge_date=kd)


def test_major1_a_different_series_in_the_same_family_licenses_nothing():
    """REVIEW MAJOR 1. `_bar_ref_index` joins on (table, metric), and `state/render.py:703` emits ONE
    `unit='percentile'` call PER COMMODITY on `silver_cot/mm_net` -- so that join names a FAMILY of
    series, not a series. Measured: corn at the 3rd percentile as [N1] and cocoa at the 52nd as [N2] in
    one turn licensed "ICE cocoa managed-money positioning is crowded [N1]" off CORN's reading, while
    the same sentence citing cocoa's own row was corrected. `query.commodity` is on every board call and
    was read by nothing."""
    calls = [_pos("corn_cbot", "United States", 3), _pos("cocoa_ice", "United States", 52)]
    S = "ICE cocoa managed-money positioning is crowded [N%d]."
    assert _vf.bar_adjective_verdict(S % 1, calls) == "unbound_adjective"
    assert _vf.bar_adjective_verdict(S % 2, calls) == "weak_adjective"
    # ...and the row the sentence's OWN market cites still reaches its bar, both ways
    assert _vf.bar_adjective_verdict("CBOT corn managed-money positioning is crowded [N1].",
                                     calls) == "licensed"


def test_major1_the_scope_test_is_a_contradiction_test_not_an_attribution_test():
    """The rule refuses a row only when the sentence names a COMPETING series of this family and names
    NOTHING of the cited row's own. A comparison naming both keeps its licence -- the alternative (a
    positive attribution test) would refuse every sentence whose subject is set by its heading."""
    calls = [_pos("corn_cbot", "United States", 55), _pos("cocoa_ice", "United States", 4)]
    assert _vf.bar_adjective_verdict("Cocoa positioning is crowded [N2] while corn is not.",
                                     calls) == "licensed"
    # a turn carrying ONE series of the family has no competing scope, so nothing can be contradicted
    assert _vf.bar_adjective_verdict("ICE cocoa positioning is crowded [N1].",
                                     [_pos("cocoa_ice", "United States", 4)]) == "licensed"


def test_major1_the_country_dimension_is_asked_separately_from_the_commodity():
    """Two dimensions, asked SEPARATELY and not as one tuple: a wheat sentence naming Brazil while
    citing the United States row names its own COMMODITY correctly, so a single-tuple test would be
    satisfied by the commodity half and license the wrong country."""
    calls = [_pos("wheat_cbot", "United States", 95), _pos("wheat_cbot", "Brazil", 50)]
    assert _vf.bar_adjective_verdict("Brazil wheat positioning is crowded [N1].",
                                     calls) == "unbound_adjective"
    assert _vf.bar_adjective_verdict("CBOT wheat positioning is crowded [N1].", calls) == "licensed"


def test_major1_row_selection_is_scoped_in_time():
    """A call whose rows are [55th pct @2026-09-05, 3rd pct @2019-04-02] licensed `crowded` off the 2019
    row. The bar is a PRESENT verdict's bar, so only the call's newest knowledge date participates."""
    q = {"table": "silver_cot", "metric": "mm_net", "commodity": "cocoa_ice",
         "country": "United States", "period": "2026-09", "asof": "2026-09-05"}
    stale = {"query": dict(q), "status": "ok",
             "rows": [{"value": 55, "unit": "percentile", "knowledge_date": "2026-09-05"},
                      {"value": 3, "unit": "percentile", "knowledge_date": "2019-04-02"}]}
    fresh = {"query": dict(q), "status": "ok",
             "rows": [{"value": 3, "unit": "percentile", "knowledge_date": "2026-09-05"},
                      {"value": 55, "unit": "percentile", "knowledge_date": "2019-04-02"}]}
    S = "ICE cocoa managed-money positioning is crowded [N1]."
    assert _vf.bar_adjective_verdict(S, [stale]) == "weak_adjective"
    assert _vf.bar_adjective_verdict(S, [fresh]) == "licensed"
    # a call whose rows carry NO knowledge date at all is unchanged -- the board's own sb_call shape
    bare = {"query": dict(q), "rows": [{"value": 3, "unit": "percentile"}], "status": "ok"}
    assert _vf.bar_adjective_verdict(S, [bare]) == "licensed"


def test_major1_the_bar_memos_follow_the_resolved_config_path():
    """REVIEW MINOR. `evidence._hier` was RE-KEYED on the resolved config path for exactly this failure
    -- six unit files repoint `extract._CFG` at a tmp dir, and a memo keyed on a constant makes the
    repointing invisible in one direction and poisons the process with `{}` in the other."""
    import functools
    for fn in (_vf._bar_conventions, _vf._bar_ref_index):
        assert not isinstance(fn, functools._lru_cache_wrapper), fn
    assert _vf._bar_conventions()          # the real registry, read through the board's ONE loader
    assert _vf._bar_cfg_key() in _vf._BAR_CONV_CACHE


def test_major2_the_post_sanitize_invariant_is_named_rather_than_broken_in_silence():
    """REVIEW MAJOR 2. `_strip_banned_sentences`' docstring states `register_leaks(sanitize(x)) == []`.
    MEASURED on the 97-case corpus: licence OFF 0/97 violations, licence ON 2/97 -- which is the
    instrument working, not a hole. The counters still take NO licence (the chip guard rests on it), so
    the subtraction lives in a SECOND, declared producer that the eval gate and the metric read."""
    kept = "A crowded long here unwinds sharply if the catalyst pauses."
    on = reg.sanitize(kept, bar_licence=lambda _s: "unbound_adjective")
    assert kept in on
    assert reg.register_leaks(on)                       # the raw counter is UNCHANGED and still charges
    assert reg.register_leaks_excluding_bar(on) == []   # ...and the declared population reads zero
    assert reg.register_leaks(reg.sanitize(kept)) == []             # flag-off: HEAD's invariant holds


def test_major2_the_second_producer_relaxes_nothing_the_fence_decides_above_the_licence():
    """Everything `_is_banned_sentence` settles ABOVE its licence clause is still charged: A2 execution,
    both structural class rules, a hard Lane-A phrase beside the adjective, and all of internal_leaks."""
    for probe in ("Positioning is crowded, so go long here.",
                  "The premium is rich and should narrow from here.",
                  "The spread is rich and that discount cannot last.",
                  "Positioning is crowded and fair value is 430.",
                  "The node fired with conf=high."):
        assert reg.register_leaks_excluding_bar(probe), probe
    # ROUND 4: the subtraction follows the RULING. A retired WORD is not a leak of the population the
    # eval gate reads on a lit turn -- while `register_leaks` itself, the chip guard and the metric, is
    # numerically unchanged on both arms.
    assert reg.register_leaks_excluding_bar("This is a pain trade.") == []
    assert reg.register_leaks("This is a pain trade.")
    clean = "Corn stocks fell in June."
    assert reg.register_leaks_excluding_bar(clean) == reg.register_leaks(clean)
    import inspect
    assert "bar_licence" not in str(inspect.signature(reg.register_leaks_excluding_bar))


def test_major2_the_two_bar_adjective_tables_agree():
    """`register._BAR_ADJ_WORDS_RX` is a COPY of `verify.BAR_ADJECTIVES`' words (this module imports
    nothing at module scope), so the agreement is graded rather than trusted."""
    words = sorted({w for w, _f, _s in _vf.BAR_ADJECTIVES})
    found = sorted({("squeeze" if w.startswith("squeez") else w)
                    for w in reg._BAR_ADJ_WORDS_RX.findall(" ".join(words))})
    assert words == found


def test_major7_a_named_institution_board_is_not_the_instrument():
    """REVIEW MAJOR 7. The commodity exemption required the crop token ADJACENT to `board`, so "Ghana
    Cocoa Board" and "Canadian Wheat Board" were exempt while "Malaysian Palm Oil Board" was CHARGED --
    in prose, in an abbreviation gloss and in a source line. MPOB is a served source family here:
    `silver_mpob` is a board table and `mpob_ending_stocks` is one of the four level-decile refs the
    LICENCE itself reads."""
    for p in ("The Malaysian Palm Oil Board publishes monthly.",
              "MPOB (Malaysian Palm Oil Board) is the source.",
              "Source: Malaysian Palm Oil Board - Monthly Palm Oil Statistics, 2026-09-10.",
              "The Ghana Cocoa Board sets the farmgate price.",
              "The Canadian Wheat Board was wound up.",
              "The Chicago Board of Trade lists the contract.",
              "The USDA Agricultural Marketing Service Livestock Mandatory Reporting receipt of bids."):
        assert reg.desk_register_hits(p) == [], p
    assert "mpob_ending_stocks" in _vf.BAR_FAMILY_REFS["level_decile"]


def test_major7_the_instrument_s_own_population_is_still_charged():
    """The exemption is CASE-DISCRIMINATED: the instrument's own leak is always lower case."""
    for p in ("Reading the board at 2026-09-07, the loudest row is weather.",
              "The graph carries this at a high knowledge date.",
              "The state read on this node is thin.",
              "The board is two-sided."):
        assert reg.desk_register_hits(p), p


def test_the_span_producer_and_the_hit_producer_cannot_disagree():
    """`desk_register_spans` is what `desk_register_hits` is built on, so the count and the span name the
    same words -- and `desk_register_masked` blanks exactly those, same length, same offsets."""
    t = "Reading the board at 2026-09-07, the loudest row on CBOT soybeans is the crush [N1]."
    spans = reg.desk_register_spans(t)
    assert len(spans) == len(reg.desk_register_hits(t))
    masked = reg.desk_register_masked(t)
    assert len(masked) == len(reg._strip_mermaid(t))
    assert "board" not in masked and "loudest" not in masked
    assert "soybeans" in masked and "crush" in masked


def test_the_offending_sentence_producer_states_its_own_segmentation_honestly():
    """REVIEW MINOR: the docstring claimed the rewrite shares this function's unit. The BOUNDARIES agree
    (both `[.!?;]\\s+`); the CHUNKS do not -- `_SENT_ITER` keeps the terminator, `_SENT_KEEP` moves it
    into the delimiter -- and the rewrite splices by index, so it uses `_SENT_KEEP` and never calls
    this. Measured unequal here so the claim can never drift back."""
    t = "The board is loud here. The market rallied."
    assert reg._SENT_ITER.split(t) != [x for x in reg._SENT_KEEP.split(t) if x][::2]
    assert "_SENT_KEEP" in reg.desk_register_sentences.__doc__


# ══ S7b R1 ROUND-3 ═══════════════════════════════════════════════════════════════════════════════════
def _bar_lic(*calls):
    from leviathan.graphrag import verify as _vf
    return lambda s: _vf.bar_adjective_verdict(s, list(calls))


#: The eight sentences the round-3 verifier measured from STRUCK-at-HEAD to SHIPPED under the licence.
#: Every one is convicted at HEAD by the BAR ADJECTIVE ALONE -- the A2 detector is silent on all eight.
RO8_PROBES = (
    "The spread screens cheap, so buy the front month.",
    "The basis screens rich, so sell it.",
    "Positioning is crowded, so lift offers here.",
    "Positioning is crowded -- add on dips.",
    "The board crush screens cheap, so own it here.",
    "Palm screens cheap against soyoil, so switch the barrel.",
    "Managed money is crowded long, so lift the offer and add on any dip.",
    "CBOT corn managed-money positioning is crowded at the 3rd percentile [N1], "
    "so buy the front month and sell the deferred.",
)


def test_round3_the_probe_reaches_the_clause_it_grades():
    """ROUND 2's LESSON, APPLIED TO ROUND 3's OWN DEFECT. `config_check`'s most-permissive-licence probe
    was 'Positioning is crowded, so go long here.', which `_EXEC_PHRASES` convicts BEFORE the licence
    clause runs -- so clause (d) passed vacuously while eight sentences of the same class shipped. Each
    probe below is asserted to be (a) invisible to the A2 detector and (b) struck at HEAD, so a green
    row below can only mean the licence's own backstop refused it."""
    for s in RO8_PROBES:
        assert not reg._EXEC_PHRASES.search(s), s
        assert not reg._exec_extra_hits(s), s
        assert reg._is_banned_sentence(s) is True, s          # HEAD strikes it -- through the adjective


def test_round4_the_a2_hole_is_named_and_is_heads_own():
    """THE HONEST PIN, and it replaces two rounds of frame lists. Every RO-8 probe carries an
    instruction the A2 detector CANNOT SEE ("so buy the front month", "so own it here") beside a bar
    adjective HEAD strikes it for, so retiring the WORD strike lets the instruction ship. The owner's
    ruling names that hole as PRE-EXISTING rather than closing it inside the licence -- rounds 3 and 4
    both tried a clause-edge frame list and the review measured each failing in BOTH directions at once
    (advice still shipping AND honest readings deleted).

    WHAT IS GRADED HERE IS THAT THE HOLE IS HEAD'S. For every probe, the IDENTICAL instruction hung off
    a sentence carrying no retired word ships at HEAD today, with no flag set anywhere -- so the licence
    exposes a hole rather than opening one. Closing it is a widening of the A2 DETECTOR on both arms,
    which is a blast-radius decision and not a licence's to take."""
    tails = (", so buy the front month.", ", so sell it.", ", so lift offers here.",
             " -- add on dips.", ", so own it here.", ", so switch the barrel.",
             ", so lift the offer and add on any dip.",
             ", so buy the front month and sell the deferred.")
    assert len(tails) == len(RO8_PROBES)
    for s in RO8_PROBES:
        assert reg._is_banned_sentence(s) is True, s                      # HEAD strikes it -- the WORD
        assert reg.exec_leaks(s) == [] and reg.count_exec_words(s) == 0, s  # ...never the instruction
        assert reg.sanitize(s, bar_licence=lambda _x: "licensed").strip() == s.strip(), s
    for tail in tails:
        # THE SAME INSTRUCTION, ON A SENTENCE CARRYING NO RETIRED WORD: HEAD ships it today, with no
        # flag set anywhere. That is what makes the hole PRE-EXISTING rather than the licence's.
        probe = "Rain is forecast in Mato Grosso" + tail
        assert reg.sanitize(probe).strip() == probe.strip(), probe
        assert reg.exec_leaks(probe) == [], probe
    # and A2 PROPER is untouched on both arms, which is the half the ruling keeps
    a2 = "Positioning is crowded, so go long here."
    assert reg.sanitize(a2) == "" and reg.sanitize(a2, bar_licence=lambda _s: "licensed") == ""


def test_round4_the_correcting_clause_survives_the_strip_that_follows_it():
    """The remedy appends BEFORE the body-wide sanitize runs, so a fence that read its own repair as a
    charge would delete it. One clause survives the round-4 ruling and it is pinned here beside the
    honest desk prose it sits in."""
    from leviathan.graphrag import answer as _an
    clause = _an._BAR_BAND_CLAUSE.format(pct="42", lo="10", hi="90")
    for s in ("Positioning is crowded here.",
              "A crowded long here unwinds sharply if the catalyst pauses.",
              "Managed money is crowded long, so funds add on dips.",
              "The basis screens rich, so exporters cut bids.",
              "The spread screens cheap, so the crush margin widens.",
              "Positioning is crowded [N1]" + clause + "."):
        assert s.strip(" .") in reg.sanitize(s, bar_licence=_bar_lic()), s
    assert reg.register_leaks(clause) == [] and reg.desk_register_hits(clause) == []


def test_round3_the_guard_is_licence_only_and_the_flag_off_arm_is_untouched():
    """The closure may NOT widen `_EXEC_PHRASES` / `_EXEC_EXTRA`: those fire on every turn and W5's
    blast-radius line is 'every non-outlook answer byte-identical'. So the guard is read by the licence
    and by nothing else -- `exec_leaks`, the raw counter and the strip with no licence all read exactly
    what they read at HEAD."""
    import inspect
    for s in RO8_PROBES:
        assert reg.exec_leaks(s) == [], s                     # A2 REPORTING is unmoved
        assert reg.count_exec_words(s) == 0, s
        assert reg.sanitize(s) == reg.sanitize(s, bar_licence=None), s
    assert "bar_licence" not in str(inspect.signature(reg.exec_leaks))


def test_round4_the_classification_names_the_column_and_the_strip_agrees():
    """ONE PRODUCER. `licence_kept_charge` answers "why is this still struck with the flag on", the
    strip reads it, `bar_shaped_spans` reads it, and `config_check` and this deck probe it directly --
    the round-2 lesson, one turn on: a pin that infers a predicate from a strip decision grades a guard
    that may never have run."""
    assert reg.licence_kept_charge("Positioning is crowded here.") == ""     # Lane B alone: a word
    assert reg.licence_kept_charge("The spread screens cheap here.") == ""   # a Lane-A bar shape
    assert reg.licence_kept_charge("This is a pain trade.") == ""            # a Lane-A flow noun
    assert reg.licence_kept_charge("The weather turned dry.") == ""          # no charge at all
    assert reg.licence_kept_charge("Positioning is crowded, so go long here.") == "a2_execution"
    assert reg.licence_kept_charge("Fair value screens near 268.") == "unbacked_figure_claim"
    for s in ("Positioning is crowded here.", "The spread screens cheap here.",
              "This is a pain trade.", "Positioning is crowded, so go long here.",
              "Fair value screens near 268."):
        assert reg._is_banned_sentence(s, bar_licence=lambda _x: "licensed") \
            is bool(reg.licence_kept_charge(s)), s


def test_round3_an_exemption_is_an_argument_about_a_word():
    """REVIEW MINOR. The exemptions were applied as pure SPAN CONTAINMENT across all eleven tokens, so a
    row written for `board` silently dropped every `loud` / `row` / `convention` charge inside its own
    window. Each row now names the token it exempts and only that one."""
    for pat, names, why in reg.DESK_REGISTER_EXEMPT:
        assert names and isinstance(names, tuple), pat
        assert all(n in {t for t, _p, _r in reg.DESK_REGISTER_TOKENS} for n in names), (pat, names)
        assert isinstance(why, str) and why
    assert reg.check_desk_exempt_table() == []
    cme = "On the CME, the loudest thing on the board is the crush."
    matif = "Against the MATIF curve, the loudest row on the board is drought."
    assert [n for n, _c in reg.desk_register_hits(cme)] == ["loud"]
    assert sorted(n for n, _c in reg.desk_register_hits(matif)) == ["loud", "row"]
    # ...and the exemption still does its own job: `board` is not charged in either
    assert "board" not in {n for n, _c in reg.desk_register_hits(cme)}
    assert "board" not in {n for n, _c in reg.desk_register_hits(matif)}
    # the named-institution and desk-English rows are unmoved
    for s in ("The Malaysian Palm Oil Board publishes monthly.",
              "The Ghana Cocoa Board sets the farmgate price.",
              "The Chicago Board of Trade lists the contract.",
              "Row crops went in late.", "Registered receipts fell again."):
        assert reg.desk_register_hits(s) == [], s


def test_round3_the_series_scope_is_not_vacuous_on_a_one_market_turn():
    """REVIEW MAJOR. The competing vocabulary was the TURN's other calls OF THIS FAMILY, so on the modal
    single-commodity board `foreign` was empty and the contradiction test could not fire at all -- a
    cross-market positioning verdict backed by another market's decile shipped `licensed`, which appends
    NO clause, which is worse than HEAD (it struck it). The second half of the vocabulary is standing:
    `display._contracts_hier()` for the commodity, `geo_lexicon` for the country."""
    from leviathan.graphrag import verify as _vf
    only = _pos("corn_cbot", "United States", 3)
    for s in ("ICE cocoa managed-money positioning is crowded [N1].",
              "Malaysian palm oil positioning is crowded [N1].",
              "South African white maize positioning is crowded [N1]."):
        assert _vf.bar_adjective_verdict(s, [only]) == "unbound_adjective", s
    assert _vf.bar_adjective_verdict("Brazil wheat positioning is crowded [N1].",
                                     [_pos("wheat_cbot", "United States", 95)]) == "unbound_adjective"
    # ...and it is STILL a contradiction test: the row's own market, and a sentence naming none at all
    for s in ("CBOT corn managed-money positioning is crowded at the 3rd percentile [N1].",
              "Managed money positioning is crowded [N1].",
              "Positioning is crowded [N1] and the weather is dry."):
        assert _vf.bar_adjective_verdict(s, [only]) == "licensed", s


def test_round3_the_standing_roster_never_refuses_a_market_naming_itself():
    """Every contract the estate declares, probed as the row's OWN market: a sentence naming that
    market's own node keeps its licence. PHRASES ONLY -- a token split would mint 'oil', 'crude', 'red'
    and 'white' as competing markets and refuse honest prose."""
    from leviathan.graphrag import verify as _vf
    vocab = _vf._bar_contract_vocab()
    assert len(vocab) >= 20
    for _slug, words in vocab:
        assert all(w == w.lower() and w.strip() == w and w for w in words)
    assert not any("ice" in words for _s, words in vocab)     # the one homonym exchange code, by name
    for slug, words in vocab:
        node = sorted(words, key=len)[0]
        s = "%s positioning is crowded [N1]." % node.title()
        assert _vf.bar_adjective_verdict(s, [_pos(slug, "United States", 3)]) == "licensed", s


def test_round3_the_geography_half_is_the_estates_one_lexicon():
    """The country dimension asks `geo_lexicon` -- decoys, demonyms, the not-a-scope follower blacklist
    and the aggregate sentinel all come with it, so 'the Brazilian real' mints nothing and a sentence
    reading 'global' stands the dimension down (the lexicon's own L1 rule: a container is not a
    disagreement with its contents)."""
    from leviathan.graphrag import verify as _vf
    us = _pos("corn_cbot", "United States", 3)
    assert _vf.bar_adjective_verdict("Brazilian positioning is crowded [N1].", [us]) \
        == "unbound_adjective"
    for s in ("Positioning quoted in the Brazilian real is crowded [N1].",
              "Global positioning is crowded [N1] while Brazil is not.",
              "American positioning is crowded [N1]."):
        assert _vf.bar_adjective_verdict(s, [us]) == "licensed", s
    # AND THE GENEROSITY THAT USED TO SIT HERE IS GONE (round-6 review MINOR 1). The row's own display
    # spelling read as a DENIAL, because `_BAR_NEGATOR` carried a case-blind `un\w+ed` and "United"
    # matches it: the sentence came back `not_a_verdict`, which cost the COUNTER (no clause, and never
    # counted in `adjectives_unbacked`) on one of the estate's commonest surfaces. It is a present
    # verdict now, and it is LICENSED, because the row it cites clears the bar -- which is also why the
    # probe above no longer has to say "American".
    assert _vf.bar_adjective_verdict("United States positioning is crowded [N1].", [us]) == "licensed"
    assert _vf.bar_adjective_verdict("United States corn positioning is crowded [N1].",
                                     [us]) == "licensed"


def test_round3_the_bar_memo_is_keyed_on_the_config_it_parsed():
    """REVIEW MINOR. `_bar_ref_index` rebound `key` inside its own loop, so the store wrote the index
    under the LAST (table, metric) tuple and the config key was never in the cache: the memo was one-way
    -- only the FAILURE branch could pin -- and 25 verdicts drove 25 `board_map()` reads."""
    from leviathan.graphrag import verify as _vf
    _vf._BAR_REF_CACHE.clear()
    idx = _vf._bar_ref_index()
    assert list(_vf._BAR_REF_CACHE) == [_vf._bar_cfg_key()]
    assert _vf._BAR_REF_CACHE[_vf._bar_cfg_key()] is idx
    assert _vf._bar_ref_index() is idx                       # ...and the second call is the memo's


def test_round3_the_eval_column_and_the_coverage_number_are_absent_rather_than_zero():
    """REVIEW MINORs, both of the 'absent is never zero' family. `register_leaks_ex_bar` was computed
    unconditionally, so the artifact's KEY SET moved on the dark arm; and the coverage block gated on
    the FLAG rather than on the lint's own census, so `GRAPHRAG_VERIFY=off` (a documented rollback,
    where the lint never runs) stamped `register_lingo_hits = 0` for an instrument that never ran."""
    import inspect

    from leviathan.graphrag import answer as _an
    from leviathan.graphrag import eval as _ev
    src = inspect.getsource(_ev)
    assert '"register_leaks_ex_bar":' in src and 'get("bar_adjectives") else {}' in src
    assert '"register_leaks_ex_bar_total"' in src and 'if any("register_leaks_ex_bar" in p' in src
    body = inspect.getsource(_an._answer_l2)
    assert "if _dreg is not None:" in body
    assert 'if _desk_register_on():\n            _d = _dreg' not in body


# ══ ROUND 4 (2026-09-15) -- THE PINS ARE SWEEPS. ═════════════════════════════════════════════════════
# The round-3 pins graded the seven sentences that produced the round-3 fix, and the round-3 review then
# found 76 advisory escapes and seven market escapes that a green deck could not see. So every pin below
# GENERATES its population: the advisory shapes as lead x tail x subject x modal x verb, the series scope
# as the estate's whole declared roster, and the freshness bound as a day offset either side of the
# card's own promise. The estate's standing law, read from the review side
# (feedback_threat_model_before_any_gate_or_fence.md).
#: THE ROUND-3 ADVICE CUT AND ITS FOUR PINS ARE REMOVED HERE (owner ruling 2026-09-15 16:30Z). They
#: graded `register.bar_advice_cut` / `bar_advice_corrected` / `bar_advice_clause` and the five
#: clause-edge frames behind them -- 112 generated advisory sentences, a 3,034-shape subject x modal x
#: verb product, and a false-positive census. The producer is gone from `register.py`, so the pins go
#: with it rather than being left to grade a symbol that no longer exists: two review rounds measured
#: the frames failing in BOTH directions at once (28 of 192 generated instructions still shipping; 12
#: of 13 honest nominal sentences DELETED, a cited reading among them), and the smoke then found two
#: more false-positive classes in 149 sentences of prose nobody in the lane had seen. What replaces
#: them is `test_round4_the_a2_hole_is_named_and_is_heads_own`, which proves the hole is HEAD's rather
#: than promising that a list closes it.


def _r4_licence(pct=3.0, commodity="corn_cbot", country="United States", kd="2026-09-05"):
    call = _pos(commodity, country, pct, kd=kd)
    return (lambda s, _c=[call]: _vf.bar_adjective_verdict(s, _c)), call


def test_round4_every_declared_market_is_foreign_to_a_corn_row():
    """REVIEW MAJOR 1, swept. The standing roster was PHRASES-ONLY, so seven bare desk nouns -- soybean,
    wheat, sugar, coffee, palm, soymeal, cattle -- licensed `crowded` off CORN's figure. The vocabulary
    now reads the estate's whole commodity hierarchy (31 contracts + 51 commodities), and the pin names
    every one of them rather than the seven that were measured."""
    _lic, call = _r4_licence()
    mine = {"corn", "corn cbot", "campinas corn reference bmf", "french maize matif",
            "white maize", "yellow maize", "maize", "south african white maize jse",
            "south african yellow maize jse"}
    leaked = []
    for ident, words in _vf._bar_market_vocab():
        if ident in mine:
            continue
        word = sorted(words, key=lambda w: (-len(w), w))[0]
        if _vf.bar_adjective_verdict(f"{word.title()} positioning is crowded [N1].",
                                     [call]) == "licensed":
            leaked.append(word)
    assert leaked == [], leaked
    # the seven the review measured, by name, in the reader's own spelling
    for bare in ("Soybean", "Wheat", "Sugar", "Coffee", "Palm", "Soymeal", "Cattle", "Hog",
                 "Rapeseed", "Cotton", "Barley", "Sorghum", "Dairy", "Ethanol"):
        assert _vf.bar_adjective_verdict(f"{bare} positioning is crowded [N1].",
                                         [call]) == "unbound_adjective", bare
    # ...and the row's OWN market keeps its licence, in every surface the hierarchy declares for it
    for own in ("CBOT corn managed-money positioning is crowded [N1].",
                "Corn positioning is crowded [N1].",
                "Maize positioning is crowded [N1].",
                "Managed money positioning is crowded [N1]."):
        assert _vf.bar_adjective_verdict(own, [call]) == "licensed", own


def test_round4_an_exchange_code_is_not_the_rows_market():
    """The sweep's own find: `mine` carried the row's whole slug token split, CBOT included, and the
    contradiction test's second half asks whether the sentence names anything of the row's own -- so
    every CBOT neighbour corn has (soybeans, soybean meal, soybean oil, SRW wheat, rough rice) licensed
    off corn's row by naming the VENUE. A venue is not a market."""
    _lic, call = _r4_licence()
    for s in ("Soybeans CBOT positioning is crowded [N1].",
              "CBOT soybean meal positioning is crowded [N1].",
              "CBOT rough rice positioning is crowded [N1].",
              "CBOT soft red winter wheat positioning is crowded [N1]."):
        assert _vf.bar_adjective_verdict(s, [call]) == "unbound_adjective", s
    assert "cbot" in _vf._bar_exchange_words()


def test_round4_a_row_with_no_country_cannot_claim_one():
    """REVIEW MAJOR 2. `state/render.py:671` emits `"country": st.key.country or None`, and both halves
    of the geo test ran only `if own[dim]` -- so a country-less row stood the whole dimension down and
    "Brazil positioning is crowded [N1]" licensed off a United States figure."""
    call = _pos("corn_cbot", None, 3.0)
    for s in ("Brazil positioning is crowded [N1].",
              "Argentine corn positioning is crowded [N1].",
              "Ukrainian positioning is crowded [N1].",
              "Positioning in Malaysia is crowded [N1]."):
        assert _vf.bar_adjective_verdict(s, [call]) == "unbound_adjective", s
    assert _vf.bar_adjective_verdict("Corn positioning is crowded [N1].", [call]) == "licensed"
    assert _vf.bar_adjective_verdict("Global positioning is crowded [N1].", [call]) == "licensed"


def test_round4_the_licensing_row_is_bounded_in_absolute_time():
    """REVIEW MAJOR 3. `_bar_current_rows` scoped the row against its own siblings; a call whose NEWEST
    row is itself ancient was not bounded at all, so a 2011 percentile licensed a present-tense verdict
    in 2026. The bound is the card's own promise -- `registry.lag_days_for` + the card's cadence + a
    stated margin -- and it is swept either side rather than probed at one date."""
    import datetime as dt
    bound = _vf._bar_freshness_bound(_pos("corn_cbot", "United States", 3.0))
    assert 7 <= bound <= 60, bound
    for off, want in ((0, "licensed"), (bound, "licensed"), (bound + 1, "weak_adjective"),
                      (bound + 400, "weak_adjective"), (5000, "weak_adjective")):
        kd = (dt.date(2026, 9, 7) - dt.timedelta(days=off)).isoformat()
        rep = _vf.bar_adjective_report("Corn positioning is crowded [N1].",
                                       [_pos("corn_cbot", "United States", 3.0, kd=kd)])
        assert rep["verdict"] == want, (off, rep)
        assert (rep["stale"] == kd) if want == "weak_adjective" else (rep["stale"] == ""), (off, rep)
    # AN UNMEASURABLE BOUND IS SILENCE, NEVER A FABRICATED STALENESS: no knowledge date on the row, or
    # no `asof` on the turn, and the row is simply not charged for age.
    nokd = {"query": {"table": "silver_cot", "metric": "mm_net", "commodity": "corn_cbot",
                      "country": "united_states", "period": "latest", "asof": "2026-09-07"},
            "rows": [{"value": 3.0, "unit": "percentile"}], "status": "ok"}
    assert _vf.bar_adjective_verdict("Corn positioning is crowded [N1].", [nokd]) == "licensed"
    noasof = {"query": {"table": "silver_cot", "metric": "mm_net", "commodity": "corn_cbot",
                        "country": "united_states", "period": "latest"},
              "rows": [{"value": 3.0, "unit": "percentile", "knowledge_date": "2011-01-04"}],
              "status": "ok"}
    assert _vf.bar_adjective_verdict("Corn positioning is crowded [N1].", [noasof]) == "licensed"


def test_round4_a_comparison_resolves_its_adjective_against_its_subject():
    """REVIEW MAJOR 4. `_bar_percentiles` OR-ed over every handle the sentence carried, so a comparison
    naming BOTH markets satisfied the contradiction test for both rows and the first handle that
    cleared the bar won -- measured: "Cocoa positioning is crowded [N2] while corn is quiet [N1]."
    resolved LICENSED off CORN's 3rd percentile while cocoa's own row read 52."""
    corn = _pos("corn_cbot", "United States", 3.0)
    coco = _pos("cocoa", "Ghana", 52.0)
    assert _vf.bar_adjective_verdict("Cocoa positioning is crowded [N2] while corn is quiet [N1].",
                                     [corn, coco]) == "weak_adjective"
    assert _vf.bar_adjective_verdict("Corn positioning is crowded [N1] while cocoa is quiet [N2].",
                                     [corn, coco]) == "licensed"
    assert _vf._bar_subject_market("Cocoa positioning is crowded [N2] while corn is quiet [N1].",
                                   "positioning") == "cocoa"
    # a ONE-market sentence is not a comparison, however many times it names its market
    assert _vf._bar_subject_market("Corn positioning is crowded and corn length is crowded [N1].",
                                   "positioning") is None
    # ROUND 4: A TWO-VENUE COMPARISON IS ONE, and it FAILS CLOSED. The venue half was excluded from the
    # count ("a venue is not a market"), so a comparison naming only the exchanges resolved to NO
    # subject and the percentile test went back to OR-ing every handle -- measured, "ICE positioning is
    # crowded [N2] while CBOT is quiet [N1]." read CORN's 3rd percentile and licensed. A venue is still
    # not a market, so no call can claim it: the verdict is unbound and the ruling appends nothing.
    for s in ("ICE positioning is crowded [N2] while CBOT is quiet [N1].",
              "The ICE book is crowded [N2] and the CBOT book is quiet [N1].",
              "Positioning on ICE is crowded [N2] and on CBOT it is quiet [N1]."):
        assert _vf.bar_adjective_verdict(s, [corn, coco]) == "unbound_adjective", s
    assert _vf._bar_subject_market("CBOT corn managed-money positioning is crowded [N1].",
                                   "positioning") == "corn"
    # ...and the homonym venue is admitted in UPPER CASE only: "Ice damage" is weather.
    assert _vf.bar_adjective_verdict("Ice damage leaves positioning crowded [N1].",
                                     [corn]) == "licensed"


def test_round4_any_charge_but_the_adjective_keeps_heads_verdict():
    """THE OWNER'S RULING, STATED AS A TEST: "the licence may change the verdict ONLY when the adjective
    charge is the SOLE charge". Driven with the MOST PERMISSIVE licence there can be -- one that
    licenses every sentence it is shown -- so nothing here depends on the verdict producer at all. The
    A2 row is the one difference the ruling itself requires: the clause is CUT and the READING survives,
    which is not the A2 charge being relieved but the charge being REMOVED from the page."""
    always = (lambda _s: "licensed")
    for why, s in (("the persistence class rule", "The spread is rich and that discount cannot last."),
                   ("forward convergence", "The premium is crowded and the spread will converge by "
                                           "March."),
                   ("an unbacked price target", "Positioning is crowded, so the price target is 512."),
                   ("a fair-value claim", "Positioning is crowded and fair value is 430."),
                   ("A2 execution", "Positioning is crowded, so go long here.")):
        assert reg.sanitize(s) == reg.sanitize(s, bar_licence=always) == "", why
    # ...and the two rows that MOVED with the owner's ruling, stated rather than deleted: a flow NOUN
    # and the one-sided-positioning idiom are words, and words are free.
    for s in ("Positioning is crowded and this is a pain trade.",
              "Positioning is crowded and one-sided positioning is the tell."):
        assert reg.sanitize(s) == ""                                   # HEAD deletes the sentence
        assert reg.sanitize(s, bar_licence=always).strip() == s.strip()  # the ruling ships it whole
# == ROUND 5 (2026-09-15) -- THE CORRECTION'S SCOPE. ==================================================
# THE CLAUSE IS THIS LANE'S ONE PRINTED FIGURE, so a clause bound to the wrong subject is the estate's
# "only printed figures must be backed" class and not a cosmetic one. Round 4 closed the two-market and
# the two-VENUE comparisons; the round-4 review then measured three residual ways a corn row's
# percentile printed itself beside a sentence about something else. Every pin below drives the SHIPPED
# CLAUSE PRODUCER (`answer._bind_bar_adjectives`) rather than the verdict string, because the verdict
# was never the thing that reached the page.


def _bound(sent, calls):
    """(did the shipped producer append a clause, the sentence as it would ship)."""
    from leviathan.graphrag import answer as _an
    st = {"tldr": sent, "mechanism": ""}
    _an._bind_bar_adjectives(st, list(calls))
    return (st["tldr"] != sent), st["tldr"]


def test_round5_one_foreign_venue_named_alone_appends_nothing():
    """ROUND-4 REVIEW MAJOR 2 (a). `_bar_subject_market` asks its question only when TWO distinct
    markets are named, so a SINGLE venue was never tested as a subject at all -- and `matif` lands in
    `mine` rather than `foreign` because `french_maize_matif` canonicalises onto node `corn`, while
    `ice` is dropped from the market words by name as a homonym. Measured: "Positioning is crowded on
    MATIF [N1]." and "...on ICE [N1]." both printed corn_cbot's 42 inside the desk's own band."""
    corn = _pos("corn_cbot", "United States", 42.0)
    for s in ("Positioning is crowded on MATIF [N1].",
              "Positioning is crowded on ICE [N1].",
              "Positioning is crowded on the DCE [N1].",
              "Positioning is crowded on ZCE [N1].",
              "Positioning is crowded on CBOT versus MATIF [N1].",
              "Positioning is crowded on the CME and on the DCE [N1]."):
        got, out = _bound(s, [corn])
        assert not got, (s, out)
    # THE ROW'S OWN VENUE IS NOT FOREIGN, and the correction still lands on it.
    got, out = _bound("Positioning is crowded on CBOT [N1].", [corn])
    assert got and "the served figure is 42" in out
    # THE VOCABULARY IS THE ESTATE'S OWN DECLARED EXCHANGE CODES, never a hand list -- and it carries
    # the homonym, which is exactly why the market half had to drop it.
    assert {"cbot", "matif", "ice", "dce", "zce", "kcbt", "mgex"} <= set(_vf._bar_exchange_words())
    assert set(_vf._bar_call_venues(corn)) == {"cbot", "cbots"}
    assert not _vf._bar_call_venues({"query": {}})
    # ...and a venue USED AS A VENUE is admitted whether it is shouted or merely placed (ruling (a)),
    # while the weather word is still weather.
    assert _vf._bar_foreign_venue("Positioning is crowded on ice [N1].", corn)
    assert not _vf._bar_foreign_venue("Ice damage leaves positioning crowded [N1].", corn)
    got, _out = _bound("Ice damage leaves positioning crowded [N1].", [corn])
    assert got
    # ALONE IS LOAD-BEARING. A venue standing NEXT TO ITS OWN MARKET is that market's address and
    # not a subject claim, so this half stands down and the PLACEMENT rule (c) refuses instead --
    # which is what keeps `config_check`'s own register_seam probe ("ICE cocoa ... while CBOT corn
    # ...") resolving against its subject while still appending nothing.
    assert not _vf._bar_foreign_venue("Corn positioning is crowded on MATIF [N1].", corn)
    got, out = _bound("Corn positioning is crowded on MATIF [N1].", [corn])
    assert not got, out


def test_round5_a_place_the_estate_cannot_resolve_fails_closed():
    """ROUND-4 REVIEW MAJOR 2 (b), RE-FOUNDED IN ROUND 6 ON THE HARVESTER'S OWN FILE.

    `configs/graphrag/regions.yaml` is GIT-IGNORED (.gitignore:75) and REGENERATED by
    `scripts/harvest_geographies.py`, so round 5's 43 hand-added alias surfaces made this deck green as
    a property of ONE WORKING TREE: a fresh clone, a CI checkout or a re-harvest turned it into a
    mystery failure (round-6 review MINOR 2, measured: 5 assertions red). The overlay is reverted and
    every assertion below is now a property of the file the harvester WRITES -- the fail-closed
    direction on a surface nothing can name, the positive direction on surfaces the harvested map
    already resolves."""
    corn = _pos("corn_cbot", "United States", 42.0)
    # (i) A FOREIGN REGION THE HARVESTED MAP RESOLVES is refused by the COUNTRY half
    for r in ("Mato Grosso", "Parana", "Sao Paulo", "Bahia", "Sabah", "Johor", "Uttar Pradesh",
              "Buenos Aires"):
        named, _agg = _vf._bar_geo(r)
        assert named, r
        got, out = _bound("Positioning in %s is crowded [N1]." % r, [corn])
        assert not got, (r, out)
    # (i-bis) ...and a region the harvester hides behind its COMMODITY PREFIX resolves to nothing and
    #         fails the sentence CLOSED, which is the SAFE outcome and the one the docstring now
    #         claims: `br_soy_rio_grande_do_sul` under commodity `soybeans_cbot` keeps its `soy`, so
    #         the region is reachable only as 'soy rio grande do sul', which no reader writes. Widening
    #         the surfaces is `scripts/harvest_geographies.py`'s job -- an OWNER DOCKET, never a hand
    #         edit of a git-ignored overlay.
    for r in ("Rio Grande do Sul", "Heilongjiang", "Jilin", "Inner Mongolia", "Liaoning"):
        got, out = _bound("Positioning in %s is crowded [N1]." % r, [corn])
        assert not got, (r, out)
    # (ii) a US region the harvested map DOES resolve still earns the correction -- the guard refuses a
    #      subject the estate cannot name, never a placed one it can
    for r in ("Iowa", "Illinois", "Nebraska", "Kansas"):
        named, _agg = _vf._bar_geo(r)
        assert named == frozenset({"united_states"}), r
        got, out = _bound("Positioning in %s is crowded [N1]." % r, [corn])
        assert got and "the served figure is 42" in out, r
    # (iii) AN UNRESOLVED capitalised phrase after a locative fails the sentence CLOSED
    for s in ("Positioning is crowded on Euronext [N1].",
              "Positioning is crowded on BMD [N1].",
              "Positioning in Zhengzhou is crowded [N1]."):
        got, out = _bound(s, [corn])
        assert not got, (s, out)
    # (iv) ...and the things a locative governs that are NOT places do not fail it closed: the calendar,
    #      and the non-geography classes the estate declares in its own entity vocabulary.
    assert _vf._bar_place_resolves("March") and _vf._bar_place_resolves("Q4")
    assert _vf._bar_place_resolves("El Nino") and _vf._bar_place_resolves("La Nina")
    assert _vf._bar_place_resolves("USDA") and _vf._bar_place_resolves("CBOT")
    assert not _vf._bar_place_resolves("Euronext")
    # (v) the rule is scoped to the ADJECTIVE'S OWN CLAUSE, so a place named in a later clause is left
    #     to the geo dimension that owns it (and that dimension still refuses a foreign one).
    got, _out = _bound("Positioning is crowded [N1], and the Euronext board is quiet.", [corn])
    assert got


def test_round5_a_two_market_sentence_places_its_clause_or_appends_none():
    """ROUND-4 REVIEW MAJOR 2 (c). `inside` took the FIRST contradicting row in written order, and the
    clause is appended at the SENTENCE END -- so "Cocoa positioning is crowded [N2] and corn
    positioning is crowded [N1]." printed COCOA's 52 at the end of a sentence whose last clause is
    about corn, whose own row reads 42. A reader binds an appended clause to the clause it is appended
    to, so that clause must carry the adjective, name this row's market, and name no other."""
    corn = _pos("corn_cbot", "United States", 42.0)
    coco = _pos("cocoa", "Ghana", 52.0)
    for s in ("Cocoa positioning is crowded [N2] and corn positioning is crowded [N1].",
              "Positioning is crowded in cocoa [N2] and in corn [N1].",
              "Corn and cocoa positioning are both crowded [N1].",
              "Corn positioning is crowded [N1] while cocoa is quiet [N2]."):
        got, out = _bound(s, [corn, coco])
        assert not got, (s, out)
    # THE CLAUSE THE READER CAN BIND still ships: the LAST clause carries the adjective, names corn and
    # names nothing else, so the figure beside it is corn's own.
    got, out = _bound("Cocoa is quiet [N2], while corn positioning is crowded [N1].", [corn, coco])
    assert got and "the served figure is 42" in out
    # ...and the placement is a property of the SENTENCE, asked of the row: one market named once or
    # five times is not a comparison and nothing about it changes.
    assert _vf._bar_clause_bound("Corn positioning is crowded [N1].", "crowded",
                                 frozenset({"corn"}), frozenset())
    assert not _vf._bar_clause_bound("Cocoa positioning is crowded [N2] and corn positioning is "
                                     "crowded [N1].", "crowded", frozenset({"corn"}), frozenset())
    got, out = _bound("Corn positioning is crowded and corn length is crowded [N1].", [corn])
    assert got and "the served figure is 42" in out


def test_round5_the_honest_correction_is_unmoved_by_all_three_guards():
    """THE OTHER HALF OF EVERY FENCE. Three guards that only ever REFUSE would be free to refuse
    everything, so the population the correction exists for is pinned beside them."""
    corn = _pos("corn_cbot", "United States", 42.0)
    for s in ("Corn positioning is crowded [N1].",
              "US corn positioning is crowded [N1].",
              "Managed-money length in corn is crowded [N1].",
              "Maize positioning is crowded [N1].",
              "CBOT corn managed-money positioning is crowded [N1].",
              "Positioning in Iowa is crowded [N1].",
              "Positioning is crowded in the United States [N1]."):
        got, out = _bound(s, [corn])
        assert got, s
        assert "the served figure is 42, inside the 10 to 90 band" in out, s
    # AND NOTHING HERE DELETES: every sentence above ships whole, clause or no clause.
    for s in ("Positioning is crowded on MATIF [N1].",
              "Positioning in Rio Grande do Sul is crowded [N1].",
              "Cocoa positioning is crowded [N2] and corn positioning is crowded [N1]."):
        _got, out = _bound(s, [corn])
        assert out == s
def test_round5_a_rows_own_venue_survives_an_undeclared_contract_slug():
    """THE REGRESSION THE DECK CAUGHT, PINNED. `_bar_call_venues` first keyed the `contracts` dict, so
    a call scoped on a slug the hierarchy does not DECLARE -- `cocoa_ice` and `wheat_cbot`, both of
    which the round-3/4 pins above drive, against declarations `cocoa` and `soft_red_winter_wheat_cbot`
    -- resolved to NO venue at all and read its own exchange as foreign: four green pins went red in
    one run. Reading the row's market through `_bar_call_canons` instead fixed cocoa and broke wheat,
    because `_bar_market_rx` assigns one canon per word and 'wheat' belongs to `french wheat`. The
    match is on the scope's own WORDS, and both shapes are pinned here so neither can come back."""
    for slug, venue in (("cocoa_ice", "ice"), ("wheat_cbot", "cbot"),
                        ("corn_cbot", "cbot"), ("soybeans_cbot", "cbot")):
        call = _pos(slug, "United States", 42.0)
        assert venue in _vf._bar_call_venues(call), slug
        assert not _vf._bar_foreign_venue("Positioning is crowded on %s [N1]." % venue.upper(), call)
    # ...and the DECLARED slug keeps exactly one venue, which is what makes (a) able to refuse at all
    assert set(_vf._bar_call_venues(_pos("corn_cbot", "United States", 42.0))) == {"cbot", "cbots"}
    assert _vf._bar_foreign_venue("Positioning is crowded on MATIF [N1].",
                                  _pos("corn_cbot", "United States", 42.0))


# == ROUND 6 (2026-09-15) -- THE SUBJECT SLOT, THE NEGATOR, AND THE OVERLAY. ======================
# Ruling (b) was written to the PREPOSITION, and the writer's other option is the SUBJECT: the same
# unresolved place refused the clause as an adjunct and TOOK it as the sentence's subject, so a US
# CBOT percentile printed beside "Dalian positioning is crowded". Every pin below drives the SHIPPED
# CLAUSE PRODUCER, and none of them depends on a git-ignored config overlay.


def test_round6_an_unnameable_subject_appends_nothing():
    """ROUND-6 REVIEW MAJOR. Measured on the round-5 tree, corn_cbot / united_states @ 42nd percentile:
    "Positioning in Dalian is crowded [N1]." appended nothing (correct) while "Dalian positioning is
    crowded [N1]." appended the US board's own 42 -- 12 of 20 probed surfaces did it on the harvester's
    own file, five of them ordinary desk vocabulary in this estate's prose (Black Sea, Midwest, Pampas,
    Santos, Rotterdam). The same predicate is read at the subject."""
    corn = _pos("corn_cbot", "United States", 42.0)
    # (i) THE FAIL-CLOSED DIRECTION, proved on a surface NO config can name -- so this assertion is
    #     true of the repo and not of a machine -- and on the estate's own measured residual.
    for s in ("Zzyzx positioning is crowded [N1].",
              "Positioning in Zzyzx is crowded [N1].",
              "Dalian positioning is crowded [N1].",
              "Black Sea basis is crowded [N1].",
              "Midwest net length is crowded [N1].",
              "Zhengzhou open interest is crowded [N1].",
              "Rotterdam board crush is rich [N1].",
              "Pampas spread is rich [N1].",
              "Dalian's positioning is crowded [N1].",
              "Dalian Positioning is crowded [N1]."):
        got, out = _bound(s, [corn])
        assert not got, (s, out)
        assert out == s                      # ...and NOTHING is struck: the sentence ships whole
    # (ii) THE ROW'S OWN COUNTRY AND ITS OWN REGIONS KEEP THE CORRECTION
    for s in ("United States positioning is crowded [N1].",
              "Iowa positioning is crowded [N1].",
              "Illinois net length is crowded [N1].",
              "Corn positioning is crowded [N1].",
              "Maize positioning is crowded [N1].",
              "CBOT positioning is crowded [N1]."):
        got, out = _bound(s, [corn])
        assert got and "the served figure is 42" in out, s
    # (iii) A DESK QUALIFIER IS NOT A SUBJECT CLAIM, and the vocabulary that says so is the numbers
    #       registry's own metric labels for the four tables the bar families read. This half is
    #       load-bearing: without it the guard refused the estate's OWN flagship licensed sentence
    #       (`_LIC` above) and turned `licensed` into a CHARGE.
    assert _vf.bar_adjective_verdict(_LIC, _cot_calls(4)) == "licensed"
    for s in ("Managed-money positioning is crowded [N1].",
              "Managed money length is crowded [N1].",
              "Reporting-fund positioning is crowded [N1].",
              "Managed-money length in corn is crowded [N1].",
              "Net length is crowded [N1].",
              "Open interest is crowded [N1].",
              "The positioning is crowded [N1].",
              "Positioning is crowded [N1]."):
        got, out = _bound(s, [corn])
        assert got and "the served figure is 42" in out, s
    assert {"managed", "money", "net", "open", "interest", "board", "crush",
            "spread"} <= set(_vf._bar_desk_words())
    assert _vf._bar_desk_subject("Reporting-fund") and not _vf._bar_desk_subject("Dalian")
    # ...and a head that IS the desk noun is never a subject claim either ("Board crush is rich" is a
    #    LEVEL_DECILE reading, so it is asked of the matcher rather than of a positioning row).
    for s in ("Board crush is rich [N1].", "Spread is rich [N1].", "Length is crowded [N1].",
              "Net length is crowded [N1].", "Open interest is crowded [N1]."):
        assert not _vf._bar_subject_place(s), s
    # (iv) ADJACENCY AND ALONE, the two bounds the rule is built on. A market word between the phrase
    #      and the desk noun is not read here ('US' is a NAMED RESIDUAL of `_bar_place_resolves`), and
    #      a place standing beside its own MARKET is that market's address -- round 5's own words for
    #      the venue half -- so the contradiction and placement rules decide those sentences.
    for s in ("US corn positioning is crowded [N1].",
              "CBOT corn managed-money positioning is crowded [N1]."):
        got, out = _bound(s, [corn])
        assert got and "the served figure is 42" in out, s
    assert _vf._bar_subject_place("Dalian positioning is crowded [N1].") == "Dalian"
    assert not _vf._bar_subject_place("Dalian corn positioning is crowded [N1].")
    assert not _vf._bar_subject_place("Positioning is crowded [N1].")
    # (v) and the rule is scoped to the ADJECTIVE'S OWN CLAUSE, exactly as the locative half is
    got, _out = _bound("Positioning is crowded [N1], while the Dalian board is quiet.", [corn])
    assert got


def test_round6_the_negator_must_be_a_real_negator():
    r"""ROUND-6 REVIEW MINOR 1. `_BAR_NEGATOR`'s `un\w+ed` alternation was read CASE-BLIND, so it
    matched the word 'United': "United States corn positioning is crowded [N1]." was exempted as a
    DENIAL, which appended no clause AND kept the sentence out of `adjectives_unbacked` -- the
    generosity cost the COUNTER rather than the page. A negation must now be a real negator."""
    corn = _pos("corn_cbot", "United States", 42.0)
    # (i) the proper nouns that are not denials in any spelling
    for s in ("United States corn positioning is crowded [N1].",
              "United States positioning is crowded [N1]."):
        assert _vf.bar_adjective_verdict(s, [corn]) == "weak_adjective", s
        got, out = _bound(s, [corn])
        assert got and "the served figure is 42" in out, s
    for w in ("United", "Unified", "Unimproved", "united", "unified", "unimproved"):
        assert not _vf._BAR_NEGATOR.search("%s States positioning is crowded" % w), w
    # (ii) ...and the denials still deny, shouted, capitalised or lower-case
    for w in ("unchanged", "Unchanged", "UNCHANGED", "unmoved", "unsupported", "unbacked",
              "unconfirmed", "unhedged", "unfilled", "not", "never", "no", "without", "hardly"):
        assert _vf._BAR_NEGATOR.search("the reading is %s" % w), w
    assert _vf._BAR_NEGATOR.search("positioning isn't crowded")
    for s in ("Corn positioning is not crowded [N1].",
              "Corn positioning is unchanged rather than crowded [N1]."):
        assert _vf.bar_adjective_verdict(s, [corn]) == "not_a_verdict", s
        got, out = _bound(s, [corn])
        assert not got and out == s, s
    # (iii) MEASURED AND STATED: 'unwound' is NOT matched by this regex and was not matched at HEAD
    #       either -- it does not end in `ed`. Pinned so the next reader does not "restore" a denial
    #       the estate never had.
    assert not _vf._BAR_NEGATOR.search("the long is unwound")


def test_round6_the_pins_do_not_depend_on_a_gitignored_overlay():
    """ROUND-6 REVIEW MINOR 2. `configs/graphrag/regions.yaml` is git-ignored (.gitignore:75) and
    REGENERATED by `scripts/harvest_geographies.py`, so a pin that needs a hand-added alias is green on
    one machine and red on a fresh clone. The overlay is reverted; this states the PROPERTY the deck
    rests on instead of the contents of an untracked file."""
    corn = _pos("corn_cbot", "United States", 42.0)
    # (i) THE FAIL-CLOSED DIRECTION NEEDS NO CONFIG AT ALL: a surface nothing can name is refused in
    #     BOTH slots, whatever the overlay says.
    assert not _vf._bar_place_resolves("Zzyzx")
    assert _vf._bar_unresolved_place("Positioning in Zzyzx is crowded [N1].") == "Zzyzx"
    assert _vf._bar_subject_place("Zzyzx positioning is crowded [N1].") == "Zzyzx"
    for s in ("Positioning in Zzyzx is crowded [N1].", "Zzyzx positioning is crowded [N1]."):
        got, out = _bound(s, [corn])
        assert not got and out == s, s
    # (ii) THE POSITIVE DIRECTION USES SURFACES THE HARVESTER'S OWN FILE CARRIES -- measured on it,
    #      not on an overlay: `harvest_geographies.harvest()` emits `Ia_Iowa`-style keys whose aliases
    #      carry the bare state name for these four.
    for r in ("Iowa", "Illinois", "Nebraska", "Kansas"):
        assert _vf._bar_region_country().get(r.lower()) or _vf._bar_geo(r)[0], r
        got, out = _bound("Positioning in %s is crowded [N1]." % r, [corn])
        assert got, r
    # (iii) and the map is READ, never guessed: an unreadable file leaves the sub-national half empty
    #       rather than inventing a country (the memo is keyed on the resolved config path).
    assert isinstance(_vf._bar_region_country(), dict)
    #     (keyed on the config it PARSED, never on a constant -- and asked as a membership rather
    #     than an identity, because six unit files repoint `extract._CFG` in the same process)
    assert _vf._bar_cfg_key() in _vf._BAR_RGN_CACHE


# -- round-6 close-out (orchestrator's hand): the "alone" bound is gone -------------------------------
def test_round6_closeout_no_alone_bound():
    """A foreign subject followed by the row's own market one preposition later is STILL a foreign
    subject: the subject half may not stand down because the clause names a market. The desk qualifier
    the old bound was written for is exempt through the registry producer, not through the bound."""
    from leviathan.graphrag import verify as _vf6
    assert _vf6._bar_subject_place("Dalian positioning in corn is crowded [N1].")
    assert _vf6._bar_subject_place("Black Sea positioning in corn is crowded [N1].")
    assert _vf6._bar_subject_place("Zhengzhou open interest in corn is crowded [N1].")
    assert _vf6._bar_subject_place("Managed-money length in corn is crowded [N1].") == ""
    assert _vf6._bar_subject_place("Positioning is crowded [N1].") == ""
    assert _vf6._bar_subject_place("Net length is crowded [N1].") == ""
