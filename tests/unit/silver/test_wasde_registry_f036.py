"""SILVER-F036 -- the WASDE additive schema + int64 fix + migration plan (registry side).

Asserts the registry contract carries the F036 target schema without breaking the
registry-vs-live-Glue invariant, and that the plan-only catalog migration cut by
``scripts/silver/wasde_f036_migration_plan.py`` is a coherent additive + reviewed-int64 change with
the F013 registered-partition audit. AWS-free (the plan runs against the R0 _raw snapshot with a
frozen in-memory glue client). No catalog is mutated.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from leviathan.silver import ddl as D
from leviathan.silver.registry import check_illegal_type_change, load_registry
from leviathan.transforms.bronze_to_silver import usda_wasde_silver as W

_REPO = Path(__file__).resolve().parents[3]
_PLAN_SCRIPT = _REPO / "scripts" / "silver" / "wasde_f036_migration_plan.py"

# The 9 additive governed columns + their INV-2 target arrow types (F036 / plan L585).
_ADDITIVE = {
    "source_table_id": "string",
    "estimate_role": "string",
    "projection_month": "string",
    "is_current_release_estimate": "bool",
    "release_sequence": "int64",
    "revision_gap_days": "int64",
    "is_projection": "bool",
    "is_source_final": "bool",
    "marketing_year_end_date": "string",
}


@pytest.fixture(scope="module")
def contract():
    return load_registry().table("silver_wasde")


@pytest.fixture(scope="module")
def plan_mod():
    spec = importlib.util.spec_from_file_location("wasde_f036_migration_plan", _PLAN_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["wasde_f036_migration_plan"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# The additive schema is present but hidden (registry == live-Glue invariant holds).
# ---------------------------------------------------------------------------
def test_additive_columns_present_as_hidden_schema(contract):
    # POST-F036 (BF-W2 step 17 applied 2026-07-15): the columns are REGISTERED in Glue -- concrete
    # glue types matching the live catalog (registry == live-Glue invariant). arrow_type stays None
    # until the physical sample carries them (the step-23 catch-up publishes the first 29-col
    # objects); the transitional lag is recorded as null_typed drift rows, asserted below.
    _GLUE = {"string": "string", "bool": "boolean", "int64": "bigint"}
    by = {c["name"]: c for c in contract["physical_columns"]}
    drift_cols = {d["column"] for d in contract["drift_summary"] if d["kind"] == "null_typed"}
    for name, target in _ADDITIVE.items():
        assert name in by, f"{name} missing from the registry contract"
        assert by[name]["target_arrow_type"] == target
        assert by[name]["glue_type"] == _GLUE[target]
        assert by[name]["nullable"] is True
        assert name in drift_cols, f"{name} physical-lag drift row missing"


def test_additive_columns_excluded_from_generated_ddl(contract):
    """POST-F036: the migration applied, so the additive columns are catalog columns -- the DDL
    carries all 29 (registry == live-Glue invariant, now at the post-migration state)."""
    catalog_names = {n for n, _ in D.catalog_columns(contract)}
    assert set(_ADDITIVE).issubset(catalog_names)
    assert set(D.physical_only_columns(contract)) == set()
    assert set(_ADDITIVE).issubset(load_registry().columns("silver_wasde"))


def test_deprecated_compat_columns_flagged(contract):
    by = {c["name"]: c for c in contract["physical_columns"]}
    assert by["is_final_or_latest"].get("deprecated") is True
    assert by["months_to_marketing_year_end"].get("deprecated") is True
    # they are RETAINED (not dropped) as compatibility columns.
    assert by["is_final_or_latest"]["glue_type"] == "boolean"


def test_int64_drift_retained_with_migration_note(contract):
    # POST-F036: glue (bigint) == physical (int64) == target -- the C-WRONG-6 mismatch is CLOSED,
    # so NO glue_catalog_mismatch row may remain (a reappearing row = catalog regression).
    mm = [d for d in contract["drift_summary"]
          if d["column"] == "months_to_marketing_year_end" and d["kind"] == "glue_catalog_mismatch"]
    assert mm == [], f"C-WRONG-6 reopened: {mm}"
    col = {c["name"]: c for c in contract["physical_columns"]}["months_to_marketing_year_end"]
    assert col["glue_type"] == "bigint" and col["arrow_type"] == "int64"


def test_frozen_natural_key_matches_transform_and_is_coherent(contract):
    # the registry natural key == the transform's frozen F033 key ...
    assert tuple(contract["natural_key"]) == W.NATURAL_KEY
    # ... and every key component is a declared column (coherent after the additive columns land).
    cols = load_registry().columns("silver_wasde")
    for k in contract["natural_key"]:
        assert k in cols, f"natural key component {k} is not a declared column"


# ---------------------------------------------------------------------------
# The plan-only catalog migration.
# ---------------------------------------------------------------------------
def test_migration_plan_is_additive_with_reviewed_int64(plan_mod):
    out = plan_mod.cut_plan()
    p = out["plan"]
    assert p["change_type"] == "additive_update"
    added = {a["name"] for a in out["column_changes"]["added"]}
    assert added == set(_ADDITIVE)                          # the 9 governed columns are catalog adds
    changes = {c["name"]: (c["from"], c["to"]) for c in out["column_changes"]["type_changes"]}
    assert changes == {"months_to_marketing_year_end": ("int", "bigint")}   # the int64 fix
    # the int->bigint correction is surfaced as a REVIEWED (not auto-apply) item, never silent.
    assert any("months_to_marketing_year_end" in u for u in p["unsafe"])


def test_migration_plan_flags_the_461_partition_repair(plan_mod):
    p = plan_mod.cut_plan()["plan"]
    audit = p["registered_partition_audit"]
    assert audit["registered"] is True
    assert "F013" in audit["action"]


def test_target_contract_has_no_narrowing_from_live(plan_mod, contract):
    """The additive columns + the int64 target are a WIDENING/add, never a narrowing (the loader's
    illegal-type-change guard is clean between the live and target contracts)."""
    target = plan_mod.build_target_contract(contract)
    assert check_illegal_type_change(contract, target) == []


def test_target_ddl_renders_bigint_and_29_columns(plan_mod, contract):
    target = plan_mod.build_target_contract(contract)
    ddl = D.render_ddl(target)
    assert "months_to_marketing_year_end bigint" in ddl
    cols = D.catalog_columns(target)
    assert len(cols) == 29                                   # 20 legacy + 9 additive now cataloged
    assert ("source_table_id", "string") in cols
    assert "PARTITIONED BY (release_date string)" in ddl
    assert "'projection." not in ddl                         # never re-projected (INV-3)


# ---------------------------------------------------------------------------
# Numbers-registry coordination (period_sql_type + pg type doctrine).
# ---------------------------------------------------------------------------
def test_numbers_registry_period_type_is_string_and_consistent():
    import yaml

    doc = yaml.safe_load((_REPO / "configs" / "graphrag" / "numbers" / "tables.yaml")
                         .read_text(encoding="utf-8"))
    wasde = doc["tables"]["silver_wasde"]
    # marketing_year is a string like '2023/24' -> period_sql_type stays string (no int coercion),
    # consistent with the string marketing_year column in the silver contract.
    assert wasde["period_sql_type"] == "string"
    assert wasde["period_col"] == "marketing_year"
    assert wasde["value_col"] == "estimate"
