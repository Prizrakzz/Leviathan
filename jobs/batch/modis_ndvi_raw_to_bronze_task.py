"""AWS Batch Fargate task: MODIS NDVI raw CSV → bronze Parquet.

Reads one AppEEARS results CSV from S3 (raw tier), parses it into per-region
DataFrames using the raw_to_bronze transform, and writes one bronze Parquet
file per (commodity, country, region, year).

Each bronze file contains up to 23 rows — one row per 16-day MODIS composite
period within the calendar year.

Required args:
  --run_id      Fetch run identifier, e.g. 20260524T203000Z
  --group       Commodity group name, e.g. grains
  --bucket      S3 bucket name
  --aws_region  e.g. us-east-1

Optional args:
  --force_overwrite  true   (default: false — skip existing bronze keys)
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import pandas as pd
import yaml

from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_modis_ndvi_key, raw_modis_ndvi_key
from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys
from leviathan.transforms.raw_to_bronze.modis_ndvi import parse_appeears_csv

logger = get_logger("modis_ndvi_raw_to_bronze")


# ── arg parsing ───────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    # Support both argparse (local / Batch) and Glue getResolvedOptions
    try:
        from awsglue.utils import getResolvedOptions
        raw = getResolvedOptions(
            sys.argv, ["run_id", "group", "bucket", "aws_region"]
        )
        ns = argparse.Namespace(**raw)
        ns.force_overwrite = "--force_overwrite" in sys.argv and (
            sys.argv[sys.argv.index("--force_overwrite") + 1].lower() == "true"
        )
        return ns
    except ImportError:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--run_id", required=True)
    parser.add_argument("--group", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--aws_region", required=True)
    parser.add_argument("--force_overwrite", default="false")
    args = parser.parse_args()
    args.force_overwrite = args.force_overwrite.lower() == "true"
    return args


# ── geography helpers ─────────────────────────────────────────────────────────

def _build_region_to_country(bucket: str, aws_region: str) -> dict[str, str]:
    """Load all geography configs from S3 and return {region_id: country}."""
    s3 = get_thread_local_s3_client(aws_region)
    keys = list_s3_keys(bucket, "configs/geographies/", suffix="_regions.yaml", aws_region=aws_region)
    mapping: dict[str, str] = {}
    for key in keys:
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        cfg = yaml.safe_load(body)
        for region_block in cfg.get("regions", []):
            country = region_block["country"]
            for loc in region_block.get("locations", []):
                mapping[loc["region"]] = country
    logger.info("Built region→country mapping: %d entries", len(mapping))
    return mapping


# ── bronze write ──────────────────────────────────────────────────────────────

def _write_bronze_partition(
    s3_client,
    bucket: str,
    commodity: str,
    country: str,
    region: str,
    year: int,
    df_partition: pd.DataFrame,
    force_overwrite: bool,
) -> bool:
    """Write one bronze Parquet to S3.  Returns True if written, False if skipped."""
    key = bronze_modis_ndvi_key(commodity, country, region, year)

    if not force_overwrite:
        try:
            s3_client.head_object(Bucket=bucket, Key=key)
            logger.debug("Skipping existing bronze: %s", key)
            return False
        except s3_client.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] != "404":
                raise

    buf = io.BytesIO()
    df_partition.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3_client.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    logger.debug("Wrote bronze: %s (%d rows)", key, len(df_partition))
    return True


def _write_all_partitions(
    df: pd.DataFrame,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
) -> tuple[int, int]:
    """Fan out bronze writes across all (commodity, country, region, year) groups.

    Uses ThreadPoolExecutor so S3 puts happen concurrently.
    Returns (written_count, skipped_count).
    """
    groups = list(df.groupby(["commodity", "country", "region", "year"]))
    logger.info("Writing %d bronze partitions (force_overwrite=%s)…", len(groups), force_overwrite)

    written = skipped = 0

    def _write(args):
        (commodity, country, region, year), group_df = args
        s3_client = get_thread_local_s3_client(aws_region)
        return _write_bronze_partition(
            s3_client, bucket,
            str(commodity), str(country), str(region), int(year),
            group_df.reset_index(drop=True),
            force_overwrite,
        )

    with ThreadPoolExecutor(max_workers=64) as pool:
        futures = {pool.submit(_write, g): g for g in groups}
        for fut in as_completed(futures):
            if fut.result():
                written += 1
            else:
                skipped += 1

    return written, skipped


# ── raw CSV fetch ─────────────────────────────────────────────────────────────

def _fetch_raw_csv(bucket: str, run_id: str, group: str, aws_region: str) -> tuple[str, bytes]:
    """Download the raw CSV from S3.  Returns (file_name, csv_bytes)."""
    prefix = f"raw/weather/source=modis_ndvi/run_id={run_id}/group={group}/"
    keys = list_s3_keys(bucket, prefix, suffix=".csv", aws_region=aws_region)
    if not keys:
        raise FileNotFoundError(
            f"No raw CSV found at s3://{bucket}/{prefix}*.csv — "
            "run fetch_modis_ndvi.py first"
        )
    if len(keys) > 1:
        logger.warning("Multiple CSVs found for group=%s, using first: %s", group, keys[0])
    key = keys[0]
    s3 = get_thread_local_s3_client(aws_region)
    csv_bytes: bytes = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    file_name = key.split("/")[-1]
    logger.info("Downloaded raw CSV: %s (%d bytes)", key, len(csv_bytes))
    return file_name, csv_bytes


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    args = _parse_args()
    logger.info(
        "Starting modis_ndvi raw→bronze | run_id=%s group=%s bucket=%s",
        args.run_id, args.group, args.bucket,
    )

    # Download raw CSV
    _file_name, csv_bytes = _fetch_raw_csv(args.bucket, args.run_id, args.group, args.aws_region)

    # Build region→country mapping from geography configs in S3
    region_to_country = _build_region_to_country(args.bucket, args.aws_region)
    if not region_to_country:
        raise RuntimeError(
            "region_to_country mapping is empty — geography configs not found in S3 at "
            f"s3://{args.bucket}/configs/geographies/. Deploy configs before running R2B."
        )

    # Parse CSV → bronze DataFrame
    ingest_date = date.today().isoformat()
    df = parse_appeears_csv(csv_bytes, region_to_country, ingest_date)
    logger.info("Parsed DataFrame: %d rows, %d columns", len(df), len(df.columns))

    if df.empty:
        logger.warning("Empty DataFrame after parsing — nothing to write")
        return

    # Write bronze partitions
    written, skipped = _write_all_partitions(df, args.bucket, args.aws_region, args.force_overwrite)
    logger.info(
        "Done. Written=%d  Skipped=%d  (run_id=%s group=%s)",
        written, skipped, args.run_id, args.group,
    )


main()
