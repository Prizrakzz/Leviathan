"""Submit the numbers->pg mirror loader (and/or the parity gate) as a Fargate Batch job.

Runs jobs/utils/load_pg_numbers.py (or jobs/utils/numbers_parity.py with --parity) on the evidence-build
job definition — the same reuse as submit_eval: that jobdef's image bakes src/ + configs/, its execution
role injects EVIDENCE_PG_DSN, and its task role now carries Athena (codified Stage-1). RDS is only
reachable in-VPC, so this is the loader's home.

    python jobs/submit/submit_batch_load_numbers_pg.py --dry-run
    python jobs/submit/submit_batch_load_numbers_pg.py                       # load the P1 set
    python jobs/submit/submit_batch_load_numbers_pg.py --tables silver_fred_fx,silver_noaa_oni
    python jobs/submit/submit_batch_load_numbers_pg.py --parity              # the blocking parity gate
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import boto3

from leviathan.common.batch_submit import write_run_record
from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_load_numbers_pg")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()
    env = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    job_queue = f"{project}-{env}-queue-ondemand"                # don't let Spot reclaim a mid-COPY loader
    job_definition = f"{project}-{env}-evidence-build"           # image + DSN secret + Athena on the role

    ap = argparse.ArgumentParser(description="Submit the numbers->pg mirror loader as a Batch job")
    ap.add_argument("--tables", default=None, help="comma-separated registry ids (default: loader's P1 set)")
    ap.add_argument("--parity", action="store_true", help="run the pg-vs-Athena parity gate instead")
    ap.add_argument("--vcpu", type=int, default=2)
    ap.add_argument("--memory", type=int, default=8192)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    aws_region = get_required_env("AWS_REGION")
    script = "jobs/utils/numbers_parity.py" if args.parity else "jobs/utils/load_pg_numbers.py"
    command = [script] + (["--tables", args.tables] if args.tables else [])
    overrides = {"command": command,
                 "resourceRequirements": [{"type": "VCPU", "value": str(args.vcpu)},
                                          {"type": "MEMORY", "value": str(args.memory)}]}
    job_name = ("numbers-pg-parity" if args.parity else "numbers-pg-load") + (
        f"-{args.tables.replace(',', '-').replace('_', '-')[:40]}" if args.tables else "")

    logger.info("queue=%s job_def=%s command: python %s", job_queue, job_definition, " ".join(command))
    if args.dry_run:
        logger.info("[DRY RUN] would submit job_name=%s", job_name)
        return
    client = boto3.client("batch", region_name=aws_region)
    resp = client.submit_job(jobName=job_name, jobQueue=job_queue, jobDefinition=job_definition,
                             containerOverrides=overrides)
    logger.info("Submitted job_name=%s job_id=%s", job_name, resp["jobId"])
    run_id = utc_now_iso().replace(":", "-")
    write_run_record(Path("data/batch_runs") / f"numbers_pg_{run_id}.json",
                     {"run_id": run_id, "job_name": job_name, "job_id": resp["jobId"],
                      "tables": args.tables, "parity": args.parity})


if __name__ == "__main__":
    main()
