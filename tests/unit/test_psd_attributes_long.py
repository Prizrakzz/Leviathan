"""D-EC L2-2 -- silver_psd_attributes, the LONG companion table, pinned as decisions.

The wide ``silver_psd`` serves 11 of the 69 attribute labels USDA's bulk PSD file
publishes (8 ``_TARGET_ATTRS`` + 3 slug-keyed remap sources).  This long companion
serves all of them, in their NATIVE units, and it can only do that safely if R4 --
attribute-aware fan-out -- ships with it.

Every figure quoted below was MEASURED on
``s3://leviathan-dev-shahem-001/bronze/production/source=usda_psd/
release_date=2026-08-13/part-000.parquet`` (2,092,687 rows, 63 commodity codes,
1,899,303 in scope) -- the same object the attribute census read.

These tests take the R2 posture from tests/unit/test_psd_slug_map_widening.py:105-135
-- a STATIC MAP ASSERTION plus a LIVE PROOF that the failure the map prevents is
real and would happen without it.

Pure Python -- no S3, no AWS.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

import leviathan.transforms.bronze_to_silver.usda_psd as U
import leviathan.transforms.bronze_to_silver.usda_psd_attributes as U4
from leviathan.transforms.bronze_to_silver.usda_psd import (
    _PSD_COMMODITY_TO_SLUGS,
    _TARGET_ATTRS,
    transform_psd_bronze_to_silver,
)
from leviathan.transforms.bronze_to_silver.usda_psd_attributes import (
    _COFFEE_ARABICA_SLUGS,
    _COFFEE_ROBUSTA_SLUGS,
    _GRAIN_COLS,
    _PSD_ATTR_FANOUT,
    _PSD_ATTR_ID_TO_DESC_PIN,
    _PSD_HOMOGENEOUS_FANOUT_CODES,
    _PSD_UNIT_MISLABELLED_ATTR_IDS,
    _SILVER_PSD_ATTR_COLS,
    _SUGAR_RAW_SLUGS,
    _SUGAR_WHITE_SLUGS,
    transform_psd_attributes_bronze_to_silver,
)

_REPO = Path(__file__).resolve().parents[2]

# (attribute_desc, attribute_id, unit_desc, value) -- byte-exact spellings from the
# 2026-08-13 census; ids are USDA's own.
_MASS_ROWS: list[tuple[str, int, str, float]] = [
    ("Beginning Stocks",     20,  "(1000 MT)", 100.0),
    ("Production",           28,  "(1000 MT)", 200.0),
    ("Imports",              57,  "(1000 MT)", 50.0),
    ("Exports",              88,  "(1000 MT)", 80.0),
    ("Ending Stocks",        176, "(1000 MT)", 70.0),
    ("Domestic Consumption", 125, "(1000 MT)", 200.0),
]

# The full 19-attribute green-coffee sheet, in USDA's own units.
_COFFEE_ROWS: list[tuple[str, int, str, float]] = [
    ("Beginning Stocks",       20,  "(1000 60 KG BAGS)", 100.0),
    ("Production",             28,  "(1000 60 KG BAGS)", 900.0),
    ("Arabica Production",     29,  "(1000 60 KG BAGS)", 600.0),
    ("Robusta Production",     53,  "(1000 60 KG BAGS)", 250.0),
    ("Other Production",       56,  "(1000 60 KG BAGS)", 50.0),
    ("Imports",                57,  "(1000 60 KG BAGS)", 10.0),
    ("Bean Imports",           58,  "(1000 60 KG BAGS)", 8.0),
    ("Roast & Ground Imports", 75,  "(1000 60 KG BAGS)", 1.0),
    ("Soluble Imports",        82,  "(1000 60 KG BAGS)", 1.0),
    ("Total Supply",           86,  "(1000 60 KG BAGS)", 1010.0),
    ("Exports",                88,  "(1000 60 KG BAGS)", 700.0),
    ("Bean Exports",           90,  "(1000 60 KG BAGS)", 650.0),
    ("Roast & Ground Exports", 107, "(1000 60 KG BAGS)", 25.0),
    ("Soluble Exports",        114, "(1000 60 KG BAGS)", 25.0),
    ("Domestic Consumption",   125, "(1000 60 KG BAGS)", 200.0),
    ("Rst,Ground Dom. Consum", 141, "(1000 60 KG BAGS)", 150.0),
    ("Soluble Dom. Cons.",     154, "(1000 60 KG BAGS)", 50.0),
    ("Ending Stocks",          176, "(1000 60 KG BAGS)", 110.0),
    ("Total Distribution",     178, "(1000 60 KG BAGS)", 1010.0),
]

# The full 16-attribute centrifugal-sugar sheet.
_SUGAR_ROWS: list[tuple[str, int, str, float]] = [
    ("Beginning Stocks",      20,  "(1000 MT)", 100.0),
    ("Production",            28,  "(1000 MT)", 900.0),
    ("Beet Sugar Production", 30,  "(1000 MT)", 300.0),
    ("Cane Sugar Production", 43,  "(1000 MT)", 600.0),
    ("Imports",               57,  "(1000 MT)", 40.0),
    ("Raw Imports",           64,  "(1000 MT)", 30.0),
    ("Refined Imp.(Raw Val)", 74,  "(1000 MT)", 10.0),
    ("Total Supply",          86,  "(1000 MT)", 1040.0),
    ("Exports",               88,  "(1000 MT)", 500.0),
    ("Raw Exports",           89,  "(1000 MT)", 450.0),
    ("Refined Exp.(Raw Val)", 99,  "(1000 MT)", 50.0),
    ("Total Disappearance",   126, "(1000 MT)", 480.0),
    ("Human Dom. Consumption", 139, "(1000 MT)", 460.0),
    ("Other Disappearance",   151, "(1000 MT)", 20.0),
    ("Ending Stocks",         176, "(1000 MT)", 60.0),
    ("Total Distribution",    178, "(1000 MT)", 1040.0),
]


def _bronze(commodity_code: int,
            rows: list[tuple[str, int, str, float]] | None = None,
            *,
            country: str = "World",
            market_year: int = 2024,
            month_code: int = 1,
            release_date: str = "2026-08-13") -> pd.DataFrame:
    """One bronze row per (attribute_desc, attribute_id, unit_desc, value) tuple."""
    rows = _MASS_ROWS if rows is None else rows
    return pd.DataFrame([
        {
            "commodity_code": commodity_code,
            "commodity_desc": f"code-{commodity_code}",
            "country_name":   country,
            "market_year":    market_year,
            "month_code":     month_code,
            "attribute_id":   attr_id,
            "attribute_desc": attr,
            "unit_desc":      unit,
            "value":          val,
            "release_date":   release_date,
        }
        for attr, attr_id, unit, val in rows
    ])


def _multi_slug_codes() -> dict[int, list[str]]:
    return {c: s for c, s in _PSD_COMMODITY_TO_SLUGS.items() if len(s) > 1}


# ---------------------------------------------------------------------------
# (a) The declared grain.
# ---------------------------------------------------------------------------
class TestGrain:

    def test_the_output_columns_are_the_declared_nine(self) -> None:
        long = transform_psd_attributes_bronze_to_silver([_bronze(440000)])
        assert list(long.columns) == _SILVER_PSD_ATTR_COLS
        assert _SILVER_PSD_ATTR_COLS == [
            "leviathan_slug", "country", "market_year", "wasde_release_month",
            "release_date", "attribute", "attribute_id", "value", "unit",
        ]

    def test_wasde_release_month_is_IN_the_grain(self) -> None:
        # silver_wasde shipped without its full grain and the latest-vintage
        # ROW_NUMBER collapsed ACROSS regions, undetectable for months. The
        # identical exposure exists here: drop wasde_release_month and one
        # arbitrary WASDE vintage per (slug, country, market_year, attribute)
        # wins. The grain declaration is the fix and it is asserted, not assumed.
        assert "wasde_release_month" in _GRAIN_COLS
        assert _GRAIN_COLS == [
            "leviathan_slug", "country", "market_year", "wasde_release_month", "attribute",
        ]

    def test_grain_is_unique_across_a_multi_code_multi_month_frame(self) -> None:
        dfs = []
        for code, rows in ((440000, None), (711100, _COFFEE_ROWS), (612000, _SUGAR_ROWS)):
            for mc in (0, 1, 5):
                for my in (2023, 2024):
                    for ctry in ("World", "Brazil"):
                        dfs.append(_bronze(code, rows, country=ctry,
                                           market_year=my, month_code=mc))
        long = transform_psd_attributes_bronze_to_silver(dfs)
        assert len(long) > 0
        dupes = long.duplicated(subset=_GRAIN_COLS).sum()
        assert int(dupes) == 0, (
            f"{dupes} rows share a grain key -- the long table's whole contract is "
            f"one row per {_GRAIN_COLS}")

    def test_two_releases_of_one_vintage_collapse_to_the_latest(self) -> None:
        # Coffee and sugar are semi-annual sheets: consecutive monthly bulk
        # snapshots RE-PRINT the same (market_year, month_code) row. They are also
        # exactly the two sheets R4 adjudicates, so the interaction is real.
        #
        # NOTE the shape: MY2024 coffee (MYS=10, month 1) computes to 2024-10-10,
        # which is in the PAST for both snapshots, so the F2 clamp does not bind and
        # BOTH re-prints carry the identical release_date. release_date alone cannot
        # order them -- the bronze ingest date is the only witness left.
        old = _bronze(711100, _COFFEE_ROWS, release_date="2026-07-17")
        new = _bronze(711100, _COFFEE_ROWS, release_date="2026-08-13")
        new.loc[new.attribute_id == 28, "value"] = 999.0
        long = transform_psd_attributes_bronze_to_silver([old, new])
        assert int(long.duplicated(subset=_GRAIN_COLS).sum()) == 0
        prod = long[(long.attribute == "Production") & (long.leviathan_slug == "robusta_coffee")]
        assert len(prod) == 1
        assert prod.value.iloc[0] == 999.0, "the LATEST vintage must win, revisions included"

    def test_the_vintage_winner_does_not_depend_on_the_callers_argument_order(self) -> None:
        # The wide producer's step-10 "keep first" makes the winner a function of
        # which DataFrame the caller passed first whenever release_date ties. Order
        # independence is the property that makes a vintage rule a rule.
        old = _bronze(612000, _SUGAR_ROWS, market_year=2004, release_date="2026-07-17")
        new = _bronze(612000, _SUGAR_ROWS, market_year=2004, release_date="2026-08-13")
        new.loc[new.attribute_id == 28, "value"] = 999.0
        for dfs in ([old, new], [new, old]):
            long = transform_psd_attributes_bronze_to_silver(dfs)
            prod = long[(long.attribute == "Production") & (long.leviathan_slug == "raw_sugar")]
            assert len(prod) == 1 and prod.value.iloc[0] == 999.0

    def test_the_wide_producer_now_resolves_reprint_ties_latest_wins(self) -> None:
        # THE RIDER FLIPPED, DELIBERATELY (owner word 2026-08-25). This test previously
        # PINNED the defect: step-10's blind keep-first let the OLDEST snapshot win every
        # historical re-print tie (identical release_date whenever the F2 clamp does not
        # bind), contradicting vintage_retention: latest-only. The wide producer now orders
        # the dedup on bronze_ingest_date -- the long companion's rule -- so the NEWEST
        # snapshot's value wins regardless of caller argument order. Both orders asserted.
        old = _bronze(711100, _COFFEE_ROWS, release_date="2026-07-17")
        new = _bronze(711100, _COFFEE_ROWS, release_date="2026-08-13")
        new.loc[new.attribute_id == 28, "value"] = 999.0
        for order in ([old, new], [new, old]):
            wide = transform_psd_bronze_to_silver([d.copy() for d in order])
            row = wide[wide.leviathan_slug == "robusta_coffee"]
            assert len(row) == 1
            assert row.production_mt.iloc[0] == 999.0 * 60.0, (
                "the newest re-print must win the vintage tie in EITHER caller order")

    def test_attribute_id_maps_one_to_one_onto_attribute(self) -> None:
        long = transform_psd_attributes_bronze_to_silver(
            [_bronze(711100, _COFFEE_ROWS), _bronze(612000, _SUGAR_ROWS), _bronze(440000)])
        pairs = long[["attribute_id", "attribute"]].drop_duplicates()
        assert pairs.attribute_id.nunique() == len(pairs)
        assert pairs.attribute.nunique() == len(pairs)


# ---------------------------------------------------------------------------
# (b) Native units -- the whole reason the long table sidesteps the unit guard.
# ---------------------------------------------------------------------------
class TestNativeUnits:

    def test_a_percent_attribute_survives_with_its_unit_and_value_intact(self) -> None:
        # Extr. Rate, 999.9999 (id 181, 37,886 in-scope rows) rides (PERCENT).
        # (PERCENT) is DELIBERATELY absent from _UNIT_FACTOR -- that absence is the
        # fence keeping the (1000 HEAD) refusal honest, and 'just add a factor' is
        # the mechanism that would quietly retire it. The long table converts
        # NOTHING, so the fence is never approached.
        long = transform_psd_attributes_bronze_to_silver([
            _bronze(813100, [("Extr. Rate, 999.9999", 181, "(PERCENT)", 0.38)])])
        assert set(long.leviathan_slug) == {"soybean_meal_cbot", "soybean_meal_dce"}
        assert set(long.unit) == {"(PERCENT)"}
        assert set(long.value) == {0.38}, "a PERCENT value must NOT be multiplied by 1000"

    def test_a_ratio_attribute_survives_too(self) -> None:
        long = transform_psd_attributes_bronze_to_silver([
            _bronze(2631000, [("Seed to Lint Ratio", 183, "(RATIO)", 1.42),
                              ("Stocks-to-Use", 195, "(PERCENT)", 0.71)])])
        assert list(long.leviathan_slug.unique()) == ["cotton"]
        assert dict(zip(long.attribute, long.unit)) == {
            "Seed to Lint Ratio": "(RATIO)", "Stocks-to-Use": "(PERCENT)"}
        assert sorted(long.value) == [0.71, 1.42]

    def test_the_same_frame_still_KILLS_the_wide_transform(self) -> None:
        # The LIVE PROOF that native units are load-bearing, not a preference: the
        # very rows the long table serves are the rows the wide producer's step-7
        # guard refuses. (It only survives today because step 6 filters them out
        # first -- so feed it a frame where they are all that is left.)
        with pytest.raises(ValueError, match="unrecognised unit_desc"):
            U.transform_psd_bronze_to_silver([
                _bronze(2631000, [("Production", 28, "(PERCENT)", 0.71)])])

    def test_a_head_count_on_a_MAPPED_code_is_representable_here(self) -> None:
        # Cows In Milk (id 6, 1,917 rows) rides Dairy, Milk, Fluid (223000), which
        # IS mapped -- the producer's comment claims (1000 HEAD) only rides the two
        # refused animal-numbers codes, and the census measured a third carrier.
        # In an all-tonnes wide schema a head count is a lie; in a table with a
        # per-row unit column it is an honest row. The long table RETIRES that
        # hazard rather than smuggling past it.
        long = transform_psd_attributes_bronze_to_silver([
            _bronze(223000, [("Cows In Milk", 6, "(1000 HEAD)", 1234.0),
                             ("Production", 28, "(1000 MT)", 5000.0)])])
        head = long[long.attribute == "Cows In Milk"]
        assert len(head) == 1
        assert head.unit.iloc[0] == "(1000 HEAD)"
        assert head.value.iloc[0] == 1234.0

    def test_a_row_with_no_unit_is_refused_loudly(self) -> None:
        # There is no _UNIT_FACTOR lookup left to fail, so this is the one
        # assertion a conversion-free table still owes its readers.
        with pytest.raises(ValueError, match="null/empty unit_desc"):
            transform_psd_attributes_bronze_to_silver([
                _bronze(440000, [("Production", 28, "   ", 200.0)])])

    def test_the_source_mislabelled_unit_is_declined_by_name(self) -> None:
        # Milling Rate (.9999) (id 182, 7,616 rows on 422110) is a 1e4-scaled RATE
        # published under unit_desc '(1000 MT)'. '(1000 MT)' is a KNOWN unit, so it
        # would sail through any guard and land ~1e7 too large. The native-unit
        # contract cannot be honoured for it, so the rows are refused BY NAME.
        assert 182 in _PSD_UNIT_MISLABELLED_ATTR_IDS
        assert len(_PSD_UNIT_MISLABELLED_ATTR_IDS[182].strip()) > 40
        long = transform_psd_attributes_bronze_to_silver([
            _bronze(422110, [("Milling Rate (.9999)", 182, "(1000 MT)", 6500.0),
                             ("Rough Production", 54, "(1000 MT)", 7000.0)])])
        assert list(long.attribute) == ["Rough Production"]


# ---------------------------------------------------------------------------
# (c) R4 -- the static map AND the live proof of the failure it prevents.
# ---------------------------------------------------------------------------
class TestR4StaticMap:

    def test_every_multi_slug_code_is_declared_in_exactly_one_register(self) -> None:
        # FAIL CLOSED. The realistic future edit is not a USDA rename -- it is a
        # second slug added to a code that used to have one, a diff nowhere near
        # this file. An undeclared fan-out must be impossible, not merely unlikely.
        multi = set(_multi_slug_codes())
        declared = set(_PSD_ATTR_FANOUT) | _PSD_HOMOGENEOUS_FANOUT_CODES
        assert multi - declared == set(), (
            f"undeclared multi-slug fan-out: "
            f"{ {c: _PSD_COMMODITY_TO_SLUGS[c] for c in sorted(multi - declared)} }")
        assert declared - multi == set(), (
            f"register entries for codes that do not fan out: {sorted(declared - multi)}")
        assert set(_PSD_ATTR_FANOUT) & _PSD_HOMOGENEOUS_FANOUT_CODES == set()

    def test_the_measured_split_is_two_heterogeneous_and_seven_venue_only(self) -> None:
        # MEASURED on the 2026-08-13 object: of the 9 multi-slug codes, exactly two
        # publish an attribute specific to a proper subset of their slugs. The other
        # seven fan to interchangeable TRADING VENUES for one subject and USDA
        # prints nothing at venue or class grain for them.
        assert len(_multi_slug_codes()) == 9
        assert set(_PSD_ATTR_FANOUT) == {711100, 612000}
        assert _PSD_HOMOGENEOUS_FANOUT_CODES == frozenset({
            410000, 440000, 2222000, 813100, 4232000, 2226000, 4243000})

    def test_every_slug_a_register_names_really_belongs_to_that_code(self) -> None:
        for code, per_attr in _PSD_ATTR_FANOUT.items():
            owned = set(_PSD_COMMODITY_TO_SLUGS[code])
            for attr_id, allowed in per_attr.items():
                assert set(allowed) <= owned, (
                    f"code {code} attribute {attr_id} permits {sorted(set(allowed) - owned)} "
                    f"which the fan-out never emits for it")

    def test_the_coffee_variety_split_is_declared_exactly(self) -> None:
        coffee = _PSD_ATTR_FANOUT[711100]
        assert _COFFEE_ARABICA_SLUGS == frozenset({"arabica_coffee", "brazilian_arabica_coffee"})
        assert _COFFEE_ROBUSTA_SLUGS == frozenset({"robusta_coffee"})
        assert coffee[29] == _COFFEE_ARABICA_SLUGS      # Arabica Production
        assert coffee[53] == _COFFEE_ROBUSTA_SLUGS      # Robusta Production
        assert coffee[56] == frozenset(), (             # Other Production
            "Other Production is the residual varieties leg -- true of neither "
            "arabica nor robusta, and there is no third coffee slug. An EMPTY set "
            "is a DECLARED drop; a missing key would be an omission.")
        # the FORM split (bean / roast+ground / soluble) is not a variety split
        for form_id in (58, 75, 82, 90, 107, 114, 141, 154):
            assert coffee[form_id] == frozenset(_PSD_COMMODITY_TO_SLUGS[711100])

    def test_the_sugar_refining_stage_split_is_declared_exactly(self) -> None:
        sugar = _PSD_ATTR_FANOUT[612000]
        assert sugar[64] == _SUGAR_RAW_SLUGS == frozenset({"raw_sugar"})    # Raw Imports
        assert sugar[89] == _SUGAR_RAW_SLUGS                                 # Raw Exports
        assert sugar[74] == _SUGAR_WHITE_SLUGS == frozenset({"white_sugar"})# Refined Imp.
        assert sugar[99] == _SUGAR_WHITE_SLUGS                               # Refined Exp.
        # Beet/Cane is a CROP-SOURCE split, ORTHOGONAL to raw/white -- both slugs
        # are produced from both crops, so these fan to both. The one adjudication
        # a reader might expect to be a restriction and deliberately is not.
        assert sugar[30] == frozenset(_PSD_COMMODITY_TO_SLUGS[612000])
        assert sugar[43] == frozenset(_PSD_COMMODITY_TO_SLUGS[612000])

    def test_the_registry_keys_on_the_stable_id_not_the_label(self) -> None:
        # A string-identity join loses a source rename SILENTLY. The label lives in
        # a pin used only as a logged tripwire; the fan-out never reads it.
        for code, per_attr in _PSD_ATTR_FANOUT.items():
            for attr_id in per_attr:
                assert isinstance(attr_id, int), f"code {code} keyed on {attr_id!r}"
        assert _PSD_ATTR_ID_TO_DESC_PIN[29] == "Arabica Production"
        assert _PSD_ATTR_ID_TO_DESC_PIN[89] == "Raw Exports"
        assert set(_PSD_ATTR_ID_TO_DESC_PIN) <= {
            a for per in _PSD_ATTR_FANOUT.values() for a in per}


class TestR4LiveProof:
    """R2's posture: prove the failure R4 prevents actually happens without it."""

    @staticmethod
    def _without_r4():
        """Disable R4's adjudication by declaring both codes venue-only."""
        return (
            {},
            _PSD_HOMOGENEOUS_FANOUT_CODES | frozenset({711100, 612000}),
        )

    def test_without_r4_arabica_production_lands_on_robusta_coffee(self) -> None:
        orig_f, orig_h = U4._PSD_ATTR_FANOUT, U4._PSD_HOMOGENEOUS_FANOUT_CODES
        try:
            U4._PSD_ATTR_FANOUT, U4._PSD_HOMOGENEOUS_FANOUT_CODES = self._without_r4()
            naive = transform_psd_attributes_bronze_to_silver([_bronze(711100, _COFFEE_ROWS)])
        finally:
            U4._PSD_ATTR_FANOUT, U4._PSD_HOMOGENEOUS_FANOUT_CODES = orig_f, orig_h

        bad = naive[(naive.attribute == "Arabica Production")
                    & (naive.leviathan_slug == "robusta_coffee")]
        assert len(bad) == 1 and bad.value.iloc[0] == 600.0, (
            "the failure R4 exists to prevent did NOT reproduce -- if the fan-out "
            "moved, re-derive R4 before relaxing it")
        # and symmetrically, robusta output stamped on the two arabica slugs
        assert set(naive[naive.attribute == "Robusta Production"].leviathan_slug) == set(
            _PSD_COMMODITY_TO_SLUGS[711100])

    def test_with_r4_the_variety_attributes_reach_only_their_own_slugs(self) -> None:
        long = transform_psd_attributes_bronze_to_silver([_bronze(711100, _COFFEE_ROWS)])
        assert set(long[long.attribute == "Arabica Production"].leviathan_slug) == {
            "arabica_coffee", "brazilian_arabica_coffee"}
        assert set(long[long.attribute == "Robusta Production"].leviathan_slug) == {
            "robusta_coffee"}
        # the declared drop really drops
        assert long[long.attribute == "Other Production"].empty
        # and the sheet-level attributes still reach all three
        assert set(long[long.attribute == "Production"].leviathan_slug) == set(
            _PSD_COMMODITY_TO_SLUGS[711100])

    def test_without_r4_raw_exports_lands_on_white_sugar(self) -> None:
        orig_f, orig_h = U4._PSD_ATTR_FANOUT, U4._PSD_HOMOGENEOUS_FANOUT_CODES
        try:
            U4._PSD_ATTR_FANOUT, U4._PSD_HOMOGENEOUS_FANOUT_CODES = self._without_r4()
            naive = transform_psd_attributes_bronze_to_silver([_bronze(612000, _SUGAR_ROWS)])
        finally:
            U4._PSD_ATTR_FANOUT, U4._PSD_HOMOGENEOUS_FANOUT_CODES = orig_f, orig_h
        bad = naive[(naive.attribute == "Raw Exports") & (naive.leviathan_slug == "white_sugar")]
        assert len(bad) == 1 and bad.value.iloc[0] == 450.0

    def test_with_r4_the_refining_legs_reach_only_their_own_slug(self) -> None:
        long = transform_psd_attributes_bronze_to_silver([_bronze(612000, _SUGAR_ROWS)])
        assert set(long[long.attribute == "Raw Exports"].leviathan_slug) == {"raw_sugar"}
        assert set(long[long.attribute == "Raw Imports"].leviathan_slug) == {"raw_sugar"}
        assert set(long[long.attribute == "Refined Exp.(Raw Val)"].leviathan_slug) == {
            "white_sugar"}
        assert set(long[long.attribute == "Refined Imp.(Raw Val)"].leviathan_slug) == {
            "white_sugar"}
        assert set(long[long.attribute == "Cane Sugar Production"].leviathan_slug) == {
            "raw_sugar", "white_sugar"}

    def test_the_measured_block_count_for_one_release_shape(self) -> None:
        # One country x one vintage of both adjudicated sheets. Naive fan-out emits
        # 19*3 + 16*2 = 89 rows; R4 emits 89 - (4616-shaped blocks) = 78. Scaled to
        # the real object: 65,700 manufactured rows per release, on LIVE contract
        # slugs (ICE Robusta, ICE #5 white sugar).
        dfs = [_bronze(711100, _COFFEE_ROWS), _bronze(612000, _SUGAR_ROWS)]
        orig_f, orig_h = U4._PSD_ATTR_FANOUT, U4._PSD_HOMOGENEOUS_FANOUT_CODES
        try:
            U4._PSD_ATTR_FANOUT, U4._PSD_HOMOGENEOUS_FANOUT_CODES = self._without_r4()
            naive = transform_psd_attributes_bronze_to_silver(dfs)
        finally:
            U4._PSD_ATTR_FANOUT, U4._PSD_HOMOGENEOUS_FANOUT_CODES = orig_f, orig_h
        guarded = transform_psd_attributes_bronze_to_silver(dfs)
        assert len(naive) == 19 * 3 + 16 * 2 == 89
        # coffee: arabica loses 1 slug, robusta loses 2, other loses 3 -> 6
        # sugar: each of the four one-leg attributes loses 1 slug -> 4
        assert len(naive) - len(guarded) == 10
        assert len(guarded) == 79


