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


@app.on_event("startup")
def _warm_startup() -> None:
    """Cold-start hardening (Stage 5.3 R1): before the task takes traffic, sync the bge model cache from S3
    (avoids the ~327 s HuggingFace download on a fresh task) then warm bge-m3 so the FIRST real turn isn't the
    model load. BLOCKS startup on purpose — the ALB only routes to the task once /healthz answers, and the
    ECS health_check_grace (300 s) covers this window while the previous task (min=1) keeps serving. Every step
    is fail-open: a cache/warm hiccup degrades to the image's HF-download path, it never stops the task coming up.

    Gated on GRAPHRAG_HF_S3_CACHE (= s3://<bucket>/models/hf); unset -> pure passthrough (today's behavior, and
    the test/eval default — so importing the app never loads torch)."""
    uri = os.environ.get("GRAPHRAG_HF_S3_CACHE")
    if not uri:
        return
    t0 = time.time()
    try:
        from leviathan.graphrag import hf_cache
        res = hf_cache.ensure(uri)
        # NOTE: do NOT force HF_HUB_OFFLINE here. The S3-reconstructed cache flattens the snapshot->blob symlink
        # layout that offline resolution needs, so offline load raises "couldn't find them in the cached files".
        # Online load reads the cached safetensors + a cheap etag re-validation and never re-fetches the pruned
        # pytorch/onnx formats (sentence-transformers prefers safetensors) — proven by the pre-prune deploy.
        print(f"[warm] hf_cache {uri} -> {res} sync_ms={int((time.time() - t0) * 1000)}", flush=True)
    except Exception as e:  # noqa: BLE001 — degrade to the HF-download path; never block startup
        print(f"[warm] hf_cache FAILED ({type(e).__name__}: {e}); falling back to HF download", flush=True)
    tw = time.time()
    try:
        from leviathan.graphrag import evidence as ev
        ev.embed(["warmup"])                              # loads the bge-m3 query embedder into this process
        from leviathan.graphrag import rankers as rk
        if rk._rerank_backend() == "bge":                 # warm the cross-encoder only when it's the active backend
            rk.rerank_scores("warmup", ["warmup"])
        print(f"[warm] models warm_ms={int((time.time() - tw) * 1000)} total_ms={int((time.time() - t0) * 1000)}",
              flush=True)
    except Exception as e:  # noqa: BLE001 — warmup is best-effort; the first turn just pays the load
        print(f"[warm] model warm skipped ({type(e).__name__}: {e})", flush=True)


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
    monkeypatch this (or set _STATE['query_fn']) to avoid Athena. Routes through the RDS pg mirror when
    enabled (5.6 W6) — the convergence matrix's ~100+ sequential lookups were an Athena query storm
    (~15-30s cold + real S3 cost); pgnumbers keeps a per-request Athena fallback so a mirror gap degrades
    to Athena latency, never an error."""
    from leviathan.graphrag import silverleg as slv
    from leviathan.graphrag.numbers import pgnumbers
    from leviathan.graphrag.numbers import query as Q
    qfn = _STATE.get("query_fn") or (pgnumbers.query_fn() if pgnumbers.enabled() else Q.athena_query_fn())
    return slv.make_silver_lookup(_graph(), qfn, cap=cap)


def _require_user(authorization: Optional[str] = Header(None)) -> str:
    """Auth dependency (default-off; Phase-4 turns it on). Off -> a fixed local user; on -> a verified
    Cognito subject, else 401."""
    from leviathan.graphrag import auth
    try:
        return auth.user_from_header(authorization)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


def _require_identity(authorization: Optional[str] = Header(None)) -> dict:
    """Like `_require_user` but returns the full identity dict ({sub} + email/name/picture when the ID
    token carries them) — the profile record (5.6) needs the claims, not just the subject."""
    from leviathan.graphrag import auth
    try:
        return auth.identity_from_header(authorization)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


def _require_identity_quota(authorization: Optional[str] = Header(None)) -> dict:
    """`_require_identity` + a per-user DAILY turn cap (Stage 5, env `GRAPHRAG_TURN_QUOTA`). Each turn is
    real Bedrock spend, so an open-signup public deploy caps per-account velocity. Over the cap -> 429.
    Quota unset -> no cap; any counter/infra error -> ALLOW (fail-open; WAF rate-limit + the Bedrock daily
    budget are the hard backstops, a counter glitch must not lock out a paying user)."""
    ident = _require_identity(authorization)
    cap = os.environ.get("GRAPHRAG_TURN_QUOTA")
    if cap:
        from leviathan.graphrag import store as st
        try:
            _store().incr_turn_quota(ident["sub"], time.strftime("%Y-%m-%d", time.gmtime()), int(cap))
        except st.QuotaExceeded:
            raise HTTPException(status_code=429, detail=f"daily turn limit ({cap}) reached; try again tomorrow")
        except Exception:  # noqa: BLE001 — fail open on any non-quota error
            pass
    return ident


def _trim_citation_provenance(citations: list) -> list:
    """Durable citations = refs + provenance POINTERS, not evidence text (PIT firewall). Each evidence
    citation's payload carries the full retrieved text; drop it (keep only {source_key}) — the 140-char
    display receipt survives on `locator.snippet` (6.4). Numbers payloads ({query, rows[:3]}) are the
    re-runnable, leakage-safe provenance and stay. Idempotent; a non-dict/foreign shape passes through."""
    out = []
    for c in (citations or []):
        if not isinstance(c, dict):
            out.append(c)
            continue
        if c.get("kind") == "evidence":
            pay = c.get("payload") or {}
            c = {**c, "payload": {"source_key": pay.get("source_key")}}   # drop the full evidence text
        out.append(c)
    return out


def _turn_record(result: dict, question: str) -> dict:
    """A PIT-safe durable turn from a respond() result: the synthesized answer + citation refs/POINTERS +
    the as-of/graph it was made under. NEVER the retrieved evidence text or trace; `_trim_citation_provenance`
    strips full evidence text off citation payloads (keeping source_key + the locator snippet), and
    store.sanitize_turn is the allowlist backstop. `question` comes from the REQUEST (the server owns it) —
    respond()'s result never carries one, so `result.get("question")` stored null and broke the frontend's
    per-question dedup (5.8 fix)."""
    trace = result.get("trace") or {}
    return {
        "question": question,
        "answer": result.get("answer"),
        "structured": result.get("structured"),
        "asof": result.get("asof"),
        "sources": _trim_citation_provenance(result.get("citations") or []),   # refs + pointers, no evidence text
        "graph_version": trace.get("graph_version"),
        "contract": result.get("contract"),
        "contracts": result.get("contracts") or [],
        "intent": result.get("intent"),
        "model": result.get("model"),
    }


def _autotitle_thread(user: str, thread_id: str, question: str, fallback: str) -> None:
    """Haiku 3-6 word thread title, fire-and-forget (daemon thread). Writes ONLY if the title is still the
    truncated-question fallback and the user hasn't renamed (title_auto) — so a rename that raced in wins.
    Injectable via _STATE['title_call'] for tests."""
    try:
        call = _STATE.get("title_call")
        if call is None:
            from leviathan.graphrag import providers as pv
            def call(q: str) -> str:
                client = pv.make_client()
                out = client.messages.create(
                    model=pv.resolve_model("claude-haiku-4-5"), max_tokens=30,
                    messages=[{"role": "user", "content":
                               "Give a terse 3-6 word title for a commodity-research thread that starts "
                               f"with this question. Title only, no quotes, ASCII.\n\nQ: {q[:400]}"}])
                return "".join(b.text for b in out.content if getattr(b, "type", "") == "text").strip()
        title = (call(question) or "").strip().strip('"')[:80]
        if not title:
            return
        cur = _store().get_item(user, "thread", thread_id) or {}
        if cur.get("title_auto") or (cur.get("title") or "") not in ("", fallback):
            return                                                   # user renamed (or state moved on) — keep theirs
        _store().put_item(user, "thread", thread_id, {**cur, "title": title, "updated_at": cur.get("updated_at")
                          or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    except Exception:  # noqa: BLE001 — a title is a nicety; never surface a failure
        pass


def _ensure_thread_index(user: str, thread_id: str, question: str) -> None:
    """Server-authoritative thread index (5.6): every saved turn upserts the thread item so the sidebar
    list never depends on the client's best-effort registration. First turn also kicks the Haiku
    auto-title (gated on GRAPHRAG_THREAD_TITLES; default off = tests/eval unchanged)."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    existing = _store().get_item(user, "thread", thread_id)
    fallback = (question or "").strip()[:80] or thread_id
    body = {
        "title": (existing or {}).get("title") or fallback,
        "title_auto": bool((existing or {}).get("title_auto", False)),
        "created_at": (existing or {}).get("created_at") or now,
        "updated_at": now,
    }
    _store().put_item(user, "thread", thread_id, body)
    if existing is None and os.environ.get("GRAPHRAG_THREAD_TITLES", "off").lower() == "on":
        threading.Thread(target=_autotitle_thread, args=(user, thread_id, question, body["title"]),
                         daemon=True).start()


