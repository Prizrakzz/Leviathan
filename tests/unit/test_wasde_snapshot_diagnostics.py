from __future__ import annotations

import numpy as np
import pandas as pd

from leviathan.model_datasets.wasde_snapshot_diagnostics import (
    audit_wasde_snapshot_leakage,
    build_baseline_diagnostics,
    build_feature_quality_report,
    build_matrix_integrity_report,
    build_readiness_decision,
    build_target_event_diagnostics,
    diagnose_wasde_snapshot_matrix,
)


FEATURE_COLUMNS = (
    "wasde_production_latest",
    "static_dense_feature",
    "all_missing_feature",
    "constant_feature",
    "sparse_feature",
)


def _matrix(
    *,
    n_groups: int = 6,
    snapshots_per_group: int = 2,
    event_groups: int = 3,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for group_idx in range(n_groups):
        year = 2000 + group_idx
        is_event = group_idx < event_groups
        target_value = -0.20 if is_event else 0.05 + group_idx / 100.0
        for snapshot_idx in range(snapshots_per_group):
            month = 5 + snapshot_idx
            rows.append({
                "source_dataset_version": "test_v",
                "dataset_key": "corn_wasde_snapshot_solo",
                "contract_key": "corn_cbot",
                "commodity": "corn_cbot",
                "commodity_group": "grains",
                "origin": "United States",
                "origin_key": "united_states",
                "target_market_year": year,
                "crop_year": year,
                "target_key": "psd_production_anomaly_pct",
                "target_family": "psd_production_anomaly",
                "target_attribute": "production",
                "target_source": "psd",
                "target_value": target_value,
                "target_anomaly_pct": target_value,
                "actual_value": 100.0 + target_value,
                "trend_prediction": 100.0,
                "history_years": 10,
                "target_available": True,
                "target_observation_release_date": f"{year + 1}-02-01",
                "target_source_vintage": "latest",
                "as_of_date": f"{year}-0{month}-12",
                "snapshot_stage": "preseason" if snapshot_idx == 0 else "early_season",
                "snapshot_month_code": month,
                "snapshot_policy": "wasde_release_month_v1",
                "snapshot_sequence": snapshot_idx + 1,
                "snapshot_count": snapshots_per_group,
                "target_event_label": is_event,
                "target_event_threshold": 0.10,
                "target_event_threshold_type": "fixed_10pct",
                "target_event_direction": "lower_is_stress",
                "target_event_definition": "fixed_10pct",
                "sample_weight": 1.0 / snapshots_per_group,
                "cv_group": f"corn_cbot|united_states|{year}",
                "cv_time": year,
                "is_trainable": True,
                "excluded_reason": "",
                "snapshot_available": True,
                "mapping_confidence": "high",
                "target_status": "trainable",
                "psd_source_slug": "corn_cbot",
                "psd_commodity": "corn",
                "psd_country": "United States",
                "origin_role": "primary",
                "wasde_commodity": "corn",
                "wasde_origin": "united_states",
                "wasde_region": "united_states",
                "wasde_release_count_for_group": snapshots_per_group,
                "psd_mapping_sha": "psd_sha",
                "wasde_mapping_sha": "wasde_sha",
                "source_release_date_max": f"{year}-0{month}-12",
                "source_release_count_visible": snapshot_idx + 1,
                "zero_anomaly_baseline": 0.0,
                "prior_year_anomaly_baseline": -0.12 if is_event else 0.03,
                "trailing_mean_anomaly_baseline": -0.05 if is_event else 0.02,
                "trailing_trend_anomaly_baseline": -0.08 if is_event else 0.04,
                "wasde_production_latest": 100.0 + group_idx + snapshot_idx,
                "static_dense_feature": float(group_idx),
                "all_missing_feature": np.nan,
                "constant_feature": 1.0,
                "sparse_feature": 7.0 if group_idx == 0 and snapshot_idx == 0 else np.nan,
            })
    return pd.DataFrame(rows)


def _static_manifest() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "feature_set_id": "preseason_physical",
            "feature": "static_dense_feature",
            "decision": "allowed",
            "reason": "static_feature_available",
        },
        {
            "feature_set_id": "preseason_physical",
            "feature": "blocked_static_feature",
            "decision": "blocked",
            "reason": "target_or_label_leakage",
        },
    ])


def test_integrity_report_flags_duplicate_keys_and_bad_weights() -> None:
    matrix = pd.concat([_matrix(n_groups=2), _matrix(n_groups=2).iloc[[0]]], ignore_index=True)
    matrix.loc[matrix.index[:2], "sample_weight"] = 1.0

    report = build_matrix_integrity_report(matrix)

    assert report["duplicate_key_count"] == 1
    assert report["bad_weight_group_count"] >= 1
    assert report["cv_group_has_dates"] is False


