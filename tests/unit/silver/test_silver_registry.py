"""SILVER-F010: the registry schema validates all 43 contracts + the loader/structural lints.

AWS-free, no network -- pure file reads under the F002 isolation guard.
"""
from __future__ import annotations

import copy

import pytest

from leviathan.silver import registry as R
from leviathan.silver.types import (
    classify_drift,
    is_narrowing_change,
    target_arrow_type,
)

EXPECTED_TABLE_COUNT = 43  # 42 silver + gold_weather_z


@pytest.fixture(scope="module")
def reg() -> R.SilverRegistry:
    return R.load_registry()


def test_registry_has_exactly_the_live_42_plus_gold(reg):
    names = reg.names()
    assert len(names) == EXPECTED_TABLE_COUNT
    assert "gold_weather_z" in names
    silver = [n for n in names if n.startswith("silver_")]
    assert len(silver) == 42
    # the ESR pair + WASDE + model_predictions are all present (registered surfaces).
    for must in ("silver_esr", "silver_esr_compact", "silver_wasde", "silver_model_predictions"):
        assert must in names


def test_every_contract_validates_against_schema(reg):
    schema = R.load_schema()
    for name in reg.names():
        errors = R.validate_contract(reg.table(name), schema)
        assert errors == [], f"{name}: {errors}"


def test_load_registry_runs_structural_lints_clean(reg):
    # load_registry() raises on any structural problem; reaching here means all passed.
    assert isinstance(reg, R.SilverRegistry)


def test_partition_modes_match_the_r0_tally(reg):
    modes = {"flat": 0, "projected": 0, "registered": 0}
    for name in reg.names():
        modes[reg.table(name)["partition_mode"]] += 1
    # R0 baseline: 28 flat / 10 projected / 4 registered (silver) + 1 flat gold.
    assert modes == {"flat": 29, "projected": 10, "registered": 4}


def test_projection_field_is_quarantined_iff_projected(reg):
    for name in reg.names():
        c = reg.table(name)
        if c["partition_mode"] == "projected":
            assert c["projection"] == "legacy-quarantined", name
        else:
            assert c["projection"] == "forbidden", name


def test_storm_trio_recovery_forbids_athena(reg):
    for name in ("silver_nasa_power", "silver_chirps", "silver_cpc_soil"):
        assert "NEVER start-query-execution" in reg.table(name)["recovery_strategy"]


def test_value_columns_single_authority_present_and_declared(reg):
    # INV-5 single authority: value_columns present for measurement tables + are real columns.
    for name in reg.names():
        c = reg.table(name)
        for vc in c["value_columns"]:
            assert vc in reg.columns(name), f"{name}: value_column {vc} not a declared column"
        if c["value_columns"]:
            assert c["min_nonnull_frac"] is not None
        else:
            assert c["min_nonnull_frac"] is None


def test_esr_compact_pins_inv2_widen_targets(reg):
    """The plan's illustrative contract: physical int16/float, INV-2 target int64/float64."""
    c = reg.table("silver_esr_compact")
    by = {col["name"]: col for col in c["physical_columns"]}
    assert by["commodity_code"]["arrow_type"] == "int16"
    assert by["commodity_code"]["target_arrow_type"] == "int64"
    assert by["weekly_exports_1000mt"]["arrow_type"] == "float"
    assert by["weekly_exports_1000mt"]["target_arrow_type"] == "float64"
    kinds = {(d["column"], d["kind"]) for d in c["drift_summary"]}
    assert ("commodity_code", "widen_int") in kinds
    assert ("weekly_exports_1000mt", "widen_float") in kinds
    assert all(d["owner_package"].startswith("SILVER-F") for d in c["drift_summary"])


def test_wasde_records_glue_catalog_mismatch(reg):
    c = reg.table("silver_wasde")
    mm = [d for d in c["drift_summary"] if d["kind"] == "glue_catalog_mismatch"]
    cols = {d["column"] for d in mm}
    assert "months_to_marketing_year_end" in cols  # C-WRONG-6: glue int32 vs physical int64


def test_wasde_null_typed_column_recorded(reg):
    c = reg.table("silver_wasde")
    nulls = {d["column"] for d in c["drift_summary"] if d["kind"] == "null_typed"}
    assert "prior_release_date" in nulls


def test_every_drift_entry_ties_to_an_r2_package(reg):
    for name in reg.names():
        for d in reg.table(name)["drift_summary"]:
            assert d["owner_package"].startswith("SILVER-F"), (name, d)


