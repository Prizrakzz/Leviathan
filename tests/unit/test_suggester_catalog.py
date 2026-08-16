"""6.8 grounded suggester — data-scoped catalog + convexity house-style prompt + answerable-gate.
Hermetic: seeds the warm convergence matrix in _STATE, injects the Haiku call, no AWS / no LLM
(the suggester's news surface was deleted in E1b). Flag-gated: GRAPHRAG_SUGGEST_CATALOG default
off -> no catalog, and since D-SG S2 that means no chips at all rather than a base prompt."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from leviathan.graphrag import api_models as M
from leviathan.graphrag import register as reg
from leviathan.graphrag import server as sv
from leviathan.graphrag import store as st


@pytest.fixture(autouse=True)
def _clean_register_caches():
    """register._slugs()/_display_map() are module-level lru_caches keyed off the hierarchy; an earlier
    suite test that patches evidence._hier (empty/fake) poisons them to ()/{} and lru_cache never clears
    between tests -> sanitize() then stops humanizing slugs and a raw `raw_sugar` survives into the prose.
    Rebuild from the real hierarchy for every test here, and don't leak the state forward either."""
    reg._slugs.cache_clear(); reg._display_map.cache_clear()
    yield
    reg._slugs.cache_clear(); reg._display_map.cache_clear()


# Real contract/regime/driver ids (from the recon) so the display registry humanizes them.
ROWS = [
    {"contract": "arabica_coffee", "regimes": [
        {"name": "bullish_supply_squeeze", "direction": "+", "matched": ["frost", "tenderable_collapse"],
         "threshold": 4, "fired": False, "n_active": 2, "proximity": 0.5}]},
    {"contract": "raw_sugar", "regimes": [
        {"name": "ethanol_diversion_regime", "direction": "+", "matched": ["crude_oil", "sugar_ethanol_parity"],
         "threshold": 2, "fired": True, "n_active": 2, "proximity": 1.0}]},
    {"contract": "corn_cbot", "regimes": [
        {"name": "bearish_glut", "direction": "-", "matched": ["ending_stocks"],
         "threshold": 3, "fired": False, "n_active": 1, "proximity": 0.333}]},
]


def _warm(monkeypatch, rows=ROWS):
    monkeypatch.setitem(sv._STATE, "conv_warm",
                        (time.time(), ("2026-07-06", "gv1"),
                         {"asof": "2026-07-06", "graph_version": "gv1", "rows": rows}))


# ── scope ─────────────────────────────────────────────────────────────────────────────────────────────
def test_suggest_scope_collects_and_dedups():
    scope = sv._suggest_scope(M.SuggestRequest(contracts=["arabica_coffee"]),
                              {"markets": ["coffee", "sugar"], "regions": ["Brazil"]})
    assert "coffee" in scope and "sugar" in scope and "brazil" in scope and "arabica coffee" in scope


# ── catalog build ───────────────────────────────────────────────────────────────────────────────────
def test_catalog_off_by_default(monkeypatch):
    _warm(monkeypatch)
    monkeypatch.delenv("GRAPHRAG_SUGGEST_CATALOG", raising=False)
    assert sv._suggest_catalog(["coffee"]) is None                     # flag off -> no catalog, no chips


