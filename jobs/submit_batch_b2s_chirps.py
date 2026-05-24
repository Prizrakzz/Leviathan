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
import logging
import os
from pathlib import Path

from leviathan.common.batch_submit import submit_batch_jobs, write_run_record
from leviathan.common.config import get_required_env, load_env
from leviathan.common.constants import ALL_COMMODITIES
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_batch_b2s_chirps")

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
    tasks = [
        {"commodity": c, "bucket": bucket, "aws_region": aws_region}
        for c in commodities
    ]
    return submit_batch_jobs(
        tasks=tasks,
        job_queue=job_queue,
        job_definition=job_definition,
        build_job_name=lambda t: f"chirps-b2s-{t['commodity']}".replace("_", "-"),
        aws_region=aws_region,
        dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# Run record
# ---------------------------------------------------------------------------

def save_run_record(submitted: list[dict], commodities: list[str]) -> None:
    run_id  = utc_now_iso().replace(":", "-")
    payload = {
        "run_id":      run_id,
        "source":      "chirps",
        "stage":       "bronze_to_silver",
        "commodities": commodities,
        "task_count":  len(submitted),
        "tasks":       submitted,
    }
    write_run_record(Path("data/batch_runs") / f"chirps_b2s_{run_id}.json", payload)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()

    env     = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    batch_queue = f"{project}-{env}-queue"
    b2s_job_def = f"{project}-{env}-chirps-bronze-to-silver"

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
        len(commodities), batch_queue, b2s_job_def, args.dry_run,
    )

    submitted = submit_tasks(
        commodities=commodities,
        job_queue=batch_queue,
        job_definition=b2s_job_def,
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
