"""Unit tests for the P2 W0.3 pg evidence-mirror shadow capability — table resolver + blue-green swap.

All PURE (no Postgres): the table-name resolver is env-only, the swap/rollback SQL is string generation, and
the guard + transaction boundaries are exercised against a tiny fake connection that records every statement.
This mirrors test_pgstore.py's "pure (no DB)" section — the DB-touching integration tests there already cover
the real round-trips; what's new here is the shadow plumbing, which must be verifiable without a container.

The table name is interpolated straight into SQL (there is no bind-param form for an identifier), so the
injection-barrier is the lower-snake regex in pgstore.table_name(): its rejection path is tested explicitly.
Fixtures are synthetic — no private config or slice content appears here.
"""
from __future__ import annotations

import pytest

from jobs.utils import pg_evidence_swap as swap
from leviathan.graphrag import pgstore as pg


# ── table-name resolver (pgstore.table_name) ─────────────────────────────────────────────────
def test_table_name_default_when_unset(monkeypatch):
    monkeypatch.delenv("EVIDENCE_PG_TABLE", raising=False)
    assert pg.table_name() == "evidence_props"


def test_table_name_env_override(monkeypatch):
    monkeypatch.setenv("EVIDENCE_PG_TABLE", "evidence_props_shadow")
    assert pg.table_name() == "evidence_props_shadow"


def test_table_name_resolved_at_call_time_not_import(monkeypatch):
    # The resolver reads the env on EVERY call, so a monkeypatch mid-test flips it — this is the property
    # that lets the loader/swap-tool set EVIDENCE_PG_TABLE in a subprocess and have pgstore honor it.
    monkeypatch.setenv("EVIDENCE_PG_TABLE", "evidence_props")
    assert pg.table_name() == "evidence_props"
    monkeypatch.setenv("EVIDENCE_PG_TABLE", "evidence_props_shadow")
    assert pg.table_name() == "evidence_props_shadow"


def test_table_name_strips_whitespace(monkeypatch):
    monkeypatch.setenv("EVIDENCE_PG_TABLE", "  evidence_props_shadow  ")
    assert pg.table_name() == "evidence_props_shadow"


@pytest.mark.parametrize("bad", [
    "evidence-props",            # hyphen
    "evidence props",           # space
    "Evidence_Props",           # uppercase
    "evidence_props; DROP TABLE x",  # injection attempt
    "1evidence",                # leading digit
    "evidence.props",           # schema-qualified / dot
    'evidence"props',           # embedded quote
    "   ",                       # whitespace-only -> strips to empty, then fails the regex
])
def test_table_name_rejects_invalid(monkeypatch, bad):
    monkeypatch.setenv("EVIDENCE_PG_TABLE", bad)
    with pytest.raises(ValueError):
        pg.table_name()


def test_table_name_empty_env_falls_back_to_default(monkeypatch):
    # An accidentally-empty EVIDENCE_PG_TABLE must not crash serving — it resolves to the safe default,
    # never reaching the regex (falsy `or` fallback).
    monkeypatch.setenv("EVIDENCE_PG_TABLE", "")
    assert pg.table_name() == "evidence_props"


# ── generated SQL references the configured table (string-level, no DB) ──────────────────────
def _fetch_sql(monkeypatch, table):
    """Return the fused SQL string fetch_candidates would run, by capturing the cursor.execute() call on a
    fake explicit connection (the non-pooled branch — no _acquire, no real DB)."""
    monkeypatch.setenv("EVIDENCE_PG_TABLE", table)
    captured = {}

    class _Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params):
            captured["sql"] = sql

        def fetchall(self):
            return []

    class _Conn:
        def cursor(self):
            return _Cur()

    pg.fetch_candidates([0.0, 0.0], "q", "coffee", asof=None, fetch_k=5, hybrid=False, conn=_Conn())
    return captured["sql"]


def test_fetch_candidates_sql_uses_configured_table(monkeypatch):
    sql = _fetch_sql(monkeypatch, "evidence_props_shadow")
    assert "FROM evidence_props_shadow" in sql
    assert "FROM evidence_props " not in sql and "JOIN evidence_props " not in sql  # no bare default leak


def test_fetch_candidates_sql_default_table(monkeypatch):
    monkeypatch.delenv("EVIDENCE_PG_TABLE", raising=False)
    sql = _fetch_sql(monkeypatch, "evidence_props")
    assert "FROM evidence_props" in sql


