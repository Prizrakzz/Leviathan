"""text_to_graphrag Batch task (Phase 0).

Reads document.json files from the text/ layer, extracts structured entities
(stress events, causal links, forecasts, policy changes, tone) via Claude
Haiku on Amazon Bedrock, and writes four Parquet tables per (source, year,
month) partition to graphrag/ in S3.

Supports two sources so far:
  usda_wasde   — 616 documents
  usda_wap     — 448 documents

Smoke-test run (3 documents from 2021):
    python jobs/batch/text_to_graphrag_task.py \\
        --source usda_wasde --year_from 2021 --year_to 2021 --limit 3

Full run:
    python jobs/batch/text_to_graphrag_task.py --source usda_wasde
    python jobs/batch/text_to_graphrag_task.py --source usda_wap

AWS Batch invocation uses parameter overrides for source, year_from, year_to,
force_overwrite.  The task exits non-zero on any write failure.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import boto3

from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys
from leviathan.transforms.text_to_graphrag.chunker import chunk_document
from leviathan.transforms.text_to_graphrag.extractor import extract_chunk
from leviathan.transforms.text_to_graphrag.schema import ChunkExtractionResult
from leviathan.transforms.text_to_graphrag.writer import partition_exists, write_partition

logger = logging.getLogger("text_to_graphrag_task")

_WORKERS = 20
_TEXT_PREFIX_TPL = "text/source={source}/"


# ---------------------------------------------------------------------------
# Argument parsing (argparse-only; Batch runs as a Python script, not Glue)
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    try:
        from awsglue.utils import getResolvedOptions
        raw = getResolvedOptions(
            sys.argv,
            ["source", "year_from", "year_to", "bucket", "aws_region"],
        )
        ns = argparse.Namespace(**raw)
        ns.year_from = int(ns.year_from)
        ns.year_to = int(ns.year_to)
        ns.force_overwrite = "--force_overwrite" in sys.argv and (
            sys.argv[sys.argv.index("--force_overwrite") + 1].lower() == "true"
        )
        ns.limit = 0
        return ns
    except ImportError:
        pass

    parser = argparse.ArgumentParser(
        description="text/ → graphrag/ Parquet extraction via Bedrock Haiku"
    )
    parser.add_argument("--source", required=True,
                        help="usda_wasde | usda_wap | usda_gain | ...")
    parser.add_argument("--year_from", type=int, default=2000)
    parser.add_argument("--year_to", type=int, default=2030)
    parser.add_argument("--bucket", default="leviathan-dev-shahem-001")
    parser.add_argument("--aws_region", default="us-east-1")
    parser.add_argument("--force_overwrite", default="false")
    parser.add_argument("--limit", type=int, default=0,
                        help="Cap total documents processed (0 = no limit)")
    args = parser.parse_args()
    args.force_overwrite = args.force_overwrite.lower() == "true"
    return args


# ---------------------------------------------------------------------------
# S3 key helpers
# ---------------------------------------------------------------------------

_KEY_YEAR_MONTH_RE = re.compile(
    r"(?:release_month|year)=(?P<year>\d{4})(?:-(?P<month>\d{2}))?",
)


def _parse_year_month(key: str) -> Tuple[int, int] | None:
    """Extract (year, month) from an S3 key in any supported partition format.

    Supported patterns:
      text/source=usda_wasde/release_month=YYYY-MM/document.json
      text/source=usda_wap/release_month=YYYY-MM/document.json
    Returns None if the key doesn't match (e.g. a top-level prefix listing).
    """
    m = _KEY_YEAR_MONTH_RE.search(key)
    if not m:
        return None
    year = int(m.group("year"))
    month_str = m.group("month")
    month = int(month_str) if month_str else 1
    return year, month


# ---------------------------------------------------------------------------
# Per-document processing
# ---------------------------------------------------------------------------

def _process_document(
    doc_key: str,
    bucket: str,
    aws_region: str,
    source: str,
    year: int,
    month: int,
) -> Tuple[str, List[ChunkExtractionResult]]:
    """Download and extract one document.json.

    Returns ("ok", results) on success, ("error", []) on failure.
    """
    s3 = get_thread_local_s3_client(aws_region)
    try:
        body = s3.get_object(Bucket=bucket, Key=doc_key)["Body"].read()
        doc = json.loads(body)
    except Exception as exc:
        logger.error("Failed to download %s: %s", doc_key, exc)
        return "error", []

    # Derive document_date from key: release_month=YYYY-MM → first day of month
    try:
        document_date = f"{year}-{month:02d}-01"
    except Exception:
        document_date = "1970-01-01"

    chunks = chunk_document(doc)
    if not chunks:
        logger.warning("No chunks from %s (empty sections)", doc_key)
        return "ok", []

    results: list[ChunkExtractionResult] = []
    for chunk in chunks:
        result = extract_chunk(
            chunk_text=chunk["text"],
            source=source,
            document_date=document_date,
            section_name=chunk["section_name"],
            doc_key=doc_key,
            chunk_index=chunk["chunk_index"],
        )
        results.append(result)

    return "ok", results


# ---------------------------------------------------------------------------
# Partition-level orchestration
# ---------------------------------------------------------------------------

def _run_partition(
    doc_keys: List[str],
    bucket: str,
    aws_region: str,
    source: str,
    year: int,
    month: int,
    force_overwrite: bool,
) -> Tuple[int, int, int]:
    """Process all documents in one (year, month) partition.

    Returns (written, skipped, errors) at the document level.
    """
    s3 = boto3.client("s3", region_name=aws_region)

    if not force_overwrite and partition_exists(s3, bucket, source, year, month):
        logger.info(
            "Skipping partition source=%s year=%d month=%02d (already exists)",
            source, year, month,
        )
        return 0, len(doc_keys), 0

    all_results: list[ChunkExtractionResult] = []
    ok_count = error_count = 0

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {
            pool.submit(
                _process_document, key, bucket, aws_region, source, year, month
            ): key
            for key in doc_keys
        }
        for fut in as_completed(futures):
            try:
                status, results = fut.result()
            except Exception as exc:
                logger.error("Unexpected error processing document: %s", exc)
                error_count += 1
                continue
            if status == "error":
                error_count += 1
            else:
                ok_count += 1
                all_results.extend(results)

    # Write Parquet for the whole partition (even if empty — maintains schema)
    try:
        write_partition(
            results=all_results,
            s3_client=s3,
            bucket=bucket,
            source=source,
            year=year,
            month=month,
        )
    except Exception as exc:
        logger.error(
            "Failed to write partition source=%s year=%d month=%02d: %s",
            source, year, month, exc,
        )
        return 0, 0, len(doc_keys)

    return ok_count, 0, error_count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )

    args = _parse_args()
    logger.info(
        "Starting text_to_graphrag  source=%s  year_from=%d  year_to=%d  "
        "force=%s  limit=%s  bucket=%s",
        args.source,
        args.year_from,
        args.year_to,
        args.force_overwrite,
        args.limit or "none",
        args.bucket,
    )

    start = datetime.now(timezone.utc)

    # List all document.json keys for this source
    prefix = _TEXT_PREFIX_TPL.format(source=args.source)
    all_keys = [
        k for k in list_s3_keys(args.bucket, prefix, suffix="document.json",
                                 aws_region=args.aws_region)
    ]

    if not all_keys:
        logger.warning("No document.json files found under %s in bucket %s",
                       prefix, args.bucket)
        return

    # Filter by year range and group by (year, month)
    partition_map: Dict[Tuple[int, int], List[str]] = defaultdict(list)
    for key in all_keys:
        ym = _parse_year_month(key)
        if ym is None:
            logger.debug("Could not parse year/month from key %s — skipping", key)
            continue
        year, month = ym
        if args.year_from <= year <= args.year_to:
            partition_map[(year, month)].append(key)

    if args.limit:
        # Cap total documents across all partitions (useful for smoke tests)
        limited_map: Dict[Tuple[int, int], List[str]] = defaultdict(list)
        total = 0
        for ym_key in sorted(partition_map.keys()):
            for doc_key in partition_map[ym_key]:
                if total >= args.limit:
                    break
                limited_map[ym_key].append(doc_key)
                total += 1
            if total >= args.limit:
                break
        partition_map = limited_map

    total_written = total_skipped = total_errors = 0

    for (year, month) in sorted(partition_map.keys()):
        doc_keys = partition_map[(year, month)]
        w, s, e = _run_partition(
            doc_keys=doc_keys,
            bucket=args.bucket,
            aws_region=args.aws_region,
            source=args.source,
            year=year,
            month=month,
            force_overwrite=args.force_overwrite,
        )
        total_written += w
        total_skipped += s
        total_errors += e

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        "Done  docs_written=%d  docs_skipped=%d  errors=%d  elapsed=%.1fs",
        total_written,
        total_skipped,
        total_errors,
        elapsed,
    )

    if total_errors:
        raise RuntimeError(
            f"text_to_graphrag finished with {total_errors} error(s). "
            "Check CloudWatch logs for details."
        )


if __name__ == "__main__":
    main()
