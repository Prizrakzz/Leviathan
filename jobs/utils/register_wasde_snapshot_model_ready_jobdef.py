"""Register the ``leviathan-dev-wasde-snapshot-model-ready`` Batch job definition."""
from __future__ import annotations

import argparse
import json

import boto3

_ACCOUNT = "668891723125"
_REGION = "us-east-1"
_REPO = "leviathan-dev-leviathan-trainer"
_NAME = "leviathan-dev-wasde-snapshot-model-ready"

_COMMAND = [
    "jobs/batch/wasde_snapshot_model_ready_task.py",
    "--bucket", "Ref::bucket",
    "--aws-region", "Ref::aws_region",
    "--source-dataset-version", "Ref::source_dataset_version",
    "--model-dataset-version", "Ref::model_dataset_version",
    "--dataset-key", "Ref::dataset_key",
    "--commodity", "Ref::commodity",
    "--target-keys", "Ref::target_keys",
    "--feature-set-ids", "Ref::feature_set_ids",
    "--workers", "Ref::workers",
    "--min-history-years", "Ref::min_history_years",
    "--min-non-null-rate", "Ref::min_non_null_rate",
    "--phase2-density-prefix", "Ref::phase2_density_prefix",
    "--skip-existing-versioned", "Ref::skip_existing_versioned",
]

_PARAMETERS = {
    "bucket": "leviathan-dev-shahem-001",
    "aws_region": _REGION,
    "source_dataset_version": "20260626T010217Z_6725de02_phase7_full",
    "model_dataset_version": "manual_phase3_wasde_snapshot_model_ready",
    "dataset_key": "corn_wasde_snapshot_solo",
    "commodity": "corn_cbot",
    "target_keys": "psd_stock_to_use_anomaly_pct,psd_ending_stocks_anomaly_pct",
    "feature_set_ids": "wasde_monthly_revision",
    "workers": "16",
    "min_history_years": "5",
    "min_non_null_rate": "0.5",
    "phase2_density_prefix": (
        "model_artifacts/wasde_snapshot_feature_density/"
        "dataset_version=20260629T115343Z_phase2_wasde_feature_density"
    ),
    "skip_existing_versioned": "true",
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
        {"name": "PYTHONIOENCODING", "value": "utf-8"},
    ],
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register the WASDE snapshot model-ready Batch job definition."
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    payload = {
        "jobDefinitionName": _NAME,
        "type": "container",
        "platformCapabilities": ["FARGATE"],
        "parameters": _PARAMETERS,
        "containerProperties": _CONTAINER,
    }
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
