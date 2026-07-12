"""Plan / apply / rollback catalog migration tool (SILVER-F012, lightened lock).

Replaces the partial hard-coded ``jobs/run_athena_ddl.py`` runner (4 of 42 silver DDLs, ad-hoc
mix of Athena + direct Glue) with ONE registry-enumerated, plan-then-apply reconciler for the whole
silver catalog. It is declarative: a *plan* is the diff between the DESIRED Glue table (built from the
SILVER-F010 registry contract) and the LIVE Glue table, expressed as the exact ``create_table`` /
``update_table`` calls to make -- and it is read-only. *apply* executes a previously-cut plan under a
single fencing lease, but only after re-confirming the live catalog hash still equals the hash the
plan was cut against (so a catalog that drifted after planning refuses the apply). *rollback-plan* and
the executable *restore* rebuild the accepted ``TableInput`` from the R0 ``_raw/`` snapshots.

MODES
-----
  * ``validate``      -- registry loads + every desired table builds cleanly (no AWS).
  * ``plan``          -- read-only; emit ``MigrationPlan`` per table (create / additive-update /
                         property-update / no-op) + the frozen live hash. Refuses to plan a DROP, a
                         partition-key change, or a type NARROWING (F012 step 7).
  * ``apply``         -- guarded; re-check live hash == plan hash + lease fencing token immediately
                         before each mutation; back up the live ``TableInput`` first; execute; write a
                         migration manifest under ``sql/athena/migrations/silver/``.
  * ``rollback-plan`` -- emit the ``TableInput`` restore call from an R0 ``_raw/`` snapshot (read-only).
  * ``restore``       -- guarded; executable restore from a snapshot with the same hash/fence guard.

SAFETY (F012 steps 4-7):
  * additive-only: a plan whose diff would DROP a column, CHANGE a partition key, or NARROW a type is
    refused (``UnsafeMigration``) -- those go through a reviewed migration, never this tool.
  * ``CREATE ... IF NOT EXISTS`` semantics are bootstrap-only: an existing table always takes the
    controlled update path (never a second create).
  * registered-partition StorageDescriptor audit: an update that changes columns/types/format/SerDe on
    a table with registered partitions flags the partitions needing a controlled repair (delegated to
    F013), it never silently leaves them stale.
  * every mutation is authorized through :mod:`leviathan.common.publish_guard` (canonical requires the
    signed approval); dry-run/shadow plan only.

The tool performs the mutation ONLY when handed an :class:`Authorization` with ``may_mutate_canonical``
AND a held :class:`Lease`; otherwise ``apply``/``restore`` emit the plan and touch nothing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from leviathan.common.logging import get_logger
from leviathan.common.publish_guard import Authorization
from leviathan.silver import catalog
from leviathan.silver.lease import Lease
from leviathan.silver.registry import SilverRegistry, load_registry
from leviathan.silver.types import is_narrowing_change

logger = get_logger(__name__)

_GLUE_INPUT_FORMAT = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
_GLUE_OUTPUT_FORMAT = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
_GLUE_SERDE = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"


class ChangeType(str, Enum):
    CREATE = "create"                    # table absent -> create_table (bootstrap)
    ADDITIVE_UPDATE = "additive_update"  # new columns / widened managed fields -> update_table
    PROPERTY_UPDATE = "property_update"   # only managed table params differ
    NOOP = "noop"                         # desired == live (managed)


class UnsafeMigration(RuntimeError):
    """A plan would drop a column, change a partition key, or narrow a type -- refused (F012 step 7)."""


class MigrationConflict(RuntimeError):
    """The live catalog hash changed after the plan was cut (or the fence is stale) -- apply refused."""


@dataclass
class MigrationPlan:
    table: str
    database: str
    change_type: ChangeType
    live_hash: Optional[str]        # frozen at plan time; apply re-checks it
    desired_hash: str
    diffs: list[str] = field(default_factory=list)
    glue_call: str = ""             # human-readable exact call (create_table / update_table)
    table_input: dict = field(default_factory=dict)
    registered_partition_audit: Optional[dict] = None
    unsafe: list[str] = field(default_factory=list)

    @property
    def is_noop(self) -> bool:
        return self.change_type is ChangeType.NOOP

    def to_dict(self) -> dict:
        return {
            "table": self.table,
            "database": self.database,
            "change_type": self.change_type.value,
            "live_hash": self.live_hash,
            "desired_hash": self.desired_hash,
            "diffs": self.diffs,
            "glue_call": self.glue_call,
            "table_input": self.table_input,
            "registered_partition_audit": self.registered_partition_audit,
            "unsafe": self.unsafe,
        }


# ---------------------------------------------------------------------------
# Desired-table synthesis from the registry contract.
# ---------------------------------------------------------------------------
def _glue_columns(contract: dict) -> list[dict]:
    """Ordered non-partition columns as Glue expects, using the registry glue_type (the CURRENT
    catalog type -- migrations here are additive/property, not the INV-2 widen which is a reviewed
    F031 data rewrite)."""
    return [{"Name": c["name"], "Type": c.get("glue_type", "string")}
            for c in contract.get("physical_columns", [])]


def _glue_partition_keys(contract: dict) -> list[dict]:
    return [{"Name": pk["name"], "Type": pk.get("glue_type", "string")}
            for pk in contract.get("partition_keys", [])]


def build_desired_table(contract: dict) -> dict:
    """Build the DESIRED Glue ``TableInput``-shaped dict from a registry contract. Deterministic;
    the managed fields only (location, columns, partition keys, formats, SerDe, EXTERNAL params)."""
    location = contract["s3_root"].rstrip("/")
    params = {"EXTERNAL": "TRUE", "parquet.compression": "SNAPPY"}
    proj = contract.get("projection")
    if proj == "enabled" or contract.get("partition_mode") == "projected":
        params["projection.enabled"] = "true"
    return {
        "Name": contract["table_name"],
        "TableType": "EXTERNAL_TABLE",
        "PartitionKeys": _glue_partition_keys(contract),
        "Parameters": params,
        "StorageDescriptor": {
            "Columns": _glue_columns(contract),
            "Location": location,
            "InputFormat": _GLUE_INPUT_FORMAT,
            "OutputFormat": _GLUE_OUTPUT_FORMAT,
            "SerdeInfo": {"SerializationLibrary": _GLUE_SERDE,
                          "Parameters": {"serialization.format": "1"}},
            "Parameters": {},
        },
    }


# ---------------------------------------------------------------------------
# The migration tool.
# ---------------------------------------------------------------------------
@dataclass
class CatalogMigrator:
    """Registry-enumerated catalog migrator. ``glue_client`` is injectable (tests mock it). ``auth``
    is the publish-guard verdict; ``lease`` (+ its ``fencing_token``) is required to mutate."""

    database: str
    auth: Authorization
    glue_client: Any
    registry: Optional[SilverRegistry] = None
    lease: Optional[Lease] = None
    fencing_token: Optional[int] = None
    migrations_dir: Optional[Path] = None
    raw_snapshot_dir: Optional[Path] = None

    def __post_init__(self) -> None:
        if self.registry is None:
            self.registry = load_registry()

    # -- live-table access --------------------------------------------------------------------
    def _get_live(self, table: str) -> Optional[dict]:
        try:
            return self.glue_client.get_table(DatabaseName=self.database, Name=table)["Table"]
        except Exception as exc:  # noqa: BLE001
            if _is_not_found(exc):
                return None
            raise

    # -- planning (read-only) -----------------------------------------------------------------
    def plan_table(self, table: str) -> MigrationPlan:
        contract = self.registry.tables[table]
        desired = build_desired_table(contract)
        live = self._get_live(table)

        # PARAM PRESERVATION (F012 additive-only doctrine): the tool manages only EXTERNAL /
        # parquet.compression / projection.enabled. Every OTHER live table param (the full
        # projection.* grid, classification, deprojected, ...) is carried forward, never proposed for
        # removal -- dropping a projection.* param would silently break a projected table. So for an
        # existing table the desired param set is (live params) overlaid with the tool-managed ones.
        if live is not None:
            preserved = catalog._clean_params(live.get("Parameters"), catalog._NOISE_TABLE_PARAMS)
            desired["Parameters"] = {**preserved, **desired["Parameters"]}
        desired_hash = catalog.hash_table(desired)

        if live is None:
            return MigrationPlan(
                table=table, database=self.database, change_type=ChangeType.CREATE,
                live_hash=None, desired_hash=desired_hash,
                diffs=["table absent -> bootstrap create"],
                glue_call=f"glue.create_table(DatabaseName={self.database!r}, "
                          f"TableInput=<desired {table}>)",
                table_input=desired,
            )

        live_hash = catalog.hash_table(live)
        diffs = catalog.diff_table(live, desired)
        unsafe = self._unsafe_diffs(live, desired)
        if not diffs:
            return MigrationPlan(table, self.database, ChangeType.NOOP, live_hash, desired_hash,
                                 diffs=[], glue_call="(no change)", table_input=desired)

        # classify: property-only vs additive-schema.
        col_or_struct_changed = any(
            d.startswith(("columns:", "partition_keys:", "location:", "input_format:",
                          "output_format:", "serde_library:", "serde_params:", "table_type:"))
            for d in diffs
        )
        change = ChangeType.ADDITIVE_UPDATE if col_or_struct_changed else ChangeType.PROPERTY_UPDATE
        audit = self._registered_partition_audit(table, live, desired) if col_or_struct_changed else None
        return MigrationPlan(
            table=table, database=self.database, change_type=change, live_hash=live_hash,
            desired_hash=desired_hash, diffs=diffs,
            glue_call=f"glue.update_table(DatabaseName={self.database!r}, "
                      f"TableInput=<desired {table}>)  # additive; VersionId re-checked",
            table_input=desired, registered_partition_audit=audit, unsafe=unsafe,
        )

    def plan_all(self) -> list[MigrationPlan]:
        return [self.plan_table(t) for t in self.registry.names()]

    def _unsafe_diffs(self, live: dict, desired: dict) -> list[str]:
        """Detect DROP column, partition-key change, type NARROWING (all refused on apply)."""
        out: list[str] = []
        live_cols = {c["Name"]: (c.get("Type") or "").lower()
                     for c in (live.get("StorageDescriptor") or {}).get("Columns", [])}
        des_cols = {c["Name"]: (c.get("Type") or "").lower()
                    for c in (desired.get("StorageDescriptor") or {}).get("Columns", [])}
        for name in live_cols:
            if name not in des_cols:
                out.append(f"DROP column '{name}' (refused)")
        for name, lt in live_cols.items():
            dt = des_cols.get(name)
            if dt and dt != lt and is_narrowing_change(_glue_target(lt), _glue_target(dt)):
                out.append(f"NARROW column '{name}' {lt} -> {dt} (refused)")
        live_pk = [(pk["Name"], (pk.get("Type") or "").lower()) for pk in live.get("PartitionKeys", [])]
        des_pk = [(pk["Name"], (pk.get("Type") or "").lower()) for pk in desired.get("PartitionKeys", [])]
        if live_pk and live_pk != des_pk:
            out.append(f"partition-key change {live_pk} -> {des_pk} (refused)")
        return out

    def _registered_partition_audit(self, table: str, live: dict, desired: dict) -> dict:
        """On a schema-changing update to a table with registered partitions, report that each
        partition's StorageDescriptor will diverge and needs a controlled F013 repair (this tool
        never blindly mutates partition SDs)."""
        contract = self.registry.tables.get(table, {})
        if contract.get("partition_mode") != "registered":
            return {"registered": False}
        sd_diffs = catalog.diff_storage_descriptor(
            live.get("StorageDescriptor") or {}, desired.get("StorageDescriptor") or {})
        return {
            "registered": True,
            "table_sd_changes": sd_diffs,
            "action": "partitions need controlled repair via SILVER-F013 PartitionPublisher "
                      "(this tool updates the table SD only, not partition SDs)",
        }

    # -- apply (guarded) ----------------------------------------------------------------------
    def apply_table(self, plan: MigrationPlan) -> dict:
        """Execute one plan. Refuses on: an unsafe diff; a live-hash drift since the plan was cut; a
        stale fence; or a no-op. Backs up the live TableInput first, then create/update, then writes
        the migration manifest. In non-canonical mode it returns the plan WITHOUT mutating."""
        if plan.unsafe:
            raise UnsafeMigration(f"{plan.table}: refused unsafe migration: {plan.unsafe}")
        if plan.is_noop:
            return {"table": plan.table, "applied": False, "reason": "noop"}

        if not self.auth.may_mutate_canonical:
            logger.info("apply %s: non-canonical mode (%s); plan only, catalog untouched",
                        plan.table, self.auth.mode.value)
            return {"table": plan.table, "applied": False, "reason": "non-canonical-plan-only",
                    "plan": plan.to_dict()}

        # re-confirm the live state has not drifted since the plan was cut.
        live = self._get_live(plan.table)
        if plan.change_type is ChangeType.CREATE:
            if live is not None:
                raise MigrationConflict(
                    f"{plan.table}: planned CREATE but the table now exists (drift); re-plan")
        else:
            if live is None:
                raise MigrationConflict(f"{plan.table}: planned update but table vanished; re-plan")
            if catalog.hash_table(live) != plan.live_hash:
                raise MigrationConflict(
                    f"{plan.table}: live catalog hash drifted since plan "
                    f"({catalog.hash_table(live)} != {plan.live_hash}); re-plan required")

        backup = self._backup_live(plan.table, live)
        self._fence()  # fencing recheck immediately before the mutation
        if plan.change_type is ChangeType.CREATE:
            self.glue_client.create_table(DatabaseName=self.database, TableInput=plan.table_input)
        else:
            self.glue_client.update_table(DatabaseName=self.database, TableInput=plan.table_input)
        manifest_path = self._write_migration_manifest(plan, backup)
        logger.info("applied %s (%s); manifest=%s", plan.table, plan.change_type.value, manifest_path)
        return {"table": plan.table, "applied": True, "change_type": plan.change_type.value,
                "manifest": str(manifest_path), "backup_hash": backup.get("catalog_hash")}

    def _backup_live(self, table: str, live: Optional[dict]) -> dict:
        return {
            "table": table,
            "captured_at": _now_iso(),
            "table_input": _serializable(live) if live else None,
            "catalog_hash": catalog.hash_table(live) if live else None,
        }

    # -- rollback / restore -------------------------------------------------------------------
    def rollback_plan(self, table: str, snapshot: Optional[dict] = None) -> dict:
        """Read-only: emit the restore call that would re-establish the R0 ``_raw`` snapshot's
        ``TableInput``. ``snapshot`` defaults to the R0 ``_raw/<table>.get-table.json``."""
        snap = snapshot if snapshot is not None else self._load_raw_snapshot(table)
        table_input = raw_snapshot_to_table_input(snap)
        return {
            "table": table,
            "restore_call": f"glue.update_table(DatabaseName={self.database!r}, "
                            f"TableInput=<R0 snapshot {table}>)",
            "table_input": table_input,
            "expected_hash_after": catalog.hash_table(table_input),
        }

    def restore_table(self, table: str, snapshot: Optional[dict] = None,
                      *, expected_current_hash: Optional[str] = None) -> dict:
        """Executable restore (F012 step 9). Guarded: canonical + fence required; if
        ``expected_current_hash`` is given the live table must still match it (do not clobber a table
        that changed since the operator decided to roll back). Verifies the post-restore hash."""
        snap = snapshot if snapshot is not None else self._load_raw_snapshot(table)
        table_input = raw_snapshot_to_table_input(snap)
        target_hash = catalog.hash_table(table_input)

        if not self.auth.may_mutate_canonical:
            return {"table": table, "restored": False, "reason": "non-canonical-plan-only",
                    "table_input": table_input, "expected_hash_after": target_hash}

        live = self._get_live(table)
        if expected_current_hash is not None:
            live_hash = catalog.hash_table(live) if live else None
            if live_hash != expected_current_hash:
                raise MigrationConflict(
                    f"{table}: live hash {live_hash} != expected {expected_current_hash}; restore refused")
        self._fence()
        if live is None:
            self.glue_client.create_table(DatabaseName=self.database, TableInput=table_input)
        else:
            self.glue_client.update_table(DatabaseName=self.database, TableInput=table_input)
        # post-restore verification.
        after = self._get_live(table)
        after_hash = catalog.hash_table(after) if after else None
        if after_hash != target_hash:
            raise MigrationConflict(
                f"{table}: post-restore hash {after_hash} != target {target_hash} (restore unverified)")
        return {"table": table, "restored": True, "verified_hash": after_hash}

    # -- helpers ------------------------------------------------------------------------------
    def _fence(self) -> None:
        if self.lease is None or self.fencing_token is None:
            raise MigrationConflict("a held lease + fencing token is required to mutate the catalog")
        self.lease.recheck(self.fencing_token)

    def _load_raw_snapshot(self, table: str) -> dict:
        base = self.raw_snapshot_dir or _default_raw_dir()
        path = base / f"{table}.get-table.json"
        if not path.exists():
            raise FileNotFoundError(f"R0 raw snapshot not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_migration_manifest(self, plan: MigrationPlan, backup: dict) -> Path:
        base = self.migrations_dir or _default_migrations_dir()
        base.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = base / f"{ts}_{plan.table}_{plan.change_type.value}.json"
        payload = {
            "applied_at": _now_iso(),
            "database": self.database,
            "table": plan.table,
            "change_type": plan.change_type.value,
            "plan": plan.to_dict(),
            "backup": backup,
            "guard_mode": self.auth.mode.value,
            "fencing_token": self.fencing_token,
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return path


# ---------------------------------------------------------------------------
# R0 _raw snapshot -> Glue TableInput.
# ---------------------------------------------------------------------------
def raw_snapshot_to_table_input(snapshot: dict) -> dict:
    """Convert an R0 ``_raw/<table>.get-table.json`` (a ``get_table`` ``Table``) into a
    ``create_table``/``update_table`` ``TableInput`` -- dropping the read-only fields Glue rejects on
    input (``CreateTime``/``UpdateTime``/``VersionId``/``CreatedBy``/``CatalogId``/``DatabaseName``/
    ``IsRegisteredWithLakeFormation``/view flags)."""
    drop = {
        "CreateTime", "UpdateTime", "VersionId", "CreatedBy", "CatalogId", "DatabaseName",
        "IsRegisteredWithLakeFormation", "IsMultiDialectView", "IsMaterializedView",
    }
    ti = {k: v for k, v in snapshot.items() if k not in drop}
    return ti


# ---------------------------------------------------------------------------
# module-level helpers.
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serializable(obj: Any) -> Any:
    """Datetime-safe deep copy for the backup blob (Glue get_table returns datetime objects)."""
    return json.loads(json.dumps(obj, default=str))


def _glue_target(glue_type: str) -> str:
    """Map a Glue type token to the types.is_narrowing_change vocabulary (int64/float64/string/...)."""
    g = (glue_type or "").split("(")[0].strip().lower()
    if g in ("bigint",):
        return "int64"
    if g in ("int", "integer", "smallint", "tinyint"):
        return "int32" if g != "smallint" else "int16"
    if g == "double":
        return "float64"
    if g in ("float", "real"):
        return "float32"
    if g in ("string", "varchar", "char"):
        return "string"
    if g in ("boolean", "bool"):
        return "bool"
    if g == "date":
        return "date32[day]"
    if g.startswith("timestamp"):
        return "timestamp[us]"
    if g.startswith("decimal"):
        return "float64"
    return g


def _default_migrations_dir() -> Path:
    return _repo_root() / "sql" / "athena" / "migrations" / "silver"


def _default_raw_dir() -> Path:
    return (_repo_root() / "reports" / "silver_readiness" / "20260712_p65impl" / "_raw")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _is_not_found(exc: BaseException) -> bool:
    resp = getattr(exc, "response", None)
    code = ""
    if isinstance(resp, dict):
        code = str(resp.get("Error", {}).get("Code", ""))
    return code in ("EntityNotFoundException", "EntityNotFound") or \
        type(exc).__name__ == "EntityNotFoundException"
