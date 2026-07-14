"""SILVER-F024 / BF-W2 step 3 (runbook Deviation 9): the CONAB registry glue_type flip.

CatalogMigrator._glue_columns does NOT drop glue_type-null columns, so an F024 additive apply
from a null-typed registry would send ``Type: null`` x12 to Glue update_table (fail-closed
reject). These tests pin the fix: the checked-in registry carries the F024 ADD COLUMNS TARGET
(22 catalog-typed columns), byte-consistent with the gated migration artifact
``reports/silver_readiness/R2_SA/F024_conab_additive_migration.json``, and CatalogMigrator now
plans a valid additive update against the live 10-col catalog (the R0 ``_raw`` snapshot).

AWS-free: real registry + real R0 snapshot + the in-memory FakeGlue.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from leviathan.silver import ddl as D
from leviathan.silver.migrate import (
    CatalogMigrator,
    ChangeType,
    build_desired_table,
    raw_snapshot_to_table_input,
)
from leviathan.silver.registry import load_registry

from tests.unit.silver.conftest import canonical_authorization, dryrun_authorization

_REPO = Path(__file__).resolve().parents[3]
_F024_ARTIFACT = (
    _REPO / "reports" / "silver_readiness" / "R2_SA" / "F024_conab_additive_migration.json"
)
_RAW_SNAPSHOT = (
    _REPO / "reports" / "silver_readiness" / "20260712_p65impl" / "_raw"
    / "silver_conab_coffee.get-table.json"
)
_TABLE = "silver_conab_coffee"

# Athena/Glue type tokens legal for this table's columns (guards against any null/None leak).
_VALID_GLUE_TYPES = {"string", "double", "bigint", "boolean"}


@pytest.fixture(scope="module")
def reg():
    return load_registry()


@pytest.fixture(scope="module")
def f024():
    return json.loads(_F024_ARTIFACT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def contract(reg):
    return reg.table(_TABLE)


# ---------------------------------------------------------------------------
# Registry <-> F024 artifact consistency (the step-3 STOP condition).
# ---------------------------------------------------------------------------
def test_registry_has_no_hidden_columns_left(contract):
    """All 22 physical columns are catalog-typed; the hidden-schema (glue_type null) class is gone."""
    assert D.physical_only_columns(contract) == []
    assert len(D.catalog_columns(contract)) == 22


def test_registry_column_order_matches_f024_target(contract, f024):
    names = [n for n, _ in D.catalog_columns(contract)]
    assert names == f024["target"]["glue_nonpartition_columns"]
    assert len(names) == f024["target"]["count"]


def test_flipped_glue_types_match_f024_added_columns_exactly(contract, f024):
    """The 12 flipped columns carry EXACTLY the artifact's target Glue types, in artifact order."""
    reg_types = dict(D.catalog_columns(contract))
    added = [(c["name"], c["glue_type"]) for c in f024["added_columns"]]
    assert [(n, reg_types[n]) for n, _ in added] == added
    # ...and they are the registry tail, preserving the additive ADD COLUMNS order.
    assert [n for n, _ in D.catalog_columns(contract)][10:] == [n for n, _ in added]


def test_generated_ddl_carries_the_22_col_target(contract, f024):
    sql = D.render_ddl(contract)
    got = D.parse_ddl(sql)
    assert [n for n, _ in got.columns] == f024["target"]["glue_nonpartition_columns"]
    for c in f024["added_columns"]:
        assert dict(got.columns)[c["name"]] == c["glue_type"]


# ---------------------------------------------------------------------------
# CatalogMigrator unit probe (Deviation 9): valid Glue types, additive plan, no AWS.
# ---------------------------------------------------------------------------
def _live_10col_glue(fake_glue):
    """Seed FakeGlue with the live 10-col table exactly as captured in the R0 _raw snapshot."""
    snap = json.loads(_RAW_SNAPSHOT.read_text(encoding="utf-8"))
    live = raw_snapshot_to_table_input(snap)
    assert len(live["StorageDescriptor"]["Columns"]) == 10  # precondition: pre-F024 catalog
    fake_glue.tables[_TABLE] = live
    return live


def test_desired_table_never_emits_null_types(reg, contract):
    """The Deviation 9 regression pin: no ``Type: null`` in the desired TableInput."""
    desired = build_desired_table(contract)
    cols = desired["StorageDescriptor"]["Columns"]
    assert len(cols) == 22
    for c in cols:
        assert isinstance(c["Type"], str) and c["Type"] in _VALID_GLUE_TYPES, c


def test_migrator_plans_valid_additive_update_from_live_10col(fake_glue, reg, f024):
    _live_10col_glue(fake_glue)
    mig = CatalogMigrator(database="leviathan_dev", auth=canonical_authorization(),
                          glue_client=fake_glue, registry=reg)
    plan = mig.plan_table(_TABLE)
    assert plan.change_type is ChangeType.ADDITIVE_UPDATE
    assert plan.unsafe == []  # additive only: no drop / narrow / partition-key change
    cols = plan.table_input["StorageDescriptor"]["Columns"]
    assert [(c["Name"], c["Type"]) for c in cols][10:] == [
        (c["name"], c["glue_type"]) for c in f024["added_columns"]]
    assert all(c["Type"] in _VALID_GLUE_TYPES for c in cols)
    # flat table stays flat: the plan adds columns, never a partition key.
    assert plan.table_input["PartitionKeys"] == []


def test_apply_without_canonical_auth_is_plan_only(fake_glue, reg):
    """Non-canonical mode returns the plan and mutates nothing (the step-5 vehicle is gated)."""
    _live_10col_glue(fake_glue)
    mig = CatalogMigrator(database="leviathan_dev", auth=dryrun_authorization(),
                          glue_client=fake_glue, registry=reg)
    plan = mig.plan_table(_TABLE)
    out = mig.apply_table(plan)
    assert out["applied"] is False and out["reason"] == "non-canonical-plan-only"
    assert ("update_table", _TABLE) not in fake_glue.calls
    assert len(fake_glue.tables[_TABLE]["StorageDescriptor"]["Columns"]) == 10
