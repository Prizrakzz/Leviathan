"""AWS Batch/local entrypoint: FNC Colombia monthly report PDFs -> text/ layer."""
from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from leviathan.common.config import get_required_env, load_env
from leviathan.storage.paths import parse_hive_key, text_fnc_report_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.raw_to_text.fnc_colombia import extract_fnc_pdf
from leviathan.transforms.raw_to_text.writer import document_exists, write_document

logger = logging.getLogger("fnc_text_task")

_RAW_PREFIX = "raw/production/source=fnc/monthly_reports/"
_DEFAULT_WORKERS = 8


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FNC Colombia monthly PDFs -> text/")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--report-type", default="all", choices=["all", "cifras", "exportaciones"])
    parser.add_argument("--force-overwrite", default="false")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=_DEFAULT_WORKERS)
    args = parser.parse_args()
    args.force_overwrite = _parse_bool(args.force_overwrite)
    args.workers = max(1, args.workers)
    return args


def _select_keys(
    keys: list[str],
    report_type: str = "all",
    limit: int = 0,
) -> list[str]:
    selected = [key for key in keys if key.lower().endswith(".pdf")]
    if report_type != "all":
        selected = [key for key in selected if parse_hive_key(key, "report_type") == report_type]
    selected = sorted(selected)
    if limit:
        selected = selected[:limit]
    return selected


def _process_one(
    raw_key: str,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
) -> tuple[str, str]:
    s3 = get_thread_local_s3_client(aws_region)
    report_type = parse_hive_key(raw_key, "report_type")
    if report_type not in {"cifras", "exportaciones"}:
        return ("error", raw_key)

    raw_bytes = s3_download_with_retry(bucket, raw_key, s3)
    extracted = extract_fnc_pdf(raw_bytes, raw_key, report_type)
    text_key = text_fnc_report_key(
        report_type=report_type,
        publisher=extracted.publisher,
        publication_date=extracted.publication_date,
    )

    if not force_overwrite and document_exists(s3, bucket, text_key):
        return ("skipped", text_key)

    write_document(s3, bucket, text_key, extracted.document)
    return ("written", text_key)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    load_env()
    args = _parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    all_keys = list_s3_keys(bucket, _RAW_PREFIX, suffix=".pdf", aws_region=aws_region)
    work = _select_keys(all_keys, report_type=args.report_type, limit=args.limit)
    logger.info(
        "Starting FNC text extraction keys=%d report_type=%s force=%s workers=%d",
        len(work),
        args.report_type,
        args.force_overwrite,
        args.workers,
    )

    counts = {"written": 0, "skipped": 0, "error": 0}
    started_at = datetime.now(timezone.utc)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                _process_one,
                raw_key=key,
                bucket=bucket,
                aws_region=aws_region,
                force_overwrite=args.force_overwrite,
            ): key
            for key in work
        }
        for future in as_completed(futures):
            raw_key = futures[future]
            try:
                status, text_key = future.result()
            except Exception:
                counts["error"] += 1
                logger.exception("error processing %s", raw_key)
                continue

            counts[status] += 1
            if status == "written":
                logger.info("written %s", text_key)
            elif status == "skipped":
                logger.debug("skipped %s", text_key)
            else:
                logger.error("unsupported key %s", raw_key)

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
    logger.info(
        "Done FNC text extraction written=%d skipped=%d error=%d elapsed=%.1fs",
        counts["written"],
        counts["skipped"],
        counts["error"],
        elapsed,
    )
    if counts["error"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
