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


# ── P7-P0.6/0.7: shared Receipt contract + provenance reservations ───────────────────────────────────
def test_receipt_contract_roundtrips_all_kinds():
    # The ONE shared receipt shape A5 (per-claim confidence) and M6 (probability receipts) both consume.
    from leviathan.graphrag import api_models as M
    ev = M.Receipt(kind="evidence", label="USDA PSD, Apr 2024", detail="snippet...")
    an = M.Receipt(kind="analogue", label="7 of 30 analogue years", n=30, years=[1997, 2009, 2015])
    nu = M.Receipt(kind="number", label="S/U 0.02", confidence=0.9)
    assert ev.kind == "evidence" and an.n == 30 and an.years[0] == 1997 and nu.confidence == 0.9
    with pytest.raises(Exception):
        M.Receipt(kind="vibes", label="nope")                       # kind is enum-locked

def test_turn_and_share_accept_reserved_provenance_fields():
    # chunk_version / calibration_version are RESERVED — default None, accepted when populated.
    from leviathan.graphrag import api_models as M
    t = M.TurnRecord(question="q")
    assert t.chunk_version is None and t.calibration_version is None
    t2 = M.TurnRecord(question="q", chunk_version="c1abc", calibration_version="k9def")
    assert t2.chunk_version == "c1abc" and t2.calibration_version == "k9def"
    s = M.ShareSnapshot(id="x", question="q", created_at="2026-07-07", payload={})
    assert s.chunk_version is None and s.calibration_version is None

def test_receipt_reservation_is_openapi_zero_diff(monkeypatch):
    # Reservation doctrine: an unreferenced model must NOT appear in the OpenAPI dump (=> no types.gen drift).
    c = _client(monkeypatch)
    spec = sv.app.openapi()
    assert "Receipt" not in (spec.get("components", {}).get("schemas", {}))


# ── P7-P0.3: identity auth on the read routes (no quota increment on reads) ──────────────────────────
def test_read_routes_401_anon_when_auth_on(monkeypatch):
    # With auth ON and no bearer, every regime/data read route refuses — the probability layer (M2/M6)
    # must never land on an unauthenticated route (teardown CRITICAL #4).
    c = _client(monkeypatch, lookup=_lookup())
    monkeypatch.setenv("GRAPHRAG_AUTH", "on")
    for path in ("/v1/graph/arabica_coffee", "/v1/convergence", "/v1/regimes/arabica_coffee",
                 "/v1/series/silver_psd/ending_stocks_mt", "/v1/events"):
        r = c.get(path)
        assert r.status_code == 401, f"{path} -> {r.status_code} (expected 401 anon)"


def test_read_routes_ok_when_auth_off(monkeypatch):
    # Auth OFF (dev/eval/tests) stays a no-op: the identity dep resolves to the local user.
    monkeypatch.delenv("GRAPHRAG_AUTH", raising=False)
    c = _client(monkeypatch, lookup=_lookup())
    assert c.get("/v1/convergence").status_code == 200
    assert c.get("/v1/regimes/arabica_coffee").status_code == 200
    assert c.get("/v1/graph/arabica_coffee").status_code == 200


def test_read_routes_use_identity_not_quota(monkeypatch):
    # Read-heavy fetches must NOT burn the per-user daily respond quota: with a 1-turn quota set,
    # repeated convergence reads still succeed (the quota dep is only on the respond routes).
    monkeypatch.delenv("GRAPHRAG_AUTH", raising=False)
    monkeypatch.setenv("GRAPHRAG_TURN_QUOTA", "1")
    c = _client(monkeypatch, lookup=_lookup())
    for _ in range(3):
        assert c.get("/v1/convergence").status_code == 200


# ── 6.5 click-to-page route (GET /v1/citation/pdf) — auth + kill-switch + shape (resolver mocked) ────
def _mock_resolver(monkeypatch, fn):
    from leviathan.graphrag import pdfpage
    monkeypatch.setattr(pdfpage, "resolve_pdf_page", fn)


def test_citation_pdf_401_anon_when_auth_on(monkeypatch):
    # Read-route auth (P0.3): the click-to-page endpoint refuses an anonymous caller when auth is on.
    c = _client(monkeypatch)
    monkeypatch.setenv("GRAPHRAG_AUTH", "on")
    assert c.get("/v1/citation/pdf", params={"source_key": "text/x/document.json"}).status_code == 401


def test_citation_pdf_404_when_killswitch_off(monkeypatch):
    # GRAPHRAG_PDF_LINKS=off -> 404 (FE hides the affordance); the resolver is never even reached.
    monkeypatch.delenv("GRAPHRAG_AUTH", raising=False)
    monkeypatch.setenv("GRAPHRAG_PDF_LINKS", "off")
    _mock_resolver(monkeypatch, lambda *a, **k: (_ for _ in ()).throw(AssertionError("resolver called w/ switch off")))
    c = _client(monkeypatch)
    assert c.get("/v1/citation/pdf", params={"source_key": "text/x/document.json"}).status_code == 404


def test_citation_pdf_200_shape_with_mocked_resolver(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_AUTH", raising=False)
    monkeypatch.setenv("GRAPHRAG_PDF_LINKS", "on")
    seen = {}

    def fake(source_key, snippet=None, char_start=None, offset_kind=None):
        seen.update(source_key=source_key, snippet=snippet, char_start=char_start, offset_kind=offset_kind)
        return {"url": "https://s3.example/doc.pdf?e=900", "page": 4, "kind": "pdf", "expires_in": 900}

    _mock_resolver(monkeypatch, fake)
    c = _client(monkeypatch)
    r = c.get("/v1/citation/pdf", params={"source_key": "text/s/document.json", "snippet": "frost",
                                          "char_start": 12, "offset_kind": "exact"})
    assert r.status_code == 200
    assert r.json() == {"url": "https://s3.example/doc.pdf?e=900", "page": 4, "kind": "pdf", "expires_in": 900}
    assert seen == {"source_key": "text/s/document.json", "snippet": "frost", "char_start": 12,
                    "offset_kind": "exact"}                       # query params flow through verbatim


def test_citation_pdf_404_when_document_missing(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_AUTH", raising=False)
    from leviathan.graphrag import pdfpage

    def fake(*a, **k):
        raise pdfpage.PdfDocumentMissing("gone")

    _mock_resolver(monkeypatch, fake)
    c = _client(monkeypatch)
    assert c.get("/v1/citation/pdf", params={"source_key": "text/gone/document.json"}).status_code == 404


def test_citation_pdf_never_500_on_resolver_error(monkeypatch):
    # Belt+braces: even an unexpected resolver exception degrades to a 200 page-null shape, never a 500.
    monkeypatch.delenv("GRAPHRAG_AUTH", raising=False)
    _mock_resolver(monkeypatch, lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    c = _client(monkeypatch)
    r = c.get("/v1/citation/pdf", params={"source_key": "text/s/document.json"})
    assert r.status_code == 200 and r.json()["page"] is None
