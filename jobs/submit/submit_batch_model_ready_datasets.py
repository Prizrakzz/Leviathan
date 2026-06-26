"""Submit the Phase 8 model-ready dataset builder as one AWS Batch job."""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from leviathan.common.batch_submit import submit_batch_jobs, write_run_record
from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_batch_model_ready_datasets")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    load_env()

    env = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    job_queue = f"{project}-{env}-queue"
    job_def = f"{project}-{env}-model-ready-datasets"

    parser = argparse.ArgumentParser(description="Submit Phase 8 model-ready dataset build.")
    parser.add_argument("--source-dataset-version", required=True, dest="source_dataset_version")
    parser.add_argument("--model-dataset-version", required=True, dest="model_dataset_version")
    parser.add_argument("--commodities", default="all")
    parser.add_argument("--target-keys", default="", dest="target_keys")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--job-queue", default=None, dest="job_queue")
    parser.add_argument("--skip-existing-versioned", action="store_true", default=False)
    parser.add_argument("--force-overwrite", action="store_true", default=False)
    parser.add_argument("--dry-run", action="store_true", default=False)
    args = parser.parse_args()

    bucket = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")
    task = {
        "bucket": bucket,
        "aws_region": aws_region,
        "source_dataset_version": args.source_dataset_version,
        "model_dataset_version": args.model_dataset_version,
        "commodities": args.commodities,
        "target_keys": args.target_keys or "none",
        "workers": str(max(1, int(args.workers))),
        "skip_existing_versioned": str(args.skip_existing_versioned).lower(),
        "force_overwrite": str(args.force_overwrite).lower(),
    }
    queue = args.job_queue or job_queue
    submitted = submit_batch_jobs(
        tasks=[task],
        job_queue=queue,
        job_definition=job_def,
        build_job_name=lambda _: "model-ready-datasets",
        aws_region=aws_region,
        dry_run=args.dry_run,
    )
    if not args.dry_run:
        run_id = utc_now_iso().replace(":", "-")
        write_run_record(
            Path("data/batch_runs") / f"model_ready_datasets_{run_id}.json",
            {
                "run_id": run_id,
                "job": "model_ready_datasets",
                "source_dataset_version": args.source_dataset_version,
                "model_dataset_version": args.model_dataset_version,
                "tasks": submitted,
            },
        )
    logger.info("Done: %d task(s) submitted", len(submitted))


if __name__ == "__main__":
    main()
