from __future__ import annotations

import argparse
import logging
from pathlib import Path

from leviathan.common.batch_submit import submit_batch_jobs, write_run_record
from leviathan.common.config import get_required_env, load_env, load_yaml
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_batch_backfill_nasa_power")


def build_tasks(
    geography_config: dict,
    commodity: str,
    start_year: int,
    end_year: int,
) -> list[dict]:
    """
    Returns one task dict per (country, region, year).
    Each Batch task handles 12 monthly API calls for that combination.
    """
    tasks = []

    for country_block in geography_config["regions"]:
        country = country_block["country"]

        for location in country_block["locations"]:
            region = location["region"]

            for year in range(start_year, end_year + 1):
                tasks.append(
                    {
                        "commodity": commodity,
                        "country": country,
                        "region": region,
                        "year": year,
                    }
                )

    return tasks


def submit_tasks(
    tasks: list[dict],
    job_queue: str,
    job_definition: str,
    aws_region: str,
    dry_run: bool,
) -> list[dict]:
    enriched = [
        {
            "commodity":  t["commodity"],
            "country":    t["country"],
            "region":     t["region"],
            "start_year": str(t["year"]),
            "end_year":   str(t["year"]),
        }
        for t in tasks
    ]
    return submit_batch_jobs(
        tasks=enriched,
        job_queue=job_queue,
        job_definition=job_definition,
        build_job_name=lambda t: (
            f"nasa-power-backfill-{t['country']}-{t['region']}-{t['start_year']}"
            .replace("_", "-")
        ),
        aws_region=aws_region,
        dry_run=dry_run,
    )


def save_run_record(submitted: list[dict], commodity: str, start_year: int, end_year: int) -> None:
    run_id  = utc_now_iso().replace(":", "-")
    payload = {
        "run_id":     run_id,
        "source":     "nasa_power",
        "commodity":  commodity,
        "start_year": start_year,
        "end_year":   end_year,
        "task_count": len(submitted),
        "tasks":      submitted,
    }
    write_run_record(Path("data/batch_runs") / f"nasa_power_backfill_{run_id}.json", payload)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(
        description="Submit NASA POWER backfill tasks to AWS Batch as individual jobs."
    )
    parser.add_argument("--commodity", required=True)
    parser.add_argument("--start-year", required=True, type=int)
    parser.add_argument("--end-year", required=True, type=int)
    parser.add_argument(
        "--job-queue",
        default=None,
        help="Batch job queue name. Defaults to leviathan-<env>-queue.",
    )
    parser.add_argument(
        "--job-definition",
        default=None,
        help="Batch job definition name or ARN. Defaults to leviathan-<env>-nasa-power-backfill.",
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
    job_definition = args.job_definition or f"leviathan-{env}-nasa-power-backfill"

    geography_config = load_yaml(f"configs/geographies/{args.commodity}_regions.yaml")

    tasks = build_tasks(
        geography_config=geography_config,
        commodity=args.commodity,
        start_year=args.start_year,
        end_year=args.end_year,
    )

    logger.info(
        "Submitting %d tasks to queue=%s job_definition=%s dry_run=%s",
        len(tasks),
        job_queue,
        job_definition,
        args.dry_run,
    )

    submitted = submit_tasks(
        tasks=tasks,
        job_queue=job_queue,
        job_definition=job_definition,
        aws_region=aws_region,
        dry_run=args.dry_run,
    )

    if not args.dry_run:
        save_run_record(
            submitted=submitted,
            commodity=args.commodity,
            start_year=args.start_year,
            end_year=args.end_year,
        )

    logger.info("Done. %d jobs submitted.", len(submitted))


if __name__ == "__main__":
    main()
