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

THE SECOND TABLE (data repairs 0929, lane ENSO): ``--table silver_noaa_enso_vintages`` builds the
vintages table -- BOTH NOAA ENSO indices (the legacy ONI and the Relative ONI, official since
2026-02-01), every held vintage with the date it became known, and the official-index dates -- from
the captures BANKED under ``raw/weather/source=noaa_cpc_enso_captures/`` (written by
jobs/ingest/fetch_noaa_oni.py). It never fetches: a vintage is in the table only if it was banked
first, and a re-run over the same captures rebuilds the same table. It never writes raw or bronze. The
default ``--table silver_noaa_oni`` path is the served producer, unchanged.

Usage
-----
    python jobs/batch/noaa_oni_task.py                       # dry-run (writes nothing)
    python jobs/batch/noaa_oni_task.py --publish-mode shadow
    python jobs/batch/noaa_oni_task.py --from-year 1990 --to-year 2020 --publish-mode shadow
    python jobs/batch/noaa_oni_task.py --table silver_noaa_enso_vintages               # dry-run
    python jobs/batch/noaa_oni_task.py --table silver_noaa_enso_vintages --publish-mode shadow
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

import requests

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.common.publish_guard import PublishTarget, authorize_publish
from leviathan.silver.flat_producer import build_flat_publish
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import bronze_oni_key, raw_oni_key, silver_oni_key
from leviathan.transforms.bronze_to_silver.noaa_oni import build_enso_vintages, build_oni_silver
from leviathan.transforms.raw_to_bronze.noaa_oni import (
    ENSO_CAPTURE_PREFIX,
    capture_from_held_object,
    extract_oni_bronze,
)

logger = get_logger("noaa_oni_task")

_ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
_TIMEOUT = 30
_TABLE = "silver_noaa_oni"
_VINTAGES_TABLE = "silver_noaa_enso_vintages"

# Validation floors (the silver record is 1950-present, 12 rows/year).
_MIN_ROWS = 800


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
    parser.add_argument("--table", default=_TABLE, choices=[_TABLE, _VINTAGES_TABLE],
                        help=f"{_TABLE} (default: the served latest-only legacy table) or "
                             f"{_VINTAGES_TABLE} (both indices, every held vintage, from banked captures)")
    args = parser.parse_args()
    if args.table == _VINTAGES_TABLE and (args.from_year is not None or args.to_year is not None):
        parser.error("--from-year/--to-year bound the legacy table only; the vintages table is "
                     "rebuilt whole from every held capture")

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    if args.table == _VINTAGES_TABLE:
        run_vintages(args, bucket, aws_region)
        return

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


def read_held_captures(reader, bucket: str, keys: list[str]) -> tuple[list, list[str]]:
    """Every banked capture under the capture root, rebuilt from its key and bytes.

    An object under the root whose key is not a capture key is LISTED (returned) and skipped, never
    guessed at -- the key carries the capture's clock, so an object without one cannot be dated."""
    captures, stray = [], []
    for key in sorted(keys):
        try:
            body = reader.get_object(Bucket=bucket, Key=key)["Body"].read()
            captures.append(capture_from_held_object(key, body))
        except ValueError as exc:
            stray.append(f"{key}: {exc}")
    return captures, stray


def run_vintages(args, bucket: str, aws_region: str) -> None:
    """Build and publish ``silver_noaa_enso_vintages`` from the banked captures (never fetches)."""
    from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys

    contract = load_registry().table(_VINTAGES_TABLE)
    account_id, role_arn = _caller_identity(aws_region)
    auth = authorize_publish(
        PublishTarget(
            account_id=account_id,
            bucket=bucket,
            database=contract["glue_database"],
            prefix=contract["s3_prefix"].rstrip("/") + "/",
            role_arn=role_arn,
            table=_VINTAGES_TABLE,
        ),
        argv=sys.argv,
    )
    logger.info("publish authorized: mode=%s may_canonical=%s", auth.mode.value, auth.may_mutate_canonical)

    # READS happen in every mode (dry-run included): the captures are the input, not an output.
    reader = get_thread_local_s3_client(aws_region)
    keys = list_s3_keys(bucket, ENSO_CAPTURE_PREFIX, suffix=".txt", aws_region=aws_region)
    captures, stray = read_held_captures(reader, bucket, keys)
    for line in stray:
        logger.error("ENSO_CAPTURE_UNREADABLE %s", line)
    build = build_enso_vintages(captures)
    logger.info("ENSO vintages build: %s", json.dumps(build.summary(), default=str, sort_keys=True))
    for q in build.quarantined:
        logger.error("ENSO_CAPTURE_REFUSED %s", json.dumps(q, sort_keys=True))
    if build.frame.empty:
        logger.error("no held ENSO capture yields a vintage (%d objects under %s): nothing to publish",
                     len(keys), ENSO_CAPTURE_PREFIX)
        sys.exit(1)

    s3_client = None if auth.mode.value == "dry-run" else reader
    manifest_store = None
    if auth.mode.value == "dry-run":
        manifest_store = lambda key, body: logger.info(  # noqa: E731
            "dry-run manifest (not persisted): %s (%d bytes)", key, len(body))
    plan = build_flat_publish(
        df=build.frame,
        contract=contract,
        # the canonical object sits at the contract's own root: the registry is the prefix authority
        canonical_key=contract["s3_prefix"].rstrip("/") + "/part-000.parquet",
        auth=auth,
        s3_client=s3_client,
        job="noaa_oni_task:vintages",
        run_id=args.run_id,
        code_sha=args.code_sha,
        manifest_store=manifest_store,
        min_rows=1,
    )
    manifest = plan.run()
    logger.info("ENSO vintages publish complete: state=%s rows=%d mode=%s validation_ok=%s",
                manifest.state.value, plan.row_count, auth.mode.value,
                manifest.validation_result.get("ok"))
    if manifest.state.value == "FAILED":
        logger.error("publish FAILED: %s", manifest.failure_reason)
        sys.exit(1)


if __name__ == "__main__":
    main()
