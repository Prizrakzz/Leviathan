"""FastAPI + SSE serving service over orchestrator.respond() — the terminal (UI) backend.

THIN CONDUCTOR by design: respond() stays framework-neutral (the same function the eval harness and
langgraph_app call); this module only translates HTTP <-> the deterministic graph/silver logic. All
resilience lives BELOW it (providers.py retry/degradation, the orchestrator's evidence-only floor), so a
request here returns a shaped JSON even when the model tier is down.

Endpoints (build-plan Phase 1 — all additive, deterministic, no new LLM spend except /v1/events live-fetch):
  GET  /healthz                       — graph loaded + provider + evidence backend + graph_version.
  POST /v1/respond                    — {question, session_id?, asof?} -> the full respond() dict.
  GET  /v1/respond/stream             — SSE: granular `stage` ticks (planning/walking/retrieving/numbers/
                                        verifying), then ONE terminal `result` (or `error`).
  GET  /v1/graph/{contract}?asof=     — cascade DAG topology (+ firing overlay when asof given).      §4.2
  GET  /v1/convergence?asof=          — 31-contract regime matrix (silver-observed firing).           §4.8
  GET  /v1/regimes/{contract}?asof=   — one contract's regimes + driver signals for the gauges.       §4.4
  GET  /v1/series/{table}/{metric}    — vintage-aware series <= asof for the sparklines.              §4.5
  GET  /v1/events?contract=&asof=     — live-events feed; empty when asof<today (PIT kill-switch).    §4.7
  POST /v1/share , GET /v1/share/{id} — immutable, reproducible note snapshot (pins graph_version).  §6.7
  GET/POST/DELETE /v1/{threads,watchlists,workspaces} — per-user persistence.

Run (image ENTRYPOINT is `python`):  -m uvicorn leviathan.graphrag.server:app --host 0.0.0.0 --port 8080
Deployment (ECS + ALB, Cognito enforcement, durable table, prod CORS origin) is a Phase-4 gated step."""
from __future__ import annotations

import json
import os
import queue
import threading
import time
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from leviathan.graphrag import api_models as M

app = FastAPI(title="leviathan-graphrag", version="0.1.0")

