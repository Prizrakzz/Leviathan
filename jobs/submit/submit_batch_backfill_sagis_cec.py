"""Submit SAGIS CEC raw backfill as a single AWS Batch Fargate job.

Unlike multi-task sources (CHIRPS, NASA POWER), the CEC backfill is one
sequential job: fetch_sagis_cec.py --skip-existing-s3 downloads ~436 report
files (PDF/DOC/XLS, 1999-present) in one pass.  Expected runtime: ~30-60 min.

Usage
-----
    # Dry-run (no AWS call)
    python jobs/submit/submit_batch_backfill_sagis_cec.py --dry-run

    # Submit
    python jobs/submit/submit_batch_backfill_sagis_cec.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import boto3

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_batch_backfill_sagis_cec")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Submit SAGIS CEC raw backfill as a single AWS Batch Fargate job."
    )
    parser.add_argument(
        "--job-queue",
        default=None,
        help="Batch job queue name.  Defaults to leviathan-<env>-queue.",
    )
    parser.add_argument(
        "--job-definition",
        default=None,
        help="Batch job definition name.  Defaults to leviathan-<env>-sagis-cec-raw-backfill.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be submitted without calling AWS.",
    )
    args = parser.parse_args()

    load_env()

    aws_region = get_required_env("AWS_REGION")
    env = get_required_env("LEVIATHAN_ENV")

    job_queue = args.job_queue or f"leviathan-{env}-queue"
    job_definition = args.job_definition or f"leviathan-{env}-sagis-cec-raw-backfill"
    job_name = f"sagis-cec-raw-backfill"

    if args.dry_run:
        logger.info(
            "[DRY RUN] Would submit: job_name=%s  queue=%s  definition=%s",
            job_name, job_queue, job_definition,
        )
        return

    client = boto3.client("batch", region_name=aws_region)
    response = client.submit_job(
        jobName=job_name,
        jobQueue=job_queue,
        jobDefinition=job_definition,
    )
    job_id = response["jobId"]
    logger.info("Submitted  job_name=%s  job_id=%s", job_name, job_id)

    # Save run record for audit trail
    run_id = utc_now_iso().replace(":", "-")
    output_dir = Path("data/batch_runs")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"sagis_cec_raw_backfill_{run_id}.json"
    output_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "source": "sagis_cec",
                "job_name": job_name,
                "job_id": job_id,
                "job_queue": job_queue,
                "job_definition": job_definition,
            },
            indent=2,
        )
    )
    logger.info("Run record saved to %s", output_path)


if __name__ == "__main__":
    main()
