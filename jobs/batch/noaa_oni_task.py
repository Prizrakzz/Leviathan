"""AWS Batch entrypoint: NOAA ONI -> raw + bronze + silver via the shadow-first publisher.

SILVER-F057 (full-orphan producer, Milestone R3). Fetches the NOAA CPC ONI ascii file,
parses bronze, computes the silver feature table, and PUBLISHES silver through the common
SILVER-F015 shadow-first publisher (``leviathan.silver.flat_producer.build_flat_publish``) --
never a bespoke ``df.to_parquet + put_object``. The publisher pins the explicit INV-2 writer
schema from the F010 registry contract and runs the V001-style row/value gate before any
promotion.

Publish modes (default ``dry-run`` -- the readiness kill switch, SILVER-F004):
    dry-run   : fetch + parse + validate the plan; write NOTHING (default).
    shadow    : write silver to a NON-canonical shadow prefix + validate; never promote.
    canonical : shadow -> validate -> promote -> catalog, ONLY with a signed approval
                artifact (the guard raises otherwise). Execution of a canonical backfill is
                gated to BF-W3.

This is also the bounded backfill entrypoint: ``--from-year`` / ``--to-year`` bound the silver
window; the full-history file is fetched once and filtered deterministically.

Raw + bronze are written to canonical only in canonical mode (the same guard gate); in
dry-run / shadow they are computed in memory and never touch the canonical surface.

Usage
-----
    python jobs/batch/noaa_oni_task.py                       # dry-run (writes nothing)
    python jobs/batch/noaa_oni_task.py --publish-mode shadow
    python jobs/batch/noaa_oni_task.py --from-year 1990 --to-year 2020 --publish-mode shadow
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

import requests

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.common.publish_guard import PublishTarget, authorize_publish
from leviathan.silver.flat_producer import build_flat_publish
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import bronze_oni_key, raw_oni_key, silver_oni_key
from leviathan.transforms.bronze_to_silver.noaa_oni import build_oni_silver
from leviathan.transforms.raw_to_bronze.noaa_oni import extract_oni_bronze

logger = get_logger("noaa_oni_task")

_ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
_TIMEOUT = 30
_TABLE = "silver_noaa_oni"

# Validation floors (the silver record is 1950-present, 12 rows/year).
_MIN_ROWS = 800


def _caller_identity(aws_region: str):
    """Best-effort STS identity for the publish target. Returns (account_id, role_arn); falls
    back to empty strings when no credentials are available (fine for dry-run)."""
    try:
        import boto3
        ident = boto3.client("sts", region_name=aws_region).get_caller_identity()
        return ident.get("Account", ""), ident.get("Arn", "")
    except Exception as exc:  # noqa: BLE001 -- dry-run must not require live credentials
        logger.info("STS identity unavailable (%s); using empty target (dry-run only)", exc)
        return "", ""


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(description="NOAA ONI -> silver via the shadow publisher")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--code-sha", default=None)
    parser.add_argument("--from-year", type=int, default=None, help="Bound silver output (inclusive)")
    parser.add_argument("--to-year", type=int, default=None, help="Bound silver output (inclusive)")
    # NOTE: --publish-mode is consumed by the publish guard from sys.argv (default dry-run).
    parser.add_argument("--publish-mode", default=None,
                        help="dry-run|shadow|canonical (default dry-run; canonical gated BF-W3)")
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

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
    # Fetch raw + bronze + silver (in memory; nothing canonical unless authorized).
    # ------------------------------------------------------------------
    logger.info("Fetching %s ...", _ONI_URL)
    resp = requests.get(_ONI_URL, timeout=_TIMEOUT)
    resp.raise_for_status()
    raw_bytes = resp.content
    logger.info("Downloaded %d bytes", len(raw_bytes))

    df_bronze = extract_oni_bronze(raw_bytes)
    df_silver = build_oni_silver(df_bronze)

    if args.from_year is not None:
        df_silver = df_silver[df_silver["year"] >= args.from_year]
    if args.to_year is not None:
        df_silver = df_silver[df_silver["year"] <= args.to_year]
    df_silver = df_silver.reset_index(drop=True)

    if args.from_year is None and args.to_year is None and len(df_silver) < _MIN_ROWS:
        logger.error("ONI silver has only %d rows (expected >= %d)", len(df_silver), _MIN_ROWS)
        sys.exit(1)

    s3_client = None
    manifest_store = None
    if auth.mode.value == "dry-run":
        # dry-run must write NOTHING -- discard the manifest to the log instead of an S3 put.
        manifest_store = lambda key, body: logger.info(  # noqa: E731
            "dry-run manifest (not persisted): %s (%d bytes)", key, len(body))
    else:
        from leviathan.storage.s3 import get_thread_local_s3_client
        s3_client = get_thread_local_s3_client(aws_region)
        # raw + bronze are written to canonical only under a fully-authorized canonical publish.
        if auth.may_mutate_canonical:
            _write_raw_bronze(s3_client, bucket, raw_bytes, df_bronze)

    plan = build_flat_publish(
        df=df_silver,
        contract=contract,
        canonical_key=silver_oni_key(),
        auth=auth,
        s3_client=s3_client,
        job="noaa_oni_task",
        run_id=args.run_id,
        code_sha=args.code_sha,
        manifest_store=manifest_store,
        min_rows=1,
    )
    manifest = plan.run()
    logger.info(
        "ONI publish complete: state=%s rows=%d mode=%s validation_ok=%s",
        manifest.state.value, plan.row_count, auth.mode.value,
        manifest.validation_result.get("ok"),
    )
    if manifest.state.value == "FAILED":
        logger.error("publish FAILED: %s", manifest.failure_reason)
        sys.exit(1)


def _write_raw_bronze(s3_client, bucket: str, raw_bytes: bytes, df_bronze) -> None:
    import io
    s3_client.put_object(Bucket=bucket, Key=raw_oni_key(), Body=raw_bytes,
                         ContentType="text/plain")
    buf = io.BytesIO()
    df_bronze.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3_client.put_object(Bucket=bucket, Key=bronze_oni_key(), Body=buf.getvalue(),
                         ContentType="application/octet-stream")
    logger.info("raw + bronze written to canonical (authorized)")


if __name__ == "__main__":
    main()
