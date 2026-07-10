"""P3 morning-brief notifications — store helpers + auth-gated routes (Phase 8 SECTION III, Track A).
Hermetic: InMemory store, stub Dynamo clients, no AWS / no LLM. Covers the idempotent conditional write,
the TTL-only-on-notif-items safety invariant (D5), the mark-seen upsert guard, the junk-item read guard,
the GRAPHRAG_NOTIFICATIONS kill-switch, and the no-event-blob-on-the-wire projection."""
from __future__ import annotations

import json

from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from leviathan.graphrag import api_models as M
from leviathan.graphrag import server as sv
from leviathan.graphrag import store as st


def _client(monkeypatch, store=None):
    monkeypatch.setitem(sv._STATE, "store", store or st.InMemoryStore())
    return TestClient(sv.app)


def _notif_body(**over) -> dict:
    b = {"created_at": "2026-07-10T12:00:00Z", "event_type": "export_ban", "commodity": "corn",
         "date": "2026-07-10", "summary": "test", "country": "Argentina",
         "label": "Export ban - corn (Argentina)",
         "query": "Has an export ban hit corn before? What cascaded?", "driver_id": "export_ban",
         "event": {"headline": "RAW HEADLINE", "url": "http://x", "source": "feed"}}
    b.update(over)
    return b


def _cond_fail(op: str) -> ClientError:
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, op)


# ── store: InMemory ──────────────────────────────────────────────────────────────────────────────────
def test_append_notification_idempotent():
    s = st.InMemoryStore()
    assert s.append_notification("u1", "2026-07-10#export_ban#corn", _notif_body()) is True
    assert s.append_notification("u1", "2026-07-10#export_ban#corn", _notif_body()) is False  # same-day re-run
    assert len(s.list_notifications("u1")) == 1
    assert s.list_notifications("u2") == []                          # user-scoped, no leak


def test_mark_seen_flips():
    s = st.InMemoryStore()
    s.append_notification("u1", "2026-07-10#frost#arabica_coffee", _notif_body())
    assert len(s.list_notifications("u1", unseen_only=True)) == 1
    s.mark_notification_seen("u1", "2026-07-10#frost#arabica_coffee")
    assert s.list_notifications("u1", unseen_only=True) == []
    full = s.list_notifications("u1")
    assert len(full) == 1 and full[0]["seen"] is True
    s.mark_notification_seen("u1", "never-appended")                 # unknown id -> no-op, no new item
    assert len(s.list_notifications("u1")) == 1


def test_list_notifications_newest_first():
    s = st.InMemoryStore()
    s.append_notification("u1", "2026-07-09#frost#arabica_coffee", _notif_body(date="2026-07-09"))
    s.append_notification("u1", "2026-07-10#export_ban#corn", _notif_body())
    ids = [n["notif_id"] for n in s.list_notifications("u1")]
    assert ids[0].startswith("2026-07-10")                           # date-prefixed id -> newest first


# ── store: Dynamo (stub client) ──────────────────────────────────────────────────────────────────────
def test_notification_ttl_only_on_notif_items():
    """D5 safety invariant: expires_at (the table TTL attr) rides ONLY notif# items — a durable
    share/turn/item write must never carry it (a bug here silently deletes user data after 60d)."""
    puts = []

    class _Db:
        def put_item(self, **kw):
            puts.append(kw["Item"])

    s = st.DynamoStore(table="t", client=_Db())
    s.append_notification("u1", "2026-07-10#frost#arabica_coffee", _notif_body())
    s.put_share(st.make_share("q", None, {"answer": "a"}))
    s.append_turn("u1", "th1", {"question": "q", "answer": "a"})
    s.put_item("u1", "thread", "t1", {"title": "x"})
    notif = [i for i in puts if i["sk"]["S"].startswith("notif#")]
    durable = [i for i in puts if not i["sk"]["S"].startswith("notif#")]
    assert len(notif) == 1 and "expires_at" in notif[0] and notif[0]["seen"] == {"BOOL": False}
    assert len(durable) == 3 and all("expires_at" not in i for i in durable)


def test_append_notification_conditional_and_rerun_noop():
    calls = []

    class _Db:
        def put_item(self, **kw):
            calls.append(kw)
            if len(calls) > 1:
                raise _cond_fail("PutItem")

    s = st.DynamoStore(table="t", client=_Db())
    assert s.append_notification("u1", "x", _notif_body()) is True
    assert calls[0]["ConditionExpression"] == "attribute_not_exists(sk)"
    assert s.append_notification("u1", "x", _notif_body()) is False   # ConditionalCheckFailed swallowed


