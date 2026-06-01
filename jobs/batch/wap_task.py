"""WAP A+B+C → text/ and bronze/ layers (Phase 3).

Processes USDA FAS World Agricultural Production (WAP) reports from three
source eras and writes:
  - text/source=usda_wap/release_month={YYYY-MM}/document.json  (all eras)
  - bronze/production/source=usda_wap/release_month={YYYY-MM}/table01.parquet
    (A + B only; C has no Table 01)

Source eras handled by --source flag:
  a    FAS portal PDFs (2002-08 → present) — stored in S3 raw/
  b    Archive.org PDFs (1988 → 2002-07)   — stored in same S3 prefix as A
  all  A + B combined (default for PDF path)
  html Wayback HTML (1996–2002)             — TOC in S3; sub-pages fetched live

Run smoke tests (3 files):
    python jobs/batch/wap_task.py --source a --limit 3
    python jobs/batch/wap_task.py --source b --limit 3
    python jobs/batch/wap_task.py --source html --limit 3

Full run (recommended sequence — run all before html so B covers overlap):
    python jobs/batch/wap_task.py --source all
    python jobs/batch/wap_task.py --source html

Expected outputs:
    ~448 files in text/source=usda_wap/
    ~448 files in bronze/production/source=usda_wap/
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests

from leviathan.storage.paths import (
    bronze_wap_key,
    parse_hive_key,
    text_wap_key,
)
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.raw_to_bronze.wap_table01 import (
    extract_table01,
    table01_exists,
    write_table01,
)
from leviathan.transforms.raw_to_text.wap_html import (
    _find_subpage_urls,
    _html_to_text,
    extract_wap_html,
)
from leviathan.transforms.raw_to_text.wap_pdf import extract_wap_pdf
from leviathan.transforms.raw_to_text.writer import document_exists, write_document

logger = logging.getLogger("wap_task")

_RAW_PDF_PREFIX = "raw/production/source=usda_wap/"
_RAW_HTML_PREFIX = "raw/production/source=usda_wap_html/"

# ThreadPoolExecutor sizes: A (FAS portal, fast S3) vs B (archive.org, polite rate)
_WORKERS_A = 30
_WORKERS_B = 6
_WORKERS_HTML = 6

# Politeness delay (seconds) between Wayback Machine HTTP requests.
_WAYBACK_DELAY = 0.5

# HTTP request timeout (seconds) for Wayback sub-page fetches.
_HTTP_TIMEOUT = 30

# Maximum retry attempts for Wayback HTTP requests.
_HTTP_MAX_RETRIES = 3


def _is_era_b(release_month: str) -> bool:
    """Return True for archive.org era (year < 2002)."""
    return int(release_month[:4]) < 2002


def _fetch_wayback_page(url: str, semaphore: threading.Semaphore) -> str:
    """Fetch a Wayback Machine page, respecting the concurrency semaphore.

    Retries up to _HTTP_MAX_RETRIES times on transient errors.  Returns an
    empty string on persistent failure (caller logs warning and skips).
    """
    with semaphore:
        time.sleep(_WAYBACK_DELAY)
        for attempt in range(1, _HTTP_MAX_RETRIES + 1):
            try:
                resp = requests.get(url, timeout=_HTTP_TIMEOUT, headers={"User-Agent": "leviathan-etl/1.0"})
                resp.raise_for_status()
                return resp.text
            except requests.RequestException as exc:
                if attempt == _HTTP_MAX_RETRIES:
                    logger.warning("Wayback fetch failed after %d attempts  url=%s: %s", attempt, url, exc)
                    return ""
                time.sleep(2 ** attempt)
    return ""  # unreachable


# ---------------------------------------------------------------------------
# PDF path (sources A and B)
# ---------------------------------------------------------------------------

def _process_pdf_key(
    raw_key: str,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
) -> tuple[str, str]:
    """Download, extract, and write text + bronze for one WAP PDF.

    Returns:
        A tuple ``(status, detail)`` where status is "written", "skipped",
        or "error".
    """
    s3 = get_thread_local_s3_client(aws_region)
    release_month = parse_hive_key(raw_key, "release_month")
    t_key = text_wap_key(release_month)
    b_key = bronze_wap_key(release_month)

    if not force_overwrite:
        text_done = document_exists(s3, bucket, t_key)
        bronze_done = table01_exists(s3, bucket, b_key)
        if text_done and bronze_done:
            return "skipped", raw_key

    try:
        pdf_bytes = s3_download_with_retry(bucket, raw_key, s3)
    except Exception as exc:  # noqa: BLE001
        logger.error("S3 download failed  key=%s: %s", raw_key, exc)
        return "error", raw_key

    # ── Text extraction ────────────────────────────────────────────────────
    if force_overwrite or not document_exists(s3, bucket, t_key):
        try:
            doc = extract_wap_pdf(pdf_bytes, raw_key, release_month)
            write_document(s3, bucket, t_key, doc)
            logger.info("text written  %s", t_key)
        except Exception as exc:  # noqa: BLE001
            logger.error("Text extraction failed  key=%s: %s", raw_key, exc)
            return "error", raw_key

    # ── Bronze extraction (Table 01) ───────────────────────────────────────
    if force_overwrite or not table01_exists(s3, bucket, b_key):
        df = extract_table01(pdf_bytes, release_month, raw_key)
        if df is not None:
            try:
                write_table01(s3, bucket, b_key, df)
                logger.info("bronze written  %s", b_key)
            except Exception as exc:  # noqa: BLE001
                logger.error("Bronze write failed  key=%s: %s", raw_key, exc)
                # Text was written; count as partial success but not error
        else:
            logger.warning("Table01 None — bronze skipped  key=%s", raw_key)

    return "written", raw_key


def _run_pdf_source(
    bucket: str,
    aws_region: str,
    source: str,
    force_overwrite: bool,
    limit: int,
    release_months: set[str] | None = None,
) -> tuple[int, int, int]:
    """Process all WAP PDF keys for sources a, b, or all.

    Args:
        release_months: If provided, only process keys whose release_month is
            in this set.  Useful for targeted re-runs of specific months.

    Returns:
        ``(written, skipped, errors)``
    """
    all_keys = list_s3_keys(bucket, _RAW_PDF_PREFIX, suffix="production.pdf", aws_region=aws_region)
    all_keys.sort()

    if source == "a":
        keys = [k for k in all_keys if not _is_era_b(parse_hive_key(k, "release_month"))]
    elif source == "b":
        keys = [k for k in all_keys if _is_era_b(parse_hive_key(k, "release_month"))]
    else:  # all
        keys = all_keys

    if release_months is not None:
        keys = [k for k in keys if parse_hive_key(k, "release_month") in release_months]

    logger.info("Found %d WAP PDF keys for source=%s", len(keys), source)

    if limit:
        keys = keys[:limit]

    # Partition into era A and era B for appropriate concurrency
    keys_a = [k for k in keys if not _is_era_b(parse_hive_key(k, "release_month"))]
    keys_b = [k for k in keys if _is_era_b(parse_hive_key(k, "release_month"))]

    written = skipped = errors = 0

    for batch_keys, workers in [(keys_a, _WORKERS_A), (keys_b, _WORKERS_B)]:
        if not batch_keys:
            continue
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_process_pdf_key, key, bucket, aws_region, force_overwrite): key
                for key in batch_keys
            }
            for fut in as_completed(futures):
                try:
                    status, _ = fut.result()
                except Exception as exc:  # noqa: BLE001
                    logger.error("Unexpected error: %s", exc)
                    errors += 1
                    continue
                if status == "written":
                    written += 1
                elif status == "skipped":
                    skipped += 1
                else:
                    errors += 1

    return written, skipped, errors


# ---------------------------------------------------------------------------
# HTML path (source C)
# ---------------------------------------------------------------------------

def _process_html_key(
    raw_key: str,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
    semaphore: threading.Semaphore,
) -> tuple[str, str]:
    """Download TOC from S3, fetch sub-pages from Wayback, write text.

    Returns:
        A tuple ``(status, detail)`` where status is "written", "skipped",
        or "error".
    """
    s3 = get_thread_local_s3_client(aws_region)
    release_month = parse_hive_key(raw_key, "release_month")
    t_key = text_wap_key(release_month)

    if not force_overwrite and document_exists(s3, bucket, t_key):
        # B era already wrote this release_month — skip
        return "skipped", raw_key

    # Download stored TOC HTML from S3
    try:
        toc_bytes = s3_download_with_retry(bucket, raw_key, s3)
        toc_html = toc_bytes.decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        logger.error("S3 download failed  key=%s: %s", raw_key, exc)
        return "error", raw_key

    # Discover sub-page URLs from TOC
    # Construct the approximate Wayback base URL from the raw key metadata
    # (we don't have the original Wayback URL, so we use the TOC content itself)
    base_url = "https://web.archive.org/"
    subpage_urls = _find_subpage_urls(toc_html, base_url)

    # Fetch sub-pages from Wayback Machine
    subpage_texts: list[str] = []
    for url in subpage_urls:
        page_html = _fetch_wayback_page(url, semaphore)
        if page_html:
            subpage_texts.append(_html_to_text(page_html))
        else:
            logger.warning("Sub-page fetch failed  url=%s  key=%s", url, raw_key)

    try:
        doc = extract_wap_html(toc_html, subpage_texts, raw_key, release_month)
        write_document(s3, bucket, t_key, doc)
        logger.info("text written  %s", t_key)
        return "written", raw_key
    except Exception as exc:  # noqa: BLE001
        logger.error("HTML extraction/write failed  key=%s: %s", raw_key, exc)
        return "error", raw_key


def _run_html_source(
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
    limit: int,
) -> tuple[int, int, int]:
    """Process all WAP HTML keys (source C).

    Returns:
        ``(written, skipped, errors)``
    """
    all_keys = list_s3_keys(bucket, _RAW_HTML_PREFIX, suffix="wap.html", aws_region=aws_region)
    all_keys.sort()
    logger.info("Found %d WAP HTML keys", len(all_keys))

    if limit:
        all_keys = all_keys[:limit]

    semaphore = threading.Semaphore(_WORKERS_HTML)
    written = skipped = errors = 0

    with ThreadPoolExecutor(max_workers=_WORKERS_HTML) as pool:
        futures = {
            pool.submit(
                _process_html_key, key, bucket, aws_region, force_overwrite, semaphore
            ): key
            for key in all_keys
        }
        for fut in as_completed(futures):
            try:
                status, _ = fut.result()
            except Exception as exc:  # noqa: BLE001
                logger.error("Unexpected error: %s", exc)
                errors += 1
                continue
            if status == "written":
                written += 1
            elif status == "skipped":
                skipped += 1
            else:
                errors += 1

    return written, skipped, errors


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(description="WAP A+B+C → text/ + bronze/ (Phase 3)")
    parser.add_argument("--bucket", default="leviathan-dev-shahem-001")
    parser.add_argument("--aws-region", default="us-east-1", dest="aws_region")
    parser.add_argument(
        "--source",
        choices=["a", "b", "all", "html"],
        default="all",
        help=(
            "a=FAS portal PDFs (2002+), b=Archive.org PDFs (pre-2002), "
            "all=A+B combined, html=Wayback HTML (1996-2002)"
        ),
    )
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        help="Re-extract and overwrite existing objects",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Cap number of files processed (0 = no limit; useful for smoke tests)",
    )
    parser.add_argument(
        "--release-months",
        nargs="+",
        default=None,
        dest="release_months",
        metavar="YYYY-MM",
        help="Process only these release months (space-separated, e.g. 2015-02 2015-03).",
    )
    args = parser.parse_args()

    logger.info(
        "Starting WAP extraction  bucket=%s  source=%s  force=%s  limit=%s  months=%s",
        args.bucket,
        args.source,
        args.force_overwrite,
        args.limit or "none",
        ",".join(args.release_months) if args.release_months else "all",
    )

    start = datetime.now(timezone.utc)

    if args.source in ("a", "b", "all"):
        written, skipped, errors = _run_pdf_source(
            args.bucket, args.aws_region, args.source, args.force_overwrite, args.limit,
            release_months=set(args.release_months) if args.release_months else None,
        )
    else:  # html
        written, skipped, errors = _run_html_source(
            args.bucket, args.aws_region, args.force_overwrite, args.limit
        )

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        "Done  written=%d  skipped=%d  error=%d  elapsed=%.1fs",
        written,
        skipped,
        errors,
        elapsed,
    )

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