def test_leakage_audit_flags_future_release_target_features_and_blocked_static() -> None:
    matrix = _matrix(n_groups=2)
    matrix.loc[0, "source_release_date_max"] = pd.Timestamp("2099-01-01")
    matrix["blocked_static_feature"] = 1.0

    issues = audit_wasde_snapshot_leakage(
        matrix,
        feature_columns=(
            "wasde_production_latest",
            "target_value",
            "psd_ending_stocks_actual",
            "blocked_static_feature",
        ),
        static_manifest=_static_manifest(),
    )

    assert set(issues["issue_type"]) == {
        "future_source_release",
        "target_feature_selected",
        "same_year_psd_feature_selected",
        "blocked_static_feature_selected",
    }


def test_feature_quality_buckets_all_missing_constant_sparse_and_dense() -> None:
    quality = build_feature_quality_report(
        _matrix(n_groups=6),
        feature_columns=FEATURE_COLUMNS,
        static_manifest=_static_manifest(),
    ).set_index("feature")

    assert quality.loc["wasde_production_latest", "quality_bucket"] == "dense"
    assert quality.loc["static_dense_feature", "feature_origin"] == "static_annual"
    assert quality.loc["all_missing_feature", "quality_bucket"] == "all_missing"
    assert quality.loc["constant_feature", "quality_bucket"] == "constant"
    assert quality.loc["sparse_feature", "quality_bucket"] == "ultra_sparse"


def test_target_event_diagnostics_count_independent_annual_groups() -> None:
    diagnostics = build_target_event_diagnostics(
        _matrix(n_groups=6, snapshots_per_group=3, event_groups=2)
    ).iloc[0]

    assert diagnostics["annual_group_count"] == 6
    assert diagnostics["row_count"] == 18
    assert diagnostics["event_group_count"] == 2
    assert diagnostics["event_snapshot_count"] == 6
    assert diagnostics["snapshot_count_median"] == 3


def test_baseline_diagnostics_report_false_negatives_and_recall() -> None:
    baselines = build_baseline_diagnostics(
        _matrix(n_groups=6, snapshots_per_group=3, event_groups=2)
    )
    zero = baselines.loc[baselines["baseline_name"] == "zero_anomaly"].iloc[0]
    prior = baselines.loc[baselines["baseline_name"] == "prior_year"].iloc[0]

    assert zero["event_count"] == 2
    assert zero["false_negative_count"] == 2
    assert zero["recall"] == 0.0
    assert prior["true_positive_count"] == 2
    assert prior["recall"] == 1.0


def test_baseline_diagnostics_include_zero_baseline_when_materialized_baselines_absent() -> None:
    matrix = _matrix(n_groups=4, event_groups=2).drop(columns=[
        "zero_anomaly_baseline",
        "prior_year_anomaly_baseline",
        "trailing_mean_anomaly_baseline",
        "trailing_trend_anomaly_baseline",
    ])

    baselines = build_baseline_diagnostics(matrix)

    assert baselines["baseline_name"].tolist() == ["zero_anomaly"]
    assert baselines.iloc[0]["event_count"] == 2
    assert baselines.iloc[0]["false_negative_count"] == 2


def test_readiness_fails_on_leakage_and_duplicate_integrity() -> None:
    matrix = _matrix(n_groups=6)
    integrity = build_matrix_integrity_report(pd.concat([matrix, matrix.iloc[[0]]], ignore_index=True))
    leakage = audit_wasde_snapshot_leakage(matrix, feature_columns=("target_value",))
    quality = build_feature_quality_report(matrix, feature_columns=("wasde_production_latest",))
    targets = build_target_event_diagnostics(matrix)

    decision = build_readiness_decision(
        integrity=integrity,
        leakage_issues=leakage,
        feature_quality=quality,
        target_diagnostics=targets,
        min_trainable_annual_groups=5,
        min_event_groups=2,
    )

    assert decision["status"] == "fail"
    assert "duplicate_snapshot_keys" in decision["failures"]
    assert "leakage_audit_failed" in decision["failures"]


def test_readiness_warns_on_too_few_event_groups_and_sparse_features() -> None:
    matrix = _matrix(n_groups=6, event_groups=1)
    decision = diagnose_wasde_snapshot_matrix(
        matrix,
        feature_columns=FEATURE_COLUMNS,
        static_manifest=_static_manifest(),
        min_trainable_annual_groups=5,
        min_event_groups=3,
        max_sparse_feature_share=0.2,
    ).readiness

    assert decision["status"] == "warn"
    assert "event_groups_below_3" in decision["warnings"]
    assert "sparse_feature_share_high" in decision["warnings"]


def test_diagnostics_report_passes_healthy_snapshot_matrix() -> None:
    report = diagnose_wasde_snapshot_matrix(
        _matrix(n_groups=8, event_groups=4),
        feature_columns=("wasde_production_latest", "static_dense_feature"),
        static_manifest=_static_manifest(),
        min_trainable_annual_groups=6,
        min_event_groups=3,
    )

    assert report.leakage_issues.empty
    assert report.readiness["status"] == "pass"
    assert report.integrity["annual_outcome_group_count"] == 8
    assert set(report.baseline_diagnostics["baseline_name"]) >= {
        "zero_anomaly",
        "prior_year",
        "trailing_mean",
        "trailing_trend",
    }
