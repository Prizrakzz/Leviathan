"""Durable per-user persistence + share snapshots for the terminal (build-plan P1.7).

A sibling of `session.py` but PERMANENT (no TTL): saved threads, watchlists, workspaces, and immutable
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
    def put_item(self, user_id: str, kind: str, item_id: str, body: dict) -> None: ...
    def delete_item(self, user_id: str, kind: str, item_id: str) -> None: ...
    def incr_turn_quota(self, user_id: str, day: str, cap: int) -> None: ...
    def append_turn(self, user_id: str, thread_id: str, record: dict) -> dict: ...
    def list_turns(self, user_id: str, thread_id: str) -> list[dict]: ...


# ── in-memory (tests / local) ──────────────────────────────────────────────────────────────────────
class InMemoryStore:
    def __init__(self):
        self._shares: dict[str, ShareSnapshot] = {}
        self._items: dict[tuple, dict] = {}                          # (user, kind, id) -> body
        self._quota: dict[tuple, int] = {}                           # (user, day) -> count
        self._turns: dict[tuple, list[dict]] = {}                    # (user, thread) -> [turn records]

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
