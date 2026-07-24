"""Submit the T2B pattern-records ledger sweep (daily) / backfill grid as an AWS Batch Fargate task.

Runs on a DEDICATED scoped jobdef (the P3 morning-brief pattern, plan sec 7 step 5): its own role +
jobdef, the EventBridge schedule created DISABLED, ONE manual day-0 run, ENABLE only after review. The
sweep is an ENGINE REPLAY over the pg mirror -- so the jobdef MUST carry the full serving pg env
(GRAPHRAG_NUMBERS_BACKEND=pg + EVIDENCE_PG_DSN from Secrets Manager); without it the quantify seam is
DEAD and every fired verdict is an ARTIFACT (the 2026-07-23 phantom-regression lesson). The task
asserts pg-only at startup and refuses to run otherwise.

Usage:
    python jobs/submit/submit_batch_pattern_records_sweep.py --dry-run           # daily sweep, plan only
    python jobs/submit/submit_batch_pattern_records_sweep.py --backfill --dry-run # the weekly grid
    python jobs/submit/submit_batch_pattern_records_sweep.py --publish-mode shadow
"""
from __future__ import annotations

import argparse
import logging
import sys

import boto3

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger

logger = get_logger("submit_batch_pattern_records_sweep")

# Dedicated scoped jobdef (plan sec 7 step 5; authored, registered at rollout -- NOT applied here).
_JOB_DEF_NAME = "leviathan-dev-pattern-records"
_JOB_QUEUE = "leviathan-dev-queue"
# Pinned by DIGEST -- content-check the sweep entrypoint (inspect.getsource markers) before use; never
# trust :latest (the d9b2e10e stale-:latest lesson). Filled at rollout step 3 after the image push.
_ECR_IMAGE = (
    "668891723125.dkr.ecr.us-east-1.amazonaws.com/leviathan-dev-leviathan-embedder"
    "@sha256:REPLACE_WITH_CONTENT_CHECKED_DIGEST"
)
# Own scoped role (least-privilege: s3 put under gold/pattern_records/*, glue on gold_pattern_records,
# the pg DSN secret) -- authored at rollout step 5, NOT the shared batch-job-role.
_JOB_ROLE_ARN = "arn:aws:iam::668891723125:role/leviathan-dev-pattern-records-role"
_EXEC_ROLE_ARN = "arn:aws:iam::668891723125:role/leviathan-dev-batch-execution-role"
# The pg DSN is injected as a Batch secret from Secrets Manager (never a plaintext env). Filled at
# rollout; the value is the same serving numbers DSN the evidence-build jobdef already mounts.
_PG_DSN_SECRET_ARN = "arn:aws:secretsmanager:us-east-1:668891723125:secret:leviathan-dev-numbers-pg-dsn"
_LOG_GROUP = "/aws/batch/leviathan-dev"
_REGION = "us-east-1"


def _ensure_job_definition(batch, bucket: str) -> str:
    """Register the jobdef; reuse the active revision ONLY when its image matches the pinned digest
    (a re-pinned digest else runs stale code -- the BF-W1 lesson)."""
    resp = batch.describe_job_definitions(jobDefinitionName=_JOB_DEF_NAME, status="ACTIVE")
    active = sorted(resp.get("jobDefinitions", []), key=lambda d: d["revision"])
    if active and active[-1]["containerProperties"].get("image") == _ECR_IMAGE:
        arn = active[-1]["jobDefinitionArn"]
        logger.info("Using existing job definition (image matches pin): %s", arn)
        return arn
    logger.info("Registering new job definition revision: %s", _JOB_DEF_NAME)
    resp = batch.register_job_definition(
        jobDefinitionName=_JOB_DEF_NAME,
        type="container",
        containerProperties={
            "image": _ECR_IMAGE,
            "jobRoleArn": _JOB_ROLE_ARN,
            "executionRoleArn": _EXEC_ROLE_ARN,
            "resourceRequirements": [
                {"type": "VCPU", "value": "2"},
                {"type": "MEMORY", "value": "8192"},
            ],
            "networkConfiguration": {"assignPublicIp": "ENABLED"},
            "logConfiguration": {
                "logDriver": "awslogs",
                "options": {
                    "awslogs-group": _LOG_GROUP,
                    "awslogs-region": _REGION,
                    "awslogs-stream-prefix": "pattern-records",
                },
                "secretOptions": [],
            },
            # Daily-sweep default command; the --backfill variant overrides it via containerOverrides at
            # submit time (a Ref:: token cannot be conditionally empty).
            "command": [
                "jobs/batch/pattern_records_sweep_task.py",
                "--asof", "Ref::asof",
                "--publish-mode", "Ref::publish_mode",
            ],
            "environment": [
                {"name": "AWS_REGION", "value": _REGION},
                {"name": "LEVIATHAN_BUCKET", "value": bucket},
                {"name": "LEVIATHAN_ENV", "value": "dev"},
                # pg-only serving env: the quantify seam is DEAD without it (assert at task startup).
                {"name": "GRAPHRAG_NUMBERS_BACKEND", "value": "pg"},
            ],
            "secrets": [
                {"name": "EVIDENCE_PG_DSN", "valueFrom": _PG_DSN_SECRET_ARN},
            ],
        },
        platformCapabilities=["FARGATE"],
    )
    arn = resp["jobDefinitionArn"]
    logger.info("Registered: %s", arn)
    return arn


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s -- %(message)s")
    load_env()
    parser = argparse.ArgumentParser(description="Submit the pattern-records sweep Batch job")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=_REGION, dest="aws_region")
    parser.add_argument("--asof", default="today", help="sweep as-of (YYYY-MM-DD) or 'today'")
    parser.add_argument("--backfill", action="store_true",
                        help="run the bounded weekly grid (provenance=backfill_grid)")
    parser.add_argument("--publish-mode", default="dry-run", dest="publish_mode",
                        help="dry-run (default) | shadow | canonical (signed approval)")
    parser.add_argument("--dry-run", action="store_true", help="print the submission, do not submit")
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    asof = _today() if args.asof == "today" else args.asof
    params = {"asof": asof, "publish_mode": args.publish_mode}
    overrides = None
    if args.backfill:  # the backfill variant overrides the daily-sweep command with --backfill appended
        overrides = {"command": ["jobs/batch/pattern_records_sweep_task.py", "--asof", asof,
                                 "--publish-mode", args.publish_mode, "--backfill"]}

    if args.dry_run:
        logger.info("[dry-run] would submit %s params=%s overrides=%s (backfill=%s, mode=%s)",
                    _JOB_DEF_NAME, params, overrides, args.backfill, args.publish_mode)
        return

    batch = boto3.client("batch", region_name=args.aws_region)
    job_def_arn = _ensure_job_definition(batch, bucket)
    submit_kw = dict(jobName=f"pattern-records-{'backfill' if args.backfill else 'daily'}-{asof}",
                     jobQueue=_JOB_QUEUE, jobDefinition=job_def_arn, parameters=params)
    if overrides is not None:
        submit_kw["containerOverrides"] = overrides
    resp = batch.submit_job(**submit_kw)
    logger.info("Submitted: jobId=%s", resp["jobId"])
    logger.info("Monitor: aws batch describe-jobs --jobs %s --region %s", resp["jobId"], args.aws_region)


def _today() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")


if __name__ == "__main__":
    main()
