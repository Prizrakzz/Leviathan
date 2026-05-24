"""Submit CPC Soil Moisture raw → bronze as AWS Batch Fargate tasks.

One task per year.  Each job reads ALL commodity region configs from S3 and
extracts per-region pixel values into bronze Parquet for all commodities,
reading each raw TIF only once.

Raw S3 files must already exist (run submit_batch_cpc_to_raw.py first).

Usage:
    python jobs/submit_batch_cpc_raw_to_bronze.py
    python jobs/submit_batch_cpc_raw_to_bronze.py --start-year 2020
    python jobs/submit_batch_cpc_raw_to_bronze.py --dry-run
    python jobs/submit_batch_cpc_raw_to_bronze.py --start-year 2024 --end-year 2024  # single-year smoke test
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import date
from pathlib import Path

from leviathan.common.batch_submit import submit_batch_jobs, write_run_record
from leviathan.common.config import get_required_env, load_env
from leviathan.common.constants import CPC_SOIL_MOISTURE_START_YEAR
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_batch_cpc_raw_to_bronze")


def build_tasks(
    start_year: int,
    end_year: int,
    variable: str,
) -> list[dict]:
    return [
        {"year": str(y), "variable": variable}
        for y in range(start_year, end_year + 1)
    ]


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
        build_job_name=lambda t: f"cpc-soil-bronze-{t['variable']}-{t['year']}",
        aws_region=aws_region,
        dry_run=dry_run,
    )


def save_run_record(
    submitted: list[dict],
    start_year: int,
    end_year: int,
    variable: str,
) -> None:
    run_id  = utc_now_iso().replace(":", "-")
    payload = {
        "run_id":     run_id,
        "source":     "cpc_soil",
        "variable":   variable,
        "start_year": start_year,
        "end_year":   end_year,
        "task_count": len(submitted),
        "tasks":      submitted,
    }
    write_run_record(Path("data/batch_runs") / f"cpc_raw_to_bronze_{run_id}.json", payload)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()

    env     = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    batch_queue = f"{project}-{env}-queue"
    job_def     = f"{project}-{env}-cpc-soil-raw-to-bronze"

    parser = argparse.ArgumentParser(
        description="Submit CPC raw → bronze as AWS Batch tasks (one per year, all commodities)."
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=CPC_SOIL_MOISTURE_START_YEAR,
        help=f"First year (default: {CPC_SOIL_MOISTURE_START_YEAR}).",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=None,
        help="Last year (default: current year).",
    )
    parser.add_argument(
        "--variable",
        default="w",
        help="CPC variable prefix (default: w).",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    bucket     = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    end_year = args.end_year if args.end_year is not None else date.today().year
    tasks = build_tasks(args.start_year, end_year, args.variable)

    logger.info(
        "Submitting %d tasks  queue=%s  definition=%s  variable=%s  dry_run=%s",
        len(tasks), batch_queue, job_def, args.variable, args.dry_run,
    )

    submitted = submit_tasks(
        tasks=tasks,
        job_queue=batch_queue,
        job_definition=job_def,
        bucket=bucket,
        aws_region=aws_region,
        dry_run=args.dry_run,
    )

    save_run_record(submitted, args.start_year, end_year, args.variable)
    logger.info(
        "Done  submitted=%d  start_year=%d  end_year=%d",
        len(submitted), args.start_year, end_year,
    )


if __name__ == "__main__":
    main()
