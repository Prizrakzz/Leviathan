"""SILVER-F055 batch task: MPOC stock-comparison live page -> silver_mpoc_stock_comparison.

Restores the C-WRONG-8 half-orphan producer on the shared F052 adapter + the SILVER-F015 publisher.
The stock-comparison page is a LIVE single-page snapshot: the task records a source-version
(as_of_date + content sha256, F052) so a refresh never erases prior evidence, melts the ending-stock
grid to the country x oil_type x year x month grain, and publishes shadow-first. The source-as-of is
carried in the RUN MANIFEST provenance, NOT as a row column (plan L697).
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.silver.flat_producer import (
    add_standard_producer_args,
    authorize_for_contract,
    build_flat_publish,
)
from leviathan.silver.mpoc.adapter import parse_tables, version_page
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import (
    raw_mpoc_stock_comparison_key,
    silver_mpoc_key,
)
from leviathan.transforms.bronze_to_silver.mpoc_stock_comparison import (
    MpocStockRelease,
    transform_stock_comparison,
)

logger = get_logger("mpoc_stock_comparison_silver_task")

TABLE = "silver_mpoc_stock_comparison"
_SOURCE_URL = "https://mpoc.org.my/market-insight/stock-comparison/"


def load_release(bucket: str, aws_region: str, as_of_date: str, s3=None) -> MpocStockRelease:
    from leviathan.storage.s3 import get_thread_local_s3_client, s3_download_with_retry

    s3 = s3 or get_thread_local_s3_client(aws_region)
    key = raw_mpoc_stock_comparison_key()
    html = s3_download_with_retry(bucket, key, s3)
    sv = version_page(html=html, release_type="stock_comparison", source_url=_SOURCE_URL,
                      as_of_date=as_of_date)
    logger.info("source version: as_of=%s sha256=%s bytes=%d", sv.as_of_date,
                sv.content_sha256[:12], sv.byte_len)
    return MpocStockRelease(as_of_date=as_of_date, tables=parse_tables(html))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MPOC stock-comparison live page -> silver")
    add_standard_producer_args(parser)
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s",
                        stream=sys.stderr)
    load_env()
    args = _parse_args()
    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")
    as_of_date = args.date_to or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    contract = load_registry().table(TABLE)
    df = transform_stock_comparison(load_release(bucket, aws_region, as_of_date))
    logger.info("silver rows: %d (as_of=%s)", len(df), as_of_date)
    if df.empty:
        logger.error("empty silver output; aborting")
        return 1

    auth = authorize_for_contract(contract, publish_mode=args.publish_mode)
    # shadow/canonical STAGE objects to S3 -> a live client is required; dry-run stages nothing (None ok).
    from leviathan.storage.s3 import get_thread_local_s3_client
    publish_s3 = None if args.publish_mode == "dry-run" else get_thread_local_s3_client(aws_region)
    plan = build_flat_publish(
        df=df, contract=contract, canonical_key=silver_mpoc_key("stock_comparison"),
        auth=auth, s3_client=publish_s3, job="mpoc_stock_comparison_silver", run_id=args.run_id,
    )
    manifest = plan.run()
    # source-as-of provenance is threaded into the manifest inputs (NOT a row column).
    manifest.inputs.append({"source_as_of_date": as_of_date, "source_url": _SOURCE_URL})
    logger.info("publish %s state=%s mode=%s rows=%d", TABLE, manifest.state.value,
                args.publish_mode, len(df))
    return 0


if __name__ == "__main__":
    sys.exit(main())
