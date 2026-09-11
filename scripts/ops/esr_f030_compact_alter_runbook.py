#!/usr/bin/env python
"""SILVER-F030 BF-W2 -- THE silver_esr_compact ADD COLUMNS, applied and accounted for.

    python scripts/ops/esr_f030_compact_alter_runbook.py                  # dry run (live Glue)
    python scripts/ops/esr_f030_compact_alter_runbook.py --offline        # dry run, AWS-free
    python scripts/ops/esr_f030_compact_alter_runbook.py --apply          # OWNER: the ALTER
    python scripts/ops/esr_f030_compact_alter_runbook.py --verify-read    # one bounded SELECT
    python scripts/ops/esr_f030_compact_alter_runbook.py --rollback       # OWNER: drop the five
    python scripts/ops/esr_f030_compact_alter_runbook.py --record-applied # reconstruct the record

DRY RUN BY DEFAULT.  With no flag this reads live Glue (or, with ``--offline``, a TRACKED
snapshot) and PRINTS the plan and the before/after column list.  Nothing mutates unless ``--apply``
or ``--rollback`` is passed, and both of those are the OWNER's: they take an S3 lease, re-read
live, and refuse on any precondition.

WHAT THIS APPLIES, AND WHAT IT REFUSES TO APPLY
-----------------------------------------------
``sql/athena/migrations/silver/silver_esr_f030_additive.sql`` carries TWO ``ALTER TABLE ... ADD
COLUMNS`` statements and they do NOT share a fate.  This runbook applies the ``silver_esr_compact``
half ONLY -- the five FAS net-commitment fields, at the TAIL, after ``source``, in this order:

    accumulated_exports_1000mt          double
    current_my_net_sales_1000mt         double
    current_my_total_commitment_1000mt  double
    next_my_outstanding_sales_1000mt    double
    next_my_net_sales_1000mt            double

``silver_esr`` is a HARD-CODED REFUSAL here, with the migration file's own reasons quoted back (it
is a written refusal, not a backlog item: no writer on any schedule, 370 registered partition
descriptors with nothing to self-heal them, and a measured all-NaN census that no floor override
can rescue).  Naming it in ``--table`` exits 2 and prints those reasons.

THE PRECONDITION, AND THE MEASUREMENT THAT DISCHARGES IT
--------------------------------------------------------
``PartitionPublisher.publish_one`` builds every partition's DESIRED StorageDescriptor by COPYING
the TABLE SD (``partition_publish.py:205`` ``_partition_input`` -> ``_sd()``; used at
``partition_publish.py:246``).  The instant this ALTER widens the table from 12 to 17 columns,
EVERY registered partition diffs -- MEASURED 2026-09-10: 243 registered partitions, all 243 at
12 columns.  Without ``reconcile_schema_widen=True`` on the RUNNING producer image, ``publish_one``
calls ``_fail`` and the canonical run exits 1 for the whole family, not just the new columns.

MEASURED, by reading the producer at the commit the running image was built from:
``git show fbe6a7cb:jobs/batch/bronze_to_silver_esr_task.py`` line 317 -- inside
``publish_esr_compact`` (line 273) -- passes ``reconcile_schema_widen=True``.  fbe6a7cb contains
lane C 6fcce483 (``git merge-base --is-ancestor`` = true), which is the commit that introduced the
flag.  The self-heal it enables is narrow by construction: ``catalog.is_schema_widen``
(``catalog.py:135``) admits ONLY a pure TRAILING-column append at an identical
location/format/SerDe, which is why the five must be the LAST five columns and why this runbook
refuses any other placement.

WHY THIS IS NOT ``pinned_writer_widening_runbook.py --table silver_esr_compact``
-------------------------------------------------------------------------------
That runbook is the machinery this one is built from -- the live-TableInput doctrine
(``migrate.raw_snapshot_to_table_input``), the shape fence, the lease, ``CatalogMigrator``, the
post-failure re-read, the exit codes -- but it cannot carry this migration, for three structural
reasons, each of which is a line of its code:

  * IT IS AN APPEND, NOT A RETYPE.  That runbook's ``assert_shape_preserved`` refuses any plan in
    which "column NAMES or ORDER would change" -- which is exactly what ADD COLUMNS does.  The
    fence here keeps the leading 12 columns byte-identical and admits ONLY a tail append.
  * THE REVERSE IS A DROP, NOT A NARROW.  ``CatalogMigrator._unsafe_diffs`` answers a reverse plan
    here with five ``DROP column '<name>' (refused)`` entries, not ``NARROW`` ones, so the bounded
    override is a different list.
  * THE TABLE IS REGISTERED-PARTITION.  Its two tables are projected/flat, so their
    ``registered_partition_audit`` comes back ``{"registered": False}``.  Here it comes back
    ``registered: True`` with the table-SD diff, and the 243 partition descriptors are part of the
    plan the owner must read -- they are repaired by the next canonical promote, not by this run.

THE TWO MUTATING PATHS ARE NOT THE SAME CALL, AND THAT IS THE WHOLE POINT
------------------------------------------------------------------------
``--apply`` (12 -> 17) is ADDITIVE: no drop, no partition-key change, no narrowing, so
``CatalogMigrator._unsafe_diffs`` returns ``[]`` and the plan goes through
``CatalogMigrator.apply_table`` -- the F012 path, with its live-hash re-check, lease fence, backup
and machine manifest.

``--rollback`` (17 -> 12) DROPS five columns, and ``apply_table`` refuses every drop on principle
(``UnsafeMigration``).  Routing the reverse plan through it would be a DEAD command: it refuses,
nothing is restored, and the rollback this file advertises would not exist.  The sanctioned detour
is ``CatalogMigrator.restore_table`` (the same detour ``leviathan.silver.types`` names in its own
comment for B2's F036 int->bigint).  So ``--rollback`` RESTORES a TableInput through
``restore_table``, and the override it represents is BOUNDED: the run refuses unless the unsafe
list is EXACTLY the five expected ``DROP column ...`` entries for exactly these five columns -- a
sixth drop, a partition-key change or a narrowing of any other column still stops the run.  The
restore basis is not a tracked snapshot but the LIVE table with only the five tail columns removed,
so unrelated catalog drift is never reverted, and ``restore_table`` refuses if the live hash moved
since the plan was cut and verifies the post-restore hash itself.

WHAT ``--offline`` READS: A PRECEDENCE, NOT A FILE
--------------------------------------------------
The estate's usual AWS-free source is ``reports/silver_readiness/20260712_p65impl/_raw/<table>
.get-table.json``.  For THIS table that sidecar is STALE and this runbook refuses to plan from it.
MEASURED 2026-09-10: the sidecar carries 13 columns (``as_of_date`` is still an in-file column) and
ONE partition key (``commodity``); live carries 12 columns and TWO partition keys (``commodity``,
``as_of_date``) -- the sidecar predates the SILVER-F031 option-b as_of_date dimension, and
``run_census``'s own recipe-v1 digest reads 669fa230... on it against 10e9e4be... on live.

Neither is the R0 RECORD ``reports/silver_readiness/20260712_p65impl/tables/
silver_esr_compact.json`` the answer on its own, and until 2026-09-11 this file called it "the
TRACKED file that IS live".  IT WAS NEVER TRACKED: ``.gitignore`` carries a
``reports/silver_readiness/`` rule and ``git ls-files`` returns nothing under it, so a fresh clone
has no copy.  THE RULE IS CITED, NEVER ITS LINE NUMBER -- MEASURED 2026-09-11, that same rule sat
at ``.gitignore`` line 77 at HEAD and line 91 in the working tree (a concurrent lane inserted
fourteen lines above it within the hour), so a pinned line number is a fact that rots silently
while a rule name stays true.  ``git check-ignore`` is the measurement, and the deck makes it.
Worse, it is a LIVING file -- this runbook's own post-apply step [2] RE-CAPTURES it -- so once the
ALTER landed (2026-09-10) it became the 17-column POST-ALTER shape, minted under ``run_census``
recipe v2, and a runbook that read it as its narrow baseline under recipe v1 refused every offline
mode it had.

So the offline source is a STATED PRECEDENCE over two halves of one file, resolved at run time by
``narrow_basis`` (the PRE-ALTER table) and ``offline_table`` (the CURRENT catalog):

  1. THE MACHINE MANIFEST ``sql/athena/migrations/silver/<UTC>_silver_esr_compact_additive_update
     .json``, which ``CatalogMigrator`` wrote INSIDE the mutation and which ``sql/`` tracks.  Its
     ``backup.table_input`` is the pre-apply ``glue.get_table`` snapshot (12 columns, both
     partition keys) and its ``plan.table_input`` is the executable POST-ALTER TableInput
     ``glue.update_table`` was handed.  Each carries its own catalog digest and is re-certified
     against BOTH that digest and this runbook's pinned live measurement -- MEASURED 2026-09-11:
     ``backup.catalog_hash`` = c1cfd5e8... = ``MEASURED['live_catalog_hash']`` and
     ``plan.desired_hash`` = 70294ffa... = ``catalog.hash_table`` of LIVE GLUE today.  Written
     once, never re-captured: it cannot go stale the way the R0 record did.
     A RECONSTRUCTED MANIFEST CARRIES NO PLAN, and that is not a defect in it: ``--record-applied``
     never cut one, so ``write_applied_manifest`` stores ``plan: null`` and a self-certifying
     ``post_apply.table_input`` + ``post_apply.catalog_hash`` instead.  ``offline_table`` therefore
     reads ``plan`` first and ``post_apply`` second -- ABSENCE falls through, non-certification
     still refuses -- because otherwise running this runbook's own repair mode would turn
     ``--offline`` into a permanent exit 2.  That shape is on this tree already: MEASURED
     2026-09-11, the sibling ``20260910T060216Z_silver_fgis_additive_update.json`` has
     ``reconstructed: true``, ``plan: null``, and a ``post_apply`` that re-hashes exactly.
  2. OTHERWISE the R0 record -- the correct narrow basis only BEFORE the ALTER lands.  Its digest
     is re-verified under THE RECIPE IT STAMPS (``glue.hash_recipe``: absent = the ghost tool's v1,
     ``2`` = ``run_census.hash_block``), which is ``run_census.check_one``'s own selection.

A source that does not certify itself is a refusal, not a warning.  ``--offline-dir DIR`` reads
``DIR/silver_esr_compact.get-table.json`` instead, and exists so a simulated catalog can be
previewed without touching AWS.

THE NARROW BASIS IS A get_table SNAPSHOT, NOT A TableInput.  ``backup.table_input`` is a RAW
``get_table`` blob and still carries the nine read-only fields Glue REJECTS on input (``CatalogId``,
``CreateTime``, ``CreatedBy``, ``DatabaseName``, ``UpdateTime``, ``VersionId``,
``IsRegisteredWithLakeFormation`` and the two view flags -- measured on the sibling modis lane).
It reaches a TableInput only through ``migrate.raw_snapshot_to_table_input`` (the migrator's OWN
drop list; this file never carries a second copy of it) or through
``CatalogMigrator.restore_table``, which applies the same helper.  Handing that blob straight to
``glue.update_table`` would fail.

WHAT THE READ PROBE PROVES, AND WHAT IT CANNOT
----------------------------------------------
``--verify-read`` runs ONE bounded, partition-filtered SELECT of the five columns on the newest
canonical partition.  It proves the EXISTING objects still read under the widened catalog.  It does
NOT prove the five are populated, and it must not be read that way -- in EITHER direction.

This file predicted all-NULL, on the reasoning that Athena resolves a registered partition's
columns from the PARTITION descriptor and every one of the 243 still says 12 columns until the next
canonical promote repairs them.  The first half is still true -- MEASURED 2026-09-11 by
``glue.get_partitions``: 243 of 243 at 12 columns, the probe partition included.  THE PREDICTION IS
NOT: MEASURED 2026-09-10, ``--verify-read`` returned 5 rows with ALL FIVE NON-NULL over that
12-column descriptor.  So a non-NULL sample does not prove the promote has run, and an all-NULL one
would not prove it has not; the descriptor count is partition work still owed, never a verdict on
what a SELECT returns.  Zero ROWS remains a failure -- the probe partition was measured to hold an
object.

EXIT CODES
----------
    0  the plan printed / the apply verified / the table was already wide and was skipped /
       the applied record was reconstructed
    2  REFUSED on a precondition (the live shape is neither the measured 12-column one nor the
       17-column target; Parameters or PartitionKeys would move; an unsafe diff beyond the bounded
       reverse set; the registry leads live Glue -- forwards OR, on a --rollback, backwards;
       --apply combined with --offline; silver_esr named; --record-applied on a table that is not
       wide, or that already has an applied manifest; and, on the offline paths, a SOURCE THAT
       DOES NOT CERTIFY ITSELF -- a manifest half whose recomputed catalog.hash_table does not
       match the digest stored beside it or this runbook's pinned live measurement, an R0 record
       whose digest does not verify under the recipe it stamps or that stamps a recipe this
       runbook cannot recompute, or a narrow basis that is not the measured 12-column shape)
    3  applied but POST-APPLY VERIFICATION FAILED (the re-read does not show the 17 columns), or
       --verify-read failed / returned no rows, or --record-applied wrote the record but could not
       certify the pre-apply backup
    4  an AWS / lease error.  The handler RE-READS the table from live Glue and names what actually
       moved -- an exception can escape AFTER update_table has already returned (MEASURED
       2026-09-10 04:07Z on the sibling runbook: the manifest writer raised on a datetime and the
       owner was told nothing was mutated while the catalog had moved).

Commands printed for the operator are WINDOWS POWERSHELL 5.1: chained with ``;``, never with
``&&`` (a parser error in 5.1).  Stdout is ASCII only (the console is cp1252).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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
LEASE_ID = "catalog-migration"          # the SAME lock the sibling catalog runbook takes
TABLE = "silver_esr_compact"
REFUSED_TABLE = "silver_esr"

R0_BASELINE = _REPO / "reports" / "silver_readiness" / "20260712_p65impl"
R0_RECORD = R0_BASELINE / "tables" / f"{TABLE}.json"
R0_RAW = R0_BASELINE / "_raw"
MIGRATIONS_DIR = _REPO / "sql" / "athena" / "migrations" / "silver"
MIGRATION_SQL = MIGRATIONS_DIR / "silver_esr_f030_additive.sql"
CENSUS_SCRIPT = _REPO / "scripts" / "silver" / "run_census.py"

# The INV-2 target arrow type -> the Glue/Athena spelling. Kept local and tiny on purpose: an
# unmapped target must fail this runbook, never be assumed safe.
_ARROW_TO_GLUE = {"float64": "double"}

# THE FIVE, PINNED, IN THE CONTRACT'S TAIL ORDER -- which is the migration file's order and the
# only order catalog.is_schema_widen can self-heal. ``five_from_registry`` re-derives this from the
# contract at every run, so the runbook and the registry cannot drift apart in silence.
FIVE = (
    ("accumulated_exports_1000mt", "double"),
    ("current_my_net_sales_1000mt", "double"),
    ("current_my_total_commitment_1000mt", "double"),
    ("next_my_outstanding_sales_1000mt", "double"),
    ("next_my_net_sales_1000mt", "double"),
)
FIVE_NAMES = tuple(n for n, _ in FIVE)
ANCHOR_COLUMN = "source"                # the five append AFTER this one, and it is the live tail

# THE PRE-ALTER TABLE, MEASURED 2026-09-10 by glue.get_table against leviathan_dev (VersionId 1,
# UpdateTime 2026-07-15T02:58:03+03:00). Column ORDER is significant.
NARROW_COLUMNS = (
    ("commodity_code", "smallint"),
    ("commodity_name", "string"),
    ("market_year", "smallint"),
    ("country_code", "smallint"),
    ("week_ending_date", "date"),
    ("outstanding_sales_1000mt", "float"),
    ("weekly_exports_1000mt", "float"),
    ("gross_new_sales_1000mt", "float"),
    ("changes_1000mt", "float"),
    ("source_unit_id", "smallint"),
    ("ingest_date", "string"),
    ("source", "string"),
)
NARROW_NAMES = tuple(n for n, _ in NARROW_COLUMNS)
PARTITION_KEYS = (("commodity", "string"), ("as_of_date", "string"))

# Every number here was measured on 2026-09-10 and the line says how. They are printed, not
# trusted: the run re-reads live Glue and refuses if what it finds is not this.
MEASURED = {
    "live_columns": 12,
    "live_version_id": "1",
    "live_update_time": "2026-07-15T02:58:03+03:00",
    "live_catalog_hash": "c1cfd5e87d4ba821b55e308dc01185b88c26329bc0a84c9487dd1587b18d8abd",
    "live_catalog_hash_v1": "10e9e4be31fcefec1d4654688c1cb0a10870bf11593af776c6c92d3ddae340b8",
    "r0_sidecar_catalog_hash_v1":
        "669fa230f9d31539906b92a9b967d21b97cede78ecc39c5944a8b3da19d80ea3",
    "r0_sidecar_columns": 13,
    "registered_partitions": 243,
    "registered_partitions_at_12_columns": 243,
    # THE POST-ALTER SIDE, MEASURED 2026-09-11 by glue.get_table (read-only) after the 2026-09-10
    # ALTER landed. The offline path is certified against these: a manifest whose plan half does
    # not hash to live_catalog_hash_post_alter is not the table this runbook is talking about.
    "measured_post_alter_on": "2026-09-11",
    "live_columns_post_alter": 17,
    "live_version_id_post_alter": "2",
    "live_update_time_post_alter": "2026-09-10T20:00:43+03:00",
    "live_catalog_hash_post_alter":
        "70294ffacf556b5bad9c7aab4543e12d7123b7bf282ef38988a6dfd3b5457d3f",
    # MEASURED 2026-09-11 by glue.get_partitions over every registered partition, AFTER the ALTER:
    # the table descriptor is 17 columns and all 243 partition descriptors are still 12.
    "registered_partitions_at_12_columns_post_alter": 243,
    # MEASURED 2026-09-10 by --verify-read on commodity=white_wheat / as_of_date=20260910, whose
    # partition descriptor was MEASURED 2026-09-11 to be one of those 243 twelve-column ones.
    # This is the measurement that falsified this runbook's all-NULL prediction.
    "verify_read_rows": 5,
    "verify_read_non_null_of_five": 5,
    "newest_object": ("s3://leviathan-dev-shahem-001/silver/esr/commodity=white_wheat/"
                      "as_of=20260910/part-000.parquet"),
    "newest_object_bytes": 33315,
    "newest_object_written": "2026-09-10T14:24:33Z",
    "producer_flag_commit": "fbe6a7cb",
    "producer_flag_file": "jobs/batch/bronze_to_silver_esr_task.py",
    "producer_flag_line": 317,
    "producer_flag_func_line": 273,
    "lane_c_commit": "6fcce483",
}

# The bounded read probe: the NEWEST canonical partition, measured 2026-09-10 to hold exactly one
# 33,315-byte part-000.parquet written by the 14:00Z promote. Partition-filtered, LIMIT 5.
PROBE_COMMODITY = "white_wheat"
PROBE_AS_OF = "20260910"
VERIFY_SQL = (
    "SELECT week_ending_date, " + ", ".join(FIVE_NAMES) + " "
    f"FROM {DATABASE}.{TABLE} "
    f"WHERE commodity = '{PROBE_COMMODITY}' AND as_of_date = '{PROBE_AS_OF}' LIMIT 5"
)

# The producing family's schedule -- the reason the ALTER is ordered rather than optional.
PROMOTE_FAMILY = ("esr_weekly", "cron(0 14 ? * THU *)")


class Refused(RuntimeError):
    """A precondition failed. Nothing was mutated (exit 2)."""


# Set iff this process is KNOWN to have moved the catalog -- either because the loop recorded it or
# because the post-failure RE-READ proved it. Being in here is a statement about the catalog, never
# about which line of this file ran.
_MUTATED: list[str] = []
_VERDICTS: list[dict] = []

APPLIED = "APPLIED"
NOT_APPLIED = "NOT APPLIED"
UNKNOWN = "UNKNOWN"

AT_SOURCE = "AT_SOURCE"          # 12 columns, the five absent -- the work is still to do
AT_TARGET = "AT_TARGET"          # 17 columns, the five at the tail as double -- already done
MIXED = "MIXED"                  # some third state -- the only shape that is a refusal

STAGED_HIDDEN = "STAGED_HIDDEN"  # the contract stages the five physical-only (pre-flip)
REGISTERED = "REGISTERED"        # the contract declares them double (the step-4 flip has landed)


# ---------------------------------------------------------------------------
# small shared readers
# ---------------------------------------------------------------------------
def _census_module():
    """``scripts/silver/run_census.py`` loaded by path -- for ``catalog_hash_v1`` and
    ``_record_glue_to_raw_shape``, the estate's OWN recipe for the digest the R0 record carries.
    Re-implementing that recipe here would be the drift this import exists to avoid. The module
    makes no AWS call at import time."""
    spec = importlib.util.spec_from_file_location("_esr_f030_run_census", CENSUS_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _columns(table: dict) -> list[dict]:
    return list((table.get("StorageDescriptor") or {}).get("Columns") or [])


def _column_names(table: dict) -> list[str]:
    return [c.get("Name") for c in _columns(table)]


def _column_types(table: dict) -> dict:
    """{column name -> lower-cased Glue type} for the non-partition columns of a get_table Table."""
    return {c.get("Name"): str(c.get("Type") or "").strip().lower() for c in _columns(table)}


def _iso(value) -> Optional[str]:
    """A Glue time field as a string. boto3 hands CreateTime/UpdateTime/LastAccessTime back as
    ``datetime``; the tracked records carry the same fields already stringified."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _managed_params(table: dict) -> str:
    """The table's Parameters with the AWS-generated noise keys stripped, as a stable string.

    ``transient_lastDdlTime`` and friends are rewritten by Glue itself on an update_table; comparing
    RAW Parameters would turn that cosmetic rewrite into a failed post-apply check and send the
    owner to a rollback for nothing. ``catalog._NOISE_TABLE_PARAMS`` is the estate's own definition
    of that noise -- the same set ``catalog.hash_table`` uses."""
    return json.dumps(catalog._clean_params(table.get("Parameters"), catalog._NOISE_TABLE_PARAMS),
                      sort_keys=True, default=str)


