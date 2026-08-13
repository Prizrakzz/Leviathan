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
  GET  /v1/gallery                    — curated starter prompts, filled from the warm convergence catalog
                                        (deterministic, no model call, no quota; D-AM-16).
  GET  /v1/credits                    — {remaining, limit, reset_at} of the monthly CREDIT grant that the
                                        metered depth tier spends (D-MW-24; 404 while GRAPHRAG_CREDITS is
                                        dark, because then nothing is metered).
  POST /v1/share , GET /v1/share/{id} — immutable, reproducible note snapshot (pins graph_version).  §6.7
  GET/POST/DELETE /v1/{threads,watchlists,workspaces,artifacts} — per-user persistence (artifacts =
                                        a named, PRIVATE freeze of one answer turn; D-AM-15).
  POST /v1/dossier , GET /v1/dossier/{id} , /v1/dossier/{id}/events , /v1/dossier/quota — the
                                        deep-research dossier job (D-DR; dark behind GRAPHRAG_DOSSIER,
                                        4 per user per UTC calendar month, result lands as a frozen
                                        artifact).

Run (image ENTRYPOINT is `python`):  -m uvicorn leviathan.graphrag.server:app --host 0.0.0.0 --port 8080
Deployment (ECS + ALB, Cognito enforcement, durable table, prod CORS origin) is a Phase-4 gated step."""
from __future__ import annotations

import functools
import json
import os
import queue
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
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
        # D-MW-5: warm the bge cross-encoder on EVERY serving start, whatever backend is active -- it is
        # the FALLBACK for both managed lanes, and the first throttle-induced fallback on a fresh task
        # otherwise pays a cold CrossEncoder load PLUS 13.88 s/60-doc inside the global rerank lock (at
        # 32-node walks: a multi-minute first fallback, during an incident). Called through the bge leaf
        # DIRECTLY, never rerank_scores -- dispatching would spend a live managed request on the word
        # "warmup" at boot. hf_cache above stays seeded, so an outage never triggers an HF download.
        # record=False: the ~14 s cold load must NOT publish a latency sample onto the active backend's
        # alarm series at every task start (diff-review catch).
        rk._bge_rerank_scores("warmup", ["warmup"], record=False)
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


def _s3():
    """A process-wide boto3 S3 client for the read-routes (PDF recovery). Loaded once, test-swappable via
    _STATE['s3']. Uses the shared retry config so a transient S3 blip degrades rather than 500s."""
    if "s3" not in _STATE:
        import boto3
        from botocore.config import Config
        _STATE["s3"] = boto3.client(
            "s3", region_name=os.environ.get("AWS_REGION", "us-east-1"),
            config=Config(retries={"max_attempts": 5, "mode": "adaptive"}))
    return _STATE["s3"]


def _silver_lookup(cap: int = 256):
    """The deterministic OBSERVED-value lookup the firing endpoints share with the answer path. Tests
    monkeypatch this (or set _STATE['query_fn']) to avoid Athena. Routes through the RDS pg mirror when
    enabled (5.6 W6) — the convergence matrix's ~100+ sequential lookups were an Athena query storm
    (~15-30s cold + real S3 cost); pgnumbers keeps a per-request Athena fallback so a mirror gap degrades
    to Athena latency, never an error."""
    from leviathan.graphrag import answer as _an
    from leviathan.graphrag import silverleg as slv
    from leviathan.graphrag.numbers import pgnumbers
    from leviathan.graphrag.numbers import query as Q
    qfn = _STATE.get("query_fn") or (pgnumbers.query_fn() if pgnumbers.enabled() else Q.athena_query_fn())
    # T1: GRAPHRAG_CONVERGENCE_INTENSITY read at this SERVER seam, threaded as a kwarg (never inside
    # silverleg). Intensity reaches the FE ONLY via the DriverSignal-serializing routes (/v1/convergence,
    # /v1/regimes/{contract}) as an UNDECLARED extra key; the map route discards driver rows ([SKEPTIC F4]).
    return slv.make_silver_lookup(_graph(), qfn, cap=cap, intensity=_an._intensity_on())


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


def _daily_turn_quota(ident: dict) -> None:
    """The per-user DAILY turn cap (Stage 5, env `GRAPHRAG_TURN_QUOTA`) — the shipped meter, on its
    shipped primitive (`incr_turn_quota` -> a plain conditional UpdateItem). Each turn is real Bedrock
    spend, so an open-signup public deploy caps per-account velocity. Over the cap -> 429. Quota unset ->
    no cap; any counter/infra error -> ALLOW (fail-open; WAF rate-limit + the Bedrock daily budget are the
    hard backstops, a counter glitch must not lock out a paying user).

    D-MW-24 NOTE (the reason this is its own function now): the credit gate must run BEFORE this
    increment, so an out-of-credits 429 never burns one of the user's 50 daily turns. Extracted, not
    rewritten — this meter stays BYTE-UNTOUCHED (wrapping it in the ledger's transactional path would
    change its failure type from ConditionalCheckFailedException to TransactionCanceledException and the
    QuotaExceeded mapping below would silently stop firing, i.e. the cap would fail OPEN)."""
    cap = os.environ.get("GRAPHRAG_TURN_QUOTA")
    if not cap:
        return
    from leviathan.graphrag import store as st
    try:
        _store().incr_turn_quota(ident["sub"], time.strftime("%Y-%m-%d", time.gmtime()), int(cap))
    except st.QuotaExceeded:
        raise HTTPException(status_code=429, detail=f"daily turn limit ({cap}) reached; try again tomorrow")
    except Exception:  # noqa: BLE001 — fail open on any non-quota error
        pass


# NOTE (P5 review F7): the mode-less `_require_identity_quota` was DELETED here. Zero routes referenced
# it once both turn routes moved to the mode-carrying wrappers, and a dead gate that reads as live is how
# a future route gets wired to the UNMETERED variant by accident — on the money path. The mode-less entry
# point still exists and is named: `_metered_identity_quota(authorization, None)` (a None mode prices
# nothing, so it behaves exactly as the deleted function did). Prose elsewhere that cites "the
# `_require_identity_quota` law" means the fail-open law now stated on `_metered_identity_quota`.


# ══ D-MW-24: THE CREDIT SEAM ════════════════════════════════════════════════════════════════════════
# The depth slider prices DEPTH, not turns. Two notches ship: Scan (`quick`, UNMETERED — the default
# experience is never metered; usage anxiety suppresses engagement) and Analysis (`deep`, 1 credit/turn
# against a monthly grant). `max`/`max_c0` stay DARK and are deliberately ABSENT from the price table:
# an un-shipped tier has no price, and a tier with no price is unmetered — which is safe here only
# because serving's GRAPHRAG_MODES allowlist is what decides whether it can be honored at all.
# THE ONE EXCEPTION, stated (D-MW-30 F6): the escalated presets ARE priced, at deep's price, even though
# they are dark and no serving turn is ever honored as one. The asymmetry is deliberate and is spelled
# out at the table below — for max, unpriced means "cannot be sold"; for esc, unpriced would mean
# "delivered the widest walk we have, then refunded it".
#
# THE ONE SEAM is the quota dependency (below): FastAPI resolves it BEFORE the handler body, which is
# the only place where (a) the credits check can precede the daily-turn increment and (b) a refusal can
# still be a 429 — once a StreamingResponse's generator starts, the status line is already sent.
_CREDITS_FLAG = "GRAPHRAG_CREDITS"              # absent/off => ZERO metering code executes (dark-first)
_CREDITS_LIMIT_ENV = "GRAPHRAG_CREDITS_LIMIT"   # the monthly grant; ratified initial 100
_CREDITS_DEFAULT_LIMIT = 100
# D-MW-30 F6 (money, defence in depth): the escalated presets are priced AT DEEP'S PRICE. A shape
# escalation is honored `deep` and therefore lands here as `deep` today -- these two entries change
# nothing about what any turn is charged. They exist because the failure they prevent is silent and
# expensive: if `honored` ever came to carry the effective preset (a future stamp change, a dossier
# sub-turn, an eval arm requesting the preset BY NAME), an unpriced `esc` would read as UNMETERED and
# the reconcile would FULL-REFUND a delivered max-width + Opus turn. A tier with no price is free.
# D-HP H1 FIX Z5(d): the four `_hp` twins are priced AT THEIR BASE'S PRICE, in the same commit as the
# escalation seam that makes them reachable. The table is keyed on the HONORED WIRE NAME, so a flipped
# `deep_hp` tier -- D-HP-26 step 0's whole point -- would bill ZERO credits: the treatment arm would be
# free while its control paid, which is a pricing defect wearing an A/B's clothes, and the refund path
# (`_credit_price` again at the reconcile) would recompute the same 0 and quietly agree. `quick_hp` is
# absent for the same reason `quick` is: Scan is unmetered on both arms, and an entry would mint a price
# for a tier that has none.
# WHY LITERALS AND NOT A DERIVATION: this table is the FROZEN WIRE CONTRACT (see the note above), and it
# must stay readable as one line of prices. `rm.base_mode(honored)` is the alternative and was refused
# here for the reason the D-MW-30 comment gives: a price table that computes is a price table that can be
# argued with at 3am. The names are pinned against the leaf's own join in test_dmw_credit_seam.
_CREDIT_PRICES: dict = {"deep": 1, "esc": 1, "esc_r": 1,   # wire names, frozen identifiers
                        "deep_hp": 1, "esc_hp": 1, "esc_r_hp": 1}
                                                # (rm.DEEP / rm.ESC / rm.ESC_R + the D-HP twins);
                                                # quick and quick_hp == free
_CREDIT_KEY = "_credit"                         # private slot on the identity dict: the turn's charge
_CREDITS_ERROR_CODE = "credits_exceeded"        # the 429's MACHINE slug; the sentence rides `detail` (F9)
# The GROUNDED-WALK STAMP (F2). `planner.grounded_subgraph` writes `trace.walk_shape` on EVERY walk, both
# arms, and `answer._answer_l2` spreads sg.trace into the result — so its PRESENCE is the artifact that a
# metered walk actually ran, and its ABSENCE is the one signal that says no depth was delivered. The
# deterministic floor (`trace.floor`, historically 17.6% of turns), the trivial-router reply, the guardrail
# refusal and the two knob-exempt lanes (live / numbers_only) all lack it. `intent_decision.mode.honored`
# CANNOT play this role: orchestrator.py stamps it unconditionally on the way out, including on the floor
# result, so a floored turn is indistinguishable from a delivered deep turn by that field alone.
# THE DIRECTION OF THE FAILURE IS DELIBERATE: any lane that does not stamp a walk reads as delivered-nothing
# and is REFUNDED. If the walk stamp ever moved or the onehop planner rollback (GRAPHRAG_PLANNER=onehop, no
# grounded_subgraph) were taken, every metered turn would net to zero — the estate stops billing rather than
# billing for depth it cannot prove it delivered.
_WALK_STAMP = "walk_shape"


class CreditsExceeded(Exception):
    """Raised by the quota dependency when the monthly grant cannot cover the requested tier.

    WHY AN EXCEPTION AND NOT A RESPONSE (measured, round-3): a dependency can only short-circuit by
    RAISING; `HTTPException` buries everything under `detail` so a top-level `reset_at` is impossible
    that way; and a `JSONResponse` RETURNED from a dependency does not short-circuit at all — the
    handler runs anyway. A bare exception + an app-level handler is the only construct that is both
    dependency-raisable (i.e. fires before the stream opens) and top-level-shaped."""

    def __init__(self, *, limit: int, remaining: int, reset_at: str, detail: Optional[str] = None):
        self.limit, self.remaining, self.reset_at = int(limit), int(remaining), str(reset_at)
        # A human `detail` string rides ALONGSIDE the structured fields on purpose: the FE transport
        # error extractor reads `detail` and renders anything else as a bare "HTTP 429" (the D-TW-6
        # class). The structured fields are what DepthControl reads for the reset day.
        self.detail = detail or (f"monthly credit limit ({self.limit}) reached; "
                                 f"credits reset {self.reset_at[:10]}")
        super().__init__(self.detail)


@app.exception_handler(CreditsExceeded)
def _credits_exceeded_handler(request, exc: CreditsExceeded) -> JSONResponse:
    """THE LOCKED 429 BODY. D-MW-25's FE parsing and the prod smoke assert exactly these five keys.

    `error` is a MACHINE SLUG and `detail` is the human sentence (P5 review F9). The FE types `error` as a
    code (`CreditsRefusal.code`) and the shipped dossier 429 already puts a code there; a prose phrase in a
    field a client branches on is a contract that reads one way and behaves another. The sentence a user
    sees never moved — it has always come from `detail`."""
    return JSONResponse(status_code=429,
                        content={"error": _CREDITS_ERROR_CODE, "limit": exc.limit,
                                 "remaining": exc.remaining, "reset_at": exc.reset_at,
                                 "detail": exc.detail})


def _credits_on() -> bool:
    """THE KILL SWITCH. Absent/''/'off' -> False -> not one line of metering code runs and not one store
    call is made on the turn path (mock-asserted): the request path is byte-identical to its pre-D-MW
    self. The flip to 'on' is a later, separate decision (the env flag and the code that reads it are ONE
    change — see the P1 flip law)."""
    return os.environ.get(_CREDITS_FLAG, "").strip().lower() in ("on", "1", "true")


def _credits_limit() -> int:
    try:
        return max(0, int(os.environ.get(_CREDITS_LIMIT_ENV, _CREDITS_DEFAULT_LIMIT)))
    except (TypeError, ValueError):
        return _CREDITS_DEFAULT_LIMIT


def _credits_period(now: Optional[float] = None) -> str:
    """The store period suffix `credits#YYYY-MM` (row sk=`quota#credits#YYYY-MM`) — DELEGATED to
    store.credits_period, never re-derived here. One authority for the key and one for the reset: a
    reset date that disagreed with the counter's bucket is how a user is told 'resets September 1' and
    is still refused on September 1."""
    from leviathan.graphrag import store as st
    return st.credits_period(now)


def _credits_reset_at(now: Optional[float] = None) -> str:
    """First instant of the next UTC month — the 429 body's `reset_at`. Delegated, same reason."""
    from leviathan.graphrag import store as st
    return st.credits_reset_at(now)


