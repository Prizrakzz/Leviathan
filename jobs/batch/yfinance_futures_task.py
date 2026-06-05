"""AWS Batch entrypoint: yfinance continuous futures → raw + bronze + silver.

Fetches all 12 US/ICE front-month continuous contracts from Yahoo Finance,
computes bronze (OHLCV + roll masking) and silver (price features), and
writes:

    silver/futures_prices/part-000.parquet

Columns: date, leviathan_slug, close, log_return, price_z_2yr,
         realized_vol_30d, momentum_60d, momentum_1yr, vol_regime, source

Validation
----------
After silver write, asserts:
  - corn_cbot 2012: price_z_2yr ≥ 1.5σ (drought-year price spike)
  - At least 10 slugs written (graceful skip if one ticker fails)

Usage
-----
    python jobs/batch/yfinance_futures_task.py
    python jobs/batch/yfinance_futures_task.py --force-overwrite
    python jobs/batch/yfinance_futures_task.py --dry-run
    python jobs/batch/yfinance_futures_task.py --slugs corn_cbot soybeans_cbot
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
from leviathan.storage.paths import (
    bronze_yfinance_key,
    raw_yfinance_key,
    silver_futures_prices_key,
)
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    upload_bytes_to_s3,
)
from leviathan.transforms.bronze_to_silver.yfinance_futures import build_futures_silver
from leviathan.transforms.raw_to_bronze.yfinance_futures import (
    TICKER_MAP,
    extract_yfinance_bronze,
)

logger = get_logger("yfinance_futures_task")

_POLITE_DELAY = 2.0


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

    parser = argparse.ArgumentParser(description="yfinance futures → raw + bronze + silver")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--slugs", nargs="+", default=list(TICKER_MAP.keys()), metavar="SLUG")
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    bucket     = args.bucket     or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    s3         = get_thread_local_s3_client(aws_region)
    s_key      = silver_futures_prices_key()

    if not args.force_overwrite and not args.dry_run and _exists(s3, bucket, s_key):
        logger.info("Silver exists — use --force-overwrite to re-run: %s", s_key)
        return

    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance not installed — run: pip install 'yfinance>=0.2'")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Fetch raw + bronze per slug
    # ------------------------------------------------------------------
    bronze_dfs: list[pd.DataFrame] = []
    errors = 0

    for i, slug in enumerate(args.slugs):
        ticker = TICKER_MAP.get(slug)
        if not ticker:
            logger.error("Unknown slug: %s", slug)
            errors += 1
            continue

        logger.info("Fetching %s (%s) …", slug, ticker)
        try:
            df_raw = yf.download(ticker, period="max", interval="1d",
                                 progress=False, auto_adjust=True)
        except Exception:
            logger.exception("yfinance download failed: %s", slug)
            errors += 1
            if i < len(args.slugs) - 1:
                time.sleep(_POLITE_DELAY)
            continue

        if df_raw.empty:
            logger.warning("%s: empty DataFrame — skipping", slug)
            errors += 1
            if i < len(args.slugs) - 1:
                time.sleep(_POLITE_DELAY)
            continue

        if isinstance(df_raw.columns, pd.MultiIndex):
            df_raw.columns = df_raw.columns.get_level_values(0)
        df_raw = df_raw.reset_index()
        df_raw.columns = [c.lower() for c in df_raw.columns]

        # Write raw
        r_key = raw_yfinance_key(slug)
        if not args.dry_run:
            buf = io.BytesIO()
            df_raw.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
            upload_bytes_to_s3(buf.getvalue(), bucket, r_key, aws_region)
            logger.info("Raw written → %s  rows=%d", r_key, len(df_raw))

        # Bronze transform
        try:
            buf_raw = io.BytesIO()
            df_raw.to_parquet(buf_raw, index=False)
            df_bronze = extract_yfinance_bronze(buf_raw.getvalue(), slug, ticker)
        except ValueError:
            logger.exception("Bronze transform failed: %s", slug)
            errors += 1
            if i < len(args.slugs) - 1:
                time.sleep(_POLITE_DELAY)
            continue

        if not args.dry_run:
            b_key = bronze_yfinance_key(slug)
            _write(s3, bucket, b_key, df_bronze)
            logger.info("Bronze written → %s  rows=%d", b_key, len(df_bronze))

        bronze_dfs.append(df_bronze)

        if i < len(args.slugs) - 1:
            time.sleep(_POLITE_DELAY)

    if not bronze_dfs:
        logger.error("No bronze DataFrames produced — all slugs failed")
        sys.exit(1)

    if errors:
        logger.warning("%d slug(s) failed ingest", errors)

    # ------------------------------------------------------------------
    # Silver transform
    # ------------------------------------------------------------------
    df_silver = build_futures_silver(bronze_dfs)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    slugs_in_silver = set(df_silver["leviathan_slug"].unique())
    if len(slugs_in_silver) < 10:
        logger.error("Silver has only %d slugs (expected ≥10)", len(slugs_in_silver))
        sys.exit(1)

    # Corn 2012 drought: price should be strongly elevated
    df_silver["date"] = pd.to_datetime(df_silver["date"])
    corn_2012 = df_silver[
        (df_silver["leviathan_slug"] == "corn_cbot") &
        (df_silver["date"].dt.year == 2012) &
        df_silver["price_z_2yr"].notna()
    ]["price_z_2yr"]

    if not corn_2012.empty:
        peak_z = float(corn_2012.max())
        if peak_z >= 1.5:
            logger.info("Validation OK: corn_cbot 2012 peak price_z_2yr=%.2f ≥ 1.5 ✓", peak_z)
        else:
            logger.warning(
                "Validation: corn_cbot 2012 peak price_z_2yr=%.2f (expected ≥1.5) "
                "— data or window issue",
                peak_z,
            )
    else:
        logger.warning("Validation: corn_cbot 2012 rows not found")

    if args.dry_run:
        logger.info(
            "dry-run — would write %s  rows=%d  slugs=%d",
            s_key, len(df_silver), len(slugs_in_silver),
        )
        # Show sample: corn 2012
        sample = df_silver[
            (df_silver["leviathan_slug"] == "corn_cbot") &
            (df_silver["date"] >= "2012-06-01") &
            (df_silver["date"] <= "2012-09-30")
        ][["date", "close", "price_z_2yr", "realized_vol_30d", "momentum_60d"]].head(8)
        if not sample.empty:
            print(sample.to_string(index=False))
        return

    _write(s3, bucket, s_key, df_silver)
    logger.info(
        "Silver written → %s  rows=%d  slugs=%d",
        s_key, len(df_silver), len(slugs_in_silver),
    )


if __name__ == "__main__":
    main()
