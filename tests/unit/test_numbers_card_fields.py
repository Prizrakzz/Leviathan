"""THE 09-23 FIX ROUND, LANE T -- the numbers cards' OWN declarations of what one row IS (CONTRACT C10), the
two readers of them (``registry.display_spec``, ``registry.card_unit_phrases``; C5 / C6), and the one
property that makes all of it safe to land first: NOT ONE BYTE of the numbers seat's cached prompt moves.

Every declared value below was re-read against its own card (or measured on the live silver object,
pulled read-only on 2026-09-23 -- see the lane's BUILD_T.md) before it was written; the pins hold the
values, and the comments say where each one came from.
"""
from __future__ import annotations

import hashlib
import os

import pytest
from pydantic import ValidationError

from leviathan.graphrag.numbers import agent as A
from leviathan.graphrag.numbers import registry as R

# B9 -- THE NUMBERS SEAT PROMPT, BYTE FOR BYTE. sha256 of `agent.system_prompt(registry.load_registry())`
# at HEAD (08d8dfd4, measured this sitting from a read-only `git archive` of HEAD's src + configs) and at
# the tree with every C10 field declared: identical, 255,421 chars. A card edit that moves this pin is a
# cache write on every numbers round of every turn -- re-bank it only with that cost written down.
B9_NUMBERS_PROMPT_SHA256 = "3caa2d83e7752c7baa6f72cd3c07ee663632623889dc4c9e780bd02ffd95adc5"
B9_NUMBERS_PROMPT_CHARS = 255421


@pytest.fixture()
def clean_env(monkeypatch):
    for k in list(os.environ):
        if k.startswith("GRAPHRAG_"):
            monkeypatch.delenv(k, raising=False)
    R.load_registry.cache_clear()
    yield
    R.load_registry.cache_clear()


# ── B9 / T-4: the fields are PARSED and NEVER PRINTED ─────────────────────────────────────────────────
def test_B9_the_numbers_prompt_is_byte_identical_with_every_c10_field_declared(clean_env):
    sp = A.system_prompt(R.load_registry())
    assert len(sp) == B9_NUMBERS_PROMPT_CHARS
    assert hashlib.sha256(sp.encode("utf-8")).hexdigest() == B9_NUMBERS_PROMPT_SHA256


def test_T4_no_c10_field_name_or_declared_value_reaches_the_prompt(clean_env):
    reg = R.load_registry()
    sp = A.system_prompt(reg)
    for name in ("basis_words", "display_scale", "display_unit", "display_decimals", "country_axis",
                 "axis_national", "provenance_kind", "period_words", "period_first_known",
                 "ending stocks as a share of domestic use", "any ethanol grind is inside it",
                 "region_cell", "release_stamp", "source_position", "crop_season"):
        assert name not in sp, name


# ── T-5: optional, defaulted, and the schema still refuses a typo ──────────────────────────────────────
def test_T5_an_undeclared_card_reads_none_on_every_field_and_the_registry_loads(clean_env):
    reg = R.load_registry()
    ts = reg.get("silver_fgis")
    assert (ts.country_axis, ts.axis_national, ts.provenance_kind, ts.period_words,
            ts.period_first_known) == (None, None, None, None, None)
    m = next(iter(ts.metrics.values()))
    assert (m.basis_words, m.display_scale, m.display_unit, m.display_decimals) == (None, None, None, None)


@pytest.mark.parametrize("bad", [{"country_axis": "planet"}, {"axis_national": "median"},
                                 {"provenance_kind": "vintage"}, {"period_words": "fortnight"},
                                 {"period_first_known": {"anchor": "mid", "offset_months": 1}},
                                 {"period_first_known": {"anchor": "period_end"}},
                                 {"period_first_known": {"anchor": "period_end", "offset_months": 5, "x": 1}},
                                 {"country_axes": "global"}])
def test_T5_a_malformed_declaration_fails_at_LOAD_never_at_a_reader(bad):
    with pytest.raises(ValidationError):
        R.TableSpec(id="x", description="d", shape="wide", **bad)


def test_period_first_known_is_stored_as_the_plain_dict_every_reader_tests_for():
    ts = R.TableSpec(id="x", description="d", shape="wide",
                     period_first_known={"anchor": "period_start", "offset_months": 4})
    assert type(ts.period_first_known) is dict
    assert ts.period_first_known == {"anchor": "period_start", "offset_months": 4}


