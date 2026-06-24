"""Shared read-only Athena helpers for pipeline validation scripts."""
from __future__ import annotations

import os
import time

import boto3

ATHENA_DB = "leviathan_dev"
BUCKET = os.environ.get("LEVIATHAN_BUCKET", "leviathan-dev-shahem-001")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
ATHENA_RESULTS = f"s3://{BUCKET}/athena-results/"


def run_query(client, sql: str, database: str | None = ATHENA_DB) -> list[dict]:
    """Run one Athena query and return all result rows."""
    kwargs: dict = {
        "QueryString": sql,
        "ResultConfiguration": {"OutputLocation": ATHENA_RESULTS},
    }
    if database:
        kwargs["QueryExecutionContext"] = {"Database": database}
    query_id = client.start_query_execution(**kwargs)["QueryExecutionId"]

    while True:
        execution = client.get_query_execution(QueryExecutionId=query_id)
        state = execution["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in {"FAILED", "CANCELLED"}:
            reason = execution["QueryExecution"]["Status"].get("StateChangeReason", "")
            raise RuntimeError(f"Athena {state}: {reason}; query={query_id}")
        time.sleep(2)

    rows: list[dict] = []
    headers: list[str] | None = None
    next_token: str | None = None
    first_page = True
    while True:
        request: dict = {"QueryExecutionId": query_id, "MaxResults": 1000}
        if next_token:
            request["NextToken"] = next_token
        response = client.get_query_results(**request)
        if headers is None:
            headers = [
                item["Name"]
                for item in response["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]
            ]
        page_rows = response["ResultSet"]["Rows"]
        start = 1 if first_page else 0
        first_page = False
        for row in page_rows[start:]:
            rows.append(
                {
                    headers[index]: value.get("VarCharValue", "")
                    for index, value in enumerate(row["Data"])
                }
            )
        next_token = response.get("NextToken")
        if not next_token:
            return rows


def ensure_catalog():
    """Ensure only the Glue database exists, never mutate table definitions."""
    glue = boto3.client("glue", region_name=AWS_REGION)
    try:
        glue.get_database(Name=ATHENA_DB)
    except glue.exceptions.EntityNotFoundException:
        glue.create_database(
            DatabaseInput={
                "Name": ATHENA_DB,
                "Description": "Leviathan data lake",
            }
        )
    print(
        f"  [catalog] Database ready: {ATHENA_DB}. "
        "Use scripts/catalog/plan_catalog.py for table reconciliation."
    )
    return boto3.client("athena", region_name=AWS_REGION)
