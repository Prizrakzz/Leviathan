"""Submit ONE named administrative action on the serving Postgres (jobs/utils/pg_admin_once.py) as a Batch job.

Run by the OWNER. RDS is reachable only in-VPC; the job runs on the evidence-build job definition, whose
execution role injects EVIDENCE_PG_DSN. The action is chosen by name; this wrapper passes no SQL.

    python jobs/submit/submit_batch_pg_admin.py --action create-pg-stat-statements --dry-run
    python jobs/submit/submit_batch_pg_admin.py --action create-pg-stat-statements \
        --bootstrap-s3-uri s3://<bucket>/ops/probes/pg_admin_once.py
    python jobs/submit/submit_batch_pg_admin.py --action drop-evidence-props-old --confirm evidence_props_old \
        --bootstrap-s3-uri s3://<bucket>/ops/probes/pg_admin_once.py

``--bootstrap-s3-uri`` is the in-VPC probe route for a job definition whose image predates the script.
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

logger = get_logger("submit_pg_admin")
ACTIONS = ("create-pg-stat-statements", "drop-evidence-props-old")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()
    env = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    job_queue = f"{project}-{env}-queue-ondemand"
    default_jobdef = f"{project}-{env}-evidence-build"

    ap = argparse.ArgumentParser(description="Submit one named Postgres administrative action as a Batch job")
    ap.add_argument("--action", required=True, choices=ACTIONS)
    ap.add_argument("--confirm", default="", help="drop-evidence-props-old: the artifact's exact name")
    ap.add_argument("--job-definition", default=None, help=f"Batch job definition (default: {default_jobdef})")
    ap.add_argument("--bootstrap-s3-uri", default=None,
                    help="s3://bucket/key of jobs/utils/pg_admin_once.py, for an image that predates the script")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    job_definition = args.job_definition or default_jobdef
    aws_region = get_required_env("AWS_REGION")
    script_args = ["--action", args.action] + (["--confirm", args.confirm] if args.confirm else [])
    command = ["jobs/utils/pg_admin_once.py"] + script_args
    if args.bootstrap_s3_uri:
        bucket, _, key = args.bootstrap_s3_uri.removeprefix("s3://").partition("/")
        if not bucket or not key:
            raise SystemExit("--bootstrap-s3-uri must be s3://bucket/key")
        command = ["-c", ("import boto3,os,runpy,sys,tempfile;"
                          "p=os.path.join(tempfile.mkdtemp(),'pg_admin_once.py');"
                          f"boto3.client('s3').download_file({bucket!r},{key!r},p);"
                          f"sys.argv=['pg_admin_once.py']+{script_args!r};"
                          "runpy.run_path(p,run_name='__main__')")]
    overrides = {"command": command,
                 "resourceRequirements": [{"type": "VCPU", "value": "1"}, {"type": "MEMORY", "value": "4096"}]}
    job_name = "pg-admin-" + args.action

    logger.info("queue=%s job_def=%s command: python %s", job_queue, job_definition, " ".join(command))
    if args.dry_run:
        logger.info("[DRY RUN] would submit job_name=%s", job_name)
        return
    client = boto3.client("batch", region_name=aws_region)
    resp = client.submit_job(jobName=job_name, jobQueue=job_queue, jobDefinition=job_definition,
                             containerOverrides=overrides)
    logger.info("Submitted job_name=%s job_id=%s", job_name, resp["jobId"])
    run_id = utc_now_iso().replace(":", "-")
    write_run_record(Path("data/batch_runs") / f"pg_admin_{run_id}.json",
                     {"run_id": run_id, "job_name": job_name, "job_id": resp["jobId"], "action": args.action})


if __name__ == "__main__":
    main()