def test_the_closed_vocabularies_are_contract_c1s_own():
    """CONTRACT C1 spells AXIS_KINDS / PERIOD_KINDS in `state/rows.py` (lane R's leaf); the registry spells
    them as Literals because it imports nothing from the state package. The two must be ONE roster."""
    assert R.AXIS_KINDS == ("national", "reporter", "destination", "region_cell", "global")
    assert R.PERIOD_KINDS == ("marketing_year", "crop_season", "month", "week", "day", "delivery_month",
                              "window")
    try:
        from leviathan.graphrag.state import rows as SR
    except Exception:  # noqa: BLE001 -- the leaf not importable is lane R's deck's finding, not this one's
        return
    for name in ("AXIS_KINDS", "PERIOD_KINDS"):
        if hasattr(SR, name):
            assert tuple(getattr(SR, name)) == getattr(R, name), name
    lits = {f: R.TableSpec.model_fields[f].annotation for f in ("country_axis", "period_words")}
    assert "region_cell" in str(lits["country_axis"]) and "crop_season" in str(lits["period_words"])


# ── C10: the declared values, card by card ─────────────────────────────────────────────────────────────
def test_C10_the_psd_stocks_to_use_basis_and_display_are_the_producers_own(clean_env):
    """The card's own desc: the producer computes ending_stocks_mt / consumption_mt, EXPORTS NOT IN THE
    DENOMINATOR, a FRACTION OF ONE (0.1072 is 10.7%). OWNER DECISION 4 (a): name the basis, serve in %."""
    m = R.load_registry().get("silver_psd").metrics["su_ratio"]
    assert m.basis_words == "ending stocks as a share of domestic use"
    assert (m.display_scale, m.display_unit, m.display_decimals) == (100, "%", 2)
    assert "ending_stocks_mt / consumption_mt" in m.desc and "EXPORTS ARE NOT IN THE DENOMINATOR" in m.desc
    assert R.display_spec("silver_psd", "su_ratio") == (100, "%", 2)


def test_C10_the_mpob_ratio_is_months_of_export_cover_at_identity_scale(clean_env):
    m = R.load_registry().get("silver_mpob").metrics["su_ratio"]
    assert (m.display_scale, m.display_unit, m.display_decimals) == (1, "months of export cover", 2)
    assert m.label == "months of export cover" and "the quantity is MONTHS" in m.desc
    assert m.basis_words is None


def test_C10_the_fsi_basis_says_what_is_inside_it(clean_env):
    """Measured on silver/psd_attributes (read-only, 2026-09-23): US corn carries `FSI Consumption`
    (175,395 kMT MY2025) and NO `Industrial Dom. Cons.` -- the ethanol grind is inside FSI and cannot be
    separated on this card. The words say "any" because the metric serves eight commodities."""
    m = R.load_registry().get("silver_psd_attributes").metrics["FSI Consumption"]
    assert m.basis_words == "food, seed and industrial use -- any ethanol grind is inside it and is not separable"


@pytest.mark.parametrize("tid,axis,national,prov,words", [
    ("silver_psd", "reporter", None, None, "marketing_year"),
    ("silver_psd_attributes", "reporter", None, None, "marketing_year"),
    ("silver_wasde", None, None, "role", "marketing_year"),
    ("silver_esr", "destination", "sum", None, "week"),
    ("gold_weather_z", "region_cell", "none", None, "month"),
    ("silver_noaa_oni", "global", None, None, "month"),
    ("silver_noaa_iod", "global", None, None, "month"),
    ("silver_mpob", None, None, None, "month"),
    ("silver_pink_sheet", "global", None, "release_stamp", "month"),
    ("silver_food_cpi", None, None, "release_stamp", None),
    ("silver_cot", None, None, None, "week"),
    ("silver_futures_eod", None, None, None, "day"),
    ("silver_fred_fx", None, None, None, "day"),
    ("gold_board_crush", None, None, "rule_version", "day"),
    ("gold_futures_spreads", None, None, "rule_version", "day"),
    ("silver_icco_cocoa", "global", None, None, "crop_season"),
    ("silver_unica_biweekly_season_history", None, None, "source_position", None),
    ("silver_unica_corn_ethanol", None, None, "source_position", None),
    ("silver_unica_monthly_ethanol_sales", None, None, "source_position", None),
    ("silver_nass_crop_progress", None, None, None, "week"),
])
def test_C10_every_card_the_ten_turns_touched_declares_what_its_row_is(clean_env, tid, axis, national,
                                                                        prov, words):
    ts = R.load_registry().get(tid)
    assert (ts.country_axis, ts.axis_national, ts.provenance_kind, ts.period_words) == (
        axis, national, prov, words)
    if prov is not None:
        assert ts.provenance_col, f"{tid} declares a provenance KIND with no provenance column"


