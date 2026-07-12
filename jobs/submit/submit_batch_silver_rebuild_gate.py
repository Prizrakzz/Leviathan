"""Submit the silver_rebuild_gate (SILVER-C001) as an in-VPC Fargate Batch job.

Branch-A tables need the RDS mirror (reachable only in-VPC), so the gate runs on the evidence-build job
definition -- the same reuse as the numbers-pg loader/parity: that jobdef's image bakes src/+configs/, its
execution role injects EVIDENCE_PG_DSN, and its task role carries Athena. The ondemand queue prevents a Spot
reclaim mid-reload.

    python jobs/submit/submit_batch_silver_rebuild_gate.py --dry-run --tables silver_wasde
    python jobs/submit/submit_batch_silver_rebuild_gate.py --tables silver_wasde,silver_chirps
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

logger = get_logger("submit_silver_rebuild_gate")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()
    env = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    job_queue = f"{project}-{env}-queue-ondemand"                # no Spot reclaim mid-reload
    job_definition = f"{project}-{env}-evidence-build"           # image + DSN secret + Athena on the role

    ap = argparse.ArgumentParser(description="Submit the silver_rebuild_gate as an in-VPC Batch job")
    ap.add_argument("--tables", required=True, help="comma-separated rebuilt table ids")
    ap.add_argument("--asof", default="2026-02-15", help="census --diff baseline as-of")
    ap.add_argument("--vcpu", type=int, default=2)
    ap.add_argument("--memory", type=int, default=8192)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    aws_region = get_required_env("AWS_REGION")
    command = ["jobs/audit/silver_rebuild_gate.py", "--tables", args.tables, "--asof", args.asof]
    overrides = {"command": command,
                 "resourceRequirements": [{"type": "VCPU", "value": str(args.vcpu)},
                                          {"type": "MEMORY", "value": str(args.memory)}]}
    job_name = "silver-rebuild-gate-" + args.tables.replace(",", "-").replace("_", "-")[:48]

    logger.info("queue=%s job_def=%s command: python %s", job_queue, job_definition, " ".join(command))
    if args.dry_run:
        logger.info("[DRY RUN] would submit job_name=%s", job_name)
        return
    client = boto3.client("batch", region_name=aws_region)
    resp = client.submit_job(jobName=job_name, jobQueue=job_queue, jobDefinition=job_definition,
                             containerOverrides=overrides)
    logger.info("Submitted job_name=%s job_id=%s", job_name, resp["jobId"])
    run_id = utc_now_iso().replace(":", "-")
    write_run_record(Path("data/batch_runs") / f"silver_rebuild_gate_{run_id}.json",
                     {"run_id": run_id, "job_name": job_name, "job_id": resp["jobId"], "tables": args.tables})


if __name__ == "__main__":
    main()
