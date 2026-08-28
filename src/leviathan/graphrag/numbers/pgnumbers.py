"""pg-mirrored numbers backend (GRAPHRAG_NUMBERS_BACKEND=pg) — Athena off the serve path.

Athena has a ~2-3s per-query planning floor that no client-side parallelism removes; a hybrid turn's 9
lookups measured 32.5s. The hot serving tables are mirrored into the SAME RDS Postgres that already serves
the evidence store (pgvector), in a schema named IDENTICALLY to the Athena database (`leviathan_dev`) — so
`build_sql()` output is byte-for-byte the same SQL on both backends: the session SQL-keyed cache stays
coherent, the forced-asof leakage guard stays IN the SQL, and per-request fallback re-runs the SAME string
on Athena. S3/Athena remain the source of truth; the mirror is a disposable derived index
(jobs/utils/load_pg_numbers.py rebuilds it any time). Rollback = drop the env flag.

PARITY-CRITICAL detail: Athena's GetQueryResults returns every cell as a STRING; psycopg returns native
types (float/date/Decimal). Downstream (the agent's null filter, json.dumps payloads, silverleg parsing)
was built on the string contract, so cells are stringified here — a pg row is indistinguishable from an
Athena row.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

# The pg schema mirrors the Athena database NAME so build_sql(db=...) output is backend-agnostic.
SCHEMA = "leviathan_dev"


def enabled() -> bool:
    """`GRAPHRAG_NUMBERS_BACKEND=pg` + a DSN present. Default OFF: offline/tests/eval stay byte-identical."""
    return (os.environ.get("GRAPHRAG_NUMBERS_BACKEND", "").strip().lower() == "pg"
            and bool(os.environ.get("EVIDENCE_PG_DSN")))


def _stringify(v):
    if v is None:
        return ""            # Athena's GetQueryResults renders NULL as "" (VarCharValue absent) — match it
    return v if isinstance(v, str) else str(v)


import threading as _threading

_NUM_POOL = None
_NUM_POOL_LOCK = _threading.Lock()
_NUM_POOL_SIZE = int(os.environ.get("NUMBERS_PG_POOL", "4") or 4)
_NUM_POOL_WAIT_S = int(os.environ.get("NUMBERS_PG_POOL_WAIT_S", "5") or 5)
_NUM_STMT_MS = int(os.environ.get("NUMBERS_PG_STATEMENT_TIMEOUT_MS", "5000") or 5000)
_NUM_BORROWS = {"n": 0}   # lane-local ledger (the evidence borrow ledger stays evidence-only)


def _num_acquire():
    """THE BULKHEAD POOL (D-HN companion, 2026-08-28). This lane used to borrow the EVIDENCE pool
    ("same RDS, same DSN, already sized for concurrent walk fetches") -- and the Q-0a smoke measured
    the consequence: evidence scans holding connections for seconds STARVED the ms-cheap numbers
    lookups into 120s wedge failures on 12/14 rows. Numbers queries are point-reads on indexed
    mirrors; they get a small DEDICATED pool so no evidence burst -- or any future evidence
    regression -- can ever starve this lane again. Same DSN, same instance, separate slots."""
    global _NUM_POOL
    import queue as _q
    import psycopg
    from leviathan.graphrag import pgstore
    if _NUM_POOL is None:
        with _NUM_POOL_LOCK:                           # module-own lock (review: never borrow another
            if _NUM_POOL is None:                      # module's lock -- the bulkhead's own thesis)
                p = _q.Queue()
                for _ in range(_NUM_POOL_SIZE):
                    p.put(None)                        # lazy slots, the pgstore idiom
                _NUM_POOL = p
    _NUM_BORROWS["n"] += 1
    try:
        conn = _NUM_POOL.get(timeout=_NUM_POOL_WAIT_S)
    except _q.Empty:
        raise RuntimeError(f"numbers pg pool exhausted: no connection freed in {_NUM_POOL_WAIT_S}s "
                           f"(size={_NUM_POOL_SIZE})")
    if conn is None or conn.closed:
        try:
            # a point read that has not answered in _NUM_STMT_MS should degrade to Athena (the
            # lane's declared patience), never hold a bulkhead slot past the waiters' window
            conn = psycopg.connect(pgstore.dsn(), autocommit=True,
                                   options=f"-c statement_timeout={_NUM_STMT_MS}")
        except BaseException:
            _NUM_POOL.put(None)
            raise
    return conn


def pg_query(sql: str) -> list[dict]:
    """Execute one (build_sql-shaped) statement on the mirror and return Athena-contract rows:
    list[dict[str, str|None]] keyed by the SELECT aliases. Runs on the lane's OWN bulkhead pool
    (see _num_acquire) -- the per-request Athena fallback in `query_fn` below remains this lane's
    patience, so a saturated bulkhead degrades a lookup to Athena's latency, never to an error."""
    conn = _num_acquire()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            names = [d.name for d in cur.description]
            return [{n: _stringify(v) for n, v in zip(names, row)} for row in cur.fetchall()]
    finally:
        _NUM_POOL.put(conn)


def query_fn():
    """A query_fn(sql)->rows for the ACTIVE pg mirror with per-request Athena fallback on the SAME SQL —
    a mirror gap/outage degrades a lookup to Athena's latency, never to an error (and every fallback is
    logged: the Jul-5 once-only-warning lesson)."""
    from leviathan.graphrag.numbers import query as Q
    athena = None

    def fn(sql: str) -> list[dict]:
        nonlocal athena
        try:
            return pg_query(sql)
        except Exception as e:  # noqa: BLE001 — never break a lookup on a mirror problem
            log.warning("pg numbers failed (%s: %s); falling back to Athena for this query",
                        type(e).__name__, str(e)[:160])
            if athena is None:
                athena = Q.athena_query_fn()
            return athena(sql)
    return fn
