"""GAIN monthly ingest DAG — USDA FAS GAIN → raw (S3 PDFs).

Runs on the 1st of each month at 06:00 UTC. Submits one Batch Fargate task
per source; each task crawls the rolling window (current_year-1 to
current_year+1) so new reports land in S3 within ~24 h of publication.

All 6 sources run every month — semi-annuals are idempotent (skip_existing_s3
skips already-uploaded PDFs) so running them monthly adds no cost beyond the
cheap S3 HEAD check.

Pipeline
--------
submit_gain_batch_tasks  →  wait_for_batch

Design notes
------------
- Pure boto3; no airflow-providers-amazon dependency.
- LocalExecutor assumed (tasks execute inside the Airflow Fargate container).
- upload-workers wired per source: 8 for monthly crawls, 4 for semi-annuals.
- skip_existing_s3 is always set → reruns are fully idempotent.
"""
from __future__ import annotations

import os
from datetime import datetime

import boto3
from airflow.decorators import dag, task
from airflow.utils.dates import days_ago

from leviathan.common.polling import poll_batch_jobs

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AWS_REGION    = os.environ.get("AWS_REGION", "us-east-1")
LEVIATHAN_ENV = os.environ.get("LEVIATHAN_ENV", "dev")
PROJECT       = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
BUCKET        = os.environ.get("LEVIATHAN_BUCKET", f"{PROJECT}-{LEVIATHAN_ENV}-shahem-001")

JOB_QUEUE      = f"{PROJECT}-{LEVIATHAN_ENV}-queue"
JOB_DEFINITION = f"{PROJECT}-{LEVIATHAN_ENV}-gain-backfill"

POLL_INTERVAL = 60  # seconds between polling calls

# ---------------------------------------------------------------------------
# Source definitions for the monthly ingest
# ---------------------------------------------------------------------------
# Each entry maps to a single Batch task. Countries match the backfill config.
# workers: number of concurrent PDF download threads inside the container.

_SOURCES: list[dict] = [
    {
        "name": "grain_monthly",
        "countries": "US,FR,AU,CA,UA,RU,IN,PK,EG,AR,CN,DE,PL,TR,BR,ZA,TH,VN,PH,NG",
        "title_filter": "grain and feed update",
        "workers": 8,
    },
    {
        "name": "oilseeds_semiannual",
        "countries": "BR,AR,US,CN,IN,ID,MY,TH,PY,BO,UA,CA,AU,FR,DE,NL",
        "title_filter": "oilseeds and products semi-annual",
        "workers": 8,
    },
    {
        "name": "sugar_semiannual",
        "countries": "BR,IN,TH,AU,CO,MX,ID,PH,EC,PK,ZA,CN",
        "title_filter": "sugar semi-annual",
        "workers": 4,
    },
    {
        "name": "cotton_monthly",
        "countries": "US,IN,CN,BR,AU,PK,UZ,TR",
        "title_filter": "cotton and products update",
        "workers": 8,
    },
    {
        "name": "coffee_semiannual",
        "countries": "BR,CO,VN,ET,ID,HN,GT,PE,MX,UG,IN,TZ,KE,CI,CM",
        "title_filter": "coffee semi-annual",
        "workers": 4,
    },
    {
        "name": "cocoa_semiannual",
        "countries": "CI,GH,CM,NG,ID,EC,PE,BR,DO",
        "title_filter": "cocoa semi-annual",
        "workers": 4,
    },
]


# ---------------------------------------------------------------------------
# DAG definition
# ---------------------------------------------------------------------------

@dag(
    dag_id="gain_monthly_ingest",
    description="Monthly USDA FAS GAIN PDF ingest for grain, oilseeds, sugar, cotton, coffee, and cocoa.",
    schedule="0 6 1 * *",
    start_date=days_ago(1),
    catchup=False,
    tags=["leviathan", "gain", "usda"],
)
def gain_monthly_ingest_dag() -> None:

    @task()
    def submit_gain_batch_tasks() -> list[str]:
        """Submit one Batch task per GAIN source for the rolling ±1 year window."""
        current_year = datetime.utcnow().year
        start_year = current_year - 1
        end_year = current_year + 1

        batch = boto3.client("batch", region_name=AWS_REGION)
        job_ids: list[str] = []

        for src in _SOURCES:
            job_name = f"gain-monthly-{src['name'].replace('_', '-')}"
            command = [
                "jobs/batch/gain_backfill_task.py",
                "--commodity-name",    src["name"],
                "--target-countries",  src["countries"],
                "--title-filter",      src["title_filter"],
                "--start-year",        str(start_year),
                "--end-year",          str(end_year),
                "--bucket",            BUCKET,
                "--aws-region",        AWS_REGION,
                "--skip-existing-s3",
                "--sleep-seconds",     "1.0",
                "--upload-workers",    str(src["workers"]),
            ]
            resp = batch.submit_job(
                jobName=job_name,
                jobQueue=JOB_QUEUE,
                jobDefinition=JOB_DEFINITION,
                containerOverrides={"command": command},
            )
            job_ids.append(resp["jobId"])

        return job_ids

    @task()
    def wait_for_batch(job_ids: list[str]) -> dict[str, str]:
        """Poll Batch until every GAIN task is terminal. Raise on any failure."""
        batch = boto3.client("batch", region_name=AWS_REGION)
        results = poll_batch_jobs(batch, job_ids, poll_interval=POLL_INTERVAL)
        failed = [jid for jid, s in results.items() if s != "SUCCEEDED"]
        if failed:
            raise RuntimeError(
                f"{len(failed)} GAIN Batch tasks failed (first 5: {failed[:5]})"
            )
        return results

    job_ids = submit_gain_batch_tasks()
    wait_for_batch(job_ids)


gain_monthly_ingest_dag()
