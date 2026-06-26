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
from datetime import date
from pathlib import Path

from leviathan.common.batch_submit import submit_batch_jobs, write_run_record
from leviathan.common.config import get_required_env, load_env
from leviathan.common.constants import ALL_COMMODITIES
from leviathan.common.logging import get_logger
from leviathan.features.spine import load_countries
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
    parser.add_argument("--source-dataset-version", default="", dest="source_dataset_version")
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
    if feature_sets and not (args.dataset_version or model_ready_mode):
        raise SystemExit("--feature-sets requires --dataset-version or --model-dataset-version")
    if model_ready_mode and args.detrend:
        raise SystemExit("--detrend is not valid with --model-dataset-version")
    targets = [t.strip() for t in args.targets.split(",")]
    target_keys = [t.strip() for t in args.target_keys.split(",") if t.strip()]
    dataset_keys = [t.strip() for t in args.dataset_keys.split(",") if t.strip()]
    models = [m.strip() for m in args.models.split(",")]
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
            "dataset_version": args.dataset_version or "none",
        }
        for c, t, tg, m in itertools.product(commodities, selectors, targets, models)
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
                "dataset_version": "none",
                "model_dataset_version": args.model_dataset_version,
                "source_dataset_version": args.source_dataset_version or "none",
                "dataset_key": dk,
                "target_key": tk,
            }
            for c, t, dk, tk, m in itertools.product(
                commodities, selectors, dataset_keys, target_keys, models
            )
        ]

    grid_target_count = len(dataset_keys) * len(target_keys) if model_ready_mode else len(targets)
    logger.info(
        "Submitting %d training tasks  queue=%s  definition=%s  model_ready=%s  grid=%dx%dx%dx%d  dry_run=%s",
        len(tasks), batch_queue, job_def, model_ready_mode,
        len(commodities), len(selectors), grid_target_count, len(models), args.dry_run,
    )

    def _job_name(task: dict) -> str:
        selector = task["feature_set"] if task.get("feature_set") != "none" else task["tier"]
        if task.get("target_key", "none") != "none":
            raw = (
                f"train-{task['commodity']}-{selector}-{task['dataset_key']}-"
                f"{task['target_key']}-{task['model']}"
            )
        else:
            raw = f"train-{task['commodity']}-{selector}-{task['target']}-{task['model']}"
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
