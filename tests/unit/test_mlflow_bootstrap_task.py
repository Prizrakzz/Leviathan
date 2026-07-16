"""Unit tests for the A-W8 MLflow pg-backend bootstrap (jobs/utils/mlflow_bootstrap_task.py).

All PURE -- no Postgres, no AWS. psycopg2/psycopg and boto3 are stubbed: a tiny FakeConn records every
statement and answers the pg_database/pg_roles existence probes from a preset state map; a FakeSM records
create/put and raises the real botocore ClientError to drive the create-vs-update branches. The password is
pinned to a sentinel via monkeypatch so we can assert it NEVER reaches logs or stdout while still landing in
the (fake) secret store. Fixtures are synthetic -- no real credentials, endpoints, or secret values.
"""
from __future__ import annotations

import sys

import pytest
from botocore.exceptions import ClientError

from jobs.utils import mlflow_bootstrap_task as mb

MASTER = "postgresql://postgres:masterpw@leviathan-dev-pg.cq7eg6wkuh11.us-east-1.rds.amazonaws.com:5432/leviathan"


# --------------------------------------------------------------------------- fake pg driver
class FakeState:
    def __init__(self, databases=(), roles=(), raise_dup_db=False):
        self.databases = set(databases)
        self.roles = set(roles)
        self.raise_dup_db = raise_dup_db
        self.log: list[tuple] = []          # (dsn, sql, params)
        self.connected: list[str] = []       # every dsn connect() was called with


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._row = None

    def execute(self, sql, params=None):
        st = self.conn.state
        st.log.append((self.conn.dsn, sql, params))
        low = sql.lower()
        self._row = None
        if "from pg_database" in low:
            self._row = (1,) if params and params[0] in st.databases else None
        elif "from pg_roles" in low:
            self._row = (1,) if params and params[0] in st.roles else None
        elif low.startswith("create database"):
            if st.raise_dup_db:
                raise RuntimeError('database "mlflow" already exists')
            st.databases.add(sql.split('"')[1])
        elif low.startswith("create role") or low.startswith("alter role"):
            st.roles.add(sql.split('"')[1])

    def fetchone(self):
        return self._row

    def close(self):
        pass


class FakeConn:
    def __init__(self, dsn, state):
        self.dsn = dsn
        self.state = state
        state.connected.append(dsn)

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        pass


def make_connect(state):
    return lambda dsn: FakeConn(dsn, state)


# --------------------------------------------------------------------------- fake secrets manager
def _client_error(code, op):
    return ClientError({"Error": {"Code": code, "Message": ""}}, op)


class FakeSM:
    def __init__(self, existing=None):
        self.store = dict(existing or {})
        self.calls: list[str] = []

    def describe_secret(self, SecretId):
        self.calls.append("describe")
        if SecretId not in self.store:
            raise _client_error("ResourceNotFoundException", "DescribeSecret")
        return {"Name": SecretId}

    def create_secret(self, Name, SecretString, Description=None):
        self.calls.append("create")
        if Name in self.store:
            raise _client_error("ResourceExistsException", "CreateSecret")
        self.store[Name] = SecretString

    def put_secret_value(self, SecretId, SecretString):
        self.calls.append("put")
        self.store[SecretId] = SecretString


# --------------------------------------------------------------------------- helpers: pure
def test_build_backend_dsn_derives_host_and_db():
    dsn = mb.build_backend_dsn(MASTER, "mlflow_user", "PWSENTINEL", "mlflow")
    assert dsn == ("postgresql://mlflow_user:PWSENTINEL@"
                   "leviathan-dev-pg.cq7eg6wkuh11.us-east-1.rds.amazonaws.com:5432/mlflow")


def test_build_backend_dsn_host_override():
    dsn = mb.build_backend_dsn(MASTER, "mlflow_user", "PW", "mlflow", host_override="other-host", port_override=6543)
    assert dsn == "postgresql://mlflow_user:PW@other-host:6543/mlflow"


def test_mask_dsn_redacts_password():
    masked = mb.mask_dsn(MASTER)
    assert "masterpw" not in masked and ":***@" in masked and "leviathan-dev-pg" in masked


def test_swap_db_repoints_path_only():
    assert mb._swap_db(MASTER, "mlflow").endswith(
        "@leviathan-dev-pg.cq7eg6wkuh11.us-east-1.rds.amazonaws.com:5432/mlflow")
    assert mb._swap_db(MASTER, "mlflow").startswith("postgresql://postgres:masterpw@")


def test_generate_password_is_url_safe():
    pw = mb.generate_password()
    assert mb._PW_RE.match(pw) and len(pw) >= 24


@pytest.mark.parametrize("bad", ["mlflow-db", "MLflow", "1mlflow", "ml flow", "ml;drop", 'ml"x'])
def test_require_ident_rejects_injection(bad):
    with pytest.raises(ValueError):
        mb._require_ident(bad, "database name")


def test_ensure_role_rejects_unsafe_password():
    conn = FakeConn(MASTER, FakeState())
    with pytest.raises(RuntimeError):
        mb.ensure_role(conn, "mlflow_user", "pw'; DROP", create=True)


