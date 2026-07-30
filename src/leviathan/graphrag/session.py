"""Session working memory for the serving orchestrator (GRAPHRAG_PLAN section 7.5, Phases 1+2).

Multi-turn conversations carry STRUCTURED STATE forward — "we're discussing {arabica, robusta} under
{frost}, as-of 2021-07" — never evidence. The point-in-time firewall is the schema itself: a TurnRecord
and SessionState hold contract ids, driver ids, an as-of string, and short summary text; there is no
field that can hold evidence props, citations, or looked-up rows (the one exception, `numbers_cache`,
is keyed by the EXACT SQL, which embeds its own as-of guard — a different as-of can never collide).

Storage is pluggable: InMemoryStore (tests/local, zero deps) and DynamoStore (on-demand table, TTL'd
items). Every failure degrades to stateless — memory must never break an answer.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Optional, Protocol

TTL_SECONDS = 24 * 3600
LAST_TURNS = 2                                 # raw turns fed to the prompt (the summary covers the rest)
MAX_NUMBERS_CACHE = 20
MAX_CACHED_ROWS_CHARS = 2048


@dataclass
class TurnRecord:
    turn: int
    query: str
    answer_tldr: str = ""                      # one line, NOT the answer body
    contracts: list = field(default_factory=list)
    focus_driver: Optional[str] = None
    asof: Optional[str] = None
    fired_regime_names: list = field(default_factory=list)
    intent: str = ""
    ts: float = 0.0


@dataclass
class SessionState:
    summary: dict = field(default_factory=dict)          # {entities:[], thesis:str, open_threads:[]}
    contracts: list = field(default_factory=list)        # last known routed contracts (ids only)
    focus_driver: Optional[str] = None
    asof_latest: Optional[str] = None
    numbers_cache: dict = field(default_factory=dict)    # sha1(sql) -> rows (small, ok-status only)
    turn_count: int = 0


@dataclass
class SessionSnapshot:
    state: SessionState
    turns: list                                          # last-N TurnRecords, oldest first


class SessionStore(Protocol):
    def load(self, session_id: str) -> Optional[SessionSnapshot]: ...
    def append_turn(self, session_id: str, turn: TurnRecord) -> None: ...
    def put_state(self, session_id: str, state: SessionState) -> None: ...


# ── in-memory (tests / local) ─────────────────────────────────────────────────────────────────────
class InMemoryStore:
    def __init__(self):
        self._turns: dict[str, list] = {}
        self._state: dict[str, SessionState] = {}

    def load(self, session_id):
        if session_id not in self._state and session_id not in self._turns:
            return None
        return SessionSnapshot(state=self._state.get(session_id) or SessionState(),
                               turns=(self._turns.get(session_id) or [])[-LAST_TURNS:])

    def append_turn(self, session_id, turn):
        self._turns.setdefault(session_id, []).append(turn)

    def put_state(self, session_id, state):
        self._state[session_id] = state


# ── DynamoDB (serving) ────────────────────────────────────────────────────────────────────────────
class DynamoStore:
    """One table, on-demand: PK session_id, SK item_key ('turn#NNNN' | 'state'), TTL `expires_at`."""

    def __init__(self, table: str = "leviathan-dev-graphrag-sessions", client=None):
        import boto3
        self.table = table
        self.db = client or boto3.client("dynamodb")

    @staticmethod
    def _s(v) -> dict:
        return {"S": json.dumps(v, ensure_ascii=True)}

    def _expires(self) -> dict:
        return {"N": str(int(time.time()) + TTL_SECONDS)}

    def load(self, session_id):
        st = self.db.get_item(TableName=self.table,
                              Key={"session_id": {"S": session_id}, "item_key": {"S": "state"}}).get("Item")
        q = self.db.query(TableName=self.table, ScanIndexForward=False, Limit=LAST_TURNS,
                          KeyConditionExpression="session_id = :s AND begins_with(item_key, :t)",
                          ExpressionAttributeValues={":s": {"S": session_id}, ":t": {"S": "turn#"}})
        turns = [TurnRecord(**json.loads(i["payload"]["S"])) for i in reversed(q.get("Items", []))]
        if st is None and not turns:
            return None
        state = SessionState(**json.loads(st["payload"]["S"])) if st else SessionState()
        return SessionSnapshot(state=state, turns=turns)

    def append_turn(self, session_id, turn):
        self.db.put_item(TableName=self.table, Item={
            "session_id": {"S": session_id}, "item_key": {"S": f"turn#{turn.turn:04d}"},
            "payload": self._s(asdict(turn)), "expires_at": self._expires()})

    def put_state(self, session_id, state):
        self.db.put_item(TableName=self.table, Item={
            "session_id": {"S": session_id}, "item_key": {"S": "state"},
            "payload": self._s(asdict(state)), "expires_at": self._expires()})


def default_store() -> SessionStore:
    """DynamoStore when GRAPHRAG_SESSIONS_TABLE is set (serving), else in-memory (local/dev)."""
    import os
    table = os.environ.get("GRAPHRAG_SESSIONS_TABLE")
    if table:
        try:
            return DynamoStore(table=table)
        except Exception:  # noqa: BLE001 — no boto3/creds -> degrade to local memory
            pass
    global _LOCAL
    try:
        _LOCAL
    except NameError:
        _LOCAL = InMemoryStore()
    return _LOCAL


# ── the prompt-facing state block + compaction ───────────────────────────────────────────────────
def state_block(snap: SessionSnapshot) -> str:
    """The CONVERSATION STATE block for the reasoner — labeled continuity context, explicitly NOT
    evidence (the reader instruction is the PIT guard's prompt-side half; the schema is the other)."""
    st = snap.state
    lines = ["=== PRIOR-CONVERSATION STATE (for coreference and continuity ONLY - this is NOT evidence; "
             "re-verify anything factual against THIS turn's evidence and numbers) ==="]
    if st.contracts:
        lines.append(f"- discussing contracts: {st.contracts}"
                     + (f" | focus driver: {st.focus_driver}" if st.focus_driver else ""))
    if st.asof_latest:
        lines.append(f"- prior as-of: {st.asof_latest}")
    if st.summary.get("thesis"):
        lines.append(f"- running thesis: {st.summary['thesis']}")
    if st.summary.get("open_threads"):
        lines.append(f"- open threads: {st.summary['open_threads']}")
    for t in snap.turns:
        lines.append(f"- turn {t.turn}: asked {t.query[:140]!r} -> {t.answer_tldr[:160]}")
    return "\n".join(lines)


def _summary_tool() -> dict:
    s = {"type": "string"}
    arr = {"type": "array", "items": s}
    return {"name": "roll_summary", "description": "Update the running conversation summary.",
            "input_schema": {"type": "object", "properties": {
                "entities": arr, "thesis": s, "open_threads": arr},
                "required": ["entities", "thesis"]}}


def roll_summary(state: SessionState, turn: TurnRecord, *, graph=None, call=None,
                 model: str = "claude-haiku-4-5") -> SessionState:
    """Phase-2 compaction: one cheap forced-tool call folds the turn into {entities, thesis,
    open_threads}. Deterministic guards: entities are validated against the graph's contract ids
    (the model cannot mint nodes into state); text fields are length-capped; any failure keeps the
    previous summary. Returns the updated state (also mutates in place)."""
    state.turn_count = turn.turn + 1
    state.contracts = turn.contracts or state.contracts
    state.focus_driver = turn.focus_driver or state.focus_driver
    state.asof_latest = turn.asof or state.asof_latest
    if call is None:
        return state                                              # summary is optional; structure carried above
    try:
        prev = json.dumps(state.summary, ensure_ascii=True)[:800]
        user = (f"PREVIOUS SUMMARY: {prev}\n"
                f"NEW TURN: asked {turn.query[:300]!r}; answered (tl;dr): {turn.answer_tldr[:300]!r}; "
                f"contracts {turn.contracts}; as-of {turn.asof}")
        out = call("Fold the new turn into a compact running summary of this commodity-research "
                   "conversation. Keep it factual and terse; entities = commodity contract ids only.",
                   user, model=model, tool=_summary_tool()) or {}
        known = set(getattr(graph, "contracts", {}) or {})
        ents = [e for e in (out.get("entities") or []) if not known or e in known][:8]
        # W5 F-H: the durable summary is injected into EVERY later turn's prompt, including plain mechanism
        # turns running the FENCED register -- so it is sanitized market_register="fenced" UNCONDITIONALLY.
        # The turn tl;dr feeding this call is already fenced at the orchestrator seam; this fences the
        # compactor's OWN paraphrase, which is the half a fenced input cannot cover.
        from leviathan.graphrag import register as _reg                # lazy: session is imported very early
        state.summary = {"entities": ents,
                         "thesis": _reg.sanitize(str(out.get("thesis") or ""), market_register=_reg.FENCED)[:400],
                         "open_threads": [_reg.sanitize(str(x), market_register=_reg.FENCED)[:160]
                                          for x in (out.get("open_threads") or [])[:5]]}
    except Exception:  # noqa: BLE001 — compaction must never break the turn
        pass
    return state


def cache_key(sql: str) -> str:
    import hashlib
    return hashlib.sha1(sql.encode()).hexdigest()


def cached_query_fn(state: SessionState, inner):
    """Session-scoped Athena reuse, keyed by the EXACT SQL (which embeds its own as-of guard — a
    different as-of can never collide). Values capped small; cache capped at MAX_NUMBERS_CACHE."""
    def q(sql: str):
        k = cache_key(sql)
        if k in state.numbers_cache:
            return state.numbers_cache[k]
        rows = inner(sql)
        try:
            if rows and len(json.dumps(rows, ensure_ascii=True)) <= MAX_CACHED_ROWS_CHARS \
                    and len(state.numbers_cache) < MAX_NUMBERS_CACHE:
                state.numbers_cache[k] = rows
        except Exception:  # noqa: BLE001
            pass
        return rows
    return q
