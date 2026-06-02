"""Submit text_to_graphrag Batch tasks (Phase 0).

Submits one AWS Batch Fargate Spot job per (source, year-band) combination.
By default submits all years for both usda_wasde and usda_wap.

Usage
-----
    # Smoke test — 2021 only for both sources
    python jobs/submit/submit_batch_text_to_graphrag.py --smoke-test --dry-run
    python jobs/submit/submit_batch_text_to_graphrag.py --smoke-test

    # Full run — all years
    python jobs/submit/submit_batch_text_to_graphrag.py --dry-run
    python jobs/submit/submit_batch_text_to_graphrag.py

    # Single source
    python jobs/submit/submit_batch_text_to_graphrag.py --source usda_wasde
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import boto3

from leviathan.common.batch_submit import write_run_record
from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_batch_text_to_graphrag")


# ---------------------------------------------------------------------------
# Task definitions
# Each dict becomes one Batch job.  Year ranges are wide — the task itself
# does idempotency checking at the (source, year, month) partition level.
# ---------------------------------------------------------------------------

_ALL_TASKS: list[dict] = [
    # usda_wasde — 616 documents spanning 1973-2025
    {"source": "usda_wasde", "year_from": 2000, "year_to": 2010},
    {"source": "usda_wasde", "year_from": 2011, "year_to": 2018},
    {"source": "usda_wasde", "year_from": 2019, "year_to": 2025},
    # usda_wap — 448 documents spanning 2002-2025
    {"source": "usda_wap",   "year_from": 2002, "year_to": 2012},
    {"source": "usda_wap",   "year_from": 2013, "year_to": 2019},
    {"source": "usda_wap",   "year_from": 2020, "year_to": 2025},
    {"source": "fnc",        "year_from": 2023, "year_to": 2026},
]

_SMOKE_TASKS: list[dict] = [
    {"source": "usda_wasde", "year_from": 2021, "year_to": 2021},
    {"source": "usda_wap",   "year_from": 2021, "year_to": 2021},
    {"source": "fnc",        "year_from": 2025, "year_to": 2025},
]


def _job_name(task: dict) -> str:
    return (
        f"graphrag-{task['source'].replace('_', '-')}-"
        f"{task['year_from']}-{task['year_to']}"
    )


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------

def submit_tasks(
    tasks: list[dict],
    job_queue: str,
    job_definition: str,
    aws_region: str,
    force_overwrite: bool,
    dry_run: bool,
) -> list[dict]:
    client = boto3.client("batch", region_name=aws_region)
    submitted: list[dict] = []

    for task in tasks:
        job_name = _job_name(task)
        parameters = {
            "source":          task["source"],
            "year_from":       str(task["year_from"]),
            "year_to":         str(task["year_to"]),
            "force_overwrite": "true" if force_overwrite else "false",
        }

        if dry_run:
            logger.info(
                "[DRY RUN] Would submit: %s  params=%s",
                job_name, parameters,
            )
            submitted.append({"job_name": job_name, "job_id": None, **task})
            continue

        response = client.submit_job(
            jobName=job_name,
            jobQueue=job_queue,
            jobDefinition=job_definition,
            parameters=parameters,
        )
        job_id = response["jobId"]
        logger.info("Submitted  job_name=%s  job_id=%s", job_name, job_id)
        submitted.append({"job_name": job_name, "job_id": job_id, **task})

    return submitted


def save_run_record(submitted: list[dict], label: str) -> None:
    run_id = utc_now_iso().replace(":", "-")
    payload = {
        "run_id":     run_id,
        "label":      label,
        "task_count": len(submitted),
        "tasks":      submitted,
    }
    write_run_record(
        Path("data/batch_runs") / f"text_to_graphrag_{label}_{run_id}.json",
        payload,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    load_env()

    env     = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    job_queue      = f"{project}-{env}-queue"
    job_definition = f"{project}-{env}-text-to-graphrag"

    parser = argparse.ArgumentParser(
        description="Submit text_to_graphrag Batch Fargate Spot tasks"
    )
    parser.add_argument(
        "--source",
        choices=["usda_wasde", "usda_wap", "fnc", "all"],
        default="all",
        help="Limit submission to a single source (default: all)",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Submit only 2021 partitions for both sources (quick validation)",
    )
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        help="Re-extract even if partition Parquet already exists",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    aws_region = get_required_env("AWS_REGION")

    if args.smoke_test:
        tasks = _SMOKE_TASKS
        label = "smoke"
    else:
        tasks = _ALL_TASKS
        label = "full"

    if args.source != "all":
        tasks = [t for t in tasks if t["source"] == args.source]

    logger.info(
        "Submitting %d text_to_graphrag tasks  queue=%s  job_def=%s  force=%s",
        len(tasks), job_queue, job_definition, args.force_overwrite,
    )

    submitted = submit_tasks(
        tasks=tasks,
        job_queue=job_queue,
        job_definition=job_definition,
        aws_region=aws_region,
        force_overwrite=args.force_overwrite,
        dry_run=args.dry_run,
    )

    if not args.dry_run:
        save_run_record(submitted, label)
        logger.info("All %d tasks submitted.", len(submitted))
    else:
        logger.info("[DRY RUN] %d tasks would be submitted.", len(submitted))


if __name__ == "__main__":
    main()
