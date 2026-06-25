"""Register (a new revision of) the ``leviathan-dev-train`` Batch job definition.

The training job def was originally created ad-hoc; this captures it in code so the
command template + defaults are reproducible.  Run after rebuilding the trainer image
when the runner's CLI surface changes.

The command threads experiment parameters through Batch ``Ref::`` substitution.  The
runner (jobs/batch/train_commodity.py) accepts ``--detrend``/``--optuna`` either bare
(local) or as a value ("true"/"false"), so they substitute cleanly here; the job-def
defaults below keep both OFF unless a submission overrides them.

    python jobs/utils/register_train_jobdef.py            # register new revision
    python jobs/utils/register_train_jobdef.py --dry-run  # print, don't register
"""
from __future__ import annotations

import argparse
import json

import boto3

_ACCOUNT = "668891723125"
_REGION = "us-east-1"
_REPO = "leviathan-dev-leviathan-trainer"
_NAME = "leviathan-dev-train"

_COMMAND = [
    "jobs/batch/train_commodity.py",
    "--commodity", "Ref::commodity",
    "--tier", "Ref::tier",
    "--feature-set", "Ref::feature_set",
    "--target", "Ref::target",
    "--model", "Ref::model",
    "--bucket", "Ref::bucket",
    "--aws-region", "Ref::aws_region",
    "--experiment", "Ref::experiment",
    "--detrend", "Ref::detrend",     # "true"/"false"
    "--optuna", "Ref::optuna",       # "true"/"false"
    "--n-trials", "Ref::n_trials",
    "--dataset-version", "Ref::dataset_version",
]

# Defaults for every Ref:: token — a submission may override any of these.
_PARAMETERS = {
    "bucket": "leviathan-dev-shahem-001",
    "aws_region": _REGION,
    "experiment": "leviathan-tier1-production",
    "tier": "climate",
    "feature_set": "none",
    "target": "production_quantity",
    "model": "xgboost",
    "detrend": "false",
    "optuna": "false",
    "n_trials": "30",
    "dataset_version": "none",
}

_CONTAINER = {
    "image": f"{_ACCOUNT}.dkr.ecr.{_REGION}.amazonaws.com/{_REPO}:latest",
    "command": _COMMAND,
    "jobRoleArn": f"arn:aws:iam::{_ACCOUNT}:role/leviathan-dev-batch-job-role",
    "executionRoleArn": f"arn:aws:iam::{_ACCOUNT}:role/leviathan-dev-batch-execution-role",
    "resourceRequirements": [
        {"type": "VCPU", "value": "2"},
        {"type": "MEMORY", "value": "8192"},
    ],
    "networkConfiguration": {"assignPublicIp": "ENABLED"},
    "fargatePlatformConfiguration": {"platformVersion": "LATEST"},
    "environment": [
        {"name": "AWS_REGION", "value": _REGION},
        {"name": "LEVIATHAN_BUCKET", "value": "leviathan-dev-shahem-001"},
        {"name": "LEVIATHAN_ENV", "value": "dev"},
        {"name": "MLFLOW_TRACKING_URI", "value": "http://172.31.29.109:5000"},
    ],
}


def main() -> None:
    ap = argparse.ArgumentParser(description="Register the leviathan-dev-train job definition.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    payload = dict(
        jobDefinitionName=_NAME,
        type="container",
        platformCapabilities=["FARGATE"],
        parameters=_PARAMETERS,
        containerProperties=_CONTAINER,
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
