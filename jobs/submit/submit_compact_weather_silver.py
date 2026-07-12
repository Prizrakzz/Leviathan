"""Submit the weather-trio deproject+compaction (SILVER-F047) as AWS Batch Fargate tasks.

One task per (source, commodity). Each task collapses a commodity's ~12x monthly projected objects per
year into ONE registered-partition object at commodity=<c>/year=<y>/ (the ~590k -> coarse file
collapse), publishing through the F015 shadow publisher. EXECUTION IS GATED to backfill wave BF-W1: the
underlying task defaults to ``--publish-mode dry-run``; pass ``--publish-mode shadow`` to stage
(non-canonical) or leave default to plan only. Canonical is refused without a signed post-R4 approval.

The de-projection FLIP (removing projection.* table params) is a SEPARATE gated step run only after
these registered partitions exist -- ``jobs/utils/deproject_glue_table.py --flip --tables
silver_chirps,silver_nasa_power,silver_cpc_soil``.

Usage:
    python jobs/submit/submit_compact_weather_silver.py --source chirps --dry-run
    python jobs/submit/submit_compact_weather_silver.py --source chirps --publish-mode shadow
    python jobs/submit/submit_compact_weather_silver.py --source all --commodities corn_cbot,arabica_coffee
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from leviathan.common.batch_submit import submit_batch_jobs, write_run_record
from leviathan.common.config import get_required_env, load_env
from leviathan.common.constants import ALL_COMMODITIES
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_compact_weather_silver")

_SOURCES = ("nasa_power", "chirps", "cpc_soil")


def submit_tasks(source: str, commodities: list[str], job_queue: str, job_definition: str,
                 bucket: str, aws_region: str, publish_mode: str, dry_run: bool) -> list[dict]:
    tasks = [
        {"source": source, "commodity": c, "bucket": bucket, "aws_region": aws_region,
         "publish-mode": publish_mode}
        for c in commodities
    ]
    return submit_batch_jobs(
        tasks=tasks,
        job_queue=job_queue,
        job_definition=job_definition,
        build_job_name=lambda t: f"weather-compact-{source}-{t['commodity']}".replace("_", "-"),
        aws_region=aws_region,
        dry_run=dry_run,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()

    env = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    batch_queue = f"{project}-{env}-queue"
    job_def = f"{project}-{env}-weather-compact"

    parser = argparse.ArgumentParser(description="Submit weather deproject+compaction (SILVER-F047).")
    parser.add_argument("--source", default="all", help='one of nasa_power/chirps/cpc_soil, or "all"')
    parser.add_argument("--commodities", default="all")
    parser.add_argument("--publish-mode", default="dry-run",
                        help="dry-run (default; plan only) | shadow | canonical (needs signed approval)")
    parser.add_argument("--dry-run", action="store_true", help="do not submit Batch jobs; print only")
    args = parser.parse_args()

    bucket = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    sources = list(_SOURCES) if args.source.strip().lower() == "all" else [args.source.strip()]
    unknown_src = [s for s in sources if s not in _SOURCES]
    if unknown_src:
        raise SystemExit(f"ERROR: unknown source(s): {unknown_src}")

    commodities = (
        list(ALL_COMMODITIES) if args.commodities.strip().lower() == "all"
        else [c.strip() for c in args.commodities.split(",")]
    )
    unknown = [c for c in commodities if c not in ALL_COMMODITIES]
    if unknown:
        raise SystemExit(f"ERROR: Unknown commodities: {unknown}")

    all_submitted: list[dict] = []
    for source in sources:
        logger.info("Submitting %d compaction tasks  source=%s  queue=%s  publish_mode=%s  dry_run=%s",
                    len(commodities), source, batch_queue, args.publish_mode, args.dry_run)
        submitted = submit_tasks(source, commodities, batch_queue, job_def, bucket, aws_region,
                                 args.publish_mode, args.dry_run)
        all_submitted.extend(submitted)

    if not args.dry_run:
        run_id = utc_now_iso().replace(":", "-")
        write_run_record(
            Path("data/batch_runs") / f"weather_compact_{run_id}.json",
            {"run_id": run_id, "sources": sources, "stage": "deproject_compact",
             "publish_mode": args.publish_mode, "commodities": commodities,
             "task_count": len(all_submitted), "tasks": all_submitted},
        )
    logger.info("Done: %d tasks (dry_run=%s, publish_mode=%s).",
                len(all_submitted), args.dry_run, args.publish_mode)


if __name__ == "__main__":
    main()