def _save_turn(ident: dict, session_id: Optional[str], result: dict, *, question: str = "") -> None:
    """Append a durable, PIT-safe turn to the thread's history + upsert the thread index + touch the
    user's profile record. Fail-open + no-op without a thread id: persistence must NEVER break or slow
    a turn. `ident` = {sub, email?, name?, ...} from the verified token (a plain user id string also
    works for older callers/tests). `question` = the request text (the server owns it; not read back from
    respond()'s result, which never carries one)."""
    if isinstance(ident, str):                                       # tolerate the pre-5.6 signature
        ident = {"sub": ident}
    user = ident["sub"]
    try:
        _store().touch_profile(user, email=ident.get("email"), name=ident.get("name"))
    except Exception:  # noqa: BLE001 — the profile record is best-effort bookkeeping
        pass
    if not session_id:
        return
    try:
        _store().append_turn(user, session_id, _turn_record(result, question))
        _ensure_thread_index(user, session_id, question)
    except Exception:  # noqa: BLE001 — history is best-effort; a store glitch must not fail the answer
        pass


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
def respond_route(body: Ask, ident: dict = Depends(_require_identity_quota)) -> dict:
    # Auth + per-user daily quota gated (Stage 4/5): a turn is Bedrock spend, so only signed-in users within
    # their daily cap may run it. When GRAPHRAG_AUTH is off (dev/eval) this is a no-op.
    from leviathan.graphrag import orchestrator as orch
    result = orch.respond(body.question, graph=_graph(), asof=body.asof, session_id=body.session_id)
    _save_turn(ident, body.session_id, result, question=body.question)   # durable history (PIT-safe, fail-open)
    return result


