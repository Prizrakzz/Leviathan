"""Resubmit the remaining failed GAIN text jobs after image rebuild.

- cotton:       exit=2 (--workers arg not in old image) → 8 workers, 6144 MB, 2 vCPU
- soybean_meal: exit=137 (OOM at 4 GB, 30 workers)     → 15 workers, 8192 MB, 2 vCPU
- soybean_oil:  exit=137 (OOM at 4 GB, 30 workers)     → 15 workers, 8192 MB, 2 vCPU
"""
from __future__ import annotations

import json
import os

import boto3

from leviathan.common.config import load_env

load_env()

env     = os.environ.get("LEVIATHAN_ENV", "dev")
project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
queue      = f"{project}-{env}-queue"
job_def    = f"{project}-{env}-gain-backfill"
bucket     = "leviathan-dev-shahem-001"
aws_region = "us-east-1"

RETRIES = [
    {
        "source": "usda_gain_cotton",
        "job_name": "gain-text-usda-gain-cotton-v2",
        "workers": 8,
        "vcpu": "2",
        "memory": "6144",
    },
    {
        "source": "usda_gain_soybean_meal",
        "job_name": "gain-text-usda-gain-soybean-meal-v2",
        "workers": 15,
        "vcpu": "2",
        "memory": "8192",
    },
    {
        "source": "usda_gain_soybean_oil",
        "job_name": "gain-text-usda-gain-soybean-oil-v2",
        "workers": 15,
        "vcpu": "2",
        "memory": "8192",
    },
]

client = boto3.client("batch", region_name=aws_region)

for r in RETRIES:
    command = [
        "jobs/batch/gain_text_task.py",
        "--source", r["source"],
        "--bucket", bucket,
        "--aws-region", aws_region,
        "--workers", str(r["workers"]),
    ]
    resp = client.submit_job(
        jobName=r["job_name"],
        jobQueue=queue,
        jobDefinition=job_def,
        containerOverrides={
            "command": command,
            "resourceRequirements": [
                {"type": "VCPU",   "value": r["vcpu"]},
                {"type": "MEMORY", "value": r["memory"]},
            ],
        },
    )
    print(f"{r['source']:<30}  job_id={resp['jobId']}  ({r['vcpu']} vCPU / {r['memory']} MB / {r['workers']} workers)")
