"""Submit CHIRPS COG → bronze as AWS Batch Fargate tasks.

One task per (commodity × year).  Uses the shared leviathan-{env}-queue.
Bypasses Glue entirely — safe to run even when the Glue account quota is
restricted.

Usage:
    python jobs/submit_batch_backfill_chirps.py --commodities all
    python jobs/submit_batch_backfill_chirps.py --commodities arabica_coffee,corn_cbot
    python jobs/submit_batch_backfill_chirps.py --commodities arabica_coffee --start-year 2020 --end-year 2025
    python jobs/submit_batch_backfill_chirps.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import date
from pathlib import Path

from leviathan.common.batch_submit import submit_batch_jobs, write_run_record
from leviathan.common.config import get_required_env, load_env
from leviathan.common.constants import ALL_COMMODITIES, CHIRPS_START_YEAR
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_batch_backfill_chirps")

# ---------------------------------------------------------------------------
# Task building
# ---------------------------------------------------------------------------

def build_tasks(
    commodities: list[str],
    start_year: int,
    end_year: int,
    force_overwrite: bool = False,
) -> list[dict]:
    """Return one task dict per (commodity, year)."""
    return [
        {"commodity": c, "year": str(y), "force_overwrite": "true" if force_overwrite else "false"}
        for c in commodities
        for y in range(start_year, end_year + 1)
    ]


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------

def submit_tasks(
    tasks: list[dict],
    job_queue: str,
    job_definition: str,
    bucket: str,
    aws_region: str,
    dry_run: bool,
) -> list[dict]:
    enriched = [
        {**t, "bucket": bucket, "aws_region": aws_region}
        for t in tasks
    ]
    return submit_batch_jobs(
        tasks=enriched,
        job_queue=job_queue,
        job_definition=job_definition,
        build_job_name=lambda t: f"chirps-bronze-{t['commodity']}-{t['year']}".replace("_", "-"),
        aws_region=aws_region,
        dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# Run record
# ---------------------------------------------------------------------------

def save_run_record(
    submitted: list[dict],
    commodities: list[str],
    start_year: int,
    end_year: int,
) -> None:
    run_id  = utc_now_iso().replace(":", "-")
    payload = {
        "run_id":      run_id,
        "source":      "chirps",
        "commodities": commodities,
        "start_year":  start_year,
        "end_year":    end_year,
        "task_count":  len(submitted),
        "tasks":       submitted,
    }
    write_run_record(Path("data/batch_runs") / f"chirps_backfill_{run_id}.json", payload)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()

    env     = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    batch_queue = f"{project}-{env}-queue"
    c2b_job_def = f"{project}-{env}-chirps-to-bronze-backfill"

    parser = argparse.ArgumentParser(
        description="Submit CHIRPS COG→bronze as AWS Batch Fargate tasks."
    )
    parser.add_argument(
        "--commodities",
        default="all",
        help='Comma-separated list or "all" (default).',
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=CHIRPS_START_YEAR,
        help=f"First year to ingest (default: {CHIRPS_START_YEAR}).",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=None,
        help="Last year to ingest (default: current year).",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--force-overwrite", action="store_true", dest="force_overwrite",
        help="Overwrite existing bronze S3 objects (required when re-ingesting null data).",
    )
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

    end_year = args.end_year if args.end_year is not None else date.today().year
    tasks    = build_tasks(commodities, args.start_year, end_year, args.force_overwrite)

    logger.info(
        "Submitting %d tasks  queue=%s  definition=%s  dry_run=%s",
        len(tasks), batch_queue, c2b_job_def, args.dry_run,
    )

    submitted = submit_tasks(
        tasks=tasks,
        job_queue=batch_queue,
        job_definition=c2b_job_def,
        bucket=bucket,
        aws_region=aws_region,
        dry_run=args.dry_run,
    )

    if not args.dry_run:
        save_run_record(submitted, commodities, args.start_year, end_year)
        logger.info(
            "Done: %d/%d tasks submitted.",
            sum(1 for t in submitted if t["job_id"]),
            len(tasks),
        )
    else:
        logger.info("Dry run complete: %d tasks would be submitted.", len(tasks))


if __name__ == "__main__":
    main()
