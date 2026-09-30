"""AWS Batch entrypoint: the banked ICCO QBCS pages -> silver_icco_cocoa_releases -> silver_icco_cocoa.

WHAT THIS READS, AND WHY IT IS THE PAGES (2026-09-29, data repairs ICCO-1..4)
-----------------------------------------------------------------------------
SILVER-F051 read ``bronze/production/source=icco_qbcs/``: 48 objects written ONCE by a restore
backfill (2026-06-03) from JSON a positional parser had minted, and no producer in the chain has
written bronze since -- so a newly fetched bulletin could never reach silver, and every defect of that
parser (a sign followed by a NO-BREAK SPACE lost, a season's previous estimate filed under the prior
season's name, the mislabelled May-2023 header trusted) was frozen into the served table.

This task reads the evidence itself: every captured bulletin page under
``raw/production/source=icco_qbcs_summary/release_date=<d>/`` (``page.html``, the capture that
minted the folder's record, and any later ``capture_<digest16>.html``; never
``page_parse_failure.html``), and builds two tables with ONE parser
(``transforms/raw_to_bronze/icco_cocoa.py:parse_qbcs_page``):

1. ``silver_icco_cocoa_releases`` -- ONE ROW PER SEASON PER RELEASE, stamped with the date the
   bulletin became known (its dateline, fenced by the bulletin's own identity).  NEW; read by nothing
   served until the serving side lands its card (HANDOFF).
2. ``silver_icco_cocoa`` -- the served table, SHAPE UNCHANGED (ten columns, one row per cocoa
   year), rebuilt from (1) as each season's latest release, whole rows only.

Both publish through the SILVER-F015 shadow-first publisher (INV-2 explicit schema from each table's
F010 contract; V001 value gate).  The releases table publishes FIRST: if it fails, the served table
is not touched.  The 48 bronze objects stay where they are, unread (never deleted).

The run log (pages read, releases, the headers the release chain overruled, restatements that do not
match the bulletin they cite, absent bulletins, rows beyond the kt rounding) is written to the job's
log as one JSON line -- it is the audit of what the publisher printed, not a table.

Publish modes (default ``dry-run`` -- the readiness kill switch, SILVER-F004): dry-run writes
nothing; shadow writes to a NON-canonical prefix + validates; canonical requires a signed approval.

Usage
-----
    python jobs/batch/icco_cocoa_task.py                        # dry-run (reads raw, writes nothing)
    python jobs/batch/icco_cocoa_task.py --publish-mode shadow
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.common.publish_guard import PublishTarget, authorize_publish
from leviathan.silver.flat_producer import build_flat_publish
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import silver_icco_cocoa_key
from leviathan.transforms.bronze_to_silver.icco_cocoa import (
    PageInput,
    build_icco_releases,
    build_icco_silver,
)
from leviathan.transforms.raw_to_bronze.icco_cocoa import is_page_capture

logger = get_logger("icco_cocoa_task")

_TABLE = "silver_icco_cocoa"
_RELEASES_TABLE = "silver_icco_cocoa_releases"
# The trailing slash is load-bearing: a LIST without it would also match any sibling source whose
# name starts with this one (T-X-4).
_PAGES_PREFIX = "raw/production/source=icco_qbcs_summary/"
_FOLDER_RE = re.compile(r"release_date=(\d{4}-\d{2}-\d{2})/")


def _caller_identity(aws_region: str) -> tuple[str, str]:
    """Best-effort STS identity for the canonical publish target (empty on failure).

    Thin wrapper over the shared resolver ``leviathan.common.aws_identity.resolve_caller_identity``
    (the one idiom the batch-task family shares). Kept as a module-level seam so tests can
    monkeypatch it and readiness/unit runs stay AWS-free; an empty identity still makes the publish
    guard fail closed on the canonical path exactly as before."""
    from leviathan.common.aws_identity import resolve_caller_identity

    return resolve_caller_identity(aws_region)


def flat_key(contract: dict) -> str:
    """The one object of a flat table, from its declared prefix (every flat silver writes part-000)."""
    return contract["s3_prefix"].rstrip("/") + "/part-000.parquet"


def select_page_keys(keys: list[str]) -> list[str]:
    """The keys a release is read from: every ``page.html`` and ``capture_<digest16>.html`` under a
    ``release_date=`` folder; never a ``page_parse_failure.html`` and never a JSON sidecar."""
    return sorted(k for k in keys
                  if _FOLDER_RE.search(k) and is_page_capture(k.rsplit("/", 1)[-1]))


def read_pages(bucket: str, prefix: str, aws_region: str) -> list[PageInput]:
    """Every banked bulletin page under ``prefix`` (read-only)."""
    from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys, s3_download_with_retry
    s3 = get_thread_local_s3_client(aws_region)
    keys = select_page_keys(list_s3_keys(bucket, prefix, suffix=".html", aws_region=aws_region))
    if not keys:
        raise SystemExit(f"no bulletin page under s3://{bucket}/{prefix}")
    pages = [PageInput(key=k, body=s3_download_with_retry(bucket, k, s3),
                       folder_release_date=_FOLDER_RE.search(k).group(1)) for k in keys]
    logger.info("read %d bulletin page(s) under %s", len(pages), prefix)
    return pages


def build_tables(pages: list[PageInput]) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """(releases, served silver, run log) from the banked pages -- pure, AWS-free."""
    releases, log = build_icco_releases(pages)
    silver = build_icco_silver(releases)
    return releases, silver, log


def _publish(df: pd.DataFrame, table: str, canonical_key: str, *, bucket: str, aws_region: str,
             account_id: str, role_arn: str, args: argparse.Namespace):
    contract = load_registry().table(table)
    auth = authorize_publish(
        PublishTarget(account_id=account_id, bucket=bucket, database=contract["glue_database"],
                      prefix=contract["s3_prefix"].rstrip("/") + "/", role_arn=role_arn, table=table),
        argv=sys.argv,
    )
    logger.info("publish authorized: table=%s mode=%s", table, auth.mode.value)
    s3_client = None
    manifest_store = None
    if auth.mode.value == "dry-run":
        manifest_store = lambda key, body: logger.info(  # noqa: E731
            "dry-run manifest (not persisted): %s (%d bytes)", key, len(body))
    else:
        from leviathan.storage.s3 import get_thread_local_s3_client
        s3_client = get_thread_local_s3_client(aws_region)
    plan = build_flat_publish(
        df=df, contract=contract, canonical_key=canonical_key, auth=auth, s3_client=s3_client,
        job="icco_cocoa_task", run_id=args.run_id, code_sha=args.code_sha,
        manifest_store=manifest_store, min_rows=1,
    )
    manifest = plan.run()
    logger.info("ICCO publish: table=%s state=%s rows=%d mode=%s",
                table, manifest.state.value, plan.row_count, auth.mode.value)
    return manifest


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s", stream=sys.stderr)
    load_env()
    parser = argparse.ArgumentParser(
        description="ICCO QBCS pages -> silver_icco_cocoa_releases -> silver_icco_cocoa")
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

    releases, silver, run_log = build_tables(read_pages(bucket, _PAGES_PREFIX, aws_region))
    logger.info("ICCO run log: %s", json.dumps(run_log, default=str, sort_keys=True))

    releases_contract = load_registry().table(_RELEASES_TABLE)
    for table, df, key in ((_RELEASES_TABLE, releases, flat_key(releases_contract)),
                           (_TABLE, silver, silver_icco_cocoa_key())):
        manifest = _publish(df, table, key, bucket=bucket, aws_region=aws_region,
                            account_id=account_id, role_arn=role_arn, args=args)
        if manifest.state.value == "FAILED":
            logger.error("publish FAILED for %s: %s -- %s", table, manifest.failure_reason,
                         "the served table is NOT touched" if table == _RELEASES_TABLE else "")
            sys.exit(1)


if __name__ == "__main__":
    main()
