from __future__ import annotations

import pandas as pd

from leviathan.model_datasets.wasde_snapshot_audit import (
    build_phase0_audit_report,
    build_psd_target_compatibility_audit,
    build_static_feature_reuse_audit,
    build_wasde_inventory,
    build_wasde_region_mapping_candidates,
    build_wasde_region_quality,
    classify_wasde_region,
)


def _wasde_frame() -> pd.DataFrame:
    rows = []
    for release in ("2024-05-10", "2024-06-12", "2024-07-12"):
        for region in ("us", "brazil", "123_4_56", "total_foreign"):
            for attribute in ("production", "ending_stocks", "exports"):
                rows.append({
                    "release_date": release,
                    "commodity": "corn",
                    "table_type": "world",
                    "region": region,
                    "marketing_year": "2024/25",
                    "attribute": attribute,
                    "estimate": 100.0,
                    "revision": 1.0,
                })
    rows.append({
        "release_date": "2024-06-12",
        "commodity": "wheat",
        "table_type": "world",
        "region": "canada",
        "marketing_year": "2024/25",
        "attribute": "production",
        "estimate": 30.0,
        "revision": -1.0,
    })
    return pd.DataFrame(rows)


def _psd_frame() -> pd.DataFrame:
    rows = []
    for year in range(2010, 2021):
        production = 100.0 + (year - 2010) * 10.0
        ending = 50.0 + (year - 2010) * 2.0
        if year == 2020:
            production = 120.0
            ending = 30.0
        rows.append({
            "leviathan_slug": "corn_cbot",
            "country": "United States",
            "market_year": year,
            "release_date": f"{year + 1}-05-10",
            "beginning_stocks_mt": 10.0,
            "production_mt": production,
            "imports_mt": 5.0 + year * 0.01,
            "exports_mt": 20.0 + year * 0.02,
            "ending_stocks_mt": ending,
            "consumption_mt": 70.0 + year * 0.02,
            "area_harvested_1000ha": 1.0,
            "yield_mt_ha": 1.0,
            "su_ratio": ending / (70.0 + year * 0.02),
            "su_ratio_yoy_delta": 0.0,
            "production_mt_revision": 0.0,
            "ending_stocks_mt_revision": 0.0,
            "consumption_mt_revision": 0.0,
        })
    return pd.DataFrame(rows)


def test_counts_core_attributes_by_commodity() -> None:
    inventory = build_wasde_inventory(_wasde_frame())
    corn = inventory.loc[inventory["commodity"] == "corn"].iloc[0]

    assert corn["release_date_count"] == 3
    assert corn["marketing_year_count"] == 1
    assert corn["region_count"] == 4
    assert corn["production_row_count"] == 12
    assert corn["ending_stocks_row_count"] == 12
    assert corn["core_snapshot_key_count"] == 36


def test_flags_garbled_and_clean_regions() -> None:
    assert classify_wasde_region("123_4_56")["quality_class"] == "garbled_parser_artifact"
    assert classify_wasde_region("US")["recommended_origin"] == "united_states"
    assert classify_wasde_region("total_foreign")["quality_class"] == "aggregate_region"


def test_region_quality_report_and_candidates() -> None:
    quality = build_wasde_region_quality(_wasde_frame())
    candidates = build_wasde_region_mapping_candidates(quality)

    assert {
        "commodity",
        "region",
        "normalized_region",
        "quality_class",
        "recommended_origin",
    }.issubset(quality.columns)
    assert "garbled_parser_artifact" in set(quality["quality_class"])
    assert set(candidates["recommended_origin"]) >= {"united_states", "brazil", "canada"}


def test_target_class_balance_thresholds() -> None:
    target_audit, class_balance = build_psd_target_compatibility_audit(
        _psd_frame(),
        source_dataset_version="unit",
        commodities=("corn_cbot",),
    )

    production = target_audit.loc[
        target_audit["target_key"] == "psd_production_anomaly_pct"
    ].iloc[0]
    assert production["row_count"] == 11
    assert production["trainable_row_count"] > 0
    fixed_5 = class_balance.loc[
        (class_balance["target_key"] == "psd_production_anomaly_pct")
        & (class_balance["threshold_type"] == "fixed_5pct")
    ].iloc[0]
    assert fixed_5["stress_event_direction"] == "lower_is_stress"
    assert fixed_5["positive_event_count"] >= 1


def test_static_feature_reuse_blocks_unsafe_sets() -> None:
    audit = build_static_feature_reuse_audit({
        "defaults": {"min_lag_days": 0},
        "feature_sets": [
            {"id": "preseason_physical"},
            {"id": "inseason_weather_dense"},
            {"id": "wasde_monthly_revision"},
            {"id": "planting_incentives", "min_lag_days": 1},
        ],
    })
    by_id = audit.set_index("feature_set_id")

    assert by_id.loc["preseason_physical", "decision"] == "safe_all_snapshots"
    assert (
        by_id.loc["inseason_weather_dense", "decision"]
        == "stage_limited_requires_as_of_filter"
    )
    assert (
        by_id.loc["wasde_monthly_revision", "decision"]
        == "dynamic_snapshot_feature_not_static_join"
    )


def test_phase0_report_recommends_proceed_when_core_inputs_exist() -> None:
    inventory = build_wasde_inventory(_wasde_frame())
    quality = build_wasde_region_quality(_wasde_frame())
    candidates = build_wasde_region_mapping_candidates(quality)
    target_audit, class_balance = build_psd_target_compatibility_audit(
        _psd_frame(),
        source_dataset_version="unit",
        commodities=("corn_cbot",),
    )
    static = build_static_feature_reuse_audit({
        "defaults": {"min_lag_days": 0},
        "feature_sets": [{"id": "preseason_physical"}],
    })

    report = build_phase0_audit_report(
        bucket="unit",
        wasde_inventory=inventory,
        region_quality=quality,
        mapping_candidates=candidates,
        psd_target_audit=target_audit,
        target_class_balance=class_balance,
        static_feature_reuse=static,
    )

    assert report["phase1_recommendation"]["proceed"] is False
    assert "corn_wasde_release_history_too_short" in report["phase1_recommendation"]["blockers"]
