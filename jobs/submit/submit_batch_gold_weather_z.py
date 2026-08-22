"""Submit the gold_weather_z transform (Phase D-W4) as a single AWS Batch Fargate task.

Reads silver weather parquet (NASA POWER + CHIRPS) directly from S3, one commodity at a
time (bounded memory), and writes gold/weather_z/{slug}.parquet -- the tall, monthly,
PIT-safe z table the D-W5 weather flip serves from. Sized for the transform, not the
output: the intermediate daily reads are the heavy part.

Runs on the EMBEDDER image (pinned by digest -- it carries leviathan.transforms.gold;
the worker image predates Phase D). Entrypoint is python, workdir /app, so the command
is the task path, mirroring submit_batch_b2s_esr.py.

Usage:
    python jobs/submit/submit_batch_gold_weather_z.py
    python jobs/submit/submit_batch_gold_weather_z.py --dry-run
    python jobs/submit/submit_batch_gold_weather_z.py --commodity corn_cbot
    python jobs/submit/submit_batch_gold_weather_z.py --force-overwrite
"""
from __future__ import annotations

import argparse
import logging
import sys

import boto3

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger

logger = get_logger("submit_batch_gold_weather_z")

_JOB_DEF_NAME = "leviathan-dev-gold-weather-z"
_JOB_QUEUE = "leviathan-dev-queue"
# Pinned by DIGEST (content-checked 2026-08-22: W1.1 basin aggregate rows -- BASINS registry +
# _tail_share metrics + frost_event_share -- present alongside the month-completeness gate + Z_CAP
# winsorize, tag 20260822T124518) -- never trust :latest, and read the digest from
# `aws ecr describe-images`, never a build log. Jobdef re-pinned to rev 7 same day (boto3
# copy-top-revision-swap-digest; tf drift recorded for the next fleet-bump batch).
_ECR_IMAGE = (
    "668891723125.dkr.ecr.us-east-1.amazonaws.com/leviathan-dev-leviathan-embedder"
    "@sha256:70de777e04a68c1e27f8a4f6e3169e8114a01d813e2b17b29425e5ba9399155b"
)
_JOB_ROLE_ARN = "arn:aws:iam::668891723125:role/leviathan-dev-batch-job-role"
_EXEC_ROLE_ARN = "arn:aws:iam::668891723125:role/leviathan-dev-batch-execution-role"
_LOG_GROUP = "/aws/batch/leviathan-dev"
_REGION = "us-east-1"


def _ensure_job_definition(batch: object, bucket: str) -> str:
    """Register job definition; return its ARN.

    Reuses the active jobdef ONLY when its image matches the pinned ``_ECR_IMAGE`` digest;
    otherwise registers a NEW revision. Without the image check a re-pinned digest is silently
    ignored -- the stale revision keeps running old code (BF-W1: the drought-floor fix ran on
    the OLD embedder digest because the pre-fix jobdef revision was blindly reused)."""
    resp = batch.describe_job_definitions(
        jobDefinitionName=_JOB_DEF_NAME, status="ACTIVE"
    )
    active = sorted(resp.get("jobDefinitions", []), key=lambda d: d["revision"])
    if active and active[-1]["containerProperties"].get("image") == _ECR_IMAGE:
        arn = active[-1]["jobDefinitionArn"]
        logger.info("Using existing job definition (image matches pin): %s", arn)
        return arn

    logger.info("Registering new job definition revision (image changed or absent): %s",
                _JOB_DEF_NAME)
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
                    "awslogs-stream-prefix": "gold-weather-z",
                },
                "secretOptions": [],
            },
            "command": [
                "jobs/batch/gold_weather_z_task.py",
                "--bucket",
                "Ref::bucket",
                "--aws-region",
                "Ref::aws_region",
                "--commodity",
                "Ref::commodity",
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
        format="%(asctime)s %(levelname)s %(name)s -- %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(description="Submit the gold_weather_z Batch job")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=_REGION, dest="aws_region")
    parser.add_argument("--commodity", default="all")
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    params = {
        "bucket": bucket,
        "aws_region": args.aws_region,
        "commodity": args.commodity,
        "force_overwrite": "true" if args.force_overwrite else "false",
    }

    if args.dry_run:
        logger.info("[dry-run] would submit %s with parameters=%s", _JOB_DEF_NAME, params)
        return

    batch = boto3.client("batch", region_name=args.aws_region)
    job_def_arn = _ensure_job_definition(batch, bucket)
    resp = batch.submit_job(
        jobName=f"gold-weather-z-{args.commodity}",
        jobQueue=_JOB_QUEUE,
        jobDefinition=job_def_arn,
        parameters=params,
    )
    logger.info("Submitted: jobId=%s", resp["jobId"])
    logger.info(
        "Monitor: aws batch describe-jobs --jobs %s --region %s", resp["jobId"], args.aws_region
    )


if __name__ == "__main__":
    main()
