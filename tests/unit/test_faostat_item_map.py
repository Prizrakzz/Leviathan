"""FAOSTAT item map (D-EC projection wave FAO-1) -- the ingested universe, pinned.

``configs/sources/faostat_item_map.yaml`` IS the FAOSTAT universe: raw_to_bronze filters ONE item per
Glue run (``--fao_item_name``), so an item absent from this file is never read at all and widening the
silver element filter recovers nothing. Two failure modes this file exists to catch, both of which are
otherwise discovered only by a cloud run:

  * a TYPOED Item string -- the bronze filter matches exactly, so the Glue job dies on "No rows found"
    after the ZIP download. Pinned against the release's own legend member (ItemCodes.csv), normalized
    ``"; " -> ", "`` because the legend prints a semicolon where the data column prints a comma;
  * a slug with no HOME -- the SLUG LAW (c4ebbf23) keys every item to the PSD 63-commodity vocabulary
    where the two annual-production surfaces overlap, so the estate carries ONE commodity axis. A key
    invented here would be a numbers axis with no node and no PSD sibling.

AWS-free; reads the tracked QCL ZIP's 10KB legend member, never the 545MB data CSV.
"""
from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

import pytest
import yaml
from leviathan.transforms.bronze_to_silver.usda_psd import (
    _PSD_COMMODITY_TO_SLUGS,
    _PSD_FORWARD_DECLARED_SLUGS,
)

_REPO = Path(__file__).resolve().parents[2]
_MAP_PATH = _REPO / "configs/sources/faostat_item_map.yaml"
_QCL_ZIP = _REPO / "data/raw/production/faostat/qcl/Production_Crops_Livestock_E_All_Data_(Normalized).zip"
_ITEM_CODES_MEMBER = "Production_Crops_Livestock_E_ItemCodes.csv"
_needs_zip = pytest.mark.skipif(not _QCL_ZIP.exists(), reason=f"raw QCL ZIP not checked out: {_QCL_ZIP}")


@pytest.fixture(scope="module")
def item_map() -> dict[str, str]:
    return yaml.safe_load(_MAP_PATH.read_text(encoding="utf-8"))


# The FAO-1 admissions, verbatim. MEASURED row / distinct-area counts under the three ingested elements
# (Area harvested / Production / Yield) on the 2026-05-11 raw ZIP, quoted here so a future edit that
# swaps an Item string has to confront what that string is worth.
FAO1_ADDITIONS: dict[str, tuple[str, int, int]] = {
    "sorghum":         ("Sorghum",                        26137, 167),
    "peanut":          ("Groundnuts, excluding shelled",  27272, 156),
    "barley":          ("Barley",                         23261, 143),
    "millet":          ("Millet",                         20250, 124),
    "oats":            ("Oats",                           17807, 113),
    "sunflower":       ("Sunflower seed",                 17685, 123),
    "rye":             ("Rye",                            14696,  96),
    "cottonseed_oil":  ("Cottonseed oil",                  8142, 140),
    "cottonseed":      ("Cotton seed",                     8065, 158),
    "sunflower_oil":   ("Sunflower-seed oil, crude",       6430, 127),
    "palm_kernel_oil": ("Oil of palm kernel",              5243,  95),
    "palm_kernel":     ("Palm kernels",                    4013,  65),
}


def test_map_population_is_pinned(item_map):
    """COUNT PIN, moved in the same change that moved the population: 31 -> 43 -> 47."""
    assert len(item_map) == 47


def test_every_fao1_addition_lands_on_its_measured_item_string(item_map):
    for slug, (item, _rows, _areas) in FAO1_ADDITIONS.items():
        assert item_map[slug] == item, slug


def test_the_pre_fao1_keys_are_untouched(item_map):
    """A widening must not re-base a live series. Every pre-FAO-1 key keeps its Item string."""
    unchanged = {
        "cocoa": "Cocoa beans", "corn_cbot": "Maize (corn)", "french_wheat_matif": "Wheat",
        "rough_rice_cbot": "Rice", "soybeans_cbot": "Soya beans", "soybean_oil_cbot": "Soya bean oil",
        "canola_ice": "Rape or colza seed", "rapeseed_oil_zce": "Rapeseed or canola oil, crude",
        "malaysian_crude_palm_oil_cme": "Palm oil", "arabica_coffee": "Coffee, green",
        "cotton": "Seed cotton, unginned", "raw_sugar": "Sugar cane",
        "frozen_orange_juice": "Oranges",
    }
    for slug, item in unchanged.items():
        assert item_map[slug] == item, slug


