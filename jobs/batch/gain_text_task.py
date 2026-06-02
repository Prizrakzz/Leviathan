"""GAIN PDF → text/ layer Batch task.

Reads raw GAIN report PDFs from S3, extracts narrative text with pdfplumber,
and writes document.json to the text/ layer.  One task invocation per
commodity source prefix.

Run a smoke test (3 files from the smallest prefix):
    python jobs/batch/gain_text_task.py --source usda_gain_cocoa --limit 3

Full run for a single commodity:
    python jobs/batch/gain_text_task.py --source usda_gain_wheat

All 17 commodity prefixes (run each independently or in parallel via Batch):
    usda_gain_cocoa, usda_gain_coffee, usda_gain_coffee_semiannual,
    usda_gain_corn, usda_gain_cotton, usda_gain_cotton_monthly,
    usda_gain_grain_monthly, usda_gain_orange_juice, usda_gain_palm_oil,
    usda_gain_rapeseed, usda_gain_rice, usda_gain_soybean_meal,
    usda_gain_soybean_oil, usda_gain_soybeans, usda_gain_sugar,
    usda_gain_sugar_semiannual, usda_gain_wheat

Expected output pattern:
    text/source={source}/country={iso2}/publication_date={YYYYMMDD}/document.json
"""
from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from leviathan.storage.paths import parse_hive_key, text_gain_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.raw_to_text.gain_pdf import extract_gain_pdf
from leviathan.transforms.raw_to_text.writer import document_exists, write_document

logger = logging.getLogger("gain_text_task")

_WORKERS = 30


# ---------------------------------------------------------------------------
# Per-key processor
# ---------------------------------------------------------------------------

def _process_key(
    raw_key: str,
    source: str,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
) -> tuple[str, str]:
    """Download, extract, and write text for one GAIN PDF.

    Returns:
        A tuple ``(status, raw_key)`` where status is "written", "skipped",
        or "error".
    """
    s3 = get_thread_local_s3_client(aws_region)
    country = parse_hive_key(raw_key, "country")
    pub_date = parse_hive_key(raw_key, "publication_date")
    t_key = text_gain_key(source, country, pub_date)

    if not force_overwrite and document_exists(s3, bucket, t_key):
        return "skipped", raw_key

    try:
        pdf_bytes = s3_download_with_retry(bucket, raw_key, s3)
    except Exception as exc:  # noqa: BLE001
        logger.error("S3 download failed  key=%s: %s", raw_key, exc)
        return "error", raw_key

    try:
        doc = extract_gain_pdf(pdf_bytes, raw_key, source)
        write_document(s3, bucket, t_key, doc)
        logger.info("text written  %s", t_key)
        return "written", raw_key
    except Exception as exc:  # noqa: BLE001
        logger.error("Extraction/write failed  key=%s: %s", raw_key, exc)
        return "error", raw_key


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def _run(
    source: str,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
    limit: int,
) -> tuple[int, int, int]:
    """Process all PDF keys for *source*.

    Returns:
        ``(written, skipped, errors)``
    """
    prefix = f"raw/production/source={source}/"
    all_keys = list_s3_keys(bucket, prefix, suffix=".pdf", aws_region=aws_region)
    all_keys.sort()
    logger.info("Found %d GAIN PDF keys for source=%s", len(all_keys), source)

    if limit:
        all_keys = all_keys[:limit]

    written = skipped = errors = 0

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {
            pool.submit(_process_key, key, source, bucket, aws_region, force_overwrite): key
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

    parser = argparse.ArgumentParser(
        description="GAIN PDF → text/ layer (one invocation per commodity source)"
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Source prefix, e.g. usda_gain_wheat",
    )
    parser.add_argument("--bucket", default="leviathan-dev-shahem-001")
    parser.add_argument("--aws-region", default="us-east-1", dest="aws_region")
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        help="Re-extract and overwrite existing document.json files",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Cap number of files processed (0 = no limit; useful for smoke tests)",
    )
    args = parser.parse_args()

    logger.info(
        "Starting GAIN text extraction  source=%s  bucket=%s  force=%s  limit=%s",
        args.source,
        args.bucket,
        args.force_overwrite,
        args.limit or "none",
    )

    start = datetime.now(timezone.utc)
    written, skipped, errors = _run(
        args.source, args.bucket, args.aws_region, args.force_overwrite, args.limit
    )
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()

    logger.info(
        "Done  written=%d  skipped=%d  errors=%d  elapsed=%.1fs",
        written,
        skipped,
        errors,
        elapsed,
    )

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
