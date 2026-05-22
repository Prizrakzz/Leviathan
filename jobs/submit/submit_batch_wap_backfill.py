"""Submit USDA WAP raw backfill as 6 parallel AWS Batch Fargate tasks.

Each task covers a non-overlapping year range of the 287-entry manifest.
All 6 tasks run concurrently — fetch + S3 upload inside each container.
Expected wall clock: ~3-5 minutes total (vs 5-8 h sequential locally).

Usage
-----
    python jobs/submit/submit_batch_wap_backfill.py --dry-run
    python jobs/submit/submit_batch_wap_backfill.py
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import boto3

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_batch_wap_backfill")

# ---------------------------------------------------------------------------
# Year-range task definitions — 6 parallel jobs
# Splits chosen to keep each task ≤ ~53 manifest entries (~3-5 min each).
# 287 total entries (2002-08 to 2026-05), one gap at 2024-03.
# ---------------------------------------------------------------------------

YEAR_RANGES: list[dict] = [
    {"name": "wap-backfill-2002-2006", "year_from": 2002, "year_to": 2006},
    {"name": "wap-backfill-2007-2010", "year_from": 2007, "year_to": 2010},
    {"name": "wap-backfill-2011-2014", "year_from": 2011, "year_to": 2014},
    {"name": "wap-backfill-2015-2018", "year_from": 2015, "year_to": 2018},
    {"name": "wap-backfill-2019-2022", "year_from": 2019, "year_to": 2022},
    {"name": "wap-backfill-2023-2026", "year_from": 2023, "year_to": 2026},
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
        command = [
            "jobs/ingest/fetch_usda_wap.py",
            "--skip-existing-s3",
            "--year-from", str(yr["year_from"]),
            "--year-to",   str(yr["year_to"]),
            "--sleep-seconds", "1.5",
        ]

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
    output_path = output_dir / f"wap_backfill_{run_id}.json"
    payload = {
        "run_id": run_id,
        "source": "usda_wap",
        "task_count": len(submitted),
        "tasks": submitted,
    }
    output_path.write_text(json.dumps(payload, indent=2))
    logger.info("Run record saved to %s", output_path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    load_env()

    env     = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    job_queue      = f"{project}-{env}-queue"
    job_definition = f"{project}-{env}-usda-wap-raw-backfill"

    parser = argparse.ArgumentParser(
        description="Submit USDA WAP raw backfill as 6 parallel Batch Fargate tasks."
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    aws_region = get_required_env("AWS_REGION")

    logger.info(
        "Submitting %d WAP backfill tasks to queue=%s  job_def=%s",
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
