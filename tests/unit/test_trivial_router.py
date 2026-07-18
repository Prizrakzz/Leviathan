"""Trivial-turn router (F1) — orchestrator short-circuit + canned mentor replies (no S3/Athena/LLM spend).

The seam sits immediately after the guardrail early-return and BEFORE session load, so a short-circuited
greeting never runs dispatch/synthesis and never touches session state. Kill-switch: GRAPHRAG_TRIVIAL_ROUTER
(default off). Everything here is hermetic — a sentinel classifier proves whether dispatch was reached without
running the (network-bound) reasoning pipeline.
"""
from __future__ import annotations

import pytest

from leviathan.causal import schema as cs
from leviathan.graphrag import graph as g
from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag import register as reg
from leviathan.graphrag import session as ss


def _graph() -> g.CausalGraph:
    coffee = cs.CausalContract(contract="arabica_coffee", aliases=["arabica"],
                               drivers=[cs.Driver(id="frost", type="hazard", sign="+", mechanism="frost")])
    corn = cs.CausalContract(contract="corn", aliases=["maize"],
                             drivers=[cs.Driver(id="drought", type="hazard", sign="+", mechanism="dry")])
    return g.CausalGraph({"arabica_coffee": coffee, "corn": corn}, silver=set())


class _Reached(Exception):
    """Raised by the sentinel classifier -> proves the turn fell THROUGH to the planner (no short-circuit)."""


def _reached(query, call=None):
    raise _Reached(query)


@pytest.fixture(autouse=True)
def _flag_off(monkeypatch):
    # default every test to flag-OFF; the ON tests opt in explicitly. Keeps the kill-switch the default.
    monkeypatch.delenv("GRAPHRAG_TRIVIAL_ROUTER", raising=False)


# ── kill-switch ───────────────────────────────────────────────────────────────────────────────────────────
def test_flag_off_greeting_falls_through_to_dispatch(monkeypatch):
    # OFF: "hi" is NOT short-circuited -> it reaches the classifier (the sentinel raises).
    with pytest.raises(_Reached):
        orch.respond("hi", graph=_graph(), asof="2024-06-01", classify=_reached)


def test_flag_on_greeting_short_circuits(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_TRIVIAL_ROUTER", "on")
    out = orch.respond("hi", graph=_graph(), asof="2024-06-01", classify=_reached)   # classifier must NOT run
    assert out["intent"] == "social" and out["model"] == "(canned)"
    assert out["citations"] == [] and out["evidence"] == [] and out["number_calls"] == []
    assert out["structured"] is None and out["contract"] is None and out["contracts"] == []
    assert out["intent_decision"] == {"intent": "social", "trivial": "greeting"}
    assert out["trace"]["trivial"] == {"class": "greeting", "starters": True}
    assert out["answer"] and reg.register_leaks(out["answer"]) == []


def test_flag_on_meta_and_smalltalk_short_circuit(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_TRIVIAL_ROUTER", "on")
    meta = orch.respond("what can you do", graph=_graph(), classify=_reached)
    assert meta["intent"] == "social" and meta["trace"]["trivial"]["class"] == "meta"
    talk = orch.respond("thanks!", graph=_graph(), classify=_reached)
    assert talk["intent"] == "social" and talk["trace"]["trivial"]["class"] == "smalltalk"


def test_flag_on_hijack_greeting_falls_through(monkeypatch):
    # the headline requirement: "hi, also what is wheat doing" MUST fall through even with the router ON.
    monkeypatch.setenv("GRAPHRAG_TRIVIAL_ROUTER", "on")
    with pytest.raises(_Reached):
        orch.respond("hi, also what is wheat doing", graph=_graph(), asof="2024-06-01", classify=_reached)


def test_flag_on_real_question_falls_through(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_TRIVIAL_ROUTER", "on")
    with pytest.raises(_Reached):
        orch.respond("why is coffee bullish", graph=_graph(), asof="2024-06-01", classify=_reached)


# ── register 0-leak on the canned replies (HARD gate; a future edit cannot regress it) ─────────────────────
def test_canned_replies_are_register_clean():
    assert set(orch._TRIVIAL_REPLIES) == {"greeting", "smalltalk", "meta"}
    for klass, text in orch._TRIVIAL_REPLIES.items():
        assert reg.register_leaks(text) == [], (klass, reg.register_leaks(text))
        assert reg._MOOD.findall(text) == [], (klass, reg._MOOD.findall(text))
        assert 0 < len(text) <= 600                              # 1-2 lines, mentor register
        assert "_" not in text                                  # no raw internal slugs


def test_trivial_answer_shape_matches_guardrail_contract():
    # mirrors _guardrail_check's respond()-shaped early return so the FE/_save_turn path is unchanged.
    d = orch._trivial_answer("hi", "greeting")
    for key in ("answer", "structured", "contract", "contracts", "citations", "evidence",
                "model", "intent", "intent_decision", "trace"):
        assert key in d, key
    assert d["model"] == "(canned)" and d["intent"] == "social"


# ── session state UNTOUCHED: a greeting must not persist a turn or wipe coreference/as-of ──────────────────
class _SpyStore(ss.InMemoryStore):
    def __init__(self):
        super().__init__()
        self.loads = 0
        self.appends = 0

    def load(self, session_id):
        self.loads += 1
        return super().load(session_id)

    def append_turn(self, session_id, turn):
        self.appends += 1
        super().append_turn(session_id, turn)


def test_flag_on_greeting_does_not_touch_session_state(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_TRIVIAL_ROUTER", "on")
    store = _SpyStore()
    sid = "sess-1"
    seeded = ss.SessionState(contracts=["arabica_coffee"], asof_latest="2021-08-01",
                             focus_driver="frost", turn_count=3)
    store.put_state(sid, seeded)

    out = orch.respond("hi", graph=_graph(), session_id=sid, session_store=store, classify=_reached)
    assert out["intent"] == "social"                            # short-circuited
    # the short-circuit returns ABOVE session load AND above _session_writeback -> store never touched:
    assert store.loads == 0 and store.appends == 0
    after = store._state[sid]
    assert after.contracts == ["arabica_coffee"] and after.asof_latest == "2021-08-01"
    assert after.focus_driver == "frost" and after.turn_count == 3   # coreference/as-of carry intact
    assert store._turns == {}                                        # no greeting persisted to thread history


# ── SSE: the canned reply streams as a NORMAL turn (one terminal `result` event) ──────────────────────────
def test_sse_stream_relays_canned_greeting_as_normal_turn(monkeypatch):
    """The SSE path runs the REAL orchestrator in a worker and relays its dict; a short-circuited greeting
    must arrive as exactly one terminal `result` event (with the canned social payload), preceded by stage
    ticks -- no special stream handling, it is a normal respond() dict."""
    import json

    from fastapi.testclient import TestClient
    from leviathan.graphrag import server as sv

    monkeypatch.setenv("GRAPHRAG_TRIVIAL_ROUTER", "on")
    monkeypatch.setitem(sv._STATE, "graph", _graph())            # real graph; the greeting returns before using it
    c = TestClient(sv.app)
    with c.stream("GET", "/v1/respond/stream", params={"question": "hi"}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        text = "".join(chunk for chunk in r.iter_text())
    assert text.count("event: result") == 1 and "event: error" not in text
    payload = json.loads(text.split("event: result\ndata: ", 1)[1].split("\n\n", 1)[0])
    assert payload["intent"] == "social" and payload["model"] == "(canned)"
    assert payload["trace"]["trivial"]["class"] == "greeting"
    assert "event: stage" in text                               # the accepted ack + the 'social' tick
