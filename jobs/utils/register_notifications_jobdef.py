"""Register (a new revision of) the ``leviathan-dev-notifications`` Batch job definition (Phase 8 P3).

A DEDICATED lightweight jobdef for the daily morning-brief sweep — deliberately NOT a reuse of
``leviathan-dev-evidence-build``: that jobdef's baked default command is the multi-hour, credit-burning
full evidence rebuild at 8 vCPU/16 GiB, so a scheduler whose ContainerOverrides key is ever miscased or
dropped would silently run it every day. Here the DEFAULT command already IS the light notifications task
at 1 vCPU/2 GiB — a dropped override is harmless.

Safety posture:
  - jobRoleArn = the dedicated Scan-scoped notifications role (terraform, Track C) — NOT batch-job-role
    (which the internet-facing serving task also assumes; it must never gain dynamodb:Scan).
  - GRAPHRAG_PROVIDER=bedrock pinned: the sweep lives in the Bedrock quota lane, never competing with
    serving's Anthropic-API RPM tier (or its prepaid credits). The Anthropic key secret is NOT injected —
    without it the anthropic path cannot even start (belt to the env pin + the in-code pin).
  - retryStrategy attempts=2: a Fargate-Spot reclaim retries once; the conditional notification writes
    make a retry duplicate-safe (idempotent sk), and a genuine bug re-runs once for pennies.

    python jobs/utils/register_notifications_jobdef.py            # register new revision
    python jobs/utils/register_notifications_jobdef.py --dry-run  # print, don't register
"""
from __future__ import annotations

import argparse
import json

import boto3

_ACCOUNT = "668891723125"
_REGION = "us-east-1"
_REPO = "leviathan-dev-leviathan-embedder"        # same image (the task file + news module + configs baked)
_NAME = "leviathan-dev-notifications"
_BUCKET = "leviathan-dev-shahem-001"
_EVIDENCE_S3 = f"s3://{_BUCKET}/graphrag_evidence"   # nf.snapshot audit -> live_events/<date>/

_CONTAINER = {
    "image": f"{_ACCOUNT}.dkr.ecr.{_REGION}.amazonaws.com/{_REPO}:latest",
    "command": ["jobs/batch/build_notifications_task.py"],       # the DEFAULT command IS the right task
    "jobRoleArn": f"arn:aws:iam::{_ACCOUNT}:role/leviathan-dev-notifications-job-role",  # Scan-scoped (Track C)
    "executionRoleArn": f"arn:aws:iam::{_ACCOUNT}:role/leviathan-dev-batch-execution-role",
    "resourceRequirements": [
        {"type": "VCPU", "value": "1"},           # fetch + one Haiku call per commodity; no torch, no embed
        {"type": "MEMORY", "value": "2048"},
    ],
    "networkConfiguration": {"assignPublicIp": "ENABLED"},
    "fargatePlatformConfiguration": {"platformVersion": "LATEST"},
    "environment": [
        {"name": "AWS_REGION", "value": _REGION},
        {"name": "LEVIATHAN_BUCKET", "value": _BUCKET},
        {"name": "LEVIATHAN_ENV", "value": "dev"},
        {"name": "EVIDENCE_S3", "value": _EVIDENCE_S3},
        {"name": "GRAPHRAG_PROVIDER", "value": "bedrock"},        # never serving's Anthropic RPM/credits
        {"name": "GRAPHRAG_STORE_TABLE", "value": "leviathan-dev-terminal-store"},
        {"name": "PYTHONIOENCODING", "value": "utf-8"},
    ],
}


def main() -> None:
    ap = argparse.ArgumentParser(description="Register the leviathan-dev-notifications job definition.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--job-role", default=None, help="override the job role ARN (default: the dedicated role)")
    args = ap.parse_args()

    container = dict(_CONTAINER)
    if args.job_role:
        container["jobRoleArn"] = args.job_role

    payload = dict(
        jobDefinitionName=_NAME,
        type="container",
        platformCapabilities=["FARGATE"],
        containerProperties=container,
        retryStrategy={"attempts": 2},            # Spot-reclaim resilience; writes are idempotent by sk
    )

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return

    batch = boto3.client("batch", region_name=_REGION)
    resp = batch.register_job_definition(**payload)
    print(f"registered {resp['jobDefinitionName']} revision {resp['revision']} "
          f"({resp['jobDefinitionArn']})")


if __name__ == "__main__":
    main()
