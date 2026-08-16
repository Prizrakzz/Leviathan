"""Phase 6.2 query suggester — POST /v1/suggest (decoupled Haiku side-channel) + the conciseness
prompt/eval hooks. All hermetic: InMemory store, injected suggest_call. No AWS, no LLM, no news
(E1b dropped the suggester's news surface). Every failure mode must degrade to
{"suggestions": []} — never an error.

D-SG S2: the route is GROUNDED-ONLY. A flag-off or cold catalog serves no chips at all, so every
route test here seeds the warm convergence matrix and the catalog flag — that combination IS the
serving path now, and a test that leaves it cold measures the degrade branch, not the feature."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from leviathan.causal import schema as cs
from leviathan.graphrag import graph as g
from leviathan.graphrag import register as reg
from leviathan.graphrag import server as sv
from leviathan.graphrag import store as st


@pytest.fixture(autouse=True)
def _clean_register_caches():
    """Mirrors test_suggester_catalog: register._slugs()/_display_map() are module-level lru_caches an
    earlier suite test can poison with a fake hierarchy, and the grounded prompt now runs sanitize() on
    every request. Rebuild from the real hierarchy per test, and don't leak the state forward."""
    reg._slugs.cache_clear(); reg._display_map.cache_clear()
    yield
    reg._slugs.cache_clear(); reg._display_map.cache_clear()


def _graph() -> g.CausalGraph:
    coffee = cs.CausalContract(
        contract="arabica_coffee", aliases=["arabica"],
        drivers=[cs.Driver(id="frost", type="hazard", sign="+", mechanism="m")])
    return g.CausalGraph({"arabica_coffee": coffee}, silver=set())


ROWS = [
    {"contract": "arabica_coffee", "regimes": [
        {"name": "bullish_supply_squeeze", "direction": "+", "matched": ["frost", "tenderable_collapse"],
         "threshold": 4, "fired": False, "n_active": 2, "proximity": 0.5}]},
    {"contract": "raw_sugar", "regimes": [
        {"name": "ethanol_diversion_regime", "direction": "+", "matched": ["crude_oil"],
         "threshold": 2, "fired": True, "n_active": 2, "proximity": 1.0}]},
]


def _client(monkeypatch, *, call=None, grounded=True):
    monkeypatch.setitem(sv._STATE, "graph", _graph())
    monkeypatch.setitem(sv._STATE, "store", st.InMemoryStore())
    if grounded:                                                       # the serving shape: flag on + warm matrix
        monkeypatch.setenv("GRAPHRAG_SUGGEST_CATALOG", "on")
        monkeypatch.setitem(sv._STATE, "conv_warm",
                            (time.time(), ("2026-07-06", "gv1"),
                             {"asof": "2026-07-06", "graph_version": "gv1", "rows": ROWS}))
    else:
        monkeypatch.delenv("GRAPHRAG_SUGGEST_CATALOG", raising=False)
        monkeypatch.delitem(sv._STATE, "conv_warm", raising=False)
    if call is not None:
        monkeypatch.setitem(sv._STATE, "suggest_call", call)
    return TestClient(sv.app)


_PACKET = {"thread_id": "t1", "question": "why is arabica tight?",
           "tldr": "Stocks are thin; a frost would spike prices.", "contracts": ["arabica_coffee"],
           "intent": "reasoning", "asof": "2026-07-06"}


def test_suggest_happy_path_returns_clean_chips(monkeypatch):
    seen = {}

    def fake(prompt: str) -> str:
        seen["prompt"] = prompt
        return '["How thin are certified stocks now?", "What would a July frost do to the KC curve?"]'

    c = _client(monkeypatch, call=fake)
    r = c.post("/v1/suggest", json=_PACKET)
    assert r.status_code == 200
    assert r.json()["suggestions"] == ["How thin are certified stocks now?",
                                       "What would a July frost do to the KC curve?"]
    # the packet reached the prompt; contracts read as words, not slugs; no news injection (E1b)
    p = seen["prompt"]
    assert "why is arabica tight?" in p and "Stocks are thin" in p
    assert "arabica coffee" in p and "arabica_coffee" not in p
    assert "Today's headlines" not in p                                  # E1b: the injection block is gone
    assert "answerable-only" in p and "Regimes closest to tipping" in p   # the grounded prompt, always


def test_suggest_empty_packet_is_thread_start(monkeypatch):
    seen = {}

    def fake(prompt: str) -> str:
        seen["prompt"] = prompt
        return '["What drives corn convexity this season?"]'

    c = _client(monkeypatch, call=fake)
    r = c.post("/v1/suggest", json={})
    assert r.status_code == 200 and len(r.json()["suggestions"]) == 1
    # an empty packet is still GROUNDED (starters off the warm catalog), it just carries no prior turn
    assert "Tracked contracts (ONLY ask about these)" in seen["prompt"]
    assert "Last question:" not in seen["prompt"]


