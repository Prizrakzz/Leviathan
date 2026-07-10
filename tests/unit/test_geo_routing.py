"""Country-aware live-news search (5.8) — name a country with no commodity and the news fetch searches
THAT country instead of generic keywords. Gated on GRAPHRAG_GEO_ROUTING, so the flag-off path is proven
inert here too. (The fuzzy in-thread topic-shift carry-breaker was removed by design — threads are the
context boundary; a new thread is a clean session, so there is nothing to detect.)"""
from __future__ import annotations

import pytest
from leviathan.graphrag import orchestrator as orch


@pytest.fixture(scope="module")
def real_graph():
    from leviathan.graphrag import graph as g
    return g.CausalGraph.load()


def test_live_search_adds_country_when_flag_on(monkeypatch, real_graph):
    monkeypatch.setenv("GRAPHRAG_GEO_ROUTING", "on")
    terms = orch._live_search_terms("anything from the news on India?", real_graph)
    assert any("india" in t.lower() for t in terms)                  # the fetch now searches India


def test_live_search_country_inert_when_flag_off(monkeypatch, real_graph):
    monkeypatch.delenv("GRAPHRAG_GEO_ROUTING", raising=False)
    terms = orch._live_search_terms("anything from the news on India?", real_graph)
    assert not any("india" in t.lower() for t in terms)              # flag-off = today's generic terms


def test_live_search_commodity_query_unchanged_by_flag(monkeypatch, real_graph):
    # a query that names a commodity keeps the commodity path — the country fallback only fires when the
    # query names NO commodity, so a normal wheat/soy news query is identical flag-on vs flag-off.
    monkeypatch.setenv("GRAPHRAG_GEO_ROUTING", "on")
    on = orch._live_search_terms("latest news on wheat exports", real_graph)
    monkeypatch.delenv("GRAPHRAG_GEO_ROUTING", raising=False)
    off = orch._live_search_terms("latest news on wheat exports", real_graph)
    assert on == off
