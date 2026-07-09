"""Query-intent classifier — heuristic + LLM fallback (pure; no spend)."""
from __future__ import annotations

from leviathan.graphrag import intent as it


def test_numbers_only_heuristic():
    d = it.classify_intent("What were Argentina corn exports in 2023?")
    assert d["intent"] == "numbers_only" and d["needs_numbers"] and not d["needs_reasoning"]


def test_reasoning_heuristic():
    d = it.classify_intent("Why is a strong dollar bearish for soybeans?")
    assert d["intent"] == "reasoning" and d["needs_reasoning"] and not d["needs_numbers"]


def test_hybrid_heuristic():
    d = it.classify_intent("Given low ending stocks, is soybeans a buy?")
    assert d["intent"] == "hybrid" and d["needs_numbers"] and d["needs_reasoning"]


def test_neither_signal_defaults_to_reasoning_without_call():
    assert it.classify_intent("tell me about coffee")["intent"] == "reasoning"


def test_neither_signal_uses_llm_when_call_available():
    def fake_call(system, user, *, model, tool):
        assert tool["name"] == "set_intent"
        return {"intent": "numbers_only"}
    assert it.classify_intent("coffee", call=fake_call)["intent"] == "numbers_only"


def test_both_signals_defer_to_llm():
    # "given the observed X, is it convex" fires BOTH cues -> the exact case the heuristic mis-routed to numbers_only
    seen = {}

    def fake_call(system, user, *, model, tool):
        seen["called"] = True
        return {"intent": "hybrid"}
    d = it.classify_intent("Given the observed corn ending stocks, is the price response convex?", call=fake_call)
    assert seen.get("called") and d["intent"] == "hybrid"


def test_convexity_state_question_is_not_numbers_only():
    # without an LLM, a data cue + a convexity cue must fall to hybrid, never numbers_only
    d = it.classify_intent("Given where corn stocks-to-use sat, is a yield shock convex or linear?")
    assert d["intent"] == "hybrid"


def test_regime_count_questions_never_route_numbers_only():
    # P1.3: a "how many"/count phrasing about a REGIME/timing must not become a pure lookup (numbers_only ->
    # structured=None -> no map). Both cues fire, so the fallback lands reasoning-or-hybrid; either mounts the map.
    for q in ("How many weeks before the squeeze fires?",
              "How many weeks before the regime breaks?",
              "What's corn's stocks-to-use threshold number?"):
        assert it.classify_intent(q)["intent"] in ("reasoning", "hybrid"), q


# ══ is_news_explicit (news-agent root-cause fix): narrow explicit-ask matcher ═════════════════════════════
def test_is_news_explicit_matches_literal_news_asks():
    from leviathan.graphrag.intent import is_news_explicit
    assert is_news_explicit("any news related to that from a week or so?")   # the production query
    assert is_news_explicit("any news on corn?")
    assert is_news_explicit("latest news about the palm ban")
    assert is_news_explicit("news regarding sugar exports")
    assert is_news_explicit("what just happened to cotton?")


def test_is_news_explicit_rejects_ambient_nowness():
    from leviathan.graphrag.intent import is_news_explicit
    assert not is_news_explicit("corn exports today?")
    assert not is_news_explicit("thoughts on wheat right now?")
    assert not is_news_explicit("is the squeeze breaking this week?")