def _rule(ch: str = "-") -> str:
    return ch * 78


def _repo_rel(path) -> str:
    """A repo-relative POSIX path where the file IS under the repo, the plain path otherwise.

    ``Path.relative_to`` RAISES on a path outside the repo, and the basis paths are module
    constants a caller may point elsewhere (the deck does, at a synthesized record). A provenance
    string is not worth an exception, and a naming helper that can only handle one location is how
    a path claim goes stale."""
    try:
        return str(Path(path).resolve().relative_to(_REPO)).replace("\\", "/")
    except (ValueError, OSError):
        return str(path).replace("\\", "/")


# ---------------------------------------------------------------------------
# THE silver_esr REFUSAL -- quoted from the migration file, never paraphrased
# ---------------------------------------------------------------------------
def silver_esr_refusal_reasons() -> list[str]:
    """The migration file's OWN words about the ``silver_esr`` half, read at run time.

    Quoting beats paraphrasing here for a reason that is not style: if the refusal is ever lifted,
    it is lifted in that file, and a copy in this script would keep printing a decision that had
    been reversed."""
    if not MIGRATION_SQL.exists():
        return [f"(the migration file is missing: {MIGRATION_SQL})",
                "silver_esr: SPECIFIED, NOT APPLIED, and DELIBERATELY NOT SCHEDULED (2026-09-04)."]
    lines = MIGRATION_SQL.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    grabbing = False
    for line in lines:
        text = line[3:] if line.startswith("-- ") else ("" if line.strip() == "--" else line)
        if "silver_esr         : SPECIFIED, NOT APPLIED" in line:
            grabbing = True
        if grabbing:
            out.append(text.rstrip())
            if "refresh reports/silver_readiness" in line:
                break
    return out or ["(the migration file no longer carries the silver_esr refusal block)"]


def assert_table_allowed(table: str) -> None:
    """``silver_esr`` is a HARD-CODED refusal, and every mode routes through here."""
    if table == TABLE:
        return
    if table == REFUSED_TABLE:
        quoted = "\n".join("    | " + line for line in silver_esr_refusal_reasons())
        raise Refused(
            f"{REFUSED_TABLE} is NEVER touched by this runbook.\n"
            f"  The migration file states the refusal and its reasons; quoted from\n"
            f"  sql/athena/migrations/silver/silver_esr_f030_additive.sql:\n\n{quoted}\n\n"
            "  This runbook applies the silver_esr_compact half ONLY. If that decision is ever\n"
            "  reversed, it is reversed in the migration file first -- not by an argument here.")
    raise Refused(f"{table!r} is not a table this runbook knows. It applies exactly one migration: "
                  f"the {TABLE} half of silver_esr_f030_additive.sql.")


# ---------------------------------------------------------------------------
# the five, re-derived from the registry so they cannot drift
# ---------------------------------------------------------------------------
def five_from_registry() -> tuple[str, list[tuple[str, str]]]:
    """``(state, [(column, glue type)])`` for the five, read from the F010 contract.

    ``STAGED_HIDDEN`` (``glue_type: null``) is the pre-ALTER state -- the writer emits the column,
    the catalog has not registered it. ``REGISTERED`` (``glue_type: double``) means the step-4
    registry flip has already landed, which is only legal AFTER the ALTER: the registry never leads
    live Glue. A mixture of the two is a refusal, not a state."""
    contract = load_registry().table(TABLE)
    cols = {c["name"]: c for c in contract.get("physical_columns") or []}
    names = [c["name"] for c in contract.get("physical_columns") or []]
    if tuple(names[-5:]) != FIVE_NAMES or names[-6] != ANCHOR_COLUMN:
        raise Refused(
            f"{TABLE}: the contract's TAIL moved -- the five must be the last five physical "
            f"columns, after {ANCHOR_COLUMN!r}.\n"
            f"  contract tail: {names[-6:]}\n"
            f"  expected     : {[ANCHOR_COLUMN] + list(FIVE_NAMES)}\n"
            "  catalog.is_schema_widen admits ONLY a pure trailing append, so a mid-list column "
            "would strand every registered partition descriptor.")
    hidden, registered, derived = [], [], []
    for name, want in FIVE:
        col = cols.get(name)
        if col is None:
            raise Refused(f"{TABLE}: the contract no longer carries {name!r} -- re-measure before "
                          "applying anything.")
        target = str(col.get("target_arrow_type") or "").strip().lower()
        if target not in _ARROW_TO_GLUE:
            raise Refused(f"{TABLE}.{name}: target_arrow_type {target!r} has no Glue spelling in "
                          "this runbook -- refusing rather than assuming one.")
        if _ARROW_TO_GLUE[target] != want:
            raise Refused(f"{TABLE}.{name}: the contract targets {_ARROW_TO_GLUE[target]!r}, this "
                          f"runbook pins {want!r} -- re-measure.")
        glue = str(col.get("glue_type") or "").strip().lower()
        (registered if glue else hidden).append(name)
        if glue and glue != want:
            raise Refused(f"{TABLE}.{name}: the contract declares glue_type {glue!r}, not "
                          f"{want!r}.")
        derived.append((name, want))
    if hidden and registered:
        raise Refused(
            f"{TABLE}: the contract is HALF-FLIPPED -- {sorted(registered)} declare a glue_type "
            f"and {sorted(hidden)} do not. The step-4 flip promotes all five in one edit; a "
            "half-flip is a hand edit, and this runbook will not plan against one.")
    return (REGISTERED if registered else STAGED_HIDDEN), derived


# ---------------------------------------------------------------------------
# live / offline table access
# ---------------------------------------------------------------------------
def _glue_client(region: str):
    import boto3
    return boto3.client("glue", region_name=region)


# THE OFFLINE PRECEDENCE, STATED ONCE. Both entries are read-only, and every mode that needs a
# pre-ALTER table resolves through it (``narrow_basis``) rather than naming a file of its own.
# WHERE IT IS PRINTED, EXACTLY (this comment said "printed wherever a basis is used", which was an
# overclaim in a lane whose subject is overclaims -- corrected 2026-09-11): the FULL two-rung list
# is printed by --record-applied, the one mode that has to justify a reconstructed backup; every
# other mode prints the RESOLVED source line instead -- the file, the half, the certifying field
# and its re-computed digest -- which is what an owner reading one run needs. A run never leaves
# its basis unnamed; only --record-applied prints the rule that chose it.
NARROW_BASIS_PRECEDENCE = (
    "1. THE MACHINE MANIFEST sql/athena/migrations/silver/<UTC>_silver_esr_compact_"
    "additive_update.json -- backup.table_input, the pre-apply glue.get_table snapshot "
    "CatalogMigrator froze INSIDE the mutation. Written once, never re-captured, and git tracks "
    "sql/. Present only AFTER the ALTER has landed.",
    "2. OTHERWISE the R0 record reports/silver_readiness/20260712_p65impl/tables/"
    "silver_esr_compact.json -- the narrow basis ONLY before the ALTER lands, because this "
    "runbook's own step [2] re-captures it to the POST-ALTER shape (done 2026-09-10). It is also "
    "GITIGNORED (the reports/silver_readiness/ rule in .gitignore), so a fresh clone carries no "
    "copy at all.",
)

