"""AWS Batch entrypoint: CFTC COT disagg_futures TXT → bronze Parquets.

Enumerates BOTH on-disk layouts of the futures-only disaggregated COT report
and writes one Parquet per source-file label to:

    bronze/production/source=cftc_cot/year={label}/part-000.parquet

Two raw layouts feed this task
------------------------------
  * backfill (annual / bulk)  — the historical ZIP-extracted files
        raw/production/source=cftc_cot/disagg_futures/backfill/fut_disagg_{label}.txt
    label is ``2006_2016`` (bulk) or a single year ``YYYY``. Each annual file
    is COMPLETE for its year; the bulk file is complete for 2006–2016.
  * weekly (live newcot snapshots) — the Friday point-in-time files
        raw/production/source=cftc_cot/disagg_futures/year={YYYY}/as_of={YYYYMMDD}/fut_disagg_{YYYYMMDD}.txt
    label is the as_of stamp ``YYYYMMDD``; each file carries ONE report_date.

Before this fix the task enumerated ONLY the backfill/ prefix, so the weekly
snapshots that the ``fetch_cftc_cot.py --mode weekly`` leg lands every Friday
were ORPHANED — bronze stalled at the last annual file's report_date while raw
kept advancing. This task now also walks the weekly year=/as_of= tree.

Deduplication precedence (backfill WINS)
----------------------------------------
The backfill annual/bulk files and the weekly snapshots overlap: an annual file
for year Y already contains every weekly report in Y. To avoid double-ingesting
those report_dates we apply a deterministic **report_date** precedence:

    backfill (annual/bulk) > weekly snapshot

i.e. any weekly row whose ``report_date`` is already covered by a backfill file
is dropped at bronze time; only report_dates NOT present in any backfill file
(the genuinely-newer weeks — typically the current partial year) are ingested
from the weekly tree. Backfill report_dates are harvested from the backfill raw
(or, when its bronze already exists and is not being rewritten, from that bronze
object) so the dedup holds even on incremental re-runs. The silver transform's
own (report_date, slug) drop_duplicates(keep="last") is a second safety net.

disagg_combined is enumerated but NOT ingested
----------------------------------------------
The combined (futures+options) weekly tree is enumerated purely for coverage
accounting (logged), never parsed here: ``silver_cot`` is a futures-only table
(see ``raw_to_bronze.cftc_cot``), and the parse path drops every ``Combined``
row. Only ``fut_disagg_*`` files are ever handed to :func:`parse_cot_txt`.

Usage
-----
    python jobs/batch/cftc_cot_bronze_task.py
    python jobs/batch/cftc_cot_bronze_task.py --force-overwrite
    python jobs/batch/cftc_cot_bronze_task.py --dry-run
"""
from __future__ import annotations

import argparse
import io
import logging
import re
import sys
from datetime import datetime, timezone

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_cot_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.raw_to_bronze.cftc_cot import parse_cot_txt

logger = get_logger("cftc_cot_bronze_task")

# Historical annual/bulk ZIP-extracted files (the ONLY prefix the task walked
# before the weekly-orphan fix).
_BACKFILL_PREFIX = "raw/production/source=cftc_cot/disagg_futures/backfill/"
# Root of the futures-only tree; the weekly year=/as_of= snapshots live directly
# under it (backfill/ is the sibling subtree we exclude by the ``/year=`` filter).
_FUTURES_ROOT = "raw/production/source=cftc_cot/disagg_futures/"
# Combined (futures+options) tree — enumerated for coverage accounting only.
_COMBINED_ROOT = "raw/production/source=cftc_cot/disagg_combined/"
# Weekly (point-in-time) keys carry a ``year=`` Hive partition; backfill keys do not.
_WEEKLY_MARKER = "/year="


def _year_label_from_key(key: str) -> str | None:
    """Extract year label from key like fut_disagg_2024.txt or fut_disagg_2006_2016.txt."""
    fname = key.split("/")[-1]
    m = re.search(r"fut_disagg_(.+)\.txt$", fname)
    return m.group(1) if m else None


def _bronze_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def _write_parquet(s3_client, bucket: str, key: str, df: pd.DataFrame) -> None:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3_client.put_object(
        Bucket=bucket, Key=key, Body=buf.getvalue(),
        ContentType="application/octet-stream",
    )


def _report_dates(df: pd.DataFrame) -> set[str]:
    """The distinct ``report_date`` strings present in a bronze DataFrame."""
    if df.empty or "report_date" not in df.columns:
        return set()
    return set(df["report_date"].astype(str).unique())


