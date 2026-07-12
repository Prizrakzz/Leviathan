"""AWS Batch task: World Bank Pink Sheet bronze/ -> silver/ layer (SILVER-F023).

Downloads all Pink Sheet bronze Parquets, applies the 36-column silver transform, and publishes the
single silver object through the SILVER-F015 shadow-first publisher with the INV-2 arrow writer
schema from the F010 registry contract.

Output S3 key: ``silver/pink_sheet/part-000.parquet``.

``--publish-mode`` defaults to ``dry-run`` (nothing written; the run manifest is a plan) -- a bare
run can never touch the canonical surface (the F004 kill-switch contract). ``shadow`` stages to the
shadow prefix; ``canonical`` requires the full guard + signed approval.

Usage
-----
    python jobs/batch/pink_sheet_silver_task.py --bucket B --aws-region R   # dry-run (default)
    python jobs/batch/pink_sheet_silver_task.py --bucket B --aws-region R --publish-mode canonical
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from datetime import datetime, timezone

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.silver.flat_producer import authorize_for_contract, build_flat_publish
from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import silver_pink_sheet_key
from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys
from leviathan.transforms.bronze_to_silver.pink_sheet import build_silver

logger = get_logger("pink_sheet_silver_task")

_BRONZE_PREFIX = "bronze/production/source=world_bank_pink_sheet/"
_SILVER_LOG_KEY = "silver/pink_sheet/_run_log.json"
_TABLE = "silver_pink_sheet"
_JOB = "pink_sheet_silver"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pink Sheet bronze -> silver")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", action="store_true", default=False,
                        help="Overwrite existing silver Parquet (canonical mode only).")
    parser.add_argument("--publish-mode", default="dry-run",
                        choices=["dry-run", "shadow", "canonical"], dest="publish_mode")
    parser.add_argument("--role-arn", default="", dest="role_arn")
    parser.add_argument("--account-id", default="", dest="account_id")
    return parser.parse_args()


def _download_parquet(s3_client, bucket: str, key: str) -> pd.DataFrame:
    resp = s3_client.get_object(Bucket=bucket, Key=key)
    return pd.read_parquet(io.BytesIO(resp["Body"].read()))


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )

    load_env()
    args = _parse_args()

    bucket: str = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region: str = args.aws_region or get_required_env("AWS_REGION")
    contract = load_registry().table(_TABLE)
    auth = authorize_for_contract(
        contract, publish_mode=args.publish_mode,
        role_arn=args.role_arn, account_id=args.account_id,
    )

    logger.info("pink_sheet_silver_task bucket=%s mode=%s", bucket, args.publish_mode)

    start = datetime.now(timezone.utc)
    s3 = get_thread_local_s3_client(aws_region)

    # ------------------------------------------------------------------
    # Step 1 -- discover and download all Pink Sheet bronze Parquets
    # ------------------------------------------------------------------
    bronze_keys = sorted(
        list_s3_keys(bucket, _BRONZE_PREFIX, suffix=".parquet", aws_region=aws_region)
    )
    logger.info("Found %d Pink Sheet bronze Parquets", len(bronze_keys))
    if not bronze_keys:
        logger.error("No bronze Parquets found under %s -- aborting.", _BRONZE_PREFIX)
        sys.exit(1)

    dfs: list[pd.DataFrame] = []
    for key in bronze_keys:
        df = _download_parquet(s3, bucket, key)
        dfs.append(df)
        logger.info("downloaded %s rows=%d", key, len(df))

    release_count = len(dfs)
    release_yms = sorted(
        {df["release_ym"].iloc[0] for df in dfs if "release_ym" in df.columns and len(df) > 0}
    )
    logger.info("release_count=%d releases=%s", release_count, release_yms)

    # ------------------------------------------------------------------
    # Step 2 -- build 36-column silver table
    # ------------------------------------------------------------------
    df_silver = build_silver(dfs)
    silver_rows = len(df_silver)
    date_min = str(df_silver["date"].min().date()) if silver_rows else "n/a"
    date_max = str(df_silver["date"].max().date()) if silver_rows else "n/a"
    logger.info("build_silver -> %d rows date_range=%s..%s", silver_rows, date_min, date_max)

    # ------------------------------------------------------------------
    # Step 3 -- publish through the shadow-first publisher (INV-2 schema)
    # ------------------------------------------------------------------
    silver_key = silver_pink_sheet_key()
    # dry-run stages nothing (no client); shadow + canonical both write to S3.
    publish_s3 = None if args.publish_mode == "dry-run" else s3
    plan = build_flat_publish(
        df=df_silver, contract=contract, canonical_key=silver_key, auth=auth,
        s3_client=publish_s3, job=_JOB,
    )
    manifest = plan.run()
    logger.info("publish %s mode=%s state=%s", silver_key, args.publish_mode, manifest.state.value)
    if manifest.state not in (ManifestState.VALIDATED, ManifestState.CERTIFIED):
        raise RuntimeError(f"pink_sheet publish failed: state={manifest.state.value} "
                           f"reason={manifest.failure_reason}")

    # ------------------------------------------------------------------
    # Step 4 -- run log (canonical only; control-plane artifact)
    # ------------------------------------------------------------------
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    if auth.may_mutate_canonical:
        run_log = {
            "run_date": datetime.now(timezone.utc).date().isoformat(),
            "elapsed_s": round(elapsed, 1),
            "release_count": release_count,
            "releases": release_yms,
            "silver_rows": silver_rows,
            "date_min": date_min,
            "date_max": date_max,
        }
        s3.put_object(Bucket=bucket, Key=_SILVER_LOG_KEY,
                      Body=json.dumps(run_log, indent=2).encode(), ContentType="application/json")
    logger.info("Done mode=%s rows=%d elapsed=%.1fs", args.publish_mode, silver_rows, elapsed)


if __name__ == "__main__":
    main()