class TestR4FailsClosed:

    def test_a_new_multi_slug_code_with_no_declaration_raises(self) -> None:
        # The edit this guards: someone adds a second slug to a single-slug code.
        # Nothing in this module changes, so only a transform-time check can catch it.
        orig_s, orig_m = U._PSD_COMMODITY_TO_SLUGS, U._PSD_COMMODITY_TO_MYS
        orig_s4 = U4._PSD_COMMODITY_TO_SLUGS
        try:
            widened = dict(orig_s)
            widened[2631000] = ["cotton", "cotton_no_2_zce"]
            U._PSD_COMMODITY_TO_SLUGS = widened
            U4._PSD_COMMODITY_TO_SLUGS = widened
            with pytest.raises(ValueError, match="declared in NEITHER"):
                transform_psd_attributes_bronze_to_silver([_bronze(2631000)])
        finally:
            U._PSD_COMMODITY_TO_SLUGS, U._PSD_COMMODITY_TO_MYS = orig_s, orig_m
            U4._PSD_COMMODITY_TO_SLUGS = orig_s4

    def test_an_uncovered_attribute_on_an_adjudicated_code_is_dropped_not_fanned(self) -> None:
        # A NEW USDA coffee label arrives. It must never be fanned blind. The
        # default is a named, logged DROP rather than a raise, because raising
        # would take the WHOLE daily transform down for every commodity -- the same
        # blast radius R1 warns about one module over.
        long = transform_psd_attributes_bronze_to_silver([
            _bronze(711100, _COFFEE_ROWS + [("Excelsa Production", 998,
                                             "(1000 60 KG BAGS)", 5.0)])])
        assert long[long.attribute == "Excelsa Production"].empty
        assert not long[long.attribute == "Production"].empty, (
            "the uncovered pair must be declined ALONE, never take the sheet with it")

    def test_the_raise_policy_is_available_for_a_backfill(self) -> None:
        with pytest.raises(ValueError, match="not covered by the fan-out registry"):
            transform_psd_attributes_bronze_to_silver(
                [_bronze(711100, _COFFEE_ROWS + [("Excelsa Production", 998,
                                                  "(1000 60 KG BAGS)", 5.0)])],
                on_uncovered="raise")

    def test_an_uncovered_attribute_on_a_VENUE_ONLY_code_still_fans(self) -> None:
        # Homogeneous codes are declared interchangeable, so a new attribute there
        # needs no adjudication -- there is no fact that belongs to CBOT corn and
        # not to MATIF maize on one global sheet.
        long = transform_psd_attributes_bronze_to_silver([
            _bronze(440000, [("Some New Line", 997, "(1000 MT)", 7.0)])])
        assert set(long.leviathan_slug) == set(_PSD_COMMODITY_TO_SLUGS[440000])

    def test_a_bad_policy_value_raises(self) -> None:
        with pytest.raises(ValueError, match="on_uncovered"):
            transform_psd_attributes_bronze_to_silver([_bronze(440000)],
                                                      on_uncovered="fan")


