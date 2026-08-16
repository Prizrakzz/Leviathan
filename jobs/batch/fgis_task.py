"""USDA FGIS Export Inspections raw → bronze Batch task.

Processes all per-year CSV files from S3 raw/ and writes one bronze Parquet
per calendar year.

Key selection strategy
----------------------
For each calendar year, the most recent raw key is used:
  - If a weekly snapshot exists (``year={y}/as_of={YYYYMMDD}/``), the
    most recent as_of date wins.
  - Historical backfill keys (``backfill/``) are used when no weekly
    snapshot exists for that year.

This ensures that historical years use the static backfill file (never
revised once a CY closes) while the current year always uses the freshest
weekly snapshot.

S3 key structure
----------------
  Raw (backfill):  raw/production/source=usda_fgis_export_inspections/
                       backfill/CY{year}.csv
  Raw (weekly):    raw/production/source=usda_fgis_export_inspections/
                       year={y}/as_of={YYYYMMDD}/CY{year}.csv
  Bronze:          bronze/production/source=usda_fgis_export_inspections/
                       year={year}/part-000.parquet

Usage
-----
    python jobs/batch/fgis_task.py [--bucket B] [--aws-region R] [--force-overwrite]

Smoke test:
    python jobs/batch/fgis_task.py --limit 2
"""
from __future__ import annotations

import argparse
import io
import logging
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from leviathan.common.config import get_required_env, load_env
from leviathan.common.ingest_fence import bronze_is_current
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_fgis_key, parse_hive_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.raw_to_bronze.usda_fgis import extract_fgis

logger = get_logger("fgis_task")

_RAW_PREFIX = "raw/production/source=usda_fgis_export_inspections/"
_WORKERS = 8