def test_mark_seen_unknown_id_is_noop():
    """An UpdateItem UPSERTS: without the attribute_exists condition a garbage notif_id would CREATE a
    body-less notif# item that escapes TTL. The conditional swallow keeps it a pure no-op."""
    calls = []

    class _Db:
        def update_item(self, **kw):
            calls.append(kw)
            raise _cond_fail("UpdateItem")

    st.DynamoStore(table="t", client=_Db()).mark_notification_seen("u1", "garbage-id")  # must not raise
    assert calls[0]["ConditionExpression"] == "attribute_exists(sk)"


def test_list_skips_undecodable_item():
    class _Db:
        def query(self, **kw):
            return {"Items": [
                {"pk": {"S": "user#u1"}, "sk": {"S": "notif#junk"}},                       # body-less junk
                {"pk": {"S": "user#u1"}, "sk": {"S": "notif#bad"}, "body": {"S": "{not json"}},
                {"pk": {"S": "user#u1"}, "sk": {"S": "notif#ok"},
                 "body": {"S": json.dumps(_notif_body(notif_id="ok"))}, "seen": {"BOOL": True}},
            ]}

    out = st.DynamoStore(table="t", client=_Db()).list_notifications("u1")
    assert len(out) == 1 and out[0]["notif_id"] == "ok" and out[0]["seen"] is True   # native attr overlay


# ── routes ───────────────────────────────────────────────────────────────────────────────────────────
def test_notifications_anon_401(monkeypatch):
    c = _client(monkeypatch)
    monkeypatch.setenv("GRAPHRAG_AUTH", "on")
    assert c.get("/v1/notifications").status_code == 401
    assert c.post("/v1/notifications/x/seen").status_code == 401


def test_notifications_killswitch_off(monkeypatch):
    s = st.InMemoryStore()
    s.append_notification("local", "2026-07-10#frost#arabica_coffee", _notif_body())
    c = _client(monkeypatch, store=s)
    monkeypatch.setenv("GRAPHRAG_NOTIFICATIONS", "off")
    assert c.get("/v1/notifications").json() == []                    # empty, never a 404 (bell degrades)
    assert c.post("/v1/notifications/x/seen").json() == {"ok": False, "disabled": True}
    monkeypatch.delenv("GRAPHRAG_NOTIFICATIONS")
    assert len(c.get("/v1/notifications").json()) == 1                # default on


def test_notifications_no_event_on_wire(monkeypatch):
    """The stored body carries the raw LiveEvent audit blob (adversary-controlled headline/url); the wire
    must carry ONLY the narrow typed fields — server projection + the strict model, belt and suspenders."""
    s = st.InMemoryStore()
    s.append_notification("local", "2026-07-10#export_ban#corn", _notif_body(extra_key="x"))
    c = _client(monkeypatch, store=s)
    items = c.get("/v1/notifications").json()
    assert len(items) == 1
    it = items[0]
    assert "event" not in it and "headline" not in json.dumps(it) and "http://x" not in json.dumps(it)
    assert "extra_key" not in it and "expires_at" not in it
    assert it["label"].startswith("Export ban") and it["query"].startswith("Has an export ban")
    assert it["commodity"] == "corn" and it["event_type"] == "export_ban" and it["seen"] is False


def test_notifications_mark_seen_roundtrip(monkeypatch):
    s = st.InMemoryStore()
    s.append_notification("local", "2026-07-10#export_ban#corn", _notif_body())
    c = _client(monkeypatch, store=s)
    assert len(c.get("/v1/notifications", params={"unseen_only": True}).json()) == 1
    assert c.post("/v1/notifications/2026-07-10%23export_ban%23corn/seen").json() == {"ok": True}
    assert c.get("/v1/notifications", params={"unseen_only": True}).json() == []
    assert c.get("/v1/notifications").json()[0]["seen"] is True


# ── model shape ──────────────────────────────────────────────────────────────────────────────────────
def test_notification_item_shape():
    n = M.NotificationItem(notif_id="x", created_at="t", event_type="export_ban", commodity="corn",
                           label="L", query="Q")
    assert n.seen is False and n.date is None and n.driver_id is None
    # STRICT-ignore: the audit blob (or any extra) is silently dropped, never serialized
    n2 = M.NotificationItem(notif_id="x", created_at="t", event_type="export_ban", commodity="corn",
                            label="L", query="Q", event={"headline": "RAW"})
    assert not hasattr(n2, "event") and "event" not in n2.model_dump()