# The R0 digest recipes this runbook knows how to RE-COMPUTE. run_census mints v2 today; records
# left by the ghost tool carry no stamp and are v1. An unknown stamp is a refusal, never a guess.
_KNOWN_R0_RECIPES = (1, 2)


def _r0_digest(block: dict, census) -> tuple[int, str, str]:
    """``(recipe, recomputed digest, the name of the field it certifies)`` for an R0 record's own
    catalog digest, UNDER THE RECIPE THE RECORD SAYS IT WAS MINTED WITH.

    ``run_census`` has two generations of recipe and every record states which one it carries;
    ``run_census.check_one`` selects on exactly that stamp -- quoted, scripts/silver/run_census.py
    line 378:

        legacy = "hash_recipe" not in stored.get("glue", {})

    so this does the same. Recomputing a recipe-v2 record under v1 is not a detection, it is a
    FALSE ALARM: MEASURED 2026-09-10, after this runbook's own step [2] re-captured the record,
    a v1 recomputation read 68df4346... against the record's stored v2 cb1a9fdc..., and every
    offline mode of this runbook refused with 'the R0 record does not certify itself'."""
    if census.HASH_RECIPE_VERSION not in _KNOWN_R0_RECIPES:
        raise Refused(
            f"run_census now mints hash recipe v{census.HASH_RECIPE_VERSION}, which this runbook "
            f"has no recomputation for (it knows v{', v'.join(str(r) for r in _KNOWN_R0_RECIPES)})."
            " Teach it the new recipe rather than letting it certify a record under the wrong one.")
    stamp = block.get("hash_recipe")
    v1 = (1, census.catalog_hash_v1(census._record_glue_to_raw_shape(block)),
          "glue.catalog_hash_sha256 (run_census recipe v1, the ghost tool's)")
    if stamp is None:
        return v1
    try:
        recipe = int(stamp)
    except (TypeError, ValueError):
        raise Refused(f"the R0 record stamps glue.hash_recipe {stamp!r}, which is not a recipe "
                      "number -- refusing rather than guessing which recipe minted its digest.")
    if recipe == 1:
        return v1
    if recipe == 2:
        return 2, census.hash_block(block), "glue.catalog_hash_sha256 (run_census recipe v2)"
    raise Refused(f"the R0 record stamps glue.hash_recipe {recipe}, which this runbook has no "
                  f"recomputation for (it knows v{', v'.join(str(r) for r in _KNOWN_R0_RECIPES)}) "
                  "-- refusing rather than assuming one.")


def r0_record_table() -> tuple[dict, dict]:
    """``(table, certification)`` -- the R0 RECORD rebuilt into a ``get_table``-shaped Table, with
    its OWN digest RE-COMPUTED under the recipe it stamps and compared to the field it certifies.

    The record, not the ``_raw`` sidecar: MEASURED 2026-09-10, the sidecar is the PRE-deprojection
    table (13 columns, one partition key) and hashes to something live has not been for two
    months. And the record is the SECOND-precedence basis, not the first -- see
    ``NARROW_BASIS_PRECEDENCE``: it is gitignored, and it is re-captured by this runbook's own
    step [2], so after an apply it is the WIDE state rather than the narrow one."""
    if not R0_RECORD.exists():
        raise Refused(
            f"the R0 record is not on disk: {R0_RECORD}\n"
            "  reports/silver_readiness/ is GITIGNORED (the reports/silver_readiness/ rule in "
            ".gitignore) and git ls-files returns nothing under it,\n"
            "  so a fresh clone carries no R0 record. Re-capture it with\n"
            "    python scripts/silver/run_census.py --table silver_esr_compact\n"
            "  or work from the tracked machine manifest instead (see NARROW_BASIS_PRECEDENCE).")
    record = json.loads(R0_RECORD.read_text(encoding="utf-8"))
    block = record.get("glue") or {}
    census = _census_module()
    table = census._record_glue_to_raw_shape(block)
    table["Name"] = record.get("table", TABLE)
    table["VersionId"] = str(block.get("version_id"))
    table["UpdateTime"] = block.get("update_time")
    table["CreateTime"] = block.get("create_time")
    recipe, got, field = _r0_digest(block, census)
    expected = block.get("catalog_hash_sha256")
    cert = {
        "source": (f"reports/silver_readiness/20260712_p65impl/tables/{TABLE}.json (the R0 record, "
                   f"GITIGNORED), rebuilt through run_census._record_glue_to_raw_shape and "
                   f"re-verified under the recipe it stamps (v{recipe})"),
        "field": field,
        "record": _repo_rel(R0_RECORD),
        "basis": "R0 record",
        "expected": expected, "got": got, "verified": bool(expected) and expected == got,
        "catalog_hash": catalog.hash_table(table),
    }
    if not cert["verified"]:
        raise Refused(
            f"the R0 record does not certify itself: recomputing {cert['field']} over its own glue "
            f"block gives {got} but the record stores {expected}. A snapshot that cannot prove it "
            "is the table it claims to be may not back a plan.")
    return table, cert


def applied_manifest_record(migrations_dir: Optional[Path] = None) -> Optional[tuple[Path, dict]]:
    """``(path, payload)`` of the machine manifest for this table's ADD COLUMNS, or ``None``.

    ``_applied_manifest`` FINDS the file and deliberately returns an unparseable one rather than
    skipping it, so that nothing overwrites a record. A basis, unlike an existence check, has to
    READ it -- so an unparseable manifest is a refusal here."""
    path = _applied_manifest(migrations_dir or MIGRATIONS_DIR)
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:                                                     # noqa: BLE001
        raise Refused(f"the machine manifest {path} does not parse ({type(exc).__name__}: {exc}) "
                      "-- it is the tracked record of this migration, and a plan may not be cut "
                      "from a record that cannot be read.")
    return path, payload


# WHAT EACH HALF OF THE MANIFEST ACTUALLY IS, in the words every refusal and every printed source
# line uses. ``backup`` is a RAW get_table snapshot and is named as one: calling it an "executable
# TableInput" is what this file's own header warns against, because those nine read-only fields are
# still on it and glue.update_table rejects them.
BACKUP_HALF_IS = ("the RAW pre-apply glue.get_table snapshot a rollback restores through "
                  "CatalogMigrator.restore_table, never glue.update_table")
PLAN_HALF_IS = "the executable POST-ALTER TableInput glue.update_table was handed"
POST_APPLY_HALF_IS = ("the POST-ALTER table re-read from live Glue and frozen by --record-applied, "
                      "which a reconstructed record carries INSTEAD of a plan")


def _half_present(payload: dict, *, block: str, key: str) -> bool:
    """Is this half of the manifest THERE at all? Absence and non-certification are different
    answers and get different treatment: absence may fall through to the next source (a manifest
    written by ``--record-applied`` carries no ``plan`` -- MEASURED on the sibling fgis manifest
    ``20260910T060216Z_silver_fgis_additive_update.json``, ``plan: null`` with a ``post_apply``
    beside it), while a half that is present and does NOT certify is always a refusal."""
    body = payload.get(block) or {}
    snap = body.get(key)
    return isinstance(snap, dict) and bool(_columns(snap))


def _manifest_half(path: Path, payload: dict, *, block: str, key: str, hash_key: str,
                   pinned: str, pinned_name: str, what: str) -> tuple[dict, dict]:
    """One half of the machine manifest as a table, RE-CERTIFIED TWICE.

    ``backup`` is the pre-apply table the mutation froze; ``plan`` is the post-apply TableInput it
    handed ``update_table``; ``post_apply`` is the post-ALTER re-read a reconstructed record carries
    INSTEAD of a plan. Each stores its own catalog digest beside it, so the first check is
    SELF-certification -- recompute ``catalog.hash_table`` over the stored table and compare. The
    second is against this runbook's own pinned measurement of that side of live Glue, so a
    hand-edited manifest, or some other migration's manifest, cannot quietly back a plan."""
    body = payload.get(block) or {}
    snap = body.get(key)
    if not isinstance(snap, dict) or not _columns(snap):
        raise Refused(f"the machine manifest {path.name} carries no usable {block}.{key} ({what}) "
                      "-- this runbook will not plan without it.")
    expected = body.get(hash_key)
    got = catalog.hash_table(snap)
    cert = {
        "source": f"sql/athena/migrations/silver/{path.name} ({block}.{key} -- {what})",
        "field": f"{block}.{hash_key} (leviathan.silver.catalog.hash_table)",
        "record": f"sql/athena/migrations/silver/{path.name}",
        "basis": "machine manifest",
        "expected": expected, "got": got, "verified": bool(expected) and expected == got,
        "catalog_hash": got,
    }
    if not cert["verified"]:
        raise Refused(
            f"the machine manifest does not certify its own {block}: recomputing {cert['field']} "
            f"over {block}.{key} gives {got} but the manifest stores {expected}. A snapshot that "
            "cannot prove it is the table it claims to be may not back a plan.")
    if got != pinned:
        raise Refused(
            f"the machine manifest's {block}.{key} ({what}) hashes to {got}, but this runbook pins "
            f"MEASURED[{pinned_name!r}] = {pinned} -- the value measured against LIVE GLUE. The "
            "manifest and the measurement disagree, so at least one of them is not this table. "
            "REFUSED rather than planning from whichever was read first.")
    return snap, cert


def _assert_narrow(table: dict, cert: dict) -> None:
    """A narrow basis must BE the measured 12-column pre-ALTER table, columns and partition keys."""
    got = tuple((c.get("Name"), str(c.get("Type") or "").strip().lower()) for c in _columns(table))
    if got != NARROW_COLUMNS:
        why = ("the R0 record is a LIVING file: this runbook's own step [2] re-captures it to the "
               "POST-ALTER shape once the ALTER lands, which is exactly why the machine manifest "
               "outranks it." if cert.get("basis") == "R0 record" else
               "the machine manifest's backup is written once, by the mutation; a backup that is "
               "not the narrow shape means this is not that mutation's manifest.")
        raise Refused(f"{cert['source']} is not the measured PRE-ALTER shape -- REFUSED.\n"
                      f"  basis   : {[n for n, _ in got]}\n"
                      f"  expected: {list(NARROW_NAMES)}\n  {why}")
    keys = tuple((p.get("Name"), str(p.get("Type") or "").strip().lower())
                 for p in table.get("PartitionKeys") or [])
    if keys != PARTITION_KEYS:
        raise Refused(f"{cert['source']} does not carry the measured partition keys -- REFUSED.\n"
                      f"  basis   : {list(keys)}\n  expected: {list(PARTITION_KEYS)}")


def narrow_basis(migrations_dir: Optional[Path] = None) -> tuple[dict, dict]:
    """``(table, certification)`` -- the PRE-ALTER (12-column) table, from the first source in
    ``NARROW_BASIS_PRECEDENCE`` that exists, with THAT source's own digest re-computed.

    WHAT COMES BACK IS A ``get_table`` SNAPSHOT, NOT A TableInput. Post-apply it is the manifest's
    RAW pre-apply blob, which still carries the nine read-only fields Glue REJECTS on input
    (CatalogId, CreateTime, CreatedBy, DatabaseName, UpdateTime, VersionId,
    IsRegisteredWithLakeFormation and the two view flags). It reaches a TableInput only through
    ``migrate.raw_snapshot_to_table_input`` -- the migrator's OWN drop list, never a second copy of
    it in this file -- or through ``CatalogMigrator.restore_table``, which applies that same helper.
    Handing this blob straight to ``glue.update_table`` would fail."""
    found = applied_manifest_record(migrations_dir)
    if found is not None:
        path, payload = found
        table, cert = _manifest_half(
            path, payload, block="backup", key="table_input", hash_key="catalog_hash",
            pinned=MEASURED["live_catalog_hash"], pinned_name="live_catalog_hash",
            what=BACKUP_HALF_IS)
    else:
        table, cert = r0_record_table()
    _assert_narrow(table, cert)
    return table, cert


def offline_table(migrations_dir: Optional[Path] = None) -> tuple[dict, dict]:
    """``(table, certification)`` -- the AWS-FREE view of the CURRENT catalog.

    SAME PRECEDENCE, OTHER HALF, AND THAT HALF HAS TWO FORMS. Once the ALTER has landed the
    manifest's ``plan.table_input`` IS the catalog: it is the executable TableInput
    ``glue.update_table`` was handed, and MEASURED 2026-09-11 it re-hashes to
    ``catalog.hash_table`` of live Glue. Before it lands there is no manifest, and the R0 record is
    the current (narrow) catalog.

    A RECONSTRUCTED MANIFEST HAS NO PLAN, AND THAT IS NOT A DEFECT IN IT. ``--record-applied``
    exists for the 04:07Z hole -- the ALTER landed and the migrator's manifest was never written --
    and what it can honestly freeze is the POST-apply re-read, not a plan it never cut:
    ``write_applied_manifest`` stores ``"plan": None`` and a self-certifying
    ``post_apply.table_input`` + ``post_apply.catalog_hash`` instead. That shape is not
    hypothetical: MEASURED 2026-09-11, the sibling manifest
    ``sql/athena/migrations/silver/20260910T060216Z_silver_fgis_additive_update.json`` on this very
    tree carries ``reconstructed: true``, ``plan: null`` and a ``post_apply`` whose stored
    ``catalog_hash`` re-hashes exactly. Reading only ``plan`` would mean that running this
    runbook's OWN repair mode turned ``--offline`` into a permanent exit 2 -- the repair destroying
    the capability. So the halves are tried in order (plan, then post_apply) and ABSENCE falls
    through while NON-CERTIFICATION still refuses; if neither half is there the R0 record is the
    last rung, and a refusal there names both failures rather than the last one.

    A TableInput carries no VersionId or UpdateTime, so those two come from the manifest's own
    ``post_apply`` when it has them and otherwise from this runbook's pinned live measurement of
    the post-ALTER table -- admissible only because the hash fence inside ``_manifest_half`` has
    just proved the manifest IS that table, and labelled as such in the source line the plan header
    prints."""
    found = applied_manifest_record(migrations_dir)
    if found is None:
        return r0_record_table()
    path, payload = found
    halves = (
        dict(block="plan", key="table_input", hash_key="desired_hash", what=PLAN_HALF_IS),
        dict(block="post_apply", key="table_input", hash_key="catalog_hash",
             what=POST_APPLY_HALF_IS),
    )
    absent = [f"{h['block']}.{h['key']}" for h in halves
              if not _half_present(payload, block=h["block"], key=h["key"])]
    for half in halves:
        if not _half_present(payload, block=half["block"], key=half["key"]):
            continue
        snap, cert = _manifest_half(
            path, payload, pinned=MEASURED["live_catalog_hash_post_alter"],
            pinned_name="live_catalog_hash_post_alter", **half)
        table = dict(snap)
        table.setdefault("Name", TABLE)
        body = payload.get(half["block"]) or {}
        version, update, whence = (
            (body.get("version_id"), body.get("update_time"),
             f"the manifest's own {half['block']}.version_id/update_time, frozen from live Glue "
             "when the record was written")
            if body.get("version_id") and body.get("update_time") else
            (MEASURED["live_version_id_post_alter"], MEASURED["live_update_time_post_alter"],
             f"MEASURED {MEASURED['measured_post_alter_on']} by glue.get_table, not carried by a "
             "TableInput"))
        table["VersionId"] = str(version)
        table["UpdateTime"] = update
        return table, dict(cert, version_source=f"VersionId/UpdateTime are {whence}")
    # Neither half is on the manifest. The R0 record is the last rung -- and post-ALTER it IS the
    # current catalog, because step [2] re-captured it. If it cannot be read either, say BOTH.
    try:
        return r0_record_table()
    except Refused as exc:
        raise Refused(
            f"the machine manifest {path.name} carries neither of the halves that describe the "
            f"CURRENT catalog ({', '.join(absent)}), so the R0 record was the last rung -- and it "
            f"does not stand either:\n  {exc}")


