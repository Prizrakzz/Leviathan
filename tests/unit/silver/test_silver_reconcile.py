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


def _contract(reg, name: str, specs: dict) -> dict:
    """The contract a numbers card reconciles against -- ``RC.contract_name_for``, the ONE rule.

    Restating the resolution here would let it drift from the lint it is meant to mirror, and the
    case it exists for is precisely a card whose id names no contract: silver_production_livestock
    (FAO-2) is a SECOND card on the silver_production physical table via ``athena_table``, so
    ``reg.table(<its id>)`` is a KeyError by construction and always will be."""
    return reg.table(RC.contract_name_for(name, specs.get(name, {}), reg))


def test_all_numbers_tables_carry_back_pointers(reg):
    specs = RC._numbers_specs()
    for name in RC.NUMBERS_TABLES:
        c = _contract(reg, name, specs)
        assert c["numbers_ref"], name
        assert c["consumers"] in ("numbers_registry", "both"), name


def test_numbers_pit_fields_match_tablespec(reg):
    specs = RC._numbers_specs()
    for name in RC.NUMBERS_TABLES:
        c, spec = _contract(reg, name, specs), specs[name]
        assert c["knowledge_date_col"] == spec.get("knowledge_date_col"), name
        assert c["knowledge_semantics"] == spec.get("knowledge_semantics"), name
        assert c["publication_lag_days"] == spec.get("publication_lag_days"), name
    # BF-W2 SILVER-F031: ESR runs per-week vintage semantics with lag 0 (the as_of stamp IS the
    # publication event) — the pre-flip data_date/+7d pair must NOT resurface via a stale regen.
    assert reg.table("silver_esr")["knowledge_semantics"] == "vintage"
    assert reg.table("silver_esr")["publication_lag_days"] == 0


class TestTheSecondCardOnOnePhysicalTable:
    """FAO-2 (Lane 5). ``silver_production_livestock`` is the estate's FIRST card id that names no
    Glue table of its own: it serves ``silver_production`` through ``athena_table`` because
    ``commodity_values`` and per-metric ``unit`` are per-CARD closed sets and the crop half and the
    livestock half must not share either.

    WHAT IS NOT DONE, and it is the point of ``contract_name_for``: no phantom F010 contract is
    minted for it. That contract would describe a table that does not exist, and the F010 registry is
    consumed downstream as a roster of PHYSICAL tables -- a DDL would be rendered for it, the
    readiness roster and the rebuild gate would count it, six count pins would move -- all to check a
    duplicate against itself, since every PIT field of a second card on one table is the SAME COLUMN
    as the first card's."""

    def test_the_logical_card_reconciles_against_the_physical_tables_contract(self, reg):
        specs = RC._numbers_specs()
        assert "silver_production_livestock" in RC.NUMBERS_TABLES
        assert "silver_production_livestock" not in reg.tables      # no phantom contract, ever
        assert RC.contract_name_for(
            "silver_production_livestock", specs["silver_production_livestock"], reg
        ) == "silver_production"
        assert [d.detail for d in RC.reconcile_numbers(reg)
                if d.table == "silver_production_livestock"] == []

    def test_the_two_cards_are_forced_to_agree_on_the_shared_tables_pit_semantics(self, reg):
        """THE CHECK THIS BUYS, and it has more teeth than a duplicated contract would: two cards on
        one physical table declaring DIFFERENT knowledge semantics is the real hazard a second card
        creates, and before this it was unreachable by any lint. Asserted in the failing direction."""
        specs = copy.deepcopy(RC._numbers_specs())
        specs["silver_production_livestock"]["knowledge_semantics"] = "vintage"

        class _Frozen:
            def __init__(self, doc): self._doc = doc
            def __call__(self, path=None): return self._doc

        original = RC._numbers_specs
        RC._numbers_specs = _Frozen(specs)                            # noqa: F811 -- restored below
        try:
            divs = RC.reconcile_numbers(reg)
        finally:
            RC._numbers_specs = original
        assert any(d.table == "silver_production_livestock"
                   and d.kind == "knowledge_semantics" for d in divs)

    def test_silver_esr_still_reconciles_against_its_OWN_contract(self, reg):
        """THE REGRESSION GUARD ON THE RESOLUTION ORDER. silver_esr ALSO carries an athena_table
        (silver_esr_compact) and BOTH names are registered contracts; its PIT trio has always been
        checked against silver_esr's own record (BF-W2 SILVER-F031 pins vintage/+0d there). A
        serving-first resolution would silently re-point that live check at a different contract."""
        specs = RC._numbers_specs()
        assert specs["silver_esr"].get("athena_table") == "silver_esr_compact"
        assert "silver_esr_compact" in reg.tables
        assert RC.contract_name_for("silver_esr", specs["silver_esr"], reg) == "silver_esr"

    def test_the_card_flipped_live_and_the_fence_stays_discharged(self):
        """FLIPPED 2026-08-26: the card was born fenced (PA-1 + the Lane-3 arm-vs-flip doctrine --
        no livestock row existed, and a served card would have read as 'no cattle') and left the
        fence the same day with every gate discharged by an artifact (the discharge record lives on
        the WHITELIST_ABSENT_DEFAULT entry). This pin now guards the discharged state: a regression
        back onto the whitelist would silently unserve a backfilled, mirrored, probed surface."""
        from leviathan.graphrag.numbers import registry as NR
        assert "silver_production_livestock" not in NR.WHITELIST_ABSENT_DEFAULT
        assert not (NR.WHITELIST_ABSENT_DEFAULT & NR._disabled_tables())   # env lane stays separate
        assert "silver_production_livestock" in NR.load_registry().tables
        # the physical table is SHARED and was never fenced -- the crop card was live throughout
        assert "silver_production" not in NR.WHITELIST_ABSENT_DEFAULT
        assert "silver_production" in NR.load_registry().tables


