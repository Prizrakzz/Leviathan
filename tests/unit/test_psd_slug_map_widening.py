"""D-EC XC-1 / XC-7 -- the PSD projection widening, pinned as decisions.

The slug map went from 13 commodity codes to 47 (29 -> 63 ``leviathan_slug``
values), which is what stops silver discarding 52.5% of the bulk ZIP the
platform already fetches every day.

These tests pin the DECISIONS, not the diff. Each of the three rules the map
obeys is an invariant of the transform underneath it, and a future widening that
breaks one fails here rather than in production -- where the failure mode is a
silently dropped balance sheet that no alarm can see.

Row counts and code counts quoted below were MEASURED, not assumed, on
``raw/production/source=usda_psd/release_type=bulk/release_date=2026-08-13/
psd_alldata.zip`` (2,092,687 rows, 63 commodity codes) and on a local run of the
widened transform over it (silver 164,288 -> 237,581 rows, 29 -> 63 slugs).

Pure Python -- no S3, no AWS.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

import leviathan.transforms.bronze_to_silver.usda_psd as U
from leviathan.transforms.bronze_to_silver.usda_psd import (
    _PSD_COMMODITY_TO_MYS,
    _PSD_COMMODITY_TO_SLUGS,
    _PSD_FORWARD_DECLARED_SLUGS,
    _PSD_UNBINDABLE_CONTRACT_SLUGS,
    _PSD_UNMAPPED_CODES,
    _UNIT_FACTOR,
    transform_psd_bronze_to_silver,
)

_REPO = Path(__file__).resolve().parents[2]

_MASS_ATTRS = {
    "Beginning Stocks":     100.0,
    "Production":           200.0,
    "Imports":              50.0,
    "Exports":              80.0,
    "Ending Stocks":        70.0,
    "Domestic Consumption": 200.0,
}


def _bronze(commodity_code: int, *, unit: str = "(1000 MT)",
            attrs: dict[str, float] | None = None, market_year: int = 2024,
            month_code: int = 1, release_date: str = "2026-08-13") -> pd.DataFrame:
    """One bronze row per attribute, all on the same unit."""
    attrs = _MASS_ATTRS if attrs is None else attrs
    return pd.DataFrame([
        {
            "commodity_code": commodity_code,
            "commodity_desc": f"code-{commodity_code}",
            "country_name":   "World",
            "market_year":    market_year,
            "month_code":     month_code,
            "attribute_desc": attr,
            "unit_desc":      unit,
            "value":          val,
            "release_date":   release_date,
        }
        for attr, val in attrs.items()
    ])


def _mapped_slugs() -> set[str]:
    return {s for slugs in _PSD_COMMODITY_TO_SLUGS.values() for s in slugs}


# ---------------------------------------------------------------------------
# R1 / R2 / R3 -- the three rules the map's own header states.
# ---------------------------------------------------------------------------
class TestSlugMapInvariants:

    def test_r1_every_mapped_code_has_a_marketing_year(self) -> None:
        # Step 4b does .map(_PSD_COMMODITY_TO_MYS).astype(int). A code present in
        # SLUGS and absent from MYS raises "cannot convert float NaN to integer"
        # for the WHOLE frame -- one missing entry takes the entire transform
        # down, not merely its own rows. Identical key sets is the only safe state.
        assert set(_PSD_COMMODITY_TO_SLUGS) == set(_PSD_COMMODITY_TO_MYS), (
            "SLUGS/MYS key drift: "
            f"slugs-only={sorted(set(_PSD_COMMODITY_TO_SLUGS) - set(_PSD_COMMODITY_TO_MYS))} "
            f"mys-only={sorted(set(_PSD_COMMODITY_TO_MYS) - set(_PSD_COMMODITY_TO_SLUGS))}"
        )

    def test_r1_the_missing_entry_really_does_take_the_frame_down(self) -> None:
        # The rule above is worth pinning only if its failure is as bad as claimed.
        orig_m = U._PSD_COMMODITY_TO_MYS
        try:
            U._PSD_COMMODITY_TO_MYS = {k: v for k, v in orig_m.items() if k != 440000}
            with pytest.raises((ValueError, TypeError, pd.errors.IntCastingNaNError)):
                transform_psd_bronze_to_silver([_bronze(440000)])
        finally:
            U._PSD_COMMODITY_TO_MYS = orig_m

    def test_r1_every_marketing_year_is_a_calendar_month(self) -> None:
        bad = {c: m for c, m in _PSD_COMMODITY_TO_MYS.items() if not 1 <= m <= 12}
        assert bad == {}, f"marketing-year start month out of range: {bad}"

    def test_r2_no_slug_is_claimed_by_two_commodity_codes(self) -> None:
        # THE SHARP EDGE of the widening. The pivot key is
        # (slug, country, market_year, wasde_release_month, release_date) and
        # step 10 drops duplicates on it keeping FIRST, so two codes sharing one
        # slug means one commodity's whole balance sheet vanishes with no warning
        # anybody reads. Fan-out (one code -> many slugs) stays legal and is how
        # the original 13 work; it is the reverse that is banned.
        seen: dict[str, int] = {}
        collisions: list[str] = []
        for code, slugs in _PSD_COMMODITY_TO_SLUGS.items():
            for s in slugs:
                if s in seen:
                    collisions.append(f"{s!r} claimed by {seen[s]} and {code}")
                seen[s] = code
        assert collisions == [], "; ".join(collisions)

    def test_r2_a_collision_really_would_lose_a_balance_sheet(self) -> None:
        orig_s, orig_m = U._PSD_COMMODITY_TO_SLUGS, U._PSD_COMMODITY_TO_MYS
        try:
            U._PSD_COMMODITY_TO_SLUGS = {440000: ["x"], 410000: ["x"]}
            U._PSD_COMMODITY_TO_MYS = {440000: 9, 410000: 9}
            corn = _bronze(440000)
            wheat = _bronze(410000)
            wheat.loc[wheat.attribute_desc == "Production", "value"] = 999.0
            silver = transform_psd_bronze_to_silver([corn, wheat])
        finally:
            U._PSD_COMMODITY_TO_SLUGS, U._PSD_COMMODITY_TO_MYS = orig_s, orig_m
        assert len(silver) == 1, (
            "two commodity codes on one slug did NOT collide -- if the pivot key "
            "changed, re-derive R2 before relaxing it"
        )

    def test_r3_forward_declared_slugs_are_all_actually_in_the_map(self) -> None:
        # The forward-declaration set is documentation ONLY if it is bound to the
        # map: an id that drifts out of the map but stays in the set would claim a
        # silver key nothing writes.
        assert _PSD_FORWARD_DECLARED_SLUGS <= _mapped_slugs(), (
            f"forward-declared but unmapped: "
            f"{sorted(_PSD_FORWARD_DECLARED_SLUGS - _mapped_slugs())}")

    def test_r3_context_commodity_ids_are_spelled_verbatim(self) -> None:
        # The declared context-commodity ids are used exactly as
        # configs/graphrag/commodity_hierarchy.yaml spells them and are never
        # renamed here. The spellings are stated literally rather than imported:
        # the hierarchy is gitignored private IP and may be absent from a
        # checkout, and a test that skips when its subject is missing pins nothing.
        mapped = _mapped_slugs()
        for cid in ("barley", "sorghum", "sunflower", "sunflower_oil", "fish_meal"):
            assert cid in mapped, f"pre-D15 context commodity {cid!r} lost its PSD binding"
        for cid in ("cottonseed", "coconut", "palm_kernel", "peanut",
                    "olive_oil", "fresh_citrus"):
            assert cid in mapped, f"D15 context commodity {cid!r} lost its PSD binding"

    def test_r3_no_d15_id_was_invented_where_psd_publishes_nothing(self) -> None:
        # ddgs, hfcs, used_cooking_oil, tallow, pulses and minor_oilseeds are D15
        # nodes that USDA PSD carries NO sheet for -- they are not among the 63
        # codes. Minting a silver key for them here would be a numbers binding
        # with no numbers behind it.
        mapped = _mapped_slugs()
        for cid in ("ddgs", "hfcs", "used_cooking_oil", "tallow",
                    "pulses", "minor_oilseeds", "minor_cereals"):
            assert cid not in mapped, (
                f"{cid!r} has a PSD slug but PSD publishes no sheet for it -- "
                f"if USDA added one, say so in the map's disposition register")


# ---------------------------------------------------------------------------
# The disposition register: all 63 codes accounted for, with reasons.
# ---------------------------------------------------------------------------
class TestCommodityCodeDisposition:

    def test_every_code_is_either_mapped_or_refused_with_a_reason(self) -> None:
        overlap = set(_PSD_COMMODITY_TO_SLUGS) & set(_PSD_UNMAPPED_CODES)
        assert overlap == set(), f"code both mapped and refused: {sorted(overlap)}"
        assert len(_PSD_COMMODITY_TO_SLUGS) + len(_PSD_UNMAPPED_CODES) == 63, (
            "the disposition register no longer covers the 63 commodity codes measured in the "
            "2026-08-13 bulk ZIP -- a new USDA code must be dispositioned, not ignored"
        )
        blank = [c for c, why in _PSD_UNMAPPED_CODES.items() if len(why.strip()) < 40]
        assert blank == [], f"refusal without a real reason: {blank}"

    def test_the_counts_are_the_measured_ones(self) -> None:
        assert len(_PSD_COMMODITY_TO_SLUGS) == 47      # was 13
        assert len(_PSD_UNMAPPED_CODES) == 16
        assert len(_mapped_slugs()) == 63              # was 29

    def test_head_count_codes_stay_refused_on_both_sides(self) -> None:
        # 11000/13000 publish (1000 HEAD) under the target attributes. The fence
        # is TWO-SIDED -- the codes are refused AND "(1000 HEAD)" has no unit
        # factor -- so restoring either half alone still cannot land a head count
        # in production_mt.
        for code in (11000, 13000):
            assert code in _PSD_UNMAPPED_CODES
            assert code not in _PSD_COMMODITY_TO_SLUGS
        assert "(1000 HEAD)" not in _UNIT_FACTOR

    def test_cwe_is_the_only_new_unit(self) -> None:
        assert _UNIT_FACTOR["(1000 MT CWE)"] == 1_000.0
        assert set(_UNIT_FACTOR) == {
            "(1000 MT)", "(MT)", "1000 480 lb. Bales", "(1000 60 KG BAGS)",
            "(1000 HA)", "(MT/HA)", "(KG/HA)", "(1000 MT CWE)",
        }

    def test_the_soy_local_codes_are_refused_for_the_my_convention_reason(self) -> None:
        for code in (813101, 2222001, 4232001):
            assert code in _PSD_UNMAPPED_CODES
            assert "Local" in _PSD_UNMAPPED_CODES[code] or "813101" in _PSD_UNMAPPED_CODES[code]

    def test_cocoa_is_the_only_contract_left_without_a_psd_sheet(self) -> None:
        # USDA PSD publishes no cocoa sheet at all. frozen_orange_juice WAS the
        # second member of this set until XC-7 closed it.
        assert _PSD_UNBINDABLE_CONTRACT_SLUGS == frozenset({"cocoa"})
        assert not (_PSD_UNBINDABLE_CONTRACT_SLUGS & _mapped_slugs())


# ---------------------------------------------------------------------------
# XC-7 -- the FCOJ binding.
# ---------------------------------------------------------------------------
class TestFcojBinding:

    def test_orange_juice_code_binds_the_contract_slug(self) -> None:
        assert _PSD_COMMODITY_TO_SLUGS[585100] == ["frozen_orange_juice"]

    def test_fresh_orange_code_binds_the_context_node_not_the_contract(self) -> None:
        # The fruit is a different subject from the juice. Sending 571120 to the
        # contract would file an oranges balance sheet under an FCOJ label --
        # exactly the confusion D15 minted `fresh_citrus` to stop.
        assert _PSD_COMMODITY_TO_SLUGS[571120] == ["fresh_citrus"]

    def test_the_other_three_citrus_codes_are_refused_under_r2(self) -> None:
        for code in (571220, 572120, 572220):     # tangerines, lemons/limes, grapefruit
            assert code in _PSD_UNMAPPED_CODES
            why = _PSD_UNMAPPED_CODES[code]
            assert "fresh_citrus" in why or "571220" in why

    def test_fresh_dom_consumption_is_remapped_so_fresh_citrus_carries_a_number(self) -> None:
        # Without the third remap the column would be NULL on every fresh-citrus
        # row while USDA publishes the figure -- the same silent hole the sugar
        # and cotton remaps already exist to close.
        silver = transform_psd_bronze_to_silver([
            _bronze(571120, attrs={"Production": 500.0, "Imports": 20.0,
                                   "Exports": 30.0, "Fresh Dom. Consumption": 480.0})])
        assert list(silver.leviathan_slug) == ["fresh_citrus"]
        assert silver.consumption_mt.iloc[0] == 480_000.0

    def test_the_remap_is_slug_scoped_and_never_reaches_another_sheet(self) -> None:
        silver = transform_psd_bronze_to_silver([_bronze(440000)])
        assert silver.consumption_mt.iloc[0] == 200_000.0

    def test_a_plain_domestic_consumption_on_the_citrus_sheet_still_works(self) -> None:
        silver = transform_psd_bronze_to_silver([_bronze(571120)])
        assert silver.consumption_mt.iloc[0] == 200_000.0


# ---------------------------------------------------------------------------
# The new families survive the transform end to end.
# ---------------------------------------------------------------------------
class TestWidenedFamiliesTransform:

    @pytest.mark.parametrize(
        "code,slug",
        [
            (430000, "barley"),
            (459200, "sorghum"),
            (452000, "oats"),
            (451000, "rye"),
            (459100, "millet"),
            (459900, "mixed_grain"),
            (2223000, "cottonseed"),
            (813300, "cottonseed_meal"),
            (4233000, "cottonseed_oil"),
            (2221000, "peanut"),
            (2231000, "coconut"),
            (2232000, "palm_kernel"),
            (4235000, "olive_oil"),
            (4236000, "sunflower_oil"),
            (814200, "fish_meal"),
            (114200, "broilers_poultry"),
            (115000, "chicken_meat"),
            (223000, "milk_fluid"),
            (240000, "cheese"),
            (230000, "butter"),
        ],
    )
    def test_family_lands_under_its_slug_in_metric_tonnes(self, code: int, slug: str) -> None:
        silver = transform_psd_bronze_to_silver([_bronze(code)])
        assert list(silver.leviathan_slug) == [slug]
        assert silver.production_mt.iloc[0] == 200_000.0

    def test_carcass_weight_equivalent_converts_as_a_thousand_tonnes(self) -> None:
        silver = transform_psd_bronze_to_silver([_bronze(111000, unit="(1000 MT CWE)")])
        assert list(silver.leviathan_slug) == ["cattle_beef"]
        assert silver.production_mt.iloc[0] == 200_000.0

    def test_a_head_count_row_raises_rather_than_converting(self) -> None:
        # Belt and braces on the two-sided fence: even if a future edit mapped
        # 11000, the missing unit factor makes the transform refuse loudly instead
        # of writing head counts into an all-tonnes column.
        orig_s, orig_m = U._PSD_COMMODITY_TO_SLUGS, U._PSD_COMMODITY_TO_MYS
        try:
            U._PSD_COMMODITY_TO_SLUGS = {11000: ["cattle_numbers"]}
            U._PSD_COMMODITY_TO_MYS = {11000: 1}
            with pytest.raises(ValueError, match="unrecognised unit_desc"):
                transform_psd_bronze_to_silver([_bronze(11000, unit="(1000 HEAD)")])
        finally:
            U._PSD_COMMODITY_TO_SLUGS, U._PSD_COMMODITY_TO_MYS = orig_s, orig_m

    def test_a_widened_frame_still_produces_the_pinned_silver_columns(self) -> None:
        from leviathan.transforms.bronze_to_silver.usda_psd import _SILVER_COLS
        silver = transform_psd_bronze_to_silver(
            [_bronze(240000), _bronze(430000), _bronze(585100, unit="(MT)")])
        assert list(silver.columns) == _SILVER_COLS
        assert set(silver.leviathan_slug) == {"cheese", "barley", "frozen_orange_juice"}


# ---------------------------------------------------------------------------
# The gate contract moved WITH the producer.
# ---------------------------------------------------------------------------
class TestWidenedGateContract:

    @staticmethod
    def _contract() -> dict:
        return yaml.safe_load(
            (_REPO / "configs" / "silver" / "tables" / "silver_psd.yaml")
            .read_text(encoding="utf-8"))

    def test_psd_contract_carries_the_structural_floor_overrides(self) -> None:
        # MEASURED post-widening, table-wide, by running this transform over the
        # real 2026-08-13 raw object: area_harvested_1000ha 0.657 -> 0.5518 and
        # yield_mt_ha 0.657 -> 0.5670. At the shipped 0.5 table scalar both still
        # pass, but by 5.2 points -- thin enough that an ordinary shift in which
        # release partitions bronze holds could red the gate on data that is
        # exactly what USDA published. Both floors sit ~27% below the measurement,
        # the same headroom ratio the nass pct_emerged recalibration used.
        # W0-2 (projection wave, 2026-08-25) -- FOUR MORE, promoted with the card
        # metrics in the same change (the D-CW-2a law: a promoted column with no
        # floor inherits the provisional 0.5 it can never reach). MEASURED on the
        # live 247,036-row object: su_ratio_yoy_delta 0.8577 -> floor 0.60; the
        # three revision columns 0.0381-0.0383 -> floor 0.025 (a revision is
        # .diff(1) across consecutive release months, and the pre-WASDE mass has
        # ONE print per key -- revisions exist only for MY2014+ on 56/63 slugs).
        ov = self._contract().get("min_nonnull_frac_overrides") or {}
        assert ov == {"area_harvested_1000ha": 0.40, "yield_mt_ha": 0.40,
                      "su_ratio_yoy_delta": 0.60, "production_mt_revision": 0.025,
                      "ending_stocks_mt_revision": 0.025, "consumption_mt_revision": 0.025}

    def test_the_other_seven_value_columns_keep_the_table_scalar(self) -> None:
        c = self._contract()
        assert c["min_nonnull_frac"] == 0.5
        ov = set(c["min_nonnull_frac_overrides"])
        assert ov < set(c["value_columns"])
        assert len(set(c["value_columns"]) - ov) == 7

    def test_the_floors_only_cover_columns_that_are_source_structural(self) -> None:
        # area/yield are absent because USDA publishes no harvested area for
        # butter or beef -- not because anything was lost. A floor added for a
        # column that IS published everywhere would be a masked producer defect
        # wearing a calibration's clothes. The W0-2 four are the same class: the
        # YoY delta has no prior-year print at the book's front edge, and a
        # revision needs a consecutive-month pair the pre-WASDE era never has.
        assert set(self._contract()["min_nonnull_frac_overrides"]) == {
            "area_harvested_1000ha", "yield_mt_ha", "su_ratio_yoy_delta",
            "production_mt_revision", "ending_stocks_mt_revision", "consumption_mt_revision"}

    def test_the_gate_still_hard_fails_a_column_that_goes_entirely_null(self) -> None:
        # The floors loosen a threshold; they do not disarm the gate. KIND_ALL_NAN
        # is checked BEFORE the floor and has no override, so a producer that
        # dropped harvested area completely still reds.
        from leviathan.silver.value_census import KIND_ALL_NAN, ColumnCensus, evaluate_gate
        census = {"area_harvested_1000ha": ColumnCensus(
            column="area_harvested_1000ha", total_rows=100, null_count=100,
            nonnull_fraction=0.0, all_nan=True, all_constant=False, constant_value=None,
            sentinel_saturated=False, distinct_lower_bound=0, min_value=None,
            max_value=None, files_sampled=1, files_with_stats=1)}
        rows = evaluate_gate("silver_psd", census, ["area_harvested_1000ha"], 0.5,
                             floor_overrides={"area_harvested_1000ha": 0.40})
        assert [r.kind for r in rows] == [KIND_ALL_NAN]


# ---------------------------------------------------------------------------
# What this change deliberately does NOT do. Refusals are pinned so a later
# reader can tell a decision from an omission.
# ---------------------------------------------------------------------------
class TestWideningRefusals:

    def test_the_release_date_convention_is_unchanged_for_every_code(self) -> None:
        # The widening measured that the bulk CSV's `Month` is the CALENDAR month
        # of the release, not the MY-relative index _compute_psd_release_dates
        # assumes. That is a PRE-EXISTING property of the shipped 13 and re-dating
        # it would move every row in silver_psd -- a re-baseline, not an enum
        # widening. The new codes therefore ride the SAME convention so one table
        # never carries two date conventions. This test pins the original 13 so a
        # future convention change is a deliberate, visible act.
        assert _PSD_COMMODITY_TO_MYS[410000] == 6      # wheat
        assert _PSD_COMMODITY_TO_MYS[440000] == 9      # corn
        assert _PSD_COMMODITY_TO_MYS[422110] == 8      # rice
        assert _PSD_COMMODITY_TO_MYS[2222000] == 9     # soybeans
        assert _PSD_COMMODITY_TO_MYS[4243000] == 10    # palm (the 2026-07-18 correction)
        assert _PSD_COMMODITY_TO_MYS[2631000] == 8     # cotton

    def test_the_livestock_and_dairy_codes_ride_the_calendar_year(self) -> None:
        # PSD publishes meat and dairy on a calendar year, so MYS=1 is both the
        # published marketing year and the only value in this file for which the
        # shipped formula and the measured semantics agree.
        for code in (111000, 113000, 114200, 115000,
                     223000, 224200, 224400, 230000, 240000):
            assert _PSD_COMMODITY_TO_MYS[code] == 1


# ---------------------------------------------------------------------------
# THE SERVING FLIP (2026-08-20). This file shipped two CONDITIONAL refusals --
# "the serving fence is NOT flipped for fcoj" and "the psd numbers card is NOT
# widened yet" -- and both hung on one condition: rows, proved by a cloud re-run
# rather than by the producer's intent. That re-run landed at 10:01 and the live
# object carries 247,036 rows over 63 distinct leviathan_slug values, with 746
# FCOJ rows across 25 countries and 1,646 fresh_citrus rows across 48
# (data/dec_p0/projection_census.json, the silver_psd commodity-code family).
# The tests below are those SAME two decisions asserting the other direction,
# plus the two traps the widened table created: a conditional refusal that is
# never flipped when its condition is met stops being a decision and becomes a
# fence nobody maintains.
# ---------------------------------------------------------------------------
class TestServingFlip:

    def _cards(self) -> dict:
        return yaml.safe_load(
            (_REPO / "configs" / "graphrag" / "numbers" / "tables.yaml")
            .read_text(encoding="utf-8"))["tables"]

    def _card(self) -> dict:
        return self._cards()["silver_psd"]

    def test_the_serving_fence_is_flipped_for_fcoj(self) -> None:
        # The psd legs on frozen_orange_juice now un-SKIP at _scope and read real
        # rows instead of declining. cocoa is a DIFFERENT shape and stays behind
        # the fence: USDA publishes no cocoa balance sheet at all, so no widening
        # can ever mint one -- that data's home is ICCO.
        from leviathan.graphrag.numbers.cascade import PSD_UNSERVED_SLUGS
        assert "frozen_orange_juice" not in PSD_UNSERVED_SLUGS
        assert PSD_UNSERVED_SLUGS == frozenset({"cocoa"})

    # PROJECTION WAVE Lane 3 (2026-08-25): the fence test now runs over BOTH PSD cards. The wide
    # table and its long companion are two projections of ONE producer map, so a 48th code landing
    # in the transform must move BOTH cards or the estate ships a table whose own fence refuses rows
    # it serves. Parametrized rather than duplicated: a THIRD psd card would join by adding a name.
    _PSD_CARD_IDS = ("silver_psd", "silver_psd_attributes")

    @pytest.mark.parametrize("tid", _PSD_CARD_IDS)
    def test_the_card_fence_is_the_producer_map_slug_for_slug(self, tid: str) -> None:
        # The condition the refusal attached to the card move was that its closed
        # set be GENERATED, never hand-listed. Equality in BOTH directions is the
        # whole point: a code added to the transform without a card move, and a
        # slug left on the card after its code is refused, each fail here rather
        # than as a silent zero-row read (the first) or a silent refusal of a
        # commodity the table serves (the second).
        card = self._cards()[tid]
        assert card["commodity_col"] == "leviathan_slug"
        assert sorted(card["commodity_values"]) == sorted(
            {s for slugs in _PSD_COMMODITY_TO_SLUGS.values() for s in slugs})
        assert len(card["commodity_values"]) == 63

    def test_the_two_psd_cards_share_one_commodity_vocabulary(self) -> None:
        # The equality above is per-card and would still pass if the two cards drifted onto two
        # DIFFERENT correct-at-authoring copies of the map. This asserts the pairwise fact directly,
        # so the failure message names the drift between the cards rather than between a card and
        # the transform -- they are one vocabulary because they are one producer map.
        cards = self._cards()
        a = set(cards["silver_psd"]["commodity_values"])
        b = set(cards["silver_psd_attributes"]["commodity_values"])
        assert a == b, {"wide_only": sorted(a - b), "long_only": sorted(b - a)}

    def test_the_card_serves_both_citrus_subjects_and_still_refuses_cocoa(self) -> None:
        # XC-7's two codes are two SUBJECTS, and the card carries both keys so a
        # juice ask and a fresh-orange ask cannot collapse onto one balance sheet.
        # cocoa stays off: an off-list ask is a teaching refusal (CommodityOffCard,
        # pre-SQL), which is the honest answer, not a zero-row read.
        vals = set(self._card()["commodity_values"])
        assert {"frozen_orange_juice", "fresh_citrus"} <= vals
        assert "cocoa" not in vals

    def test_the_card_notes_carry_the_two_traps_the_widening_created(self) -> None:
        # Both are MEASURED properties of the widened table, not style: chicken_meat
        # (115000) is broader than broilers_poultry (114200) and OVERLAPS it, so the
        # two are never summed; and broilers_poultry's newest release_date is
        # 2016-10-10 -- a content ceiling inside PSD, which a reader quoting it must
        # know before calling the figure current.
        blob = " ".join(self._card()["notes"].split()).lower()
        assert "never sum broilers_poultry and chicken_meat" in blob
        assert "2016-10-10" in blob
