from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import boto3

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
    client = boto3.client("batch", region_name=aws_region)

    submitted = []

    for task in tasks:
        job_name = (
            f"nasa-power-backfill-{task['country']}-{task['region']}-{task['year']}"
            .replace("_", "-")
        )

        parameters = {
            "commodity": task["commodity"],
            "country": task["country"],
            "region": task["region"],
            "start_year": str(task["year"]),
            "end_year": str(task["year"]),
        }

        if dry_run:
            logger.info("[DRY RUN] Would submit: %s params=%s", job_name, parameters)
            submitted.append({"job_name": job_name, "parameters": parameters, "job_id": None})
            continue

        response = client.submit_job(
            jobName=job_name,
            jobQueue=job_queue,
            jobDefinition=job_definition,
            parameters=parameters,
        )

        job_id = response["jobId"]
        logger.info("Submitted job_name=%s job_id=%s", job_name, job_id)

        submitted.append(
            {
                "job_name": job_name,
                "parameters": parameters,
                "job_id": job_id,
            }
        )

    return submitted


def save_run_record(submitted: list[dict], commodity: str, start_year: int, end_year: int) -> None:
    run_id = utc_now_iso().replace(":", "-")
    output_dir = Path("data/batch_runs")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"nasa_power_backfill_{run_id}.json"

    payload = {
        "run_id": run_id,
        "source": "nasa_power",
        "commodity": commodity,
        "start_year": start_year,
        "end_year": end_year,
        "task_count": len(submitted),
        "tasks": submitted,
    }

    output_path.write_text(json.dumps(payload, indent=2))
    logger.info("Run record saved to %s", output_path)


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
