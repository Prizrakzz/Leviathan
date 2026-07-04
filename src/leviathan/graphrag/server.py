"""FastAPI + SSE serving service over orchestrator.respond() — the UI backend.

THIN CONDUCTOR by design: respond() stays framework-neutral (the same function the eval harness and
langgraph_app call); this module only translates HTTP <-> respond(). All resilience lives BELOW it
(providers.py retry/degradation, the orchestrator's evidence-only floor), so a request here returns a
respond()-shaped JSON even when the model tier is down.

Endpoints:
  GET  /healthz            — graph loaded + active provider + evidence backend (LB target check).
  POST /v1/respond         — {question, session_id?, asof?} -> the full respond() dict.
  GET  /v1/respond/stream  — same args as query params, SSE: `stage` heartbeats while the turn runs
                             (30-90s is normal), then ONE `result` event with the payload. respond()
                             is not a token stream — SSE here is keepalive + progress, not tokens.

Run (image ENTRYPOINT is `python`):  -m uvicorn leviathan.graphrag.server:app --host 0.0.0.0 --port 8080
Deployment (ECS service + ALB) is a separate gated infra step."""
from __future__ import annotations

import json
import os
import queue
import threading
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="leviathan-graphrag", version="0.1.0")

_STATE: dict = {}                                    # graph loads once, on first use (fork-safe, test-swappable)


def _graph():
    if "graph" not in _STATE:
        from leviathan.graphrag import graph as g
        _STATE["graph"] = g.CausalGraph.load()
    return _STATE["graph"]


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
def respond_route(body: Ask) -> dict:
    from leviathan.graphrag import orchestrator as orch
    return orch.respond(body.question, graph=_graph(), asof=body.asof, session_id=body.session_id)


@app.get("/v1/respond/stream")
def respond_stream(question: str, session_id: Optional[str] = None, asof: Optional[str] = None):
    """SSE wrapper: respond() runs in a worker thread; the stream stays alive with keepalive comments
    + `stage` events until the single terminal `result` (or `error`) event."""
    from leviathan.graphrag import orchestrator as orch

    def gen():
        out: queue.Queue = queue.Queue()

        def work() -> None:
            try:
                out.put(("result", orch.respond(question, graph=_graph(), asof=asof, session_id=session_id)))
            except Exception as e:  # noqa: BLE001 — the floor makes this near-impossible; belt + braces
                out.put(("error", {"error": f"{type(e).__name__}: {str(e)[:200]}"}))

        threading.Thread(target=work, daemon=True).start()
        yield 'event: stage\ndata: {"stage": "running"}\n\n'
        while True:
            try:
                kind, payload = out.get(timeout=10)
            except queue.Empty:
                yield ": keepalive\n\n"               # SSE comment — keeps ALB/proxy from idling out
                continue
            yield f"event: {kind}\ndata: {json.dumps(payload, default=str)}\n\n"
            return

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
