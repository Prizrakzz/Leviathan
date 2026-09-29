"""Submit the READ-ONLY Postgres audit (jobs/utils/pg_audit.py) as a Fargate Batch job.

RDS is reachable only in-VPC. The audit runs on the evidence-build job definition, the same reuse as the
numbers loader: that jobdef's image bakes jobs/ + src/, and its execution role injects EVIDENCE_PG_DSN. The
job opens a read-only session and prints its report to its own log (one ``PG_AUDIT <section> <json>`` line
per chunk); it writes nothing to the database and nothing to the bucket.

    python jobs/submit/submit_batch_pg_audit.py --dry-run
    python jobs/submit/submit_batch_pg_audit.py
    python jobs/submit/submit_batch_pg_audit.py --top 60
    python jobs/submit/submit_batch_pg_audit.py --bootstrap-s3-uri s3://<bucket>/ops/probes/pg_audit.py

``--bootstrap-s3-uri`` is the in-VPC probe route for a job definition whose image predates the script: the
job downloads the script body from S3 and runs it (a short command; Batch overrides over 8192 characters fail
with no log stream). The body is the same read-only file; the session guard is in the file, not the route.
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

logger = get_logger("submit_pg_audit")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()
    env = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    job_queue = f"{project}-{env}-queue-ondemand"
    default_jobdef = f"{project}-{env}-evidence-build"           # image + DSN secret

    ap = argparse.ArgumentParser(description="Submit the read-only Postgres audit as a Batch job")
    ap.add_argument("--top", type=int, default=40, help="statements per ordering")
    ap.add_argument("--min-calls", type=int, default=3)
    ap.add_argument("--job-definition", default=None, help=f"Batch job definition (default: {default_jobdef})")
    ap.add_argument("--bootstrap-s3-uri", default=None,
                    help="s3://bucket/key of jobs/utils/pg_audit.py, for an image that predates the script")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    job_definition = args.job_definition or default_jobdef
    aws_region = get_required_env("AWS_REGION")
    script_args = ["--top", str(args.top), "--min-calls", str(args.min_calls)]
    command = ["jobs/utils/pg_audit.py"] + script_args
    if args.bootstrap_s3_uri:
        bucket, _, key = args.bootstrap_s3_uri.removeprefix("s3://").partition("/")
        if not bucket or not key:
            raise SystemExit("--bootstrap-s3-uri must be s3://bucket/key")
        command = ["-c", ("import boto3,os,runpy,sys,tempfile;"
                          "p=os.path.join(tempfile.mkdtemp(),'pg_audit.py');"
                          f"boto3.client('s3').download_file({bucket!r},{key!r},p);"
                          f"sys.argv=['pg_audit.py']+{script_args!r};"
                          "runpy.run_path(p,run_name='__main__')")]
    overrides = {"command": command,
                 "resourceRequirements": [{"type": "VCPU", "value": "1"}, {"type": "MEMORY", "value": "4096"}]}
    job_name = "pg-audit"

    logger.info("queue=%s job_def=%s command: python %s", job_queue, job_definition, " ".join(command))
    if args.dry_run:
        logger.info("[DRY RUN] would submit job_name=%s", job_name)
        return
    client = boto3.client("batch", region_name=aws_region)
    resp = client.submit_job(jobName=job_name, jobQueue=job_queue, jobDefinition=job_definition,
                             containerOverrides=overrides)
    logger.info("Submitted job_name=%s job_id=%s", job_name, resp["jobId"])
    run_id = utc_now_iso().replace(":", "-")
    write_run_record(Path("data/batch_runs") / f"pg_audit_{run_id}.json",
                     {"run_id": run_id, "job_name": job_name, "job_id": resp["jobId"], "top": args.top})


if __name__ == "__main__":
    main()
