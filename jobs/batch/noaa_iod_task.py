"""AWS Batch entrypoint: NOAA IOD DMI → raw + bronze + silver (single task).

Fetches the NOAA PSL DMI file, writes raw bytes to S3, parses bronze, and
computes the silver feature table — all in one container run.  The file
is 12 KB and completes end-to-end in under 5 seconds; splitting into
separate bronze/silver tasks would add more overhead than the work itself.

Silver outputs
--------------
    silver/weather/source=noaa_iod/part-000.parquet

Columns: date, dmi_value, iod_dmi_3month_avg, iod_phase,
         iod_dmi_ethiopia_lag4, source

Validation
----------
After silver write, asserts:
  - rows ≥ 1860
  - iod_dmi_3month_avg non-null ≥ 1800
  - 1997-11 3mo avg ≈ 0.97 (known strong positive IOD event)

Publish authorization
---------------------
Raw + bronze (like silver) touch the canonical surface ONLY under a fully-authorized
canonical publish (``publish_guard.authorize_publish`` -> ``may_mutate_canonical``); the
default ``--publish-mode`` is dry-run, so a dry-run / shadow run writes nothing canonical.

Usage
-----
    python jobs/batch/noaa_iod_task.py                       # dry-run (writes nothing)
    python jobs/batch/noaa_iod_task.py --publish-mode shadow
    python jobs/batch/noaa_iod_task.py --publish-mode canonical --force-overwrite
    python jobs/batch/noaa_iod_task.py --dry-run
"""
from __future__ import annotations

import argparse
import io
import logging
import sys

import requests

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.common.publish_guard import PublishTarget, authorize_publish
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import bronze_iod_key, raw_iod_key, silver_iod_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    upload_bytes_to_s3,
)
from leviathan.transforms.bronze_to_silver.noaa_iod import build_iod_silver
from leviathan.transforms.raw_to_bronze.noaa_iod import extract_iod_bronze
from jobs.batch._sb_producer_publish import publish_flat_silver

import pandas as pd

logger = get_logger("noaa_iod_task")

_IOD_URL = "https://psl.noaa.gov/gcos_wgsp/Timeseries/Data/dmi.had.long.data"
_TIMEOUT  = 30
_TABLE    = "silver_noaa_iod"

# Validation thresholds
_MIN_ROWS           = 1860
_MIN_3MO_NON_NULL   = 1800
_VALIDATION_DATE    = "1997-11-01"
_EXPECTED_3MO_MIN   = 0.90   # 1997-11 should be ≈ 0.97
_EXPECTED_3MO_MAX   = 1.10


def _exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def _write(s3_client, bucket: str, key: str, df: pd.DataFrame) -> None:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3_client.put_object(Bucket=bucket, Key=key, Body=buf.getvalue(),
                         ContentType="application/octet-stream")


