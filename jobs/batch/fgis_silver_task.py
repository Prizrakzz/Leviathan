"""AWS Batch task: USDA FGIS Export Inspections bronze -> silver (shadow-first, SILVER-F015/INV-6).

Reads per-CY bronze Parquets from S3, aggregates per-shipment rows into weekly
volumes with cumulative season-to-date (CTD), and publishes partitions under
``silver/fgis/``.

Marketing year / calendar year boundary
-----------------------------------------
A single marketing year spans **two** calendar year (CY) bronze files:

    corn / soybeans  (Sep-start):  MY2024 = CY2024 (Sep-Dec) + CY2025 (Jan-Aug)
    wheat classes    (Jun-start):  MY2024 = CY2024 (Jun-Dec) + CY2025 (Jan-May)

For a requested set of marketing years Y, this task loads bronze CY files for
years Y and Y+1 (i.e. the union of all CYs needed). The transform then filters by
``marketing_year`` column -- which was already computed during bronze creation.

Publish contract (A-W4 CLASS-B retrofit)
----------------------------------------
``silver_fgis`` is a PARTITIONED (projected) table -- one object per
``(leviathan_slug, marketing_year)``. The flat-table ``build_flat_publish`` path
does NOT fit (per-partition fan-out + the parquet body carries the ``leviathan_slug``
and ``marketing_year`` partition columns), so the write routes through the
SILVER-F015 shadow-first publisher (:class:`leviathan.silver.publisher.ShadowPublisher`,
PROJECTED strategy) directly -- the quandl-CHRIS pattern -- with the task's own parquet
writer. ``--publish-mode`` (default ``dry-run``) resolves through the publish guard:

  * dry-run   : nothing is written anywhere.
  * shadow    : each partition object is staged ONLY under ``silver/fgis/_shadow/``;
                canonical partitions are untouched.
  * canonical : shadow-stage -> validate -> promote, ONLY with a verified signed approval.

This replaces the former latest-only ``put_object`` overwrite so a red rebuild
gate can protect the canonical writes (INV-3: projected tables are never
partition-registered in Glue; PROJECTED cataloging is a no-op). The legacy
``--dry-run`` flag is retained as an alias for ``--publish-mode dry-run``.

Usage
-----
    python jobs/batch/fgis_silver_task.py --dry-run
    python jobs/batch/fgis_silver_task.py --marketing-years 2024 --slugs corn_cbot,soybeans_cbot \\
        --publish-mode shadow
    python jobs/batch/fgis_silver_task.py --publish-mode canonical --force-overwrite true
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.silver.flat_producer import authorize_for_contract, encode_partitioned_body
from leviathan.silver.publisher import (
    ManifestState,
    PublishStrategy,
    ShadowPublisher,
    StagedObject,
    ValidationHooks,
)
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import bronze_fgis_key, parse_hive_key, silver_fgis_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.bronze_to_silver.usda_fgis import (
    OUTPUT_COLUMNS,
    transform_fgis_bronze_to_silver,
)

logger = get_logger("fgis_silver_task")

_BRONZE_PREFIX = "bronze/production/source=usda_fgis_export_inspections/"
_FGIS_MIN_CY = 1983
_TABLE = "silver_fgis"
_JOB = "fgis_silver"


# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------

def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="USDA FGIS bronze -> silver (shadow-first)")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument(
        "--force-overwrite",
        default="false",
        help="Re-write silver partitions even if they already exist.",
    )
    parser.add_argument(
        "--workers",
        type=_positive_int,
        default=8,
        help="Concurrent S3 load workers (default: 8).",
    )
    parser.add_argument(
        "--marketing-years",
        default="all",
        dest="marketing_years",
        help="Comma-separated marketing years or 'all' (default: all).",
    )
    parser.add_argument(
        "--slugs",
        default="all",
        help="Comma-separated leviathan slugs or 'all' (default: all).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Alias for --publish-mode dry-run (writes nothing).",
    )
    parser.add_argument("--publish-mode", default="dry-run",
                        choices=["dry-run", "shadow", "canonical"], dest="publish_mode",
                        help="dry-run|shadow|canonical (default dry-run; canonical needs a signed approval)")
    parser.add_argument("--role-arn", default="", dest="role_arn")
    parser.add_argument("--account-id", default="", dest="account_id")
    args = parser.parse_args()
    args.force_overwrite = _parse_bool(args.force_overwrite)
    return args


# ---------------------------------------------------------------------------
# CY selection
# ---------------------------------------------------------------------------

def _cy_years_for_marketing_years(
    marketing_years: list[int],
) -> list[int]:
    """Return the sorted list of calendar years needed to cover *marketing_years*.

    For every requested marketing year Y, we need CY Y (data starts mid-year)
    and CY Y+1 (data continues into the next calendar year).
    """
    cy_set: set[int] = set()
    for my in marketing_years:
        cy_set.add(my)
        cy_set.add(my + 1)
    return sorted(cy_set)


def _available_cy_years(bucket: str, aws_region: str) -> list[int]:
    """List all CY years for which a bronze Parquet exists in S3."""
    keys = list_s3_keys(bucket, _BRONZE_PREFIX, suffix=".parquet", aws_region=aws_region)
    years: list[int] = []
    for key in keys:
        year_str = parse_hive_key(key, "year")
        if year_str.isdigit():
            years.append(int(year_str))
    return sorted(set(years))


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def _load_cy_bronze(bucket: str, year: int, aws_region: str) -> pd.DataFrame:
    """Download and deserialise one CY bronze Parquet."""
    s3 = get_thread_local_s3_client(aws_region)
    key = bronze_fgis_key(year)
    raw_bytes = s3_download_with_retry(bucket, key, s3)
    df = pd.read_parquet(io.BytesIO(raw_bytes))
    logger.info("loaded bronze CY=%d key=%s rows=%d", year, key, len(df))
    return df


def _load_bronze_union(
    bucket: str,
    cy_years: list[int],
    aws_region: str,
    workers: int,
) -> pd.DataFrame:
    """Load and concatenate multiple CY bronze Parquets in parallel."""
    frames: list[pd.DataFrame] = []
    errors = 0

    with ThreadPoolExecutor(max_workers=min(workers, len(cy_years))) as executor:
        future_to_year = {
            executor.submit(_load_cy_bronze, bucket, cy, aws_region): cy
            for cy in cy_years
        }
        for future in as_completed(future_to_year):
            cy = future_to_year[future]
            try:
                frames.append(future.result())
            except Exception as exc:  # noqa: BLE001
                logger.error("failed to load CY=%d: %s", cy, exc)
                errors += 1

    if errors:
        raise RuntimeError(f"{errors} CY bronze file(s) failed to load -- aborting.")

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Shadow-first publish (A-W4 CLASS-B retrofit)
# ---------------------------------------------------------------------------

def _exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001
        return False


def _caller_identity(aws_region: str) -> tuple[str, str]:
    """Best-effort STS identity for the canonical publish target (empty on failure).

    Thin wrapper over the shared resolver ``leviathan.common.aws_identity.resolve_caller_identity``
    (the one idiom the batch-task family shares). Kept as a module-level seam so tests can
    monkeypatch it and readiness/unit runs stay AWS-free; an empty identity still makes the publish
    guard fail closed on the canonical path exactly as before."""
    from leviathan.common.aws_identity import resolve_caller_identity

    return resolve_caller_identity(aws_region)


def _partition_body(df: pd.DataFrame, contract: dict) -> bytes:
    """Encode one (leviathan_slug, marketing_year) partition under the contract-PINNED arrow schema.

    THE SIBLING SWEEP (NASS GATE RCA 2026-09-09, A2 extended). This was the same bare
    ``df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")`` that let arrow infer
    ``silver_nass_annual``'s absent measure columns as arrow ``null`` -- physical INT32 with NO
    Statistics struct -- and refused that chain three consecutive Tuesdays.

    MEASURED BEFORE THE PIN, on all 223 canonical footers (2026-09-09, 113,217 rows): ZERO
    null-typed column instances; both value columns are DOUBLE with statistics in every file, and
    the census passes. The pin changes NO census kind today -- it converts a convention into a
    contract. ``usda_fgis.py`` casts ``exports_mt_weekly`` / ``exports_mt_ctd`` with an explicit
    ``.astype("float64")``, which is what has kept the arrow-null path shut here; nothing asserted
    it, and nothing would have caught its removal.

    BOTH partition keys ride in the body here (``leviathan_slug`` string, ``marketing_year`` int),
    not just one -- which is exactly why the flat ``encode_parquet`` cannot be used verbatim and why
    the shared adapter takes the keys from ``partition_keys`` rather than a hand-written list.

    THE PHYSICAL MOVES THIS TABLE'S REWRITE WILL MAKE, measured by re-encoding all 223 real objects
    through this function (223/223, zero raises, zero value differences): ``week_of_marketing_year``
    INT32 -> INT64 and ``marketing_year`` INT32 -> INT64. Only the FIRST of the two is a catalog
    column -- Glue declares it ``int`` and the registry's own ``drift_summary`` already records it
    as a SILVER-F062 ``widen_int`` -- so the canonical rewrite MUST be preceded by the F011 DDL diff
    and the catalog ALTER: writing INT64 under an ``int`` column is an Athena read error, not a
    silent widen. ``marketing_year`` is a PROJECTED partition key (glue_nonpartition_cols 6 vs
    physical_parquet_cols 8), so Athena takes its value from the object path and never reads the
    body copy; its widen is invisible to the catalog.

    THE REWRITE IS NOT OWNER-GATED, AND THIS TABLE IS ONE OF THE TWO WHERE THAT MATTERS -- corrected
    2026-09-09 after a review finding (MAJOR); an earlier draft of this note ended "nothing changes
    until that owner-gated ``--force-overwrite`` rewrite runs", AND THAT IS FALSE. Measured in
    ``infra/terraform/envs/dev/dag_schedules.auto.tfvars.json``: the ENABLED ``fgis`` schedule,
    ``cron(0 12 ? * THU *)``, carries ``promote`` with ``"mode": "autonomous"`` and the command
    ``fgis_silver_task.py --force-overwrite true --publish-mode canonical`` on
    ``leviathan-dev-fgis-silver`` under the KMS publisher env. ``modules/step_functions/main.tf``
    enters Promote as a plain Map over ``$.promote.tasks`` on any GREEN gate, no human in the loop,
    and ``jobs/audit/silver_rebuild_gate`` is a value/footer census -- nothing on that path can see
    a parquet-vs-Glue type mismatch. So the FIRST GREEN THURSDAY after this code reaches the worker
    image (repin = the trigger; next fire 2026-09-10 12:00Z) rewrites all 223 canonical objects with
    ``week_of_marketing_year`` as INT64 under a Glue ``int`` column, which is an Athena read error on
    every one of them. SEQUENCING, therefore, and it is an ORDER, not a suggestion: either land the
    catalog ALTER (``ALTER TABLE leviathan_dev.silver_fgis CHANGE COLUMN week_of_marketing_year
    week_of_marketing_year bigint``, after the F011 DDL diff) BEFORE the image repin, or disable this
    schedule until it lands. ``tests/unit/silver/test_pinned_writer_catalog_debt.py`` is the pin that
    keeps this debt named."""
    return encode_partitioned_body(df, contract)


def _publish_fgis(
    silver: pd.DataFrame,
    contract: dict,
    auth,
    s3_client,
    bucket: str,
    *,
    slug_filter: set[str] | None,
    my_filter: set[int] | None,
    force_overwrite: bool,
) -> ManifestState | None:
    """Publish one silver object per (leviathan_slug, marketing_year) through the shadow-first
    publisher (PROJECTED), applying the slug/MY filters. Returns the manifest state, or ``None``
    when no partitions remain after filtering / skipping existing canonical objects."""
    staged: list[StagedObject] = []
    skipped = 0
    for (slug, marketing_year), group in silver.groupby(["leviathan_slug", "marketing_year"]):
        slug = str(slug)
        marketing_year = int(marketing_year)
        if slug_filter is not None and slug not in slug_filter:
            continue
        if my_filter is not None and marketing_year not in my_filter:
            continue
        canonical_key = silver_fgis_key(slug, marketing_year)
        if (
            not force_overwrite
            and auth.may_mutate_canonical
            and s3_client is not None
            and _exists(s3_client, bucket, canonical_key)
        ):
            logger.info("skipping existing silver partition: %s", canonical_key)
            skipped += 1
            continue
        staged.append(StagedObject(
            canonical_key=canonical_key,
            body=_partition_body(group[OUTPUT_COLUMNS].reset_index(drop=True), contract),
            partition_values=[slug, str(marketing_year)],
            row_count=len(group),
        ))

    if not staged:
        logger.warning("fgis: no partitions to publish after filtering (skipped=%d existing)", skipped)
        return None

    manifest_store = None if s3_client is not None else (lambda _k, _b: None)
    publisher = ShadowPublisher(
        job=_JOB,
        table=contract["table_name"],
        database=contract["glue_database"],
        bucket=bucket,
        canonical_root=contract["s3_root"],
        auth=auth,
        s3_client=s3_client,
        strategy=PublishStrategy.PROJECTED,
        validation=ValidationHooks(min_rows=1),
        manifest_store=manifest_store,
    )
    manifest = publisher.run(staged)
    logger.info(
        "fgis silver publish mode=%s state=%s partitions=%d skipped=%d",
        auth.mode.value, manifest.state.value, len(staged), skipped,
    )
    return manifest.state


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    load_env()
    args = _parse_args()

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

    s3_read = get_thread_local_s3_client(aws_region)
    publish_client = None if publish_mode == "dry-run" else s3_read

    # --- Resolve filters ---
    slug_filter: set[str] | None = None
    if args.slugs.strip().lower() != "all":
        slug_filter = {s.strip() for s in args.slugs.split(",") if s.strip()}

    # --- Determine marketing years ---
    available_cys = _available_cy_years(bucket, aws_region)
    if not available_cys:
        raise FileNotFoundError(
            f"No FGIS bronze Parquets found under {_BRONZE_PREFIX}"
        )

    # Infer available marketing years from available CYs.
    # A CY provides data for MY(CY-1) (Jan-Aug tail) and MY(CY) (Sep-Dec head).
    all_possible_mys: set[int] = set()
    for cy in available_cys:
        all_possible_mys.add(cy - 1)  # tail end
        all_possible_mys.add(cy)      # head

    if args.marketing_years.strip().lower() == "all":
        requested_mys = sorted(all_possible_mys)
    else:
        requested_mys = sorted(
            int(y.strip())
            for y in args.marketing_years.split(",")
            if y.strip()
        )

    my_filter: set[int] | None = set(requested_mys)

    # --- Determine which CY files to load ---
    needed_cys = [
        cy for cy in _cy_years_for_marketing_years(requested_mys)
        if cy in set(available_cys)
    ]

    if not needed_cys:
        raise FileNotFoundError(
            f"None of the required CY files are available for "
            f"marketing years {requested_mys}"
        )

    logger.info(
        "FGIS silver task bucket=%s marketing_years=%s cys=%s slugs=%s force=%s mode=%s workers=%d",
        bucket, requested_mys, needed_cys, args.slugs, args.force_overwrite, publish_mode, args.workers,
    )

    start = datetime.now(timezone.utc)

    # --- Load bronze ---
    bronze = _load_bronze_union(bucket, needed_cys, aws_region, args.workers)
    if bronze.empty:
        logger.warning("No bronze rows loaded -- nothing to transform.")
        return

    logger.info("Loaded %d bronze rows from %d CY files", len(bronze), len(needed_cys))

    # --- Transform ---
    silver = transform_fgis_bronze_to_silver(bronze)
    if silver.empty:
        logger.warning("Transform produced empty silver DataFrame -- nothing to write.")
        return

    # --- Publish partitions (shadow-first) ---
    _publish_fgis(
        silver, contract, auth, publish_client, bucket,
        slug_filter=slug_filter, my_filter=my_filter, force_overwrite=args.force_overwrite,
    )

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info("Done FGIS silver rows=%d elapsed=%.1fs", len(silver), elapsed)


if __name__ == "__main__":
    main()
