"""CHIRPS backfill: COG -> bronze then bronze -> silver for all 31 commodities.

Submits chirps_to_bronze Glue jobs in parallel (one per commodity × year),
polls to completion, then runs bronze_to_silver_chirps per commodity.

Before submitting jobs, uploads the geography config YAMLs to S3 so the
Glue jobs (which have no local filesystem access) can read them at runtime.

Usage:
    python jobs/run_chirps_backfill.py
    python jobs/run_chirps_backfill.py --commodities corn_cbot,cocoa
    python jobs/run_chirps_backfill.py --start-year 2010 --end-year 2020
    python jobs/run_chirps_backfill.py --skip-c2b             # bronze->silver only
    python jobs/run_chirps_backfill.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import boto3
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from glue_utils import poll_glue_runs as _poll_glue_runs

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BUCKET        = os.environ.get("LEVIATHAN_BUCKET", "leviathan-dev-shahem-001")
AWS_REGION    = os.environ.get("AWS_REGION", "us-east-1")
LEVIATHAN_ENV = os.environ.get("LEVIATHAN_ENV", "dev")
PROJECT       = os.environ.get("LEVIATHAN_PROJECT", "leviathan")

C2B_JOB = f"{PROJECT}-{LEVIATHAN_ENV}-chirps-to-bronze"
B2S_JOB = f"{PROJECT}-{LEVIATHAN_ENV}-bronze-to-silver-chirps"

POLL_INTERVAL = 30  # seconds

_CONFIGS_DIR = Path(__file__).parents[1] / "configs"

# ---------------------------------------------------------------------------
# Load commodity list from constants
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from leviathan.common.constants import ALL_COMMODITIES, CHIRPS_START_YEAR


# ---------------------------------------------------------------------------
# Helpers: geography config upload
# ---------------------------------------------------------------------------

def _upload_geo_configs(s3_client, commodities: list[str]) -> None:
    """Upload geography YAML configs for each commodity to S3.

    The Glue jobs read these at runtime from
    s3://{bucket}/configs/geographies/{commodity}_regions.yaml.
    """
    geo_dir = _CONFIGS_DIR / "geographies"
    for commodity in commodities:
        local_path = geo_dir / f"{commodity}_regions.yaml"
        if not local_path.exists():
            print(f"  WARNING: Geography config not found: {local_path}")
            continue
        s3_key = f"configs/geographies/{commodity}_regions.yaml"
        s3_client.upload_file(str(local_path), BUCKET, s3_key)
        print(f"  Uploaded {s3_key}")


# ---------------------------------------------------------------------------
# Helpers: job submission
# ---------------------------------------------------------------------------

def _start_c2b(
    glue, commodity: str, year: int, ingest_date: str, dry_run: bool
) -> tuple[str, int, str]:
    label = f"{commodity}/{year}"
    if dry_run:
        print(f"  [DRY RUN] Would start {C2B_JOB} commodity={commodity} year={year}")
        return commodity, year, "DRY_RUN"
    run_id = glue.start_job_run(
        JobName=C2B_JOB,
        Arguments={
            "--commodity":   commodity,
            "--year":        str(year),
            "--ingest_date": ingest_date,
            "--bucket":      BUCKET,
            "--aws_region":  AWS_REGION,
        },
    )["JobRunId"]
    print(f"  Started {C2B_JOB} {label}  run_id={run_id}")
    return commodity, year, run_id


def _start_b2s(
    glue, commodity: str, dry_run: bool, force_overwrite: bool
) -> tuple[str, str]:
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
    print(f"  Started {B2S_JOB} commodity={commodity}  run_id={run_id}")
    return commodity, run_id


# ---------------------------------------------------------------------------
# Stage runner
# ---------------------------------------------------------------------------

def _run_c2b_stage(
    glue,
    commodities: list[str],
    start_year: int,
    end_year: int,
    dry_run: bool,
) -> dict[tuple[str, int], str]:
    """Submit one chirps_to_bronze job per commodity × year, poll to completion."""
    jobs: list[tuple[str, int]] = [
        (c, y) for c in commodities for y in range(start_year, end_year + 1)
    ]
    print(f"\n--- Stage: {C2B_JOB} ({len(jobs)} jobs) ---")
    ingest_date = date.today().isoformat()

    with ThreadPoolExecutor(max_workers=min(len(jobs), 100)) as pool:
        futures = [pool.submit(_start_c2b, glue, c, y, ingest_date, dry_run) for c, y in jobs]
        submissions = [f.result() for f in as_completed(futures)]

    if dry_run:
        return {(c, y): "SUCCEEDED" for c, y in jobs}

    run_id_to_job: dict[str, str] = {run_id: C2B_JOB for _, _, run_id in submissions}
    run_id_to_key: dict[str, tuple[str, int]] = {
        run_id: (c, y) for c, y, run_id in submissions
    }
    run_statuses = _poll_glue_runs(glue, run_id_to_job, POLL_INTERVAL)
    return {run_id_to_key[rid]: status for rid, status in run_statuses.items()}


def _run_b2s_stage(
    glue,
    commodities: list[str],
    dry_run: bool,
    force_overwrite: bool,
) -> dict[str, str]:
    print(f"\n--- Stage: {B2S_JOB} ({len(commodities)} commodities) ---")
    if not commodities:
        print("  No commodities to process — skipping.")
        return {}

    with ThreadPoolExecutor(max_workers=min(len(commodities), 31)) as pool:
        futures = [
            pool.submit(_start_b2s, glue, c, dry_run, force_overwrite)
            for c in commodities
        ]
        submissions = [f.result() for f in as_completed(futures)]

    if dry_run:
        return {c: "SUCCEEDED" for c in commodities}

    run_id_to_job: dict[str, str] = {run_id: B2S_JOB for _, run_id in submissions}
    run_id_to_commodity: dict[str, str] = {run_id: c for c, run_id in submissions}
    run_statuses = _poll_glue_runs(glue, run_id_to_job, POLL_INTERVAL)
    return {run_id_to_commodity[rid]: status for rid, status in run_statuses.items()}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="CHIRPS backfill: COG->bronze then bronze->silver for all 31 commodities."
    )
    parser.add_argument(
        "--commodities",
        default="all",
        help='Comma-separated list or "all" (default).',
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=CHIRPS_START_YEAR,
        help=f"First year to ingest (default: {CHIRPS_START_YEAR}).",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=date.today().year,
        help="Last year to ingest (default: current year).",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--skip-c2b",
        action="store_true",
        help="Skip COG->bronze stage (bronze already exists). Runs bronze->silver only.",
    )
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        help="Rewrite existing bronze and silver partitions.",
    )
    args = parser.parse_args()

    commodities: list[str] = (
        list(ALL_COMMODITIES)
        if args.commodities.strip().lower() == "all"
        else [c.strip() for c in args.commodities.split(",")]
    )

    unknown = [c for c in commodities if c not in ALL_COMMODITIES]
    if unknown:
        print(f"ERROR: Unknown commodities: {unknown}")
        sys.exit(1)

    print(f"CHIRPS backfill — {len(commodities)} commodities  "
          f"years={args.start_year}–{args.end_year}  dry_run={args.dry_run}")
    print(f"Bucket: {BUCKET}  Region: {AWS_REGION}")

    s3_client = boto3.client("s3", region_name=AWS_REGION)
    glue = boto3.client("glue", region_name=AWS_REGION)

    # Upload geography configs so Glue jobs can read them from S3.
    if not args.dry_run:
        print("\nUploading geography configs to S3...")
        _upload_geo_configs(s3_client, commodities)

    # Stage 1: COG -> bronze
    if args.skip_c2b:
        print("--skip-c2b set: skipping COG->bronze stage.")
        c2b_results: dict[tuple[str, int], str] = {
            (c, y): "SKIPPED"
            for c in commodities
            for y in range(args.start_year, args.end_year + 1)
        }
        b2s_commodities = list(commodities)
    else:
        c2b_results = _run_c2b_stage(
            glue, commodities, args.start_year, args.end_year, args.dry_run
        )
        c2b_failed_keys = [(c, y) for (c, y), s in c2b_results.items() if s != "SUCCEEDED"]
        if c2b_failed_keys:
            failed_commodities = sorted({c for c, _ in c2b_failed_keys})
            print(f"\nWARNING: {len(c2b_failed_keys)} COG->bronze jobs failed.")
            print(f"Failed commodities: {failed_commodities}")
        # Only run B2S for commodities where ALL years succeeded.
        fully_succeeded = {
            c for c in commodities
            if all(
                c2b_results.get((c, y)) == "SUCCEEDED"
                for y in range(args.start_year, args.end_year + 1)
            )
        }
        b2s_commodities = [c for c in commodities if c in fully_succeeded]

    # Stage 2: bronze -> silver
    b2s_results = _run_b2s_stage(
        glue, b2s_commodities, args.dry_run, args.force_overwrite
    )

    # Summary
    total_c2b = len(commodities) * (args.end_year - args.start_year + 1)
    c2b_succeeded = sum(1 for s in c2b_results.values() if s == "SUCCEEDED")
    c2b_failed = sum(1 for s in c2b_results.values() if s not in ("SUCCEEDED", "SKIPPED"))
    b2s_succeeded = sum(1 for s in b2s_results.values() if s == "SUCCEEDED")
    b2s_failed = sum(1 for s in b2s_results.values() if s != "SUCCEEDED")

    print("\n" + "=" * 70)
    print("CHIRPS BACKFILL SUMMARY")
    print("=" * 70)
    print(f"  COG->bronze:    {c2b_succeeded}/{total_c2b} succeeded  ({c2b_failed} failed)")
    print(f"  Bronze->silver: {b2s_succeeded}/{len(b2s_commodities)} succeeded  ({b2s_failed} failed)")

    any_fail = c2b_failed > 0 or b2s_failed > 0
    if any_fail:
        print("\nSome jobs failed — check CloudWatch logs for details.")
        sys.exit(1)
    print("\nAll jobs completed successfully.")


if __name__ == "__main__":
    main()
