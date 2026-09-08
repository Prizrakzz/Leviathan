"""The NASS state-code reference loader and its ``query`` wiring -- STATE ENGINE DESIGN sec 2.1 / 2.6
item 3, sitting S1.

The card half (``country_name_ref`` on ``silver_nass_crop_progress``) is NOT landed here, and that order
is the point of the first test: ``query._country_ref`` RAISES on a ref no loader serves, so a card key
arriving first would turn today's honest zero-row NASS lookup into a hard error on every lookup that
names a country. A loader with no card is inert; a card with no loader is an outage.
"""
import pytest
from leviathan.graphrag.numbers import nass_states as NS
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers.registry import load_registry


# ── the wiring, and the order it landed in ───────────────────────────────────────────────────────────
def test_the_loader_is_registered_and_the_three_references_share_one_protocol():
    assert Q._COUNTRY_REF_LOADERS["numbers/nass_states.yaml"] == \
        ("leviathan.graphrag.numbers.nass_states", "load_nass_states")
    for ref in Q._COUNTRY_REF_LOADERS:
        from importlib import import_module
        module, fn = Q._COUNTRY_REF_LOADERS[ref]
        loaded = getattr(import_module(module), fn)()
        for method in ("resolve_codes", "display", "is_pseudo", "kind"):
            assert callable(getattr(loaded, method)), f"{ref} does not serve {method}"


def test_every_card_that_declares_a_country_name_ref_has_a_loader():
    """Fail-closed, estate-wide: a card declaring a reference and silently getting the plain-equality
    path back is the zero-rows-narrated-as-a-figure failure the mechanism exists to close."""
    for tid, ts in load_registry().tables.items():
        if getattr(ts, "country_name_ref", None):
            assert ts.country_name_ref in Q._COUNTRY_REF_LOADERS, tid
            Q._country_ref(ts)                       # RAISES on an unserved ref


def test_the_nass_card_does_not_yet_name_the_reference_and_that_is_the_recorded_state():
    """S0 measured that FOUR things must land in one change for the NASS row (the silver contract's
    ``cascade_ref`` back-pointer through its GENERATOR, the card key, this loader, and a live probe).
    S1 lands the loader -- inert on its own -- and the card half waits for the commit that can carry the
    other three. This test states that fact so the next sitting reads it as a plan, not as an omission."""
    ts = load_registry().get("silver_nass_crop_progress")
    assert getattr(ts, "country_name_ref", None) in (None, "")
    assert ts.country_col == "state"


# ── the reference itself ─────────────────────────────────────────────────────────────────────────────
def test_the_reference_lints_clean():
    assert NS.lint_reference() == []


def test_a_country_NAME_resolves_to_the_USPS_code_the_column_actually_holds():
    ref = NS.load_nass_states()
    assert ref.resolve_codes("United States") == ["US"]
    assert ref.resolve_codes("united states of america") == ["US"]
    assert ref.resolve_codes("Iowa") == ["IA"]
    assert ref.resolve_codes("  IOWA  ") == ["IA"]           # the shared normal form
    assert len(ref.code_to_display) == 52                    # 50 states + DC + the national roll-up


def test_an_unresolved_name_fails_CLOSED_and_never_widens_to_the_national_roll_up():
    """The July name-vs-code lesson class. On THIS card a wrong widening would be the worst of the
    three surfaces: a national crop condition served for a question about France reads as plausible."""
    ref = NS.load_nass_states()
    assert ref.resolve_codes("France") == []
    assert ref.resolve_codes("") == [] and ref.resolve_codes(None) == []


def test_the_national_roll_up_is_PSEUDO_because_it_sits_in_the_same_column_as_its_members():
    ref = NS.load_nass_states()
    assert ref.is_pseudo("US") is True and ref.kind("US") == "national"
    assert ref.is_pseudo("IA") is False and ref.kind("IA") == "state"


def test_the_display_render_is_a_REAL_translation_never_the_identity():
    ref = NS.load_nass_states()
    assert ref.display("IA") == "Iowa" and ref.display("US") == "United States"
    assert ref.display("ZZ") == "ZZ"                          # bare-value fallback, never a raise


def test_every_code_is_quoted_so_no_state_is_read_as_a_yaml_boolean():
    """``NO`` (Norway's ISO code, and a YAML 1.1 boolean) is not a USPS code, but ``ON``/``NO``/``NA``
    class keys are exactly how an unquoted mapping key becomes ``False``. The lint's token clause is
    what catches it, and this is the reason that clause exists."""
    ref = NS.load_nass_states()
    assert all(isinstance(c, str) and len(c) == 2 for c in ref.code_to_display)


def test_a_code_present_here_but_absent_from_the_data_is_reported_not_assumed():
    assert NS.missing_codes(["IA", "IL", "ZZ"]) == ["ZZ"]
    assert NS.missing_codes(["IA", "US"]) == []


# ── what the filter would compile once the card names the reference ──────────────────────────────────
def test_the_reference_compiles_a_type_agnostic_IN_filter_on_a_card_that_names_it():
    """The mechanism, proved on a MODEL of the card rather than on the card -- landing the key is the
    other commit's job, and this asserts the SQL that key will produce."""
    ts = load_registry().get("silver_nass_crop_progress").model_copy(
        update={"country_name_ref": "numbers/nass_states.yaml"})
    spec = Q.NumberQuery(table="silver_nass_crop_progress", metric=sorted(ts.metrics)[0],
                         asof="2026-09-08", commodity="corn", country="United States", agg="series")
    where = Q._country_ref_filters(spec, ts)
    assert where == ["CAST(state AS varchar) IN ('US')"]
    unresolved = Q.NumberQuery(table=spec.table, metric=spec.metric, asof=spec.asof,
                               commodity="corn", country="Brazil", agg="series")
    assert Q._country_ref_filters(unresolved, ts) == \
        ["CAST(state AS varchar) IN ('__unresolved_destination__')"]


def test_the_oracle_mirrors_that_filter_row_for_row():
    ts = load_registry().get("silver_nass_crop_progress").model_copy(
        update={"country_name_ref": "numbers/nass_states.yaml"})
    metric = sorted(ts.metrics)[0]
    spec = Q.NumberQuery(table="silver_nass_crop_progress", metric=metric, asof="2026-09-08",
                         commodity="corn", country="United States", agg="series")
    rows = [{"state": "US", "commodity": "corn", "date": "2026-08-30", "value": 1.0},
            {"state": "IA", "commodity": "corn", "date": "2026-08-30", "value": 2.0}]
    kept = Q.apply_pit_filter(rows, spec, ts)
    assert [r["state"] for r in kept] == ["US"]