def test_cotton_lint_stays_parked(item_map):
    """WRITTEN REFUSAL. `Cotton lint, ginned` (7,903 rows / 135 areas) is the FAO item matching what the
    ICE contract trades and what PSD 2631000 publishes; `cotton` here resolves to SEED COTTON, the
    unginned field crop. One item per slug, so admitting lint would REBASE a live series onto a
    different physical subject rather than widen it -- an owner decision, not a map edit. The parked
    state is asserted, not just commented, so a later widening has to face it."""
    assert item_map["cotton"] == "Seed cotton, unginned"
    assert "Cotton lint, ginned" not in set(item_map.values())
    text = _MAP_PATH.read_text(encoding="utf-8")
    assert "Cotton lint, ginned" in text and "PARKED" in text        # the reason travels with the file


def test_every_slug_has_a_home_in_the_psd_vocabulary(item_map):
    """SLUG LAW: every key is a slug the PSD map already publishes, so one commodity axis serves both
    annual-production surfaces. `_PSD_FORWARD_DECLARED_SLUGS` is the auditable half -- publication
    grains that are numbers keys today and graph nodes when the edge half declares them (usda_psd R3)."""
    psd_slugs = {s for slugs in _PSD_COMMODITY_TO_SLUGS.values() for s in slugs}
    homeless = sorted(s for s in item_map if s not in psd_slugs)
    # `cocoa` is the ONE pre-FAO-1 key outside the PSD vocabulary and stays outside it: USDA publishes
    # no cocoa balance sheet, so there is no overlap for the law to govern. Pinned so the exception
    # stays a single named fact rather than a hole the next widening walks through.
    assert homeless == ["cocoa"], homeless
    assert all(s in psd_slugs for s in FAO1_ADDITIONS)
    forward = sorted(s for s in FAO1_ADDITIONS if s in _PSD_FORWARD_DECLARED_SLUGS)
    assert forward == ["cottonseed_oil", "millet", "oats", "palm_kernel_oil", "rye"]


@_needs_zip
def test_every_item_string_exists_in_the_release_legend(item_map):
    """The tripwire that replaces a failed cloud run. A typoed Item string reaches bronze as a filter
    that matches nothing; here it is a red test instead."""
    with zipfile.ZipFile(_QCL_ZIP) as z:
        raw = z.read(_ITEM_CODES_MEMBER).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(raw)))
    legend = {r[2].replace("; ", ", ") for r in rows[1:] if len(r) >= 3}
    unknown = sorted({v for v in item_map.values()} - legend)
    assert unknown == [], unknown


def test_backfill_runner_derives_its_roster_from_the_map():
    """The roster is never restated as a literal: the map grew 31 -> 43 -> 47 and a hard-coded count
    would have gone stale in each commit. The Glue-start concurrency cap is a separate number and
    deliberately does NOT move with the population -- that is the whole reason the two were split."""
    from jobs.orchestrate.run_faostat_backfill import ALL_COMMODITIES, ITEM_MAP, _MAX_CONCURRENT_STARTS
    assert set(ALL_COMMODITIES) == set(ITEM_MAP) and len(ALL_COMMODITIES) == 47
    assert _MAX_CONCURRENT_STARTS == 31             # a throttle, NOT a commodity count


# ---------------------------------------------------------------------------
# FAO-2 (Lane 5): the livestock half.
#
# Row / distinct-area counts are MEASURED on the tracked 2026-05-11 ZIP and banked at
# `data/dec_p0/faostat_livestock_census.json` (cut by `jobs/utils/faostat_element_item_census.py`).
# They are quoted here so an edit that swaps an Item string has to confront what that string is
# worth, and re-derived from the artifact by the last test in this file when it is checked out.
# ---------------------------------------------------------------------------
FAO2_ADDITIONS: dict[str, tuple[str, int, int]] = {
    "cattle_beef":      ("Cattle",             13831, 238),   # Stocks, An
    "hogs":             ("Swine / pigs",       12824, 219),   # Stocks, An
    "broilers_poultry": ("Chickens",           13932, 240),   # Stocks, 1000 An  <- the 1000x trap
    "milk_fluid":       ("Raw milk of cattle", 40067, 231),   # Milk Animals + Production + Yield/CW
}
FAO2_ADMITTED_ROWS = 80654

