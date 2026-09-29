"""ONE-OFF, NAMED administrative actions on the serving Postgres -- run by the OWNER, never on a schedule.

The pg audit of 2026-09-29 (jobs/utils/pg_audit.py) found two things only a write can fix. This file holds
exactly those two actions, each behind its own name and its own pre-checks. There is no free SQL here: an
action is chosen by name, and nothing else can be run through this file.

* ``create-pg-stat-statements`` -- ``CREATE EXTENSION IF NOT EXISTS pg_stat_statements``. The library is
  already preloaded on the instance; the extension was never created in the database, so no statement census
  has ever existed. Additive, no restart.
* ``drop-evidence-props-old`` -- drops the evidence table's RETAINED ROLLBACK ARTIFACT (``<live>_old``, see
  jobs/utils/pg_evidence_swap.py). NOTE: the next blue-green swap drops and replaces that artifact by itself
  (its first statement); this action exists only to free the space sooner. It refuses unless the artifact is
  NOT the live table, the live table exists with at least as many rows, and the live table carries a vector
  index -- and unless ``--confirm`` names the artifact exactly.

RDS is reachable only in-VPC: submit through jobs/submit/submit_batch_pg_admin.py.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

ACTIONS = ("create-pg-stat-statements", "drop-evidence-props-old")
CONNECT_OPTIONS = "-c statement_timeout=120000 -c lock_timeout=5000"
_NAME_RX = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def live_table() -> str:
    """The evidence table serving reads (the same env the store reads), validated as a bare identifier."""
    name = (os.environ.get("EVIDENCE_PG_TABLE") or "evidence_props").strip()
    if not _NAME_RX.match(name):
        raise SystemExit(f"refusing: live table name {name!r} is not a bare identifier")
    return name


def old_table() -> str:
    return live_table() + "_old"


def say(section: str, payload) -> None:
    print(f"PG_ADMIN {section} {json.dumps(payload, default=str)}")


def _one(conn, sql: str, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def create_pg_stat_statements(conn) -> int:
    before = _one(conn, "SELECT extversion FROM pg_extension WHERE extname = 'pg_stat_statements'")
    say("before", {"extension": "pg_stat_statements", "version": before[0] if before else None})
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
    after = _one(conn, "SELECT extversion FROM pg_extension WHERE extname = 'pg_stat_statements'")
    n = _one(conn, "SELECT count(*) FROM pg_stat_statements")
    say("after", {"extension": "pg_stat_statements", "version": after[0] if after else None,
                  "statements_visible": n[0] if n else None})
    return 0 if after else 1


def drop_refusal(facts: dict, confirm: str) -> str:
    """The reason the drop is refused, or '' when every pre-check holds. Pure: the facts are read by the caller."""
    if confirm != facts["old"]:
        return f"--confirm must name the artifact exactly: {facts['old']}"
    if facts["old"] == facts["live"]:
        return "the artifact IS the live table"
    if not facts["old_exists"]:
        return f"{facts['old']} does not exist (nothing to drop)"
    if not facts["live_exists"]:
        return f"the live table {facts['live']} does not exist"
    if int(facts["live_rows"]) < int(facts["old_rows"]):
        return (f"the live table holds fewer rows than the artifact "
                f"({facts['live_rows']} < {facts['old_rows']}): the artifact may be the better copy")
    if int(facts["live_vector_indexes"]) < 1:
        return "the live table carries no vector index: the artifact may be needed for a rollback"
    if int(facts["dependents"]) > 0:
        return f"{facts['dependents']} object(s) depend on the artifact"
    return ""


def drop_evidence_props_old(conn, confirm: str) -> int:
    live, old = live_table(), old_table()
    ex = lambda t: bool(_one(conn, "SELECT 1 FROM pg_tables WHERE tablename = %s", (t,)))  # noqa: E731
    facts = {"live": live, "old": old, "live_exists": ex(live), "old_exists": ex(old),
             "live_rows": 0, "old_rows": 0, "live_vector_indexes": 0, "dependents": 0, "old_bytes": 0}
    if facts["live_exists"]:
        facts["live_rows"] = _one(conn, f"SELECT count(*) FROM {live}")[0]
        facts["live_vector_indexes"] = _one(
            conn, "SELECT count(*) FROM pg_indexes WHERE tablename = %s AND indexdef LIKE %s",
            (live, "%USING hnsw%"))[0]
    if facts["old_exists"]:
        facts["old_rows"] = _one(conn, f"SELECT count(*) FROM {old}")[0]
        facts["old_bytes"] = _one(conn, "SELECT pg_total_relation_size(%s::regclass)", (old,))[0]
        facts["dependents"] = _one(
            conn, "SELECT count(*) FROM pg_depend d JOIN pg_class c ON c.oid = d.refobjid "
                  "JOIN pg_rewrite r ON r.oid = d.objid JOIN pg_class v ON v.oid = r.ev_class "
                  "WHERE c.relname = %s AND v.relname <> %s", (old, old))[0]
    say("facts", facts)
    why = drop_refusal(facts, confirm)
    if why:
        say("refused", {"why": why})
        return 2
    before = _one(conn, "SELECT pg_database_size(current_database())")[0]
    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE {old}")
    after = _one(conn, "SELECT pg_database_size(current_database())")[0]
    say("dropped", {"table": old, "database_bytes_before": before, "database_bytes_after": after,
                    "freed_bytes": before - after})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="One-off named administrative actions on the serving Postgres.")
    ap.add_argument("--action", required=True, choices=ACTIONS)
    ap.add_argument("--confirm", default="", help="drop-evidence-props-old: the artifact's exact name")
    ap.add_argument("--dry-run", action="store_true", help="name the action and connect to nothing")
    args = ap.parse_args(argv)
    if args.dry_run:
        say("dry_run", {"action": args.action, "live": live_table(), "old": old_table()})
        return 0
    dsn = os.environ.get("EVIDENCE_PG_DSN")
    if not dsn:
        raise SystemExit("EVIDENCE_PG_DSN not set (run in-VPC via jobs/submit/submit_batch_pg_admin.py)")
    import psycopg
    with psycopg.connect(dsn, autocommit=True, options=CONNECT_OPTIONS) as conn:
        if args.action == "create-pg-stat-statements":
            return create_pg_stat_statements(conn)
        return drop_evidence_props_old(conn, args.confirm)


if __name__ == "__main__":
    sys.exit(main())
