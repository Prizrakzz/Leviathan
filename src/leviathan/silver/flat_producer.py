"""Flat-silver producer runtime: the INV-2 writer-schema + common-publisher glue (SILVER-F062).

WHY THIS EXISTS
---------------
The Milestone R3 "common producer-restoration standard" (plan L668) demands that EVERY restored
producer (1) pins an EXPLICIT ``pyarrow`` writer schema from the F010 registry contract (INV-2) and
(2) routes its write through the SILVER-F015 shadow-first publisher -- never a bespoke
``df.to_parquet(...) + put_object(...)``. Five orphan producers in this lane (the three
``silver_mpoc_*`` tables + ``silver_sagis_cec`` + ``silver_sagis_weekly_exports``) plus the F062
migration of the already-compliant-but-bespoke ``silver_mpob`` / ``silver_mpob_annual`` writers all
need the same two mechanics. This module is that single, pure, table-agnostic glue so no producer
re-implements it.

It is AWS-free in dry-run: :func:`build_flat_publish` hands back a configured
:class:`~leviathan.silver.publisher.ShadowPublisher` and the caller runs it; in dry-run mode the
publisher stages nothing and needs no live client. ``pa.schema`` construction, the null-fraction
census, and the parquet encode are pure.

INV-2: the arrow schema is derived from the contract's ``physical_columns[].target_arrow_type`` in
declared order -- the widen-migration target, so an all-null measure column still writes ``double``
(never arrow ``null``), closing the s3-lane null-type hazard for every flat producer at once.
"""
from __future__ import annotations

import argparse
import io
from dataclasses import dataclass
from typing import Any, Optional, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from leviathan.common.publish_guard import (
    Authorization,
    PublishMode,
    PublishTarget,
    authorize_publish,
)
from leviathan.silver.publisher import (
    PublishStrategy,
    ShadowPublisher,
    StagedObject,
    ValidationHooks,
)

# ---------------------------------------------------------------------------
# INV-2 target token -> pyarrow type. The vocabulary is exactly leviathan.silver.types' target
# tokens (int64 / float64 / string / bool / date32[day] / timestamp[us]).
# ---------------------------------------------------------------------------
_TOKEN_TO_PA = {
    "int64": pa.int64(),
    "float64": pa.float64(),
    "double": pa.float64(),
    "string": pa.string(),
    "large_string": pa.string(),
    "bool": pa.bool_(),
    "boolean": pa.bool_(),
    "date32[day]": pa.date32(),
    "timestamp[us]": pa.timestamp("us"),
}


def arrow_type_for(token: str) -> pa.DataType:
    """Map an INV-2 ``target_arrow_type`` token to a concrete pyarrow type (fail closed)."""
    t = (token or "").strip().lower()
    if t not in _TOKEN_TO_PA:
        raise ValueError(f"unmapped INV-2 target_arrow_type token: {token!r}")
    return _TOKEN_TO_PA[t]


def pa_schema_from_contract(contract: dict) -> pa.Schema:
    """Build the explicit INV-2 ``pa.schema`` for a flat table from its F010 registry contract.

    Columns are emitted in ``physical_columns`` declaration order with the ``target_arrow_type``
    the widen-migration must write, and each column's ``nullable`` flag. This is the SOLE writer
    schema a flat producer passes to ``pa.Table.from_*`` -- pinning it means an all-null measure
    column can never silently become arrow ``null`` (the crawler/merge hazard)."""
    fields = [
        pa.field(c["name"], arrow_type_for(c["target_arrow_type"]), nullable=bool(c.get("nullable", True)))
        for c in contract.get("physical_columns", [])
    ]
    if not fields:
        raise ValueError(f"{contract.get('table_name')}: contract has no physical_columns")
    return pa.schema(fields)


def _column_order(contract: dict) -> list[str]:
    return [c["name"] for c in contract.get("physical_columns", [])]


def encode_parquet(df, contract: dict) -> bytes:
    """Encode a pandas DataFrame to snappy parquet under the contract's explicit INV-2 schema.

    The DataFrame must carry exactly the contract's physical columns (order-agnostic in; the
    schema pins the order out). Raises if a column is missing or extra -- a producer must emit
    precisely the contracted shape."""
    schema = pa_schema_from_contract(contract)
    want = _column_order(contract)
    have = list(df.columns)
    missing = [c for c in want if c not in have]
    extra = [c for c in have if c not in want]
    if missing or extra:
        raise ValueError(
            f"{contract.get('table_name')}: DataFrame columns do not match contract "
            f"(missing={missing}, extra={extra})"
        )
    table = pa.Table.from_pandas(df[want], schema=schema, preserve_index=False)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    return buf.getvalue()


def null_metrics_for(df, value_columns: Sequence[str]) -> dict[str, float]:
    """Per-value-column non-null fraction (the V001-style floor input for the publisher gate)."""
    n = len(df)
    out: dict[str, float] = {}
    for col in value_columns:
        if col not in df.columns or n == 0:
            out[col] = 0.0
        else:
            out[col] = float(df[col].notna().sum()) / float(n)
    return out