def test_price_observability_tables_in_exact_numbers_set(reg):
    """PRICE_OBSERVABILITY W2/W4: silver_pink_sheet (v1b) and silver_cot (v2) are members of the EXACT
    NUMBERS_TABLES set, reconcile clean, and carry consumers=both + their W-card PIT fields (a mis-derived
    lag or a dropped back-pointer would ship live while the gate reports 'clean' -- CORRECTION V3)."""
    specs = RC._numbers_specs()
    for name in ("silver_pink_sheet", "silver_cot"):
        assert name in RC.NUMBERS_TABLES, name
        assert [d.detail for d in RC.reconcile_numbers(reg) if d.table == name] == []
        c = reg.table(name)
        assert c["numbers_ref"] and c["consumers"] == "both", name
        assert c["knowledge_date_col"] == specs[name].get("knowledge_date_col"), name
        assert c["publication_lag_days"] == specs[name].get("publication_lag_days"), name
    # silver_cot's W4.1 card values, pinned exactly (data_date semantics, 6d lag, max_lag_days=10 SLA).
    cot = reg.table("silver_cot")
    assert cot["knowledge_semantics"] == "data_date" and cot["knowledge_date_col"] == "report_date"
    assert cot["publication_lag_days"] == 6
    assert cot["freshness_sla"]["max_lag_days"] == 10          # the staleness alarm ceiling (W4.0)
    # R9 AS AMENDED (D1, ratified 2026-08-01). This used to assert `is None` with the reason "positioning
    # enters NO engine map". D1 split that rule: silver_cot may enter cascade_map as the narrow past-tense
    # CONTEXT leg (and only that -- config_check._check_positioning_lane is build-failing on every other
    # shape and on any chain/complex/transmission reference). So the back-pointer is now REQUIRED, and it
    # is required to name the context ref specifically: a back-pointer to some other ref would mean a
    # second, unratified positioning row exists.
    assert cot["cascade_ref"] == "configs/graphrag/numbers/cascade_map.yaml#cot_mm_positioning"


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
