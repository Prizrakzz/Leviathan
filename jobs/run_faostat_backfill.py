"""One-shot FAOSTAT backfill: raw→bronze then bronze→silver for all 31 commodities.

Submits Glue jobs in parallel (up to 31 concurrent), polls to completion,
then starts the next stage. Uses the shared FAOSTAT ZIP on S3.

Usage:
    python jobs/run_faostat_backfill.py
    python jobs/run_faostat_backfill.py --commodities cocoa,soybeans_cbot
    python jobs/run_faostat_backfill.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import boto3
import yaml

from leviathan.common.polling import poll_glue_runs as _poll_glue_runs

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BUCKET       = os.environ.get("LEVIATHAN_BUCKET", "leviathan-dev-shahem-001")
AWS_REGION   = os.environ.get("AWS_REGION", "us-east-1")
LEVIATHAN_ENV = os.environ.get("LEVIATHAN_ENV", "dev")
PROJECT      = os.environ.get("LEVIATHAN_PROJECT", "leviathan")

R2B_JOB = f"{PROJECT}-{LEVIATHAN_ENV}-raw-to-bronze-faostat"
B2S_JOB = f"{PROJECT}-{LEVIATHAN_ENV}-bronze-to-silver-faostat"

RAW_S3_KEY = (
    "raw/production/source=faostat/dataset=QCL/"
    "Production_Crops_Livestock_E_All_Data_Normalized.zip"
)

POLL_INTERVAL = 30  # seconds

# ---------------------------------------------------------------------------
# Load item map
# ---------------------------------------------------------------------------

_MAP_PATH = Path(__file__).parents[1] / "configs" / "sources" / "faostat_item_map.yaml"
with _MAP_PATH.open() as _f:
    ITEM_MAP: dict[str, str] = yaml.safe_load(_f)

ALL_COMMODITIES: list[str] = list(ITEM_MAP.keys())

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _start_r2b(glue, commodity: str, ingest_date: str, dry_run: bool) -> tuple[str, str]:
    if dry_run:
        print(f"  [DRY RUN] Would start {R2B_JOB} commodity={commodity}")
        return commodity, "DRY_RUN"
    run_id = glue.start_job_run(
        JobName=R2B_JOB,
        Arguments={
            "--commodity":     commodity,
            "--fao_item_name": ITEM_MAP[commodity],
            "--ingest_date":   ingest_date,
            "--s3_raw_key":    RAW_S3_KEY,
            "--bucket":        BUCKET,
            "--aws_region":    AWS_REGION,
        },
    )["JobRunId"]
    print(f"  Started {R2B_JOB} commodity={commodity} run_id={run_id}")
    return commodity, run_id


def _start_b2s(glue, commodity: str, dry_run: bool, force_overwrite: bool = False) -> tuple[str, str]:
    if dry_run:
        print(f"  [DRY RUN] Would start {B2S_JOB} commodity={commodity}")
        return commodity, "DRY_RUN"
    arguments: dict[str, str] = {
        "--commodity":  commodity,
        "--bucket":     BUCKET,
        "--aws_region": AWS_REGION,
    }
    if force_overwrite:
        arguments["--force_overwrite"] = "true"
    run_id = glue.start_job_run(JobName=B2S_JOB, Arguments=arguments)["JobRunId"]
    print(f"  Started {B2S_JOB} commodity={commodity} run_id={run_id}")
    return commodity, run_id


def poll_stage(
    glue,
    job_name: str,
    commodity_run_ids: list[tuple[str, str]],
    dry_run: bool,
) -> dict[str, str]:
    """Poll all runs until terminal. Returns {commodity: status}."""
    if dry_run:
        return {c: "SUCCEEDED" for c, _ in commodity_run_ids}

    run_id_to_commodity = {run_id: commodity for commodity, run_id in commodity_run_ids}
    run_id_to_job = {run_id: job_name for _, run_id in commodity_run_ids}
    run_statuses = _poll_glue_runs(glue, run_id_to_job, POLL_INTERVAL)
    return {run_id_to_commodity[run_id]: status for run_id, status in run_statuses.items()}


def run_stage(
    glue,
    job_name: str,
    start_fn,
    commodities: list[str],
    dry_run: bool,
    force_overwrite: bool = False,
) -> dict[str, str]:
    print(f"\n--- Stage: {job_name} ({len(commodities)} commodities) ---")
    if not commodities:
        print("  No commodities to process — skipping.")
        return {}
    ingest_date = date.today().isoformat()

    with ThreadPoolExecutor(max_workers=min(len(commodities), 31)) as pool:
        if "r2b" in job_name or "raw" in job_name:
            futures = [pool.submit(_start_r2b, glue, c, ingest_date, dry_run) for c in commodities]
        else:
            futures = [
                pool.submit(_start_b2s, glue, c, dry_run, force_overwrite)
                for c in commodities
            ]
        commodity_run_ids = [f.result() for f in as_completed(futures)]

    if dry_run:
        return {c: "SUCCEEDED" for c in commodities}

    return poll_stage(glue, job_name, commodity_run_ids, dry_run)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="FAOSTAT backfill: raw→bronze then bronze→silver for all 31 commodities."
    )
    parser.add_argument(
        "--commodities",
        default="all",
        help='Comma-separated list or "all" (default).',
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--skip-r2b",
        action="store_true",
        help="Skip raw→bronze stage (bronze data already exists in S3). Runs bronze→silver only.",
    )
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        help=(
            "Pass --force_overwrite true to bronze→silver Glue jobs, rewriting existing "
            "silver partitions. Required after a silver schema change. "
            "Usually combined with --skip-r2b: run_faostat_backfill.py --skip-r2b --force-overwrite"
        ),
    )
    args = parser.parse_args()

    commodities = (
        ALL_COMMODITIES
        if args.commodities.strip().lower() == "all"
        else [c.strip() for c in args.commodities.split(",")]
    )

    unknown = [c for c in commodities if c not in ITEM_MAP]
    if unknown:
        print(f"ERROR: Unknown commodities (not in faostat_item_map.yaml): {unknown}")
        sys.exit(1)

    print(f"FAOSTAT backfill — {len(commodities)} commodities  dry_run={args.dry_run}")
    print(f"Bucket: {BUCKET}  Region: {AWS_REGION}")

    glue = boto3.client("glue", region_name=AWS_REGION)

    if args.force_overwrite:
        print("--force-overwrite set: bronze→silver jobs will rewrite existing silver partitions.")

    # Stage 1: raw → bronze (skipped when --skip-r2b is set)
    if args.skip_r2b:
        print("--skip-r2b set: skipping raw→bronze stage.")
        r2b_results = {c: "SKIPPED" for c in commodities}
        b2s_commodities = list(commodities)
    else:
        r2b_results = run_stage(glue, R2B_JOB, _start_r2b, commodities, args.dry_run)
        r2b_failed = [c for c, s in r2b_results.items() if s != "SUCCEEDED"]
        if r2b_failed:
            print(f"\nWARNING: {len(r2b_failed)} raw→bronze jobs failed: {r2b_failed}")
            print("Proceeding to bronze→silver for successful commodities only.")
        b2s_commodities = [c for c in commodities if r2b_results.get(c) == "SUCCEEDED"]

    # Stage 2: bronze → silver
    b2s_results = run_stage(
        glue, B2S_JOB, _start_b2s, b2s_commodities, args.dry_run,
        force_overwrite=args.force_overwrite,
    )
    b2s_failed = [c for c, s in b2s_results.items() if s != "SUCCEEDED"]

    # Summary
    print("\n" + "=" * 70)
    print("FAOSTAT BACKFILL SUMMARY")
    print("=" * 70)
    print(f"{'COMMODITY':<45} {'RAW→BRZ':>12} {'BRZ→SLV':>12}")
    print("-" * 70)
    any_fail = False
    for c in commodities:
        r = r2b_results.get(c, "SKIPPED")
        b = b2s_results.get(c, "SKIPPED")
        if r != "SUCCEEDED" or b != "SUCCEEDED":
            any_fail = True
        print(f"{c:<45} {r:>12} {b:>12}")
    print("=" * 70)

    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