def test_C10_a_provenance_kind_names_the_column_the_card_actually_carries(clean_env):
    reg = R.load_registry()
    assert reg.get("silver_wasde").provenance_col == "estimate_role"
    assert reg.get("silver_pink_sheet").provenance_col == "latest_release_ym"
    assert reg.get("gold_board_crush").provenance_col == "crush_rule_version"
    assert reg.get("silver_unica_corn_ethanol").provenance_col == "source_position_date"


def test_C10_period_first_known_is_the_measured_first_print_under_the_evaluators_own_anchor(clean_env):
    """Lane C's `feeders.period_gap` reads a label by its CALENDAR extent ('2023' -> 2023-01-01..12-31,
    '2024/25' -> 2024-01-01..2025-12-31). MEASURED on the live objects (read-only, 2026-09-23):
      silver_psd       MY2026 cells first appear in the 2026-05 release on 3,218 of 3,698
                       -> first day of the label + 4 months (the contract's "-4" was written against a
                       September marketing-year start; the date is the same May)
      silver_icco      2024/25 is carried from the 2026-05-29 release, 2023/24 from 2025-05-30
                       -> last day of the label + 5 months (the contract's "+8" from a September 30 end
                       is the same end-of-May date)."""
    # 09-23 FIX ROUND (review FATAL-6 / M-2): the rule is a SURELY-KNOWN bound (the evaluator reads the
    # month's LAST day) and the offset is the LATEST first print across the card's slugs -- MY2026 first
    # printed in July on the coffee sheets (fix_round_0923/fix/census_first_known.out) -> +6, not +4.
    reg = R.load_registry()
    assert reg.get("silver_psd").period_first_known == {"anchor": "period_start", "offset_months": 6}
    assert reg.get("silver_psd_attributes").period_first_known == {"anchor": "period_start",
                                                                   "offset_months": 6}
    assert reg.get("silver_icco_cocoa").period_first_known == {"anchor": "period_end", "offset_months": 5}


# ── C5 / C6: the two readers ───────────────────────────────────────────────────────────────────────────
def test_display_spec_never_defaults_a_value_and_never_raises(clean_env):
    assert R.display_spec("silver_psd", "production_mt") == (None, None, None)
    assert R.display_spec("no_such_card", "x") == (None, None, None)
    assert R.display_spec("silver_psd", "no_such_metric") == (None, None, None)


def test_C6_card_unit_phrases_is_every_declared_unit_normalised_once(clean_env):
    ph = R.card_unit_phrases()
    reg = R.load_registry()
    declared = set()
    for ts in reg.tables.values():
        for m in ts.metrics.values():
            for u in [m.unit, m.display_unit] + list((m.unit_overrides or {}).values()):
                if u:
                    declared.add(R.normalise_unit_phrase(u))
    assert ph == frozenset(declared)
    for p in ph:
        assert p == p.lower() and "  " not in p and "-" not in p and p == p.strip(), p
    # the phrases whose numerals the verifier must MASK, not read as claims (the C6 purpose)
    for p in ("1000 480 lb. bales", "1000 60 kg bags", "cop per 125 kg carga", "sigma vs 5 yr mean",
              "million 480 lb bales", "mmt, milled basis", "us cents/bushel", "months of export cover"):
        assert p in ph, p


def test_C6_the_normaliser_folds_the_reader_spaces_and_keeps_the_range_dash():
    en_dash = chr(0x2013)
    assert R.normalise_unit_phrase("  BRL/60-kg bag ") == "brl/60 kg bag"
    assert R.normalise_unit_phrase("480" + chr(0x2011) + "lb") == "480 lb"
    assert R.normalise_unit_phrase("3" + en_dash + "4") == "3" + en_dash + "4"      # a RANGE, untouched
    assert R.normalise_unit_phrase(None) == ""


# ── T-6: the reading words the row identity reads are register-clean and complete ─────────────────────
def test_T6_the_corrected_reading_words_are_clause_13_clean_and_name_the_series():
    from leviathan.graphrag.state import lint as L
    from leviathan.graphrag.state import render as SR
    assert L._check_reading_words() == []
    assert SR.reading_words("gold_weather_z", "drought_z") == \
        "the longest dry-day run in the month, as a z-score"
    assert SR.reading_words("silver_esr", "weekly_exports_1000mt") == "weekly export shipments"
    assert SR.reading_words("silver_psd", "beginning_stocks_mt") == "carry-in stocks, all holders"
    # the card's own words the corrections were read against
    reg = R.load_registry()
    assert "longest consecutive dry-day run in the month" in reg.get("gold_weather_z").metrics["drought_z"].desc
    assert reg.get("silver_esr").metrics["weekly_exports_1000mt"].desc == "actual shipments in the week"
