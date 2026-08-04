"""AWS Batch entrypoint: NASS citrus monthly-forecast raw PDFs -> bronze Parquet.

SILVER-F056 completion (stale-producer restore). This is the tracked raw->bronze producer that the
citrus chain was missing: it reads the monthly-forecast PDFs under
``raw/production/source=usda_nass_citrus/report_type=monthly_forecast/season=<S>/`` and writes one
bronze Parquet per (season, report_month) via
:func:`leviathan.transforms.raw_to_bronze.nass_citrus.extract_nass_citrus_forecast_bronze`, so the
existing ``nass_citrus_task.py`` silver step (which reads the WHOLE bronze corpus) can advance.

The season is scoped from ``--season`` or, for the scheduled chain, derived from ``--asof`` via
:func:`current_forecast_season` (the current open forecast season; the off-season falls forward).
It writes bronze only -- it never touches silver and submits no downstream job. Idempotent: it
overwrites the season's bronze Parquets in place, so re-running a mid-season fire (Oct, then Dec,
then Jan ...) simply rebuilds that season's bronze from whatever raw is present.

D-PR-25 -- DECLARED ABSENCE (failure class G), 2026-08-04
--------------------------------------------------------
Citrus is SEASONALLY ABSENT BY DESIGN. The forecast season runs October -> July, the schedule
``cron(0 18 13 1-7,10-12 ? *)`` already skips months 8-9, and ``current_forecast_season`` FALLS
FORWARD in Aug/Sep -- so an out-of-season fire (only reachable ad hoc, e.g. a catchup) targets a
season that has not opened yet and its raw prefix is EMPTY BY CONSTRUCTION. Independently, the
source itself has been paused since 2024-25/cit0725.pdf, so an in-season fire can also find nothing.

Neither is a failure, and neither may be a SILENT SKIP either. The ratified shape (same as E1's
clamp-and-declare) is: **exit 0 with an explicit "source not published this season" RECORD**. This
task therefore emits a :data:`DECLARED_ABSENCE_MARKER` log line carrying the full JSON record on
every empty-prefix fire, and persists that record to S3 under
``raw_meta/declared_absence/...``, naming which of the two reasons applies
(:data:`ABSENCE_REASON_SEASON_NOT_OPEN` vs :data:`ABSENCE_REASON_SOURCE_NOT_PUBLISHED`). Staleness
remains owned by the FreshnessLagDays / FreshnessLagRatio poller and the per-table
``silver_nass_citrus`` alarm, never by this exit code.

Usage
-----
    python jobs/batch/nass_citrus_bronze_task.py --season 2025-26
    python jobs/batch/nass_citrus_bronze_task.py --asof 2026-01-13T18:00:00Z
    python jobs/batch/nass_citrus_bronze_task.py --season 2024-25 --dry-run
"""
from __future__ import annotations

import argparse
import datetime as _dt
import io
import json
import logging
import sys

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso
from leviathan.storage.paths import bronze_nass_citrus_key
from leviathan.transforms.raw_to_bronze.nass_citrus import (
    # deliberately the SAME asof coercion current_forecast_season uses, so the record's fire_date
    # and the season it is declaring an absence FOR can never disagree about what --asof meant.
    _coerce_date as coerce_asof_date,
    current_forecast_season,
    extract_nass_citrus_forecast_bronze,
)

logger = get_logger("nass_citrus_bronze_task")

_REPORT_TYPE = "monthly_forecast"
_SOURCE = "usda_nass_citrus"
_RAW_PREFIX_FMT = "raw/production/source=usda_nass_citrus/report_type=monthly_forecast/season={season}/"

# D-PR-25. The declared-absence record.
#
# The log MARKER is emitted unconditionally and first, so the declaration survives even when the S3
# write fails -- an absence record that only exists if a put_object succeeds is still a silent skip
# on the day it matters. The S3 copy is what makes it queryable after Batch's 7-day log retention.
DECLARED_ABSENCE_MARKER = "DECLARED-ABSENCE"
ABSENCE_RECORD_TYPE = "declared_absence"

#: The season has not opened yet (the fire is before 1 October of the season's start year). This is
#: the seasonal, BY-DESIGN absence class G names: Aug/Sep fires fall forward to the coming season.
ABSENCE_REASON_SEASON_NOT_OPEN = "season_not_open"
#: The season IS open and the vendor has still published nothing -- the measured upstream pause
#: (NASS citrus history.php carries no 2025-26 season; newest file 2024-25/cit0725.pdf, Jul-2025).
ABSENCE_REASON_SOURCE_NOT_PUBLISHED = "source_not_published"