def test_catalog_cold_matrix_is_none(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_SUGGEST_CATALOG", "on")
    monkeypatch.delitem(sv._STATE, "conv_warm", raising=False)
    assert sv._suggest_catalog(["coffee"]) is None                     # cold -> never compute live


def test_catalog_global_sorted_by_proximity(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_SUGGEST_CATALOG", "on")
    _warm(monkeypatch)
    g = sv._suggest_catalog([])
    assert g["contracts"] == ["arabica_coffee", "corn_cbot", "raw_sugar"]
    assert [c["contract"] for c in g["near"]] == ["raw_sugar", "arabica_coffee", "corn_cbot"]  # 1.0, 0.5, 0.33


def test_catalog_scoped(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_SUGGEST_CATALOG", "on")
    _warm(monkeypatch)
    s = sv._suggest_catalog(["sugar", "coffee"])                        # >=2 matches -> scoped pool
    got = {c["contract"] for c in s["near"]}
    assert got == {"raw_sugar", "arabica_coffee"} and "corn_cbot" not in got
    one = sv._suggest_catalog(["coffee"])                              # 1 match (<2) -> falls back to global
    assert any(c["contract"] == "arabica_coffee" for c in one["near"])
    assert any(c["contract"] == "raw_sugar" for c in one["near"])


# ── catalog rendering: register-clean + drivers de-underscored ───────────────────────────────────────
def test_catalog_text_register_clean(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_SUGGEST_CATALOG", "on")
    _warm(monkeypatch)
    txt = sv._suggest_catalog_text(sv._suggest_catalog([]))
    assert reg.register_leaks(txt) == []                               # sanitize() humanizes slugs + regime ids
    assert "crude oil" in txt and "sugar ethanol parity" in txt        # drivers de-underscored
    assert "ending stocks" in txt.lower()                              # answerable metrics line
    assert "raw_sugar" not in txt and "bullish_supply_squeeze" not in txt  # no raw ids survive


# ── answerable-gate denylist ─────────────────────────────────────────────────────────────────────────
def test_answerable_deny_matches_out_of_domain():
    assert sv._SUGGEST_DENY.search("How much diesel inventory buffer does Europe have?")
    assert sv._SUGGEST_DENY.search("Is crude oil storage drawing at Cushing?")
    assert sv._SUGGEST_DENY.search("Gold vs the dollar this week?")
    # inflected forms the trailing-\b regex used to miss (review finding #1)
    assert sv._SUGGEST_DENY.search("Is aluminium inventory drawing down at LME warehouses?")
    assert sv._SUGGEST_DENY.search("How large is the gasoline inventory overhang in PADD 1?")
    assert sv._SUGGEST_DENY.search("How many diesel inventories are left in ARA?")
    assert sv._SUGGEST_DENY.search("Are equities pricing in the ag cycle?")
    assert sv._SUGGEST_DENY.search("Is the treasury curve steepening?")
    assert sv._SUGGEST_DENY.search("Is cryptocurrency risk-on for commodities?")


def test_answerable_deny_keeps_covered_energy_and_ag():
    # covered drivers (biodiesel/renewable-diesel demand, crude as a price) must NOT be dropped
    assert not sv._SUGGEST_DENY.search("Is the soybean crush-rally regime arming as RIN bids firm?")
    assert not sv._SUGGEST_DENY.search("Brent firm -- sugar ethanol-diversion arming vs the cane crush?")
    assert not sv._SUGGEST_DENY.search("How thin is arabica's certified-stock buffer vs the export pace?")
    assert not sv._SUGGEST_DENY.search("Does the B40 mandate divert palm toward the diversion regime?")


# ── route: grounded vs base ──────────────────────────────────────────────────────────────────────────
def _client(monkeypatch):
    monkeypatch.setitem(sv._STATE, "store", st.InMemoryStore())
    return TestClient(sv.app)


def test_route_grounded_uses_catalog_and_drops_out_of_domain(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_SUGGEST", "on")
    monkeypatch.setenv("GRAPHRAG_SUGGEST_CATALOG", "on")
    _warm(monkeypatch)
    captured: dict = {}

    def fake_call(p):
        captured["prompt"] = p
        return ('["Is arabica squeeze arming as certified stocks fall?",'
                ' "How much European diesel inventory buffer is left?"]')

    monkeypatch.setitem(sv._STATE, "suggest_call", fake_call)
    r = _client(monkeypatch).post("/v1/suggest", json={"contracts": ["arabica_coffee"]})
    assert r.status_code == 200
    out = r.json()["suggestions"]
    assert "answerable-only" in captured["prompt"] and "Regimes closest to tipping" in captured["prompt"]
    assert any("arabica" in s.lower() for s in out)                    # kept
    assert not any("diesel" in s.lower() for s in out)                 # answerable-gate dropped it


def test_route_grounded_returns_chips_without_news(monkeypatch):
    # E1b guard: the grounded PROD-default path yields non-empty suggestions with ZERO news/headline
    # injection -- no "Today's headlines" block, no news fetch, no news _STATE keys
    monkeypatch.setenv("GRAPHRAG_SUGGEST", "on")
    monkeypatch.setenv("GRAPHRAG_SUGGEST_CATALOG", "on")
    _warm(monkeypatch)

    def boom(terms):
        raise AssertionError("news gather must never fire from the suggester")

    from leviathan.graphrag.news import fetch as nf
    monkeypatch.setattr(nf, "gather", boom)
    captured: dict = {}

    def fake_call(p):
        captured["prompt"] = p
        return '["Is arabica squeeze arming as certified stocks fall?"]'

    monkeypatch.setitem(sv._STATE, "suggest_call", fake_call)
    r = _client(monkeypatch).post("/v1/suggest", json={"contracts": ["arabica_coffee"]})
    assert r.status_code == 200
    assert r.json()["suggestions"] == ["Is arabica squeeze arming as certified stocks fall?"]
    assert "Today's headlines" not in captured["prompt"]               # the injection block is gone
    assert not any(k.startswith("suggest_news") for k in sv._STATE)    # no news state written


# ── RV-v2 cross-commodity pairs allowlist + positive answerable-gate ─────────────────────────────────
def _allow_soy_palm(monkeypatch):
    """Advertise one realizable material pair (soy oil <-> palm) in the catalog."""
    monkeypatch.setattr(sv, "_suggest_pairs",
                        lambda: [{"id": "veg_oil_soy_palm",
                                  "legs": ["soybean_oil_cbot", "malaysian_crude_palm_oil_cme"],
                                  "complex_name": "veg_oil", "shared_event": "palm_export_ban"}])


def _fake_xc(monkeypatch):
    """A stand-in is_cross_commodity_explicit: a chip that names two commodities is 'framed'. Keyed on the
    presence of a cross phrasing so single-commodity chips read False."""
    import types as _t
    fake = _t.ModuleType("leviathan.graphrag.intent")

    def is_cross_commodity_explicit(q: str):
        ql = q.lower()
        framed = ("->" in ql or "does that do to" in ql or " vs " in ql or "impact on" in ql)
        return (framed, None)
    fake.is_cross_commodity_explicit = is_cross_commodity_explicit
    monkeypatch.setitem(__import__("sys").modules, "leviathan.graphrag.intent", fake)


def test_catalog_advertises_only_realizable_pairs(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_SUGGEST_CATALOG", "on")
    monkeypatch.setenv("GRAPHRAG_REROUTE_V2", "on")                     # pairs surface ONLY when the flag is on
    _warm(monkeypatch)
    _allow_soy_palm(monkeypatch)
    txt = sv._suggest_catalog_text(sv._suggest_catalog([]))
    assert "Cross-commodity cascades you MAY ask about" in txt
    assert "soybean oil <-> palm oil" in txt                           # _leg_word strips exchange/venue tokens


def test_xc_gate_keeps_allowlisted_pair_drops_non_allowlisted(monkeypatch):
    _fake_xc(monkeypatch)
    cat = {"pairs": [{"id": "veg_oil_soy_palm",
                      "legs": ["soybean_oil_cbot", "malaysian_crude_palm_oil_cme"]}]}
    chips = [
        "How thin is arabica's certified-stock buffer as the export pace lifts?",  # single-commodity (not framed): kept
        "palm export ban -- what does that do to soybean oil?",              # framed, allowlisted pair: kept
        "palm export ban -- what does that do to sunflower oil?",            # framed, NON-allowlisted pair: dropped
    ]
    out = sv._xc_chip_gate(chips, cat)
    assert "soybean oil" in " ".join(out)
    assert not any("sunflower" in s for s in out)                          # the non-realizable pair chip dropped
    assert any("arabica" in s for s in out)                                # single-commodity chip untouched


def test_xc_gate_drops_all_framed_when_no_realizable_pairs(monkeypatch):
    _fake_xc(monkeypatch)
    out = sv._xc_chip_gate(["palm ban -- impact on soybean oil?"], {"pairs": []})
    assert out == []                                                       # no allowlist -> every cross-ask drops


def test_xc_gate_fails_open_when_detector_absent(monkeypatch):
    """Lane-B's detector absent (parallel build) -> the gate leaves chips untouched (the register/deny/number
    gates still run); it never errors."""
    import sys as _sys
    monkeypatch.setitem(_sys.modules, "leviathan.graphrag.intent", None)   # import raises -> fail-open
    chips = ["palm ban -- impact on soybean oil?"]
    assert sv._xc_chip_gate(chips, {"pairs": []}) == chips


def test_route_serves_nothing_when_flag_off(monkeypatch):
    """D-SG S2/L1: the route is grounded-ONLY. With the flag off there is no catalog, so there is no
    prompt, no model call and no chip -- the ungrounded base prompt used to fill this window, and it
    bypassed the answerable denylist and the cross-commodity gate (both catalog-guarded)."""
    monkeypatch.setenv("GRAPHRAG_SUGGEST", "on")
    monkeypatch.delenv("GRAPHRAG_SUGGEST_CATALOG", raising=False)
    _warm(monkeypatch)                                                 # warm present, but flag off -> no catalog
    captured: dict = {}

    def fake_call(p):
        captured["prompt"] = p
        return '["A base follow-up about corn stocks?"]'

    monkeypatch.setitem(sv._STATE, "suggest_call", fake_call)
    r = _client(monkeypatch).post("/v1/suggest", json={"question": "corn?", "tldr": "tight"})
    assert r.status_code == 200
    assert r.json()["suggestions"] == []
    assert "prompt" not in captured                                    # the model was never called


def test_route_serves_nothing_when_matrix_is_cold(monkeypatch):
    """The other half of the same branch: flag ON but the convergence warmer cold (task restart, warmer
    down). Expected for up to one warmer cycle after a deploy -- an empty row, never a generic one."""
    monkeypatch.setenv("GRAPHRAG_SUGGEST", "on")
    monkeypatch.setenv("GRAPHRAG_SUGGEST_CATALOG", "on")
    monkeypatch.delitem(sv._STATE, "conv_warm", raising=False)
    called: dict = {}
    monkeypatch.setitem(sv._STATE, "suggest_call", lambda p: called.setdefault("hit", True) or '["Q?"]')
    r = _client(monkeypatch).post("/v1/suggest", json={"question": "corn?", "tldr": "tight"})
    assert r.status_code == 200 and r.json()["suggestions"] == [] and "hit" not in called


def test_grounded_prompt_asks_for_five_and_keeps_the_hard_rules(monkeypatch):
    """L3: the count clause and the Mix clause move together (a '5 questions' ask under three hard-named
    roles reads as a contradiction), while the two clauses the gates cannot repair after the fact -- the
    120-char rule and the no-minted-number rule -- stay exactly as ratified."""
    monkeypatch.setenv("GRAPHRAG_SUGGEST_CATALOG", "on")
    _warm(monkeypatch)
    p = sv._suggest_prompt_grounded(M.SuggestRequest(question="corn?"), None,
                                    sv._suggest_catalog_text(sv._suggest_catalog([])))
    assert "EXACTLY 5 questions" in p and "EXACTLY 3" not in p
    assert "Mix: cover at least (1)" in p and "extras beyond these are welcome" in p
    assert "MUST be under 120 characters" in p
    assert "NEVER state a specific numeric level, threshold, or quantity" in p
