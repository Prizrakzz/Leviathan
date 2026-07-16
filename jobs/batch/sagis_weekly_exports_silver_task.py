"""SILVER-F059 batch task: SAGIS weekly-export governed bronze -> silver_sagis_weekly_exports.

Restores the C-WRONG-8 half-orphan producer on the SILVER-F015 publisher. Loads the governed weekly
export bronze (the imp_exp_progressive dataset), selects the authoritative snapshot per season,
filters grade/total rows without double-counting, and computes the leakage-free trailing metrics
(pct_of_prior_yr, z_vs_3yr_avg). Publishes shadow-first (``--publish-mode`` default dry-run).
"""
from __future__ import annotations

import argparse
import io
import logging
import sys

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.silver.flat_producer import (
    add_standard_producer_args,
    authorize_for_contract,
    build_flat_publish,
)
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import silver_sagis_weekly_key
from leviathan.transforms.bronze_to_silver.sagis_weekly_exports import (
    WeeklyExportRow,
    transform_weekly_exports,
)

logger = get_logger("sagis_weekly_exports_silver_task")

TABLE = "silver_sagis_weekly_exports"
_BRONZE_PREFIX = "bronze/production/source=sagis_weekly/dataset=imp_exp_progressive/"


def _row_to_export(r: dict) -> WeeklyExportRow:
    return WeeklyExportRow(
        season=str(r["season"]),
        crop=str(r["crop"]),
        week_number=int(r["week_number"]),
        prog_exports_mt=(None if pd.isna(r.get("prog_exports_mt")) else float(r["prog_exports_mt"])),
        week_ending=r.get("week_ending"),
        is_total=bool(r.get("is_total", True)),
        snapshot_id=str(r.get("snapshot_id", "")),
        snapshot_week=int(r.get("snapshot_week", 0)),
        snapshot_release_date=r.get("snapshot_release_date"),
    )


def load_rows(bucket: str, aws_region: str, s3=None) -> list[WeeklyExportRow]:
    from leviathan.storage.s3 import (
        get_thread_local_s3_client,
        list_s3_keys,
        s3_download_with_retry,
    )

    s3 = s3 or get_thread_local_s3_client(aws_region)
    keys = list_s3_keys(bucket, _BRONZE_PREFIX, suffix=".parquet", aws_region=aws_region)
    rows: list[WeeklyExportRow] = []
    for key in keys:
        df = pd.read_parquet(io.BytesIO(s3_download_with_retry(bucket, key, s3)))
        rows.extend(_row_to_export(rec) for rec in df.to_dict("records"))
    logger.info("loaded %d weekly-export bronze rows from %d files", len(rows), len(keys))
    return rows


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SAGIS weekly exports bronze -> silver")
    add_standard_producer_args(parser)
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s",
                        stream=sys.stderr)
    load_env()
    args = _parse_args()
    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    contract = load_registry().table(TABLE)
    df = transform_weekly_exports(load_rows(bucket, aws_region))
    logger.info("silver rows: %d", len(df))
    if df.empty:
        logger.error("empty silver output; aborting")
        return 1

    auth = authorize_for_contract(contract, publish_mode=args.publish_mode)
    from leviathan.storage.s3 import get_thread_local_s3_client
    publish_s3 = None if args.publish_mode == "dry-run" else get_thread_local_s3_client(aws_region)
    plan = build_flat_publish(
        df=df, contract=contract, canonical_key=silver_sagis_weekly_key("exports"),
        auth=auth, s3_client=publish_s3, job="sagis_weekly_exports_silver", run_id=args.run_id,
    )
    manifest = plan.run()
    logger.info("publish %s state=%s mode=%s rows=%d", TABLE, manifest.state.value,
                args.publish_mode, len(df))
    return 0


if __name__ == "__main__":
    sys.exit(main())
