#!/usr/bin/env python
"""SILVER-F081: catalog + object recovery REHEARSAL -- restore a table's Glue definition and its
registered partitions from the R0 ``_raw`` snapshots into an ISOLATED rehearsal database, verify the
restore is byte-for-byte faithful, then destroy the ephemeral objects. The canonical catalog is
NEVER touched.

WHAT THIS PROVES (the F081 acceptance)
--------------------------------------
A disaster-recovery drill: if a silver Glue table (or its registered partitions) were lost, could we
rebuild the exact definition from the retained R0 snapshot? This tool answers that WITHOUT risking
production:

  1. read the table definition + registered partitions from
     ``reports/silver_readiness/<baseline>/_raw/<table>.get-table.json`` and ``.get-partitions.json``
     (the R0 live-Glue export -- the recovery source of truth);
  2. build the ``create_table`` ``TableInput`` + the ``batch_create_partition`` ``PartitionInput``
     list that recreate them **in the isolated rehearsal database** (default ``leviathan_rehearsal``,
     which is NOT ``leviathan_dev``) -- the ESR/WASDE registered class carries each partition's
     EXPLICIT Glue ``Location`` (MSCK cannot repair those; this preserves them exactly);
  3. verify the restore is byte-for-byte on the managed catalog subset -- the definition read back
     from the rehearsal DB must hash-equal the snapshot (``leviathan.silver.catalog``);
  4. tear the ephemeral table down (``delete_table``) so nothing lingers in the rehearsal DB.

THE ISOLATION GUARD (fail-closed -- refuses production)
-------------------------------------------------------
:func:`assert_rehearsal_isolated` runs BEFORE any mutating call and refuses, using the
publish_guard-declared production identity (:data:`leviathan.common.publish_guard.PROD_ENVIRONMENT`)
as the single source of truth for "what production is":

  * the target database equals the production Glue database (``leviathan_dev``)               -> REFUSE
  * the target database does not match the rehearsal pattern (must contain ``rehearsal``)      -> REFUSE
  * the resolved ``--publish-mode`` is ``canonical`` (rehearsal is NEVER a canonical publish)  -> REFUSE
  * any S3 write target resolves under the production bucket                                   -> REFUSE

So no production database or prefix can ever appear as a mutation target in a rehearsal run (the F081
"no production database/prefix in integration mutation logs" criterion). The table ``Location`` in
the restored definition still POINTS at the retained production S3 data (that is the correct DR
semantic -- recovery re-points the catalog at the surviving objects); it is a read pointer, never a
write target, and it lives in the isolated ``leviathan_rehearsal`` namespace.

MODES
-----
  * ``--dry-run`` (DEFAULT): issues ZERO AWS calls. It round-trips the snapshot through the
    build -> simulated-readback -> verify pipeline entirely offline (Glue echoes a ``TableInput`` back
    as a ``Table`` plus AWS-generated noise that the managed-subset normalization drops), so the
    transcript is real evidence that the restore is faithful -- not a promise. Emits the transcript +
    the ``CREATE DATABASE`` gate command.
  * ``--execute``: performs the real create/read/verify/delete against the rehearsal DB. It requires
    (a) the rehearsal database to already exist (a small, separate USER gate -- see the emitted gate
    command) and (b) the explicit ``--i-understand-this-mutates-rehearsal`` token. It still refuses
    production fail-closed. This path is intentionally NOT exercised by the readiness campaign
    (read-only AWS only); it is the documented run the owner performs once the rehearsal DB exists.

READ-ONLY-by-default, AWS-free in dry-run, ASCII-only stdout (cp1252 console). Report files UTF-8.

Usage:
    # dry-run transcript for two sample tables (a flat table + a registered-partition table)
    python scripts/silver/rehearse_recovery.py --table silver_cot --out reports/.../R4_F081_rehearsal
    python scripts/silver/rehearse_recovery.py --table silver_esr --out reports/.../R4_F081_rehearsal

    # the real drill (needs the rehearsal DB; separate user gate)
    python scripts/silver/rehearse_recovery.py --table silver_cot --execute \\
        --i-understand-this-mutates-rehearsal
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from leviathan.silver.catalog import (  # noqa: E402
    diff_partition_managed,
    diff_table,
    hash_partition,
    hash_table,
    normalize_partition,
    normalize_table,
)
from leviathan.common.publish_guard import (  # noqa: E402
    PROD_ENVIRONMENT,
    PublishMode,
    resolve_publish_mode,
)

DEFAULT_BASELINE = "20260712_p65impl"
DEFAULT_REHEARSAL_DB = "leviathan_rehearsal"
# The rehearsal database name MUST match this (and must NOT be the prod db). A drill can never target
# leviathan_dev even by typo.
REHEARSAL_DB_RE = re.compile(r"rehearsal", re.IGNORECASE)
# Batch Glue partition registration is capped at 100 inputs per call.
BATCH_PARTITION_CHUNK = 100


# ---------------------------------------------------------------------------
# Fail-closed isolation guard.
# ---------------------------------------------------------------------------
class RehearsalGuardError(RuntimeError):
    """Raised (BEFORE any mutation) when a rehearsal target is not provably isolated from prod."""


def assert_rehearsal_isolated(
    database: str,
    *,
    write_bucket: Optional[str] = None,
    argv: Optional[Sequence[str]] = None,
    env: Optional[Mapping[str, str]] = None,
) -> None:
    """Refuse fail-closed unless the rehearsal target is provably isolated from production.

    Uses the publish_guard-declared production identity as the single source of truth. Raises
    :class:`RehearsalGuardError` on ANY of: prod database, non-rehearsal database name, an S3 write
    target under the prod bucket, or a resolved ``--publish-mode canonical``. Mutates nothing.
    """
    env = os.environ if env is None else env
    problems: list[str] = []

    if not database or not database.strip():
        problems.append("empty rehearsal database name")
    else:
        if database == PROD_ENVIRONMENT.database:
            problems.append(
                f"database={database!r} IS the production Glue database "
                f"({PROD_ENVIRONMENT.database!r}); a rehearsal may never target it"
            )
        if REHEARSAL_DB_RE.search(database) is None:
            problems.append(
                f"database={database!r} does not match the rehearsal pattern "
                f"/{REHEARSAL_DB_RE.pattern}/ -- refuse a non-rehearsal namespace fail-closed"
            )

    if write_bucket is not None and write_bucket == PROD_ENVIRONMENT.bucket:
        problems.append(
            f"write_bucket={write_bucket!r} IS the production bucket "
            f"({PROD_ENVIRONMENT.bucket!r}); a rehearsal writes no production object"
        )

    # A rehearsal is never a canonical publish. Resolve the mode the same way publish_guard does.
    mode = resolve_publish_mode(argv, env)
    if mode is PublishMode.CANONICAL:
        problems.append(
            "resolved --publish-mode is 'canonical'; rehearsal recovery is never a canonical publish"
        )

    if problems:
        raise RehearsalGuardError(
            "rehearsal target is not provably isolated from production: " + "; ".join(problems)
        )


# ---------------------------------------------------------------------------
# Snapshot loading (the R0 _raw recovery source of truth).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Snapshot:
    """The R0 export for one table: the live Glue table def + its registered partitions."""

    table: str
    table_def: dict
    partitions: tuple[dict, ...]
    partition_count: int
    capped: bool
    table_path: Path
    partitions_path: Path


def raw_dir_for(baseline: str) -> Path:
    return _REPO / "reports" / "silver_readiness" / baseline / "_raw"


def load_snapshot(table: str, raw_dir: Path) -> Snapshot:
    """Load ``<table>.get-table.json`` + ``<table>.get-partitions.json`` from an R0 ``_raw`` dir."""
    tpath = raw_dir / f"{table}.get-table.json"
    ppath = raw_dir / f"{table}.get-partitions.json"
    if not tpath.exists():
        raise FileNotFoundError(f"no table snapshot for {table!r}: {tpath}")
    table_def = json.loads(tpath.read_text(encoding="utf-8"))
    parts: tuple[dict, ...] = ()
    count = 0
    capped = False
    if ppath.exists():
        pdoc = json.loads(ppath.read_text(encoding="utf-8"))
        parts = tuple(pdoc.get("partitions", []))
        count = int(pdoc.get("count", len(parts)))
        capped = bool(pdoc.get("capped", False))
    return Snapshot(
        table=table,
        table_def=table_def,
        partitions=parts,
        partition_count=count,
        capped=capped,
        table_path=tpath,
        partitions_path=ppath,
    )


# ---------------------------------------------------------------------------
# Build the create_table / batch_create_partition inputs (targeting the rehearsal DB).
# ---------------------------------------------------------------------------
# Keys AWS generates on read-back that are NOT part of a TableInput and must be stripped when we
# reconstruct the create request from a get-table export.
_TABLE_READ_ONLY_KEYS = frozenset({
    "DatabaseName", "CreateTime", "UpdateTime", "CreatedBy", "IsRegisteredWithLakeFormation",
    "CatalogId", "VersionId", "IsMultiDialectView", "IsMaterializedView", "FederatedTable",
})
_PARTITION_READ_ONLY_KEYS = frozenset({
    "DatabaseName", "TableName", "CreationTime", "LastAccessTime", "CatalogId",
})


def build_table_input(table_def: dict) -> dict:
    """A Glue ``TableInput`` reconstructed from a ``get-table`` export (read-only keys stripped).

    The DatabaseName is supplied to ``create_table`` separately, never inside the TableInput."""
    return {k: v for k, v in table_def.items() if k not in _TABLE_READ_ONLY_KEYS}


def build_partition_inputs(partitions: Sequence[dict]) -> list[dict]:
    """Glue ``PartitionInput`` list reconstructed from a ``get-partitions`` export.

    Each carries its EXPLICIT ``StorageDescriptor.Location`` -- for the ESR/WASDE registered class
    this per-partition location mapping (``as_of=`` / ``release_date=``) is exactly what MSCK cannot
    rebuild, so it must survive the restore verbatim."""
    return [{k: v for k, v in p.items() if k not in _PARTITION_READ_ONLY_KEYS} for p in partitions]


def chunk_partitions(pinputs: Sequence[dict], size: int = BATCH_PARTITION_CHUNK) -> list[list[dict]]:
    return [list(pinputs[i:i + size]) for i in range(0, len(pinputs), size)]


# ---------------------------------------------------------------------------
# Offline round-trip simulation (dry-run byte-for-byte proof, no AWS).
# ---------------------------------------------------------------------------
def simulate_readback_table(table_input: dict, database: str) -> dict:
    """Model what ``get_table`` returns after ``create_table(TableInput=table_input)``.

    Glue echoes the TableInput fields and ADDS server-generated noise (CreateTime, VersionId,
    CatalogId, ...) that the managed-subset normalization drops. Modelling that noise here makes the
    dry-run verify exercise the SAME normalization the real ``--execute`` readback verify uses."""
    readback = dict(table_input)
    readback["DatabaseName"] = database
    readback.setdefault("CreateTime", "2026-01-01 00:00:00+00:00")
    readback.setdefault("UpdateTime", "2026-01-01 00:00:00+00:00")
    readback["VersionId"] = "0"
    readback["CatalogId"] = "REHEARSAL"
    readback["IsRegisteredWithLakeFormation"] = False
    # Glue re-emits transient_lastDdlTime into Parameters -- also normalization noise.
    params = dict(readback.get("Parameters") or {})
    params["transient_lastDdlTime"] = "1900000000"
    readback["Parameters"] = params
    return readback


def simulate_readback_partition(pinput: dict, database: str, table: str) -> dict:
    """Model what ``get_partitions`` returns after ``batch_create_partition``."""
    readback = dict(pinput)
    readback["DatabaseName"] = database
    readback["TableName"] = table
    readback.setdefault("CreationTime", "2026-01-01 00:00:00+00:00")
    return readback


# ---------------------------------------------------------------------------
# Byte-for-byte verification (managed catalog subset).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class VerifyResult:
    table_match: bool
    table_hash_snapshot: str
    table_hash_readback: str
    table_diffs: tuple[str, ...]
    partitions_total: int
    partitions_matched: int
    partition_mismatches: tuple[dict, ...]

    @property
    def ok(self) -> bool:
        return (
            self.table_match
            and not self.table_diffs
            and self.partitions_matched == self.partitions_total
        )

    def to_dict(self) -> dict:
        return {
            "table_match": self.table_match,
            "table_hash_snapshot": self.table_hash_snapshot,
            "table_hash_readback": self.table_hash_readback,
            "table_diffs": list(self.table_diffs),
            "partitions_total": self.partitions_total,
            "partitions_matched": self.partitions_matched,
            "partition_mismatches": list(self.partition_mismatches),
            "byte_for_byte_ok": self.ok,
        }


def verify_restore(snapshot_table: dict, readback_table: dict,
                   snapshot_parts: Sequence[dict], readback_parts: Sequence[dict]) -> VerifyResult:
    """Compare a restored definition to its snapshot on the managed catalog subset.

    ``byte_for_byte_ok`` requires: the table's managed hash matches AND every partition's managed
    hash matches (by partition Values). AWS-generated noise (timestamps/version ids/db+table
    back-references) is normalized away by :mod:`leviathan.silver.catalog` first, so the comparison
    is over exactly the fields we manage and restore."""
    h_snap = hash_table(snapshot_table)
    h_back = hash_table(readback_table)
    tdiffs = tuple(diff_table(snapshot_table, readback_table))

    back_by_values = {tuple(normalize_partition(p)["values"]): p for p in readback_parts}
    matched = 0
    mismatches: list[dict] = []
    for sp in snapshot_parts:
        key = tuple(normalize_partition(sp)["values"])
        rb = back_by_values.get(key)
        if rb is None:
            mismatches.append({"values": list(key), "problem": "missing in readback"})
            continue
        if hash_partition(sp) == hash_partition(rb):
            matched += 1
        else:
            mismatches.append({
                "values": list(key),
                "problem": "managed-subset mismatch",
                "diffs": diff_partition_managed(sp, rb),
            })
    return VerifyResult(
        table_match=(h_snap == h_back),
        table_hash_snapshot=h_snap,
        table_hash_readback=h_back,
        table_diffs=tdiffs,
        partitions_total=len(snapshot_parts),
        partitions_matched=matched,
        partition_mismatches=tuple(mismatches),
    )


# ---------------------------------------------------------------------------
# Gate command (the rehearsal DB creation -- a small, separate user gate).
# ---------------------------------------------------------------------------
def create_database_command(database: str, region: str = "us-east-1") -> str:
    """The one-time ``CREATE DATABASE`` gate command. Documented as a gate artifact; NOT run here."""
    return (
        f"aws glue create-database --region {region} "
        f"--database-input '{json.dumps({'Name': database, 'Description': 'SILVER-F081 isolated recovery-rehearsal database (ephemeral objects only; never a serving surface).'})}'"
    )


# ---------------------------------------------------------------------------
# Dry-run transcript.
# ---------------------------------------------------------------------------
def rehearse_dry_run(table: str, raw_dir: Path, database: str,
                     *, argv: Optional[Sequence[str]] = None,
                     env: Optional[Mapping[str, str]] = None) -> dict:
    """Produce the full dry-run transcript (issues ZERO AWS calls). Runs the isolation guard first."""
    # Guard first -- even a dry-run refuses to describe a prod-targeted plan.
    assert_rehearsal_isolated(database, write_bucket=None, argv=argv, env=env)

    snap = load_snapshot(table, raw_dir)
    tinput = build_table_input(snap.table_def)
    pinputs = build_partition_inputs(snap.partitions)
    chunks = chunk_partitions(pinputs)

    # Offline round-trip: build -> simulated readback -> verify (the same normalization --execute uses).
    rb_table = simulate_readback_table(tinput, database)
    rb_parts = [simulate_readback_partition(p, database, table) for p in pinputs]
    verify = verify_restore(snap.table_def, rb_table, list(snap.partitions), rb_parts)

    norm = normalize_table(snap.table_def)
    partition_keys = [pk.get("Name") for pk in (snap.table_def.get("PartitionKeys") or [])]
    sample_partition_locations = [
        (normalize_partition(p)["values"], normalize_partition(p)["storage_descriptor"]["location"])
        for p in snap.partitions[:3]
    ]

    plan = {
        "package": "SILVER-F081",
        "mode": "dry-run",
        "table": table,
        "rehearsal_database": database,
        "production_database_refused": PROD_ENVIRONMENT.database,
        "source_snapshots": {
            "table": snap.table_path.relative_to(_REPO).as_posix(),
            "partitions": snap.partitions_path.relative_to(_REPO).as_posix(),
        },
        "definition": {
            "table_type": norm["table_type"],
            "location": norm["storage_descriptor"]["location"],
            "nonpartition_columns": len(norm["storage_descriptor"]["columns"]),
            "partition_keys": partition_keys,
            "registered_partition_count": snap.partition_count,
            "partitions_in_snapshot": len(snap.partitions),
            "partitions_capped_in_snapshot": snap.capped,
        },
        "planned_aws_calls": _planned_calls(database, table, tinput, chunks),
        "sample_partition_locations": [
            {"values": v, "location": loc} for v, loc in sample_partition_locations
        ],
        "verify": verify.to_dict(),
        "cleanup": {
            "call": "glue.delete_table",
            "args": {"DatabaseName": database, "Name": table},
            "note": "removes only the ephemeral rehearsal table; leaves the rehearsal DB for reuse.",
        },
        "gate_command_create_database": create_database_command(database),
        "isolation": {
            "guard": "assert_rehearsal_isolated",
            "refuses": [
                f"database == {PROD_ENVIRONMENT.database} (prod Glue db)",
                "database not matching /rehearsal/",
                f"any S3 write under {PROD_ENVIRONMENT.bucket} (prod bucket)",
                "resolved --publish-mode == canonical",
            ],
            "location_pointer_note": (
                "the restored table/partition Location still points at the retained production S3 "
                "data (a READ pointer -- correct DR semantics); no production object is written and "
                "the definition lives in the isolated rehearsal database."
            ),
        },
    }
    return plan


def _planned_calls(database: str, table: str, tinput: dict, chunks: list[list[dict]]) -> list[dict]:
    calls: list[dict] = [{
        "call": "glue.create_table",
        "args": {"DatabaseName": database, "TableInput.Name": tinput.get("Name"),
                 "TableInput.TableType": tinput.get("TableType")},
    }]
    for i, ch in enumerate(chunks):
        calls.append({
            "call": "glue.batch_create_partition",
            "chunk": i + 1,
            "of": len(chunks),
            "partition_inputs": len(ch),
            "args": {"DatabaseName": database, "TableName": table},
        })
    calls.append({"call": "glue.get_table", "purpose": "readback for byte-for-byte verify"})
    if chunks:
        calls.append({"call": "glue.get_partitions", "purpose": "readback for byte-for-byte verify"})
    calls.append({"call": "glue.delete_table", "purpose": "cleanup (teardown ephemeral rehearsal)"})
    return calls


def render_transcript_md(plan: dict) -> str:
    """A human transcript of the dry-run plan (UTF-8 report file)."""
    d = plan["definition"]
    v = plan["verify"]
    lines = [
        f"# SILVER-F081 recovery rehearsal -- `{plan['table']}` (dry-run transcript)",
        "",
        f"- rehearsal database: `{plan['rehearsal_database']}` "
        f"(production `{plan['production_database_refused']}` is refused fail-closed)",
        f"- source table snapshot: `{plan['source_snapshots']['table']}`",
        f"- source partitions snapshot: `{plan['source_snapshots']['partitions']}`",
        "",
        "## Definition restored",
        f"- table type: `{d['table_type']}`",
        f"- location (read pointer): `{d['location']}`",
        f"- non-partition columns: {d['nonpartition_columns']}",
        f"- partition keys: {d['partition_keys'] or '(none -- flat table)'}",
        f"- registered partitions: {d['registered_partition_count']} "
        f"(in snapshot: {d['partitions_in_snapshot']}, capped={d['partitions_capped_in_snapshot']})",
        "",
        "## Planned AWS calls (NONE issued in dry-run)",
    ]
    for c in plan["planned_aws_calls"]:
        extra = {k: val for k, val in c.items() if k != "call"}
        lines.append(f"- `{c['call']}` {json.dumps(extra) if extra else ''}".rstrip())
    if plan["sample_partition_locations"]:
        lines += ["", "## Sample explicit partition locations (registered class -- MSCK cannot rebuild these)"]
        for s in plan["sample_partition_locations"]:
            lines.append(f"- `{s['values']}` -> `{s['location']}`")
    lines += [
        "",
        "## Byte-for-byte verification (managed catalog subset)",
        f"- table managed hash (snapshot): `{v['table_hash_snapshot']}`",
        f"- table managed hash (readback): `{v['table_hash_readback']}`",
        f"- table match: **{v['table_match']}**  diffs: {v['table_diffs'] or 'none'}",
        f"- partitions matched: **{v['partitions_matched']}/{v['partitions_total']}**",
        f"- BYTE-FOR-BYTE OK: **{v['byte_for_byte_ok']}**",
        "",
        "## Cleanup",
        f"- `{plan['cleanup']['call']}` {json.dumps(plan['cleanup']['args'])} -- "
        f"{plan['cleanup']['note']}",
        "",
        "## Gate command (one-time, separate user gate -- NOT run by this tool)",
        "```",
        plan["gate_command_create_database"],
        "```",
        "",
        "## Isolation guard",
        f"- guard: `{plan['isolation']['guard']}` refuses: "
        + "; ".join(plan["isolation"]["refuses"]),
        f"- location pointer: {plan['isolation']['location_pointer_note']}",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Execute path (the real drill -- gated; NOT run by the readiness campaign).
# ---------------------------------------------------------------------------
def rehearse_execute(table: str, raw_dir: Path, database: str, region: str = "us-east-1") -> dict:
    """Perform the real create/read/verify/delete against the rehearsal DB. Guard runs first.

    Lazily imports boto3 so the module stays AWS-free for dry-run + tests. The isolation guard here
    passes ``write_bucket=None`` because the rehearsal writes only catalog metadata (no S3 object)."""
    assert_rehearsal_isolated(database, write_bucket=None)
    import boto3  # lazy

    glue = boto3.client("glue", region_name=region)
    snap = load_snapshot(table, raw_dir)
    tinput = build_table_input(snap.table_def)
    pinputs = build_partition_inputs(snap.partitions)

    created = False
    try:
        glue.create_table(DatabaseName=database, TableInput=tinput)
        created = True
        for ch in chunk_partitions(pinputs):
            if ch:
                glue.batch_create_partition(DatabaseName=database, TableName=table, PartitionInputList=ch)
        rb_table = glue.get_table(DatabaseName=database, Name=table)["Table"]
        rb_parts: list[dict] = []
        paginator = glue.get_paginator("get_partitions")
        for page in paginator.paginate(DatabaseName=database, TableName=table):
            rb_parts.extend(page.get("Partitions", []))
        verify = verify_restore(snap.table_def, rb_table, list(snap.partitions), rb_parts)
        return {
            "package": "SILVER-F081", "mode": "execute", "table": table,
            "rehearsal_database": database, "verify": verify.to_dict(),
        }
    finally:
        if created:
            glue.delete_table(DatabaseName=database, Name=table)


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------
def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description="SILVER-F081 catalog/object recovery rehearsal")
    ap.add_argument("--table", required=True, help="silver/gold table to rehearse (must be in _raw)")
    ap.add_argument("--baseline", default=DEFAULT_BASELINE, help="R0 baseline id under reports/silver_readiness")
    ap.add_argument("--raw-dir", default=None, help="override the _raw snapshot dir")
    ap.add_argument("--database", default=DEFAULT_REHEARSAL_DB, help="isolated rehearsal Glue db")
    ap.add_argument("--out", default=None, help="write the transcript under this dir")
    ap.add_argument("--publish-mode", default=None, help="publish_guard mode (rehearsal refuses 'canonical')")
    ap.add_argument("--execute", action="store_true", help="real drill (needs the rehearsal DB; gated)")
    ap.add_argument("--i-understand-this-mutates-rehearsal", action="store_true",
                    help="required acknowledgement token for --execute")
    args = ap.parse_args(argv)

    raw_dir = Path(args.raw_dir) if args.raw_dir else raw_dir_for(args.baseline)

    try:
        if args.execute:
            if not args.i_understand_this_mutates_rehearsal:
                print("ERROR: --execute requires --i-understand-this-mutates-rehearsal", file=sys.stderr)
                return 2
            result = rehearse_execute(args.table, raw_dir, args.database)
            print(f"[F081] execute {args.table}: byte_for_byte_ok="
                  f"{result['verify']['byte_for_byte_ok']}")
        else:
            result = rehearse_dry_run(args.table, raw_dir, args.database, argv=argv, env=os.environ)
            v = result["verify"]
            print(f"[F081] dry-run {args.table}: table_match={v['table_match']} "
                  f"partitions={v['partitions_matched']}/{v['partitions_total']} "
                  f"byte_for_byte_ok={v['byte_for_byte_ok']}")
    except RehearsalGuardError as exc:
        print(f"[F081] REFUSED (isolation guard): {exc}", file=sys.stderr)
        return 3
    except FileNotFoundError as exc:
        print(f"[F081] ERROR: {exc}", file=sys.stderr)
        return 4

    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{args.table}.rehearsal.json").write_text(
            json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        if not args.execute:
            (out_dir / f"{args.table}.rehearsal.md").write_text(
                render_transcript_md(result), encoding="utf-8")
        print(f"[F081] transcript -> {out_dir}")

    return 0 if result["verify"]["byte_for_byte_ok"] else 5


if __name__ == "__main__":
    raise SystemExit(main())