@dataclass(frozen=True)
class FlatSilverPlan:
    """The single canonical object a flat producer publishes + the publisher preconfigured for it."""

    publisher: ShadowPublisher
    staged: StagedObject
    schema: pa.Schema
    row_count: int

    def run(self):
        """Execute the controlled publish and return the run manifest (dry-run: in-memory)."""
        return self.publisher.run([self.staged])


def build_flat_publish(
    *,
    df,
    contract: dict,
    canonical_key: str,
    auth,
    s3_client: Any = None,
    job: str,
    run_id: Optional[str] = None,
    code_sha: Optional[str] = None,
    manifest_store=None,
    min_rows: int = 1,
) -> FlatSilverPlan:
    """Assemble a flat-table shadow-first publish for one silver DataFrame.

    ``contract`` is the F010 registry contract (the schema + value_columns + min_nonnull_frac
    authority). ``auth`` is the :class:`~leviathan.common.publish_guard.Authorization` verdict; in
    dry-run/shadow it never touches canonical. The staged object carries the row count + per-value
    non-null metrics so the publisher's V001-style validation gate runs before any promotion."""
    body = encode_parquet(df, contract)
    value_columns = list(contract.get("value_columns", []))
    metrics = null_metrics_for(df, value_columns) if value_columns else None
    staged = StagedObject(
        canonical_key=canonical_key,
        body=body,
        partition_values=None,          # flat tables carry no Glue partitions (INV-3)
        row_count=len(df),
        null_metrics=metrics,
    )
    floor = contract.get("min_nonnull_frac")
    validation = ValidationHooks(
        min_rows=min_rows,
        min_nonnull_frac=float(floor) if floor is not None else 0.0,
        floor_overrides=contract.get("min_nonnull_frac_overrides") or None,
    )
    # The publisher persists the run manifest on EVERY run (dry-run included). With no S3 client
    # (dry-run), the default S3 manifest store cannot run -> supply a no-op sink; the manifest is
    # still returned in memory as the run's evidence.
    if manifest_store is None and s3_client is None:
        manifest_store = lambda _k, _b: None  # noqa: E731 -- tiny no-op sink for offline dry-run
    bucket = contract["s3_bucket"]
    canonical_root = contract["s3_root"]
    publisher = ShadowPublisher(
        job=job,
        table=contract["table_name"],
        database=contract["glue_database"],
        bucket=bucket,
        canonical_root=canonical_root,
        auth=auth,
        s3_client=s3_client,
        strategy=PublishStrategy.FLAT,
        validation=validation,
        manifest_store=manifest_store,
        code_sha=code_sha,
        registry_schema_version=contract.get("schema_version"),
        run_id=run_id,
    )
    return FlatSilverPlan(publisher=publisher, staged=staged, schema=pa_schema_from_contract(contract),
                          row_count=len(df))


# ---------------------------------------------------------------------------
# The standard producer job protocol (SILVER-F062 producer-restoration standard #6).
# ---------------------------------------------------------------------------
def add_standard_producer_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Attach the common producer CLI surface every restored/adopted producer must expose.

    ``--publish-mode`` defaults to ``dry-run`` (fail-closed with the publish guard). ``shadow`` and
    ``canonical`` require live clients + (canonical) a signed approval, which readiness identities
    can never obtain."""
    parser.add_argument("--environment", default="dev")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--database", default="leviathan_dev")
    parser.add_argument("--run-id", default=None, dest="run_id")
    parser.add_argument("--from", default=None, dest="date_from")
    parser.add_argument("--to", default=None, dest="date_to")
    parser.add_argument("--partitions", default=None)
    parser.add_argument("--shadow-root", default=None, dest="shadow_root")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--publish-mode", default="dry-run",
                        choices=[m.value for m in PublishMode], dest="publish_mode")
    parser.add_argument("--contract-version", default=None, type=int, dest="contract_version")
    return parser


def authorize_for_contract(
    contract: dict,
    *,
    publish_mode: str,
    role_arn: str = "",
    account_id: str = "",
    approval=None,
    env: Optional[dict] = None,
) -> Authorization:
    """Authorize a flat producer's publish for its contract via the publish guard.

    dry-run/shadow return a non-canonical verdict without any environment check; canonical runs the
    full fail-closed environment + approval gate. Readiness identities are denied canonical."""
    mode = PublishMode(publish_mode)
    target = PublishTarget(
        account_id=account_id,
        bucket=contract["s3_bucket"],
        database=contract["glue_database"],
        prefix=contract["s3_prefix"].rstrip("/") + "/",
        role_arn=role_arn,
        table=contract["table_name"],
    )
    return authorize_publish(target, mode=mode, approval=approval, env=env or {})