def _credit_price(honored: Optional[str]) -> int:
    """What the tier that ACTUALLY RAN costs. Unknown/None/absent (every early-return lane) -> 0."""
    return int(_CREDIT_PRICES.get((honored or "").strip().lower(), 0))


def _grounded_walk_ran(result: Optional[dict]) -> bool:
    """Did this turn actually run the grounded walk the metered tier prices? See `_WALK_STAMP`."""
    if not isinstance(result, dict):
        return False
    # PRESENCE, not truthiness: the stamp's existence is the delivery signal (planner stamps it at
    # its single return); an empty-dict stamp must still read as a delivered walk (verify catch).
    return _WALK_STAMP in ((result.get("trace") or {}) if isinstance(result.get("trace"), dict) else {})


def _honored_mode(result: Optional[dict]) -> Optional[str]:
    """The tier the user actually RECEIVED — the reconcile's one authority for what to charge for.

    TWO conditions, not one (F2). The honored stamp says what the resolver decided; the walk stamp says
    whether that depth was ever delivered. The guardrail refusal and the trivial-router reply return ABOVE
    `rm.resolve` and carry neither, which was always the reconcile signal — but the DETERMINISTIC FLOOR
    carries the honored stamp and no walk: orchestrator.py stamps `intent_decision` on the way out, after
    the floor has already replaced the branch with a banner plus raw evidence lines. Reading the honored
    stamp alone charged a full credit for the single largest population that delivers no depth at all."""
    if not _grounded_walk_ran(result):
        return None
    return (((result.get("intent_decision") or {}).get("mode") or {}).get("honored")) or None


def _credits_remaining(sub: str, period: str, limit: int, *, on_error: int) -> int:
    """Grant minus spend. `on_error` is the caller's choice of degradation and the two callers want
    OPPOSITE things: the 429 body passes 0 (we are already refusing — a made-up positive balance beside
    a refusal is worse than none), the badge passes the full grant (a badge that cannot read the counter
    must not tell a paying user they have nothing left)."""
    try:
        return max(0, limit - int(_store().read_quota(sub, period) or 0))
    except Exception:  # noqa: BLE001
        return int(on_error)


_TURN_ID_RE = re.compile(r"[^A-Za-z0-9_-]")


def _op_id(sub: str, turn_id: Optional[str]) -> str:
    """THE CHARGE'S IDENTITY (F4). Idempotency is only reachable if two invocations of the gate can agree
    on one key, so the op_id is derived from the SUBJECT plus the client's per-question turn id: the FE
    mints one uuid at submit and REUSES it across an SSE reconnect or a retry of the same question, so the
    ledgerop marker collapses the replay to a no-op and the same question cannot be billed twice.

    RECORDED: a caller that sends no turn_id (bare curl, an API integration) gets a random key and
    therefore NO cross-request idempotency — the single-in-flight lease is its only protection. The sub is
    in the key so one user's turn id can never collide with another's; the id is sanitised because it
    lands in a DynamoDB sort key."""
    tid = _TURN_ID_RE.sub("", str(turn_id or ""))[:64]
    if not tid:
        return f"turn-{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}-{os.urandom(8).hex()}"
    return f"turn-{sub}-{tid}"


def _exempt_sub(sub: str) -> bool:
    """GRAPHRAG_METER_EXEMPT_SUBS: comma-separated Cognito subs whose turns and dossiers are NEVER
    metered (owner/ops accounts). Exempt users see no credits badge (/v1/credits 404s, the dark idiom)
    and the dossier monthly counter is never consumed. Config-of-record rides extra_environment."""
    raw = os.environ.get("GRAPHRAG_METER_EXEMPT_SUBS", "")
    return bool(sub) and sub in {s.strip() for s in raw.split(",") if s.strip()}


def _credit_gate(ident: dict, mode: Optional[str], turn_id: Optional[str] = None) -> Optional[dict]:
    """STEP 1 — GATE. Runs INSIDE the quota dependency, BEFORE the daily-turn increment.

    Order, and why it is this order:
      1. kill switch  — off => return immediately, zero store calls, zero imports.
      2. resolve      — the REQUESTED-AND-ALLOWLISTED tier via `rm.resolve` (a PURE function; calling it
                        here with the same inputs the orchestrator will use is not a second resolution
                        authority) intersected with the same GRAPHRAG_MODES allowlist. A tier the
                        allowlist does not honor prices as what will actually run: nothing.
      3. price        — 0 (quick/standard/dark) => unmetered, still zero store calls.
      4. lease        — single-in-flight for METERED tiers only. `store.acquire_lease` is a LEASE, not a
                        TTL (DynamoDB TTL deletion is best-effort within ~48h, so a crashed turn on a TTL
                        would lock the user out of metered depth for up to two days); its 15-minute
                        horizon is the store's `LEASE_SECONDS` default and is not re-declared here.
      5. debit        — the atomic conditional debit. Over the grant -> CreditsExceeded -> 429 BEFORE the
                        daily counter moves and before any stream opens.

    Returns the CHARGE RECORD the turn reconciles against, or None when nothing was charged. FAIL-OPEN on
    every non-quota store error (the `_metered_identity_quota` fail-open law, and the store's docstring puts
    that decision HERE — a swallowed AccessDenied at the store would turn every metered turn unmetered
    without a signal): an infra glitch runs the turn unmetered rather than refusing a paying user."""
    if not _credits_on():
        return None                                   # THE KILL SWITCH — nothing below this line runs
    if _exempt_sub(str(ident.get("sub") or "")):
        return None                                   # owner/ops exemption: unmetered, zero store calls
    from leviathan.graphrag import orchestrator as orch
    from leviathan.graphrag import reasoning_modes as rm
    from leviathan.graphrag import store as st
    honored = rm.resolve(mode, orch._modes_enabled())["honored"]
    amount = _credit_price(honored)
    if amount <= 0:
        return None                                   # Scan (quick) + standard are UNMETERED by design
    sub = str(ident.get("sub") or "")
    period, limit = _credits_period(), _credits_limit()
    op_id = _op_id(sub, turn_id)
    lease, busy = None, False
    try:
        lease = _store().acquire_lease(sub) or None   # the OWNER TOKEN (F5), or None when held
        busy = lease is None                          # a live lease held by another turn => refuse
    except Exception:  # noqa: BLE001 — a lease glitch admits the turn; it never blocks a paying user
        lease, busy = None, False
    if busy:
        raise HTTPException(status_code=429,
                            detail="a metered turn is already running on this account; wait for it to "
                                   "finish, or run this question as a Scan")
    try:
        applied = _store().debit(sub, period, amount, limit, op_id=f"{op_id}#debit", ref=honored)
    except st.QuotaExceeded:
        _release_lease({"sub": sub, "lease": lease})
        raise CreditsExceeded(limit=limit, remaining=_credits_remaining(sub, period, limit, on_error=0),
                              reset_at=_credits_reset_at())
    except Exception:  # noqa: BLE001 — nothing was charged, so there is nothing to reconcile
        _release_lease({"sub": sub, "lease": lease})
        return None
    # `applied is False` = the ledgerop marker was already there, i.e. THIS request is a replay of a turn
    # that was charged once. It still runs (the user asked for an answer), it still holds the lease, and it
    # still settles — but its refund leg is a no-op, because refunding here would give back the ORIGINAL
    # request's credit and hand a delivered turn away for free.
    return {"sub": sub, "period": period, "amount": amount, "op_id": op_id, "applied": bool(applied),
            "honored": honored, "lease": lease, "settled": False}


