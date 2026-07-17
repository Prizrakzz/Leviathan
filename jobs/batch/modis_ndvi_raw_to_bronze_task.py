"""AWS Batch Fargate task: MODIS NDVI raw CSV -> bronze Parquet.

Reads one AppEEARS results CSV from S3 (raw tier) per commodity group, parses it
into per-region DataFrames using the raw_to_bronze transform, and writes one
bronze Parquet file per (commodity, country, region, year).

Each bronze file contains up to 23 rows -- one row per 16-day MODIS composite
period within the calendar year.

Thin-contract invocation (A-Wave-3 retrofit)
--------------------------------------------
The descriptor invokes this task with NO args; every argument has a safe default
so the chain never argparse-exits:

  --run_id      Fetch run identifier, e.g. 20260524T183717Z.
                DEFAULT: the MAX run_id partition discovered under the raw prefix
                ``raw/weather/source=modis_ndvi/`` (run_ids are ISO-UTC stamps, so
                lexical max == chronological latest). Fails closed if none exist.
  --group       Commodity group name, e.g. grains.
                DEFAULT: ``all`` -- iterate every group in
                ``configs/sources/modis_ndvi.yaml`` (commodity_groups keys); if
                that config is unavailable, fall back to the group= partitions
                actually present under the resolved run_id.
  --bucket      S3 bucket name.            DEFAULT: ``$LEVIATHAN_BUCKET``.
  --aws_region  e.g. us-east-1.            DEFAULT: ``$AWS_REGION``.

Single-group invocation is unchanged: pass ``--run_id X --group grains --bucket B
--aws_region R`` and only that group is processed.

Optional args:
  --force_overwrite  true   (default: false -- skip existing bronze keys)
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import pandas as pd
import yaml
from leviathan.common.config import get_required_env, load_env, load_yaml
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_modis_ndvi_key, parse_hive_key
from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys
from leviathan.transforms.raw_to_bronze.modis_ndvi import parse_appeears_csv

logger = get_logger("modis_ndvi_raw_to_bronze")

_RAW_PREFIX = "raw/weather/source=modis_ndvi/"
_SOURCE_CONFIG = "configs/sources/modis_ndvi.yaml"


# -- run_id / group discovery (thin-contract defaults) --------------------------

def _discover_max_run_id(bucket: str, aws_region: str) -> str:
    """Return the MAX run_id partition under the raw prefix (fails closed if none).

    MODIS run_ids are ISO-UTC stamps (e.g. ``20260524T183717Z``), so the lexical
    max is the chronologically latest fetch run. Only run_ids with at least one
    ``group=`` data object count: the fetcher mirrors a ``_tasks.json`` checkpoint
    into the run prefix at SUBMISSION time (before any CSV exists), so a crashed
    submission must never be discovered as the newest data partition."""
    keys = list_s3_keys(bucket, _RAW_PREFIX, aws_region=aws_region)
    run_ids = sorted(
        {r for r in (parse_hive_key(k, "run_id") for k in keys if "/group=" in k) if r}
    )
    if not run_ids:
        raise FileNotFoundError(
            f"No MODIS raw run_id partitions under s3://{bucket}/{_RAW_PREFIX} -- "
            "run fetch_modis_ndvi.py first"
        )
    latest = run_ids[-1]
    logger.info("discovered %d run_id partition(s); using MAX=%s", len(run_ids), latest)
    return latest


def _groups_from_config() -> list[str]:
    """Commodity-group names from configs/sources/modis_ndvi.yaml (empty list if absent)."""
    try:
        cfg = load_yaml(_SOURCE_CONFIG)
    except FileNotFoundError:
        logger.info("source config %s not found; will derive groups from raw partitions", _SOURCE_CONFIG)
        return []
    return list((cfg.get("commodity_groups") or {}).keys())


def _discover_groups_from_raw(bucket: str, run_id: str, aws_region: str) -> list[str]:
    """Distinct group= partitions present under the resolved run_id (config fallback)."""
    prefix = f"{_RAW_PREFIX}run_id={run_id}/"
    keys = list_s3_keys(bucket, prefix, aws_region=aws_region)
    return sorted({g for g in (parse_hive_key(k, "group") for k in keys) if g})


def _resolve_groups(bucket: str, run_id: str, group_arg: str, aws_region: str) -> list[str]:
    """Resolve the group list: a single named group, or every group when ``all``."""
    if group_arg and group_arg.strip().lower() != "all":
        return [group_arg.strip()]

    groups = _groups_from_config()
    if groups:
        logger.info("group=all -> %d group(s) from %s: %s", len(groups), _SOURCE_CONFIG, groups)
        return groups

    groups = _discover_groups_from_raw(bucket, run_id, aws_region)
    if not groups:
        raise FileNotFoundError(
            f"group=all but no groups found in {_SOURCE_CONFIG} nor under "
            f"s3://{bucket}/{_RAW_PREFIX}run_id={run_id}/"
        )
    logger.info("group=all -> %d group(s) from raw partitions: %s", len(groups), groups)
    return groups


# -- geography helpers ----------------------------------------------------------

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
    logger.info("Built region->country mapping: %d entries", len(mapping))
    return mapping


# -- bronze write ---------------------------------------------------------------

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
    logger.info("Writing %d bronze partitions (force_overwrite=%s)...", len(groups), force_overwrite)

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


# -- raw CSV fetch --------------------------------------------------------------

def _fetch_raw_csv(bucket: str, run_id: str, group: str, aws_region: str) -> tuple[str, bytes]:
    """Download the raw CSV from S3.  Returns (file_name, csv_bytes)."""
    prefix = f"raw/weather/source=modis_ndvi/run_id={run_id}/group={group}/"
    keys = list_s3_keys(bucket, prefix, suffix=".csv", aws_region=aws_region)
    if not keys:
        raise FileNotFoundError(
            f"No raw CSV found at s3://{bucket}/{prefix}*.csv -- "
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


# -- per-group processing -------------------------------------------------------

def _process_group(
    bucket: str,
    run_id: str,
    group: str,
    aws_region: str,
    region_to_country: dict[str, str],
    force_overwrite: bool,
) -> tuple[int, int]:
    """Fetch + parse + write one commodity group. Returns (written, skipped)."""
    _file_name, csv_bytes = _fetch_raw_csv(bucket, run_id, group, aws_region)

    ingest_date = date.today().isoformat()
    df = parse_appeears_csv(csv_bytes, region_to_country, ingest_date)
    logger.info("group=%s parsed DataFrame: %d rows, %d columns", group, len(df), len(df.columns))

    if df.empty:
        logger.warning("group=%s empty DataFrame after parsing -- nothing to write", group)
        return 0, 0

    written, skipped = _write_all_partitions(df, bucket, aws_region, force_overwrite)
    logger.info("group=%s done: written=%d skipped=%d", group, written, skipped)
    return written, skipped


# -- arg parsing ----------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MODIS NDVI raw CSV -> bronze Parquet")
    parser.add_argument("--run_id", default=None,
                        help="raw run_id partition (default: MAX discovered under the raw prefix)")
    parser.add_argument("--group", default="all",
                        help="commodity group name, or 'all' to iterate every group (default: all)")
    parser.add_argument("--bucket", default=None, help="S3 bucket (default: $LEVIATHAN_BUCKET)")
    parser.add_argument("--aws_region", default=None, help="AWS region (default: $AWS_REGION)")
    parser.add_argument("--force_overwrite", default="false")
    args = parser.parse_args()
    args.force_overwrite = str(args.force_overwrite).lower() == "true"
    return args


# -- main -----------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    load_env()
    args = _parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    run_id = args.run_id or _discover_max_run_id(bucket, aws_region)
    groups = _resolve_groups(bucket, run_id, args.group, aws_region)
    logger.info(
        "Starting modis_ndvi raw->bronze | run_id=%s groups=%d bucket=%s",
        run_id, len(groups), bucket,
    )

    # Build region->country mapping once (shared across every group).
    region_to_country = _build_region_to_country(bucket, aws_region)
    if not region_to_country:
        raise RuntimeError(
            "region_to_country mapping is empty -- geography configs not found in S3 at "
            f"s3://{bucket}/configs/geographies/. Deploy configs before running R2B."
        )

    total_written = total_skipped = 0
    failures: list[str] = []
    for group in groups:
        try:
            written, skipped = _process_group(
                bucket, run_id, group, aws_region, region_to_country, args.force_overwrite
            )
            total_written += written
            total_skipped += skipped
        except Exception as exc:  # noqa: BLE001 -- one group's failure must not kill the rest
            logger.error("[group=%s] FAILED: %s: %s", group, type(exc).__name__, str(exc)[:300])
            failures.append(group)

    logger.info(
        "Done. run_id=%s groups=%d written=%d skipped=%d%s",
        run_id, len(groups), total_written, total_skipped,
        f"  FAILURES={failures}" if failures else "",
    )
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
