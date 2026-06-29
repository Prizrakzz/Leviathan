from __future__ import annotations

import pandas as pd

from leviathan.model_datasets.wasde_snapshot_audit import (
    build_origin_attribute_coverage,
    build_phase0_audit_report,
    build_phase1_source_truth_report,
    build_parser_artifact_report,
    build_psd_target_compatibility_audit,
    build_release_sequence_coverage,
    build_static_feature_reuse_audit,
    build_stock_to_use_constructibility,
    build_wasde_inventory,
    build_wasde_mapping_gaps,
    build_wasde_region_mapping_candidates,
    build_wasde_region_quality,
    build_wasde_source_truth_audit,
    classify_wasde_coverage,
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


def _phase1_wasde_frame() -> pd.DataFrame:
    rows = []
    for year in range(2010, 2022):
        for seq, release in enumerate(("05-10", "06-12", "07-12", "08-12"), start=1):
            for attr, value in (
                ("ending_stocks", 30.0 + year * 0.1 + seq),
                ("total_use", 100.0 + year * 0.2 + seq),
                ("domestic_total", 70.0 + year * 0.1 + seq),
                ("exports", 20.0 + seq),
                ("production", 160.0 + year * 0.5 + seq),
            ):
                rows.append({
                    "release_date": f"{year}-{release}",
                    "commodity": "corn",
                    "table_type": "world",
                    "region": "us",
                    "marketing_year": f"{year}/{str(year + 1)[-2:]}",
                    "attribute": attr,
                    "estimate": value,
                    "revision": 1.0 if seq > 1 else None,
                })
    for year in range(2018, 2022):
        for release in ("05-10", "06-12"):
            rows.append({
                "release_date": f"{year}-{release}",
                "commodity": "corn",
                "table_type": "world",
                "region": "brazil",
                "marketing_year": f"{year}/{str(year + 1)[-2:]}",
                "attribute": "ending_stocks",
                "estimate": 12.0,
                "revision": None,
            })
    rows.extend([
        {
            "release_date": "2021-06-12",
            "commodity": "corn",
            "table_type": "world",
            "region": "argentina_0_39",
            "marketing_year": "2021/22",
            "attribute": "ending_stocks",
            "estimate": 5.0,
            "revision": None,
        },
        {
            "release_date": "2021-06-12",
            "commodity": "corn",
            "table_type": "world",
            "region": "unmappedland",
            "marketing_year": "2021/22",
            "attribute": "ending_stocks",
            "estimate": 6.0,
            "revision": None,
        },
        {
            "release_date": "2021-06-12",
            "commodity": "corn",
            "table_type": "world",
            "region": "world",
            "marketing_year": "2021/22",
            "attribute": "ending_stocks",
            "estimate": 100.0,
            "revision": 1.0,
        },
        {
            "release_date": "2021-06-12",
            "commodity": "corn",
            "table_type": "world",
            "region": "us",
            "marketing_year": "2021/22",
            "attribute": "ending_stocks",
            "estimate": 999.0,
            "revision": 2.0,
        },
    ])
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


def test_source_truth_audit_counts_release_density() -> None:
    audit = build_wasde_source_truth_audit(_phase1_wasde_frame())
    us_ending_2020 = audit.loc[
        (audit["commodity"] == "corn")
        & (audit["normalized_origin"] == "united_states")
        & (audit["marketing_year_start"] == 2020)
        & (audit["attribute"] == "ending_stocks")
    ].iloc[0]

    assert us_ending_2020["release_count"] == 4
    assert us_ending_2020["estimate_non_null_count"] == 4
    assert us_ending_2020["revision_non_null_count"] == 3
    assert us_ending_2020["release_months_present"] == "5,6,7,8"


def test_origin_attribute_coverage_classifies_core_features() -> None:
    source_truth = build_wasde_source_truth_audit(_phase1_wasde_frame())
    coverage = build_origin_attribute_coverage(source_truth)
    us_ending = coverage.loc[
        (coverage["commodity"] == "corn")
        & (coverage["normalized_origin"] == "united_states")
        & (coverage["attribute"] == "ending_stocks")
    ].iloc[0]

    assert us_ending["coverage_class"] == "core_model_feature"
    assert us_ending["recommended_use"] == "core"
    assert us_ending["market_year_count"] == 12
    assert us_ending["median_releases_per_year"] >= 4.0


def test_revision_sparsity_does_not_block_dense_estimate_features() -> None:
    source_truth = build_wasde_source_truth_audit(_phase1_wasde_frame())
    coverage = build_origin_attribute_coverage(source_truth)
    brazil = coverage.loc[
        (coverage["commodity"] == "corn")
        & (coverage["normalized_origin"] == "brazil")
        & (coverage["attribute"] == "ending_stocks")
    ].iloc[0]

    assert brazil["estimate_coverage_rate"] == 1.0
    assert brazil["revision_coverage_rate"] == 0.0
    assert brazil["coverage_class"] == "blocked_insufficient_history"


def test_stock_to_use_constructible_from_total_use_or_components() -> None:
    source_truth = build_wasde_source_truth_audit(_phase1_wasde_frame())
    constructible = build_stock_to_use_constructibility(source_truth)
    us_2020 = constructible.loc[
        (constructible["commodity"] == "corn")
        & (constructible["normalized_origin"] == "united_states")
        & (constructible["marketing_year_start"] == 2020)
    ].iloc[0]

    assert bool(us_2020["stock_to_use_constructible"]) is True
    assert us_2020["stock_to_use_method"] == "official_total_use"


def test_parser_artifact_regions_are_flagged() -> None:
    source_truth = build_wasde_source_truth_audit(_phase1_wasde_frame())
    artifacts = build_parser_artifact_report(source_truth)

    assert "garbled_parser_artifact" in set(artifacts["reason"])
    assert "mapping_gap_review_required" in set(artifacts["reason"])


def test_aggregate_regions_are_not_target_origins() -> None:
    source_truth = build_wasde_source_truth_audit(_phase1_wasde_frame())
    coverage = build_origin_attribute_coverage(source_truth)
    world = coverage.loc[
        (coverage["commodity"] == "corn")
        & (coverage["normalized_origin"] == "world")
        & (coverage["attribute"] == "ending_stocks")
    ].iloc[0]

    assert world["quality_class"] == "aggregate_region"
    assert world["coverage_class"] == "diagnostic_only"
    assert world["recommended_use"] == "aggregate_context_not_target_origin"


def test_mapping_gaps_are_reported_not_silently_dropped() -> None:
    source_truth = build_wasde_source_truth_audit(_phase1_wasde_frame())
    gaps = build_wasde_mapping_gaps(source_truth)

    assert "unmappedland" in set(gaps["region"])
    assert set(gaps["reason"]) == {"unknown_non_aggregate_region"}


def test_conflicting_duplicate_cells_are_reported() -> None:
    source_truth = build_wasde_source_truth_audit(_phase1_wasde_frame())
    duplicate = source_truth.loc[
        (source_truth["commodity"] == "corn")
        & (source_truth["normalized_origin"] == "united_states")
        & (source_truth["marketing_year_start"] == 2021)
        & (source_truth["attribute"] == "ending_stocks")
    ].iloc[0]

    assert duplicate["duplicate_cell_count"] >= 1
    assert duplicate["conflicting_duplicate_count"] >= 2


def test_release_sequence_coverage_summarizes_distribution() -> None:
    source_truth = build_wasde_source_truth_audit(_phase1_wasde_frame())
    sequence = build_release_sequence_coverage(source_truth)
    us_production = sequence.loc[
        (sequence["commodity"] == "corn")
        & (sequence["normalized_origin"] == "united_states")
        & (sequence["attribute"] == "production")
    ].iloc[0]

    assert us_production["market_year_count"] == 12
    assert us_production["median_releases_per_year"] == 4.0


def test_classify_wasde_coverage_helper() -> None:
    assert classify_wasde_coverage({
        "quality_class": "clean_origin",
        "market_year_count": 12,
        "median_releases_per_year": 4,
        "estimate_coverage_rate": 1.0,
        "revision_coverage_rate": 0.1,
    }) == "core_model_feature"


def test_phase1_report_recommends_dense_estimate_rebuild() -> None:
    source_truth = build_wasde_source_truth_audit(_phase1_wasde_frame())
    coverage = build_origin_attribute_coverage(source_truth)
    artifacts = build_parser_artifact_report(source_truth)
    gaps = build_wasde_mapping_gaps(source_truth)
    constructible = build_stock_to_use_constructibility(source_truth)

    report = build_phase1_source_truth_report(
        bucket="unit",
        source_truth=source_truth,
        origin_attribute_coverage=coverage,
        parser_artifacts=artifacts,
        mapping_gaps=gaps,
        stock_to_use_constructibility=constructible,
        commodities=("corn",),
    )

    assert report["phase2_recommendation"]["proceed"] is True
    assert "latest_estimate" in report["phase2_recommendation"]["recommended_core_features"]
    assert "ending_stocks" in report["corn"]["core_attributes"]