def _settle_credit(charge: Optional[dict], result: Optional[dict]) -> None:
    """STEP 2 — RECONCILE, and the CHARGE-COMMIT point.

    Called at exactly one moment per turn: where the result event is ENQUEUED (the stream) or the result
    is returned (the POST twin), and on every path that delivers no metered depth — the trivial-router
    reply, the guardrail refusal, an honored-tier DOWNGRADE (requested deep, honored standard, because
    the allowlist did not honor it), and any exception before the result. Pass `result=None` for those
    last ones: nothing was delivered, so the whole charge goes back.

    The refund is the DIFFERENCE between what the gate charged and what the turn actually delivered, so
    a requested-but-downgraded tier leaves the ledger NET UNCHANGED. Idempotent twice over: the store op
    is keyed on a fixed op_id, and `settled` makes a second call a local no-op (a turn that raises AFTER
    its result event must not be refunded — it was delivered).

    DELIVERY SEMANTICS, PLAINLY: a GET SSE route has no delivery signal, so a client disconnect AFTER
    compute is CHARGED (the recorded trade; the product copy says so) and a disconnect before the result
    is not auto-refunded — no observable signal distinguishes it from a completed read."""
    if not charge or charge.get("settled"):
        return
    charge["settled"] = True                          # set FIRST: a raising refund must not be retried
    if not charge.get("applied", True):
        return                                        # a replay charged nothing here (F4): the ORIGINAL
                                                      # request owns this op_id's reconcile
    back = int(charge.get("amount") or 0) - _credit_price(_honored_mode(result))
    if back <= 0:
        return
    try:
        _store().credit(charge["sub"], charge["period"], back, op_id=f"{charge['op_id']}#refund",
                        ref=f"undelivered:{_honored_mode(result) or 'none'}")
    except Exception:  # noqa: BLE001 — a refund that raised would turn one failure into two
        pass


def _release_lease(charge: Optional[dict]) -> None:
    """Drop the single-in-flight lease. Called in a FINALLY on every terminal path (the item's TTL is
    garbage collection only, and its 15-minute expiry only the crash backstop). Idempotent.

    OWNERSHIP-FENCED (F5): `charge["lease"]` is the TOKEN this turn was admitted with, and the release is
    conditional on it at the store. A worker whose own lease expired mid-turn — so a second turn was
    admitted and holds a fresh token — releases NOTHING instead of deleting the live lease."""
    if not charge or not charge.get("lease"):
        return
    token = charge["lease"]
    charge["lease"] = None
    try:
        _store().release_lease(charge["sub"], token)
    except Exception:  # noqa: BLE001 — the lease expires on its own; never fail a turn on its release
        pass


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


# CYCLE-7-AMEND (2026-08-08): respond() keys that are IN-PROCESS INSTRUMENTS, never wire fields.
_INTERNAL_RESULT_KEYS = ("number_calls_full",)


def _public_result(result: dict) -> dict:
    """Strip respond()'s in-process-only keys before anything leaves this service.

    CYCLE-7 INSTRUMENT-1 put `number_calls_full` -- the FULL cascade-seam call list, i.e. every served row
    of every injected leg -- at respond()'s TOP LEVEL so `eval._served_rows` could audit a hybrid footer.
    The eval harness calls `orchestrator.respond` DIRECTLY and still receives it. The SERVICE must not, and
    this is the boundary: unstripped, /v1/respond returned it raw, the SSE `result` event serialized it,
    and the frontend posts the whole payload back to /v1/share (a PUBLIC read) and /v1/artifacts (a durable
    freeze) -- so an unbounded internal row projection would ride onto a share link.

    THE OTHER TWO SEAMS, STATED. Thread history was never exposed: `store._TURN_ALLOWED` is an ALLOWLIST and
    has never carried the key. `store.make_share` has NO strip list of its own -- it freezes exactly the
    payload it is handed -- which is precisely why the strip belongs HERE, before the client is ever given
    the field it would post back.

    Mutates and returns the SAME dict: respond() mints a fresh result per turn and the caller owns it."""
    if isinstance(result, dict):
        for k in _INTERNAL_RESULT_KEYS:
            result.pop(k, None)
    return result


# ── existing serving surface ────────────────────────────────────────────────────────────────────────
class Ask(BaseModel):
    question: str
    session_id: Optional[str] = None
    asof: Optional[str] = None                       # explicit as-of always beats session carry (PIT rule)
    context: list[M.ContextAttachment] = []          # P2 typed graph gestures; resolver caps 4, drops invalid
    # D-AM-9: the reasoning-scale request field. FREE-FORM str on purpose -- NOT a pydantic Enum: an
    # unknown value must resolve to `standard` with a mode_invalid stamp, never 422 a desk turn (a
    # typed enum would reject at the edge, which is exactly the failure mode the fail-open pin
    # forbids). The orchestrator does the validation, the allowlist and the stamping.
    mode: Optional[str] = None
    # D-MW-24 / F4: the client's per-question TURN ID -- one uuid minted at submit and REUSED across an
    # SSE reconnect or a retry of the same question. It is the only thing that can make the credit charge
    # idempotent across requests (`_op_id`); absent, the charge falls back to a random key and a genuine
    # retry is billed again. Free-form and optional for the same reason `mode` is: an unknown value must
    # never 422 a desk turn.
    turn_id: Optional[str] = None


def _metered_identity_quota(authorization: Optional[str], mode: Optional[str],
                            turn_id: Optional[str] = None) -> dict:
    """THE ONE GATE for a turn: identity -> credits (on the requested-and-allowlisted tier) -> daily cap.

    The order is the whole point. FastAPI resolves this dependency before the handler body, so a
    route-level credits check would already have burned a daily turn; here the credits refusal fires
    FIRST and the daily counter never moves. The reverse hazard is covered too: a daily-cap 429 after a
    successful debit credits the debit back (the turn never ran).

    The charge record rides on the identity dict under a private key — the handler pops it, so nothing
    downstream (`_save_turn`, `_turn_profile_facts`) ever sees it.

    THE FAIL-OPEN LAW lives here (it used to be named after `_require_identity_quota`, deleted per F7): a
    counter or ledger glitch must never lock a paying user out — see `_credit_gate`."""
    ident = _require_identity(authorization)
    charge = _credit_gate(ident, mode, turn_id)        # raises CreditsExceeded / 429-busy, or returns None
    try:
        _daily_turn_quota(ident)
    except BaseException:
        _settle_credit(charge, None)                   # daily cap hit: no depth delivered, credit it back
        _release_lease(charge)
        raise
    if charge:
        ident[_CREDIT_KEY] = charge
    return ident


def _require_identity_quota_ask(body: Ask, authorization: Optional[str] = Header(None)) -> dict:
    """The POST /v1/respond gate. A dependency MAY declare a body param — and declaring it under the
    SAME name as the handler's (`body`) is load-bearing: FastAPI counts body params by NAME, so one
    shared name keeps the request body top-level (two distinct names would embed it and change the
    wire contract). Pinned by test.

    THE VALIDATION FENCE (F1), and the reason this route was already safe: `body: Ask` is the endpoint's
    OWN required input, so a request that cannot satisfy it fails in the DEPENDENCY's own params and
    FastAPI never calls this function — no lease is taken and no ledger row is written for a request that
    was never going to run. The stream twin declares `question` for exactly this reason."""
    return _metered_identity_quota(authorization, body.mode, body.turn_id)


def _require_identity_quota_stream(question: str, mode: Optional[str] = None,
                                   turn_id: Optional[str] = None,
                                   authorization: Optional[str] = Header(None)) -> dict:
    """The GET /v1/respond/stream gate — the same seam reading the route's `mode` QUERY param.

    `question: str` is declared here DELIBERATELY and is not decoration (F1). FastAPI solves
    sub-dependencies BEFORE it validates the path operation's own params, so a gate whose parameters are
    all optional can never be skipped: `GET /v1/respond/stream?mode=deep` with no `question` used to
    debit a credit and take the 15-minute lease, then 422 — and the 422 never enters the generator where
    every settle and release lives, so the credit was destroyed and the account was locked out of metered
    depth for 15 minutes. Declaring the endpoint's own required param HERE makes the gate UNREACHABLE for
    a request that cannot be served. Keep it required; a default value re-opens the window."""
    return _metered_identity_quota(authorization, mode, turn_id)


