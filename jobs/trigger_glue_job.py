"""Trigger an AWS Glue job run and poll until it finishes.

Usage
-----
python jobs/trigger_glue_job.py \\
    --job-name leviathan-dev-raw-to-bronze-nasa-power \\
    --commodity cocoa \\
    --ingest-date 2026-05-12

Any extra --key value pairs after the known flags are forwarded as Glue job
arguments (with the leading -- added automatically if absent).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).parent))
from glue_utils import poll_glue_runs


POLL_INTERVAL_SECONDS = 15
TERMINAL_STATES = {"SUCCEEDED", "FAILED", "STOPPED", "ERROR", "TIMEOUT"}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Trigger and poll a Glue job run.")
    parser.add_argument("--job-name", required=True, help="Name of the Glue job.")
    parser.add_argument("--commodity", default="cocoa", help="Commodity parameter (default: cocoa).")
    parser.add_argument("--bucket", default="leviathan-dev-shahem-001", help="S3 bucket.")
    parser.add_argument("--aws-region", default="us-east-1", help="AWS region.")
    parser.add_argument("--ingest-date", default=None, help="Override ingest date (YYYY-MM-DD).")
    parser.add_argument("--s3-raw-key", default=None, help="S3 raw key (for FAOSTAT job).")
    return parser


def main() -> None:
    parser = build_arg_parser()

    # Split known args from extra passthrough args
    known, extra = parser.parse_known_args()

    glue_args: dict[str, str] = {
        "--JOB_NAME": known.job_name,
        "--commodity": known.commodity,
        "--bucket": known.bucket,
        "--aws_region": known.aws_region,
    }

    if known.ingest_date:
        glue_args["--ingest_date"] = known.ingest_date

    if known.s3_raw_key:
        glue_args["--s3_raw_key"] = known.s3_raw_key

    # Forward extra key=value pairs
    i = 0
    while i < len(extra):
        key = extra[i]
        if not key.startswith("--"):
            key = f"--{key}"
        if i + 1 < len(extra) and not extra[i + 1].startswith("--"):
            glue_args[key] = extra[i + 1]
            i += 2
        else:
            glue_args[key] = "true"
            i += 1

    glue = boto3.client("glue", region_name=known.aws_region)

    print(f"Starting Glue job: {known.job_name}")
    print(f"Arguments: {glue_args}")

    response = glue.start_job_run(JobName=known.job_name, Arguments=glue_args)
    run_id = response["JobRunId"]
    print(f"Job run ID: {run_id}")

    results = poll_glue_runs(glue, {run_id: known.job_name}, POLL_INTERVAL_SECONDS, TERMINAL_STATES)
    state = results[run_id]
    if state == "SUCCEEDED":
        print(f"Job succeeded: {known.job_name} ({run_id})")
        sys.exit(0)
    else:
        detail = glue.get_job_run(JobName=known.job_name, RunId=run_id)
        error_msg = detail["JobRun"].get("ErrorMessage", "(no error message)")
        print(f"Job {state}: {known.job_name} ({run_id})\n{error_msg}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
