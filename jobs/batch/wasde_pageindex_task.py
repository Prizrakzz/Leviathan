"""Batch entrypoint: build the scanned-WASDE per-page index (6.5 click-to-page, W1b).

Writes an immutable ``pages.json`` sidecar next to each scanned WASDE
``document.json`` so the click-to-page resolver can localise a cited snippet to
a real 1-indexed PDF page for OCR / Textract documents (which have no per-page
signal in ``document.json``).  The sidecar schema is
``{page_count, pages: [{page, text}]}`` (see
:func:`leviathan.transforms.raw_to_text.pageindex.build_pages_json`).

Discriminator (which documents form the scanned set)
----------------------------------------------------
The scanned set is identified by the SAME rule the shipped extraction task uses,
:func:`leviathan.transforms.raw_to_text.wasde_scanned._is_scanned_key`: a raw
key ending in ``.pdf`` whose ``release_date`` year is < 1999 (the 1973-1998
scanned era; 1995-1999 releases were published as ``.txt`` and 2000+ as digital
PDFs).  This is the only discriminator the codebase actually supports for the
scanned set -- the alternative "``extraction_method == 'textract'`` from the
``text/`` listing" would require a second-hop read of every ``document.json`` and
buys nothing, because the raw ``.pdf`` + ``year < 1999`` predicate already
selects exactly the Textract-extracted releases.  The shipped
``wasde_scanned_task`` docstring cites ~251 reports for this same set; the
authoritative count is whatever ``--dry-run`` reports from the live listing (the
plan flagged a 251-vs-310-vs-312 ambiguity that this task's dry-run resolves
before any spend).

Cost / safety model
-------------------
* ``--dry-run`` is the DEFAULT.  It enumerates the scanned set, subtracts
  sidecars that already exist (idempotent skip), estimates billable pages, and
  prints the cost.  It submits NOTHING to Textract and creates no Textract
  client.
* Textract bills DetectDocumentText at ~$1.50 / 1000 pages.  Each PDF is
  truncated to at most ``_MAX_NARRATIVE_PAGES`` (8) pages before submission --
  exactly as the shipped scanned task does -- so billable pages per document are
  ``min(actual_pages, 8) <= 8``.  The dry-run therefore uses 8 pages/doc as a
  guaranteed UPPER BOUND on cost.
* ``--apply`` is the explicit gate that actually calls Textract.  D3: the
  ``batch_job_role`` has NO Textract permission, so ``--apply`` must be run under
  LOCAL user credentials (like the original scanned backfill); the task prints
  this before doing anything paid.

Run (safe, default):
    python jobs/batch/wasde_pageindex_task.py            # dry-run, submits nothing
    python jobs/batch/wasde_pageindex_task.py --dry-run  # explicit, identical

Run (paid, local creds only):
    python jobs/batch/wasde_pageindex_task.py --apply
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from leviathan.storage.paths import parse_hive_key, text_wasde_key
from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys
from leviathan.transforms.raw_to_text.pageindex import build_pages_json, sidecar_key
from leviathan.transforms.raw_to_text.wasde_scanned import (
    _MAX_NARRATIVE_PAGES,
    _is_scanned_key,
    _truncate_pdf,
)
from leviathan.transforms.raw_to_text.writer import document_exists

logger = logging.getLogger("wasde_pageindex_task")

_RAW_PREFIX = "raw/production/source=usda_wasde/"
_TMP_PREFIX = "text/tmp/usda_wasde/pageindex/"
_POLL_INTERVAL_SECONDS = 5
_TEXTRACT_BATCH_SIZE = 100  # Textract soft limit: 100 concurrent async jobs
_TEXTRACT_PRICE_PER_1K_PAGES = 1.5  # USD, DetectDocumentText first 1M pages/month


# ---------------------------------------------------------------------------
# Pure helpers (hermetically testable, no I/O)
# ---------------------------------------------------------------------------

def _sidecar_for_raw_key(raw_key: str) -> str:
    """Map a raw scanned ``.pdf`` key to its ``pages.json`` sidecar key.

    Chains the two shipped derivations: ``raw_key`` -> ``release_date`` ->
    ``text_wasde_key`` (the ``document.json`` key) ->
    :func:`~leviathan.transforms.raw_to_text.pageindex.sidecar_key`.
    """
    release_date = parse_hive_key(raw_key, "release_date")
    return sidecar_key(text_wasde_key(release_date))


def estimate_cost(
    n_docs: int,
    page_cap: int = _MAX_NARRATIVE_PAGES,
    price_per_1k: float = _TEXTRACT_PRICE_PER_1K_PAGES,
) -> Tuple[int, float]:
    """Return ``(billable_pages_upper_bound, cost_usd_upper_bound)``.

    Each document is truncated to ``page_cap`` pages before Textract, so
    ``page_cap`` per document is the worst case; the true cost is <= this.

    Args:
        n_docs: Number of documents that would be submitted (pending count).
        page_cap: Max pages billed per document (Textract truncation cap).
        price_per_1k: USD per 1000 pages.

    Returns:
        ``(total_pages, cost_usd)`` -- both upper bounds.
    """
    total_pages = n_docs * page_cap
    cost_usd = total_pages * price_per_1k / 1000.0
    return total_pages, cost_usd


# ---------------------------------------------------------------------------
# Discovery (S3 I/O, but driven entirely by injectable / patchable helpers)
# ---------------------------------------------------------------------------

def discover_pending(
    bucket: str,
    aws_region: str = "us-east-1",
    s3_client: Optional[object] = None,
) -> Tuple[List[str], List[str], int]:
    """Enumerate the scanned set and split it into pending vs already-indexed.

    Lists ``raw/production/source=usda_wasde/``, keeps only scanned-era keys
    (:func:`_is_scanned_key`), then for each checks whether its ``pages.json``
    sidecar already exists (idempotent skip).

    Args:
        bucket: S3 bucket holding the raw + text layers.
        aws_region: AWS region for the listing / head-object calls.
        s3_client: Optional pre-built S3 client (injected in tests); a
            thread-local client is created when omitted.

    Returns:
        ``(scanned_keys, pending_keys, skipped_count)`` where ``pending_keys``
        are the scanned keys whose sidecar is missing.
    """
    all_keys = list_s3_keys(bucket, _RAW_PREFIX, aws_region=aws_region)
    scanned = sorted(k for k in all_keys if _is_scanned_key(k))

    client = s3_client if s3_client is not None else get_thread_local_s3_client(aws_region)

    pending: List[str] = []
    skipped = 0
    for raw_key in scanned:
        side_key = _sidecar_for_raw_key(raw_key)
        # document_exists is a generic head_object existence probe (name is
        # historical); it returns True iff the sidecar object is present.
        if document_exists(client, bucket, side_key):
            skipped += 1
        else:
            pending.append(raw_key)

    return scanned, pending, skipped


def run_dry_run(
    bucket: str,
    aws_region: str = "us-east-1",
    s3_client: Optional[object] = None,
) -> Dict[str, object]:
    """Enumerate + estimate + print the cost.  Submits NOTHING to Textract.

    Prints an ASCII-only report to stdout and returns a summary dict for
    programmatic callers / tests.

    Returns:
        ``{"scanned": int, "skipped": int, "pending": int, "pages": int,
        "cost_usd": float}``.
    """
    scanned, pending, skipped = discover_pending(bucket, aws_region, s3_client)
    pages, cost = estimate_cost(len(pending))

    print("[dry-run] scanned-WASDE page index (6.5 W1b) -- submitting NOTHING")
    print(
        "[dry-run] discriminator: _is_scanned_key (raw .pdf, release_date year < 1999)"
    )
    print("[dry-run] scanned docs found : %d" % len(scanned))
    print("[dry-run] sidecars present   : %d (skip-if-exists)" % skipped)
    print("[dry-run] pending (to index) : %d" % len(pending))
    print(
        "[dry-run] page cap per doc   : %d (Textract truncation; billable <= cap)"
        % _MAX_NARRATIVE_PAGES
    )
    print(
        "[dry-run] estimated cost     : %d docs x %d pages x $%.2f/1k = $%.2f (upper bound)"
        % (len(pending), _MAX_NARRATIVE_PAGES, _TEXTRACT_PRICE_PER_1K_PAGES, cost)
    )
    print("[dry-run] to execute: re-run with --apply under LOCAL user creds (D3).")

    return {
        "scanned": len(scanned),
        "skipped": skipped,
        "pending": len(pending),
        "pages": pages,
        "cost_usd": cost,
    }


# ---------------------------------------------------------------------------
# Apply path (PAID -- gated behind --apply, mirrors wasde_scanned async shape)
# ---------------------------------------------------------------------------

def _upload_tmp(s3_client, bucket: str, release_date: str, pdf_bytes: bytes) -> str:
    """Upload truncated PDF bytes to a temp S3 key; return the key."""
    key = "%s%s/input.pdf" % (_TMP_PREFIX, release_date)
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=pdf_bytes,
        ContentType="application/pdf",
    )
    return key


def _delete_tmp(s3_client, bucket: str, tmp_key: str) -> None:
    """Best-effort delete of a temp S3 object (errors logged, not raised)."""
    try:
        s3_client.delete_object(Bucket=bucket, Key=tmp_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to delete temp key %s: %s", tmp_key, exc)


def _write_sidecar(s3_client, bucket: str, key: str, pages_json: Dict[str, object]) -> None:
    """Serialise *pages_json* as compact JSON and write it to S3 at *key*."""
    body = json.dumps(pages_json, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/json",
    )


def _collect_line_blocks(textract_client, job_id: str) -> List[dict]:
    """Paginate GetDocumentTextDetection and return all LINE blocks.

    Mirrors the collection loop in ``wasde_scanned_task``; kept LINE-filtered so
    :func:`build_pages_json` receives the same shape the extractor expects.
    """
    blocks: List[dict] = []
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
    in_flight: Dict[str, Tuple[str, str, str]],
) -> Tuple[int, int]:
    """Poll every job in *in_flight* to completion, writing sidecars on success.

    Args:
        in_flight: Mapping ``{job_id: (release_date, raw_key, tmp_key)}``.

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

            try:
                blocks = _collect_line_blocks(textract_client, job_id)
                pages_json = build_pages_json(blocks)
                side_key = _sidecar_for_raw_key(raw_key)
                _write_sidecar(s3_client, bucket, side_key, pages_json)
                logger.info("written  %s  (%d pages)", side_key, pages_json["page_count"])
                written += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("Build/write failed  key=%s: %s", raw_key, exc)
                errors += 1
            finally:
                _delete_tmp(s3_client, bucket, tmp_key)

    return written, errors


