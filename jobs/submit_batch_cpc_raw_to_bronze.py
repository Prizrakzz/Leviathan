"""Submit CPC Soil Moisture raw → bronze as AWS Batch Fargate tasks.

One task per (commodity × year).  Each job reads raw CPC GeoTIFF files from S3
for that year and extracts per-region pixel values into bronze Parquet.

Raw S3 files must already exist (run submit_batch_cpc_to_raw.py first).

Usage:
    python jobs/submit_batch_cpc_raw_to_bronze.py
    python jobs/submit_batch_cpc_raw_to_bronze.py --commodities corn_cbot,soybeans_cbot
    python jobs/submit_batch_cpc_raw_to_bronze.py --commodities all --start-year 2020
    python jobs/submit_batch_cpc_raw_to_bronze.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

import boto3

from leviathan.common.config import get_required_env, load_env
from leviathan.common.constants import ALL_COMMODITIES, CPC_SOIL_MOISTURE_START_YEAR
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_batch_cpc_raw_to_bronze")


def build_tasks(
    commodities: list[str],
    start_year: int,
    end_year: int,
    variable: str,
) -> list[dict]:
    return [
        {"commodity": c, "year": str(y), "variable": variable}
        for c in commodities
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
    client = boto3.client("batch", region_name=aws_region)
    submitted: list[dict] = []

    for task in tasks:
        job_name = (
            f"cpc-soil-bronze-{task['commodity']}-{task['variable']}-{task['year']}"
            .replace("_", "-")
        )
        parameters = {
            "commodity":  task["commodity"],
            "year":       task["year"],
            "variable":   task["variable"],
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


def save_run_record(
    submitted: list[dict],
    commodities: list[str],
    start_year: int,
    end_year: int,
    variable: str,
) -> None:
    run_id = utc_now_iso().replace(":", "-")
    output_dir = Path("data/batch_runs")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"cpc_raw_to_bronze_{run_id}.json"
    payload = {
        "run_id":      run_id,
        "source":      "cpc_soil",
        "variable":    variable,
        "commodities": commodities,
        "start_year":  start_year,
        "end_year":    end_year,
        "task_count":  len(submitted),
        "tasks":       submitted,
    }
    output_path.write_text(json.dumps(payload, indent=2))
    logger.info("Run record saved to %s", output_path)


def main() -> None:
    load_env()

    env     = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    batch_queue = f"{project}-{env}-queue"
    job_def     = f"{project}-{env}-cpc-soil-raw-to-bronze"

    parser = argparse.ArgumentParser(
        description="Submit CPC raw → bronze as AWS Batch tasks (one per commodity × year)."
    )
    parser.add_argument(
        "--commodities",
        default="all",
        help='Comma-separated list or "all" (default).',
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

    commodities: list[str] = (
        list(ALL_COMMODITIES)
        if args.commodities.strip().lower() == "all"
        else [c.strip() for c in args.commodities.split(",")]
    )
    unknown = [c for c in commodities if c not in ALL_COMMODITIES]
    if unknown:
        raise SystemExit(f"ERROR: Unknown commodities: {unknown}")

    end_year = args.end_year if args.end_year is not None else date.today().year
    tasks = build_tasks(commodities, args.start_year, end_year, args.variable)

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

    save_run_record(submitted, commodities, args.start_year, end_year, args.variable)
    logger.info(
        "Done  submitted=%d  commodities=%d  start_year=%d  end_year=%d",
        len(submitted), len(commodities), args.start_year, end_year,
    )


if __name__ == "__main__":
    main()
