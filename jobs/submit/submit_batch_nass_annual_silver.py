"""Submit USDA NASS annual bronze -> silver as an AWS Batch task.

Requires the NASS annual bronze layer to already exist under
``bronze/production/source=usda_nass/series=annual/``.
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from leviathan.common.batch_submit import submit_batch_jobs, write_run_record
from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_batch_nass_annual_silver")


def save_run_record(submitted: list[dict], params: dict[str, str]) -> None:
    run_id = utc_now_iso().replace(":", "-")
    payload = {
        "run_id": run_id,
        "source": "usda_nass",
        "stage": "annual_bronze_to_silver",
        "task_count": len(submitted),
        "parameters": params,
        "tasks": submitted,
    }
    write_run_record(
        Path("data/batch_runs") / f"nass_annual_silver_{run_id}.json",
        payload,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    load_env()

    env = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    batch_queue = f"{project}-{env}-queue"
    job_definition = f"{project}-{env}-usda-nass-annual-silver"

    parser = argparse.ArgumentParser(
        description="Submit USDA NASS annual bronze->silver Batch task."
    )
    parser.add_argument("--bronze-commodities", default="all")
    parser.add_argument("--years", default="all")
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Concurrent S3/parquet workers for the Batch task.",
    )
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be >= 1")

    bucket = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    params = {
        "bucket": bucket,
        "aws_region": aws_region,
        "force_overwrite": "true" if args.force_overwrite else "false",
        "bronze_commodities": args.bronze_commodities,
        "years": args.years,
        "workers": str(args.workers),
    }

    logger.info(
        "Submitting NASS annual silver task queue=%s definition=%s dry_run=%s",
        batch_queue,
        job_definition,
        args.dry_run,
    )
    submitted = submit_batch_jobs(
        tasks=[params],
        job_queue=batch_queue,
        job_definition=job_definition,
        build_job_name=lambda _: "nass-annual-silver",
        aws_region=aws_region,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        logger.info("[DRY RUN] params=%s", params)
        return

    save_run_record(submitted, params)
    logger.info("Submitted NASS annual silver task: %s", submitted[0].get("job_id"))


if __name__ == "__main__":
    main()
