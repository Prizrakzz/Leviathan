"""Submit CHIRPS year-level bronze tasks as AWS Batch Fargate jobs.

One job per YEAR (46 total for 1981-2026).  Each job downloads every daily
.tif.gz file ONCE and extracts pixels for all 31 commodities in a single
rasterio pass — 31x fewer downloads than the per-commodity approach.

The task script is uploaded to S3 and pulled by the container at startup via
a boto3 one-liner command override.  The ECR image already has the correct
chirps.py (vsigzip fix) baked in — no hot-patching required.

Usage:
    python jobs/submit/submit_batch_chirps_year_backfill.py
    python jobs/submit/submit_batch_chirps_year_backfill.py --start-year 2020 --end-year 2025
    python jobs/submit/submit_batch_chirps_year_backfill.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import date
from pathlib import Path

import boto3

from leviathan.common.batch_submit import write_run_record
from leviathan.common.config import get_required_env, load_env
from leviathan.common.constants import CHIRPS_START_YEAR
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_batch_chirps_year_backfill")

_TASK_LOCAL_PATH = Path("jobs/batch/chirps_year_to_bronze_task.py")
_TASK_S3_KEY     = "scripts/chirps_year_to_bronze_task.py"


def _upload_task_script(bucket: str, aws_region: str) -> None:
    """Upload the year-level task script to S3 so containers can pull it."""
    s3 = boto3.client("s3", region_name=aws_region)
    s3.upload_file(str(_TASK_LOCAL_PATH), bucket, _TASK_S3_KEY)
    logger.info("Uploaded task script -> s3://%s/%s", bucket, _TASK_S3_KEY)


def _build_container_command(bucket: str, aws_region: str, year: int) -> list[str]:
    """Return the container command that downloads and runs the year task."""
    bootstrap = (
        f"import boto3, subprocess; "
        f"boto3.client('s3', region_name='{aws_region}').download_file("
        f"'{bucket}', '{_TASK_S3_KEY}', '/tmp/chirps_year_task.py'); "
        f"subprocess.check_call(["
        f"'python', '/tmp/chirps_year_task.py', "
        f"'--year', '{year}', "
        f"'--bucket', '{bucket}', "
        f"'--aws_region', '{aws_region}', "
        f"'--force_overwrite', 'true'"
        f"])"
    )
    return ["-c", bootstrap]


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    load_env()

    env     = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    job_queue  = f"{project}-{env}-queue"
    # Reuse the existing bronze job definition — command is overridden per job
    job_def    = f"{project}-{env}-chirps-to-bronze-backfill"

    parser = argparse.ArgumentParser(
        description="Submit CHIRPS year-level bronze jobs (all commodities per year)."
    )
    parser.add_argument("--start-year", type=int, default=CHIRPS_START_YEAR, dest="start_year")
    parser.add_argument("--end-year",   type=int, default=None, dest="end_year")
    parser.add_argument("--dry-run",    action="store_true")
    args = parser.parse_args()

    bucket     = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")
    end_year   = args.end_year or date.today().year
    years      = list(range(args.start_year, end_year + 1))

    logger.info(
        "Submitting %d year-level jobs  queue=%s  years=%d-%d  dry_run=%s",
        len(years), job_queue, years[0], years[-1], args.dry_run,
    )

    if not args.dry_run:
        _upload_task_script(bucket, aws_region)

    batch = boto3.client("batch", region_name=aws_region)
    submitted: list[dict] = []

    for year in years:
        job_name = f"chirps-year-bronze-{year}"
        command  = _build_container_command(bucket, aws_region, year)

        if args.dry_run:
            logger.info("[DRY RUN] Would submit: %s", job_name)
            submitted.append({"job_name": job_name, "year": year, "job_id": None})
            continue

        resp = batch.submit_job(
            jobName=job_name,
            jobQueue=job_queue,
            jobDefinition=job_def,
            containerOverrides={"command": command},
        )
        job_id = resp["jobId"]
        logger.info("Submitted  job_name=%s  job_id=%s", job_name, job_id)
        submitted.append({"job_name": job_name, "year": year, "job_id": job_id})

    if not args.dry_run:
        run_id = utc_now_iso().replace(":", "-")
        write_run_record(
            Path("data/batch_runs") / f"chirps_year_backfill_{run_id}.json",
            {
                "run_id":     run_id,
                "source":     "chirps",
                "strategy":   "year_level",
                "start_year": args.start_year,
                "end_year":   end_year,
                "job_count":  len(submitted),
                "jobs":       submitted,
            },
        )
        logger.info(
            "Done: %d/%d jobs submitted.",
            sum(1 for j in submitted if j["job_id"]),
            len(submitted),
        )
    else:
        logger.info("Dry run: %d jobs would be submitted.", len(submitted))


if __name__ == "__main__":
    main()
