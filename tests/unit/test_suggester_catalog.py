"""6.8 grounded suggester — data-scoped catalog + convexity house-style prompt + answerable-gate.
Hermetic: seeds the warm convergence matrix in _STATE, injects the Haiku call, no AWS / no LLM / no news
fetch. Flag-gated: GRAPHRAG_SUGGEST_CATALOG default off -> base prompt is byte-identical."""
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
    assert sv._suggest_catalog(["coffee"]) is None                     # flag off -> base prompt


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
    monkeypatch.setattr(sv, "_suggest_news_scoped", lambda scope: ["Frost hits Minas Gerais coffee belt"])
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
    assert "Frost hits Minas Gerais" in captured["prompt"]             # scoped headline fused in
    assert any("arabica" in s.lower() for s in out)                    # kept
    assert not any("diesel" in s.lower() for s in out)                 # answerable-gate dropped it


def test_route_base_prompt_when_flag_off(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_SUGGEST", "on")
    monkeypatch.delenv("GRAPHRAG_SUGGEST_CATALOG", raising=False)
    _warm(monkeypatch)                                                 # warm present, but flag off -> base
    captured: dict = {}

    def fake_call(p):
        captured["prompt"] = p
        return '["A base follow-up about corn stocks?"]'

    monkeypatch.setitem(sv._STATE, "suggest_call", fake_call)
    monkeypatch.setitem(sv._STATE, "suggest_news", (time.time(), []))  # keep base news off the fetch path
    r = _client(monkeypatch).post("/v1/suggest", json={"question": "corn?", "tldr": "tight"})
    assert r.status_code == 200
    assert "answerable-only" not in captured["prompt"]                 # base prompt, no catalog
    assert "Regimes closest to tipping" not in captured["prompt"]


# ── scoped news cache ────────────────────────────────────────────────────────────────────────────────
def test_news_scoped_returns_cached_without_fetch(monkeypatch):
    monkeypatch.setitem(sv._STATE, "suggest_news_cache", {"coffee sugar": (time.time(), ["h1", "h2"])})
    assert sv._suggest_news_scoped("coffee sugar") == ["h1", "h2"]     # fresh -> no background fetch


def test_news_scoped_empty_delegates_to_global(monkeypatch):
    monkeypatch.setitem(sv._STATE, "suggest_news", (time.time(), ["g1"]))
    assert sv._suggest_news_scoped("") == ["g1"]                        # empty scope -> global cache
