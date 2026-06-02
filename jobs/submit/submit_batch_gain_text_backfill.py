"""Submit GAIN text-extraction backfill as 17 parallel AWS Batch Fargate tasks.

Each task covers one commodity source prefix.  All 17 run concurrently —
S3 list + pdfplumber extraction + document.json upload inside each container.

Reuses the ``leviathan-dev-gain-backfill`` job definition (same worker image,
same queue); the command is fully overridden via containerOverrides.

Usage
-----
    python jobs/submit/submit_batch_gain_text_backfill.py --dry-run
    python jobs/submit/submit_batch_gain_text_backfill.py
    python jobs/submit/submit_batch_gain_text_backfill.py --sources wheat corn
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

logger = get_logger("submit_batch_gain_text_backfill")

# ---------------------------------------------------------------------------
# Source definitions — one Batch task per entry
# ---------------------------------------------------------------------------

SOURCES: list[str] = [
    "usda_gain_cocoa",
    "usda_gain_coffee",
    "usda_gain_coffee_semiannual",
    "usda_gain_corn",
    "usda_gain_cotton",
    "usda_gain_cotton_monthly",
    "usda_gain_grain_monthly",
    "usda_gain_orange_juice",
    "usda_gain_palm_oil",
    "usda_gain_rapeseed",
    "usda_gain_rice",
    "usda_gain_soybean_meal",
    "usda_gain_soybean_oil",
    "usda_gain_soybeans",
    "usda_gain_sugar",
    "usda_gain_sugar_semiannual",
    "usda_gain_wheat",
]


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------

def submit_tasks(
    sources: list[str],
    job_queue: str,
    job_definition: str,
    bucket: str,
    aws_region: str,
    dry_run: bool,
) -> list[dict]:
    client = boto3.client("batch", region_name=aws_region)
    submitted: list[dict] = []

    for source in sources:
        job_name = f"gain-text-{source.replace('_', '-')}"
        command = [
            "jobs/batch/gain_text_task.py",
            "--source", source,
            "--bucket", bucket,
            "--aws-region", aws_region,
        ]

        if dry_run:
            logger.info("[DRY RUN] Would submit: %s  cmd=%s", job_name, command)
            submitted.append({"job_name": job_name, "job_id": None, "source": source})
            continue

        response = client.submit_job(
            jobName=job_name,
            jobQueue=job_queue,
            jobDefinition=job_definition,
            containerOverrides={
                "command": command,
                # Bump from 2 GB → 4 GB; 30 concurrent pdfplumber workers OOM at 2 GB
                "resourceRequirements": [
                    {"type": "VCPU",   "value": "1"},
                    {"type": "MEMORY", "value": "4096"},
                ],
            },
        )
        job_id = response["jobId"]
        logger.info("Submitted  job_name=%s  job_id=%s", job_name, job_id)
        submitted.append({"job_name": job_name, "job_id": job_id, "source": source})

    return submitted


def save_run_record(submitted: list[dict]) -> None:
    run_id = utc_now_iso().replace(":", "-")
    payload = {
        "run_id": run_id,
        "source": "usda_gain_text",
        "sources": [t["source"] for t in submitted],
        "task_count": len(submitted),
        "tasks": submitted,
    }
    write_run_record(Path("data/batch_runs") / f"gain_text_backfill_{run_id}.json", payload)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    load_env()

    env    = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    batch_queue    = f"{project}-{env}-queue"
    job_definition = f"{project}-{env}-gain-backfill"

    parser = argparse.ArgumentParser(
        description="Submit GAIN text-extraction backfill as 17 parallel Batch Fargate tasks."
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        metavar="SOURCE",
        default=None,
        help="Subset of source names to submit (default: all 17).",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    bucket     = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    sources = SOURCES
    if args.sources:
        unknown = set(args.sources) - set(SOURCES)
        if unknown:
            raise SystemExit(f"Unknown sources: {unknown}")
        sources = [s for s in SOURCES if s in args.sources]

    logger.info(
        "Submitting %d GAIN text tasks to queue=%s  job_def=%s",
        len(sources), batch_queue, job_definition,
    )

    submitted = submit_tasks(
        sources=sources,
        job_queue=batch_queue,
        job_definition=job_definition,
        bucket=bucket,
        aws_region=aws_region,
        dry_run=args.dry_run,
    )

    save_run_record(submitted)

    if not args.dry_run:
        logger.info("All %d jobs submitted.  Monitor via AWS Console → Batch → Jobs.", len(submitted))


if __name__ == "__main__":
    main()
