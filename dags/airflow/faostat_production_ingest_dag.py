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
- FAOSTAT has no Batch worker step — raw data is a single shared ZIP uploaded
  manually (or via upload_raw_faostat_qcl.py) to S3 before this DAG runs.
- All commodities share one raw S3 key:
    raw/production/source=faostat/dataset=QCL/Production_Crops_Livestock_E_All_Data_Normalized.zip
- The Glue raw→bronze job receives --fao_item_name (exact FAO CSV "Item" string)
  and filters the ZIP to only that item's rows.
- FAO item strings are loaded at import time from configs/sources/faostat_item_map.yaml.
- Pure boto3; no airflow-providers-amazon dependency.
- Polling loops live inside each @task.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import boto3
import yaml
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

# ---------------------------------------------------------------------------
# Load commodity → FAO item name mapping
# ---------------------------------------------------------------------------

_ITEM_MAP_PATH = (
    Path(__file__).parents[2] / "configs" / "sources" / "faostat_item_map.yaml"
)
with _ITEM_MAP_PATH.open() as _f:
    FAOSTAT_ITEM_MAP: dict[str, str] = yaml.safe_load(_f)

FAOSTAT_COMMODITIES: list[str] = list(FAOSTAT_ITEM_MAP.keys())

# Single shared ZIP for all commodities.
FAOSTAT_RAW_S3_KEY = (
    "raw/production/source=faostat/dataset=QCL/"
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
            run_id = glue.start_job_run(
                JobName=R2B_GLUE_JOB,
                Arguments={
                    "--commodity":      commodity,
                    "--fao_item_name": FAOSTAT_ITEM_MAP[commodity],
                    "--ingest_date":   ingest_date,
                    "--s3_raw_key":    FAOSTAT_RAW_S3_KEY,
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