def sidecar_note() -> str:
    """One line about the ``_raw`` sidecar, so nobody reaches for it later. Read, not asserted."""
    path = R0_RAW / f"{TABLE}.get-table.json"
    if not path.exists():
        return f"  NOTE: no _raw sidecar at {path} (this runbook does not use one)."
    snap = json.loads(path.read_text(encoding="utf-8"))
    return ("  NOTE: the _raw sidecar is NOT used and is NOT the pre-apply table -- "
            f"{len(_columns(snap))} columns, partition keys "
            f"{[p.get('Name') for p in snap.get('PartitionKeys') or []]}, VersionId "
            f"{snap.get('VersionId')}. It predates the SILVER-F031 as_of_date dimension.")


def read_table(*, offline: bool, glue_client=None, database: str = DATABASE,
               offline_dir: Optional[Path] = None) -> tuple[dict, str]:
    """``(table, source description)``. Read-only in every branch."""
    if offline_dir is not None:
        path = Path(offline_dir) / f"{TABLE}.get-table.json"
        if not path.exists():
            raise Refused(f"offline source missing: {path}")
        return json.loads(path.read_text(encoding="utf-8")), f"offline snapshot {path} (AWS-free)"
    if offline:
        table, cert = offline_table()
        extra = f"; {cert['version_source']}" if cert.get("version_source") else ""
        return table, (f"{cert['source']}, digest RE-VERIFIED ({cert['field']} = {cert['got']})"
                       f"{extra} (AWS-free)")
    return (glue_client.get_table(DatabaseName=database, Name=TABLE)["Table"],
            "live glue.get_table")


# ---------------------------------------------------------------------------
# shape: which end of this migration the live table sits at
# ---------------------------------------------------------------------------
def live_shape(live: dict, five: list[tuple[str, str]]) -> str:
    """AT_SOURCE, AT_TARGET or MIXED. TOTAL BY CONSTRUCTION -- separating "already done" from "some
    third state" is what makes a half-finished run finishable by the same command, and it narrows
    the refusal to what actually deserves one."""
    names = tuple(_column_names(live))
    types = _column_types(live)
    want = tuple(n for n, _ in five)
    if names == NARROW_NAMES and all(types.get(n) == t for n, t in NARROW_COLUMNS):
        return AT_SOURCE
    if names == NARROW_NAMES + want and all(types.get(n) == t for n, t in five) \
            and all(types.get(n) == t for n, t in NARROW_COLUMNS):
        return AT_TARGET
    return MIXED


def describe_shape(live: dict, five: list[tuple[str, str]]) -> str:
    """Why a MIXED table is MIXED, in the words an owner needs to decide what to do next."""
    names = _column_names(live)
    types = _column_types(live)
    want = [n for n, _ in five]
    bits = [f"{len(names)} column(s) (expected {len(NARROW_NAMES)} narrow or "
            f"{len(NARROW_NAMES) + len(want)} wide)"]
    missing = [n for n in NARROW_NAMES if n not in names]
    extra = [n for n in names if n not in NARROW_NAMES and n not in want]
    if missing:
        bits.append(f"MISSING expected column(s): {missing}")
    if extra:
        bits.append(f"UNEXPECTED column(s): {extra}")
    present = [n for n in want if n in names]
    if present and len(present) != len(want):
        bits.append(f"only {len(present)} of the five are present: {present}")
    if names and names[-1] != ANCHOR_COLUMN and not present:
        bits.append(f"the last column is {names[-1]!r}, not {ANCHOR_COLUMN!r}")
    wrong = [f"{n}: {types.get(n)!r} != {t!r}" for n, t in NARROW_COLUMNS
             if n in names and types.get(n) != t]
    if wrong:
        bits.append(f"retyped incumbent column(s): {wrong}")
    return "; ".join(bits)


# ---------------------------------------------------------------------------
# the desired TableInput: the LIVE one, with ONLY the five appended at the tail
# ---------------------------------------------------------------------------
def widen_table_input(live: dict, five: list[tuple[str, str]]) -> dict:
    """The live TableInput with exactly the five columns APPENDED after ``source``, in order.

    Every other field is carried VERBATIM. ``update_table`` REPLACES a table definition -- a field
    omitted from the TableInput is GONE -- which is why this never rebuilds a TableInput from a
    contract (MEASURED on the estate's 2026-07-15 silver_noaa_oni widen: a rebuilt minimal
    TableInput dropped Owner, LastAccessTime, SkewedInfo and BucketColumns on that table)."""
    names = _column_names(live)
    already = [n for n, _ in five if n in names]
    if already:
        raise Refused(f"{TABLE}: {already} already exist in live Glue -- this is not a widen to "
                      "plan. (An ALREADY WIDE table is skipped, not widened twice.)")
    if tuple(names) != NARROW_NAMES:
        raise Refused(f"{TABLE}: live column list is not the measured pre-ALTER one -- REFUSED.\n"
                      f"  live    : {names}\n  expected: {list(NARROW_NAMES)}")
    if names[-1] != ANCHOR_COLUMN:
        raise Refused(f"{TABLE}: the last live column is {names[-1]!r}, not {ANCHOR_COLUMN!r}; the "
                      "five may only be appended after it.")
    ti = raw_snapshot_to_table_input(live)
    sd = dict(ti.get("StorageDescriptor") or {})
    sd["Columns"] = [dict(c) for c in sd.get("Columns") or []] + \
                    [{"Name": n, "Type": t} for n, t in five]
    ti["StorageDescriptor"] = sd
    return ti


def narrow_table_input(live: dict, five: list[tuple[str, str]]) -> dict:
    """The live (wide) TableInput with exactly the five TAIL columns REMOVED -- the rollback basis.

    The basis is the LIVE table, not a tracked snapshot, so unrelated catalog drift is never
    reverted along with the five."""
    names = _column_names(live)
    want = [n for n, _ in five]
    if tuple(names) != NARROW_NAMES + tuple(want):
        raise Refused(f"{TABLE}: live column list is not the measured POST-ALTER one -- REFUSED "
                      "(a rollback that quietly no-ops is a rollback an owner believes "
                      f"happened).\n  live    : {names}\n"
                      f"  expected: {list(NARROW_NAMES) + want}")
    ti = raw_snapshot_to_table_input(live)
    sd = dict(ti.get("StorageDescriptor") or {})
    sd["Columns"] = [dict(c) for c in (sd.get("Columns") or [])[:len(NARROW_NAMES)]]
    ti["StorageDescriptor"] = sd
    return ti


def assert_shape_preserved(live: dict, desired: dict, five: list[tuple[str, str]],
                           direction: str) -> None:
    """Everything except the tail append (or its removal) must be byte-identical.

    This is the fence the sibling widening runbook cannot lend: ITS rule is that column names and
    order never move, which an ADD COLUMNS violates by definition. The rule here is narrower and
    stricter about what it does allow -- the leading 12 columns identical in NAME, TYPE and ORDER,
    and the ONLY difference the five, at the tail, in the contract's order."""
    for field in ("Parameters", "PartitionKeys"):
        a = json.dumps(live.get(field), sort_keys=True, default=str)
        b = json.dumps(desired.get(field), sort_keys=True, default=str)
        if a != b:
            raise Refused(f"{TABLE}: {field} would change -- REFUSED.\n  live   : {a}\n"
                          f"  desired: {b}")
    lsd = live.get("StorageDescriptor") or {}
    dsd = desired.get("StorageDescriptor") or {}
    for field in ("Location", "InputFormat", "OutputFormat", "SerdeInfo", "Parameters",
                  "BucketColumns", "SortColumns", "SkewedInfo", "NumberOfBuckets", "Compressed",
                  "StoredAsSubDirectories"):
        a = json.dumps(lsd.get(field), sort_keys=True, default=str)
        b = json.dumps(dsd.get(field), sort_keys=True, default=str)
        if a != b:
            raise Refused(f"{TABLE}: StorageDescriptor.{field} would change -- REFUSED."
                          f"\n  live   : {a}\n  desired: {b}")
    lcols = [(c.get("Name"), str(c.get("Type") or "").lower()) for c in lsd.get("Columns") or []]
    dcols = [(c.get("Name"), str(c.get("Type") or "").lower()) for c in dsd.get("Columns") or []]
    tail = [(n, t) for n, t in five]
    if direction == "ROLLBACK":
        keep, added = dcols, lcols[len(dcols):]
        prefix = lcols[:len(dcols)]
    else:
        keep, added = lcols, dcols[len(lcols):]
        prefix = dcols[:len(lcols)]
    if prefix != keep:
        raise Refused(f"{TABLE}: the incumbent columns would change -- REFUSED (this migration "
                      f"appends, it never touches an existing column).\n  keep : {keep}\n"
                      f"  found: {prefix}")
    if added != tail:
        raise Refused(f"{TABLE}: the tail is not exactly the five, in order -- REFUSED.\n"
                      f"  tail    : {added}\n  expected: {tail}")


# ---------------------------------------------------------------------------
# plan + the bounded unsafe gate
# ---------------------------------------------------------------------------
def build_plan(live: dict, desired: dict, mig: CatalogMigrator, database: str = DATABASE,
               direction: str = "ADD") -> MigrationPlan:
    if direction == "ROLLBACK":
        glue_call = (
            f"CatalogMigrator.restore_table({TABLE!r}, snapshot=<live {TABLE} with the five tail "
            f"columns removed>, expected_current_hash=<the live hash below>)\n"
            f"      -> glue.update_table(DatabaseName={database!r}, TableInput=<that snapshot>)  "
            "# lease-fenced; post-restore hash verified by restore_table")
    else:
        glue_call = (f"glue.update_table(DatabaseName={database!r}, TableInput=<live {TABLE} with "
                     "the five columns appended>)  # additive; live hash re-checked")
    return MigrationPlan(
        table=TABLE,
        database=database,
        change_type=ChangeType.ADDITIVE_UPDATE,
        live_hash=catalog.hash_table(live),
        desired_hash=catalog.hash_table(desired),
        diffs=catalog.diff_table(live, desired),
        glue_call=glue_call,
        table_input=desired,
        # MEASURED, never asserted: this contract is partition_mode=registered, so this comes back
        # registered=True with the table-SD diff -- the 243 partition descriptors the next canonical
        # promote must repair. It comes from the migrator, not from a literal.
        registered_partition_audit=mig._registered_partition_audit(TABLE, live, desired),
        unsafe=mig._unsafe_diffs(live, desired),  # the sanctioned refuser; apply_table raises on it
    )


def expected_reverse_unsafe(five: list[tuple[str, str]]) -> list[str]:
    """The EXACT ``_unsafe_diffs`` lines a correct reverse plan must produce -- one DROP per column,
    in the migrator's own wording. The rollback's override is bounded by this list: an entry that is
    not in it (a sixth drop, a partition-key change, a narrowing) is a REFUSAL, not an override."""
    return [f"DROP column '{name}' (refused)" for name, _ in five]


def check_unsafe(plan: MigrationPlan, five: list[tuple[str, str]], direction: str) -> list[str]:
    """Gate the plan's unsafe list for the direction. Returns the entries deliberately OVERRIDDEN
    (empty for the additive). Raises ``Refused`` on anything unexpected."""
    if direction != "ROLLBACK":
        if plan.unsafe:
            raise Refused(f"{TABLE}: unsafe diff {plan.unsafe} -- an ADD COLUMNS must produce none")
        return []
    want = expected_reverse_unsafe(five)
    if sorted(plan.unsafe) != sorted(want):
        raise Refused(
            f"{TABLE}: the reverse plan's unsafe set is not the bounded expected one -- REFUSED.\n"
            f"  got  : {plan.unsafe}\n  want : {want}\n"
            "  Only the five measured tail-column drops may be overridden by --rollback.")
    return want


