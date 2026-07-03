from __future__ import annotations

import pandas as pd
import pytest

from leviathan.model_datasets.wasde_snapshot_model_ready import (
    SNAPSHOT_MATRIX_NATURAL_KEY,
    build_wasde_snapshot_model_ready_matrix,
    build_wasde_snapshot_model_ready_matrix_from_targets,
    validate_wasde_snapshot_model_ready_matrix,
)
from leviathan.model_datasets.wasde_snapshot_targets import (
    build_wasde_snapshot_target_rows,
)


def _psd_rows(values: list[float] | None = None) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    values = values or [10.0, 11.0, 12.0, 13.0, 14.0, 12.0]
    for offset, value in enumerate(values):
        year = 2000 + offset
        rows.append({
            "leviathan_slug": "corn_cbot",
            "country": "United States",
            "market_year": year,
            "release_date": f"{year + 1}-02-01",
            "production_mt": value,
            "ending_stocks_mt": value + 20.0,
            "su_ratio": value / 100.0,
            "exports_mt": value + 30.0,
            "imports_mt": value + 40.0,
            "consumption_mt": value + 50.0,
        })
    return pd.DataFrame(rows)


def _wasde_rows(
    *,
    market_year: str = "2005/06",
    release_dates: list[str] | None = None,
) -> pd.DataFrame:
    release_dates = release_dates or ["2005-05-12", "2005-06-10", "2005-08-12"]
    attributes = [
        "production",
        "ending_stocks",
        "exports",
        "imports",
        "domestic_total",
        "total_supply",
    ]
    rows: list[dict[str, object]] = []
    for release_idx, release_date in enumerate(release_dates):
        for attr_idx, attribute in enumerate(attributes):
            rows.append({
                "release_date": release_date,
                "commodity": "corn",
                "region": "United States",
                "marketing_year": market_year,
                "attribute": attribute,
                "estimate": 100.0 + release_idx + attr_idx,
            })
    return pd.DataFrame(rows)


def _static_matrix() -> pd.DataFrame:
    return pd.DataFrame([{
        "commodity": "corn_cbot",
        "country": "united_states",
        "crop_year": 2005,
        "faostat_production_yoy": 0.12,
        "pink_sheet_dap_z": -0.4,
        "psd_prior_ending_stocks": 18.5,
        "weather_dense_heat_z_mean": 2.0,
        "label_production_quantity": 999.0,
        "target_value": -0.2,
    }])


def _static_sets() -> dict[str, list[str]]:
    return {
        "corn_preseason_core": [
            "faostat_production_yoy",
            "pink_sheet_dap_z",
            "label_production_quantity",
            "target_value",
            "missing_static_feature",
        ],
        "balance_sheet": ["psd_prior_ending_stocks"],
        "inseason_weather_dense": ["weather_dense_heat_z_mean"],
    }


def test_builds_snapshot_model_ready_matrix_with_dynamic_and_static_features() -> None:
    result = build_wasde_snapshot_model_ready_matrix(
        _psd_rows(),
        _wasde_rows(),
        source_dataset_version="test_source_v",
        dataset_key="corn_wasde_snapshot_solo",
        target_keys=("psd_production_anomaly_pct",),
        static_feature_matrix=_static_matrix(),
        static_feature_sets={
            "corn_preseason_core": ["faostat_production_yoy", "pink_sheet_dap_z"],
            "balance_sheet": ["psd_prior_ending_stocks"],
        },
        min_history_years=2,
    )
    matrix = result.matrix

    assert len(matrix) == 3
    assert set(result.dynamic_feature_columns) >= {
        "wasde_production_latest",
        "wasde_production_mom_revision",
    }
    assert set(result.static_feature_columns) == {
        "faostat_production_yoy",
        "pink_sheet_dap_z",
        "psd_prior_ending_stocks",
    }
    assert matrix["faostat_production_yoy"].tolist() == [0.12, 0.12, 0.12]
    assert matrix["wasde_production_latest"].notna().all()
    assert result.summary["row_count"] == 3
    assert result.summary["feature_count"] == len(result.feature_columns)


def test_dynamic_snapshot_features_are_reused_across_target_keys() -> None:
    result = build_wasde_snapshot_model_ready_matrix(
        _psd_rows(),
        _wasde_rows(),
        source_dataset_version="test_source_v",
        dataset_key="corn_wasde_snapshot_solo",
        target_keys=("psd_production_anomaly_pct", "psd_ending_stocks_anomaly_pct"),
        static_feature_matrix=_static_matrix(),
        static_feature_sets={"corn_preseason_core": ["faostat_production_yoy"]},
        min_history_years=2,
    )

    by_snapshot = result.matrix.pivot_table(
        index="as_of_date",
        columns="target_key",
        values="wasde_production_latest",
        aggfunc="first",
    )
    assert len(result.targets) == 6
    assert by_snapshot["psd_production_anomaly_pct"].equals(
        by_snapshot["psd_ending_stocks_anomaly_pct"]
    )


