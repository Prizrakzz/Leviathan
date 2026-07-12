"""
Run a fixed subset of Athena DDL statements via boto3.

Creates the ``leviathan_dev`` database (if absent) then runs the CREATE EXTERNAL TABLE IF NOT
EXISTS statements listed in ``_GRAPHRAG_DDLS`` -- as of this writing 9 tables: the 4 graphrag
tables (entities, causal_edges, forecasts, sentiment) PLUS 4 silver tables (nass_annual, fgis,
mpob, mpob_annual) and gold_feature_spine. It is NOT a full-catalog applier and it is NOT the DDL
authority: the registry-driven generator ``scripts/silver/generate_ddls_from_registry.py``
(SILVER-F011) renders every silver/gold DDL from the SILVER-F010 registry, and the governed
plan/apply/rollback tool (SILVER-F012) is the sanctioned path for catalog migration.

Usage:
    python jobs/run_athena_ddl.py

No arguments needed.  Idempotent — safe to rerun at any time.
"""

import logging
import time
from pathlib import Path

import boto3

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("run_athena_ddl")

_BUCKET = "leviathan-dev-shahem-001"
_RESULTS_PREFIX = f"s3://{_BUCKET}/athena-results/ddl/"
_WORKGROUP = "primary"
_DATABASE = "leviathan_dev"
_DDL_DIR = Path(__file__).parent.parent / "sql" / "athena" / "ddl"
_GRAPHRAG_DDLS = [
    "graphrag_entities.sql",
    "graphrag_causal_edges.sql",
    "graphrag_forecasts.sql",
    "graphrag_sentiment.sql",
    "silver_nass_annual.sql",
    "silver_fgis.sql",
    "silver_mpob.sql",
    "silver_mpob_annual.sql",
    "gold_feature_spine.sql",
]


def _run_query(client, sql: str, database: str | None = None) -> tuple[bool, str]:
    """Submit an Athena query and poll until terminal state. Returns (ok, message)."""
    kwargs: dict = {
        "QueryString": sql,
        "ResultConfiguration": {"OutputLocation": _RESULTS_PREFIX},
        "WorkGroup": _WORKGROUP,
    }
    if database:
        kwargs["QueryExecutionContext"] = {"Database": database}

    resp = client.start_query_execution(**kwargs)
    exec_id = resp["QueryExecutionId"]

    for _ in range(60):
        time.sleep(2)
        status = client.get_query_execution(QueryExecutionId=exec_id)
        state = status["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            return True, "SUCCEEDED"
        if state in ("FAILED", "CANCELLED"):
            reason = status["QueryExecution"]["Status"].get("StateChangeReason", "")
            return False, f"{state}: {reason}"

    return False, "TIMEOUT after 120s"


def main() -> None:
    client = boto3.client("athena", region_name="us-east-1")

    # 1 — Ensure database exists
    log.info("Creating database %s (if not exists)...", _DATABASE)
    ok, msg = _run_query(client, f"CREATE DATABASE IF NOT EXISTS {_DATABASE}")
    if ok:
        log.info("  database OK")
    else:
        log.error("  database creation failed: %s", msg)
        raise SystemExit(1)

    # 2 — Run each DDL file
    errors = 0
    for filename in _GRAPHRAG_DDLS:
        path = _DDL_DIR / filename
        sql = path.read_text(encoding="utf-8")
        table_name = filename.replace(".sql", "")
        log.info("Creating table %s.%s ...", _DATABASE, table_name)
        ok, msg = _run_query(client, sql, database=_DATABASE)
        if ok:
            log.info("  ✓ %s", table_name)
        else:
            log.error("  ✗ %s — %s", table_name, msg)
            errors += 1

    if errors:
        log.error("%d table(s) failed.", errors)
        raise SystemExit(1)

    log.info("All %d tables created in %s.", len(_GRAPHRAG_DDLS), _DATABASE)
    log.info("Verify with:")
    log.info(
        "  aws glue get-tables --database-name %s "
        "--query \"TableList[?contains(Name,'graphrag')].Name\" --output table",
        _DATABASE,
    )


if __name__ == "__main__":
    main()
