"""World Bank Pink Sheet ARCHIVE raw -> bronze Batch task (the backfill's bronze half).

``jobs/batch/pink_sheet_task.py`` with the ARCHIVE prefixes.  Same 36-column extractor, same
``bronze_is_current`` staleness rule, same worker pool.  It is NOT in the DAG: it runs on demand,
after a harvest.

S3 key structure
----------------
  Raw:    raw/production/source=world_bank_pink_sheet_archive/
              release={YYYYMmm}/{filename}.xlsx
  Bronze: bronze/production/source=world_bank_pink_sheet_archive/
              release={YYYYMmm}/part-000.parquet

WHY A SEPARATE SOURCE PREFIX
----------------------------
``jobs/batch/pink_sheet_task.py`` relists exactly
``raw/production/source=world_bank_pink_sheet/`` and ``jobs/batch/pink_sheet_silver_task.py``
exactly ``bronze/production/source=world_bank_pink_sheet/``.  Neither prefix is parameterized and
neither job takes a prefix argument, so a BACKFILLED vintage is unreachable from the scheduled
chain -- and therefore from the served latest-only table -- BY CONSTRUCTION rather than by a runtime
gate the 8th-of-month cron would have to remember to pass.  The trailing slash is what makes the
disjointness true (``source=world_bank_pink_sheet/`` is not a prefix of
``source=world_bank_pink_sheet_archive/``), and
``tests/unit/test_pink_sheet_prefix_fence.py`` pins exactly that.

THE SERVED-SET CENSUS (A REPORT, NEVER A RUNTIME REFUSAL)
---------------------------------------------------------
An older vintage can carry a governed ``(date, series_name)`` key that NO newer release carries --
a series the World Bank later dropped or a month it later blanked.  If such an object ever reached
the SCHEDULED bronze, the served latest-only table would gain a cell it currently holds NULL: a
widening of a shape the served contract fixes.  Under the prefix fence it cannot reach it, so this
job COUNTS the widening and reports it.  Whether a widening vintage should ever be promoted into the
served prefix is an OWNER DECISION with a visible diff, never a side effect of a backfill.

MEASURED before the fence existed: ZERO governed extra keys across all five older modern vintages
(28,860 / 29,304 / 29,452 / 29,526 / 29,563 rows).  Phase 0 is provably served-set-inert twice over.
The pre-2021 era is where the census earns its keep.

Usage
-----
    python jobs/batch/pink_sheet_archive_task.py [--bucket B] [--aws-region R] [--force-overwrite]
    python jobs/batch/pink_sheet_archive_task.py --census-only    # bronze untouched; the
                                                                 # census REPORT still lands
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd
from leviathan.common.config import get_required_env, load_env
from leviathan.common.ingest_fence import bronze_is_current
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_pink_sheet_archive_key, parse_hive_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.raw_to_bronze.world_bank_pink_sheet import extract_pink_sheet

logger = get_logger("pink_sheet_archive_task")

_RAW_PREFIX = "raw/production/source=world_bank_pink_sheet_archive/"
_BRONZE_PREFIX = "bronze/production/source=world_bank_pink_sheet_archive/"
# The SCHEDULED bronze prefix is read ONLY as the census's comparison set; nothing is ever written
# under it from this job.
_SCHEDULED_BRONZE_PREFIX = "bronze/production/source=world_bank_pink_sheet/"
_CENSUS_KEY = "bronze/production/source=world_bank_pink_sheet_archive/_served_set_census.json"
_WORKERS = 6


def _process(
    raw_key: str,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
) -> tuple[str, str]:
    s3 = get_thread_local_s3_client(aws_region)
    release_ym = parse_hive_key(raw_key, "release")
    if not release_ym:
        logger.warning("Could not parse release from key: %s", raw_key)
        return "error", raw_key

    b_key = bronze_pink_sheet_archive_key(release_ym)

    # D-SG G2-1: skip only when bronze is NOT STALE, never on bare existence -- the same rule the
    # scheduled task carries, for the same reason (a re-downloaded release into the same key with
    # bronze skipping on existence exits 0 having landed nothing).
    if not force_overwrite and bronze_is_current(s3, bucket, raw_key, b_key):
        return "skipped", raw_key

    try:
        raw_bytes = s3_download_with_retry(bucket, raw_key, s3)
    except Exception as exc:  # noqa: BLE001
        logger.error("S3 download failed  key=%s: %s", raw_key, exc)
        return "error", raw_key

    try:
        df = extract_pink_sheet(raw_bytes, release_ym)
    except Exception as exc:  # noqa: BLE001
        # A NARROW ERA IS A COUNTED REFUSAL, NEVER A LOOSENED GATE. extract_pink_sheet raises when a
        # required governed series is missing/ambiguous/double-claimed; relaxing _REQUIRED_SERIES to
        # make an old vintage pass would reopen the narrowed-table class SILVER-F023/F063 closed and
        # publish a silently narrowed vintage every downstream gate reads as complete.
        logger.error("Pink Sheet transform failed (extract_narrow?)  key=%s: %s", raw_key, exc)
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
        logger.info("archive bronze written  %s", b_key)
        return "written", raw_key
    except Exception as exc:  # noqa: BLE001
        logger.error("Parquet write failed  key=%s: %s", raw_key, exc)
        return "error", raw_key


def _read_bronze(s3, bucket: str, key: str) -> pd.DataFrame:
    resp = s3.get_object(Bucket=bucket, Key=key)
    return pd.read_parquet(io.BytesIO(resp["Body"].read()))


def served_set_census(
    archive_frames: dict[str, pd.DataFrame],
    scheduled_frames: dict[str, pd.DataFrame],
) -> dict:
    """For every archived release R, the governed keys R carries that NO STRICTLY-NEWER scheduled
    release carries.

    Pure (no S3, no clock), so it is unit-testable on frames.  ``release_ym`` is fixed-width
    ``'YYYYMmm'``, so a lexicographic compare IS a chronological one.

    Returns a record with, per release: the newer scheduled releases it was compared against, the
    count of extra governed keys, and for each extra ``series_name`` the month RANGE it spans (a
    range names the finding; a bare count does not).
    """
    report: dict = {"releases": [], "total_extra_keys": 0,
                    "scheduled_releases": sorted(scheduled_frames)}
    for release in sorted(archive_frames):
        newer = sorted(r for r in scheduled_frames if r > release)
        covered: set[tuple] = set()
        for r in newer:
            frame = scheduled_frames[r]
            covered |= set(zip(frame["date"].astype(str), frame["series_name"].astype(str)))
        mine_frame = archive_frames[release]
        mine = set(zip(mine_frame["date"].astype(str), mine_frame["series_name"].astype(str)))
        extra = sorted(mine - covered) if newer else []
        by_series: dict[str, list[str]] = {}
        for date_s, series in extra:
            by_series.setdefault(series, []).append(date_s)
        entry = {
            "release_ym": release,
            "compared_against_newer_scheduled": newer,
            "governed_keys_in_release": len(mine),
            "extra_governed_keys": len(extra),
            "extras_by_series": {s: {"n": len(v), "first": min(v), "last": max(v)}
                                 for s, v in sorted(by_series.items())},
        }
        if not newer:
            # ABSENT IS NEVER ZERO: a release with no strictly-newer scheduled release has an EMPTY
            # comparison set, so "0 extras" would be an unmeasured claim, not a finding.
            entry["declined"] = ("no strictly-newer scheduled release to compare against -- "
                                 "the widening question is UNMEASURED for this vintage, not answered")
        report["releases"].append(entry)
        report["total_extra_keys"] += len(extra)
    return report


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )

    load_env()

    parser = argparse.ArgumentParser(
        description="World Bank Pink Sheet ARCHIVE raw -> bronze (+ served-set census)")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--census-only", action="store_true", dest="census_only",
                        help="Emit the served-set census over the bronze already landed. No BRONZE "
                             "object is written; the census report itself still lands under the "
                             "archive bronze prefix (that is the deliverable).")
    parser.add_argument("--no-census", action="store_true", dest="no_census",
                        help="Skip the served-set census (bronze only).")
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    written = skipped = errors = 0
    start = datetime.now(timezone.utc)

    if not args.census_only:
        raw_keys = list_s3_keys(bucket, _RAW_PREFIX, aws_region=aws_region)
        raw_keys = [k for k in raw_keys if k.endswith((".xlsx", ".xls"))]
        raw_keys.sort()
        logger.info(
            "Pink Sheet ARCHIVE task  bucket=%s  raw_keys=%d  force=%s",
            bucket, len(raw_keys), args.force_overwrite,
        )
        if args.limit:
            raw_keys = raw_keys[: args.limit]

        with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
            futures = {
                pool.submit(_process, key, bucket, aws_region, args.force_overwrite): key
                for key in raw_keys
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

    if not args.no_census:
        s3 = get_thread_local_s3_client(aws_region)
        archive_frames: dict[str, pd.DataFrame] = {}
        for key in sorted(list_s3_keys(bucket, _BRONZE_PREFIX, suffix=".parquet",
                                       aws_region=aws_region)):
            release = parse_hive_key(key, "release")
            if release:
                archive_frames[release] = _read_bronze(s3, bucket, key)
        scheduled_frames: dict[str, pd.DataFrame] = {}
        for key in sorted(list_s3_keys(bucket, _SCHEDULED_BRONZE_PREFIX, suffix=".parquet",
                                       aws_region=aws_region)):
            release = parse_hive_key(key, "release")
            if release:
                scheduled_frames[release] = _read_bronze(s3, bucket, key)

        census = served_set_census(archive_frames, scheduled_frames)
        census["run_date"] = datetime.now(timezone.utc).date().isoformat()
        logger.info("served-set census: archive_releases=%d scheduled_releases=%d "
                    "total_extra_governed_keys=%d",
                    len(archive_frames), len(scheduled_frames), census["total_extra_keys"])
        for entry in census["releases"]:
            logger.info("  %s: %d governed keys, %d absent from every newer scheduled release%s",
                        entry["release_ym"], entry["governed_keys_in_release"],
                        entry["extra_governed_keys"],
                        " [" + entry["declined"] + "]" if "declined" in entry else "")
        # The census lands under the ARCHIVE bronze prefix -- a report about the backfill, stored
        # with the backfill, unreachable from the served chain like everything else under this root.
        s3.put_object(Bucket=bucket, Key=_CENSUS_KEY,
                      Body=json.dumps(census, indent=2).encode(),
                      ContentType="application/json")
        logger.info("census written -> s3://%s/%s", bucket, _CENSUS_KEY)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        "Done  written=%d  skipped=%d  errors=%d  elapsed=%.1fs",
        written, skipped, errors, elapsed,
    )

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