def test_model_ready_matrix_preserves_grouped_cv_and_sample_weights() -> None:
    result = build_wasde_snapshot_model_ready_matrix(
        _psd_rows(),
        _wasde_rows(),
        source_dataset_version="test_source_v",
        dataset_key="corn_wasde_snapshot_solo",
        target_keys=("psd_production_anomaly_pct",),
        min_history_years=2,
    )

    assert set(result.matrix["cv_group"]) == {"corn_cbot|united_states|2005"}
    assert not result.matrix["cv_group"].astype(str).str.contains("2005-05-12").any()
    weights = result.matrix.groupby([
        "dataset_key",
        "contract_key",
        "origin_key",
        "target_market_year",
        "target_key",
    ])["sample_weight"].sum()
    assert weights.iloc[0] == pytest.approx(1.0)


def test_leakage_columns_from_static_features_are_absent_but_manifested() -> None:
    result = build_wasde_snapshot_model_ready_matrix(
        _psd_rows(),
        _wasde_rows(),
        source_dataset_version="test_source_v",
        dataset_key="corn_wasde_snapshot_solo",
        target_keys=("psd_production_anomaly_pct",),
        static_feature_matrix=_static_matrix(),
        static_feature_sets=_static_sets(),
        min_history_years=2,
    )
    manifest = result.static_manifest.set_index("feature")

    assert "label_production_quantity" not in result.matrix.columns
    assert "target_value" in result.matrix.columns
    assert "target_value" not in result.feature_columns
    assert "missing_static_feature" not in result.matrix.columns
    assert manifest.loc["label_production_quantity", "decision"] == "blocked"
    assert manifest.loc["target_value", "decision"] == "blocked"
    assert manifest.loc["missing_static_feature", "decision"] == "missing_static_feature"


def test_stage_limited_static_features_are_masked_for_preseason_snapshots() -> None:
    result = build_wasde_snapshot_model_ready_matrix(
        _psd_rows(),
        _wasde_rows(),
        source_dataset_version="test_source_v",
        dataset_key="corn_wasde_snapshot_solo",
        target_keys=("psd_production_anomaly_pct",),
        static_feature_matrix=_static_matrix(),
        static_feature_sets={"inseason_weather_dense": ["weather_dense_heat_z_mean"]},
        min_history_years=2,
    )

    preseason = result.matrix.loc[result.matrix["snapshot_stage"] == "preseason"]
    early = result.matrix.loc[result.matrix["snapshot_stage"] == "early_season"]
    assert preseason["weather_dense_heat_z_mean"].isna().all()
    assert early["weather_dense_heat_z_mean"].notna().all()
    assert result.static_manifest.iloc[0]["decision"] == "stage_masked"


def test_duplicate_matrix_keys_raise() -> None:
    result = build_wasde_snapshot_model_ready_matrix(
        _psd_rows(),
        _wasde_rows(),
        source_dataset_version="test_source_v",
        dataset_key="corn_wasde_snapshot_solo",
        target_keys=("psd_production_anomaly_pct",),
        min_history_years=2,
    )
    duplicate = pd.concat([result.matrix, result.matrix.iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate WASDE snapshot model-ready rows"):
        validate_wasde_snapshot_model_ready_matrix(
            duplicate,
            feature_columns=result.feature_columns,
        )


def test_future_wasde_release_in_matrix_raises() -> None:
    result = build_wasde_snapshot_model_ready_matrix(
        _psd_rows(),
        _wasde_rows(),
        source_dataset_version="test_source_v",
        dataset_key="corn_wasde_snapshot_solo",
        target_keys=("psd_production_anomaly_pct",),
        min_history_years=2,
    )
    bad = result.matrix.copy()
    bad.loc[0, "source_release_date_max"] = pd.Timestamp("2005-12-01")

    with pytest.raises(ValueError, match="future release data"):
        validate_wasde_snapshot_model_ready_matrix(
            bad,
            feature_columns=result.feature_columns,
        )


def test_build_from_existing_targets_filters_target_keys() -> None:
    targets = build_wasde_snapshot_target_rows(
        _psd_rows(),
        _wasde_rows(),
        source_dataset_version="test_source_v",
        dataset_key="corn_wasde_snapshot_solo",
    )

    result = build_wasde_snapshot_model_ready_matrix_from_targets(
        targets,
        _wasde_rows(),
        target_keys=("psd_exports_anomaly_pct",),
        min_history_years=2,
    )

    assert set(result.matrix["target_key"]) == {"psd_exports_anomaly_pct"}
    assert not result.matrix.duplicated(SNAPSHOT_MATRIX_NATURAL_KEY).any()
