"""FAO-2 (PROJECTION WAVE Lane 5): the FAOSTAT LIVESTOCK axis -- the card and the narration fences.

The transform half is pinned in ``test_transforms_faostat_raw.py`` (the bronze element gate) and
``test_transforms_faostat_silver.py`` (the element map, the case-insensitive resolution, the unit
fence); the item/slug roster in ``test_faostat_item_map.py``. THIS file pins the SERVING half: the
second card on the shared physical table, the crop/livestock partition it rests on, and the
narration fences that only prose can carry.

WHY A NOTES-TOKEN LINT AND NOT A COMMENT. The hazard this lane creates is a UNITS hazard, and units
reach the model through the card, not through the transform: ``live_animals`` is ``An`` for
cattle_beef and hogs but ``1000 An`` for broilers_poultry (MEASURED -- 13,831 / 12,824 / 13,932 rows
on the 2026-05-11 ZIP), so a cross-slug read that does not consult the row's own unit is wrong by
exactly 1000x. The estate has met this before on ``Cows In Milk`` and answered it the same way: the
hazard is CARRIED honestly on a per-row unit column and the card is REQUIRED to say so, by a lint
that can fail. A prose fence nobody tests is a comment.

SAME-COMMIT COUPLING. This file reads the ``silver_production_livestock`` card from tables.yaml. That
card and this diff are ONE change -- the existing drift test
(``tests/unit/silver/test_silver_reconcile.py::test_numbers_tables_matches_tablespec_keys_no_drift``,
``set(NUMBERS_TABLES) == set(tables.yaml keys)``) is what makes that true rather than merely
intended, and ``_card()`` below fails with the remedy if the card has not been applied.

AWS-free.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from leviathan.graphrag.numbers import registry as NR
from leviathan.transforms.bronze_to_silver.faostat_production import (
    ELEMENT_TO_METRIC,
    FAOSTAT_LIVESTOCK_SLUGS,
    HEAD_COUNT_METRICS,
    LIVESTOCK_METRICS,
    METRIC_UNITS,
    PER_ANIMAL_RATE_METRICS,
    TONNAGE_METRICS,
)

_REPO = Path(__file__).resolve().parents[2]
_TABLES_YAML = _REPO / "configs" / "graphrag" / "numbers" / "tables.yaml"
_ITEM_MAP = _REPO / "configs" / "sources" / "faostat_item_map.yaml"
_CENSUS = _REPO / "data" / "dec_p0" / "faostat_livestock_census.json"

CARD_ID = "silver_production_livestock"
PHYSICAL = "silver_production"

# The four metrics the card SERVES. `laying_birds` and `animals_producing_or_slaughtered` are mapped
# by the transform and deliberately NOT carded -- see test_the_two_dead_metrics_are_not_carded.
SERVED_METRICS = {"live_animals", "milk_animals", "production_quantity", "yield_per_animal"}


def _tables() -> dict:
    return yaml.safe_load(_TABLES_YAML.read_text(encoding="utf-8"))["tables"]


def _card() -> dict:
    tables = _tables()
    if CARD_ID not in tables:
        pytest.fail(
            f"{CARD_ID} is absent from configs/graphrag/numbers/tables.yaml. The Lane-5 card block "
            f"and the Lane-5 code diff are ONE change: apply the card (it is delivered verbatim in "
            f"the Lane-5 report, section THE CARD) and re-run. The drift test "
            f"set(NUMBERS_TABLES) == set(tables.yaml keys) enforces the same coupling from the "
            f"other side."
        )
    return tables[CARD_ID]


def _item_map() -> dict[str, str]:
    return yaml.safe_load(_ITEM_MAP.read_text(encoding="utf-8"))


class TestTheCropLivestockPartition:
    """The two cards' ``commodity_values`` are DISJOINT and together EXACTLY the item map.

    This re-specifies FAO-5's CLAUSE-4 non-vacuity pin rather than weakening it. FAO-5 declares the
    crop card's ``commodity_values`` generated from ``ITEM_MAP.keys()`` with a set-equality test both
    directions; Lane 5 widens that map by four keys, so the equality has to become a PARTITION or the
    crop card ends up serving `cattle_beef` + `area_harvested` as a silent 0-row -- the exact defect
    the commodity fence exists to close. It still fails in both directions, and it now also fails if
    a slug is double-homed."""

    def test_the_partition_lives_in_code_and_is_exactly_the_four(self):
        assert FAOSTAT_LIVESTOCK_SLUGS == {"cattle_beef", "hogs", "broilers_poultry", "milk_fluid"}

    def test_the_livestock_card_serves_exactly_the_livestock_half(self):
        assert set(_card()["commodity_values"]) == FAOSTAT_LIVESTOCK_SLUGS

    def test_the_two_halves_are_disjoint_and_together_the_whole_map(self):
        item_map = set(_item_map())
        livestock = set(_card()["commodity_values"])
        crop = set(_tables()[PHYSICAL].get("commodity_values") or [])
        if not crop:
            pytest.skip("FAO-5 has not yet declared silver_production.commodity_values (Lane 4); "
                        "the partition's livestock half is pinned unconditionally above")
        assert not (crop & livestock), sorted(crop & livestock)      # no slug on two cards
        assert crop | livestock == item_map, {
            "only_in_cards": sorted((crop | livestock) - item_map),
            "only_in_item_map": sorted(item_map - (crop | livestock)),
        }


class TestTheSecondCardIsTheSameTable:

    def test_it_redirects_to_the_physical_table_and_declares_the_same_columns(self):
        card, crop = _card(), _tables()[PHYSICAL]
        assert card["athena_table"] == PHYSICAL
        assert crop.get("athena_table") is None                      # the crop card IS the table
        # A card that names a column the table does not write compiles SQL that dies COLUMN_NOT_FOUND
        # at serving time (the silver_nasa_power incident). One physical table, so bind the two cards
        # to each other rather than re-typing the column names.
        for key in ("shape", "commodity_col", "country_col", "period_col", "period_type",
                    "period_sql_type", "knowledge_date_col", "knowledge_semantics",
                    "metric_col", "value_col", "unit_col", "country_name_ref",
                    "country_axis_is_destination"):
            assert card.get(key) == crop.get(key), key

    def test_the_pa1_coverage_fields_are_the_measured_backfill(self):
        """PA-1, FLIPPED 2026-08-26: the fields were DELIBERATELY ABSENT while zero livestock rows
        existed (an absent census is SILENCE, never a fabricated one) and were measured on the
        PRODUCED objects in the flip change -- where every figure landed exactly on the banked
        census (data/dec_p0/faostat_livestock_census.md): 13,831 + 12,824 + 13,932 + 40,067 =
        80,654 rows, 1961-2024. `cadence` was always a declaration, not a measurement."""
        card = _card()
        assert card["row_count"] == 80654
        assert card["first_obs"] == "1961"
        assert card["last_obs"] == "2024"
        assert card["cadence"] == "annual"

    def test_the_card_declares_a_unit_only_where_one_unit_is_true(self):
        """A metric-level unit that is true of only SOME of the metric's rows is worse than none:
        `_metric_line` renders it verbatim onto every citation. MEASURED, `live_animals` spans two
        units across the three slugs that carry it, so its card entry declares NONE and the row's
        unit column governs -- and that is asserted, not left to good intentions."""
        metrics = _card()["metrics"]
        assert (metrics["live_animals"].get("unit") or "") == ""
        assert metrics["milk_animals"]["unit"] == "An"
        assert metrics["production_quantity"]["unit"] == "t"
        assert metrics["yield_per_animal"]["unit"] == "kg/An"
        # and every declared unit must be one the fence governs for that metric
        for name, m in metrics.items():
            if m.get("unit"):
                assert m["unit"] in METRIC_UNITS[name], name

    def test_the_carded_metrics_are_metrics_the_transform_can_produce(self):
        """Byte-for-byte against the transform's governed names. A house-cased or invented variant
        matches ZERO rows and reads as 'not published' -- the silver_wasde Title-Case bug, which hid
        every WASDE lookup for months."""
        assert set(_card()["metrics"]) == SERVED_METRICS
        assert SERVED_METRICS <= set(ELEMENT_TO_METRIC.values())

    def test_the_two_dead_metrics_are_not_carded(self):
        """`laying_birds` and `animals_producing_or_slaughtered` are MAPPED by the transform (so a
        later item admission lights them with no code change) and NOT carded, because no item Lane 5
        admits carries them: they belong to the MEAT and EGG items, both parked in writing. Carding
        them would be a metric that returns zero rows and reads as 'not published' -- silver_production's
        own history, where the declared name `production` was a zero-row phantom the pg loader never
        even mirrored."""
        dead = {"laying_birds", "animals_producing_or_slaughtered"}
        assert dead <= set(ELEMENT_TO_METRIC.values())         # mapped, so the seam is ready
        assert not (dead & set(_card()["metrics"]))            # and NOT advertised
        assert not (dead & set(_tables()[PHYSICAL]["metrics"]))

    def test_the_crop_card_is_untouched_by_this_lane(self):
        """A widening must not re-base a live series. silver_production is SERVED today off exactly
        these three metric strings."""
        assert set(_tables()[PHYSICAL]["metrics"]) == {
            "production_quantity", "area_harvested", "yield"}


class TestTheNarrationFences:
    """FAO-2 (c). The fences that only prose can carry, pinned as tokens so they cannot quietly
    leave the card. Each assertion names the number it protects."""

    @staticmethod
    def _blob() -> str:
        card = _card()
        return " ".join(f"{card['description']} {card['notes']}".split()).lower()

    def test_the_row_unit_is_declared_authoritative(self):
        assert "unit` column is authoritative" in self._blob()

    def test_a_head_count_is_told_never_to_sum_with_a_tonnage(self):
        blob = self._blob()
        assert "head count must never be summed with a tonnage" in blob
        # and the classes the fence protects are the transform's, not a second list
        assert HEAD_COUNT_METRICS and TONNAGE_METRICS
        assert not (HEAD_COUNT_METRICS & TONNAGE_METRICS)

    def test_the_1000x_cross_slug_trap_is_stated_with_its_units(self):
        """The single most citable fact on this card. MEASURED: live_animals is `An` for cattle_beef
        (13,831 rows) and hogs (12,824) and `1000 An` for broilers_poultry (13,932)."""
        blob = self._blob()
        assert "1000x" in blob
        assert "1000 an" in blob and "broilers_poultry" in blob
        assert METRIC_UNITS["live_animals"] == {"An", "1000 An"}

    def test_the_per_animal_rate_is_told_it_is_not_a_tonnage(self):
        blob = self._blob()
        assert "never narrate it as a tonnage" in blob
        assert PER_ANIMAL_RATE_METRICS == {"yield_per_animal"}
        assert not (METRIC_UNITS["yield_per_animal"] & {"t", "kg", "ha"})

    def test_the_psd_overlap_is_de_conflated_by_name(self):
        """cattle_beef / hogs / broilers_poultry exist on BOTH surfaces and mean different physical
        subjects: animals here, meat tonnage on silver_psd. A card that does not say so invites one
        figure built from both."""
        blob = self._blob()
        assert "silver_psd" in blob
        assert "animals, not meat" in blob or "animals and not meat" in blob
        assert "how many animals" in blob and "how much meat" in blob

    def test_the_dairy_gloss_is_de_conflated(self):
        blob = self._blob()
        assert "milk_fluid" in blob and "`dairy`" in blob
        assert "butter, cheese" in blob

    def test_the_unserved_slaughter_axis_is_declared_unserved(self):
        """313,081 source rows this card does NOT serve. The honest answer is 'unserved', and a card
        that stays silent about it lets the model answer a slaughter question from the herd."""
        blob = self._blob()
        assert "313,081" in blob
        assert "slaughter axis is unserved" in blob

    def test_the_aggregate_ladder_warning_rides_the_shared_country_axis(self):
        blob = self._blob()
        assert "never sum an aggregate with the countries inside it" in blob


class TestTheCensusBacksEveryNumberOnTheCard:

    @pytest.mark.skipif(not _CENSUS.exists(),
                        reason=f"Lane-5 census artifact absent from this checkout: {_CENSUS}")
    def test_the_notes_figures_re_derive_from_the_banked_census(self):
        doc = json.loads(_CENSUS.read_text(encoding="utf-8"))
        blob = " ".join(f"{_card()['description']} {_card()['notes']}".split())
        # the slaughter axis's row count, and the laying count beside it
        assert f"{doc['element_rows']['Producing Animals/Slaughtered']:,}" in blob
        assert f"{doc['element_rows']['Laying']:,}" in blob

    @pytest.mark.skipif(not _CENSUS.exists(), reason="census artifact absent")
    def test_the_units_the_card_declares_are_the_units_the_release_prints(self):
        doc = json.loads(_CENSUS.read_text(encoding="utf-8"))
        items = doc["items"]
        assert set(items["Cattle || Stocks"]["units"]) == {"An"}
        assert set(items["Swine / pigs || Stocks"]["units"]) == {"An"}
        assert set(items["Chickens || Stocks"]["units"]) == {"1000 An"}
        assert set(items["Raw milk of cattle || Milk Animals"]["units"]) == {"An"}
        assert set(items["Raw milk of cattle || Production"]["units"]) == {"t"}
        assert set(items["Raw milk of cattle || Yield/Carcass Weight"]["units"]) == {"kg/An"}
        # the union is exactly what METRIC_UNITS governs for the metrics this card serves
        assert METRIC_UNITS["live_animals"] == {"An", "1000 An"}
        assert METRIC_UNITS["milk_animals"] == {"An"}
        assert METRIC_UNITS["yield_per_animal"] >= {"kg/An"}


class TestTheFlipIsRealAndTheFenceStaysDischarged:
    """FLIPPED 2026-08-26. The arm-state pins this class carried until the flip now guard the
    DISCHARGED state (the mpoc anchor-pin precedent): a regression back onto the whitelist would
    silently unserve a backfilled, mirrored, probed surface -- worse than the arm it would imitate,
    because this time the rows EXIST and 'no cattle' would be a lie about served data."""

    def test_the_card_is_served_post_flip(self):
        assert CARD_ID not in NR.WHITELIST_ABSENT_DEFAULT
        assert CARD_ID in NR.load_registry().tables

    def test_the_shared_physical_table_stays_served_throughout(self):
        """The arm fenced a CARD, never the object. silver_production was live throughout --
        this is the one respect in which a second-card arm differs from silver_futures_eod's."""
        assert PHYSICAL not in NR.WHITELIST_ABSENT_DEFAULT
        assert PHYSICAL in NR.load_registry().tables

    def test_the_discharge_record_is_written_where_the_fence_was(self):
        """A fence with no written removal trigger is a fence nobody dares remove -- and a fence
        removed with no written discharge is a decision nobody can audit. The SIX gates travel with
        the entry as its discharge record now: backfill via run_faostat_backfill with the Lane-4
        canary discipline, the PROJECTION-ENUM ALTER, the DISTINCT probe, the pg reload (whose
        first run's 875,512-of-942,807 shortfall exposed the one-card-roster filter on a two-card
        physical -- fixed as the load_pg_numbers union), the RE-MEASURED coverage, and the CROP
        card's commodity_values fence."""
        text = (_REPO / "src/leviathan/graphrag/numbers/registry.py").read_text(encoding="utf-8")
        block = text.split("PROJECTION WAVE Lane 5")[1].split("})")[0]
        assert "FLIPPED OUT" in block
        for token in ("THE FLIP GATE", "run_faostat_backfill", "canary",
                      "projection.commodity.values", "DISTINCT probe",
                      "load_pg_numbers", "RE-MEASURED", "commodity_values"):
            assert token in block, token
        # the flip must not have left the ENTRY behind -- the record stays, the fence goes
        assert '"silver_production_livestock",' not in block