# ---------------------------------------------------------------------------
# (d) The branch point: BEFORE the _TARGET_ATTRS filter.
# ---------------------------------------------------------------------------
class TestBranchPoint:

    def test_rows_the_wide_table_drops_at_step_6_are_present_here(self) -> None:
        # The T1 payload, ranked: Crush first, then the demand decomposition, then
        # the TY trade trio. NONE of them is in _TARGET_ATTRS, so the wide producer
        # discards every one of them at step 6 on every release.
        t1 = [
            ("Crush",                  7,   "(1000 MT)", 1000.0),
            ("Feed Dom. Consumption",  130, "(1000 MT)", 400.0),
            ("FSI Consumption",        192, "(1000 MT)", 300.0),
            ("Feed Waste Dom. Cons.",  161, "(1000 MT)", 60.0),
            ("Food Use Dom. Cons.",    149, "(1000 MT)", 50.0),
            ("Industrial Dom. Cons.",  140, "(1000 MT)", 20.0),
            ("TY Exports",             113, "(1000 MT)", 90.0),
            ("TY Imports",             81,  "(1000 MT)", 30.0),
            ("TY Imp. from U.S.",      84,  "(1000 MT)", 12.0),
        ]
        for attr, _, _, _ in t1:
            assert attr not in _TARGET_ATTRS

        frame = _bronze(2222000, _MASS_ROWS + t1)
        long = transform_psd_attributes_bronze_to_silver([frame])
        assert set(a for a, _, _, _ in t1) <= set(long.attribute)
        # and the wide table, from the very same frame, carries none of them
        wide = transform_psd_bronze_to_silver([frame])
        assert "Crush" not in wide.columns
        assert set(wide.columns) == set(U._SILVER_COLS)

    def test_the_branch_is_AFTER_the_slug_fan_out_and_the_wasde_date_fix(self) -> None:
        # Branching earlier would mean re-deriving both, and two copies of one
        # prefix drift apart silently.
        long = transform_psd_attributes_bronze_to_silver([_bronze(440000)])
        assert set(long.leviathan_slug) == set(_PSD_COMMODITY_TO_SLUGS[440000])
        # corn MYS=9, month_code=1 -> (9+1-2)%12+1 = 9 -> 2024-09-10, not the ingest date
        assert set(long.release_date) == {"2024-09-10"}

    def test_the_shared_prefix_leaves_the_wide_transform_byte_identical(self) -> None:
        # The extraction of steps 1-5 into prepare_psd_combined_frame must be a
        # refactor, not a behaviour change.
        frame = _bronze(612000, _SUGAR_ROWS)
        wide = transform_psd_bronze_to_silver([frame])
        assert set(wide.leviathan_slug) == {"raw_sugar", "white_sugar"}
        # Total Disappearance (126) is still remapped into consumption_mt for the
        # wide table -- 480.0 * 1000
        assert set(wide.consumption_mt) == {480_000.0}


