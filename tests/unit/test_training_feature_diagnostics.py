from __future__ import annotations

import json

import pandas as pd

from leviathan.training.feature_diagnostics import (
    build_correlation_pairs,
    build_feature_diagnostics,
    build_feature_inventory,
    build_missingness_target_association,
    build_target_tail_reports,
    write_feature_diagnostics,
)
from leviathan.training.certification import TargetEventPolicy


def _frame() -> pd.DataFrame:
    rows = []
    for country, base in [("argentina", -0.2), ("brazil", 0.1)]:
        for i, year in enumerate(range(2010, 2018)):
            signal = float(i)
            target = base + 0.04 * signal
            rows.append({
                "country": country,
                "crop_year": year,
                "target_value": target,
                "weather_signal": signal,
                "weather_signal_clone": signal * 2.0,
                "constant_feature": 1.0,
                "sometimes_missing": None if year in {2010, 2011, 2012} else signal,
                "categorical_feature": "wet" if i % 2 else "dry",
            })
    return pd.DataFrame(rows)


def _membership() -> pd.DataFrame:
    return pd.DataFrame({
        "feature": [
            "weather_signal",
            "weather_signal_clone",
            "constant_feature",
            "sometimes_missing",
            "categorical_feature",
        ],
        "feature_family": [
            "weather_temperature",
            "weather_temperature",
            "diagnostic",
            "weather_drought",
            "bad_input",
        ],
        "semantic_scope": ["global_climate"] * 5,
        "policy": ["fundamental_physical"] * 4 + ["diagnostic_only"],
        "mechanism": ["test"] * 5,
        "sources": ["fixture"] * 5,
        "source_cadence": ["annual"] * 5,
        "empirical_scope": ["commodity"] * 5,
        "groups": ["grains"] * 5,
        "target_compatibility": ["production_anomaly"] * 5,
        "missingness_policy": ["tree_models_allow_nan"] * 5,
        "min_lag_days": [0] * 5,
    })


def _features() -> list[str]:
    return [
        "weather_signal",
        "weather_signal_clone",
        "constant_feature",
        "sometimes_missing",
        "categorical_feature",
    ]


def test_feature_inventory_flags_missing_constant_and_non_numeric_features() -> None:
    inventory = build_feature_inventory(
        _frame(), _features(), membership=_membership()
    )

    by_feature = inventory.set_index("feature")
    assert by_feature.loc["sometimes_missing", "null_rate"] > 0
    assert bool(by_feature.loc["constant_feature", "is_constant"]) is True
    assert bool(by_feature.loc["categorical_feature", "is_numeric"]) is False
    assert by_feature.loc["weather_signal", "feature_family"] == "weather_temperature"


def test_target_tail_reports_count_downside_events_by_origin_and_year() -> None:
    summary, by_country, by_year = build_target_tail_reports(
        _frame(),
        target_col="target_value",
        bad_quantile=0.25,
        thresholds=(-0.10,),
    )

    assert set(summary["event_definition"]) == {"bottom_quantile_0.25", "target_le_-0.1"}
    bottom = summary.set_index("event_definition").loc["bottom_quantile_0.25"]
    assert bottom["event_count"] > 0
    assert "argentina" in set(by_country["country"])
    assert 2010 in set(by_year["crop_year"])


def test_target_tail_reports_support_higher_is_stress_events() -> None:
    summary, by_country, _ = build_target_tail_reports(
        _frame(),
        target_col="target_value",
        bad_quantile=0.25,
        thresholds=(0.10,),
        target_policy=TargetEventPolicy(
            target_key="psd_exports_anomaly_pct",
            stress_event_direction="higher_is_stress",
        ),
    )

    assert set(summary["event_definition"]) == {"top_quantile_0.25", "target_ge_0.1"}
    assert set(summary["stress_event_direction"]) == {"higher_is_stress"}
    assert "brazil" in set(by_country["country"])


def test_missingness_target_association_measures_missing_target_delta() -> None:
    assoc = build_missingness_target_association(
        _frame(),
        _features(),
        target_col="target_value",
        bad_quantile=0.25,
    ).set_index("feature")

    assert assoc.loc["sometimes_missing", "missing_count"] == 6
    assert pd.notna(assoc.loc["sometimes_missing", "missing_minus_present_target_mean"])


def test_correlation_pairs_finds_near_duplicate_numeric_features() -> None:
    pairs = build_correlation_pairs(_frame(), _features(), threshold=0.99)

    assert {
        tuple(sorted((row.feature_a, row.feature_b)))
        for row in pairs.itertuples(index=False)
    } >= {("weather_signal", "weather_signal_clone")}

    none = build_correlation_pairs(_frame(), _features(), threshold=1.01)
    assert list(none.columns) == [
        "feature_a",
        "feature_b",
        "correlation",
        "abs_correlation",
    ]
    assert none.empty


def test_full_diagnostics_bundle_writes_expected_artifacts(tmp_path) -> None:
    artifacts = build_feature_diagnostics(
        _frame(),
        _features(),
        target_col="target_value",
        membership=_membership(),
        reports=[],
        commodity="corn_cbot",
        dataset_key="psd_snd_anomaly",
        target_key="psd_production_anomaly_pct",
        feature_set_id="fixture_set",
    )
    paths = write_feature_diagnostics(
        artifacts,
        tmp_path,
        manifest={"model_dataset_version": "test_version"},
    )

    assert (tmp_path / "feature_inventory.parquet").exists()
    assert (tmp_path / "preprocessing_audit.json").exists()
    assert (tmp_path / "manifest.json").exists()
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["model_dataset_version"] == "test_version"
    assert "feature_inventory" in paths
    assert artifacts.preprocessing_audit["non_numeric_features"] == ["categorical_feature"]