@app.get("/v1/respond/stream")
def respond_stream(question: str, session_id: Optional[str] = None, asof: Optional[str] = None,
                   ident: dict = Depends(_require_identity_quota)):
    """SSE wrapper: respond() runs in a worker thread; the stream relays each `on_stage` tick as its own
    `stage` event, then the single terminal `result` (or `error`)."""
    from leviathan.graphrag import orchestrator as orch

    def gen():
        out: queue.Queue = queue.Queue()

        def on_stage(stage: str, info: dict) -> None:
            out.put(("stage", {"stage": stage, **(info or {})}))   # granular pipeline ticks (P1.1) from the worker

        def work() -> None:
            try:
                result = orch.respond(question, graph=_graph(), asof=asof, session_id=session_id,
                                      on_stage=on_stage)
                out.put(("result", result))               # deliver the note FIRST — the user isn't waiting on persistence
                _save_turn(ident, session_id, result, question=question)  # then durable history (fail-open, off the perceived path)
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
def _conv_warm_once() -> None:
    """Compute the LIVE-asof convergence matrix into _STATE['conv_warm'] (5.6 W6). One entry, keyed
    (asof, graph_version); the route serves it instantly on key match. Historical as-ofs stay on the
    on-demand path."""
    from leviathan.graphrag import firing as F
    t0 = time.time()
    asof = _today()
    g = _graph()
    key = (asof, getattr(g, "version", None))
    rows = F.convergence_matrix(g, asof, _silver_lookup(),
                                workers=int(os.environ.get("GRAPHRAG_CONVERGENCE_WORKERS", "8")))
    out = M.ConvergenceMatrix(asof=asof, graph_version=key[1], rows=rows).model_dump()
    _STATE["conv_warm"] = (time.time(), key, out)
    print(f"[warm] convergence asof={asof} rows={len(rows)} ms={int((time.time() - t0) * 1000)}", flush=True)