# CORS: allowlist the app origin(s) only (env-driven; localhost dev default). Prod origin set at deploy.
_ORIGINS = [o.strip() for o in os.environ.get("GRAPHRAG_CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

_STATE: dict = {}                                    # graph/store load once, on first use (fork-safe, test-swappable)


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _graph():
    if "graph" not in _STATE:
        from leviathan.graphrag import graph as g
        _STATE["graph"] = g.CausalGraph.load()
    return _STATE["graph"]


def _store():
    if "store" not in _STATE:
        from leviathan.graphrag import store as st
        _STATE["store"] = st.default_store()
    return _STATE["store"]


def _silver_lookup(cap: int = 256):
    """The deterministic OBSERVED-value lookup the firing endpoints share with the answer path. Tests
    monkeypatch this (or set _STATE['query_fn']) to avoid Athena."""
    from leviathan.graphrag import silverleg as slv
    from leviathan.graphrag.numbers import query as Q
    qfn = _STATE.get("query_fn") or Q.athena_query_fn()
    return slv.make_silver_lookup(_graph(), qfn, cap=cap)


def _require_user(authorization: Optional[str] = Header(None)) -> str:
    """Auth dependency (default-off; Phase-4 turns it on). Off -> a fixed local user; on -> a verified
    Cognito subject, else 401."""
    from leviathan.graphrag import auth
    try:
        return auth.user_from_header(authorization)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


# ── existing serving surface ────────────────────────────────────────────────────────────────────────
class Ask(BaseModel):
    question: str
    session_id: Optional[str] = None
    asof: Optional[str] = None                       # explicit as-of always beats session carry (PIT rule)


@app.get("/healthz")
def healthz() -> dict:
    from leviathan.graphrag import providers as pv
    return {"status": "ok", "contracts": len(_graph().contracts), "provider": pv.provider(),
            "evidence_backend": os.environ.get("EVIDENCE_BACKEND", "local"),
            "graph_version": getattr(_graph(), "version", None)}


@app.post("/v1/respond")
def respond_route(body: Ask, user: str = Depends(_require_user)) -> dict:
    # Auth-gated (Stage 4): a turn is Bedrock spend, so only signed-in users may run it. When GRAPHRAG_AUTH
    # is off (dev/eval), _require_user returns the local user and this is a no-op.
    from leviathan.graphrag import orchestrator as orch
    return orch.respond(body.question, graph=_graph(), asof=body.asof, session_id=body.session_id)


@app.get("/v1/respond/stream")
def respond_stream(question: str, session_id: Optional[str] = None, asof: Optional[str] = None,
                   user: str = Depends(_require_user)):
    """SSE wrapper: respond() runs in a worker thread; the stream relays each `on_stage` tick as its own
    `stage` event, then the single terminal `result` (or `error`)."""
    from leviathan.graphrag import orchestrator as orch

    def gen():
        out: queue.Queue = queue.Queue()

        def on_stage(stage: str, info: dict) -> None:
            out.put(("stage", {"stage": stage, **(info or {})}))   # granular pipeline ticks (P1.1) from the worker

        def work() -> None:
            try:
                out.put(("result", orch.respond(question, graph=_graph(), asof=asof, session_id=session_id,
                                                 on_stage=on_stage)))
            except Exception as e:  # noqa: BLE001 — the floor makes this near-impossible; belt + braces
                out.put(("error", {"error": f"{type(e).__name__}: {str(e)[:200]}"}))

        threading.Thread(target=work, daemon=True).start()
        yield 'event: stage\ndata: {"stage": "accepted"}\n\n'      # immediate ack before the first planning tick
        while True:
            try:
                kind, payload = out.get(timeout=10)
            except queue.Empty:
                yield ": keepalive\n\n"               # SSE comment — keeps ALB/proxy from idling out
                continue
            yield f"event: {kind}\ndata: {json.dumps(payload, default=str)}\n\n"
            if kind in ("result", "error"):          # terminal event — close the stream (stages precede it)
                return

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── 1.2 cascade DAG topology ──────────────────────────────────────────────────────────────────────
@app.get("/v1/graph/{contract}", response_model=M.GraphTopology)
def graph_route(contract: str, asof: Optional[str] = Query(None)) -> dict:
    try:
        topo = _graph().topology(contract)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown contract {contract!r}")
    if asof:                                                        # overlay OBSERVED-active drivers (dim the rest)
        from leviathan.graphrag import firing as F
        try:
            fired = F.fire_contract(_graph(), contract, asof, _silver_lookup())
            active = {d["id"] for d in fired["drivers"] if d.get("live") and d.get("verdict") == "observed"}
            for n in topo["nodes"]:
                if n["kind"] not in ("contract", "commodity"):
                    n["active"] = n["id"] in active
        except Exception:  # noqa: BLE001 — a silver miss must never break the topology view
            pass
    return M.GraphTopology(contract=contract, graph_version=topo["graph_version"], asof=asof,
                           nodes=topo["nodes"], edges=topo["edges"]).model_dump()


# ── 1.3 convergence matrix ──────────────────────────────────────────────────────────────────────────
@app.get("/v1/convergence", response_model=M.ConvergenceMatrix)
def convergence_route(asof: Optional[str] = Query(None)) -> dict:
    from leviathan.graphrag import firing as F
    asof = asof or _today()
    g = _graph()
    key = (asof, getattr(g, "version", None))
    cache_on = os.environ.get("GRAPHRAG_CONVERGENCE_CACHE", "off").lower() == "on"
    if cache_on:                                                   # per-(asof, graph_version) TTL cache (deploy)
        hit = _STATE.get("conv_cache", {}).get(key)
        if hit and (time.time() - hit[0]) < int(os.environ.get("GRAPHRAG_CONVERGENCE_TTL", "120")):
            return hit[1]
    rows = F.convergence_matrix(g, asof, _silver_lookup())
    out = M.ConvergenceMatrix(asof=asof, graph_version=getattr(g, "version", None), rows=rows).model_dump()
    if cache_on:
        _STATE.setdefault("conv_cache", {})[key] = (time.time(), out)
    return out


# ── 1.4 per-contract regimes (gauges) ────────────────────────────────────────────────────────────────
@app.get("/v1/regimes/{contract}", response_model=M.ConvergenceRow)
def regimes_route(contract: str, asof: Optional[str] = Query(None)) -> dict:
    from leviathan.graphrag import firing as F
    asof = asof or _today()
    try:
        row = F.fire_contract(_graph(), contract, asof, _silver_lookup())
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown contract {contract!r}")
    return M.ConvergenceRow(**row).model_dump()


# ── 1.5 vintage-aware series ─────────────────────────────────────────────────────────────────────────
@app.get("/v1/series/{table}/{metric}", response_model=M.Series)
def series_route(table: str, metric: str, commodity: Optional[str] = Query(None),
                 country: Optional[str] = Query(None), asof: Optional[str] = Query(None)) -> dict:
    from leviathan.graphrag.numbers import query as Q
    from leviathan.graphrag.numbers.registry import load_registry
    asof = asof or _today()
    reg = load_registry()
    try:
        ts = reg.get(table)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown table {table!r}")
    if ts is None:
        raise HTTPException(status_code=404, detail=f"unknown table {table!r}")
    if ts.metrics and metric not in ts.metrics:                   # registry-validated -> never an open query hole
        raise HTTPException(status_code=400, detail=f"unknown metric {metric!r} for {table!r}")
    spec = Q.NumberQuery(table=table, metric=metric, asof=asof, commodity=commodity, country=country, agg="series")
    try:
        rows = Q.run(spec, query_fn=_STATE.get("query_fn"))
    except Exception as e:  # noqa: BLE001 — a query failure is a 502, never a 500 stacktrace to the UI
        raise HTTPException(status_code=502, detail=f"series query failed: {type(e).__name__}")
    unit = ts.metrics[metric].unit if (ts.metrics and metric in ts.metrics) else ""
    return M.Series(table=table, metric=metric, commodity=commodity, asof=asof, unit=unit, points=rows).model_dump()


# ── 1.6 live events rail (PIT kill-switch visible) ──────────────────────────────────────────────────
@app.get("/v1/events", response_model=M.EventsFeed)
def events_route(contract: Optional[str] = Query(None), asof: Optional[str] = Query(None)) -> dict:
    asof = asof or _today()
    if asof < _today():                                           # PIT kill-switch: no headlines behind an as-of
        return M.EventsFeed(contract=contract, asof=asof, live=False, events=[]).model_dump()
    from leviathan.graphrag import answer as an
    from leviathan.graphrag import orchestrator as orch
    from leviathan.graphrag.news import extract_live as nx
    from leviathan.graphrag.news import fetch as nf
    try:
        terms = orch._live_search_terms(contract or "", _graph())
        items = nf.gather(terms)
        evs = nx.extract_events(items, call=an._call_opus, graph=_graph()) if items else []
        events = [M.EventItem(**e.model_dump()) for e in evs]
    except Exception:  # noqa: BLE001 — the rail is best-effort context; never 500 the terminal
        events = []
    return M.EventsFeed(contract=contract, asof=asof, live=True, events=events).model_dump()


# ── 1.7 share snapshots + per-user persistence (auth default-off) ───────────────────────────────────
class ShareIn(BaseModel):
    question: str
    asof: Optional[str] = None
    payload: dict[str, Any]


class ItemIn(BaseModel):
    id: Optional[str] = None
    body: dict[str, Any] = {}


@app.post("/v1/share", response_model=M.ShareRef)
def share_create(body: ShareIn, user: str = Depends(_require_user)) -> dict:
    from leviathan.graphrag import store as st
    snap = st.make_share(body.question, body.asof, body.payload)
    _store().put_share(snap)
    return M.ShareRef(id=snap.id, url=f"/s/{snap.id}").model_dump()


@app.get("/v1/share/{share_id}", response_model=M.ShareSnapshot)
def share_get(share_id: str) -> dict:                             # public read (a share link is shareable)
    snap = _store().get_share(share_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="no such share")
    return M.ShareSnapshot(**snap.to_dict()).model_dump()


def _register_item_routes(coll: str, kind: str) -> None:
    def _list(user: str = Depends(_require_user)) -> dict:
        return {"items": _store().list_items(user, kind)}

    def _put(body: ItemIn, user: str = Depends(_require_user)) -> dict:
        from leviathan.graphrag import store as st
        item_id = body.id or st.new_id()
        _store().put_item(user, kind, item_id, body.body or {})
        return {"id": item_id}

    def _del(item_id: str, user: str = Depends(_require_user)) -> dict:
        _store().delete_item(user, kind, item_id)
        return {"ok": True}

    app.add_api_route(f"/v1/{coll}", _list, methods=["GET"])
    app.add_api_route(f"/v1/{coll}", _put, methods=["POST"])
    app.add_api_route(f"/v1/{coll}/{{item_id}}", _del, methods=["DELETE"])


for _coll, _kind in (("threads", "thread"), ("watchlists", "watchlist"), ("workspaces", "workspace")):
    _register_item_routes(_coll, _kind)
