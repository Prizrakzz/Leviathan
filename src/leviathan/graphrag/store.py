"""Durable per-user persistence + share snapshots for the terminal (build-plan P1.7).

A sibling of `session.py` but PERMANENT (no TTL): saved threads, watchlists, workspaces, artifacts, and immutable
SHARE snapshots. A share = the full `respond()` payload + question + as-of + `graph_version` at a uuid
permalink, so a research note is forwardable AND reproducible (design §6.7). Same InMemory/Dynamo split as
session.py: InMemory for tests/local, Dynamo for serving. The DynamoDB table and Cognito enforcement are a
Phase-4 deploy step; this module is fully testable now with the in-memory backend.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Optional, Protocol


class QuotaExceeded(Exception):
    """Raised when a user has spent their daily turn allowance (maps to HTTP 429)."""


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _turn_sort_key(thread_id: str) -> str:
    """A per-thread, chronologically-sortable DynamoDB sort key for a turn (epoch-micros + a short random
    suffix so same-microsecond appends never collide)."""
    return f"turn#{thread_id}#{int(time.time() * 1_000_000):020d}#{uuid.uuid4().hex[:6]}"


# The PIT firewall for durable turns: a saved turn holds the CONCLUSION only. Retrieved evidence, raw number
# rows, and the trace (which embeds resolved evidence text) are NEVER persisted — they are re-derived under
# the turn's own as-of if the turn is re-run. This allowlist is the store-layer backstop to whatever the
# caller passes, so a leak can't slip through even if the caller is wrong.
_TURN_ALLOWED = frozenset({"question", "answer", "structured", "asof", "sources",
                           "graph_version", "contract", "contracts", "intent", "model", "ts"})


def sanitize_turn(record: dict) -> dict:
    """Strip a turn record to the PIT-safe allowlist (drops evidence / number_calls / trace / citations
    text). Ensures a `ts`."""
    rec = {k: record[k] for k in record if k in _TURN_ALLOWED}
    rec.setdefault("ts", _now())
    return rec


@dataclass
class ShareSnapshot:
    id: str
    question: str
    asof: Optional[str]
    graph_version: Optional[str]
    created_at: str
    payload: dict

    def to_dict(self) -> dict:
        return {"id": self.id, "question": self.question, "asof": self.asof,
                "graph_version": self.graph_version, "created_at": self.created_at, "payload": self.payload}


class Store(Protocol):
    def put_share(self, snap: ShareSnapshot) -> None: ...
    def get_share(self, share_id: str) -> Optional[ShareSnapshot]: ...
    def list_items(self, user_id: str, kind: str) -> list[dict]: ...
    def get_item(self, user_id: str, kind: str, item_id: str) -> Optional[dict]: ...
    def put_item(self, user_id: str, kind: str, item_id: str, body: dict) -> None: ...
    def delete_item(self, user_id: str, kind: str, item_id: str) -> None: ...
    def incr_turn_quota(self, user_id: str, day: str, cap: int) -> None: ...
    def append_turn(self, user_id: str, thread_id: str, record: dict) -> dict: ...
    def list_turns(self, user_id: str, thread_id: str) -> list[dict]: ...
    def delete_turns(self, user_id: str, thread_id: str) -> int: ...
    def touch_profile(self, user_id: str, *, email: Optional[str] = None, name: Optional[str] = None,
                      count_turn: bool = True) -> None: ...
    def get_profile(self, user_id: str, *, consistent: bool = False) -> Optional[dict]: ...
    def update_profile(self, user_id: str, *, facts: Optional[dict] = None,
                       onboarded: Optional[bool] = None) -> None: ...
    def append_notification(self, user_id: str, notif_id: str, body: dict, *,
                            ttl_seconds: int = 5184000) -> bool: ...
    def list_notifications(self, user_id: str, *, unseen_only: bool = False) -> list[dict]: ...
    def mark_notification_seen(self, user_id: str, notif_id: str) -> None: ...


# ── in-memory (tests / local) ──────────────────────────────────────────────────────────────────────
class InMemoryStore:
    def __init__(self):
        self._shares: dict[str, ShareSnapshot] = {}
        self._items: dict[tuple, dict] = {}                          # (user, kind, id) -> body
        self._quota: dict[tuple, int] = {}                           # (user, day) -> count
        self._turns: dict[tuple, list[dict]] = {}                    # (user, thread) -> [turn records]
        self._profiles: dict[str, dict] = {}                         # user -> profile record
        self._notifs: dict[str, dict] = {}                           # user -> {notif_id -> record} (P3)

    def incr_turn_quota(self, user_id: str, day: str, cap: int) -> None:
        n = self._quota.get((user_id, day), 0)
        if n >= cap:
            raise QuotaExceeded(f"daily turn limit {cap} reached")
        self._quota[(user_id, day)] = n + 1

    def put_share(self, snap: ShareSnapshot) -> None:
        self._shares[snap.id] = snap

    def get_share(self, share_id: str) -> Optional[ShareSnapshot]:
        return self._shares.get(share_id)

    def list_items(self, user_id: str, kind: str) -> list[dict]:
        return [b for (u, k, _i), b in self._items.items() if u == user_id and k == kind]

    def get_item(self, user_id: str, kind: str, item_id: str) -> Optional[dict]:
        return self._items.get((user_id, kind, item_id))

    def put_item(self, user_id: str, kind: str, item_id: str, body: dict) -> None:
        self._items[(user_id, kind, item_id)] = {**body, "id": item_id, "kind": kind}

    def delete_item(self, user_id: str, kind: str, item_id: str) -> None:
        self._items.pop((user_id, kind, item_id), None)

    def append_turn(self, user_id: str, thread_id: str, record: dict) -> dict:
        rec = sanitize_turn(record)
        self._turns.setdefault((user_id, thread_id), []).append(rec)
        return rec

    def list_turns(self, user_id: str, thread_id: str) -> list[dict]:
        return list(self._turns.get((user_id, thread_id), []))

    def delete_turns(self, user_id: str, thread_id: str) -> int:
        return len(self._turns.pop((user_id, thread_id), []))

    def touch_profile(self, user_id: str, *, email: Optional[str] = None, name: Optional[str] = None,
                      count_turn: bool = True) -> None:
        p = self._profiles.setdefault(user_id, {"first_seen": _now(), "turn_count": 0})
        p["last_seen"] = _now()
        if count_turn:
            p["turn_count"] = int(p.get("turn_count", 0)) + 1
        if email is not None:
            p["email"] = email
        if name is not None:
            p["name"] = name

    def get_profile(self, user_id: str, *, consistent: bool = False) -> Optional[dict]:
        return self._profiles.get(user_id)                           # in-memory is always consistent

    def update_profile(self, user_id: str, *, facts: Optional[dict] = None,
                       onboarded: Optional[bool] = None) -> None:
        p = self._profiles.setdefault(user_id, {"first_seen": _now(), "turn_count": 0})
        if facts is not None:
            p["facts"] = facts
        if onboarded is not None:
            p["onboarded"] = bool(onboarded)
            if onboarded:
                p.setdefault("onboarded_at", _now())

    def append_notification(self, user_id: str, notif_id: str, body: dict, *,
                            ttl_seconds: int = 5184000) -> bool:
        d = self._notifs.setdefault(user_id, {})
        if notif_id in d:
            return False                                             # idempotent same-day no-op
        d[notif_id] = {**body, "notif_id": notif_id, "seen": False}
        return True

    def list_notifications(self, user_id: str, *, unseen_only: bool = False) -> list[dict]:
        vals = sorted(self._notifs.get(user_id, {}).values(),
                      key=lambda n: n.get("notif_id", ""), reverse=True)   # date-prefixed id -> newest first
        return [n for n in vals if not n["seen"]] if unseen_only else list(vals)

    def mark_notification_seen(self, user_id: str, notif_id: str) -> None:
        n = self._notifs.get(user_id, {}).get(notif_id)
        if n:
            n["seen"] = True                                         # unknown id -> no-op (Dynamo parity)


# ── DynamoDB (serving) — PK pk, SK sk, NO TTL (durable) ─────────────────────────────────────────────
class DynamoStore:
    """One table: share = (pk 'share#<id>', sk 'share'); user item = (pk 'user#<uid>', sk '<kind>#<id>')."""

    def __init__(self, table: str = "leviathan-dev-terminal-store", client=None):
        import boto3
        self.table = table
        self.db = client or boto3.client("dynamodb")

    @staticmethod
    def _s(v) -> dict:
        return {"S": json.dumps(v, ensure_ascii=True)}

    def put_share(self, snap: ShareSnapshot) -> None:
        self.db.put_item(TableName=self.table, Item={
            "pk": {"S": f"share#{snap.id}"}, "sk": {"S": "share"}, "body": self._s(snap.to_dict())})

    def get_share(self, share_id: str) -> Optional[ShareSnapshot]:
        it = self.db.get_item(TableName=self.table,
                              Key={"pk": {"S": f"share#{share_id}"}, "sk": {"S": "share"}}).get("Item")
        return ShareSnapshot(**json.loads(it["body"]["S"])) if it else None

    def list_items(self, user_id: str, kind: str) -> list[dict]:
        q = self.db.query(TableName=self.table,
                          KeyConditionExpression="pk = :p AND begins_with(sk, :k)",
                          ExpressionAttributeValues={":p": {"S": f"user#{user_id}"}, ":k": {"S": f"{kind}#"}})
        return [json.loads(i["body"]["S"]) for i in q.get("Items", [])]

    def get_item(self, user_id: str, kind: str, item_id: str) -> Optional[dict]:
        it = self.db.get_item(TableName=self.table,
                              Key={"pk": {"S": f"user#{user_id}"}, "sk": {"S": f"{kind}#{item_id}"}}).get("Item")
        return json.loads(it["body"]["S"]) if it else None

    def put_item(self, user_id: str, kind: str, item_id: str, body: dict) -> None:
        self.db.put_item(TableName=self.table, Item={
            "pk": {"S": f"user#{user_id}"}, "sk": {"S": f"{kind}#{item_id}"},
            "body": self._s({**body, "id": item_id, "kind": kind})})

    def delete_item(self, user_id: str, kind: str, item_id: str) -> None:
        self.db.delete_item(TableName=self.table,
                            Key={"pk": {"S": f"user#{user_id}"}, "sk": {"S": f"{kind}#{item_id}"}})

    def incr_turn_quota(self, user_id: str, day: str, cap: int) -> None:
        """Atomic daily counter (pk=user#uid, sk=quota#DAY, attr n). ADD + a condition that rejects at the
        cap in ONE call (no read-modify-write race). ConditionalCheckFailed = over quota (QuotaExceeded);
        any other Dynamo error FAILS OPEN (a counter glitch must not lock out a paying user — WAF + the
        Bedrock budget are the hard backstops)."""
        from botocore.exceptions import ClientError
        try:
            self.db.update_item(
                TableName=self.table,
                Key={"pk": {"S": f"user#{user_id}"}, "sk": {"S": f"quota#{day}"}},
                UpdateExpression="ADD n :one",
                ConditionExpression="attribute_not_exists(n) OR n < :cap",
                ExpressionAttributeValues={":one": {"N": "1"}, ":cap": {"N": str(int(cap))}},
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise QuotaExceeded(f"daily turn limit {cap} reached")
            raise  # non-condition Dynamo error -> caller fails open

    def append_turn(self, user_id: str, thread_id: str, record: dict) -> dict:
        """Durable per-thread turn (pk=user#uid, sk=turn#<thread>#<epoch-micros>#<rand> -> chronological).
        Sanitized to the PIT allowlist so evidence can never be persisted."""
        rec = sanitize_turn(record)
        self.db.put_item(TableName=self.table, Item={
            "pk": {"S": f"user#{user_id}"}, "sk": {"S": _turn_sort_key(thread_id)}, "body": self._s(rec)})
        return rec

    def list_turns(self, user_id: str, thread_id: str) -> list[dict]:
        q = self.db.query(
            TableName=self.table,
            KeyConditionExpression="pk = :p AND begins_with(sk, :k)",
            ExpressionAttributeValues={":p": {"S": f"user#{user_id}"}, ":k": {"S": f"turn#{thread_id}#"}})
        return [json.loads(i["body"]["S"]) for i in q.get("Items", [])]

    def delete_turns(self, user_id: str, thread_id: str) -> int:
        """Purge every turn item of a thread (paginated query -> batch deletes of 25, one retry on
        UnprocessedItems). Called BEFORE the thread-index delete so a partial failure leaves the thread
        visible and the delete retryable."""
        deleted = 0
        kwargs = dict(
            TableName=self.table,
            KeyConditionExpression="pk = :p AND begins_with(sk, :k)",
            ExpressionAttributeValues={":p": {"S": f"user#{user_id}"}, ":k": {"S": f"turn#{thread_id}#"}},
            ProjectionExpression="pk, sk",
        )
        while True:
            page = self.db.query(**kwargs)
            keys = [{"pk": i["pk"], "sk": i["sk"]} for i in page.get("Items", [])]
            for chunk_at in range(0, len(keys), 25):
                chunk = keys[chunk_at:chunk_at + 25]
                req = {self.table: [{"DeleteRequest": {"Key": k}} for k in chunk]}
                resp = self.db.batch_write_item(RequestItems=req)
                unproc = (resp.get("UnprocessedItems") or {}).get(self.table)
                if unproc:                                           # one retry, then surface to the caller
                    resp = self.db.batch_write_item(RequestItems={self.table: unproc})
                    if (resp.get("UnprocessedItems") or {}).get(self.table):
                        raise RuntimeError(f"delete_turns: unprocessed deletes for thread {thread_id}")
                deleted += len(chunk)
            last = page.get("LastEvaluatedKey")
            if not last:
                return deleted
            kwargs["ExclusiveStartKey"] = last

    def touch_profile(self, user_id: str, *, email: Optional[str] = None, name: Optional[str] = None,
                      count_turn: bool = True) -> None:
        """Per-user profile record (pk=user#<sub>, sk=profile) with NATIVE attributes (not the body-JSON
        convention) so first_seen/turn_count are a single atomic UpdateItem — no read-modify-write.
        `count_turn=False` for sign-in touches (threads list) so turn_count stays turns-only."""
        now = _now()
        sets = ["last_seen = :now", "first_seen = if_not_exists(first_seen, :now)"]
        vals: dict = {":now": {"S": now}}
        names: dict = {}
        if email is not None:
            sets.append("email = :e")
            vals[":e"] = {"S": email}
        if name is not None:
            sets.append("#nm = :n")                                  # `name` is a Dynamo reserved word
            vals[":n"] = {"S": name}
            names["#nm"] = "name"
        expr = "SET " + ", ".join(sets)
        if count_turn:
            expr += " ADD turn_count :one"
            vals[":one"] = {"N": "1"}
        kwargs = dict(
            TableName=self.table,
            Key={"pk": {"S": f"user#{user_id}"}, "sk": {"S": "profile"}},
            UpdateExpression=expr,
            ExpressionAttributeValues=vals,
        )
        if names:
            kwargs["ExpressionAttributeNames"] = names
        self.db.update_item(**kwargs)

    def update_profile(self, user_id: str, *, facts: Optional[dict] = None,
                       onboarded: Optional[bool] = None) -> None:
        """User-authored profile prefs (6.6) — facts (a JSON blob attr) + the onboarding flag — written as
        native attributes on the SAME profile item as touch_profile's bookkeeping. Independent SET clauses,
        so this never races touch_profile (they touch disjoint attributes). An UpdateItem on a not-yet-created
        profile creates it with just these attrs (get_profile tolerates a partial record)."""
        sets: list[str] = []
        vals: dict = {}
        if facts is not None:
            sets.append("facts = :f")
            vals[":f"] = {"S": json.dumps(facts, ensure_ascii=True)}
        if onboarded is not None:
            sets.append("onboarded = :ob")
            vals[":ob"] = {"BOOL": bool(onboarded)}
            if onboarded:
                sets.append("onboarded_at = if_not_exists(onboarded_at, :now)")
                vals[":now"] = {"S": _now()}
        if not sets:
            return
        self.db.update_item(
            TableName=self.table,
            Key={"pk": {"S": f"user#{user_id}"}, "sk": {"S": "profile"}},
            UpdateExpression="SET " + ", ".join(sets),
            ExpressionAttributeValues=vals,
        )

    def get_profile(self, user_id: str, *, consistent: bool = False) -> Optional[dict]:
        # `consistent=True` on the PUT read-after-write so a save's response can't echo the pre-update copy
        # (DynamoDB GetItem is eventually consistent by default); GET stays eventual (cheaper).
        it = self.db.get_item(TableName=self.table, ConsistentRead=consistent,
                              Key={"pk": {"S": f"user#{user_id}"}, "sk": {"S": "profile"}}).get("Item")
        if not it:
            return None
        out: dict = {}
        for k, v in it.items():
            if k in ("pk", "sk"):
                continue
            if "N" in v:
                out[k] = int(v["N"])
            elif "BOOL" in v:
                out[k] = v["BOOL"]
            else:
                out[k] = v.get("S")
        if isinstance(out.get("facts"), str):                    # the facts blob is stored as a JSON string
            try:
                out["facts"] = json.loads(out["facts"])
            except (ValueError, TypeError):
                out["facts"] = {}
        return out

    def append_notification(self, user_id: str, notif_id: str, body: dict, *,
                            ttl_seconds: int = 5184000) -> bool:
        """Idempotent per-user daily-digest notification (pk=user#uid, sk=notif#<id>). Conditional PutItem:
        a same-day re-run of the digest job is a no-op (ConditionalCheckFailed swallowed). `seen` is a
        NATIVE attribute (not inside body) so mark-seen is one UpdateItem with no body rewrite; `expires_at`
        (the table's TTL attr) is written ONLY here — a durable share/thread/turn never carries it."""
        from botocore.exceptions import ClientError
        item = {"pk": {"S": f"user#{user_id}"}, "sk": {"S": f"notif#{notif_id}"},
                "body": self._s({**body, "notif_id": notif_id}),
                "seen": {"BOOL": False},                             # native attr (NOT in body)
                "expires_at": {"N": str(int(time.time()) + int(ttl_seconds))}}
        try:
            self.db.put_item(TableName=self.table, Item=item,
                             ConditionExpression="attribute_not_exists(sk)")
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False                                         # already delivered today -> no-op
            raise

    def list_notifications(self, user_id: str, *, unseen_only: bool = False) -> list[dict]:
        q = self.db.query(TableName=self.table, ScanIndexForward=False,   # newest sk first (date-prefixed)
                          KeyConditionExpression="pk = :p AND begins_with(sk, :k)",
                          ExpressionAttributeValues={":p": {"S": f"user#{user_id}"},
                                                     ":k": {"S": "notif#"}})
        out = []
        for i in q.get("Items", []):
            try:
                n = json.loads(i["body"]["S"])
            except (KeyError, ValueError):
                continue                                             # one junk item never 500s the feed
            n["seen"] = bool(i.get("seen", {}).get("BOOL", False))   # native attr overlays body
            out.append(n)
        return [n for n in out if not n.get("seen")] if unseen_only else out

    def mark_notification_seen(self, user_id: str, notif_id: str) -> None:
        """Flip the native `seen` attr. Conditional on attribute_exists(sk): an UpdateItem UPSERTS, so a
        POST with a garbage notif_id would otherwise CREATE a body-less notif# item that escapes TTL. An
        unknown id is a swallowed no-op instead."""
        from botocore.exceptions import ClientError
        try:
            self.db.update_item(TableName=self.table,
                                Key={"pk": {"S": f"user#{user_id}"}, "sk": {"S": f"notif#{notif_id}"}},
                                UpdateExpression="SET seen = :t",
                                ConditionExpression="attribute_exists(sk)",
                                ExpressionAttributeValues={":t": {"BOOL": True}})
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return                                               # unknown id -> no-op, never upsert
            raise


def default_store() -> Store:
    """InMemory unless GRAPHRAG_STORE=dynamo (serving). The Dynamo table is a Phase-4 apply."""
    import os
    if os.environ.get("GRAPHRAG_STORE", "memory").lower() == "dynamo":
        return DynamoStore(os.environ.get("GRAPHRAG_STORE_TABLE", "leviathan-dev-terminal-store"))
    return InMemoryStore()


def make_share(question: str, asof: Optional[str], payload: dict, *, graph_version: Optional[str] = None) -> ShareSnapshot:
    """Freeze a respond() result into an immutable, permalinkable snapshot; pins the graph_version from the
    payload's trace when not given (so a forwarded note is provably tied to the exact graph that made it)."""
    gv = graph_version or (payload.get("trace") or {}).get("graph_version")
    return ShareSnapshot(id=new_id(), question=question, asof=asof, graph_version=gv,
                         created_at=_now(), payload=payload)
