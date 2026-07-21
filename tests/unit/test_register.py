"""Output-register linter — deterministic, no spend.

Guards that internal representation (raw slugs, `conf=`, a bare `(+)`, graph jargon) is caught when it leaks
into reader prose, and — just as important — that a clean researcher-register answer trips NOTHING (false
positives would make the eval metric noise).
"""
from __future__ import annotations

from leviathan.graphrag import evidence as ev
from leviathan.graphrag import register as reg


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
