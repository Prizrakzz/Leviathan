"""Submit model-candidate certification jobs to AWS Batch."""
from __future__ import annotations

import argparse
import itertools
import logging
import os
from pathlib import Path

from leviathan.common.batch_submit import submit_batch_jobs, write_run_record
from leviathan.common.config import get_required_env, load_env
from leviathan.common.constants import ALL_COMMODITIES
from leviathan.common.logging import get_logger
from leviathan.features.spine import load_countries
from leviathan.model_datasets.version_status import load_model_dataset_version_registry
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_batch_candidate_certification")


def _split(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


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

    parser = argparse.ArgumentParser(description="Submit candidate certification jobs.")
    parser.add_argument("--commodities", default="corn_cbot")
    parser.add_argument("--feature-sets", default="preseason_physical")
    parser.add_argument("--model-dataset-version", default="latest", dest="model_dataset_version")
    parser.add_argument("--target-source", default="psd", choices=["psd", "faostat"],
                        dest="target_source")
    parser.add_argument("--dataset-keys", default="psd_snd_anomaly", dest="dataset_keys")
    parser.add_argument("--target-keys", default="psd_production_anomaly_pct", dest="target_keys")
    parser.add_argument("--models", default="lightgbm")
    parser.add_argument("--model-params-json", default="{}", dest="model_params_json")
    parser.add_argument("--cv-policies", default="expanding_post_2000", dest="cv_policies")
    parser.add_argument("--min-train-years", type=int, default=10, dest="min_train_years")
    parser.add_argument("--permutation-trials", type=int, default=20, dest="permutation_trials")
    parser.add_argument("--stress-years", default="2010,2011,2012,2020,2021,2022",
                        dest="stress_years")
    parser.add_argument("--source-dataset-version", default="none", dest="source_dataset_version")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    bucket = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    if args.commodities.strip().lower() == "all":
        commodities = [c for c in ALL_COMMODITIES if load_countries(c)]
    else:
        commodities = _split(args.commodities)
        unknown = [c for c in commodities if c not in ALL_COMMODITIES]
        if unknown:
            raise SystemExit(f"ERROR: Unknown commodities: {unknown}")

    dataset_keys = _split(args.dataset_keys)
    if args.model_dataset_version.strip().lower() in {"latest", "active", "default"}:
        if len(dataset_keys) != 1:
            raise SystemExit(
                "--model-dataset-version latest requires exactly one --dataset-keys value"
            )
        selected = load_model_dataset_version_registry().select_default(
            target_source=args.target_source,
            dataset_key=dataset_keys[0],
        )
        args.model_dataset_version = selected.dataset_version
        logger.info(
            "Resolved model_dataset_version=%s status=%s target_source=%s dataset_key=%s",
            selected.dataset_version,
            selected.status,
            selected.target_source,
            dataset_keys[0],
        )

    feature_sets = _split(args.feature_sets)
    target_keys = _split(args.target_keys)
    models = _split(args.models)
    cv_policies = _split(args.cv_policies)

    tasks = [
        {
            "commodity": commodity,
            "feature_set": feature_set,
            "model_dataset_version": args.model_dataset_version,
            "dataset_key": dataset_key,
            "target_key": target_key,
            "model": model,
            "model_params_json": args.model_params_json or "{}",
            "cv_policy": cv_policy,
            "min_train_years": str(args.min_train_years),
            "permutation_trials": str(args.permutation_trials),
            "stress_years": args.stress_years or "none",
            "source_dataset_version": args.source_dataset_version or "none",
            "bucket": bucket,
            "aws_region": aws_region,
        }
        for commodity, feature_set, dataset_key, target_key, model, cv_policy
        in itertools.product(
            commodities, feature_sets, dataset_keys, target_keys, models, cv_policies
        )
    ]

    logger.info(
        "Submitting %d candidate certification tasks queue=%s definition=%s dry_run=%s",
        len(tasks), batch_queue, job_def, args.dry_run,
    )

    def _job_name(task: dict) -> str:
        return (
            f"certify-{task['commodity']}-{task['feature_set']}-{task['dataset_key']}-"
            f"{task['target_key']}-{task['model']}-{task['cv_policy']}"
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
            Path("data/batch_runs") / f"candidate_certification_{run_id}.json",
            {"run_id": run_id, "job": "candidate_certification", "task_count": len(submitted),
             "tasks": submitted},
        )
        logger.info(
            "Done: %d/%d tasks submitted.",
            sum(1 for task in submitted if task["job_id"]),
            len(tasks),
        )


if __name__ == "__main__":
    main()