# Every item the livestock block's written refusals name, with the number that makes the refusal
# honest. A park with no measurement is an opinion.
FAO2_PARKED: dict[str, tuple[int, int]] = {
    "Sheep":                                          (12994, 225),
    "Goats":                                          (13350, 233),
    "Hen eggs in shell, fresh":                       (69051, 240),
    "Meat of cattle with the bone, fresh or chilled": (41541, 239),
    "Meat of chickens, fresh or chilled":             (41920, 240),
    "Meat of pig with the bone, fresh or chilled":    (38491, 220),
}

_CENSUS = _REPO / "data" / "dec_p0" / "faostat_livestock_census.json"


def test_every_fao2_addition_lands_on_its_measured_item_string(item_map):
    """TWO OF THE PLAN'S ITEM STRINGS WERE WRONG and this is where that is caught: the release
    prints `Swine / pigs` (the plan said "Pigs") and `Hen eggs in shell, fresh` (the plan said
    "Hen eggs in shell"). Either would have cost a cloud Glue run dying on 'No rows found'."""
    for slug, (item, _rows, _areas) in FAO2_ADDITIONS.items():
        assert item_map[slug] == item, slug
    assert item_map["hogs"] == "Swine / pigs"


def test_the_livestock_admissions_are_the_only_new_keys(item_map):
    """43 -> 47 and NOTHING ELSE MOVED. A widening must not re-base a live series, so the four new
    keys are named and the residue is asserted to be EXACTLY the 31 pre-FAO-1 keys."""
    residue = set(item_map) - set(FAO1_ADDITIONS) - set(FAO2_ADDITIONS)
    assert len(residue) == 31
    assert residue == {
        "cocoa", "corn_cbot", "campinas_corn_reference_bmf", "french_maize_matif",
        "south_african_white_maize_jse", "south_african_yellow_maize_jse",
        "french_wheat_matif", "hard_red_winter_wheat_kcbt", "hard_red_spring_wheat_mgex",
        "soft_red_winter_wheat_cbot", "rough_rice_cbot", "soybeans_cbot", "soybeans_no_1_dce",
        "soybeans_no_2_dce", "soybean_meal_cbot", "soybean_meal_dce", "soybean_oil_cbot",
        "soybean_oil_dce", "french_rapeseed_matif", "canola_ice", "rapeseed_oil_zce",
        "rapeseed_meal_zce", "malaysian_crude_palm_oil_cme", "palm_olein_dce",
        "arabica_coffee", "robusta_coffee", "brazilian_arabica_coffee", "cotton",
        "raw_sugar", "white_sugar", "frozen_orange_juice",
    }


def test_the_crop_card_commodity_values_are_the_maps_crop_half_both_directions(item_map):
    """FAO-5's non-vacuity pin (CLAUSE 4): the silver_production card's commodity_values must be
    EXACTLY the item map's crop half -- the map minus the four livestock slugs (which belong to
    the fenced silver_production_livestock card). A slug in the map but off the card is served
    silver a card fence refuses; a slug on the card but off the map is an advertisement for rows
    that cannot exist. This is also the projection-enum roster (the Lane-4 ALTER), so all three
    surfaces -- map, card, enum -- are one universe or this reds."""
    import yaml as _yaml
    card = _yaml.safe_load(
        (_REPO / "configs/graphrag/numbers/tables.yaml").read_text(encoding="utf-8")
    )["tables"]["silver_production"]
    crop_half = set(item_map) - set(FAO2_ADDITIONS)
    assert set(card["commodity_values"]) == crop_half, {
        "on_card_not_in_map": sorted(set(card["commodity_values"]) - crop_half),
        "in_map_not_on_card": sorted(crop_half - set(card["commodity_values"]))}
    livestock_card = _yaml.safe_load(
        (_REPO / "configs/graphrag/numbers/tables.yaml").read_text(encoding="utf-8")
    )["tables"]["silver_production_livestock"]
    assert set(livestock_card["commodity_values"]) == set(FAO2_ADDITIONS)


