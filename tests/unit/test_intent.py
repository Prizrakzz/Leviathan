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