# ---------------------------------------------------------------------------
# printing
# ---------------------------------------------------------------------------
def print_plan(live: dict, desired: dict, plan: MigrationPlan, five: list[tuple[str, str]],
               *, source: str, direction: str) -> None:
    lsd = live.get("StorageDescriptor") or {}
    lnames = _column_names(live)
    dnames = _column_names(desired)
    ltypes = _column_types(live)
    dtypes = _column_types(desired)
    added = [n for n in dnames if n not in lnames]
    dropped = [n for n in lnames if n not in dnames]

    print(_rule("="))
    print(f"{TABLE}   [{direction}]   source={source}")
    print(_rule("="))
    print(f"  database        : {plan.database}")
    print(f"  location        : {lsd.get('Location')}")
    print(f"  table VersionId : {live.get('VersionId')}   UpdateTime: "
          f"{_iso(live.get('UpdateTime'))}")
    family, cron = PROMOTE_FAMILY
    print(f"  producing family: {family} on {cron} (the promote that repairs the partition SDs)")
    print(f"  migration file  : sql/athena/migrations/silver/{MIGRATION_SQL.name}  "
          f"({TABLE} half ONLY)")
    print()
    print("  COLUMNS  (+ = added by this plan, - = dropped by this plan)")
    print(("    %-2s %-3s %-36s %-10s %-10s" % ("", "#", "column", "before", "after")).rstrip())
    for i, name in enumerate(lnames):
        mark = "-" if name in dropped else " "
        print(("    %-2s %-3d %-36s %-10s %-10s"
               % (mark, i, name, ltypes.get(name), dtypes.get(name, "(dropped)"))).rstrip())
    for j, name in enumerate(added):
        print(("    %-2s %-3d %-36s %-10s %-10s"
               % ("+", len(lnames) + j, name, "(absent)", dtypes.get(name))).rstrip())
    print(f"    ({len(lnames)} -> {len(dnames)} non-partition columns; "
          f"{len(added)} added, {len(dropped)} dropped, "
          f"{len(lnames) - len(dropped)} carried byte-for-byte)")
    print()
    print("  PARTITION KEYS  (carried byte-for-byte; NOT part of this migration)")
    for p in live.get("PartitionKeys") or []:
        print(f"    {p['Name']:<24} {p['Type']}")
    print()
    params = live.get("Parameters") or {}
    print(f"  TABLE PARAMETERS  ({len(params)} keys, carried byte-for-byte)")
    for k in sorted(params):
        print(f"    {k:<44} = {params[k]}")
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
    audit = plan.registered_partition_audit or {}
    print(f"    registered_partition_audit.registered: {audit.get('registered')}")
    if audit.get("registered"):
        print(f"    action        : {audit.get('action')}")
        print(f"    MEASURED 2026-09-10: {MEASURED['registered_partitions']} registered "
              f"partitions, all {MEASURED['registered_partitions_at_12_columns']} at "
              f"{MEASURED['live_columns']} columns. This run updates the TABLE descriptor ONLY.")
        if direction == "ROLLBACK":
            print("    A rollback therefore needs NO partition work: the partition descriptors")
            print(f"    never left {MEASURED['live_columns']} columns, so restoring the table to "
                  f"{MEASURED['live_columns']} RE-ALIGNS the two")
            print("    and the next promote finds no diff to repair.")
        else:
            print("    Every one of them is repaired by the NEXT canonical --vintage-mode all "
                  "promote:")
            print("    PartitionPublisher._partition_input copies the TABLE SD, the diff is a pure")
            print("    trailing append, and the producer image carries reconcile_schema_widen=True")
            print(f"    ({MEASURED['producer_flag_file']}:{MEASURED['producer_flag_line']} at "
                  f"{MEASURED['producer_flag_commit']}).")
            print("    Until that promote runs the partition descriptors keep "
                  f"{MEASURED['live_columns']} columns -- MEASURED")
            print(f"    {MEASURED['measured_post_alter_on']} by glue.get_partitions, all "
                  f"{MEASURED['registered_partitions_at_12_columns_post_alter']} of them still do.")
            print("    READ THAT AS PARTITION WORK STILL OWED, NOT AS A PREDICTION OF NULLS: this")
            print("    runbook predicted the five would read NULL until the promote, and MEASURED")
            print(f"    2026-09-10 the --verify-read probe returned {MEASURED['verify_read_rows']} "
                  f"rows, and {MEASURED['verify_read_non_null_of_five']} of the five read")
            print("    NON-NULL over a 12-column partition descriptor. Neither result is a verdict")
            print("    on the data.")
    if direction == "ROLLBACK":
        print(f"    unsafe        : {len(plan.unsafe)} entry(ies) -- EXPECTED. A reverse plan"
              " DROPS")
        print("                    columns, and CatalogMigrator.apply_table refuses every drop.")
        print("                    --rollback therefore does NOT go through apply_table: it goes")
        print("                    through CatalogMigrator.restore_table, and this exact list is")
        print("                    the bounded override (any other entry = REFUSED).")
        for u in plan.unsafe:
            print(f"      {u[:2000]}")
    elif plan.unsafe:
        print(f"    unsafe        : {plan.unsafe}   <-- REFUSED (an ADD COLUMNS must produce none)")
    else:
        print("    unsafe        : [] (no drop, no partition-key change, no narrowing -- an "
              "append is")
        print("                    additive by construction)")
    print()
    print("  THE EXACT CALL THIS WOULD ISSUE")
    print(f"    {plan.glue_call}")
    print("  EQUIVALENT DDL (documentation only -- NOT the path taken; a DDL statement cannot")
    print("  assert Parameters/PartitionKeys byte-identity, and it cannot re-check a live hash)")
    if direction == "ROLLBACK":
        print("    -- there is no additive DDL for a rollback: dropping a column is a "
              "REPLACE COLUMNS,")
        print(f"    ALTER TABLE {plan.database}.{TABLE} REPLACE COLUMNS ("
              + ", ".join(f"{n} {dtypes[n]}" for n in dnames) + ");")
    else:
        print(f"    ALTER TABLE {plan.database}.{TABLE} ADD COLUMNS ("
              + ", ".join(f"{n} {dtypes[n]}" for n in added) + ");")
    print()


def print_post_apply_steps() -> None:
    """Steps (2)-(4) of the runbook's S5, as PowerShell 5.1, with the exact files."""
    print()
    print(_rule("="))
    print("POST-APPLY STEPS  (Windows PowerShell 5.1: one statement per line; chain with ';')")
    print(_rule("="))
    print("THE ALTER IS ONE COMMIT'S WORTH OF WORK, NOT ONE COMMAND. Steps [2]-[4] below are the")
    print("rest of that commit; step [5] is the promote that makes the columns readable.")
    print()
    print("[1] PROVE THE EXISTING OBJECTS STILL READ under the widened catalog. One bounded,")
    print("    partition-filtered SELECT of the five on the newest canonical partition.")
    print("    python scripts/ops/esr_f030_compact_alter_runbook.py --verify-read")
    print("    EXPECT ROWS. Rows = the objects read. Zero rows = a failure; roll back:")
    print("    python scripts/ops/esr_f030_compact_alter_runbook.py --rollback")
    print("    EXPECT NOTHING IN PARTICULAR OF THE VALUES. This step used to say 'EXPECT the five")
    print("    to be NULL', reasoning that Athena reads a registered partition's columns from the")
    print(f"    PARTITION descriptor and all {MEASURED['registered_partitions']} still say "
          f"{MEASURED['live_columns']} columns until step [5].")
    print(f"    The descriptors ARE still narrow -- MEASURED "
          f"{MEASURED['measured_post_alter_on']} by glue.get_partitions, "
          f"{MEASURED['registered_partitions_at_12_columns_post_alter']} of")
    print(f"    {MEASURED['registered_partitions']}, the probe partition included. THE PREDICTION "
          "WAS WRONG: MEASURED 2026-09-10 this")
    print(f"    probe returned {MEASURED['verify_read_rows']} rows, and "
          f"{MEASURED['verify_read_non_null_of_five']} of the five read NON-NULL over that")
    print("    12-column descriptor. Populated or NULL, the probe proves readability and nothing")
    print("    else.")
    print()
    print("[2] REFRESH THE R0 RECORD FROM THE POST-ALTER LIVE TABLE. --check first (it writes")
    print("    nothing and prints the stored-vs-live diff), then the real capture.")
    print("    python scripts/silver/run_census.py --table silver_esr_compact --check")
    print("    python scripts/silver/run_census.py --table silver_esr_compact")
    print("    THE FILE THIS WRITES:")
    print("      reports/silver_readiness/20260712_p65impl/tables/silver_esr_compact.json")
    print("      (glue.nonpartition_columns 12 -> 17, glue.num_nonpartition_columns, and the")
    print("       fingerprint the registry copies as fingerprint.catalog_hash_sha256)")
    print("      THAT FILE IS GITIGNORED (the 'reports/silver_readiness/' rule in .gitignore --")
    print("      the RULE, not a line number: that rule moved from line 77 to line 91 inside one")
    print("      hour on 2026-09-11), so it does")
    print("      NOT ride in the commit and a fresh clone will not have it. This runbook therefore")
    print("      stops using it as its pre-ALTER basis the moment this step runs: the tracked")
    print("      machine manifest written by the apply outranks it (NARROW_BASIS_PRECEDENCE).")
    print("    DO NOT pass --raw. The _raw sidecar is the frozen pre-event side by design, and for")
    print("    this table it is already the pre-F031 shape; re-capturing it destroys a record and")
    print("    refreshes nothing this migration needs.")
    print()
    print("[3] PROMOTE THE FIVE IN THE REGISTRY GENERATOR. In scripts/silver/")
    print("    gen_registry_from_baseline.py, CURATION_OVERRIDES['silver_esr_compact']:")
    print("      - rename the key   \"additive_columns_hidden\"  to  \"additive_columns\"")
    print("      - add                \"additive_columns_registered\": True,")
    print("    (Both, in the same edit. additive_columns_registered is what resolves float64 ->")
    print("    double and puts the five in the rendered DDL; the rename alone leaves them hidden.)")
    print()
    print("[4] REGENERATE AND PROVE IT, IN THE SAME COMMIT AS [2] AND [3].")
    print("    python scripts/silver/gen_registry_from_baseline.py")
    print("    python scripts/silver/gen_registry_from_baseline.py --check")
    print("    python scripts/silver/generate_ddls_from_registry.py --write")
    print("    python -m pytest tests/unit/silver/test_ddl_generation.py "
          "tests/unit/silver/test_esr_contract_rebaseline.py -q")
    print("    python -m pytest tests/unit/silver/test_esr_f030_compact_alter_runbook.py -q")
    print("    python -m pytest tests/unit/silver -q")
    print("    EXPECT: sql/athena/ddl_generated/silver_esr_compact.sql goes 12 -> 17 columns, the")
    print("    five LAST, as double. (That is the generated tree's real path -- this step named")
    print("    sql/athena/ddl/silver/, which has never existed in this repo; corrected 2026-09-11")
    print("    after the generator was run and the file VERIFIED at 17 columns.)")
    print("    THE HAND DDL IS NOW DRIFTED, DELIBERATELY AND OUT OF THIS COMMIT'S SCOPE.")
    print("    sql/athena/ddl/silver_esr_compact.sql is a DIFFERENT, TRACKED file -- the hand-DDL")
    print("    tree (scripts/silver/generate_ddls_from_registry.py calls it that) that")
    print("    config_check.check_numbers_schema_pins reads for card-vs-DDL drift. MEASURED")
    print("    2026-09-11 it still declares 12 columns while the generated file declares 17, and")
    print("    that lint only fires on a column a numbers CARD references -- none of the five is")
    print("    referenced by any card in configs/graphrag/numbers/tables.yaml today, so the drift")
    print("    is latent, not failing. It becomes real the first time a card reads one of the")
    print("    five. NOT FIXED HERE -- repairing the hand DDL is outside this runbook's own files,")
    print("    so it is named as owed rather than left for the next reader to discover.")
    print("    THREE tests carry their post-ALTER form and must be flipped in this commit -- this")
    print("    step named two until 2026-09-11, and the third went red on the same regeneration.")
    print("    ALL THREE WERE RENAMED BY THE FLIP, so the names below are the POST-ALTER ones and")
    print("    each line records the pre-ALTER name it replaced (this step named the old three")
    print("    until 2026-09-11, by which time none of them existed):")
    print("      tests/unit/silver/test_esr_contract_rebaseline.py::")
    print("        TestAdditiveNetCommitmentColumns::")
    print("        test_the_five_are_registered_catalog_columns_since_the_gated_alter")
    print("        -- was test_the_five_are_physical_only_until_the_gated_alter, whose docstring")
    print("           said 'This test then flips to asserting glue_type == \"double\"'.")
    print("      tests/unit/silver/test_ddl_generation.py::")
    print("        test_esr_compact_ddl_renders_the_five_since_the_gated_alter")
    print("        -- was test_esr_compact_ddl_does_not_yet_render_the_five. Its sibling")
    print("           test_esr_compact_ddl_renders_the_five_last_once_registered already passed")
    print("           before the flip (it simulates it on a deepcopy) and keeps passing.")
    print("      tests/unit/silver/test_esr_f030_compact_alter_runbook.py::")
    print("        test_the_contract_registers_the_five_today")
    print("        -- was test_the_contract_stages_the_five_hidden_today, asserting STAGED_HIDDEN.")
    print("           THE ONE TEST THAT PINS TODAY'S CONTRACT STATE.")
    print()
    print("[5] THE CANONICAL PROMOTE -- this is what repairs the "
          f"{MEASURED['registered_partitions']} partition descriptors")
    print("    and makes the five readable. It is runbook step S7:")
    print("    python scripts/ops/esr_netcommitment_runbook.py --step S7")
    print("    Then READ partition_actions AGAINST A DENOMINATOR (the publisher only walks the")
    print("    partitions the run STAGES; an orphan keeps its 12-column descriptor):")
    print("    aws glue get-partitions --database-name leviathan_dev --table-name "
          "silver_esr_compact --region us-east-1 --query 'length(Partitions)' --output text")
    print()
    print("[6] THE RECORD. There is no hand-authored manifest for this ALTER: the machine manifest")
    print("    CatalogMigrator wrote above IS the record, and it carries the RAW pre-apply")
    print("    get_table snapshot a rollback restores. KEEP IT IN THE COMMIT -- after step [2] it is")
    print("    also this runbook's NARROW BASIS (the R0 record is gitignored AND has just")
    print("    been re-captured to the wide shape), so leaving it out breaks --offline and the")
    print("    reconstructed backup in a fresh clone.")
    print("    backup.table_input in that file is a RAW get_table snapshot: it still carries the")
    print("    nine read-only fields Glue REJECTS on input (CatalogId, CreateTime, CreatedBy,")
    print("    DatabaseName, UpdateTime, VersionId, IsRegisteredWithLakeFormation and the two view")
    print("    flags). Restore it ONLY through CatalogMigrator.restore_table(snapshot=...), which")
    print("    drops them; never hand that blob to glue.update_table.")
    print()
    print("ROLLBACK, IF STEP [1] FAILS:")
    print("    python scripts/ops/esr_f030_compact_alter_runbook.py --rollback")
    print("  AFTER step [5] there is no rollback: the old producer image lacks")
    print("  reconcile_schema_widen and would meet a widened table SD. Roll FORWARD instead.")


