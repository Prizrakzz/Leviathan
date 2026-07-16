"""A-W8 MLflow relocation -- IN-VPC Postgres backend bootstrap (one-shot Batch job).

Turns A1A2_PLAN.md A-W8 step 1 ("create the mlflow pg database out-of-band + Secrets Manager secret +
mlflow db upgrade") into a runnable, idempotent Batch job so the MLflow cutover needs NO manual psql. RDS
leviathan-dev-pg is PRIVATE (reachable only in-VPC), so this MUST run inside the VPC as a Fargate Batch job,
exactly like the evidence/numbers pg loaders (jobs/utils/load_pg_evidence.py, jobs/utils/load_pg_numbers.py).

What it does (each step tolerates a prior partial run -- safe to re-run):
  1. Resolve the RDS MASTER (superuser) DSN.
  2. CREATE DATABASE mlflow if it does not already exist (autocommit; DuplicateDatabase tolerated).
  3. CREATE ROLE mlflow_user LOGIN with a RANDOM password (secrets.token_urlsafe); GRANT it the mlflow db +
     schema-public CREATE so `mlflow db upgrade` / the server's first-boot migration can build its tables.
  4. Write postgresql://mlflow_user:<pw>@<rds-host>:5432/mlflow into Secrets Manager
     leviathan/dev/mlflow-backend-dsn (boto3 create-or-update). The DSN/password are NEVER printed or logged.
  5. If mlflow is importable in the image, run `mlflow db upgrade <dsn>`; otherwise print the marker
     MLFLOW-DB-UPGRADE-SKIPPED and let the Fargate MLflow server migrate the empty schema on first boot.

MASTER-DSN resolution (precedence):
  * MLFLOW_BOOTSTRAP_MASTER_DSN  -- explicit override. Use this if a DEDICATED RDS-master secret is preferred,
    or if EVIDENCE_PG_DSN does not carry a superuser (see below). Inject it into the jobdef as a `secrets`
    valueFrom mount pointing at whatever secret holds the master DSN; the value stays out of the submit call.
  * EVIDENCE_PG_DSN              -- mirrors how existing in-VPC code reads pg (leviathan.graphrag.pgstore.dsn()
    is just `os.environ.get("EVIDENCE_PG_DSN")`, injected by the evidence-build jobdef's execution role from
    Secrets Manager leviathan/dev/evidence-pg-dsn). That DSN is already a SUPERUSER: the evidence loader runs
    `CREATE EXTENSION IF NOT EXISTS vector` (pgstore.init_schema), which on RDS requires rds_superuser -- the
    RDS master. So CREATE DATABASE / CREATE ROLE succeed under it with no new secret.

Driver note: the repo standard is psycopg v3 (pyproject `pg` extra, `psycopg[binary]>=3.1`); this module
prefers it and falls back to psycopg2 if only that is present. NB the shared silver runner image
(leviathan-dev-b3-flat-silver == the worker Dockerfile's `pip install -e ".[batch]"`) bundles NEITHER a pg
driver NOR the EVIDENCE_PG_DSN secret mount -- so submit this on the leviathan-dev-evidence-build jobdef,
which already bakes psycopg + injects EVIDENCE_PG_DSN + reaches RDS in-VPC (see the submit-command note in the
handoff). Running it on b3-flat-silver would fail at driver-import / DSN-resolution.

MLflow-on-un-migrated-pg (why the SKIPPED path is safe): mlflow's SqlAlchemyStore, on first init against a
`--backend-store-uri` pointing at an EMPTY database, detects that its tables do not exist and runs
`alembic upgrade head` (creating every table + stamping the schema version) before serving. It only refuses to
auto-migrate when the DB has an OLDER, already-stamped schema (then it raises and tells you to run
`mlflow db upgrade`). Under G4 we start FRESH (empty schema), so the Fargate server self-migrates on first
boot; the explicit `mlflow db upgrade` here is belt-and-suspenders for images that happen to carry mlflow.

    python -m jobs.utils.mlflow_bootstrap_task --dry-run
    python -m jobs.utils.mlflow_bootstrap_task            # create db+role, write the secret, (maybe) upgrade
    python -m jobs.utils.mlflow_bootstrap_task --rotate   # force a password rotation + secret rewrite

ASCII-only. No AWS mutations happen at import; everything is inside main()/run_bootstrap().
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import secrets
import subprocess
import sys
from typing import Callable, Optional
from urllib.parse import urlsplit, urlunsplit

from leviathan.common.config import load_env
from leviathan.common.logging import get_logger

logger = get_logger("mlflow_bootstrap")

# Must equal the secret NAME the mlflow_fargate tf module mounts as MLFLOW_BACKEND_STORE_URI
# (envs/dev/main.tf local.mlflow_backend_dsn_secret_arn -> ...:secret:leviathan/dev/mlflow-backend-dsn).
DEFAULT_SECRET_NAME = "leviathan/dev/mlflow-backend-dsn"
DEFAULT_DB_NAME = "mlflow"
DEFAULT_DB_USER = "mlflow_user"

# Postgres identifiers are interpolated straight into DDL (no bind-param form exists for a db/role name),
# so the injection barrier is this lower-snake allowlist -- same discipline as pgstore._TABLE_RE.
_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
# token_urlsafe emits only URL-safe base64 (A-Z a-z 0-9 - _): no quote, no backslash, so it is safe both in a
# single-quoted SQL literal AND in a DSN userinfo without percent-encoding. Assert it, never assume it.
_PW_RE = re.compile(r"^[A-Za-z0-9_-]+$")


# --------------------------------------------------------------------------- resolution + helpers
def resolve_master_dsn() -> Optional[str]:
    """MLFLOW_BOOTSTRAP_MASTER_DSN wins; else EVIDENCE_PG_DSN (the in-VPC superuser DSN). See module docstring."""
    return os.environ.get("MLFLOW_BOOTSTRAP_MASTER_DSN") or os.environ.get("EVIDENCE_PG_DSN")


def _require_ident(name: str, kind: str) -> str:
    if not _IDENT_RE.match(name):
        raise ValueError(f"{kind} {name!r} is not a valid pg identifier (^[a-z_][a-z0-9_]*$)")
    return name


def generate_password(nbytes: int = 36) -> str:
    """A fresh URL-safe random password. token_urlsafe(36) ~ 48 chars of base64url entropy."""
    pw = secrets.token_urlsafe(nbytes)
    if not _PW_RE.match(pw):  # defensive: token_urlsafe can never violate this, but the SQL/DSN safety leans on it
        raise RuntimeError("generated password contains characters outside the URL-safe set")
    return pw


def mask_dsn(dsn: Optional[str]) -> str:
    """Render a DSN for logs with the password redacted. Never log a raw DSN."""
    if not dsn:
        return "<none>"
    try:
        parts = urlsplit(dsn)
        if parts.password:
            netloc = parts.hostname or ""
            if parts.port:
                netloc += f":{parts.port}"
            userinfo = (parts.username or "") + ":***@"
            return urlunsplit((parts.scheme, userinfo + netloc, parts.path, "", ""))
    except ValueError:
        return "<unparseable-dsn>"
    return dsn


def _swap_db(dsn: str, dbname: str) -> str:
    """Return the master DSN re-pointed at `dbname` (path swap only -- keeps user/pass/host/port/query)."""
    parts = urlsplit(dsn)
    if not parts.hostname:
        raise ValueError("master DSN is not URL-form (expected postgresql://user:pass@host:port/db)")
    return urlunsplit(parts._replace(path="/" + dbname))


def build_backend_dsn(master_dsn: str, user: str, password: str, dbname: str,
                      host_override: Optional[str] = None, port_override: Optional[int] = None) -> str:
    """postgresql://<user>:<pw>@<host>:<port>/<dbname>, host/port derived from the master DSN unless overridden.

    Deriving host/port from the master DSN keeps the written secret pointed at whatever RDS the master DSN
    already targets (so no hard-coded endpoint drifts) -- for leviathan-dev-pg that resolves to
    leviathan-dev-pg.cq7eg6wkuh11.us-east-1.rds.amazonaws.com:5432 exactly as A-W8 specifies.
    """
    parts = urlsplit(master_dsn)
    host = host_override or parts.hostname
    port = port_override or parts.port or 5432
    if not host:
        raise ValueError("cannot determine RDS host: master DSN is not URL-form and no MLFLOW_BACKEND_HOST set")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


# --------------------------------------------------------------------------- pg driver seam
def _connect(dsn: str):
    """Autocommit connection via whichever pg driver the image ships: psycopg v3 (repo default) then psycopg2.

    Isolated behind this seam so tests inject a fake and so the driver choice is one place. Autocommit is
    REQUIRED: CREATE DATABASE cannot run inside a transaction block.
    """
    try:
        import psycopg  # psycopg v3
        return psycopg.connect(dsn, autocommit=True)
    except ImportError:
        pass
    import psycopg2  # v2 fallback
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    return conn


def _exec(conn, sql: str, params=None, *, fetch: bool = False):
    """Run one statement through a cursor (works for both psycopg v3 and psycopg2). Returns fetchone() if asked."""
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        return cur.fetchone() if fetch else None
    finally:
        cur.close()


# --------------------------------------------------------------------------- steps
def ensure_database(conn, dbname: str) -> str:
    """CREATE DATABASE dbname unless it already exists. Returns 'exists' or 'created'."""
    _require_ident(dbname, "database name")
    row = _exec(conn, "SELECT 1 FROM pg_database WHERE datname = %s", (dbname,), fetch=True)
    if row:
        logger.info("database %s already present", dbname)
        return "exists"
    try:
        _exec(conn, f'CREATE DATABASE "{dbname}"')  # identifier validated above; no bind-param form for a db name
    except Exception as e:  # noqa: BLE001 -- tolerate a concurrent creator (DuplicateDatabase) so re-runs are safe
        if "already exists" not in str(e).lower():
            raise
        logger.info("database %s created concurrently (tolerated)", dbname)
        return "exists"
    logger.info("database %s created", dbname)
    return "created"


def _role_exists(conn, user: str) -> bool:
    return _exec(conn, "SELECT 1 FROM pg_roles WHERE rolname = %s", (user,), fetch=True) is not None


def apply_grants(conn, master_dsn: str, dbname: str, user: str) -> None:
    """Grant `user` the db + schema-public CREATE (idempotent; re-applied every run so perms self-heal).

    Db-level grant + ownership transfer, then a second connection INTO the mlflow db for the schema-public
    grant (PG15+ revokes CREATE-on-public from PUBLIC, so mlflow_user needs it explicitly to build tables).
    """
    _exec(conn, f'GRANT ALL PRIVILEGES ON DATABASE "{dbname}" TO "{user}"')
    try:
        _exec(conn, f'ALTER DATABASE "{dbname}" OWNER TO "{user}"')  # db owner => CREATE on public via pg_database_owner
    except Exception as e:  # noqa: BLE001 -- ownership transfer can be refused on locked-down RDS; grant below still covers
        logger.info("ALTER DATABASE OWNER skipped (%s); relying on schema grant", str(e)[:80])
    # schema-public CREATE must be granted while connected to the target db.
    db_conn = _connect_via(master_dsn, dbname)
    try:
        _exec(db_conn, f'GRANT ALL ON SCHEMA public TO "{user}"')
    finally:
        _safe_close(db_conn)


# indirection so apply_grants' inner connection is patchable in tests (they set _CONNECT).
_CONNECT: Callable[[str], object] = _connect


def _connect_via(master_dsn: str, dbname: str):
    return _CONNECT(_swap_db(master_dsn, dbname))


def _safe_close(conn) -> None:
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass


def ensure_role(conn, user: str, password: str, *, create: bool) -> None:
    """CREATE (or ALTER, on rotate) the login role with `password`. Password embedded as a validated literal."""
    _require_ident(user, "role name")
    if not _PW_RE.match(password):
        raise RuntimeError("refusing to embed a password with characters outside the URL-safe set")
    verb = "CREATE" if create else "ALTER"
    _exec(conn, f"{verb} ROLE \"{user}\" WITH LOGIN PASSWORD '{password}'")
    logger.info("%s role %s", "created" if create else "rotated password for", user)


# --------------------------------------------------------------------------- secrets manager
def _sm_client(region: Optional[str] = None):
    import boto3
    return boto3.client("secretsmanager", region_name=region or os.environ.get("AWS_REGION") or "us-east-1")


def secret_exists(sm, name: str) -> bool:
    from botocore.exceptions import ClientError
    try:
        sm.describe_secret(SecretId=name)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            return False
        raise


def write_secret(sm, name: str, dsn: str) -> str:
    """Create-or-update the secret. The DSN value is NEVER logged. Returns 'created' or 'updated'."""
    from botocore.exceptions import ClientError
    try:
        sm.create_secret(Name=name, SecretString=dsn,
                         Description="A-W8 MLflow backend DSN (mlflow_user on leviathan-dev-pg/mlflow).")
        logger.info("secret %s created", name)
        return "created"
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceExistsException":
            raise
        sm.put_secret_value(SecretId=name, SecretString=dsn)
        logger.info("secret %s updated (new version)", name)
        return "updated"


# --------------------------------------------------------------------------- mlflow db upgrade
def maybe_upgrade_db(dsn: str, password: str) -> str:
    """Run `mlflow db upgrade <dsn>` iff mlflow is importable; else print MLFLOW-DB-UPGRADE-SKIPPED.

    Returns 'upgraded', 'skipped', or 'failed'. The DSN is passed as a subprocess arg (not logged); on failure
    we redact the password out of the captured stderr before printing it.
    """
    if importlib.util.find_spec("mlflow") is None:
        print("MLFLOW-DB-UPGRADE-SKIPPED: mlflow not importable in this image; the Fargate MLflow server "
              "migrates the empty schema on first boot (fresh backend, G4).")
        return "skipped"
    try:
        subprocess.run([sys.executable, "-m", "mlflow", "db", "upgrade", dsn],
                       check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        redacted = (e.stderr or "").replace(password, "***").replace(dsn, mask_dsn(dsn))
        print(f"MLFLOW-DB-UPGRADE-FAILED rc={e.returncode}: {redacted[-500:]}")
        return "failed"
    print("MLFLOW-DB-UPGRADE-OK")
    return "upgraded"


# --------------------------------------------------------------------------- orchestration
def run_bootstrap(*, master_dsn: str, secret_name: str = DEFAULT_SECRET_NAME, dbname: str = DEFAULT_DB_NAME,
                  user: str = DEFAULT_DB_USER, rotate: bool = False,
                  connect: Optional[Callable[[str], object]] = None,
                  sm=None, host_override: Optional[str] = None, port_override: Optional[int] = None,
                  do_upgrade: bool = True) -> dict:
    """Idempotent bootstrap. Fully injectable (connect + sm) so it is unit-testable with no RDS and no AWS.

    Rotation policy (true no-op steady state): a first run creates the role and writes the secret. A re-run
    with BOTH role and secret present changes NOTHING (password preserved, secret untouched) unless rotate=True.
    A re-run where the secret is missing (partial prior run) self-heals by rotating the password + writing it,
    since the old password is unrecoverable. Grants are ALWAYS re-applied (harmless, self-healing).
    """
    global _CONNECT
    connect = connect or _connect      # resolved at CALL time so main()/tests can swap the module-level _connect
    _CONNECT = connect                 # apply_grants' inner db connection uses the same (injected) factory
    sm = sm if sm is not None else _sm_client()

    conn = connect(master_dsn)
    try:
        db_status = ensure_database(conn, dbname)
        role_present = _role_exists(conn, user)
        sec_present = secret_exists(sm, secret_name)

        do_write = (not role_present) or (not sec_present) or rotate
        result = {"database": db_status, "secret_name": secret_name, "dbname": dbname, "user": user}

        if do_write:
            password = generate_password()
            ensure_role(conn, user, password, create=not role_present)
            result["role"] = "created" if not role_present else "rotated"
            apply_grants(conn, master_dsn, dbname, user)
            backend_dsn = build_backend_dsn(master_dsn, user, password, dbname, host_override, port_override)
            result["secret"] = write_secret(sm, secret_name, backend_dsn)
            result["upgrade"] = maybe_upgrade_db(backend_dsn, password) if do_upgrade else "not-run"
        else:
            # steady-state re-run: role + secret already exist and no rotation asked -> re-apply grants only.
            apply_grants(conn, master_dsn, dbname, user)
            result["role"] = "unchanged"
            result["secret"] = "unchanged"
            result["upgrade"] = "skipped-no-write"
            logger.info("role %s and secret %s already present; grants re-applied, nothing rotated",
                        user, secret_name)
        return result
    finally:
        _safe_close(conn)


def main(argv=None) -> int:
    load_env()
    ap = argparse.ArgumentParser(description="Bootstrap the MLflow Postgres backend (db + role + secret) in-VPC.")
    ap.add_argument("--secret-name", default=os.environ.get("MLFLOW_BACKEND_DSN_SECRET", DEFAULT_SECRET_NAME),
                    help="Secrets Manager secret to write (default: leviathan/dev/mlflow-backend-dsn).")
    ap.add_argument("--db-name", default=os.environ.get("MLFLOW_DB_NAME", DEFAULT_DB_NAME))
    ap.add_argument("--db-user", default=os.environ.get("MLFLOW_DB_USER", DEFAULT_DB_USER))
    ap.add_argument("--host", default=os.environ.get("MLFLOW_BACKEND_HOST"),
                    help="Override the RDS host in the written DSN (default: derived from the master DSN).")
    ap.add_argument("--port", type=int, default=(int(os.environ["MLFLOW_BACKEND_PORT"])
                                                 if os.environ.get("MLFLOW_BACKEND_PORT") else None))
    ap.add_argument("--rotate", action="store_true",
                    help="Force a password rotation + secret rewrite even if role and secret already exist.")
    ap.add_argument("--no-upgrade", action="store_true", help="Skip the mlflow db upgrade step entirely.")
    ap.add_argument("--dry-run", action="store_true", help="Resolve + validate inputs, mutate nothing.")
    args = ap.parse_args(argv)

    master_dsn = resolve_master_dsn()
    if not master_dsn:
        print("MLFLOW_BOOTSTRAP_MASTER_DSN / EVIDENCE_PG_DSN not set: cannot resolve the RDS master DSN")
        return 1
    try:
        _require_ident(args.db_name, "database name")
        _require_ident(args.db_user, "role name")
    except ValueError as e:
        print(f"invalid identifier: {e}")
        return 1

    if args.dry_run:
        # Validate DSN shape without connecting or mutating; only the MASKED endpoint is shown.
        try:
            preview = mask_dsn(build_backend_dsn(master_dsn, args.db_user, "<pw>", args.db_name,
                                                 args.host, args.port))
        except ValueError as e:
            print(f"[DRY RUN] master DSN unusable: {e}")
            return 1
        print(f"[DRY RUN] master={mask_dsn(master_dsn)}  would ensure db={args.db_name} role={args.db_user}")
        print(f"[DRY RUN] would write secret {args.secret_name} = {preview}")
        print(f"[DRY RUN] mlflow importable: {importlib.util.find_spec('mlflow') is not None} "
              f"(else MLFLOW-DB-UPGRADE-SKIPPED)")
        return 0

    result = run_bootstrap(master_dsn=master_dsn, secret_name=args.secret_name, dbname=args.db_name,
                           user=args.db_user, rotate=args.rotate, host_override=args.host,
                           port_override=args.port, do_upgrade=not args.no_upgrade)
    # Report status ONLY -- never the DSN/password.
    print("mlflow-bootstrap: " + "  ".join(f"{k}={v}" for k, v in result.items()))
    if result.get("upgrade") == "failed":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
