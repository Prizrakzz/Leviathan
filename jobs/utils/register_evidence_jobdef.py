"""Register (a new revision of) the ``leviathan-dev-evidence-build`` Batch job definition (GraphRAG v2 WS-MS2).

The cloud evidence builder: Bedrock-Haiku propositional chunking + self-hosted bge-m3 embeddings -> S3
(EVIDENCE_S3). It reuses the SAME Fargate compute env / queue / IAM roles as the other Leviathan Batch jobs —
``leviathan-dev-batch-job-role`` already grants Bedrock-invoke + S3 (text_to_graphrag uses it for exactly that),
so no new IAM role is needed. Only the image differs: ``leviathan-dev-leviathan-embedder`` (torch + bge-m3 baked).

    python jobs/utils/register_evidence_jobdef.py            # register new revision
    python jobs/utils/register_evidence_jobdef.py --dry-run  # print, don't register
"""
from __future__ import annotations

import argparse
import json

import boto3

_ACCOUNT = "668891723125"
_REGION = "us-east-1"
_REPO = "leviathan-dev-leviathan-embedder"        # separate ECR repo (torch + bge-m3 ~2.5 GB; not the lean worker)
_NAME = "leviathan-dev-evidence-build"
_BUCKET = "leviathan-dev-shahem-001"
# Dedicated top-level prefix — kept OUT of the MLOps `graphrag/` Parquet layer (text_to_graphrag owns that).
_EVIDENCE_S3 = f"s3://{_BUCKET}/graphrag_evidence"

_COMMAND = [
    "jobs/batch/build_evidence_task.py",
    "--nodes", "Ref::nodes",          # "all" | "new" | comma-separated node/contract ids
    "--n-docs", "Ref::n_docs",
    "--workers", "Ref::workers",
]

# Defaults for every Ref:: token — a submission may override any of these.
_PARAMETERS = {
    "nodes": "all",
    "n_docs": "90",
    "workers": "16",
}

_CONTAINER = {
    "image": f"{_ACCOUNT}.dkr.ecr.{_REGION}.amazonaws.com/{_REPO}:latest",
    "command": _COMMAND,
    "jobRoleArn": f"arn:aws:iam::{_ACCOUNT}:role/leviathan-dev-batch-job-role",          # has Bedrock + S3
    "executionRoleArn": f"arn:aws:iam::{_ACCOUNT}:role/leviathan-dev-batch-execution-role",
    "resourceRequirements": [
        {"type": "VCPU", "value": "8"},        # 16 network-bound Haiku threads + CPU bge-m3 embedding
        {"type": "MEMORY", "value": "16384"},  # bge-m3 weights (~2.5 GB) + working set
    ],
    "networkConfiguration": {"assignPublicIp": "ENABLED"},
    "fargatePlatformConfiguration": {"platformVersion": "LATEST"},
    "environment": [
        {"name": "AWS_REGION", "value": _REGION},
        {"name": "LEVIATHAN_BUCKET", "value": _BUCKET},
        {"name": "LEVIATHAN_ENV", "value": "dev"},
        {"name": "EVIDENCE_S3", "value": _EVIDENCE_S3},        # write evidence/<node>.jsonl here (not local disk)
        {"name": "EVIDENCE_EMBED_BACKEND", "value": "bge_local"},
        {"name": "EVIDENCE_WORKERS", "value": "16"},
        {"name": "PYTHONIOENCODING", "value": "utf-8"},
    ],
}


def main() -> None:
    ap = argparse.ArgumentParser(description="Register the leviathan-dev-evidence-build job definition.")
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