def run_apply(bucket: str, aws_region: str, max_concurrent: int, limit: int) -> int:
    """PAID: re-run Textract over pending scanned docs and write ``pages.json``.

    This is the only code path that constructs a Textract client or spends
    money.  It is reached solely via ``--apply``.  D3: the ``batch_job_role``
    lacks Textract permission, so this must run under LOCAL user credentials.

    Returns:
        Process exit code (0 = clean, 1 = one or more errors).
    """
    # boto3 / Textract are imported lazily so the default dry-run path never
    # needs them and unit tests never touch a real client.
    import boto3

    print("[apply] PAID PATH -- this calls AWS Textract (~$1.5/1k pages).")
    print("[apply] D3: batch_job_role has NO textract permission; run under LOCAL user creds.")

    s3 = get_thread_local_s3_client(aws_region)
    textract = boto3.client("textract", region_name=aws_region)

    scanned, pending, skipped = discover_pending(bucket, aws_region, s3)
    if limit:
        pending = pending[:limit]
    logger.info(
        "scanned=%d  pending=%d  skipped=%d  (limit=%s)",
        len(scanned),
        len(pending),
        skipped,
        limit or "none",
    )

    from leviathan.storage.s3 import s3_download_with_retry

    start = datetime.now(timezone.utc)
    total_written = 0
    total_errors = 0

    for batch_start in range(0, len(pending), max_concurrent):
        batch = pending[batch_start : batch_start + max_concurrent]
        in_flight: Dict[str, Tuple[str, str, str]] = {}  # job_id -> (date, raw_key, tmp_key)

        for raw_key in batch:
            release_date = parse_hive_key(raw_key, "release_date")
            try:
                pdf_bytes = s3_download_with_retry(bucket, raw_key, s3)
                truncated = _truncate_pdf(pdf_bytes, _MAX_NARRATIVE_PAGES)
                tmp_key = _upload_tmp(s3, bucket, release_date, truncated)

                resp = textract.start_document_text_detection(
                    DocumentLocation={"S3Object": {"Bucket": bucket, "Name": tmp_key}}
                )
                job_id = resp["JobId"]
                in_flight[job_id] = (release_date, raw_key, tmp_key)
                logger.info("submitted  %s  job=%s", raw_key, job_id)
            except Exception as exc:  # noqa: BLE001
                logger.error("Submit failed  key=%s: %s", raw_key, exc)
                total_errors += 1

        if in_flight:
            batch_written, batch_errors = _poll_batch(textract, s3, bucket, in_flight)
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
    return 1 if total_errors else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    """Return the argument parser (default action = dry-run)."""
    parser = argparse.ArgumentParser(
        description="Build the scanned-WASDE per-page index (6.5 click-to-page, W1b)."
    )
    parser.add_argument("--bucket", default="leviathan-dev-shahem-001")
    parser.add_argument("--aws-region", default="us-east-1", dest="aws_region")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Enumerate + estimate cost, submit nothing (this is also the default).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="PAID: actually call Textract. Requires LOCAL user creds (D3).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Cap number of docs processed on --apply (0 = no limit).",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=_TEXTRACT_BATCH_SIZE,
        dest="max_concurrent",
        help="Max in-flight Textract jobs on --apply (default 100; AWS soft limit).",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint.  Default behavior is the safe, unpriced dry-run.

    Returns a process exit code so tests can call ``main`` directly.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    args = _build_parser().parse_args(argv)

    if not args.apply:
        run_dry_run(args.bucket, args.aws_region)
        return 0

    return run_apply(args.bucket, args.aws_region, args.max_concurrent, args.limit)


if __name__ == "__main__":
    sys.exit(main())