# --------------------------------------------------------------------------- resolution
def test_resolve_master_dsn_precedence(monkeypatch):
    monkeypatch.setenv("EVIDENCE_PG_DSN", "postgresql://evid")
    monkeypatch.delenv("MLFLOW_BOOTSTRAP_MASTER_DSN", raising=False)
    assert mb.resolve_master_dsn() == "postgresql://evid"
    monkeypatch.setenv("MLFLOW_BOOTSTRAP_MASTER_DSN", "postgresql://master")
    assert mb.resolve_master_dsn() == "postgresql://master"   # explicit override wins


# --------------------------------------------------------------------------- driver seam (stubbed psycopg2)
def test_connect_prefers_psycopg3(monkeypatch):
    import types
    captured = {}
    fake = types.SimpleNamespace(connect=lambda dsn, autocommit=None: captured.update(dsn=dsn, ac=autocommit) or "V3")
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    assert mb._connect("postgresql://x") == "V3"
    assert captured == {"dsn": "postgresql://x", "ac": True}


def test_connect_falls_back_to_psycopg2(monkeypatch):
    import types

    class _Conn:
        autocommit = False

    conn = _Conn()
    fake2 = types.SimpleNamespace(connect=lambda dsn: conn)
    monkeypatch.setitem(sys.modules, "psycopg", None)          # make `import psycopg` raise ImportError
    monkeypatch.setitem(sys.modules, "psycopg2", fake2)
    out = mb._connect("postgresql://x")
    assert out is conn and out.autocommit is True              # v2 path sets autocommit after connect


# --------------------------------------------------------------------------- database step
def test_ensure_database_creates_when_absent():
    st = FakeState()
    assert mb.ensure_database(FakeConn(MASTER, st), "mlflow") == "created"
    assert "mlflow" in st.databases


def test_ensure_database_exists_is_tolerated():
    st = FakeState(databases=["mlflow"])
    conn = FakeConn(MASTER, st)
    assert mb.ensure_database(conn, "mlflow") == "exists"
    assert not any(s.lower().startswith("create database") for _, s, _ in st.log)   # no CREATE issued


def test_ensure_database_duplicate_error_tolerated():
    st = FakeState(raise_dup_db=True)          # probe says absent, but CREATE races and errors "already exists"
    assert mb.ensure_database(FakeConn(MASTER, st), "mlflow") == "exists"


# --------------------------------------------------------------------------- secret create vs update
def test_write_secret_create_path():
    sm = FakeSM()
    assert mb.write_secret(sm, "leviathan/dev/mlflow-backend-dsn", "postgresql://mlflow_user:pw@h/mlflow") == "created"
    assert sm.store["leviathan/dev/mlflow-backend-dsn"].endswith("/mlflow") and sm.calls == ["create"]


def test_write_secret_update_path():
    sm = FakeSM(existing={"leviathan/dev/mlflow-backend-dsn": "old"})
    assert mb.write_secret(sm, "leviathan/dev/mlflow-backend-dsn", "new-dsn") == "updated"
    assert sm.store["leviathan/dev/mlflow-backend-dsn"] == "new-dsn" and sm.calls == ["create", "put"]


# --------------------------------------------------------------------------- mlflow upgrade branch
def test_maybe_upgrade_skips_when_mlflow_absent(monkeypatch, capsys):
    monkeypatch.setattr(mb.importlib.util, "find_spec", lambda name: None)
    assert mb.maybe_upgrade_db("postgresql://mlflow_user:pw@h/mlflow", "pw") == "skipped"
    assert "MLFLOW-DB-UPGRADE-SKIPPED" in capsys.readouterr().out


def test_maybe_upgrade_runs_when_mlflow_present(monkeypatch, capsys):
    monkeypatch.setattr(mb.importlib.util, "find_spec", lambda name: object())
    calls = {}
    monkeypatch.setattr(mb.subprocess, "run", lambda cmd, **kw: calls.update(cmd=cmd))
    assert mb.maybe_upgrade_db("postgresql://mlflow_user:pw@h/mlflow", "pw") == "upgraded"
    assert calls["cmd"][1:4] == ["-m", "mlflow", "db"] and "MLFLOW-DB-UPGRADE-OK" in capsys.readouterr().out


# --------------------------------------------------------------------------- full bootstrap orchestration
def _run(monkeypatch, state, sm, *, rotate=False, pw="PWSENTINEL_ABC-123"):
    monkeypatch.setattr(mb, "generate_password", lambda *a, **k: pw)
    monkeypatch.setattr(mb.importlib.util, "find_spec", lambda name: None)   # force the SKIPPED path (no subprocess)
    return mb.run_bootstrap(master_dsn=MASTER, connect=make_connect(state), sm=sm, rotate=rotate)


