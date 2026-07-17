"""Submit MODIS NDVI bronze Parquet → silver Parquet (z-scores) as Batch tasks.

One task per commodity (31 total).  All run concurrently — each job reads all
bronze files for one commodity, computes NDVI z-scores against the 2000–2020
climatological baseline, and writes per-partition silver Parquet files.

Requires that the bronze layer is already populated (run
``submit_batch_modis_ndvi_r2b.py`` first and wait for all 5 tasks to complete).

Usage:
    python jobs/submit/submit_batch_modis_ndvi_b2s.py
    python jobs/submit/submit_batch_modis_ndvi_b2s.py --commodities arabica_coffee,corn_cbot
    python jobs/submit/submit_batch_modis_ndvi_b2s.py --dry-run
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

logger = get_logger("submit_batch_modis_ndvi_b2s")

_SOURCE_CONFIG = Path("configs/sources/modis_ndvi.yaml")


def _load_modis_commodities() -> list[str]:
    """Return the flat list of all 31 MODIS NDVI commodities from the source config."""
    cfg = yaml.safe_load(_SOURCE_CONFIG.read_text(encoding="utf-8"))
    commodities: list[str] = []
    for group_commodities in cfg["commodity_groups"].values():
        commodities.extend(group_commodities)
    return commodities


def submit_tasks(
    commodities: list[str],
    job_queue: str,
    job_definition: str,
    bucket: str,
    aws_region: str,
    dry_run: bool,
) -> list[dict]:
    tasks = [
        {"commodity": c, "bucket": bucket, "aws_region": aws_region}
        for c in commodities
    ]
    return submit_batch_jobs(
        tasks=tasks,
        job_queue=job_queue,
        job_definition=job_definition,
        build_job_name=lambda t: f"modis-ndvi-b2s-{t['commodity']}".replace("_", "-"),
        aws_region=aws_region,
        dry_run=dry_run,
    )


def save_run_record(submitted: list[dict], commodities: list[str]) -> None:
    run_id = utc_now_iso().replace(":", "-")
    payload = {
        "run_id":      run_id,
        "source":      "modis_ndvi",
        "stage":       "bronze_to_silver",
        "commodities": commodities,
        "task_count":  len(submitted),
        "tasks":       submitted,
    }
    write_run_record(
        Path("data/batch_runs") / f"modis_ndvi_b2s_{run_id}.json", payload
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
    b2s_job_def = f"{project}-{env}-modis-ndvi-bronze-to-silver"

    parser = argparse.ArgumentParser(
        description="Submit MODIS NDVI bronze→silver as AWS Batch Fargate tasks."
    )
    parser.add_argument(
        "--commodities",
        default="all",
        help='Comma-separated list or "all" (default).',
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    bucket     = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    all_modis_commodities = _load_modis_commodities()

    commodities: list[str] = (
        all_modis_commodities
        if args.commodities.strip().lower() == "all"
        else [c.strip() for c in args.commodities.split(",")]
    )
    unknown = [c for c in commodities if c not in all_modis_commodities]
    if unknown:
        raise SystemExit(f"ERROR: Not in MODIS commodity list: {unknown}")

    logger.info(
        "Submitting %d B2S tasks  queue=%s  definition=%s  dry_run=%s",
        len(commodities), batch_queue, b2s_job_def, args.dry_run,
    )

    submitted = submit_tasks(
        commodities=commodities,
        job_queue=batch_queue,
        job_definition=b2s_job_def,
        bucket=bucket,
        aws_region=aws_region,
        dry_run=args.dry_run,
    )

    if not args.dry_run:
        save_run_record(submitted, commodities)
        logger.info(
            "Done: %d/%d tasks submitted.",
            sum(1 for t in submitted if t.get("job_id")),
            len(submitted),
        )
    else:
        for t in submitted:
            logger.info("  [DRY-RUN] commodity=%s", t.get("commodity", "?"))


main()
