"""SILVER-F053 batch task: MPOC raw HTML -> silver_mpoc_exports_by_country.

Restores the C-WRONG-8 half-orphan producer on the shared F052 adapter + the SILVER-F015 common
publisher. Loads each annual MPOC Trade Statistics HTML page from raw S3, parses it through the
F052 adapter (source-faithful table normalization), transforms to the year x country grain, and
publishes SHADOW-FIRST through the guard (``--publish-mode`` default dry-run -- nothing canonical
is touched in the readiness campaign).

Standard producer CLI (SILVER-F062): --environment --bucket --database --run-id --from --to
--partitions --shadow-root --resume --publish-mode --contract-version.
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.silver.flat_producer import (
    add_standard_producer_args,
    authorize_for_contract,
    build_flat_publish,
)
from leviathan.silver.mpoc.adapter import parse_tables
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import silver_mpoc_key
from leviathan.transforms.bronze_to_silver.mpoc_exports_by_country import (
    MpocExportsRelease,
    transform_exports_by_country,
)

logger = get_logger("mpoc_exports_by_country_silver_task")

TABLE = "silver_mpoc_exports_by_country"
_RAW_PREFIX = "raw/production/source=mpoc/release_type=trade_statistics/"
_YEAR_RE_KEY = "year="


def load_releases(bucket: str, aws_region: str, s3=None) -> list[MpocExportsRelease]:
    """List the annual MPOC trade-statistics HTML pages and parse each into a release."""
    from leviathan.storage.paths import parse_hive_key
    from leviathan.storage.s3 import (
        get_thread_local_s3_client,
        list_s3_keys,
        s3_download_with_retry,
    )

    s3 = s3 or get_thread_local_s3_client(aws_region)
    keys = list_s3_keys(bucket, _RAW_PREFIX, suffix=".html", aws_region=aws_region)
    releases: list[MpocExportsRelease] = []
    for key in keys:
        year_str = parse_hive_key(key, "year")
        if not year_str.isdigit():
            continue
        html = s3_download_with_retry(bucket, key, s3)
        releases.append(MpocExportsRelease(year=int(year_str), tables=parse_tables(html)))
    logger.info("loaded %d MPOC trade-statistics pages", len(releases))
    return releases


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MPOC exports-by-country bronze/raw -> silver")
    add_standard_producer_args(parser)
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s",
                        stream=sys.stderr)
    load_env()
    args = _parse_args()
    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    contract = load_registry().table(TABLE)
    releases = load_releases(bucket, aws_region)
    df = transform_exports_by_country(releases)
    logger.info("silver rows: %d", len(df))
    if df.empty:
        logger.error("empty silver output; aborting")
        return 1

    auth = authorize_for_contract(contract, publish_mode=args.publish_mode)
    # shadow/canonical STAGE objects to S3 -> a live client is required; dry-run stages nothing (None ok).
    from leviathan.storage.s3 import get_thread_local_s3_client
    publish_s3 = None if args.publish_mode == "dry-run" else get_thread_local_s3_client(aws_region)
    plan = build_flat_publish(
        df=df, contract=contract, canonical_key=silver_mpoc_key("exports_by_country"),
        auth=auth, s3_client=publish_s3, job="mpoc_exports_by_country_silver", run_id=args.run_id,
    )
    manifest = plan.run()
    logger.info("publish %s state=%s mode=%s rows=%d", TABLE, manifest.state.value,
                args.publish_mode, len(df))
    return 0


if __name__ == "__main__":
    sys.exit(main())
