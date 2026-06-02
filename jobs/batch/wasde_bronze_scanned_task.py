"""AWS Batch task: USDA WASDE scanned PDFs → bronze/ layer (1973–1994).

Routes scanned-era WASDE PDFs through AWS Textract async
(``StartDocumentTextDetection``), then parses the resulting LINE blocks into
the tidy bronze S/D schema using ``parse_wasde_pdf_scanned``.

Source files: ``raw/production/source=usda_wasde/`` — .pdf with year < 1999
Output key:   ``bronze/production/source=usda_wasde/release_date={YYYY-MM-DD}/part-000.parquet``
Run log:      ``bronze/production/source=usda_wasde/_scanned_run_log.json``

Cost note
---------
Each scanned PDF is pre-truncated to discard narrative pages 0–7 before
submission to Textract (using pypdf in-memory).  Only the supply-use table
pages (8+) are sent.  This reduces billable pages by ~30–40% compared with
submitting the full document.

Estimated cost: ~$6–7 for all 251 scanned releases.

Usage
-----
    # Smoke test — 3 files
    python jobs/batch/wasde_bronze_scanned_task.py --limit 3

    # Full run
    python jobs/batch/wasde_bronze_scanned_task.py \\
        --bucket leviathan-dev-shahem-001 --aws-region us-east-1

    # Force re-process all
    python jobs/batch/wasde_bronze_scanned_task.py \\
        --bucket leviathan-dev-shahem-001 --force-overwrite
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import sys
import time
from datetime import datetime, timezone

import boto3
import pypdf

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_wasde_key, parse_hive_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.raw_to_bronze.usda_wasde import parse_wasde_pdf_scanned
from leviathan.transforms.raw_to_text.wasde_scanned import _is_scanned_key

logger = get_logger("wasde_bronze_scanned_task")

_RAW_PREFIX = "raw/production/source=usda_wasde/"
_TMP_PREFIX = "text/tmp/usda_wasde_bronze/"
_RUN_LOG_KEY = "bronze/production/source=usda_wasde/_scanned_run_log.json"

_POLL_INTERVAL_SECONDS = 5
_TEXTRACT_BATCH_SIZE = 100  # AWS soft limit: 100 concurrent async jobs

# Pages to SKIP from the front before sending to Textract.
# Pages 0–7 are narrative (already in text/ layer); page 8 onwards are S/D tables.
_SKIP_NARRATIVE_PAGES = 8


# ---------------------------------------------------------------------------
# PDF page stripping
# ---------------------------------------------------------------------------

def _strip_narrative_pages(pdf_bytes: bytes) -> bytes:
    """Return a new PDF containing only pages 8+ (0-indexed).

    If the PDF has 8 or fewer pages (unusual for scanned era, but safe to
    handle), return the original bytes unchanged.
    """
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    total = len(reader.pages)
    if total <= _SKIP_NARRATIVE_PAGES:
        return pdf_bytes
    writer = pypdf.PdfWriter()
    for page in reader.pages[_SKIP_NARRATIVE_PAGES:]:
        writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------

def _upload_tmp(s3_client, bucket: str, release_date: str, pdf_bytes: bytes) -> str:
    """Upload truncated PDF to a temp S3 key; return the key."""
    key = f"{_TMP_PREFIX}{release_date}/input.pdf"
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=pdf_bytes,
        ContentType="application/pdf",
    )
    return key


def _delete_tmp(s3_client, bucket: str, tmp_key: str) -> None:
    try:
        s3_client.delete_object(Bucket=bucket, Key=tmp_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to delete temp key %s: %s", tmp_key, exc)


def _key_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001
        return False


def _upload_parquet(s3_client, bucket: str, key: str, df) -> None:
    import pandas as pd  # noqa: PLC0415 (local import to keep boto3 import at top)
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
# Textract poll loop
# ---------------------------------------------------------------------------

def _collect_line_blocks(textract_client, job_id: str) -> list[dict]:
    """Paginate GetDocumentTextDetection; return all LINE blocks."""
    blocks: list[dict] = []
    kwargs: dict = {"JobId": job_id}
    while True:
        resp = textract_client.get_document_text_detection(**kwargs)
        for block in resp.get("Blocks", []):
            if block.get("BlockType") == "LINE":
                blocks.append(block)
        next_token = resp.get("NextToken")
        if not next_token:
            break
        kwargs["NextToken"] = next_token
    return blocks


def _poll_batch(
    textract_client,
    s3_client,
    bucket: str,
    in_flight: dict[str, tuple[str, str, str]],
    dry_run: bool,
) -> tuple[list[dict], int]:
    """Poll all in-flight Textract jobs until every one finishes.

    Args:
        in_flight: ``{job_id: (release_date, raw_key, tmp_key)}``
        dry_run:   If True, parse but do not upload Parquets.

    Returns:
        ``(result_list, error_count)``
    """
    results: list[dict] = []
    errors = 0

    while in_flight:
        time.sleep(_POLL_INTERVAL_SECONDS)
        for job_id in list(in_flight):
            resp = textract_client.get_document_text_detection(JobId=job_id)
            status = resp["JobStatus"]
            if status not in ("SUCCEEDED", "FAILED"):
                continue

            release_date, raw_key, tmp_key = in_flight.pop(job_id)
            bronze_key = bronze_wasde_key(release_date)
            result: dict = {
                "raw_key":      raw_key,
                "release_date": release_date,
                "bronze_key":   bronze_key,
                "rows":         0,
                "status":       "unknown",
                "error":        None,
            }

            if status == "FAILED":
                detail = resp.get("StatusMessage", "no detail")
                logger.error(
                    "Textract FAILED  job=%s  key=%s  detail=%s", job_id, raw_key, detail
                )
                result["status"] = "error"
                result["error"] = f"Textract FAILED: {detail}"
                errors += 1
                _delete_tmp(s3_client, bucket, tmp_key)
                results.append(result)
                continue

            # SUCCEEDED — parse and write
            try:
                blocks = _collect_line_blocks(textract_client, job_id)
                df = parse_wasde_pdf_scanned(blocks, release_date)
                result["rows"] = len(df)

                if not dry_run:
                    _upload_parquet(s3_client, bucket, bronze_key, df)
                    result["status"] = "written"
                else:
                    result["status"] = "dry_run"

                logger.info(
                    "%-8s  rows=%-6d  %s",
                    result["status"],
                    result["rows"],
                    raw_key,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Parse/write failed  key=%s: %s", raw_key, exc)
                result["status"] = "error"
                result["error"] = str(exc)
                errors += 1
            finally:
                _delete_tmp(s3_client, bucket, tmp_key)

            results.append(result)

    return results, errors


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="WASDE scanned PDFs (1973–1994) → bronze/ via Textract"
    )
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        default=False,
        help="Re-process and overwrite existing bronze Parquets.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Run Textract and parse, but do not write Parquets to S3.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process at most N files (0 = no limit; useful for smoke tests).",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=_TEXTRACT_BATCH_SIZE,
        dest="max_concurrent",
        help=f"Max in-flight Textract jobs (default {_TEXTRACT_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=None,
        dest="start_year",
        help="Only process releases from this year onwards (inclusive).",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=None,
        dest="end_year",
        help="Only process releases up to and including this year.",
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
    textract = boto3.client("textract", region_name=aws_region)
    start = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Discover scanned raw keys
    # ------------------------------------------------------------------
    all_keys = list_s3_keys(bucket, _RAW_PREFIX, aws_region=aws_region)
    scanned_keys = sorted(k for k in all_keys if _is_scanned_key(k))

    logger.info(
        "WASDE bronze scanned task  bucket=%s  scanned_keys=%d  force=%s  dry_run=%s  limit=%s",
        bucket,
        len(scanned_keys),
        args.force_overwrite,
        args.dry_run,
        args.limit or "none",
    )

    if not scanned_keys:
        logger.error("No scanned WASDE keys found under %s — aborting", _RAW_PREFIX)
        sys.exit(1)

    # Apply year filter before limit so --limit is a slice of the filtered set
    if args.start_year or args.end_year:
        filtered: list[str] = []
        for k in scanned_keys:
            yr = int(parse_hive_key(k, "release_date")[:4])
            if args.start_year and yr < args.start_year:
                continue
            if args.end_year and yr > args.end_year:
                continue
            filtered.append(k)
        logger.info(
            "Year filter %s–%s: %d → %d keys",
            args.start_year or "*", args.end_year or "*",
            len(scanned_keys), len(filtered),
        )
        scanned_keys = filtered

    if args.limit:
        scanned_keys = scanned_keys[: args.limit]

    # ------------------------------------------------------------------
    # Filter already-done (idempotency)
    # ------------------------------------------------------------------
    pending: list[str] = []
    skipped = 0
    for raw_key in scanned_keys:
        release_date = parse_hive_key(raw_key, "release_date")
        bronze_key = bronze_wasde_key(release_date)
        if not args.force_overwrite and _key_exists(s3, bucket, bronze_key):
            skipped += 1
        else:
            pending.append(raw_key)

    logger.info("To process: %d  |  Already done (skipped): %d", len(pending), skipped)

    # ------------------------------------------------------------------
    # Submit + poll in batches
    # ------------------------------------------------------------------
    all_results: list[dict] = []
    total_errors = 0

    for batch_start in range(0, len(pending), args.max_concurrent):
        batch = pending[batch_start : batch_start + args.max_concurrent]
        in_flight: dict[str, tuple[str, str, str]] = {}

        for raw_key in batch:
            release_date = parse_hive_key(raw_key, "release_date")
            try:
                pdf_bytes = s3_download_with_retry(bucket, raw_key, s3)
                stripped = _strip_narrative_pages(pdf_bytes)
                tmp_key = _upload_tmp(s3, bucket, release_date, stripped)

                resp = textract.start_document_text_detection(
                    DocumentLocation={
                        "S3Object": {"Bucket": bucket, "Name": tmp_key}
                    }
                )
                job_id = resp["JobId"]
                in_flight[job_id] = (release_date, raw_key, tmp_key)
                logger.info("submitted  %s  job=%s", raw_key, job_id)
            except Exception as exc:  # noqa: BLE001
                logger.error("Submit failed  key=%s: %s", raw_key, exc)
                all_results.append({
                    "raw_key":      raw_key,
                    "release_date": parse_hive_key(raw_key, "release_date"),
                    "bronze_key":   bronze_wasde_key(parse_hive_key(raw_key, "release_date")),
                    "rows":         0,
                    "status":       "error",
                    "error":        f"submit: {exc}",
                })
                total_errors += 1

        if in_flight:
            batch_results, batch_errors = _poll_batch(
                textract, s3, bucket, in_flight, args.dry_run
            )
            all_results.extend(batch_results)
            total_errors += batch_errors

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    written  = sum(1 for r in all_results if r["status"] == "written")
    dry_runs = sum(1 for r in all_results if r["status"] == "dry_run")
    errors   = sum(1 for r in all_results if r["status"] == "error")
    total_rows = sum(r["rows"] for r in all_results)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        "Done  written=%d  skipped=%d  dry_run=%d  errors=%d  total_rows=%d  elapsed=%.1fs",
        written, skipped, dry_runs, errors, total_rows, elapsed,
    )

    # ------------------------------------------------------------------
    # Run log
    # ------------------------------------------------------------------
    run_log = {
        "task":          "wasde_bronze_scanned_task",
        "completed_at":  datetime.now(timezone.utc).isoformat(),
        "bucket":        bucket,
        "written":       written,
        "skipped":       skipped,
        "dry_run":       dry_runs,
        "errors":        errors,
        "total_rows":    total_rows,
        "elapsed_seconds": round(elapsed, 2),
        "results":       all_results,
    }

    if not args.dry_run:
        try:
            _upload_json(s3, bucket, _RUN_LOG_KEY, run_log)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not write run log: %s", exc)

    if total_errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