def _decode_context(raw: Optional[str]) -> list:
    """SSE rides a JSON-encoded `context` query param (the stream endpoint is GET-only). A malformed or
    oversized param degrades to NO attachments — fail-open, matching the stream's degrade-never-500 posture
    (a stale share-link should still answer); the POST path validates loudly via pydantic instead."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data[:4] if isinstance(data, list) else []
    except Exception:  # noqa: BLE001 — a bad context param never breaks the turn
        return []


@app.get("/healthz")
def healthz() -> dict:
    from leviathan.graphrag import providers as pv
    return {"status": "ok", "contracts": len(_graph().contracts), "provider": pv.provider(),
            "evidence_backend": os.environ.get("EVIDENCE_BACKEND", "local"),
            "graph_version": getattr(_graph(), "version", None)}


def _turn_profile_facts(ident: dict) -> Optional[dict]:
    """D-RC-14: the signed-in user's profile facts for the ANSWER path -- read ONLY when
    GRAPHRAG_PROFILE_CONTEXT is on (flag off = zero DDB round-trips on the turn path), fail-OPEN on
    any store error (the suggest_route idiom: a store glitch must never fail a billed turn). The
    orchestrator re-checks the same flag and builds the labeled non-citable block; facts are
    PREFERENCES, never evidence (PIT firewall untouched)."""
    from leviathan.graphrag import orchestrator as orch
    if not orch._profile_context_on():
        return None
    try:
        facts = (_store().get_profile(ident.get("sub") or "") or {}).get("facts")
    except Exception:  # noqa: BLE001
        return None
    return facts if isinstance(facts, dict) and facts else None


@app.post("/v1/respond")
def respond_route(body: Ask, ident: dict = Depends(_require_identity_quota_ask)) -> dict:
    # Auth + per-user daily quota + (D-MW-24) the credit gate: a turn is Bedrock spend, so only signed-in
    # users within their daily cap and their monthly grant may run it. When GRAPHRAG_AUTH is off (dev/eval)
    # the identity is local; when GRAPHRAG_CREDITS is off the credit half is not executed at all.
    from leviathan.graphrag import orchestrator as orch
    charge = ident.pop(_CREDIT_KEY, None)                       # the turn's charge record (None = unmetered)
    try:
        result = _public_result(                                # CYCLE-7-AMEND: in-process keys stop here
            orch.respond(body.question, graph=_graph(), asof=body.asof, session_id=body.session_id,
                         context=body.context, profile_facts=_turn_profile_facts(ident),
                         mode=body.mode))                       # D-AM-9 (None = absent = standard)
    except BaseException:
        _settle_credit(charge, None)                            # no result: the whole charge goes back
        raise
    finally:
        _release_lease(charge)                                  # the lease drops on EVERY terminal path
    _settle_credit(charge, result)                              # COMMIT (or refund a downgrade/early return)
    _save_turn(ident, body.session_id, result, question=body.question)   # durable history (PIT-safe, fail-open)
    return result


@app.get("/v1/respond/stream")
def respond_stream(question: str, session_id: Optional[str] = None, asof: Optional[str] = None,
                   context: Optional[str] = None, mode: Optional[str] = None,
                   turn_id: Optional[str] = None,
                   ident: dict = Depends(_require_identity_quota_stream)):
    """SSE wrapper: respond() runs in a worker thread; the stream relays each `on_stage` tick as its own
    `stage` event, then the single terminal `result` (or `error`).

    `mode` (D-AM-9) is the reasoning-scale query param, the GET twin of Ask.mode -- untyped for the
    same reason (unknown -> standard + stamp, never a 422 on a streamed desk turn)."""
    from leviathan.graphrag import orchestrator as orch

    def gen():
        out: queue.Queue = queue.Queue()

        def on_stage(stage: str, info: dict) -> None:
            # granular pipeline ticks (P1.1) from the worker. THREAD-SAFETY (F7, verified — no change needed):
            # this closure is called from MORE than the one `work` thread. run_hybrid's numbers pool emits
            # `numbers`/`number` while the walk emits `walk`/`chain` on the caller, and planner.ground's fill
            # pool emits `retrieving`/`evidence` from N fill workers concurrently. queue.Queue is already
            # synchronized (put() takes the internal mutex; documented thread-safe), it is unbounded so put()
            # never blocks a producer, and the dict is built fresh per call — so concurrent emitters interleave
            # safely and nothing is dropped. Ordering across lanes is therefore ARRIVAL order, not lane order,
            # which is the whole point of F7: the feed shows what landed, when it landed.
            out.put(("stage", {"stage": stage, **(info or {})}))

        _pf = _turn_profile_facts(ident)                  # D-RC-14: read on the request thread, before the worker
        _charge = ident.pop(_CREDIT_KEY, None)            # D-MW-24: read in the streaming task (see below)
        # ACCEPTED-WITH-RECORD (F11): a generator that is never iterated leaves this charge unsettled and the
        # lease held. BOUNDED, not open-ended: F1 removed the reachable trigger (an un-servable request now
        # 422s before the gate runs), the lease self-expires in 15 minutes, and every path that DOES enter
        # here settles through the refund. Closing it fully means eagerly starting the worker -- a larger
        # behavior change than the residual hazard.

        def work() -> None:
            try:
                result = _public_result(                  # CYCLE-7-AMEND: strip BEFORE the terminal event
                    orch.respond(question, graph=_graph(), asof=asof, session_id=session_id,
                                 on_stage=on_stage, context=_decode_context(context),
                                 profile_facts=_pf, mode=mode))         # D-AM-9
                out.put(("result", result))               # deliver the note FIRST — the user isn't waiting on persistence
                _settle_credit(_charge, result)           # D-MW-24: the charge COMMITS at the result ENQUEUE
                _save_turn(ident, session_id, result, question=question)  # then durable history (fail-open, off the perceived path)
            except Exception as e:  # noqa: BLE001 — the floor makes this near-impossible; belt + braces
                _settle_credit(_charge, None)             # pre-result failure: the whole charge goes back
                out.put(("error", {"error": f"{type(e).__name__}: {str(e)[:200]}"}))
            finally:
                _release_lease(_charge)               # the lease drops HERE, not in the generator: the
                                                     # worker owns the compute, and a disconnected client
                                                     # abandons the generator while this thread runs on.

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


@app.get("/v1/credits")
def credits_route(ident: dict = Depends(_require_identity)) -> dict:
    """{remaining, limit, reset_at} — what the credits badge renders, and what the FE re-reads after a
    submit or a 429 (the /v1/dossier/quota pattern, generalized). FREE: identity-gated, no model call,
    and explicitly NOT the turn quota — reading a counter is not a use of it.

    DARK IS A 404, not a zero (the dossier-gate idiom, and the shape api/credits.ts already codes
    against): with `GRAPHRAG_CREDITS` off nothing is metered, so there is no meter to report and the FE
    renders no badge at all. A 500 would say something different — that the feature exists and broke.

    FAIL-OPEN on any store error: a badge that cannot read the counter shows the full grant rather than
    telling a paying user they have nothing left."""
    if not _credits_on() or _exempt_sub(str(ident.get("sub") or "")):
        raise HTTPException(status_code=404, detail="not found")   # dark OR exempt: no meter to report
    limit = _credits_limit()
    return {"remaining": _credits_remaining(str(ident.get("sub") or ""), _credits_period(), limit,
                                            on_error=limit),
            "limit": limit, "reset_at": _credits_reset_at()}


# ── 1.2 cascade DAG topology ──────────────────────────────────────────────────────────────────────
@app.get("/v1/graph/{contract}", response_model=M.GraphTopology)
def graph_route(contract: str, asof: Optional[str] = Query(None),
                ident: dict = Depends(_require_identity)) -> dict:
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
def convergence_route(asof: Optional[str] = Query(None),
                      ident: dict = Depends(_require_identity)) -> dict:
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
def regimes_route(contract: str, asof: Optional[str] = Query(None),
                  ident: dict = Depends(_require_identity)) -> dict:
    from leviathan.graphrag import firing as F
    asof = asof or _today()
    try:
        row = F.fire_contract(_graph(), contract, asof, _silver_lookup())
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown contract {contract!r}")
    return M.ConvergenceRow(**row).model_dump()


# ── 1.5 vintage-aware series ─────────────────────────────────────────────────────────────────────────
_SERIES_AGGS = ("series", "latest")
"""D-AM-21: the ONLY two aggs /v1/series compiles, and the pair is deliberately short.