def test_upsert_sql_uses_configured_table(monkeypatch):
    """upsert's INSERT targets the resolved table — captured off a fake conn (no executemany runs)."""
    monkeypatch.setenv("EVIDENCE_PG_TABLE", "evidence_props_shadow")
    captured = {}

    class _Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def executemany(self, sql, rows):
            captured["sql"] = sql

    class _Conn:
        def cursor(self):
            return _Cur()

    rec = {"source": "GAIN", "source_key": "s3://g", "date": "2021-01-01", "text": "frost",
           "vector": [0.1, 0.2]}
    pg.upsert("coffee", [rec], conn=_Conn())
    assert captured["sql"].startswith("INSERT INTO evidence_props_shadow (")


# ── swap / rollback SQL correctness + transaction boundaries ─────────────────────────────────
def test_names_default(monkeypatch):
    monkeypatch.delenv("EVIDENCE_PG_TABLE", raising=False)
    assert swap._names() == ("evidence_props", "evidence_props_shadow", "evidence_props_old")


def test_swap_sql_order_and_content():
    stmts = swap.swap_sql("evidence_props", "evidence_props_shadow", "evidence_props_old")
    assert stmts == [
        "DROP TABLE IF EXISTS evidence_props_old",
        "ALTER TABLE evidence_props RENAME TO evidence_props_old",
        "ALTER TABLE evidence_props_shadow RENAME TO evidence_props",
    ]


def test_rollback_sql_is_reverse_rename():
    stmts = swap.rollback_sql("evidence_props", "evidence_props_shadow", "evidence_props_old")
    assert stmts == [
        "DROP TABLE IF EXISTS evidence_props_shadow",
        "ALTER TABLE evidence_props RENAME TO evidence_props_shadow",
        "ALTER TABLE evidence_props_old RENAME TO evidence_props",
    ]


def test_swap_and_rollback_both_end_at_live():
    """swap ends with shadow->live; rollback ends with old->live — so after swap+rollback the pre-swap live
    (now `_old`) is promoted back to live, restoring the original identity."""
    live, shadow, old = "evidence_props", "evidence_props_shadow", "evidence_props_old"
    assert swap.swap_sql(live, shadow, old)[-1] == f"ALTER TABLE {shadow} RENAME TO {live}"
    assert swap.rollback_sql(live, shadow, old)[-1] == f"ALTER TABLE {old} RENAME TO {live}"


# ── fake connection: records statements + transaction boundaries ─────────────────────────────
class _Txn:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.log.append("BEGIN")
        return self

    def __exit__(self, exc_type, *a):
        self.conn.log.append("ROLLBACK" if exc_type else "COMMIT")
        return False


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class FakeConn:
    """Minimal psycopg3-shaped stand-in: execute() logs the SQL and answers to_regclass/count probes from
    a preset `tables` map ({name: row_count}); transaction() logs BEGIN/COMMIT so we can assert atomicity."""
    def __init__(self, tables):
        self.tables = dict(tables)
        self.log: list[str] = []

    def transaction(self):
        return _Txn(self)

    def execute(self, sql, params=None):
        self.log.append(sql)
        if "to_regclass" in sql:
            name = params[0]
            return _Result((name in self.tables,))
        if sql.lower().startswith("select count(*)"):
            name = sql.rsplit(" ", 1)[-1]
            return _Result((self.tables.get(name, 0),))
        return _Result(None)

    def close(self):
        pass


def test_run_txn_wraps_statements_in_one_transaction():
    conn = FakeConn({})
    swap._run_txn(conn, ["A", "B", "C"])
    assert conn.log == ["BEGIN", "A", "B", "C", "COMMIT"]


def test_guard_refuses_swap_when_shadow_missing(monkeypatch, capsys):
    monkeypatch.delenv("EVIDENCE_PG_TABLE", raising=False)
    conn = FakeConn({"evidence_props": 100})            # shadow absent
    monkeypatch.setattr(swap.pgstore, "dsn", lambda: "postgresql://x")
    import sys as _sys
    monkeypatch.setitem(_sys.modules, "psycopg", _fake_psycopg(conn))
    rc = _run_main(monkeypatch, ["--swap"])
    out = capsys.readouterr().out
    assert rc == 1 and "REFUSE swap" in out and "does not exist" in out
    # NO rename ran — only the existence probe touched the conn.
    assert not any("RENAME" in s for s in conn.log)


def test_guard_refuses_swap_when_shadow_empty(monkeypatch, capsys):
    monkeypatch.delenv("EVIDENCE_PG_TABLE", raising=False)
    conn = FakeConn({"evidence_props": 100, "evidence_props_shadow": 0})   # shadow exists but is empty
    monkeypatch.setattr(swap.pgstore, "dsn", lambda: "postgresql://x")
    import sys as _sys
    monkeypatch.setitem(_sys.modules, "psycopg", _fake_psycopg(conn))
    rc = _run_main(monkeypatch, ["--swap"])
    out = capsys.readouterr().out
    assert rc == 1 and "REFUSE swap" in out and "0 rows" in out
    assert not any("RENAME" in s for s in conn.log)