_ABSENCE_KEY_FMT = (
    "raw_meta/declared_absence/source={source}/report_type={report_type}/"
    "season={season}/{fire_date}.json"
)

# The Florida citrus forecast season opens in October of its start year and closes the following
# July (Aug-Sep is the closed period). Only the OPEN date is needed to classify an absence.
_SEASON_OPEN_MONTH = 10


def season_open_date(season: str) -> _dt.date:
    """First day a ``YYYY-YY`` citrus forecast season can publish: 1 October of its start year.

    ``'2026-27' -> date(2026, 10, 1)``. Raises ``ValueError`` on a malformed season so a typo in
    ``--season`` can never be silently classified as an expected absence."""
    text = str(season).strip()
    head, sep, tail = text.partition("-")
    if not sep or len(head) != 4 or len(tail) != 2 or not head.isdigit() or not tail.isdigit():
        raise ValueError(f"malformed citrus season {season!r} -- expected YYYY-YY")
    return _dt.date(int(head), _SEASON_OPEN_MONTH, 1)


def absence_reason(season: str, asof: "str | _dt.date | _dt.datetime | None" = None) -> str:
    """Classify an empty season prefix: has the season even opened as of this fire?

    Before 1 October of the season's start year the season CANNOT have published -- that is the
    by-design seasonal absence (class G). On or after it, the season is open and an empty prefix
    means the vendor has published nothing, which is the measured upstream pause. Both are declared
    absences and both exit 0; the record says WHICH, so "the calendar explains it" is never confused
    with "the source went quiet"."""
    return (ABSENCE_REASON_SEASON_NOT_OPEN
            if coerce_asof_date(asof) < season_open_date(season)
            else ABSENCE_REASON_SOURCE_NOT_PUBLISHED)


def declared_absence_record(*, bucket: str, prefix: str, season: str,
                            asof: "str | _dt.date | _dt.datetime | None" = None) -> dict:
    """The explicit "source not published this season" record for one empty-prefix fire."""
    reason = absence_reason(season, asof)
    detail = (
        f"citrus forecast season {season} opens {season_open_date(season).isoformat()}; "
        f"no monthly_forecast raw PDFs can exist yet"
        if reason == ABSENCE_REASON_SEASON_NOT_OPEN else
        f"citrus forecast season {season} is open but the vendor has published no "
        f"monthly_forecast PDFs (upstream pause; newest published file is 2024-25/cit0725.pdf)"
    )
    return {
        "record_type": ABSENCE_RECORD_TYPE,
        "decision": "D-PR-25",
        "source": _SOURCE,
        "report_type": _REPORT_TYPE,
        "season": season,
        "season_opens": season_open_date(season).isoformat(),
        "asof": "" if asof is None else str(asof),
        "fire_date": coerce_asof_date(asof).isoformat(),
        "reason": reason,
        "detail": detail,
        "raw_prefix": f"s3://{bucket}/{prefix}",
        "raw_objects_found": 0,
        "declared_at": utc_now_iso(),
    }


def absence_record_key(record: dict) -> str:
    """Where the record lands: one object per (season, fire date), so a re-fire overwrites in place
    rather than accumulating a duplicate per retry attempt."""
    return _ABSENCE_KEY_FMT.format(
        source=record["source"], report_type=record["report_type"],
        season=record["season"], fire_date=record["fire_date"])


def _persist_absence_record(s3, bucket: str, record: dict, *, dry_run: bool) -> None:
    """Write the record to S3. BEST-EFFORT: the marker line is already in the job log, and failing
    the fire here would manufacture the very red D-PR-25 exists to remove."""
    key = absence_record_key(record)
    if dry_run:
        logger.info("DRY-RUN declared-absence record -> s3://%s/%s", bucket, key)
        return
    try:
        s3.put_object(Bucket=bucket, Key=key,
                      Body=json.dumps(record, indent=2, sort_keys=True).encode("utf-8"),
                      ContentType="application/json")
        logger.info("declared-absence record -> s3://%s/%s", bucket, key)
    except Exception as exc:  # noqa: BLE001 - record persistence must not fail an honest no-op
        logger.error("could not persist declared-absence record to s3://%s/%s: %s "
                     "(the %s log line above IS the declaration)", bucket, key, exc,
                     DECLARED_ABSENCE_MARKER)


