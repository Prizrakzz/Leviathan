from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

TERMINAL_GLUE_STATES = frozenset({"SUCCEEDED", "FAILED", "ERROR", "TIMEOUT", "STOPPED"})
TERMINAL_BATCH_STATES = frozenset({"SUCCEEDED", "FAILED"})


def poll_glue_runs(
    client: Any,
    run_ids: dict[str, str],
    poll_interval: int = 30,
) -> dict[str, str]:
    """Block until all Glue job runs reach a terminal state.

    Args:
        client: boto3 Glue client.
        run_ids: Mapping of ``{run_id: job_name}`` to monitor.
        poll_interval: Seconds between polling iterations.

    Returns:
        Mapping of run_id → final state string.
    """
    remaining: dict[str, str] = dict(run_ids)
    results: dict[str, str] = {}
    while remaining:
        done: list[str] = []
        for run_id, job_name in remaining.items():
            state = client.get_job_run(JobName=job_name, RunId=run_id)["JobRun"]["JobRunState"]
            if state in TERMINAL_GLUE_STATES:
                results[run_id] = state
                done.append(run_id)
                logger.info("Glue %s run_id=%s → %s", job_name, run_id, state)
        for run_id in done:
            del remaining[run_id]
        if remaining:
            logger.info("Glue: %d runs still in progress...", len(remaining))
            time.sleep(poll_interval)
    return results


def poll_batch_jobs(
    client: Any,
    job_ids: list[str],
    poll_interval: int = 30,
) -> dict[str, str]:
    """Block until all Batch jobs reach a terminal state.

    Args:
        client: boto3 Batch client.
        job_ids: List of Batch job IDs to monitor.
        poll_interval: Seconds between polling iterations.

    Returns:
        Mapping of job_id → final state string.
    """
    remaining: set[str] = set(job_ids)
    results: dict[str, str] = {}
    while remaining:
        remaining_list = list(remaining)
        for i in range(0, len(remaining_list), 100):  # AWS limit: 100 per describe_jobs call
            chunk = remaining_list[i : i + 100]
            for job in client.describe_jobs(jobs=chunk)["jobs"]:
                if job["status"] in TERMINAL_BATCH_STATES:
                    results[job["jobId"]] = job["status"]
                    remaining.discard(job["jobId"])
        if remaining:
            time.sleep(poll_interval)
    return results
