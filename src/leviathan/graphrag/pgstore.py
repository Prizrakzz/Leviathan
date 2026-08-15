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
# lock-serialized connection made that ~8.5s of the walk. A few pooled autocommit connections un-serialize it
# (RDS t4g.micro handles this comfortably). Callers that pass an explicit `conn` (tests, the loader) keep the
# old single-connection + lock path.
_POOL = None
_POOL_SIZE = int(os.environ.get("EVIDENCE_PG_POOL", "4"))
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
    indexes carry their pre-flip (shadow-derived) names. That's cosmetic: they stay attached and functional,
    and the next rebuild's CREATE INDEX IF NOT EXISTS is keyed on the (new) table's own derived names."""
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
    conn.execute(f"CREATE INDEX IF NOT EXISTS {t}_node_date ON {t} (node, date)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS {t}_tsv ON {t} USING gin (tsv)")


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
                     hybrid: bool = True, conn=None, with_vectors: bool = True) -> list[dict]:
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
    picked the candidate set in the dense CTE."""
    pooled = conn is None
    t = table_name()
    qv = _vec_lit(query_vec)
    where = "node = %(node)s" + (" AND date <= %(asof)s" if asof else "")
    params = {"node": node, "asof": asof, "qv": qv, "k": fetch_k, "tsq": _tsquery(query_text) if hybrid else ""}
    dense = (f"SELECT id, ROW_NUMBER() OVER (ORDER BY vector <=> %(qv)s::vector) AS rnk "
             f"FROM {t} WHERE {where} ORDER BY vector <=> %(qv)s::vector LIMIT %(k)s")
    # 7th projected column: the raw vector (rerank/MMR need it in-process) or the scalar cosine. The alias is
    # NOT `score` — the fused CTE already exposes one, and `ORDER BY f.score` must keep resolving to the CTE's.
    payload = "p.vector::text" if with_vectors else "1 - (p.vector <=> %(qv)s::vector) AS cos_score"
    cols = f"SELECT p.id, p.source, p.source_key, p.date, p.event_date, p.text, {payload} "
    if hybrid and params["tsq"]:
        lex = (f"SELECT id, ROW_NUMBER() OVER (ORDER BY ts_rank(tsv, to_tsquery('simple', %(tsq)s)) DESC) AS rnk "
               f"FROM {t} WHERE {where} AND tsv @@ to_tsquery('simple', %(tsq)s) LIMIT %(k)s")
        fused = (f"WITH dense AS ({dense}), lex AS ({lex}), "
                 "fused AS (SELECT COALESCE(d.id, l.id) AS id, "
                 "COALESCE(1.0/(60+d.rnk),0) + COALESCE(1.0/(60+l.rnk),0) AS score "
                 "FROM dense d FULL OUTER JOIN lex l USING (id)) "
                 + cols + f"FROM fused f JOIN {t} p USING (id) ORDER BY f.score DESC LIMIT %(k)s")
    else:
        fused = (f"WITH dense AS ({dense}) "
                 + cols + f"FROM dense d JOIN {t} p USING (id) ORDER BY d.rnk LIMIT %(k)s")
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
    if with_vectors:                                         # the six metadata keys are identical either way
        return [{"id": r[0], "source": r[1], "source_key": r[2], "date": r[3], "event_date": r[4],
                 "text": r[5], "vector": _vec_parse(r[6])} for r in rows]
    return [{"id": r[0], "source": r[1], "source_key": r[2], "date": r[3], "event_date": r[4],
             "text": r[5], "score": float(r[6])} for r in rows]


def pg_retrieve(query: str, node: str, *, k: int = 5, asof: str | None = None, near: str | None = None,
                beta: float = 0.25, mode: str = "dense", rerank: bool = False, mmr: float = 0.0,
                same_source: bool = True, fairness: float = 0.30, fetch_k: int = 60,
                embed=None, conn=None) -> list[dict]:
    """The pg twin of evidence.retrieve(): same knobs, same output shape, same post-fetch pipeline.
    Candidates come from SQL; proximity/rerank/MMR are computed in-process exactly like the flat path."""
    from leviathan.graphrag import evidence as ev
    from leviathan.graphrag import rankers as rk
    embed = embed or ev.embed
    qv = embed([query])[0]
    with_vec = needs_vectors(rerank=rerank, mmr=mmr)           # F2: no vectors on the probe/no-MMR arms
    cand = fetch_candidates(qv, query, node, asof=asof, fetch_k=fetch_k, hybrid=(mode == "hybrid"), conn=conn,
                            with_vectors=with_vec)
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
             "score": rel_by.get(id(r))}
            for r in top]
