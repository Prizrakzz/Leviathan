"""Submit SAGIS CEC raw backfill as 4 parallel AWS Batch Fargate tasks.

Each task covers a non-overlapping year range of the ~358-file archive
(PDF/DOC/XLS, 1999-present).  All 4 tasks run concurrently.

Usage
-----
    python jobs/submit/submit_batch_backfill_sagis_cec.py --dry-run
    python jobs/submit/submit_batch_backfill_sagis_cec.py
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

import boto3

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_batch_backfill_sagis_cec")

# ---------------------------------------------------------------------------
# Year-range task definitions — 4 parallel jobs
# Splits approximate equal file counts (~80-120 per chunk).
# year_from=None means no lower bound; year_to=None means no upper bound.
# ---------------------------------------------------------------------------

YEAR_RANGES: list[dict] = [
    {"name": "sagis-cec-backfill-pre-2009",  "year_from": None, "year_to": 2008},
    {"name": "sagis-cec-backfill-2009-2014", "year_from": 2009, "year_to": 2014},
    {"name": "sagis-cec-backfill-2015-2019", "year_from": 2015, "year_to": 2019},
    {"name": "sagis-cec-backfill-2020-plus", "year_from": 2020, "year_to": None},
]


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------

def submit_tasks(
    year_ranges: list[dict],
    job_queue: str,
    job_definition: str,
    aws_region: str,
    dry_run: bool,
) -> list[dict]:
    client = boto3.client("batch", region_name=aws_region)
    submitted: list[dict] = []

    for yr in year_ranges:
        job_name = yr["name"]
        command = ["jobs/ingest/fetch_sagis_cec.py", "--skip-existing-s3"]
        if yr["year_from"] is not None:
            command += ["--year-from", str(yr["year_from"])]
        if yr["year_to"] is not None:
            command += ["--year-to", str(yr["year_to"])]

        if dry_run:
            logger.info("[DRY RUN] Would submit: %s  cmd=%s", job_name, command)
            submitted.append({"job_name": job_name, "job_id": None, **yr})
            continue

        response = client.submit_job(
            jobName=job_name,
            jobQueue=job_queue,
            jobDefinition=job_definition,
            containerOverrides={"command": command},
        )
        job_id = response["jobId"]
        logger.info("Submitted  job_name=%s  job_id=%s", job_name, job_id)
        submitted.append({"job_name": job_name, "job_id": job_id, **yr})

    return submitted


def save_run_record(submitted: list[dict]) -> None:
    run_id = utc_now_iso().replace(":", "-")
    output_dir = Path("data/batch_runs")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"sagis_cec_backfill_{run_id}.json"
    payload = {
        "run_id": run_id,
        "source": "sagis_cec",
        "task_count": len(submitted),
        "tasks": submitted,
    }
    output_path.write_text(json.dumps(payload, indent=2))
    logger.info("Run record saved to %s", output_path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()

    env     = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    job_queue      = f"{project}-{env}-queue"
    job_definition = f"{project}-{env}-sagis-cec-raw-backfill"

    parser = argparse.ArgumentParser(
        description="Submit SAGIS CEC raw backfill as 4 parallel Batch Fargate tasks."
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    aws_region = get_required_env("AWS_REGION")

    logger.info(
        "Submitting %d SAGIS CEC backfill tasks to queue=%s  job_def=%s",
        len(YEAR_RANGES), job_queue, job_definition,
    )

    submitted = submit_tasks(
        year_ranges=YEAR_RANGES,
        job_queue=job_queue,
        job_definition=job_definition,
        aws_region=aws_region,
        dry_run=args.dry_run,
    )

    if not args.dry_run:
        save_run_record(submitted)
        logger.info("All %d tasks submitted.", len(submitted))
    else:
        logger.info("[DRY RUN] %d tasks would be submitted.", len(submitted))


if __name__ == "__main__":
    main()

