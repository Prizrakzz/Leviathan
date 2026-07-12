"""Deproject + within-year COMPACTION job for the weather trio (SILVER-F047; execution gated to BF-W1).

Reads the projected MONTH-grain silver for one weather (source, commodity), buckets objects by the
``year=`` segment, merges each year's twelve tiny objects into ONE registered-partition object at
``commodity=<c>/year=<y>/part-000.parquet`` (the coarse ``[commodity, year]`` grain), and publishes
THROUGH the F015 shadow publisher (shadow-first, atomic) + the F013 registered-partition publisher
(exact/repairable). It is the write-through path F045's value rebuild uses so the rebuild fixes the NaN
values AND collapses the ~590k tiny-file layout in one wave, instead of the plain projected
``--force-overwrite`` that re-mints the tiny files.

GATED: ``--publish-mode`` defaults to ``dry-run`` (nothing written, plan only). ``shadow`` writes the
compacted objects to a non-canonical shadow prefix and validates them. ``canonical`` is refused without
a signed post-R4 approval (publish_guard). This job never issues an Athena query and never re-enables
projection (INV-3). The de-projection FLIP (removing the projection.* table params) is a separate,
independently-gated step -- ``jobs/utils/deproject_glue_table.py --flip`` -- run only after this job's
registered partitions exist and are validated.

Usage (all gated):
    python jobs/batch/compact_weather_silver_task.py --source chirps --commodity arabica_coffee
    python jobs/batch/compact_weather_silver_task.py --source chirps --commodity all --publish-mode shadow
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
from leviathan.common.publish_guard import PublishTarget, authorize_publish
from leviathan.silver.publisher import PublishStrategy, ShadowPublisher, StagedObject, ValidationHooks
from leviathan.storage.paths import parse_hive_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.bronze_to_silver.weather_compaction import (
    compact_partition,
    compacted_bytes,
    compaction_plan,
)

logger = get_logger("compact_weather_silver")

_SILVER_WEATHER = "silver/weather"
_WORKERS = 32
_SOURCE_TO_TABLE = {
    "nasa_power": "silver_nasa_power",
    "chirps": "silver_chirps",
    "cpc_soil": "silver_cpc_soil",
}


def _source_prefix(source: str, commodity: str) -> str:
    return f"{_SILVER_WEATHER}/source={source}/commodity={commodity}/"


def _year_from_key(key: str) -> int | None:
    try:
        raw = parse_hive_key(key, "year")
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _discover_commodities(bucket: str, source: str, aws_region: str) -> list[str]:
    keys = list_s3_keys(bucket, f"{_SILVER_WEATHER}/source={source}/", suffix=".parquet",
                        aws_region=aws_region)
    return sorted({s for s in (parse_hive_key(k, "commodity") for k in keys) if s})


def _read_frame(bucket: str, key: str, aws_region: str) -> pd.DataFrame | None:
    try:
        s3 = get_thread_local_s3_client(aws_region)
        data = s3_download_with_retry(bucket, key, s3)
        return pq.read_table(io.BytesIO(data)).to_pandas()
    except Exception as exc:  # noqa: BLE001 -- per-file failure logged, loop continues
        logger.error("failed to read %s: %s", key, exc)
        return None


def _compact_one_commodity(bucket: str, source: str, table: str, commodity: str, aws_region: str,
                           auth, glue_client) -> dict:
    prefix = _source_prefix(source, commodity)
    keys = list_s3_keys(bucket, prefix, suffix=".parquet", aws_region=aws_region)
    if not keys:
        logger.info("no projected silver for source=%s commodity=%s", source, commodity)
        return {"commodity": commodity, "units": 0, "state": "empty"}

    by_year: dict[int, list[str]] = defaultdict(list)
    for k in keys:
        y = _year_from_key(k)
        if y is not None:
            by_year[y].append(k)
    units = compaction_plan(source, table, commodity, by_year)
    logger.info("source=%s commodity=%s: %d month objects -> %d (commodity,year) units",
                source, commodity, len(keys), len(units))

    staged: list[StagedObject] = []
    for unit in units:
        frames = [_read_frame(bucket, k, aws_region) for k in by_year[unit.year]]
        frames = [f for f in frames if f is not None and not f.empty]
        if not frames:
            continue
        compacted = compact_partition(frames, table)
        body = compacted_bytes(compacted, table)
        nonnull = _nonnull_fraction(compacted)
        staged.append(StagedObject(
            canonical_key=unit.canonical_key,
            body=body,
            partition_values=unit.partition_values,
            row_count=len(compacted),
            null_metrics=nonnull,
        ))

    s3_client = get_thread_local_s3_client(aws_region)
    canonical_root = f"s3://{bucket}/{_SILVER_WEATHER}/source={source}"
    publisher = ShadowPublisher(
        job="compact_weather_silver", table=table, database="leviathan_dev", bucket=bucket,
        canonical_root=canonical_root, auth=auth, s3_client=s3_client, glue_client=glue_client,
        strategy=PublishStrategy.REGISTERED,
        validation=ValidationHooks(min_rows=1, min_nonnull_frac=0.0),
        run_id=f"{table}-{commodity}",
    )
    manifest = publisher.run(staged)
    logger.info("source=%s commodity=%s: publish %s (%d objects, mode=%s)",
                source, commodity, manifest.state.value, len(staged), auth.mode.value)
    return {"commodity": commodity, "units": len(staged), "state": manifest.state.value,
            "file_collapse": {"from_month_objects": len(keys), "to_year_objects": len(staged)}}


def _nonnull_fraction(df: pd.DataFrame) -> dict:
    out: dict[str, float] = {}
    for col in ("value", "precipitation_mm", "temperature_2m_mean_c"):
        if col in df.columns and len(df):
            out[col] = float(df[col].notna().mean())
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s", stream=sys.stderr)
    load_env()
    parser = argparse.ArgumentParser(description="deproject + within-year compact the weather trio")
    parser.add_argument("--source", required=True, choices=sorted(_SOURCE_TO_TABLE))
    parser.add_argument("--commodity", default="all")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--publish-mode", default="dry-run")
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    table = _SOURCE_TO_TABLE[args.source]

    import boto3
    sts = boto3.client("sts", region_name=aws_region)
    ident = sts.get_caller_identity()
    auth = authorize_publish(
        PublishTarget(account_id=ident["Account"], bucket=bucket, database="leviathan_dev",
                      prefix=f"{_SILVER_WEATHER}/source={args.source}/", role_arn=ident["Arn"],
                      table=table),
        argv=sys.argv,
    )
    glue_client = boto3.client("glue", region_name=aws_region) if auth.may_mutate_canonical else None

    if args.commodity.strip().lower() == "all":
        commodities = _discover_commodities(bucket, args.source, aws_region)
    else:
        commodities = [c.strip() for c in args.commodity.split(",") if c.strip()]

    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(_compact_one_commodity, bucket, args.source, table, c, aws_region,
                            auth, glue_client): c for c in commodities}
        for fut in as_completed(futs):
            results.append(fut.result())
    total_units = sum(r["units"] for r in results)
    logger.info("DONE source=%s: %d commodities, %d compacted (commodity,year) objects, mode=%s",
                args.source, len(commodities), total_units, auth.mode.value)


if __name__ == "__main__":
    main()
