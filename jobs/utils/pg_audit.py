"""READ-ONLY audit of the serving Postgres (owner word 2026-09-29: "pg audit").

The instance has been upgraded three times for one user and never audited: no index-usage read, no statement
census, no plan check, the default parameter group. This job reads the catalog and the statistics views and
prints what it finds. It changes NOTHING:

* the connection is opened with ``default_transaction_read_only=on`` and a statement timeout, so a write is
  refused by the server, not by this file's good intentions;
* every statement in :data:`SECTIONS` is a single SELECT over a catalog or statistics view;
* plans are read with ``EXPLAIN (GENERIC_PLAN)`` -- PostgreSQL 16+ plans a parameterised statement WITHOUT
  executing it -- and only for statements whose own first keyword is SELECT or WITH.

RDS is reachable only in-VPC, so this runs as a Batch job (jobs/submit/submit_batch_pg_audit.py) on the
evidence-build job definition, whose execution role injects ``EVIDENCE_PG_DSN``. The report is printed to the
job's log, one ``PG_AUDIT <section> <json>`` line per chunk (a CloudWatch event holds 256 KB).

    python jobs/utils/pg_audit.py --dry-run          # list the sections, connect to nothing
    python jobs/utils/pg_audit.py --top 40           # in-VPC: the audit
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Iterable

#: The server-side guard. A write inside this session is an ERROR raised by Postgres.
CONNECT_OPTIONS = "-c default_transaction_read_only=on -c statement_timeout=60000 -c lock_timeout=2000"

#: The planner / memory settings the audit reports (the instance runs the DEFAULT parameter group).
SETTINGS = ("shared_buffers", "effective_cache_size", "work_mem", "maintenance_work_mem", "random_page_cost",
            "seq_page_cost", "effective_io_concurrency", "max_connections", "max_parallel_workers_per_gather",
            "max_parallel_workers", "max_worker_processes", "jit", "default_statistics_target",
            "autovacuum", "autovacuum_vacuum_scale_factor", "autovacuum_analyze_scale_factor",
            "hnsw.ef_search", "hnsw.iterative_scan", "hnsw.max_scan_tuples", "shared_preload_libraries",
            "track_io_timing", "statement_timeout", "idle_in_transaction_session_timeout")

#: name -> (sql, params). One SELECT each; catalog and statistics views only.
SECTIONS: dict[str, tuple[str, tuple]] = {
    "server": (
        "SELECT version() AS version, current_database() AS database, "
        "pg_database_size(current_database()) AS database_bytes, "
        "(SELECT stats_reset FROM pg_stat_database WHERE datname = current_database()) AS stats_reset",
        ()),
    "settings": (
        "SELECT name, setting, unit, source FROM pg_settings WHERE name = ANY(%s) ORDER BY name",
        (list(SETTINGS),)),
    "connections": (
        "SELECT coalesce(state, 'background') AS state, count(*) AS n, "
        "max(extract(epoch FROM (now() - state_change)))::int AS oldest_state_s "
        "FROM pg_stat_activity WHERE datname = current_database() GROUP BY 1 ORDER BY 2 DESC",
        ()),
    "tables": (
        "SELECT schemaname, relname, n_live_tup, n_dead_tup, seq_scan, seq_tup_read, idx_scan, "
        "idx_tup_fetch, n_tup_ins, n_tup_upd, n_tup_del, last_analyze, last_autoanalyze, last_vacuum, "
        "last_autovacuum, pg_total_relation_size(relid) AS total_bytes, pg_relation_size(relid) AS heap_bytes "
        "FROM pg_stat_user_tables ORDER BY pg_total_relation_size(relid) DESC LIMIT 300",
        ()),
    "indexes": (
        "SELECT s.schemaname, s.relname, s.indexrelname, s.idx_scan, s.idx_tup_read, s.idx_tup_fetch, "
        "pg_relation_size(s.indexrelid) AS index_bytes, i.indexdef "
        "FROM pg_stat_user_indexes s JOIN pg_indexes i "
        "ON i.schemaname = s.schemaname AND i.indexname = s.indexrelname "
        "ORDER BY pg_relation_size(s.indexrelid) DESC LIMIT 800",
        ()),
    "indexes_not_valid": (
        "SELECT c.relname AS index_name, t.relname AS table_name, x.indisvalid, x.indisready "
        "FROM pg_index x JOIN pg_class c ON c.oid = x.indexrelid JOIN pg_class t ON t.oid = x.indrelid "
        "WHERE NOT x.indisvalid OR NOT x.indisready",
        ()),
    "indexes_same_columns": (
        "SELECT x.indrelid::regclass::text AS table_name, x.indkey::text AS column_numbers, "
        "array_agg(x.indexrelid::regclass::text ORDER BY x.indexrelid) AS index_names, count(*) AS n "
        "FROM pg_index x JOIN pg_class t ON t.oid = x.indrelid JOIN pg_namespace n ON n.oid = t.relnamespace "
        "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast') "
        "GROUP BY x.indrelid, x.indkey, x.indclass, x.indpred, x.indexprs HAVING count(*) > 1",
        ()),
    "io_by_table": (
        "SELECT schemaname, relname, heap_blks_read, heap_blks_hit, idx_blks_read, idx_blks_hit "
        "FROM pg_statio_user_tables ORDER BY heap_blks_read + idx_blks_read DESC LIMIT 60",
        ()),
}

#: The statement census. pg_stat_statements is preloaded on this instance; the view exists only where the
#: extension was created in the database, so its absence is a finding the audit reports, never an error.
STATEMENTS_SQL = (
    "SELECT queryid::text AS queryid, calls, total_exec_time, mean_exec_time, max_exec_time, "
    "stddev_exec_time, rows, shared_blks_hit, shared_blks_read, temp_blks_written, "
    "left(query, 6000) AS query FROM pg_stat_statements "
    "WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database()) "
    "AND calls >= %s ORDER BY {order} DESC LIMIT %s")
STATEMENT_ORDERS = ("total_exec_time", "mean_exec_time")

#: A statement is planned only when its OWN first keyword is one of these (never a COPY, a utility, a write).
PLANNABLE_FIRST_WORDS = ("select", "with")
CHUNK_BYTES = 180_000


def first_word(sql: str) -> str:
    """The statement's first keyword, lowercased, leading whitespace and '(' skipped."""
    s = (sql or "").lstrip().lstrip("(").lstrip()
    word = ""
    for ch in s:
        if ch.isalpha() or ch == "_":
            word += ch
        else:
            break
    return word.lower()


def plannable(sql: str) -> bool:
    """True when the statement may be handed to EXPLAIN (GENERIC_PLAN): one statement, a SELECT or a WITH."""
    body = (sql or "").strip().rstrip(";")
    return first_word(body) in PLANNABLE_FIRST_WORDS and ";" not in body


def explain_sql(sql: str) -> str:
    """The plan read: GENERIC_PLAN plans a parameterised statement without executing it (PostgreSQL 16+)."""
    return "EXPLAIN (GENERIC_PLAN, FORMAT JSON) " + (sql or "").strip().rstrip(";")


def emit(section: str, rows: Iterable[Any], out=sys.stdout) -> int:
    """Print ``PG_AUDIT <section> <json>`` lines, chunked under the log event ceiling. Returns the row count."""
    batch: list = []
    size = n = 0
    for row in rows:
        text = json.dumps(row, default=str)
        if batch and size + len(text) > CHUNK_BYTES:
            print(f"PG_AUDIT {section} {json.dumps(batch, default=str)}", file=out)
            batch, size = [], 0
        batch.append(row)
        size += len(text)
        n += 1
    print(f"PG_AUDIT {section} {json.dumps(batch, default=str)}", file=out)
    return n


def _rows(cur) -> list[dict]:
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def run(conn, *, top: int = 40, min_calls: int = 3, out=sys.stdout) -> dict:
    """Run every section on an open READ-ONLY connection. Returns {section: row count | 'absent: <why>'}."""
    done: dict = {}
    for name, (sql, params) in SECTIONS.items():
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                done[name] = emit(name, _rows(cur), out)
        except Exception as e:  # noqa: BLE001 -- one section's failure is a finding, never the audit's end
            done[name] = f"absent: {type(e).__name__}: {str(e)[:200]}"
            emit(name + "_absent", [{"why": done[name]}], out)
    seen: dict[str, str] = {}
    for order in STATEMENT_ORDERS:
        key = "statements_by_" + order
        try:
            with conn.cursor() as cur:
                cur.execute(STATEMENTS_SQL.format(order=order), (min_calls, top))
                rows = _rows(cur)
            done[key] = emit(key, rows, out)
            for r in rows:
                seen.setdefault(str(r["queryid"]), str(r["query"]))
        except Exception as e:  # noqa: BLE001
            done[key] = f"absent: {type(e).__name__}: {str(e)[:200]}"
            emit(key + "_absent", [{"why": done[key]}], out)
    plans = []
    for qid, sql in seen.items():
        if not plannable(sql):
            plans.append({"queryid": qid, "planned": False, "why": "first word " + repr(first_word(sql))})
            continue
        try:
            with conn.cursor() as cur:
                cur.execute(explain_sql(sql))
                plans.append({"queryid": qid, "planned": True, "plan": cur.fetchall()[0][0]})
        except Exception as e:  # noqa: BLE001 -- a truncated or utility-shaped text does not plan; say so
            plans.append({"queryid": qid, "planned": False, "why": f"{type(e).__name__}: {str(e)[:200]}"})
    done["generic_plans"] = emit("generic_plans", plans, out)
    emit("summary", [done], out)
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only audit of the serving Postgres (catalog + statistics).")
    ap.add_argument("--top", type=int, default=40, help="statements per ordering")
    ap.add_argument("--min-calls", type=int, default=3, help="ignore statements called fewer times")
    ap.add_argument("--dry-run", action="store_true", help="list the sections and connect to nothing")
    args = ap.parse_args(argv)
    if args.dry_run:
        emit("sections", [{"sections": sorted(SECTIONS), "statement_orders": list(STATEMENT_ORDERS),
                           "connect_options": CONNECT_OPTIONS}])
        return 0
    dsn = os.environ.get("EVIDENCE_PG_DSN")
    if not dsn:
        raise SystemExit("EVIDENCE_PG_DSN not set (run in-VPC via jobs/submit/submit_batch_pg_audit.py)")
    import psycopg
    with psycopg.connect(dsn, autocommit=True, options=CONNECT_OPTIONS) as conn:
        run(conn, top=args.top, min_calls=args.min_calls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
