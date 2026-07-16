"""SILVER-F058 batch task: SAGIS CEC governed bronze -> silver_sagis_cec.

Restores the C-WRONG-8 half-orphan producer on the SILVER-F015 publisher. Loads the governed CEC
bronze records (produced by the raw->bronze workbook parser -- a separate documented dependency),
selects the authoritative estimate per natural key, computes the no-lookahead revision metrics, and
publishes shadow-first (``--publish-mode`` default dry-run).
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
from leviathan.storage.paths import silver_sagis_cec_key
from leviathan.transforms.bronze_to_silver.sagis_cec import (
    CecObservation,
    transform_sagis_cec,
)

logger = get_logger("sagis_cec_silver_task")

TABLE = "silver_sagis_cec"
_BRONZE_PREFIX = "bronze/production/source=sagis_cec/"


def _row_to_obs(r: dict) -> CecObservation:
    return CecObservation(
        production_year=int(r["production_year"]),
        report_month=int(r["report_month"]),
        crop=str(r["crop"]),
        scope=str(r["scope"]),
        estimate_number=int(r["estimate_number"]),
        current_estimate_t=(None if pd.isna(r.get("current_estimate_t")) else float(r["current_estimate_t"])),
        release_date=r.get("release_date"),
        season_type=r.get("season_type"),
        area_planted_ha=(None if pd.isna(r.get("area_planted_ha")) else float(r.get("area_planted_ha"))),
        source_format=str(r.get("source_format", "pdf")),
        source_key=str(r.get("source_key", "")),
    )


def load_observations(bucket: str, aws_region: str, s3=None) -> list[CecObservation]:
    from leviathan.storage.s3 import (
        get_thread_local_s3_client,
        list_s3_keys,
        s3_download_with_retry,
    )

    s3 = s3 or get_thread_local_s3_client(aws_region)
    keys = list_s3_keys(bucket, _BRONZE_PREFIX, suffix=".parquet", aws_region=aws_region)
    obs: list[CecObservation] = []
    for key in keys:
        df = pd.read_parquet(io.BytesIO(s3_download_with_retry(bucket, key, s3)))
        obs.extend(_row_to_obs(rec) for rec in df.to_dict("records"))
    logger.info("loaded %d CEC bronze observations from %d files", len(obs), len(keys))
    return obs


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SAGIS CEC bronze -> silver")
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
    df = transform_sagis_cec(load_observations(bucket, aws_region))
    logger.info("silver rows: %d", len(df))
    if df.empty:
        logger.error("empty silver output; aborting")
        return 1

    auth = authorize_for_contract(contract, publish_mode=args.publish_mode)
    from leviathan.storage.s3 import get_thread_local_s3_client
    publish_s3 = None if args.publish_mode == "dry-run" else get_thread_local_s3_client(aws_region)
    plan = build_flat_publish(
        df=df, contract=contract, canonical_key=silver_sagis_cec_key(),
        auth=auth, s3_client=publish_s3, job="sagis_cec_silver", run_id=args.run_id,
    )
    manifest = plan.run()
    logger.info("publish %s state=%s mode=%s rows=%d", TABLE, manifest.state.value,
                args.publish_mode, len(df))
    return 0


if __name__ == "__main__":
    sys.exit(main())