def _build_season_bronze(bucket: str, season: str, aws_region: str, *,
                         skip_existing: bool, dry_run: bool,
                         asof: "str | _dt.date | _dt.datetime | None" = None,
                         ) -> tuple[int, int, int, "dict | None"]:
    """Parse every monthly-forecast PDF of ``season`` to bronze.

    Returns ``(written, skipped, failed, absence)`` -- ``absence`` is the D-PR-25 declared-absence
    record when the season's raw prefix held nothing, else ``None``."""
    from leviathan.storage.s3 import (
        get_thread_local_s3_client,
        list_s3_keys,
        s3_download_with_retry,
        s3_object_exists,
    )
    s3 = get_thread_local_s3_client(aws_region)
    prefix = _RAW_PREFIX_FMT.format(season=season)
    keys = sorted(list_s3_keys(bucket, prefix, suffix=".pdf", aws_region=aws_region))
    if not keys:
        # D-PR-25 DECLARED ABSENCE, not an error and not a silent skip. Two ways to get here, both
        # expected and both exit 0: the season has not opened yet (Aug/Sep fall-forward; the cron
        # already skips months 8-9, so this is reachable only ad hoc), or the season is open and the
        # SOURCE is paused -- NASS's citrus history page carries no 2025-26 season at all, the
        # newest published file being 2024-25/cit0725.pdf (probed 2026-07-23). Failing red would
        # page the owner on every fire of a known-quiet source; skipping silently would leave no
        # evidence that the fire happened at all. So: declare, record, exit 0. Staleness detection
        # stays with the FreshnessLagDays/FreshnessLagRatio poller and the per-table
        # silver_nass_citrus alarm, NOT with this exit code. If NASS resumes, the fetch step stages
        # PDFs and this branch never triggers.
        record = declared_absence_record(bucket=bucket, prefix=prefix, season=season, asof=asof)
        logger.warning("%s %s", DECLARED_ABSENCE_MARKER, json.dumps(record, sort_keys=True))
        _persist_absence_record(s3, bucket, record, dry_run=dry_run)
        return (0, 0, 0, record)
    logger.info("citrus bronze: %d raw PDFs under %s", len(keys), prefix)

    written = skipped = failed = 0
    for key in keys:
        filename = key.rsplit("/", 1)[-1]
        try:
            df = extract_nass_citrus_forecast_bronze(
                s3_download_with_retry(bucket, key, s3), season, filename)
            report_month = int(df["report_month"].iloc[0])
            b_key = bronze_nass_citrus_key(season, _REPORT_TYPE, report_month)
            if skip_existing and s3_object_exists(bucket, b_key, aws_region):
                logger.info("SKIP (bronze exists) %s -> %s", filename, b_key)
                skipped += 1
                continue
            if dry_run:
                logger.info("DRY-RUN %s -> %s (%d rows)", filename, b_key, len(df))
                written += 1
                continue
            buf = io.BytesIO()
            df.to_parquet(buf, index=False, compression="snappy", engine="pyarrow")
            s3.put_object(Bucket=bucket, Key=b_key, Body=buf.getvalue())
            logger.info("OK %s -> s3://%s/%s (%d rows)", filename, bucket, b_key, len(df))
            written += 1
        except Exception as exc:  # noqa: BLE001 - one bad PDF must not abort the whole season
            logger.error("FAILED %s: %s", filename, exc)
            failed += 1
    return written, skipped, failed, None


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s", stream=sys.stderr)
    load_env()
    parser = argparse.ArgumentParser(description="NASS citrus monthly-forecast raw PDFs -> bronze")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--asof", default=None,
                        help="scheduled-time ISO; the season is derived from it when --season is absent")
    parser.add_argument("--season", default=None,
                        help="YYYY-YY season to (re)build; overrides --asof derivation")
    parser.add_argument("--skip-existing", action="store_true",
                        help="skip a report whose bronze Parquet already exists")
    parser.add_argument("--dry-run", action="store_true", help="parse + log; write nothing")
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    season = args.season or current_forecast_season(args.asof)
    logger.info("citrus bronze producer: season=%s (asof=%s) dry_run=%s",
                season, args.asof, args.dry_run)

    written, skipped, failed, absence = _build_season_bronze(
        bucket, season, aws_region, skip_existing=args.skip_existing, dry_run=args.dry_run,
        asof=args.asof)
    logger.info("citrus bronze complete: season=%s written=%d skipped=%d failed=%d absence=%s",
                season, written, skipped, failed,
                absence["reason"] if absence else "none")
    if failed:
        sys.exit(1)
    # A declared absence is a SUCCESS (D-PR-25): the fire is falling through to exit 0 with the
    # record above standing as its evidence. Nothing below may turn it into a failure.


if __name__ == "__main__":
    main()