class TestNativeAttributeLabels:

    def test_the_three_remapped_labels_keep_USDAs_own_spelling_here(self) -> None:
        # The shared prefix folds Total Disappearance / Domestic Use / Fresh Dom.
        # Consumption onto "Domestic Consumption" for the WIDE pivot. The long table
        # emits the native label, because attribute_id is in its schema and a table
        # where one label spans four ids cannot be joined to the source's own key.
        # MEASURED: codes 612000 / 2631000 / 571120 publish NO attribute 125 of
        # their own, so this is a fidelity choice, not a collision dodge.
        sugar = transform_psd_attributes_bronze_to_silver([_bronze(612000, _SUGAR_ROWS)])
        assert "Total Disappearance" in set(sugar.attribute)
        assert "Domestic Consumption" not in set(sugar.attribute)
        assert set(sugar[sugar.attribute == "Total Disappearance"].attribute_id) == {126}

        cotton = transform_psd_attributes_bronze_to_silver([
            _bronze(2631000, [("Domestic Use", 142, "1000 480 lb. Bales", 77.0)])])
        assert list(cotton.attribute) == ["Domestic Use"]
        assert list(cotton.attribute_id) == [142]

        citrus = transform_psd_attributes_bronze_to_silver([
            _bronze(571120, [("Fresh Dom. Consumption", 135, "(1000 MT)", 480.0)])])
        assert list(citrus.attribute) == ["Fresh Dom. Consumption"]
        assert list(citrus.attribute_id) == [135]

    def test_a_genuine_domestic_consumption_keeps_its_own_id(self) -> None:
        long = transform_psd_attributes_bronze_to_silver([_bronze(440000)])
        dc = long[long.attribute == "Domestic Consumption"]
        assert set(dc.attribute_id) == {125}