def _year_from_key(raw_key: str) -> int | None:
    """Extract calendar year from a FGIS CSV key."""
    basename = raw_key.rsplit("/", 1)[-1]  # e.g. CY2025.csv
    m = re.match(r"CY(\d{4})\.csv$", basename, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _select_best_keys(raw_keys: list[str]) -> dict[int, str]:
    """For each calendar year, pick the best raw key.

    Priority: most recent weekly as_of date > backfill (static).
    """
    # year → list of (sort_key, raw_key)
    by_year: dict[int, list[tuple[str, str]]] = defaultdict(list)

    for key in raw_keys:
        year = _year_from_key(key)
        if year is None:
            continue
        if "backfill/" in key:
            sort_key = "0_backfill"  # lower priority than any weekly date
        else:
            as_of = parse_hive_key(key, "as_of")
            sort_key = f"1_{as_of}" if as_of else "1_unknown"

        by_year[year].append((sort_key, key))

    return {
        year: max(entries, key=lambda t: t[0])[1]
        for year, entries in by_year.items()
    }


def _process(
    year: int,
    raw_key: str,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
    ingest_date: str,
) -> tuple[str, str]:
    """Download one FGIS CSV, transform, and write bronze Parquet.

    Returns:
        ``(status, detail)`` where status is ``"written"``, ``"skipped"``, or ``"error"``.
    """
    s3 = get_thread_local_s3_client(aws_region)
    b_key = bronze_fgis_key(year)

    # D-SG G2-1: skip only when bronze is NOT STALE. Existence alone let four
    # consecutive fresh raw snapshots be selected and discarded while the job
    # exited 0 (fgis bronze year=2026 frozen at 2026-07-17T07:22:53Z against
    # raw as_of=20260723/0730/0806/0813).
    if not force_overwrite and bronze_is_current(s3, bucket, raw_key, b_key):
        return "skipped", raw_key

    try:
        raw_bytes = s3_download_with_retry(bucket, raw_key, s3)
    except Exception as exc:  # noqa: BLE001
        logger.error("S3 download failed  year=%d  key=%s: %s", year, raw_key, exc)
        return "error", raw_key

    try:
        df = extract_fgis(raw_bytes, year, ingest_date)
    except Exception as exc:  # noqa: BLE001
        logger.error("FGIS transform failed  year=%d  key=%s: %s", year, raw_key, exc)
        return "error", raw_key

    try:
        buf = io.BytesIO()
        df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
        s3.put_object(
            Bucket=bucket,
            Key=b_key,
            Body=buf.getvalue(),
            ContentType="application/octet-stream",
        )
        logger.info("bronze written  year=%d  rows=%d  %s", year, len(df), b_key)
        return "written", raw_key
    except Exception as exc:  # noqa: BLE001
        logger.error("Parquet write failed  year=%d: %s", year, exc)
        return "error", raw_key


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )

    load_env()

    parser = argparse.ArgumentParser(description="USDA FGIS raw → bronze")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Cap number of years processed (0 = all)",
    )
    parser.add_argument(
        "--max-raw-age-days",
        type=int,
        default=8,
        dest="max_raw_age_days",
        help=(
            "Advance fence: fail if the newest raw as_of snapshot for the CURRENT calendar "
            "year is older than this (weekly cadence + 1 day of slack). Default 8."
        ),
    )
    parser.add_argument(
        "--no-advance-fence",
        dest="advance_fence",
        action="store_false",
        default=True,
        help="Disable the D-SG G2-1 advance fence (deliberate historical-only reruns only).",
    )
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    raw_keys = list_s3_keys(bucket, _RAW_PREFIX, suffix=".csv", aws_region=aws_region)
    logger.info("Found %d FGIS raw CSV keys", len(raw_keys))

    year_key_map = _select_best_keys(raw_keys)
    years = sorted(year_key_map.keys())
    logger.info(
        "FGIS task  bucket=%s  years=%d (%d–%d)  force=%s",
        bucket, len(years), min(years, default=0), max(years, default=0), args.force_overwrite,
    )

    if args.limit:
        years = years[: args.limit]

    ingest_date = datetime.now(timezone.utc).date().isoformat()
    start = datetime.now(timezone.utc)
    written = skipped = errors = 0
    written_years: set[int] = set()

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {
            pool.submit(
                _process,
                year, year_key_map[year], bucket, aws_region, args.force_overwrite, ingest_date,
            ): year
            for year in years
        }
        for fut in as_completed(futures):
            fut_year = futures[fut]
            try:
                status, _ = fut.result()
            except Exception as exc:  # noqa: BLE001
                logger.error("Unexpected error: %s", exc)
                errors += 1
                continue
            if status == "written":
                written += 1
                written_years.add(fut_year)
            elif status == "skipped":
                skipped += 1
            else:
                errors += 1

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        "Done  written=%d  skipped=%d  errors=%d  elapsed=%.1fs",
        written, skipped, errors, elapsed,
    )

    if errors:
        sys.exit(1)

    # ---- D-SG G2-1(b) ZERO-ADVANCE FENCE -------------------------------------
    # FGIS is a WEEKLY CUMULATIVE source: every Thursday fetch stages a new
    # year={CY}/as_of={YYYYMMDD}/CY{CY}.csv that contains rows the prior one did
    # not, so a healthy fire MUST rebuild the current CY. Between 2026-07-17 and
    # 2026-08-13 four consecutive fires staged fresh raw and rebuilt nothing while
    # exiting 0. Two stateless assertions: (1) the fetch leg is alive, (2) the
    # bronze leg consumed it.
    # --limit is a deliberately partial run (the module's own smoke test), so it
    # cannot assert anything about the current CY: the fence stands down for it.
    if args.advance_fence and not args.limit:
        current_cy = datetime.now(timezone.utc).year
        if current_cy not in year_key_map:
            logger.error(
                "ADVANCE FENCE: no raw CSV for the current calendar year %d under "
                "s3://%s/%s -- the weekly fetch leg is dead.",
                current_cy, bucket, _RAW_PREFIX,
            )
            sys.exit(1)
        current_key = year_key_map[current_cy]
        as_of = parse_hive_key(current_key, "as_of")
        if not as_of:
            logger.error(
                "ADVANCE FENCE: newest raw key for CY%d has no as_of= partition (%s) -- "
                "only the static backfill is present; the weekly fetch never ran.",
                current_cy, current_key,
            )
            sys.exit(1)
        age_days = (
            datetime.now(timezone.utc).date()
            - datetime.strptime(as_of, "%Y%m%d").date()
        ).days
        if age_days > args.max_raw_age_days:
            logger.error(
                "ADVANCE FENCE: newest CY%d raw snapshot as_of=%s is %d days old "
                "(limit %d) -- the weekly FGIS fetch has stopped landing snapshots.",
                current_cy, as_of, age_days, args.max_raw_age_days,
            )
            sys.exit(1)
        # Assert the STATE, not the event: "bronze consumed the newest raw" is true either
        # because this run rebuilt it (written_years) or because a prior run already did
        # (bronze_is_current). Asserting the event alone reds every idempotent re-run --
        # an operator refire, an SFN re-execution, a second fire in the same week -- and a
        # <family>-sched-* FAILED execution voids the G5 streak on a routine action.
        if current_cy not in written_years and not bronze_is_current(
            get_thread_local_s3_client(aws_region), bucket, current_key,
            bronze_fgis_key(current_cy),
        ):
            logger.error(
                "ADVANCE FENCE: CY%d bronze is OLDER than raw as_of=%s (%d days old) and was "
                "NOT rebuilt this run (written=%d skipped=%d). A fresh cumulative snapshot "
                "was selected and discarded -- the D-SG G2-1 silent no-op.",
                current_cy, as_of, age_days, written, skipped,
            )
            sys.exit(1)
        logger.info(
            "ADVANCE FENCE OK: CY%d bronze current against as_of=%s (%d days old; rebuilt "
            "this run: %s).",
            current_cy, as_of, age_days, current_cy in written_years,
        )


if __name__ == "__main__":
    main()
