"""Submit MODIS NDVI raw-CSV → bronze Parquet as AWS Batch Fargate tasks.

One task per commodity group (5 total).  The raw CSVs must already have been
downloaded to S3 by ``fetch_modis_ndvi.py``.  Pass the ``--run-id`` that was
printed / saved by the fetch script.

Usage:
    python jobs/submit/submit_batch_modis_ndvi_r2b.py --run-id 20260524T203000Z
    python jobs/submit/submit_batch_modis_ndvi_r2b.py --run-id 20260524T203000Z --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import yaml

from leviathan.common.batch_submit import submit_batch_jobs, write_run_record
from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_batch_modis_ndvi_r2b")

_SOURCE_CONFIG = Path("configs/sources/modis_ndvi.yaml")


def _load_groups() -> list[str]:
    cfg = yaml.safe_load(_SOURCE_CONFIG.read_text(encoding="utf-8"))
    return list(cfg["commodity_groups"].keys())


def submit_tasks(
    run_id: str,
    groups: list[str],
    job_queue: str,
    job_definition: str,
    bucket: str,
    aws_region: str,
    dry_run: bool,
) -> list[dict]:
    tasks = [
        {"run_id": run_id, "group": g, "bucket": bucket, "aws_region": aws_region}
        for g in groups
    ]
    return submit_batch_jobs(
        tasks=tasks,
        job_queue=job_queue,
        job_definition=job_definition,
        build_job_name=lambda t: f"modis-ndvi-r2b-{t['group']}".replace("_", "-"),
        aws_region=aws_region,
        dry_run=dry_run,
    )


def save_run_record(submitted: list[dict], run_id: str, groups: list[str]) -> None:
    record_id = utc_now_iso().replace(":", "-")
    payload = {
        "run_id":        record_id,
        "source":        "modis_ndvi",
        "stage":         "raw_to_bronze",
        "fetch_run_id":  run_id,
        "groups":        groups,
        "task_count":    len(submitted),
        "tasks":         submitted,
    }
    write_run_record(
        Path("data/batch_runs") / f"modis_ndvi_r2b_{record_id}.json", payload
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    load_env()

    env     = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    batch_queue = f"{project}-{env}-queue"
    r2b_job_def = f"{project}-{env}-modis-ndvi-raw-to-bronze"

    parser = argparse.ArgumentParser(
        description="Submit MODIS NDVI raw→bronze as AWS Batch Fargate tasks."
    )
    parser.add_argument(
        "--run-id", required=True,
        help="Fetch run ID from fetch_modis_ndvi.py (e.g. 20260524T203000Z).",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    bucket     = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    groups = _load_groups()
    logger.info(
        "Submitting %d R2B tasks  run_id=%s  queue=%s  definition=%s  dry_run=%s",
        len(groups), args.run_id, batch_queue, r2b_job_def, args.dry_run,
    )

    submitted = submit_tasks(
        run_id=args.run_id,
        groups=groups,
        job_queue=batch_queue,
        job_definition=r2b_job_def,
        bucket=bucket,
        aws_region=aws_region,
        dry_run=args.dry_run,
    )

    if not args.dry_run:
        save_run_record(submitted, args.run_id, groups)
        logger.info(
            "Done: %d/%d tasks submitted.",
            sum(1 for t in submitted if t.get("job_id")),
            len(submitted),
        )
    else:
        for t in submitted:
            logger.info("  [DRY-RUN] group=%s", t.get("group", "?"))


main()