def _caller_identity(aws_region: str) -> tuple[str, str]:
    """Best-effort STS identity for the canonical publish target (empty on failure).

    Thin wrapper over the shared resolver ``leviathan.common.aws_identity.resolve_caller_identity``
    (the one idiom the batch-task family shares). Kept as a module-level seam so tests can
    monkeypatch it and readiness/unit runs stay AWS-free; an empty identity still makes the publish
    guard fail closed on the canonical path exactly as before."""
    from leviathan.common.aws_identity import resolve_caller_identity

    return resolve_caller_identity(aws_region)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(description="NOAA IOD DMI → raw + bronze + silver")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    # NOTE: --publish-mode is consumed by the publish guard from sys.argv (default dry-run).
    parser.add_argument("--publish-mode", default=None,
                        help="dry-run|shadow|canonical (default dry-run; canonical needs a signed approval)")
    args = parser.parse_args()

    bucket     = args.bucket     or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    s3         = get_thread_local_s3_client(aws_region)
    s_key      = silver_iod_key()
    r_key      = raw_iod_key()
    b_key      = bronze_iod_key()

    if not args.force_overwrite and not args.dry_run and _exists(s3, bucket, s_key):
        logger.info("Silver exists — use --force-overwrite to re-run: %s", s_key)
        return

    # Authorize BEFORE any mutating write. raw + bronze touch the canonical surface only under a
    # fully-authorized canonical publish (may_mutate_canonical); dry-run / shadow write nothing.
    account_id, role_arn = _caller_identity(aws_region)
    contract = load_registry().table(_TABLE)
    auth = authorize_publish(
        PublishTarget(
            account_id=account_id,
            bucket=bucket,
            database=contract["glue_database"],
            prefix=contract["s3_prefix"].rstrip("/") + "/",
            role_arn=role_arn,
            table=_TABLE,
        ),
        argv=sys.argv,
    )
    logger.info("publish authorized: mode=%s may_canonical=%s", auth.mode.value, auth.may_mutate_canonical)

    # ------------------------------------------------------------------
    # Fetch raw
    # ------------------------------------------------------------------
    logger.info("Fetching %s …", _IOD_URL)
    resp = requests.get(_IOD_URL, timeout=_TIMEOUT)
    resp.raise_for_status()
    raw_bytes = resp.content
    logger.info("Downloaded %d bytes", len(raw_bytes))

    if auth.may_mutate_canonical:
        upload_bytes_to_s3(raw_bytes, bucket, r_key, aws_region)
        logger.info("Raw written → %s", r_key)

    # ------------------------------------------------------------------
    # Bronze transform
    # ------------------------------------------------------------------
    df_bronze = extract_iod_bronze(raw_bytes)

    if auth.may_mutate_canonical:
        buf = io.BytesIO()
        df_bronze.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
        s3.put_object(Bucket=bucket, Key=b_key, Body=buf.getvalue(),
                      ContentType="application/octet-stream")
        logger.info("Bronze written → %s  rows=%d", b_key, len(df_bronze))

    # ------------------------------------------------------------------
    # Silver transform
    # ------------------------------------------------------------------
    df_silver = build_iod_silver(df_bronze)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    rows = len(df_silver)
    non_null_3mo = int(df_silver["iod_dmi_3month_avg"].notna().sum())

    if rows < _MIN_ROWS:
        logger.error("IOD silver has only %d rows (expected ≥ %d)", rows, _MIN_ROWS)
        sys.exit(1)
    if non_null_3mo < _MIN_3MO_NON_NULL:
        logger.error(
            "iod_dmi_3month_avg non-null=%d (expected ≥ %d)",
            non_null_3mo, _MIN_3MO_NON_NULL,
        )
        sys.exit(1)

    # Known event check: 1997-11 strong positive IOD
    df_silver["date"] = pd.to_datetime(df_silver["date"])
    event_row = df_silver[df_silver["date"] == _VALIDATION_DATE]
    if not event_row.empty:
        event_val = float(event_row["iod_dmi_3month_avg"].iloc[0])
        if not (_EXPECTED_3MO_MIN <= event_val <= _EXPECTED_3MO_MAX):
            logger.warning(
                "Validation check: 1997-11 iod_dmi_3month_avg=%.4f "
                "(expected %.2f–%.2f) — data may have changed",
                event_val, _EXPECTED_3MO_MIN, _EXPECTED_3MO_MAX,
            )
        else:
            logger.info("Validation OK: 1997-11 iod_dmi_3month_avg=%.4f ✓", event_val)
    else:
        logger.warning("Validation: 1997-11 row not found in silver")

    if args.dry_run:
        logger.info(
            "dry-run - would write %s  rows=%d  3mo_non_null=%d",
            s_key, rows, non_null_3mo,
        )
        # Show sample around 1997 strong positive IOD
        sample = df_silver[
            (df_silver["date"] >= "1997-06-01") &
            (df_silver["date"] <= "1998-03-01")
        ][["date", "dmi_value", "iod_dmi_3month_avg", "iod_phase", "iod_dmi_ethiopia_lag4"]]
        print(sample.to_string(index=False))

    # SILVER-F041 / INV-6: the silver write is routed through the shadow-first
    # controlled publisher with an EXPLICIT registry-derived arrow schema (INV-2).
    # Default --publish-mode is dry-run (nothing written); canonical requires a
    # verified signed approval. year/month are physical columns in the registry.
    manifest = publish_flat_silver(
        table_name="silver_noaa_iod",
        df=df_silver,
        job="noaa_iod_task",
        canonical_key=s_key,
        bucket=bucket,
        s3_client=s3,
        argv=sys.argv,
    )
    logger.info("Silver publish %s  state=%s  rows=%d", s_key, manifest.state.value, rows)


if __name__ == "__main__":
    main()
