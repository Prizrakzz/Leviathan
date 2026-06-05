"""AWS Batch entrypoint: Quandl CHRIS continuous futures → raw + bronze + silver.

Downloads 36 series (12 slugs × C1/C2/C3 tenors) from Nasdaq Data Link,
computes bronze (settlement prices) and silver (calendar spreads), and
writes:

    silver/calendar_spreads/part-000.parquet

Columns: date, leviathan_slug, settle_c1, settle_c2, settle_c3,
         spread_c1c3, spread_c1c3_z_3yr, contango_flag, source

Prerequisites
-------------
Set NASDAQ_API_KEY in environment or .env.
Register free at https://data.nasdaq.com/sign-up

Validation
----------
  - corn_cbot 2012 (drought): spread_c1c3 should be > 0 (backwardation)
  - corn_cbot 2016 (surplus): spread_c1c3 should be < 0 (contango)

Usage
-----
    python jobs/batch/quandl_chris_task.py
    python jobs/batch/quandl_chris_task.py --force-overwrite
    python jobs/batch/quandl_chris_task.py --dry-run
    python jobs/batch/quandl_chris_task.py --slugs corn_cbot soybeans_cbot
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
import time

import requests
import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import (
    bronze_chris_key,
    raw_chris_key,
    silver_calendar_spreads_key,
)
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    upload_bytes_to_s3,
)
from leviathan.transforms.bronze_to_silver.quandl_chris import build_calendar_spreads_silver
from leviathan.transforms.raw_to_bronze.quandl_chris import extract_chris_bronze
from jobs.ingest.fetch_quandl_chris import CHRIS_MAP  # reuse dataset ID map

logger = get_logger("quandl_chris_task")

_API_BASE     = "https://data.nasdaq.com/api/v3/datasets"
_TIMEOUT      = 30
_POLITE_DELAY = 1.0
_DEFAULT_START = "1990-01-01"


def _exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def _write(s3_client, bucket: str, key: str, df: pd.DataFrame) -> None:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3_client.put_object(Bucket=bucket, Key=key, Body=buf.getvalue(),
                         ContentType="application/octet-stream")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(description="Quandl CHRIS → raw + bronze + silver")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--api-key", default=None, dest="api_key")
    parser.add_argument("--slugs", nargs="+", default=list(CHRIS_MAP.keys()), metavar="SLUG")
    parser.add_argument("--tenors", nargs="+", type=int, default=[1, 2, 3], metavar="N")
    parser.add_argument("--start-date", default=_DEFAULT_START, dest="start_date")
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    bucket     = args.bucket     or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    api_key    = (
        args.api_key
        or os.environ.get("NASDAQ_API_KEY")
        or os.environ.get("QUANDL_API_KEY")
    )

    if not api_key:
        logger.error(
            "NASDAQ_API_KEY not set.  Register free at https://data.nasdaq.com/sign-up"
        )
        sys.exit(1)

    s3    = get_thread_local_s3_client(aws_region)
    s_key = silver_calendar_spreads_key()

    if not args.force_overwrite and not args.dry_run and _exists(s3, bucket, s_key):
        logger.info("Silver exists — use --force-overwrite to re-run: %s", s_key)
        return

    # ------------------------------------------------------------------
    # Fetch raw + bronze per (slug, tenor)
    # ------------------------------------------------------------------
    bronze_by_slug: dict[str, dict[int, pd.DataFrame]] = {}
    errors = 0
    total  = len(args.slugs) * len(args.tenors)
    count  = 0

    for slug in args.slugs:
        bronze_by_slug[slug] = {}
        for tenor in args.tenors:
            ds_id  = f"{CHRIS_MAP[slug]}{tenor}"
            r_key  = raw_chris_key(slug, tenor)
            b_key  = bronze_chris_key(slug, tenor)
            url    = f"{_API_BASE}/{ds_id}.json"
            params = {"api_key": api_key, "start_date": args.start_date, "order": "asc"}

            count += 1
            logger.info("[%d/%d] Fetching %s C%d (%s) …", count, total, slug, tenor, ds_id)

            try:
                resp = requests.get(url, params=params, timeout=_TIMEOUT)
                resp.raise_for_status()
                raw_bytes = resp.content
            except requests.HTTPError as e:
                code = e.response.status_code if e.response is not None else "?"
                logger.warning("HTTP %s for %s C%d — skipping", code, slug, tenor)
                errors += 1
                if count < total:
                    time.sleep(_POLITE_DELAY)
                continue
            except requests.RequestException:
                logger.exception("Request failed: %s C%d", slug, tenor)
                errors += 1
                if count < total:
                    time.sleep(_POLITE_DELAY)
                continue

            n_rows = len(json.loads(raw_bytes).get("dataset", {}).get("data", []))
            logger.info("  %d data rows", n_rows)

            if not args.dry_run:
                upload_bytes_to_s3(raw_bytes, bucket, r_key, aws_region)
                logger.info("  Raw → %s", r_key)

            try:
                df_bronze = extract_chris_bronze(raw_bytes, slug, tenor, ds_id)
            except ValueError:
                logger.exception("Bronze parse failed: %s C%d", slug, tenor)
                errors += 1
                if count < total:
                    time.sleep(_POLITE_DELAY)
                continue

            if not args.dry_run and not df_bronze.empty:
                _write(s3, bucket, b_key, df_bronze)
                logger.info("  Bronze → %s  rows=%d", b_key, len(df_bronze))

            if not df_bronze.empty:
                bronze_by_slug[slug][tenor] = df_bronze

            if count < total:
                time.sleep(_POLITE_DELAY)

    # ------------------------------------------------------------------
    # Silver transform
    # ------------------------------------------------------------------
    non_empty = {s: t for s, t in bronze_by_slug.items() if t}
    if not non_empty:
        logger.error("No bronze data produced — all series failed")
        sys.exit(1)

    df_silver = build_calendar_spreads_silver(non_empty)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    df_silver["date"] = pd.to_datetime(df_silver["date"])

    for slug_v, year_v, expected_sign, label in [
        ("corn_cbot", 2012, "positive", "backwardation during drought"),
        ("corn_cbot", 2016, "negative", "contango during surplus"),
    ]:
        rows = df_silver[
            (df_silver["leviathan_slug"] == slug_v) &
            (df_silver["date"].dt.year == year_v) &
            df_silver["spread_c1c3"].notna()
        ]["spread_c1c3"]
        if not rows.empty:
            median_spread = float(rows.median())
            ok = (expected_sign == "positive" and median_spread > 0) or \
                 (expected_sign == "negative" and median_spread < 0)
            status = "OK" if ok else "WARN"
            logger.info(
                "Validation %s: %s %d median_spread=%.2f (%s) %s",
                status, slug_v, year_v, median_spread, label,
                "✓" if ok else "⚠",
            )

    if args.dry_run:
        logger.info(
            "dry-run — would write %s  rows=%d  slugs=%d",
            s_key, len(df_silver), df_silver["leviathan_slug"].nunique(),
        )
        # Show corn 2012 backwardation sample
        sample = df_silver[
            (df_silver["leviathan_slug"] == "corn_cbot") &
            (df_silver["date"] >= "2012-06-01") &
            (df_silver["date"] <= "2012-10-01")
        ][["date", "settle_c1", "settle_c3", "spread_c1c3", "spread_c1c3_z_3yr"]].head(8)
        if not sample.empty:
            print(sample.to_string(index=False))
        return

    _write(s3, bucket, s_key, df_silver)
    logger.info(
        "Silver written → %s  rows=%d  slugs=%d  errors=%d",
        s_key, len(df_silver), df_silver["leviathan_slug"].nunique(), errors,
    )

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
