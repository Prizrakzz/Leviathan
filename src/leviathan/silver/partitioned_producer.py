"""Registered-partition producer runtime: the INV-2 writer schema + F013/F015 glue (SILVER-F013).

WHY THIS EXISTS
---------------
:mod:`leviathan.silver.flat_producer` is the "single, pure, table-agnostic glue so no producer
re-implements it" for FLAT tables -- and it is explicitly flat-only
(``StagedObject(partition_values=None)  # flat tables carry no Glue partitions (INV-3)``). There has
never been a partitioned equivalent, so every registered producer in the repo (``silver_esr``,
``silver_wasde``, ``gold_pattern_records``) hand-rolls the same thirty lines: group by partition
value, drop the partition columns, coerce, ``encode_parquet``, build the Hive key, configure a
``ShadowPublisher(strategy=REGISTERED)``. PRICE_AND_PLAYBOOKS W1.0 (D5) closes that gap, because
W1a/W1b/W1c/W2 land roughly TEN producers against ONE table (``silver_futures_eod``) -- ten chances
to get the partition layout subtly wrong, in a way that is silent and unrecoverable once registered.

WHAT THIS MODULE OWNS (and what it deliberately does not)
---------------------------------------------------------
It owns the MECHANICS: object keys, the group/drop/encode cycle, the ordered ``partition_values``,
the validation hooks derived from the F010 contract, and the publisher wiring. It owns NO
table-specific knowledge -- ``silver_futures_eod``'s unit/currency/settle_kind map and its
slug->partition derivation live in :mod:`leviathan.silver.futures_eod_contracts`, not here.

THE FOUR INVARIANTS IT ENFORCES, EACH FOR A CONCRETE REASON
------------------------------------------------------------
1. **Partition columns live in the PATH, never in the parquet body.** ``encode_parquet`` raises on
   an extra column, so this is partly mechanical -- but the deeper reason is
   ``silver_esr_compact``, which carries ``as_of_date`` in BOTH path and body and is exactly why
   ``jobs/utils/load_pg_numbers.py`` had to grow ``_probe_body_columns()`` (a LIST + footer read
   per load) to stop pyarrow's dataset-schema unification dying on string/large_string. Glue
   exposes partition keys to Athena as ordinary columns, so nothing is lost by keeping them out.
2. **``partition_values`` order == the contract's declared ``partition_keys`` order.** Registering
   a partition with transposed values is silent at write time and unrecoverable afterwards (the
   Glue partition is keyed positionally). Checked, fail-closed, at plan-build time.
3. **Directory key == COLUMN name.** ``silver_esr``'s ``esr_partition_location`` exists ONLY because
   that table maps column ``as_of_date`` to directory ``as_of=``; nothing else in the estate does,
   and nothing new should. Do not re-add an analogue -- ``StagedObject.location_prefix()`` derives
   the Glue location from the object key, so a plain ``<col>=<val>`` layout needs no special case.
4. **Every partition VALUE is typed and non-null** (:func:`partition_value_str`). ``str()`` happily
   renders ``nan`` and ``2026.0`` as encodable path segments, so an unguarded render registers
   ``leviathan_slug=nan`` (rows orphaned behind every slug predicate) or ``trade_year=2026.0``
   against an ``int`` Glue key (Athena reads it back NULL). Both are silent at write time and
   unrecoverable afterwards -- the same failure class as invariant 2, one layer down.

NEVER MSCK, NEVER PROJECTION: the publisher's REGISTERED strategy writes an explicit per-partition
Glue location through :class:`~leviathan.silver.partition_publish.PartitionPublisher`, which
write-then-verifies-then-registers and refuses a location mismatch unless a
:class:`~leviathan.silver.partition_publish.RepairAuthorization` names that exact value tuple. The
projected grid is the Jul-2026 S3 LIST-storm class ($134 in two days).

AWS-free in dry-run, exactly like ``flat_producer``: the plan is built and the parquet encoded
in-memory; only shadow/canonical need live clients.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

import pyarrow as pa

from leviathan.common.publish_guard import Authorization, PublishMode
from leviathan.silver.flat_producer import encode_parquet, null_metrics_for, pa_schema_from_contract
from leviathan.silver.partition_publish import RepairAuthorization
from leviathan.silver.publisher import (
    PublishStrategy,
    RunManifest,
    ShadowPublisher,
    StagedObject,
    ValidationHooks,
)

DEFAULT_OBJECT_NAME = "part-000.parquet"

# Glue integer types. A partition key declared int MUST render without a decimal point: pandas
# widens ANY column that has ever held a NaN to float64, so a perfectly ordinary `trade_year` can
# arrive as 2026.0 and `str()` it to the partition `trade_year=2026.0` -- a value Athena reads back
# as NULL against an `int` key, on a path that is silent at write time and unrecoverable once
# registered (module docstring, invariant 2's rationale).
_INT_GLUE_TYPES = frozenset({"int", "integer", "bigint", "smallint", "tinyint"})


def _is_null(val: Any) -> bool:
    """True for None / NaN / NaT / pandas NA -- WITHOUT importing pandas.

    ``flat_producer`` is deliberately duck-typed on the DataFrame (it imports pyarrow only), and
    this module follows it. NaN and NaT are the only values unequal to themselves; ``pandas.NA``
    propagates instead of returning a bool, so an ambiguous comparison is treated as null too."""
    if val is None:
        return True
    try:
        return bool(val != val)
    except (TypeError, ValueError):  # noqa: BLE001 -- pandas.NA truth value is ambiguous
        return True


def partition_value_str(col: str, val: Any, glue_type: Optional[str] = None) -> str:
    """Render ONE partition value as its Hive path segment -- FAIL CLOSED on a bad value.

    This is the guard the module's invariants depend on and the reason it is a function rather than
    a ``str()`` call at the two call sites:

      * **NULL is never a partition.** ``str(float('nan'))`` is the perfectly encodable string
        ``'nan'``, so an unguarded render turns a missing slug into the real, registered partition
        ``leviathan_slug=nan`` -- write-verify-REGISTER accepts it and the row is then invisible to
        every slug predicate. Rejected outright, naming the column.
      * **An ``int`` key renders as an integer.** ``2026.0`` (pandas float widening on any column
        that has ever held a NaN) would register ``trade_year=2026.0`` against an ``int`` Glue key,
        which Athena reads back as NULL. An exactly-integral float is normalized to ``2026``; a
        non-integral value is an error, never a silent truncation.
      * **The segment must be Hive-encodable** -- non-empty, no ``/``, no ``=``.

    ``glue_type`` comes from the F010 contract's ``partition_keys[].glue_type``; ``None`` means
    "unknown type", which still gets the null + encodability checks."""
    if _is_null(val):
        raise ValueError(
            f"partition value for column {col!r} is NULL (None/NaN/NaT) -- a null partition value "
            f"would register the literal partition {col}=nan and silently orphan the rows; drop or "
            f"repair the rows upstream, never partition on a missing value"
        )
    if glue_type is not None and str(glue_type).strip().lower() in _INT_GLUE_TYPES:
        try:
            fval = float(val)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"partition value {val!r} for column {col!r} is not numeric, but the contract "
                f"declares glue_type {glue_type!r}"
            ) from exc
        if not fval.is_integer():
            raise ValueError(
                f"partition value {val!r} for column {col!r} is not an exact integer, but the "
                f"contract declares glue_type {glue_type!r} -- refusing to truncate"
            )
        sval = str(int(fval))
    else:
        sval = str(val)
    if not sval or "/" in sval or "=" in sval:
        raise ValueError(
            f"partition value {val!r} for column {col!r} is empty or contains '/' or '=' -- "
            f"it cannot be encoded as a Hive path segment"
        )
    return sval


def partition_object_key(
    s3_prefix: str,
    partition_cols: Sequence[str],
    values: Sequence[Any],
    *,
    glue_types: Optional[Sequence[Optional[str]]] = None,
    filename: str = DEFAULT_OBJECT_NAME,
) -> str:
    """``<s3_prefix>/<col>=<val>/.../<filename>`` -- the canonical object key for one partition.

    The directory key is the COLUMN name verbatim (see invariant 3 in the module docstring): there
    is no ESR-style ``as_of_date`` -> ``as_of=`` remap here and none should ever be added. The Glue
    partition LOCATION is derived from this key by ``StagedObject.location_prefix()``, so this
    function is the single place the physical layout is decided. Every value goes through
    :func:`partition_value_str`, so a NULL / non-integral-int / unencodable value fails here."""
    if len(partition_cols) != len(values):
        raise ValueError(
            f"partition_cols {list(partition_cols)} and values {list(values)} differ in length"
        )
    types = list(glue_types) if glue_types is not None else [None] * len(values)
    if len(types) != len(values):
        raise ValueError(
            f"glue_types {types} and values {list(values)} differ in length"
        )
    parts = [s3_prefix.strip("/")]
    for col, val, gtype in zip(partition_cols, values, types):
        parts.append(f"{col}={partition_value_str(col, val, gtype)}")
    parts.append(filename)
    return "/".join(parts)


def _contract_partition_cols(contract: dict) -> list[str]:
    return [pk["name"] for pk in contract.get("partition_keys", [])]


def _contract_partition_types(contract: dict) -> dict[str, Optional[str]]:
    return {pk["name"]: pk.get("glue_type") for pk in contract.get("partition_keys", [])}


def build_partition_objects(
    df,
    contract: dict,
    *,
    partition_cols: Optional[Sequence[str]] = None,
    filename: str = DEFAULT_OBJECT_NAME,
) -> list[StagedObject]:
    """One :class:`StagedObject` per partition group, encoded under the contract's INV-2 schema.

    ``df`` must carry the contract's physical columns PLUS the partition columns. The partition
    columns are dropped before the encode (invariant 1) and re-emitted as ordered
    ``partition_values`` (invariant 2). Groups are emitted in sorted value order so a run is
    deterministic.

    Every group's values are rendered ONCE by :func:`partition_value_str` against the contract's
    declared ``glue_type`` and that SAME rendering feeds both the object key and
    ``partition_values`` -- so the S3 path and the Glue partition can never disagree, and a NULL or
    float-widened value fails closed here instead of registering ``leviathan_slug=nan`` /
    ``trade_year=2026.0``."""
    declared = _contract_partition_cols(contract)
    cols = list(partition_cols) if partition_cols is not None else declared
    if not cols:
        raise ValueError(
            f"{contract.get('table_name')}: no partition_keys declared -- a flat table belongs to "
            f"leviathan.silver.flat_producer.build_flat_publish, not here"
        )
    if cols != declared:
        raise ValueError(
            f"{contract.get('table_name')}: partition_cols {cols} != the contract's declared "
            f"partition_keys {declared} (order is load-bearing: Glue keys partitions positionally)"
        )
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(
            f"{contract.get('table_name')}: DataFrame is missing partition column(s) {missing}"
        )
    s3_prefix = contract["s3_prefix"]
    value_columns = list(contract.get("value_columns", []))
    types = _contract_partition_types(contract)

    objects: list[StagedObject] = []
    # sort=True keeps object order deterministic across runs (the F011/F015 determinism discipline);
    # dropna=False so a NULL partition value is KEPT as its own group and then rejected loudly by
    # partition_value_str -- pandas' default would DROP those rows silently, which is the worse of
    # the two failures (data disappears with an exit code of 0).
    for values, group in df.groupby(list(cols), dropna=False, sort=True):
        values = list(values) if isinstance(values, tuple) else [values]
        rendered = [partition_value_str(c, v, types.get(c)) for c, v in zip(cols, values)]
        body_df = group.drop(columns=list(cols))
        body = encode_parquet(body_df, contract)
        objects.append(StagedObject(
            canonical_key=partition_object_key(
                s3_prefix, cols, rendered, filename=filename),
            body=body,
            partition_values=rendered,
            row_count=len(body_df),
            null_metrics=null_metrics_for(body_df, value_columns) if value_columns else None,
        ))
    return objects


@dataclass(frozen=True)
class PartitionedSilverPlan:
    """The staged partitions for one run + the publisher preconfigured for them."""

    publisher: ShadowPublisher
    staged: list[StagedObject]
    schema: pa.Schema
    row_count: int

    @property
    def partition_count(self) -> int:
        return len(self.staged)

    def run(self, repair: Optional[RepairAuthorization] = None) -> RunManifest:
        """Execute the controlled publish and return the run manifest (dry-run: in-memory).

        ``repair`` is the F013 per-partition UPDATE authority: without it a partition already
        registered at a DIFFERENT location is a hard error, never a silent accept."""
        return self.publisher.run(self.staged, repair)


def build_partitioned_publish(
    *,
    df,
    contract: dict,
    auth: Authorization,
    job: str,
    partition_cols: Optional[Sequence[str]] = None,
    s3_client: Any = None,
    glue_client: Any = None,
    run_id: Optional[str] = None,
    code_sha: Optional[str] = None,
    shadow_prefix: Optional[str] = None,
    manifest_store=None,
    min_rows: int = 1,
    filename: str = DEFAULT_OBJECT_NAME,
    row_validator: Optional[Callable[[Any], Sequence[str]]] = None,
) -> PartitionedSilverPlan:
    """Assemble a registered-partition shadow-first publish for one silver DataFrame.

    ``contract`` is the F010 registry contract -- the schema, partition-key order, ``value_columns``
    and ``min_nonnull_frac`` authority. ``auth`` is the publish-guard verdict; dry-run and shadow
    never touch canonical, and the publisher only builds a ``PartitionPublisher`` (and so only needs
    ``glue_client``) on the canonical branch.

    ``min_rows=0`` is the documented way to round-trip a ZERO-ROW partition through
    write-verify-register: the house default of 1 rejects an empty object at STAGED->VALIDATED, so a
    zero-row smoke MUST pass ``min_rows=0`` or it fails by design rather than by defect.

    ``row_validator`` is the CONDITIONAL-INVARIANT hook: ``df -> list[str]`` of violations, run
    before a single byte is staged, non-empty => ``ValueError``. It exists because the F010 contract
    can only express UNCONDITIONAL nullability (``required_nonnull``), and the real rules are often
    conditional -- ``silver_futures_eod``'s ``contract_month`` is legally NULL if and ONLY if
    ``instrument_kind == 'cash_index'``, so leaving it merely ``nullable: true`` would let a
    producer that dropped the delivery month write natural-key-colliding rows past every gate.
    ``leviathan.silver.futures_eod_contracts.lint_frame`` is that table's validator and every
    futures_eod producer MUST pass it."""
    if contract.get("partition_mode") != "registered":
        raise ValueError(
            f"{contract.get('table_name')}: partition_mode is "
            f"{contract.get('partition_mode')!r}, not 'registered' -- this helper publishes ONLY "
            f"through the F013 registered path (INV-3: never enumerate/register a projected table)"
        )
    # Fail closed at plan-build time: shadow AND canonical STAGE objects to S3 (put_object), so a
    # write-mode publish with no client is a wiring bug -- surface it here as an actionable error
    # rather than a cryptic ``'NoneType' object has no attribute 'put_object'`` deep in the staging
    # loop. Only dry-run legitimately stages nothing and may pass ``s3_client=None``.
    if s3_client is None and auth.mode is not PublishMode.DRY_RUN:
        raise ValueError(
            f"{contract.get('table_name')}: publish-mode '{auth.mode.value}' stages objects to S3 and "
            "requires a live s3_client; only dry-run may pass s3_client=None"
        )
    if row_validator is not None:
        violations = list(row_validator(df))
        if violations:
            raise ValueError(
                f"{contract.get('table_name')}: {len(violations)} conditional-invariant "
                f"violation(s) -- refusing to stage: " + "; ".join(violations[:10])
            )
    objects = build_partition_objects(df, contract, partition_cols=partition_cols, filename=filename)
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
    publisher = ShadowPublisher(
        job=job,
        table=contract["table_name"],
        database=contract["glue_database"],
        bucket=contract["s3_bucket"],
        canonical_root=contract["s3_root"],
        auth=auth,
        s3_client=s3_client,
        glue_client=glue_client,
        strategy=PublishStrategy.REGISTERED,
        shadow_prefix=shadow_prefix,
        validation=validation,
        manifest_store=manifest_store,
        code_sha=code_sha,
        registry_schema_version=contract.get("schema_version"),
        run_id=run_id,
    )
    return PartitionedSilverPlan(
        publisher=publisher,
        staged=objects,
        schema=pa_schema_from_contract(contract),
        row_count=sum(o.row_count or 0 for o in objects),
    )
