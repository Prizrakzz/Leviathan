"""D-AM-15 -- the `artifacts` collection: a NAMED, PRIVATE freeze of one answer turn.

The wave's whole point is that artifacts are not a new subsystem: they are one tuple entry on the SAME
per-user collection factory threads/watchlists/workspaces ride, so they inherit that factory's identity
gate for free, and their freeze is `store.make_share` -- the same one the public share link uses -- so the
two can never pin different (payload, asof, graph_version) triples. These tests hold exactly those two
claims, plus the privacy the gate is supposed to buy.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from leviathan.graphrag import server as sv
from leviathan.graphrag import store as st

PAYLOAD = {"answer": "A", "structured": {"tldr": "headline"}, "trace": {"graph_version": "gdam15aa99cc"}}
BODY = {"name": "KC frost convexity", "question": "why frost", "asof": "2021-07-20", "payload": PAYLOAD}


def _client(monkeypatch) -> TestClient:
    monkeypatch.setitem(sv._STATE, "store", st.InMemoryStore())
    monkeypatch.delenv("GRAPHRAG_AUTH", raising=False)
    return TestClient(sv.app)


def _as_user(monkeypatch, sub: str) -> dict:
    """Auth ON with a stubbed verifier: the bearer string IS the subject. Patching `_verified_claims` covers
    BOTH dependencies -- `_require_identity` calls it directly, `_require_user` reaches it via verify_token."""
    from leviathan.graphrag import auth
    monkeypatch.setenv("GRAPHRAG_AUTH", "on")
    monkeypatch.setattr(auth, "_verified_claims", lambda token: {"sub": token})
    return {"Authorization": f"Bearer {sub}"}


def _registered() -> set:
    return {(r.path, m) for r in sv.app.routes for m in (getattr(r, "methods", None) or set())}


# -- registration on the shared factory ---------------------------------------------------------------
def test_artifacts_register_the_full_collection_triple():
    reg = _registered()
    assert ("/v1/artifacts", "GET") in reg          # listable
    assert ("/v1/artifacts", "POST") in reg         # named + saveable
    assert ("/v1/artifacts/{item_id}", "DELETE") in reg


def test_artifacts_use_the_same_dependencies_as_the_other_collections():
    # The gate is inherited, not re-implemented: the artifacts routes must hang off the SAME dependency
    # callables the watchlists routes do. A hand-rolled route with its own (or no) gate fails here.
    def deps(path, method):
        r = next(r for r in sv.app.routes
                 if r.path == path and method in (getattr(r, "methods", None) or set()))
        return {d.call for d in r.dependant.dependencies}

    assert deps("/v1/artifacts", "GET") == deps("/v1/watchlists", "GET") == {sv._require_identity}
    assert deps("/v1/artifacts", "POST") == deps("/v1/watchlists", "POST") == {sv._require_user}
    assert deps("/v1/artifacts/{item_id}", "DELETE") == {sv._require_user}


# -- the freeze ---------------------------------------------------------------------------------------
def test_artifact_stores_the_full_frozen_payload_and_pins_graph_version(monkeypatch):
    c = _client(monkeypatch)
    aid = c.post("/v1/artifacts", json={"body": BODY}).json()["id"]
    items = c.get("/v1/artifacts").json()["items"]
    assert len(items) == 1 and items[0]["id"] == aid
    assert items[0]["name"] == "KC frost convexity"
    snap = items[0]["snapshot"]
    # Reproducibility is the product: the WHOLE payload is kept, not a pointer to a re-runnable question.
    assert snap["payload"] == PAYLOAD
    assert snap["question"] == "why frost" and snap["asof"] == "2021-07-20"
    assert snap["graph_version"] == "gdam15aa99cc"        # pinned from payload.trace by make_share
    assert set(snap) == {"id", "question", "asof", "graph_version", "created_at", "payload"}
    assert items[0]["updated_at"] == snap["created_at"]   # server-stamped: the list sorts on it


def test_freeze_reuses_make_share_rather_than_inventing_a_second_one(monkeypatch):
    c = _client(monkeypatch)
    calls = []
    real = st.make_share

    def spy(question, asof, payload, **kw):
        calls.append((question, asof, payload))
        return real(question, asof, payload, **kw)

    monkeypatch.setattr(st, "make_share", spy)
    assert c.post("/v1/artifacts", json={"body": BODY}).status_code == 200
    assert calls == [("why frost", "2021-07-20", PAYLOAD)]


def test_artifact_and_share_of_the_same_turn_pin_identically(monkeypatch):
    c = _client(monkeypatch)
    sid = c.post("/v1/share", json={"question": "why frost", "asof": "2021-07-20",
                                    "payload": PAYLOAD}).json()["id"]
    share = c.get(f"/v1/share/{sid}").json()
    c.post("/v1/artifacts", json={"body": BODY})
    snap = c.get("/v1/artifacts").json()["items"][0]["snapshot"]
    for k in ("question", "asof", "graph_version", "payload"):
        assert snap[k] == share[k], k


def test_unnamed_artifact_falls_back_to_the_question_never_blank(monkeypatch):
    c = _client(monkeypatch)
    c.post("/v1/artifacts", json={"body": {**BODY, "name": "   "}})
    assert c.get("/v1/artifacts").json()["items"][0]["name"] == "why frost"


def test_artifact_survives_a_payload_free_body(monkeypatch):
    # A malformed/empty POST must not 500 the collection -- it freezes an empty payload instead.
    c = _client(monkeypatch)
    assert c.post("/v1/artifacts", json={"body": {}}).status_code == 200
    snap = c.get("/v1/artifacts").json()["items"][0]["snapshot"]
    assert snap["payload"] == {} and snap["graph_version"] is None


def test_artifact_delete_removes_it(monkeypatch):
    c = _client(monkeypatch)
    aid = c.post("/v1/artifacts", json={"body": BODY}).json()["id"]
    assert c.delete(f"/v1/artifacts/{aid}").json()["ok"] is True
    assert c.get("/v1/artifacts").json()["items"] == []


# -- the gate -----------------------------------------------------------------------------------------
def test_artifacts_401_anon_when_auth_on(monkeypatch):
    c = _client(monkeypatch)
    monkeypatch.setenv("GRAPHRAG_AUTH", "on")
    assert c.get("/v1/artifacts").status_code == 401
    assert c.post("/v1/artifacts", json={"body": BODY}).status_code == 401
    assert c.delete("/v1/artifacts/whatever").status_code == 401


def test_artifacts_are_private_to_their_owner(monkeypatch):
    # The ratified split: share links are public, artifacts are NOT. One user's saved research must be
    # invisible (and undeletable) to another even with a perfectly valid token of their own.
    c = _client(monkeypatch)
    alice = _as_user(monkeypatch, "alice")
    bob = {"Authorization": "Bearer bob"}
    aid = c.post("/v1/artifacts", json={"body": BODY}, headers=alice).json()["id"]
    assert c.get("/v1/artifacts", headers=bob).json()["items"] == []
    c.delete(f"/v1/artifacts/{aid}", headers=bob)
    assert [i["id"] for i in c.get("/v1/artifacts", headers=alice).json()["items"]] == [aid]


# -- the other collections are untouched --------------------------------------------------------------
def test_the_freeze_hook_is_artifacts_only(monkeypatch):
    # The factory gained a `freeze` seam; every pre-existing collection passes None, so its stored body is
    # still the client's verbatim dict (no snapshot wrapper, no server-stamped timestamps).
    c = _client(monkeypatch)
    wid = c.post("/v1/watchlists", json={"body": {"contracts": ["corn"]}}).json()["id"]
    item = c.get("/v1/watchlists").json()["items"][0]
    assert item == {"contracts": ["corn"], "id": wid, "kind": "watchlist"}
