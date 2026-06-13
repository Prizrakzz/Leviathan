"""Submit silver/* → gold/feature_spine as AWS Batch Fargate tasks.

One task per commodity.  All tasks are submitted together and AWS Batch
runs them in parallel (up to the queue's max_vcpus limit).  Each Batch
task runs feature_spine_task.py for a single commodity, which probes its
silver inputs, builds the point-in-time-correct spine, and writes one
Parquet partition + a run manifest to S3.

Usage:
    python jobs/submit/submit_batch_feature_spine.py
    python jobs/submit/submit_batch_feature_spine.py --commodities corn_cbot,arabica_coffee
    python jobs/submit/submit_batch_feature_spine.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import date
from pathlib import Path

from leviathan.common.batch_submit import submit_batch_jobs, write_run_record
from leviathan.common.config import get_required_env, load_env
from leviathan.common.constants import ALL_COMMODITIES
from leviathan.common.logging import get_logger
from leviathan.features.spine import load_countries
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_batch_feature_spine")


def build_tasks(
    commodities: list[str],
    bucket: str,
    aws_region: str,
    start_crop_year: int,
    end_crop_year: int,
) -> list[dict[str, str]]:
    """One task dict per commodity — all string values for Batch parameters."""
    return [
        {
            "commodity": c,
            "bucket": bucket,
            "aws_region": aws_region,
            "start_crop_year": str(start_crop_year),
            "end_crop_year": str(end_crop_year),
        }
        for c in commodities
    ]


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    load_env()

    env = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    batch_queue = f"{project}-{env}-queue"
    job_def = f"{project}-{env}-feature-spine"

    parser = argparse.ArgumentParser(
        description="Submit silver/* → gold/feature_spine Batch tasks (one per commodity).",
    )
    parser.add_argument(
        "--commodities",
        default="all",
        help=(
            'Comma-separated slugs or "all" (default). '
            '"all" filters to commodities that have a geography config.'
        ),
    )
    parser.add_argument(
        "--start-crop-year", type=int, default=1981, dest="start_crop_year",
    )
    parser.add_argument(
        "--end-crop-year", type=int, default=None, dest="end_crop_year",
        help="Last crop year (inclusive). Defaults to the current calendar year.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    bucket = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    if args.commodities.strip().lower() == "all":
        commodities = [c for c in ALL_COMMODITIES if load_countries(c)]
    else:
        commodities = [c.strip() for c in args.commodities.split(",")]
        unknown = [c for c in commodities if c not in ALL_COMMODITIES]
        if unknown:
            raise SystemExit(f"ERROR: Unknown commodities: {unknown}")

    end_crop_year = args.end_crop_year or date.today().year
    tasks = build_tasks(commodities, bucket, aws_region, args.start_crop_year, end_crop_year)

    logger.info(
        "Submitting %d tasks  queue=%s  definition=%s  crop_years=%d-%d  dry_run=%s",
        len(tasks), batch_queue, job_def, args.start_crop_year, end_crop_year, args.dry_run,
    )

    submitted = submit_batch_jobs(
        tasks=tasks,
        job_queue=batch_queue,
        job_definition=job_def,
        build_job_name=lambda t: f"feature-spine-{t['commodity']}".replace("_", "-"),
        aws_region=aws_region,
        dry_run=args.dry_run,
    )

    if not args.dry_run:
        run_id = utc_now_iso().replace(":", "-")
        write_run_record(
            Path("data/batch_runs") / f"feature_spine_{run_id}.json",
            {
                "run_id": run_id,
                "job": "feature_spine",
                "commodities": commodities,
                "start_crop_year": args.start_crop_year,
                "end_crop_year": end_crop_year,
                "task_count": len(submitted),
                "tasks": submitted,
            },
        )
        logger.info(
            "Done: %d/%d tasks submitted.",
            sum(1 for t in submitted if t["job_id"]),
            len(tasks),
        )
    else:
        logger.info("Dry run complete: %d tasks would be submitted.", len(tasks))


if __name__ == "__main__":
    main()
