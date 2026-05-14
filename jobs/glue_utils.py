"""Shared AWS Glue polling utilities for Leviathan pipeline scripts."""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

_DEFAULT_TERMINAL_STATES: frozenset[str] = frozenset(
    {"SUCCEEDED", "FAILED", "ERROR", "TIMEOUT", "STOPPED"}
)


def poll_glue_runs(
    client,
    run_ids: dict[str, str],
    poll_interval_seconds: int = 30,
    terminal_states: frozenset[str] | set[str] | None = None,
) -> dict[str, str]:
    """Poll Glue job runs until all reach a terminal state.

    Args:
        client: boto3 Glue client.
        run_ids: Mapping of ``{run_id: job_name}``.
        poll_interval_seconds: Seconds to sleep between polling rounds.
        terminal_states: Set of state strings considered terminal.
            Defaults to ``{"SUCCEEDED", "FAILED", "ERROR", "TIMEOUT", "STOPPED"}``.

    Returns:
        ``{run_id: final_status}`` for every run passed in.
    """
    if terminal_states is None:
        terminal_states = _DEFAULT_TERMINAL_STATES

    remaining: dict[str, str] = dict(run_ids)  # {run_id: job_name}
    results: dict[str, str] = {}

    while remaining:
        done: list[str] = []
        for run_id, job_name in remaining.items():
            state = client.get_job_run(JobName=job_name, RunId=run_id)["JobRun"]["JobRunState"]
            if state in terminal_states:
                results[run_id] = state
                done.append(run_id)
                logger.info("Glue %s run_id=%s → %s", job_name, run_id, state)

        for run_id in done:
            del remaining[run_id]

        if remaining:
            logger.info("Glue: %d runs still in progress...", len(remaining))
            time.sleep(poll_interval_seconds)

    return results
