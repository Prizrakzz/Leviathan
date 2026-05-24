"""One-shot smoke test: start leviathan-dev-raw-to-bronze-usda-esr for
commodity 401 / year 2025 only, then poll until terminal state."""
import datetime
import time

import boto3

JOB_NAME = "leviathan-dev-raw-to-bronze-usda-esr"

glue = boto3.client("glue", region_name="us-east-1")

run = glue.start_job_run(
    JobName=JOB_NAME,
    Arguments={
        "--bucket":          "leviathan-dev-shahem-001",
        "--aws_region":      "us-east-1",
        "--ingest_date":     "2026-05-24",
        "--mode":            "backfill",
        "--commodity_codes": "401",
        "--start_year":      "2025",
        "--end_year":        "2025",
    },
)
run_id = run["JobRunId"]
print(f"Started  run_id={run_id}")

TERMINAL = {"SUCCEEDED", "FAILED", "ERROR", "STOPPED", "TIMEOUT"}

while True:
    time.sleep(15)
    detail = glue.get_job_run(JobName=JOB_NAME, RunId=run_id)
    state = detail["JobRun"]["JobRunState"]
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"  {ts}  state={state}")
    if state in TERMINAL:
        if state != "SUCCEEDED":
            err = detail["JobRun"].get("ErrorMessage", "")
            print(f"FAILED: {err}")
        else:
            print("Smoke test PASSED")
        break
