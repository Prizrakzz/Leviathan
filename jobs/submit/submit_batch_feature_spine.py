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
import datetime
import logging
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

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
    *,
    workers: int,
    source_year_min: int | None,
    source_year_max: int | None,
    dataset_version: str,
    write_versioned: bool,
    versioned_only: bool,
    fail_if_version_exists: bool,
    source_certification_report: str,
) -> list[dict[str, str]]:
    """One task dict per commodity — all string values for Batch parameters."""
    return [
        {
            "commodity": c,
            "bucket": bucket,
            "aws_region": aws_region,
            "start_crop_year": str(start_crop_year),
            "end_crop_year": str(end_crop_year),
            "workers": str(workers),
            "source_year_min": "none" if source_year_min is None else str(source_year_min),
            "source_year_max": "none" if source_year_max is None else str(source_year_max),
            "dataset_version": dataset_version or "none",
            "write_versioned": str(write_versioned).lower(),
            "versioned_only": str(versioned_only).lower(),
            "fail_if_version_exists": str(fail_if_version_exists).lower(),
            "source_certification_report": source_certification_report or "none",
        }
        for c in commodities
    ]


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _default_dataset_version() -> str:
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    git_sha = _git_sha()
    suffix = git_sha[:12] if git_sha and git_sha != "unknown" else "unknown"
    return f"{stamp}_{suffix}"


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
        description="Submit silver/* to gold/feature_spine Batch tasks (one per commodity).",
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
    parser.add_argument(
        "--single-job", action="store_true", default=False,
        help=(
            "Submit one Batch job with --commodity all. Required for broad "
            "versioned dataset builds so one manifest is written."
        ),
    )
    parser.add_argument(
        "--workers", type=int, default=4,
        help="Internal worker threads for the feature spine Batch task.",
    )
    parser.add_argument("--source-year-min", type=int, default=None, dest="source_year_min")
    parser.add_argument("--source-year-max", type=int, default=None, dest="source_year_max")
    parser.add_argument("--dataset-version", default="", dest="dataset_version")
    parser.add_argument("--write-versioned", action="store_true", default=False)
    parser.add_argument("--versioned-only", action="store_true", default=False)
    parser.add_argument(
        "--allow-existing-version", action="store_true", default=False,
        help="Allow versioned outputs to overwrite. Avoid outside local debugging.",
    )
    parser.add_argument(
        "--source-certification-report", default="", dest="source_certification_report",
        help="S3 URI or bucket key for the Phase 2 source certification report.",
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

    if args.versioned_only:
        args.write_versioned = True
    if args.write_versioned and not args.dataset_version:
        args.dataset_version = _default_dataset_version()
    if args.write_versioned and len(commodities) > 1 and not args.single_job:
        raise SystemExit(
            "ERROR: versioned broad builds must use --single-job so one full "
            "dataset manifest is written. Use one commodity only for a narrow smoke."
        )
    task_commodities = ["all"] if args.single_job else commodities

    end_crop_year = args.end_crop_year or date.today().year
    tasks = build_tasks(
        task_commodities,
        bucket,
        aws_region,
        args.start_crop_year,
        end_crop_year,
        workers=max(1, int(args.workers)),
        source_year_min=args.source_year_min,
        source_year_max=args.source_year_max,
        dataset_version=args.dataset_version,
        write_versioned=args.write_versioned,
        versioned_only=args.versioned_only,
        fail_if_version_exists=not args.allow_existing_version,
        source_certification_report=args.source_certification_report,
    )

    logger.info(
        (
            "Submitting %d tasks  queue=%s  definition=%s  crop_years=%d-%d  "
            "dry_run=%s  write_versioned=%s  versioned_only=%s  "
            "dataset_version=%s  workers=%d  source_years=%s-%s"
        ),
        len(tasks), batch_queue, job_def, args.start_crop_year, end_crop_year,
        args.dry_run, args.write_versioned, args.versioned_only,
        args.dataset_version, max(1, int(args.workers)),
        args.source_year_min, args.source_year_max,
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
                "task_commodities": task_commodities,
                "dataset_version": args.dataset_version,
                "write_versioned": args.write_versioned,
                "versioned_only": args.versioned_only,
                "workers": max(1, int(args.workers)),
                "source_year_min": args.source_year_min,
                "source_year_max": args.source_year_max,
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
