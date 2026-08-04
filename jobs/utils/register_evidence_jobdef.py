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
    "--skip-existing", "Ref::skip_existing",   # "true" to resume a partial run without re-billing
    "--drivers", "Ref::drivers",               # "true" captures cross-cutting driver/cascade slices (WS-MS6)
    "--chunk-provider", "Ref::chunk_provider", # "anthropic" bills Haiku to the Anthropic account (prepaid credit)
]

# Defaults for every Ref:: token — a submission may override any of these.
_PARAMETERS = {
    "nodes": "all",
    "n_docs": "90",
    "workers": "16",
    "skip_existing": "false",
    "drivers": "true",
    "chunk_provider": "anthropic",             # use the prepaid Anthropic credit by default
}

# Secrets are injected from Secrets Manager (the execution role has GetSecretValue on them). ARNs are
# resolved by NAME at registration so the random suffixes stay out of this (public) repo.
_SECRET_NAME = "leviathan-dev-anthropic-api-key"
_PG_DSN_SECRET_NAME = "leviathan/dev/evidence-pg-dsn"          # load_pg_evidence.py / pg_evidence_swap.py exit 1 without it

_CONTAINER = {
    # Image is pinned to the digest :latest resolves to AT REGISTRATION (matching the live revision's digest
    # pin) — a mutable tag on the jobdef would re-resolve at every pull and defeat provenance.
    "image": f"{_ACCOUNT}.dkr.ecr.{_REGION}.amazonaws.com/{_REPO}:latest",
    "command": _COMMAND,
    "jobRoleArn": f"arn:aws:iam::{_ACCOUNT}:role/leviathan-dev-batch-job-role",          # has Bedrock + S3
    "executionRoleArn": f"arn:aws:iam::{_ACCOUNT}:role/leviathan-dev-batch-execution-role",
    "resourceRequirements": [
        # DO NOT DOWNSIZE. 8 vCPU / 16 GB was OOM-killed (exit 137) mid-write on the 1.03 GB soybeans slice,
        # tearing the evidence store (2026-08-02; see commit 480253ff). rebuild-slices holds the full prop
        # routing in memory; 16/120 GB is the measured-safe envelope.
        {"type": "VCPU", "value": "16"},
        {"type": "MEMORY", "value": "122880"},
    ],
    "networkConfiguration": {"assignPublicIp": "ENABLED"},
    "fargatePlatformConfiguration": {"platformVersion": "LATEST"},
    "environment": [
        {"name": "AWS_REGION", "value": _REGION},
        {"name": "LEVIATHAN_BUCKET", "value": _BUCKET},
        {"name": "LEVIATHAN_ENV", "value": "dev"},
        {"name": "EVIDENCE_S3", "value": _EVIDENCE_S3},        # write evidence/<node>.jsonl here (not local disk)
        {"name": "EVIDENCE_EMBED_BACKEND", "value": "bge_local"},
        {"name": "EVIDENCE_BACKEND", "value": "pg"},           # prop reads/loads target the pgvector store
        {"name": "GRAPHRAG_SESSIONS_TABLE", "value": "leviathan-dev-graphrag-sessions"},
        {"name": "EVIDENCE_WORKERS", "value": "16"},
        {"name": "PYTHONIOENCODING", "value": "utf-8"},
    ],
}


def main() -> None:
    ap = argparse.ArgumentParser(description="Register the leviathan-dev-evidence-build job definition.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    container = dict(_CONTAINER)

    # Pin the image to the digest :latest resolves to right now (live revisions are digest-pinned).
    ecr = boto3.client("ecr", region_name=_REGION)
    digest = ecr.describe_images(repositoryName=_REPO, imageIds=[{"imageTag": "latest"}])["imageDetails"][0][
        "imageDigest"
    ]
    container["image"] = f"{_ACCOUNT}.dkr.ecr.{_REGION}.amazonaws.com/{_REPO}@{digest}"

    # Inject both secrets from Secrets Manager, ARNs resolved by name.
    sm = boto3.client("secretsmanager", region_name=_REGION)
    container["secrets"] = [
        {"name": "ANTHROPIC_API_KEY", "valueFrom": sm.describe_secret(SecretId=_SECRET_NAME)["ARN"]},
        {"name": "EVIDENCE_PG_DSN", "valueFrom": sm.describe_secret(SecretId=_PG_DSN_SECRET_NAME)["ARN"]},
    ]

    payload = dict(
        jobDefinitionName=_NAME,
        type="container",
        platformCapabilities=["FARGATE"],
        parameters=_PARAMETERS,
        containerProperties=container,
    )

    if args.dry_run:
        masked = [{"name": s["name"], "valueFrom": "[resolved by name]"} for s in container["secrets"]]
        print(json.dumps({**payload, "containerProperties": {**container, "secrets": masked}}, indent=2))
        return

    batch = boto3.client("batch", region_name=_REGION)
    resp = batch.register_job_definition(**payload)
    print(f"registered {resp['jobDefinitionName']} revision {resp['revision']} "
          f"({resp['jobDefinitionArn']})")


if __name__ == "__main__":
    main()
