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

    # Full backfill (idempotent — skips outputs that are present AND not stale against
    # their raw PDF; a re-landed raw rebuilds automatically, see _all_bronze_current)
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

from leviathan.common.config import get_required_env, load_env
from leviathan.common.ingest_fence import bronze_is_current
from leviathan.common.logging import get_logger
from leviathan.common.unica_bulletins import corrected_season, relabel_reason
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


def _all_bronze_current(
    s3_client,
    bucket: str,
    raw_key: str,
    harvest_year: str,
    idm: str,
    expected_tables: list[str],
) -> bool:
    """True only when every expected bronze Parquet exists AND is NOT STALE against *raw_key*.

    D-LD Track U -- the skip predicate is CONTENT-AWARE, never bare existence.

    WHY THE SMALLER CHANGE IS THE RIGHT ONE.  The alternative on the table was a
    ``--force-reprocess <window>`` flag: an operator names the backfill window and bronze
    rebuilds everything inside it.  That is strictly worse here.  It needs a human to know the
    window and to remember to pass it; it rebuilds untouched bulletins along with the repaired
    ones; and, decisively, it leaves the DEFECT in place -- the next re-landed PDF outside
    whatever window someone typed is skipped on existence exactly as before, so the silent no-op
    survives its own fix.  The staleness fence needs no operator, no window and no memory: a
    bulletin whose raw bytes were re-landed by the wayback backfill has a newer LastModified than
    its bronze and rebuilds automatically, while a bulletin nobody touched still skips.

    It is also not new machinery: ``leviathan.common.ingest_fence.bronze_is_current`` is the
    shared fence D-SG G2-1 already installed on the unica ANNUAL leg (``jobs/batch/unica_task.py``
    :67), on fgis and on pink_sheet.  The biweekly leg was the one member of the family still
    reading bare existence.  The fence fails toward REBUILDING on any uncertainty -- an
    unreadable mtime rebuilds rather than skips -- which is the correct direction for a leg whose
    documented failure mode is "green while landing nothing".
    """
    for table_name in expected_tables:
        key = bronze_unica_biweekly_key(harvest_year, idm, table_name)
        if not bronze_is_current(s3_client, bucket, raw_key, key):
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

    # QUARANTINE RELABEL (D-SG G2-1(a-iii); full story in leviathan.common.unica_bulletins).
    # The hive key is a LABEL, not evidence.  idm=32820684 was published 2026/04 -- the first
    # fortnight of season 2026/2027 -- but its raw object was written under
    # harvest_year=2025_2026 by the loop-year-beats-evidence bug, and MOVING that object is
    # owner decision D22, not an ingest-code decision.  So the object stays where it is and the
    # correction is applied on READ, here, before the harvest_year reaches either the skip
    # predicate or the bronze key.  Without it, silver resolves the bulletin's "DD/04" fortnight
    # labels against 2025_2026 and dates April-2026 readings to April 2025 -- a 2026/2027
    # bulletin folded into the 2025/2026 season.  The fetch layer applies the identical map to
    # manifest rows (fetch_unica_biweekly._apply_season_relabels); one correction, both layers.
    note = relabel_reason(idm, harvest_year)
    if note:
        logger.warning("%s  raw_key=%s", note, raw_key)
        harvest_year = corrected_season(idm, harvest_year) or harvest_year

    # Skip check: content-aware -- every output table must exist AND be no older than the raw
    # PDF behind it.  Bare existence was the defect (see _all_bronze_current).
    if not force_overwrite and _all_bronze_current(
        s3, bucket, raw_key, harvest_year, idm, _OUTPUT_TABLES
    ):
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

    # Optional harvest-year filter -- QUARANTINE-AWARE.  A raw key is a LABEL: idm=32820684 is a
    # 2026/2027 bulletin whose object sits under harvest_year=2025_2026 (owner decision D22 keeps
    # it there).  Filtering on the literal key text would silently drop it from a
    # "--harvest-year 2026_2027" backfill -- the same class of trap the relabel exists to close --
    # so the filter matches the CORRECTED season as well as the recorded one.
    if args.harvest_year:
        hy = args.harvest_year.replace("/", "_")

        def _in_target_season(key: str) -> bool:
            recorded = parse_hive_key(key, "harvest_year")
            idm = parse_hive_key(key, "idm")
            return hy in {recorded, corrected_season(idm, recorded)}

        raw_keys = [k for k in raw_keys if _in_target_season(k)]
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
            s3 = get_thread_local_s3_client(aws_region)
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
