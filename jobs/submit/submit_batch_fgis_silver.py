"""Submit USDA FGIS bronze → silver as an AWS Batch task.

Requires the FGIS bronze layer to already exist under
``bronze/production/source=usda_fgis_export_inspections/``.

Usage
-----
    # Smoke test — corn + soy MY2024 only
    python jobs/submit/submit_batch_fgis_silver.py --smoke-test --dry-run
    python jobs/submit/submit_batch_fgis_silver.py --smoke-test

    # Full backfill
    python jobs/submit/submit_batch_fgis_silver.py --dry-run
    python jobs/submit/submit_batch_fgis_silver.py

    # Specific marketing years
    python jobs/submit/submit_batch_fgis_silver.py --marketing-years 2023,2024,2025

    # Force overwrite existing silver partitions
    python jobs/submit/submit_batch_fgis_silver.py --force-overwrite
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

logger = get_logger("submit_batch_fgis_silver")

# Smoke test covers corn + soy for a single recent marketing year.
_SMOKE_SLUGS = "corn_cbot,soybeans_cbot"
_SMOKE_MARKETING_YEARS = "2024"


def save_run_record(submitted: list[dict], params: dict[str, str], label: str) -> None:
    run_id = utc_now_iso().replace(":", "-")
    payload = {
        "run_id": run_id,
        "source": "usda_fgis_export_inspections",
        "stage": "bronze_to_silver",
        "label": label,
        "task_count": len(submitted),
        "parameters": params,
        "tasks": submitted,
    }
    write_run_record(
        Path("data/batch_runs") / f"fgis_silver_{label}_{run_id}.json",
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
    job_definition = f"{project}-{env}-fgis-silver"

    parser = argparse.ArgumentParser(
        description="Submit USDA FGIS bronze->silver Batch task."
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help=f"Submit corn + soy MY{_SMOKE_MARKETING_YEARS} only (quick validation).",
    )
    parser.add_argument(
        "--marketing-years",
        default="all",
        dest="marketing_years",
        help="Comma-separated marketing years or 'all' (default: all).",
    )
    parser.add_argument(
        "--slugs",
        default="all",
        help="Comma-separated leviathan slugs or 'all' (default: all).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Concurrent S3 workers for the Batch task.",
    )
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.workers < 1:
        parser.error("--workers must be >= 1")

    bucket = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    # Smoke test overrides slug and year filters.
    if args.smoke_test:
        slugs = _SMOKE_SLUGS
        marketing_years = _SMOKE_MARKETING_YEARS
        label = "smoke"
    else:
        slugs = args.slugs
        marketing_years = args.marketing_years
        label = "full"

    params = {
        "bucket": bucket,
        "aws_region": aws_region,
        "force_overwrite": "true" if args.force_overwrite else "false",
        "marketing_years": marketing_years,
        "slugs": slugs,
        "workers": str(args.workers),
    }

    logger.info(
        "Submitting FGIS silver task  queue=%s  definition=%s  "
        "marketing_years=%s  slugs=%s  force=%s  dry_run=%s",
        batch_queue,
        job_definition,
        marketing_years,
        slugs,
        args.force_overwrite,
        args.dry_run,
    )

    submitted = submit_batch_jobs(
        tasks=[params],
        job_queue=batch_queue,
        job_definition=job_definition,
        build_job_name=lambda _: f"fgis-silver-{label}",
        aws_region=aws_region,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        logger.info("[DRY RUN] params=%s", params)
        return

    save_run_record(submitted, params, label)
    logger.info("Submitted FGIS silver task: %s", submitted[0].get("job_id"))


if __name__ == "__main__":
    main()
