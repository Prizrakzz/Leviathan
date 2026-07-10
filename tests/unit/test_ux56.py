"""Phase 5.6 UX backend — profile records, server-registered threads + Haiku titles, delete-purge,
convergence warm path, and the streaming-progress events' byte-identical (on_stage=None) contract.
All hermetic: InMemory store / stub Dynamo clients / injected fakes. No AWS, no LLM."""
from __future__ import annotations

import time

from fastapi.testclient import TestClient
from leviathan.causal import schema as cs
from leviathan.graphrag import firing as fr
from leviathan.graphrag import graph as g
from leviathan.graphrag import server as sv
from leviathan.graphrag import store as st


# ── shared fixtures ─────────────────────────────────────────────────────────────────────────────────
def _graph() -> g.CausalGraph:
    coffee = cs.CausalContract(
        contract="arabica_coffee", aliases=["arabica"],
        drivers=[cs.Driver(id="frost", type="hazard", sign="+", mechanism="m"),
                 cs.Driver(id="low_stocks", type="hazard", sign="+", mechanism="m")],
        convergence=[cs.ConvergenceSignal(name="squeeze", direction="+",
                                          requires_any_n_of=2, drivers=["frost", "low_stocks"])])
    return g.CausalGraph({"arabica_coffee": coffee}, silver=set())


def _lookup(contract, did, asof):
    return {"live": True, "verdict": "observed", "z": -2.0, "value": 0.1, "unit": "ratio",
            "ref": "su", "knowledge_date": "2021-07-10"}


def _client(monkeypatch, respond_fn=None):
    monkeypatch.setitem(sv._STATE, "graph", _graph())
    monkeypatch.setitem(sv._STATE, "store", st.InMemoryStore())
    if respond_fn is not None:
        from leviathan.graphrag import orchestrator as orch
        monkeypatch.setattr(orch, "respond", respond_fn)
    return TestClient(sv.app)


def _fake_respond(query, *, graph, asof=None, session_id=None, **kw):
    # NOTE: no "question" key — respond() never emits one. The server must inject the request question
    # into the durable turn itself (5.8 regression: relying on result.get("question") stored null).
    return {"answer": f"note for {query}", "structured": {"tldr": "t"},
            "asof": asof or "2026-01-01", "citations": [], "contracts": ["arabica_coffee"],
            "intent": "reasoning", "model": "m", "trace": {"graph_version": "gv1"}}


