"""D-AM-16 -- the deterministic prompt gallery (GET /v1/gallery).

Three claims, in descending order of how expensive they are to get wrong:

  1. RESPONSE-CONTRACT TRUTH. Every row of configs/graphrag/gallery.yaml declares `rc_target`, the response
     contract its wording is authored to select. If a template drifts off its target the landing page starts
     handing the engine questions shaped for one contract and labelled another -- silent, and invisible in
     any eval that does not read this file. Each row is pinned TWICE: filled from a catalog, and with its
     slots neutralized, because the cue must live in the AUTHORED words, never in a slot value (a slot
     renders live data whose wording moves with the book).
  2. FREE + DETERMINISTIC. The route is a dict read off the warm catalog -- no model call, no quota. The
     suggester's Haiku seam and quota counter must be provably untouched.
  3. NEVER BLANK, NEVER WRONG. Cold catalog -> the unfilled templates (the page's only content). Warm
     catalog with an unfillable slot -> that row is dropped, not shown blank. Unreadable config -> [].
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from leviathan.graphrag import intent
from leviathan.graphrag import server as sv
from leviathan.graphrag import store as st

# A catalog in the exact shape `_suggest_catalog` returns. `regime` values are RAW ids on purpose -- the
# route must humanize them through the display registry, so a raw slug reaching a question fails here.
CATALOG = {
    "near": [
        {"contract": "arabica_coffee", "regime": "bullish_frost_squeeze", "proximity": 0.9},
        {"contract": "corn_cbot", "regime": "bearish_record_supply", "proximity": 0.7},
        {"contract": "raw_sugar", "regime": "bullish_ethanol_diversion", "proximity": 0.5},
    ],
    "contracts": ["arabica_coffee", "corn_cbot", "raw_sugar", "soybeans_cbot"],
    "pairs": [{"id": "veg_oils", "legs": ["malaysian_crude_palm_oil_cme", "soybean_oil_cbot"],
               "complex_name": "vegoils", "shared_event": "export_ban"}],
}


@pytest.fixture(autouse=True)
def _fresh_templates():
    # The parse is lru_cached for the life of the process; every test here either re-reads the real file or
    # points the loader at a temp one, so the cache is cleared on both sides of each test.
    sv._gallery_templates.cache_clear()
    yield
    sv._gallery_templates.cache_clear()


def _client(monkeypatch, catalog=CATALOG) -> TestClient:
    monkeypatch.setitem(sv._STATE, "store", st.InMemoryStore())
    monkeypatch.delenv("GRAPHRAG_AUTH", raising=False)
    monkeypatch.setattr(sv, "_suggest_catalog", lambda scope: catalog)
    return TestClient(sv.app)


def _rows() -> tuple[dict, ...]:
    rows = sv._gallery_templates()
    assert rows, "gallery.yaml did not parse -- every later assertion would pass vacuously"
    return rows


# -- 1. the response-contract claim -------------------------------------------------------------------
def test_every_template_selects_its_declared_response_contract(monkeypatch):
    # The load-bearing test of the whole task: the AUTHORED wording, once filled, must select rc_target.
    c = _client(monkeypatch)
    items = c.get("/v1/gallery").json()["items"]
    assert len(items) == len(_rows())                       # nothing dropped: this catalog fills every slot
    for it in items:
        got = intent.select_response_contract(it["question"]) or "default"
        assert got == it["rc_target"], f"{it['id']}: {it['question']!r} -> {got}, declared {it['rc_target']}"


def test_the_contract_cue_lives_in_the_authored_words_not_the_fill():
    # Slots render live data (a contract phrase, a display-registry regime label, a realizable pair) whose
    # wording we do not control. Neutralize every slot: the declared contract must still be selected, so a
    # new regime label or a renamed contract can never re-route a starter.
    for r in _rows():
        neutral = sv._GALLERY_SLOT.sub("X", r["template"])
        got = intent.select_response_contract(neutral) or "default"
        assert got == r["rc_target"], f"{r['id']}: neutralized {neutral!r} -> {got}"


def test_declared_targets_are_real_contracts_the_selector_can_return():
    known = {name for name, _ in intent._RC_PATTERNS} | {"default"}
    assert {r["rc_target"] for r in _rows()} <= known


def test_the_gallery_covers_the_ratified_categories():
    cats = {r["category"] for r in _rows()}
    assert {"cross_commodity", "convergence", "cascade", "verification",
            "ranking", "horizon", "recency"} <= cats
    assert len({r["id"] for r in _rows()}) == len(_rows())   # ids are the FE's chip keys


# -- 2. free + deterministic --------------------------------------------------------------------------
def test_the_route_spends_no_model_call_and_no_quota(monkeypatch):
    # The whole reason the gallery is not /v1/suggest. A Haiku call or a quota increment here would make the
    # landing page cost money per visit and go dark at the daily cap.
    c = _client(monkeypatch)
    monkeypatch.setitem(sv._STATE, "suggest_call", lambda p: (_ for _ in ()).throw(AssertionError("model call")))
    monkeypatch.setattr(sv._store(), "incr_turn_quota",
                        lambda *a, **k: pytest.fail("gallery must not touch any quota counter"))
    assert c.get("/v1/gallery").status_code == 200


def test_two_reads_of_the_same_catalog_are_identical(monkeypatch):
    c = _client(monkeypatch)
    assert c.get("/v1/gallery").json() == c.get("/v1/gallery").json()


def test_contract_and_regime_come_from_the_same_near_row(monkeypatch):
    # The pairing must be TRUE: a row may only name the regime that is actually closest to firing for the
    # contract it names. Rotation is by template index, so row i pairs near[i % 3].
    c = _client(monkeypatch)
    items = c.get("/v1/gallery").json()["items"]
    truth = {"arabica coffee": "frost squeeze", "corn": "record supply", "sugar": "ethanol diversion"}
    seen = 0
    for it in items:
        for contract, regime in truth.items():
            if f" {contract} " in f" {it['question']} " or f" {contract}?" in it["question"]:
                assert all(r not in it["question"] for c2, r in truth.items() if c2 != contract), it["question"]
                seen += 1
    assert seen >= 3                                        # every near row is exercised by some template


def test_regime_ids_are_humanized_and_never_leak_raw(monkeypatch):
    c = _client(monkeypatch)
    body = " ".join(i["question"] for i in c.get("/v1/gallery").json()["items"])
    assert "bullish_frost_squeeze" not in body and "corn_cbot" not in body
    assert "frost squeeze" in body.lower()


def test_no_near_rows_falls_back_to_the_tracked_contract_list(monkeypatch):
    # A warm matrix with nothing near firing still names real tracked contracts; the regime rows drop out
    # (there is no honest regime to name) rather than inventing one.
    c = _client(monkeypatch, catalog={**CATALOG, "near": []})
    items = c.get("/v1/gallery").json()["items"]
    assert {i["id"] for i in items} == {r["id"] for r in _rows() if "{regime}" not in r["template"]}
    assert all(i["filled"] for i in items)
    assert "arabica coffee" in " ".join(i["question"] for i in items)


def test_an_empty_catalog_reads_as_cold_not_as_warm_and_empty(monkeypatch):
    # `_suggest_catalog` returns None when the matrix is cold, but a degenerate {} must not be treated as a
    # warm catalog -- that would drop every row and serve a gallery of nothing.
    c = _client(monkeypatch, catalog={})
    body = c.get("/v1/gallery").json()
    assert body["catalog_warm"] is False and len(body["items"]) == len(_rows())


def test_pairs_come_only_from_the_realizable_set(monkeypatch):
    # The pair rows exist to name a cascade the engine can actually walk. With no realizable pair the rows
    # are DROPPED (never a blank slot beside concrete questions) -- the RV-v2-off production default.
    c = _client(monkeypatch, catalog={**CATALOG, "pairs": []})
    items = c.get("/v1/gallery").json()["items"]
    assert items, "dropping the pair rows must not empty the gallery"
    assert not any("{pair}" in i["question"] for i in items)
    assert {i["id"] for i in items} == {r["id"] for r in _rows() if "{pair}" not in r["template"]}


# -- 3. the fallbacks ---------------------------------------------------------------------------------
def test_cold_catalog_serves_every_template_unfilled(monkeypatch):
    # A cold warmer must not blank the landing page: the fill-in-the-blank form IS the fallback product.
    c = _client(monkeypatch, catalog=None)
    body = c.get("/v1/gallery").json()
    assert body["catalog_warm"] is False
    assert len(body["items"]) == len(_rows())
    assert all(i["filled"] is False for i in body["items"])
    assert any("{contract}" in i["question"] for i in body["items"])


def test_catalog_raise_degrades_to_the_template_fallback(monkeypatch):
    monkeypatch.setitem(sv._STATE, "store", st.InMemoryStore())
    monkeypatch.delenv("GRAPHRAG_AUTH", raising=False)
    monkeypatch.setattr(sv, "_suggest_catalog", lambda scope: (_ for _ in ()).throw(RuntimeError("cold")))
    body = TestClient(sv.app).get("/v1/gallery").json()
    assert body["catalog_warm"] is False and len(body["items"]) == len(_rows())


def test_unreadable_config_fails_closed_to_an_empty_gallery(monkeypatch, tmp_path):
    bad = tmp_path / "gallery.yaml"
    bad.write_text("templates: [ {id: a, template: 'x'\n", encoding="utf-8")   # unterminated flow mapping
    monkeypatch.setattr(sv, "_GALLERY_PATH", bad)
    sv._gallery_templates.cache_clear()
    c = _client(monkeypatch)
    assert c.get("/v1/gallery").json()["items"] == []


def test_missing_config_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(sv, "_GALLERY_PATH", tmp_path / "absent.yaml")
    sv._gallery_templates.cache_clear()
    assert sv._gallery_templates() == ()


def test_rows_missing_id_or_template_are_skipped_not_fatal(monkeypatch, tmp_path):
    p = tmp_path / "gallery.yaml"
    p.write_text("templates:\n  - id: ok\n    category: recency\n    rc_target: recency\n"
                 "    template: 'What changed in the past 30 days?'\n"
                 "  - category: orphan\n    template: 'no id'\n"
                 "  - id: blank\n    category: orphan\n", encoding="utf-8")
    monkeypatch.setattr(sv, "_GALLERY_PATH", p)
    sv._gallery_templates.cache_clear()
    assert [r["id"] for r in sv._gallery_templates()] == ["ok"]


# -- the gate -----------------------------------------------------------------------------------------
def test_gallery_401_anon_when_auth_on(monkeypatch):
    c = _client(monkeypatch)
    monkeypatch.setenv("GRAPHRAG_AUTH", "on")
    assert c.get("/v1/gallery").status_code == 401


def test_gallery_uses_the_same_identity_dependency_as_the_other_reads():
    def deps(path):
        r = next(r for r in sv.app.routes if r.path == path and "GET" in (getattr(r, "methods", None) or set()))
        return {d.call for d in r.dependant.dependencies}

    assert deps("/v1/gallery") == deps("/v1/convergence") == {sv._require_identity}
