"""pgvector evidence store — the indexed backend for retrieve() (EVIDENCE_BACKEND=pg).

Replaces the flat-file path's per-call full-slice scan (JSONL -> pure-Python cosine over 15-23K props) with ONE
SQL round-trip per node: a dense CTE (exact cosine via `vector <=>`, filtered `node = :n AND date <= :asof`) fused
with a lexical CTE (Postgres FTS, 'simple' dict so finance codes like B40/ZL stay whole tokens) by Reciprocal
Rank Fusion — mirroring the flat path's hybrid semantics. Everything AFTER candidate fetch is byte-identical to
the flat path: episode-proximity re-scoring, the bge cross-encoder rerank, and source-aware MMR all run
in-process on the returned candidates (rankers.py untouched, as its docstring promised).

Design choices (deliberate):
  - NO ANN index. Slices are small (thousands of props once filtered), so a btree(node, date) prefilter + exact
    cosine is milliseconds with ZERO recall loss. HNSW is a later option if the corpus 10x-es.
  - Postgres is a DISPOSABLE derived index — S3 stays the source of truth. Drop/rebuild anytime via the loader,
    which reuses the slices' inline vectors (never re-embed, never re-chunk).
  - Leakage-safety in SQL: `date <= asof` is part of the candidate query itself, mirroring retrieve()'s
    filter-FIRST rule.
  - The vector payload is CONDITIONAL (F2): arms that consume the raw vectors in-process (rerank / MMR) get
    `p.vector::text`; arms that consume only the cosine ORDER — every convergence probe — get the scalar
    pgvector already computed for the ORDER BY. Same formula, ~700 KB less wire and no Python cosine.

DSN from EVIDENCE_PG_DSN (e.g. postgresql://postgres:...@host:5432/leviathan). psycopg3; the query vector rides
as a '[f1,f2,...]' literal cast ::vector, so no extra adapter package is needed.

EC-3 FILL PATIENCE -- THE ORCHESTRATOR DECISION OF RECORD (2026-08-15). A METERED turn (the user bought
depth: rm.is_metered on the HONORED mode) waits longer for a pool slot than an unmetered one, because
flooring a paid turn to save 3 minutes is the wrong trade and fast-fail is only correct for Scan. The
shape of that patience was the decision, and it is a TURN-SCOPED DEADLINE, NOT A PER-BORROW DURATION:

  ONE horizon per turn bounds the TOTAL borrow WAITING across ALL of that turn's borrows.

WHY, PLAINLY: a max-width walk issues HUNDREDS of borrows (the EC-2 item exists precisely to collapse
that count). A per-borrow patience of 300s is therefore not a 300s promise -- it is 300s x hundreds of
borrows of worst-case latency, i.e. an unbounded turn wearing a bounded-looking number, and the ALB's
1800s idle would be the only thing left holding the line. A deadline installed once at the top of the
grounded walk cannot compound: every borrow reads the SAME instant, the last one gets whatever is left,
and the turn degrades to the deterministic floor the moment the horizon passes -- degrade, never hang.
It also makes the knob READABLE: `GRAPHRAG_FILL_PATIENCE_S=300` means this turn will spend at most ~300s
waiting on the pool, full stop, whatever the walk's width turns out to be.

Two consequences, both deliberate. (1) The deadline lives on a THREAD-LOCAL, so it is per-turn by
construction on a threaded server and a concurrent unmetered turn is untouched -- but the fill/probe
worker pools do not inherit it (contextvars do not reach them either; planner records that finding), so
each pool CAPTURES on the parent thread and INSTALLS per worker, the exact `rankers.adopt_lane` shape.
(2) A borrow that starts with less than `_POOL_WAIT_S` left on the clock takes the LEGACY single-get
path unchanged, so the last borrow of an exhausted horizon can overshoot it by at most one `_POOL_WAIT_S`
-- accepted, because the alternative is a second timeout grammar for the final borrow of every walk.
Patience is OFF by default in the sense that matters: nothing installs a deadline unless the orchestrator
does, and `GRAPHRAG_FILL_PATIENCE_S=0` disables it estate-wide with no deploy.

THE NUMBERS LANE IS EXEMPT, AND THE EXEMPTION IS ENFORCED, NOT ASSUMED (corrected 2026-08-15). Its
Athena fallback IS its patience, and making it wait would trade a fast honest degrade for a slow one.
But the deadline is AMBIENT -- `_acquire` reads a thread-local, it is not an opt-in argument -- so
"does not adopt" buys nothing on its own: the cascade-quantify legs call `numbers_lookup` SEQUENTIALLY
ON THE WALK THREAD (answer.py's `cq.quantify(qfn=...)`, inside the orchestrator's `_patience_ctx`),
so `pgnumbers.pg_query` inherited the metered horizon on every metered reasoning/hybrid turn and a
lookup the design says fast-fails at `_POOL_WAIT_S` could block for the whole remaining horizon. Only
the FORKED numbers-agent thread was ever exempt, and that was an accident of threading, not the
decision. `without_patience()` below is the enforcement: the numbers lane SUSPENDS the turn's horizon
across its own borrow and restores it, so its borrow is the legacy single-get on every lane while the
walk's own borrows keep the horizon they were given.

EC-2 BATCHED FILL READS + THE BORROW LEDGER (2026-08-15; LIVE IN SERVING at GRAPHRAG_EVIDENCE_BATCH=1
since rev 98 -- CORRECTED 2026-08-18, D-LD Track 2 #8, this line used to say "SHIPS DARK". The code
default remains OFF, so clearing the env var is still the no-redeploy rollback).
`fetch_candidates` is ONE BORROW PER NODE, and a max-width walk visits hundreds of nodes -- that borrow
COUNT is the capacity problem EC-1 bought hardware to survive and EC-3 bought patience to tolerate.
`fetch_candidates_batch()` is the structural fix: N nodes collapse into ceil(N/chunk) LATERAL
set-statements, ONE borrow each, scattered back to a per-node dict by the leading node column. The
per-node SQL is UNCHANGED in shape -- the same dense leg, the same RRF fusion, the same `date <= asof`
leakage filter riding INSIDE the same WHERE -- so PIT safety is not re-argued here, it is re-used.

TWO THINGS THIS FILE OWES THAT ARC.
  (1) THE TIEBREAK. RRF ties are REAL (1/(60+r) collides across the dense and lexical legs), and fetch
      ORDER is load-bearing downstream (every later sort is stable, so it preserves what SQL handed it).
      Without a total order two statements that are semantically identical may legitimately return two
      different sequences, and a parity pin would then be measuring Postgres' plan choice rather than
      this code. So EVERY ordering in BOTH shapes now ends in the table's PRIMARY KEY (`id`): the dense
      ROW_NUMBER, the dense LIMIT, the lexical ROW_NUMBER, the lexical LIMIT (which had NO ORDER BY at
      all -- an arbitrary k-of-n whenever the FTS leg overflowed `fetch_k`) and the fused final ORDER BY.
      Deterministic on BOTH sides, in the SAME commit, or the parity pin is theatre.
  (2) THE BORROW LEDGER, `borrow_ledger()`: EC-0's gate-(a) instrument. A turn-scoped counter dict on a
      thread-local that `_acquire` bumps, ADOPTED across the fill/probe workers exactly the way the EC-3
      deadline is (same capture on the parent, same install per worker, ONE capture carrying both). It
      counts borrows, never time, and `planner.ground` reads it at two boundaries so the fill's borrows
      and the rest of the walk's are attributable separately.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import random
import re
import threading
import time
from typing import Optional

DIM = 1024                                                   # bge-m3 (and Titan v2) embedding width

# Blue-green plumbing: every DDL/DML statement below resolves its table name through table_name() at CALL
# time (never at import), so a shadow rebuild can point the loader at `evidence_props_shadow`, verify it,
# then flip live<->shadow with a transactional rename (jobs/utils/pg_evidence_swap.py) — the pre-flip table
# is retained for rollback. Default stays `evidence_props`, so unset-env behavior is byte-identical.
_DEFAULT_TABLE = "evidence_props"
# A pg identifier we interpolate straight into DDL/DML (no bind-param path exists for table names). The
# strict lower-snake regex keeps SQL injection impossible: the only accepted characters are the ones a
# legitimate table name uses, so a hostile EVIDENCE_PG_TABLE can never smuggle a quote or a semicolon.
_TABLE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def table_name() -> str:
    """Resolve the evidence table from EVIDENCE_PG_TABLE (default `evidence_props`), validated at call time.

    Resolved per-call (NOT cached at import) so a subprocess/env flip — the loader's --table, the swap
    tool's guard query, a shadow eval's `--env EVIDENCE_PG_TABLE=evidence_props_shadow` — takes effect
    without a re-import, and so tests can monkeypatch the env. Rejects anything that isn't lower-snake:
    the name is interpolated into SQL and there is no bind-parameter form for an identifier, so validation
    is the injection barrier, not an f-string escape."""
    name = (os.environ.get("EVIDENCE_PG_TABLE") or _DEFAULT_TABLE).strip()
    if not _TABLE_RE.match(name):
        raise ValueError(f"EVIDENCE_PG_TABLE {name!r} is not a valid table name (^[a-z_][a-z0-9_]*$)")
    return name

_CONN = None
# The module connection is a SINGLE psycopg connection (not concurrency-safe). The L2 walk now fetches nodes
# in parallel (to overlap the managed-rerank round-trips), so serialize cursor use here — the SQL fetch is
# milliseconds, and the slow rerank happens OUTSIDE this lock, back in pg_retrieve.
_PG_LOCK = threading.Lock()

# Serving-path connection POOL: a turn issues ~34 round-trips (10 fill fetches + ~24 regime probes); one
# lock-serialized connection made that ~8.5s of the walk. A few pooled autocommit connections un-serialize it.
# Callers that pass an explicit `conn` (tests, the loader) keep the old single-connection + lock path.
#
# DEFAULT 4 -> 8 (2026-08-23, owner challenge "why don't we increase ... since it affects answer quality").
# The old 4 was sized against an RDS t4g.micro this estate no longer runs, and it was never a safety margin --
# it was a BOTTLENECK wearing one, on two measured counts:
#   (1) QUALITY/LATENCY: planner._PROBE_WORKERS notes effective probe concurrency is
#       min(probe_workers, EVIDENCE_PG_POOL), so a pool of 4 throttles the WALK itself no matter how wide
#       the preset asks to be -- the pool silently sets the graph's fan-out.
#   (2) AVAILABILITY: exhaustion is not a queue, it is a KILL -- _POOL_WAIT_S trips and the turn floors
#       (`pg_pool_exhausted`). That class voided a whole deck arm set on 2026-08-23.
# MEASURED HEADROOM (db.m7g.xlarge, 4 vCPU/16 GB, postgres 17): max_connections ~1,800; 14-day peak
# 56 connections (the 2026-08-23 eval arms), production-only peak far lower. 8 matches what the serving
# taskdef has always overridden to, so this default now AGREES with production instead of quietly
# disagreeing with it. THE REAL CEILING IS RDS CPU, NOT CONNECTIONS -- measured 2026-08-23: TWO eval arms
# pinned the DB at 99.8-100% CPU at 56 conns (3% of the connection ceiling). The mechanism: there is NO ANN
# index by design (see the module docstring) -- the dense leg is an exact cosine scan, single-threaded and
# CPU-bound, so ONE borrowed slot ~= ONE busy DB vCPU and the sane pool is ~2x DB cores. 4 vCPU -> 8.
# Raise ONLY after the DB grows cores, and NEVER without decoupling numbers/cascade.py's fan-out width,
# which reads _POOL_SIZE directly (cascade.py:1223/:3226/:3404) -- a bigger pool currently widens ONE
# turn's cascade instead of admitting more turns. Eval arms pass EVIDENCE_PG_POOL=24 explicitly because
# their concurrency is known and bounded.
_POOL = None
_POOL_SIZE = int(os.environ.get("EVIDENCE_PG_POOL", "8"))
# Checkout wait ceiling: holders keep a conn for milliseconds (one execute+fetch), so a multi-minute wait
# means slots leaked or a holder wedged — fail the ONE caller loudly (pg_query degrades to its Athena
# fallback; a walk fetch errors its turn) instead of blocking every worker forever (Jul-11 stall autopsy).
_POOL_WAIT_S = int(os.environ.get("EVIDENCE_PG_POOL_WAIT_S", "120"))

# ── EC-3: METERED-TURN FILL PATIENCE (see the module docstring for the decision of record) ─────────────
# The turn's borrow-wait horizon, as a MONOTONIC DEADLINE on a thread-local. Absent (the default state,
# and every unmetered turn) -> `_acquire` runs the legacy single-get path byte-identically.
_PATIENCE_TL = threading.local()
_PATIENCE_ENV = "GRAPHRAG_FILL_PATIENCE_S"
_PATIENCE_DEFAULT_S = 300.0                      # the EC-3 spec's horizon: 120s fast-fail -> up to 300s


def _fill_patience_s() -> float:
    """The metered horizon in seconds, read at CALL TIME (never cached at import), 0.0 = disabled.

    CALL-TIME, like `table_name()` and `_STMT_TIMEOUT_MS`'s read: the knob is the rollback. `=0` turns
    EC-3 off estate-wide without a deploy and without a code path changing shape -- with no deadline
    installed, `_acquire` is the pre-EC-3 function.

    THE GRAMMAR, and the asymmetry is on purpose: an EXPLICIT `0` (or any non-positive value) DISABLES,
    because that is someone deliberately reaching for the rollback. Anything unparseable -- a typo, an
    empty string, `300s`, a value some future taskdef renders as a list -- falls back to the 300s
    DEFAULT rather than to off. A rollback should be something you MEANT; a typo must not silently
    un-ship the feature and leave a floor rate nobody can explain."""
    raw = os.environ.get(_PATIENCE_ENV)
    if raw is None or not str(raw).strip():
        return _PATIENCE_DEFAULT_S
    try:
        v = float(str(raw).strip())
    except (TypeError, ValueError):
        return _PATIENCE_DEFAULT_S
    return v if v > 0 else 0.0


def patience_deadline() -> Optional[float]:
    """THIS thread's borrow-wait deadline (a `time.monotonic()` instant), or None. `_acquire` reads it.

    None is a valid state everywhere -- it is the state of every unmetered turn, every eval/Batch arm,
    every loader and every test that has not installed one."""
    return getattr(_PATIENCE_TL, "deadline", None)


def current_patience_deadline() -> Optional[float]:
    """THE CAPTURE SEAM: read the parent thread's deadline before handing work to a pool.

    Same value as `patience_deadline()`; a distinct NAME because the call sites are distinct duties --
    `patience_deadline()` is the consumer (`_acquire`), this is the producer of the value a worker
    later adopts. `rankers.lane_collector()` plays the same double role for the lane."""
    return patience_deadline()


@contextlib.contextmanager
def set_patience(seconds):
    """Install a horizon of `seconds` on THIS thread for the duration of the block. The orchestrator's
    seam: entered ONCE per metered turn, around the grounded-walk region.

    NESTED-SAFE IN THE DIRECTION THAT MATTERS -- a nested block may SHORTEN the turn's horizon, never
    EXTEND it (the installed deadline is `min(new, existing)`). One horizon per turn is the whole
    decision; a nested 300s inside a 300s turn that had 20s left would silently mint a second horizon
    and the bound would stop being a bound. The prior value is restored in a `finally`, so an exception
    inside the walk can never leave a pooled serving thread carrying a dead turn's deadline.

    `seconds` non-positive/None -> the block is a NO-OP that leaves whatever is installed alone (the
    disabled knob must not clear an outer deadline, and must not install one)."""
    try:
        secs = float(seconds or 0)
    except (TypeError, ValueError):
        secs = 0.0
    if secs <= 0:
        yield
        return
    prior = patience_deadline()
    new = time.monotonic() + secs
    _PATIENCE_TL.deadline = new if prior is None else min(prior, new)
    try:
        yield
    finally:
        if prior is None:
            _clear_patience()
        else:
            _PATIENCE_TL.deadline = prior


@contextlib.contextmanager
def adopt_patience(deadline):
    """Run a block with the PARENT's `deadline` installed on THIS thread -- the fill/probe workers' seam,
    and a literal copy of `rankers.adopt_lane`'s shape (contextvars provably do not reach these pools;
    planner.py records that measurement).

    NESTED-SAFE the same way `adopt_lane` is: a thread that already carries a deadline KEEPS it. The
    sequential branches of both pools run on the CALLER's own thread, where installing-and-clearing
    would strip the turn's own horizon mid-walk. Fail-open end to end -- patience is a latency policy,
    so nothing in here may ever raise into a walk."""
    own = False
    try:
        own = deadline is not None and patience_deadline() is None
        if own:
            _PATIENCE_TL.deadline = float(deadline)
    except Exception:  # noqa: BLE001 — a patience miss costs latitude, never correctness
        own = False
    try:
        yield
    finally:
        if own:
            _clear_patience()


@contextlib.contextmanager
def without_patience():
    """SUSPEND this thread's horizon for the block, then restore it -- THE NUMBERS LANE's seam, and the
    only declared exemption that has to be spelled to be true.

    WHY IT EXISTS AT ALL. The deadline is AMBIENT: `_acquire` reads the thread-local, no caller opts in.
    So a lane cannot exempt itself by not mentioning the patience API -- silence is precisely the state
    in which it INHERITS. `pgnumbers.pg_query` runs on the WALK's own thread on the cascade-quantify
    legs (`cq.quantify(qfn=...)` calls them sequentially inside the orchestrator's `_patience_ctx`), so
    before this seam existed a numbers lookup on a metered turn waited the turn's whole remaining
    horizon instead of fast-failing into Athena at `_POOL_WAIT_S`. The forked numbers-agent thread was
    the only genuinely exempt caller, and only because thread-locals do not cross a fork.

    SUSPEND, NOT DISABLE, and the difference is the bound: the horizon is TURN-scoped, so clearing it
    permanently would hand the rest of the walk an unbounded wait. The prior deadline is restored in a
    `finally` -- the same instant, not a fresh one, so time spent inside the block still counts against
    the turn's horizon and the bound stays a bound. Nesting is a no-op (nothing installed -> nothing to
    restore). Fail-open end to end: patience is a latency policy and may never raise into a lookup."""
    prior = None
    had = False
    try:
        prior = patience_deadline()
        had = prior is not None
        if had:
            _clear_patience()
    except Exception:  # noqa: BLE001 — a suspend miss costs latitude, never correctness
        had = False
    try:
        yield
    finally:
        if had:
            try:
                _PATIENCE_TL.deadline = prior
            except Exception:  # noqa: BLE001 — same fail-open contract as the install side
                pass


def _clear_patience() -> None:
    """Drop this thread's deadline. Pool threads are REUSED across turns, so the clear is what keeps a
    later unmetered turn from inheriting a paid turn's (already expired) horizon."""
    try:
        del _PATIENCE_TL.deadline
    except AttributeError:
        pass


