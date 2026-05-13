from __future__ import annotations

import time
from typing import Any


TERMINAL_GLUE_STATES = frozenset({"SUCCEEDED", "FAILED", "ERROR", "TIMEOUT"})
TERMINAL_BATCH_STATES = frozenset({"SUCCEEDED", "FAILED"})


def poll_glue_runs(
    client: Any,
    runs: list[tuple[str, str]],
    poll_interval: int = 30,
) -> dict[str, str]:
    """Block until all Glue job runs reach a terminal state.

    Args:
        client: boto3 Glue client.
        runs: List of (job_name, run_id) pairs to monitor.
        poll_interval: Seconds between polling iterations.

    Returns:
        Mapping of run_id → final state string.
    """
    remaining: set[tuple[str, str]] = set(runs)
    results: dict[str, str] = {}
    while remaining:
        done: set[tuple[str, str]] = set()
        for job_name, run_id in remaining:
            state = client.get_job_run(JobName=job_name, RunId=run_id)["JobRun"]["JobRunState"]
            if state in TERMINAL_GLUE_STATES:
                results[run_id] = state
                done.add((job_name, run_id))
        remaining -= done
        if remaining:
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
