"""Submit USDA ESR bronze → silver as a single AWS Batch Fargate task.

ESR processes all 10 commodity codes in one job (no per-commodity loop).
Output: silver/esr/commodity={slug}/part-000.parquet for each of the
7 Leviathan slugs covered by ESR data.

Usage:
    python jobs/submit/submit_batch_b2s_esr.py
    python jobs/submit/submit_batch_b2s_esr.py --dry-run
    python jobs/submit/submit_batch_b2s_esr.py --force-overwrite
"""
from __future__ import annotations

import argparse
import logging
import sys

import boto3

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger

logger = get_logger("submit_batch_b2s_esr")

_JOB_DEF_NAME = "leviathan-dev-esr-bronze-to-silver"
_JOB_QUEUE = "leviathan-dev-queue"
# pinned by DIGEST (BF-W1 discipline): read from `aws ecr describe-images`, never a build log or :latest
_ECR_IMAGE = (
    "668891723125.dkr.ecr.us-east-1.amazonaws.com/leviathan-dev-leviathan-worker"
    "@sha256:7a8b32e638c27c8e4d469c44c5f9d495be3303f2e568dce6593c5ad2e2f64f8f"
)
_JOB_ROLE_ARN = "arn:aws:iam::668891723125:role/leviathan-dev-batch-job-role"
_EXEC_ROLE_ARN = "arn:aws:iam::668891723125:role/leviathan-dev-batch-execution-role"
_LOG_GROUP = "/aws/batch/leviathan-dev"
_REGION = "us-east-1"


def _ensure_job_definition(batch: object, bucket: str) -> str:
    """Register the job definition; return a COMPATIBLE revision's ARN.

    describe_job_definitions returns revisions in UNDEFINED order -- a blind [-1] ran
    jobdef rev1 (whose command lacks --vintage-mode/--publish-mode), so the shadow
    all-vintage submit silently no-oped as latest+dry-run (BF-W2 step-10 live find; the
    gold-weather submit had the same class). Reuse only the highest revision whose
    command threads THIS script's parameter names AND whose image matches the pin."""
    resp = batch.describe_job_definitions(
        jobDefinitionName=_JOB_DEF_NAME, status="ACTIVE"
    )
    active = sorted(resp.get("jobDefinitions", []), key=lambda d: d["revision"])
    if active:
        latest = active[-1]
        cp = latest["containerProperties"]
        cmd = cp.get("command", [])
        if ("Ref::vintage_mode" in cmd and "Ref::publish_mode" in cmd
                and cp.get("image") == _ECR_IMAGE):
            arn = latest["jobDefinitionArn"]
            logger.info("Using existing job definition rev%s: %s", latest["revision"], arn)
            return arn
        logger.info("rev%s incompatible (command or image) -- registering a new revision",
                    latest["revision"])

    logger.info("Registering new job definition: %s", _JOB_DEF_NAME)
    resp = batch.register_job_definition(
        jobDefinitionName=_JOB_DEF_NAME,
        type="container",
        containerProperties={
            "image": _ECR_IMAGE,
            "jobRoleArn": _JOB_ROLE_ARN,
            "executionRoleArn": _EXEC_ROLE_ARN,
            "resourceRequirements": [
                {"type": "VCPU", "value": "2"},
                {"type": "MEMORY", "value": "4096"},
            ],
            "networkConfiguration": {"assignPublicIp": "ENABLED"},
            "logConfiguration": {
                "logDriver": "awslogs",
                "options": {
                    "awslogs-group": _LOG_GROUP,
                    "awslogs-region": _REGION,
                    "awslogs-stream-prefix": "esr-bronze-to-silver",
                },
                "secretOptions": [],
            },
            "command": [
                "jobs/batch/bronze_to_silver_esr_task.py",
                "--bucket",
                "Ref::bucket",
                "--aws-region",
                "Ref::aws_region",
                "--vintage-mode",
                "Ref::vintage_mode",
                "--publish-mode",
                "Ref::publish_mode",
                "--force-overwrite",
                "Ref::force_overwrite",
            ],
            "environment": [
                {"name": "AWS_REGION", "value": _REGION},
                {"name": "LEVIATHAN_BUCKET", "value": bucket},
                {"name": "LEVIATHAN_ENV", "value": "dev"},
            ],
        },
        platformCapabilities=["FARGATE"],
    )
    arn = resp["jobDefinitionArn"]
    logger.info("Registered: %s", arn)
    return arn


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(description="Submit ESR bronze→silver Batch job")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=_REGION, dest="aws_region")
    parser.add_argument("--vintage-mode", default="latest", choices=["latest", "all"],
                        dest="vintage_mode",
                        help="latest (default) | all (option-b per-week vintages, BF-W2)")
    parser.add_argument("--publish-mode", default="dry-run", dest="publish_mode",
                        help="dry-run (default; kill switch) | shadow | canonical (signed approval)")
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="do not submit the Batch job; print the plan only")
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    batch = boto3.client("batch", region_name=args.aws_region)

    job_def_arn = _ensure_job_definition(batch, bucket)

    params = {
        "bucket": bucket,
        "aws_region": args.aws_region,
        "vintage_mode": args.vintage_mode,
        "publish_mode": args.publish_mode,
        "force_overwrite": "true" if args.force_overwrite else "false",
    }

    if args.dry_run:
        logger.info("[dry-run] Would submit: job_def=%s  params=%s", job_def_arn, params)
        return

    resp = batch.submit_job(
        jobName="esr-bronze-to-silver",
        jobQueue=_JOB_QUEUE,
        jobDefinition=job_def_arn,
        parameters=params,
    )
    job_id = resp["jobId"]
    logger.info("Submitted: jobId=%s", job_id)
    logger.info("Monitor: aws batch describe-jobs --jobs %s --region %s", job_id, args.aws_region)


if __name__ == "__main__":
    main()
