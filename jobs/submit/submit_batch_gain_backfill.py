"""Submit GAIN backfill as 10 parallel AWS Batch Fargate tasks (one per commodity).

All 10 run concurrently — crawl + manifest + S3 upload inside each container.

Usage
-----
    python jobs/submit/submit_batch_gain_backfill.py
    python jobs/submit/submit_batch_gain_backfill.py --commodities wheat corn soybeans
    python jobs/submit/submit_batch_gain_backfill.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import boto3

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_batch_gain_backfill")

# ---------------------------------------------------------------------------
# Commodity definitions
# ---------------------------------------------------------------------------

COMMODITIES: list[dict] = [
    {"name": "wheat",       "commodity_id": "15",    "countries": "US,FR,AU,CA,UA,RU,IN,PK,EG,AR,CN,DE,PL,TR"},
    {"name": "corn",        "commodity_id": "14",    "countries": "US,BR,AR,CN,UA,FR,ZA,MX,PH,NG"},
    {"name": "soybeans",    "commodity_id": "27",    "countries": "BR,US,AR,CN,PY,BO,IN,UA"},
    {"name": "palm_oil",    "commodity_id": "13023", "countries": "MY,ID,TH,CO,NG,CM,GH"},
    {"name": "sugar",       "commodity_id": "34",    "countries": "BR,IN,TH,AU,CO,MX,ID,PH,EC"},
    {"name": "cotton",      "commodity_id": "6",     "countries": "US,IN,CN,BR,AU,PK,UZ"},
    {"name": "rapeseed",    "commodity_id": "28",    "countries": "CA,AU,FR,CN,DE,UA,PL"},
    {"name": "rice",        "commodity_id": "16",    "countries": "TH,VN,IN,CN,US,PK"},
    {"name": "soybean_oil",  "commodity_id": "13022", "countries": "BR,US,AR,CN"},
    {"name": "soybean_meal", "commodity_id": "13021", "countries": "US,BR,AR,CN"},
    # Processed Fruit (13014) is the closest GAIN category for FCOJ — no dedicated OJ ID
    {"name": "orange_juice", "commodity_id": "13014", "countries": "BR,US,MX", "title_filter": "orange"},
    # Cocoa has no FAS taxonomy ID — uses title-filter on all GAIN reports
    {"name": "cocoa",        "commodity_id": None,    "countries": "CI,GH,CM,ID,NG,EC,PE", "title_filter": "cocoa"},
]


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------

def submit_tasks(
    commodities: list[dict],
    job_queue: str,
    job_definition: str,
    bucket: str,
    aws_region: str,
    sleep_seconds: str,
    dry_run: bool,
) -> list[dict]:
    client = boto3.client("batch", region_name=aws_region)
    submitted: list[dict] = []

    for c in commodities:
        job_name = f"gain-backfill-{c['name'].replace('_', '-')}"

        # Build command override — Batch parameters don't support optional args cleanly,
        # so we use containerOverrides.command to pass the full arg list.
        command = [
            "jobs/batch/gain_backfill_task.py",
            "--commodity-name", c["name"],
            "--target-countries", c["countries"],
            "--bucket", bucket,
            "--aws-region", aws_region,
            "--skip-existing-s3",
            "--sleep-seconds", sleep_seconds,
        ]
        if c.get("commodity_id") is not None:
            command += ["--commodity-id", str(c["commodity_id"])]
        if c.get("title_filter"):
            command += ["--title-filter", c["title_filter"]]

        if dry_run:
            logger.info("[DRY RUN] Would submit: %s  cmd=%s", job_name, command)
            submitted.append({"job_name": job_name, "job_id": None, "commodity": c["name"]})
            continue

        response = client.submit_job(
            jobName=job_name,
            jobQueue=job_queue,
            jobDefinition=job_definition,
            containerOverrides={"command": command},
        )
        job_id = response["jobId"]
        logger.info("Submitted  job_name=%s  job_id=%s", job_name, job_id)
        submitted.append({"job_name": job_name, "job_id": job_id, "commodity": c["name"]})

    return submitted


def save_run_record(submitted: list[dict], commodities: list[dict]) -> None:
    run_id = utc_now_iso().replace(":", "-")
    output_dir = Path("data/batch_runs")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"gain_backfill_{run_id}.json"
    payload = {
        "run_id": run_id,
        "source": "usda_gain",
        "commodities": [c["name"] for c in commodities],
        "task_count": len(submitted),
        "tasks": submitted,
    }
    output_path.write_text(json.dumps(payload, indent=2))
    logger.info("Run record saved to %s", output_path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    load_env()

    env     = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    batch_queue   = f"{project}-{env}-queue"
    job_definition = f"{project}-{env}-gain-backfill"

    parser = argparse.ArgumentParser(
        description="Submit GAIN backfill as 10 parallel Batch Fargate tasks."
    )
    parser.add_argument(
        "--commodities",
        nargs="+",
        metavar="NAME",
        default=None,
        help="Subset of commodity names to submit (default: all 10).",
    )
    parser.add_argument(
        "--sleep-seconds",
        default="2",
        help="Seconds between PDF downloads inside each task (default: 2).",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    bucket     = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    commodities = COMMODITIES
    if args.commodities:
        names = {c["name"] for c in COMMODITIES}
        unknown = set(args.commodities) - names
        if unknown:
            raise SystemExit(f"Unknown commodities: {unknown}")
        commodities = [c for c in COMMODITIES if c["name"] in args.commodities]

    logger.info(
        "Submitting %d GAIN backfill tasks to queue=%s  job_def=%s",
        len(commodities), batch_queue, job_definition,
    )

    submitted = submit_tasks(
        commodities=commodities,
        job_queue=batch_queue,
        job_definition=job_definition,
        bucket=bucket,
        aws_region=aws_region,
        sleep_seconds=args.sleep_seconds,
        dry_run=args.dry_run,
    )

    save_run_record(submitted, commodities)

    if not args.dry_run:
        logger.info("All %d tasks submitted. Monitor at:", len(submitted))
        logger.info(
            "  https://%s.console.aws.amazon.com/batch/home?region=%s#jobs",
            aws_region, aws_region,
        )


if __name__ == "__main__":
    main()
