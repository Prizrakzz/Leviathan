"""Phase 6.2 query suggester — POST /v1/suggest (decoupled Haiku side-channel) + the conciseness
prompt/eval hooks. All hermetic: InMemory store, injected suggest_call. No AWS, no LLM, no news
(E1b dropped the suggester's news surface). Every failure mode must degrade to
{"suggestions": []} — never an error."""
from __future__ import annotations

import time

from fastapi.testclient import TestClient
from leviathan.causal import schema as cs
from leviathan.graphrag import graph as g
from leviathan.graphrag import server as sv
from leviathan.graphrag import store as st


def _graph() -> g.CausalGraph:
    coffee = cs.CausalContract(
        contract="arabica_coffee", aliases=["arabica"],
        drivers=[cs.Driver(id="frost", type="hazard", sign="+", mechanism="m")])
    return g.CausalGraph({"arabica_coffee": coffee}, silver=set())


def _client(monkeypatch, *, call=None):
    monkeypatch.setitem(sv._STATE, "graph", _graph())
    monkeypatch.setitem(sv._STATE, "store", st.InMemoryStore())
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
    assert "headline" not in p.lower()


def test_suggest_empty_packet_is_thread_start(monkeypatch):
    seen = {}

    def fake(prompt: str) -> str:
        seen["prompt"] = prompt
        return '["What drives corn convexity this season?"]'

    c = _client(monkeypatch, call=fake)
    r = c.post("/v1/suggest", json={})
    assert r.status_code == 200 and len(r.json()["suggestions"]) == 1
    assert "NEW empty session" in seen["prompt"]


def test_suggest_parse_failure_and_model_error_degrade_to_empty(monkeypatch):
    c = _client(monkeypatch, call=lambda p: "no json here at all")
    assert c.post("/v1/suggest", json=_PACKET).json()["suggestions"] == []

    def boom(p):
        raise RuntimeError("provider down")
    c2 = _client(monkeypatch, call=boom)
    r = c2.post("/v1/suggest", json=_PACKET)
    assert r.status_code == 200 and r.json()["suggestions"] == []


def test_suggest_guards_drop_leaks_longs_dupes_and_cap_at_4(monkeypatch):
    long = "x" * 141
    raw = ('["Watch the bullish_drought_squeeze regime", "Good question?", "Good question?", '
           f'"{long}", 42, "Second?", "Third?", "Fourth?", "Fifth?"]')
    c = _client(monkeypatch, call=lambda p: raw)
    out = c.post("/v1/suggest", json=_PACKET).json()["suggestions"]
    assert out == ["Good question?", "Second?", "Third?", "Fourth?"]   # leak/dupe/long/non-str dropped, <=4


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
    assert "User interests: corn, wheat" in seen["prompt"]


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
