"""AWS Batch/Fargate task: MODIS NDVI bronze Parquet -> silver (shadow-first, SILVER-F015/INV-6).

Reads all bronze Parquet files for a commodity from S3, concatenates them into a
single DataFrame, computes NDVI z-scores against the 2000-2020 baseline using
``modis_ndvi_bronze_to_silver``, then publishes silver objects keyed by
(commodity, country, region, year).

Publish contract (A-W4 CLASS-B retrofit)
----------------------------------------
``silver_modis_ndvi`` is registered as a FLAT table (``partition_keys: []``,
discovered by LIST) whose producer nonetheless writes MANY objects (one per
country/region/year under the ``commodity=`` prefix). The flat-table
``build_flat_publish`` path assembles a SINGLE canonical object, so it does not
fit this multi-object producer; the write routes through the SILVER-F015
shadow-first publisher (:class:`leviathan.silver.publisher.ShadowPublisher`, FLAT
strategy) directly -- the quandl-CHRIS pattern -- with the task's own parquet
writer and a StagedObject per output. ``--publish-mode`` (default ``dry-run``)
resolves through the publish guard:

  * dry-run   : nothing is written anywhere.
  * shadow    : each object is staged ONLY under
                ``silver/weather/source=modis_ndvi/_shadow/``; canonical is untouched.
  * canonical : shadow-stage -> validate -> promote, ONLY with a verified signed approval.

This replaces the former latest-only ``put_object`` overwrite so a red rebuild
gate can protect the canonical writes (FLAT cataloging is a no-op; objects are
discovered by LIST).

Required args:
  --commodity   e.g. corn_cbot
  --bucket      S3 bucket name
  --aws_region  e.g. us-east-1

Optional args:
  --force_overwrite  true             (default: false -- skip existing canonical keys)
  --publish-mode     {dry-run,shadow,canonical}   (default: dry-run)
  --role-arn / --account-id           (canonical target identity; else best-effort STS)
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.silver.flat_producer import authorize_for_contract
from leviathan.silver.publisher import (
    ManifestState,
    PublishStrategy,
    ShadowPublisher,
    StagedObject,
    ValidationHooks,
)
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import silver_modis_ndvi_key
from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys, s3_download_with_retry
from leviathan.transforms.bronze_to_silver.modis_ndvi import modis_ndvi_bronze_to_silver

logger = get_logger("modis_ndvi_bronze_to_silver")

_MAX_WORKERS = 64
_TABLE = "silver_modis_ndvi"
_JOB = "modis_ndvi_silver"


# -- arg parsing ----------------------------------------------------------------

def _sysargv_flag(name: str, default: str = "") -> str:
    """Read ``--name VALUE`` from sys.argv (Glue getResolvedOptions branch helper)."""
    if name in sys.argv:
        idx = sys.argv.index(name)
        if idx + 1 < len(sys.argv):
            return sys.argv[idx + 1]
    return default


def _parse_args() -> argparse.Namespace:
    try:
        from awsglue.utils import getResolvedOptions
        raw = getResolvedOptions(sys.argv, ["commodity", "bucket", "aws_region"])
        ns = argparse.Namespace(**raw)
        ns.force_overwrite = _sysargv_flag("--force_overwrite", "false").lower() == "true"
        ns.publish_mode = _sysargv_flag("--publish-mode", "dry-run")
        ns.dry_run = "--dry-run" in sys.argv
        ns.role_arn = _sysargv_flag("--role-arn", "")
        ns.account_id = _sysargv_flag("--account-id", "")
        return ns
    except ImportError:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--commodity", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--aws_region", required=True)
    parser.add_argument("--force_overwrite", default="false")
    parser.add_argument("--dry-run", action="store_true",
                        help="Alias for --publish-mode dry-run (writes nothing).")
    parser.add_argument("--publish-mode", default="dry-run",
                        choices=["dry-run", "shadow", "canonical"], dest="publish_mode",
                        help="dry-run|shadow|canonical (default dry-run; canonical needs a signed approval)")
    parser.add_argument("--role-arn", default="", dest="role_arn")
    parser.add_argument("--account-id", default="", dest="account_id")
    args = parser.parse_args()
    args.force_overwrite = args.force_overwrite.lower() == "true"
    return args


# -- bronze read ----------------------------------------------------------------

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
            f"No bronze parquet files found at s3://{bucket}/{prefix} -- "
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
        logger.warning("%d/%d bronze files failed to read -- proceeding with %d", failed, len(keys), len(frames))

    df = pd.concat(frames, ignore_index=True)
    logger.info("Loaded %d rows from %d bronze files", len(df), len(frames))
    return df


# -- shadow-first publish (A-W4 CLASS-B retrofit) -------------------------------

def _exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001
        return False


def _caller_identity(aws_region: str) -> tuple[str, str]:
    """Best-effort STS identity for the canonical publish target (empty on failure)."""
    try:
        import boto3
        ident = boto3.client("sts", region_name=aws_region).get_caller_identity()
        return ident.get("Account", ""), ident.get("Arn", "")
    except Exception as exc:  # noqa: BLE001 -- dry-run / shadow must not require live credentials
        logger.info("STS identity unavailable (%s); using empty target (dry-run/shadow only)", exc)
        return "", ""


def _partition_body(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    return buf.getvalue()


def _publish_modis(
    silver_df: pd.DataFrame,
    commodity: str,
    contract: dict,
    auth,
    s3_client,
    bucket: str,
    *,
    force_overwrite: bool,
) -> ManifestState | None:
    """Publish one silver object per (country, region, year) through the shadow-first publisher
    (FLAT strategy -- objects discovered by LIST, no Glue partition registration). Returns the
    manifest state, or ``None`` when every object is a skipped existing canonical object."""
    staged: list[StagedObject] = []
    skipped = 0
    for (country, region, year), grp in silver_df.groupby(["country", "region", "year"]):
        canonical_key = silver_modis_ndvi_key(commodity, str(country), str(region), int(year))
        if (
            not force_overwrite
            and auth.may_mutate_canonical
            and s3_client is not None
            and _exists(s3_client, bucket, canonical_key)
        ):
            skipped += 1
            continue
        staged.append(StagedObject(
            canonical_key=canonical_key,
            body=_partition_body(grp.reset_index(drop=True)),
            partition_values=[str(country), str(region), str(int(year))],
            row_count=len(grp),
        ))

    if not staged:
        logger.info("modis_ndvi: no objects to publish (skipped=%d existing)", skipped)
        return None

    manifest_store = None if s3_client is not None else (lambda _k, _b: None)
    publisher = ShadowPublisher(
        job=_JOB,
        table=contract["table_name"],
        database=contract["glue_database"],
        bucket=bucket,
        canonical_root=contract["s3_root"],
        auth=auth,
        s3_client=s3_client,
        strategy=PublishStrategy.FLAT,
        validation=ValidationHooks(min_rows=1),
        manifest_store=manifest_store,
    )
    manifest = publisher.run(staged)
    logger.info(
        "modis_ndvi silver publish commodity=%s mode=%s state=%s objects=%d skipped=%d",
        commodity, auth.mode.value, manifest.state.value, len(staged), skipped,
    )
    return manifest.state


# -- main -----------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    args = _parse_args()

    publish_mode = "dry-run" if getattr(args, "dry_run", False) else args.publish_mode
    contract = load_registry().table(_TABLE)

    account_id, role_arn = args.account_id, args.role_arn
    if publish_mode == "canonical" and not account_id and not role_arn:
        account_id, role_arn = _caller_identity(args.aws_region)
    auth = authorize_for_contract(
        contract, publish_mode=publish_mode,
        role_arn=role_arn, account_id=account_id, env=os.environ,
    )
    logger.info(
        "Starting modis_ndvi bronze->silver | commodity=%s bucket=%s mode=%s may_canonical=%s",
        args.commodity, args.bucket, publish_mode, auth.may_mutate_canonical,
    )

    s3_read = get_thread_local_s3_client(args.aws_region)
    publish_client = None if publish_mode == "dry-run" else s3_read

    df = _load_all_bronze(args.bucket, args.commodity, args.aws_region)

    silver_df = modis_ndvi_bronze_to_silver(
        df, source_label=f"modis_ndvi/{args.commodity}"
    )
    logger.info("Silver transform produced %d rows", len(silver_df))

    if silver_df.empty:
        logger.warning("Silver transform returned empty DataFrame -- nothing to write")
        return

    _publish_modis(
        silver_df, args.commodity, contract, auth, publish_client, args.bucket,
        force_overwrite=args.force_overwrite,
    )


if __name__ == "__main__":
    main()