def _wait(cond, timeout=3.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


# ── store: profile record ───────────────────────────────────────────────────────────────────────────
def test_touch_profile_inmemory_first_seen_and_turn_count():
    s = st.InMemoryStore()
    s.touch_profile("u1", email="a@b.c", name="Alice")
    p1 = s.get_profile("u1")
    assert p1["email"] == "a@b.c" and p1["name"] == "Alice" and p1["turn_count"] == 1
    first = p1["first_seen"]
    s.touch_profile("u1")                                            # None claims -> keep existing
    s.touch_profile("u1", count_turn=False)                          # sign-in touch -> no turn increment
    p2 = s.get_profile("u1")
    assert p2["turn_count"] == 2 and p2["email"] == "a@b.c" and p2["first_seen"] == first
    assert s.get_profile("nobody") is None


def test_touch_profile_dynamo_update_expression():
    calls = []

    class _Db:
        def update_item(self, **kw):
            calls.append(kw)

    s = st.DynamoStore(table="t", client=_Db())
    s.touch_profile("u1", email="a@b.c", name="Alice")
    kw = calls[0]
    assert kw["Key"] == {"pk": {"S": "user#u1"}, "sk": {"S": "profile"}}
    expr = kw["UpdateExpression"]
    assert "if_not_exists(first_seen" in expr and "ADD turn_count :one" in expr
    assert kw["ExpressionAttributeNames"] == {"#nm": "name"}         # reserved word aliased
    s.touch_profile("u1", count_turn=False)                          # no ADD on sign-in touches
    assert "ADD" not in calls[1]["UpdateExpression"] and ":one" not in calls[1]["ExpressionAttributeValues"]


# ── store: get_item + delete_turns ──────────────────────────────────────────────────────────────────
def test_get_item_roundtrip_inmemory():
    s = st.InMemoryStore()
    assert s.get_item("u", "thread", "t1") is None
    s.put_item("u", "thread", "t1", {"title": "x"})
    assert s.get_item("u", "thread", "t1")["title"] == "x"


def test_delete_turns_dynamo_paginated_batches():
    pages = [
        {"Items": [{"pk": {"S": "user#u"}, "sk": {"S": f"turn#t1#{i:03d}"}} for i in range(30)],
         "LastEvaluatedKey": {"pk": {"S": "user#u"}}},
        {"Items": [{"pk": {"S": "user#u"}, "sk": {"S": f"turn#t1#{i:03d}"}} for i in range(30, 40)]},
    ]
    batches = []

    class _Db:
        def query(self, **kw):
            return pages.pop(0)

        def batch_write_item(self, RequestItems):
            batches.append(RequestItems)
            return {}

    s = st.DynamoStore(table="t", client=_Db())
    assert s.delete_turns("u", "t1") == 40
    sizes = [len(b["t"]) for b in batches]
    assert sizes == [25, 5, 10]                                      # 25-chunked within each page
    assert all("DeleteRequest" in r for b in batches for r in b["t"])


# ── server: thread self-registration + list sort + delete purge ─────────────────────────────────────
def test_save_turn_registers_thread_index_and_bumps_updated_at(monkeypatch):
    c = _client(monkeypatch, _fake_respond)
    c.post("/v1/respond", json={"question": "first corn question", "session_id": "t-abc"})
    store = sv._STATE["store"]
    item = store.get_item("local", "thread", "t-abc")
    assert item is not None and item["title"] == "first corn question"
    assert item["created_at"] and item["updated_at"] and item["title_auto"] is False
    first_updated = item["updated_at"]
    turn0 = store.list_turns("local", "t-abc")[0]
    assert turn0["answer"] == "note for first corn question"
    # 5.8 regression: the durable turn carries the REQUEST question (respond() never emits one). A null
    # here broke the frontend per-question dedup and rendered the answer twice.
    assert turn0["question"] == "first corn question"
    time.sleep(1.1)                                                  # updated_at has 1s resolution
    c.post("/v1/respond", json={"question": "follow-up", "session_id": "t-abc"})
    item2 = store.get_item("local", "thread", "t-abc")
    assert item2["title"] == "first corn question"                   # title set once (fallback preserved)
    assert item2["updated_at"] > first_updated                       # every turn bumps recency
    assert len(store.list_turns("local", "t-abc")) == 2


def test_threads_list_sorted_updated_desc(monkeypatch):
    c = _client(monkeypatch)
    store = sv._STATE["store"]
    store.put_item("local", "thread", "t-old", {"title": "old", "updated_at": "2026-01-01T00:00:00Z"})
    store.put_item("local", "thread", "t-new", {"title": "new", "updated_at": "2026-07-01T00:00:00Z"})
    store.put_item("local", "thread", "t-mid", {"title": "mid", "updated_at": "2026-03-01T00:00:00Z"})
    ids = [t["id"] for t in c.get("/v1/threads").json()["items"]]
    assert ids == ["t-new", "t-mid", "t-old"]


def test_delete_thread_purges_turns_then_index(monkeypatch):
    c = _client(monkeypatch, _fake_respond)
    c.post("/v1/respond", json={"question": "q1", "session_id": "t-del"})
    store = sv._STATE["store"]
    assert store.list_turns("local", "t-del")
    r = c.delete("/v1/threads/t-del")
    assert r.status_code == 200
    assert store.list_turns("local", "t-del") == []
    assert store.get_item("local", "thread", "t-del") is None


def test_threads_list_touches_profile_without_turn_count(monkeypatch):
    c = _client(monkeypatch)
    c.get("/v1/threads")
    store = sv._STATE["store"]
    assert _wait(lambda: store.get_profile("local") is not None)     # fire-and-forget daemon write
    assert store.get_profile("local").get("turn_count", 0) == 0


# ── server: Haiku auto-title ────────────────────────────────────────────────────────────────────────
def test_autotitle_applies_on_first_turn(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_THREAD_TITLES", "on")
    monkeypatch.setitem(sv._STATE, "title_call", lambda q: "Corn Stocks Squeeze")
    c = _client(monkeypatch, _fake_respond)
    c.post("/v1/respond", json={"question": "why are corn stocks so tight this year?", "session_id": "t-ttl"})
    store = sv._STATE["store"]
    assert _wait(lambda: (store.get_item("local", "thread", "t-ttl") or {}).get("title") == "Corn Stocks Squeeze")


def test_autotitle_never_overwrites_a_user_rename(monkeypatch):
    monkeypatch.setitem(sv._STATE, "store", st.InMemoryStore())
    monkeypatch.setitem(sv._STATE, "title_call", lambda q: "Machine Title")
    store = sv._STATE["store"]
    store.put_item("local", "thread", "t-r", {"title": "MY name", "title_auto": True,
                                              "updated_at": "2026-07-01T00:00:00Z"})
    sv._autotitle_thread("local", "t-r", "some question", fallback="some question")   # run synchronously
    assert store.get_item("local", "thread", "t-r")["title"] == "MY name"


# ── server: convergence warm path ───────────────────────────────────────────────────────────────────
def test_convergence_serves_warm_entry_on_key_match(monkeypatch):
    c = _client(monkeypatch)
    today = sv._today()
    warm_out = {"asof": today, "graph_version": _graph().version, "rows": []}
    key = (today, sv._STATE["graph"].version)
    monkeypatch.setitem(sv._STATE, "conv_warm", (time.time(), key, warm_out))
    body = c.get("/v1/convergence").json()
    assert body == warm_out                                          # served straight from the warmer


def test_convergence_falls_through_on_key_mismatch(monkeypatch):
    c = _client(monkeypatch)
    monkeypatch.setitem(sv._STATE, "conv_warm",
                        (time.time(), ("1999-01-01", "other"), {"asof": "1999-01-01", "graph_version": "x", "rows": []}))
    monkeypatch.setattr(fr, "convergence_matrix",
                        lambda graph, asof, lookup, workers=1: [fr.fire_contract(graph, "arabica_coffee", asof, _lookup)])
    body = c.get("/v1/convergence", params={"asof": "2021-07-20"}).json()
    assert body["asof"] == "2021-07-20" and body["rows"][0]["contract"] == "arabica_coffee"


# ── firing: parallel matrix parity ──────────────────────────────────────────────────────────────────
def test_convergence_matrix_workers_parity():
    gr = _graph()
    assert fr.convergence_matrix(gr, "2021-07-20", _lookup, workers=4) == \
        fr.convergence_matrix(gr, "2021-07-20", _lookup, workers=1)


# ── streaming events: byte-identical when on_stage=None + ordering when set ─────────────────────────
def test_numbers_agent_on_call_progress_and_none_identity():
    from leviathan.graphrag.numbers import agent as na

    class _Blk:
        def __init__(self, typ, **kw):
            self.type = typ
            for k, v in kw.items():
                setattr(self, k, v)

    class _FakeClient:
        def __init__(self):
            self.n = 0

        class messages:  # noqa: N801 — mimic anthropic client shape
            pass

    def _mk_client():
        calls = {"n": 0}

        class _C:
            class messages:  # noqa: N801
                @staticmethod
                def create(**kw):
                    calls["n"] += 1
                    if calls["n"] == 1:
                        return type("R", (), {"content": [
                            _Blk("tool_use", id="tu1", input={"table": "silver_psd", "metric": "su_ratio"}),
                            _Blk("tool_use", id="tu2", input={"table": "silver_noaa_oni", "metric": "oni"}),
                        ]})()
                    return type("R", (), {"content": [_Blk("text", text="done: 0.36")]})()
        return _C()

    def qfn(sql):
        return [{"value": "0.36", "period": "2021"}]

    seen = []
    out1 = na.answer_numbers("stocks?", "2021-07-20", client=_mk_client(), query_fn=qfn,
                             on_call=lambda n, t: seen.append((n, t)))
    assert seen == [(1, "silver_psd"), (2, "silver_noaa_oni")]       # one tick per executed lookup
    out2 = na.answer_numbers("stocks?", "2021-07-20", client=_mk_client(), query_fn=qfn)
    assert out1 == out2                                              # on_call=None is byte-identical


def test_l2_on_stage_none_is_byte_identical_and_events_ordered(monkeypatch):
    from leviathan.graphrag import answer as an
    from leviathan.graphrag import evidence as ev
    monkeypatch.setattr(ev, "embed", lambda texts, **k: [[1.0 if "frost" in t.lower() else 0.0] for t in texts])
    gr = _graph()

    def fake_call(system, user, *, model, tool):
        return {"tldr": "frost bullish [1]", "mechanism": "frost -> price [1]", "diagram_mermaid": "",
                "sources": [{"ref": 1, "source": "GAIN", "date": "2021-07-20", "note": "frost"}]}

    def fake_retrieve(q, node, *, k, asof=None, near=None):
        return [{"date": "2021-07-20", "source": "GAIN", "source_key": f"s3://{node}", "text": "July frost hit"}]

    kw = dict(graph=gr, planner="l2", asof="2021-08-01", retrieve=fake_retrieve, call=fake_call,
              route_fn=lambda q, g: ["arabica_coffee"])
    base = an.answer("trace how a coffee frost spikes price", **kw)
    events = []
    probed = an.answer("trace how a coffee frost spikes price", on_stage=lambda s, i: events.append((s, i)), **kw)

    def _strip(res):
        out = {k: v for k, v in res.items() if k != "trace"}
        out["trace"] = {k: v for k, v in res["trace"].items() if k != "ground_ms"}   # wall-clock only
        return out

    assert _strip(base) == _strip(probed)                            # the load-bearing contract
    names = [s for s, _ in events]
    assert names.index("walking") < names.index("retrieving")        # early walking tick precedes retrieval
    assert names.index("synthesizing") > names.index("retrieving")
    assert names.index("verifying") > names.index("synthesizing")
