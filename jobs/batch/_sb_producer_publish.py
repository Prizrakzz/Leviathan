"""Lane-SB (Small Sources B) producer-publish helper -- SILVER-F040/F041/F042/F043.

A thin, private helper the four Lane-SB batch tasks (frankfurter_fx, noaa_iod, sagis
deliveries, wap silver) route their SILVER writes through so they all satisfy the R1
platform contract with no duplicated ceremony:

  * INV-2 -- the parquet is written with an EXPLICIT pyarrow schema built directly from
    the SILVER-F010 registry contract's ``target_arrow_type`` (never dtype inference).
  * INV-6 / SILVER-F015 -- the write goes through :class:`leviathan.silver.publisher.
    ShadowPublisher` (FLAT strategy): shadow-first, validated, manifest-driven; canonical
    promotion happens ONLY with a verified signed approval.
  * INV-7 -- authorization comes from :func:`leviathan.common.publish_guard.authorize_publish`
    with the default ``--publish-mode dry-run`` (nothing is written unless explicitly and
    legitimately promoted to canonical).

This module makes NO AWS calls itself. It is deliberately underscore + ``sb``-prefixed so it
cannot collide with any other lane's new files. Read-only registry access only.
"""
from __future__ import annotations

import io
from typing import Any, Optional, Sequence

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from leviathan.common.publish_guard import PublishTarget, authorize_publish
from leviathan.silver.publisher import (
    PublishStrategy,
    RunManifest,
    ShadowPublisher,
    StagedObject,
    ValidationHooks,
)
from leviathan.silver.registry import load_registry

# INV-2 target_arrow_type token -> pyarrow type. The registry's target vocabulary
# (leviathan.silver.types) is closed over exactly these tokens.
_TARGET_TO_PA: dict[str, pa.DataType] = {
    "int64": pa.int64(),
    "float64": pa.float64(),
    "string": pa.string(),
    "bool": pa.bool_(),
    "date32[day]": pa.date32(),
    "timestamp[us]": pa.timestamp("us"),
}


def arrow_schema_from_contract(contract: dict) -> pa.Schema:
    """Build the explicit INV-2 writer schema for a table from its registry contract.

    One field per ``physical_columns`` entry, typed by ``target_arrow_type`` -- the single
    authority. Raises on an unknown target token so a bad contract fails closed, never
    silently degrading to inference.
    """
    fields: list[pa.Field] = []
    for col in contract.get("physical_columns", []):
        target = col["target_arrow_type"]
        if target not in _TARGET_TO_PA:
            raise ValueError(
                f"{contract.get('table_name')}.{col['name']}: unknown target_arrow_type "
                f"{target!r} (INV-2 vocabulary is {sorted(_TARGET_TO_PA)})"
            )
        fields.append(pa.field(col["name"], _TARGET_TO_PA[target], nullable=col.get("nullable", True)))
    return pa.schema(fields)


def df_to_parquet_bytes(df: pd.DataFrame, schema: pa.Schema) -> bytes:
    """Serialise ``df`` to parquet bytes under an EXPLICIT ``schema`` (INV-2).

    The frame's columns are reordered to the schema field order and cast through
    ``pa.Table.from_pandas(..., schema=schema)`` so pandas/pyarrow inference can never
    pick a float32/int32/large_string fragment.
    """
    ordered = df[[f.name for f in schema]]
    table = pa.Table.from_pandas(ordered, schema=schema, preserve_index=False)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    return buf.getvalue()


def nonnull_metrics(df: pd.DataFrame, value_columns: Sequence[str]) -> dict[str, float]:
    """Per-value-column non-null fraction for the publisher's V001-style validation hook."""
    n = len(df)
    if n == 0:
        return {c: 0.0 for c in value_columns}
    return {c: float(df[c].notna().sum()) / n for c in value_columns if c in df.columns}


def publish_flat_silver(
    *,
    table_name: str,
    df: pd.DataFrame,
    job: str,
    canonical_key: str,
    bucket: str,
    s3_client: Any,
    argv: Optional[Sequence[str]] = None,
    account_id: str = "",
    role_arn: str = "",
    approval: Any = None,
    code_sha: Optional[str] = None,
    min_nonnull_frac_override: Optional[float] = None,
) -> RunManifest:
    """Publish one flat single-object silver table through the shadow-first publisher.

    Loads the registry contract for ``table_name``, builds the explicit INV-2 schema,
    serialises ``df`` under it, and runs the controlled publish. Default mode is dry-run
    (nothing written); ``--publish-mode shadow`` writes only to the shadow prefix;
    ``--publish-mode canonical`` requires a verified signed approval. Returns the manifest.
    """
    # Resolve the caller identity when the task did not: the guard's canonical environment
    # check fails closed on an empty account/role (live-caught at the BF-W3 FX window -- dry-run
    # and shadow never reach check_environment, so T1-T5 cannot expose a blank identity).
    if not account_id and not role_arn:
        try:
            import boto3
            ident = boto3.client("sts").get_caller_identity()
            account_id, role_arn = ident.get("Account", ""), ident.get("Arn", "")
        except Exception:  # noqa: BLE001 -- offline dry-run stays authorized without identity
            pass

    reg = load_registry()
    contract = reg.table(table_name)
    schema = arrow_schema_from_contract(contract)
    body = df_to_parquet_bytes(df, schema)

    value_columns = list(contract.get("value_columns", []))
    floor = (
        min_nonnull_frac_override
        if min_nonnull_frac_override is not None
        else (contract.get("min_nonnull_frac") or 0.0)
    )

    target = PublishTarget(
        account_id=account_id,
        bucket=bucket,
        database=contract["glue_database"],
        prefix=contract["s3_prefix"].rstrip("/") + "/",
        role_arn=role_arn,
        table=table_name,
    )
    auth = authorize_publish(target, argv=argv, approval=approval)

    staged = StagedObject(
        canonical_key=canonical_key,
        body=body,
        row_count=len(df),
        null_metrics=nonnull_metrics(df, value_columns),
    )
    publisher = ShadowPublisher(
        job=job,
        table=table_name,
        database=contract["glue_database"],
        bucket=bucket,
        canonical_root=contract["s3_prefix"].rstrip("/"),
        auth=auth,
        s3_client=s3_client,
        strategy=PublishStrategy.FLAT,
        validation=ValidationHooks(min_rows=1, min_nonnull_frac=float(floor),
                                   floor_overrides=contract.get("min_nonnull_frac_overrides") or None),
        code_sha=code_sha,
        registry_schema_version=contract.get("schema_version"),
    )
    return publisher.run([staged])
