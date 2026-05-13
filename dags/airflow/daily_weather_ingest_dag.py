"""Daily weather ingest DAG — NASA POWER → raw → bronze → silver.

Runs at midnight UTC. Fetches yesterday's data for all 31 commodities across
every (country, region) pair defined in each commodity's geography YAML.

Pipeline
--------
submit_batch_tasks  →  wait_for_batch
  →  run_glue_raw_to_bronze  →  run_glue_bronze_to_silver

Design notes
------------
- Pure boto3; no airflow-providers-amazon dependency.
- Polling loops live inside each @task so the DAG needs no custom sensors.
- LocalExecutor is assumed (tasks execute in the same container as the
  scheduler, i.e., the Fargate task running Airflow).
- Geography configs are read from configs/geographies/ relative to /app
  (WORKDIR set in the Docker image).
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import boto3
from airflow.decorators import dag, task
from airflow.utils.dates import days_ago

from leviathan.common.constants import ALL_COMMODITIES
from leviathan.common.polling import poll_batch_jobs, poll_glue_runs

# ---------------------------------------------------------------------------
# Config — resolved from environment variables at import time
# ---------------------------------------------------------------------------

AWS_REGION    = os.environ.get("AWS_REGION", "us-east-1")
LEVIATHAN_ENV = os.environ.get("LEVIATHAN_ENV", "dev")
PROJECT       = os.environ.get("LEVIATHAN_PROJECT", "leviathan")

JOB_QUEUE      = f"{PROJECT}-{LEVIATHAN_ENV}-queue"
JOB_DEFINITION = f"{PROJECT}-{LEVIATHAN_ENV}-nasa-power-backfill"
R2B_GLUE_JOB   = f"{PROJECT}-{LEVIATHAN_ENV}-raw-to-bronze-nasa-power"
B2S_GLUE_JOB   = f"{PROJECT}-{LEVIATHAN_ENV}-bronze-to-silver-nasa-power"

POLL_INTERVAL = 30  # seconds between polling calls

# ---------------------------------------------------------------------------
# Internal helpers (not Airflow tasks)
# ---------------------------------------------------------------------------

def _load_yaml(path: str) -> dict:
    import yaml
    with open(path) as fh:
        return yaml.safe_load(fh)


# ---------------------------------------------------------------------------
# DAG definition
# ---------------------------------------------------------------------------

@dag(
    dag_id="daily_weather_ingest",
    description="Ingest yesterday's NASA POWER data for all commodities and regions.",
    schedule="@daily",
    start_date=days_ago(1),
    catchup=False,
    tags=["leviathan", "weather", "nasa-power"],
)
def daily_weather_ingest_dag() -> None:

    @task()
    def submit_batch_tasks() -> list[str]:
        """Submit one Batch task per (commodity, country, region) for yesterday."""
        yesterday = date.today() - timedelta(days=1)
        ingest_year = str(yesterday.year)

        batch = boto3.client("batch", region_name=AWS_REGION)
        job_ids: list[str] = []

        for commodity in ALL_COMMODITIES:
            cfg = _load_yaml(f"configs/geographies/{commodity}_regions.yaml")
            for country_block in cfg.get("regions", []):
                country = country_block["country"]
                for loc in country_block.get("locations", []):
                    region = loc["region"]
                    # Batch job names: max 128 chars, must match [a-zA-Z0-9_-]
                    job_name = (
                        f"daily-{commodity}-{country}-{region}-{ingest_year}"
                        .replace("_", "-")
                    )[:128]
                    resp = batch.submit_job(
                        jobName=job_name,
                        jobQueue=JOB_QUEUE,
                        jobDefinition=JOB_DEFINITION,
                        parameters={
                            "commodity":  commodity,
                            "country":    country,
                            "region":     region,
                            "start_year": ingest_year,
                            "end_year":   ingest_year,
                        },
                    )
                    job_ids.append(resp["jobId"])

        return job_ids

    @task()
    def wait_for_batch(job_ids: list[str]) -> dict[str, str]:
        """Poll Batch until every job is terminal. Raise on any failure."""
        batch = boto3.client("batch", region_name=AWS_REGION)
        results = poll_batch_jobs(batch, job_ids, poll_interval=POLL_INTERVAL)
        failed = [jid for jid, s in results.items() if s != "SUCCEEDED"]
        if failed:
            raise RuntimeError(
                f"{len(failed)} Batch tasks failed (first 5: {failed[:5]})"
            )
        return results

    @task()
    def run_glue_raw_to_bronze(_batch_results: dict[str, str]) -> list[list[str]]:
        """Start raw→bronze Glue job for every commodity in parallel, then poll."""
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        glue = boto3.client("glue", region_name=AWS_REGION)
        runs: list[tuple[str, str]] = []

        def _start(commodity: str) -> tuple[str, str]:
            run_id = glue.start_job_run(
                JobName=R2B_GLUE_JOB,
                Arguments={"--commodity": commodity, "--ingest_date": yesterday},
            )["JobRunId"]
            return R2B_GLUE_JOB, run_id

        with ThreadPoolExecutor(max_workers=min(len(ALL_COMMODITIES), 50)) as pool:
            futures = [pool.submit(_start, c) for c in ALL_COMMODITIES]
            for f in as_completed(futures):
                runs.append(f.result())

        statuses = poll_glue_runs(glue, runs, poll_interval=POLL_INTERVAL)
        failed = [rid for rid, s in statuses.items() if s != "SUCCEEDED"]
        if failed:
            raise RuntimeError(f"{len(failed)} raw→bronze Glue runs failed.")

        # Return as list[list[str]] so it is JSON-serialisable for XCom
        return [[job_name, run_id] for job_name, run_id in runs]

    @task()
    def run_glue_bronze_to_silver(_r2b_runs: list[list[str]]) -> None:
        """Start bronze→silver Glue job for every commodity in parallel, then poll."""
        glue = boto3.client("glue", region_name=AWS_REGION)
        runs: list[tuple[str, str]] = []

        def _start(commodity: str) -> tuple[str, str]:
            run_id = glue.start_job_run(
                JobName=B2S_GLUE_JOB,
                Arguments={"--commodity": commodity},
            )["JobRunId"]
            return B2S_GLUE_JOB, run_id

        with ThreadPoolExecutor(max_workers=min(len(ALL_COMMODITIES), 50)) as pool:
            futures = [pool.submit(_start, c) for c in ALL_COMMODITIES]
            for f in as_completed(futures):
                runs.append(f.result())

        statuses = poll_glue_runs(glue, runs, poll_interval=POLL_INTERVAL)
        failed = [rid for rid, s in statuses.items() if s != "SUCCEEDED"]
        if failed:
            raise RuntimeError(f"{len(failed)} bronze→silver Glue runs failed.")

    # Wire the task dependencies
    job_ids      = submit_batch_tasks()
    batch_done   = wait_for_batch(job_ids)
    r2b_runs     = run_glue_raw_to_bronze(batch_done)
    run_glue_bronze_to_silver(r2b_runs)


daily_weather_ingest_dag()
