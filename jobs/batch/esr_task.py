"""USDA FAS Export Sales Reporting (ESR) raw → bronze Batch task.

Processes raw ESR JSON files from S3 raw/ and writes per-(commodity, year,
as_of_date) bronze Parquets.

Key design
----------
Two raw key shapes exist:

  Backfill  raw/production/source=usda_esr/
                commodity_code={code}/market_year={year}/all_countries.json
  Weekly    raw/production/source=usda_esr/
                commodity_code={code}/market_year={year}/as_of={YYYYMMDD}/all_countries.json

For backfill keys (no ``as_of`` partition) the ``--backfill-as-of`` date is
used as the ``as_of_date`` for the bronze key (defaults to today in
``YYYYMMDD`` format).  This means re-running the backfill task with a newer
date will write a fresh bronze snapshot without overwriting the original; use
``--force-overwrite`` if you want to replace it.

For weekly keys the ``as_of_date`` is read directly from the ``as_of=``
partition, so each Thursday snapshot lands in its own immutable bronze key.

S3 key structure
----------------
  Bronze: bronze/production/source=usda_esr/
              commodity_code={code}/
              market_year={year}/
              as_of={YYYYMMDD}/
              part-000.parquet

Usage
-----
    python jobs/batch/esr_task.py [--bucket B] [--aws-region R] [--force-overwrite]

Smoke test (first 5 files):
    python jobs/batch/esr_task.py --limit 5
"""
from __future__ import annotations

import argparse
import io
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_esr_key, parse_hive_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.raw_to_bronze.usda_esr import transform_esr_json_to_bronze

logger = get_logger("esr_task")

_RAW_PREFIX = "raw/production/source=usda_esr/"
_WORKERS = 16

# Matches the as_of partition in a weekly raw key, e.g. "as_of=20260522"
_AS_OF_RE = re.compile(r"as_of=(\d{8})")


def _bronze_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001
        return False


def _as_of_from_key(raw_key: str, fallback: str) -> str:
    """Return the ``YYYYMMDD`` as_of_date for a raw ESR key.

    For weekly keys the date is embedded in the ``as_of=`` partition.
    For backfill keys (no such partition) *fallback* is returned.
    """
    m = _AS_OF_RE.search(raw_key)
    return m.group(1) if m else fallback


def _process(
    raw_key: str,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
    backfill_as_of: str,
    ingest_date: str,
) -> tuple[str, str]:
    s3 = get_thread_local_s3_client(aws_region)

    commodity_code_str = parse_hive_key(raw_key, "commodity_code")
    market_year_str = parse_hive_key(raw_key, "market_year")

    if not commodity_code_str or not market_year_str:
        logger.warning("Could not parse commodity_code/market_year from key: %s", raw_key)
        return "error", raw_key

    try:
        commodity_code = int(commodity_code_str)
        market_year = int(market_year_str)
    except ValueError:
        logger.warning("Non-integer commodity_code/market_year in key: %s", raw_key)
        return "error", raw_key

    as_of_date = _as_of_from_key(raw_key, backfill_as_of)
    b_key = bronze_esr_key(commodity_code, market_year, as_of_date)

    if not force_overwrite and _bronze_exists(s3, bucket, b_key):
        return "skipped", raw_key

    try:
        raw_bytes = s3_download_with_retry(bucket, raw_key, s3)
    except Exception as exc:  # noqa: BLE001
        logger.error("S3 download failed  key=%s: %s", raw_key, exc)
        return "error", raw_key

    try:
        df = transform_esr_json_to_bronze(
            raw_bytes,
            commodity_code=commodity_code,
            market_year=market_year,
            as_of_date=as_of_date,
            ingest_date=ingest_date,
        )
    except (ValueError, Exception) as exc:  # noqa: BLE001
        logger.error("ESR transform failed  key=%s: %s", raw_key, exc)
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
        logger.info(
            "bronze written  commodity=%d  year=%d  as_of=%s  rows=%d  %s",
            commodity_code, market_year, as_of_date, len(df), b_key,
        )
        return "written", raw_key
    except Exception as exc:  # noqa: BLE001
        logger.error("Parquet write failed  key=%s: %s", raw_key, exc)
        return "error", raw_key


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )

    load_env()

    parser = argparse.ArgumentParser(description="USDA ESR raw → bronze")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument("--limit", type=int, default=0,
                        help="Cap the number of raw keys processed (smoke test)")
    parser.add_argument(
        "--backfill-as-of",
        default=None,
        dest="backfill_as_of",
        help="YYYYMMDD date to use as as_of_date for backfill keys "
             "(no as_of= partition).  Defaults to today.",
    )
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    today = datetime.now(timezone.utc)
    backfill_as_of = args.backfill_as_of or today.strftime("%Y%m%d")
    ingest_date = today.date().isoformat()

    raw_keys = list_s3_keys(bucket, _RAW_PREFIX, suffix=".json", aws_region=aws_region)
    raw_keys.sort()

    logger.info(
        "ESR task  bucket=%s  raw_keys=%d  force=%s  backfill_as_of=%s",
        bucket, len(raw_keys), args.force_overwrite, backfill_as_of,
    )

    if args.limit:
        raw_keys = raw_keys[: args.limit]

    start = datetime.now(timezone.utc)
    written = skipped = errors = 0

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {
            pool.submit(
                _process,
                key,
                bucket,
                aws_region,
                args.force_overwrite,
                backfill_as_of,
                ingest_date,
            ): key
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

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        "Done  written=%d  skipped=%d  errors=%d  elapsed=%.1fs",
        written, skipped, errors, elapsed,
    )

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
