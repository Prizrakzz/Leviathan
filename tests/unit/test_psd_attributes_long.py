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

import pandas as pd
import pytest

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
