#!/usr/bin/env python
"""SILVER-F062 PINNED-WRITER CATALOG WIDENING -- the two tables the writer pin left in debt.

    python scripts/ops/pinned_writer_widening_runbook.py
    python scripts/ops/pinned_writer_widening_runbook.py --table silver_fgis
    python scripts/ops/pinned_writer_widening_runbook.py --offline
    python scripts/ops/pinned_writer_widening_runbook.py --apply
    python scripts/ops/pinned_writer_widening_runbook.py --verify-read
    python scripts/ops/pinned_writer_widening_runbook.py --table silver_fgis --rollback
    python scripts/ops/pinned_writer_widening_runbook.py --rollback --dry-run --offline --offline-dir DIR

DRY RUN BY DEFAULT.  With no flag this reads live Glue (or, with ``--offline``, the tracked R0
``_raw`` sidecars) and PRINTS the plan and the before/after column types.  Nothing mutates unless
``--apply`` or ``--rollback`` is passed, and both of those are the OWNER's: they take a lease,
re-read live, and refuse on any precondition.

THE TWO MUTATING PATHS ARE NOT THE SAME CALL, AND THAT IS THE WHOLE POINT
------------------------------------------------------------------------
``--apply`` (narrow -> wide) is a WIDEN: ``is_narrowing_change`` is False for all eleven columns,
``CatalogMigrator._unsafe_diffs`` returns ``[]``, and the plan goes through
``CatalogMigrator.apply_table`` -- the F012 path, with its live-hash re-check, lease fence, backup
and machine manifest.

``--rollback`` (wide -> narrow) is a NARROWING BY CONSTRUCTION, and ``apply_table`` refuses every
narrowing on principle (``UnsafeMigration``).  MEASURED 2026-09-10 against a simulated post-apply
WIDE catalog: ``is_narrowing_change`` is True for all eleven reverse directions (bigint->int,
bigint->smallint, bigint->tinyint, double->float), so routing the reverse plan through
``apply_table`` produces a DEAD command -- it refuses, nothing is restored, and the rollback the
manifests advertise does not exist.  The sanctioned detour for exactly this case is
``CatalogMigrator.restore_table`` (``leviathan.silver.types`` names the precedent in its own
comment: "B2's F036 int->bigint had to detour through restore_table for the same false NARROW").
So ``--rollback`` restores a TableInput through ``restore_table``, and the narrowing override it
represents is BOUNDED: the run refuses unless the unsafe list is EXACTLY the eleven expected
``NARROW column ...`` entries for exactly the debt columns -- a DROP, a partition-key change or a
narrowing of any other column still stops the run.  The restore basis is not the R0 sidecar but the
LIVE table with only those Type tokens reversed, so unrelated catalog drift is never reverted, and
``restore_table`` refuses if the live hash moved since the plan was cut and verifies the
post-restore hash itself.

Commands printed for the operator are WINDOWS POWERSHELL 5.1: chained with ``;``, never with
``&&`` (a parser error in 5.1).  Stdout is ASCII only (the console is cp1252).

WHAT THIS PAYS, AND WHY IT IS A DEBT AND NOT AN ERRAND
-----------------------------------------------------
Commit 3f5f4720 flipped ``writer_schema_pinned`` on six silver contracts.  The pin makes each
writer emit its contract's ``target_arrow_type`` -- the SILVER-F062 WIDEN target, deliberately
wider than what the live objects carry.  On four of the six the widen is a no-op.  On
``silver_fgis`` and ``silver_modis_ndvi`` it is not:

    silver_fgis        week_of_marketing_year   int      -> bigint    (1 column)
    silver_modis_ndvi  year / period / pixel_reliability
                                                smallint/tinyint -> bigint
                       latitude / longitude / ndvi_raw / ndvi /
                       ndvi_z_score / baseline_mean / baseline_std
                                                float    -> double    (10 columns)

The next canonical promote of either family writes INT64/DOUBLE parquet under a catalog that says
int/smallint/tinyint/float.  That promote is AUTONOMOUS -- both families' schedules are ENABLED
with ``promote.mode = "autonomous"`` and a ``--force-overwrite`` canonical command, and
``jobs/audit/silver_rebuild_gate`` is a value/footer census that carries no ``glue_type`` and no
type reconciliation, so nothing on that path can see the mismatch.  The trigger is therefore the
WORKER IMAGE REPIN, not a human decision, which is why no silver jobdef may be repinned past
fbe6a7cb until both widens land.  ``tests/unit/silver/test_pinned_writer_catalog_debt.py`` holds
the debt list; this runbook pays it and prints the steps that empty it.

WHY THE F012 PLANNER CANNOT PLAN THIS
-------------------------------------
``migrate._glue_columns`` builds the DESIRED table from the contract's ``glue_type``, which its own
docstring calls "the CURRENT catalog type -- migrations here are additive/property, not the INV-2
widen".  So ``CatalogMigrator.plan_table`` computes desired == live and returns NOOP for both
tables; ``scripts/silver/plan_catalog_migration.py`` reports them as ``noop`` rows.  The sanctioned
way to make the planner emit a widen is to move the contract's ``glue_type`` to the target FIRST
(registry LEADS Glue -- the ``f011_ddl_diff_report._MIGRATION_PENDING`` mechanism).  That registry
edit is deliberately NOT taken: the catalog is applied first and the registry is REGENERATED from a
re-captured R0 afterwards (the CONAB / tranche-2 apply-then-refresh precedent), so no hand-edited
contract ever exists.  This runbook therefore builds the desired ``TableInput`` from the LIVE table
and hands the resulting plan to the SAME ``CatalogMigrator.apply_table``.

WHY THE DESIRED TableInput IS THE LIVE ONE, VERBATIM
----------------------------------------------------
``update_table`` REPLACES a table definition: a field omitted from the ``TableInput`` is GONE.
MEASURED 2026-09-09: the 2026-07-15 ``silver_noaa_oni`` widen went through
``CatalogMigrator.build_desired_table``, whose minimal ``TableInput`` dropped ``Owner``
('hadoop' -> None), ``LastAccessTime``, ``SkewedInfo`` and ``BucketColumns`` and moved
``NumberOfBuckets`` -1 -> 0 on that table.  ``silver_fgis`` carries FIVE ``projection.*`` parameters
plus ``storage.location.template``; losing one of them silently breaks a projected table.  So this
runbook never rebuilds a TableInput: it takes the live one, drops only the read-only fields Glue
rejects on input (``migrate.raw_snapshot_to_table_input``), changes ONLY the Type tokens of the
named columns, and then ASSERTS that ``Parameters`` and ``PartitionKeys`` serialize byte-identically
before and after -- refusing the apply if they do not.

THE ORDER, AND THE ONE STEP THAT MUST NOT MOVE
----------------------------------------------
    1. apply the widen              (--apply)              catalog leads the objects
    2. prove the objects still read (--verify-read)        one bounded SELECT
    3. canonical --force-overwrite rewrite                 objects become wide; catalog == objects
    4. re-capture R0 + regenerate the registry             ONLY AFTER 3
    5. empty EXPECTED_DEBT to {} and run the decks

Step 4 must not run before step 3, and that is MEASURED, not cautionary:
``leviathan.silver.types.classify_drift('int32','bigint')`` returns
``['glue_catalog_mismatch', 'widen_int']`` (against ``[]`` for ``('int64','bigint')``).  An R0
re-capture taken in the window between the ALTER and the rewrite therefore regenerates a contract
that STILL declares an F062 widen -- which empties ``EXPECTED_DEBT`` and then fails
``test_pinned_writer_catalog_debt.py::test_every_debt_column_is_already_declared_as_an_f062_widen``,
whose second loop asserts that a pinned contract off the debt list declares no widen.

EXIT CODES
----------
    0  the plan printed / the apply verified
    2  REFUSED on a precondition (types are not what we expect; Parameters or PartitionKeys would
       move; an unsafe diff beyond the bounded reverse set; --apply combined with --offline)
    3  applied but POST-APPLY VERIFICATION FAILED (the re-read does not show the expected types),
       or --verify-read failed / returned no rows
    4  an AWS / lease error.  The handler names every table that had already been mutated when it
       fired -- with ``--table all`` the second table can fail after the first has applied.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from leviathan.common.publish_guard import Authorization, PublishMode  # noqa: E402
from leviathan.silver import catalog  # noqa: E402
from leviathan.silver.lease import Lease  # noqa: E402
from leviathan.silver.migrate import (  # noqa: E402
    CatalogMigrator,
    ChangeType,
    MigrationPlan,
    raw_snapshot_to_table_input,
)
from leviathan.silver.registry import load_registry  # noqa: E402

DATABASE = "leviathan_dev"
REGION = "us-east-1"
BUCKET = "leviathan-dev-shahem-001"
LEASE_PREFIX = "silver"
LEASE_ID = "catalog-migration"
R0_RAW = _REPO / "reports" / "silver_readiness" / "20260712_p65impl" / "_raw"
MIGRATIONS_DIR = _REPO / "sql" / "athena" / "migrations" / "silver"

# The INV-2 target arrow type -> the Glue/Athena spelling of the same physical type. Kept local and
# tiny on purpose: an unmapped target must fail the runbook, never be assumed safe.
_ARROW_TO_GLUE = {"int64": "bigint", "float64": "double"}

# THE DEBT, PINNED. Ordered as the live catalog orders the columns. MEASURED 2026-09-09 by
# glue.get_table against database leviathan_dev; identical to the tracked R0 _raw sidecars
# (catalog.hash_table equal on both tables), and identical to the EXPECTED_DEBT map in
# tests/unit/silver/test_pinned_writer_catalog_debt.py. ``_assert_matches_registry`` re-derives this
# from the contracts at every run, so the two cannot drift apart in silence.
EXPECTED_WIDENING = {
    "silver_fgis": [
        ("week_of_marketing_year", "int", "bigint"),
    ],
    "silver_modis_ndvi": [
        ("year", "smallint", "bigint"),
        ("period", "tinyint", "bigint"),
        ("latitude", "float", "double"),
        ("longitude", "float", "double"),
        ("ndvi_raw", "float", "double"),
        ("ndvi", "float", "double"),
        ("pixel_reliability", "tinyint", "bigint"),
        ("ndvi_z_score", "float", "double"),
        ("baseline_mean", "float", "double"),
        ("baseline_std", "float", "double"),
    ],
}

# The migration manifest each table's widen is recorded in (the hand-authored, gated record; the
# machine manifest CatalogMigrator writes on apply lands beside it).
MIGRATION_FILES = {
    "silver_fgis": "20260909T000000Z_silver_fgis_type_widening_additive.json",
    "silver_modis_ndvi": "20260909T000000Z_silver_modis_ndvi_type_widening_additive.json",
}

# The autonomous promote each table rides -- the reason the widen is ordered, not optional.
PROMOTE = {
    "silver_fgis": ("fgis", "cron(0 12 ? * THU *)"),
    "silver_modis_ndvi": ("modis_biweekly", "cron(0 9 ? * MON *)"),
}

# A bounded read probe per table: proves the EXISTING narrow objects are still readable under the
# widened catalog. fgis is projected, so the probe pins one slug + one year and touches one object.
VERIFY_SQL = {
    "silver_fgis": (
        "SELECT week_of_marketing_year, count(*) AS n "
        "FROM leviathan_dev.silver_fgis "
        "WHERE leviathan_slug = 'corn_cbot' AND marketing_year = 2024 "
        "GROUP BY 1 ORDER BY 1 LIMIT 5"
    ),
    "silver_modis_ndvi": (
        "SELECT year, period, pixel_reliability, latitude, longitude, ndvi, ndvi_z_score, "
        "baseline_mean, baseline_std, ndvi_raw "
        "FROM leviathan_dev.silver_modis_ndvi LIMIT 5"
    ),
}

TABLES = tuple(EXPECTED_WIDENING)


class Refused(RuntimeError):
    """A precondition failed. Nothing was mutated (exit 2)."""


# Tables this process has actually mutated, in order. The error handlers read it so an owner is
# never told "no mutation was issued" after the first of two tables already moved.
_MUTATED: list[str] = []


def _managed_params(table: dict) -> str:
    """The table's Parameters with the AWS-generated noise keys stripped, as a stable string.

    ``transient_lastDdlTime`` and friends are rewritten by Glue itself on an update_table; comparing
    RAW Parameters would turn that cosmetic rewrite into a failed post-apply check and send the
    owner to a rollback for nothing. ``catalog._NOISE_TABLE_PARAMS`` is the estate's own definition
    of that noise -- the same set ``catalog.hash_table`` and ``CatalogMigrator.plan_table`` use."""
    return json.dumps(catalog._clean_params(table.get("Parameters"), catalog._NOISE_TABLE_PARAMS),
                      sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# the widening map, re-derived from the registry so it cannot drift
# ---------------------------------------------------------------------------
def widening_from_registry(table: str) -> list[tuple[str, str, str]]:
    """[(column, live glue type, target glue type)] for every column the pinned writer would write
    untypeable, derived from the contract exactly the way the debt deck derives it."""
    contract = load_registry().table(table)
    if not contract.get("writer_schema_pinned"):
        raise Refused(f"{table}: contract is not writer_schema_pinned -- it owes no widen")
    out: list[tuple[str, str, str]] = []
    for col in contract.get("physical_columns") or []:
        glue = str(col.get("glue_type") or "").strip().lower()
        target = str(col.get("target_arrow_type") or "").strip().lower()
        if not glue or target not in _ARROW_TO_GLUE:
            continue
        want = _ARROW_TO_GLUE[target]
        if want != glue:
            out.append((col["name"], glue, want))
    return out


def _assert_matches_registry(table: str) -> list[tuple[str, str, str]]:
    derived = widening_from_registry(table)
    pinned = EXPECTED_WIDENING[table]
    if derived != pinned:
        raise Refused(
            f"{table}: the contract's widen set moved.\n"
            f"  registry says : {derived}\n"
            f"  runbook pins  : {pinned}\n"
            "  Re-measure before applying anything: this runbook and the contract must agree.")
    return pinned


# ---------------------------------------------------------------------------
# live / offline table access
# ---------------------------------------------------------------------------
def _glue_client(region: str):
    import boto3
    return boto3.client("glue", region_name=region)


def read_table(table: str, *, offline: bool, glue_client=None, database: str = DATABASE,
               offline_dir: Path = None) -> dict:
    if offline:
        path = (offline_dir or R0_RAW) / f"{table}.get-table.json"
        if not path.exists():
            raise Refused(f"offline source missing: {path}")
        return json.loads(path.read_text(encoding="utf-8"))
    return glue_client.get_table(DatabaseName=database, Name=table)["Table"]


# ---------------------------------------------------------------------------
# the desired TableInput: the live one, with ONLY the named Type tokens changed
# ---------------------------------------------------------------------------
def widen_table_input(live: dict, changes: list[tuple[str, str, str]]) -> dict:
    """Return (TableInput). Every field except the named column Types is carried verbatim.

    REFUSES (``Refused``) unless every named column exists and holds EXACTLY its expected ``from``
    type -- a column already widened, or holding some third type, stops the run rather than being
    overwritten."""
    want = {name: (frm, to) for name, frm, to in changes}
    ti = raw_snapshot_to_table_input(live)
    sd = dict(ti.get("StorageDescriptor") or {})
    cols = []
    seen = set()
    for col in sd.get("Columns") or []:
        col = dict(col)
        name = col.get("Name")
        if name in want:
            frm, to = want[name]
            have = str(col.get("Type") or "").strip().lower()
            if have != frm:
                raise Refused(
                    f"{ti.get('Name')}.{name}: live Glue says {have!r}, expected exactly {frm!r} "
                    "-- refusing (the catalog is not in the state this migration was measured "
                    "against)")
            col["Type"] = to
            seen.add(name)
        cols.append(col)
    missing = sorted(set(want) - seen)
    if missing:
        raise Refused(f"{ti.get('Name')}: columns absent from live Glue: {missing}")
    sd["Columns"] = cols
    ti["StorageDescriptor"] = sd
    return ti


def assert_shape_preserved(live: dict, desired: dict) -> None:
    """Parameters and PartitionKeys must serialize byte-identically. This is the projection fence."""
    for field in ("Parameters", "PartitionKeys"):
        a = json.dumps(live.get(field), sort_keys=True, default=str)
        b = json.dumps(desired.get(field), sort_keys=True, default=str)
        if a != b:
            raise Refused(
                f"{live.get('Name')}: {field} would change -- REFUSED.\n  live   : {a}\n  desired: {b}")
    lsd = live.get("StorageDescriptor") or {}
    dsd = desired.get("StorageDescriptor") or {}
    for field in ("Location", "InputFormat", "OutputFormat", "SerdeInfo", "Parameters",
                  "BucketColumns", "SortColumns", "SkewedInfo", "NumberOfBuckets", "Compressed",
                  "StoredAsSubDirectories"):
        a = json.dumps(lsd.get(field), sort_keys=True, default=str)
        b = json.dumps(dsd.get(field), sort_keys=True, default=str)
        if a != b:
            raise Refused(f"{live.get('Name')}: StorageDescriptor.{field} would change -- REFUSED."
                          f"\n  live   : {a}\n  desired: {b}")
    lnames = [c.get("Name") for c in lsd.get("Columns") or []]
    dnames = [c.get("Name") for c in dsd.get("Columns") or []]
    if lnames != dnames:
        raise Refused(f"{live.get('Name')}: column NAMES or ORDER would change -- REFUSED.\n"
                      f"  live   : {lnames}\n  desired: {dnames}")


def build_plan(table: str, live: dict, desired: dict, mig: CatalogMigrator,
               database: str = DATABASE, direction: str = "WIDEN") -> MigrationPlan:
    if direction == "ROLLBACK":
        glue_call = (
            f"CatalogMigrator.restore_table({table!r}, snapshot=<live {table} with the column "
            f"types reversed to narrow>, expected_current_hash=<the live hash below>)\n"
            f"      -> glue.update_table(DatabaseName={database!r}, TableInput=<that snapshot>)  "
            "# lease-fenced; post-restore hash verified by restore_table")
    else:
        glue_call = (f"glue.update_table(DatabaseName={database!r}, "
                     f"TableInput=<live {table} with the widened column types>)  "
                     "# additive; live hash re-checked")
    return MigrationPlan(
        table=table,
        database=database,
        change_type=ChangeType.ADDITIVE_UPDATE,
        live_hash=catalog.hash_table(live),
        desired_hash=catalog.hash_table(desired),
        diffs=catalog.diff_table(live, desired),
        glue_call=glue_call,
        table_input=desired,
        # MEASURED, never asserted: both contracts are partition_mode projected/flat, so this comes
        # back {"registered": False} -- but it comes back from the migrator, not from a literal.
        registered_partition_audit=mig._registered_partition_audit(table, live, desired),
        unsafe=mig._unsafe_diffs(live, desired),  # the sanctioned refuser; apply_table raises on it
    )


def expected_reverse_unsafe(changes: list[tuple[str, str, str]]) -> list[str]:
    """The EXACT ``_unsafe_diffs`` lines a correct reverse plan must produce -- one per debt column,
    in the migrator's own wording. The rollback's narrowing override is bounded by this list: an
    unsafe entry that is not in it (a DROP, a partition-key change, a narrowing of some other
    column) is a REFUSAL, not an override."""
    return [f"NARROW column {name!r} {frm} -> {to} (refused)" for name, frm, to in changes]


def check_unsafe(table: str, plan: MigrationPlan, changes: list[tuple[str, str, str]],
                 direction: str) -> list[str]:
    """Gate the plan's unsafe list for the direction. Returns the list of entries deliberately
    OVERRIDDEN (empty for a widen). Raises ``Refused`` on anything unexpected."""
    if direction != "ROLLBACK":
        if plan.unsafe:
            raise Refused(f"{table}: unsafe diff {plan.unsafe}")
        return []
    want = expected_reverse_unsafe(changes)
    if sorted(plan.unsafe) != sorted(want):
        raise Refused(
            f"{table}: the reverse plan's unsafe set is not the bounded expected one -- REFUSED.\n"
            f"  got  : {plan.unsafe}\n"
            f"  want : {want}\n"
            "  Only the eleven measured debt-column narrowings may be overridden by --rollback.")
    return want


# ---------------------------------------------------------------------------
# printing
# ---------------------------------------------------------------------------
def _rule(ch: str = "-") -> str:
    return ch * 78


def print_plan(table: str, live: dict, desired: dict, plan: MigrationPlan,
               changes: list[tuple[str, str, str]], *, source: str, direction: str) -> None:
    lsd = live.get("StorageDescriptor") or {}
    dsd = desired.get("StorageDescriptor") or {}
    dtypes = {c["Name"]: c["Type"] for c in dsd.get("Columns") or []}
    changed = {name for name, _, _ in changes}

    print(_rule("="))
    print(f"{table}   [{direction}]   source={source}")
    print(_rule("="))
    print(f"  database        : {plan.database}")
    print(f"  location        : {lsd.get('Location')}")
    print(f"  table VersionId : {live.get('VersionId')}   UpdateTime: {live.get('UpdateTime')}")
    family, cron = PROMOTE[table]
    print(f"  autonomous promote: family {family} on {cron}")
    print(f"  migration record: sql/athena/migrations/silver/{MIGRATION_FILES[table]}")
    print()
    print("  COLUMN TYPES  (* = changed by this plan)")
    print(("    %-2s %-24s %-10s %-10s" % ("", "column", "before", "after")).rstrip())
    for c in lsd.get("Columns") or []:
        n = c["Name"]
        mark = "*" if n in changed else " "
        print(("    %-2s %-24s %-10s %-10s" % (mark, n, c["Type"], dtypes.get(n))).rstrip())
    print(f"    ({len(changed)} of {len(lsd.get('Columns') or [])} columns change; "
          "names, order and ordinals are unchanged)")
    print()
    pk = live.get("PartitionKeys") or []
    print("  PARTITION KEYS  (carried byte-for-byte; NOT part of this migration)")
    if pk:
        for p in pk:
            projected = ""
            if (live.get("Parameters") or {}).get(f"projection.{p['Name']}.type"):
                projected = ("  [PROJECTED: %s -- read from the S3 path, never from the parquet body]"
                             % (live["Parameters"][f"projection.{p['Name']}.type"]))
            print(f"    {p['Name']:<24} {p['Type']}{projected}")
    else:
        print("    (none -- flat table)")
    print()
    params = live.get("Parameters") or {}
    proj = sorted(k for k in params if k.startswith("projection.") or k == "storage.location.template")
    print(f"  TABLE PARAMETERS  ({len(params)} keys, carried byte-for-byte)")
    for k in sorted(params):
        tag = "  <- partition projection" if k in proj else ""
        print(f"    {k:<44} = {params[k]}{tag}")
    same_params = (json.dumps(live.get("Parameters"), sort_keys=True, default=str)
                   == json.dumps(desired.get("Parameters"), sort_keys=True, default=str))
    same_keys = (json.dumps(live.get("PartitionKeys"), sort_keys=True, default=str)
                 == json.dumps(desired.get("PartitionKeys"), sort_keys=True, default=str))
    print(f"    byte-identity (Parameters)   : {'PASS' if same_params else 'FAIL'}")
    print(f"    byte-identity (PartitionKeys): {'PASS' if same_keys else 'FAIL'}")
    print()
    print("  PLAN")
    print(f"    change_type   : {plan.change_type.value}")
    print(f"    live_hash     : {plan.live_hash}")
    print(f"    desired_hash  : {plan.desired_hash}")
    print(f"    diffs         : {len(plan.diffs)}")
    for d in plan.diffs:
        print(f"      {d[:2000]}")
    print(f"    registered_partition_audit: {json.dumps(plan.registered_partition_audit, sort_keys=True)}")
    if direction == "ROLLBACK":
        print(f"    unsafe        : {len(plan.unsafe)} entry(ies) -- EXPECTED. A reverse plan IS a")
        print("                    narrowing, and CatalogMigrator.apply_table refuses every")
        print("                    narrowing. --rollback therefore does NOT go through apply_table:")
        print("                    it goes through CatalogMigrator.restore_table, and this exact")
        print("                    list is the bounded override (any other entry = REFUSED).")
        for u in plan.unsafe:
            print(f"      {u[:2000]}")
    elif plan.unsafe:
        print(f"    unsafe        : {plan.unsafe}   <-- REFUSED (a widen must produce none)")
    else:
        print("    unsafe        : [] (no drop, no partition-key change, no narrowing -- "
              "is_narrowing_change is False for every widen here)")
    print()
    print("  THE EXACT CALL THIS WOULD ISSUE")
    print(f"    {plan.glue_call}")
    print("  EQUIVALENT DDL (documentation only -- NOT the path taken; a DDL statement cannot")
    print("  assert Parameters/PartitionKeys byte-identity, which on a projected table IS the risk)")
    after = ", ".join(f"{c['Name']} {dtypes[c['Name']]}" for c in lsd.get("Columns") or [])
    print(f"    ALTER TABLE {plan.database}.{table} REPLACE COLUMNS ({after});")
    print()


def print_post_rollback_steps(rolled_back: list[str]) -> None:
    """What a ROLLBACK owes the operator -- which is the OPPOSITE of the post-apply sequence.

    The post-apply steps end in 'let the canonical rewrite happen' and 'empty EXPECTED_DEBT'. After
    a rollback those two are the two most dangerous actions in the estate: the rewrite would put
    INT64/DOUBLE parquet under a catalog that has just been put BACK to int/smallint/tinyint/float,
    and emptying the debt map would delete the tripwire that says so. So a rollback prints this
    instead, and print_post_apply_steps is never reached on this path."""
    print()
    print(_rule("="))
    print("POST-ROLLBACK STEPS  (Windows PowerShell 5.1: one statement per line; chain with ';')")
    print(_rule("="))
    print("THE CATALOG IS NARROW AGAIN. The estate is back in the state the debt map describes.")
    print("DO NOT run the post-apply sequence. In particular:")
    print("  - do NOT fire a canonical --force-overwrite rewrite on these families;")
    print("  - do NOT re-capture R0 or regenerate the registry;")
    print("  - do NOT empty EXPECTED_DEBT -- it is the tripwire that is now correct again.")
    print()
    print("[1] CONFIRM the narrow types are what live Glue carries (a dry-run re-reads live and")
    print("    refuses unless every column is exactly narrow, so exit 0 IS the confirmation).")
    for t in rolled_back:
        print(f"    python scripts/ops/pinned_writer_widening_runbook.py --table {t}")
    print()
    print("[2] PROVE THE OBJECTS STILL READ under the restored catalog.")
    for t in rolled_back:
        print(f"    python scripts/ops/pinned_writer_widening_runbook.py --table {t} --verify-read")
    print()
    print("[3] THE HOLD STANDS, AND IT IS NOW THE ONLY THING PROTECTING THESE TWO FAMILIES:")
    print("    no silver jobdef may be repinned past fbe6a7cb. A worker image carrying 3f5f4720")
    print("    would make the next autonomous promote write wide parquet under this narrow")
    print("    catalog, with no owner gate in the way:")
    for t in rolled_back:
        family, cron = PROMOTE[t]
        print(f"      {t:<18} family {family:<15} {cron}")
    print()
    print("[4] THE DECKS -- they must still be GREEN, because nothing about the debt has changed.")
    print("    python -m pytest tests/unit/silver/test_pinned_writer_catalog_debt.py -q")
    print("    python -m pytest tests/unit/silver/test_pinned_writer_widening_migration.py -q")
    print()
    print("[5] Leave \"applied\": false in the hand-authored manifests (it never became true), and")
    print("    keep the rollback record this run wrote beside them as the audit trail. Then work")
    print("    out WHY the widen had to be reversed before proposing it again.")


def print_post_apply_steps(applied: list[str]) -> None:
    print()
    print(_rule("="))
    print("POST-APPLY STEPS  (Windows PowerShell 5.1: one statement per line; chain with ';')")
    print(_rule("="))
    print("Run them IN THIS ORDER. Step 3 gates step 4; see the header of this file for the")
    print("measurement that makes that ordering load-bearing.")
    print()
    print("[1] PROVE THE EXISTING NARROW OBJECTS STILL READ under the widened catalog.")
    print("    This is the one claim the authoring lane could not measure (it is read-only on AWS).")
    for t in applied:
        print(f"    python scripts/ops/pinned_writer_widening_runbook.py --table {t} --verify-read")
    print("    If it FAILS: roll back and stop --")
    for t in applied:
        print(f"    python scripts/ops/pinned_writer_widening_runbook.py --table {t} --rollback")
    print()
    print("[2] LET THE CANONICAL REWRITE HAPPEN (or fire it by hand). The autonomous promote")
    print("    rewrites the objects wide; after it, catalog == objects.")
    for t in applied:
        family, cron = PROMOTE[t]
        print(f"    {t:<18} family {family:<15} {cron}")
    print()
    print("[3] R0 RE-CAPTURE -- ONLY AFTER THE REWRITE. --check first (it writes nothing and")
    print("    prints the stored-vs-live diff), then the real capture with its _raw sidecars.")
    for t in applied:
        print(f"    python scripts/silver/run_census.py --table {t} --check")
    for t in applied:
        print(f"    python scripts/silver/run_census.py --table {t} --raw")
    print()
    print("[4] REGENERATE THE REGISTRY FROM THE RE-CAPTURED BASELINE. --check FIRST: exit 3 means")
    print("    'regeneration would change the tree', which is exactly what we expect here; run it")
    print("    again without --check to write, then re-render the generated DDL tree.")
    print("    python scripts/silver/gen_registry_from_baseline.py --check")
    print("    python scripts/silver/gen_registry_from_baseline.py")
    print("    python scripts/silver/generate_ddls_from_registry.py --write")
    print()
    print("[5] THE F011 DDL DIFF -- the registry-vs-hand-DDL-vs-live-Glue drift report.")
    print("    python scripts/silver/f011_ddl_diff_report.py")
    print()
    print("[6] EMPTY THE DEBT MAP. In tests/unit/silver/test_pinned_writer_catalog_debt.py replace")
    print("    the whole EXPECTED_DEBT literal with:")
    print("        EXPECTED_DEBT = {}")
    print("    (its own comment says 'EMPTY THIS as each ALTER lands and the R0 baseline is")
    print("    re-captured'. Do NOT empty it before step 4 -- an un-regenerated contract still")
    print("    carries the narrow glue_type and the deck would then fail the other way.)")
    print()
    print("[7] THE DECKS. Read every exit code.")
    print("    python -m pytest tests/unit/silver/test_pinned_writer_catalog_debt.py -q")
    print("    python -m pytest tests/unit/silver/test_pinned_writer_widening_migration.py -q")
    print("    python -m pytest tests/unit/silver/test_ddl_generation.py -q")
    print("    python -m pytest tests/unit/silver -q")
    print()
    print("[8] Record the apply in the migration manifests: set \"applied\": true and")
    print("    \"applied_at\" to the UTC timestamp in")
    for t in applied:
        print(f"    sql/athena/migrations/silver/{MIGRATION_FILES[t]}")
    print("    The machine manifest CatalogMigrator wrote on apply lands in the same directory as")
    print("    <UTC>_<table>_additive_update.json and carries the executable backup.")
    print()
    print("ONLY AFTER ALL OF THE ABOVE is the fbe6a7cb silver-jobdef repin hold released.")


# ---------------------------------------------------------------------------
# modes
# ---------------------------------------------------------------------------
def dry_run(tables: list[str], *, offline: bool, region: str, database: str,
            direction: str = "WIDEN", offline_dir: Path = None) -> int:
    glue = None if offline else _glue_client(region)
    mig = CatalogMigrator(
        database=database,
        auth=Authorization(mode=PublishMode.DRY_RUN, may_mutate_canonical=False, readiness=False,
                           reason="pinned-writer widening dry-run"),
        glue_client=glue)
    if offline:
        source = ("tracked R0 _raw sidecar (AWS-free)" if offline_dir is None
                  else f"offline snapshot dir {offline_dir} (AWS-free)")
    else:
        source = "live glue.get_table"
    for table in tables:
        changes = _assert_matches_registry(table)
        if direction == "ROLLBACK":
            changes = [(n, to, frm) for n, frm, to in changes]
        live = read_table(table, offline=offline, glue_client=glue, database=database,
                          offline_dir=offline_dir)
        desired = widen_table_input(live, changes)
        assert_shape_preserved(live, desired)
        plan = build_plan(table, live, desired, mig, database, direction)
        # The SAME gate the mutating path runs. A dry-run that previews a plan the apply would
        # refuse is worse than no preview at all, so this refuses here too (exit 2).
        check_unsafe(table, plan, changes, direction)
        print_plan(table, live, desired, plan, changes, source=source, direction=direction)
    print(_rule("="))
    print("DRY RUN -- NOTHING WAS MUTATED. No glue.update_table was issued, no lease was taken,")
    if direction == "ROLLBACK":
        print("no S3 object was written. Re-run with --rollback ALONE (drop --dry-run) to execute.")
    else:
        print("no S3 object was written. Re-run with --apply (owner) to execute.")
    print(_rule("="))
    return 0


def _write_rollback_record(table: str, plan: MigrationPlan, live: dict, result: dict,
                           migrations_dir: Path) -> Path:
    """``CatalogMigrator.restore_table`` writes no machine manifest (the F012 restore step never
    did). A rollback that leaves no record is an unaudited catalog mutation, so this runbook writes
    one beside the apply manifests, in the same directory and the same spirit: the PRE-ROLLBACK
    (wide) TableInput is the backup."""
    migrations_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = migrations_dir / f"{ts}_{table}_rollback_restore.json"
    payload = {
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "database": plan.database,
        "table": table,
        "change_type": "rollback_restore",
        "mechanism": "leviathan.silver.migrate.CatalogMigrator.restore_table "
                     "(apply_table refuses every narrowing; restore_table is the sanctioned "
                     "reverse path)",
        "plan": plan.to_dict(),
        "backup": {"table": table, "captured_at": datetime.now(timezone.utc).isoformat(),
                   "table_input": json.loads(json.dumps(live, default=str)),
                   "catalog_hash": plan.live_hash},
        "result": result,
        "guard_mode": "canonical",
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def apply(tables: list[str], *, region: str, database: str, bucket: str, lease_prefix: str,
          lease_id: str, direction: str = "WIDEN", glue_client=None, s3_client=None,
          migrations_dir: Path = None) -> int:
    import boto3

    glue = glue_client if glue_client is not None else _glue_client(region)
    s3 = s3_client if s3_client is not None else boto3.client("s3", region_name=region)
    migrations_dir = migrations_dir or MIGRATIONS_DIR
    del _MUTATED[:]
    auth = Authorization(mode=PublishMode.CANONICAL, may_mutate_canonical=True, readiness=False,
                         reason=f"SILVER-F062 pinned-writer catalog widening (owner {direction})")
    print(_rule("="))
    print(f"APPLY [{direction}] -- this MUTATES the Glue catalog.")
    print("  guard: an Authorization(mode=canonical) constructed by this runbook, plus a REAL S3")
    print("         lease fence rechecked immediately before each update_table. This mirrors the")
    print("         2026-07-15 silver_noaa_oni apply (manifest guard_mode=canonical). No parquet")
    print("         object is read or written by this path.")
    if direction == "ROLLBACK":
        print("  path : CatalogMigrator.restore_table -- NOT apply_table, which refuses every")
        print("         narrowing (measured: is_narrowing_change is True for all eleven reverse")
        print("         directions). The override is bounded to exactly those eleven columns.")
    print(_rule("="))

    # ---- preflight: every table, every precondition, BEFORE any mutation ----------------------
    staged = []
    for table in tables:
        changes = _assert_matches_registry(table)
        if direction == "ROLLBACK":
            changes = [(n, to, frm) for n, frm, to in changes]
        live = read_table(table, offline=False, glue_client=glue, database=database)
        desired = widen_table_input(live, changes)          # refuses on any unexpected live type
        assert_shape_preserved(live, desired)               # refuses if Parameters/PK would move
        mig = CatalogMigrator(database=database, auth=auth, glue_client=glue,
                              migrations_dir=migrations_dir, raw_snapshot_dir=R0_RAW)
        plan = build_plan(table, live, desired, mig, database, direction)
        overridden = check_unsafe(table, plan, changes, direction)
        if len(plan.diffs) != 1 or not plan.diffs[0].startswith("columns:"):
            raise Refused(f"{table}: expected exactly one `columns:` diff, got {plan.diffs}")
        staged.append((table, live, desired, plan, changes, mig))
        print(f"  preflight OK: {table}  ({len(changes)} column(s); VersionId "
              f"{live.get('VersionId')})")
        for u in overridden:
            print(f"    bounded narrowing override: {u}")
    print()

    lease = Lease(bucket=bucket, prefix=lease_prefix, lock_id=lease_id, s3_client=s3)
    state = lease.acquire()
    print(f"  lease ACQUIRED s3://{bucket}/{lease.key}  owner={state.owner} "
          f"token={state.fencing_token} expires={state.expires_at}")
    try:
        for table, live, desired, plan, changes, mig in staged:
            mig.lease = lease
            mig.fencing_token = state.fencing_token
            before_version = live.get("VersionId")
            if direction == "ROLLBACK":
                # restore_table, NOT apply_table: the reverse plan is a narrowing and apply_table
                # refuses every narrowing (UnsafeMigration). restore_table re-checks the live hash
                # against the one this plan was cut from, fences, and verifies the post-restore
                # hash itself.
                result = mig.restore_table(table, snapshot=desired,
                                           expected_current_hash=plan.live_hash)
            else:
                result = mig.apply_table(plan)
            after = read_table(table, offline=False, glue_client=glue, database=database)
            after_types = {c["Name"]: c["Type"] for c in
                           (after.get("StorageDescriptor") or {}).get("Columns", [])}
            _MUTATED.append(table)
            if direction == "ROLLBACK":
                record = _write_rollback_record(table, plan, live, result, migrations_dir)
            print()
            print(_rule("="))
            print(f"{'ROLLED BACK' if direction == 'ROLLBACK' else 'APPLIED'} {table}")
            print(_rule("="))
            if direction == "ROLLBACK":
                print(f"  restored      : {result.get('restored')}")
                print(f"  verified hash : {result.get('verified_hash')}")
                print(f"    (restore_table re-read the table and asserted this equals the hash of")
                print(f"     the narrow TableInput it wrote: {plan.desired_hash})")
                print(f"  record        : {record}")
            else:
                print(f"  manifest      : {result.get('manifest')}")
                print(f"  backup hash   : {result.get('backup_hash')}")
            print(f"  VersionId     : {before_version}  ->  {after.get('VersionId')}")
            print(f"  UpdateTime    : {live.get('UpdateTime')}  ->  {after.get('UpdateTime')}")
            print("  column types now:")
            bad = []
            for name, frm, to in changes:
                got = after_types.get(name)
                ok = "OK" if got == to else "MISMATCH"
                if got != to:
                    bad.append((name, to, got))
                print(f"    {name:<24} {frm:<10} -> {got:<10} [{ok}]")
            # Compare the MANAGED parameter set: Glue may rewrite transient_lastDdlTime on any
            # update_table, and a cosmetic key must never send the owner to a rollback.
            # catalog._NOISE_TABLE_PARAMS is the estate's own definition of that noise -- the same
            # one catalog.hash_table and CatalogMigrator.plan_table use.
            pa, pb = _managed_params(live), _managed_params(after)
            ra = json.dumps(live.get("Parameters"), sort_keys=True, default=str)
            rb = json.dumps(after.get("Parameters"), sort_keys=True, default=str)
            ka = json.dumps(live.get("PartitionKeys"), sort_keys=True, default=str)
            kb = json.dumps(after.get("PartitionKeys"), sort_keys=True, default=str)
            print(f"  Parameters preserved (managed set)  : {'YES' if pa == pb else 'NO'}")
            if pa != pb:
                print(f"    before: {pa}")
                print(f"    after : {pb}")
            elif ra != rb:
                print("    (AWS-generated keys moved -- noise, not operator intent:")
                print(f"     before: {ra}")
                print(f"     after : {rb})")
            print(f"  PartitionKeys preserved after apply : {'YES' if ka == kb else 'NO'}")
            if bad or pa != pb or ka != kb:
                print()
                print("POST-APPLY VERIFICATION FAILED.")
                if direction == "ROLLBACK":
                    print("  The ROLLBACK itself did not verify. Do NOT run the post-apply steps.")
                    print("  Re-read the table and compare against the record written above:")
                    print(f"  python scripts/ops/pinned_writer_widening_runbook.py --table {table}")
                else:
                    print("  Roll back now:")
                    print(f"  python scripts/ops/pinned_writer_widening_runbook.py --table {table} "
                          "--rollback")
                return 3
    finally:
        lease.release()
        print()
        print(f"  lease RELEASED s3://{bucket}/{lease.key}")

    if direction == "ROLLBACK":
        print_post_rollback_steps(list(_MUTATED))
    else:
        print_post_apply_steps(list(_MUTATED))
    return 0


def verify_read(tables: list[str], *, region: str, database: str, client=None, runner=None) -> int:
    """Prove the EXISTING objects are readable under the current catalog. One bounded query each.

    NOTE: this deliberately builds a plain athena client. It must NEVER call
    jobs/utils/athena_utils.ensure_catalog(), which DROPS AND RECREATES tables.

    ``client`` / ``runner`` are injection seams for the deck (the zero-row fail-closed branch is
    the one behaviour here that must be tested, and it cannot be tested against live Athena from a
    read-only lane). Left None, this builds the real boto3 client and uses the real run_query."""
    import boto3
    run_query = runner
    if run_query is None:
        sys.path.insert(0, str(_REPO / "jobs" / "utils"))
        from athena_utils import run_query  # noqa: E402  (library call only; no ensure_catalog)

    if client is None:
        client = boto3.client("athena", region_name=region)
    wg = client.get_work_group(WorkGroup="primary")["WorkGroup"]
    engine = (wg.get("Configuration") or {}).get("EngineVersion") or {}
    print(f"  workgroup primary EngineVersion: {json.dumps(engine, sort_keys=True)}")
    rc = 0
    for table in tables:
        sql = VERIFY_SQL[table]
        print()
        print(_rule("="))
        print(f"VERIFY READ {table}")
        print(_rule("="))
        print(f"  SQL: {sql}")
        try:
            rows = run_query(client, sql, database=database)
        except Exception as exc:  # noqa: BLE001 -- the failure IS the result
            print(f"  FAILED: {exc}")
            print("  The existing objects do NOT read under the widened catalog. ROLL BACK:")
            print(f"  python scripts/ops/pinned_writer_widening_runbook.py --table {table} "
                  "--rollback")
            rc = 3
            continue
        if not rows:
            # FAIL CLOSED. Under partition projection a partition that does not exist returns zero
            # rows WITHOUT reading a parquet byte, so an empty result proves nothing about
            # readability -- which is the one thing this probe exists to prove. (MEASURED
            # 2026-09-09: the chosen fgis probe partition
            # s3://leviathan-dev-shahem-001/silver/fgis/leviathan_slug=corn_cbot/marketing_year=2024/
            # holds exactly one part-000.parquet, so 0 rows here means something is wrong.)
            print("  FAILED: 0 rows. An empty result does NOT prove the objects read -- a missing")
            print("  projected partition returns 0 rows without touching a parquet file. Treat this")
            print("  as a failure: check the probe partition still holds objects, and if the")
            print("  catalog was just widened, ROLL BACK:")
            print(f"  python scripts/ops/pinned_writer_widening_runbook.py --table {table} "
                  "--rollback")
            rc = 3
            continue
        print(f"  OK -- {len(rows)} row(s) returned; the existing narrow objects read.")
        for r in rows[:5]:
            print(f"    {json.dumps(r, sort_keys=True, default=str)[:200]}")
    return rc


# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="SILVER-F062 pinned-writer catalog widening -- dry-run by default")
    ap.add_argument("--table", default="all", choices=list(TABLES) + ["all"])
    ap.add_argument("--dry-run", action="store_true",
                    help="the default; also FORCES plan-only when combined with --apply/--rollback "
                         "(the way to preview the reverse plan)")
    ap.add_argument("--apply", action="store_true", help="OWNER: apply the widen (mutates Glue)")
    ap.add_argument("--rollback", action="store_true",
                    help="OWNER: apply the REVERSE plan (wide -> narrow)")
    ap.add_argument("--verify-read", action="store_true", dest="verify_read",
                    help="run the bounded read probe against the CURRENT catalog")
    ap.add_argument("--offline", action="store_true",
                    help="dry-run against the tracked R0 _raw sidecars instead of live Glue")
    ap.add_argument("--offline-dir", default=None, dest="offline_dir",
                    help="with --offline: read <dir>/<table>.get-table.json instead of the tracked "
                         "R0 sidecars. A DRY-RUN SOURCE ONLY (it cannot back a mutation) -- it "
                         "exists so the reverse plan can be exercised against a simulated "
                         "post-apply WIDE catalog without touching AWS")
    ap.add_argument("--database", default=DATABASE)
    ap.add_argument("--region", default=REGION)
    ap.add_argument("--lease-bucket", default=BUCKET, dest="lease_bucket")
    ap.add_argument("--lease-prefix", default=LEASE_PREFIX, dest="lease_prefix")
    ap.add_argument("--lease-id", default=LEASE_ID, dest="lease_id")
    args = ap.parse_args(argv)

    tables = list(TABLES) if args.table == "all" else [args.table]
    # --dry-run always wins: it is how an operator previews the REVERSE plan without mutating.
    mutating = (args.apply or args.rollback) and not args.dry_run
    if args.apply and args.rollback:
        print("REFUSED: --apply and --rollback are mutually exclusive.")
        return 2
    if mutating and args.offline:
        print("REFUSED: --offline is a dry-run source; it cannot back a mutation.")
        return 2

    try:
        if args.verify_read:
            return verify_read(tables, region=args.region, database=args.database)
        if mutating:
            return apply(tables, region=args.region, database=args.database,
                         bucket=args.lease_bucket, lease_prefix=args.lease_prefix,
                         lease_id=args.lease_id,
                         direction="ROLLBACK" if args.rollback else "WIDEN")
        return dry_run(tables, offline=args.offline, region=args.region, database=args.database,
                       direction="ROLLBACK" if args.rollback else "WIDEN",
                       offline_dir=Path(args.offline_dir) if args.offline_dir else None)
    except Refused as exc:
        print()
        print(_mutation_status("REFUSED"))
        print(f"  {exc}")
        return 2
    except Exception as exc:  # noqa: BLE001
        print()
        print(f"ERROR ({type(exc).__name__}) -- see above.")
        print(f"  {_mutation_status('ERROR')}")
        print(f"  {exc}")
        return 4


def _mutation_status(prefix: str) -> str:
    """Never tell an owner 'nothing was mutated' when something was. With ``--table all`` the second
    table's mutation can fail after the first has already landed."""
    if not _MUTATED:
        return f"{prefix} -- nothing was mutated by this runbook."
    return (f"{prefix} -- BUT {len(_MUTATED)} table(s) WERE ALREADY MUTATED by this run: "
            f"{', '.join(_MUTATED)}. The catalog is now HALF-MOVED. Re-read each table "
            "(a bare dry-run does that and refuses if the types are not what it expects) before "
            "deciding whether to continue or to roll the mutated table(s) back.")


if __name__ == "__main__":
    sys.exit(main())
