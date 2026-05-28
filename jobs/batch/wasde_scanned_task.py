"""AWS Batch entrypoint: WASDE scanned PDFs → text/ layer (Phase 2).

Processes WASDE scanned PDFs (1973–1994, Section F) via AWS Textract async
(``StartDocumentTextDetection``).  Writes one document.json per release to:

    text/source=usda_wasde/release_date={YYYY-MM-DD}/document.json

Phase 1 handled digital PDFs (2000–2026) and TXT files (1995–1999) using
pdfplumber/TXT decode — those are already complete and are skipped here.

Cost mitigation: each PDF is pre-truncated to at most 8 pages using ``pypdf``
before submission to Textract.  Only pages 0–7 contain narrative highlights;
tail pages are supply-use tables redundant with PSD CSV.  This reduces billable
pages by ~40% (~$4 instead of ~$7 for all 251 reports).

Run locally for smoke tests:
    python jobs/batch/wasde_scanned_task.py --limit 3

Full run (~$4):
    python jobs/batch/wasde_scanned_task.py
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone

import boto3

from leviathan.storage.paths import parse_hive_key, text_wasde_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.raw_to_text.wasde_scanned import (
    _MAX_NARRATIVE_PAGES,
    _is_scanned_key,
    _truncate_pdf,
    extract_wasde_scanned,
)
from leviathan.transforms.raw_to_text.writer import document_exists, write_document

logger = logging.getLogger("wasde_scanned_task")

_RAW_PREFIX = "raw/production/source=usda_wasde/"
_TMP_PREFIX = "text/tmp/usda_wasde/"
_POLL_INTERVAL_SECONDS = 5
_TEXTRACT_BATCH_SIZE = 100  # Textract soft limit: 100 concurrent async jobs


def _upload_tmp(s3_client, bucket: str, release_date: str, pdf_bytes: bytes) -> str:
    """Upload truncated PDF bytes to a temp S3 key; return the key."""
    key = f"{_TMP_PREFIX}{release_date}/input.pdf"
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=pdf_bytes,
        ContentType="application/pdf",
    )
    return key


def _delete_tmp(s3_client, bucket: str, tmp_key: str) -> None:
    """Best-effort delete of a temp S3 object (errors are logged, not raised)."""
    try:
        s3_client.delete_object(Bucket=bucket, Key=tmp_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to delete temp key %s: %s", tmp_key, exc)


def _collect_all_blocks(textract_client, job_id: str) -> list[dict]:
    """Paginate through GetDocumentTextDetection and return all LINE blocks."""
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
) -> tuple[int, int]:
    """Poll all jobs in *in_flight* until every one is SUCCEEDED or FAILED.

    Args:
        in_flight: Mapping of ``{job_id: (release_date, raw_key, tmp_key)}``.

    Returns:
        ``(written, errors)`` counts for this batch.
    """
    written = 0
    errors = 0

    while in_flight:
        time.sleep(_POLL_INTERVAL_SECONDS)
        for job_id in list(in_flight):
            resp = textract_client.get_document_text_detection(JobId=job_id)
            status = resp["JobStatus"]
            if status not in ("SUCCEEDED", "FAILED"):
                continue

            release_date, raw_key, tmp_key = in_flight.pop(job_id)

            if status == "FAILED":
                detail = resp.get("StatusMessage", "no detail")
                logger.error("Textract FAILED  job=%s  key=%s  detail=%s", job_id, raw_key, detail)
                errors += 1
                _delete_tmp(s3_client, bucket, tmp_key)
                continue

            # SUCCEEDED — collect all LINE blocks (may be paginated)
            try:
                blocks: list[dict] = []
                kwargs: dict = {"JobId": job_id}
                while True:
                    page_resp = textract_client.get_document_text_detection(**kwargs)
                    for block in page_resp.get("Blocks", []):
                        if block.get("BlockType") == "LINE":
                            blocks.append(block)
                    next_token = page_resp.get("NextToken")
                    if not next_token:
                        break
                    kwargs["NextToken"] = next_token

                doc = extract_wasde_scanned(blocks, raw_key)
                t_key = text_wasde_key(release_date)
                write_document(s3_client, bucket, t_key, doc)
                logger.info("written  %s", t_key)
                written += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("Extract/write failed  key=%s: %s", raw_key, exc)
                errors += 1
            finally:
                _delete_tmp(s3_client, bucket, tmp_key)

    return written, errors


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(description="WASDE scanned → text/ (Phase 2)")
    parser.add_argument("--bucket", default="leviathan-dev-shahem-001")
    parser.add_argument("--aws-region", default="us-east-1", dest="aws_region")
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        help="Re-extract and overwrite existing document.json objects",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Cap number of files processed (0 = no limit; useful for smoke tests)",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=_TEXTRACT_BATCH_SIZE,
        dest="max_concurrent",
        help="Max in-flight Textract jobs at once (default 100; AWS soft limit)",
    )
    args = parser.parse_args()

    logger.info(
        "Starting WASDE scanned text extraction  bucket=%s  force=%s  limit=%s",
        args.bucket,
        args.force_overwrite,
        args.limit or "none",
    )

    s3 = get_thread_local_s3_client(args.aws_region)
    textract = boto3.client("textract", region_name=args.aws_region)

    # ── 1. Discover scanned keys ──────────────────────────────────────────────
    all_keys = list_s3_keys(args.bucket, _RAW_PREFIX, aws_region=args.aws_region)
    scanned_keys = [k for k in all_keys if _is_scanned_key(k)]
    scanned_keys.sort()
    logger.info("Found %d scanned WASDE keys (1973–1994)", len(scanned_keys))

    if args.limit:
        scanned_keys = scanned_keys[: args.limit]

    # ── 2. Filter already-done (idempotency) ─────────────────────────────────
    pending: list[str] = []
    skipped = 0
    for raw_key in scanned_keys:
        release_date = parse_hive_key(raw_key, "release_date")
        if not args.force_overwrite and document_exists(s3, args.bucket, text_wasde_key(release_date)):
            skipped += 1
        else:
            pending.append(raw_key)

    logger.info(
        "To process: %d  |  Already done (skipped): %d",
        len(pending),
        skipped,
    )

    # ── 3. Submit + poll in batches of max_concurrent ─────────────────────────
    start = datetime.now(timezone.utc)
    total_written = 0
    total_errors = 0

    for batch_start in range(0, len(pending), args.max_concurrent):
        batch = pending[batch_start : batch_start + args.max_concurrent]
        in_flight: dict[str, tuple[str, str, str]] = {}  # job_id → (date, raw_key, tmp_key)

        for raw_key in batch:
            release_date = parse_hive_key(raw_key, "release_date")
            try:
                pdf_bytes = s3_download_with_retry(args.bucket, raw_key, s3)
                truncated = _truncate_pdf(pdf_bytes, _MAX_NARRATIVE_PAGES)
                tmp_key = _upload_tmp(s3, args.bucket, release_date, truncated)

                resp = textract.start_document_text_detection(
                    DocumentLocation={
                        "S3Object": {"Bucket": args.bucket, "Name": tmp_key}
                    }
                )
                job_id = resp["JobId"]
                in_flight[job_id] = (release_date, raw_key, tmp_key)
                logger.info("submitted  %s  job=%s", raw_key, job_id)
            except Exception as exc:  # noqa: BLE001
                logger.error("Submit failed  key=%s: %s", raw_key, exc)
                total_errors += 1

        if in_flight:
            batch_written, batch_errors = _poll_batch(textract, s3, args.bucket, in_flight)
            total_written += batch_written
            total_errors += batch_errors

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        "Done  written=%d  skipped=%d  error=%d  elapsed=%.1fs",
        total_written,
        skipped,
        total_errors,
        elapsed,
    )

    if total_errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
