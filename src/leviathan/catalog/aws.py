"""Small AWS helpers shared by catalog scripts."""
from __future__ import annotations

import time
from typing import Any


def list_glue_tables(glue, database: str) -> dict[str, dict[str, Any]]:
    tables: dict[str, dict[str, Any]] = {}
    paginator = glue.get_paginator("get_tables")
    for page in paginator.paginate(DatabaseName=database):
        for table in page.get("TableList", []):
            tables[table["Name"]] = table
    return tables


def run_athena_statement(
    athena,
    *,
    sql: str,
    database: str | None,
    output_location: str,
    workgroup: str = "primary",
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "QueryString": sql,
        "ResultConfiguration": {"OutputLocation": output_location},
        "WorkGroup": workgroup,
    }
    if database:
        request["QueryExecutionContext"] = {"Database": database}
    execution_id = athena.start_query_execution(**request)["QueryExecutionId"]
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = athena.get_query_execution(QueryExecutionId=execution_id)
        execution = response["QueryExecution"]
        state = execution["Status"]["State"]
        if state == "SUCCEEDED":
            execution["QueryExecutionId"] = execution_id
            return execution
        if state in {"FAILED", "CANCELLED"}:
            reason = execution["Status"].get("StateChangeReason", "")
            raise RuntimeError(f"Athena {state}: {reason}; query={execution_id}")
        time.sleep(2)
    raise TimeoutError(f"Athena query timed out: {execution_id}")


def athena_has_data_rows(athena, query_execution_id: str) -> bool:
    response = athena.get_query_results(
        QueryExecutionId=query_execution_id,
        MaxResults=2,
    )
    return len(response.get("ResultSet", {}).get("Rows", [])) > 1
