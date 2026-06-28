from __future__ import annotations

import pandas as pd
import pytest

from leviathan.training.feature_quality import (
    FeatureQualityPolicy,
    build_feature_quality_report,
    enforce_feature_quality,
)


def _matrix() -> pd.DataFrame:
    return pd.DataFrame({
        "country": ["united_states"] * 5,
        "crop_year": [2020, 2021, 2022, 2023, 2024],
        "is_trainable": [True, True, True, True, True],
        "target_value": [0.1, -0.2, 0.0, 0.3, -0.1],
        "signal_a": [1.0, 2.0, 3.0, 4.0, 5.0],
        "signal_b": [5.0, 4.0, 3.0, 2.0, 1.0],
        "mostly_missing": [None, None, None, None, 1.0],
        "all_missing": [None, None, None, None, None],
        "constant_signal": [7.0, 7.0, 7.0, 7.0, 7.0],
        "category_signal": ["dry", "wet", "dry", "normal", "wet"],
        "label_production_quantity": [100.0, 101.0, 99.0, 102.0, 98.0],
        "wasde_latest_revision": [0.1, 0.0, -0.1, 0.2, 0.1],
    })


def _membership() -> pd.DataFrame:
    return pd.DataFrame({
        "feature_set_id": [
            "clean",
            "clean",
            "official_revision",
            "wasde_monthly_revision",
            "bad",
        ],
        "feature": [
            "signal_a",
            "signal_b",
            "wasde_latest_revision",
            "wasde_latest_revision",
            "label_production_quantity",
        ],
        "is_label": [False, False, False, False, True],
        "sources": ["fixture", "fixture", "wasde", "wasde", "fixture"],
    })


def test_feature_quality_passes_clean_numeric_features() -> None:
    report = build_feature_quality_report(
        _matrix(),
        ["signal_a", "signal_b"],
        membership=_membership(),
        dataset_key="psd_snd_anomaly",
        feature_set_id="clean",
        selected_feature_sets=("clean",),
    )

    assert report["status"] == "pass"
    assert report["feature_count"] == 2
    enforce_feature_quality(report)


def test_feature_quality_fails_dangerous_feature_columns() -> None:
    report = build_feature_quality_report(
        _matrix(),
        [
            "all_missing",
            "category_signal",
            "label_production_quantity",
            "missing_from_matrix",
        ],
        membership=_membership(),
        dataset_key="psd_snd_anomaly",
        feature_set_id="bad",
        selected_feature_sets=("bad",),
    )

    reasons = {item["reason"] for item in report["failures"]}
    assert report["status"] == "fail"
    assert "all_missing_features" in reasons
    assert "non_numeric_features" in reasons
    assert "label_or_target_like_features" in reasons
    assert "selected_features_missing_from_matrix" in reasons
    with pytest.raises(ValueError, match="feature quality gate failed"):
        enforce_feature_quality(report)


def test_feature_quality_reports_constant_and_high_missing_warnings() -> None:
    report = build_feature_quality_report(
        _matrix(),
        ["signal_a", "constant_signal", "mostly_missing"],
        membership=_membership(),
        dataset_key="psd_snd_anomaly",
        feature_set_id="sparse",
        selected_feature_sets=("sparse",),
        policy=FeatureQualityPolicy(high_missing_threshold=0.6),
    )

    warning_reasons = {item["reason"] for item in report["warnings"]}
    assert report["status"] == "warn"
    assert "constant_features" in warning_reasons
    assert "high_missing_features" in warning_reasons
    enforce_feature_quality(report)


def test_feature_quality_warns_on_low_coverage_dense_weather_features() -> None:
    matrix = _matrix().assign(
        weather_dense_tmax_anomaly_mean_silking=[1.0, 2.0, None, None, None],
        weather_dense_precip_z_mean_silking=[1.0, 2.0, 3.0, 4.0, 5.0],
    )

    report = build_feature_quality_report(
        matrix,
        [
            "weather_dense_tmax_anomaly_mean_silking",
            "weather_dense_precip_z_mean_silking",
        ],
        membership=_membership(),
        dataset_key="psd_snd_anomaly",
        feature_set_id="inseason_weather_dense",
        selected_feature_sets=("inseason_weather_dense",),
    )

    assert report["status"] == "warn"
    assert report["dense_weather_review_feature_count"] == 1
    assert any(
        item["reason"] == "dense_weather_low_model_ready_coverage"
        for item in report["warnings"]
    )


def test_feature_quality_fails_snapshot_and_annual_wasde_mixed() -> None:
    report = build_feature_quality_report(
        _matrix(),
        ["wasde_latest_revision"],
        membership=_membership(),
        dataset_key="psd_snd_anomaly_snapshot",
        feature_set_id="mixed",
        selected_feature_sets=("official_revision", "wasde_monthly_revision"),
    )

    assert report["status"] == "fail"
    assert report["semantic_duplicate_count"] == 2
    assert any(
        item["reason"] == "duplicate_semantic_feature_sets"
        for item in report["failures"]
    )


def test_feature_quality_fails_large_feature_row_ratio_when_rows_are_sufficient() -> None:
    matrix = pd.DataFrame({
        "is_trainable": [True] * 40,
        **{f"feature_{idx}": [float(idx)] * 40 for idx in range(45)},
    })

    report = build_feature_quality_report(
        matrix,
        [f"feature_{idx}" for idx in range(45)],
        dataset_key="psd_snd_anomaly",
        feature_set_id="too_wide",
        selected_feature_sets=("too_wide",),
    )

    assert report["status"] == "fail"
    assert any(
        item["reason"] == "feature_count_too_large_for_rows"
        for item in report["failures"]
    )


def test_feature_quality_warn_policy_downgrades_failures() -> None:
    report = build_feature_quality_report(
        _matrix(),
        ["all_missing", "category_signal"],
        membership=_membership(),
        dataset_key="legacy_annual",
        feature_set_id="legacy",
        selected_feature_sets=("legacy",),
        policy=FeatureQualityPolicy(mode="warn"),
    )

    assert report["status"] == "warn"
    assert report["failures"] == []
    assert {item["reason"] for item in report["warnings"]} >= {
        "all_missing_features",
        "non_numeric_features",
    }
    enforce_feature_quality(report)