def test_swap_runs_rename_txn_when_shadow_loaded(monkeypatch, capsys):
    monkeypatch.delenv("EVIDENCE_PG_TABLE", raising=False)
    conn = FakeConn({"evidence_props": 100, "evidence_props_shadow": 250})
    monkeypatch.setattr(swap.pgstore, "dsn", lambda: "postgresql://x")
    import sys as _sys
    monkeypatch.setitem(_sys.modules, "psycopg", _fake_psycopg(conn))
    rc = _run_main(monkeypatch, ["--swap"])
    out = capsys.readouterr().out
    assert rc == 0 and "swapped" in out
    # the three renames ran BETWEEN a single BEGIN/COMMIT pair
    assert conn.log.count("BEGIN") == 1 and conn.log.count("COMMIT") == 1
    b, c = conn.log.index("BEGIN"), conn.log.index("COMMIT")
    body = conn.log[b + 1:c]
    assert body == [
        "DROP TABLE IF EXISTS evidence_props_old",
        "ALTER TABLE evidence_props RENAME TO evidence_props_old",
        "ALTER TABLE evidence_props_shadow RENAME TO evidence_props",
    ]


def test_rollback_refuses_when_old_missing(monkeypatch, capsys):
    monkeypatch.delenv("EVIDENCE_PG_TABLE", raising=False)
    conn = FakeConn({"evidence_props": 100})            # no _old to roll back to
    monkeypatch.setattr(swap.pgstore, "dsn", lambda: "postgresql://x")
    import sys as _sys
    monkeypatch.setitem(_sys.modules, "psycopg", _fake_psycopg(conn))
    rc = _run_main(monkeypatch, ["--rollback"])
    out = capsys.readouterr().out
    assert rc == 1 and "REFUSE rollback" in out
    assert not any("RENAME" in s for s in conn.log)


def test_rollback_runs_reverse_rename_txn(monkeypatch, capsys):
    monkeypatch.delenv("EVIDENCE_PG_TABLE", raising=False)
    conn = FakeConn({"evidence_props": 250, "evidence_props_old": 100})
    monkeypatch.setattr(swap.pgstore, "dsn", lambda: "postgresql://x")
    import sys as _sys
    monkeypatch.setitem(_sys.modules, "psycopg", _fake_psycopg(conn))
    rc = _run_main(monkeypatch, ["--rollback"])
    out = capsys.readouterr().out
    assert rc == 0 and "rolled back" in out
    b, c = conn.log.index("BEGIN"), conn.log.index("COMMIT")
    assert conn.log[b + 1:c] == [
        "DROP TABLE IF EXISTS evidence_props_shadow",
        "ALTER TABLE evidence_props RENAME TO evidence_props_shadow",
        "ALTER TABLE evidence_props_old RENAME TO evidence_props",
    ]


def test_dry_run_prints_sql_touches_nothing(monkeypatch, capsys):
    monkeypatch.delenv("EVIDENCE_PG_TABLE", raising=False)
    # No DSN, no psycopg needed: --dry-run returns before any connect.
    monkeypatch.setattr(swap.pgstore, "dsn", lambda: None)
    rc = _run_main(monkeypatch, ["--swap", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "BEGIN;" in out and "COMMIT;" in out
    assert "ALTER TABLE evidence_props_shadow RENAME TO evidence_props;" in out


def test_swap_missing_dsn_returns_1(monkeypatch, capsys):
    monkeypatch.delenv("EVIDENCE_PG_TABLE", raising=False)
    monkeypatch.setattr(swap.pgstore, "dsn", lambda: None)
    rc = _run_main(monkeypatch, ["--swap"])
    out = capsys.readouterr().out
    assert rc == 1 and "EVIDENCE_PG_DSN not set" in out


def test_shadow_table_env_flips_all_three_names(monkeypatch):
    """If someone flips the BASE name via env, the derived shadow/old track it — the tool isn't hardwired to
    the literal `evidence_props`."""
    monkeypatch.setenv("EVIDENCE_PG_TABLE", "evprops")
    assert swap._names() == ("evprops", "evprops_shadow", "evprops_old")


# ── helpers ──────────────────────────────────────────────────────────────────────────────────
def _fake_psycopg(conn):
    import types
    m = types.SimpleNamespace()
    m.connect = lambda *a, **k: conn
    return m


def _run_main(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["pg_evidence_swap.py"] + argv)
    return swap.main()
