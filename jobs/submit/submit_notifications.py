"""Day-0 manual submit for the P3 morning-brief notifications job (Phase 8 SECTION III, Track C).

The dedicated jobdef's defaults (command, 1 vCPU/2 GiB, bedrock pin, retry) are already correct, so a
plain submit needs NO overrides — the same property that makes the EventBridge schedule safe. `--dry-run`
appends the task's --dry-run flag (resolve + sweep + print, write nothing) for the user-reviewed first run.

    python jobs/submit/submit_notifications.py --dry-run   # day-0 review run (writes NOTHING)
    python jobs/submit/submit_notifications.py             # real run
"""
from __future__ import annotations

import argparse

import boto3

_REGION = "us-east-1"
_QUEUE = "leviathan-dev-queue"
_JOBDEF = "leviathan-dev-notifications"


def main() -> None:
    ap = argparse.ArgumentParser(description="Submit the daily notifications sweep to AWS Batch.")
    ap.add_argument("--dry-run", action="store_true", help="run the task in --dry-run mode (no writes)")
    args = ap.parse_args()

    kwargs = dict(jobName="build-notifications" + ("-dry" if args.dry_run else ""),
                  jobQueue=_QUEUE, jobDefinition=_JOBDEF)
    if args.dry_run:
        kwargs["containerOverrides"] = {
            "command": ["jobs/batch/build_notifications_task.py", "--dry-run"]}
    resp = boto3.client("batch", region_name=_REGION).submit_job(**kwargs)
    print(f"submitted {resp['jobName']} -> {resp['jobId']}")


if __name__ == "__main__":
    main()