def test_vintage_retention_enum_and_esr_per_week(reg):
    for name in reg.names():
        assert reg.table(name)["vintage_retention"] in ("latest-only", "per-vintage", "per-week")
    # BF-W2 SILVER-F031 option-b: both ESR contracts declare per-week as_of vintages (the serving
    # compact gains a REGISTERED as_of_date partition dimension at the gated migration).
    assert reg.table("silver_esr")["vintage_retention"] == "per-week"
    assert reg.table("silver_esr_compact")["vintage_retention"] == "per-week"
    assert reg.table("silver_wasde")["vintage_retention"] == "per-vintage"


def test_producer_metadata_complete(reg):
    for name in reg.names():
        prod = reg.table(name)["producer"]
        assert prod["status"] in ("producer", "half-orphan", "orphan")
        if prod["status"] == "producer":
            assert prod.get("transform") or prod.get("batch_task"), name
    # C-WRONG-8 full orphans.
    assert reg.table("silver_fred_fx")["producer"]["status"] == "orphan"
    assert reg.table("silver_noaa_oni")["producer"]["status"] == "orphan"


# ---------------------------------------------------------------------------
# Structural lint negative tests (synthetic contracts).
# ---------------------------------------------------------------------------
def _minimal_contract(name="silver_test_tbl") -> dict:
    return {
        "table_name": name,
        "layer": "silver",
        "domain": "test",
        "lifecycle_class": "source",
        "owner": "silver-platform",
        "schema_version": 1,
        "glue_database": "leviathan_dev",
        "s3_root": "s3://leviathan-dev-shahem-001/silver/test_tbl",
        "layout": "flat",
        "partition_mode": "flat",
        "projection": "forbidden",
        "partition_keys": [],
        "physical_columns": [
            {"name": "value", "glue_type": "double", "arrow_type": "double",
             "parquet_physical_type": "DOUBLE", "target_arrow_type": "float64", "nullable": True},
        ],
        "natural_key": [],
        "value_columns": ["value"],
        "min_nonnull_frac": 0.5,
        "vintage_retention": "latest-only",
        "consumers": "none",
        "location_mode": "static",
        "producer": {"status": "orphan", "transform": None, "batch_task": None},
        "provenance": {"baseline_id": "t", "generated_from": "t"},
    }


def test_schema_rejects_missing_required_field():
    c = _minimal_contract()
    del c["value_columns"]
    errors = R.validate_contract(c)
    assert any("value_columns" in e for e in errors)


def test_schema_rejects_bad_enum():
    c = _minimal_contract()
    c["vintage_retention"] = "forever"
    errors = R.validate_contract(c)
    assert any("vintage_retention" in e for e in errors)


def test_schema_rejects_additional_property():
    c = _minimal_contract()
    c["surprise"] = 1
    errors = R.validate_contract(c)
    assert any("surprise" in e for e in errors)


def test_structural_lint_flags_unsafe_root():
    c = _minimal_contract()
    c["s3_root"] = "s3://some-other-bucket/silver/test_tbl"
    problems = R._structural_lints(c, "x.yaml")
    assert any("unsafe s3_root" in p for p in problems)


def test_structural_lint_flags_duplicate_column():
    c = _minimal_contract()
    c["physical_columns"].append(dict(c["physical_columns"][0]))
    problems = R._structural_lints(c, "x.yaml")
    assert any("duplicate physical column" in p for p in problems)


def test_structural_lint_flags_producer_without_entrypoint():
    c = _minimal_contract()
    c["producer"] = {"status": "producer", "transform": None, "batch_task": None}
    problems = R._structural_lints(c, "x.yaml")
    assert any("no transform/batch_task" in p for p in problems)


def test_structural_lint_flags_value_frac_incoherence():
    c = _minimal_contract()
    c["min_nonnull_frac"] = None  # value_columns set but no floor
    problems = R._structural_lints(c, "x.yaml")
    assert any("min_nonnull_frac is null" in p for p in problems)


def test_illegal_type_change_detected():
    old = _minimal_contract()
    new = copy.deepcopy(old)
    new["physical_columns"][0]["target_arrow_type"] = "int64"  # float64 -> int64 base change
    viol = R.check_illegal_type_change(old, new)
    assert viol and "illegal type change" in viol[0]
    # a no-op is legal
    assert R.check_illegal_type_change(old, copy.deepcopy(old)) == []


def test_type_helpers_inv2_targets():
    assert target_arrow_type("int16", "smallint") == "int64"
    assert target_arrow_type("float", "float") == "float64"
    assert target_arrow_type("large_string", "string") == "string"
    assert target_arrow_type(None, "date") == "date32[day]"
    assert classify_drift("int16", "smallint") == ["widen_int"]
    assert classify_drift("int64", "int") == ["glue_catalog_mismatch"]
    assert classify_drift(None, "string") == ["null_typed"]
    assert classify_drift("double", "double") == []
    assert is_narrowing_change("int64", "int32") is True
    assert is_narrowing_change("int64", "int64") is False
