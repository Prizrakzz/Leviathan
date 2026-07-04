"""FastAPI serving conductor — mocked respond()/graph (no LLM, no evidence store, no AWS).

Pins: the thin-conductor contract (server passes question/asof/session_id through to respond() and
returns its dict untouched), the healthz shape the load balancer will probe, and the SSE stream's
terminal `result` event carrying the payload.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from leviathan.graphrag import server as sv


class _FakeGraph:
    contracts = {"arabica_coffee": object(), "corn": object()}


def _client(monkeypatch, respond_fn):
    monkeypatch.setitem(sv._STATE, "graph", _FakeGraph())
    from leviathan.graphrag import orchestrator as orch
    monkeypatch.setattr(orch, "respond", respond_fn)
    return TestClient(sv.app)


def test_healthz_reports_graph_and_provider(monkeypatch):
    monkeypatch.setitem(sv._STATE, "graph", _FakeGraph())
    monkeypatch.delenv("GRAPHRAG_PROVIDER", raising=False)
    r = TestClient(sv.app).get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["contracts"] == 2 and body["provider"] in ("anthropic", "bedrock")


def test_respond_route_passes_args_through_and_returns_dict(monkeypatch):
    seen = {}

    def fake_respond(query, *, graph, asof=None, session_id=None, **kw):
        seen.update(query=query, asof=asof, session_id=session_id, graph=graph)
        return {"answer": "A", "intent": "reasoning", "trace": {}}

    c = _client(monkeypatch, fake_respond)
    r = c.post("/v1/respond", json={"question": "corn outlook", "asof": "2024-01-01", "session_id": "s1"})
    assert r.status_code == 200 and r.json()["answer"] == "A"
    assert seen["query"] == "corn outlook" and seen["asof"] == "2024-01-01" and seen["session_id"] == "s1"
    assert isinstance(seen["graph"], _FakeGraph)


def test_sse_stream_emits_stage_then_result(monkeypatch):
    def fake_respond(query, *, graph, asof=None, session_id=None, **kw):
        return {"answer": "streamed", "intent": "reasoning"}

    c = _client(monkeypatch, fake_respond)
    with c.stream("GET", "/v1/respond/stream", params={"question": "corn outlook"}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        text = "".join(chunk for chunk in r.iter_text())
    assert "event: stage" in text and "event: result" in text
    payload = json.loads(text.split("event: result\ndata: ", 1)[1].split("\n\n", 1)[0])
    assert payload["answer"] == "streamed"


def test_sse_stream_reports_error_event_when_respond_raises(monkeypatch):
    def dead_respond(query, *, graph, asof=None, session_id=None, **kw):
        raise RuntimeError("boom")

    c = _client(monkeypatch, dead_respond)
    with c.stream("GET", "/v1/respond/stream", params={"question": "x"}) as r:
        text = "".join(chunk for chunk in r.iter_text())
    assert "event: error" in text and "RuntimeError" in text
