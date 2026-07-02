"""Submit the Phase 3 WASDE release-date snapshot model-ready build to Batch."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from leviathan.common.batch_submit import submit_batch_jobs, write_run_record  # noqa: E402
from leviathan.common.config import load_env  # noqa: E402
from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.storage.metadata import utc_now_iso  # noqa: E402

logger = get_logger("submit_batch_wasde_snapshot_model_ready")


def _version() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    load_env()
    env = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")

    parser = argparse.ArgumentParser(
        description="Submit the WASDE snapshot model-ready build."
    )
    parser.add_argument("--source-dataset-version", default="20260626T010217Z_6725de02_phase7_full", dest="source_dataset_version")
    parser.add_argument("--model-dataset-version", default="", dest="model_dataset_version")
    parser.add_argument("--dataset-key", default="corn_wasde_snapshot_solo", dest="dataset_key")
    parser.add_argument("--commodity", default="corn_cbot")
    parser.add_argument("--target-keys", default="psd_stock_to_use_anomaly_pct,psd_ending_stocks_anomaly_pct", dest="target_keys")
    parser.add_argument("--feature-set-ids", default="wasde_monthly_revision", dest="feature_set_ids")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--min-history-years", type=int, default=5, dest="min_history_years")
    parser.add_argument("--min-non-null-rate", type=float, default=0.5, dest="min_non_null_rate")
    parser.add_argument("--phase2-density-prefix", default="", dest="phase2_density_prefix")
    parser.add_argument("--job-queue", default=None, dest="job_queue")
    parser.add_argument("--job-definition", default=None, dest="job_definition")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.workers < 1:
        parser.error("--workers must be >= 1")
    model_dataset_version = args.model_dataset_version.strip() or (
        f"{_version()}_phase3_wasde_snapshot_model_ready"
    )
    bucket = os.environ.get("LEVIATHAN_BUCKET", "leviathan-dev-shahem-001")
    aws_region = os.environ.get("AWS_REGION", "us-east-1")
    phase2_prefix = args.phase2_density_prefix.strip() or (
        "model_artifacts/wasde_snapshot_feature_density/"
        "dataset_version=20260629T115343Z_phase2_wasde_feature_density"
    )
    params = {
        "bucket": bucket,
        "aws_region": aws_region,
        "source_dataset_version": args.source_dataset_version,
        "model_dataset_version": model_dataset_version,
        "dataset_key": args.dataset_key,
        "commodity": args.commodity,
        "target_keys": args.target_keys,
        "feature_set_ids": args.feature_set_ids,
        "workers": str(max(1, int(args.workers))),
        "min_history_years": str(max(1, int(args.min_history_years))),
        "min_non_null_rate": str(float(args.min_non_null_rate)),
        "phase2_density_prefix": phase2_prefix,
        "skip_existing_versioned": "true",
    }
    queue = args.job_queue or f"{project}-{env}-queue"
    job_def = args.job_definition or f"{project}-{env}-wasde-snapshot-model-ready"
    logger.info(
        "Submitting WASDE snapshot model-ready build queue=%s job_definition=%s params=%s",
        queue,
        job_def,
        params,
    )
    submitted = submit_batch_jobs(
        tasks=[params],
        job_queue=queue,
        job_definition=job_def,
        build_job_name=lambda task: f"wasde-snapshot-model-ready-{task['dataset_key']}",
        aws_region=aws_region,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        logger.info("[DRY RUN] model_dataset_version=%s", model_dataset_version)
        return

    run_id = utc_now_iso().replace(":", "-")
    write_run_record(
        Path("data/batch_runs") / f"wasde_snapshot_model_ready_{run_id}.json",
        {
            "run_id": run_id,
            "job": "wasde_snapshot_model_ready",
            "task_count": len(submitted),
            "parameters": params,
            "tasks": submitted,
        },
    )
    logger.info("Submitted WASDE snapshot model-ready job: %s", submitted[0].get("job_id"))


if __name__ == "__main__":
    main()
