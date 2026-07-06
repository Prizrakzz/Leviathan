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
    clean = ("Soybeans read bullish into 2021: the drought driver is active, confirmed by the 2021-07 WASDE "
             "cut to Brazilian output. The price response turns convex once ending stocks fall below the buffer, "
             "a classic tail-risk regime. A strong dollar is a bearish offset. Stocks-to-use fell 5-10%.")
    assert reg.register_leaks(clean) == []                            # register-approved phrasing trips nothing


def test_mermaid_signs_are_not_prose_leaks():
    md = ('The frost is bullish for arabica.\n\n```mermaid\nflowchart LR\n frost["frost (+)"] --> price\n```\n')
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
        assert "high confidence" in clean and "bullish" in clean and "bearish" in clean and "(mixed)" in clean
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
        assert "drought squeeze (bullish)" in clean and "supply glut (bearish)" in clean
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