# ── EC-2: THE BORROW LEDGER (gate (a)'s instrument -- borrows per walk) ─────────────────────────────────
# A turn-scoped counter dict on a thread-local, bumped by `_acquire`. Absent (the default, and every
# process that never opens one) -> `_acquire` does one `getattr` and nothing else.
#
# WHY A DICT PLUS ONE MODULE-LEVEL LOCK, and not a lock per ledger: the ledger is SHARED by the fill and
# probe workers that adopt it, so `+= 1` needs mutual exclusion; but the critical section is a single
# integer add against a borrow that is about to spend milliseconds in Postgres, so one process-wide lock
# costs nothing measurable. The DICTS stay per-ledger (so two concurrent turns never blend -- pinned),
# only the mutex is shared.
_LEDGER_TL = threading.local()
_LEDGER_LOCK = threading.Lock()


def _bump_borrow() -> None:
    """Count one pool borrow into THIS thread's ledger, if one is installed. Fail-open by construction:
    an instrument may never raise into a walk."""
    led = getattr(_LEDGER_TL, "ledger", None)
    if led is None:
        return
    try:
        with _LEDGER_LOCK:
            led["borrows"] = int(led.get("borrows", 0)) + 1
    except Exception:  # noqa: BLE001 — a miscount costs a gate read, never an answer
        pass


