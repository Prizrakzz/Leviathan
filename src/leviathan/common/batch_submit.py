"""Shared AWS Batch job-submission helpers for leviathan submit scripts.

Two utilities extracted from submit_batch_*.py scripts to eliminate the
repeated boto3 submit loop and run-record file writer across every script::

    submit_batch_jobs() -- submits tasks via parameters= (not containerOverrides)
    write_run_record()  -- writes the JSON run record to data/batch_runs/
"""
from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Callable, TypedDict

import boto3

logger = logging.getLogger(__name__)


class BatchJobRecord(TypedDict):
    """Record returned by :func:`submit_batch_jobs` for each submitted task."""

    job_name: str
    parameters: dict[str, str]
    job_id: str | None


def submit_batch_jobs(
    tasks: list[dict[str, str]],
    job_queue: str,
    job_definition: str,
    build_job_name: Callable[[dict[str, str]], str],
    aws_region: str,
    dry_run: bool = False,
) -> list[BatchJobRecord]:
    """Submit *tasks* to AWS Batch via the ``parameters`` field.

    Each task dict is passed as-is to ``submit_job(parameters=...)``.
    Not suitable for scripts that use ``containerOverrides``
    (WAP, SAGIS CEC, WASDE, GAIN backfill).

    Args:
        tasks: List of parameter dicts; each maps parameter name → string value.
        job_queue: Batch job queue name or ARN.
        job_definition: Batch job definition name or ARN.
        build_job_name: Callable that receives a task dict and returns the job name.
        aws_region: AWS region name (e.g. ``"us-east-1"``).
        dry_run: If True, log what would be submitted without calling the Batch API.

    Returns:
        List of task records with ``"job_name"`` and ``"job_id"`` added.
        ``"job_id"`` is ``None`` in dry-run mode.
    """
    client = boto3.client("batch", region_name=aws_region)
    submitted: list[BatchJobRecord] = []

    for task in tasks:
        job_name = build_job_name(task)

        if dry_run:
            logger.info("[DRY RUN] Would submit: %s  params=%s", job_name, task)
            submitted.append({"job_name": job_name, "parameters": task, "job_id": None})
            continue

        response = client.submit_job(
            jobName=job_name,
            jobQueue=job_queue,
            jobDefinition=job_definition,
            parameters=task,
        )
        job_id = response["jobId"]
        logger.info("Submitted  job_name=%s  job_id=%s", job_name, job_id)
        submitted.append({"job_name": job_name, "parameters": task, "job_id": job_id})

    return submitted


def write_run_record(path: Path, payload: Mapping[str, object]) -> None:
    """Write a JSON run record to *path*, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    logger.info("Run record saved to %s", path)
