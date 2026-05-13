"""One-shot backfill orchestrator — designed to run as an AWS Batch Fargate task.

Sequence
--------
1. Submit all NASA POWER Batch worker tasks across selected commodities.
2. Poll until every Batch job reaches a terminal state.
3. Start raw→bronze Glue jobs for all commodities in parallel.
4. Poll until all Glue runs complete.
5. Start bronze→silver Glue jobs for all commodities in parallel.
6. Poll until all Glue runs complete.
7. Print per-commodity summary table. Exit non-zero on any failure.

The orchestrator runs as a single long-lived container (~36 min for all 31
commodities, 1981-2024) so it requires a 16-hour Batch timeout ceiling.

Run locally (dry-run):
    python jobs/orchestrate_backfill.py --dry-run --commodities cocoa
    python jobs/orchestrate_backfill.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3

# Import shared task building / submission helpers from the sibling script.
sys.path.insert(0, str(Path(__file__).parent))
from submit_batch_backfill_nasa_power import build_tasks, submit_tasks

from leviathan.common.config import get_required_env, load_env, load_yaml
from leviathan.common.logging import get_logger

logger = get_logger("orchestrate_backfill")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALL_COMMODITIES: list[str] = [
    "cocoa",
    "corn_cbot",
    "campinas_corn_reference_bmf",
    "french_wheat_matif",
    "french_maize_matif",
    "hard_red_winter_wheat_kcbt",
    "hard_red_spring_wheat_mgex",
    "soft_red_winter_wheat_cbot",
    "rough_rice_cbot",
    "south_african_white_maize_jse",
    "south_african_yellow_maize_jse",
    "soybeans_cbot",
    "soybean_meal_cbot",
    "soybean_oil_cbot",
    "soybeans_no_1_dce",
    "soybeans_no_2_dce",
    "soybean_meal_dce",
    "soybean_oil_dce",
    "french_rapeseed_matif",
    "canola_ice",
    "rapeseed_oil_zce",
    "rapeseed_meal_zce",
    "malaysian_crude_palm_oil_cme",
    "palm_olein_dce",
    "brazilian_arabica_coffee",
    "arabica_coffee",
    "robusta_coffee",
    "cotton",
    "raw_sugar",
    "white_sugar",
    "frozen_orange_juice",
]

POLL_INTERVAL_SECONDS = 30
BATCH_DESCRIBE_CHUNK = 100  # AWS hard limit per describe_jobs call


# ---------------------------------------------------------------------------
# Batch polling
# ---------------------------------------------------------------------------

def poll_batch_jobs(
    client: boto3.client,
    job_ids: list[str],
    dry_run: bool = False,
) -> dict[str, str]:
    """Poll until all jobs reach a terminal state. Returns {job_id: final_status}."""
    if dry_run:
        return {jid: "SUCCEEDED" for jid in job_ids}

    remaining: set[str] = set(job_ids)
    results: dict[str, str] = {}

    while remaining:
        remaining_list = list(remaining)
        for i in range(0, len(remaining_list), BATCH_DESCRIBE_CHUNK):
            chunk = remaining_list[i : i + BATCH_DESCRIBE_CHUNK]
            for job in client.describe_jobs(jobs=chunk)["jobs"]:
                if job["status"] in ("SUCCEEDED", "FAILED"):
                    results[job["jobId"]] = job["status"]
                    remaining.discard(job["jobId"])

        if remaining:
            succeeded = sum(1 for s in results.values() if s == "SUCCEEDED")
            failed = sum(1 for s in results.values() if s == "FAILED")
            logger.info(
                "Batch: %d pending  %d succeeded  %d failed",
                len(remaining),
                succeeded,
                failed,
            )
            time.sleep(POLL_INTERVAL_SECONDS)

    return results


# ---------------------------------------------------------------------------
# Glue helpers
# ---------------------------------------------------------------------------

def _start_glue_run(
    client: boto3.client,
    job_name: str,
    commodity: str,
    extra_args: dict[str, str] | None = None,
) -> tuple[str, str, str]:
    """Start a single Glue job run. Returns (job_name, run_id, commodity)."""
    arguments: dict[str, str] = {"--commodity": commodity}
    if extra_args:
        arguments.update(extra_args)
    run_id = client.start_job_run(JobName=job_name, Arguments=arguments)["JobRunId"]
    logger.info("Started Glue job=%s commodity=%s run_id=%s", job_name, commodity, run_id)
    return job_name, run_id, commodity


def poll_glue_runs(
    client: boto3.client,
    runs: list[tuple[str, str, str]],  # [(job_name, run_id, commodity), ...]
    dry_run: bool = False,
) -> dict[str, str]:
    """Poll until all Glue runs reach a terminal state. Returns {run_id: status}."""
    if dry_run:
        return {run_id: "SUCCEEDED" for _, run_id, _ in runs}

    remaining: set[tuple[str, str, str]] = set(runs)
    results: dict[str, str] = {}

    while remaining:
        done: set[tuple[str, str, str]] = set()
        for job_name, run_id, commodity in remaining:
            state = client.get_job_run(JobName=job_name, RunId=run_id)["JobRun"]["JobRunState"]
            if state in ("SUCCEEDED", "FAILED", "ERROR", "TIMEOUT"):
                results[run_id] = state
                done.add((job_name, run_id, commodity))
                logger.info(
                    "Glue %s commodity=%s run_id=%s → %s",
                    job_name,
                    commodity,
                    run_id,
                    state,
                )
        remaining -= done
        if remaining:
            logger.info("Glue: %d runs still in progress...", len(remaining))
            time.sleep(POLL_INTERVAL_SECONDS)

    return results


def run_glue_stage(
    glue: boto3.client,
    job_name: str,
    commodities: list[str],
    dry_run: bool,
    extra_args: dict[str, str] | None = None,
) -> dict[str, str]:
    """Start all Glue runs for a stage in parallel, then poll to completion.

    Returns {commodity: final_status}.
    """
    if dry_run:
        logger.info("[DRY RUN] Would start %d Glue runs for job: %s", len(commodities), job_name)
        return {c: "SUCCEEDED" for c in commodities}

    runs: list[tuple[str, str, str]] = []

    with ThreadPoolExecutor(max_workers=min(len(commodities), 50)) as pool:
        futures = {
            pool.submit(_start_glue_run, glue, job_name, c, extra_args): c
            for c in commodities
        }
        for f in as_completed(futures):
            runs.append(f.result())

    statuses = poll_glue_runs(glue, runs, dry_run)
    # Map back from run_id to commodity
    run_id_to_commodity = {run_id: commodity for _, run_id, commodity in runs}
    return {run_id_to_commodity[run_id]: status for run_id, status in statuses.items()}


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(
    commodities: list[str],
    batch_results: dict[str, dict],
    r2b_results: dict[str, str],
    b2s_results: dict[str, str],
) -> int:
    """Print per-commodity result table. Returns exit code (0 = all OK)."""
    print("\n" + "=" * 82)
    print("BACKFILL ORCHESTRATOR — SUMMARY")
    print("=" * 82)
    print(f"{'COMMODITY':<45} {'BATCH':>12} {'RAW→BRZ':>10} {'BRZ→SLV':>10}")
    print("-" * 82)

    any_failure = False
    for c in commodities:
        br = batch_results.get(c, {"succeeded": 0, "failed": 0})
        ok, fail = br["succeeded"], br["failed"]
        batch_str = f"{ok}✓" if fail == 0 else f"{ok}✓ {fail}✗"
        r2b = r2b_results.get(c, "N/A")
        b2s = b2s_results.get(c, "N/A")
        if fail > 0 or r2b != "SUCCEEDED" or b2s != "SUCCEEDED":
            any_failure = True
        print(f"{c:<45} {batch_str:>12} {r2b:>10} {b2s:>10}")

    print("=" * 82)
    return 1 if any_failure else 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Orchestrate full NASA POWER backfill: "
            "Batch worker tasks → raw→bronze Glue → bronze→silver Glue."
        )
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=1981,
        help="First year to backfill (default: 1981).",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=2024,
        help="Last year to backfill (default: 2024).",
    )
    parser.add_argument(
        "--commodities",
        default="all",
        help='Comma-separated list of commodities, or "all" (default).',
    )
    parser.add_argument(
        "--job-queue",
        default=None,
        help="Batch job queue name. Defaults to <project>-<env>-queue.",
    )
    parser.add_argument(
        "--job-definition",
        default=None,
        help="Batch worker job definition. Defaults to <project>-<env>-nasa-power-backfill.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would happen without making any AWS API calls.",
    )
    args = parser.parse_args()

    load_env()

    aws_region = get_required_env("AWS_REGION")
    env        = get_required_env("LEVIATHAN_ENV")
    project    = os.environ.get("LEVIATHAN_PROJECT", "leviathan")

    commodities = (
        ALL_COMMODITIES
        if args.commodities.strip().lower() == "all"
        else [c.strip() for c in args.commodities.split(",")]
    )

    job_queue      = args.job_queue       or f"{project}-{env}-queue"
    job_definition = args.job_definition  or f"{project}-{env}-nasa-power-backfill"
    r2b_job_name   = f"{project}-{env}-raw-to-bronze-nasa-power"
    b2s_job_name   = f"{project}-{env}-bronze-to-silver-nasa-power"

    logger.info(
        "Orchestrator starting  commodities=%d  years=%d-%d  dry_run=%s",
        len(commodities),
        args.start_year,
        args.end_year,
        args.dry_run,
    )

    # -----------------------------------------------------------------------
    # Step 1: Build + submit all Batch worker tasks
    # -----------------------------------------------------------------------
    all_tasks: list[dict] = []
    for commodity in commodities:
        geography = load_yaml(f"configs/geographies/{commodity}_regions.yaml")
        tasks = build_tasks(
            geography_config=geography,
            commodity=commodity,
            start_year=args.start_year,
            end_year=args.end_year,
        )
        all_tasks.extend(tasks)

    logger.info("Total Batch tasks to submit: %d", len(all_tasks))

    submitted = submit_tasks(
        tasks=all_tasks,
        job_queue=job_queue,
        job_definition=job_definition,
        aws_region=aws_region,
        dry_run=args.dry_run,
    )

    # -----------------------------------------------------------------------
    # Step 2: Poll all Batch jobs
    # -----------------------------------------------------------------------
    job_ids = [s["job_id"] for s in submitted if s["job_id"]]
    logger.info("Polling %d Batch jobs...", len(job_ids))

    batch_client = boto3.client("batch", region_name=aws_region)
    batch_statuses = poll_batch_jobs(batch_client, job_ids, dry_run=args.dry_run)

    # Aggregate per commodity
    batch_results: dict[str, dict] = {c: {"succeeded": 0, "failed": 0} for c in commodities}
    for s in submitted:
        commodity = s["parameters"]["commodity"]
        job_id    = s["job_id"]
        if job_id:
            status = batch_statuses.get(job_id, "UNKNOWN")
            key = "succeeded" if status == "SUCCEEDED" else "failed"
            batch_results[commodity][key] += 1

    failed_count = sum(1 for st in batch_statuses.values() if st != "SUCCEEDED")
    if failed_count:
        logger.warning(
            "%d Batch tasks failed — Glue will still run for commodities with partial data.",
            failed_count,
        )

    # -----------------------------------------------------------------------
    # Step 3: Glue raw → bronze (all commodities in parallel)
    # -----------------------------------------------------------------------
    glue = boto3.client("glue", region_name=aws_region)
    logger.info("Starting Glue raw→bronze for %d commodities...", len(commodities))
    r2b_results = run_glue_stage(glue, r2b_job_name, commodities, dry_run=args.dry_run)

    # -----------------------------------------------------------------------
    # Step 4: Glue bronze → silver (all commodities in parallel)
    # -----------------------------------------------------------------------
    logger.info("Starting Glue bronze→silver for %d commodities...", len(commodities))
    b2s_results = run_glue_stage(glue, b2s_job_name, commodities, dry_run=args.dry_run)

    # -----------------------------------------------------------------------
    # Summary + exit code
    # -----------------------------------------------------------------------
    exit_code = print_summary(commodities, batch_results, r2b_results, b2s_results)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