def _conv_warm_loop() -> None:
    interval = int(os.environ.get("GRAPHRAG_CONVERGENCE_WARM_INTERVAL", "900"))
    while True:
        try:
            _conv_warm_once()
        except Exception as e:  # noqa: BLE001 — the warm cache is an optimization; the route still computes
            print(f"[warm] convergence FAILED ({type(e).__name__}: {str(e)[:160]})", flush=True)
        slept = 0
        day = _today()
        while slept < interval and _today() == day:      # re-fire early on UTC-midnight rollover
            time.sleep(15)
            slept += 15


@app.on_event("startup")
def _warm_convergence() -> None:
    """Convergence warmer (5.6 W6): a NON-blocking daemon loop that keeps the live-asof matrix hot so the
    heatmap opens in <1s instead of a cold multi-second lookup fan-out. Registered AFTER _warm_startup
    (FastAPI runs startup hooks in order), gated on GRAPHRAG_CONVERGENCE_WARM=on — unset (tests/dev/eval)
    is a pure no-op."""
    if os.environ.get("GRAPHRAG_CONVERGENCE_WARM", "off").lower() != "on":
        return
    threading.Thread(target=_conv_warm_loop, daemon=True).start()


@app.get("/v1/convergence", response_model=M.ConvergenceMatrix)
def convergence_route(asof: Optional[str] = Query(None)) -> dict:
    from leviathan.graphrag import firing as F
    asof = asof or _today()
    g = _graph()
    key = (asof, getattr(g, "version", None))
    warm = _STATE.get("conv_warm")
    if warm and warm[1] == key:                                    # warmer-maintained live matrix (5.6 W6)
        return warm[2]
    cache_on = os.environ.get("GRAPHRAG_CONVERGENCE_CACHE", "off").lower() == "on"
    if cache_on:                                                   # per-(asof, graph_version) TTL cache (deploy)
        hit = _STATE.get("conv_cache", {}).get(key)
        if hit and (time.time() - hit[0]) < int(os.environ.get("GRAPHRAG_CONVERGENCE_TTL", "120")):
            return hit[1]
    rows = F.convergence_matrix(g, asof, _silver_lookup(),
                                workers=int(os.environ.get("GRAPHRAG_CONVERGENCE_WORKERS", "8")))
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


# ── 6.2 query suggester — decoupled Haiku side-channel (never touches the answer path) ──────────────
_SUGGEST_NEWS_TTL = 900   # seconds; headlines refresh at most 4x/hour, off the request path


