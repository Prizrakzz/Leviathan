"""AWS Batch task: USDA WASDE raw/ → bronze/ layer (TXT 1995–1999 + digital PDFs 2000–2026).

Reads each raw WASDE file from S3, parses it into a tidy S/D DataFrame using
``parse_wasde_txt`` or ``parse_wasde_pdf_digital``, and writes one Parquet per
release date to the bronze/ layer.

Output S3 key pattern
---------------------
    bronze/production/source=usda_wasde/release_date={YYYY-MM-DD}/part-000.parquet

For each release a companion run-log entry is appended to::

    bronze/production/source=usda_wasde/_run_log.json

Scanned-era PDFs (1973–1994) are handled separately by
``wasde_bronze_scanned_task.py`` which routes through AWS Textract.

Usage
-----
    # Idempotent run (skip releases already in bronze/)
    python jobs/batch/wasde_bronze_modern_task.py \\
        --bucket leviathan-dev-shahem-001 --aws-region us-east-1

    # Force overwrite all
    python jobs/batch/wasde_bronze_modern_task.py \\
        --bucket leviathan-dev-shahem-001 --aws-region us-east-1 --force-overwrite

    # Dry-run (no writes)
    python jobs/batch/wasde_bronze_modern_task.py \\
        --bucket leviathan-dev-shahem-001 --aws-region us-east-1 --dry-run

    # Smoke-test: process at most 5 files
    python jobs/batch/wasde_bronze_modern_task.py \\
        --bucket leviathan-dev-shahem-001 --aws-region us-east-1 --limit 5
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_wasde_key, parse_hive_key
from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys, s3_download_with_retry
from leviathan.transforms.raw_to_bronze.usda_wasde import (
    parse_wasde_pdf_digital,
    parse_wasde_txt,
)
from leviathan.transforms.raw_to_text.wasde_scanned import _is_scanned_key

logger = get_logger("wasde_bronze_modern_task")

_RAW_PREFIX = "raw/production/source=usda_wasde/"
_RUN_LOG_KEY = "bronze/production/source=usda_wasde/_run_log.json"
_MAX_WORKERS = 8


# ---------------------------------------------------------------------------
# Key classification helpers
# ---------------------------------------------------------------------------

def _is_txt_key(key: str) -> bool:
    """Return True if this is a TXT-era WASDE (1995–1999)."""
    return key.endswith(".txt")


def _is_modern_pdf_key(key: str) -> bool:
    """Return True if this is a digital PDF (2000–2026), not scanned."""
    return key.endswith(".pdf") and not _is_scanned_key(key)


def _is_modern_key(key: str) -> bool:
    return _is_txt_key(key) or _is_modern_pdf_key(key)


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------

def _key_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001
        return False


def _upload_parquet(s3_client, bucket: str, key: str, df: pd.DataFrame) -> None:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=buf.getvalue(),
        ContentType="application/octet-stream",
    )


def _upload_json(s3_client, bucket: str, key: str, payload: object) -> None:
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(payload, indent=2, default=str).encode(),
        ContentType="application/json",
    )


# ---------------------------------------------------------------------------
# Per-file processing
# ---------------------------------------------------------------------------

def _process_one(
    raw_key: str,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
    dry_run: bool,
) -> dict:
    """Download, parse, and upload bronze Parquet for a single WASDE release.

    Returns a result dict (for the run log) with keys:
        raw_key, release_date, bronze_key, rows, status, error
    """
    release_date = parse_hive_key(raw_key, "release_date")
    bronze_key = bronze_wasde_key(release_date)
    result: dict = {
        "raw_key":      raw_key,
        "release_date": release_date,
        "bronze_key":   bronze_key,
        "rows":         0,
        "status":       "unknown",
        "error":        None,
    }

    s3 = get_thread_local_s3_client(aws_region)

    # Idempotency check
    if not force_overwrite and _key_exists(s3, bucket, bronze_key):
        result["status"] = "skipped"
        return result

    try:
        raw_bytes = s3_download_with_retry(bucket, raw_key, s3)
    except Exception as exc:  # noqa: BLE001
        result["status"] = "error"
        result["error"] = f"download: {exc}"
        return result

    try:
        if _is_txt_key(raw_key):
            df = parse_wasde_txt(raw_bytes, release_date)
        else:
            df = parse_wasde_pdf_digital(raw_bytes, release_date)
    except Exception as exc:  # noqa: BLE001
        result["status"] = "error"
        result["error"] = f"parse: {exc}"
        return result

    result["rows"] = len(df)

    if df.empty:
        logger.warning("Zero rows parsed  key=%s", raw_key)

    if not dry_run:
        try:
            _upload_parquet(s3, bucket, bronze_key, df)
        except Exception as exc:  # noqa: BLE001
            result["status"] = "error"
            result["error"] = f"upload: {exc}"
            return result

    result["status"] = "dry_run" if dry_run else "written"
    return result


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="WASDE raw → bronze (TXT 1995–1999 + digital PDF 2000–2026)"
    )
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        default=False,
        help="Re-parse and overwrite existing bronze Parquets.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Parse files but do not write to S3.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process at most N files (0 = no limit; useful for smoke tests).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=_MAX_WORKERS,
        help=f"ThreadPoolExecutor workers (default {_MAX_WORKERS}).",
    )
    return parser.parse_args()


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

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    s3 = get_thread_local_s3_client(aws_region)
    start = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Discover raw keys for the modern era
    # ------------------------------------------------------------------
    all_keys = list_s3_keys(bucket, _RAW_PREFIX, aws_region=aws_region)
    modern_keys = sorted(k for k in all_keys if _is_modern_key(k))

    logger.info(
        "WASDE bronze modern task  bucket=%s  total_modern=%d  force=%s  dry_run=%s  limit=%s",
        bucket,
        len(modern_keys),
        args.force_overwrite,
        args.dry_run,
        args.limit or "none",
    )

    if not modern_keys:
        logger.error("No modern WASDE keys found under %s — aborting", _RAW_PREFIX)
        sys.exit(1)

    if args.limit:
        modern_keys = modern_keys[: args.limit]

    # ------------------------------------------------------------------
    # Process in parallel
    # ------------------------------------------------------------------
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                _process_one,
                key,
                bucket,
                aws_region,
                args.force_overwrite,
                args.dry_run,
            ): key
            for key in modern_keys
        }
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                res = fut.result()
            except Exception as exc:  # noqa: BLE001
                res = {
                    "raw_key":      key,
                    "release_date": parse_hive_key(key, "release_date"),
                    "bronze_key":   "",
                    "rows":         0,
                    "status":       "error",
                    "error":        str(exc),
                }
            results.append(res)
            logger.info(
                "%-8s  rows=%-6d  %s",
                res["status"],
                res["rows"],
                res["raw_key"],
            )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    written  = sum(1 for r in results if r["status"] == "written")
    skipped  = sum(1 for r in results if r["status"] == "skipped")
    dry_runs = sum(1 for r in results if r["status"] == "dry_run")
    errors   = sum(1 for r in results if r["status"] == "error")
    total_rows = sum(r["rows"] for r in results)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        "Done  written=%d  skipped=%d  dry_run=%d  errors=%d  total_rows=%d  elapsed=%.1fs",
        written, skipped, dry_runs, errors, total_rows, elapsed,
    )

    # ------------------------------------------------------------------
    # Run log
    # ------------------------------------------------------------------
    run_log = {
        "task":          "wasde_bronze_modern_task",
        "completed_at":  datetime.now(timezone.utc).isoformat(),
        "bucket":        bucket,
        "written":       written,
        "skipped":       skipped,
        "dry_run":       dry_runs,
        "errors":        errors,
        "total_rows":    total_rows,
        "elapsed_seconds": round(elapsed, 2),
        "results":       results,
    }

    if not args.dry_run:
        try:
            _upload_json(s3, bucket, _RUN_LOG_KEY, run_log)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not write run log: %s", exc)

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