def test_the_livestock_slugs_have_a_home_and_dairy_is_deliberately_not_one(item_map):
    """THE NODE TEST, run item by item -- the FAO-1 law, and the reason `dairy` is NOT a key here.

    `dairy` IS a commodity_hierarchy context node and `milk_fluid` is NOT, so the hierarchy alone
    would point the other way. usda_psd.py settles it in its own words: PSD publishes five separate
    dairy balance sheets and R2 forbids collapsing them onto one key, so "`dairy` survives as the
    family GLOSS over the five product slugs, and the product grain is what the table stores".
    Keying a physical FAOSTAT series to a gloss would break the SLUG LAW below AND put one number
    under a name that also covers butter, cheese and two milk powders."""
    psd_slugs = {s for slugs in _PSD_COMMODITY_TO_SLUGS.values() for s in slugs}
    for slug in FAO2_ADDITIONS:
        assert slug in psd_slugs, slug
    assert "dairy" not in item_map and "dairy" not in psd_slugs
    # milk_fluid enters through the FORWARD-DECLARED disjunct, exactly as five FAO-1 keys did
    assert "milk_fluid" in _PSD_FORWARD_DECLARED_SLUGS
    # the three that carry BOTH homes (hierarchy context node AND PSD slug) -- pinned as the roster
    # the main tree's gitignored configs/graphrag/commodity_hierarchy.yaml declares under
    # `context_commodities`, completion-wave class 1, so CI never has to read that file
    assert HIERARCHY_CONTEXT_NODES <= set(FAO2_ADDITIONS)


# The completion wave's class-1 livestock nodes, pinned here because the artifact that declares them
# -- configs/graphrag/commodity_hierarchy.yaml, `context_commodities` -- is GITIGNORED and absent
# from a CI checkout. Named, not merely asserted: the pin is only honest if the reader can find what
# it was cut from. Re-derived live by the test below wherever the file IS present.
HIERARCHY_CONTEXT_NODES = frozenset({"cattle_beef", "hogs", "broilers_poultry"})
_HIERARCHY = _REPO / "configs" / "graphrag" / "commodity_hierarchy.yaml"


@pytest.mark.skipif(not _HIERARCHY.exists(),
                    reason=f"gitignored hierarchy absent from this checkout: {_HIERARCHY} (present "
                           f"in the main tree). HIERARCHY_CONTEXT_NODES above is the pinned roster "
                           f"and runs unconditionally -- this is the re-derivation.")
def test_the_node_test_re_derives_against_the_live_hierarchy():
    """THE NODE TEST, run against the artifact itself wherever it exists. It asserts BOTH halves:
    the three admitted slugs ARE declared nodes, and `sheep` / `goats` are NOT -- so a later wave
    that mints those two nodes fails HERE, which is exactly the moment the item-map park should be
    revisited rather than a moment nobody notices."""
    doc = yaml.safe_load(_HIERARCHY.read_text(encoding="utf-8")) or {}
    declared = set(doc.get("context_commodities") or []) | set(doc.get("contracts") or {})
    assert HIERARCHY_CONTEXT_NODES <= declared, sorted(HIERARCHY_CONTEXT_NODES - declared)
    assert "dairy" in declared            # a node, and still NOT an item-map key (see above)
    assert "milk_fluid" not in declared   # a PSD product grain, not a graph node
    for parked in ("sheep", "goats"):
        assert parked not in declared, (
            f"{parked!r} is now a hierarchy node -- the FAO-2 park was taken for want of one. "
            f"Revisit configs/sources/faostat_item_map.yaml's livestock refusal (1).")


def test_sheep_and_goats_stay_parked_for_want_of_a_node(item_map):
    """WRITTEN REFUSAL. The two live-animal items with real mass and NO home: no `contracts:` entry,
    no `context_commodities` id, no PSD slug. The completion wave minted four livestock nodes and
    these were not among them, so admitting them would invent a commodity axis from the wrong end of
    the system. The parked state is asserted, not just commented."""
    psd_slugs = {s for slugs in _PSD_COMMODITY_TO_SLUGS.values() for s in slugs}
    for name in ("sheep", "goats", "sheep_meat", "goat_meat"):
        assert name not in item_map and name not in psd_slugs
    assert "Sheep" not in set(item_map.values()) and "Goats" not in set(item_map.values())
    text = _MAP_PATH.read_text(encoding="utf-8")
    assert "12,994" in text and "13,350" in text        # the numbers travel with the refusal


