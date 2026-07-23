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

Usage
-----
    python jobs/batch/nass_citrus_bronze_task.py --season 2025-26
    python jobs/batch/nass_citrus_bronze_task.py --asof 2026-01-13T18:00:00Z
    python jobs/batch/nass_citrus_bronze_task.py --season 2024-25 --dry-run
"""
from __future__ import annotations

import argparse
import io
import logging
import sys

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_nass_citrus_key
from leviathan.transforms.raw_to_bronze.nass_citrus import (
    current_forecast_season,
    extract_nass_citrus_forecast_bronze,
)

logger = get_logger("nass_citrus_bronze_task")

_REPORT_TYPE = "monthly_forecast"
_RAW_PREFIX_FMT = "raw/production/source=usda_nass_citrus/report_type=monthly_forecast/season={season}/"


def _build_season_bronze(bucket: str, season: str, aws_region: str, *,
                         skip_existing: bool, dry_run: bool) -> tuple[int, int, int]:
    """Parse every monthly-forecast PDF of ``season`` to bronze. Returns (written, skipped, failed)."""
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
        # HONEST NO-OP, not an error (2026-07-23 probe): NASS's citrus history page carries NO
        # 2025-26 season at all -- the newest published file is 2024-25/cit0725.pdf, i.e. the
        # SOURCE is paused/discontinued after Jul-2025. An empty season prefix therefore means
        # "nothing published upstream yet", and failing red here would page every scheduled fire
        # of a known-quiet source. Staleness detection is owned by the FreshnessLagDays poller +
        # the per-table freshness alarm (silver_nass_citrus), NOT by this exit code. If NASS
        # resumes, the fetch step stages PDFs and this branch never triggers.
        logger.warning("no citrus monthly-forecast raw PDFs under s3://%s/%s -- source has "
                       "published nothing for this season (upstream pause); honest no-op", bucket, prefix)
        return (0, 0, 0)
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
    return written, skipped, failed


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

    written, skipped, failed = _build_season_bronze(
        bucket, season, aws_region, skip_existing=args.skip_existing, dry_run=args.dry_run)
    logger.info("citrus bronze complete: season=%s written=%d skipped=%d failed=%d",
                season, written, skipped, failed)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
