"""Terminal read/persist endpoints (build-plan P1.2-1.7) — real small graph, mocked silver/query/news.

Asserts each route returns its §6 response shape and honors the PIT kill-switch on /v1/events."""
from __future__ import annotations

import types

import pytest
from fastapi.testclient import TestClient

from leviathan.causal import schema as cs
from leviathan.graphrag import graph as g
from leviathan.graphrag import server as sv


def _graph() -> g.CausalGraph:
    coffee = cs.CausalContract(
        contract="arabica_coffee", aliases=["arabica"],
        drivers=[cs.Driver(id="frost", type="hazard", sign="+", mechanism="m",
                           silver_status="available", silver_ref="frost"),
                 cs.Driver(id="low_stocks", type="hazard", sign="+", mechanism="m",
                           silver_status="available", silver_ref="su"),
                 cs.Driver(id="drought", type="hazard", sign="+", mechanism="m")],
        convergence=[cs.ConvergenceSignal(name="squeeze", direction="+", requires_any_n_of=2,
                                          drivers=["frost", "low_stocks", "drought"])])
    return g.CausalGraph({"arabica_coffee": coffee}, silver=set(), version="gtest12ab34cd")


def _lookup(observed=("frost", "low_stocks")):
    def lk(contract, did, asof):
        if did in observed:
            return {"live": True, "verdict": "observed", "z": -2.0, "value": 0.09, "unit": "ratio", "ref": "su"}
        return {"live": False}
    return lk


def _client(monkeypatch, *, lookup=None):
    monkeypatch.setitem(sv._STATE, "graph", _graph())
    monkeypatch.setitem(sv._STATE, "store", __import__("leviathan.graphrag.store", fromlist=["x"]).InMemoryStore())
    if lookup is not None:
        monkeypatch.setattr(sv, "_silver_lookup", lambda cap=256: lookup)
    return TestClient(sv.app)


# ── 1.2 graph topology ──────────────────────────────────────────────────────────────────────────────
def test_graph_topology_route(monkeypatch):
    body = _client(monkeypatch).get("/v1/graph/arabica_coffee").json()
    ids = {n["id"] for n in body["nodes"]}
    assert {"frost", "arabica_coffee"} <= ids and body["graph_version"] == "gtest12ab34cd"


def test_graph_topology_unknown_404(monkeypatch):
    assert _client(monkeypatch).get("/v1/graph/nope").status_code == 404


def test_graph_topology_asof_firing_overlay(monkeypatch):
    body = _client(monkeypatch, lookup=_lookup()).get("/v1/graph/arabica_coffee",
                                                       params={"asof": "2021-07-20"}).json()
    frost = next(n for n in body["nodes"] if n["id"] == "frost")
    drought = next(n for n in body["nodes"] if n["id"] == "drought")
    assert frost["active"] is True and drought["active"] is False        # observed vs unresolved


# ── 1.3 convergence ──────────────────────────────────────────────────────────────────────────────────
def test_convergence_route(monkeypatch):
    body = _client(monkeypatch, lookup=_lookup()).get("/v1/convergence", params={"asof": "2021-07-20"}).json()
    assert body["asof"] == "2021-07-20" and body["rows"]
    sq = next(r for r in body["rows"][0]["regimes"] if r["name"] == "squeeze")
    assert sq["fired"] is True and sq["n_active"] == 2


# ── 1.4 regimes ──────────────────────────────────────────────────────────────────────────────────────
def test_regimes_route_and_404(monkeypatch):
    c = _client(monkeypatch, lookup=_lookup(observed=("frost",)))
    body = c.get("/v1/regimes/arabica_coffee", params={"asof": "2021-07-20"}).json()
    sq = next(r for r in body["regimes"] if r["name"] == "squeeze")
    assert sq["fired"] is False and sq["proximity"] == pytest.approx(0.5)   # 1 of 2
    assert c.get("/v1/regimes/nope").status_code == 404


# ── 1.5 series ───────────────────────────────────────────────────────────────────────────────────────
def test_series_validation_and_shape(monkeypatch):
    from leviathan.graphrag.numbers import query as Q
    from leviathan.graphrag.numbers.registry import load_registry
    c = _client(monkeypatch)
    assert c.get("/v1/series/not_a_table/x").status_code == 404            # unknown table
    reg = load_registry()
    table = next(t for t in reg.tables if reg.get(t).metrics)              # any real table with metrics
    metric = next(iter(reg.get(table).metrics))
    assert c.get(f"/v1/series/{table}/definitely_not_a_metric").status_code == 400   # unknown metric
    monkeypatch.setattr(Q, "run", lambda spec, query_fn=None: [{"value": "0.09", "period": "2021",
                                                                "knowledge_date": "2021-07-10"}])
    body = c.get(f"/v1/series/{table}/{metric}", params={"asof": "2024-01-01"}).json()
    assert body["table"] == table and body["metric"] == metric and body["points"][0]["value"] == "0.09"


# ── 1.6 events (PIT kill-switch) ─────────────────────────────────────────────────────────────────────
def test_events_killswitch_no_fetch_behind_asof(monkeypatch):
    from leviathan.graphrag.news import fetch as nf
    monkeypatch.setattr(nf, "gather", lambda terms: (_ for _ in ()).throw(AssertionError("fetched behind as-of!")))
    body = _client(monkeypatch).get("/v1/events", params={"contract": "arabica_coffee",
                                                          "asof": "2020-01-01"}).json()
    assert body["live"] is False and body["events"] == []


def test_events_live_path(monkeypatch):
    from leviathan.graphrag import orchestrator as orch
    from leviathan.graphrag.news import extract_live as nx
    from leviathan.graphrag.news import fetch as nf
    monkeypatch.setattr(orch, "_live_search_terms", lambda q, gr: ["frost coffee"])
    monkeypatch.setattr(nf, "gather", lambda terms: [{"title": "Frost", "fetched_at": "2026-07-04"}])
    ev = types.SimpleNamespace(model_dump=lambda: {"source": "Reuters", "summary": "frost hit",
                                                   "driver_id": "frost", "commodity": "arabica_coffee"})
    monkeypatch.setattr(nx, "extract_events", lambda items, call=None, graph=None: [ev])
    body = _client(monkeypatch).get("/v1/events", params={"contract": "arabica_coffee"}).json()   # asof=today
    assert body["live"] is True and body["events"][0]["source"] == "Reuters"


# ── 1.7 share ────────────────────────────────────────────────────────────────────────────────────────
def test_share_roundtrip_pins_graph_version(monkeypatch):
    c = _client(monkeypatch)
    payload = {"answer": "A", "trace": {"graph_version": "gtest12ab34cd"}}
    sid = c.post("/v1/share", json={"question": "why frost", "asof": "2021-07-20", "payload": payload}).json()["id"]
    got = c.get(f"/v1/share/{sid}").json()
    assert got["question"] == "why frost" and got["graph_version"] == "gtest12ab34cd"
    assert got["payload"]["answer"] == "A"
    assert c.get("/v1/share/nope").status_code == 404


def test_watchlist_crud(monkeypatch):
    c = _client(monkeypatch)
    wid = c.post("/v1/watchlists", json={"body": {"contracts": ["corn", "arabica_coffee"]}}).json()["id"]
    items = c.get("/v1/watchlists").json()["items"]
    assert len(items) == 1 and items[0]["id"] == wid and items[0]["contracts"] == ["corn", "arabica_coffee"]
    assert c.delete(f"/v1/watchlists/{wid}").json()["ok"] is True
    assert c.get("/v1/watchlists").json()["items"] == []
