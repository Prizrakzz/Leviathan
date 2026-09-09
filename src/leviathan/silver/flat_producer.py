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
import os
from dataclasses import dataclass
from typing import Any, Optional, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from leviathan.common.aws_identity import resolve_caller_identity
from leviathan.common.publish_guard import (
    Authorization,
    PublishMode,
    PublishTarget,
    authorize_publish,
)
from leviathan.silver.publisher import (
    PublishStrategy,
    RunManifest,
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


# ---------------------------------------------------------------------------
# The PARTITIONED sibling of encode_parquet (NASS GATE RCA 2026-09-09, the four-sibling sweep).
# ---------------------------------------------------------------------------
# Partition-key glue types -> the INV-2 token the BODY carries for that key. A projected key can
# ride in the parquet body as well as in the object path (``year``, ``marketing_year``,
# ``leviathan_slug``), which is exactly why ``encode_parquet`` cannot be used verbatim by a
# per-partition producer: it would refuse the body as ``extra=['year']``. The map is deliberately
# TINY and fail-closed -- an unmapped glue type raises rather than being guessed, because guessing a
# column's type is how the defect this helper exists to close was born.
_PARTITION_KEY_TOKEN = {"int": "int64", "bigint": "int64", "string": "string"}


def pa_schema_for_partitioned_body(contract: dict, columns: Sequence[str]) -> pa.Schema:
    """The explicit INV-2 writer schema for ONE partition body of a partitioned/projected table.

    :func:`pa_schema_from_contract` gives the declared ``physical_columns`` with their
    ``target_arrow_type`` and nullability; this adds the partition keys that ride in the body and
    emits the fields in the BODY's own column order, so the on-disk layout is unchanged. A key that
    lives only in the object path (the usual ``commodity``) is simply absent from ``columns`` and is
    skipped; a key the contract also declares as a physical column keeps its physical declaration.

    FAIL CLOSED both ways, which is the whole point: a contract column missing from the body, a body
    column the contract does not declare, or a partition key whose glue type has no mapping RAISES
    rather than being inferred. Inference per group is precisely the defect -- see
    :func:`encode_partitioned_body`.
    """
    by_name = {f.name: f for f in pa_schema_from_contract(contract)}
    contracted = list(by_name)
    for pk in contract.get("partition_keys") or []:
        name = pk.get("name")
        if name in by_name or name not in columns:
            continue
        token = _PARTITION_KEY_TOKEN.get(str(pk.get("glue_type", "")).lower())
        if token is None:
            raise ValueError(f"{contract.get('table_name')}: unmapped partition-key glue type "
                             f"{pk.get('glue_type')!r} for {name!r}")
        by_name[name] = pa.field(name, arrow_type_for(token), nullable=False)
    missing = [c for c in contracted if c not in columns]
    extra = [c for c in columns if c not in by_name]
    if missing or extra:
        raise ValueError(f"{contract.get('table_name')}: partition body does not match the contract "
                         f"(missing={missing}, extra={extra})")
    return pa.schema([by_name[c] for c in columns])


def encode_partitioned_body(df, contract: dict) -> bytes:
    """Encode ONE partition body to snappy parquet under the contract-PINNED arrow schema.

    THE MEASURED TRIGGER (NASS GATE RCA, 2026-09-09). Five per-partition producers wrote their
    bodies with a bare ``df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")``
    and NO schema argument, so arrow INFERRED the type per group and any group holding zero non-NA
    values in a measure column was written as arrow ``null`` -- physical INT32 with no Statistics
    struct at all. Over the 1,206 canonical ``silver_nass_annual`` objects that produced 475 such
    column-instances, of which the 322 cottonseed yield/planted-area ones made the SILVER-V001
    footer census raise ``KIND_STATS_UNAVAILABLE`` and refuse the usda_nass chain three consecutive
    Tuesdays. ``pa_schema_from_contract``'s own docstring exists to prevent exactly this ("pinning
    it means an all-null measure column can never silently become arrow ``null``"); this function is
    that pin for the partitioned shape, so no producer re-implements it a sixth time.

    WHAT IT DOES AND DOES NOT FIX. It makes the column's TYPE a property of the contract instead of
    the data, so the footer always carries statistics and ``null_count`` is countable. It does NOT
    make an absent source series pass a census: a double all-null column trips ``KIND_ALL_NAN``
    where an arrow-null one tripped ``KIND_STATS_UNAVAILABLE``, and both are hard. Narrating a real
    absence is the registry's ``value_column_absent_groups`` job. And it moves NO non-null fraction:
    ``value_census.file_column_stat`` skips a ``None`` statistics object, so a null-typed file books
    its rows with ``effective_nonnull`` 0 before the pin and an all-null typed file books them with
    ``effective_nonnull`` 0 after it.

    WHEN THE LIVE BYTES OF AN ALREADY-PUBLISHED TABLE CHANGE -- corrected 2026-09-09 after a review
    finding (MAJOR); this docstring previously said "not until an owner-gated canonical rewrite
    runs", which is FALSE for every caller in the estate today. Each of the five producers rides an
    ENABLED schedule whose Step Functions ``promote`` phase is ``"mode": "autonomous"`` and whose
    command is that very ``--force-overwrite ... --publish-mode canonical`` rewrite, taken on any
    GREEN gate with no human in the loop. The trigger is the WORKER IMAGE REPIN. A caller whose pin
    moves a physical type into one the Glue catalog does not declare must therefore land the catalog
    ALTER (or hold its schedule) BEFORE that repin -- see each writer's own block note, and
    ``tests/unit/silver/test_pinned_writer_catalog_debt.py`` for the checked list."""
    schema = pa_schema_for_partitioned_body(contract, list(df.columns))
    table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
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

    def run(self) -> RunManifest:
        """Execute the controlled publish and return the run manifest (dry-run: in-memory)."""
        return self.publisher.run([self.staged])


def build_flat_publish(
    *,
    df,
    contract: dict,
    canonical_key: str,
    auth: Authorization,
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
    # Fail closed at plan-build time: shadow AND canonical STAGE objects to S3 (put_object), so a
    # write-mode publish with no client is a wiring bug -- surface it here as an actionable error
    # rather than a cryptic ``'NoneType' object has no attribute 'put_object'`` deep in the staging
    # loop. Only dry-run legitimately stages nothing and may pass ``s3_client=None``.
    if s3_client is None and auth.mode is not PublishMode.DRY_RUN:
        raise ValueError(
            f"{contract.get('table_name')}: publish-mode '{auth.mode.value}' stages objects to S3 and "
            "requires a live s3_client; only dry-run may pass s3_client=None"
        )
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


def _resolve_caller_identity() -> tuple[str, str]:
    """Best-effort live STS identity for a canonical publish target: ``(account_id, role_arn)``.

    Reuses the in-repo idiom (``boto3.client("sts").get_caller_identity()`` -> ``Account`` / ``Arn``;
    the same shape ``jobs/batch/_sb_producer_publish.publish_flat_silver`` and
    ``noaa_oni_task._caller_identity`` already resolve). ``boto3`` is imported lazily so importing
    this module never pulls it, and a missing-credentials failure falls back to empty strings --
    :func:`~leviathan.common.publish_guard.check_environment` then fails closed exactly as before.

    This is a module-level seam ON PURPOSE: it is called ONLY on the canonical path (never in
    dry-run/shadow), and tests monkeypatch it so unit runs + readiness identities stay AWS-free.

    Thin adapter over the shared best-effort resolver
    :func:`leviathan.common.aws_identity.resolve_caller_identity` (the same idiom the batch tasks
    now share); the wrapper is retained so the monkeypatch seam and AWS-free unit runs are unchanged."""
    return resolve_caller_identity()


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
    full fail-closed environment + approval gate. Readiness identities are denied canonical.

    On the canonical path the guard's :func:`check_environment` fails closed on an empty
    ``account_id`` / ``role_arn`` (dry-run/shadow never reach it, which is why only the PROMOTE step
    of pink_sheet / mpob / mpob_annual failed). Resolve the LIVE STS identity for the WHOLE flat
    producer family in this ONE place -- callers need not each plumb it -- but ONLY when the caller
    supplied neither (explicit args always win) and ONLY for canonical, so dry-run/shadow and every
    readiness identity stay fully offline and byte-identical to before."""
    mode = PublishMode(publish_mode)
    if mode is PublishMode.CANONICAL and not account_id and not role_arn:
        account_id, role_arn = _resolve_caller_identity()
    target = PublishTarget(
        account_id=account_id,
        bucket=contract["s3_bucket"],
        database=contract["glue_database"],
        prefix=contract["s3_prefix"].rstrip("/") + "/",
        role_arn=role_arn,
        table=contract["table_name"],
    )
    # The canonical branch of authorize_publish reads LEVIATHAN_APPROVAL_MODE (+ the KMS key/registry
    # binding) from ``env`` to R1-self-mint the signed approval via kms:Sign. When the caller does not
    # supply env we must hand it the LIVE process env on the canonical path, else the guard sees an
    # empty mapping, cannot see kms mode, and fails closed with ApprovalError (the round-3 pink_sheet /
    # mpob / mpob_annual promote failure -- fnc_colombia passed only because it plumbed env=os.environ
    # explicitly). Resolve it ONCE here for the whole flat-producer family. dry-run/shadow never reach
    # the approval gate, so they stay on the empty offline mapping (byte-identical); explicit env wins.
    if env is None:
        env = os.environ if mode is PublishMode.CANONICAL else {}
    return authorize_publish(target, mode=mode, approval=approval, env=env)
