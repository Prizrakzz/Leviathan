"""SILVER-F010: the reconciliation lints -- the registry is a SUPERSET that agrees with the live
numbers / cascade / source-contract / features consumer configs. AWS-free.

Acceptance: the numbers-stack lint is CLEAN (no publication_lag / PIT divergence), and every
surviving divergence across all four lints is carried in known_drift.yaml with an R2 owner (so
reconcile_all() minus the allowlist is EMPTY).
"""
from __future__ import annotations

import copy

import pytest

from leviathan.silver import reconcile as RC
from leviathan.silver import registry as R


@pytest.fixture(scope="module")
def reg() -> R.SilverRegistry:
    return R.load_registry()


def test_numbers_reconciliation_is_clean(reg):
    """The F010 acceptance criterion: NO publication_lag / PIT / partition divergence."""
    divs = RC.reconcile_numbers(reg)
    assert divs == [], [d.detail for d in divs]


def test_numbers_tables_matches_tablespec_keys_no_drift():
    """CORRECTION V3 (numbers-depth wave): NUMBERS_TABLES must enumerate EXACTLY the tables.yaml
    TableSpec ids. reconcile_numbers iterates ONLY this tuple, so any tables.yaml table absent here is
    STRUCTURALLY UNCHECKED (its knowledge_date_col / knowledge_semantics / publication_lag_days never
    reconcile against the F010 registry -- a mis-derived lag would ship live while the gate reports
    'clean'). This assertion makes the gap impossible to reopen silently."""
    spec_keys = set(RC._numbers_specs().keys())
    tuple_keys = set(RC.NUMBERS_TABLES)
    assert tuple_keys == spec_keys, (
        f"NUMBERS_TABLES drift -- only-in-tuple={sorted(tuple_keys - spec_keys)}, "
        f"only-in-tables.yaml={sorted(spec_keys - tuple_keys)}")


def test_all_numbers_tables_carry_back_pointers(reg):
    for name in RC.NUMBERS_TABLES:
        c = reg.table(name)
        assert c["numbers_ref"], name
        assert c["consumers"] in ("numbers_registry", "both"), name


def test_numbers_pit_fields_match_tablespec(reg):
    specs = RC._numbers_specs()
    for name in RC.NUMBERS_TABLES:
        c, spec = reg.table(name), specs[name]
        assert c["knowledge_date_col"] == spec.get("knowledge_date_col"), name
        assert c["knowledge_semantics"] == spec.get("knowledge_semantics"), name
        assert c["publication_lag_days"] == spec.get("publication_lag_days"), name
    # BF-W2 SILVER-F031: ESR runs per-week vintage semantics with lag 0 (the as_of stamp IS the
    # publication event) — the pre-flip data_date/+7d pair must NOT resurface via a stale regen.
    assert reg.table("silver_esr")["knowledge_semantics"] == "vintage"
    assert reg.table("silver_esr")["publication_lag_days"] == 0


def test_cascade_refs_all_resolve(reg):
    assert RC.reconcile_cascade(reg) == []


def test_source_contract_columns_and_value_authority(reg):
    divs = RC.reconcile_source_contracts(reg)
    # any divergence must be a real producer/data gap in the known-drift allowlist, never a
    # value_columns/min_nonnull_frac authority leak.
    leaks = [d for d in divs if d.kind == "value_authority_leak"]
    assert leaks == [], leaks
    assert RC.unallowed(divs) == [], [d.detail for d in RC.unallowed(divs)]


def test_features_sources_resolve_to_feature_consumers(reg):
    assert RC.reconcile_features(reg) == []


def test_reconcile_all_minus_known_drift_is_empty(reg):
    divs = RC.reconcile_all(reg)
    residual = RC.unallowed(divs)
    assert residual == [], [d.detail for d in residual]


def test_known_drift_has_no_stale_entries(reg):
    # every allowlist entry must still correspond to a live divergence (no orphaned waivers).
    stale = RC.orphan_allowlist_entries(RC.reconcile_all(reg))
    assert stale == [], stale


def test_value_columns_not_declared_in_source_contracts():
    """Attack 3 finding #6: the silver registry is the SINGLE authority for value_columns /
    min_nonnull_frac -- source_contracts.yaml must not re-declare them."""
    sources = RC._source_contracts()
    for s in sources:
        assert "value_columns" not in s, s.get("source_key")
        assert "min_nonnull_frac" not in s, s.get("source_key")


# ---------------------------------------------------------------------------
# The lints actually FIRE on an injected divergence (guard against a vacuous pass).
# ---------------------------------------------------------------------------
def test_numbers_lint_catches_a_pit_divergence(reg):
    poisoned = copy.deepcopy(reg)
    poisoned.tables["silver_esr"] = dict(poisoned.tables["silver_esr"])
    poisoned.tables["silver_esr"]["publication_lag_days"] = 999
    divs = RC.reconcile_numbers(poisoned)
    assert any(d.kind == "publication_lag_days" and d.table == "silver_esr" for d in divs)


def test_source_contract_lint_catches_missing_column(reg):
    poisoned = copy.deepcopy(reg)
    c = copy.deepcopy(poisoned.tables["silver_psd"])
    c["physical_columns"] = [col for col in c["physical_columns"]
                             if col["name"] != "su_ratio"]
    poisoned.tables["silver_psd"] = c
    divs = RC.reconcile_source_contracts(poisoned)
    assert any(d.kind == "required_column_absent" and d.column == "su_ratio" for d in divs)


def test_value_authority_leak_is_caught(reg, tmp_path):
    import yaml
    # write a source_contracts variant that illegally re-declares value_columns.
    sc = {"sources": [{
        "source_key": "psd", "glue_table": "silver_psd", "required_columns": [],
        "value_columns": ["production_mt"],
    }]}
    p = tmp_path / "sc.yaml"
    p.write_text(yaml.safe_dump(sc), encoding="utf-8")
    divs = RC.reconcile_source_contracts(reg, path=p)
    assert any(d.kind == "value_authority_leak" for d in divs)


def test_known_drift_allowlist_filters_by_owner(reg):
    div = RC.Divergence("source_contracts", "silver_psd", "required_column_absent",
                        "x", column="ghost_col")
    known = {"reconciliation_drift": [
        {"check": "source_contracts", "table": "silver_psd",
         "kind": "required_column_absent", "column": "ghost_col",
         "owner_package": "SILVER-F062"}
    ]}
    assert RC.unallowed([div], known) == []
    # a different column is NOT covered.
    other = RC.Divergence("source_contracts", "silver_psd", "required_column_absent",
                          "x", column="other_col")
    assert RC.unallowed([other], known) == [other]