# ---------------------------------------------------------------------------
# (e) month_code 0 -- the pre-WASDE mass.
# ---------------------------------------------------------------------------
class TestPreWasdeMass:

    def test_month_code_zero_rows_survive_with_their_real_release_date(self) -> None:
        # 245,315 in-scope rows carry month_code 0 (MY 1960-2004) across 12 codes,
        # including both R4-adjudicated sheets. _compute_psd_release_dates anchors
        # them to Jan 1 of the market year so they stay visible to any historical
        # crop-year cutoff; that anchor must survive the branch.
        long = transform_psd_attributes_bronze_to_silver([
            _bronze(711100, _COFFEE_ROWS, market_year=1990, month_code=0)])
        assert set(long.wasde_release_month) == {0}
        assert set(long.release_date) == {"1990-01-01"}
        assert set(long.market_year) == {1990}
        # and R4 still adjudicates them -- the pre-WASDE mass is not a bypass
        assert set(long[long.attribute == "Robusta Production"].leviathan_slug) == {
            "robusta_coffee"}

    def test_month_zero_and_a_real_month_coexist_in_one_grain(self) -> None:
        long = transform_psd_attributes_bronze_to_silver([
            _bronze(612000, _SUGAR_ROWS, market_year=2004, month_code=0),
            _bronze(612000, _SUGAR_ROWS, market_year=2004, month_code=5),
        ])
        assert set(long.wasde_release_month) == {0, 5}
        assert int(long.duplicated(subset=_GRAIN_COLS).sum()) == 0


