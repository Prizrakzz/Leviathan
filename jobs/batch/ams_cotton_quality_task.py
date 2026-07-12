"""AWS Batch entrypoint: AMS cotton-quality bronze -> silver via the shadow-first publisher.

SILVER-F050 (half-orphan restore, Milestone R3). Reads the AMS cotton-quality bronze corpus
(``bronze/production/source=usda_ams_cotton_classing/**/part-000.parquet``), builds the wide
national silver via :func:`~leviathan.transforms.bronze_to_silver.ams_cotton_quality.build_ams_cotton_silver`,
and PUBLISHES silver through the SILVER-F015 shadow-first publisher. The INV-2 schema pins the
all-null ``avg_micronaire`` / ``avg_strength`` columns to ``double`` (never Arrow ``null``).

Publish modes default to ``dry-run`` (SILVER-F004): dry-run writes nothing; shadow writes to a
NON-canonical prefix; canonical needs a signed approval (execution gated BF-W3). This is the
bounded backfill entrypoint.

Usage
-----
    python jobs/batch/ams_cotton_quality_task.py                        # dry-run
    python jobs/batch/ams_cotton_quality_task.py --publish-mode shadow
"""
from __future__ import annotations

import argparse
import io
import logging
import sys

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.common.publish_guard import PublishTarget, authorize_publish
from leviathan.silver.flat_producer import build_flat_publish
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import silver_ams_cotton_key
from leviathan.transforms.bronze_to_silver.ams_cotton_quality import build_ams_cotton_silver

logger = get_logger("ams_cotton_quality_task")

_TABLE = "silver_ams_cotton_quality"
_BRONZE_PREFIX = "bronze/production/source=usda_ams_cotton_classing/"


def _caller_identity(aws_region: str):
    try:
        import boto3
        ident = boto3.client("sts", region_name=aws_region).get_caller_identity()
        return ident.get("Account", ""), ident.get("Arn", "")
    except Exception as exc:  # noqa: BLE001
        logger.info("STS identity unavailable (%s); dry-run only", exc)
        return "", ""


def _read_bronze_corpus(bucket: str, prefix: str, aws_region: str) -> pd.DataFrame:
    from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys, s3_download_with_retry
    s3 = get_thread_local_s3_client(aws_region)
    keys = list_s3_keys(bucket, prefix, suffix=".parquet", aws_region=aws_region)
    if not keys:
        raise SystemExit(f"no bronze parquet under s3://{bucket}/{prefix}")
    frames = [pd.read_parquet(io.BytesIO(s3_download_with_retry(bucket, k, s3))) for k in keys]
    logger.info("read %d bronze objects under %s", len(frames), prefix)
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s", stream=sys.stderr)
    load_env()
    parser = argparse.ArgumentParser(description="AMS cotton quality bronze -> silver via shadow publisher")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--code-sha", default=None)
    parser.add_argument("--publish-mode", default=None,
                        help="dry-run|shadow|canonical (default dry-run; canonical gated BF-W3)")
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    account_id, role_arn = _caller_identity(aws_region)
    contract = load_registry().table(_TABLE)

    auth = authorize_publish(
        PublishTarget(account_id=account_id, bucket=bucket, database=contract["glue_database"],
                      prefix=contract["s3_prefix"].rstrip("/") + "/", role_arn=role_arn, table=_TABLE),
        argv=sys.argv,
    )
    logger.info("publish authorized: mode=%s", auth.mode.value)

    df_bronze = _read_bronze_corpus(bucket, _BRONZE_PREFIX, aws_region)
    df_silver = build_ams_cotton_silver(df_bronze)

    s3_client = None
    manifest_store = None
    if auth.mode.value == "dry-run":
        manifest_store = lambda key, body: logger.info(  # noqa: E731
            "dry-run manifest (not persisted): %s (%d bytes)", key, len(body))
    else:
        from leviathan.storage.s3 import get_thread_local_s3_client
        s3_client = get_thread_local_s3_client(aws_region)

    plan = build_flat_publish(
        df=df_silver, contract=contract, canonical_key=silver_ams_cotton_key(), auth=auth,
        s3_client=s3_client, job="ams_cotton_quality_task", run_id=args.run_id,
        code_sha=args.code_sha, manifest_store=manifest_store, min_rows=1,
    )
    manifest = plan.run()
    logger.info("AMS cotton publish complete: state=%s rows=%d mode=%s",
                manifest.state.value, plan.row_count, auth.mode.value)
    if manifest.state.value == "FAILED":
        logger.error("publish FAILED: %s", manifest.failure_reason)
        sys.exit(1)


if __name__ == "__main__":
    main()
