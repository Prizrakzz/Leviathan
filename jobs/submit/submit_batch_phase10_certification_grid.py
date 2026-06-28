"""Submit the Phase 10 candidate-certification hypothesis grid to AWS Batch."""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import boto3  # noqa: E402

from leviathan.common.batch_submit import submit_batch_jobs, write_run_record  # noqa: E402
from leviathan.common.config import get_required_env, load_env                 # noqa: E402
from leviathan.common.logging import get_logger                                # noqa: E402
from leviathan.model_datasets.version_status import (                          # noqa: E402
    load_model_dataset_version_registry,
)
from leviathan.storage.metadata import utc_now_iso                             # noqa: E402
from leviathan.training.feature_quality import (                               # noqa: E402
    FeatureQualityPolicy,
    build_feature_quality_report,
    enforce_feature_quality,
)
from leviathan.training.model_ready import (                                   # noqa: E402
    load_model_ready_training_dataset,
)
from leviathan.training.phase10_grid import (                                  # noqa: E402
    expand_phase10_grid,
    load_phase10_grid_config,
    phase10_grid_summary,
)

logger = get_logger("submit_batch_phase10_certification_grid")


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


def _validate_feature_quality(
    tasks: list[dict[str, str]],
    *,
    bucket: str,
    aws_region: str,
) -> dict[str, int]:
    """Fail fast when selected Phase 10 feature sets are not experiment-ready."""
    s3 = boto3.client("s3", region_name=aws_region)
    seen: set[tuple[str, str, str, str, str, str | None]] = set()
    status_counts: dict[str, int] = {}
    for task in tasks:
        identity = (
            task["model_dataset_version"],
            task["dataset_key"],
            task["commodity"],
            task["target_key"],
            task["feature_set"],
            task.get("source_dataset_version"),
        )
        if identity in seen:
            continue
        seen.add(identity)
        dataset = load_model_ready_training_dataset(
            s3,
            bucket=bucket,
            model_dataset_version=task["model_dataset_version"],
            dataset_key=task["dataset_key"],
            commodity=task["commodity"],
            target_key=task["target_key"],
            feature_set_id=task["feature_set"],
            source_dataset_version=(
                None
                if task.get("source_dataset_version") in {None, "", "none"}
                else task.get("source_dataset_version")
            ),
        )
        report = build_feature_quality_report(
            dataset.matrix,
            dataset.feature_cols,
            membership=dataset.feature_membership,
            dataset_key=task["dataset_key"],
            feature_set_id=task["feature_set"],
            selected_feature_sets=(task["feature_set"],),
            policy=FeatureQualityPolicy(mode="strict"),
        )
        enforce_feature_quality(report)
        status = str(report.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
    logger.info(
        "Validated feature quality for %d unique Phase 10 slices: %s",
        len(seen),
        status_counts,
    )
    return status_counts


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    load_env()

    env = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    batch_queue = f"{project}-{env}-queue"
    job_def = f"{project}-{env}-certify-model-candidate"

    parser = argparse.ArgumentParser(description="Submit the Phase 10 certification grid.")
    parser.add_argument("--grid-config", default=None, dest="grid_config")
    parser.add_argument("--include-hypotheses", default="", dest="include_hypotheses")
    parser.add_argument("--exclude-hypotheses", default="", dest="exclude_hypotheses")
    parser.add_argument("--model-dataset-version", default=None, dest="model_dataset_version")
    parser.add_argument("--source-dataset-version", default=None, dest="source_dataset_version")
    parser.add_argument("--target-source", default="psd", choices=["psd", "faostat"],
                        dest="target_source")
    parser.add_argument("--permutation-trials", type=int, default=None, dest="permutation_trials")
    parser.add_argument("--max-jobs", type=int, default=0, dest="max_jobs")
    parser.add_argument(
        "--skip-feature-quality-validation",
        action="store_true",
        dest="skip_feature_quality_validation",
        help="Skip pre-submit feature quality validation for emergency/debug runs.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    bucket = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    config = load_phase10_grid_config(args.grid_config)
    tasks = expand_phase10_grid(
        config,
        include_hypotheses=_split(args.include_hypotheses),
        exclude_hypotheses=_split(args.exclude_hypotheses),
        model_dataset_version=args.model_dataset_version,
        source_dataset_version=args.source_dataset_version,
        permutation_trials=args.permutation_trials,
        bucket=bucket,
        aws_region=aws_region,
    )
    tasks = _resolve_latest_versions(tasks, args.target_source)
    if args.max_jobs and args.max_jobs > 0:
        tasks = tasks[:args.max_jobs]

    feature_quality_status_counts: dict[str, int] = {}
    if not args.skip_feature_quality_validation:
        feature_quality_status_counts = _validate_feature_quality(
            tasks,
            bucket=bucket,
            aws_region=aws_region,
        )

    summary = phase10_grid_summary(tasks)
    summary["feature_quality_status_counts"] = feature_quality_status_counts
    logger.info("Phase 10 grid summary: %s", summary)

    def _job_name(task: dict[str, str]) -> str:
        return (
            f"phase10-{task['hypothesis_id']}-{task['commodity']}-"
            f"{task['feature_set']}-{task['dataset_key']}-{task['target_key']}-"
            f"{task['model']}-{task['model_param_profile']}-{task['cv_policy']}"
        ).replace("_", "-")

    submitted = submit_batch_jobs(
        tasks=tasks,
        job_queue=batch_queue,
        job_definition=job_def,
        build_job_name=_job_name,
        aws_region=aws_region,
        dry_run=args.dry_run,
    )
    if not args.dry_run:
        run_id = utc_now_iso().replace(":", "-")
        write_run_record(
            Path("data/batch_runs") / f"phase10_candidate_grid_{run_id}.json",
            {
                "run_id": run_id,
                "job": "phase10_candidate_grid",
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
