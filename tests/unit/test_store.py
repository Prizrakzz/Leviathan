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
