"""Terminal API response contract (build-plan P1 cross-cutting).

One Pydantic source of truth for the shapes the private `leviathan-terminal` frontend binds to (design §6).
`test_api_contract` asserts each route returns its model, and Phase 2 generates the TS types from these — so
backend/frontend drift is caught at compile time. Models are permissive (`extra="allow"`) where they wrap the
rich, evolving graph/silver/respond dicts: the CORE fields are pinned, extra fields ride along for
forward-compat rather than 500-ing a response."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

_RICH = ConfigDict(extra="allow")            # wraps a rich underlying dict; pin the core keys, allow the rest


# ── 1.2 cascade DAG topology (design §4.2) ─────────────────────────────────────────────────────────
class GraphNode(BaseModel):
    model_config = _RICH
    id: str
    kind: str                                # driver type | 'contract' | 'commodity'
    contract: str
    label: Optional[str] = None              # human node text (6.3) — de-underscored / official; never a raw slug
    silver_status: Optional[str] = None
    confidence: Optional[str] = None         # qualitative label in the causal schema ('high'/'medium'/'low')
    active: Optional[bool] = None            # firing overlay, only when ?asof= supplied


class GraphEdge(BaseModel):
    model_config = _RICH
    source: str
    target: str
    edge_type: str
    sign: Optional[str] = None
    lag: Optional[str] = None
    mechanism: Optional[str] = None
    confidence: Optional[str] = None         # qualitative label ('high'/'medium'/'low'), mirrors the driver


class GraphTopology(BaseModel):
    contract: str
    graph_version: Optional[str] = None
    asof: Optional[str] = None
    nodes: list[GraphNode]
    edges: list[GraphEdge]


# ── 1.3 / 1.4 convergence firing (design §4.8 / §4.4) ──────────────────────────────────────────────
class DriverSignal(BaseModel):
    model_config = _RICH
    id: str
    live: bool = False
    verdict: Optional[str] = None            # observed | normal | None (inconclusive/unresolved)
    z: Optional[float] = None
    value: Optional[Any] = None
    unit: str = ""
    ref: Optional[str] = None
    knowledge_date: str = ""


class RegimeCard(BaseModel):
    name: str
    direction: str                           # '+' bullish / '-' bearish
    matched: list[str]
    threshold: int
    fired: bool
    n_active: int
    proximity: float                         # n_active / threshold, capped 1.0 — heatmap shading


class ConvergenceRow(BaseModel):
    contract: str
    regimes: list[RegimeCard]
    drivers: list[DriverSignal]


class ConvergenceMatrix(BaseModel):
    asof: str
    graph_version: Optional[str] = None
    rows: list[ConvergenceRow]


# ── 1.5 vintage-aware series (design §4.5) ─────────────────────────────────────────────────────────
class Series(BaseModel):
    table: str
    metric: str
    commodity: Optional[str] = None
    asof: str                                # the vintage marker: everything shown was known at/below this
    unit: str = ""
    points: list[dict[str, Any]]             # rows {value, date/period, knowledge_date} <= asof


# ── 1.6 live events rail (design §4.7) ─────────────────────────────────────────────────────────────
class EventItem(BaseModel):
    model_config = _RICH
    source: str = ""
    title: str = ""
    summary: str = ""
    url: str = ""
    date: str = ""
    driver_id: Optional[str] = None
    commodity: Optional[str] = None


class EventsFeed(BaseModel):
    contract: Optional[str] = None
    asof: str
    live: bool                               # False (+ empty events) whenever asof < today (PIT kill-switch)
    events: list[EventItem]


# ── 1.7 share / persistence (design §6.7) ──────────────────────────────────────────────────────────
class ShareRef(BaseModel):
    id: str
    url: str


class ShareSnapshot(BaseModel):
    model_config = _RICH
    id: str
    question: str
    asof: Optional[str] = None
    graph_version: Optional[str] = None
    created_at: str
    payload: dict[str, Any]                  # the full immutable respond() dict — reproducible, forwardable


# ── 1.6 durable per-thread history (design §3.1) ───────────────────────────────────────────────────
class TurnRecord(BaseModel):
    """One durable turn in a thread — the CONCLUSION only (PIT firewall): question + synthesized answer +
    citation refs + the as-of/graph it was made under. NEVER carries retrieved evidence or raw number rows;
    those re-derive under the turn's own as-of if it is re-run."""
    model_config = _RICH
    question: Optional[str] = None
    answer: Optional[str] = None
    structured: Optional[dict[str, Any]] = None
    asof: Optional[str] = None
    sources: list[dict[str, Any]] = []       # citation refs only ({kind, ref, source, date}) — no evidence text
    graph_version: Optional[str] = None
    contract: Optional[str] = None
    contracts: list[str] = []
    intent: Optional[str] = None
    model: Optional[str] = None
    ts: Optional[str] = None


class ThreadTurns(BaseModel):
    thread_id: str
    turns: list[TurnRecord] = []


# ── 6.2 query suggester (decoupled Haiku side-channel; never touches the answer path) ───────────────
class SuggestRequest(BaseModel):
    """The turn packet the CLIENT sends after a completed turn (or `{}` on thread start). The server
    enriches with profile facts + cached news headlines — it never re-reads evidence or session state."""
    thread_id: Optional[str] = None
    question: Optional[str] = None
    tldr: Optional[str] = None
    contracts: list[str] = []
    intent: Optional[str] = None
    asof: Optional[str] = None


class SuggestResponse(BaseModel):
    """3-4 follow-up questions (or [] — over-cap, kill-switch, parse failure all degrade to empty;
    suggestions are a nicety and must never surface an error)."""
    suggestions: list[str] = []
