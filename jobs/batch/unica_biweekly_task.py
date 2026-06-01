"""AWS Batch task: UNICA biweekly PDF reports → bronze/ layer.

Downloads each UNICA bi-weekly bulletin PDF from raw/, classifies it,
parses up to five output tables, and writes them as Parquet files to bronze/.

Output S3 key structure
-----------------------
    bronze/production/source=unica_biweekly/
        table={table_name}/
        harvest_year={YYYY_YYYY}/
        idm={idm}/
        part-000.parquet

Output table names
------------------
    fortnight_production      historical fortnight accumulation by region
    summary_snapshot          current-report snapshot (accumulated + fortnightly)
    corn_ethanol              corn-derived ethanol by fortnight
    monthly_ethanol_sales     ethanol sales by month and market destination
    season_final_extras       EAV table for season-final supplementary sub-tables

Skipped documents (skip_offtopic, season_estimate, unknown) produce no output
Parquet files but are counted in the run log.

Usage
-----
    # Dry-run (no writes)
    python jobs/batch/unica_biweekly_task.py --bucket leviathan-dev-shahem-001 \\
        --aws-region us-east-1 --dry-run

    # Full backfill (idempotent — skips existing outputs)
    python jobs/batch/unica_biweekly_task.py --bucket leviathan-dev-shahem-001 \\
        --aws-region us-east-1

    # Force overwrite all outputs
    python jobs/batch/unica_biweekly_task.py --force-overwrite

    # Smoke test (first 5 PDFs)
    python jobs/batch/unica_biweekly_task.py --limit 5

    # Restrict to a single harvest year
    python jobs/batch/unica_biweekly_task.py --harvest-year 2023_2024
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import (
    bronze_unica_biweekly_key,
    parse_hive_key,
)
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.raw_to_bronze.unica_biweekly_pdf import transform_pdf

logger = get_logger("unica_biweekly_task")

_RAW_PREFIX = "raw/production/source=unica_biweekly/"
_BRONZE_PREFIX = "bronze/production/source=unica_biweekly/"
_WORKERS = 8

_OUTPUT_TABLES = [
    "fortnight_production",
    "summary_snapshot",
    "corn_ethanol",
    "monthly_ethanol_sales",
    "season_final_extras",
]


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UNICA biweekly PDFs → bronze/")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument(
        "--force-overwrite",
        default="false",
        help="Overwrite existing bronze Parquets (default: false).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be written without writing to S3.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process at most N raw PDFs (0 = no limit; useful for smoke tests).",
    )
    parser.add_argument(
        "--harvest-year",
        default=None,
        dest="harvest_year",
        help="Restrict processing to a single harvest year, e.g. 2023_2024.",
    )
    args = parser.parse_args()
    args.force_overwrite = _parse_bool(args.force_overwrite)
    return args


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


def _all_bronze_exist(
    s3_client,
    bucket: str,
    harvest_year: str,
    idm: str,
    expected_tables: list[str],
) -> bool:
    """Return True only when every expected bronze Parquet already exists."""
    for table_name in expected_tables:
        key = bronze_unica_biweekly_key(harvest_year, idm, table_name)
        try:
            s3_client.head_object(Bucket=bucket, Key=key)
        except Exception:  # noqa: BLE001
            return False
    return True


def _process(
    raw_key: str,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
    dry_run: bool,
    ingest_date: str,
) -> tuple[str, str, str]:
    """Process one raw PDF key.

    Returns:
        (status, raw_key, doc_type)
        status: "written" | "skipped" | "skip_offtopic" | "error"
    """
    s3 = get_thread_local_s3_client(aws_region)

    harvest_year = parse_hive_key(raw_key, "harvest_year")
    idm = parse_hive_key(raw_key, "idm")

    if not harvest_year or not idm:
        logger.warning("Could not parse harvest_year/idm from key: %s", raw_key)
        return "error", raw_key, "unknown"

    # Skip check: if ALL output tables already exist, skip unless force-overwrite
    if not force_overwrite and _all_bronze_exist(s3, bucket, harvest_year, idm, _OUTPUT_TABLES):
        return "skipped", raw_key, "skipped"

    # Download
    try:
        pdf_bytes = s3_download_with_retry(bucket, raw_key, s3)
    except Exception as exc:  # noqa: BLE001
        logger.error("S3 download failed  key=%s: %s", raw_key, exc)
        return "error", raw_key, "unknown"

    # Transform
    try:
        tables = transform_pdf(pdf_bytes, harvest_year, idm, ingest_date)
    except Exception as exc:  # noqa: BLE001
        logger.error("transform_pdf failed  key=%s: %s", raw_key, exc)
        return "error", raw_key, "unknown"

    doc_type: str = tables.get("_classification", "unknown")

    if doc_type in ("skip_offtopic", "season_estimate", "unknown"):
        logger.debug("Skipped (doc_type=%s)  key=%s", doc_type, raw_key)
        return "skip_offtopic", raw_key, doc_type

    # Write each output table
    written_any = False
    for table_name, df in tables.items():
        if table_name.startswith("_"):
            continue
        bronze_key = bronze_unica_biweekly_key(harvest_year, idm, table_name)
        if dry_run:
            logger.info(
                "[DRY-RUN] would write  table=%s  rows=%d  key=%s",
                table_name, len(df), bronze_key,
            )
            written_any = True
            continue
        try:
            buf = io.BytesIO()
            df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
            s3.put_object(
                Bucket=bucket,
                Key=bronze_key,
                Body=buf.getvalue(),
                ContentType="application/octet-stream",
            )
            logger.info(
                "bronze written  table=%s  rows=%d  key=%s",
                table_name, len(df), bronze_key,
            )
            written_any = True
        except Exception as exc:  # noqa: BLE001
            logger.error("Parquet write failed  table=%s  key=%s: %s", table_name, bronze_key, exc)
            return "error", raw_key, doc_type

    return ("written" if written_any else "skipped"), raw_key, doc_type


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )

    load_env()
    args = _parse_args()

    bucket: str = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region: str = args.aws_region or get_required_env("AWS_REGION")

    # Discover raw PDF keys
    raw_keys = list_s3_keys(bucket, _RAW_PREFIX, suffix="report.pdf", aws_region=aws_region)
    raw_keys.sort()

    # Optional harvest-year filter
    if args.harvest_year:
        hy = args.harvest_year.replace("/", "_")
        raw_keys = [k for k in raw_keys if f"harvest_year={hy}/" in k]
        logger.info("Filtered to harvest_year=%s  keys=%d", hy, len(raw_keys))

    if args.limit:
        raw_keys = raw_keys[: args.limit]

    logger.info(
        "unica_biweekly_task  bucket=%s  raw_keys=%d  force=%s  dry_run=%s",
        bucket, len(raw_keys), args.force_overwrite, args.dry_run,
    )

    ingest_date = datetime.now(timezone.utc).date().isoformat()
    start = datetime.now(timezone.utc)

    status_counts: dict[str, int] = defaultdict(int)
    doctype_counts: dict[str, int] = defaultdict(int)
    errors = 0

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {
            pool.submit(
                _process,
                key, bucket, aws_region, args.force_overwrite, args.dry_run, ingest_date,
            ): key
            for key in raw_keys
        }
        for fut in as_completed(futures):
            try:
                status, _, doc_type = fut.result()
            except Exception as exc:  # noqa: BLE001
                logger.error("Unexpected error: %s", exc)
                errors += 1
                status_counts["error"] += 1
                continue
            status_counts[status] += 1
            doctype_counts[doc_type] += 1
            if status == "error":
                errors += 1

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        "Done  written=%d  skipped=%d  skip_offtopic=%d  errors=%d  elapsed=%.1fs",
        status_counts["written"],
        status_counts["skipped"],
        status_counts["skip_offtopic"],
        errors,
        elapsed,
    )

    # Write run log to S3
    if not args.dry_run:
        try:
            run_log = {
                "ingest_date":    ingest_date,
                "elapsed_s":      round(elapsed, 1),
                "status_counts":  dict(status_counts),
                "doctype_counts": dict(doctype_counts),
            }
            import boto3  # noqa: PLC0415
            from botocore.config import Config  # noqa: PLC0415
            s3 = boto3.client("s3", region_name=aws_region, config=Config(retries={"max_attempts": 3}))
            s3.put_object(
                Bucket=bucket,
                Key=f"{_BRONZE_PREFIX}_run_log.json",
                Body=json.dumps(run_log, indent=2).encode(),
                ContentType="application/json",
            )
            logger.info("Run log written to %s_run_log.json", _BRONZE_PREFIX)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to write run log: %s", exc)

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
