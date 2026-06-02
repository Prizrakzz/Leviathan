"""Resubmit all 17 GAIN text jobs with --force-overwrite to rewrite at the
new document={slug} key format (adds one partition level per PDF).

This resolves the partition collision where multiple PDFs sharing the same
country/publication_date overwrote each other's document.json.
"""
from __future__ import annotations

import os
import boto3
from leviathan.common.config import load_env

load_env()

env     = os.environ.get("LEVIATHAN_ENV", "dev")
project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
queue   = f"{project}-{env}-queue"
job_def = f"{project}-{env}-gain-backfill"
bucket  = "leviathan-dev-shahem-001"
region  = "us-east-1"

# Per-source memory tuning based on prior OOM history
# Sources with 100-300 PDFs at 30 workers → 4GB fine
# Cotton (889), soybean_meal (261), soybean_oil (133), soybeans (127), wheat (214) → 8GB/15w
SOURCES = [
    ("usda_gain_cocoa",             "1", "4096",  30),
    ("usda_gain_coffee",            "1", "4096",  30),
    ("usda_gain_coffee_semiannual", "1", "4096",  30),
    ("usda_gain_corn",              "1", "4096",  30),
    ("usda_gain_cotton",            "2", "8192",  8),
    ("usda_gain_cotton_monthly",    "1", "4096",  30),
    ("usda_gain_grain_monthly",     "1", "4096",  30),
    ("usda_gain_orange_juice",      "1", "4096",  30),
    ("usda_gain_palm_oil",          "1", "4096",  30),
    ("usda_gain_rapeseed",          "1", "4096",  30),
    ("usda_gain_rice",              "1", "4096",  30),
    ("usda_gain_soybean_meal",      "2", "8192",  15),
    ("usda_gain_soybean_oil",       "2", "8192",  15),
    ("usda_gain_soybeans",          "2", "8192",  15),
    ("usda_gain_sugar",             "1", "4096",  30),
    ("usda_gain_sugar_semiannual",  "1", "4096",  30),
    ("usda_gain_wheat",             "2", "8192",  15),
]

client = boto3.client("batch", region_name=region)

for source, vcpu, memory, workers in SOURCES:
    resp = client.submit_job(
        jobName=f"gain-text-{source.replace('_', '-')}-rekey",
        jobQueue=queue,
        jobDefinition=job_def,
        containerOverrides={
            "command": [
                "jobs/batch/gain_text_task.py",
                "--source", source,
                "--bucket", bucket,
                "--aws-region", region,
                "--workers", str(workers),
                "--force-overwrite",
            ],
            "resourceRequirements": [
                {"type": "VCPU",   "value": vcpu},
                {"type": "MEMORY", "value": memory},
            ],
        },
    )
    print(f"{source:<32}  {vcpu}vCPU / {memory}MB / {workers}w  job_id={resp['jobId']}")
