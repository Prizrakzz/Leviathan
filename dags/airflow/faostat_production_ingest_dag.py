"""Monthly FAOSTAT production ingest DAG — raw → bronze → silver.

Runs on the 1st of each month. FAO doesn't publish daily updates; this DAG
is intended to pick up new annual releases and refreshes automatically.
It can also be triggered manually at any time when a new FAOSTAT ZIP has
been uploaded to S3.

Pipeline
--------
run_glue_raw_to_bronze  →  run_glue_bronze_to_silver

Design notes
------------
- FAOSTAT has no Batch worker step — raw data is a ZIP uploaded manually (or
  via a separate ingestion job) to S3 before this DAG runs.
- The S3 raw key is constructed per-commodity:
    raw/production/source=faostat/commodity={commodity}/Production_Crops_Livestock_E_All_Data_Normalized.zip
- Pure boto3; no airflow-providers-amazon dependency.
- Polling loops live inside each @task.
- Extend FAOSTAT_COMMODITIES as raw ZIPs are uploaded for new commodities.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import boto3
from airflow.decorators import dag, task
from airflow.utils.dates import days_ago

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AWS_REGION    = os.environ.get("AWS_REGION", "us-east-1")
LEVIATHAN_ENV = os.environ.get("LEVIATHAN_ENV", "dev")
PROJECT       = os.environ.get("LEVIATHAN_PROJECT", "leviathan")

R2B_GLUE_JOB = f"{PROJECT}-{LEVIATHAN_ENV}-raw-to-bronze-faostat"
B2S_GLUE_JOB = f"{PROJECT}-{LEVIATHAN_ENV}-bronze-to-silver-faostat"

POLL_INTERVAL = 30  # seconds

# Extend this list as raw FAOSTAT ZIPs are uploaded to S3 for new commodities.
FAOSTAT_COMMODITIES: list[str] = [
    "cocoa",
]

FAOSTAT_RAW_KEY_TEMPLATE = (
    "raw/production/source=faostat/commodity={commodity}/"
    "Production_Crops_Livestock_E_All_Data_Normalized.zip"
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _poll_glue(client, runs: list[tuple[str, str]]) -> dict[str, str]:
    """Block until all Glue runs are terminal. Returns {run_id: status}."""
    remaining: set[tuple[str, str]] = set(runs)
    results: dict[str, str] = {}
    while remaining:
        done: set[tuple[str, str]] = set()
        for job_name, run_id in remaining:
            state = client.get_job_run(JobName=job_name, RunId=run_id)["JobRun"]["JobRunState"]
            if state in ("SUCCEEDED", "FAILED", "ERROR", "TIMEOUT"):
                results[run_id] = state
                done.add((job_name, run_id))
        remaining -= done
        if remaining:
            time.sleep(POLL_INTERVAL)
    return results


# ---------------------------------------------------------------------------
# DAG definition
# ---------------------------------------------------------------------------

@dag(
    dag_id="faostat_production_ingest",
    description=(
        "Monthly FAOSTAT QCL production data ingest: raw ZIP → bronze → silver "
        "for all commodities with uploaded raw data."
    ),
    schedule="@monthly",
    start_date=days_ago(1),
    catchup=False,
    tags=["leviathan", "production", "faostat"],
)
def faostat_production_ingest_dag() -> None:

    @task()
    def run_glue_raw_to_bronze() -> list[list[str]]:
        """Start raw→bronze Glue job for every FAOSTAT commodity in parallel, then poll."""
        ingest_date = date.today().isoformat()
        glue = boto3.client("glue", region_name=AWS_REGION)
        runs: list[tuple[str, str]] = []

        def _start(commodity: str) -> tuple[str, str]:
            s3_raw_key = FAOSTAT_RAW_KEY_TEMPLATE.format(commodity=commodity)
            run_id = glue.start_job_run(
                JobName=R2B_GLUE_JOB,
                Arguments={
                    "--commodity":   commodity,
                    "--ingest_date": ingest_date,
                    "--s3_raw_key":  s3_raw_key,
                },
            )["JobRunId"]
            return R2B_GLUE_JOB, run_id

        with ThreadPoolExecutor(max_workers=min(len(FAOSTAT_COMMODITIES), 20)) as pool:
            futures = [pool.submit(_start, c) for c in FAOSTAT_COMMODITIES]
            for f in as_completed(futures):
                runs.append(f.result())

        statuses = _poll_glue(glue, runs)
        failed = [rid for rid, s in statuses.items() if s != "SUCCEEDED"]
        if failed:
            raise RuntimeError(
                f"{len(failed)} raw→bronze FAOSTAT Glue runs failed: {failed}"
            )

        # Return as list[list[str]] so it is JSON-serialisable for XCom
        return [[job_name, run_id] for job_name, run_id in runs]

    @task()
    def run_glue_bronze_to_silver(_r2b_runs: list[list[str]]) -> None:
        """Start bronze→silver Glue job for every FAOSTAT commodity in parallel, then poll."""
        glue = boto3.client("glue", region_name=AWS_REGION)
        runs: list[tuple[str, str]] = []

        def _start(commodity: str) -> tuple[str, str]:
            run_id = glue.start_job_run(
                JobName=B2S_GLUE_JOB,
                Arguments={"--commodity": commodity},
            )["JobRunId"]
            return B2S_GLUE_JOB, run_id

        with ThreadPoolExecutor(max_workers=min(len(FAOSTAT_COMMODITIES), 20)) as pool:
            futures = [pool.submit(_start, c) for c in FAOSTAT_COMMODITIES]
            for f in as_completed(futures):
                runs.append(f.result())

        statuses = _poll_glue(glue, runs)
        failed = [rid for rid, s in statuses.items() if s != "SUCCEEDED"]
        if failed:
            raise RuntimeError(
                f"{len(failed)} bronze→silver FAOSTAT Glue runs failed: {failed}"
            )

    r2b_runs = run_glue_raw_to_bronze()
    run_glue_bronze_to_silver(r2b_runs)


faostat_production_ingest_dag()