``series`` is the route's pre-wave default and stays it, so an unparameterized call is byte-identical.
``latest`` exists for exactly ONE shape -- the CURVE read (`contract_month` naming several expiries, one
row per expiry at one as-of, which is what `agg` DEFAULTS to in the numbers tool schema). The four scalar
aggs (sum/mean/max/min) are NOT reachable here on purpose: each collapses to a single ``{value}`` row with
no date, no period and no expiry, i.e. a point the chart cannot place and the [N#] label cannot attribute --
a new capability behind a chart parameter, which is not what this parameter is for."""


@app.get("/v1/series/{table}/{metric}", response_model=M.Series)
def series_route(table: str, metric: str, commodity: Optional[str] = Query(None),
                 country: Optional[str] = Query(None), asof: Optional[str] = Query(None),
                 contract_month: Optional[str] = Query(None), agg: str = Query("series"),
                 ident: dict = Depends(_require_identity)) -> dict:
    from leviathan.graphrag import answer as an
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
    if agg not in _SERIES_AGGS:
        raise HTTPException(status_code=400, detail=f"unsupported agg {agg!r} for /v1/series")
    # D-AM-21 CURVE READ. `contract_month` is the SAME single comma-separated field the numbers tool carries
    # (one value = a named expiry through time, a list = the term structure at one as-of) and it is threaded
    # VERBATIM -- the route parses nothing, so `_contract_months` stays the one splitter and the SQL emit and
    # the PIT oracle cannot disagree with the URL. The delivery-month guard below is build_sql's own
    # (query.py: "a dimension the table cannot express is a decline, never a quiet substitution"), lifted to
    # a DETERMINISTIC 400 rather than left to surface as the generic 502 this route wraps every query failure
    # in -- a caller asking a PSD card for a December expiry has made a request error, not met an outage.
    if contract_month and not ts.contract_month_col:
        raise HTTPException(status_code=400,
                            detail=f"table {table!r} carries no delivery-month column, so a contract_month "
                                   f"read is not expressible against it")
    spec = Q.NumberQuery(table=table, metric=metric, asof=asof, commodity=commodity, country=country,
                         contract_month=contract_month, agg=agg)
    # FUTURES_READPATH S1 (D-FR-10). This route sits ABOVE answer.py, so there is nothing to thread the
    # canary through -- it imports the ONE env seam and hands the bool straight to the compiler. That is the
    # seam doctrine rather than an exception to it: the flag is still read in exactly one function estate-
    # wide, and this route never spells the variable's name. Threaded here because /v1/series is the ONE
    # user-facing surface that compiles an UNBOUNDED agg='series' read with no eval pin behind it -- the
    # exact shape whose LIMIT 5000 keeps the OLDEST rows and stops an unbounded corn settle series in 2011.
    # Flag off -> the byte-identical ASC compile this route has always issued.
    #
    # Read ABOVE the try, deliberately: inside it, a seam failure would be reported to the UI as
    # "series query failed", which is the one thing it would not have been.
    # D-AM-18: the token, not a bare bool -- this route is the ONE user-facing surface that compiles an
    # unbounded agg='series' read on ANY card, so it is the surface the estate-wide scope exists for.
    _nf = an._newest_first_scope(an._futures_newest_first_on(), an._series_newest_first_on())
    try:
        rows = Q.run(spec, query_fn=_STATE.get("query_fn"), futures_newest_first=_nf)
    except Exception as e:  # noqa: BLE001 — a query failure is a 502, never a 500 stacktrace to the UI
        raise HTTPException(status_code=502, detail=f"series query failed: {type(e).__name__}")
    unit = ts.metrics[metric].unit if (ts.metrics and metric in ts.metrics) else ""
    return M.Series(table=table, metric=metric, commodity=commodity, asof=asof, unit=unit, points=rows).model_dump()


# ── 1.6 live events rail (PIT kill-switch visible) ──────────────────────────────────────────────────
@app.get("/v1/events", response_model=M.EventsFeed)
def events_route(contract: Optional[str] = Query(None), asof: Optional[str] = Query(None),
                 ident: dict = Depends(_require_identity)) -> dict:
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


# ── 6.5 click-to-page: resolve a doc citation to its source PDF + best page ─────────────────────────
@app.get("/v1/citation/pdf", response_model=M.CitationPdf)
def citation_pdf_route(source_key: str = Query(...), snippet: Optional[str] = Query(None),
                       char_start: Optional[int] = Query(None), offset_kind: Optional[str] = Query(None),
                       ident: dict = Depends(_require_identity)) -> dict:
    """Resolve a document citation's `locator` (source_key + optional snippet/char_start/offset_kind) to a
    presigned source-PDF url + the best 1-indexed page (6.5). Identity-gated like the other read routes.
    Kill-switch `GRAPHRAG_PDF_LINKS` (default ON, mirroring GRAPHRAG_SUGGEST) -> 404 when off, so the FE hides
    the affordance with no redeploy. Never 500: a resolver miss degrades to page=null with the url still set;
    a MISSING document.json is the only 404 the resolver itself triggers."""
    if os.environ.get("GRAPHRAG_PDF_LINKS", "on").lower() != "on":   # kill-switch, no redeploy (rollback path)
        raise HTTPException(status_code=404, detail="pdf links disabled")
    from leviathan.graphrag import pdfpage
    try:
        res = pdfpage.resolve_pdf_page(source_key, snippet=snippet, char_start=char_start, offset_kind=offset_kind)
    except pdfpage.PdfDocumentMissing:
        raise HTTPException(status_code=404, detail="source document not found")
    except Exception:  # noqa: BLE001 — the resolver never raises otherwise; belt+braces so a click never 500s
        res = {"url": "", "page": None, "kind": "other", "expires_in": 900}
    return M.CitationPdf(**res).model_dump()


# ── 6.2 query suggester — decoupled Haiku side-channel (never touches the answer path) ──────────────
def _suggest_prompt(body: M.SuggestRequest, facts: Optional[dict]) -> str:
    """The Haiku prompt: role + strict output contract + the turn packet + optional facts.
    ASCII, hard-truncated fields (the packet is client-supplied text)."""
    lines = [
        "You suggest the NEXT question a commodity researcher would ask in a research terminal that",
        "answers from causal driver graphs, official-source evidence (USDA/WASDE/GAIN etc.) and",
        "supply/demand balance sheets, with an interest in convexity (buffer exhaustion, regime tips).",
        "Return ONLY a JSON array of 3-4 short questions. Each: under 110 characters, plain English,",
        "ASCII, specific and answerable from fundamentals -- no internal identifiers, no code_like_names,",
        "no price targets. Mix: one going deeper on the last answer and one on an adjacent contract",
        "or driver.",
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
    f = facts or {}
    interests: list[str] = []                                          # 6.6: fold every list-shaped fact key
    for key in ("markets", "interests", "regions"):
        v = f.get(key)
        if isinstance(v, list):
            interests += [str(x).strip() for x in v if str(x).strip()]
        elif isinstance(v, str) and v.strip():
            interests.append(v.strip())
    if interests:
        lines.append("User interests: " + ", ".join(dict.fromkeys(interests))[:200])
    seat = f.get("seat")
    if isinstance(seat, str) and seat.strip():
        lines.append(f"User seat: {seat.strip()[:40]}")
    notes = f.get("notes")
    if isinstance(notes, list) and notes:
        lines.append("User notes: " + "; ".join(str(n).strip() for n in notes if str(n).strip())[:200])
    return "\n".join(lines)


# ── P1.2 suggester numeric guard: a chip asks about DIRECTION and CONFLUENCE, never a minted numeric level ──
# Known digit-tokens that are NAMES/labels, not invented magnitudes — whitelisted so the magnitude reject can't
# kill them. ORDER MATTERS: these spans are neutralized BEFORE the reject runs (else "ONI 0.5" dies on the
# bare-ratio rule). Year handling mirrors the orchestrator's 1900-2100 integer-year predicate.
_NUM_OK = re.compile(
    r"\b[BE]\d{1,3}\b"                                                 # biofuel mandate codes: B40, E15, B35
    r"|\bONI\s*[+\-]?\d+(?:\.\d+)?\b|\b[+\-]?\d+(?:\.\d+)?\s*ONI\b"     # the ONI band, either order: ONI 0.5 / 0.5 ONI
    r"|\bNo\.?\s*\d+\b"                                                # grade names: No. 2
    r"|\b(?:19|20)\d{2}\b"                                             # 4-digit years 1900-2099
    r"|\bQ[1-4]\b|\bH[12]\b"                                           # quarter / half labels
    r"|\b\d{1,2}\s*/\s*\d{1,2}\b"                                      # proximity fractions: 2/4
    r"|\b\d{1,3}-(?:year|yr|day|week|month|quarter|season|hour)s?\b",  # windows: 5-year, 90-day
    re.I)
# A minted numeric MAGNITUDE a chip must never assert (the "fake threshold" failure, per the 6.8 audit): a
# number bound to a unit/scale word, or a bare ratio decimal.
_NUM_BAD = re.compile(
    r"\d[\d.,]*\s*%"                                                   # a percentage: 15%, 40% (% is not a \w, so no \b)
    r"|\d[\d.,]*\s*(?:million|billion|mmt|thousand|bags|bushels?|tonnes?|tons?|percent|cents?|ratio)\b"
    r"|\b0\.\d+\b", re.I)


def _mints_number(s: str) -> bool:
    """True if a chip states a specific numeric level/threshold/quantity (drop it — chips ask about direction and
    confluence, not levels). Whitelisted digit-tokens (codes, years, ONI band, grades, fractions, windows) are
    neutralized FIRST so a legitimate label can't trip the magnitude reject. Pure regex on a str — never raises."""
    return bool(_NUM_BAD.search(_NUM_OK.sub(" ", s)))


def _parse_suggestions(raw: str) -> list[str]:
    """First JSON array in the completion -> <=4 clean chips. Deterministic guards (the one-vocab
    doctrine applies to chips): strings only, trimmed, <=140 chars, ZERO register leaks (an internal
    id can never render as a chip), no minted numeric level (_mints_number), deduped. Unparseable -> []."""
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
        if not s or len(s) > 140 or s in out or reg.register_leaks(s) or reg.lane_b_hits(s) or _mints_number(s):
            continue                                                  # Lane A rides register_leaks; Lane B is the +1
        out.append(s)
    return out[:4]


# ── 6.8 grounded suggester — data-scoped catalog + convexity house style (flag GRAPHRAG_SUGGEST_CATALOG) ─
# When ON (and the convergence matrix is warm), the suggester is handed a catalog derived from OUR data —
# tracked contracts, the regimes CLOSEST TO FIRING (from the warm matrix), answerable buffer/rate metrics,
# and the driver lanes — and prompted in the convexity house style with a hard "answerable-only" rule, so it
# can only propose questions we can actually answer (never energy inventories, metals, or non-covered geos).
# D-CW-1b (2026-08-07, the DARK CAPABILITY CENSUS): this catalog advertised 7 fundamentals and ZERO
# prices, so the whole price / input-cost / curve half of the numbers registry was invisible to the user
# even though the agent has served it since W2-W4. The additions below are census-GATED -- every one names
# a table the agent can actually reach today (silver_pink_sheet, silver_wasde.avg_farm_price,
# silver_futures_eod, silver_nass_crop_progress, ESR per-destination), never a dark or whitelist-absent
# one, because a suggested question we cannot answer is worse than no suggestion.
# WHAT IS DELIBERATELY ABSENT: POSITIONING. The wave plan asked for it here, and config_check's R10
# (check_cot_register, PRICE_OBSERVABILITY W0.2 as amended by D1) forbids it -- a positioning-table metric
# or its vocabulary in THIS string is a build failure, because positioning is a driver LANE, not a
# suggestible numbers source. That fence is ratified and this wave changes no ratified fence; the router
# already advertises COT positioning in dispatch.REGISTRY, which is the reachable half of the census's
# item 9. Recorded here so the omission reads as a decision rather than an oversight.
_SUGGEST_METRICS = ("ending stocks & stocks-to-use, weekly export pace (ESR) including which destination "
                    "bought, production/consumption, crush, crop conditions & planting/harvest pace "
                    "(NASS, by US state), weather anomalies (rain/heat z), FX, ENSO (ONI/IOD), the US "
                    "season-average farm price (WASDE, with its release vintage), world monthly price "
                    "benchmarks and fertilizer/energy input costs (urea/DAP/potash/NPK, US & EU natural "
                    "gas, Brent) with their 5-year z-scores, and per-delivery-month futures settles "
                    "including the forward curve across expiries")
_SUGGEST_LANES = ("weather (frost/drought/harmattan/monsoon/La Nina), policy & trade (export bans/tariffs/"
                  "MSP/DMO/biodiesel mandates), biofuel & energy (RIN/RFS/crude/natgas/fertilizer), macro "
                  "(FX/freight/logistics), substitution, positioning, and stock/reserve buffers")
# The answerable-gate denylist: subjects we hold NO data for. Energy is denied ONLY as an inventory/stock
# (we have crude/natgas PRICES + biodiesel/renewable-diesel DEMAND as drivers — those stay); metals/financials
# are always out. A grounded chip matching this is dropped.
_SUGGEST_DENY = re.compile(
    r"\b(diesel|gasoil|gasoline|heating oil|jet fuel|crude\s*oil|natural\s*gas|petroleum|refined product)\b"
    r"[^.?!]{0,30}\b(inventor(y|ies)|stocks?|storage|buffers?|overhang|depletion|reserves?|days of (supply|cover))\b"
    r"|\b(gold|silver|copper|iron ore|lithium|nickel|zinc|palladium|platinum|alumin\w+)\b"
    r"|\b(bitcoin|crypto\w*|ethereum|equit\w+|s&p\s*500|nasdaq|treasur\w+|bond yield|fed funds|interest rate)\b",
    re.I)


def _reroute_v2_on() -> bool:
    """RV-v2 feature flag, read at the suggester surface so flag-off is BYTE-IDENTICAL here too: when OFF the
    suggester neither advertises cross-commodity pairs nor runs the framed-cross-ask gate (mirrors the
    orchestrator's _reroute_v2_on). Default-off, fail-closed."""
    return os.environ.get("GRAPHRAG_REROUTE_V2", "off").lower() == "on"


# ── RV-v2 cross-commodity pairs (allowlist = curated `material` AND per-PAIR census-realizable) ─────────
# The suggester may propose a cross-commodity CASCADE chip ONLY for a pair whose per-PAIR census verdict is
# FIRES (cascade_census.pair_realizable -- the Recipe-B World su_ratio probe, NOT contract_can_any_leg_fire).
# Candidacy from the graph's cross_links is NOT enough; realizability is the gate. A clicked chip re-enters
# as an ordinary query and must re-pass is_cross_commodity_explicit + the orchestrator LAW, so the chip is
# never a bypass -- it is only Haiku TEXT, gated here and degrading to [] on any failure.
_XC_EXCHANGE_TOKENS = frozenset({"cbot", "cme", "dce", "zce", "ice", "matif", "mcpo", "nybot", "liffe",
                                 "bmd", "crude", "malaysian", "zce", "mcx", "kcbt"})


def _leg_word(slug: str) -> str:
    """A chip-facing commodity phrase from a contract slug: drop exchange/venue tokens, de-underscore
    ('soybean_oil_cbot' -> 'soybean oil', 'malaysian_crude_palm_oil_cme' -> 'palm oil')."""
    words = [w for w in str(slug or "").lower().split("_") if w and w not in _XC_EXCHANGE_TOKENS]
    return " ".join(words)


def _leg_tokens(slug: str) -> set:
    """Distinguishing match tokens for a leg (>=3 chars, exchange tokens stripped)."""
    return {w for w in _leg_word(slug).split() if len(w) >= 3}


def _suggest_pairs() -> list[dict]:
    """Realizable `material` cross-commodity pairs from lane-A's complex_map, filtered by the per-PAIR census
    verdict (cascade_census.pair_realizable == True). [] on any failure or when the map is unavailable
    (fail-closed: the suggester never advertises a pair it cannot realize)."""
    try:
        from leviathan.graphrag.complex_map import load_complex_map
        from leviathan.graphrag.numbers.cascade_census import pair_realizable
        cm = load_complex_map()
    except Exception:  # noqa: BLE001 -- map missing/malformed -> no pairs, never an error
        return []
    out: list[dict] = []
    for p in (getattr(cm, "pairs", []) or []):
        try:
            if getattr(p, "materiality_tier", None) not in (None, "material"):
                continue
            if pair_realizable(getattr(p, "id", None)) is not True:
                continue
            legs = list(getattr(p, "pair", ()) or ())
            if len(legs) != 2:
                continue
            out.append({"id": p.id, "legs": legs, "complex_name": getattr(p, "complex_name", None),
                        "shared_event": getattr(p, "shared_event", None)})
        except Exception:  # noqa: BLE001 -- skip a malformed pair, never fail the whole suggest
            continue
    return out


def _names_allowed_pair(text_lc: str, allowed: list[tuple]) -> bool:
    """True if the chip text mentions a token from BOTH legs of SOME allowlisted realizable pair."""
    for a_tok, b_tok in allowed:
        if any(t in text_lc for t in a_tok) and any(t in text_lc for t in b_tok):
            return True
    return False


def _xc_chip_gate(chips: list[str], catalog: Optional[dict]) -> list[str]:
    """Positive answerable-gate (RV-W4.4): DROP any chip FRAMED as an explicit cross-commodity ask
    (self-trips is_cross_commodity_explicit) whose named pair is NOT a realizable material pair. A chip
    naming an allowlisted realizable pair passes; a single-commodity chip (not framed) passes untouched.
    Fail-OPEN on any error (the register/deny/number gates still run); the whole suggest still degrades to []
    on an outer failure."""
    pairs = (catalog or {}).get("pairs") or []
    # DISTINGUISHING tokens only: subtract the shared token ('oil' is in both soybean_oil and palm_oil), so a
    # sunflower-oil chip mentioning 'palm' + 'oil' does NOT false-match the soy<->palm allowlist.
    allowed = [(a - b, b - a) for a, b in
               ((_leg_tokens(p["legs"][0]), _leg_tokens(p["legs"][1])) for p in pairs)]
    try:
        from leviathan.graphrag.intent import is_cross_commodity_explicit as _xc
    except Exception:  # noqa: BLE001 -- lane-B detector absent -> cannot identify framing, leave chips as-is
        return chips
    out: list[str] = []
    for s in chips:
        try:
            framed = bool(_xc(s)[0])
        except Exception:  # noqa: BLE001
            framed = False
        if framed and not _names_allowed_pair(s.lower(), allowed):
            continue                                                   # framed cross-ask, non-allowlisted pair
        out.append(s)
    return out


def _suggest_scope(body: M.SuggestRequest, facts: Optional[dict]) -> list[str]:
    """Lowercased, de-underscored scope terms (the user's markets/regions + the last turn's contracts) used to
    pick which regimes-near-firing to surface. Empty -> global (top-N closest to firing)."""
    terms: list[str] = []
    f = facts or {}
    for key in ("markets", "regions"):
        v = f.get(key)
        if isinstance(v, list):
            terms += [str(x).strip().lower() for x in v if str(x).strip()]
    terms += [c.replace("_", " ").lower() for c in (body.contracts or [])]
    return list(dict.fromkeys(t for t in terms if t))[:12]


def _suggest_catalog(scope: list[str]) -> Optional[dict]:
    """Data-scoped catalog from the WARM convergence matrix (never computed live): tracked contracts + the
    regimes closest to firing (scoped to the user's markets, else global top-N). None when the flag is off or
    the matrix is cold -> the route then uses the byte-identical base prompt."""
    if os.environ.get("GRAPHRAG_SUGGEST_CATALOG", "off").lower() != "on":
        return None
    warm = _STATE.get("conv_warm")
    if not warm:
        return None                                                    # cold -> no regime block (never live)
    rows = (warm[2] or {}).get("rows") or []
    cands: list[dict] = []
    for r in rows:
        cid, regs = r.get("contract"), (r.get("regimes") or [])
        if not cid or not regs:
            continue
        top = regs[0]                                                  # rows are sorted fired-first, closest-first
        cands.append({"contract": cid, "regime": top.get("name"), "direction": top.get("direction"),
                      "proximity": top.get("proximity") or 0.0, "n_active": top.get("n_active"),
                      "threshold": top.get("threshold"), "matched": top.get("matched") or []})
    if not cands:
        return None
    scoped = [c for c in cands if any(t in str(c["contract"]).replace("_", " ").lower() for t in scope)] if scope else []
    pool = sorted(scoped if len(scoped) >= 2 else cands, key=lambda c: -(c["proximity"] or 0.0))[:8]
    return {"near": pool, "contracts": sorted({c["contract"] for c in cands}),
            "pairs": _suggest_pairs() if _reroute_v2_on() else []}   # flag off => byte-identical (no pairs)


def _suggest_catalog_text(cat: dict) -> str:
    """Render the catalog into register-clean prompt lines. `reg.sanitize` humanizes contract slugs + regime
    ids via the authoritative display registry (arabica_coffee -> spelled out; bullish_supply_squeeze ->
    'supply squeeze (bullish)'); drivers are de-underscored (they are not register-leaky)."""
    from leviathan.graphrag import register as reg
    lines = ["Tracked contracts (ONLY ask about these): " + ", ".join(cat["contracts"])[:500]]
    near = cat.get("near") or []
    if near:
        rl = []
        for c in near:
            prox = f'{c["n_active"]}/{c["threshold"]}' if c.get("threshold") else ""
            drv = ", ".join(str(d).replace("_", " ") for d in (c.get("matched") or [])[:3])
            rl.append(f"- {c['contract']}: {c['regime']} at {prox} (firing now: {drv or 'none yet'})")
        lines.append("Regimes closest to tipping (drivers firing / threshold to fire):\n" + "\n".join(rl))
    pairs = cat.get("pairs") or []
    if pairs:                                                          # RV-v2: only realizable material pairs
        pl = []
        for p in pairs:
            a, b = _leg_word(p["legs"][0]), _leg_word(p["legs"][1])
            ev = str(p.get("shared_event") or "").replace("_", " ")
            pl.append(f"- {a} <-> {b}" + (f" (shared event: {ev})" if ev else ""))
        lines.append("Cross-commodity cascades you MAY ask about (ONLY these pairs; phrase each as an EXPLICIT "
                     "two-commodity question, e.g. 'palm export ban -- what does that do to soybean oil?'):\n"
                     + "\n".join(pl))
    lines.append("Answerable fundamentals you may cite: " + _SUGGEST_METRICS)
    lines.append("Any headline shock maps into one of these lanes: " + _SUGGEST_LANES)
    return reg.sanitize("\n".join(lines))


def _suggest_prompt_grounded(body: M.SuggestRequest, facts: Optional[dict], cat_text: str) -> str:
    """The convexity-house-style, ANSWERABLE-ONLY prompt: short buffer+rate -> named-regime-tip questions
    scoped to the catalog (our DAGs + silver). Used only when the catalog flag is on and the matrix is
    warm; otherwise the route uses the byte-identical base `_suggest_prompt`."""
    lines = [
        "You suggest the NEXT question a commodity researcher would ask, in the house style of a convexity",
        "desk: a supply BUFFER + a depletion/flow RATE tipping a NAMED regime. Return ONLY a JSON array of",
        "EXACTLY 3 questions. Each MUST be under 120 characters -- count the characters, a longer one is",
        "DISCARDED. Keep each to ONE buffer + ONE rate + ONE regime, no extra clauses. Plain English, ASCII,",
        "no code_like names, no price targets.",
        "HARD RULE -- answerable-only: reference ONLY the contracts, regimes, drivers and fundamentals listed",
        "below. NEVER invent a commodity, inventory, geography or metric that is not listed (no energy/diesel",
        "inventories, no metals, no non-listed countries).",
        "NEVER state a specific numeric level, threshold, or quantity (no '16 million bags', no '0.45 ratio', no",
        "'>15% lag') -- ask about DIRECTION and CONFLUENCE; you do not have the live values.",
        "Style (108 chars): 'Cane crush firm -- how fast must sugar ending stocks fall before the ethanol-",
        "diversion regime fires?'",
        "Mix: (1) a regime CLOSEST TO FIRING for the user's markets, (2) a cross-commodity CASCADE, (3) one",
        "going deeper on the last answer.",
        "",
        cat_text,
    ]
    if body.question:
        lines.append(f"\nLast question: {body.question[:300]}")
    if body.tldr:
        lines.append(f"Answer TL;DR: {body.tldr[:400]}")
    f = facts or {}
    interests: list[str] = []
    for key in ("markets", "interests", "regions"):
        v = f.get(key)
        if isinstance(v, list):
            interests += [str(x).strip() for x in v if str(x).strip()]
    if interests:
        lines.append("User markets/interests: " + ", ".join(dict.fromkeys(interests))[:200])
    return "\n".join(lines)


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
    facts_d = facts if isinstance(facts, dict) else None
    # 6.8 grounded path: when GRAPHRAG_SUGGEST_CATALOG=on AND the convergence matrix is warm, build a
    # data-scoped catalog + the convexity house-style prompt; else the byte-identical base prompt. EVERYTHING
    # below (catalog build, prompt build, model call, parse) is inside ONE try so ANY failure degrades to [].
    try:
        scope = _suggest_scope(body, facts_d)
        catalog = _suggest_catalog(scope)
        if catalog:
            prompt = _suggest_prompt_grounded(body, facts_d, _suggest_catalog_text(catalog))
        else:
            prompt = _suggest_prompt(body, facts_d)
        call = _STATE.get("suggest_call")
        if call is None:
            from leviathan.graphrag import providers as pv
            def call(p: str) -> str:
                client = pv.make_client()
                out = client.messages.create(model=pv.resolve_model("claude-haiku-4-5"), max_tokens=320,
                                             messages=[{"role": "user", "content": p}])
                return "".join(b.text for b in out.content if getattr(b, "type", "") == "text").strip()
        sug = _parse_suggestions(call(prompt) or "")
        if catalog:                                                    # answerable-gate: drop out-of-domain chips
            sug = [s for s in sug if not _SUGGEST_DENY.search(s)]
            if _reroute_v2_on():                                       # flag off => gate never runs (byte-identical)
                sug = _xc_chip_gate(sug, catalog)                      # RV-v2: drop non-allowlisted cross-asks
        return M.SuggestResponse(suggestions=sug).model_dump()
    except Exception:  # noqa: BLE001 — ANY failure (catalog/prompt/model/parse) -> no chips
        return empty


# ── D-AM-16 deterministic prompt gallery — the suggester's opposite number ───────────────────────────
# /v1/suggest is a per-request Haiku call against a daily quota that degrades to []: right for a follow-up
# row under a finished answer, wrong for the landing page, where an empty starter row IS the whole screen.
# The gallery is the deterministic half: AUTHORED templates (configs/graphrag/gallery.yaml) whose slots are
# filled from the SAME warm catalog `_suggest_catalog` builds — a dict read off the convergence warmer, no
# model, no quota, no per-request computation. Two users on the same book on the same day see the same
# gallery, which is what makes it a gallery rather than a feed.
_GALLERY_PATH = Path(__file__).resolve().parents[3] / "configs" / "graphrag" / "gallery.yaml"
_GALLERY_SLOT = re.compile(r"\{(\w+)\}")


@functools.lru_cache(maxsize=1)
def _gallery_templates() -> tuple[dict, ...]:
    """The curated templates, parsed ONCE per process (authored IP, never hot-edited; tests call
    `_gallery_templates.cache_clear()`). Fail-CLOSED to () on a missing or malformed file — no starter row
    is a quiet degradation, whereas a half-parsed one puts a broken question in front of every new thread.

    Each row's `rc_target` is a CLAIM about the authored wording: that the filled question selects that
    response contract through intent.select_response_contract. tests/unit/test_dam_gallery.py pins every
    row, filled and slot-neutralized, so the cue can never migrate into a slot value."""
    try:
        import yaml
        rows = (yaml.safe_load(_GALLERY_PATH.read_text(encoding="utf-8")) or {}).get("templates") or []
        out: list[dict] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            tid, tpl = str(r.get("id") or "").strip(), str(r.get("template") or "").strip()
            if not tid or not tpl:
                continue                                   # a row missing either is unrenderable, not fatal
            out.append({"id": tid, "category": str(r.get("category") or "general"), "template": tpl,
                        "rc_target": str(r.get("rc_target") or "default")})
        return tuple(out)
    except Exception:  # noqa: BLE001 — unreadable/malformed config must never 500 the landing page
        return ()


def _gallery_slots(cat: Optional[dict], i: int) -> dict:
    """Deterministic slot values for template index `i`, read straight out of the warm catalog dict.

    `contract` and `regime` come from the SAME near-firing row, so the pairing is TRUE — that regime really
    is the one closest to tipping for that contract, not an arbitrary cross-product. Only when the near pool
    is empty does `contract` fall back to the tracked-contract list, and then no regime is offered at all.
    `pair` is drawn ONLY from the catalog's realizable set (census-gated upstream in `_suggest_pairs`), so
    the gallery can never advertise a cascade the engine cannot walk.

    Rotating every pool by the template index is what keeps a 12-row gallery from naming one contract twelve
    times while staying reproducible: same catalog in, same gallery out."""
    if not cat:
        return {}
    out: dict = {}
    near, contracts, pairs = cat.get("near") or [], cat.get("contracts") or [], cat.get("pairs") or []
    if near:
        row = near[i % len(near)]
        out["contract"] = _leg_word(str(row.get("contract") or ""))
        regime = str(row.get("regime") or "")
        if regime:
            from leviathan.graphrag import display as dsp
            out["regime"] = dsp.regime_label(regime)       # the authoritative reader label; never a raw id
    elif contracts:
        out["contract"] = _leg_word(str(contracts[i % len(contracts)]))
    if pairs:
        legs = list((pairs[i % len(pairs)] or {}).get("legs") or ())
        if len(legs) == 2:
            a, b = _leg_word(str(legs[0])), _leg_word(str(legs[1]))
            if a and b:
                out["pair"] = f"{a} and {b}"
    return {k: v for k, v in out.items() if v}


def _gallery_vocab(cat: Optional[dict]) -> dict:
    """D-UX-1 — the RAW slot vocabularies beside the filled examples: what the FE's per-slot combobox offers
    when the analyst edits a template. Same warm-catalog dict `_gallery_slots` fills from, so the answerable
    set has exactly ONE definition on this route (including the per-pair census gate: `cat['pairs']` is
    already the realizable set, and nothing else may reach `pairs`).

    Order is meaning, not cosmetics: the near-firing contracts lead the contract list (those are the ones a
    desk has a reason to ask about today), then the rest of the tracked book in catalog order. De-duped,
    order-preserving, and free of any pairing claim — a dropdown offers VALUES; only `_gallery_slots` pairs
    a contract with the regime that is truly closest to firing for it. Cold catalog -> three empty lists
    (the combobox still accepts free typing, which is the honest degradation)."""
    if not cat:
        return {"contracts": [], "regimes": [], "pairs": []}
    near = cat.get("near") or []
    contracts: list[str] = []
    regimes: list[str] = []
    for row in near:
        c = _leg_word(str(row.get("contract") or ""))
        if c and c not in contracts:
            contracts.append(c)
        regime = str(row.get("regime") or "")
        if regime:
            from leviathan.graphrag import display as dsp
            label = dsp.regime_label(regime)               # reader label, never a raw id (same rule as the fill)
            if label and label not in regimes:
                regimes.append(label)
    for slug in cat.get("contracts") or []:
        c = _leg_word(str(slug))
        if c and c not in contracts:
            contracts.append(c)
    pairs: list[str] = []
    for p in cat.get("pairs") or []:
        legs = list((p or {}).get("legs") or ())
        if len(legs) == 2:
            a, b = _leg_word(str(legs[0])), _leg_word(str(legs[1]))
            if a and b and f"{a} and {b}" not in pairs:
                pairs.append(f"{a} and {b}")
    return {"contracts": contracts, "regimes": regimes, "pairs": pairs}


def _gallery_items(cat: Optional[dict]) -> list[dict]:
    """Fill each template, or fall back to the raw template. The two miss-cases are deliberately different:
    a COLD catalog returns every row unfilled (the gallery is the landing page's only content, so it must
    never be empty — the braces read as the fill-in-the-blank prompt the row already is), while a WARM
    catalog DROPS a row whose slots it cannot fill (a lone blank next to eleven concrete questions reads as
    a bug; the commonest case is the pair rows with RV-v2 off)."""
    items: list[dict] = []
    for i, t in enumerate(_gallery_templates()):
        vals = _gallery_slots(cat, i)
        filled = set(_GALLERY_SLOT.findall(t["template"])) <= set(vals)
        if cat is not None and not filled:
            continue
        q = _GALLERY_SLOT.sub(lambda m: vals[m.group(1)], t["template"]) if filled else t["template"]
        # D-UX-1: the raw wording and the values it was filled with ride along, so the FE can re-fill the
        # template under analyst edits. `slots` is narrowed to the template's OWN blanks -- `_gallery_slots`
        # may compute a value (e.g. `pair`) for a row that has no such blank, and shipping it would invite
        # the FE to substitute a slot the authored wording never had.
        used = {k: v for k, v in vals.items() if k in set(_GALLERY_SLOT.findall(t["template"]))} if filled else {}
        items.append({"id": t["id"], "category": t["category"], "question": q,
                      "rc_target": t["rc_target"], "filled": filled,
                      "template": t["template"], "slots": used})
    return items


@app.get("/v1/gallery", response_model=M.Gallery)
def gallery_route(ident: dict = Depends(_require_identity)) -> dict:
    """Curated starters for the empty state. Identity-gated like every other read, and FREE — no model call
    and NO quota of any kind (unlike /v1/suggest, which spends one per turn). The catalog is the suggester's
    own `_suggest_catalog` with an empty scope (global top-N closest to firing): reusing it keeps ONE
    definition of what is answerable, including the per-pair census gate. That also means the catalog flag
    and the convergence warmer govern here too — with either off the catalog is None and the route serves
    the unfilled templates, which is a legible fallback rather than a failure.

    D-UX-1 makes the same read serve the EDITABLE library as well as the landing page: each item carries its
    raw `template` plus the `slots` it was filled with, and the response carries the `vocab` those slots were
    drawn from. Additive only — `items[].question` and `catalog_warm` are byte-identical to D-AM-16."""
    try:
        cat = _suggest_catalog([]) or None      # `or None`: an EMPTY catalog is a cold one, not a warm empty
    except Exception:  # noqa: BLE001 — a catalog hiccup degrades to the template fallback, never a 500
        cat = None
    return M.Gallery(items=[M.GalleryItem(**i) for i in _gallery_items(cat)],
                     catalog_warm=cat is not None,
                     vocab=M.GalleryVocab(**_gallery_vocab(cat))).model_dump()


# ── 6.6 settings / profile facts / onboarding (auth-gated; prefs, never the answer path) ────────────
_FACT_KEYS_LIST = ("markets", "regions", "notes")
_FACTS_MAX_ITEMS = 12
_FACT_MAX_LEN = 140
_SEAT_MAX_LEN = 40


def _sanitize_facts(facts: Any) -> dict:
    """Normalize the client-supplied facts dict to KNOWN keys with bounded, trimmed values — it is
    user-authored text that later flows into the suggester prompt. Unknown keys dropped; each list capped at
    12 items x 140 chars (blanks removed); seat capped at 40. Anything malformed collapses to {}."""
    if not isinstance(facts, dict):
        return {}
    out: dict = {}
    for key in _FACT_KEYS_LIST:
        v = facts.get(key)
        if isinstance(v, list):
            cleaned = [str(x).strip()[:_FACT_MAX_LEN] for x in v if str(x).strip()]
            if cleaned:
                out[key] = cleaned[:_FACTS_MAX_ITEMS]
    seat = facts.get("seat")
    if isinstance(seat, str) and seat.strip():
        out["seat"] = seat.strip()[:_SEAT_MAX_LEN]
    return out


def _profile_payload(ident: dict, *, consistent: bool = False) -> dict:
    """Assemble the Profile response: the stored record's fields, falling back to the ID-token claims for
    name/email (a user who signed in but never ran a turn has claims but a thin/absent record). `consistent`
    forces a strongly-consistent read for the PUT read-after-write."""
    p = _store().get_profile(ident["sub"], consistent=consistent) or {}
    facts = p.get("facts")
    return M.Profile(
        sub=ident.get("sub"),
        email=p.get("email") or ident.get("email"),
        name=p.get("name") or ident.get("name"),
        facts=facts if isinstance(facts, dict) else {},
        onboarded=bool(p.get("onboarded")),
        turn_count=int(p.get("turn_count") or 0),
        first_seen=p.get("first_seen"),
        last_seen=p.get("last_seen"),
    ).model_dump()


@app.get("/v1/profile", response_model=M.Profile)
def get_profile_route(ident: dict = Depends(_require_identity)) -> dict:
    """The signed-in user's own profile — identity claims + facts + the onboarding flag. Auth-gated; a
    missing record returns identity-only defaults (facts={}, onboarded=false)."""
    return _profile_payload(ident)


@app.put("/v1/profile", response_model=M.Profile)
def put_profile_route(body: M.ProfileUpdate, ident: dict = Depends(_require_identity)) -> dict:
    """Update the user's facts and/or onboarding flag — a PARTIAL update (omitted fields unchanged). Facts
    are normalized server-side before the write; the fresh profile is returned. A genuine store failure
    propagates (the client must know a save didn't persist — unlike the fire-and-forget touch_profile)."""
    facts = _sanitize_facts(body.facts) if body.facts is not None else None
    _store().update_profile(ident["sub"], facts=facts, onboarded=body.onboarded)
    return _profile_payload(ident, consistent=True)                  # read-after-write must not echo a stale copy


# ── P3 morning-brief notifications (auth-gated; read + mark-seen; behind GRAPHRAG_NOTIFICATIONS) ─────
_NOTIF_WIRE = ("notif_id", "created_at", "seen", "event_type", "commodity", "date",
               "summary", "country", "label", "query", "driver_id")


def _notifications_on() -> bool:
    return os.environ.get("GRAPHRAG_NOTIFICATIONS", "on").lower() == "on"


def _project_notification(n: dict) -> dict:
    """Server-side projection to the NARROW wire fields ONLY. The stored body also carries `event` (the raw
    LiveEvent audit blob: adversary-controlled headline/url/source) which must NEVER reach the browser —
    strip it here; the strict NotificationItem model (extra='ignore') is the belt."""
    return {k: n[k] for k in _NOTIF_WIRE if k in n}


@app.get("/v1/notifications", response_model=list[M.NotificationItem])
def list_notifications_route(unseen_only: bool = False, ident: dict = Depends(_require_identity)) -> list:
    """The signed-in user's daily-digest notifications, newest-first. Empty list when the feature is off or
    the user has none — the bell degrades to 'no notifications' cleanly, never a 404. Preferences-adjacent
    (never the answer/evidence path), so the PIT firewall is untouched. No quota (reads are free)."""
    if not _notifications_on():
        return []
    return [_project_notification(n)
            for n in _store().list_notifications(ident["sub"], unseen_only=unseen_only)]


@app.post("/v1/notifications/{notif_id}/seen")
def mark_notification_seen_route(notif_id: str, ident: dict = Depends(_require_identity)) -> dict:
    """Mark one notification read (idempotent). 404-free AND upsert-free: the store's conditional UpdateItem
    (attribute_exists(sk)) makes an unknown/garbage id a swallowed no-op, so a POST can never CREATE a
    body-less notif# item that escapes TTL. Always 200."""
    if not _notifications_on():
        return {"ok": False, "disabled": True}
    _store().mark_notification_seen(ident["sub"], notif_id)
    return {"ok": True}


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


def _register_item_routes(coll: str, kind: str, purge=None, on_list=None, freeze=None) -> None:
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
        stored = body.body or {}
        if freeze is not None:
            stored = freeze(stored)          # server-side normalization; the client cannot author the shape
        _store().put_item(user, kind, item_id, stored)
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


def _freeze_artifact(body: dict) -> dict:
    """D-AM-15: an artifact is a NAMED, PRIVATE freeze of one answer turn (the per-user collection factory's
    default identity gate is what makes it private — unlike /v1/share, which is public by ratified design).

    The snapshot is minted by `store.make_share`, the SAME freeze the public share link uses — never a second
    one — so an artifact and a share of the same turn can never pin different (payload, asof, graph_version)
    triples. The FULL payload is stored rather than a pointer: reopening an artifact must reproduce the exact
    turn after the graph has moved on, which a re-run by construction cannot. Size therefore rides the same
    ceiling a share does (one Dynamo item).

    The `_TURN_ALLOWED` PIT firewall does NOT apply here and that is deliberate: it governs THREAD history,
    which is replayed as context into later turns and must therefore never carry evidence forward in time.
    An artifact is never replayed into anything — it is a terminal, user-owned copy of a finished answer,
    the same posture `put_share` has held since 1.7.

    `updated_at` is stamped HERE because the client never re-PUTs an artifact (it is immutable once frozen),
    so nothing else would give `_list`'s newest-first sort a key to sort on."""
    from leviathan.graphrag import store as st
    payload = body.get("payload")
    snap = st.make_share(str(body.get("question") or ""), body.get("asof"),
                         payload if isinstance(payload, dict) else {})
    name = str(body.get("name") or "").strip() or snap.question or "untitled artifact"
    return {"name": name[:200], "snapshot": snap.to_dict(),
            "created_at": snap.created_at, "updated_at": snap.created_at}


for _coll, _kind, _purge, _on_list, _freeze in (
    ("threads", "thread", lambda u, tid: _store().delete_turns(u, tid), _touch_profile_async, None),
    ("watchlists", "watchlist", None, None, None),
    ("workspaces", "workspace", None, None, None),
    ("artifacts", "artifact", None, None, _freeze_artifact),
):
    _register_item_routes(_coll, _kind, purge=_purge, on_list=_on_list, freeze=_freeze)


@app.get("/v1/threads/{thread_id}/turns", response_model=M.ThreadTurns)
def thread_turns(thread_id: str, user: str = Depends(_require_user)) -> dict:
    """Durable per-thread history (design §3.1) — the PIT-safe turn records for a thread, oldest-first.
    Conclusions + citation refs only; evidence is never persisted (re-derived on re-run)."""
    return {"thread_id": thread_id, "turns": _store().list_turns(user, thread_id)}


# ══ D-DR-1/2/5: the deep-research DOSSIER surface (NEW REGION — nothing above this line changed) ═════
# Four routes, one flag, one quota. The orchestration lives ENTIRELY in dossier.py (the thin-conductor
# contract this module opens with): everything here is HTTP translation — gate, auth, 202/404/429, the
# SSE relay, and the in-process job handoff. `dossier` is imported lazily inside each handler, exactly
# like `orchestrator`, so importing the app never drags the answer stack in.
#
# DARK-FIRST (D-DR-5): GRAPHRAG_DOSSIER absent -> every route 404s, indistinguishable from a build that
# never had them. A non-wildcard value is an ALLOWLIST of Cognito subs (the internal-only stage), and a
# principal outside it gets the same 404 — a feature you are not in must not be advertised by a 403.
_DOSSIER_ASOF_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class DossierIn(BaseModel):
    question: str
    asof: Optional[str] = None


def _dossier_gate(ident: dict):
    """The flag + allowlist gate, applied identically on all four routes. Returns the dossier module so
    a handler reads `dsr = _dossier_gate(ident)` and is done."""
    from leviathan.graphrag import dossier as dsr
    if not dsr.allowed(ident.get("sub")):
        raise HTTPException(status_code=404, detail="not found")
    return dsr


@app.post("/v1/dossier", status_code=202)
def dossier_create(body: DossierIn, ident: dict = Depends(_require_identity)) -> dict:
    """Accept a deep-research dossier -> 202 {dossier_id, plan_pending: true}.

    QUOTA IS CHARGED HERE, at ACCEPTANCE, never at completion: two submissions racing on the last slot
    must not both pass, and the atomic conditional counter can only guarantee that at the gate. A job
    that later FAILS refunds; a PARTIAL one does not (it delivered a document and spent real money).

    ONE as-of is stamped now and governs every sub-query (PIT by construction). An unparseable one is
    rejected loudly rather than silently defaulted — a dossier is 20 minutes and 5-12 turns of spend,
    which is the one place in this API where a typo must not be absorbed."""
    dsr = _dossier_gate(ident)
    from leviathan.graphrag import store as st
    q = (body.question or "").strip()
    if not q:
        raise HTTPException(status_code=422, detail="question is required")
    asof = (body.asof or "").strip() or _today()
    if not _DOSSIER_ASOF_RX.match(asof):
        raise HTTPException(status_code=422, detail="asof must be YYYY-MM-DD")
    try:
        # Owner/ops exemption: the monthly counter is never consumed (start() accepts a None period,
        # so the failure-refund path no-ops too). The quota BADGE stays truthful: it never decrements.
        period = None if _exempt_sub(str(ident.get("sub") or "")) else dsr.consume_quota(_store(), ident)
    except st.QuotaExceeded:
        # A JSONResponse, not an HTTPException: the locked contract puts `reset_at` at the TOP level of
        # the 429 body (the picker renders the date), and HTTPException would bury it under `detail`.
        state = dsr.quota_state(_store(), ident)
        return JSONResponse(status_code=429, content={"error": "monthly dossier limit reached",
                                                      "limit": state["limit"], "remaining": 0,
                                                      "reset_at": state["reset_at"]})
    job = dsr.start(_store(), ident, q, asof, graph=_graph(), quota_period=period)
    return {"dossier_id": job.id, "plan_pending": True}


@app.get("/v1/dossier/quota")
def dossier_quota(ident: dict = Depends(_require_identity)) -> dict:
    """{remaining, limit, reset_at} — what the mode picker's badge renders. Free, no model call, no
    turn quota (a read of a counter is not a use of it)."""
    dsr = _dossier_gate(ident)
    return dsr.quota_state(_store(), ident)


@app.get("/v1/dossier/{dossier_id}")
def dossier_get(dossier_id: str, ident: dict = Depends(_require_identity)) -> dict:
    """Job state. Owner-scoped by construction: the record is read out of the caller's OWN partition,
    so another user's id is simply not there (404) — the artifacts privacy posture, not a new one."""
    dsr = _dossier_gate(ident)
    rec = dsr.load(_store(), ident["sub"], dossier_id)
    if not rec:
        raise HTTPException(status_code=404, detail="no such dossier")
    return dsr.wire_snapshot(dsr.reap_orphan(_store(), ident["sub"], rec))


@app.get("/v1/dossier/{dossier_id}/events")
def dossier_events(dossier_id: str, ident: dict = Depends(_require_identity)):
    """SSE progress stream — the `respond_stream` idiom (queue relay, 10s keepalive comment, terminal
    event closes), with ONE difference that matters: the job is not owned by this request, so the
    stream REPLAYS the events already recorded before it attaches. A client that connects after the
    plan landed still sees the plan; a client that connects after the job finished gets the whole
    history and an immediate close. Both are the same code path.

    A dossier that is not live in THIS process (a restart, or another task) replays its persisted log
    and closes — never a stream that hangs forever waiting for a thread that does not exist."""
    dsr = _dossier_gate(ident)
    rec = dsr.load(_store(), ident["sub"], dossier_id)
    if not rec:
        raise HTTPException(status_code=404, detail="no such dossier")
    job = dsr.get_job(dossier_id)
    live = job is not None and job.user == ident["sub"]

    def gen():
        if not live:
            for ev in (dsr.reap_orphan(_store(), ident["sub"], rec).get("events") or []):
                yield f"event: {ev.get('type', 'stage')}\ndata: {json.dumps(ev, default=str)}\n\n"
            return
        replay, q = job.subscribe()
        # Hard stop: the job's own wall-clock cap plus slack. A job thread that dies WITHOUT emitting a
        # terminal event (a hard kill; execute() itself always emits one) would otherwise keepalive
        # this stream until the ALB idle timeout, which reads to the client as a job still running.
        stream_deadline = time.time() + dsr.WALL_CLOCK_S + 60
        try:
            for ev in replay:
                yield f"event: {ev.get('type', 'stage')}\ndata: {json.dumps(ev, default=str)}\n\n"
                if ev.get("type") in dsr.TERMINAL:
                    return
            while True:
                try:
                    ev = q.get(timeout=10)
                except queue.Empty:
                    if job.status in dsr.TERMINAL or time.time() > stream_deadline:
                        return                       # terminal landed between the replay and the wait
                    yield ": keepalive\n\n"          # SSE comment — keeps ALB/proxy from idling out
                    continue
                yield f"event: {ev.get('type', 'stage')}\ndata: {json.dumps(ev, default=str)}\n\n"
                if ev.get("type") in dsr.TERMINAL:
                    return
        finally:
            job.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
