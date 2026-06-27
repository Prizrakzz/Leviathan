"""AWS Batch task: USDA NASS crop-progress bronze Parquet to silver Parquet.

Reads NASS crop-progress bronze shards from S3, converts them to weekly wide
state/national feature rows, and writes partitions under
``silver/nass_crop_progress/``.
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import parse_hive_key, silver_nass_crop_progress_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.bronze_to_silver.usda_nass_crop_progress import (
    OUTPUT_COLUMNS,
    transform_nass_crop_progress_bronze_to_silver,
)

logger = get_logger("nass_crop_progress_silver_task")

_BRONZE_PREFIX = "bronze/production/source=usda_nass/series=crop_progress/"


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="USDA NASS crop progress bronze -> silver")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", default="false")
    parser.add_argument("--limit", type=int, default=0, help="Cap bronze keys for smoke tests")
    parser.add_argument(
        "--workers",
        type=_positive_int,
        default=8,
        help="Concurrent S3/parquet workers. Use 1 for sequential debugging.",
    )
    parser.add_argument(
        "--bronze-commodities",
        default="all",
        help="Comma-separated bronze commodity partitions or 'all'.",
    )
    parser.add_argument(
        "--years",
        default="all",
        help="Comma-separated years or 'all'.",
    )
    args = parser.parse_args()
    args.force_overwrite = _parse_bool(args.force_overwrite)
    return args


def _selected(value: str, allowed: set[str] | None) -> bool:
    return allowed is None or value in allowed


def _select_keys(
    keys: list[str],
    bronze_commodities: str,
    years: str,
    limit: int,
) -> list[str]:
    commodity_filter = None if bronze_commodities.strip().lower() == "all" else {
        item.strip() for item in bronze_commodities.split(",") if item.strip()
    }
    year_filter = None if years.strip().lower() == "all" else {
        item.strip() for item in years.split(",") if item.strip()
    }

    selected = [
        key
        for key in keys
        if key.startswith(_BRONZE_PREFIX)
        and _selected(parse_hive_key(key, "commodity"), commodity_filter)
        and _selected(parse_hive_key(key, "year"), year_filter)
    ]
    selected.sort()
    return selected[:limit] if limit else selected


def _load_and_transform(bucket: str, key: str, aws_region: str) -> pd.DataFrame:
    s3 = get_thread_local_s3_client(aws_region)
    raw_bytes = s3_download_with_retry(bucket, key, s3)
    bronze = pd.read_parquet(io.BytesIO(raw_bytes))
    silver = transform_nass_crop_progress_bronze_to_silver(bronze)
    logger.info("transformed key=%s bronze_rows=%d silver_rows=%d", key, len(bronze), len(silver))
    return silver


def _transform_keys(
    bucket: str,
    keys: list[str],
    aws_region: str,
    workers: int,
) -> tuple[list[pd.DataFrame], int]:
    frames: list[pd.DataFrame] = []
    errors = 0
    completed = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_key = {
            executor.submit(_load_and_transform, bucket, key, aws_region): key
            for key in keys
        }
        for future in as_completed(future_to_key):
            key = future_to_key[future]
            completed += 1
            try:
                silver = future.result()
            except Exception as exc:  # noqa: BLE001
                logger.error("failed to transform %s: %s", key, exc)
                errors += 1
                continue
            if not silver.empty:
                frames.append(silver)
            logger.info("transform progress=%d/%d key=%s", completed, len(keys), key)

    return frames, errors


def _target_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except s3_client.exceptions.ClientError as exc:
        if exc.response["Error"]["Code"] == "404":
            return False
        raise


def _write_partition(
    bucket: str,
    aws_region: str,
    commodity: str,
    year: int,
    df: pd.DataFrame,
    force_overwrite: bool,
) -> str:
    s3_client = get_thread_local_s3_client(aws_region)
    key = silver_nass_crop_progress_key(commodity, year)
    if not force_overwrite and _target_exists(s3_client, bucket, key):
        logger.info("skipping existing silver partition: %s", key)
        return "skipped"

    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=buf.getvalue(),
        ContentType="application/octet-stream",
    )
    logger.info("wrote silver partition: %s rows=%d", key, len(df))
    return "written"


def _write_partitions(
    final: pd.DataFrame,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
    workers: int,
) -> tuple[int, int]:
    groups = [
        (str(commodity), int(year), group.reset_index(drop=True))
        for (commodity, year), group in final.groupby(["leviathan_slug", "year"])
    ]
    written = skipped = errors = completed = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_partition = {
            executor.submit(
                _write_partition,
                bucket,
                aws_region,
                commodity,
                year,
                group,
                force_overwrite,
            ): (commodity, year)
            for commodity, year, group in groups
        }
        for future in as_completed(future_to_partition):
            commodity, year = future_to_partition[future]
            completed += 1
            try:
                status = future.result()
            except Exception as exc:  # noqa: BLE001
                logger.error("failed to write commodity=%s year=%s: %s", commodity, year, exc)
                errors += 1
                continue
            if status == "written":
                written += 1
            else:
                skipped += 1
            logger.info(
                "write progress=%d/%d commodity=%s year=%s status=%s",
                completed,
                len(groups),
                commodity,
                year,
                status,
            )

    if errors:
        raise SystemExit(1)
    return written, skipped


def _validate_final_uniqueness(df: pd.DataFrame) -> None:
    duplicate_mask = df.duplicated(
        subset=["leviathan_slug", "state", "year", "date"],
        keep=False,
    )
    if duplicate_mask.any():
        dupes = df.loc[
            duplicate_mask,
            ["leviathan_slug", "state", "year", "date"],
        ].drop_duplicates()
        preview = dupes.head(5).to_dict("records")
        raise ValueError(f"NASS crop progress silver has duplicate output rows: {preview}")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    load_env()
    args = _parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    all_keys = list_s3_keys(bucket, _BRONZE_PREFIX, suffix=".parquet", aws_region=aws_region)
    keys = _select_keys(all_keys, args.bronze_commodities, args.years, args.limit)
    if not keys:
        raise FileNotFoundError(f"No NASS crop-progress bronze parquet files found under {_BRONZE_PREFIX}")

    logger.info(
        "NASS crop progress silver task bucket=%s bronze_keys=%d force=%s workers=%d",
        bucket,
        len(keys),
        args.force_overwrite,
        args.workers,
    )

    start = datetime.now(timezone.utc)
    frames, errors = _transform_keys(bucket, keys, aws_region, args.workers)

    if errors:
        raise SystemExit(1)
    if not frames:
        logger.warning("All selected bronze keys transformed to empty silver outputs")
        return

    final = pd.concat(frames, ignore_index=True)
    final = final[OUTPUT_COLUMNS].drop_duplicates().reset_index(drop=True)
    _validate_final_uniqueness(final)

    written, skipped = _write_partitions(
        final,
        bucket,
        aws_region,
        args.force_overwrite,
        args.workers,
    )

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        "Done NASS crop progress silver written=%d skipped=%d rows=%d elapsed=%.1fs",
        written,
        skipped,
        len(final),
        elapsed,
    )


if __name__ == "__main__":
    main()