def _suggest_news() -> list[str]:
    """Top headlines for the suggester prompt — cached, STALE-WHILE-REVALIDATE. Serves whatever is
    cached immediately; on TTL expiry a daemon thread does ONE keyless `nf.gather()` sweep (raw
    headlines, NO LLM — /v1/events' per-call fetch+extract is exactly what this must not do). A fetch
    error keeps the stale list; the first-ever call returns [] and warms in the background."""
    now = time.time()
    ts, items = _STATE.get("suggest_news") or (0.0, [])
    if now - ts > _SUGGEST_NEWS_TTL and not _STATE.get("suggest_news_refreshing"):
        _STATE["suggest_news_refreshing"] = True

        def _refresh(stale=items):
            try:
                from leviathan.graphrag import orchestrator as orch
                from leviathan.graphrag.news import fetch as nf
                got = nf.gather(orch._live_search_terms("", _graph()))
                heads = [str(i.get("headline") or "").strip() for i in (got or [])]
                _STATE["suggest_news"] = (time.time(), [h for h in heads if h][:8])
            except Exception:  # noqa: BLE001 — keep the stale list; never retry-storm
                _STATE["suggest_news"] = (time.time(), stale)
            finally:
                _STATE.pop("suggest_news_refreshing", None)

        threading.Thread(target=_refresh, daemon=True).start()
    return items


def _suggest_prompt(body: M.SuggestRequest, facts: Optional[dict]) -> str:
    """The Haiku prompt: role + strict output contract + the turn packet + optional facts/headlines.
    ASCII, hard-truncated fields (the packet is client-supplied text)."""
    lines = [
        "You suggest the NEXT question a commodity researcher would ask in a research terminal that",
        "answers from causal driver graphs, official-source evidence (USDA/WASDE/GAIN etc.) and",
        "supply/demand balance sheets, with an interest in convexity (buffer exhaustion, regime tips).",
        "Return ONLY a JSON array of 3-4 short questions. Each: under 110 characters, plain English,",
        "ASCII, specific and answerable from fundamentals -- no internal identifiers, no code_like_names,",
        "no price targets. Mix: one going deeper on the last answer, one on an adjacent contract or",
        "driver, and one time-aware question when headlines are given.",
    ]
    if body.question or body.tldr:
        if body.question:
            lines.append(f"\nLast question: {body.question[:300]}")
        if body.tldr:
            lines.append(f"Answer TL;DR: {body.tldr[:400]}")
        if body.contracts:
            lines.append("Contracts in focus: " + ", ".join(c.replace("_", " ") for c in body.contracts[:4]))
    else:
        lines.append("\nThis is a NEW empty session -- suggest strong starter questions a researcher"
                     " would actually ask today.")
    interests = (facts or {}).get("markets") or (facts or {}).get("interests")
    if interests:
        lines.append("User interests: " + (", ".join(interests) if isinstance(interests, list) else str(interests))[:200])
    heads = _suggest_news()
    if heads:
        lines.append("Today's headlines:\n" + "\n".join(f"- {h[:160]}" for h in heads))
    return "\n".join(lines)


def _parse_suggestions(raw: str) -> list[str]:
    """First JSON array in the completion -> <=4 clean chips. Deterministic guards (the one-vocab
    doctrine applies to chips): strings only, trimmed, <=140 chars, ZERO register leaks (an internal
    id can never render as a chip), deduped. Anything unparseable -> []."""
    from leviathan.graphrag import register as reg
    m = None
    try:
        a, b = raw.index("["), raw.rindex("]")
        m = json.loads(raw[a:b + 1])
    except Exception:  # noqa: BLE001 — parse failure -> no chips, never an error
        return []
    out: list[str] = []
    for s in (m if isinstance(m, list) else []):
        if not isinstance(s, str):
            continue
        s = s.strip().strip('"').strip()
        if not s or len(s) > 140 or s in out or reg.register_leaks(s):
            continue
        out.append(s)
    return out[:4]


