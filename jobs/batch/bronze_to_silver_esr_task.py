"""AWS Batch Fargate task: bronze -> silver (registered/compact) for USDA ESR data.

Reads bronze ESR parquet under ``bronze/production/source=usda_esr/`` and writes the
``silver_esr_compact`` serving table under ``silver/esr/`` THROUGH the F015 shadow publisher
(shadow-first, atomic) + the F013 registered-partition publisher (exact / repairable). This is the
SILVER-F031 (option-b vintage path) + SILVER-F032 (registered-partition publication fail-safe)
producer.

Vintage mode (SILVER-F031)
--------------------------
``--vintage-mode latest`` (DEFAULT -- today's behaviour): keep the file with the latest ``as_of=``
per (commodity_code, market_year), merge to ONE file per commodity slug at
``silver/esr/commodity={slug}/part-000.parquet``; the compact table stays partitioned by
``commodity`` only. ``vintage_retention=latest-only``.

``--vintage-mode all`` (option-b, execution gated to BF-W2): retain EVERY ``as_of`` vintage. The
``_latest_snapshot_keys`` collapse is bypassed; the compact layout gains an ``as_of_date``
REGISTERED partition dimension -- one object per (commodity slug, as_of) at
``silver/esr/commodity={slug}/as_of={date}/part-000.parquet`` (NEVER re-projection, INV-3). This is
the per-week vintage surface that unblocks the pace/forward-commitment features (FR-002).

Publication safety (SILVER-F032 + the R0/F004 kill switch)
----------------------------------------------------------
``--publish-mode`` defaults to ``dry-run`` (plan only; nothing written, catalog untouched).
``shadow`` writes validated objects to a non-canonical shadow prefix. ``canonical`` is refused
without a signed post-R4 approval (publish_guard). The registered strategy delegates to the F013
PartitionPublisher: a new partition is validated-then-registered; an existing partition at a WRONG
location is never silently accepted; a registration failure fails the run (no false success marker),
and an identical rerun is an idempotent no-op. Bronze->silver ordering is asserted before any write
so the ``esr_weekly_ingest`` sibling-task race cannot silver-write ahead of bronze.

Memory envelope (SILVER-F030 BF-W2 widen, measured 2026-09-04)
--------------------------------------------------------------
``--vintage-mode all`` holds every per-file frame AND the ``pd.concat`` copy, then a parquet body
per staged object. This jobdef OOM-killed at 4 GB on the 2026-09-03 fire and was bumped to
12,288 MiB (``leviathan-dev-esr-bronze-to-silver`` rev 8, ``leviathan-dev-silver-publisher-runner``
rev 36 -- BOTH 2 vCPU / 12,288 MiB, verified live). Adding the five float64 columns makes the frame
13 -> 18 columns and **306.35 -> 346.35 bytes/row deep (+40.00 B/row, +13.1%)**, measured on 80
real bronze objects through both the HEAD and the widened transform. Over the whole bronze layer
(143,332,722 parquet bytes at 0.09711 rows/byte, ~13.92M rows) that is one copy 3.97 -> 4.49 GiB
and a two-copy concat peak 7.94 -> 8.98 GiB against a 12.0 GiB envelope: 66.2% -> 74.8%. It fits at
12,288 MiB and OOMs immediately at 4,096, so ANY re-registration of these two jobdefs must PRESERVE
the envelope -- copy the live revision with ``scripts/ops/repin_jobdef_digest.py``, never rebuild a
descriptor from constants (``jobs/submit/submit_batch_b2s_esr.py`` hardcodes ``MEMORY: "4096"``).
Read the shadow run's peak before the canonical promote; the shadow does the identical concat.

Reading ``partition_actions``
-----------------------------
The terminal line reports the OUTCOME SET, not a count against a denominator, and
``PartitionPublisher`` only walks the partitions THIS RUN STAGES (specs are built from ``objects``,
which come from bronze). A registered partition with no surviving bronze source is never repaired
and keeps its old StorageDescriptor, so after a widening ALTER Athena will not expose the new
columns there. Compare repaired+created against ``aws glue get-partitions --database-name
leviathan_dev --table-name silver_esr_compact --query 'length(Partitions)'``; any shortfall is an
orphan partition to reconcile deliberately, named one by one.

Usage (all gated):
    python jobs/batch/bronze_to_silver_esr_task.py                      # dry-run, latest
    python jobs/batch/bronze_to_silver_esr_task.py --vintage-mode all   # dry-run, per-week plan
    python jobs/batch/bronze_to_silver_esr_task.py --publish-mode shadow --shadow-prefix silver/_shadow/esr
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import pyarrow.parquet as pq

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.common.publish_guard import PublishTarget, authorize_publish
from leviathan.silver.publisher import (
    ManifestState,
    PublishStrategy,
    ShadowPublisher,
    StagedObject,
    ValidationHooks,
)
from leviathan.storage.paths import parse_hive_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.bronze_to_silver.usda_esr import transform_esr_bronze_to_silver

logger = get_logger("bronze_to_silver_esr")

_BRONZE_PREFIX = "bronze/production/source=usda_esr/"
_SILVER_ESR_PREFIX = "silver/esr"
_DATABASE = "leviathan_dev"
_TABLE = "silver_esr_compact"
_WORKERS = 32

VINTAGE_LATEST = "latest"
VINTAGE_ALL = "all"

# Non-deprecated ESR measures reported into the run manifest as V001-style null metrics (observability;
# the real per-commodity floor is the SILVER-V001 census). changes_1000mt is DEPRECATED (SILVER-F030)
# and intentionally excluded from the producer's reported floor.
#
# The five BF-W2 net-commitment columns (2026-09-04) ARE listed -- this tuple is the ONLY per-
# (commodity, as_of) instrument that proves the promotion landed. _null_metrics reports
# notna().mean() per column per staged object and the publisher records it as
# row_key_null_metrics[<canonical key>] in the run manifest, so a shadow run answers "which slugs
# and which vintages actually carry the new fields" without a single Athena query.
#
# HOW TO READ IT, restated 2026-09-04 after the raw census (C-M3). The earlier reading -- "as_of >=
# 20260813 is non-zero and every earlier vintage is 0.0" -- could not fail: the 0.0 was guaranteed
# by the re-bronze SCOPE, not by the source. MEASURED over all 446 dated raw objects, every one of
# the 12 as_of vintages (20260712..20260904) carries all five keys, so there is no pre-publication
# vintage at all. The honest reading is therefore: every (commodity, as_of) object whose BRONZE was
# re-written reads NON-ZERO on all five, and a 0.0 is a PIPELINE finding (a bronze object the
# re-bronze did not reach -- e.g. one of the 8,474 backfill-derived bronze objects stamped with a
# run date before the vintage law landed), NEVER a statement about the source. Write any exception
# down PER COMMODITY; frequency floors deny the tail. Being in this tuple does NOT govern the five:
# ValidationHooks(min_nonnull_frac=0.0) below means an all-null new column can never block the
# publish, so the measurement cannot fail closed on itself.
_ESR_MEASURE_COLS = (
    "weekly_exports_1000mt",
    "outstanding_sales_1000mt",
    "gross_new_sales_1000mt",
    "accumulated_exports_1000mt",
    "current_my_net_sales_1000mt",
    "current_my_total_commitment_1000mt",
    "next_my_outstanding_sales_1000mt",
    "next_my_net_sales_1000mt",
)


class BronzeNotReadyError(RuntimeError):
    """Raised when silver would be written ahead of a complete bronze layer (F032 ordering guard)."""


# ---------------------------------------------------------------------------
# Canonical object keys (compact serving layout).
# ---------------------------------------------------------------------------
def silver_esr_compact_key(commodity_slug: str) -> str:
    """latest-only layout: one file per commodity slug (partition key = commodity)."""
    return f"{_SILVER_ESR_PREFIX}/commodity={commodity_slug}/part-000.parquet"


def silver_esr_compact_vintage_key(commodity_slug: str, as_of_date: str) -> str:
    """option-b per-week layout: one file per (commodity slug, as_of) -- an as_of_date REGISTERED
    partition dimension (never re-projection, INV-3)."""
    return f"{_SILVER_ESR_PREFIX}/commodity={commodity_slug}/as_of={as_of_date}/part-000.parquet"


# ---------------------------------------------------------------------------
# Bronze key selection.
# ---------------------------------------------------------------------------
def _latest_snapshot_keys(all_keys: list[str]) -> list[str]:
    """Keep the file with the latest ``as_of=`` per (commodity_code, market_year) -- latest mode."""
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for key in all_keys:
        code = parse_hive_key(key, "commodity_code")
        year = parse_hive_key(key, "market_year")
        if code and year:
            groups[(code, year)].append(key)
    latest: list[str] = []
    for group_keys in groups.values():
        latest.append(max(group_keys, key=lambda k: parse_hive_key(k, "as_of") or ""))
    return sorted(latest)


def _all_snapshot_keys(all_keys: list[str]) -> list[str]:
    """Retain EVERY as_of vintage (option-b): every parseable bronze key, no max() collapse."""
    return sorted(
        k for k in all_keys
        if parse_hive_key(k, "commodity_code") and parse_hive_key(k, "market_year")
    )


def _select_keys(all_keys: list[str], vintage_mode: str) -> list[str]:
    if vintage_mode == VINTAGE_ALL:
        return _all_snapshot_keys(all_keys)
    return _latest_snapshot_keys(all_keys)


def assert_bronze_ready(all_keys: list[str], keys_to_read: list[str]) -> None:
    """F032 ordering guard: never silver-write ahead of bronze. Raise if bronze is empty or if the
    selected key set is empty (the ``esr_weekly_ingest`` sibling-task race would otherwise let silver
    run before the raw->bronze promotion has landed the week)."""
    if not all_keys:
        raise BronzeNotReadyError(
            f"no bronze ESR objects under {_BRONZE_PREFIX} -- refusing to write silver ahead of "
            f"bronze (F032 ordering guard)."
        )
    if not keys_to_read:
        raise BronzeNotReadyError(
            "bronze exists but no (commodity_code, market_year) partitions parsed from it -- "
            "refusing to publish an empty silver set."
        )


# ---------------------------------------------------------------------------
# Read + transform + stage.
# ---------------------------------------------------------------------------
def _read_and_transform(key: str, bucket: str, aws_region: str) -> pd.DataFrame | None:
    market_year_str = parse_hive_key(key, "market_year")
    if not market_year_str:
        logger.warning("Could not parse market_year from: %s", key)
        return None
    try:
        market_year = int(market_year_str)
    except ValueError:
        logger.warning("Non-integer market_year in: %s", key)
        return None
    try:
        s3 = get_thread_local_s3_client(aws_region)
        data = s3_download_with_retry(bucket, key, s3)
        df = pq.read_table(io.BytesIO(data)).to_pandas()
        return transform_esr_bronze_to_silver(df, market_year)
    except Exception as exc:  # noqa: BLE001 -- per-file failures logged; loop continues
        logger.error("Failed to read/transform %s: %s", key, exc)
        return None


def _to_parquet_bytes(group: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    group.reset_index(drop=True).to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    return buf.getvalue()


def _null_metrics(group: pd.DataFrame) -> dict:
    out: dict[str, float] = {}
    n = len(group)
    if not n:
        return out
    for col in _ESR_MEASURE_COLS:
        if col in group.columns:
            out[col] = float(group[col].notna().mean())
    return out


def build_staged_objects(combined: pd.DataFrame, vintage_mode: str) -> list[StagedObject]:
    """Group the combined silver frame into the staged objects the publisher writes.

    latest -> one object per commodity slug, partition_values=[slug].
    all    -> one object per (commodity slug, as_of), partition_values=[slug, as_of]; the per-week
              vintages are NEVER collapsed to max(as_of)."""
    objects: list[StagedObject] = []
    if vintage_mode == VINTAGE_ALL:
        if "as_of_date" not in combined.columns:
            raise ValueError("option-b (all) mode requires an as_of_date column in the silver frame")
        for (name, as_of), group in combined.groupby(["commodity_name", "as_of_date"], sort=True):
            slug, asof = str(name), str(as_of)
            objects.append(StagedObject(
                canonical_key=silver_esr_compact_vintage_key(slug, asof),
                body=_to_parquet_bytes(group),
                partition_values=[slug, asof],
                row_count=len(group),
                null_metrics=_null_metrics(group),
            ))
    else:
        for name, group in combined.groupby("commodity_name", sort=True):
            slug = str(name)
            objects.append(StagedObject(
                canonical_key=silver_esr_compact_key(slug),
                body=_to_parquet_bytes(group),
                partition_values=[slug],
                row_count=len(group),
                null_metrics=_null_metrics(group),
            ))
    return objects


def publish_esr_compact(
    objects: list[StagedObject],
    *,
    bucket: str,
    s3_client,
    glue_client,
    auth,
    vintage_mode: str,
    shadow_prefix: str | None = None,
    code_sha: str | None = None,
    run_id: str | None = None,
):
    """Publish the compact objects through the F015 shadow publisher + F013 registered-partition
    publisher. Returns the run manifest (persisted; FAILED runs included). No canonical mutation
    unless ``auth.may_mutate_canonical`` -- otherwise every partition action is PLANNED.

    ``reconcile_schema_widen=True`` (2026-09-04, the SILVER-F030 BF-W2 additive widen) is not
    cosmetic: it is what keeps the WHOLE family's promote alive across the Glue ``ADD COLUMNS``.
    PartitionPublisher.publish_one builds every partition's desired StorageDescriptor by copying
    the TABLE SD, so the moment the table widens from 12 to 17 columns EVERY already-registered
    partition diffs; with no RepairAuthorization and this flag False, publish_one calls _fail,
    ShadowPublisher._catalog raises PublisherError, and the canonical run exits 1 -- for the entire
    table, not just the new columns. The self-heal it enables is deliberately narrow:
    catalog.is_schema_widen admits ONLY a pure TRAILING-column append at an identical
    location/format/SerDe (measured: five columns at the tail -> True, the same five inserted at
    position 9 -> False), so F013's wrong-location protection is untouched. This flag must be LIVE
    on the image that runs the promote BEFORE the ALTER is applied; expect partition_actions
    'repaired' on every pre-existing partition on the first post-ALTER promote and 'existing' on
    the second."""
    publisher = ShadowPublisher(
        job="bronze_to_silver_esr",
        table=_TABLE,
        database=_DATABASE,
        bucket=bucket,
        canonical_root=f"s3://{bucket}/{_SILVER_ESR_PREFIX}",
        auth=auth,
        s3_client=s3_client,
        glue_client=glue_client,
        strategy=PublishStrategy.REGISTERED,
        shadow_prefix=shadow_prefix,
        validation=ValidationHooks(min_rows=1, min_nonnull_frac=0.0),
        code_sha=code_sha,
        registry_schema_version=1,
        run_id=run_id or f"{_TABLE}-{vintage_mode}",
        reconcile_schema_widen=True,
    )
    return publisher.run(objects)


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------
def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(description="USDA ESR bronze -> silver (compact, gated)")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--vintage-mode", default=VINTAGE_LATEST,
                        choices=[VINTAGE_LATEST, VINTAGE_ALL],
                        help="latest (default, single as_of per MY) | all (option-b per-week, BF-W2)")
    parser.add_argument("--publish-mode", default="dry-run",
                        help="dry-run (default) | shadow | canonical (signed approval required)")
    parser.add_argument("--shadow-prefix", default=None, dest="shadow_prefix")
    parser.add_argument("--force-overwrite", default="false", dest="force_overwrite",
                        help="retained for compatibility; the publisher's exact/repair semantics "
                             "supersede blind skip-existing")
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    vintage_mode = args.vintage_mode

    # 1. List bronze + select keys for the chosen vintage mode.
    all_keys = list_s3_keys(bucket, _BRONZE_PREFIX, suffix=".parquet", aws_region=aws_region)
    logger.info("Found %d total bronze ESR files", len(all_keys))
    keys_to_read = _select_keys(all_keys, vintage_mode)
    logger.info("vintage-mode=%s -> selected %d bronze files", vintage_mode, len(keys_to_read))

    # 2. F032 ordering guard BEFORE any read/write.
    assert_bronze_ready(all_keys, keys_to_read)

    # 3. Download + transform in parallel.
    frames: list[pd.DataFrame] = []
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {pool.submit(_read_and_transform, k, bucket, aws_region): k for k in keys_to_read}
        for fut in as_completed(futures):
            result = fut.result()
            if result is not None and not result.empty:
                frames.append(result)
    if not frames:
        logger.error("All bronze reads/transforms failed - nothing to write")
        sys.exit(1)

    combined = pd.concat(frames, ignore_index=True)
    logger.info(
        "Silver combined: %d rows across %d market_years / %d as_of vintages",
        len(combined),
        combined["market_year"].nunique() if "market_year" in combined.columns else 0,
        combined["as_of_date"].nunique() if "as_of_date" in combined.columns else 0,
    )

    # 4. Stage + authorize + publish (shadow-first, registered, fail-safe).
    objects = build_staged_objects(combined, vintage_mode)
    logger.info("Staged %d compact object(s) for vintage-mode=%s", len(objects), vintage_mode)

    import boto3
    sts = boto3.client("sts", region_name=aws_region)
    ident = sts.get_caller_identity()
    auth = authorize_publish(
        PublishTarget(account_id=ident["Account"], bucket=bucket, database=_DATABASE,
                      prefix=f"{_SILVER_ESR_PREFIX}/", role_arn=ident["Arn"], table=_TABLE),
        argv=sys.argv,
    )
    glue_client = boto3.client("glue", region_name=aws_region) if auth.may_mutate_canonical else None
    s3_client = get_thread_local_s3_client(aws_region)

    manifest = publish_esr_compact(
        objects, bucket=bucket, s3_client=s3_client, glue_client=glue_client, auth=auth,
        vintage_mode=vintage_mode, shadow_prefix=args.shadow_prefix,
    )
    logger.info(
        "ESR bronze->silver complete. mode=%s vintage=%s state=%s objects=%d partition_actions=%s",
        auth.mode.value, vintage_mode, manifest.state.value, len(objects),
        {a.get("outcome"): 1 for a in manifest.partition_actions} if manifest.partition_actions else {},
    )
    if manifest.state == ManifestState.FAILED:
        logger.error("publish FAILED: %s", manifest.failure_reason)
        sys.exit(1)


if __name__ == "__main__":
    main()
