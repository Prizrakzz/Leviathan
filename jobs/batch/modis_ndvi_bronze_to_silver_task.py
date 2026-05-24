"""AWS Batch Fargate task: MODIS NDVI bronze Parquet → silver Parquet (z-scores).

Reads all bronze Parquet files for a commodity from S3, concatenates them into
a single DataFrame, computes NDVI z-scores against the 2000–2020 baseline using
``modis_ndvi_bronze_to_silver``, then writes silver partitions keyed by
(commodity, country, region, year).

Required args:
  --commodity   e.g. corn_cbot
  --bucket      S3 bucket name
  --aws_region  e.g. us-east-1

Optional args:
  --force_overwrite  true   (default: false — skip existing silver keys)
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.storage.paths import silver_modis_ndvi_key
from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys, s3_download_with_retry
from leviathan.transforms.bronze_to_silver.modis_ndvi import modis_ndvi_bronze_to_silver

logger = get_logger("modis_ndvi_bronze_to_silver")

_MAX_WORKERS = 64


# ── arg parsing ───────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    try:
        from awsglue.utils import getResolvedOptions
        raw = getResolvedOptions(sys.argv, ["commodity", "bucket", "aws_region"])
        ns = argparse.Namespace(**raw)
        ns.force_overwrite = "--force_overwrite" in sys.argv and (
            sys.argv[sys.argv.index("--force_overwrite") + 1].lower() == "true"
        )
        return ns
    except ImportError:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--commodity", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--aws_region", required=True)
    parser.add_argument("--force_overwrite", default="false")
    args = parser.parse_args()
    args.force_overwrite = args.force_overwrite.lower() == "true"
    return args


# ── bronze read ───────────────────────────────────────────────────────────────

def _read_one_bronze(bucket: str, key: str, aws_region: str) -> pd.DataFrame | None:
    try:
        s3_client = get_thread_local_s3_client(aws_region)
        raw_bytes = s3_download_with_retry(bucket, key, s3_client)
        return pd.read_parquet(io.BytesIO(raw_bytes))
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to read bronze file %s: %s", key, exc)
        return None


def _load_all_bronze(
    bucket: str, commodity: str, aws_region: str
) -> pd.DataFrame:
    prefix = f"bronze/weather/source=modis_ndvi/commodity={commodity}/"
    keys = list_s3_keys(bucket, prefix, suffix=".parquet", aws_region=aws_region)
    if not keys:
        raise FileNotFoundError(
            f"No bronze parquet files found at s3://{bucket}/{prefix} — "
            "run modis_ndvi_raw_to_bronze_task first"
        )
    logger.info("Found %d bronze files for commodity=%s", len(keys), commodity)

    frames: list[pd.DataFrame] = []
    failed = 0
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(_read_one_bronze, bucket, k, aws_region): k for k in keys}
        for fut in as_completed(futures):
            result = fut.result()
            if result is not None:
                frames.append(result)
            else:
                failed += 1

    if not frames:
        raise RuntimeError(f"All {len(keys)} bronze files failed to read for {commodity}")
    if failed:
        logger.warning("%d/%d bronze files failed to read — proceeding with %d", failed, len(keys), len(frames))

    df = pd.concat(frames, ignore_index=True)
    logger.info("Loaded %d rows from %d bronze files", len(df), len(frames))
    return df


# ── silver write ──────────────────────────────────────────────────────────────

def _write_silver_partition(
    s3_client,
    bucket: str,
    commodity: str,
    country: str,
    region: str,
    year: int,
    df_partition: pd.DataFrame,
    force_overwrite: bool,
) -> bool:
    key = silver_modis_ndvi_key(commodity, country, region, year)
    if not force_overwrite:
        try:
            s3_client.head_object(Bucket=bucket, Key=key)
            logger.debug("Skipping existing silver: %s", key)
            return False
        except s3_client.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] != "404":
                raise

    buf = io.BytesIO()
    df_partition.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3_client.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    logger.debug("Wrote silver: %s (%d rows)", key, len(df_partition))
    return True


def _write_all_silver(
    df: pd.DataFrame,
    commodity: str,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
) -> tuple[int, int]:
    groups = list(df.groupby(["country", "region", "year"]))
    logger.info(
        "Writing %d silver partitions for commodity=%s (force_overwrite=%s)…",
        len(groups), commodity, force_overwrite,
    )

    written = skipped = 0

    def _write(args):
        (country, region, year), grp = args
        s3_client = get_thread_local_s3_client(aws_region)
        return _write_silver_partition(
            s3_client, bucket,
            commodity, str(country), str(region), int(year),
            grp.reset_index(drop=True),
            force_overwrite,
        )

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(_write, g): g for g in groups}
        for fut in as_completed(futures):
            if fut.result():
                written += 1
            else:
                skipped += 1

    return written, skipped


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    args = _parse_args()
    logger.info(
        "Starting modis_ndvi bronze→silver | commodity=%s bucket=%s",
        args.commodity, args.bucket,
    )

    df = _load_all_bronze(args.bucket, args.commodity, args.aws_region)

    silver_df = modis_ndvi_bronze_to_silver(
        df, source_label=f"modis_ndvi/{args.commodity}"
    )
    logger.info("Silver transform produced %d rows", len(silver_df))

    if silver_df.empty:
        logger.warning("Silver transform returned empty DataFrame — nothing to write")
        return

    written, skipped = _write_all_silver(
        silver_df, args.commodity, args.bucket, args.aws_region, args.force_overwrite
    )
    logger.info(
        "Done. Written=%d  Skipped=%d  (commodity=%s)",
        written, skipped, args.commodity,
    )


main()
