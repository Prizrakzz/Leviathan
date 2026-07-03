"""Submit the Phase 2 WASDE snapshot feature-density audit to AWS Batch."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from leviathan.common.batch_submit import submit_batch_jobs, write_run_record  # noqa: E402
from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.storage.metadata import utc_now_iso  # noqa: E402

logger = get_logger("submit_batch_wasde_snapshot_feature_density")


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
    batch_queue = f"{project}-{env}-queue"
    job_definition = f"{project}-{env}-wasde-snapshot-feature-density"

    parser = argparse.ArgumentParser(
        description="Submit the WASDE snapshot feature-density Batch audit."
    )
    parser.add_argument("--dataset-key", default="corn_wasde_snapshot_solo", dest="dataset_key")
    parser.add_argument("--origins", default="", help="Comma-separated normalized origins.")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--min-history-years", type=int, default=5, dest="min_history_years")
    parser.add_argument("--min-non-null-rate", type=float, default=0.5, dest="min_non_null_rate")
    parser.add_argument(
        "--max-snapshots-per-group",
        type=int,
        default=0,
        dest="max_snapshots_per_group",
        help="Optional quick-debug row cap per origin/market-year group. Use 0 for full audit.",
    )
    parser.add_argument("--job-queue", default=None, dest="job_queue")
    parser.add_argument("--job-definition", default=None, dest="job_definition")
    parser.add_argument("--output-prefix", default="", dest="output_prefix")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.workers < 1:
        parser.error("--workers must be >= 1")
    if args.min_history_years < 1:
        parser.error("--min-history-years must be >= 1")
    if not 0.0 <= args.min_non_null_rate <= 1.0:
        parser.error("--min-non-null-rate must be between 0 and 1")

    bucket = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")
    output_prefix = args.output_prefix.strip("/")
    if not output_prefix:
        output_prefix = (
            "model_artifacts/wasde_snapshot_feature_density/"
            f"dataset_version={_version()}_phase2_wasde_feature_density"
        )

    params = {
        "bucket": bucket,
        "aws_region": aws_region,
        "dataset_key": args.dataset_key,
        "origins": args.origins or "none",
        "workers": str(max(1, int(args.workers))),
        "min_history_years": str(max(1, int(args.min_history_years))),
        "min_non_null_rate": str(float(args.min_non_null_rate)),
        "max_snapshots_per_group": str(max(0, int(args.max_snapshots_per_group))),
        "output_prefix": output_prefix,
    }

    queue = args.job_queue or batch_queue
    job_def = args.job_definition or job_definition
    logger.info(
        "Submitting WASDE snapshot feature-density audit queue=%s job_definition=%s params=%s",
        queue,
        job_def,
        params,
    )
    submitted = submit_batch_jobs(
        tasks=[params],
        job_queue=queue,
        job_definition=job_def,
        build_job_name=lambda task: f"wasde-density-{task['dataset_key']}",
        aws_region=aws_region,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        logger.info("[DRY RUN] output_prefix=s3://%s/%s", bucket, output_prefix)
        return

    run_id = utc_now_iso().replace(":", "-")
    write_run_record(
        Path("data/batch_runs") / f"wasde_snapshot_feature_density_{run_id}.json",
        {
            "run_id": run_id,
            "job": "wasde_snapshot_feature_density",
            "task_count": len(submitted),
            "parameters": params,
            "tasks": submitted,
        },
    )
    logger.info("Submitted WASDE snapshot feature-density job: %s", submitted[0].get("job_id"))


if __name__ == "__main__":
    main()