def test_first_run_creates_everything(monkeypatch, capsys):
    st, sm = FakeState(), FakeSM()
    res = _run(monkeypatch, st, sm)
    assert res["database"] == "created" and res["role"] == "created" and res["secret"] == "created"
    assert res["upgrade"] == "skipped"
    # secret holds the derived, mlflow_user DSN pointing at /mlflow
    stored = sm.store["leviathan/dev/mlflow-backend-dsn"]
    assert stored.startswith("postgresql://mlflow_user:PWSENTINEL_ABC-123@") and stored.endswith(":5432/mlflow")
    # the schema grant ran on a SECOND connection into the mlflow db (as the master user)
    assert any(d.endswith("/mlflow") and d.startswith("postgresql://postgres:") for d in st.connected)
    assert any("grant all on schema public" in s.lower() for _, s, _ in st.log)


def test_password_and_dsn_never_logged(monkeypatch, caplog, capsys):
    caplog.set_level("INFO")
    st, sm = FakeState(), FakeSM()
    _run(monkeypatch, st, sm)
    out = capsys.readouterr().out
    combined = out + caplog.text
    assert "PWSENTINEL_ABC-123" not in combined      # password never surfaces in stdout or logs
    assert "masterpw" not in combined                # master password never surfaces either
    # but it WAS stored in the (fake) secret -- proving the flow ran, just not via a log
    assert "PWSENTINEL_ABC-123" in sm.store["leviathan/dev/mlflow-backend-dsn"]


def test_steady_state_rerun_is_noop(monkeypatch):
    st = FakeState(databases=["mlflow"], roles=["mlflow_user"])
    sm = FakeSM(existing={"leviathan/dev/mlflow-backend-dsn": "postgresql://mlflow_user:kept@h/mlflow"})
    res = _run(monkeypatch, st, sm)
    assert res["role"] == "unchanged" and res["secret"] == "unchanged"
    assert "put" not in sm.calls and "create" not in sm.calls          # secret untouched
    assert sm.store["leviathan/dev/mlflow-backend-dsn"] == "postgresql://mlflow_user:kept@h/mlflow"
    assert any("grant all on schema public" in s.lower() for _, s, _ in st.log)   # grants still re-applied


def test_partial_run_missing_secret_self_heals(monkeypatch):
    st = FakeState(databases=["mlflow"], roles=["mlflow_user"])     # role exists but secret was never written
    sm = FakeSM()
    res = _run(monkeypatch, st, sm)
    assert res["role"] == "rotated" and res["secret"] == "created"
    assert any(s.lower().startswith("alter role") for _, s, _ in st.log)   # password rotated, not re-created
    assert sm.store["leviathan/dev/mlflow-backend-dsn"].startswith("postgresql://mlflow_user:PWSENTINEL")


def test_rotate_forces_update(monkeypatch):
    st = FakeState(databases=["mlflow"], roles=["mlflow_user"])
    sm = FakeSM(existing={"leviathan/dev/mlflow-backend-dsn": "old"})
    res = _run(monkeypatch, st, sm, rotate=True)
    assert res["role"] == "rotated" and res["secret"] == "updated" and "put" in sm.calls
    assert any(s.lower().startswith("alter role") for _, s, _ in st.log)


# --------------------------------------------------------------------------- main() wiring
def test_main_missing_dsn_returns_1(monkeypatch, capsys):
    monkeypatch.delenv("EVIDENCE_PG_DSN", raising=False)
    monkeypatch.delenv("MLFLOW_BOOTSTRAP_MASTER_DSN", raising=False)
    monkeypatch.setattr(mb, "load_env", lambda: None)
    assert mb.main([]) == 1
    assert "cannot resolve" in capsys.readouterr().out


def test_main_dry_run_mutates_nothing(monkeypatch, capsys):
    monkeypatch.setenv("EVIDENCE_PG_DSN", MASTER)
    monkeypatch.setattr(mb, "load_env", lambda: None)

    def _boom(*a, **k):
        raise AssertionError("run_bootstrap must not be called in --dry-run")

    monkeypatch.setattr(mb, "run_bootstrap", _boom)
    assert mb.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "[DRY RUN]" in out and "leviathan/dev/mlflow-backend-dsn" in out and "masterpw" not in out


def test_main_rejects_bad_identifier(monkeypatch, capsys):
    monkeypatch.setenv("EVIDENCE_PG_DSN", MASTER)
    monkeypatch.setattr(mb, "load_env", lambda: None)
    assert mb.main(["--db-name", "ml-flow"]) == 1
    assert "invalid identifier" in capsys.readouterr().out


def test_main_happy_path_reports_status(monkeypatch, capsys):
    monkeypatch.setenv("EVIDENCE_PG_DSN", MASTER)
    monkeypatch.setattr(mb, "load_env", lambda: None)
    st, sm = FakeState(), FakeSM()
    monkeypatch.setattr(mb, "generate_password", lambda *a, **k: "PWSENTINEL")
    monkeypatch.setattr(mb.importlib.util, "find_spec", lambda name: None)
    # inject the fakes by wrapping run_bootstrap's defaults through the module seam
    monkeypatch.setattr(mb, "_sm_client", lambda *a, **k: sm)
    monkeypatch.setattr(mb, "_connect", make_connect(st))
    rc = mb.main([])
    out = capsys.readouterr().out
    assert rc == 0 and "mlflow-bootstrap:" in out and "PWSENTINEL" not in out
    assert sm.store["leviathan/dev/mlflow-backend-dsn"].endswith(":5432/mlflow")
