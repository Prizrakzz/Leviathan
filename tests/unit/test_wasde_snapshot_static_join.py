from __future__ import annotations

import pandas as pd
import pytest
from leviathan.model_datasets.wasde_snapshot_static_join import (
    build_static_feature_reuse_manifest,
    classify_static_feature_availability,
    join_static_features_to_wasde_snapshots,
)


def _snapshot_rows(stages: list[str] | None = None) -> pd.DataFrame:
    stages = stages or ["preseason", "early_season", "midseason"]
    rows: list[dict[str, object]] = []
    for idx, stage in enumerate(stages, start=5):
        rows.append({
            "dataset_key": "corn_wasde_snapshot_solo",
            "contract_key": "corn_cbot",
            "origin_key": "united_states",
            "target_market_year": 2024,
            "as_of_date": f"2024-{idx:02d}-12",
            "snapshot_stage": stage,
            "target_key": "psd_production_anomaly_pct",
        })
    return pd.DataFrame(rows)


def _static_matrix() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "commodity": "corn_cbot",
            "country": "united_states",
            "crop_year": 2024,
            "faostat_production_yoy": 0.04,
            "pink_sheet_dap_z": 1.2,
            "psd_prior_ending_stocks": 20.0,
            "psd_ending_stocks_actual": 18.0,
            "weather_dense_heat_z_mean": 2.5,
            "fgis_export_pace_yoy": -0.1,
            "label_production_quantity": 100.0,
            "target_value": -0.2,
            "futures_front_month_return": 0.08,
        }
    ])


def _feature_sets() -> dict[str, list[str]]:
    return {
        "corn_preseason_core": [
            "faostat_production_yoy",
            "pink_sheet_dap_z",
            "label_production_quantity",
            "target_value",
            "futures_front_month_return",
        ],
        "balance_sheet": [
            "psd_prior_ending_stocks",
            "psd_ending_stocks_actual",
        ],
        "inseason_weather_dense": ["weather_dense_heat_z_mean"],
        "physical_flow": ["fgis_export_pace_yoy"],
    }


def test_static_join_repeats_annual_features_across_snapshots() -> None:
    joined, manifest = join_static_features_to_wasde_snapshots(
        _snapshot_rows(),
        _static_matrix(),
        {
            "corn_preseason_core": ["faostat_production_yoy", "pink_sheet_dap_z"],
        },
    )

    assert len(joined) == 3
    assert joined["faostat_production_yoy"].tolist() == [0.04, 0.04, 0.04]
    assert joined["pink_sheet_dap_z"].tolist() == [1.2, 1.2, 1.2]
    assert set(manifest["decision"]) == {"allowed"}


def test_aliases_static_country_and_commodity_to_snapshot_keys() -> None:
    static = _static_matrix()[[
        "commodity",
        "country",
        "crop_year",
        "faostat_production_yoy",
    ]]

    joined, _ = join_static_features_to_wasde_snapshots(
        _snapshot_rows(["preseason"]),
        static,
        {"preseason_physical": ["faostat_production_yoy"]},
    )

    assert joined.iloc[0]["faostat_production_yoy"] == pytest.approx(0.04)


def test_blocked_target_label_market_and_same_year_psd_columns_are_not_joined() -> None:
    joined, manifest = join_static_features_to_wasde_snapshots(
        _snapshot_rows(["preseason"]),
        _static_matrix(),
        _feature_sets(),
    )

    assert "label_production_quantity" not in joined.columns
    assert "target_value" not in joined.columns
    assert "futures_front_month_return" not in joined.columns
    assert "psd_ending_stocks_actual" not in joined.columns
    by_feature = manifest.set_index("feature")
    assert by_feature.loc["label_production_quantity", "reason"] == "target_or_label_leakage"
    assert by_feature.loc["target_value", "reason"] == "target_or_label_leakage"
    assert by_feature.loc["futures_front_month_return", "reason"] == "excluded_market_signal"
    assert by_feature.loc["psd_ending_stocks_actual", "reason"] == "same_year_psd_context_not_lagged"


def test_prior_year_balance_sheet_context_is_allowed() -> None:
    joined, manifest = join_static_features_to_wasde_snapshots(
        _snapshot_rows(["preseason"]),
        _static_matrix(),
        {"balance_sheet": ["psd_prior_ending_stocks"]},
    )

    assert joined.iloc[0]["psd_prior_ending_stocks"] == pytest.approx(20.0)
    assert manifest.iloc[0]["decision"] == "allowed"


