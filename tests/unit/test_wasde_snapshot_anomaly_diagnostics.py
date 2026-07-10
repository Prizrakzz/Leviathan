from __future__ import annotations

import pandas as pd
from leviathan.model_datasets.wasde_snapshot_anomaly_diagnostics import (
    build_composite_dominance_report,
    build_redundant_feature_family_report,
    build_score_component_clusters,
    build_score_component_correlation,
    build_score_missingness_diagnostics,
)


def _score_row(
    year: int,
    *,
    score_name: str,
    detector_id: str,
    source_feature: str,
    source_attribute: str,
    source_transform: str,
    score_value: float | None,
) -> dict[str, object]:
    return {
        "dataset_key": "corn_wasde_snapshot_solo",
        "contract_key": "corn_cbot",
        "origin_key": "united_states",
        "target_market_year": year,
        "target_key": "psd_stock_to_use_anomaly_pct",
        "as_of_date": f"{year}-06-12",
        "snapshot_stage": "preseason",
        "detector_id": detector_id,
        "score_name": score_name,
        "source_feature": source_feature,
        "source_attribute": source_attribute,
        "source_transform": source_transform,
        "raw_value": score_value,
        "score_value": score_value,
        "stress_direction": "higher_is_stress",
        "prior_observation_count": 10,
        "normalization_group_used": "contract_origin_stage",
        "component_count": None,
        "score_null_reason": "" if score_value is not None else "missing_value",
    }


def test_score_missingness_reports_stage_origin_detector() -> None:
    scores = pd.DataFrame([
        _score_row(
            2000,
            score_name="a",
            detector_id="revision_shock",
            source_feature="wasde_exports_mom_revision",
            source_attribute="exports",
            source_transform="mom_revision",
            score_value=1.0,
        ),
        _score_row(
            2001,
            score_name="a",
            detector_id="revision_shock",
            source_feature="wasde_exports_mom_revision",
            source_attribute="exports",
            source_transform="mom_revision",
            score_value=None,
        ),
    ])

    report = build_score_missingness_diagnostics(scores)

    assert len(report) == 1
    assert report.iloc[0]["non_null_rate"] == 0.5
    assert report.iloc[0]["null_reasons"] == "missing_value"


def test_component_correlation_clusters_highly_related_scores() -> None:
    rows = []
    for year, value in enumerate([1, 2, 3, 4, 5], start=2000):
        rows.append(_score_row(
            year,
            score_name="stocks",
            detector_id="stage_level_z",
            source_feature="wasde_ending_stocks_latest",
            source_attribute="ending_stocks",
            source_transform="level",
            score_value=float(value),
        ))
        rows.append(_score_row(
            year,
            score_name="stock_to_use",
            detector_id="stage_level_z",
            source_feature="wasde_stock_to_use_latest",
            source_attribute="stock_to_use",
            source_transform="level",
            score_value=float(value * 2),
        ))
    corr = build_score_component_correlation(pd.DataFrame(rows))
    clusters = build_score_component_clusters(corr, threshold=0.95)

    assert not corr.empty
    assert corr.iloc[0]["abs_correlation"] > 0.95
    assert not clusters.empty
    assert clusters["cluster_size"].max() == 2


def test_redundant_feature_family_report_groups_stock_use_variants() -> None:
    scores = pd.DataFrame([
        _score_row(
            2000,
            score_name="stock_to_use_latest",
            detector_id="stage_level_z",
            source_feature="wasde_stock_to_use_latest",
            source_attribute="stock_to_use",
            source_transform="level",
            score_value=1.0,
        ),
        _score_row(
            2001,
            score_name="stock_to_use_estimate",
            detector_id="stage_level_z",
            source_feature="wasde_stock_to_use_estimate",
            source_attribute="stock_to_use",
            source_transform="level",
            score_value=2.0,
        ),
    ])

    report = build_redundant_feature_family_report(scores)

    assert report.iloc[0]["source_attribute"] == "stock_to_use"
    assert report.iloc[0]["score_name_count"] == 2


def test_composite_dominance_reports_top_attribute_share() -> None:
    scores = pd.DataFrame([
        _score_row(
            2000,
            score_name="stock_to_use",
            detector_id="stage_level_percentile",
            source_feature="wasde_stock_to_use_latest",
            source_attribute="stock_to_use",
            source_transform="level",
            score_value=0.95,
        ),
        _score_row(
            2000,
            score_name="exports",
            detector_id="revision_shock",
            source_feature="wasde_exports_mom_revision",
            source_attribute="exports",
            source_transform="mom_revision",
            score_value=-4.0,
        ),
    ])

    report = build_composite_dominance_report(scores)

    assert not report.empty
    assert report.iloc[0]["top_attribute"] == "stock_to_use"
    assert report.iloc[0]["top_attribute_contribution_share"] > 0.9
