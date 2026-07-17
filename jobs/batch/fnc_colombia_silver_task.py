"""AWS Batch task: FNC Colombia bronze Parquet -> silver (shadow-first, SILVER-F015/INV-6).

Reads the FNC Colombia coffee Excel bronze series, builds the three business-facing
silver tables (monthly, area_department, exports_port_type) and publishes each under
its own ``silver/fnc_colombia/<table>/`` prefix.

Publish contract (A-W4 CLASS-B retrofit)
----------------------------------------
Every fnc silver table is PARTITIONED (projected) -- one object per
``(commodity, year)``. The flat-table ``build_flat_publish`` path does NOT fit
(its single-object plan + exact contract-column encode cannot express the
per-partition fan-out, and the parquet body carries the ``year`` partition
column), so each write routes through the SILVER-F015 shadow-first publisher
(:class:`leviathan.silver.publisher.ShadowPublisher`, PROJECTED strategy) directly
-- the same pattern the NASS annual / quandl CHRIS tasks use -- with the task's own
parquet writer (preserving the on-disk byte layout). ``--publish-mode`` (default
``dry-run``) resolves through the publish guard:

  * dry-run   : nothing is written anywhere (the manifest is an in-memory plan).
  * shadow    : each partition object is staged ONLY under
                ``silver/fnc_colombia/<table>/_shadow/``; canonical is untouched.
  * canonical : shadow-stage -> validate -> promote, ONLY with a verified signed
                approval (the guard raises otherwise before any write).

This replaces the former latest-only ``put_object`` overwrite so a red rebuild gate
can protect the canonical writes (a red gate cannot protect data already
overwritten). The projected tables are never partition-registered in Glue (INV-3);
PROJECTED cataloging is a no-op. The legacy ``--dry-run`` flag is retained as an
alias for ``--publish-mode dry-run``.

Usage
-----
    python jobs/batch/fnc_colombia_silver_task.py                         # dry-run (writes nothing)
    python jobs/batch/fnc_colombia_silver_task.py --publish-mode shadow
    python jobs/batch/fnc_colombia_silver_task.py --publish-mode canonical --force-overwrite true
    python jobs/batch/fnc_colombia_silver_task.py --dry-run
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from datetime import datetime, timezone

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.silver.flat_producer import authorize_for_contract
from leviathan.silver.publisher import (
    ManifestState,
    PublishStrategy,
    ShadowPublisher,
    StagedObject,
    ValidationHooks,
)
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import (
    bronze_fnc_key,
    silver_fnc_colombia_area_department_key,
    silver_fnc_colombia_exports_port_type_key,
    silver_fnc_colombia_monthly_key,
)
from leviathan.storage.s3 import get_thread_local_s3_client, s3_download_with_retry
from leviathan.transforms.bronze_to_silver.fnc_colombia import (
    AREA_OUTPUT_COLUMNS,
    EXPORTS_PORT_TYPE_OUTPUT_COLUMNS,
    MONTHLY_OUTPUT_COLUMNS,
    transform_fnc_colombia_bronze_to_silver,
)

logger = get_logger("fnc_colombia_silver_task")

_JOB = "fnc_colombia_silver"

_BRONZE_SERIES = [
    "produccion_mensual",
    "precio_ex_dock_mensual",
    "precio_interno_mensual",
    "area_departamento",
    "exportaciones_total_volumen",
    "exportaciones_total_valor",
    "exportaciones_puerto_tipo",
]

# One controlled-publish descriptor per fnc silver table: (registry table_name, key
# function, output columns). The DataFrame attribute is resolved from the transform
# result in main(). Each is a PROJECTED (commodity, year) table.
_MONTHLY_TABLE = "silver_fnc_colombia_monthly"
_AREA_TABLE = "silver_fnc_colombia_area_department"
_EXPORTS_TABLE = "silver_fnc_colombia_exports_port_type"


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FNC Colombia bronze -> silver (shadow-first)")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", default="false")
    parser.add_argument(
        "--years",
        default="all",
        help="Comma-separated years or 'all'. Useful for smoke tests.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Alias for --publish-mode dry-run (writes nothing).")
    parser.add_argument("--publish-mode", default="dry-run",
                        choices=["dry-run", "shadow", "canonical"], dest="publish_mode",
                        help="dry-run|shadow|canonical (default dry-run; canonical needs a signed approval)")
    parser.add_argument("--role-arn", default="", dest="role_arn")
    parser.add_argument("--account-id", default="", dest="account_id")
    args = parser.parse_args()
    args.force_overwrite = _parse_bool(args.force_overwrite)
    return args


def _selected_years(value: str) -> set[int] | None:
    if value.strip().lower() == "all":
        return None
    return {int(item.strip()) for item in value.split(",") if item.strip()}


def _read_bronze_series(bucket: str, aws_region: str) -> dict[str, pd.DataFrame]:
    s3 = get_thread_local_s3_client(aws_region)
    series: dict[str, pd.DataFrame] = {}
    for series_name in _BRONZE_SERIES:
        key = bronze_fnc_key(series_name)
        raw_bytes = s3_download_with_retry(bucket, key, s3)
        df = pd.read_parquet(io.BytesIO(raw_bytes))
        series[series_name] = df
        logger.info("read FNC bronze series=%s rows=%d key=%s", series_name, len(df), key)
    return series


def _filter_years(df: pd.DataFrame, years: set[int] | None) -> pd.DataFrame:
    if years is None or df.empty:
        return df
    return df.loc[df["year"].isin(years)].copy()


def _validate_uniqueness(monthly: pd.DataFrame, area: pd.DataFrame, exports: pd.DataFrame) -> None:
    checks = [
        ("monthly", monthly, ["leviathan_slug", "year", "month", "date"]),
        ("area_department", area, ["leviathan_slug", "department", "year"]),
        (
            "exports_port_type",
            exports,
            ["leviathan_slug", "year", "month", "port", "coffee_type"],
        ),
    ]
    for label, df, key_cols in checks:
        if df.empty:
            continue
        duplicate_mask = df.duplicated(subset=key_cols, keep=False)
        if duplicate_mask.any():
            preview = df.loc[duplicate_mask, key_cols].drop_duplicates().head(5).to_dict("records")
            raise ValueError(f"FNC Colombia {label} has duplicate output rows: {preview}")


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


def _partition_body(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    return buf.getvalue()


def _publish_projected(
    df: pd.DataFrame,
    output_columns: list[str],
    contract: dict,
    key_fn,
    auth,
    s3_client,
    bucket: str,
    *,
    force_overwrite: bool,
) -> tuple[ManifestState | None, int, int]:
    """Publish one silver object per year through the shadow-first publisher (PROJECTED).

    Each fnc table carries a single ``commodity`` (arabica_coffee), so partitions fan out over
    ``year``. Returns ``(manifest_state, published, skipped)``; ``manifest_state`` is ``None`` when
    the frame is empty or every partition is a skipped existing canonical object (canonical mode
    only). The parquet body carries ``year`` (the partition column), preserving the on-disk layout;
    the projected table is never partition-registered in Glue (INV-3)."""
    if df.empty:
        return None, 0, 0

    staged: list[StagedObject] = []
    skipped = 0
    for year, group in df.groupby("year", sort=True):
        year = int(year)
        canonical_key = key_fn(year)
        if (
            not force_overwrite
            and auth.may_mutate_canonical
            and s3_client is not None
            and _exists(s3_client, bucket, canonical_key)
        ):
            logger.info("skipping existing silver partition: %s", canonical_key)
            skipped += 1
            continue
        commodity = str(group["leviathan_slug"].iloc[0])
        staged.append(StagedObject(
            canonical_key=canonical_key,
            body=_partition_body(group[output_columns].reset_index(drop=True)),
            partition_values=[commodity, str(year)],
            row_count=len(group),
        ))

    if not staged:
        logger.info("fnc_colombia %s: no partitions to publish (skipped=%d existing)",
                    contract["table_name"], skipped)
        return None, 0, skipped

    # dry-run (no client) needs a no-op manifest sink; shadow/canonical persist via the S3 store.
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
        registry_schema_version=contract.get("schema_version"),
    )
    manifest = publisher.run(staged)
    logger.info(
        "fnc_colombia %s publish mode=%s state=%s partitions=%d skipped=%d",
        contract["table_name"], auth.mode.value, manifest.state.value, len(staged), skipped,
    )
    return manifest.state, len(staged), skipped


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
    years = _selected_years(args.years)
    registry = load_registry()

    account_id, role_arn = args.account_id, args.role_arn
    if publish_mode == "canonical" and not account_id and not role_arn:
        account_id, role_arn = _caller_identity(aws_region)

    # A read client is always needed to load bronze; the publisher only writes in shadow/canonical.
    s3_read = get_thread_local_s3_client(aws_region)
    publish_client = None if publish_mode == "dry-run" else s3_read

    start = datetime.now(timezone.utc)
    bronze = _read_bronze_series(bucket, aws_region)
    silver = transform_fnc_colombia_bronze_to_silver(bronze)
    monthly = _filter_years(silver.monthly, years)
    area = _filter_years(silver.area_department, years)
    exports = _filter_years(silver.exports_port_type, years)
    _validate_uniqueness(monthly, area, exports)

    tables = [
        (_MONTHLY_TABLE, silver_fnc_colombia_monthly_key, MONTHLY_OUTPUT_COLUMNS, monthly),
        (_AREA_TABLE, silver_fnc_colombia_area_department_key, AREA_OUTPUT_COLUMNS, area),
        (_EXPORTS_TABLE, silver_fnc_colombia_exports_port_type_key, EXPORTS_PORT_TYPE_OUTPUT_COLUMNS, exports),
    ]

    published = skipped = 0
    rows = 0
    for table_name, key_fn, output_columns, frame in tables:
        contract = registry.table(table_name)
        auth = authorize_for_contract(
            contract, publish_mode=publish_mode,
            role_arn=role_arn, account_id=account_id, env=os.environ,
        )
        logger.info("publish authorized: table=%s mode=%s may_canonical=%s",
                    table_name, auth.mode.value, auth.may_mutate_canonical)
        _state, pub, skip = _publish_projected(
            frame, output_columns, contract, key_fn, auth, publish_client, bucket,
            force_overwrite=args.force_overwrite,
        )
        published += pub
        skipped += skip
        rows += len(frame)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        "Done FNC Colombia silver mode=%s published=%d skipped=%d rows=%d elapsed=%.1fs",
        publish_mode, published, skipped, rows, elapsed,
    )


if __name__ == "__main__":
    main()