def _bronze_report_dates(s3_client, bucket: str, key: str) -> set[str]:
    """Harvest the report_dates from an already-written bronze Parquet.

    Lets an incremental re-run (backfill bronze already present, so its raw is
    NOT re-downloaded/rewritten) still contribute its report_dates to the weekly
    dedup precedence set. Best-effort: a read failure returns an empty set so a
    transient hiccup cannot silently double-ingest -- the weekly rows it would
    have masked are still caught by the silver keep="last" dedup."""
    try:
        raw = s3_download_with_retry(bucket, key, s3_client)
        return _report_dates(pd.read_parquet(io.BytesIO(raw)))
    except Exception:
        logger.warning("could not read bronze for dedup harvest: %s", key)
        return set()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(description="CFTC COT disagg_futures → bronze")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    bucket     = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    s3         = get_thread_local_s3_client(aws_region)

    # Backfill (annual/bulk) keys -- the historical files.
    backfill_keys = sorted(list_s3_keys(bucket, _BACKFILL_PREFIX, suffix=".txt",
                                        aws_region=aws_region))
    # Weekly (point-in-time) futures keys -- everything under the futures root that
    # carries a ``year=`` partition (this excludes the backfill/ subtree).
    weekly_keys = sorted(
        k for k in list_s3_keys(bucket, _FUTURES_ROOT, suffix=".txt", aws_region=aws_region)
        if _WEEKLY_MARKER in k
    )
    # Combined weekly keys -- enumerated for coverage accounting ONLY (never ingested;
    # silver_cot is futures-only and the parse path drops every Combined row).
    combined_weekly_keys = [
        k for k in list_s3_keys(bucket, _COMBINED_ROOT, suffix=".txt", aws_region=aws_region)
        if _WEEKLY_MARKER in k
    ]
    logger.info(
        "Found %d backfill + %d weekly futures TXT files (%d combined-weekly enumerated, "
        "NOT ingested)  force=%s  dry_run=%s",
        len(backfill_keys), len(weekly_keys), len(combined_weekly_keys),
        args.force_overwrite, args.dry_run,
    )

    started_at = datetime.now(timezone.utc)
    written = skipped = errors = deduped = 0
    # report_dates already covered by a backfill file (or an earlier-processed weekly
    # file). Weekly rows whose report_date is in this set are dropped -- backfill wins.
    covered_dates: set[str] = set()

    # --- Pass 1: backfill (annual/bulk) -- unchanged write behaviour; harvest dates ---
    for raw_key in backfill_keys:
        year_label = _year_label_from_key(raw_key)
        if not year_label:
            logger.warning("Could not parse year label from %s", raw_key)
            errors += 1
            continue

        b_key = bronze_cot_key(year_label)

        if not args.force_overwrite and not args.dry_run and _bronze_exists(s3, bucket, b_key):
            # Do not rewrite existing backfill bronze, but still harvest its report_dates
            # so the weekly dedup precedence holds on incremental re-runs.
            covered_dates |= _bronze_report_dates(s3, bucket, b_key)
            logger.debug("skipped (exists)  year=%s", year_label)
            skipped += 1
            continue

        logger.info("Processing backfill year=%s  (%s)", year_label, raw_key.split("/")[-1])
        try:
            raw_bytes = s3_download_with_retry(bucket, raw_key, s3)
        except Exception:
            logger.exception("S3 download failed: %s", raw_key)
            errors += 1
            continue

        try:
            df = parse_cot_txt(raw_bytes, year_label)
        except Exception:
            logger.exception("Parse failed: %s", raw_key)
            errors += 1
            continue

        if df.empty:
            logger.warning("No mapped markets in backfill year=%s — skipping write", year_label)
            errors += 1
            continue

        covered_dates |= _report_dates(df)

        if args.dry_run:
            logger.info("dry-run  backfill year=%s  rows=%d  slugs=%s",
                        year_label, len(df), sorted(df["leviathan_slug"].unique().tolist()))
            written += 1
            continue

        try:
            _write_parquet(s3, bucket, b_key, df)
            logger.info("written  backfill year=%s  rows=%d  %s", year_label, len(df), b_key)
            written += 1
        except Exception:
            logger.exception("Write failed: %s", b_key)
            errors += 1

    # --- Pass 2: weekly snapshots -- dedup against backfill coverage by report_date ---
    for raw_key in weekly_keys:
        as_of_label = _year_label_from_key(raw_key)
        if not as_of_label:
            logger.warning("Could not parse as_of label from %s", raw_key)
            errors += 1
            continue

        b_key = bronze_cot_key(as_of_label)

        if not args.force_overwrite and not args.dry_run and _bronze_exists(s3, bucket, b_key):
            covered_dates |= _bronze_report_dates(s3, bucket, b_key)
            logger.debug("skipped (exists)  as_of=%s", as_of_label)
            skipped += 1
            continue

        logger.info("Processing weekly as_of=%s  (%s)", as_of_label, raw_key.split("/")[-1])
        try:
            raw_bytes = s3_download_with_retry(bucket, raw_key, s3)
        except Exception:
            logger.exception("S3 download failed: %s", raw_key)
            errors += 1
            continue

        try:
            df = parse_cot_txt(raw_bytes, as_of_label)
        except Exception:
            logger.exception("Parse failed: %s", raw_key)
            errors += 1
            continue

        if df.empty:
            # A futures weekly file that maps NO markets is genuinely wrong (every
            # weekly file carries the mapped contracts) -- a real error, not a dedup.
            logger.warning("No mapped markets in weekly as_of=%s — skipping write", as_of_label)
            errors += 1
            continue

        # Backfill precedence: drop report_dates already covered by a backfill file
        # (or an earlier weekly file). Only genuinely-newer weeks survive.
        before = len(df)
        df = df[~df["report_date"].astype(str).isin(covered_dates)].copy()
        dropped = before - len(df)

        if df.empty:
            logger.info("deduped  weekly as_of=%s  (%d rows already covered by backfill)",
                        as_of_label, dropped)
            deduped += 1
            continue

        if dropped:
            logger.info("weekly as_of=%s  dropped %d backfill-covered rows, keeping %d",
                        as_of_label, dropped, len(df))

        covered_dates |= _report_dates(df)

        if args.dry_run:
            logger.info("dry-run  weekly as_of=%s  rows=%d  slugs=%s",
                        as_of_label, len(df), sorted(df["leviathan_slug"].unique().tolist()))
            written += 1
            continue

        try:
            _write_parquet(s3, bucket, b_key, df)
            logger.info("written  weekly as_of=%s  rows=%d  %s", as_of_label, len(df), b_key)
            written += 1
        except Exception:
            logger.exception("Write failed: %s", b_key)
            errors += 1

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
    label = "dry-run" if args.dry_run else "written"
    logger.info(
        "Done in %.1fs — %s=%d  skipped=%d  deduped=%d  errors=%d",
        elapsed, label, written, skipped, deduped, errors,
    )
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