def test_stage_limited_features_are_masked_before_they_are_available() -> None:
    joined, manifest = join_static_features_to_wasde_snapshots(
        _snapshot_rows(["preseason", "early_season"]),
        _static_matrix(),
        {"inseason_weather_dense": ["weather_dense_heat_z_mean"]},
    )

    preseason = joined.loc[joined["snapshot_stage"] == "preseason"].iloc[0]
    early = joined.loc[joined["snapshot_stage"] == "early_season"].iloc[0]
    assert pd.isna(preseason["weather_dense_heat_z_mean"])
    assert early["weather_dense_heat_z_mean"] == pytest.approx(2.5)
    assert manifest.iloc[0]["decision"] == "stage_masked"
    assert manifest.iloc[0]["blocked_snapshot_stages"] == "preseason"


def test_stage_limited_features_are_blocked_when_only_preseason_snapshots_exist() -> None:
    joined, manifest = join_static_features_to_wasde_snapshots(
        _snapshot_rows(["preseason"]),
        _static_matrix(),
        {"physical_flow": ["fgis_export_pace_yoy"]},
    )

    assert "fgis_export_pace_yoy" not in joined.columns
    assert manifest.iloc[0]["decision"] == "blocked"
    assert manifest.iloc[0]["reason"] == "stage_limited_feature_unavailable"


def test_missing_static_features_are_reported_without_dropping_rows() -> None:
    joined, manifest = join_static_features_to_wasde_snapshots(
        _snapshot_rows(["preseason"]),
        _static_matrix(),
        {"corn_preseason_core": ["not_in_matrix"]},
    )

    assert len(joined) == 1
    assert "not_in_matrix" not in joined.columns
    assert manifest.iloc[0]["decision"] == "missing_static_feature"


def test_empty_feature_set_membership_returns_empty_manifest_and_preserves_rows() -> None:
    joined, manifest = join_static_features_to_wasde_snapshots(
        _snapshot_rows(["preseason"]),
        _static_matrix(),
        pd.DataFrame(columns=["feature_set_id", "feature"]),
    )

    assert len(joined) == 1
    assert manifest.empty
    assert {
        "feature_set_id",
        "feature",
        "decision",
        "reason",
    }.issubset(manifest.columns)


def test_duplicate_static_keys_raise_on_conflicting_values() -> None:
    static = pd.concat([
        _static_matrix(),
        _static_matrix().assign(faostat_production_yoy=0.99),
    ], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate static feature keys"):
        join_static_features_to_wasde_snapshots(
            _snapshot_rows(["preseason"]),
            static,
            {"preseason_physical": ["faostat_production_yoy"]},
        )


def test_duplicate_static_keys_with_same_values_are_deduped() -> None:
    static = pd.concat([_static_matrix(), _static_matrix()], ignore_index=True)

    joined, _ = join_static_features_to_wasde_snapshots(
        _snapshot_rows(["preseason"]),
        static,
        {"preseason_physical": ["faostat_production_yoy"]},
    )

    assert len(joined) == 1
    assert joined.iloc[0]["faostat_production_yoy"] == pytest.approx(0.04)


def test_dynamic_feature_collision_is_blocked_in_manifest() -> None:
    manifest = build_static_feature_reuse_manifest(
        _snapshot_rows(["preseason"]),
        _static_matrix().assign(wasde_production_latest=100.0),
        {"corn_preseason_core": ["wasde_production_latest"]},
        dynamic_feature_columns={"wasde_production_latest"},
    )

    assert manifest.iloc[0]["decision"] == "blocked"
    assert manifest.iloc[0]["reason"] == "dynamic_feature_collision"


def test_existing_snapshot_column_collision_raises_for_selected_feature() -> None:
    snapshots = _snapshot_rows(["preseason"]).assign(existing_static_feature=1.0)
    static = _static_matrix().assign(existing_static_feature=2.0)

    with pytest.raises(ValueError, match="collide with snapshot columns"):
        join_static_features_to_wasde_snapshots(
            snapshots,
            static,
            {"preseason_physical": ["existing_static_feature"]},
        )


def test_diagnostic_only_policy_blocks_unless_allowed() -> None:
    blocked = classify_static_feature_availability(
        "faostat_data_quality_flag",
        "preseason_physical",
        snapshot_stages=["preseason"],
        feature_policy="diagnostic_only",
    )
    allowed = classify_static_feature_availability(
        "faostat_data_quality_flag",
        "preseason_physical",
        snapshot_stages=["preseason"],
        feature_policy="diagnostic_only",
        allow_diagnostic=True,
    )

    assert blocked.decision == "blocked"
    assert blocked.reason == "diagnostic_only"
    assert allowed.decision == "allowed"