def test_suggest_parse_failure_and_model_error_degrade_to_empty(monkeypatch):
    c = _client(monkeypatch, call=lambda p: "no json here at all")
    assert c.post("/v1/suggest", json=_PACKET).json()["suggestions"] == []

    def boom(p):
        raise RuntimeError("provider down")
    c2 = _client(monkeypatch, call=boom)
    r = c2.post("/v1/suggest", json=_PACKET)
    assert r.status_code == 200 and r.json()["suggestions"] == []


def test_parse_guards_drop_leaks_longs_dupes_and_cap_at_6():
    """The PARSE cap is 6 (D-SG S2/L3: the prompt asks for 5, the cap carries one slot of slack so the
    gates have something to spend). The wire trim to 3 happens in the route, not here."""
    long = "x" * 141
    raw = ('["Watch the bullish_drought_squeeze regime", "Good question?", "Good question?", '
           f'"{long}", 42, "Second?", "Third?", "Fourth?", "Fifth?", "Sixth?", "Seventh?"]')
    out = sv._parse_suggestions(raw)
    assert out == ["Good question?", "Second?", "Third?", "Fourth?", "Fifth?", "Sixth?"]   # <=6, "Seventh?" cut


def test_parse_truncated_mid_array_returns_empty():
    """The truncation risk L3c pays for: `_parse_suggestions` locates the array with rindex("]"), so a
    completion cut off mid-array has no closing bracket and yields NO chips — the row goes to zero rather
    than to a partial. This is why max_tokens carries headroom over the 5-chip ask."""
    raw = ('["How fast must certified stocks fall before the squeeze fires?", '
           '"Does the cane crush mix tip the diversion regi')
    assert sv._parse_suggestions(raw) == []


def test_parse_keeps_six_chips_at_the_length_ceiling():
    """Six DISTINCT chips at exactly the 140-char parser ceiling all survive: the cap is 6 and the length
    rule is <=140, so a full over-generated batch reaches the route's gates intact."""
    chips = [f"How fast must ending stocks fall before the {w} squeeze regime fires".ljust(140, ".")
             for w in ("coffee", "sugar", "corn", "wheat", "cotton", "soybean")]
    assert all(len(s) == 140 for s in chips)
    out = sv._parse_suggestions("[" + ", ".join(f'"{s}"' for s in chips) + "]")
    assert out == chips


def test_suggest_route_trims_the_wire_to_three(monkeypatch):
    """Over-generation is the mechanism, 3 is the contract: six clean chips in, the first three out."""
    chips = [f"Is the {w} squeeze regime arming as the export pace lifts?"
             for w in ("coffee", "sugar", "corn", "wheat", "cotton", "soybean")]
    c = _client(monkeypatch, call=lambda p: "[" + ", ".join(f'"{s}"' for s in chips) + "]")
    assert c.post("/v1/suggest", json=_PACKET).json()["suggestions"] == chips[:3]


def test_mints_number_whitelists_labels_rejects_magnitudes():
    # survivors: named digit-tokens (codes, ONI band either order, grades, years, fractions, windows, quarters)
    for keep in ("Does the B40 mandate divert palm toward the diversion regime?",
                 "Will an E15 waiver lift the ethanol grind?",
                 "As ONI 0.5 flips to El Nino, is soy convex?",
                 "A 0.5 ONI reading -- does the teleconnection fire?",
                 "Is No. 2 yellow corn's basis tightening?",
                 "How did the 2016 analog play out for coffee?",
                 "Corn ending stocks vs the 5-year average -- convex?",
                 "At 2/4 drivers, how close is the squeeze?",
                 "Does a Q4 crush surge tip the ethanol regime?"):
        assert not sv._mints_number(keep), keep
    # dropped: minted magnitudes (unit/scale words) and bare ratio decimals
    for drop in ("Will Brazil's crop fall 16 million bags before the squeeze?",
                 "Does stocks-to-use below 0.45 ratio tip it?",
                 "Is a >15% export lag bullish?",
                 "Will ending stocks drop 5 MMT?",
                 "Does a 40% tariff cascade to soymeal?"):
        assert sv._mints_number(drop), drop


def test_suggest_drops_minted_number_keeps_clean(monkeypatch):
    raw = ('["Will Brazil lose 16 million bags before the squeeze fires?", '
           '"As ONI 0.5 flips to El Nino, is the soy teleconnection convex?"]')
    c = _client(monkeypatch, call=lambda p: raw)
    out = c.post("/v1/suggest", json=_PACKET).json()["suggestions"]
    assert out == ["As ONI 0.5 flips to El Nino, is the soy teleconnection convex?"]   # minted magnitude dropped


