"""AWS Batch entrypoint: yfinance continuous futures -> raw + bronze + silver (shadow-first).

Fetches all 12 US/ICE front-month continuous contracts from Yahoo Finance,
computes bronze (OHLCV + roll masking) and silver (price features), and
publishes the flat table:

    silver/futures_prices/part-000.parquet

Publish contract (A-W4 CLASS-B retrofit)
----------------------------------------
The silver write is routed through the SILVER-F015 shadow-first controlled
publisher via ``leviathan.silver.flat_producer.build_flat_publish`` with the
EXPLICIT INV-2 arrow schema from the F010 ``silver_futures_prices`` contract.
``--publish-mode`` (default ``dry-run``) resolves through the publish guard:

  * dry-run   : nothing is written anywhere.
  * shadow    : the silver object is staged ONLY under ``silver/futures_prices/_shadow/``;
                canonical is untouched. Raw + bronze are NOT written (gated on
                ``may_mutate_canonical``).
  * canonical : raw + bronze + shadow-stage -> validate -> promote, ONLY with a
                verified signed approval.

The legacy ``--dry-run`` flag is retained as an alias for ``--publish-mode dry-run``.
Note: the former ``--force-overwrite`` no-op guard is subsumed by the publish
contract -- a bare run is now dry-run (writes nothing) rather than a canonical
overwrite; ``--publish-mode canonical --force-overwrite`` performs the overwrite.

Usage
-----
    python jobs/batch/yfinance_futures_task.py                         # dry-run (writes nothing)
    python jobs/batch/yfinance_futures_task.py --publish-mode shadow
    python jobs/batch/yfinance_futures_task.py --publish-mode canonical --force-overwrite
    python jobs/batch/yfinance_futures_task.py --dry-run
    python jobs/batch/yfinance_futures_task.py --slugs corn_cbot soybeans_cbot
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys
import time

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.silver.flat_producer import authorize_for_contract, build_flat_publish
from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry
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

_TABLE = "silver_futures_prices"
_JOB = "yfinance_futures_silver"
_POLITE_DELAY = 2.0


def _exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def _write_bronze(s3_client, bucket: str, key: str, df: pd.DataFrame) -> None:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3_client.put_object(Bucket=bucket, Key=key, Body=buf.getvalue(),
                         ContentType="application/octet-stream")


def _caller_identity(aws_region: str) -> tuple[str, str]:
    """Best-effort STS identity for the canonical publish target (empty on failure)."""
    try:
        import boto3
        ident = boto3.client("sts", region_name=aws_region).get_caller_identity()
        return ident.get("Account", ""), ident.get("Arn", "")
    except Exception as exc:  # noqa: BLE001 -- dry-run / shadow must not require live credentials
        logger.info("STS identity unavailable (%s); using empty target (dry-run/shadow only)", exc)
        return "", ""


def _fetch_bronze(
    slugs: list[str],
    bucket: str,
    aws_region: str,
    s3_client,
    write_canonical: bool,
) -> tuple[list[pd.DataFrame], int]:
    """Download raw + extract bronze per slug; raw + bronze reach the canonical surface only when
    ``write_canonical``. Returns (bronze_dfs, error_count)."""
    import yfinance as yf

    bronze_dfs: list[pd.DataFrame] = []
    errors = 0

    for i, slug in enumerate(slugs):
        ticker = TICKER_MAP.get(slug)
        if not ticker:
            logger.error("Unknown slug: %s", slug)
            errors += 1
            continue

        logger.info("Fetching %s (%s) ...", slug, ticker)
        try:
            df_raw = yf.download(ticker, period="max", interval="1d",
                                 progress=False, auto_adjust=True)
        except Exception:
            logger.exception("yfinance download failed: %s", slug)
            errors += 1
            if i < len(slugs) - 1:
                time.sleep(_POLITE_DELAY)
            continue

        if df_raw.empty:
            logger.warning("%s: empty DataFrame -- skipping", slug)
            errors += 1
            if i < len(slugs) - 1:
                time.sleep(_POLITE_DELAY)
            continue

        if isinstance(df_raw.columns, pd.MultiIndex):
            df_raw.columns = df_raw.columns.get_level_values(0)
        df_raw = df_raw.reset_index()
        df_raw.columns = [c.lower() for c in df_raw.columns]

        if write_canonical:
            r_key = raw_yfinance_key(slug)
            buf = io.BytesIO()
            df_raw.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
            upload_bytes_to_s3(buf.getvalue(), bucket, r_key, aws_region)
            logger.info("Raw written -> %s  rows=%d", r_key, len(df_raw))

        try:
            buf_raw = io.BytesIO()
            df_raw.to_parquet(buf_raw, index=False)
            df_bronze = extract_yfinance_bronze(buf_raw.getvalue(), slug, ticker)
        except ValueError:
            logger.exception("Bronze transform failed: %s", slug)
            errors += 1
            if i < len(slugs) - 1:
                time.sleep(_POLITE_DELAY)
            continue

        if write_canonical:
            b_key = bronze_yfinance_key(slug)
            _write_bronze(s3_client, bucket, b_key, df_bronze)
            logger.info("Bronze written -> %s  rows=%d", b_key, len(df_bronze))

        bronze_dfs.append(df_bronze)

        if i < len(slugs) - 1:
            time.sleep(_POLITE_DELAY)

    return bronze_dfs, errors


def _publish_futures(
    df: pd.DataFrame,
    contract: dict,
    auth,
    s3_client,
    bucket: str,
    *,
    force_overwrite: bool,
) -> ManifestState | None:
    """Publish the flat futures-prices silver object through the shadow-first publisher."""
    canonical_key = silver_futures_prices_key()
    if (
        not force_overwrite
        and auth.may_mutate_canonical
        and s3_client is not None
        and _exists(s3_client, bucket, canonical_key)
    ):
        logger.info(
            "silver exists -- use --publish-mode canonical --force-overwrite to re-run: %s",
            canonical_key,
        )
        return None
    plan = build_flat_publish(
        df=df, contract=contract, canonical_key=canonical_key,
        auth=auth, s3_client=s3_client, job=_JOB,
    )
    manifest = plan.run()
    logger.info(
        "futures_prices silver publish mode=%s state=%s rows=%d key=%s",
        auth.mode.value, manifest.state.value, len(df), canonical_key,
    )
    return manifest.state


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(description="yfinance futures -> raw + bronze + silver")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--slugs", nargs="+", default=list(TICKER_MAP.keys()), metavar="SLUG")
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="Alias for --publish-mode dry-run (writes nothing).")
    parser.add_argument("--publish-mode", default="dry-run",
                        choices=["dry-run", "shadow", "canonical"], dest="publish_mode",
                        help="dry-run|shadow|canonical (default dry-run; canonical needs a signed approval)")
    parser.add_argument("--role-arn", default="", dest="role_arn")
    parser.add_argument("--account-id", default="", dest="account_id")
    args = parser.parse_args()

    publish_mode = "dry-run" if args.dry_run else args.publish_mode
    bucket     = args.bucket     or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    contract = load_registry().table(_TABLE)

    try:
        import yfinance  # noqa: F401 -- fail fast with a clear message if the dep is absent
    except ImportError:
        logger.error("yfinance not installed -- run: pip install 'yfinance>=0.2'")
        sys.exit(1)

    account_id, role_arn = args.account_id, args.role_arn
    if publish_mode == "canonical" and not account_id and not role_arn:
        account_id, role_arn = _caller_identity(aws_region)
    auth = authorize_for_contract(
        contract, publish_mode=publish_mode,
        role_arn=role_arn, account_id=account_id, env=os.environ,
    )
    logger.info("publish authorized: mode=%s may_canonical=%s", auth.mode.value, auth.may_mutate_canonical)

    s3 = get_thread_local_s3_client(aws_region)
    publish_client = None if publish_mode == "dry-run" else s3

    bronze_dfs, errors = _fetch_bronze(
        args.slugs, bucket, aws_region, s3, write_canonical=auth.may_mutate_canonical,
    )
    if not bronze_dfs:
        logger.error("No bronze DataFrames produced -- all slugs failed")
        sys.exit(1)
    if errors:
        logger.warning("%d slug(s) failed ingest", errors)

    df_silver = build_futures_silver(bronze_dfs)
    # INV-2: date must be a timestamp for the pinned timestamp[us] writer schema.
    df_silver["date"] = pd.to_datetime(df_silver["date"])

    slugs_in_silver = set(df_silver["leviathan_slug"].unique())
    if len(slugs_in_silver) < 10:
        logger.error("Silver has only %d slugs (expected >=10)", len(slugs_in_silver))
        sys.exit(1)

    if publish_mode == "dry-run":
        logger.info(
            "dry-run -- would publish %s rows=%d slugs=%d",
            silver_futures_prices_key(), len(df_silver), len(slugs_in_silver),
        )
        sample = df_silver[
            (df_silver["leviathan_slug"] == "corn_cbot")
            & (df_silver["date"] >= "2012-06-01")
            & (df_silver["date"] <= "2012-09-30")
        ][["date", "close", "price_z_2yr", "realized_vol_30d", "momentum_60d"]].head(8)
        if not sample.empty:
            print(sample.to_string(index=False))

    _publish_futures(df_silver, contract, auth, publish_client, bucket,
                     force_overwrite=args.force_overwrite)


if __name__ == "__main__":
    main()
