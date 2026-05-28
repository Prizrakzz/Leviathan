"""AWS Batch entrypoint: WASDE raw files → text/ layer (Phase 1).

Processes WASDE digital PDFs (2000–2026, Section D) and WASDE TXT files
(1995–1999, Section E).  Writes one document.json per release to:

    text/source=usda_wasde/release_date={YYYY-MM-DD}/document.json

Scanned PDFs (1973–1994, Section F) are skipped here — they require
Textract and are handled in Phase 2.

Run locally for smoke tests:
    python jobs/batch/wasde_text_task.py --era digital --limit 5
    python jobs/batch/wasde_text_task.py --era txt --limit 5

Full run (all 374 non-Textract WASDE files):
    python jobs/batch/wasde_text_task.py --era all
"""
from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from leviathan.storage.paths import parse_hive_key, text_wasde_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.raw_to_text.wasde_digital import extract_wasde_digital
from leviathan.transforms.raw_to_text.wasde_txt import extract_wasde_txt
from leviathan.transforms.raw_to_text.writer import document_exists, write_document

logger = logging.getLogger("wasde_text_task")

_RAW_PREFIX = "raw/production/source=usda_wasde/"
_DIGITAL_YEAR_MIN = 2000
_SCANNED_YEAR_MAX = 1999  # 1973–1994 PDF = scanned; 1995–1999 = TXT
_MAX_WORKERS = 30


def _classify_key(key: str) -> str | None:
    """Return 'digital', 'txt', or None (scanned — skip in Phase 1)."""
    if key.endswith(".txt"):
        return "txt"
    if key.endswith(".pdf"):
        release_date = parse_hive_key(key, "release_date")
        if not release_date:
            return None
        year = int(release_date[:4])
        if year >= _DIGITAL_YEAR_MIN:
            return "digital"
        # year < 2000 with .pdf = scanned era — Phase 2
        return None
    return None


def _process_one(
    raw_key: str,
    era: str,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
) -> tuple[str, str]:
    """Fetch one raw file, extract text, write document.json.

    Returns (status, text_key) where status is 'skipped', 'written', or 'error'.
    """
    release_date = parse_hive_key(raw_key, "release_date")
    text_key = text_wasde_key(release_date)

    s3 = get_thread_local_s3_client(aws_region)

    if not force_overwrite and document_exists(s3, bucket, text_key):
        return ("skipped", text_key)

    raw_bytes = s3_download_with_retry(bucket, raw_key, s3)

    if era == "digital":
        doc = extract_wasde_digital(raw_bytes, raw_key)
    else:
        doc = extract_wasde_txt(raw_bytes, raw_key)

    write_document(s3, bucket, text_key, doc)
    return ("written", text_key)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(description="WASDE raw → text/ (Phase 1)")
    parser.add_argument("--bucket", default="leviathan-dev-shahem-001")
    parser.add_argument("--aws-region", default="us-east-1", dest="aws_region")
    parser.add_argument(
        "--era",
        choices=["digital", "txt", "all"],
        default="all",
        help="Which WASDE era to process (default: all non-Textract)",
    )
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
    args = parser.parse_args()

    logger.info(
        "Starting WASDE text extraction  era=%s  bucket=%s  force=%s",
        args.era,
        args.bucket,
        args.force_overwrite,
    )

    all_keys = list_s3_keys(args.bucket, _RAW_PREFIX, aws_region=args.aws_region)
    logger.info("Found %d raw keys under %s", len(all_keys), _RAW_PREFIX)

    # Filter by era
    work: list[tuple[str, str]] = []
    for key in all_keys:
        era_label = _classify_key(key)
        if era_label is None:
            continue
        if args.era != "all" and era_label != args.era:
            continue
        work.append((key, era_label))

    if args.limit:
        work = work[: args.limit]

    logger.info(
        "Queued %d files to process (era=%s, limit=%s)",
        len(work),
        args.era,
        args.limit or "none",
    )

    counts: dict[str, int] = {"written": 0, "skipped": 0, "error": 0}
    started_at = datetime.now(timezone.utc)

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {
            pool.submit(
                _process_one,
                raw_key=key,
                era=era_label,
                bucket=args.bucket,
                aws_region=args.aws_region,
                force_overwrite=args.force_overwrite,
            ): key
            for key, era_label in work
        }

        for fut in as_completed(futures):
            raw_key = futures[fut]
            try:
                status, text_key = fut.result()
                counts[status] += 1
                if status == "written":
                    logger.info("written  %s", text_key)
                else:
                    logger.debug("skipped  %s", text_key)
            except Exception:
                counts["error"] += 1
                logger.exception("error processing %s", raw_key)

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
    logger.info(
        "Done in %.1fs — written=%d  skipped=%d  error=%d",
        elapsed,
        counts["written"],
        counts["skipped"],
        counts["error"],
    )

    if counts["error"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
