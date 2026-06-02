"""AWS Batch task: CONAB coffee XLS bronze Parquet to silver Parquet."""
from __future__ import annotations

import argparse
import io
import logging
import sys
from datetime import datetime, timezone

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import parse_hive_key, silver_conab_coffee_key
from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys, s3_download_with_retry
from leviathan.transforms.bronze_to_silver.conab_coffee import (
    OUTPUT_COLUMNS,
    transform_conab_coffee_bronze_to_silver,
)

logger = get_logger("conab_coffee_silver_task")

_BRONZE_PREFIX = "bronze/production/source=conab_xls/"


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _selected_years(value: str) -> set[int] | None:
    if value.strip().lower() == "all":
        return None
    return {int(item.strip()) for item in value.split(",") if item.strip()}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CONAB coffee bronze -> silver")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", default="false")
    parser.add_argument("--years", default="all", help="Comma-separated safra years or 'all'.")
    args = parser.parse_args()
    args.force_overwrite = _parse_bool(args.force_overwrite)
    return args


def _target_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except s3_client.exceptions.ClientError as exc:
        if exc.response["Error"]["Code"] == "404":
            return False
        raise


def _list_bronze_keys(bucket: str, aws_region: str, years: set[int] | None) -> list[str]:
    keys = [
        key
        for key in list_s3_keys(bucket, _BRONZE_PREFIX, aws_region=aws_region)
        if key.endswith(".parquet")
    ]
    if years is not None:
        keys = [
            key
            for key in keys
            if (year := parse_hive_key(key, "safra_year")) and int(year) in years
        ]
    return sorted(keys)


def _read_bronze(bucket: str, aws_region: str, years: set[int] | None) -> pd.DataFrame:
    s3 = get_thread_local_s3_client(aws_region)
    keys = _list_bronze_keys(bucket, aws_region, years)
    if not keys:
        return pd.DataFrame()

    frames = []
    for key in keys:
        raw_bytes = s3_download_with_retry(bucket, key, s3)
        df = pd.read_parquet(io.BytesIO(raw_bytes))
        frames.append(df)
        logger.info("read CONAB bronze rows=%d key=%s", len(df), key)
    return pd.concat(frames, ignore_index=True)


def _write_parquet(
    bucket: str,
    aws_region: str,
    key: str,
    df: pd.DataFrame,
    force_overwrite: bool,
) -> str:
    s3 = get_thread_local_s3_client(aws_region)
    if not force_overwrite and _target_exists(s3, bucket, key):
        logger.info("skipping existing silver partition: %s", key)
        return "skipped"

    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=buf.getvalue(),
        ContentType="application/octet-stream",
    )
    logger.info("wrote silver partition: %s rows=%d", key, len(df))
    return "written"


def _validate_uniqueness(df: pd.DataFrame) -> None:
    if df.empty:
        return
    key_cols = ["commodity", "safra_year", "survey_number", "region"]
    duplicate_mask = df.duplicated(subset=key_cols, keep=False)
    if duplicate_mask.any():
        preview = df.loc[duplicate_mask, key_cols].drop_duplicates().head(5).to_dict("records")
        raise ValueError(f"CONAB coffee silver has duplicate output rows: {preview}")


def _write_grouped(
    df: pd.DataFrame,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
) -> tuple[int, int]:
    written = skipped = 0
    if df.empty:
        return written, skipped

    for (commodity, safra_year), group in df.groupby(["commodity", "safra_year"], sort=True):
        key = silver_conab_coffee_key(int(safra_year), str(commodity))
        status = _write_parquet(
            bucket,
            aws_region,
            key,
            group[OUTPUT_COLUMNS].reset_index(drop=True),
            force_overwrite,
        )
        if status == "written":
            written += 1
        else:
            skipped += 1
    return written, skipped


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
    years = _selected_years(args.years)

    start = datetime.now(timezone.utc)
    bronze = _read_bronze(bucket, aws_region, years)
    silver = transform_conab_coffee_bronze_to_silver(bronze)
    _validate_uniqueness(silver)
    written, skipped = _write_grouped(silver, bucket, aws_region, args.force_overwrite)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        "Done CONAB coffee silver written=%d skipped=%d rows=%d elapsed=%.1fs",
        written,
        skipped,
        len(silver),
        elapsed,
    )


if __name__ == "__main__":
    main()
