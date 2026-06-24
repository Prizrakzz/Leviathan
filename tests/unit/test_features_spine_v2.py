from __future__ import annotations

import pandas as pd

from leviathan.features.pivot import build_feature_matrix_v2
from leviathan.features.spine_v2 import build_spine_v2, validate_spine_v2


def test_spine_v2_emits_only_features_available_by_as_of_date() -> None:
    nass = pd.DataFrame({
        "state": ["US", "US", "US"],
        "year": [2024, 2024, 2024],
        "date": ["2024-06-02", "2024-06-30", "2024-07-07"],
        "pct_good_excellent": [50.0, 62.0, 90.0],
        "pct_planted": [95.0, 100.0, 100.0],
        "pct_harvested": [None, 10.0, 20.0],
    })
    result = build_spine_v2(
        commodity="corn_cbot",
        crop_years=[2024],
        as_of_dates={2024: "2024-07-01"},
        inputs={"nass_crop_progress": nass},
    )
    assert result.passed
    features = result.df.set_index("feature")["value"].to_dict()
    assert features["nass_ge_pct_latest"] == 62.0
    assert features["nass_planted_pct_latest"] == 100.0
    assert features["nass_harvested_pct_latest"] == 10.0
    assert features["nass_ge_pct_change_4w"] == 12.0
    assert result.df["feature_available_at"].max() <= pd.Timestamp("2024-07-01")


def test_spine_v2_validation_rejects_duplicate_natural_keys() -> None:
    df = pd.DataFrame({
        "entity_type": ["contract_origin", "contract_origin"],
        "entity_id": ["corn_cbot:united_states", "corn_cbot:united_states"],
        "physical_commodity": ["corn", "corn"],
        "contract_slug": ["corn_cbot", "corn_cbot"],
        "origin": ["united_states", "united_states"],
        "crop_year": [2024, 2024],
        "as_of_date": [pd.Timestamp("2024-07-01"), pd.Timestamp("2024-07-01")],
        "snapshot_stage": ["custom_as_of", "custom_as_of"],
        "feature": ["nass_ge_pct_latest", "nass_ge_pct_latest"],
        "value": [62.0, 63.0],
        "feature_available_at": [pd.Timestamp("2024-06-30"), pd.Timestamp("2024-06-30")],
        "source": ["nass_crop_progress", "nass_crop_progress"],
        "source_vintage": ["v1", "v1"],
        "is_label": [False, False],
    })
    report = validate_spine_v2(df, commodity="corn_cbot")
    assert not report["passed"]
    assert report["hard_failures"]["duplicate_natural_keys"] == 1


def test_feature_matrix_v2_pivots_snapshot_identity() -> None:
    result = build_spine_v2(
        commodity="corn_cbot",
        crop_years=[2024],
        as_of_dates={2024: "2024-07-01"},
        inputs={
            "nass_crop_progress": pd.DataFrame({
                "state": ["US"],
                "year": [2024],
                "date": ["2024-06-30"],
                "pct_good_excellent": [62.0],
            })
        },
    )
    matrix = build_feature_matrix_v2(result.df)
    assert matrix["entity_id"].tolist() == ["corn_cbot:united_states"]
    assert matrix["nass_ge_pct_latest"].iloc[0] == 62.0
