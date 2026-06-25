from __future__ import annotations

from leviathan.features.taxonomy_v2 import load_feature_taxonomy_v2


def test_taxonomy_v2_classifies_core_feature_families() -> None:
    registry = load_feature_taxonomy_v2()

    nass = registry.classify_feature("nass_ge_pct_latest")
    assert nass.semantic_scope == "origin"
    assert nass.mechanism == "crop_condition_progress"
    assert nass.policy == "fundamental_physical"
    assert nass.sources == ("nass_crop_progress",)

    veg_oil = registry.classify_feature("veg_oil_soy_palm_ratio_z")
    assert veg_oil.semantic_scope == "group"
    assert veg_oil.policy == "certified_economic_driver"
    assert "palm" in veg_oil.groups

    spread = registry.classify_feature("calendar_spread_c1_c2_z")
    assert spread.policy == "excluded_market_signal"
    assert spread.mechanism == "market_term_structure"


def test_taxonomy_v2_falls_back_to_default_physical_origin() -> None:
    classification = load_feature_taxonomy_v2().classify_feature("source_specific_new_metric")
    assert classification.semantic_scope == "origin"
    assert classification.policy == "fundamental_physical"
    assert classification.sources == ()


def test_feature_groups_map_contracts_to_overlapping_groups() -> None:
    groups = load_feature_taxonomy_v2().groups
    assert "oilseeds" in groups.groups_for_commodity("soybean_oil_cbot")
    assert "soy_complex" in groups.groups_for_commodity("soybean_oil_cbot")
    assert "palm" in groups.groups_for_commodity("malaysian_crude_palm_oil_cme")
    assert "us_row_crops" in groups.groups_for_commodity("corn_cbot")
