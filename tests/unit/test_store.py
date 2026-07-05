"""Durable store + share snapshots + auth dependency (build-plan P1.7) — no AWS, no token infra."""
from __future__ import annotations

import pytest

from leviathan.graphrag import auth
from leviathan.graphrag import store as st


def test_inmemory_share_roundtrip():
    s = st.InMemoryStore()
    snap = st.make_share("q", "2021-07-20", {"answer": "A", "trace": {"graph_version": "gv123"}})
    s.put_share(snap)
    got = s.get_share(snap.id)
    assert got.question == "q" and got.graph_version == "gv123" and got.payload["answer"] == "A"
    assert s.get_share("missing") is None


def test_inmemory_user_items_scoped_by_user_and_kind():
    s = st.InMemoryStore()
    s.put_item("u1", "watchlist", "w1", {"contracts": ["corn"]})
    s.put_item("u1", "thread", "t1", {"title": "x"})
    s.put_item("u2", "watchlist", "w9", {"contracts": ["soy"]})
    wl = s.list_items("u1", "watchlist")
    assert len(wl) == 1 and wl[0]["id"] == "w1" and wl[0]["contracts"] == ["corn"]   # u2's item not leaked
    s.delete_item("u1", "watchlist", "w1")
    assert s.list_items("u1", "watchlist") == []


def test_make_share_pins_graph_version_from_trace():
    snap = st.make_share("q", None, {"trace": {"graph_version": "abc"}})
    assert snap.graph_version == "abc" and snap.id


def test_inmemory_turns_roundtrip_scoped_and_ordered():
    s = st.InMemoryStore()
    s.append_turn("u1", "thread-A", {"question": "q1", "answer": "a1"})
    s.append_turn("u1", "thread-A", {"question": "q2", "answer": "a2"})
    s.append_turn("u1", "thread-B", {"question": "other"})
    s.append_turn("u2", "thread-A", {"question": "u2 secret"})            # different user
    turns = s.list_turns("u1", "thread-A")
    assert [t["question"] for t in turns] == ["q1", "q2"]                 # append order preserved
    assert all("ts" in t for t in turns)                                 # ts stamped
    assert s.list_turns("u1", "thread-B")[0]["question"] == "other"      # thread-scoped
    assert s.list_turns("u1", "thread-A") != s.list_turns("u2", "thread-A")  # user-scoped, no leak


def test_sanitize_turn_pit_firewall_drops_evidence():
    """The load-bearing invariant: a durable turn NEVER carries retrieved evidence, raw number rows, or the
    trace (which embeds resolved evidence text). Only the conclusion + citation refs survive."""
    full = {
        "question": "KC frost?",
        "answer": "",
        "structured": {"tldr": "convex spike", "sources": [{"ref": 1}]},
        "asof": "2021-07-20",
        "citations": [{"kind": "evidence", "ref": 1, "source": "usda_gain", "date": "2021-07-20"}],
        "graph_version": "gv1",
        "contract": "arabica_coffee",
        # everything below MUST be stripped:
        "evidence": [{"text": "secret frost report body", "source_key": "s3://gain/x"}],
        "number_calls": [{"rows": [{"value": "0.36"}]}],
        "trace": {"graph_version": "gv1", "citation_verifier": {"resolved": {"1": {"text": "evidence text"}}}},
    }
    rec = st.sanitize_turn(full)
    assert "evidence" not in rec and "number_calls" not in rec and "trace" not in rec and "citations" not in rec
    assert rec["question"] == "KC frost?" and rec["contract"] == "arabica_coffee"
    assert rec["structured"]["tldr"] == "convex spike"
    blob = str(rec)
    assert "secret frost report body" not in blob and "evidence text" not in blob


def test_append_turn_enforces_firewall_at_store_layer():
    """Even if a caller passes a raw payload, the store strips it (defense in depth)."""
    s = st.InMemoryStore()
    s.append_turn("u1", "t1", {"question": "q", "evidence": [{"text": "leak"}], "trace": {"resolved": "x"}})
    got = s.list_turns("u1", "t1")[0]
    assert "evidence" not in got and "trace" not in got and "leak" not in str(got)


def test_auth_off_returns_local_user(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_AUTH", raising=False)
    assert auth.user_from_header(None) == auth.LOCAL_USER
    assert auth.user_from_header("Bearer whatever") == auth.LOCAL_USER            # off -> token ignored entirely


def test_auth_on_requires_and_verifies_token(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_AUTH", "on")
    with pytest.raises(ValueError):
        auth.user_from_header(None)                                              # missing bearer -> reject
    monkeypatch.setattr(auth, "verify_token", lambda t: "user-123")             # stub JWKS/JWT verify
    assert auth.user_from_header("Bearer good.jwt.here") == "user-123"