def open_borrow_ledger() -> dict:
    """Install a FRESH ledger on this thread and return it; whatever was installed is REPLACED.

    Replace-don't-nest is deliberate and is what makes the leak harmless. `planner.ground` reads its two
    regions with `open` + `close_borrow_ledger` rather than a `with` block (wrapping ~320 lines of ground
    in a context manager would have been a whole-function reindent for an instrument), so an exception
    mid-walk can leave a ledger installed on a POOLED SERVING THREAD. The consequences are bounded to
    nothing: the next turn's `open` throws the stale dict away, so counts never accumulate across turns
    and no memory grows; the only cost of a leak is that a few unrelated borrows increment a dict nobody
    will ever read. `borrow_ledger()` below is the nested-safe context-manager form for every other
    caller (and every test)."""
    led: dict = {"borrows": 0}
    _LEDGER_TL.ledger = led
    return led


def close_borrow_ledger() -> Optional[int]:
    """Uninstall this thread's ledger and return its borrow count (None when none was installed)."""
    led = getattr(_LEDGER_TL, "ledger", None)
    try:
        del _LEDGER_TL.ledger
    except AttributeError:
        pass
    if led is None:
        return None
    return int(led.get("borrows", 0))


@contextlib.contextmanager
def borrow_ledger():
    """Count this block's pool borrows on THIS thread; yields the live counter dict ({'borrows': int}).

    Nested-safe in the direction that matters: the PRIOR ledger is restored in a `finally`, so an inner
    measurement never destroys an outer one -- but borrows inside the inner block are counted by the
    INNER ledger only. That is the right meaning for the two things that measure here (a region of a
    walk, and a test), and it is why `planner.ground` opens ONE ledger per region rather than nesting."""
    prior = getattr(_LEDGER_TL, "ledger", None)
    led = open_borrow_ledger()
    try:
        yield led
    finally:
        if prior is None:
            close_borrow_ledger()
        else:
            _LEDGER_TL.ledger = prior


