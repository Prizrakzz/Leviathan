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
import logging
import os
import sys

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.silver.flat_producer import authorize_for_contract, build_flat_publish
from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import parse_hive_key, silver_psd_key
from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys
from leviathan.transforms.bronze_to_silver.usda_psd import transform_psd_bronze_to_silver

logger = get_logger("psd_silver_task")

_BRONZE_PREFIX = "bronze/production/source=usda_psd/"
_RAW_BULK_PREFIX = "raw/production/source=usda_psd/release_type=bulk/"
_TABLE = "silver_psd"
_JOB = "psd_silver"


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
    transform pays 8.5 GiB to load and then discards at usda_psd.py:400.

    Keeping the NEWEST label per ETag is content-preserving by construction: step 11.5 of
    the transform already resolves a re-printed vintage by keeping the latest
    release_date, so dropping an OLDER byte-identical copy can change nothing it would
    have kept.

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

    logger.info("Running PSD silver transform on %d bronze DataFrames", len(dfs))
    try:
        silver_df = transform_psd_bronze_to_silver(dfs)
    except Exception as exc:  # noqa: BLE001
        logger.error("PSD silver transform failed: %s", exc)
        sys.exit(1)

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
