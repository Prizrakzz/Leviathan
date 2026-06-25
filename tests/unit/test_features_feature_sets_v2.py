from __future__ import annotations

import pandas as pd
import pytest

from leviathan.features.feature_sets_v2 import (
    FeatureSetV2Error,
    select_feature_set_columns_v2,
)


def _matrix() -> pd.DataFrame:
    return pd.DataFrame({
        "entity_type": ["contract_origin"] * 3,
        "entity_id": ["a", "b", "c"],
        "physical_commodity": ["corn", "corn", "corn"],
        "contract_slug": ["corn_cbot"] * 3,
        "origin": ["united_states"] * 3,
        "crop_year": [2022, 2023, 2024],
        "as_of_date": pd.to_datetime(["2022-12-31", "2023-12-31", "2024-12-31"]),
        "snapshot_stage": ["crop_year_end"] * 3,
        "dataset_version": ["v1"] * 3,
        "commodity": ["corn_cbot"] * 3,
        "nass_ge_pct_latest": [50.0, 60.0, 70.0],
        "crush_margin_z": [0.1, 0.2, 0.3],
        "veg_oil_soy_palm_premium_z": [1.0, 2.0, 3.0],
        "veg_oil_soy_palm_ratio_z": [1.0, 2.0, 3.0],
        "pink_sheet_energy_z": [5.0, 5.0, 5.0],
        "cot_mm_net_z": [1.0, 2.0, 3.0],
        "close": [100.0, 101.0, 102.0],
    })


def _catalog() -> pd.DataFrame:
    return pd.DataFrame({
        "feature": [
            "nass_ge_pct_latest",
            "crush_margin_z",
            "veg_oil_soy_palm_premium_z",
            "veg_oil_soy_palm_ratio_z",
            "pink_sheet_energy_z",
            "cot_mm_net_z",
            "close",
        ],
        "semantic_scope": ["origin", "group", "group", "group", "global", "contract", "contract"],
        "policy": [
            "fundamental_physical",
            "certified_economic_driver",
            "certified_economic_driver",
            "certified_economic_driver",
            "certified_economic_driver",
            "diagnostic_only",
            "excluded_market_signal",
        ],
        "mechanism": [
            "crop_condition_progress",
            "soybean_processing_profitability",
            "vegetable_oil_substitution",
            "vegetable_oil_substitution",
            "energy_freight_processing_cost",
            "market_positioning",
            "raw_contract_price",
        ],
    })


def test_feature_set_selection_keeps_crop_condition_only() -> None:
    selection = select_feature_set_columns_v2(
        _matrix(),
        _catalog(),
        "crop_condition",
        target="yield",
    )
    assert selection.columns == ("nass_ge_pct_latest",)
    assert selection.report["selected_count"] == 1


def test_feature_set_selection_filters_and_reduces_processing_economics() -> None:
    selection = select_feature_set_columns_v2(
        _matrix(),
        _catalog(),
        "processing_economics",
        target="production_quantity",
    )
    assert "crush_margin_z" in selection.columns
    assert "close" not in selection.columns
    assert "cot_mm_net_z" not in selection.columns
    assert "pink_sheet_energy_z" in selection.report["dropped"]["zero_variance"]
    assert selection.report["dropped"]["duplicate"] == ["veg_oil_soy_palm_ratio_z"]


def test_feature_set_selection_rejects_incompatible_target() -> None:
    with pytest.raises(FeatureSetV2Error, match="not compatible"):
        select_feature_set_columns_v2(
            _matrix(),
            _catalog(),
            "crop_condition",
            target="stock_to_use",
        )
