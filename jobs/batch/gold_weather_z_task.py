"""AWS Batch Fargate task: silver weather -> gold_weather_z (tall, monthly, PIT-safe z-anomalies).

Reads the silver weather LONG parquet DIRECTLY from S3 (the load_pg_numbers no-Athena pattern: the Glue
catalog is never touched here), pruned by commodity, and writes one tall gold parquet per commodity to
gold/weather_z/{slug}.parquet. The compute core lives in leviathan.transforms.gold.weather_z
(pure, unit-tested on synthetic frames); this file is only the S3 I/O + orchestration shell.

  * nasa_power (silver/weather/source=nasa_power/commodity={slug}/...): tmax/tmin -> heat/gdd/tmax/frost.
  * chirps     (silver/weather/source=chirps/commodity={slug}/...):     precip    -> drought.

The gold table is NON-PROJECTED and NON-PARTITIONED (Glue DDL sql/athena/ddl/gold_weather_z.sql), so there
is no per-partition ADD on refresh and no LIST-storm enumeration surface -- the DDL registration + a
load_pg_numbers mirror run are the (USER-GATED) cloud steps; this job only writes the parquet.

WARNING (D-W4 sizing risk): the INTERMEDIATE read of raw daily weather is heavy (country x region x day x
years per commodity). The gold OUTPUT is tiny (region x year_month x few metrics), but size the
Fargate/Batch job for the transform, not the output. Processed one commodity at a time so memory is bounded.

Usage:
    python jobs/batch/gold_weather_z_task.py --commodity corn_cbot
    python jobs/batch/gold_weather_z_task.py --commodity all --force-overwrite true
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
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
from leviathan.transforms.gold.weather_z import compute_weather_z

logger = get_logger("gold_weather_z")

_SILVER_WEATHER = "silver/weather"
_WORKERS = 32


def _source_prefix(source: str, commodity: str) -> str:
    return f"{_SILVER_WEATHER}/source={source}/commodity={commodity}/"


def _gold_key(commodity: str) -> str:
    return f"gold/weather_z/{commodity}.parquet"


def _discover_commodities(bucket: str, aws_region: str) -> list[str]:
    """Distinct commodity slugs present under silver/weather/source=nasa_power/."""
    keys = list_s3_keys(bucket, f"{_SILVER_WEATHER}/source=nasa_power/", suffix=".parquet",
                        aws_region=aws_region)
    slugs = {parse_hive_key(k, "commodity") for k in keys}
    return sorted(s for s in slugs if s)


def _read_long(bucket: str, source: str, commodity: str, aws_region: str) -> pd.DataFrame | None:
    """Read + concat every silver parquet under one (source, commodity) prefix into a long frame."""
    keys = list_s3_keys(bucket, _source_prefix(source, commodity), suffix=".parquet",
                        aws_region=aws_region)
    if not keys:
        logger.info("no %s silver for commodity=%s", source, commodity)
        return None

    def _one(key: str) -> pd.DataFrame | None:
        try:
            s3 = get_thread_local_s3_client(aws_region)
            data = s3_download_with_retry(bucket, key, s3)
            return pq.read_table(io.BytesIO(data)).to_pandas()
        except Exception as exc:  # noqa: BLE001 — per-file failures logged; loop continues
            logger.error("failed to read %s: %s", key, exc)
            return None

    frames: list[pd.DataFrame] = []
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        for fut in as_completed({pool.submit(_one, k) for k in keys}):
            df = fut.result()
            if df is not None and not df.empty:
                frames.append(df)
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


def _process_commodity(bucket: str, commodity: str, aws_region: str, force_overwrite: bool) -> int:
    s3 = get_thread_local_s3_client(aws_region)
    gold_key = _gold_key(commodity)
    if not force_overwrite:
        try:
            s3.head_object(Bucket=bucket, Key=gold_key)
            logger.info("gold already exists, skipping: %s", gold_key)
            return 0
        except Exception:  # noqa: BLE001 — 404 is expected for a new commodity
            pass

    nasa = _read_long(bucket, "nasa_power", commodity, aws_region)
    chirps = _read_long(bucket, "chirps", commodity, aws_region)
    if nasa is None and chirps is None:
        logger.warning("no silver weather for commodity=%s -- nothing to compute", commodity)
        return 0

    gold = compute_weather_z(commodity, nasa_power=nasa, chirps=chirps)
    if gold.empty:
        logger.warning("commodity=%s produced 0 gold rows (thin history?)", commodity)
        return 0

    buf = io.BytesIO()
    gold.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3.put_object(Bucket=bucket, Key=gold_key, Body=buf.getvalue())
    logger.info("wrote gold  commodity=%s  rows=%d  metrics=%s  key=%s",
                commodity, len(gold), sorted(gold["metric"].unique()), gold_key)
    return len(gold)


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s", stream=sys.stderr)
    load_env()

    parser = argparse.ArgumentParser(description="silver weather -> gold_weather_z")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--commodity", default="all",
                        help="comma-separated slugs, or 'all' to discover from silver/weather")
    parser.add_argument("--force-overwrite", default="false", dest="force_overwrite")
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    force = str(args.force_overwrite).lower() == "true"

    if args.commodity.strip().lower() == "all":
        commodities = _discover_commodities(bucket, aws_region)
    else:
        commodities = [c.strip() for c in args.commodity.split(",") if c.strip()]
    logger.info("gold_weather_z: %d commodities", len(commodities))

    total, failures = 0, []
    for commodity in commodities:
        try:
            total += _process_commodity(bucket, commodity, aws_region, force)
        except Exception as exc:  # noqa: BLE001 — one commodity's failure must not kill the rest
            logger.error("[%s] FAILED: %s: %s", commodity, type(exc).__name__, str(exc)[:300])
            failures.append(commodity)
    logger.info("DONE: %d gold rows across %d commodities%s", total, len(commodities),
                f"  FAILURES: {failures}" if failures else "")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
