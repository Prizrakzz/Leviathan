"""AWS Batch entrypoint: USDA PSD bronze -> silver LONG attributes (shadow-first, SILVER-F015/INV-6).

The LONG companion to ``jobs/batch/psd_silver_task.py``. Both producers read the SAME bronze
objects under the SAME raw-ETag dedup rider and enforce the SAME F2 fail-closed release_date
guard; they differ only in the transform they run and the object they publish:

    silver/psd/part-000.parquet             <- psd_silver_task (wide, 8 attributes, MT-converted)
    silver/psd_attributes/part-000.parquet  <- this task       (long, every attribute, native units)

The bronze load and the F2 guard are IMPORTED from ``psd_silver_task``, never re-implemented:
two copies of one prefix are two tables that drift apart silently, which is exactly why the two
TRANSFORMS share ``prepare_psd_combined_frame`` one layer down. The import is one-way (this
module -> psd_silver_task) and psd_silver_task's CLI and semantics are untouched by it; that
producer is wired to the live psd_monthly schedule.

Publish contract (A-W4 CLASS-B retrofit)
----------------------------------------
The silver write is routed through the SILVER-F015 shadow-first controlled publisher via
``leviathan.silver.flat_producer.build_flat_publish`` with an EXPLICIT registry-derived INV-2
arrow schema (the F010 ``silver_psd_attributes`` contract). ``--publish-mode`` (default
``dry-run``) resolves through the publish guard:

  * dry-run   : nothing is written anywhere (the manifest is an in-memory plan).
  * shadow    : the object is staged ONLY under ``silver/psd_attributes/_shadow/`` and
                validated; the canonical object is never touched.
  * canonical : shadow-stage -> validate -> promote -> catalog, but ONLY with a verified signed
                approval (the guard raises otherwise before any write).

Usage
-----
MODULE FORM ONLY. This task imports ``jobs.batch.psd_silver_task``, which requires the repository
root on ``sys.path``; script form (``python jobs/batch/psd_attributes_silver_task.py``) puts only
``jobs/batch/`` there and cannot resolve it. The Batch job definition bakes the module form for
the same reason.

    python -m jobs.batch.psd_attributes_silver_task                       # dry-run (writes nothing)
    python -m jobs.batch.psd_attributes_silver_task --publish-mode shadow
    python -m jobs.batch.psd_attributes_silver_task --publish-mode canonical --force-overwrite

``--force-overwrite`` IS ``store_true`` AND DEFAULTS TO FALSE, AND THE DEFAULT IS A SILENT NO-OP
AGAINST AN EXISTING TABLE. A ``--publish-mode canonical`` run WITHOUT the flag, with the canonical
object already present, publishes NOTHING and still EXITS 0 -- the skip is an INFO line, not a
failure, so the job reports success while the table is untouched. Every scheduled fire passes
``--force-overwrite`` for exactly this reason; a hand-run that omits it is a no-op, not a rebuild.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

import pandas as pd
from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.silver.flat_producer import authorize_for_contract, build_flat_publish
from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import silver_psd_attributes_key
from leviathan.storage.s3 import get_thread_local_s3_client
from leviathan.transforms.bronze_to_silver.usda_psd import (
    _COTTON_CONSUMPTION_ATTR,
    _COTTON_SLUGS,
    _FRESH_CONSUMPTION_ATTR,
    _FRESH_SLUGS,
    _SUGAR_CONSUMPTION_ATTR,
    _SUGAR_SLUGS,
    _TARGET_ATTRS,
)
from leviathan.transforms.bronze_to_silver.usda_psd_attributes import (
    _GRAIN_COLS,
    transform_psd_attributes_bronze_to_silver,
)

from jobs.batch.psd_silver_task import (
    _assert_release_dates_not_future,
    _caller_identity,
    _exists,
    _load_bronze,
    _snapshot_ingest_date,
)

logger = get_logger("psd_attributes_silver_task")

_TABLE = "silver_psd_attributes"
_JOB = "psd_attributes_silver"

# The attribute labels the WIDE silver_psd table already serves, in USDA's OWN spellings: the
# eight it pivots, plus the three consumption labels its step-5 remaps fold onto "Domestic
# Consumption". The aliases belong in this set because the long table emits the NATIVE label, so
# sugar's "Total Disappearance" and cotton's "Domestic Use" are already-served rows wearing their
# source spelling. Imported from the wide producer, never re-typed -- a re-typed copy of a
# source's labels drifts silently, which is the failure the long table's R4 registry keys on
# attribute_id to avoid one layer down.
_WIDE_SERVED_ATTRS: frozenset[str] = _TARGET_ATTRS | {
    _SUGAR_CONSUMPTION_ATTR,
    _COTTON_CONSUMPTION_ATTR,
    _FRESH_CONSUMPTION_ATTR,
}

# THE ALIASES ARE SLUG-GATED, exactly as the wide producer's step-5 remaps are (usda_psd.py:719-731):
# "Total Disappearance" is wide-served on raw_sugar/white_sugar ONLY, "Domestic Use" on cotton ONLY,
# "Fresh Dom. Consumption" on fresh_citrus ONLY. The same native labels ride OTHER slugs too
# (cottonseed's family emits 142, frozen_orange_juice emits 135) and silver_psd DROPS those rows --
# counting them as "already served" by label alone over-reports wide coverage in the one log line
# this job emits about it (the Lane-3 job review's measured case: a 3-row frame reading 3/3 served
# when the wide table serves none). Imported, never re-typed.
_ALIAS_SLUGS_BY_ATTR: dict[str, frozenset[str]] = {
    _SUGAR_CONSUMPTION_ATTR: _SUGAR_SLUGS,
    _COTTON_CONSUMPTION_ATTR: _COTTON_SLUGS,
    _FRESH_CONSUMPTION_ATTR: _FRESH_SLUGS,
}


# ---------------------------------------------------------------------------
# Fail-closed grain guard
# ---------------------------------------------------------------------------

def _assert_grain_unique(df: pd.DataFrame) -> int:
    """Abort if the long table's declared grain is not unique. Returns the dupe count (always 0).

    The transform enforces this on the way out, so a duplicate arriving here means that dedup was
    bypassed or has regressed. The assertion is repeated at the WRITE because that is where it
    binds the published object: a latest-vintage ROW_NUMBER over a non-unique grain picks an
    arbitrary row, silently and for as long as the table lives (the silver_wasde 2026-07-05
    cross-region collapse, which is also why ``wasde_release_month`` is part of this grain).
    """
    if df.empty:
        return 0
    n = int(df.duplicated(subset=_GRAIN_COLS).sum())
    if n:
        sample = (
            df.loc[df.duplicated(subset=_GRAIN_COLS, keep=False), _GRAIN_COLS]
            .drop_duplicates()
            .head(5)
            .to_dict("records")
        )
        raise ValueError(
            "PSD attributes silver guard: %d row(s) duplicate the declared grain %s "
            "(transform dedup bypassed or regressed). Examples: %s"
            % (n, _GRAIN_COLS, sample)
        )
    return n


# ---------------------------------------------------------------------------
# Coverage accounting
# ---------------------------------------------------------------------------

def _attribute_split(df: pd.DataFrame) -> tuple[int, int, int, int]:
    """Split the emitted attributes into the ones silver_psd already serves and the rest.

    Returns ``(declared_labels, total_labels, declared_rows, total_rows)``. "Declared" means
    declared by the WIDE table (:data:`_WIDE_SERVED_ATTRS`); the remainder is the coverage this
    table exists to add, and it is the one number that says whether the long producer is doing
    its job on a given release. Reported as counts in both units -- labels AND rows -- because
    the two move independently: the unserved labels are many and thin, the served ones few and
    fat.
    """
    if df.empty:
        return 0, 0, 0, 0
    labels = set(df["attribute"].dropna().unique())
    # Row-level membership first: an alias row counts as wide-served ONLY on the slug the wide
    # producer's remap actually folds (label-alone membership over-reports; see _ALIAS_SLUGS_BY_ATTR).
    served_mask = df["attribute"].isin(_TARGET_ATTRS)
    for attr, slugs in _ALIAS_SLUGS_BY_ATTR.items():
        served_mask |= (df["attribute"] == attr) & df["leviathan_slug"].isin(slugs)
    declared_rows = int(served_mask.sum())
    declared = set(df.loc[served_mask, "attribute"].dropna().unique())
    return len(declared), len(labels), declared_rows, len(df)


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------

def _publish_psd_attributes(
    df: pd.DataFrame,
    contract: dict,
    auth,
    s3_client,
    bucket: str,
    *,
    force_overwrite: bool,
) -> ManifestState | None:
    """Publish the flat long PSD attributes object through the shadow-first publisher. Returns the
    manifest state, or ``None`` when an existing canonical object is skipped (canonical mode only).

    The skip is gated on ``auth.may_mutate_canonical``, so a shadow run never declines to stage
    just because the canonical object exists -- shadow's whole job is to build the candidate that
    the canonical object will later be compared against.
    """
    canonical_key = silver_psd_attributes_key()
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
        "PSD attributes silver publish mode=%s state=%s rows=%d key=%s",
        auth.mode.value, manifest.state.value, len(df), canonical_key,
    )
    return manifest.state


def _build_arg_parser() -> argparse.ArgumentParser:
    """The task's CLI.

    Split out of ``main()`` so the DEFAULTS are directly assertable: ``--force-overwrite``
    defaulting to False is a silent no-op against an existing canonical table (see the module
    docstring), and a default that costs a run is a default that owns a test.
    """
    parser = argparse.ArgumentParser(
        description="USDA PSD bronze -> silver long attributes table (shadow-first)"
    )
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", action="store_true",
                        help="Re-publish over an EXISTING canonical object. Without it a "
                             "canonical run against an existing table skips and exits 0.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Alias for --publish-mode dry-run (writes nothing).")
    parser.add_argument("--publish-mode", default="dry-run",
                        choices=["dry-run", "shadow", "canonical"], dest="publish_mode",
                        help="dry-run|shadow|canonical (default dry-run; canonical needs a signed approval)")
    parser.add_argument("--on-uncovered", default="drop", choices=["drop", "raise"],
                        dest="on_uncovered",
                        help="R4 policy for a (multi-slug code, attribute) pair the fan-out "
                             "registry does not cover: drop (default; named, counted, logged) "
                             "or raise (stop the run)")
    parser.add_argument("--role-arn", default="", dest="role_arn")
    parser.add_argument("--account-id", default="", dest="account_id")
    return parser


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    load_env()

    args = _build_arg_parser().parse_args()

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

    logger.info("Running PSD attributes silver transform on %d bronze DataFrames", len(dfs))
    try:
        silver_df = transform_psd_attributes_bronze_to_silver(dfs, on_uncovered=args.on_uncovered)
    except Exception as exc:  # noqa: BLE001
        logger.error("PSD attributes silver transform failed: %s", exc)
        sys.exit(1)

    logger.info(
        "Silver attributes DataFrame: rows=%d cols=%d slugs=%d releases=%d attributes=%d",
        len(silver_df), len(silver_df.columns),
        silver_df["leviathan_slug"].nunique(), silver_df["release_date"].nunique(),
        silver_df["attribute"].nunique(),
    )

    # Fail-closed guard: the declared grain must be unique in the object that gets published.
    try:
        n_grain_dupes = _assert_grain_unique(silver_df)
    except ValueError as exc:
        logger.error("%s", exc)
        sys.exit(1)
    logger.info("PSD attributes grain OK: %d duplicate rows on %s", n_grain_dupes, _GRAIN_COLS)

    n_declared, n_total, declared_rows, total_rows = _attribute_split(silver_df)
    logger.info(
        "PSD attributes coverage: %d of %d attribute labels are already served by the wide "
        "silver_psd table (%d of %d rows); the other %d labels are served ONLY here",
        n_declared, n_total, declared_rows, total_rows, n_total - n_declared,
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
        logger.info("dry-run -- would publish %s rows=%d",
                    silver_psd_attributes_key(), len(silver_df))

    _publish_psd_attributes(silver_df, contract, auth, publish_client, bucket,
                            force_overwrite=args.force_overwrite)


if __name__ == "__main__":
    main()
