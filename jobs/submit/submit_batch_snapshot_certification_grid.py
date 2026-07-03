"""Submit the WASDE snapshot candidate smoke grid to AWS Batch."""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from leviathan.common.batch_submit import submit_batch_jobs, write_run_record  # noqa: E402
from leviathan.common.config import get_required_env, load_env                 # noqa: E402
from leviathan.common.logging import get_logger                                # noqa: E402
from leviathan.model_datasets.version_status import (                          # noqa: E402
    load_model_dataset_version_registry,
)
from leviathan.storage.metadata import utc_now_iso                             # noqa: E402
from leviathan.training.snapshot_candidate_grid import (                       # noqa: E402
    expand_snapshot_candidate_grid,
    load_snapshot_candidate_grid_config,
    snapshot_candidate_grid_summary,
)

logger = get_logger("submit_batch_snapshot_certification_grid")


def _split(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _resolve_latest_versions(tasks: list[dict[str, str]], target_source: str) -> list[dict[str, str]]:
    registry = load_model_dataset_version_registry()
    out: list[dict[str, str]] = []
    cache: dict[str, str] = {}
    for task in tasks:
        copied = dict(task)
        requested = copied["model_dataset_version"].strip().lower()
        if requested in {"latest", "active", "default"}:
            dataset_key = copied["dataset_key"]
            if dataset_key not in cache:
                selected = registry.select_default(
                    target_source=target_source,
                    dataset_key=dataset_key,
                )
                cache[dataset_key] = selected.dataset_version
                logger.info(
                    "Resolved dataset_key=%s to model_dataset_version=%s status=%s",
                    dataset_key,
                    selected.dataset_version,
                    selected.status,
                )
            copied["model_dataset_version"] = cache[dataset_key]
        out.append(copied)
    return out


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    load_env()

    env = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    batch_queue = f"{project}-{env}-queue"
    job_def = f"{project}-{env}-certify-snapshot-model-candidate"

    parser = argparse.ArgumentParser(description="Submit grouped WASDE snapshot candidates.")
    parser.add_argument("--grid-config", default=None, dest="grid_config")
    parser.add_argument("--include-hypotheses", default="", dest="include_hypotheses")
    parser.add_argument("--exclude-hypotheses", default="", dest="exclude_hypotheses")
    parser.add_argument("--model-dataset-version", default=None, dest="model_dataset_version")
    parser.add_argument("--source-dataset-version", default=None, dest="source_dataset_version")
    parser.add_argument(
        "--target-source",
        default="psd",
        choices=["psd", "faostat"],
        dest="target_source",
    )
    parser.add_argument("--job-queue", default=None, dest="job_queue")
    parser.add_argument("--max-jobs", type=int, default=0, dest="max_jobs")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    bucket = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    config = load_snapshot_candidate_grid_config(args.grid_config)
    tasks = expand_snapshot_candidate_grid(
        config,
        include_hypotheses=_split(args.include_hypotheses),
        exclude_hypotheses=_split(args.exclude_hypotheses),
        model_dataset_version=args.model_dataset_version,
        source_dataset_version=args.source_dataset_version,
        bucket=bucket,
        aws_region=aws_region,
    )
    tasks = _resolve_latest_versions(tasks, args.target_source)
    if args.max_jobs and args.max_jobs > 0:
        tasks = tasks[:args.max_jobs]

    summary = snapshot_candidate_grid_summary(tasks)
    logger.info("Snapshot candidate grid summary: %s", summary)

    def _job_name(task: dict[str, str]) -> str:
        return (
            f"snapshot-{task['hypothesis_id']}-{task['commodity']}-"
            f"{task['feature_set']}-{task['dataset_key']}-{task['target_key']}-"
            f"{task['model']}-{task['model_param_profile']}"
        ).replace("_", "-")

    submitted = submit_batch_jobs(
        tasks=tasks,
        job_queue=args.job_queue or batch_queue,
        job_definition=job_def,
        build_job_name=_job_name,
        aws_region=aws_region,
        dry_run=args.dry_run,
    )
    if not args.dry_run:
        run_id = utc_now_iso().replace(":", "-")
        write_run_record(
            Path("data/batch_runs") / f"snapshot_candidate_grid_{run_id}.json",
            {
                "run_id": run_id,
                "job": "snapshot_candidate_grid",
                "dry_run": args.dry_run,
                "summary": summary,
                "task_count": len(submitted),
                "tasks": submitted,
            },
        )
    logger.info(
        "Done: %d/%d tasks submitted.",
        sum(1 for task in submitted if task["job_id"]),
        len(tasks),
    )


if __name__ == "__main__":
    main()
