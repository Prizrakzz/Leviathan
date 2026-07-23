"""Register (a new revision of) the ``leviathan-dev-freshness-poller`` Batch job definition.

A DEDICATED lightweight jobdef for the SILVER-F082 freshness poller (scripts/silver/freshness_poller.py),
mirroring register_notifications_jobdef.py exactly: the DEFAULT command already IS the poller at
0.25 vCPU / 1 GiB, so a scheduler whose ContainerOverrides key is ever dropped/miscased still runs the
right (cheap, read-mostly) task -- never some heavy default like the evidence rebuild.

Safety posture:
  - jobRoleArn = a DEDICATED freshness-poller job role (freshness_poller.tf.prepared, Track: this lane)
    scoped to s3:ListBucket on the data-lake bucket + cloudwatch:PutMetricData (namespace-conditioned).
    NOT batch-job-role (the internet-facing serving task assumes that; it must not gain PutMetricData
    on the account, and the poller must not gain serving's Bedrock/dynamo grants).
  - The poller only LISTS S3 and PUTS one custom metric per table -- no GET, no Athena, no writes to
    the data lake. It cannot mutate any table.
  - retryStrategy attempts=2: a Fargate-Spot reclaim retries once; a re-emit of the same lags is
    idempotent (CloudWatch just overwrites the datapoint at that timestamp).

NOTE: the worker image must contain scripts/silver/freshness_poller.py + src/leviathan/silver/freshness.py
+ the configs/silver/tables registry (all baked into the embedder image on the next build). Register a
new revision AFTER that image ships.

    python jobs/utils/register_freshness_poller_jobdef.py            # register new revision
    python jobs/utils/register_freshness_poller_jobdef.py --dry-run  # print, don't register
"""
from __future__ import annotations

import argparse
import json

import boto3

_ACCOUNT = "668891723125"
_REGION = "us-east-1"
_REPO = "leviathan-dev-leviathan-embedder"   # same image (poller + registry configs baked)
_NAME = "leviathan-dev-freshness-poller"
_BUCKET = "leviathan-dev-shahem-001"

_CONTAINER = {
    "image": f"{_ACCOUNT}.dkr.ecr.{_REGION}.amazonaws.com/{_REPO}:latest",
    "command": ["scripts/silver/freshness_poller.py"],       # the DEFAULT command IS the poller
    "jobRoleArn": f"arn:aws:iam::{_ACCOUNT}:role/leviathan-dev-freshness-poller-job-role",  # ListBucket + PutMetricData only
    "executionRoleArn": f"arn:aws:iam::{_ACCOUNT}:role/leviathan-dev-batch-execution-role",
    "resourceRequirements": [
        {"type": "VCPU", "value": "0.25"},        # a few list_objects_v2 pages + put_metric_data
        {"type": "MEMORY", "value": "1024"},
    ],
    "networkConfiguration": {"assignPublicIp": "ENABLED"},
    "fargatePlatformConfiguration": {"platformVersion": "LATEST"},
    "environment": [
        {"name": "AWS_REGION", "value": _REGION},
        {"name": "LEVIATHAN_BUCKET", "value": _BUCKET},
        {"name": "LEVIATHAN_ENV", "value": "dev"},
        {"name": "PYTHONIOENCODING", "value": "utf-8"},
    ],
}


def main() -> None:
    ap = argparse.ArgumentParser(description="Register the leviathan-dev-freshness-poller job definition.")
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
        retryStrategy={"attempts": 2},            # Spot-reclaim resilience; re-emit is idempotent
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
