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


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


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


# ── in-memory (tests / local) ──────────────────────────────────────────────────────────────────────
class InMemoryStore:
    def __init__(self):
        self._shares: dict[str, ShareSnapshot] = {}
        self._items: dict[tuple, dict] = {}                          # (user, kind, id) -> body

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