def current_borrow_ledger() -> Optional[dict]:
    """THE CAPTURE SEAM (the `current_patience_deadline()` twin): read the parent thread's ledger before
    handing work to a pool, so each worker can adopt the SAME dict and its borrows land in the turn's
    own count instead of vanishing."""
    return getattr(_LEDGER_TL, "ledger", None)


@contextlib.contextmanager
def adopt_borrow_ledger(ledger):
    """Install the parent's `ledger` on THIS thread for the block -- the fill/probe workers' seam, and a
    literal copy of `adopt_patience`'s shape.

    NESTED-SAFE the same way: a thread that already carries a ledger KEEPS it, because both pools have a
    SEQUENTIAL branch that runs on the caller's own thread, where installing-and-clearing would strip the
    region's own ledger mid-walk. Fail-open end to end -- an instrument may never raise into a walk."""
    own = False
    try:
        own = ledger is not None and getattr(_LEDGER_TL, "ledger", None) is None
        if own:
            _LEDGER_TL.ledger = ledger
    except Exception:  # noqa: BLE001 — a miscount costs a gate read, never an answer
        own = False
    try:
        yield
    finally:
        if own:
            try:
                del _LEDGER_TL.ledger
            except AttributeError:
                pass
# Server-side per-statement ceiling on POOLED SERVING connections (numbers lookups AND evidence-walk
# fetches — both draw from this pool). A pooled conn should hold its slot only for one execute()+fetch;
# without a server-side kill a pathological query (e.g. a bad plan on a freshly-reloaded, un-ANALYZEd
# mirror table) holds its slot for MINUTES, and because a turn's walk fans out GRAPHRAG_WALK_WORKERS
# fetches while several turns run at once, a couple of wedged holders starve every slot -> the 120s
# checkout wait above trips for everyone and turns floor. Worse, the eval watchdog ORPHANS a wedged
# worker WITHOUT releasing its slot, so the pool monotonically dies and never recovers (the 2026-07-22
# rev-51 gate: silver_wasde reloaded +18% rows -> ~800K, first heavy run of the new row_filters
# `col IN (...)` SQL wedged the pool at ~64min and 18 turns floored / the last 3 ran to the 4200s
# watchdog). Bounding each statement server-side keeps the hold to <=_STMT_TIMEOUT_MS: a numbers lookup
# catches the cancel and falls back to Athena on the SAME SQL (honest); an evidence fetch floors only
# its own turn; and an orphaned worker's query self-cancels so its finally frees the slot. The LOADER
# connects directly (never via _acquire), so a multi-minute bulk COPY stays unbounded. 0 disables.
#
# CEILING CALIBRATION (2026-07-23 floor RCA): the original 60s default CAUSED the very floors it
# guarded against — the fused hybrid retrieval (exact-scan by design, no ANN index, t4g.micro 2 vCPU)
# has a LEGITIMATE >60s tail on heavy multi-node hybrid turns (the walk fans out ~8 concurrent fused
# queries that contend for 2 vCPUs; solo turns still floor), so 19/30 judged rows died in
# fetch_candidates wearing the "model tier unavailable" banner while Sonnet was never even called.
# 300s clears the honest tail with headroom while still killing true wedges (the rev-51 wedge held
# slots for 64+ minutes). Do NOT tighten below the observed heavy-turn retrieval tail without
# measuring it first.
_STMT_TIMEOUT_MS = int(os.environ.get("EVIDENCE_PG_STATEMENT_TIMEOUT_MS", "300000"))


def _acquire():
    global _POOL
    import queue as _q

    import psycopg
    if _POOL is None:
        with _PG_LOCK:
            if _POOL is None:
                p: _q.Queue = _q.Queue()
                for _ in range(max(1, _POOL_SIZE)):
                    p.put(None)                          # lazy slots — connect on first checkout
                _POOL = p
    # EC-2: ONE CALL TO `_acquire` IS ONE BORROW, counted HERE at entry rather than after a successful
    # checkout -- the gate question is "how many times did this walk ask the pool for a connection", and
    # the borrow that WEDGES is the most load-bearing one there is. Counting on success would hide
    # exactly the population EC-0 exists to watch.
    _bump_borrow()
    # EC-3: the SIGNATURE IS UNCHANGED and the deadline is ambient (thread-local), because the borrow
    # sites are hundreds of call sites deep inside the walk -- threading a patience argument through
    # them would be the same edit as threading a lane collector, which the estate already refused once.
    _dl = patience_deadline()
    _rem = None if _dl is None else _dl - time.monotonic()
    if _rem is None or _rem <= _POOL_WAIT_S:
        # THE LEGACY PATH, byte-identical (same single get, same timeout arithmetic, same message, same
        # `from None`): no deadline installed -- every unmetered turn, every eval arm, every loader --
        # or a horizon so nearly spent that one more slice would just be this wait wearing a new name.
        try:
            conn = _POOL.get(timeout=max(1, _POOL_WAIT_S))
        except _q.Empty:
            raise RuntimeError(f"pg pool exhausted: no connection freed in {_POOL_WAIT_S}s "
                               f"(size={_POOL_SIZE}) — leaked slot or wedged holder") from None
    else:
        # THE PATIENT PATH. Slices are JITTERED (0.8-1.2x) so N workers that all queued at the same
        # instant do not re-collide in lockstep every wait, and each slice is CLAMPED to what is left
        # of the turn's horizon so the loop cannot overshoot it. There is NO SLEEP between attempts:
        # `Queue.get(timeout=...)` IS the wait, and a sleep would hand the freed slot to some other
        # thread while this one napped -- latency invented, not spent.
        _t0 = time.monotonic()
        _horizon = max(0.0, _dl - _t0)
        while True:
            _left = _dl - time.monotonic()
            if _left <= 0:
                # PAST THE HORIZON = the same terminal wedge as the legacy path, deliberately the same
                # message SHAPE with the total horizon in the seconds slot: `orchestrator._floor_cause`
                # types it (slug `pg_pool_exhausted`) off the leading phrase, and a second grammar
                # would mean a second thing to match. The turn floors -- and a floored turn carries no
                # walk stamp, so `server._settle_credit` prices it 0 and refunds it.
                raise RuntimeError(f"pg pool exhausted: no connection freed in {int(round(_horizon))}s "
                                   f"(size={_POOL_SIZE}) — leaked slot or wedged holder") from None
            _slice = min(_left, max(1.0, _POOL_WAIT_S * random.uniform(0.8, 1.2)))
            try:
                conn = _POOL.get(timeout=_slice)
                break
            except _q.Empty:
                continue
    if conn is None or conn.closed:
        try:
            kw = {"autocommit": True}
            if _STMT_TIMEOUT_MS > 0:
                # bound EVERY statement server-side via libpq options (atomic with connect, survives the
                # pooled conn's whole lifetime, no extra round-trip) so a wedged query is KILLED instead
                # of holding a pool slot for minutes (the rev-51 pool death). Read at call time so tests
                # and an env override take effect without re-import.
                kw["options"] = f"-c statement_timeout={int(_STMT_TIMEOUT_MS)}"
            conn = psycopg.connect(dsn(), **kw)
        except BaseException:
            _POOL.put(None)      # a failed connect returns the SLOT (lazy) — it must never shrink the pool
            raise
    return conn


