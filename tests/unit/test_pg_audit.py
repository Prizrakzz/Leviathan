"""The pg audit is READ-ONLY BY CONSTRUCTION (owner word 2026-09-29: "pg audit").

The job runs against the serving database. These pins hold the three things that make that safe: the server
refuses a write on the session, every section is one SELECT over a catalog or statistics view, and a plan is
read without executing the statement and only for a statement that is itself a read."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from jobs.utils import pg_audit as A  # noqa: E402

#: The verbs a statement may not START with, and may not carry as a second statement.
WRITE_VERBS = {"insert", "update", "delete", "merge", "truncate", "drop", "create", "alter", "grant", "revoke",
               "copy", "vacuum", "analyze", "reindex", "cluster", "refresh", "call", "do", "set", "reset",
               "lock", "comment", "security", "import"}


def test_the_session_is_read_only_at_the_server_and_carries_a_statement_timeout():
    assert "default_transaction_read_only=on" in A.CONNECT_OPTIONS
    assert "statement_timeout=" in A.CONNECT_OPTIONS
    assert "lock_timeout=" in A.CONNECT_OPTIONS


def test_every_section_is_one_select():
    assert A.SECTIONS, "the audit has sections"
    for name, (sql, _params) in A.SECTIONS.items():
        assert A.first_word(sql) == "select", name
        assert ";" not in sql, name
        assert A.first_word(sql) not in WRITE_VERBS, name


def test_the_statement_census_is_a_select_over_the_statistics_view():
    for order in A.STATEMENT_ORDERS:
        sql = A.STATEMENTS_SQL.format(order=order)
        assert A.first_word(sql) == "select" and ";" not in sql
        assert "pg_stat_statements" in sql
        assert order in ("total_exec_time", "mean_exec_time")


def test_a_plan_is_read_without_executing_and_only_for_a_read():
    assert A.explain_sql("SELECT 1").startswith("EXPLAIN (GENERIC_PLAN, FORMAT JSON) SELECT 1")
    assert "ANALYZE" not in A.explain_sql("SELECT 1").upper().split("SELECT")[0]
    assert A.plannable("SELECT a FROM t WHERE b = $1")
    assert A.plannable("  WITH x AS (SELECT 1) SELECT * FROM x")
    assert A.plannable("(SELECT 1) UNION ALL (SELECT 2)")
    for sql in ('COPY "s"."t" ("a") FROM STDIN', "INSERT INTO t VALUES (1)", "UPDATE t SET a = 1",
                "DELETE FROM t", "CREATE INDEX i ON t (a)", "ANALYZE t", "SET work_mem = 1",
                "SELECT 1; DROP TABLE t", ""):
        assert not A.plannable(sql), sql


class _Cur:
    def __init__(self, log, fail_on=()):
        self.log, self.fail_on, self.description, self._rows = log, fail_on, [], []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        self.log.append(sql)
        if any(f in sql for f in self.fail_on):
            raise RuntimeError("relation does not exist")
        if sql.startswith("EXPLAIN"):
            self._rows = [([{"Plan": {"Node Type": "Index Scan"}}],)]
            return
        if "pg_stat_statements" in sql:
            self.description = [type("D", (), {"name": n}) for n in ("queryid", "query")]
            self._rows = [("1", "SELECT v FROM t WHERE k = $1"), ("2", 'COPY "s"."t" ("a") FROM STDIN')]
            return
        self.description = [type("D", (), {"name": "n"})]
        self._rows = [(1,)]

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, fail_on=()):
        self.log, self.fail_on = [], fail_on

    def cursor(self):
        return _Cur(self.log, self.fail_on)


def test_run_issues_only_reads_and_plans_only_the_read_statement():
    conn, out = _Conn(), io.StringIO()
    done = A.run(conn, top=5, min_calls=1, out=out)
    assert conn.log, "statements were issued"
    for sql in conn.log:
        assert A.first_word(sql) in ("select", "explain"), sql
    explains = [s for s in conn.log if s.startswith("EXPLAIN")]
    assert explains == ["EXPLAIN (GENERIC_PLAN, FORMAT JSON) SELECT v FROM t WHERE k = $1"]
    lines = [ln for ln in out.getvalue().splitlines() if ln.startswith("PG_AUDIT generic_plans ")]
    plans = json.loads(lines[0].split(" ", 2)[2])
    assert [p["planned"] for p in plans] == [True, False]
    assert set(A.SECTIONS) <= set(done)


def test_an_absent_statistics_view_is_a_finding_and_the_audit_continues():
    conn, out = _Conn(fail_on=("pg_stat_statements",)), io.StringIO()
    done = A.run(conn, top=5, min_calls=1, out=out)
    assert str(done["statements_by_total_exec_time"]).startswith("absent:")
    assert done["generic_plans"] == 0
    assert isinstance(done["tables"], int)


def test_the_report_lines_stay_under_the_log_event_ceiling():
    out = io.StringIO()
    n = A.emit("big", [{"q": "x" * 50_000} for _ in range(12)], out)
    assert n == 12
    lines = out.getvalue().splitlines()
    assert len(lines) > 1 and all(len(ln) < 256_000 for ln in lines)
    got = [r for ln in lines for r in json.loads(ln.split(" ", 2)[2])]
    assert len(got) == 12
