"""Fetch yfinance continuous futures OHLCV and write raw Parquets to S3.

Downloads daily OHLCV for 12 US/ICE front-month continuous contracts and
writes one raw Parquet per slug under:

    raw/production/source=yfinance/{slug}/part-000.parquet

No API key required.  yfinance is an unofficial wrapper around Yahoo
Finance's undocumented API — no authentication, no rate limits enforced
by the library (though aggressive use may trigger 429s).  A 2-second
polite delay is added between ticker downloads.

12 contracts covered
--------------------
    corn_cbot                  ZC=F   2000–present
    soybeans_cbot              ZS=F   2000–present
    soybean_oil_cbot           ZL=F   2000–present
    soybean_meal_cbot          ZM=F   2000–present
    soft_red_winter_wheat_cbot ZW=F   2000–present
    hard_red_winter_wheat_kcbt KE=F   2000–present
    arabica_coffee             KC=F   2000–present
    cocoa                      CC=F   2000–present
    cotton                     CT=F   2000–present
    raw_sugar                  SB=F   2000–present
    rough_rice_cbot            ZR=F   1999–present
    frozen_orange_juice        OJ=F   2001–present

HRS Wheat MGEX excluded — no proper continuous ticker on Yahoo Finance.

Data note
---------
yfinance returns unadjusted continuous prices.  Roll gaps (up to 23% for
corn) are present in the raw data.  The bronze transform adds is_roll_date
and log_return (NaN on roll dates) to handle this.  auto_adjust=True is
passed to yfinance to normalise for equity-style splits (not relevant for
futures, but avoids occasional dividend adjustment artifacts).

Usage
-----
    python jobs/ingest/fetch_yfinance_futures.py
    python jobs/ingest/fetch_yfinance_futures.py --dry-run
    python jobs/ingest/fetch_yfinance_futures.py --slugs corn_cbot soybeans_cbot
    python jobs/ingest/fetch_yfinance_futures.py --force-overwrite
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
import time

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_yfinance_key
from leviathan.storage.s3 import get_thread_local_s3_client, upload_bytes_to_s3
from leviathan.transforms.raw_to_bronze.yfinance_futures import TICKER_MAP

logger = get_logger("fetch_yfinance_futures")

_POLITE_DELAY = 2.0   # seconds between yfinance calls


def _fetch_one(slug: str, ticker: str, dry_run: bool,
               bucket: str, aws_region: str) -> bool:
    """Download OHLCV for one ticker and write raw Parquet. Returns True on success."""
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance not installed — run: pip install yfinance>=0.2")
        return False

    logger.info("Fetching %s (%s) …", slug, ticker)
    try:
        df = yf.download(ticker, period="max", interval="1d",
                         progress=False, auto_adjust=True)
    except Exception:
        logger.exception("yfinance download failed: %s (%s)", slug, ticker)
        return False

    if df.empty:
        logger.warning("%s (%s): empty DataFrame returned", slug, ticker)
        return False

    # Flatten MultiIndex columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Reset index so date is a column
    df = df.reset_index()
    df.columns = [c.lower() for c in df.columns]

    rows = len(df)
    if rows < 100:
        logger.warning("%s: only %d rows — possible API issue", slug, rows)

    if dry_run:
        close_col = "close" if "close" in df.columns else df.columns[4]
        last = float(df[close_col].dropna().iloc[-1])
        logger.info(
            "dry-run  %s: %d rows  %s – %s  last=%s=%.2f",
            slug, rows, str(df.iloc[0, 0])[:10], str(df.iloc[-1, 0])[:10],
            ticker, last,
        )
        return True

    key = raw_yfinance_key(slug)
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    upload_bytes_to_s3(buf.getvalue(), bucket, key, aws_region)
    logger.info("Raw written → %s  rows=%d", key, rows)
    return True


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(
        description="Fetch yfinance futures OHLCV → raw S3 Parquets"
    )
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument(
        "--slugs", nargs="+", default=list(TICKER_MAP.keys()),
        metavar="SLUG",
        help="Slugs to fetch (default: all 12)",
    )
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    bucket     = args.bucket     or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    s3         = get_thread_local_s3_client(aws_region)

    unknown = set(args.slugs) - set(TICKER_MAP)
    if unknown:
        logger.error("Unknown slugs: %s", sorted(unknown))
        sys.exit(1)

    logger.info("yfinance ingest  slugs=%s  dry_run=%s", args.slugs, args.dry_run)

    errors = 0
    for i, slug in enumerate(args.slugs):
        ticker = TICKER_MAP[slug]

        if not args.force_overwrite and not args.dry_run:
            key = raw_yfinance_key(slug)
            try:
                s3.head_object(Bucket=bucket, Key=key)
                logger.debug("Skipping %s (raw exists) — use --force-overwrite", slug)
                if i < len(args.slugs) - 1:
                    time.sleep(_POLITE_DELAY)
                continue
            except Exception:
                pass

        ok = _fetch_one(slug, ticker, args.dry_run, bucket, aws_region)
        if not ok:
            errors += 1

        if i < len(args.slugs) - 1:
            time.sleep(_POLITE_DELAY)

    label = "dry-run" if args.dry_run else "written"
    ok_count = len(args.slugs) - errors
    logger.info("Done — %s=%d  errors=%d", label, ok_count, errors)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
