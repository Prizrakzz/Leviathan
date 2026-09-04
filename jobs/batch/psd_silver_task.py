"""AWS Batch entrypoint: USDA PSD bronze -> silver (shadow-first, SILVER-F015/INV-6).

Downloads all PSD bronze Parquets (one per monthly release date), applies the
silver transform, enforces the F2 fail-closed release_date guard, and publishes
the flat table:

    silver/psd/part-000.parquet

Publish contract (A-W4 CLASS-B retrofit)
----------------------------------------
The silver write is routed through the SILVER-F015 shadow-first controlled
publisher via ``leviathan.silver.flat_producer.build_flat_publish`` with an
EXPLICIT registry-derived INV-2 arrow schema (the F010 ``silver_psd`` contract).
``--publish-mode`` (default ``dry-run``) resolves through the publish guard:

  * dry-run   : nothing is written anywhere (the manifest is an in-memory plan).
  * shadow    : the object is staged ONLY under ``silver/psd/_shadow/`` and
                validated; the canonical object is never touched.
  * canonical : shadow-stage -> validate -> promote -> catalog, but ONLY with a
                verified signed approval (the guard raises otherwise before any write).

This replaces the former latest-only ``put_object`` overwrite so a red rebuild
gate can protect the canonical write (a red gate cannot protect data already
overwritten). The legacy ``--dry-run`` flag is retained as an alias for
``--publish-mode dry-run``. The bespoke ``silver/psd/_run_log.json`` is retired
in favour of the publisher's per-run manifest under ``silver/psd/_manifests/``.

Usage
-----
    python jobs/batch/psd_silver_task.py                          # dry-run (writes nothing)
    python jobs/batch/psd_silver_task.py --publish-mode shadow
    python jobs/batch/psd_silver_task.py --publish-mode canonical --force-overwrite
    python jobs/batch/psd_silver_task.py --dry-run
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys

import boto3
import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.silver.flat_producer import authorize_for_contract, build_flat_publish
from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import parse_hive_key, silver_psd_key
from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys
from leviathan.transforms.bronze_to_silver.usda_psd import (
    _CLOCK_COUNTER_KEYS,
    _PSD_COMMODITY_TO_SLUGS,
    transform_psd_bronze_to_silver,
)

logger = get_logger("psd_silver_task")

_BRONZE_PREFIX = "bronze/production/source=usda_psd/"
_RAW_BULK_PREFIX = "raw/production/source=usda_psd/release_type=bulk/"
_TABLE = "silver_psd"
_JOB = "psd_silver"
_CALENDAR_TABLE = "silver_wasde"


def _exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001
        return False


def _download_parquet(s3_client, bucket: str, key: str) -> pd.DataFrame:
    resp = s3_client.get_object(Bucket=bucket, Key=key)
    return pd.read_parquet(io.BytesIO(resp["Body"].read()))


def _caller_identity(aws_region: str) -> tuple[str, str]:
    """Best-effort STS identity for the canonical publish target (empty on failure).

    Thin wrapper over the shared resolver ``leviathan.common.aws_identity.resolve_caller_identity``
    (the one idiom the batch-task family shares). Kept as a module-level seam so tests can
    monkeypatch it and readiness/unit runs stay AWS-free; an empty identity still makes the publish
    guard fail closed on the canonical path exactly as before."""
    from leviathan.common.aws_identity import resolve_caller_identity

    return resolve_caller_identity(aws_region)


# ---------------------------------------------------------------------------
# THE WASDE RELEASE CALENDAR -- READ AT RUN TIME, NEVER BAKED INTO THE IMAGE
# ---------------------------------------------------------------------------

def _glue_client(aws_region: str):
    """A Glue client.  This module held NONE before the honest-clock change.

    Kept as its own module-level seam so tests can monkeypatch it and unit runs
    stay AWS-free, exactly like ``_caller_identity`` above.
    """
    return boto3.client("glue", region_name=aws_region)


def wasde_release_calendar(aws_region: str, glue_client=None) -> dict[str, int]:
    """``{'YYYY-MM': day}`` from the REGISTERED silver_wasde partitions.

    WHY IT IS READ HERE AND NOT GENERATED INTO THE IMAGE.  The PSD clock needs the
    day of each month's WASDE release, and it FAILS CLOSED on a stamp month newer
    than the newest month it is given.  silver_wasde's newest partition and the
    newest PSD stamp advance in LOCKSTEP every month, and psd_monthly fires
    ``cron(0 18 8-13 * ? *)``, so a calendar baked into the worker image would
    RED-STOP this DAG every single month until a new image, a terraform digest
    bump and a jobdef re-register had landed first.  A one-time build step cannot
    be a monthly mechanism.  Read live, the fail-closed raise fires only when USDA
    publishes a PSD file whose newest stamp is a month silver_wasde has not yet
    ingested -- a real ordering problem worth stopping for.

    GET-PARTITIONS, NEVER MSCK.  configs/silver/tables/silver_wasde.yaml declares
    ``partition_mode: registered``, ``projection: forbidden`` and a
    recovery_strategy of "get-partitions reconcile + explicit per-partition
    locations ... never MSCK".  This function obeys that contract; it only ever
    READS.

    Raises:
        ValueError: If the catalog returns no registered partitions.  An empty
            calendar would date every row by convention with no measurement behind
            it, so it must stop the run.
    """
    contract = load_registry().table(_CALENDAR_TABLE)
    # Both the database AND the table name come from the F010 contract, never from
    # a literal here: the contract is the single authority for where a silver table
    # lives, and a second spelling of it is a rename waiting to go silent.
    database, table = contract["glue_database"], contract["table_name"]
    glue_client = glue_client or _glue_client(aws_region)
    days: dict[str, int] = {}
    n_partitions = 0
    paginator = glue_client.get_paginator("get_partitions")
    for page in paginator.paginate(DatabaseName=database, TableName=table,
                                   PaginationConfig={"PageSize": 1000}):
        for part in page.get("Partitions", []):
            values = part.get("Values") or []
            if not values:
                continue
            release_date = str(values[0])
            if len(release_date) != 10:
                logger.warning("silver_wasde partition %r is not a YYYY-MM-DD date; skipped",
                               release_date)
                continue
            n_partitions += 1
            month, day = release_date[:7], int(release_date[8:10])
            prior = days.get(month)
            if prior is not None and prior != day:
                # One release per calendar month is what the live catalog shows
                # (472 partitions, 1985-01..2026-08, no month with two). If that
                # ever stops holding, take the LATEST day and SAY SO -- a
                # correction that displaces a primary release is a real event, not
                # a tie to break silently.
                logger.warning(
                    "silver_wasde carries TWO releases for %s (days %d and %d); taking the "
                    "later one for the PSD clock", month, prior, day,
                )
                day = max(prior, day)
            days[month] = day
    if not days:
        raise ValueError(
            "PSD clock: silver_wasde returned NO registered partitions from Glue database "
            "%r. The release calendar is required and must never be empty -- an empty "
            "calendar would date every PSD row by a month-end convention with nothing "
            "measured behind it." % database
        )
    logger.info(
        "WASDE release calendar read from registered partitions: months=%d partitions=%d "
        "span=%s..%s", len(days), n_partitions, min(days), max(days),
    )
    return days


def log_clock_counters(counters: dict) -> None:
    """Emit every clock counter as ONE machine-readable line the gate can read.

    A counter that lives only in a prose log line is not a gate reading.
    """
    payload = {k: counters.get(k) for k in _CLOCK_COUNTER_KEYS}
    logger.info("PSD_CLOCK_COUNTERS %s", json.dumps(payload, sort_keys=True, default=str))


# ---------------------------------------------------------------------------
# THE SIBLING-DAG RACE, AND THE BOUNDED WAIT THAT ABSORBS IT
# ---------------------------------------------------------------------------
# THE EXPOSURE, NAMED. psd_monthly and wasde_monthly BOTH fire cron(0 18 8-13 * ? *)
# with NO ordering dependency between them, and the PSD clock FAILS CLOSED on a stamp
# month strictly newer than the newest REGISTERED silver_wasde partition. Those two
# facts collide on exactly one day a month: this task's own ETag measurement (see
# _distinct_release_dates) shows the vendor's PSD object flipping content ON the WASDE
# day -- 08-08/09/10/11 share one ETag and 08-12/13 share the next, with 2026-08-12 the
# registered WASDE day -- and b_20260813 carries 31,610 in-scope rows stamped 2026-08.
# So on the WASDE day the new PSD bulk file can be in the bucket BEFORE the concurrent
# WASDE chain has fetched, transformed and REGISTERED its own partition, and the clock
# would then raise on a condition that resolves itself within the hour.
#
# WHAT WE DO ABOUT IT, AND WHAT WE DELIBERATELY DO NOT. We do not sequence the two DAGs
# (that is a scheduler change with its own blast radius and it is not this lane's), and
# we do not weaken the raise -- a silent month-end fallback on TODAY's stamp month would
# move today's citation by up to ~19 days with no counter, which is the whole defect
# lane E exists to close. We WAIT, BOUNDED, and then fail closed exactly as before:
#
#   * up to _WASDE_WAIT_MAX_SECONDS (90 minutes) in total,
#   * re-reading the REGISTERED partitions every _WASDE_WAIT_POLL_SECONDS (5 minutes),
#   * i.e. at most 18 polls, each one a get-partitions read and nothing else.
#
# NINETY MINUTES is chosen against the sibling chain's own shape, not as a round number:
# wasde_monthly's fetch -> bronze -> silver -> register path is minutes of work on a
# schedule that starts in the SAME cron minute, so an hour and a half is generous cover
# for a slow fire and still far inside the job's own timeout. Past the bound the run
# exits 1 with the stamp month and the newest registered month NAMED -- a WASDE chain
# that has genuinely failed must red psd_monthly, because publishing PSD rows dated by a
# convention we never measured is the worse outcome.
_WASDE_WAIT_MAX_SECONDS = 90 * 60
_WASDE_WAIT_POLL_SECONDS = 5 * 60


def _newest_psd_stamp_month(dfs: list[pd.DataFrame]) -> str | None:
    """The newest ``YYYY-MM`` stamp among IN-SCOPE, STAMPED bronze rows, or None.

    In-scope because the clock only ever dates rows the commodity filter keeps, and
    stamped because ``month_code == 0`` carries no publication month at all. Rows the
    transform would refuse (a coerced NA month_code, a non-positive calendar_year) are
    skipped here and left to the clock to raise on: this function decides whether to
    WAIT, and it must never invent a reason to.
    """
    newest: str | None = None
    for df in dfs:
        if not len(df) or "month_code" not in df.columns or "calendar_year" not in df.columns:
            continue
        if "commodity_code" in df.columns:
            df = df[df["commodity_code"].isin(_PSD_COMMODITY_TO_SLUGS)]
            if not len(df):
                continue
        mc = pd.to_numeric(df["month_code"], errors="coerce")
        cy = pd.to_numeric(df["calendar_year"], errors="coerce")
        ok = mc.notna() & (mc > 0) & cy.notna() & (cy > 0)
        if not bool(ok.any()):
            continue
        stamps = (cy[ok].astype("int64").astype(str).str.zfill(4) + "-"
                  + mc[ok].astype("int64").astype(str).str.zfill(2))
        top = str(stamps.max())
        if newest is None or top > newest:
            newest = top
    return newest


def wait_for_wasde_calendar(
    dfs: list[pd.DataFrame],
    calendar: dict[str, int],
    aws_region: str,
    *,
    glue_client=None,
    sleep=None,
    max_seconds: int = _WASDE_WAIT_MAX_SECONDS,
    poll_seconds: int = _WASDE_WAIT_POLL_SECONDS,
) -> dict[str, int]:
    """Re-read the registered calendar until it covers the newest PSD stamp month.

    Returns the calendar to use. Returns the one it was given, unchanged and without a
    single extra Glue call, whenever the newest stamp month is already covered -- which
    is every day of the month except the one this function exists for.

    ``sleep`` and ``glue_client`` are injected seams so the wait path is testable
    without AWS and without wall-clock time.
    """
    stamp = _newest_psd_stamp_month(dfs)
    if stamp is None or not calendar or stamp <= max(calendar):
        return calendar
    if sleep is None:
        import time as _time
        sleep = _time.sleep
    waited = 0
    logger.warning(
        "PSD clock: newest PSD stamp month %s is NEWER than the newest registered "
        "silver_wasde month %s. psd_monthly and wasde_monthly share cron(0 18 8-13) with no "
        "ordering dependency, so this is most likely the sibling chain still registering "
        "today's partition. WAITING up to %d minute(s), re-reading get-partitions every %d "
        "minute(s), then failing closed.",
        stamp, max(calendar), max_seconds // 60, poll_seconds // 60,
    )
    while waited < max_seconds:
        sleep(poll_seconds)
        waited += poll_seconds
        try:
            fresh = wasde_release_calendar(aws_region, glue_client=glue_client)
        except Exception as exc:  # noqa: BLE001
            logger.warning("PSD clock: calendar re-read failed after %ds (%s); still waiting",
                           waited, exc)
            continue
        # MERGE, NEVER REPLACE (post-fix re-review M2): wasde_release_calendar raises only on ZERO
        # partitions, so a short-but-nonempty Glue listing would otherwise SHRINK the calendar,
        # satisfy `stamp <= max(calendar)` on the one new month, and drop every other month to the
        # month-end fallback with no raise. A re-read may only ADD months.
        lost = sorted(set(calendar) - set(fresh))
        if lost:
            logger.warning("PSD clock: calendar re-read lacks %d previously registered month(s) "
                           "(first: %s); keeping them -- a re-read may only add.", len(lost), lost[:3])
        calendar = {**calendar, **fresh}
        if calendar and stamp <= max(calendar):
            logger.info(
                "PSD clock: silver_wasde now carries %s after waiting %ds; the race resolved "
                "itself and the run continues.", max(calendar), waited,
            )
            return calendar
    logger.error(
        "PSD clock: waited %ds and silver_wasde still stops at %s while the PSD file is "
        "stamped %s. This is no longer a same-cron race -- the WASDE chain has not "
        "registered its partition. Failing closed: dating today's rows by a convention with "
        "nothing measured behind it would move the freshest citation silently.",
        waited, max(calendar) if calendar else "(empty)", stamp,
    )
    return calendar


# ---------------------------------------------------------------------------
# Fail-closed release_date guard (F2) -- PRESERVED
# ---------------------------------------------------------------------------

def _snapshot_ingest_date(dfs: list[pd.DataFrame]) -> str:
    """Newest bronze ingest date across all partitions, as a 'YYYY-MM-DD' string.

    Bronze stamps every row with its download (ingest) date. A release can never
    be known before the snapshot that observed it, so the newest ingest date is
    the hard upper bound for every silver release_date.
    """
    stamps = []
    for df in dfs:
        if "release_date" in df.columns and len(df):
            stamps.append(pd.to_datetime(df["release_date"]).max())
    if not stamps:
        raise ValueError(
            "PSD guard: no bronze release_date values found to bound silver dates"
        )
    return max(stamps).strftime("%Y-%m-%d")


def _assert_release_dates_not_future(silver_df: pd.DataFrame, ingest_date: str) -> None:
    """Abort if any silver release_date post-dates the bronze snapshot ingest date.

    The silver transform clamps computed WASDE release_dates to the ingest date,
    so a future date reaching this guard means the clamp was bypassed or has
    regressed. Raising prevents a silent recurrence of future-dated PSD rows in
    the serving layer.

    Comparison is lexical over 'YYYY-MM-DD' strings, which equals chronological
    order for ISO-8601 dates.
    """
    if silver_df.empty:
        return
    rd = silver_df["release_date"].astype(str)
    future_mask = rd > ingest_date
    n_future = int(future_mask.sum())
    if n_future:
        sample = sorted(rd[future_mask].unique())[:5]
        raise ValueError(
            "PSD silver guard: %d release_date row(s) post-date the bronze snapshot "
            "ingest date %s (clamp bypassed or regressed). Examples: %s"
            % (n_future, ingest_date, sample)
        )


# ---------------------------------------------------------------------------
# Bronze load
# ---------------------------------------------------------------------------

def _distinct_release_dates(s3_client, bucket: str) -> tuple[set[str] | None, set[str]]:
    """The release_date labels whose RAW vendor zip is the NEWEST copy of its content.

    fetch_usda_psd.py stamps ``release_date`` with the FETCH date (its default is
    ``date.today()``), and psd_monthly fires on days 8-13, so ONE monthly USDA bulk file
    lands under up to six different release_date labels. Measured 2026-08-16 on the live
    prefix: 08-08/09/10/11 all carry ETag d085f3d1a6048cedcbc9b5df94e07b21 and 08-12/13
    both carry bd5be5458e069a6f8ccc260acfff4b4f -- 8 bronze partitions, 4 distinct vendor
    releases, and 8,238,412 of the 16,735,546 concatenated rows are exact duplicates the
    transform pays 8.5 GiB to load and then discards at usda_psd.py:1224 (step 10's
    ``combined.duplicated(subset=dedup_key)``).

    Keeping the NEWEST label per ETag is content-preserving by construction, and the
    property it rests on is STEP 10, not step 11.5. Step 10 (usda_psd.py, "Dedup before
    pivot") sorts every duplicate of one (slug, country, market_year, release_date,
    attribute_desc) by ``bronze_ingest_date`` and keeps LAST, so of two byte-identical
    copies of one vendor release the newer-labelled one already wins and the older one is
    discarded there. Dropping the older copy up here can therefore change nothing the
    transform would have kept. (Step 11.5 used to be the latest-only vintage reduction
    this sentence named; under the honest clock it is an ASSERTION that deletes nothing --
    it counts the re-prints the retired key would have deleted and raises on a duplicate
    vintage key. It is no longer a load-bearing premise for this rider.)

    Returns ``(keep, seen_raw)``: ``keep`` is the newest-label-per-ETag set (None = keep
    everything, if the raw prefix cannot be read -- a listing failure degrades to today's
    behaviour instead of silently truncating history); ``seen_raw`` is EVERY release_date
    observed under the raw prefix. A bronze partition whose release_date is absent from
    ``seen_raw`` has no raw counterpart to judge it a duplicate BY, so the caller must
    KEEP it -- dropping it would silently truncate the input of a self-promoting
    canonical transform on the strength of an absent object.
    """
    try:
        newest: dict[str, str] = {}
        seen_raw: set[str] = set()
        paginator = s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=_RAW_BULK_PREFIX):
            for obj in page.get("Contents", []):
                rd = parse_hive_key(obj["Key"], "release_date")
                if not rd:
                    continue
                seen_raw.add(rd)
                etag = obj["ETag"].strip('"')
                if etag not in newest or rd > newest[etag]:
                    newest[etag] = rd
        return (set(newest.values()) or None, seen_raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("raw ETag dedup unavailable (%s) -- loading every bronze partition", exc)
        return None, set()


def _load_bronze(bucket: str, aws_region: str, s3_client) -> list[pd.DataFrame]:
    bronze_keys = sorted(
        list_s3_keys(bucket, _BRONZE_PREFIX, suffix="part-000.parquet", aws_region=aws_region)
    )
    if not bronze_keys:
        logger.error("No bronze PSD Parquets found under %s -- aborting", _BRONZE_PREFIX)
        sys.exit(1)
    keep, seen_raw = _distinct_release_dates(s3_client, bucket)
    if keep is not None:
        selected = []
        orphans = []
        for k in bronze_keys:
            rd = parse_hive_key(k, "release_date")
            if rd in keep:
                selected.append(k)
            elif rd not in seen_raw:
                # No raw counterpart exists to judge this partition a duplicate BY
                # (raw expiry / hand-delete / bronze-without-raw). KEEP it: the dedup
                # may only drop a partition raw PROVES is an older copy.
                selected.append(k)
                orphans.append(rd)
        if orphans:
            logger.info(
                "bronze dedup: %d partition(s) have no raw counterpart and are KEPT: %s",
                len(orphans), sorted(orphans),
            )
        if selected:
            logger.info(
                "bronze dedup by raw ETag: %d of %d partitions carry distinct vendor "
                "content; skipping %d re-download(s) of an unchanged release",
                len(selected), len(bronze_keys), len(bronze_keys) - len(selected),
            )
            bronze_keys = selected
    logger.info("Loading %d bronze PSD Parquets ...", len(bronze_keys))
    dfs: list[pd.DataFrame] = []
    for key in bronze_keys:
        try:
            dfs.append(_download_parquet(s3_client, bucket, key))
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to download %s: %s", key, exc)
            sys.exit(1)
    return dfs


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------

def _publish_psd(
    df: pd.DataFrame,
    contract: dict,
    auth,
    s3_client,
    bucket: str,
    *,
    force_overwrite: bool,
) -> ManifestState | None:
    """Publish the flat PSD silver object through the shadow-first publisher. Returns the manifest
    state, or ``None`` when an existing canonical object is skipped (canonical mode only)."""
    canonical_key = silver_psd_key()
    if (
        not force_overwrite
        and auth.may_mutate_canonical
        and s3_client is not None
        and _exists(s3_client, bucket, canonical_key)
    ):
        logger.info(
            "silver exists -- use --publish-mode canonical --force-overwrite to re-run: %s",
            canonical_key,
        )
        return None
    plan = build_flat_publish(
        df=df, contract=contract, canonical_key=canonical_key,
        auth=auth, s3_client=s3_client, job=_JOB,
    )
    manifest = plan.run()
    logger.info(
        "PSD silver publish mode=%s state=%s rows=%d key=%s",
        auth.mode.value, manifest.state.value, len(df), canonical_key,
    )
    return manifest.state


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(description="USDA PSD bronze -> silver (shadow-first)")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="Alias for --publish-mode dry-run (writes nothing).")
    parser.add_argument("--publish-mode", default="dry-run",
                        choices=["dry-run", "shadow", "canonical"], dest="publish_mode",
                        help="dry-run|shadow|canonical (default dry-run; canonical needs a signed approval)")
    parser.add_argument("--role-arn", default="", dest="role_arn")
    parser.add_argument("--account-id", default="", dest="account_id")
    args = parser.parse_args()

    publish_mode = "dry-run" if args.dry_run else args.publish_mode
    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    contract = load_registry().table(_TABLE)

    account_id, role_arn = args.account_id, args.role_arn
    if publish_mode == "canonical" and not account_id and not role_arn:
        account_id, role_arn = _caller_identity(aws_region)
    auth = authorize_for_contract(
        contract, publish_mode=publish_mode,
        role_arn=role_arn, account_id=account_id, env=os.environ,
    )
    logger.info("publish authorized: mode=%s may_canonical=%s", auth.mode.value, auth.may_mutate_canonical)

    # A read client is always needed to load bronze; the publisher only writes in shadow/canonical.
    s3_read = get_thread_local_s3_client(aws_region)
    publish_client = None if publish_mode == "dry-run" else s3_read

    dfs = _load_bronze(bucket, aws_region, s3_read)

    # The clock's calendar, read LIVE from the registered silver_wasde partitions
    # (never baked, never MSCK) and passed into the pure transform as a plain dict
    # so the transform keeps the "No S3 or AWS dependencies" property its own
    # docstring claims.
    try:
        calendar = wasde_release_calendar(aws_region)
    except Exception as exc:  # noqa: BLE001
        logger.error("PSD silver: could not read the WASDE release calendar: %s", exc)
        sys.exit(1)

    # THE SAME-CRON RACE. On the WASDE day the new PSD bulk file can land before the
    # sibling wasde_monthly chain has registered its partition; the clock would then
    # raise on a condition that resolves itself within the hour. Wait, bounded, then
    # let the transform fail closed exactly as it would have. See the block above
    # wait_for_wasde_calendar for the exposure and why the bound is 90 minutes.
    calendar = wait_for_wasde_calendar(dfs, calendar, aws_region)

    logger.info("Running PSD silver transform on %d bronze DataFrames", len(dfs))
    counters: dict = {}
    try:
        silver_df = transform_psd_bronze_to_silver(dfs, calendar=calendar, counters=counters)
    except Exception as exc:  # noqa: BLE001
        log_clock_counters(counters)
        logger.error("PSD silver transform failed: %s", exc)
        sys.exit(1)
    log_clock_counters(counters)

    logger.info(
        "Silver DataFrame: rows=%d cols=%d slugs=%d releases=%d",
        len(silver_df), len(silver_df.columns),
        silver_df["leviathan_slug"].nunique(), silver_df["release_date"].nunique(),
    )

    # Fail-closed guard (F2): no silver release_date may post-date the bronze snapshot ingest date.
    ingest_date = _snapshot_ingest_date(dfs)
    try:
        _assert_release_dates_not_future(silver_df, ingest_date)
    except ValueError as exc:
        logger.error("%s", exc)
        sys.exit(1)
    logger.info("PSD guard OK: all release_dates <= snapshot ingest date %s", ingest_date)

    if publish_mode == "dry-run":
        logger.info("dry-run -- would publish %s rows=%d", silver_psd_key(), len(silver_df))

    _publish_psd(silver_df, contract, auth, publish_client, bucket,
                 force_overwrite=args.force_overwrite)


if __name__ == "__main__":
    main()