@app.post("/v1/suggest", response_model=M.SuggestResponse)
def suggest_route(body: M.SuggestRequest, ident: dict = Depends(_require_identity)) -> dict:
    """3-4 follow-up questions for the completed turn (or starters for `{}`). Fired once per turn BY THE
    CLIENT; identity-gated but NEVER the turn quota — a separate namespaced daily counter caps the Haiku
    spend, and every failure mode degrades to `[]` (chips are a nicety, never an error state)."""
    empty = M.SuggestResponse(suggestions=[]).model_dump()
    if os.environ.get("GRAPHRAG_SUGGEST", "on").lower() != "on":       # kill-switch, no redeploy
        return empty
    from leviathan.graphrag import store as st
    try:                                                               # sk=quota#suggest#<day> — the turn
        cap = int(os.environ.get("GRAPHRAG_SUGGEST_QUOTA", "200"))     # quota counter is untouched
        _store().incr_turn_quota(ident["sub"], f"suggest#{time.strftime('%Y-%m-%d', time.gmtime())}", cap)
    except st.QuotaExceeded:
        return empty
    except Exception:  # noqa: BLE001 — counter glitch -> fail open
        pass
    try:
        facts = (_store().get_profile(ident["sub"]) or {}).get("facts")
    except Exception:  # noqa: BLE001
        facts = None
    prompt = _suggest_prompt(body, facts if isinstance(facts, dict) else None)
    try:
        call = _STATE.get("suggest_call")
        if call is None:
            from leviathan.graphrag import providers as pv
            def call(p: str) -> str:
                client = pv.make_client()
                out = client.messages.create(model=pv.resolve_model("claude-haiku-4-5"), max_tokens=200,
                                             messages=[{"role": "user", "content": p}])
                return "".join(b.text for b in out.content if getattr(b, "type", "") == "text").strip()
        return M.SuggestResponse(suggestions=_parse_suggestions(call(prompt) or "")).model_dump()
    except Exception:  # noqa: BLE001 — model/provider failure -> no chips
        return empty


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


def _register_item_routes(coll: str, kind: str, purge=None, on_list=None) -> None:
    def _list(ident: dict = Depends(_require_identity)) -> dict:
        if on_list is not None:
            try:
                on_list(ident)
            except Exception:  # noqa: BLE001 — listing must never fail on a side-effect
                pass
        items = _store().list_items(ident["sub"], kind)
        items.sort(key=lambda b: b.get("updated_at") or "", reverse=True)   # newest first for the sidebar
        return {"items": items}

    def _put(body: ItemIn, user: str = Depends(_require_user)) -> dict:
        from leviathan.graphrag import store as st
        item_id = body.id or st.new_id()
        _store().put_item(user, kind, item_id, body.body or {})
        return {"id": item_id}

    def _del(item_id: str, user: str = Depends(_require_user)) -> dict:
        if purge is not None:
            purge(user, item_id)                          # purge FIRST: a failure leaves the item retryable
        _store().delete_item(user, kind, item_id)
        return {"ok": True}

    app.add_api_route(f"/v1/{coll}", _list, methods=["GET"])
    app.add_api_route(f"/v1/{coll}", _put, methods=["POST"])
    app.add_api_route(f"/v1/{coll}/{{item_id}}", _del, methods=["DELETE"])


def _touch_profile_async(ident: dict) -> None:
    """Fire-and-forget profile upsert on the threads list (once per app boot) — records users who signed
    in but never ran a turn. Daemon thread: never adds latency to the listing."""
    threading.Thread(
        target=lambda: _store().touch_profile(ident["sub"], email=ident.get("email"),
                                              name=ident.get("name"), count_turn=False),
        daemon=True).start()


for _coll, _kind, _purge, _on_list in (
    ("threads", "thread", lambda u, tid: _store().delete_turns(u, tid), _touch_profile_async),
    ("watchlists", "watchlist", None, None),
    ("workspaces", "workspace", None, None),
):
    _register_item_routes(_coll, _kind, purge=_purge, on_list=_on_list)


@app.get("/v1/threads/{thread_id}/turns", response_model=M.ThreadTurns)
def thread_turns(thread_id: str, user: str = Depends(_require_user)) -> dict:
    """Durable per-thread history (design §3.1) — the PIT-safe turn records for a thread, oldest-first.
    Conclusions + citation refs only; evidence is never persisted (re-derived on re-run)."""
    return {"thread_id": thread_id, "turns": _store().list_turns(user, thread_id)}
