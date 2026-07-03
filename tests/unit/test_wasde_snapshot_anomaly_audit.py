from __future__ import annotations

import pandas as pd

from leviathan.model_datasets.wasde_snapshot_anomaly_audit import (
    audit_wasde_snapshot_anomaly_inputs,
    build_event_distribution_audit,
    build_feature_coverage_audit,
    build_prior_history_viability_audit,
    build_snapshot_key_audit,
    feature_columns_for_anomaly_audit,
)


def _snapshot_matrix(
    *,
    years: range = range(2000, 2015),
    origins: tuple[str, ...] = ("united_states", "brazil"),
    target_keys: tuple[str, ...] = ("psd_stock_to_use_anomaly_pct",),
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    releases = [
        ("05-12", "preseason"),
        ("07-12", "early_season"),
        ("09-12", "midseason"),
    ]
    for target_key in target_keys:
        for origin_idx, origin in enumerate(origins):
            for year in years:
                event = year in {2003, 2008, 2012}
                for seq, (month_day, stage) in enumerate(releases, start=1):
                    rows.append({
                        "source_dataset_version": "unit_source",
                        "dataset_key": "corn_wasde_snapshot_solo",
                        "contract_key": "corn_cbot",
                        "commodity": "corn_cbot",
                        "commodity_group": "grains",
                        "origin": origin,
                        "origin_key": origin,
                        "target_market_year": year,
                        "crop_year": year,
                        "target_key": target_key,
                        "target_family": "psd_balance_sheet_anomaly",
                        "target_attribute": "stock_to_use",
                        "target_source": "psd",
                        "target_value": -0.2 if event else 0.1,
                        "target_event_label": event,
                        "target_event_threshold": -0.1,
                        "target_event_threshold_type": "fixed_10pct",
                        "target_event_direction": "lower_is_stress",
                        "as_of_date": f"{year}-{month_day}",
                        "snapshot_stage": stage,
                        "snapshot_month_code": int(month_day[:2]),
                        "sample_weight": 1 / len(releases),
                        "cv_group": f"corn_cbot|{origin}|{year}|{target_key}",
                        "cv_time": year,
                        "is_trainable": year >= 2002,
                        "wasde_commodity": "corn",
                        "wasde_origin": origin,
                        "wasde_stock_to_use_latest": 0.15 + origin_idx + year * 0.001 - seq * 0.01,
                        "wasde_stock_to_use_mom_revision": -0.01 * seq,
                        "wasde_ending_stocks_latest": 50.0 + year * 0.1 - seq,
                        "wasde_exports_mom_revision": 0.5 * seq,
                        "wasde_all_missing_latest": None,
                        "wasde_constant_latest": 1.0,
                        "faostat_production_yoy": 0.02,
                    })
    return pd.DataFrame(rows)


def test_audit_detects_duplicate_snapshot_target_keys() -> None:
    matrix = _snapshot_matrix()
    duplicated = pd.concat([matrix, matrix.iloc[[0]]], ignore_index=True)

    audit = build_snapshot_key_audit(duplicated)

    assert audit["duplicate_natural_key_count"] == 1
    assert audit["missing_id_columns"] == []


def test_audit_counts_independent_annual_groups() -> None:
    matrix = _snapshot_matrix()

    audit = build_snapshot_key_audit(matrix)

    assert audit["annual_group_count"] == 30
    assert audit["trainable_annual_group_count"] == 26
    assert audit["snapshot_count"] == 45


def test_audit_summarizes_feature_coverage_for_wasde_columns() -> None:
    matrix = _snapshot_matrix()

    features = feature_columns_for_anomaly_audit(matrix)
    coverage = build_feature_coverage_audit(matrix)
    by_feature = coverage.set_index("feature")

    assert "wasde_stock_to_use_latest" in features
    assert "faostat_production_yoy" not in features
    assert by_feature.loc["wasde_stock_to_use_latest", "quality_bucket"] == "dense"
    assert by_feature.loc["wasde_all_missing_latest", "quality_bucket"] == "all_missing"
    assert by_feature.loc["wasde_constant_latest", "quality_bucket"] == "constant"


def test_audit_summarizes_event_distribution_by_annual_group() -> None:
    matrix = _snapshot_matrix(years=range(2000, 2005))

    events = build_event_distribution_audit(matrix)
    annual = events.loc[events["level"] == "annual_group_by_target"].iloc[0]
    by_origin = events.loc[events["level"] == "annual_group_by_target_origin"]

    assert annual["trainable_row_count"] == 6
    assert annual["event_count"] == 2
    assert set(by_origin["origin_key"]) == {"united_states", "brazil"}


def test_audit_flags_insufficient_prior_history() -> None:
    matrix = _snapshot_matrix(years=range(2000, 2004), origins=("united_states",))

    prior = build_prior_history_viability_audit(matrix, min_prior_observations=10)

    assert not prior.empty
    assert prior["share_with_min_prior_observations"].max() == 0.0


def test_full_audit_blocks_missing_required_columns() -> None:
    matrix = _snapshot_matrix().drop(columns=["target_event_label"])

    result = audit_wasde_snapshot_anomaly_inputs(
        matrix,
        min_independent_groups=1,
        min_event_groups=1,
        min_prior_observations=1,
    )

    assert result.report["status"] == "blocked"
    assert "missing_required_target_columns" in result.report["blockers"]


def test_full_audit_can_go_with_valid_fixture() -> None:
    matrix = _snapshot_matrix(years=range(1990, 2020))

    result = audit_wasde_snapshot_anomaly_inputs(
        matrix,
        min_independent_groups=30,
        min_event_groups=5,
        min_prior_observations=10,
    )

    assert result.report["status"] in {"go", "go_with_warnings"}
    assert result.report["feature_coverage"]["usable_feature_count"] >= 4
    assert result.report["event_distribution"]["annual_event_counts_by_target"][
        "psd_stock_to_use_anomaly_pct"
    ] >= 5
