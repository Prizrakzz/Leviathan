"""Params loader — dotted-path reads, fallback discipline, and the no-behavior-change pin.

The pin matters: externalizing constants must not silently change serving values. If params.yaml and
the code defaults ever disagree, that must be a REVIEWED decision (edit the pin), not drift.
"""
from __future__ import annotations

from leviathan.graphrag import params as pr


def test_get_reads_dotted_paths_and_falls_back():
    pr.reload()
    assert pr.get("serving.walk.tau", 0.35) == 0.35                 # yaml agrees with the code default
    assert pr.get("serving.nope.missing", "fb") == "fb"             # absent path -> caller default
    assert pr.get("not_a_section.at_all", 7) == 7


def test_missing_yaml_degrades_to_defaults(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_PARAMS", "does/not/exist.yaml")
    pr.reload()
    assert pr.get("serving.retrieval.rerank_pool", 60) == 60        # public clone runs on code defaults
    monkeypatch.delenv("GRAPHRAG_PARAMS")
    pr.reload()


def test_serving_values_pin_the_code_defaults():
    """params.yaml serving values == the constants they replaced (change = reviewed decision)."""
    pr.reload()
    from leviathan.graphrag import rankers as rk
    assert rk.RERANK_POOL == 60
    assert pr.get("serving.walk.node_budget", None) in (None, 10)
    assert pr.get("serving.ground.recency_days", None) in (None, 548)
    assert tuple(pr.get("serving.ground.k_by_depth", (5, 3, 2))) == (5, 3, 2)
    assert pr.get("serving.retrieval.fetch_k", None) in (None, 60)
    assert pr.get("serving.retrieval.mmr", None) in (None, 0.5)