# ---------------------------------------------------------------------------
# Degenerate inputs.
# ---------------------------------------------------------------------------
class TestDegenerate:

    def test_empty_dfs_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one DataFrame"):
            transform_psd_attributes_bronze_to_silver([])

    def test_attribute_id_is_required(self) -> None:
        frame = _bronze(440000).drop(columns=["attribute_id"])
        with pytest.raises(ValueError, match="attribute_id"):
            transform_psd_attributes_bronze_to_silver([frame])

    def test_an_all_out_of_scope_frame_returns_the_empty_schema(self) -> None:
        long = transform_psd_attributes_bronze_to_silver([_bronze(574000)])  # Apples
        assert long.empty
        assert list(long.columns) == _SILVER_PSD_ATTR_COLS


# ---------------------------------------------------------------------------
# L2-3 -- THE CARD, AND THE DECLARED ROSTER THAT IS THE D-6 DECISION.
# ---------------------------------------------------------------------------
# The roster on the numbers card is not documentation. ``load_pg_numbers.load_table``
# filters every TALL table to ``field(metric_col).isin(ts.metrics)``, so an attribute
# absent from the card is invisible to serving AND to the census whatever silver holds
# -- and, symmetrically, declaring one is what spends RDS storage on a database whose
# autoscaling is OFF. So the roster IS the admission decision and it is pinned here.
#
# THE PIN IS THE ROSTER ITSELF, NOT THE CENSUS FILE. ``data/dec_p0/psd_attribute_census
# .json`` is an untracked run artifact: it is present in the main tree and absent from a
# fresh worktree, so a test that only read it would SKIP in exactly the checkout a
# reviewer uses. The measured figures therefore live in the table below as literals and
# the arithmetic is asserted from them unconditionally; the census cross-check at the end
# re-derives the same numbers from the artifact WHEN it is on disk, and says which file
# it wanted when it is not.
#
# COLUMNS: attribute_id (USDA's own, the key R4 joins on), the card's declared unit (None
# = the card deliberately declares none because the attribute is multi-unit in scope),
# the census in-scope row count BEFORE slug fan-out, and ADMITTED = the post-fan-out rows
# the mirror actually loads. Admitted == in_scope x (number of slugs the attribute reaches)
# and for the six variety/refining splits that multiplier is R4's, not the code's -- which
# is the entire reason R4 ships with the table.
_ROSTER: dict[str, tuple[int, str | None, int, int]] = {
    # -- T1, the ranked payload. These nine sum to 742,057 == the D-6 admission number.
    "Crush":                  (7,   "1000 MT",             52475,  71551),
    "Feed Dom. Consumption":  (130, "1000 MT",             31153,  84759),
    "FSI Consumption":        (192, "1000 MT",             31153,  84759),
    "Feed Waste Dom. Cons.":  (161, "1000 MT",             60140,  83368),
    "Food Use Dom. Cons.":    (149, "1000 MT",             60140,  83368),
    "Industrial Dom. Cons.":  (140, "1000 MT",             43446,  57127),
    "TY Exports":             (113, "1000 MT",             38769,  92375),
    "TY Imports":             (81,  "1000 MT",             38769,  92375),
    "TY Imp. from U.S.":      (84,  "1000 MT",             38769,  92375),
    # -- the FOUR consumption labels: 237,581 together == every slug-vintage exactly once.
    "Domestic Consumption":   (125, None,                 123090, 209156),
    "Total Disappearance":    (126, "1000 MT",              9501,  19002),
    "Domestic Use":           (142, "1000 480 lb. Bales",   7777,   7777),
    "Fresh Dom. Consumption": (135, "1000 MT",              1646,   1646),
    # -- the variety / refining splits: R4-restricted, so admitted < a naive fan-out.
    "Arabica Production":     (29,  "1000 60 KG BAGS",      4616,   9232),
    "Robusta Production":     (53,  "1000 60 KG BAGS",      4616,   4616),
    "Raw Imports":            (64,  "1000 MT",              9501,   9501),
    "Raw Exports":            (89,  "1000 MT",              9501,   9501),
    "Refined Imp.(Raw Val)":  (74,  "1000 MT",              9501,   9501),
    "Refined Exp.(Raw Val)":  (99,  "1000 MT",              9501,   9501),
    # -- the head count, carried because the per-row unit column retires the hazard.
    "Cows In Milk":           (6,   "1000 HEAD",            1917,   1917),
}
_T1_LABELS: tuple[str, ...] = (
    "Crush", "Feed Dom. Consumption", "FSI Consumption", "Feed Waste Dom. Cons.",
    "Food Use Dom. Cons.", "Industrial Dom. Cons.", "TY Exports", "TY Imports",
    "TY Imp. from U.S.",
)
_CONSUMPTION_LABELS: tuple[str, ...] = (
    "Domestic Consumption", "Total Disappearance", "Domestic Use", "Fresh Dom. Consumption",
)
_D6_ADMISSION = 742057          # the T1 nine -- the census's own answers.e_d6_number
_DECLARED_ADMISSION = 1033407   # the whole roster, post-R4, ON THE CENSUS OBJECT (2026-08-13)
_CONSUMPTION_ROWS = 237581      # the four labels together
# The LIVE serving figure, measured on the first canonical object (2026-08-26, certified manifest
# silver_psd_attributes-1787727710260): the same 20-metric roster over 3,397,958 physical rows.
# ~4.3% above the census figure because the producer consumed every DISTINCT vendor snapshot in
# bronze (raw-ETag dedup kept 3-4), preserving vintages that survive only in older/newer snapshots.
# TWO PROVENANCES BY DESIGN: the census pins (_ROSTER figures, _D6_ADMISSION, _DECLARED_ADMISSION)
# stay frozen against their artifact; the card's row_count is the live figure and moves at each
# canonical re-measure -- decoupling them here is what lets both stay true at once.
_LIVE_SERVED_ROWS = 1079487
_CENSUS = _REPO / "data" / "dec_p0" / "psd_attribute_census.json"


