"""Submit CHIRPS bronze → silver as AWS Batch Fargate tasks.

One task per commodity (31 total).  All run concurrently — each job reads
all bronze files for one commodity, applies the silver transform, and writes
per-partition silver Parquet files.  Skips existing silver partitions.

Bypasses Glue entirely — safe to run even when the Glue account quota is
restricted.

Usage:
    python jobs/submit_batch_b2s_chirps.py
    python jobs/submit_batch_b2s_chirps.py --commodities arabica_coffee,corn_cbot
    python jobs/submit_batch_b2s_chirps.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import boto3

from leviathan.common.config import get_required_env, load_env
from leviathan.common.constants import ALL_COMMODITIES
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_batch_b2s_chirps")

# ---------------------------------------------------------------------------
# Derived constants (overridable via env vars)
# ---------------------------------------------------------------------------

LEVIATHAN_ENV = os.environ.get("LEVIATHAN_ENV", "dev")
PROJECT       = os.environ.get("LEVIATHAN_PROJECT", "leviathan")

BATCH_QUEUE  = f"{PROJECT}-{LEVIATHAN_ENV}-queue"
B2S_JOB_DEF  = f"{PROJECT}-{LEVIATHAN_ENV}-chirps-bronze-to-silver"


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------

def submit_tasks(
    commodities: list[str],
    job_queue: str,
    job_definition: str,
    bucket: str,
    aws_region: str,
    dry_run: bool,
) -> list[dict]:
    client = boto3.client("batch", region_name=aws_region)
    submitted: list[dict] = []

    for commodity in commodities:
        job_name = f"chirps-b2s-{commodity}".replace("_", "-")
        parameters = {
            "commodity":  commodity,
            "bucket":     bucket,
            "aws_region": aws_region,
        }

        if dry_run:
            logger.info("[DRY RUN] Would submit: %s  params=%s", job_name, parameters)
            submitted.append({"job_name": job_name, "parameters": parameters, "job_id": None})
            continue

        response = client.submit_job(
            jobName=job_name,
            jobQueue=job_queue,
            jobDefinition=job_definition,
            parameters=parameters,
        )
        job_id = response["jobId"]
        logger.info("Submitted  job_name=%s  job_id=%s", job_name, job_id)
        submitted.append({"job_name": job_name, "parameters": parameters, "job_id": job_id})

    return submitted


# ---------------------------------------------------------------------------
# Run record
# ---------------------------------------------------------------------------

def save_run_record(submitted: list[dict], commodities: list[str]) -> None:
    run_id     = utc_now_iso().replace(":", "-")
    output_dir = Path("data/batch_runs")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"chirps_b2s_{run_id}.json"
    payload = {
        "run_id":      run_id,
        "source":      "chirps",
        "stage":       "bronze_to_silver",
        "commodities": commodities,
        "task_count":  len(submitted),
        "tasks":       submitted,
    }
    output_path.write_text(json.dumps(payload, indent=2))
    logger.info("Run record saved to %s", output_path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    load_env()

    parser = argparse.ArgumentParser(
        description="Submit CHIRPS bronze→silver as AWS Batch Fargate tasks."
    )
    parser.add_argument(
        "--commodities",
        default="all",
        help='Comma-separated list or "all" (default).',
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    bucket     = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    commodities: list[str] = (
        list(ALL_COMMODITIES)
        if args.commodities.strip().lower() == "all"
        else [c.strip() for c in args.commodities.split(",")]
    )
    unknown = [c for c in commodities if c not in ALL_COMMODITIES]
    if unknown:
        raise SystemExit(f"ERROR: Unknown commodities: {unknown}")

    logger.info(
        "Submitting %d tasks  queue=%s  definition=%s  dry_run=%s",
        len(commodities), BATCH_QUEUE, B2S_JOB_DEF, args.dry_run,
    )

    submitted = submit_tasks(
        commodities=commodities,
        job_queue=BATCH_QUEUE,
        job_definition=B2S_JOB_DEF,
        bucket=bucket,
        aws_region=aws_region,
        dry_run=args.dry_run,
    )

    if not args.dry_run:
        save_run_record(submitted, commodities)
        logger.info(
            "Done: %d/%d tasks submitted.",
            sum(1 for t in submitted if t["job_id"]),
            len(submitted),
        )
    else:
        logger.info("Dry run complete: %d tasks would be submitted.", len(submitted))


if __name__ == "__main__":
    main()
