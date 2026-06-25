from __future__ import annotations

import pandas as pd

from leviathan.features.catalog_v2 import build_feature_catalog_v2


def _spine() -> pd.DataFrame:
    return pd.DataFrame({
        "dataset_version": ["v1", "v1", "v1", "v1"],
        "commodity": ["corn_cbot", "corn_cbot", "soybean_oil_cbot", "malaysian_crude_palm_oil_cme"],
        "entity_type": ["contract_origin"] * 4,
        "entity_id": [
            "corn_cbot:united_states",
            "corn_cbot:united_states",
            "soybean_oil_cbot:united_states",
            "malaysian_crude_palm_oil_cme:malaysia",
        ],
        "physical_commodity": ["corn", "corn", "soybean_oil", "palm_oil"],
        "contract_slug": [
            "corn_cbot",
            "corn_cbot",
            "soybean_oil_cbot",
            "malaysian_crude_palm_oil_cme",
        ],
        "origin": ["united_states", "united_states", "united_states", "malaysia"],
        "crop_year": [2024, 2025, 2024, 2024],
        "as_of_date": ["2024-12-31", "2025-12-31", "2024-12-31", "2024-12-31"],
        "snapshot_stage": ["crop_year_end"] * 4,
        "feature": [
            "nass_ge_pct_latest",
            "nass_ge_pct_latest",
            "crush_margin_z",
            "veg_oil_soy_palm_ratio_z",
        ],
        "value": [62.0, None, 1.2, -0.4],
        "feature_available_at": ["2024-07-01", "2025-07-01", "2024-11-01", "2024-10-15"],
        "source": ["nass_crop_progress", "nass_crop_progress", "futures_prices", "pink_sheet"],
        "source_vintage": ["v"] * 4,
        "is_label": [False] * 4,
    })


def test_feature_catalog_v2_summarizes_taxonomy_and_coverage() -> None:
    result = build_feature_catalog_v2(_spine(), dataset_version="v1")
    catalog = result.catalog.set_index("feature")

    assert catalog.loc["nass_ge_pct_latest", "semantic_scope"] == "origin"
    assert catalog.loc["nass_ge_pct_latest", "mechanism"] == "crop_condition_progress"
    assert catalog.loc["nass_ge_pct_latest", "groups"] == "us_row_crops"
    assert catalog.loc["nass_ge_pct_latest", "row_count"] == 2
    assert catalog.loc["nass_ge_pct_latest", "non_null_rate"] == 0.5

    assert catalog.loc["crush_margin_z", "policy"] == "certified_economic_driver"
    assert catalog.loc["crush_margin_z", "groups"] == "soy_complex"
    assert catalog.loc["veg_oil_soy_palm_ratio_z", "groups"] == "oilseeds,palm"


def test_feature_catalog_v2_emits_entity_and_group_maps() -> None:
    result = build_feature_catalog_v2(_spine(), dataset_version="v1")
    entity = result.entity_map.set_index(["feature", "entity_id"])
    assert entity.loc[("nass_ge_pct_latest", "corn_cbot:united_states"), "row_count"] == 2
    assert entity.loc[("nass_ge_pct_latest", "corn_cbot:united_states"), "non_null_count"] == 1

    groups = result.group_map.set_index(["feature", "group"])
    assert groups.loc[("nass_ge_pct_latest", "us_row_crops"), "entity_count"] == 1
    assert groups.loc[("crush_margin_z", "soy_complex"), "commodity_count"] == 1