def test_suggest_kill_switch_short_circuits_before_model(monkeypatch):
    called = {}
    c = _client(monkeypatch, call=lambda p: called.setdefault("hit", True) or "[]")
    monkeypatch.setenv("GRAPHRAG_SUGGEST", "off")
    r = c.post("/v1/suggest", json=_PACKET)
    assert r.status_code == 200 and r.json()["suggestions"] == [] and "hit" not in called


def test_suggest_cold_catalog_serves_nothing_and_spends_no_quota(monkeypatch):
    """D-SG S2/L1: no catalog -> no chips (the ungrounded base prompt is off the serving path) AND no
    quota slot. The counter caps Haiku spend, so a call that never happens must not consume one."""
    called = {}
    c = _client(monkeypatch, call=lambda p: called.setdefault("hit", True) or '["Q?"]', grounded=False)
    monkeypatch.setenv("GRAPHRAG_SUGGEST", "on")
    r = c.post("/v1/suggest", json=_PACKET)
    assert r.status_code == 200 and r.json()["suggestions"] == []
    assert "hit" not in called                                          # no model call
    assert sv._STATE["store"]._quota == {}                              # and no slot burned


def test_suggest_cap_uses_namespaced_counter_never_turn_quota(monkeypatch):
    c = _client(monkeypatch, call=lambda p: '["Q?"]')
    monkeypatch.setenv("GRAPHRAG_SUGGEST_QUOTA", "2")
    day = time.strftime("%Y-%m-%d", time.gmtime())
    store = sv._STATE["store"]
    assert c.post("/v1/suggest", json=_PACKET).json()["suggestions"] == ["Q?"]
    assert c.post("/v1/suggest", json=_PACKET).json()["suggestions"] == ["Q?"]
    r3 = c.post("/v1/suggest", json=_PACKET)                          # over cap -> 200 + [] (never 429)
    assert r3.status_code == 200 and r3.json()["suggestions"] == []
    assert store._quota[("local", f"suggest#{day}")] == 2             # namespaced counter incremented
    assert ("local", day) not in store._quota                          # the TURN quota was never touched


def test_suggest_includes_profile_facts_when_present(monkeypatch):
    seen = {}
    c = _client(monkeypatch, call=lambda p: seen.setdefault("prompt", p) and '["Q?"]')
    sv._STATE["store"]._profiles["local"] = {"facts": {"markets": ["corn", "wheat"]}}
    c.post("/v1/suggest", json=_PACKET)
    assert "User markets/interests: corn, wheat" in seen["prompt"]


def test_suggest_news_surface_is_gone(monkeypatch):
    # E1b: the suggester's news half is deleted -- no fetch fires and no news state is written
    def boom(terms):
        raise AssertionError("news gather must never fire from the suggester")

    from leviathan.graphrag.news import fetch as nf
    monkeypatch.setattr(nf, "gather", boom)
    assert not hasattr(sv, "_suggest_news") and not hasattr(sv, "_suggest_news_scoped")
    c = _client(monkeypatch, call=lambda p: '["Q?"]')
    assert c.post("/v1/suggest", json=_PACKET).json()["suggestions"] == ["Q?"]
    assert not any(k.startswith("suggest_news") for k in sv._STATE)   # the 4 news keys never appear


def test_system_prompt_has_length_discipline_and_eval_tracks_chars():
    from leviathan.graphrag import answer as an
    from leviathan.graphrag import eval as E
    assert "LENGTH DISCIPLINE" in an._SYSTEM and "150-220 words" in an._SYSTEM   # P9-A mentor budget
    row = {"q": {"contract": "corn", "id": "q1"}, "rubric": {"routed_right": True},
           "out": {"answer": "x" * 500, "evidence": [], "structured": {}}}
    assert E._metrics(row)["answer_chars"] == 500
    panel = "\n".join(E.register_report([row]))
    assert "answer length: mean 500" in panel


def test_suggest_drops_lane_b_valuation_chip():
    """PRICE_OBSERVABILITY W0.3 (S1.F9): a Lane B windowed-valuation chip drops via the server.py:609
    guard; Lane A already rides register_leaks. An honest fundamental chip survives."""
    raw = ('["Is palm cheap vs soyoil?", "Is the drought squeeze regime firing for coffee?"]')
    out = sv._parse_suggestions(raw)
    assert "Is palm cheap vs soyoil?" not in out                       # Lane B (cheap + comparison) dropped
    assert out == ["Is the drought squeeze regime firing for coffee?"]  # fundamental squeeze regime survives
