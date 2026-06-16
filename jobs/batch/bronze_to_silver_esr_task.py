"""AWS Batch Fargate task: bronze → silver (flat) for USDA ESR data.

Reads the LATEST as_of snapshot for each (commodity_code, market_year) pair
from bronze/production/source=usda_esr/ and writes one merged flat parquet per
commodity slug to silver/esr/commodity={slug}/part-000.parquet.

Unlike the weather bronze→silver jobs, ESR is processed in one run across all
10 commodity codes — no --commodity arg.  The output path uses the Leviathan
slug (not the commodity_code) so the feature extractor can probe by slug.

Usage:
    python jobs/batch/bronze_to_silver_esr_task.py --bucket B --aws-region R
    python jobs/batch/bronze_to_silver_esr_task.py --force-overwrite
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import pyarrow.parquet as pq

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import parse_hive_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.bronze_to_silver.usda_esr import transform_esr_bronze_to_silver

logger = get_logger("bronze_to_silver_esr")

_BRONZE_PREFIX = "bronze/production/source=usda_esr/"
_WORKERS = 32


def _silver_esr_key(commodity_slug: str) -> str:
    return f"silver/esr/commodity={commodity_slug}/part-000.parquet"


def _latest_snapshot_keys(all_keys: list[str]) -> list[str]:
    """Keep the file with the latest as_of= date per (commodity_code, market_year)."""
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for key in all_keys:
        code = parse_hive_key(key, "commodity_code")
        year = parse_hive_key(key, "market_year")
        if code and year:
            groups[(code, year)].append(key)

    latest: list[str] = []
    for group_keys in groups.values():
        # as_of=YYYYMMDD is lexicographically sortable, so max() on the full key is safe
        # within a group that shares the same commodity_code/market_year prefix.
        latest.append(max(group_keys, key=lambda k: parse_hive_key(k, "as_of")))
    return sorted(latest)


def _read_and_transform(key: str, bucket: str, aws_region: str) -> pd.DataFrame | None:
    market_year_str = parse_hive_key(key, "market_year")
    if not market_year_str:
        logger.warning("Could not parse market_year from: %s", key)
        return None
    try:
        market_year = int(market_year_str)
    except ValueError:
        logger.warning("Non-integer market_year in: %s", key)
        return None
    try:
        s3 = get_thread_local_s3_client(aws_region)
        data = s3_download_with_retry(bucket, key, s3)
        df = pq.read_table(io.BytesIO(data)).to_pandas()
        return transform_esr_bronze_to_silver(df, market_year)
    except Exception as exc:  # noqa: BLE001 — per-file failures are logged; loop continues
        logger.error("Failed to read/transform %s: %s", key, exc)
        return None


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(description="USDA ESR bronze → silver")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", default="false", dest="force_overwrite")
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    # 1. List bronze, pick latest snapshot per (commodity_code, market_year)
    all_keys = list_s3_keys(bucket, _BRONZE_PREFIX, suffix=".parquet", aws_region=aws_region)
    logger.info("Found %d total bronze ESR files", len(all_keys))
    keys_to_read = _latest_snapshot_keys(all_keys)
    logger.info("Selected %d files (latest as_of per code×year)", len(keys_to_read))

    if not keys_to_read:
        logger.error("No bronze ESR files found under %s", _BRONZE_PREFIX)
        sys.exit(1)

    # 2. Download + transform in parallel
    frames: list[pd.DataFrame] = []
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {
            pool.submit(_read_and_transform, k, bucket, aws_region): k
            for k in keys_to_read
        }
        for fut in as_completed(futures):
            result = fut.result()
            if result is not None and not result.empty:
                frames.append(result)

    if not frames:
        logger.error("All bronze reads/transforms failed — nothing to write")
        sys.exit(1)

    combined = pd.concat(frames, ignore_index=True)
    logger.info(
        "Silver combined: %d rows across %d market_years",
        len(combined),
        combined["market_year"].nunique() if "market_year" in combined.columns else 0,
    )

    # 3. Write one file per commodity slug (commodity_name maps 1:1 to slug)
    s3 = get_thread_local_s3_client(aws_region)
    written = skipped = errors = 0

    for commodity_name, group in combined.groupby("commodity_name"):
        slug = str(commodity_name)
        silver_key = _silver_esr_key(slug)

        if str(args.force_overwrite).lower() != "true":
            try:
                s3.head_object(Bucket=bucket, Key=silver_key)
                logger.info("Silver already exists, skipping: %s", silver_key)
                skipped += 1
                continue
            except Exception:  # noqa: BLE001 — head_object 404 is expected for new files
                pass

        try:
            buf = io.BytesIO()
            group.reset_index(drop=True).to_parquet(
                buf, index=False, engine="pyarrow", compression="snappy"
            )
            s3.put_object(Bucket=bucket, Key=silver_key, Body=buf.getvalue())
            logger.info(
                "Wrote silver  commodity=%s  rows=%d  key=%s", slug, len(group), silver_key
            )
            written += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("Write failed for %s: %s", silver_key, exc)
            errors += 1

    logger.info(
        "ESR bronze→silver complete.  written=%d  skipped=%d  errors=%d",
        written, skipped, errors,
    )
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
