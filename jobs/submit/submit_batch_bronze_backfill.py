"""Submit Phase 1 bronze backfill as 9 parallel AWS Batch Fargate tasks.

One task per source — all 9 run concurrently.  Each container reads raw data
from S3 and writes bronze Parquet.  Expected wall clock: 5–20 minutes total.

Usage
-----
    python jobs/submit/submit_batch_bronze_backfill.py --dry-run
    python jobs/submit/submit_batch_bronze_backfill.py
    python jobs/submit/submit_batch_bronze_backfill.py --sources usda_psd usda_esr
    python jobs/submit/submit_batch_bronze_backfill.py --force-overwrite
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

logger = get_logger("submit_batch_bronze_backfill")

# ---------------------------------------------------------------------------
# Job definitions — one entry per Phase 1 source
# ---------------------------------------------------------------------------

JOBS: list[dict] = [
    {
        "source":         "usda_psd",
        "job_name":       "bronze-backfill-usda-psd",
        "job_def_suffix": "usda-psd-bronze",
        "script":         "psd_task.py",
        "extra_args":     [],
    },
    {
        "source":         "usda_fgis",
        "job_name":       "bronze-backfill-usda-fgis",
        "job_def_suffix": "usda-fgis-bronze",
        "script":         "fgis_task.py",
        "extra_args":     [],
    },
    {
        "source":         "world_bank_pink_sheet",
        "job_name":       "bronze-backfill-pink-sheet",
        "job_def_suffix": "world-bank-pink-sheet-bronze",
        "script":         "pink_sheet_task.py",
        "extra_args":     [],
    },
    {
        "source":         "usda_nass",
        "job_name":       "bronze-backfill-usda-nass",
        "job_def_suffix": "usda-nass-bronze",
        "script":         "nass_task.py",
        "extra_args":     ["--series", "all"],
    },
    {
        "source":         "conab_xls",
        "job_name":       "bronze-backfill-conab-xls",
        "job_def_suffix": "conab-xls-bronze",
        "script":         "conab_xls_task.py",
        "extra_args":     [],
    },
    {
        "source":         "fnc_excel",
        "job_name":       "bronze-backfill-fnc-excel",
        "job_def_suffix": "fnc-excel-bronze",
        "script":         "fnc_excel_task.py",
        "extra_args":     [],
    },
    {
        "source":         "mpob",
        "job_name":       "bronze-backfill-mpob",
        "job_def_suffix": "mpob-bronze",
        "script":         "mpob_task.py",
        "extra_args":     ["--release-type", "all"],
    },
    {
        "source":         "unica",
        "job_name":       "bronze-backfill-unica",
        "job_def_suffix": "unica-bronze",
        "script":         "unica_task.py",
        "extra_args":     [],
    },
    {
        "source":         "usda_esr",
        "job_name":       "bronze-backfill-usda-esr",
        "job_def_suffix": "usda-esr-bronze",
        "script":         "esr_task.py",
        # --include-backfill is REQUIRED here from 2026-09-04 (C-F1, the ESR vintage law): an
        # undated raw key (raw/.../market_year=Y/all_countries.json, no as_of= segment) is out of
        # scope for every run unless the operator admits it, and its bronze as_of is then taken
        # from the raw_meta sidecar's download_timestamp -- the day the bytes were actually
        # fetched -- never from the run date. Without this flag a BACKFILL submission would
        # correctly select nothing. NOTE: --force-overwrite now also requires --as-of-min, so a
        # forced ESR backfill must add "--as-of-min <YYYYMMDD> --backfill-as-of <YYYYMMDD>"
        # explicitly; the refusal is the point.
        "extra_args":     ["--include-backfill"],
    },
]


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------

def submit_tasks(
    jobs: list[dict],
    job_queue: str,
    project: str,
    env: str,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
    dry_run: bool,
) -> list[dict]:
    client = boto3.client("batch", region_name=aws_region)
    submitted: list[dict] = []

    for job in jobs:
        job_definition = f"{project}-{env}-{job['job_def_suffix']}"
        command = [
            f"jobs/batch/{job['script']}",
            "--bucket",     bucket,
            "--aws-region", aws_region,
        ] + job["extra_args"]
        if force_overwrite:
            command.append("--force-overwrite")

        if dry_run:
            logger.info(
                "[DRY RUN] Would submit: %s  def=%s  cmd=%s",
                job["job_name"], job_definition, command,
            )
            submitted.append({
                "job_name":       job["job_name"],
                "job_id":         None,
                "source":         job["source"],
                "job_definition": job_definition,
            })
            continue

        response = client.submit_job(
            jobName=job["job_name"],
            jobQueue=job_queue,
            jobDefinition=job_definition,
            containerOverrides={"command": command},
        )
        job_id = response["jobId"]
        logger.info(
            "Submitted  job_name=%s  job_id=%s  def=%s",
            job["job_name"], job_id, job_definition,
        )
        submitted.append({
            "job_name":       job["job_name"],
            "job_id":         job_id,
            "source":         job["source"],
            "job_definition": job_definition,
        })

    return submitted


def save_run_record(submitted: list[dict]) -> None:
    run_id  = utc_now_iso().replace(":", "-")
    payload = {
        "run_id":     run_id,
        "source":     "phase1_bronze_backfill",
        "task_count": len(submitted),
        "tasks":      submitted,
    }
    write_run_record(
        Path("data/batch_runs") / f"bronze_backfill_{run_id}.json",
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

    env     = os.environ.get("LEVIATHAN_ENV",     "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    batch_queue = f"{project}-{env}-queue"

    valid_sources = [j["source"] for j in JOBS]

    parser = argparse.ArgumentParser(
        description="Submit Phase 1 bronze backfill as 9 parallel Batch Fargate tasks."
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        metavar="SOURCE",
        default=None,
        help=(
            "Subset of sources to submit (default: all 9). "
            f"Valid: {', '.join(valid_sources)}"
        ),
    )
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        help="Pass --force-overwrite to each task (re-writes existing bronze).",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    bucket     = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    jobs = JOBS
    if args.sources:
        valid = {j["source"] for j in JOBS}
        unknown = set(args.sources) - valid
        if unknown:
            raise SystemExit(f"Unknown sources: {unknown}. Valid: {valid}")
        jobs = [j for j in JOBS if j["source"] in args.sources]

    logger.info(
        "Submitting %d bronze backfill task(s) to queue=%s",
        len(jobs), batch_queue,
    )

    submitted = submit_tasks(
        jobs=jobs,
        job_queue=batch_queue,
        project=project,
        env=env,
        bucket=bucket,
        aws_region=aws_region,
        force_overwrite=args.force_overwrite,
        dry_run=args.dry_run,
    )

    save_run_record(submitted)

    if not args.dry_run:
        logger.info("All %d task(s) submitted. Monitor at:", len(submitted))
        logger.info(
            "  https://%s.console.aws.amazon.com/batch/home?region=%s#jobs",
            aws_region, aws_region,
        )


if __name__ == "__main__":
    main()
