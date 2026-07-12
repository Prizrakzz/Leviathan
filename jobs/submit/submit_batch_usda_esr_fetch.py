"""Submit the weekly USDA FAS ESR FETCH (api.data.gov -> raw S3) as one AWS Batch job.

Phase D D-W1: manual/gated companion to the DISABLED weekly EventBridge Scheduler
rule (leviathan-dev-esr-weekly-ingest). Fires the terraform-managed usda_esr_fetch
jobdef, which runs jobs/ingest/fetch_usda_esr.py --mode weekly --skip-existing-s3:
a snapshot of the current + new-crop marketing year for all 10 ESR commodity codes
as an immutable as_of={today} object.

Unlike submit_batch_b2s_esr.py this script does NOT register the jobdef -- the fetch
jobdef lives in terraform (infra/terraform/modules/batch). It looks the jobdef up by
name and refuses to submit if it is not ACTIVE yet, so a run before the user-gated
`tf -target apply` fails loudly instead of silently doing nothing.

SEQUENTIAL BY CONTRACT: this submits ONE Batch job; the fetch inside it is strictly
sequential (api.data.gov = 1,000 req/hr, government server not a CDN -- never thread,
fetch_usda_esr.py:16-17). Do NOT fan this out into per-commodity parallel submits.

USER-GATED PREREQS (the job will FAIL at container start until these are done):
  1. Create the leviathan/dev/fas-api-key secret (value from the local .env).
  2. tf -target apply the usda_esr_fetch jobdef + the execution-role GetSecretValue grant.

Usage:
    python jobs/submit/submit_batch_usda_esr_fetch.py
    python jobs/submit/submit_batch_usda_esr_fetch.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys

import boto3

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger

logger = get_logger("submit_batch_usda_esr_fetch")

_JOB_DEF_NAME = "leviathan-dev-usda-esr-fetch"
_JOB_QUEUE = "leviathan-dev-queue"
_REGION = "us-east-1"


def _active_job_definition_arn(batch: object) -> str:
    """Return the ARN of the ACTIVE terraform-managed fetch jobdef, or exit.

    The jobdef is created by terraform (not here). A missing jobdef means the
    user-gated `tf -target apply` has not run yet.
    """
    resp = batch.describe_job_definitions(jobDefinitionName=_JOB_DEF_NAME, status="ACTIVE")
    definitions = resp.get("jobDefinitions", [])
    if not definitions:
        raise SystemExit(
            f"job definition {_JOB_DEF_NAME} is not ACTIVE. Apply the terraform "
            "usda_esr_fetch jobdef first (tf -target aws_batch_job_definition.usda_esr_fetch)."
        )
    arn = definitions[-1]["jobDefinitionArn"]
    logger.info("Using terraform-managed job definition: %s", arn)
    return arn


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(description="Submit the weekly USDA ESR fetch Batch job")
    parser.add_argument("--aws-region", default=_REGION, dest="aws_region")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Resolved for logging parity with the jobdef env; the fetch reads these from the
    # container environment (LEVIATHAN_BUCKET/AWS_REGION) + FAS_API_KEY from the secret.
    bucket = get_required_env("LEVIATHAN_BUCKET")
    batch = boto3.client("batch", region_name=args.aws_region)

    job_def_arn = _active_job_definition_arn(batch)

    if args.dry_run:
        logger.info(
            "[dry-run] Would submit weekly ESR fetch: job_def=%s queue=%s bucket=%s "
            "command=[fetch_usda_esr.py --mode weekly --skip-existing-s3]",
            job_def_arn, _JOB_QUEUE, bucket,
        )
        logger.info(
            "[dry-run] Reminder: the job fails at start until the FAS secret exists + "
            "the execution-role GetSecretValue grant is applied (D-W1 gated prereqs)."
        )
        return

    resp = batch.submit_job(
        jobName="usda-esr-fetch",
        jobQueue=_JOB_QUEUE,
        jobDefinition=job_def_arn,
    )
    job_id = resp["jobId"]
    logger.info("Submitted: jobId=%s", job_id)
    logger.info("Monitor: aws batch describe-jobs --jobs %s --region %s", job_id, args.aws_region)


if __name__ == "__main__":
    main()
