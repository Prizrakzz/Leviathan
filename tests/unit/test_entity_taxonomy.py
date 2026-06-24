from __future__ import annotations

from pathlib import Path
from typing import get_args

import pytest

from leviathan.common.types import CommodityName
from leviathan.entities.taxonomy import TaxonomyError, load_entity_taxonomy


def test_entity_taxonomy_loads_and_covers_all_contracts() -> None:
    taxonomy = load_entity_taxonomy()
    expected = set(get_args(CommodityName))
    commodity_files = {path.stem for path in Path("configs/commodities").glob("*.yaml")}

    assert set(taxonomy.contracts) == expected
    assert commodity_files == expected


def test_contract_resolution_distinguishes_physical_and_processed_products() -> None:
    taxonomy = load_entity_taxonomy()

    soybeans = taxonomy.resolve_contract("soybeans_cbot")
    assert soybeans.entity_type == "physical_commodity"
    assert soybeans.entity_id == "soybeans"

    meal = taxonomy.resolve_contract("soybean_meal_cbot")
    assert meal.entity_type == "processed_product"
    assert meal.entity_id == "soybean_meal"
    assert meal.physical_commodity == "soybeans"


def test_processed_products_cannot_use_crop_area_yield_or_crop_production() -> None:
    taxonomy = load_entity_taxonomy()

    for target in ("production_quantity", "area_harvested", "yield"):
        result = taxonomy.label_policy("soybean_meal_cbot", target, "silver_production")
        assert result.policy == "blocked"
        assert "processed" in result.reason.lower() or "allows" in result.reason.lower()

    valid = taxonomy.label_policy(
        "soybean_meal_cbot",
        "product_production_quantity",
        "silver_wasde",
    )
    assert valid.policy == "direct"


def test_wheat_class_faostat_labels_are_proxy_not_direct() -> None:
    taxonomy = load_entity_taxonomy()
    result = taxonomy.label_policy(
        "hard_red_spring_wheat_mgex",
        "production_quantity",
        "silver_production",
    )
    assert result.policy == "proxy"
    assert "all-wheat" in result.reason
    with pytest.raises(TaxonomyError, match="proxy"):
        taxonomy.require_direct_label(
            "hard_red_spring_wheat_mgex",
            "production_quantity",
            "silver_production",
        )


def test_coffee_species_generic_faostat_labels_are_proxy() -> None:
    taxonomy = load_entity_taxonomy()
    arabica = taxonomy.label_policy("arabica_coffee", "production_quantity", "faostat")
    robusta = taxonomy.label_policy("robusta_coffee", "production_quantity", "faostat")

    assert arabica.policy == "proxy"
    assert robusta.policy == "proxy"
    assert "green-coffee" in arabica.reason


def test_authoritative_source_precedence_uses_specific_sources_before_fallbacks() -> None:
    taxonomy = load_entity_taxonomy()

    assert taxonomy.authoritative_sources("corn_cbot", "production_quantity")[:2] == (
        "silver_nass_annual",
        "silver_production",
    )
    assert taxonomy.authoritative_sources(
        "south_african_white_maize_jse",
        "production_revision",
    )[0] == "silver_sagis_cec"
    assert taxonomy.authoritative_sources(
        "brazilian_arabica_coffee",
        "production_revision",
    ) == ("silver_conab_coffee",)
    assert taxonomy.authoritative_sources("cotton", "quality_tenderable_pct") == (
        "silver_ams_cotton_quality",
    )


def test_duplicate_faostat_label_groups_are_reported_for_phase4_remediation() -> None:
    taxonomy = load_entity_taxonomy()
    groups = taxonomy.duplicate_label_groups()
    by_label = {group.label_id: set(group.contract_slugs) for group in groups}

    assert {"corn_cbot", "campinas_corn_reference_bmf", "french_maize_matif"} <= by_label[
        "Maize (corn)"
    ]
    assert {"arabica_coffee", "robusta_coffee"} <= by_label["Coffee, green"]
    assert {"hard_red_winter_wheat_kcbt", "hard_red_spring_wheat_mgex"} <= by_label[
        "Wheat"
    ]


def test_legacy_commodity_target_audit_flags_known_invalid_targets() -> None:
    taxonomy = load_entity_taxonomy()
    issues = taxonomy.audit_legacy_commodity_targets()
    issue_keys = {(item.contract_slug, item.target_name, item.policy) for item in issues}

    assert ("soybean_meal_cbot", "yield", "blocked") in issue_keys
    assert ("soybean_oil_cbot", "production_quantity", "blocked") in issue_keys
    assert ("hard_red_winter_wheat_kcbt", "production_quantity", "proxy") in issue_keys
    assert ("arabica_coffee", "production_quantity", "proxy") in issue_keys