def test_hen_eggs_stay_parked_with_all_three_reasons_written(item_map):
    """WRITTEN REFUSAL, and the one the plan asked for the other way round: FAO-2 pairs `Chickens`
    AND `Hen eggs in shell, fresh` under broilers_poultry. Three independent reasons, any one fatal
    -- one item per slug (a duplicate YAML key is last-wins SILENTLY, so it would REPLACE the flock
    series); the multi-unit natural-key collision (13,801 of 14,009 (area, year) keys carry both `t`
    and `1000 No` under one governed metric); and the unit-category lie (`No/An` against the crop
    card's `yield [kg/ha]`)."""
    assert item_map["broilers_poultry"] == "Chickens"
    assert "Hen eggs in shell, fresh" not in set(item_map.values())
    text = _MAP_PATH.read_text(encoding="utf-8")
    for token in ("Hen eggs in shell, fresh", "13,801", "14,009", "ONE ITEM PER SLUG", "No/An"):
        assert token in text, token


def test_the_slaughter_axis_items_stay_parked_with_their_mass(item_map):
    """WRITTEN REFUSAL. The three MEAT items are the only carriers of `Producing Animals/Slaughtered`
    (313,081 rows file-wide). They are parked because one item per slug leaves them nowhere to go:
    cattle_beef / hogs / broilers_poultry are taken by the LIVE-ANIMAL items, which is the deliberate
    choice -- PSD already serves the meat in tonnes on those same three slugs and serves no herd size
    anywhere. The bronze element gate admits their elements ALREADY, so the day a slug exists the
    change is one line in the map."""
    values = set(item_map.values())
    text = _MAP_PATH.read_text(encoding="utf-8")
    for item in ("Meat of cattle with the bone, fresh or chilled",
                 "Meat of chickens, fresh or chilled",
                 "Meat of pig with the bone, fresh or chilled"):
        assert item not in values, item
        assert item in text, item
    from leviathan.transforms.raw_to_bronze.faostat_qcl import TARGET_ELEMENTS
    assert "producing animals/slaughtered" in TARGET_ELEMENTS


def test_the_admitted_rows_sum_to_the_declared_total():
    """Stated as the sum rather than as a literal, so a roster edit that forgets the total fails
    with the arithmetic (the psd_attributes roster idiom)."""
    assert sum(rows for _item, rows, _areas in FAO2_ADDITIONS.values()) == FAO2_ADMITTED_ROWS


@pytest.mark.skipif(not _CENSUS.exists(),
                    reason=f"Lane-5 census artifact absent from this checkout: {_CENSUS}. The "
                           f"roster pins above run unconditionally -- this is the re-derivation.")
def test_the_fao2_figures_re_derive_from_the_banked_census():
    """THE NON-VACUITY PIN. Every literal in this file's FAO-2 block is re-derived from the artifact
    it claims to come from, admissions and parks alike -- so a pin that drifts from the measurement
    fails here rather than aging quietly into folklore."""
    doc = json.loads(_CENSUS.read_text(encoding="utf-8"))
    items = doc["items"]

    def _rows_areas(item: str) -> tuple[int, int]:
        recs = [v for k, v in items.items() if k.split(" || ")[0] == item]
        assert recs, item
        return sum(r["rows"] for r in recs), max(r["areas"] for r in recs)

    for _slug, (item, rows, areas) in FAO2_ADDITIONS.items():
        assert _rows_areas(item) == (rows, areas), item
    for item, (rows, areas) in FAO2_PARKED.items():
        assert _rows_areas(item) == (rows, areas), item

    # the five livestock elements are the plan's 832,196 rows, MEASURED and exact
    livestock = ("Producing Animals/Slaughtered", "Yield/Carcass Weight", "Stocks",
                 "Milk Animals", "Laying")
    assert sum(doc["element_rows"][e] for e in livestock) == 832196
    assert sum(doc["element_rows"].values()) == doc["total_rows"] == 4209110

    # THE COLLISION, re-derived: of 724 distinct (item, element) pairs in all 301 items, exactly two
    # carry more than one unit -- both egg items under `Production`. The one-unit-per-pair assumption
    # silver_production's natural key rests on had never been checked before this lane.
    multi = doc["item_element_pairs_with_multiple_units"]
    assert set(multi) == {"Hen eggs in shell, fresh || Production",
                          "Eggs from other birds in shell, fresh, n.e.c. || Production"}
    assert sorted(multi["Hen eggs in shell, fresh || Production"]) == ["1000 No", "t"]
    egg = items["Hen eggs in shell, fresh || Production"]
    assert (egg["area_year_keys_with_multiple_units"], egg["area_year_keys"]) == (13801, 14009)