def print_post_rollback_steps() -> None:
    """What a ROLLBACK owes the operator -- which is the OPPOSITE of the post-apply sequence."""
    print()
    print(_rule("="))
    print("POST-ROLLBACK STEPS  (Windows PowerShell 5.1: one statement per line; chain with ';')")
    print(_rule("="))
    print("THE CATALOG IS BACK AT 12 COLUMNS. That is a CONSISTENT state, not a damaged one: the")
    print("producer has been emitting 18 physical columns since lane C, and a parquet reader reads")
    print("by name -- the five are simply undeclared again, exactly as they were this morning.")
    print()
    print("DO NOT run the post-apply sequence. In particular:")
    print("  - do NOT refresh the R0 record or regenerate the registry (they would then declare 12")
    print("    columns from a catalog that is 12 -- correct, but it would burn the diff that")
    print("    proves the ALTER is still owed);")
    print("  - do NOT rename additive_columns_hidden -> additive_columns. HIDDEN is now correct")
    print("    again, and it is the tripwire that says the ALTER has not landed.")
    print()
    print("[1] CONFIRM the narrow shape is what live Glue carries (a dry-run re-reads live and")
    print("    refuses unless the columns are exactly the measured 12, so exit 0 IS the")
    print("    confirmation).")
    print("    python scripts/ops/esr_f030_compact_alter_runbook.py")
    print()
    print("[2] PROVE THE OBJECTS STILL READ under the restored catalog.")
    print("    python scripts/ops/esr_f030_compact_alter_runbook.py --verify-read")
    print("    The five are no longer selectable, so this probe now names only the incumbents --")
    print("    read the SQL it prints before reading its verdict.")
    print()
    print("[3] THE DECKS -- they must still be GREEN, because nothing about the staging changed.")
    print("    python -m pytest tests/unit/silver/test_esr_f030_compact_alter_runbook.py -q")
    print("    python -m pytest tests/unit/silver/test_ddl_generation.py "
          "tests/unit/silver/test_esr_contract_rebaseline.py -q")
    print()
    print("[4] Keep the rollback record this run wrote in sql/athena/migrations/silver/ as the")
    print("    audit trail, and work out WHY the ALTER had to be reversed before proposing it")
    print("    again. The whole-family promote failure this migration's PRECONDITION block exists")
    print("    to prevent is the first thing to rule out.")


# ---------------------------------------------------------------------------
# modes
# ---------------------------------------------------------------------------
def assert_registry_not_ahead(state: str, shape: str, live: dict, five: list[tuple[str, str]],
                              direction: str) -> None:
    """THE ORDER FENCE, both ways round. The registry NEVER leads live Glue.

    Forwards: step [1] is the ALTER and step [3] is the CURATION_OVERRIDES flip. A contract that
    already declares the five over a catalog that does not carry them is that order reversed --
    which is the exact state ``test_generated_matches_live_glue_for_every_table`` reds on.

    Backwards: rolling the CATALOG back after the flip has landed produces the same illegal state
    from the other side, and it would do it silently. The registry has to be reverted FIRST."""
    if state != REGISTERED:
        return
    if direction == "ROLLBACK":
        raise Refused(
            f"{TABLE}: the step-4 registry flip has ALREADY LANDED -- the contract declares the "
            "five as double. Rolling the CATALOG back now would leave the registry ahead of live "
            "Glue, which is the state the whole hidden-staging exists to prevent.\n"
            "  Revert the CURATION_OVERRIDES flip in scripts/silver/gen_registry_from_baseline.py "
            "(rename\n"
            "  additive_columns back to additive_columns_hidden, drop "
            "additive_columns_registered),\n"
            "  regenerate, and THEN roll the catalog back.")
    if shape != AT_TARGET:
        raise Refused(
            f"{TABLE}: THE REGISTRY LEADS LIVE GLUE. The contract declares the five as double "
            f"(the step-4 flip has landed) but the catalog is {shape} -- "
            f"{describe_shape(live, five)}.\n"
            "  The order is ALTER first, regenerate second. Either apply the ALTER, or revert "
            "the CURATION_OVERRIDES flip in scripts/silver/gen_registry_from_baseline.py.")


def dry_run(*, offline: bool, region: str, database: str, direction: str = "ADD",
            offline_dir: Optional[Path] = None, glue_client=None) -> int:
    glue = glue_client if glue_client is not None else (None if (offline or offline_dir) else
                                                        _glue_client(region))
    state, five = five_from_registry()
    mig = CatalogMigrator(
        database=database,
        auth=Authorization(mode=PublishMode.DRY_RUN, may_mutate_canonical=False, readiness=False,
                           reason="SILVER-F030 compact ADD COLUMNS dry-run"),
        glue_client=glue)
    live, source = read_table(offline=offline, glue_client=glue, database=database,
                              offline_dir=offline_dir)
    shape = live_shape(live, five)

    assert_registry_not_ahead(state, shape, live, five, direction)
    if state == REGISTERED:
        # The flip has landed AND the catalog is at the target: the migration is closed.
        print(_rule("="))
        print(f"{TABLE}   [{direction}]   source={source}")
        print(_rule("="))
        print("  DONE AND RECORDED. The catalog carries all 17 columns AND the contract declares")
        print("  the five as double -- the ALTER and the step-4 regeneration have both landed.")
        print(f"  VersionId {live.get('VersionId')}  UpdateTime {_iso(live.get('UpdateTime'))}")
        print(_rule("="))
        return 0

    if direction != "ROLLBACK" and shape == AT_TARGET:
        print(_rule("="))
        print(f"{TABLE}   [{direction}]   source={source}")
        print(_rule("="))
        print(f"  ALREADY WIDE (VersionId {live.get('VersionId')}, UpdateTime "
              f"{_iso(live.get('UpdateTime'))}) -- skipping.")
        print("  All five columns are already at the tail as double; there is nothing to plan.")
        for name, glue_type in five:
            print(("    %-2s %-36s %-10s %-10s" % ("=", name, glue_type, glue_type)).rstrip())
        print("  The registry still stages them HIDDEN, so the commit is not finished: steps")
        print("  [2]-[4] below are still owed.")
        print(_rule("="))
        print_post_apply_steps()
        return 0

    if shape == MIXED:
        raise Refused(f"{TABLE}: live Glue is neither the measured pre-ALTER shape nor the target "
                      f"-- {describe_shape(live, five)}. REFUSED (the catalog is not in the state "
                      "this migration was measured against).")

    if direction == "ROLLBACK":
        desired = narrow_table_input(live, five)
    else:
        desired = widen_table_input(live, five)
    assert_shape_preserved(live, desired, five, direction)
    plan = build_plan(live, desired, mig, database, direction)
    # The SAME gate the mutating path runs. A dry-run that previews a plan the apply would refuse
    # is worse than no preview at all, so this refuses here too (exit 2).
    check_unsafe(plan, five, direction)
    print_plan(live, desired, plan, five, source=source, direction=direction)
    if offline and offline_dir is None:
        print(sidecar_note())
        print()
    print(_rule("="))
    print("DRY RUN -- NOTHING WAS MUTATED. No glue.update_table was issued, no lease was taken,")
    if direction == "ROLLBACK":
        print("no S3 object was written. Re-run with --rollback ALONE (drop --dry-run) to execute.")
    else:
        print("no S3 object was written. Re-run with --apply (owner) to execute.")
    print(_rule("="))
    return 0


# ---------------------------------------------------------------------------
# the APPLIED record
# ---------------------------------------------------------------------------
def _applied_manifest(migrations_dir: Path) -> Optional[Path]:
    """The machine manifest for an APPLIED widen of this table, if one is already on disk.

    ``CatalogMigrator`` writes ``<UTC>_<table>_<change_type>.json`` and no ``applied`` key at all --
    the file's existence IS the claim -- so any file matching that name counts, except one that
    explicitly says ``applied: false``."""
    if migrations_dir is None or not migrations_dir.exists():
        return None
    for path in sorted(migrations_dir.glob(f"*_{TABLE}_{ChangeType.ADDITIVE_UPDATE.value}.json")):
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("applied") is False:
                continue
        except Exception:                                                        # noqa: BLE001
            pass                         # an unparseable record is still a record; do not overwrite
        return path
    return None


def pre_apply_basis(five: list[tuple[str, str]],
                    migrations_dir: Optional[Path] = None) -> dict:
    """The PRE-apply TableInput for a RECONSTRUCTED record -- with its certification RE-VERIFIED.

    The basis is ``narrow_basis``'s, so the precedence rule lives in ONE place: the machine
    manifest's frozen pre-apply snapshot once the ALTER has landed, the R0 record before it. The
    certificate is whatever THAT source stores -- ``backup.catalog_hash`` recomputed with
    ``catalog.hash_table``, or the record's own ``glue.catalog_hash_sha256`` under the recipe it
    stamps. A basis that does not verify yields NO backup and says why: a backup that might not be
    the state the apply overwrote is worse than an absent one, because it would be restored.

    ``migrations_dir`` defaults to the REPOSITORY's migrations directory, never the one a mode
    happens to be writing into: the narrow basis is a fact about this TABLE's history, not about
    where this run files its record."""
    out = {"source": None, "field": None, "table_input": None, "catalog_hash": None,
           "verified": False, "expected": None, "got": None, "reason": None, "record": None,
           "planned_desired_hash": None}
    try:
        table, cert = narrow_basis(migrations_dir)
    except Refused as exc:
        out["reason"] = str(exc)
        return out
    out.update({"source": cert["source"], "field": cert["field"], "record": cert["record"],
                "expected": cert["expected"], "got": cert["got"]})
    if live_shape(table, five) != AT_SOURCE:
        out["reason"] = (f"the narrow basis is not the pre-ALTER shape "
                         f"({describe_shape(table, five)}) -- it cannot be the state the apply "
                         "overwrote")
        return out
    out["verified"] = True
    # raw_snapshot_to_table_input IS the migrator's own drop list for the nine read-only fields
    # Glue rejects on input; this file never carries a second copy of that list.
    out["table_input"] = raw_snapshot_to_table_input(table)
    out["catalog_hash"] = catalog.hash_table(table)
    out["planned_desired_hash"] = catalog.hash_table(widen_table_input(table, five))
    return out


def write_applied_manifest(*, after: dict, five: list[tuple[str, str]], database: str,
                           migrations_dir: Path, backup: dict, reconstructed_note: str,
                           plan: MigrationPlan = None, fencing_token=None) -> Path:
    """Write the machine manifest for an ALTER that IS on the catalog, FROM THE POST-APPLY RE-READ.

    Same directory and the same ``<UTC>_<table>_additive_update.json`` name ``CatalogMigrator``
    uses, because it is the same record -- it is only being written late. ``applied_at`` is the LIVE
    ``UpdateTime`` (the catalog's own clock), never this process's clock, and ``reconstructed:
    true`` marks it so nobody mistakes it for a manifest the mutation itself produced."""
    migrations_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = migrations_dir / f"{ts}_{TABLE}_{ChangeType.ADDITIVE_UPDATE.value}.json"
    payload = {
        "applied": True,
        "applied_at": _iso(after.get("UpdateTime")),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "reconstructed": True,
        "reconstructed_note": reconstructed_note,
        "database": database,
        "table": TABLE,
        "change_type": ChangeType.ADDITIVE_UPDATE.value,
        "package": "SILVER-F030 BF-W2 (ESR NET-COMMITMENT ADD COLUMNS)",
        "migration_sql": f"sql/athena/migrations/silver/{MIGRATION_SQL.name} ({TABLE} half)",
        "guard_mode": "canonical",
        "fencing_token": fencing_token,
        "added_columns": [{"name": n, "glue_type": t, "ordinal": len(NARROW_NAMES) + i}
                          for i, (n, t) in enumerate(five)],
        "post_apply": {
            "version_id": str(after.get("VersionId")),
            "update_time": _iso(after.get("UpdateTime")),
            "catalog_hash": catalog.hash_table(after),
            "column_types": _column_types(after),
            "table_input": raw_snapshot_to_table_input(after),
        },
        "registered_partitions_note": (
            "ADD COLUMNS updates the TABLE descriptor only. The registered partition "
            "StorageDescriptors are repaired by the next canonical --vintage-mode all promote "
            "(PartitionPublisher._repair under reconcile_schema_widen=True); until then they keep "
            f"{MEASURED['live_columns']} columns -- MEASURED "
            f"{MEASURED['measured_post_alter_on']}, "
            f"{MEASURED['registered_partitions_at_12_columns_post_alter']} of "
            f"{MEASURED['registered_partitions']} still do. That is partition work owed, NOT a "
            "prediction of NULLs: MEASURED 2026-09-10 the --verify-read probe returned "
            f"{MEASURED['verify_read_rows']} rows with all "
            f"{MEASURED['verify_read_non_null_of_five']} of the five NON-NULL over a 12-column "
            "partition descriptor."),
        "backup": backup,
        "plan": plan.to_dict() if plan is not None else None,
        "written_by": "scripts/ops/esr_f030_compact_alter_runbook.py",
        "rollback": "python scripts/ops/esr_f030_compact_alter_runbook.py --rollback",
    }
    # default=str for the same reason the migrator carries it: post_apply.table_input is the live
    # table minus the read-only fields, and LastAccessTime stays and is a datetime. Without it this
    # writer raises AFTER the catalog has already moved -- MEASURED 2026-09-10 04:07Z on the
    # sibling runbook, where that raise cost the estate the record of a mutation that happened.
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return path