def _psd_attr_card() -> dict:
    return yaml.safe_load(
        (_REPO / "configs" / "graphrag" / "numbers" / "tables.yaml")
        .read_text(encoding="utf-8"))["tables"]["silver_psd_attributes"]


class TestTheCardIsTheTable:

    def test_the_card_is_tall_on_the_producers_own_columns(self) -> None:
        # A tall card that names a column the producer does not write compiles SQL that
        # dies COLUMN_NOT_FOUND at serving time (the silver_nasa_power incident). Bind the
        # three tall columns to the producer's output schema rather than re-typing them.
        card = _psd_attr_card()
        assert card["shape"] == "tall"
        for key in ("commodity_col", "country_col", "period_col", "knowledge_date_col",
                    "metric_col", "value_col", "unit_col"):
            assert card[key] in _SILVER_PSD_ATTR_COLS, (key, card[key])
        assert card["metric_col"] == "attribute"
        assert card["value_col"] == "value"
        assert card["unit_col"] == "unit"

    def test_the_serving_grain_is_not_the_physical_grain(self) -> None:
        # THE LANE-3 REVIEW'S FATAL #1, pinned in the fixed direction. The PHYSICAL grain
        # (with wasde_release_month) is the F010 contract's natural_key == the transform's
        # _GRAIN_COLS -- the table retains all ~13 WASDE vintages per marketing year. The
        # CARD declares NO grain_cols: its serving identity is the tall fallback
        # [slug, country, market_year, attribute], which is what lets build_sql's
        # latest-vintage ROW_NUMBER collapse those vintages to "the latest release on or
        # before asof". Declaring the physical grain on the card partitions the ROW_NUMBER
        # by the table's own uniqueness key -- _rn = 1 filters NOTHING and every ask fans
        # ~13 vintages per marketing year. silver_psd is the precedent: its natural_key
        # carries release_date, its card's serving grain does not.
        card = _psd_attr_card()
        assert "grain_cols" not in card, (
            "grain_cols on this card makes the as-of vintage collapse a structural no-op; "
            "the physical grain lives in the F010 natural_key, not here")
        contract = yaml.safe_load(
            (_REPO / "configs" / "silver" / "tables" / "silver_psd_attributes.yaml")
            .read_text(encoding="utf-8"))
        assert contract["natural_key"] == list(_GRAIN_COLS)
        assert "wasde_release_month" in contract["natural_key"]
        assert contract["vintage_retention"] == "per-vintage"

    def test_the_pit_trio_is_the_vintage_one(self) -> None:
        card = _psd_attr_card()
        assert card["knowledge_date_col"] == "release_date"
        assert card["knowledge_semantics"] == "vintage"
        assert "publication_lag_days" not in card      # same as silver_psd: no data-date lag
        assert card["period_col"] == "market_year" and card["period_sql_type"] == "int"

    def test_the_coverage_census_is_declared_without_a_false_ceiling(self) -> None:
        # PA-1: row_count is the SERVED subset -- the registry field's own contract
        # (registry.py glosses it as "MEASURED rows the card SERVES", the
        # silver_wap_table01_revisions precedent), and for a tall card the served subset
        # is exactly what the pg mirror admits: the declared roster, measured on the LIVE
        # canonical object (_LIVE_SERVED_ROWS -- see its comment for why it differs from
        # the census figure). The full-object figure lives in the card's COVERAGE comment.
        # first_obs is the table-wide floor. NO last_obs -- the bulk file is cumulative
        # and re-fires monthly, and a stale end date is the model DECLINING a question
        # the table can answer.
        card = _psd_attr_card()
        assert card["row_count"] == _LIVE_SERVED_ROWS
        assert card["first_obs"] == "1960"
        assert card["cadence"] == "annual"
        assert "last_obs" not in card


