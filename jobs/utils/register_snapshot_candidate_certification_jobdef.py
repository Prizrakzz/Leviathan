"""Register the ``leviathan-dev-certify-snapshot-model-candidate`` Batch job definition."""
from __future__ import annotations

import argparse
import json

import boto3

_ACCOUNT = "668891723125"
_REGION = "us-east-1"
_REPO = "leviathan-dev-leviathan-trainer"
_NAME = "leviathan-dev-certify-snapshot-model-candidate"

_COMMAND = [
    "jobs/batch/certify_snapshot_model_candidate.py",
    "--commodity", "Ref::commodity",
    "--feature-set", "Ref::feature_set",
    "--feature-stack", "Ref::feature_stack",
    "--model-dataset-version", "Ref::model_dataset_version",
    "--dataset-key", "Ref::dataset_key",
    "--target-key", "Ref::target_key",
    "--model", "Ref::model",
    "--model-params-json", "Ref::model_params_json",
    "--min-train-years", "Ref::min_train_years",
    "--min-trainable-annual-groups", "Ref::min_trainable_annual_groups",
    "--min-event-groups", "Ref::min_event_groups",
    "--min-non-null-rate", "Ref::min_non_null_rate",
    "--collapse-policy", "Ref::collapse_policy",
    "--source-dataset-version", "Ref::source_dataset_version",
    "--bucket", "Ref::bucket",
    "--aws-region", "Ref::aws_region",
]

_PARAMETERS = {
    "bucket": "leviathan-dev-shahem-001",
    "aws_region": _REGION,
    "commodity": "corn_cbot",
    "feature_set": "wasde_monthly_revision",
    "feature_stack": "auto",
    "model_dataset_version": "none",
    "dataset_key": "psd_snd_anomaly_snapshot",
    "target_key": "psd_production_anomaly_pct",
    "model": "lightgbm",
    "model_params_json": "{}",
    "min_train_years": "10",
    "min_trainable_annual_groups": "20",
    "min_event_groups": "5",
    "min_non_null_rate": "0.2",
    "collapse_policy": "latest",
    "source_dataset_version": "none",
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
        {"name": "PYTHONIOENCODING", "value": "utf-8"},
    ],
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register the grouped WASDE snapshot candidate job definition."
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

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
    print(
        f"registered {resp['jobDefinitionName']} revision {resp['revision']} "
        f"({resp['jobDefinitionArn']})"
    )


if __name__ == "__main__":
    main()
