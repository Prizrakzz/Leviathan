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
    """COUNT PIN, moved in the same change that moved the population: 31 -> 43."""
    assert len(item_map) == 43


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
    """The roster is never restated as a literal: the map grew 31 -> 43 and a hard-coded count would
    have gone stale in the same commit. The Glue-start concurrency cap is a separate number."""
    from jobs.orchestrate.run_faostat_backfill import ALL_COMMODITIES, ITEM_MAP, _MAX_CONCURRENT_STARTS
    assert set(ALL_COMMODITIES) == set(ITEM_MAP) and len(ALL_COMMODITIES) == 43
    assert _MAX_CONCURRENT_STARTS == 31             # a throttle, NOT a commodity count
