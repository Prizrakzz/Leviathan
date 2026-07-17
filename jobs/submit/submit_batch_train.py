"""Submit training experiments as AWS Batch jobs — one per
(commodity × tier × target × model) combination.

Feature selection is by TIER name (resolved from configs/features/
feature_tiers.yaml inside the job), never a hand-listed column set.  Sweep an
experiment grid by listing multiple tiers/targets/models; the Batch queue runs
them in parallel and each logs to MLflow.

Usage:
    python jobs/submit/submit_batch_train.py \
        --commodities corn_cbot,soybeans_cbot --tiers climate,full \
        --targets production_quantity --models xgboost
    python jobs/submit/submit_batch_train.py --commodities all --dry-run
"""
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
from leviathan.model_datasets.version_status import (
    get_model_dataset_version_status,
    load_model_dataset_version_registry,
)
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_batch_train")


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()

    env = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    batch_queue = f"{project}-{env}-queue"
    job_def = f"{project}-{env}-train"

    parser = argparse.ArgumentParser(description="Submit training experiments to Batch.")
    parser.add_argument("--commodities", default="all",
                        help='Comma-separated slugs or "all" (commodities with a geography).')
    parser.add_argument("--tiers", default="climate")
    parser.add_argument(
        "--feature-sets",
        default="",
        dest="feature_sets",
        help="Comma-separated model-purpose feature_set ids. Requires --dataset-version.",
    )
    parser.add_argument("--targets", default="production_quantity")
    parser.add_argument("--target-keys", default="production_anomaly_pct", dest="target_keys")
    parser.add_argument("--dataset-keys", default="annual_physical_anomaly", dest="dataset_keys")
    parser.add_argument("--models", default="xgboost")
    parser.add_argument("--experiment", default="leviathan-tier1-production")
    parser.add_argument("--dataset-version", default="", dest="dataset_version")
    parser.add_argument("--model-dataset-version", default="", dest="model_dataset_version")
    parser.add_argument(
        "--target-source",
        default="psd",
        choices=["psd", "faostat"],
        dest="target_source",
        help="Target source to use when resolving --model-dataset-version latest.",
    )
    parser.add_argument("--source-dataset-version", default="", dest="source_dataset_version")
    parser.add_argument("--cv-policies", default="expanding_full_history", dest="cv_policies")
    parser.add_argument("--min-train-years", type=int, default=10, dest="min_train_years")
    parser.add_argument("--train-start-year", default="", dest="train_start_year")
    parser.add_argument("--rolling-window-years", default="", dest="rolling_window_years")
    parser.add_argument(
        "--register-model",
        action="store_true",
        dest="register_model",
        help="Register model versions. Keep off for broad sweeps.",
    )
    parser.add_argument("--registered-model-name", default="", dest="registered_model_name")
    parser.add_argument("--detrend", action="store_true",
                        help="predict the detrended anomaly target (recommended for stress features)")
    parser.add_argument("--optuna", action="store_true",
                        help="search hyperparameters with Optuna per job")
    parser.add_argument("--n-trials", type=int, default=30, dest="n_trials")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    bucket = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    if args.commodities.strip().lower() == "all":
        commodities = [c for c in ALL_COMMODITIES if load_countries(c)]
    else:
        commodities = [c.strip() for c in args.commodities.split(",")]
        unknown = [c for c in commodities if c not in ALL_COMMODITIES]
        if unknown:
            raise SystemExit(f"ERROR: Unknown commodities: {unknown}")

    tiers = [t.strip() for t in args.tiers.split(",") if t.strip()]
    feature_sets = [t.strip() for t in args.feature_sets.split(",") if t.strip()]
    model_ready_mode = bool(args.model_dataset_version.strip())
    if args.model_dataset_version.strip().lower() in {"latest", "active", "default"}:
        registry = load_model_dataset_version_registry()
        raw_dataset_keys = [
            t.strip() for t in args.dataset_keys.split(",") if t.strip()
        ]
        if len(raw_dataset_keys) != 1:
            raise SystemExit(
                "--model-dataset-version latest requires exactly one --dataset-keys value"
            )
        selected = registry.select_default(
            target_source=args.target_source,
            dataset_key=raw_dataset_keys[0],
        )
        args.model_dataset_version = selected.dataset_version
        model_ready_mode = True
        logger.info(
            "Resolved active model dataset version=%s status=%s target_source=%s dataset_key=%s",
            selected.dataset_version,
            selected.status,
            selected.target_source,
            raw_dataset_keys[0],
        )
    elif model_ready_mode:
        selected = get_model_dataset_version_status(args.model_dataset_version)
        logger.info(
            "Using explicit model dataset version=%s status=%s default_allowed=%s",
            selected.dataset_version,
            selected.status,
            selected.default_discovery_allowed,
        )
    if feature_sets and not (args.dataset_version or model_ready_mode):
        raise SystemExit("--feature-sets requires --dataset-version or --model-dataset-version")
    if model_ready_mode and args.detrend:
        raise SystemExit("--detrend is not valid with --model-dataset-version")
    targets = [t.strip() for t in args.targets.split(",")]
    target_keys = [t.strip() for t in args.target_keys.split(",") if t.strip()]
    dataset_keys = [t.strip() for t in args.dataset_keys.split(",") if t.strip()]
    models = [m.strip() for m in args.models.split(",")]
    cv_policies = [p.strip() for p in args.cv_policies.split(",") if p.strip()]
    selectors = feature_sets or tiers

    tasks = [
        {
            "commodity": c,
            "tier": t if not feature_sets else "climate",
            "feature_set": t if feature_sets else "none",
            "target": tg,
            "model": m,
            "bucket": bucket, "aws_region": aws_region, "experiment": args.experiment,
            "detrend": str(args.detrend).lower(),   # Ref::detrend → "true"/"false"
            "optuna": str(args.optuna).lower(),
            "n_trials": str(args.n_trials),
            "min_train_years": str(args.min_train_years),
            "dataset_version": args.dataset_version or "none",
            "cv_policy": cvp,
            "train_start_year": args.train_start_year or "none",
            "rolling_window_years": args.rolling_window_years or "none",
            "register_model": str(args.register_model).lower(),
            "registered_model_name": args.registered_model_name or "none",
        }
        for c, t, tg, m, cvp in itertools.product(
            commodities, selectors, targets, models, cv_policies
        )
    ]
    if model_ready_mode:
        tasks = [
            {
                "commodity": c,
                "tier": t if not feature_sets else "climate",
                "feature_set": t if feature_sets else "none",
                "target": "production_quantity",
                "model": m,
                "bucket": bucket, "aws_region": aws_region, "experiment": args.experiment,
                "detrend": "false",
                "optuna": str(args.optuna).lower(),
                "n_trials": str(args.n_trials),
                "min_train_years": str(args.min_train_years),
                "dataset_version": "none",
                "model_dataset_version": args.model_dataset_version,
                "source_dataset_version": args.source_dataset_version or "none",
                "dataset_key": dk,
                "target_key": tk,
                "cv_policy": cvp,
                "train_start_year": args.train_start_year or "none",
                "rolling_window_years": args.rolling_window_years or "none",
                "register_model": str(args.register_model).lower(),
                "registered_model_name": args.registered_model_name or "none",
            }
            for c, t, dk, tk, m, cvp in itertools.product(
                commodities, selectors, dataset_keys, target_keys, models, cv_policies
            )
        ]

    grid_target_count = len(dataset_keys) * len(target_keys) if model_ready_mode else len(targets)
    logger.info(
        "Submitting %d training tasks  queue=%s  definition=%s  model_ready=%s  grid=%dx%dx%dx%dx%d  dry_run=%s",
        len(tasks), batch_queue, job_def, model_ready_mode,
        len(commodities), len(selectors), grid_target_count, len(models),
        len(cv_policies), args.dry_run,
    )

    def _job_name(task: dict) -> str:
        selector = task["feature_set"] if task.get("feature_set") != "none" else task["tier"]
        if task.get("target_key", "none") != "none":
            raw = (
                f"train-{task['commodity']}-{selector}-{task['dataset_key']}-"
                f"{task['target_key']}-{task['model']}-{task['cv_policy']}"
            )
        else:
            raw = (
                f"train-{task['commodity']}-{selector}-{task['target']}-"
                f"{task['model']}-{task['cv_policy']}"
            )
        return raw.replace("_", "-")

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
            Path("data/batch_runs") / f"train_{run_id}.json",
            {"run_id": run_id, "job": "train", "experiment": args.experiment,
             "task_count": len(submitted), "tasks": submitted},
        )
        logger.info("Done: %d/%d tasks submitted.",
                    sum(1 for t in submitted if t["job_id"]), len(tasks))


if __name__ == "__main__":
    main()