def _write_rollback_record(plan: MigrationPlan, live: dict, result: dict,
                           migrations_dir: Path) -> Path:
    """``CatalogMigrator.restore_table`` writes no machine manifest (the F012 restore step never
    did). A rollback that leaves no record is an unaudited catalog mutation, so this writes one
    beside the apply manifests: the PRE-ROLLBACK (wide) TableInput is the backup."""
    migrations_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = migrations_dir / f"{ts}_{TABLE}_rollback_restore.json"
    payload = {
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "database": plan.database,
        "table": TABLE,
        "change_type": "rollback_restore",
        "mechanism": "leviathan.silver.migrate.CatalogMigrator.restore_table (apply_table refuses "
                     "every column DROP; restore_table is the sanctioned reverse path)",
        "plan": plan.to_dict(),
        "backup": {"table": TABLE, "captured_at": datetime.now(timezone.utc).isoformat(),
                   "table_input": json.loads(json.dumps(live, default=str)),
                   "catalog_hash": plan.live_hash},
        "result": result,
        "guard_mode": "canonical",
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# the truth report
# ---------------------------------------------------------------------------
def table_verdict(before: Optional[dict], five: list[tuple[str, str]], *, glue,
                  database: str) -> dict:
    """RE-READ live Glue and say what actually happened. Read-only.

    This is the only question an owner has after a failed run, and it is answered by the CATALOG.
    Where the exception fired is not evidence."""
    try:
        after, _src = read_table(offline=False, glue_client=glue, database=database)
    except Exception as exc:                                                     # noqa: BLE001
        return {"table": TABLE, "status": UNKNOWN, "version_id": None, "after": None,
                "version_before": None if before is None else str(before.get("VersionId")),
                "shape": None,
                "detail": f"the RE-READ ITSELF failed ({type(exc).__name__}: {exc}) -- the live "
                          "state of this table is UNKNOWN. Do not assume either way; re-run a bare "
                          "dry-run when AWS answers."}
    shape = live_shape(after, five)
    names = _column_names(after)
    version_before = None if before is None else str(before.get("VersionId"))
    version_after = str(after.get("VersionId"))
    moved = version_before is not None and version_after != version_before
    present = [n for n, _ in five if n in names]
    if shape == AT_TARGET and (moved or version_before is None):
        status = APPLIED
        detail = (f"VersionId {version_before} -> {version_after}; all {len(five)} column(s) are"
                  " at "
                  f"the tail as double ({len(names)} columns); UpdateTime "
                  f"{_iso(after.get('UpdateTime'))}")
    elif shape == AT_SOURCE and not moved:
        status = NOT_APPLIED
        detail = (f"VersionId {version_after} (unchanged); {len(names)} columns and none of the "
                  f"five present; UpdateTime {_iso(after.get('UpdateTime'))}")
    else:
        status = UNKNOWN
        detail = (f"live VersionId {version_after} (this run read {version_before} before it "
                  f"started); {len(present)} of {len(five)} new column(s) present; shape={shape} "
                  f"({describe_shape(after, five)}); UpdateTime {_iso(after.get('UpdateTime'))}. "
                  "This is neither a clean apply nor an untouched table -- read it before doing "
                  "anything else.")
    return {"table": TABLE, "status": status, "version_id": version_after, "after": after,
            "version_before": version_before, "shape": shape, "detail": detail}


def _report_the_truth(staged, *, glue, database: str, direction: str, migrations_dir: Path,
                      fencing_token=None, exc: BaseException = None) -> None:
    """RE-READ the table from live Glue and print what actually happened.

    It answers from the catalog, and it does three things a printed traceback cannot: it names the
    table APPLIED / NOT APPLIED / UNKNOWN with the live VersionId; it appends a table the re-read
    proves APPLIED to ``_MUTATED``, so the exit summary cannot say "nothing was mutated" while the
    catalog has moved; and it WRITES THE MISSING MANIFEST for an applied table whose record never
    got written. Read-only on AWS (get_table) plus a local file write."""
    del _VERDICTS[:]
    print()
    print(_rule("="))
    print("WHAT ACTUALLY HAPPENED -- the table RE-READ from live Glue")
    print(_rule("="))
    if exc is not None:
        print(f"  the failure   : {type(exc).__name__}: {exc}")
    print("  This runbook does NOT infer what moved from where the exception fired. An exception")
    print("  can escape AFTER glue.update_table has returned -- MEASURED 2026-09-10 04:07Z on the")
    print("  sibling catalog runbook, when the migration-manifest writer raised on a datetime and")
    print("  the owner was told nothing was mutated while the catalog had already moved. The line")
    print("  below is a fresh glue.get_table issued just now.")
    if direction == "ROLLBACK":
        print()
        print("  DIRECTION IS ROLLBACK, so read the words accordingly: APPLIED means the REVERSE")
        print("  plan landed and the table is 12 columns again; NOT APPLIED means it is still 17.")
    print()
    for live, _desired, plan, five in staged:
        verdict = table_verdict(live, five, glue=glue, database=database)
        _VERDICTS.append(verdict)
        print(f"  {TABLE:<22} {verdict['status']:<12} -- {verdict['detail']}")
        if verdict["status"] == APPLIED and TABLE not in _MUTATED:
            _MUTATED.append(TABLE)
        if verdict["status"] != APPLIED or direction == "ROLLBACK":
            continue
        existing = _applied_manifest(migrations_dir)
        if existing is not None:
            print(f"    machine manifest already on disk: {existing}")
            continue
        try:
            path = write_applied_manifest(
                after=verdict["after"], five=five, database=database,
                migrations_dir=migrations_dir, plan=plan, fencing_token=fencing_token,
                backup={"table": TABLE, "captured_at": _iso(live.get("UpdateTime")),
                        "source": "the PRE-APPLY glue.get_table this run froze before it issued "
                                  "update_table (the same TableInput the plan was cut from)",
                        "catalog_hash": plan.live_hash,
                        "version_id": str(live.get("VersionId")),
                        "table_input": raw_snapshot_to_table_input(live)},
                reconstructed_note=(
                    "WRITTEN FROM A POST-FAILURE RE-READ, not by the mutation. "
                    f"{'' if exc is None else type(exc).__name__ + ' '}"
                    "escaped CatalogMigrator.apply_table after glue.update_table had already "
                    "returned, so the manifest the apply would have written was never written. "
                    "applied_at is the LIVE UpdateTime, post_apply is the re-read, and backup is "
                    "the pre-apply TableInput frozen by this run."))
            print(f"    manifest WRITTEN from the re-read: {path}")
        except Exception as werr:                                                # noqa: BLE001
            print(f"    could not write the manifest ({type(werr).__name__}: {werr}) -- the "
                  "catalog HAS moved; record it by hand.")
    print()
    moved = [v["table"] for v in _VERDICTS if v["status"] == APPLIED]
    unsure = [v["table"] for v in _VERDICTS if v["status"] == UNKNOWN]
    todo = [v["table"] for v in _VERDICTS if v["status"] == NOT_APPLIED]
    print(f"  MOVED      : {', '.join(moved) if moved else '(none)'}")
    print(f"  NOT MOVED  : {', '.join(todo) if todo else '(none)'}")
    print(f"  UNKNOWN    : {', '.join(unsure) if unsure else '(none)'}")
    if moved and direction != "ROLLBACK":
        print()
        print("  TO UNDO the mutation that DID land:")
        print("    python scripts/ops/esr_f030_compact_alter_runbook.py --rollback")


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------
def apply(*, region: str, database: str, bucket: str, lease_prefix: str, lease_id: str,
          direction: str = "ADD", glue_client=None, s3_client=None,
          migrations_dir: Path = None) -> int:
    import boto3

    glue = glue_client if glue_client is not None else _glue_client(region)
    s3 = s3_client if s3_client is not None else boto3.client("s3", region_name=region)
    migrations_dir = migrations_dir or MIGRATIONS_DIR
    del _MUTATED[:]
    del _VERDICTS[:]
    state, five = five_from_registry()
    auth = Authorization(mode=PublishMode.CANONICAL, may_mutate_canonical=True, readiness=False,
                         reason=f"SILVER-F030 BF-W2 compact ADD COLUMNS (owner {direction})")
    print(_rule("="))
    print(f"APPLY [{direction}] -- this MUTATES the Glue catalog.")
    print(f"  table: {database}.{TABLE}   ({REFUSED_TABLE} is never touched by this runbook)")
    print("  guard: an Authorization(mode=canonical) constructed by this runbook, plus a REAL S3")
    print("         lease fence rechecked immediately before update_table. No parquet object is")
    print("         read or written by this path.")
    print(f"  precondition: reconcile_schema_widen=True on the RUNNING producer image -- MEASURED "
          f"at {MEASURED['producer_flag_commit']}:")
    print(f"         {MEASURED['producer_flag_file']}:{MEASURED['producer_flag_line']} "
          f"(publish_esr_compact, line {MEASURED['producer_flag_func_line']}), and "
          f"{MEASURED['lane_c_commit']} is an ancestor of it.")
    if direction == "ROLLBACK":
        print("  path : CatalogMigrator.restore_table -- NOT apply_table, which refuses every")
        print("         column DROP. The override is bounded to exactly these five columns.")
    print(_rule("="))

    # ---- preflight: every precondition, BEFORE any mutation ----------------------------------
    live, source = read_table(offline=False, glue_client=glue, database=database)
    shape = live_shape(live, five)
    assert_registry_not_ahead(state, shape, live, five, direction)
    if direction != "ROLLBACK" and shape == AT_TARGET:
        # IDEMPOTENCE. Already done is not a precondition failure -- and refusing it would make a
        # half-finished run unfinishable by the same command. WIDEN ONLY: a --rollback that quietly
        # no-ops is a rollback an owner believes happened.
        print(f"  ALREADY WIDE: {TABLE} (VersionId {live.get('VersionId')}, UpdateTime "
              f"{_iso(live.get('UpdateTime'))}) -- skipping.")
        for name, glue_type in five:
            print(f"    {name:<36} (absent) -> {glue_type:<8} [already {glue_type}]")
        record = _applied_manifest(migrations_dir)
        if record is not None:
            print(f"    applied record already on disk: {record.name}")
        else:
            basis = pre_apply_basis(five)
            path = write_applied_manifest(
                after=live, five=five, database=database, migrations_dir=migrations_dir,
                backup={"table": TABLE, "captured_at": None, "source": basis["source"],
                        "certifying_field": basis["field"], "catalog_hash": basis["catalog_hash"],
                        "table_input": basis["table_input"],
                        "unavailable_reason": basis["reason"]},
                reconstructed_note=(
                    "RECONSTRUCTED: the table was already at its target shape when the run reached "
                    "it and carried no applied machine manifest, so the ALTER landed in some "
                    "earlier run whose record was never written. applied_at is the LIVE "
                    "UpdateTime, post_apply is a read of the live table, and the backup is the "
                    "pre-apply TableInput certified by the source named in backup.source (the "
                    "narrow-basis precedence: the tracked machine manifest, else the R0 record)."))
            print(f"    applied record RECONSTRUCTED: {path}")
            if not basis["verified"]:
                print(f"    WARNING: the pre-apply backup could not be certified -- "
                      f"{basis['reason']}")
        print()
        print(_rule("="))
        print("NOTHING TO DO -- the catalog is ALREADY WIDE. No lease was taken, no")
        print("glue.update_table was issued.")
        print(_rule("="))
        print_post_apply_steps()
        return 0
    if shape == MIXED:
        raise Refused(f"{TABLE}: live Glue is neither the measured pre-ALTER shape nor the target "
                      f"-- {describe_shape(live, five)}. REFUSED.")

    if direction == "ROLLBACK":
        desired = narrow_table_input(live, five)
    else:
        desired = widen_table_input(live, five)
    assert_shape_preserved(live, desired, five, direction)
    mig = CatalogMigrator(database=database, auth=auth, glue_client=glue,
                          migrations_dir=migrations_dir, raw_snapshot_dir=R0_RAW)
    plan = build_plan(live, desired, mig, database, direction)
    overridden = check_unsafe(plan, five, direction)
    if len(plan.diffs) != 1 or not plan.diffs[0].startswith("columns:"):
        raise Refused(f"{TABLE}: expected exactly one `columns:` diff, got {plan.diffs}")
    if direction == "ROLLBACK":
        detail = (f"live carries {len(_column_names(live))} non-partition column(s) with the five "
                  f"at the tail; this plan removes them, back to {len(_column_names(desired))}")
    else:
        detail = (f"live carries {len(_column_names(live))} non-partition column(s), "
                  f"{ANCHOR_COLUMN!r} last, none of the five present; this plan appends them, to "
                  f"{len(_column_names(desired))}")
    print(f"  preflight OK: {TABLE}  -- {detail}.")
    print(f"                VersionId {live.get('VersionId')}; source={source}")
    for u in overridden:
        print(f"    bounded DROP override: {u}")
    staged = [(live, desired, plan, five)]
    print()

    lease = Lease(bucket=bucket, prefix=lease_prefix, lock_id=lease_id, s3_client=s3)
    state_ = lease.acquire()
    print(f"  lease ACQUIRED s3://{bucket}/{lease.key}  owner={state_.owner} "
          f"token={state_.fencing_token} expires={state_.expires_at}")
    truth = dict(glue=glue, database=database, direction=direction,
                 migrations_dir=migrations_dir, fencing_token=state_.fencing_token)
    try:
        # ONE try around the whole body -- the mutation, the post-read and the printing. Anything
        # that escapes has to answer "what moved?", and the only honest answer is a fresh read.
        try:
            mig.lease = lease
            mig.fencing_token = state_.fencing_token
            before_version = live.get("VersionId")
            if direction == "ROLLBACK":
                result = mig.restore_table(TABLE, snapshot=desired,
                                           expected_current_hash=plan.live_hash)
            else:
                result = mig.apply_table(plan)
            after, _src = read_table(offline=False, glue_client=glue, database=database)
            after_types = _column_types(after)
            if TABLE not in _MUTATED:
                _MUTATED.append(TABLE)
            record = None
            if direction == "ROLLBACK":
                record = _write_rollback_record(plan, live, result, migrations_dir)
            print()
            print(_rule("="))
            print(f"{'ROLLED BACK' if direction == 'ROLLBACK' else 'APPLIED'} {TABLE}")
            print(_rule("="))
            if direction == "ROLLBACK":
                print(f"  restored      : {result.get('restored')}")
                print(f"  verified hash : {result.get('verified_hash')}")
                print("    (restore_table re-read the table and asserted this equals the hash of")
                print(f"     the narrow TableInput it wrote: {plan.desired_hash})")
                print(f"  record        : {record}")
            else:
                print(f"  manifest      : {result.get('manifest')}")
                print(f"  backup hash   : {result.get('backup_hash')}")
            print(f"  VersionId     : {before_version}  ->  {after.get('VersionId')}")
            print(f"  UpdateTime    : {_iso(live.get('UpdateTime'))}  ->  "
                  f"{_iso(after.get('UpdateTime'))}")
            print(f"  columns       : {len(_column_names(live))}  ->  {len(_column_names(after))}")
            bad = []
            expected_after = AT_SOURCE if direction == "ROLLBACK" else AT_TARGET
            for name, glue_type in five:
                got = after_types.get(name)
                if direction == "ROLLBACK":
                    ok = "OK (gone)" if got is None else "MISMATCH (still present)"
                    if got is not None:
                        bad.append((name, "(absent)", got))
                else:
                    ok = "OK" if got == glue_type else "MISMATCH"
                    if got != glue_type:
                        bad.append((name, glue_type, got))
                print(f"    {name:<36} {str(got):<10} [{ok}]")
            shape_after = live_shape(after, five)
            if shape_after != expected_after:
                bad.append(("<table shape>", expected_after, shape_after))
            # Compare the MANAGED parameter set: Glue may rewrite transient_lastDdlTime on any
            # update_table, and a cosmetic key must never send the owner to a rollback.
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
                for name, want, got in bad:
                    print(f"    {name}: expected {want}, live says {got}")
                if direction == "ROLLBACK":
                    print("  The ROLLBACK itself did not verify. Do NOT run the post-apply steps.")
                    print("  Re-read the table and compare against the record written above:")
                    print("  python scripts/ops/esr_f030_compact_alter_runbook.py")
                else:
                    print("  Roll back now:")
                    print("  python scripts/ops/esr_f030_compact_alter_runbook.py --rollback")
                _report_the_truth(staged, exc=None, **truth)
                return 3
        except Exception as exc:                                                 # noqa: BLE001
            _report_the_truth(staged, exc=exc, **truth)
            raise
    finally:
        lease.release()
        print()
        print(f"  lease RELEASED s3://{bucket}/{lease.key}")

    if direction == "ROLLBACK":
        print_post_rollback_steps()
    else:
        print_post_apply_steps()
    return 0


# ---------------------------------------------------------------------------
# verify-read
# ---------------------------------------------------------------------------
def verify_read(*, region: str, database: str, client=None, runner=None,
                sql: str = None) -> int:
    """Prove the EXISTING objects are readable under the CURRENT catalog. One bounded query.

    NOTE: this deliberately builds a plain athena client. It must NEVER call
    ``jobs/utils/athena_utils.ensure_catalog()``, which DROPS AND RECREATES tables.

    ``client`` / ``runner`` are injection seams for the deck (the zero-row fail-closed branch is the
    one behaviour here that must be tested, and it cannot be tested against live Athena from a
    read-only lane)."""
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
    sql = sql or VERIFY_SQL
    print()
    print(_rule("="))
    print(f"VERIFY READ {TABLE}")
    print(_rule("="))
    print(f"  SQL: {sql}")
    print(f"  probe partition: commodity={PROBE_COMMODITY} as_of_date={PROBE_AS_OF} -- MEASURED "
          f"2026-09-10 to hold exactly one object,")
    print(f"    {MEASURED['newest_object']} ({MEASURED['newest_object_bytes']:,} bytes, written "
          f"{MEASURED['newest_object_written']}).")
    try:
        rows = run_query(client, sql, database=database)
    except Exception as exc:                       # noqa: BLE001 -- the failure IS the result
        print(f"  FAILED: {exc}")
        print("  The existing objects do NOT read under the current catalog. ROLL BACK:")
        print("  python scripts/ops/esr_f030_compact_alter_runbook.py --rollback")
        return 3
    if not rows:
        # FAIL CLOSED. A partition-filtered query against a partition that is not registered
        # returns zero rows without reading a parquet byte, so an empty result proves nothing about
        # readability -- which is the one thing this probe exists to prove.
        print("  FAILED: 0 rows. An empty result does NOT prove the objects read -- a filter that")
        print("  matches no registered partition returns 0 rows without touching a parquet file.")
        print("  Check the probe partition still holds objects, and if the catalog was just")
        print("  widened, ROLL BACK:")
        print("  python scripts/ops/esr_f030_compact_alter_runbook.py --rollback")
        return 3
    print(f"  OK -- {len(rows)} row(s) returned; the existing objects read.")
    for r in rows[:5]:
        print(f"    {json.dumps(r, sort_keys=True, default=str)[:200]}")
    populated = [n for n in FIVE_NAMES
                 if any(str(r.get(n, "")).strip() not in ("", "None", "null") for r in rows)]
    print()
    print(f"  of the five, {len(populated)} read non-NULL in this sample: "
          f"{populated if populated else '(none)'}")
    print("  READ THAT CAREFULLY -- IT IS NOT A VERDICT ON THE DATA, IN EITHER DIRECTION. This")
    print("  runbook predicted all-NULL between the ALTER and the promote, on the reasoning that")
    print("  Athena resolves a registered partition's columns from the PARTITION descriptor and")
    print(f"  all {MEASURED['registered_partitions']} of them still declare "
          f"{MEASURED['live_columns']} columns. THE DESCRIPTORS DO -- MEASURED")
    print(f"  {MEASURED['measured_post_alter_on']} by glue.get_partitions, "
          f"{MEASURED['registered_partitions_at_12_columns_post_alter']} of "
          f"{MEASURED['registered_partitions']}, this probe's partition included. THE")
    print(f"  PREDICTION DOES NOT: MEASURED 2026-09-10 this probe returned "
          f"{MEASURED['verify_read_rows']} rows, and")
    print(f"  {MEASURED['verify_read_non_null_of_five']} of the five read NON-NULL over that "
          "12-column descriptor. So all-NULL would not mean the")
    print("  ALTER failed, and non-NULL does not mean the promote has run. What this probe proves")
    print("  is that the objects READ; the partition repair is still owed until step [5].")
    return 0


# ---------------------------------------------------------------------------
# record-applied
# ---------------------------------------------------------------------------
def record_applied(*, region: str, database: str, glue_client=None,
                   migrations_dir: Path = None) -> int:
    """RECONSTRUCT the machine manifest for an ALTER that IS on the catalog but was never recorded.

    READ-ONLY ON AWS: one ``glue.get_table``, plus a LOCAL file write. It mutates nothing.

    IT PROVES BEFORE IT WRITES, and refuses (exit 2) rather than assert:
      * the live table must actually be at the 17-column target;
      * the live ``catalog.hash_table`` digest must equal the hash the plan WOULD have produced
        from the certified pre-apply table -- i.e. the catalog is EXACTLY the table this migration
        planned, not merely a table with five extra columns;
      * no applied machine manifest may already exist.
    Exit 3 means the record was written but the pre-apply backup could not be certified."""
    glue = glue_client if glue_client is not None else _glue_client(region)
    migrations_dir = migrations_dir or MIGRATIONS_DIR
    _state, five = five_from_registry()

    print(_rule("="))
    print(f"RECORD APPLIED [{TABLE}] -- reconstruct the machine manifest for an ALTER that landed")
    print(_rule("="))
    print("  READ-ONLY on AWS: one glue.get_table. The only write is a local JSON file under")
    print(f"  {migrations_dir}.")
    print()

    existing = _applied_manifest(migrations_dir)
    if existing is not None:
        raise Refused(
            f"{TABLE}: an applied machine manifest already exists -- {existing}\n"
            "  There is nothing to reconstruct. Read that file; do not write a second record of "
            "the same mutation.")

    live, _src = read_table(offline=False, glue_client=glue, database=database)
    shape = live_shape(live, five)
    types = _column_types(live)
    print(f"  live VersionId : {live.get('VersionId')}")
    print(f"  live UpdateTime: {_iso(live.get('UpdateTime'))}")
    print(f"  live columns   : {len(_column_names(live))}")
    for name, glue_type in five:
        got = types.get(name)
        print(f"    {name:<36} {str(got):<10} [{'PRESENT' if got == glue_type else 'ABSENT'}]")
    if shape != AT_TARGET:
        raise Refused(
            f"{TABLE}: the catalog is not at the target shape (shape={shape}; "
            f"{describe_shape(live, five)}) -- there is no applied ALTER to record. Apply it "
            "first:\n  python scripts/ops/esr_f030_compact_alter_runbook.py --apply")

    basis = pre_apply_basis(five)
    live_hash = catalog.hash_table(live)
    print()
    print("  PRE-APPLY BASIS (what a rollback would restore, and what certifies it)")
    print("    precedence       :")
    for line in NARROW_BASIS_PRECEDENCE:
        print(f"      {line}")
    print(f"    record           : {basis['record']}")
    print(f"    source           : {basis['source']}")
    print(f"    certifying field : {basis['field']}")
    print(f"    that field says  : {basis['expected']}")
    print(f"    recomputed       : {basis['got']}")
    print(f"    certified        : {'YES' if basis['verified'] else 'NO'}")
    if not basis["verified"]:
        print(f"    reason           : {basis['reason']}")
    print()
    print(f"  live catalog hash                    : {live_hash}")
    print(f"  the hash this migration would produce: {basis['planned_desired_hash']}")
    print("  live == the planned post-ALTER table  : "
          f"{'YES' if live_hash == basis['planned_desired_hash'] else 'NO'}")
    if basis["verified"] and live_hash != basis["planned_desired_hash"]:
        raise Refused(
            f"{TABLE}: live hashes to {live_hash} but this migration planned "
            f"{basis['planned_desired_hash']}. The catalog carries the five but it is NOT the "
            "table this migration planned, so this run will not claim it is. Re-measure before "
            "recording anything.")

    path = write_applied_manifest(
        after=live, five=five, database=database, migrations_dir=migrations_dir,
        backup={"table": TABLE, "captured_at": None, "source": basis["source"],
                "certifying_field": basis["field"], "catalog_hash": basis["catalog_hash"],
                "table_input": basis["table_input"], "unavailable_reason": basis["reason"]},
        reconstructed_note=(
            "RECONSTRUCTED BY --record-applied, not written by the mutation. applied_at is the "
            "LIVE UpdateTime -- when the catalog actually moved, not when this record was made. "
            "post_apply is a fresh read of live Glue; the backup is the pre-apply TableInput "
            "certified by its own source's stored digest -- the tracked machine manifest's "
            "backup.catalog_hash, or (before the ALTER) the R0 record's digest under the recipe "
            "it stamps."))
    print()
    print(f"  RECORD WRITTEN: {path}")
    print("    applied      : true")
    print(f"    applied_at   : {_iso(live.get('UpdateTime'))}  (the live UpdateTime)")
    print("    rollback     : python scripts/ops/esr_f030_compact_alter_runbook.py --rollback")
    print()
    print("  NOTHING WAS MUTATED IN AWS by this command. The Glue catalog was read, never written.")
    if not basis["verified"]:
        print()
        print("  EXIT 3: the record exists, but WITHOUT a certified pre-apply backup. The rollback")
        print("  command above still works (it removes the five from the LIVE table and never")
        print("  reads this file), but this record cannot hand a restorer the original TableInput.")
        return 3
    return 0


# ---------------------------------------------------------------------------
def _mutation_status(prefix: str) -> str:
    """Never tell an owner 'nothing was mutated' when something was, and never claim certainty the
    runbook does not have."""
    unknown = [v["table"] for v in _VERDICTS if v["status"] == UNKNOWN]
    if not _MUTATED and not unknown:
        return f"{prefix} -- nothing was mutated by this runbook."
    if not _MUTATED:
        return (f"{prefix} -- the re-read could NOT establish the state of {TABLE}. Do not assume "
                "nothing moved. Re-read it (a bare dry-run does that) before deciding anything.")
    return (f"{prefix} -- BUT the catalog WAS ALREADY MUTATED by this run: "
            f"{', '.join(_MUTATED)}. See the RE-READ report above for the verdict; a mutated "
            "table's machine manifest has been written from that re-read. Re-read the table (a "
            "bare dry-run does that and refuses if the shape is not what it expects) before "
            "deciding whether to continue or to roll back.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="SILVER-F030 BF-W2 silver_esr_compact ADD COLUMNS -- dry-run by default")
    ap.add_argument("--table", default=TABLE,
                    help=f"the table to act on. Only {TABLE} is applicable; {REFUSED_TABLE} is a "
                         "hard-coded refusal with the migration file's reasons quoted")
    ap.add_argument("--dry-run", action="store_true",
                    help="the default; also FORCES plan-only when combined with --apply/--rollback "
                         "(the way to preview the reverse plan)")
    ap.add_argument("--apply", action="store_true",
                    help="OWNER: apply the ADD COLUMNS (mutates Glue)")
    ap.add_argument("--rollback", action="store_true",
                    help="OWNER: drop the five again (restore the pre-apply TableInput)")
    ap.add_argument("--verify-read", action="store_true", dest="verify_read",
                    help="run the bounded read probe against the CURRENT catalog")
    ap.add_argument("--record-applied", action="store_true", dest="record_applied",
                    help="reconstruct the machine manifest for an ALTER that IS on the catalog but "
                         "was never recorded. READ-ONLY on AWS -- one get_table plus a local file "
                         "write; refuses unless the table is provably at the planned wide state")
    ap.add_argument("--offline", action="store_true",
                    help="dry-run AWS-free, against the tracked machine manifest for this table "
                         "(or, before the ALTER lands, the R0 record) -- the source's own digest "
                         "is RE-VERIFIED before anything is planned")
    ap.add_argument("--offline-dir", default=None, dest="offline_dir",
                    help="with --offline: read <dir>/silver_esr_compact.get-table.json instead of "
                         "the resolved offline source. A DRY-RUN SOURCE ONLY (it cannot back a "
                         "mutation) -- it exists so the reverse plan can be exercised against a "
                         "simulated post-apply catalog without touching AWS")
    ap.add_argument("--database", default=DATABASE)
    ap.add_argument("--region", default=REGION)
    ap.add_argument("--lease-bucket", default=BUCKET, dest="lease_bucket")
    ap.add_argument("--lease-prefix", default=LEASE_PREFIX, dest="lease_prefix")
    ap.add_argument("--lease-id", default=LEASE_ID, dest="lease_id")
    args = ap.parse_args(argv)

    # --dry-run always wins: it is how an operator previews the REVERSE plan without mutating.
    mutating = (args.apply or args.rollback) and not args.dry_run
    if args.apply and args.rollback:
        print("REFUSED: --apply and --rollback are mutually exclusive.")
        return 2
    if mutating and (args.offline or args.offline_dir):
        print("REFUSED: an offline snapshot is a dry-run source; it cannot back a mutation.")
        return 2
    if args.record_applied and (args.apply or args.rollback or args.verify_read or args.offline):
        print("REFUSED: --record-applied is a standalone, read-only mode; it does not combine "
              "with --apply, --rollback, --verify-read or --offline.")
        return 2

    try:
        assert_table_allowed(args.table)
        if args.record_applied:
            return record_applied(region=args.region, database=args.database)
        if args.verify_read:
            return verify_read(region=args.region, database=args.database)
        if mutating:
            return apply(region=args.region, database=args.database, bucket=args.lease_bucket,
                         lease_prefix=args.lease_prefix, lease_id=args.lease_id,
                         direction="ROLLBACK" if args.rollback else "ADD")
        return dry_run(offline=bool(args.offline or args.offline_dir), region=args.region,
                       database=args.database,
                       direction="ROLLBACK" if args.rollback else "ADD",
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


if __name__ == "__main__":
    sys.exit(main())
