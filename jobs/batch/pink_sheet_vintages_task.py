"""AWS Batch task: World Bank Pink Sheet bronze/ -> BITEMPORAL silver/ (the vintages sibling).

Reads BOTH Pink Sheet bronze prefixes, applies ``build_silver_vintages`` -- one row per (data month,
WB release) instead of the latest-only collapse -- and publishes the single silver object through the
SILVER-F015 shadow-first publisher with the INV-2 arrow writer schema from the F010 registry
contract.

Output S3 key: ``silver/pink_sheet_vintages/part-000.parquet``.

WHY A SIBLING TABLE AND NOT AN IN-PLACE WIDEN
---------------------------------------------
``silver_pink_sheet`` declares ``natural_key: [date]`` with ``duplicate_check: full``; multiplying
its rows by release would fire the ``duplicate_natural_keys`` hard failure on essentially every row,
and four other consumers key on "the one row for this month".  So the bitemporal history lands under
its OWN root, with its OWN contract (``natural_key: [release_date, date]``), and the served
latest-only table is untouched.

THE ONLY PLACE THE TWO BRONZE PREFIXES MEET
-------------------------------------------
``jobs/batch/pink_sheet_silver_task.py`` relists exactly
``bronze/production/source=world_bank_pink_sheet/`` and nothing else, so a BACKFILLED vintage
(which lands under ``...source=world_bank_pink_sheet_archive/``) is structurally unreachable from the
served builder.  This task is the one job that reads both and unions them -- and the table it writes
has no numbers card, so nothing the agent reads is downstream of it yet.  That is served-set
invariance by PREFIX, not by a runtime flag a cron can bypass; pinned in
``tests/unit/test_pink_sheet_prefix_fence.py``.

AND SO IT IS WHERE A CROSS-PREFIX COLLISION IS ADJUDICATED.  Nothing stops the Wayback backfill
landing a release the scheduled chain already holds, and unioned that release restates every
``(date, series_name)`` twice.  This job declares the ORIGIN of every frame it read -- the row's own
``source`` column cannot say, because archive bronze is built by the same shipped extractor -- and
``build_silver_vintages`` dedups on ``(release_ym, date, series_name)`` preferring the SCHEDULED
frame, counting the drop.  A release that still breaks a per-release premise is QUARANTINED under a
counted name, never raised: this task is a ``publishes:true`` leg of the autonomous
``pink_sheet_monthly`` chain, so an abort here reds the served chain.

THE CLOCK COMES FROM THE RAW_META SIDECARS, AND ONLY FROM HERE.  Rung 1 of the release-clock ladder
is the ORIGIN's HTTP ``Last-Modified`` recorded AT CAPTURE; bronze has no clock column, so unless
this job reads ``raw_meta/`` every vintage row would say ``derived_month_first`` and the ladder's
distinction between an origin-clocked and an archive-clocked vintage would be unmeasurable.
A release whose sidecar is absent or unreadable takes rung 2 -- declared, never guessed.

FLAT, NOT PARTITIONED.  Volume makes flat correct: 800 months x ~79 columns x N releases is ~3,193
rows at four vintages and ~80k at a hundred, against silver_esr's 1.47M.

``--publish-mode`` defaults to ``dry-run`` (nothing written; the run manifest is a plan) -- a bare run
can never touch the canonical surface (the F004 kill-switch contract).  ``shadow`` stages to the
shadow prefix; ``canonical`` requires the full guard + signed approval and runs on the silver
publisher-runner, never on the flat-silver jobdef.

Usage
-----
    python jobs/batch/pink_sheet_vintages_task.py --bucket B --aws-region R   # dry-run (default)
    python jobs/batch/pink_sheet_vintages_task.py --bucket B --aws-region R --publish-mode shadow
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
from leviathan.storage.paths import parse_hive_key, silver_pink_sheet_vintages_key
from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys
from leviathan.transforms.bronze_to_silver.pink_sheet import (
    ORIGIN_ARCHIVE,
    ORIGIN_SCHEDULED,
    build_silver_vintages,
)

logger = get_logger("pink_sheet_vintages_task")

# THE SCHEDULED prefix and THE ARCHIVE prefix, relisted separately and counted separately, so the
# run log says how many releases came from the monthly chain and how many from the backfill.
_BRONZE_PREFIX = "bronze/production/source=world_bank_pink_sheet/"
_BRONZE_ARCHIVE_PREFIX = "bronze/production/source=world_bank_pink_sheet_archive/"
# THE CLOCK SIDECARS. write_raw_s3_metadata files every raw object's companion record under
# ``raw_meta/{raw_key}_meta.json``, so the sidecar prefix is the raw prefix with that one stem in
# front. This is the ONLY place rung 1 of the release-clock ladder becomes reachable: the origin's
# HTTP Last-Modified is recorded AT CAPTURE and exists nowhere else -- bronze carries no clock
# column, so without this read every row of every vintage takes derived_month_first and the ladder
# is documentation rather than a measurement.
_RAW_META_PREFIX = "raw_meta/raw/production/source=world_bank_pink_sheet/"
_RAW_META_ARCHIVE_PREFIX = "raw_meta/raw/production/source=world_bank_pink_sheet_archive/"
_SILVER_LOG_KEY = "silver/pink_sheet_vintages/_run_log.json"
_TABLE = "silver_pink_sheet_vintages"
_JOB = "pink_sheet_vintages"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pink Sheet bronze -> bitemporal vintages silver")
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


def read_release_clocks(s3_client, bucket: str, aws_region: str) -> dict:
    """``{release_ym: {'http_last_modified': str|None, 'archive': bool}}`` from the raw_meta sidecars.

    ONE RECORD PER RELEASE, and the SCHEDULED sidecar wins when both prefixes describe one release
    -- the same preference the frame dedup applies, for the same reason: the scheduled capture came
    from the origin directly and its ``Last-Modified`` IS the origin's, while an archive replay's
    own header is the CRAWL's and may never reach rung 1.

    ABSENCE IS DECLARED, NEVER GUESSED. A release with no readable sidecar is simply missing from the
    mapping and takes rung 2 in the builder; a sidecar that cannot be parsed is logged and skipped.
    Best-effort by construction: ``write_raw_s3_metadata`` never re-raises, so a sidecar can be
    legitimately absent for an object that landed correctly.
    """
    clocks: dict = {}
    for prefix, archive in ((_RAW_META_ARCHIVE_PREFIX, True), (_RAW_META_PREFIX, False)):
        # ARCHIVE FIRST, SCHEDULED SECOND: the later assignment wins, so the scheduled record
        # overwrites an archive record for the same release.
        try:
            keys = list_s3_keys(bucket, prefix, suffix=".json", aws_region=aws_region)
        except Exception as exc:  # noqa: BLE001 -- an unreadable sidecar prefix is rung 2, not a crash
            logger.warning("raw_meta listing failed for %s: %s -- those releases take rung 2",
                           prefix, exc)
            continue
        for key in sorted(keys):
            release = parse_hive_key(key, "release")
            if not release:
                continue
            try:
                body = s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
                record = json.loads(body.decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("raw_meta unreadable %s: %s -- release %s takes rung 2",
                               key, exc, release)
                continue
            # LAW 4 (pink_sheet_release.release_clock): on an ARCHIVE body only the ORIGIN header may
            # reach rung 1. The backfill records it under `origin_last_modified`; the replay's own
            # `http_last_modified` is the archive's clock and is deliberately NOT read here.
            header = (record.get("origin_last_modified") if archive
                      else record.get("http_last_modified"))
            clocks[release] = {"http_last_modified": header, "archive": archive,
                               "raw_meta_key": key}
    return clocks


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

    logger.info("pink_sheet_vintages_task bucket=%s mode=%s", bucket, args.publish_mode)

    start = datetime.now(timezone.utc)
    s3 = get_thread_local_s3_client(aws_region)

    # ------------------------------------------------------------------
    # Step 1 -- discover and download BOTH bronze prefixes
    # ------------------------------------------------------------------
    scheduled_keys = sorted(
        list_s3_keys(bucket, _BRONZE_PREFIX, suffix=".parquet", aws_region=aws_region)
    )
    archive_keys = sorted(
        list_s3_keys(bucket, _BRONZE_ARCHIVE_PREFIX, suffix=".parquet", aws_region=aws_region)
    )
    logger.info("bronze scheduled=%d archive=%d", len(scheduled_keys), len(archive_keys))
    bronze_keys = scheduled_keys + archive_keys
    # ORIGIN IS A PROPERTY OF THE PREFIX, NOT OF THE ROW: archive bronze is written by the SAME
    # shipped extractor, so every row of both prefixes carries source == 'world_bank_pink_sheet'.
    # This list is the only place that knowledge exists, and it is what decides which frame wins a
    # cross-prefix collision on one release.
    origins = ([ORIGIN_SCHEDULED] * len(scheduled_keys)) + ([ORIGIN_ARCHIVE] * len(archive_keys))
    if not bronze_keys:
        logger.error("No bronze Parquets found under %s or %s -- aborting.",
                     _BRONZE_PREFIX, _BRONZE_ARCHIVE_PREFIX)
        sys.exit(1)

    dfs: list[pd.DataFrame] = []
    for key in bronze_keys:
        df = _download_parquet(s3, bucket, key)
        dfs.append(df)
        logger.info("downloaded %s rows=%d", key, len(df))

    # TWO DIFFERENT NUMBERS, NAMED APART. `object_count` is how many bronze OBJECTS were read -- the
    # S3 listing's own tally. `vintage_count` is how many distinct releases those objects carry, read
    # off the rows' own `release_ym` rather than off a key's `release=` path label. They diverge
    # exactly when the two prefixes both hold a release, which is the case the dedup below exists
    # for, so reporting the object count under a vintage-count name would hide the one event it is
    # meant to surface.
    object_count = len(dfs)
    release_yms = sorted({
        str(v) for df in dfs if "release_ym" in df.columns and len(df) > 0
        for v in df["release_ym"].dropna().unique()          # EVERY release a frame carries, not row 0
    })
    vintage_count = len(release_yms)
    logger.info("object_count=%d vintage_count=%d releases=%s",
                object_count, vintage_count, release_yms)

    # ------------------------------------------------------------------
    # Step 1b -- the CLOCK sidecars (rung 1 of the release-clock ladder)
    # ------------------------------------------------------------------
    clocks = read_release_clocks(s3, bucket, aws_region)
    logger.info("release clocks read from raw_meta: %d of %d release(s) have a sidecar; "
                "the rest take derived_month_first", len(clocks), vintage_count)

    # ------------------------------------------------------------------
    # Step 2 -- build the bitemporal table (one row per data month PER RELEASE)
    # ------------------------------------------------------------------
    declines: dict = {}
    counters: dict = {}
    df_silver = build_silver_vintages(dfs, origins=origins, clocks=clocks,
                                      declines=declines, counters=counters)
    # ABSENCE IS NEVER ZERO: both lines are logged whether or not anything fired, so "no quarantine"
    # is an observation rather than a missing log line.
    logger.info("VINTAGE_COUNTERS %s", json.dumps(counters, sort_keys=True))
    logger.info("VINTAGE_QUARANTINE %s", json.dumps(declines, sort_keys=True))
    silver_rows = len(df_silver)
    date_min = str(df_silver["date"].min().date()) if silver_rows else "n/a"
    date_max = str(df_silver["date"].max().date()) if silver_rows else "n/a"
    vintages = sorted(df_silver["release_ym"].unique()) if silver_rows else []
    logger.info("build_silver_vintages -> %d rows vintages=%d %s date_range=%s..%s",
                silver_rows, len(vintages), vintages, date_min, date_max)

    # ------------------------------------------------------------------
    # Step 3 -- publish through the shadow-first publisher (INV-2 schema)
    # ------------------------------------------------------------------
    silver_key = silver_pink_sheet_vintages_key()
    # dry-run stages nothing (no client); shadow + canonical both write to S3.
    publish_s3 = None if args.publish_mode == "dry-run" else s3
    plan = build_flat_publish(
        df=df_silver, contract=contract, canonical_key=silver_key, auth=auth,
        s3_client=publish_s3, job=_JOB,
    )
    manifest = plan.run()
    logger.info("publish %s mode=%s state=%s", silver_key, args.publish_mode, manifest.state.value)
    if manifest.state not in (ManifestState.VALIDATED, ManifestState.CERTIFIED):
        raise RuntimeError(f"pink_sheet_vintages publish failed: state={manifest.state.value} "
                           f"reason={manifest.failure_reason}")

    # ------------------------------------------------------------------
    # Step 4 -- run log (canonical only; control-plane artifact)
    # ------------------------------------------------------------------
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    if auth.may_mutate_canonical:
        run_log = {
            "run_date": datetime.now(timezone.utc).date().isoformat(),
            "elapsed_s": round(elapsed, 1),
            "object_count": object_count,
            "vintage_count": vintage_count,
            "releases": release_yms,
            "bronze_scheduled": len(scheduled_keys),
            "bronze_archive": len(archive_keys),
            "release_clocks_from_sidecar": len(clocks),
            "counters": counters,
            "quarantined": declines,
            "vintages": list(vintages),
            "silver_rows": silver_rows,
            "date_min": date_min,
            "date_max": date_max,
        }
        s3.put_object(Bucket=bucket, Key=_SILVER_LOG_KEY,
                      Body=json.dumps(run_log, indent=2).encode(), ContentType="application/json")
    logger.info("Done mode=%s rows=%d vintages=%d elapsed=%.1fs",
                args.publish_mode, silver_rows, len(vintages), elapsed)


if __name__ == "__main__":
    main()
