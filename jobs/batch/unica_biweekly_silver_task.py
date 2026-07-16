"""AWS Batch task: UNICA biweekly bronze/ -> silver/ layer (shadow-first, SILVER-F015/INV-6).

Reads all bronze Parquet files produced by ``unica_biweekly_task.py`` for the
four main tables, applies the silver transforms, and publishes one flat Parquet
per output table through the shadow-first controlled publisher:

    silver/unica_biweekly_season_history/part-000.parquet
    silver/unica_biweekly_release_series/part-000.parquet
    silver/unica_corn_ethanol/part-000.parquet
    silver/unica_monthly_ethanol_sales/part-000.parquet

Publish contract (A-W4 CLASS-B retrofit)
----------------------------------------
Each silver write is routed through ``leviathan.silver.flat_producer.build_flat_publish``
with the EXPLICIT INV-2 arrow schema from that table's F010 registry contract.
``--publish-mode`` (default ``dry-run``) resolves through the publish guard:

  * dry-run   : nothing is written anywhere.
  * shadow    : each object is staged ONLY under ``<table root>/_shadow/``; canonical
                is untouched (INV-6 -- a red rebuild gate can still protect canonical).
  * canonical : shadow-stage -> validate -> promote -> catalog, ONLY with a verified
                signed approval.

The per-run ``_run_log.json`` lives under ``silver/`` and is therefore written ONLY on
an authorized canonical publish (``may_mutate_canonical``). The legacy ``--dry-run`` flag
is retained as an alias for ``--publish-mode dry-run``.

Usage
-----
    # dry-run (writes nothing)
    python jobs/batch/unica_biweekly_silver_task.py --bucket B --aws-region us-east-1

    # shadow (stages under _shadow/, canonical untouched)
    python jobs/batch/unica_biweekly_silver_task.py --bucket B --aws-region us-east-1 --publish-mode shadow

    # canonical (needs a signed approval)
    python jobs/batch/unica_biweekly_silver_task.py --bucket B --aws-region us-east-1 \\
        --publish-mode canonical --force-overwrite
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
from datetime import datetime, timezone

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.silver.flat_producer import authorize_for_contract, build_flat_publish
from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import (
    silver_unica_biweekly_season_history_key,
    silver_unica_biweekly_release_series_key,
    silver_unica_corn_ethanol_key,
    silver_unica_monthly_ethanol_sales_key,
)
from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys
from leviathan.transforms.bronze_to_silver.unica_biweekly import (
    transform_corn_ethanol,
    transform_monthly_ethanol_sales,
    transform_release_series,
    transform_season_history,
)

logger = get_logger("unica_biweekly_silver_task")

_BRONZE_PREFIX = "bronze/production/source=unica_biweekly/"
_SILVER_LOG_KEY = "silver/unica_biweekly/_run_log.json"
_JOB = "unica_biweekly_silver"

# (bronze table name, silver registry table, transform fn, silver key fn)
_TABLE_MAP = [
    ("fortnight_production",  "silver_unica_biweekly_season_history",
     transform_season_history,        silver_unica_biweekly_season_history_key),
    ("summary_snapshot",      "silver_unica_biweekly_release_series",
     transform_release_series,        silver_unica_biweekly_release_series_key),
    ("corn_ethanol",          "silver_unica_corn_ethanol",
     transform_corn_ethanol,          silver_unica_corn_ethanol_key),
    ("monthly_ethanol_sales", "silver_unica_monthly_ethanol_sales",
     transform_monthly_ethanol_sales, silver_unica_monthly_ethanol_sales_key),
]


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UNICA biweekly bronze -> silver (shadow-first)")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        default=False,
        help="Overwrite existing canonical silver Parquets (canonical mode only; default: skip).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Alias for --publish-mode dry-run (writes nothing).",
    )
    parser.add_argument("--publish-mode", default="dry-run",
                        choices=["dry-run", "shadow", "canonical"], dest="publish_mode",
                        help="dry-run|shadow|canonical (default dry-run; canonical needs a signed approval)")
    parser.add_argument("--role-arn", default="", dest="role_arn")
    parser.add_argument("--account-id", default="", dest="account_id")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------

def _key_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001
        return False


def _download_parquet(s3_client, bucket: str, key: str) -> pd.DataFrame:
    resp = s3_client.get_object(Bucket=bucket, Key=key)
    return pd.read_parquet(io.BytesIO(resp["Body"].read()))


def _caller_identity(aws_region: str) -> tuple[str, str]:
    """Best-effort STS identity for the canonical publish target (empty on failure)."""
    try:
        import boto3
        ident = boto3.client("sts", region_name=aws_region).get_caller_identity()
        return ident.get("Account", ""), ident.get("Arn", "")
    except Exception as exc:  # noqa: BLE001 -- dry-run / shadow must not require live credentials
        logger.info("STS identity unavailable (%s); using empty target (dry-run/shadow only)", exc)
        return "", ""


# ---------------------------------------------------------------------------
# Per-table publish
# ---------------------------------------------------------------------------

def _publish_table(
    df: pd.DataFrame,
    contract: dict,
    auth,
    s3_client,
    canonical_key: str,
    *,
    force_overwrite: bool,
    bucket: str,
) -> ManifestState | None:
    """Publish one flat UNICA silver object through the shadow-first publisher. Returns the manifest
    state, or ``None`` when an existing canonical object is skipped (canonical mode only)."""
    if (
        not force_overwrite
        and auth.may_mutate_canonical
        and s3_client is not None
        and _key_exists(s3_client, bucket, canonical_key)
    ):
        logger.info("silver exists -- skipping (canonical, no --force-overwrite): %s", canonical_key)
        return None
    plan = build_flat_publish(
        df=df, contract=contract, canonical_key=canonical_key,
        auth=auth, s3_client=s3_client, job=_JOB,
    )
    return plan.run().state


def _process_table(
    table_name: str,
    contract: dict,
    transform_fn,
    silver_key_fn,
    auth,
    read_client,
    publish_client,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
) -> dict:
    """Download all bronze Parquets for *table_name*, transform, and publish shadow-first."""
    prefix = f"{_BRONZE_PREFIX}table={table_name}/"
    bronze_keys = list(list_s3_keys(bucket, prefix, suffix=".parquet", aws_region=aws_region))
    logger.info("table=%s  bronze_keys=%d", table_name, len(bronze_keys))

    silver_key = silver_key_fn()
    if not bronze_keys:
        logger.warning("table=%s: no bronze Parquets found under %s", table_name, prefix)
        return {"table": table_name, "output_rows": 0, "silver_key": silver_key, "status": "empty"}

    frames: list[pd.DataFrame] = []
    for key in sorted(bronze_keys):
        try:
            frames.append(_download_parquet(read_client, bucket, key))
        except Exception as exc:  # noqa: BLE001
            logger.error("Download failed  key=%s: %s", key, exc)
            raise

    df_bronze = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    df_silver = transform_fn(df_bronze)
    output_rows = len(df_silver)

    if df_silver.empty:
        logger.warning("table=%s: silver transform produced 0 rows -- nothing to publish", table_name)
        return {"table": table_name, "output_rows": 0, "silver_key": silver_key, "status": "empty_silver"}

    state = _publish_table(
        df_silver, contract, auth, publish_client, silver_key,
        force_overwrite=force_overwrite, bucket=bucket,
    )
    logger.info(
        "table=%s  mode=%s  publish_state=%s  output_rows=%d  key=%s",
        table_name, auth.mode.value, state.value if state else "skipped", output_rows, silver_key,
    )
    return {
        "table": table_name,
        "output_rows": output_rows,
        "silver_key": silver_key,
        "publish_state": state.value if state else "skipped",
        "status": "published" if state is not None else "skipped",
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    load_env()
    args = _parse_args()

    publish_mode = "dry-run" if args.dry_run else args.publish_mode
    bucket: str = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region: str = args.aws_region or get_required_env("AWS_REGION")
    registry = load_registry()

    account_id, role_arn = args.account_id, args.role_arn
    if publish_mode == "canonical" and not account_id and not role_arn:
        account_id, role_arn = _caller_identity(aws_region)

    logger.info(
        "unica_biweekly_silver_task  bucket=%s  mode=%s  force=%s",
        bucket, publish_mode, args.force_overwrite,
    )

    read_client = get_thread_local_s3_client(aws_region)
    publish_client = None if publish_mode == "dry-run" else read_client

    start = datetime.now(timezone.utc)
    table_results: list[dict] = []
    errors = 0
    any_may_canonical = False

    for table_name, registry_table, transform_fn, silver_key_fn in _TABLE_MAP:
        contract = registry.table(registry_table)
        auth = authorize_for_contract(
            contract, publish_mode=publish_mode,
            role_arn=role_arn, account_id=account_id, env=os.environ,
        )
        any_may_canonical = any_may_canonical or auth.may_mutate_canonical
        try:
            result = _process_table(
                table_name=table_name,
                contract=contract,
                transform_fn=transform_fn,
                silver_key_fn=silver_key_fn,
                auth=auth,
                read_client=read_client,
                publish_client=publish_client,
                bucket=bucket,
                aws_region=aws_region,
                force_overwrite=args.force_overwrite,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("FAILED  table=%s: %s", table_name, exc)
            table_results.append({"table": table_name, "status": "error", "error": str(exc)})
            errors += 1
            continue
        table_results.append(result)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info("Done  tables=%d  errors=%d  elapsed=%.1fs", len(table_results), errors, elapsed)

    # The run log lives under silver/ -- write it only on an authorized canonical publish.
    if any_may_canonical:
        try:
            run_log = {
                "run_date":  datetime.now(timezone.utc).date().isoformat(),
                "mode":      publish_mode,
                "elapsed_s": round(elapsed, 1),
                "tables":    table_results,
                "errors":    errors,
            }
            read_client.put_object(
                Bucket=bucket,
                Key=_SILVER_LOG_KEY,
                Body=json.dumps(run_log, indent=2).encode(),
                ContentType="application/json",
            )
            logger.info("Run log written  key=%s", _SILVER_LOG_KEY)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to write run log: %s", exc)

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