class TestTheDeclaredRosterIsTheD6Decision:

    def test_the_card_declares_exactly_the_adjudicated_roster(self) -> None:
        declared = set(_psd_attr_card()["metrics"])
        assert declared == set(_ROSTER), {
            "on_card_not_adjudicated": sorted(declared - set(_ROSTER)),
            "adjudicated_not_on_card": sorted(set(_ROSTER) - declared),
            "why_this_matters": "the roster IS the pg admission set (load_table filters tall "
                                "tables to it), so a metric added here silently adds rows to a "
                                "mirror whose database cannot autoscale"}

    def test_the_t1_nine_sum_to_the_d6_number_exactly(self) -> None:
        assert sum(_ROSTER[k][3] for k in _T1_LABELS) == _D6_ADMISSION

    def test_the_whole_roster_sums_to_the_declared_footprint(self) -> None:
        # 742,057 (T1) + 237,581 (the four consumption labels) + 51,852 (the six splits,
        # post-R4) + 1,917 (Cows In Milk) = 1,033,407. Stated as the sum rather than as a
        # literal so a roster edit that forgets this number fails with the arithmetic.
        assert sum(v[3] for v in _ROSTER.values()) == _DECLARED_ADMISSION

    def test_the_four_consumption_labels_are_every_slug_vintage_once(self) -> None:
        assert sum(_ROSTER[k][3] for k in _CONSUMPTION_LABELS) == _CONSUMPTION_ROWS

    def test_the_card_declares_a_unit_only_where_one_unit_is_true(self) -> None:
        # A metric-level unit that is true of only SOME of the attribute's rows is worse
        # than none: _metric_line renders it verbatim onto every citation. Domestic
        # Consumption spans four in-scope units, so its card entry declares none and the
        # row's unit column governs -- and that is asserted, not left to good intentions.
        metrics = _psd_attr_card()["metrics"]
        for label, (_id, unit, _rows, _adm) in _ROSTER.items():
            got = (metrics[label].get("unit") or "") or None
            assert got == unit, (label, got, unit)

    def test_the_split_attributes_admission_is_r4s_and_not_the_codes(self) -> None:
        # THE NON-VACUOUS HALF. Every split attribute's admitted row count is DERIVED from
        # the live R4 registry (in-scope rows x the slugs R4 lets it reach), never copied
        # from the table above -- so widening one of these adjudications back to the whole
        # code fails here with the row count it would manufacture.
        splits = {29: 711100, 53: 711100, 64: 612000, 89: 612000, 74: 612000, 99: 612000}
        for label, (attr_id, _unit, in_scope, admitted) in _ROSTER.items():
            code = splits.get(attr_id)
            if code is None:
                continue
            reach = len(_PSD_ATTR_FANOUT[code][attr_id])
            assert in_scope * reach == admitted, (label, reach, in_scope * reach, admitted)
            assert reach < len(_PSD_COMMODITY_TO_SLUGS[code]), (
                f"{label} now fans to EVERY slug of {code} -- that is the manufactured-row "
                f"failure R4 exists to prevent, and it would add "
                f"{in_scope * len(_PSD_COMMODITY_TO_SLUGS[code]) - admitted} false rows")

    def test_the_refused_attributes_are_absent_from_the_roster(self) -> None:
        # Two named declines, and neither may drift onto the card without also leaving the
        # transform's refusal: Milling Rate carries a FALSE '(1000 MT)' label on a 1e4-scaled
        # rate, and coffee's Other Production belongs to no slug.
        declared_ids = {v[0] for v in _ROSTER.values()}
        assert 182 in _PSD_UNIT_MISLABELLED_ATTR_IDS and 182 not in declared_ids
        assert _PSD_ATTR_FANOUT[711100][56] == frozenset() and 56 not in declared_ids

    def test_the_notes_teach_the_four_labels_the_refusal_and_the_ceiling(self) -> None:
        blob = " ".join(_psd_attr_card()["notes"].split()).lower()
        assert "consumption is four labels" in blob
        assert "milling rate" in blob
        assert "2016-10-10" in blob          # broilers_poultry's per-slug content ceiling
        assert "unit` column is authoritative" in blob or "unit` is authoritative" in blob

    @pytest.mark.skipif(not _CENSUS.exists(),
                        reason=f"L2-0 census artifact absent from this checkout: {_CENSUS} "
                               f"(untracked run output; present in the main tree). The roster "
                               f"pins above run unconditionally -- this is the re-derivation.")
    def test_the_roster_figures_re_derive_from_the_banked_census(self) -> None:
        doc = json.loads(_CENSUS.read_text(encoding="utf-8"))
        by_label = {l["attribute_desc"]: l for l in doc["labels"]}
        for label, (attr_id, _unit, in_scope, _adm) in _ROSTER.items():
            rec = by_label[label]
            assert rec["attribute_ids"] == [attr_id], (label, rec["attribute_ids"])
            assert rec["rows_in_scope"] == in_scope, (label, rec["rows_in_scope"], in_scope)
        # the census answered D-6 on its own naive (R4-blind) fan-out of the T1 nine; those
        # nine touch no heterogeneous code, so the two derivations must agree exactly.
        assert doc["answers"]["e_d6_number"]["rows_in_scope_post_slug_explode"] == _D6_ADMISSION
        assert sorted(doc["answers"]["e_d6_number"]["declared_labels_byte_exact"]) == \
            sorted(_T1_LABELS)
