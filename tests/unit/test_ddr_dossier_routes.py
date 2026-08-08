"""D-DR-1/2/5 -- the dossier HTTP surface: gate, auth, quota, SSE (hermetic; no LLM, no AWS).

The routes are a thin conductor over `dossier.py`, so these pin exactly the HTTP-shaped claims and
nothing else:
  * DARK-FIRST -- GRAPHRAG_DOSSIER absent means all four routes 404, indistinguishable from a build
    that never had them; a principal outside a non-wildcard allowlist gets the same 404, never a 403
    (a feature you are not in must not be advertised);
  * the LOCKED wire contract -- 202 {dossier_id, plan_pending}, the GET body's key set, 429 carrying
    reset_at at the TOP level, and the quota GET;
  * auth first -- an anonymous caller is 401 before any dossier logic runs;
  * SSE ordering + late attach -- a client connecting after the plan landed still sees the plan.
"""
from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from leviathan.graphrag import dossier as dsr
from leviathan.graphrag import server as sv
from leviathan.graphrag import store as st

ROUTES = ("/v1/dossier", "/v1/dossier/quota", "/v1/dossier/{dossier_id}",
          "/v1/dossier/{dossier_id}/events")


class _FakeGraph:
    contracts = {"corn": object()}
    version = "gddr02aabbcc"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("GRAPHRAG_DOSSIER", "GRAPHRAG_DOSSIER_ADMINS", "GRAPHRAG_AUTH"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setitem(sv._STATE, "graph", _FakeGraph())
    monkeypatch.setitem(sv._STATE, "store", st.InMemoryStore())


def _client() -> TestClient:
    return TestClient(sv.app)


def _as_user(monkeypatch, sub: str) -> dict:
    """Auth ON with a stubbed verifier: the bearer string IS the subject (the test_dam_artifacts idiom)."""
    from leviathan.graphrag import auth
    monkeypatch.setenv("GRAPHRAG_AUTH", "on")
    monkeypatch.setattr(auth, "_verified_claims", lambda token: {"sub": token})
    return {"Authorization": f"Bearer {sub}"}


def _stub_job(monkeypatch, *, status=dsr.DONE, artifact_id="art-1"):
    """Replace the whole orchestration with a job that lands immediately -- these tests are about HTTP."""
    def start(store, ident, question, asof, *, graph, respond=None, quota_period=None, thread=True):
        job = dsr.Job("d-fixed", ident["sub"], question, asof, quota_period=quota_period)
        dsr.register(job)
        job.emit("plan", title="T", n=1,
                 subqueries=[{"i": 1, "n": 1, "title": "One", "question": "q1?", "config": "quick",
                              "rationale": "r"}])
        job.subqueries = [{"i": 1, "n": 1, "title": "One", "status": dsr.SQ_OK}]
        job.plan = {"title": "T", "subqueries": job.subqueries}
        job.status, job.stage, job.artifact_id = status, status, artifact_id
        job.emit(status, artifact_id=artifact_id)
        dsr.persist(store, job)
        return job

    monkeypatch.setattr(dsr, "start", start)


# ══ 1. THE DARK GATE ═════════════════════════════════════════════════════════════════════════════════
def test_all_four_routes_are_registered():
    reg = {(r.path, m) for r in sv.app.routes for m in (getattr(r, "methods", None) or set())}
    assert ("/v1/dossier", "POST") in reg
    assert ("/v1/dossier/quota", "GET") in reg
    assert ("/v1/dossier/{dossier_id}", "GET") in reg
    assert ("/v1/dossier/{dossier_id}/events", "GET") in reg


def test_the_quota_route_is_registered_before_the_id_route():
    """Ordering is load-bearing: FastAPI matches in registration order, so `/v1/dossier/quota` must be
    declared BEFORE `/v1/dossier/{dossier_id}` or the badge read becomes a lookup for a dossier
    called 'quota'."""
    paths = [r.path for r in sv.app.routes if str(r.path).startswith("/v1/dossier")]
    assert paths.index("/v1/dossier/quota") < paths.index("/v1/dossier/{dossier_id}")


def test_every_route_404s_when_the_flag_is_absent():
    c = _client()
    assert c.post("/v1/dossier", json={"question": "corn?"}).status_code == 404
    assert c.get("/v1/dossier/quota").status_code == 404
    assert c.get("/v1/dossier/anything").status_code == 404
    assert c.get("/v1/dossier/anything/events").status_code == 404


def test_a_principal_outside_the_allowlist_gets_404_not_403(monkeypatch):
    h = _as_user(monkeypatch, "u-carol")
    monkeypatch.setenv("GRAPHRAG_DOSSIER", "u-alice,u-bob")
    c = _client()
    assert c.get("/v1/dossier/quota", headers=h).status_code == 404
    assert c.get("/v1/dossier/quota", headers={"Authorization": "Bearer u-alice"}).status_code == 200


def test_auth_runs_before_the_gate(monkeypatch):
    """401 for an anonymous caller even with the flag on -- the dependency resolves before the handler."""
    _as_user(monkeypatch, "u-alice")
    monkeypatch.setenv("GRAPHRAG_DOSSIER", "on")
    c = _client()
    assert c.post("/v1/dossier", json={"question": "corn?"}).status_code == 401
    assert c.get("/v1/dossier/quota").status_code == 401
    assert c.get("/v1/dossier/x").status_code == 401
    assert c.get("/v1/dossier/x/events").status_code == 401


def test_the_dossier_routes_use_the_same_identity_dependency_as_the_rest_of_the_api():
    def deps(path, method):
        r = next(r for r in sv.app.routes
                 if r.path == path and method in (getattr(r, "methods", None) or set()))
        return {d.call for d in r.dependant.dependencies}

    for path, method in (("/v1/dossier", "POST"), ("/v1/dossier/quota", "GET"),
                         ("/v1/dossier/{dossier_id}", "GET"),
                         ("/v1/dossier/{dossier_id}/events", "GET")):
        assert deps(path, method) == {sv._require_identity}, (path, method)


# ══ 2. ACCEPTANCE ════════════════════════════════════════════════════════════════════════════════════
def test_post_returns_202_with_the_locked_body(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_DOSSIER", "on")
    _stub_job(monkeypatch)
    r = _client().post("/v1/dossier", json={"question": "what breaks corn?", "asof": "2026-08-01"})
    assert r.status_code == 202
    assert r.json() == {"dossier_id": "d-fixed", "plan_pending": True}
    dsr.forget("d-fixed")


def test_a_missing_or_malformed_asof_is_rejected_loudly(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_DOSSIER", "on")
    _stub_job(monkeypatch)
    c = _client()
    assert c.post("/v1/dossier", json={"question": "  "}).status_code == 422
    assert c.post("/v1/dossier", json={"question": "q", "asof": "last tuesday"}).status_code == 422
    # Absent as-of defaults to today, which is the normal desk path.
    assert c.post("/v1/dossier", json={"question": "q"}).status_code == 202
    dsr.forget("d-fixed")


def test_one_asof_is_stamped_at_submission_and_reaches_the_job(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_DOSSIER", "on")
    seen = {}

    def start(store, ident, question, asof, **kw):
        seen.update(question=question, asof=asof, sub=ident["sub"])
        job = dsr.Job("d-asof", ident["sub"], question, asof)
        job.status = dsr.DONE
        return job

    monkeypatch.setattr(dsr, "start", start)
    _client().post("/v1/dossier", json={"question": "corn?", "asof": "2021-07-20"})
    assert seen == {"question": "corn?", "asof": "2021-07-20", "sub": "local"}


# ══ 3. QUOTA OVER HTTP ═══════════════════════════════════════════════════════════════════════════════
def test_quota_route_shape_and_the_429_carries_reset_at(monkeypatch):
    h = _as_user(monkeypatch, "u-alice")
    monkeypatch.setenv("GRAPHRAG_DOSSIER", "on")
    _stub_job(monkeypatch)
    c = _client()
    q = c.get("/v1/dossier/quota", headers=h).json()
    assert q["limit"] == 4 and q["remaining"] == 4 and q["reset_at"].endswith("Z")
    assert q["reset_at"].endswith("-01T00:00:00Z")        # D-DR-2b: the first instant of the next month
    for i in range(dsr.QUOTA_LIMIT):
        assert c.post("/v1/dossier", json={"question": f"q{i}"}, headers=h).status_code == 202
        dsr.forget("d-fixed")
    assert c.get("/v1/dossier/quota", headers=h).json()["remaining"] == 0
    r = c.post("/v1/dossier", json={"question": "one too many"}, headers=h)
    assert r.status_code == 429
    body = r.json()
    assert body["remaining"] == 0 and body["limit"] == 4 and body["reset_at"] == q["reset_at"]
    assert "month" in body["error"]                      # the refusal names the window it will lift in


def test_quota_is_per_principal(monkeypatch):
    alice = _as_user(monkeypatch, "u-alice")
    bob = {"Authorization": "Bearer u-bob"}
    monkeypatch.setenv("GRAPHRAG_DOSSIER", "on")
    _stub_job(monkeypatch)
    c = _client()
    for i in range(dsr.QUOTA_LIMIT):
        c.post("/v1/dossier", json={"question": f"q{i}"}, headers=alice)
        dsr.forget("d-fixed")
    assert c.get("/v1/dossier/quota", headers=alice).json()["remaining"] == 0
    assert c.get("/v1/dossier/quota", headers=bob).json()["remaining"] == dsr.QUOTA_LIMIT


def test_the_eval_lane_never_consumes_quota(monkeypatch):
    """Auth off = dev/eval deployment: no principal to charge, and the route is still flag-gated."""
    monkeypatch.setenv("GRAPHRAG_DOSSIER", "on")
    _stub_job(monkeypatch)
    c = _client()
    for i in range(dsr.QUOTA_LIMIT + 2):
        assert c.post("/v1/dossier", json={"question": f"q{i}"}).status_code == 202
        dsr.forget("d-fixed")
    assert c.get("/v1/dossier/quota").json() == {"remaining": 4, "limit": 4, "bypass": True,
                                                 "reset_at": dsr.month_reset_at()}


# ══ 4. GET ═══════════════════════════════════════════════════════════════════════════════════════════
def test_get_returns_the_locked_wire_shape(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_DOSSIER", "on")
    _stub_job(monkeypatch)
    c = _client()
    did = c.post("/v1/dossier", json={"question": "corn?"}).json()["dossier_id"]
    body = c.get(f"/v1/dossier/{did}").json()
    assert body["dossier_id"] == did and body["status"] == dsr.DONE
    assert body["artifact_id"] == "art-1" and body["stage"] == dsr.DONE
    assert body["subqueries"] == [{"i": 1, "n": 1, "title": "One", "status": dsr.SQ_OK}]
    assert set(body) <= {"dossier_id", "status", "stage", "question", "asof", "created_at",
                         "title", "subqueries", "artifact_id", "error"}
    dsr.forget(did)


def test_get_works_across_requests_from_the_store(monkeypatch):
    """The job registry is in-process; the STORE is what makes GET survive the accepting request."""
    monkeypatch.setenv("GRAPHRAG_DOSSIER", "on")
    _stub_job(monkeypatch)
    c = _client()
    did = c.post("/v1/dossier", json={"question": "corn?"}).json()["dossier_id"]
    dsr.forget(did)                                   # simulate: the job object is gone, the item is not
    body = c.get(f"/v1/dossier/{did}").json()
    assert body["dossier_id"] == did and body["status"] == dsr.DONE and body["artifact_id"] == "art-1"


def test_an_unknown_dossier_is_404(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_DOSSIER", "on")
    assert _client().get("/v1/dossier/nope").status_code == 404


def test_a_dossier_is_private_to_its_owner(monkeypatch):
    alice = _as_user(monkeypatch, "u-alice")
    bob = {"Authorization": "Bearer u-bob"}
    monkeypatch.setenv("GRAPHRAG_DOSSIER", "on")
    _stub_job(monkeypatch)
    c = _client()
    did = c.post("/v1/dossier", json={"question": "corn?"}, headers=alice).json()["dossier_id"]
    dsr.forget(did)                                   # force the store read (owner-scoped partition)
    assert c.get(f"/v1/dossier/{did}", headers=bob).status_code == 404
    assert c.get(f"/v1/dossier/{did}", headers=alice).status_code == 200


def test_a_restart_orphan_is_reported_failed_and_refunded(monkeypatch):
    h = _as_user(monkeypatch, "u-alice")
    monkeypatch.setenv("GRAPHRAG_DOSSIER", "on")
    store = sv._STATE["store"]
    for _ in range(dsr.QUOTA_LIMIT):                  # month fully spent, one of them by the orphan
        store.incr_turn_quota("u-alice", dsr.quota_period(), dsr.QUOTA_LIMIT)
    store.put_item("u-alice", dsr.KIND, "orphan",
                   {"dossier_id": "orphan", "status": dsr.RUNNING, "stage": "subquery 3/6",
                    "quota_period": dsr.quota_period(), "subqueries": [], "events": []})
    c = _client()
    body = c.get("/v1/dossier/orphan", headers=h).json()
    assert body["status"] == dsr.FAILED and "restarted" in body["error"]
    assert c.get("/v1/dossier/quota", headers=h).json()["remaining"] == 1


# ══ 5. SSE ═══════════════════════════════════════════════════════════════════════════════════════════
def _events(text: str) -> list[tuple[str, dict]]:
    out = []
    for blk in text.split("\n\n"):
        if not blk.startswith("event: "):
            continue
        head, _, data = blk.partition("\ndata: ")
        out.append((head[len("event: "):], json.loads(data)))
    return out


def test_sse_replays_history_then_closes_on_the_terminal_event(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_DOSSIER", "on")
    _stub_job(monkeypatch)
    c = _client()
    did = c.post("/v1/dossier", json={"question": "corn?"}).json()["dossier_id"]
    with c.stream("GET", f"/v1/dossier/{did}/events") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        text = "".join(chunk for chunk in r.iter_text())
    evs = _events(text)
    assert [k for k, _ in evs] == ["plan", dsr.DONE]      # a LATE subscriber still sees the plan
    assert evs[0][1]["subqueries"][0]["question"] == "q1?"
    assert evs[-1][1]["artifact_id"] == "art-1"           # the terminal event carries the artifact id
    dsr.forget(did)


def test_sse_streams_live_stage_transitions_in_order(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_DOSSIER", "on")
    job = dsr.Job("d-live", "local", "corn?", "2026-08-01")
    dsr.register(job)
    dsr.persist(sv._STATE["store"], job)

    def feed():
        for kind, info in (("plan", {"n": 2}), ("subquery", {"i": 1}), ("subquery", {"i": 2}),
                           ("synthesis", {"notes": 2}), (dsr.PARTIAL, {"artifact_id": "a9"})):
            time.sleep(0.02)
            job.emit(kind, **info)
        job.status = dsr.PARTIAL

    # Started BEFORE the request: starlette's TestClient runs the ASGI app to completion inside
    # `stream()`, so a producer started after it would never get a turn. The ordering assertion holds
    # either way -- events emitted before the subscriber attaches arrive on the REPLAY leg, which is
    # the same list in the same order (that equivalence is the point of the replay-then-tail design).
    import threading
    threading.Thread(target=feed, daemon=True).start()
    try:
        with _client().stream("GET", "/v1/dossier/d-live/events") as r:
            text = "".join(chunk for chunk in r.iter_text())
    finally:
        dsr.forget("d-live")
    assert [k for k, _ in _events(text)] == ["plan", "subquery", "subquery", "synthesis", dsr.PARTIAL]


def test_sse_for_an_orphan_replays_the_persisted_log_and_closes(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_DOSSIER", "on")
    sv._STATE["store"].put_item("local", dsr.KIND, "dead",
                                {"dossier_id": "dead", "status": dsr.RUNNING, "subqueries": [],
                                 "quota_period": None,
                                 "events": [{"type": "plan", "n": 6}, {"type": "subquery", "i": 1}]})
    c = _client()
    with c.stream("GET", "/v1/dossier/dead/events") as r:
        text = "".join(chunk for chunk in r.iter_text())
    kinds = [k for k, _ in _events(text)]
    assert kinds == ["plan", "subquery", dsr.FAILED]      # never a stream that hangs on a dead job


def test_sse_404s_for_an_unknown_dossier(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_DOSSIER", "on")
    assert _client().get("/v1/dossier/nope/events").status_code == 404