def _release(conn) -> None:
    _POOL.put(conn)


def dsn() -> Optional[str]:
    return os.environ.get("EVIDENCE_PG_DSN")


def connect():
    """Module-cached autocommit connection (single-process serving/eval); reconnects if the old one died."""
    global _CONN
    import psycopg
    if _CONN is not None and not _CONN.closed:
        return _CONN
    _CONN = psycopg.connect(dsn(), autocommit=True)
    return _CONN


def init_schema(conn=None, *, dim: int = DIM) -> None:
    """Idempotent DDL for the resolved table (table_name()). `tsv` is a stored generated column ('simple'
    config: no stemming — B40/ZL/CIF stay whole). Indexes: btree(node, date) for the filtered exact scan +
    GIN(tsv) for the lexical leg. No HNSW on purpose.

    Index names are DERIVED from the table name (`<t>_node_date`, `<t>_tsv`) so building the shadow table
    while the live table exists doesn't collide on a shared index name. NB the swap tool renames the TABLE
    only — Postgres keeps indexes attached across a table rename but does NOT rename them, so post-flip the
    indexes carry their pre-flip (shadow-derived) names.

    ⚠ INCIDENT 2026-08-27 — that leftover naming is NOT cosmetic when combined with CREATE INDEX IF NOT
    EXISTS, which is NAME-GLOBAL, not table-scoped: on the SECOND blue-green cycle the fresh shadow's
    derived name (`evidence_props_shadow_node_date`) already existed ATTACHED TO THE LIVE TABLE (a rename
    survivor of cycle one), the create silently NO-OPED, and the swap shipped an index-less table live —
    every per-node read became a full 16 GB seq scan, the eval pool wedged at every size (~$12 of dead
    arm runs), and prod was degraded ~4h until CREATE INDEX CONCURRENTLY repaired it. The ensure below is
    therefore TABLE-SCOPED (pg_indexes on THIS table, matched by shape) with collision-free naming."""
    conn = conn or connect()
    t = table_name()
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {t} (
            id         text PRIMARY KEY,
            node       text NOT NULL,
            source     text,
            source_key text,
            date       text,
            event_date text,
            backend    text,
            text       text NOT NULL,
            meta       jsonb,
            vector     vector({dim}) NOT NULL,
            tsv        tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED
        )""")
    for suffix, frag, tail in _CANONICAL_INDEXES:
        _ensure_index(conn, t, suffix, frag, tail)


# The canonical secondary-index shapes: (name suffix, the indexdef fragment that identifies the
# shape in pg_indexes, the CREATE tail). One list, three consumers: init_schema's ensure, the
# loader's post-load assertion, and the swap tool's parity guard.
_CANONICAL_INDEXES = (
    ("node_date", "(node, date)", "(node, date)"),
    ("tsv", "USING gin (tsv)", "USING gin (tsv)"),
)


def _ensure_index(conn, t: str, suffix: str, frag: str, tail: str) -> None:
    """TABLE-SCOPED index ensure (incident 2026-08-27, see init_schema). Checks THIS table's
    pg_indexes for the shape; when absent, creates under the derived name, suffixing numerically
    if another table (a rename survivor of a prior blue-green cycle) already holds that name."""
    if conn.execute("SELECT 1 FROM pg_indexes WHERE tablename = %s AND indexdef LIKE %s",
                    (t, f"%{frag}%")).fetchone():
        return
    name, n = f"{t}_{suffix}", 1
    while conn.execute("SELECT 1 FROM pg_indexes WHERE indexname = %s", (name,)).fetchone():
        n += 1
        name = f"{t}_{suffix}_{n}"
    conn.execute(f"CREATE INDEX {name} ON {t} {tail}")


def missing_canonical_indexes(table: str, conn=None) -> list:
    """The canonical index shapes ABSENT from `table` — [] is the only healthy answer. The
    loader refuses to finish on a non-empty result (the belt over init_schema's ensure)."""
    conn = conn or connect()
    return [frag for _s, frag, _t in _CANONICAL_INDEXES
            if not conn.execute("SELECT 1 FROM pg_indexes WHERE tablename = %s AND indexdef LIKE %s",
                                (table, f"%{frag}%")).fetchone()]


def prop_id(node: str, rec: dict) -> str:
    """Stable content id — idempotent reloads, and a prop duplicated across slices keeps per-slice rows
    (matching today's slice semantics exactly)."""
    return hashlib.md5(f"{node}|{rec.get('source_key')}|{rec.get('text')}".encode("utf-8")).hexdigest()


def _vec_lit(v) -> str:
    return "[" + ",".join(repr(float(x)) for x in v) + "]"


def _vec_parse(t: str) -> list[float]:
    return [float(x) for x in t.strip("[]").split(",")] if t else []


_CORE = {"source", "source_key", "date", "event_date", "backend", "text", "vector"}


def upsert(node: str, records: list[dict], conn=None, *, batch: int = 500) -> int:
    """Load a slice's records (REUSING their inline vectors). ON CONFLICT updates date/meta so a restamped slice
    reloads cleanly. Returns rows written."""
    conn = conn or connect()
    n = 0
    t = table_name()
    sql = (f"INSERT INTO {t} (id,node,source,source_key,date,event_date,backend,text,meta,vector) "
           "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector) "
           "ON CONFLICT (id) DO UPDATE SET date=EXCLUDED.date, event_date=EXCLUDED.event_date, meta=EXCLUDED.meta")
    with conn.cursor() as cur:
        for i in range(0, len(records), batch):
            rows = []
            for r in records[i:i + batch]:
                meta = {k: v for k, v in r.items() if k not in _CORE}
                rows.append((prop_id(node, r), node, r.get("source"), r.get("source_key"), r.get("date"),
                             r.get("event_date"), r.get("backend"), r.get("text"),
                             json.dumps(meta) if meta else None, _vec_lit(r["vector"])))
            cur.executemany(sql, rows)
            n += len(rows)
    return n


def _tsquery(query: str) -> str:
    """OR the query's tokens ('simple'-config lexemes) — BM25-style recall, not AND-of-everything."""
    from leviathan.graphrag import rankers as rk
    return " | ".join(dict.fromkeys(rk.tokenize(query))) or ""


def needs_vectors(*, rerank: bool, mmr: float) -> bool:
    """The F2 payload gate: does this retrieve() arm actually CONSUME the raw candidate vectors in-process?

    Only two post-fetch steps read `cand[i]["vector"]`: MMR's same-source novelty term (rankers.mmr_select)
    and — by convention, not by need — the rerank arm, which we keep on the vector payload so the fill path
    (rerank=True, mmr=0.5) is provably untouched by F2. Everything else consumes only the ORDER the cosine
    produces, and pgvector can compute that cosine in SQL. Written as a named predicate so the gate is
    directly assertable in a test instead of inferred from a fetch_candidates call."""
    return bool(rerank) or float(mmr) > 0


def fetch_candidates(query_vec, query_text: str, node: str, *, asof: Optional[str], fetch_k: int,
                     hybrid: bool = True, conn=None, with_vectors: bool = True,
                     candidates: Optional[list[dict]] = None) -> list[dict]:
    """ONE round-trip: dense CTE + (optionally) lexical CTE, RRF-fused in SQL (c=60, same as rankers.rrf_fuse).
    Rows come back with their vectors so rerank/MMR run in-process unchanged.

    `with_vectors=False` (F2) swaps the `p.vector::text` payload for the cosine pgvector ALREADY computes for
    the ORDER BY — `1 - (p.vector <=> qv) AS cos_score`. The 24 convergence probes per turn (rerank=False,
    mmr<=0) consumed nothing but the resulting order, while paying 60 x 1024 float4 rendered as text (~700 KB
    on the wire), 60 `_vec_parse` calls and ~122,880 pure-Python mul-adds EACH. The six metadata columns are
    byte-identical on both shapes; the seventh key is `score` (float) instead of `vector` (list[float]) —
    pg_retrieve gates on needs_vectors() and its OWN return shape is unchanged either way. NB pgvector's
    distance accumulates in single precision, so `score` can differ from ev._cosine in ~the 7th significant
    digit; it is the same formula (both divide by the norms) and it is the SAME computation that already
    picked the candidate set in the dense CTE.

    EC-2 `candidates=`: rows ALREADY FETCHED for this node by `fetch_candidates_batch` on the caller's
    thread. Returned VERBATIM (a shallow list copy -- the row dicts are the very objects SQL produced),
    and CRUCIALLY WITHOUT A BORROW: the whole point of the batch is that this node's connection checkout
    already happened, folded into one statement with its slice-mates. `None` (the default, and every
    caller that has not opted in) is the shipped path, byte for byte."""
    if candidates is not None:
        # THE PREFETCHED PATH: no pool, no cursor, no SQL. The copy is shallow on purpose -- the caller's
        # map must not be aliased into a mutable result, but the ROWS must be identical objects or the
        # parity claim would be about a re-serialization rather than about the same fetch.
        return list(candidates)
    pooled = conn is None
    t = table_name()
    qv = _vec_lit(query_vec)
    where = "node = %(node)s" + (" AND date <= %(asof)s" if asof else "")
    params = {"node": node, "asof": asof, "qv": qv, "k": fetch_k, "tsq": _tsquery(query_text) if hybrid else ""}
    # EC-2 TIEBREAK: every ORDER BY in this statement ends in the PRIMARY KEY. RRF ties are real, and a
    # tie under a partial order lets Postgres return either sequence -- which downstream (stable sorts all
    # the way to the prompt) is a different ANSWER, and which would make the batch/single parity pin a
    # measurement of the planner instead of the code. The SAME tiebreak rides fetch_candidates_batch.
    dense = (f"SELECT id, ROW_NUMBER() OVER (ORDER BY vector <=> %(qv)s::vector, id) AS rnk "
             f"FROM {t} WHERE {where} ORDER BY vector <=> %(qv)s::vector, id LIMIT %(k)s")
    # 7th projected column: the whole `meta` jsonb — char_start/char_end/offset_kind ride it to the citation
    # locator (Phase F: the serving read DROPPED them since 6.5, so the deterministic click-to-page leg and
    # the highlight were structurally dark; one column beats three ->> accessors and keeps the two statement
    # shapes symmetric). ~100 bytes/row against the 700 KB/row vector payload — immaterial on the fill arm.
    # 8th: the raw vector (rerank/MMR need it in-process) or the scalar cosine. The alias is
    # NOT `score` — the fused CTE already exposes one, and `ORDER BY f.score` must keep resolving to the CTE's.
    payload = "p.vector::text" if with_vectors else "1 - (p.vector <=> %(qv)s::vector) AS cos_score"
    cols = f"SELECT p.id, p.source, p.source_key, p.date, p.event_date, p.text, p.meta, {payload} "
    if hybrid and params["tsq"]:
        # ...and the lexical leg's LIMIT had NO ORDER BY at all: it took an arbitrary k of however many
        # rows matched the tsquery, relying on the WindowAgg's emission order. `ORDER BY rnk` states the
        # order that was already being assumed, and makes it survive a plan change.
        lex = (f"SELECT id, ROW_NUMBER() OVER (ORDER BY ts_rank(tsv, to_tsquery('simple', %(tsq)s)) DESC, id) "
               f"AS rnk FROM {t} WHERE {where} AND tsv @@ to_tsquery('simple', %(tsq)s) ORDER BY rnk LIMIT %(k)s")
        fused = (f"WITH dense AS ({dense}), lex AS ({lex}), "
                 "fused AS (SELECT COALESCE(d.id, l.id) AS id, "
                 "COALESCE(1.0/(60+d.rnk),0) + COALESCE(1.0/(60+l.rnk),0) AS score "
                 "FROM dense d FULL OUTER JOIN lex l USING (id)) "
                 + cols + f"FROM fused f JOIN {t} p USING (id) ORDER BY f.score DESC, p.id LIMIT %(k)s")
    else:
        fused = (f"WITH dense AS ({dense}) "
                 + cols + f"FROM dense d JOIN {t} p USING (id) ORDER BY d.rnk, p.id LIMIT %(k)s")
    if pooled:                                               # serving path: pooled conns, concurrent fetches
        c = _acquire()
        try:
            with c.cursor() as cur:
                cur.execute(fused, params)
                rows = cur.fetchall()
        finally:
            _release(c)
    else:                                                    # explicit conn (tests/loader): serialized as before
        with _PG_LOCK, conn.cursor() as cur:
            cur.execute(fused, params)
            rows = cur.fetchall()
    return [_project(r, with_vectors) for r in rows]


def _project(r, with_vectors: bool, off: int = 0) -> dict:
    """One row tuple -> the candidate dict. The nine metadata keys are identical on both payload shapes
    (six scalars + the three span keys read off `meta`); the last column is `vector` (list[float]) or
    `score` (float).

    `off` shifts the tuple index because the BATCH statement projects the node as a LEADING column. This
    projection is SHARED by `fetch_candidates` and `fetch_candidates_batch` on purpose: EC-2's parity
    claim is "the batched read returns the same rows", and two hand-written projections are the cheapest
    imaginable way for that claim to become false in a later edit nobody reviews as a parity change.

    Phase F: `meta` (jsonb -> dict, column index off+6) supplies char_start/char_end/offset_kind so the
    citation locator stops shipping nulls; absent keys stay None — the honest legacy shape for pre-offset
    vintages."""
    meta = r[off + 6] or {}
    base = {"id": r[off], "source": r[off + 1], "source_key": r[off + 2], "date": r[off + 3],
            "event_date": r[off + 4], "text": r[off + 5],
            "char_start": meta.get("char_start"), "char_end": meta.get("char_end"),
            "offset_kind": meta.get("offset_kind")}
    if with_vectors:
        return {**base, "vector": _vec_parse(r[off + 7])}
    return {**base, "score": float(r[off + 7])}


# EC-2 CHUNK SIZE -- THE PAYLOAD ARITHMETIC, stated so the number is auditable rather than folkloric.
# The expensive shape is the FILL's (`with_vectors=True`): each node returns up to `fetch_k` rows and each
# row carries `p.vector::text` = 1024 float4 rendered as text. The module docstring's measured figure is
# ~700 KB per 60-row slice (~11-12 bytes per component incl. the separator). One statement therefore costs
# roughly `chunk x 700 KB`:
#     chunk 20 -> ~14 MB     chunk 24 -> ~16.8 MB     chunk 32 -> ~22 MB
# The target is <= ~15-20 MB per statement -- big enough that the borrow count collapses by more than an
# order of magnitude, small enough that one statement's result set cannot become the new memory event on a
# 2-worker container (psycopg materializes `fetchall()`, and up to `_WALK_WORKERS` statements can be in
# flight). 20 is the pick: ~14 MB sits UNDER the band rather than at its edge, and it still turns the
# realistic 60-distinct-slice depth-1 union into 3 statements (vs 329 node borrows) and the 119-slice
# ceiling into 6. The no-vector (probe) shape is ~50x cheaper per row, but ONE constant is kept for both
# because the fill is the population that matters and a second knob would be a second thing to reason about.
#
# AND THE ARITHMETIC ABOVE IS ABOUT THE WIRE, NOT ABOUT LIVE OBJECTS -- the review's correction, recorded
# because the first version of this comment stopped at the wire figure and that read as a residency bound.
# `_vec_parse` turns each 1024-float4 payload into a CPython `list[float]`: ~8 KB of list slots plus 1024
# boxed floats at 24 B = ~33 KB per vector, ~34-42 KB per full row dict. So ONE 20-slice chunk at
# fetch_k=60 is ~14 MB on the wire but ~40 MB of LIVE HEAP, and an accumulated map of every slice a wide
# walk touches would be ~120 MB at 60 slices and ~240 MB at the 119-slice ceiling -- PER CONCURRENT TURN,
# which the gate arm runs 2-4 of in ONE process. `_BATCH_CHUNK` bounds a STATEMENT; it cannot bound a map
# the caller accumulates. THEREFORE THE RESIDENCY CONTRACT LIVES WITH THE CALLER, and `planner._Prefetch`
# is where it is enforced: chunks are pulled ON DEMAND by the fill workers and each slice's rows are
# DROPPED as its last consumer takes them, so live heap tracks the chunks actually in flight (~40 MB, and
# decaying) instead of the whole walk's width. A future caller that materializes the whole map at once
# owes that same arithmetic, and this paragraph is here so it cannot be paid by accident.
_BATCH_CHUNK = 20


def fetch_candidates_batch(query_vec, query_text: str, nodes, *, asof: Optional[str], fetch_k: int,
                           hybrid: bool = True, with_vectors: bool = True, chunk: Optional[int] = None,
                           conn=None) -> dict[str, list[dict]]:
    """EC-2: the SAME per-node fetch, for MANY nodes, in ceil(len(nodes)/chunk) statements and ONE POOL
    BORROW EACH -- the structural fix for a walk that spends hundreds of borrows on one turn.

    RETURNS `{node: [row, ...]}` covering every node whose chunk's statement SUCCEEDED: such a node with
    no matching rows maps to `[]` EXPLICITLY, never to a missing key. The caller distinguishes "fetched,
    nothing there" (`[]`) from "not fetched" (ABSENT) by presence alone, and `planner._fill` relies on
    exactly that to decide whether to pass `candidates=` or to let the node take the legacy per-node path.
    A node is absent only when its chunk raised -- see DEGRADE below.

    THE SHAPE. One `VALUES` list of nodes, `CROSS JOIN LATERAL` the per-node query, node projected as the
    LEADING column and scattered in Python. The inner query is the same dense + (RRF-fused) lexical read
    `fetch_candidates` issues, with `node = q.node` where the single-node form has `node = %(node)s`, and
    the leakage filter `date <= %(asof)s` riding INSIDE the same WHERE on BOTH legs -- PIT safety is
    server-side and per-node here exactly as it is there, which is the property the EC-2 gate pins.
    Written with sub-SELECTs instead of CTEs deliberately: a lateral reference from inside a nested WITH
    is the one construct whose support is version-sensitive, and the sub-SELECT form is the classic
    lateral idiom that has always worked. Semantics are identical (Postgres inlines these CTEs anyway).

    DEGRADE, NEVER FLOOR -- AND DEGRADE AT THE CALLER'S CONCURRENCY. A chunk that raises for ANY reason
    -- a plan the server dislikes, a statement timeout, a psycopg version that mishandles the VALUES list
    -- is caught, and that chunk's nodes are OMITTED FROM THE MAP. They are NOT re-fetched here.
    This is deliberate and it is a correction of the first build: re-fetching them here ran up to `chunk`
    legacy statements STRICTLY SEQUENTIALLY on whatever thread called the batch, while the path they are
    degrading BACK to -- `planner._fill` inside `_parallel_fill` -- issues exactly those statements from
    the fill pool, `EVIDENCE_PG_POOL`-ways concurrent. A fallback that serialized them would not cost
    "what it costs today"; it would cost a serialized version of today, once per chunk, with each borrow
    free to wait `_POOL_WAIT_S` (or the whole EC-3 horizon) on its own. So the ABSENCE of a key means
    exactly one thing -- "the batch did not serve this node" -- and the caller re-fetches it wherever its
    own concurrency lives. `planner._fill`'s omit-when-absent kwarg already does precisely that, and those
    per-node borrows are still counted by the ledger, so a silently-degrading deployment still shows up as
    a borrow count that never fell, rather than as nothing.

    ORDERING is total (see `fetch_candidates`' tiebreak note): every ORDER BY ends in the primary key, so
    the sequence this returns per node is the sequence the single-node statement returns, tie for tie."""
    out: dict[str, list[dict]] = {}
    nodes = list(dict.fromkeys(nodes))                       # dedupe, PRESERVING the caller's order
    if not nodes:
        return out
    size = max(1, int(chunk or _BATCH_CHUNK))
    t = table_name()
    qv = _vec_lit(query_vec)
    tsq = _tsquery(query_text) if hybrid else ""
    for i in range(0, len(nodes), size):
        part = nodes[i:i + size]
        try:
            rows = _batch_rows(t, qv, tsq, part, asof=asof, fetch_k=fetch_k, hybrid=hybrid,
                               with_vectors=with_vectors, conn=conn)
        except Exception:  # noqa: BLE001 — the batch is an optimization; correctness falls back to today
            continue                                         # OMIT: the caller re-fetches these nodes at
            #                                                  ITS OWN concurrency (see DEGRADE above).
        for n in part:
            out[n] = []                                      # EXPLICIT empty for a node SQL returned nothing for
        for r in rows:
            bucket = out.get(r[0])
            if bucket is None:                               # defensive: a node the VALUES list did not carry
                bucket = out[r[0]] = []
            bucket.append(_project(r, with_vectors, off=1))
    return out


def _batch_rows(t: str, qv: str, tsq: str, part: list, *, asof, fetch_k: int, hybrid: bool,
                with_vectors: bool, conn=None) -> list:
    """ONE statement, ONE borrow: the LATERAL set-read for `part`'s nodes. Returns raw tuples whose first
    column is the node. Split out so `fetch_candidates_batch` can wrap exactly this in its per-chunk
    fallback -- and so the chunk that raises has NOT yet written anything into the result map."""
    params: dict = {"asof": asof, "qv": qv, "k": fetch_k, "tsq": tsq}
    vals = []
    for j, n in enumerate(part):
        params[f"n{j}"] = n
        vals.append(f"(%(n{j})s::text)")
    where = "node = q.node" + (" AND date <= %(asof)s" if asof else "")
    dense = (f"SELECT id, ROW_NUMBER() OVER (ORDER BY vector <=> %(qv)s::vector, id) AS rnk "
             f"FROM {t} WHERE {where} ORDER BY vector <=> %(qv)s::vector, id LIMIT %(k)s")
    payload = "p.vector::text" if with_vectors else "1 - (p.vector <=> %(qv)s::vector)"
    cols = f"SELECT p.id, p.source, p.source_key, p.date, p.event_date, p.text, p.meta, {payload} AS payload "
    if hybrid and tsq:
        lex = (f"SELECT id, ROW_NUMBER() OVER (ORDER BY ts_rank(tsv, to_tsquery('simple', %(tsq)s)) DESC, id) "
               f"AS rnk FROM {t} WHERE {where} AND tsv @@ to_tsquery('simple', %(tsq)s) ORDER BY rnk LIMIT %(k)s")
        inner = (cols + f"FROM (SELECT COALESCE(d.id, l.id) AS id, "
                        "COALESCE(1.0/(60+d.rnk),0) + COALESCE(1.0/(60+l.rnk),0) AS score "
                        f"FROM ({dense}) d FULL OUTER JOIN ({lex}) l USING (id)) f "
                        f"JOIN {t} p USING (id) ORDER BY f.score DESC, p.id LIMIT %(k)s")
    else:
        inner = cols + f"FROM ({dense}) d JOIN {t} p USING (id) ORDER BY d.rnk, p.id LIMIT %(k)s"
    sql = ("WITH q(node) AS (VALUES " + ",".join(vals) + ") "
           "SELECT q.node, x.id, x.source, x.source_key, x.date, x.event_date, x.text, x.meta, x.payload "
           f"FROM q CROSS JOIN LATERAL ({inner}) x")
    if conn is None:                                         # serving path: ONE pooled borrow for the chunk
        c = _acquire()
        try:
            with c.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()
        finally:
            _release(c)
    with _PG_LOCK, conn.cursor() as cur:                     # explicit conn (tests/loader/parity harness)
        cur.execute(sql, params)
        return cur.fetchall()


def pg_retrieve(query: str, node: str, *, k: int = 5, asof: str | None = None, near: str | None = None,
                beta: float = 0.25, mode: str = "dense", rerank: bool = False, mmr: float = 0.0,
                same_source: bool = True, fairness: float = 0.30, fetch_k: int = 60,
                embed=None, conn=None, candidates: Optional[list[dict]] = None) -> list[dict]:
    """The pg twin of evidence.retrieve(): same knobs, same output shape, same post-fetch pipeline.
    Candidates come from SQL; proximity/rerank/MMR are computed in-process exactly like the flat path.

    EC-2 `candidates=`: this node's rows, already fetched in a batch statement upstream. Everything after
    the fetch -- the proximity re-score, the rerank pool, MMR -- runs on them UNCHANGED, which is the
    whole design: EC-2 moves WHERE the rows come from, never what happens to them."""
    from leviathan.graphrag import evidence as ev
    from leviathan.graphrag import rankers as rk
    embed = embed or ev.embed
    qv = embed([query])[0]
    with_vec = needs_vectors(rerank=rerank, mmr=mmr)           # F2: no vectors on the probe/no-MMR arms
    if candidates and ("vector" in candidates[0]) != with_vec:
        # PAYLOAD-SHAPE GUARD. The prefetch derives `with_vectors` from the retriever partial's own
        # rerank/mmr, so this cannot fire on the wired path -- but if a future caller ever prefetched the
        # cheap probe shape for a rerank arm, `_dense` would read a `vector` key that is not there and
        # floor the turn. Dropping the mismatched prefetch costs one borrow and keeps the answer.
        candidates = None
    cand = fetch_candidates(qv, query, node, asof=asof, fetch_k=fetch_k, hybrid=(mode == "hybrid"), conn=conn,
                            with_vectors=with_vec, candidates=candidates)
    if not cand:
        if rerank:                                 # this caller WAS counted in the walk's coalescer hint but
            rk.rerank_unexpect()                   # will never score — retract, or the leader waits it out
        return []

    if with_vec:
        def _dense(r):                                        # identical scoring to evidence.retrieve
            return ev._cosine(qv, r["vector"]) + (beta * ev._proximity(r["date"], near) if near else 0.0)
    else:
        def _dense(r):  # noqa: E306
            # Same formula, cosine leg computed in SQL. `near` still works: _proximity reads only r["date"],
            # which the row carries on BOTH shapes — so F2 is NOT gated on `near is None` and stays live on
            # near-dated turns (where it would otherwise have been a silent no-op).
            return r["score"] + (beta * ev._proximity(r["date"], near) if near else 0.0)

    # ONE _dense evaluation per candidate, reused as BOTH the sort key and the relevance value: the old
    # `cand.sort(key=_dense)` + `[_dense(r) for r in cand]` scored every candidate TWICE (2 x 60 x 1024
    # mul-adds per fetch on the vector path). sorted(reverse=True) has the same stability guarantee as
    # list.sort(reverse=True) — equal scores keep fetch order — so the sequence is byte-identical.
    relevance = [_dense(r) for r in cand]
    order = sorted(range(len(cand)), key=lambda i: relevance[i], reverse=True)
    cand, relevance = [cand[i] for i in order], [relevance[i] for i in order]
    if rerank and cand:
        cand = cand[:rk.RERANK_POOL]                          # same pool cap as evidence.retrieve
        relevance = rk.rerank_scores(query, [r["text"] for r in cand])
        order = sorted(range(len(cand)), key=lambda i: relevance[i], reverse=True)
        cand, relevance = [cand[i] for i in order], [relevance[i] for i in order]
    top = (rk.mmr_select(cand, relevance, k, mmr, same_source=same_source, fairness=fairness)
           if (mmr > 0 and len(cand) > k) else cand[:k])
    # D-DV-2: the same additive `score` key evidence._out emits -- the FINAL relevance (post-rerank when a
    # reranker ran, else the fused dense+proximity value), keyed by id() so an mmr_select reorder still
    # pairs each row with its own value. The no-vector SQL shape already carries a raw r["score"]; this
    # overwrites it in the OUTPUT projection only, so both backends hand the planner one meaning.
    rel_by = {id(r): s for r, s in zip(cand, relevance)}
    return [{"date": r["date"], "source": r["source"], "source_key": r["source_key"], "text": r["text"],
             "event_date": r.get("event_date"), "event_date_precision": r.get("event_date_precision"),
             "char_start": r.get("char_start"), "char_end": r.get("char_end"),
             "offset_kind": r.get("offset_kind"),                       # Phase F: ride to the citation locator
             "score": rel_by.get(id(r))}
            for r in top]
