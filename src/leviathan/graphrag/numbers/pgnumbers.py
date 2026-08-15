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


def pg_query(sql: str) -> list[dict]:
    """Execute one (build_sql-shaped) statement on the mirror and return Athena-contract rows:
    list[dict[str, str|None]] keyed by the SELECT aliases. Reuses the evidence store's connection pool —
    same RDS, same DSN, already sized for concurrent walk fetches.

    EC-3 EXEMPTION, ENFORCED (2026-08-15). The borrow runs inside `pgstore.without_patience()`: this
    lane keeps the LEGACY fast-fail wait (`_POOL_WAIT_S`) even on a metered turn, because the per-request
    Athena fallback in `query_fn` below IS this lane's patience — waiting out a 300s pool horizon here
    would trade a fast honest degrade for a slow one. It must be SAID, not assumed: the patience deadline
    is ambient (a thread-local `_acquire` reads), and the cascade-quantify legs call this on the WALK's
    own thread inside the orchestrator's horizon, so without the suspend this lane silently inherited it.
    Suspend, not disable — the deadline is restored immediately after the borrow, so the walk's remaining
    borrows keep the turn's bound and the time spent here still counts against it."""
    from leviathan.graphrag import pgstore
    with pgstore.without_patience():
        conn = pgstore._acquire()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            names = [d.name for d in cur.description]
            return [{n: _stringify(v) for n, v in zip(names, row)} for row in cur.fetchall()]
    finally:
        pgstore._release(conn)


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
