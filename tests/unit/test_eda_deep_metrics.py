from __future__ import annotations

import numpy as np
import pandas as pd

from leviathan.eda.deep_metrics import eda_statistics_thresholds
from leviathan.eda.models import Exactness, TableSpec
from leviathan.eda.profiling import profile_frame


def _contract(columns: list[tuple[str, str]], **overrides):
    contract = {
        "table_name": "silver_deep_test",
        "layer": "silver",
        "domain": "production",
        "lifecycle_class": "source",
        "s3_root": "s3://leviathan-dev-shahem-001/silver/deep_test",
        "physical_columns": [
            {
                "name": name,
                "target_arrow_type": target_type,
                "nullable": True,
            }
            for name, target_type in columns
        ],
        "partition_keys": [],
        "natural_key": [columns[0][0]],
        "required_nonnull": [columns[0][0]],
        "value_columns": [],
        "min_nonnull_frac": None,
        "knowledge_date_col": None,
        "knowledge_semantics": None,
        "freshness_sla": {"cadence": "monthly"},
    }
    contract.update(overrides)
    return contract


def test_co_conditional_missingness_and_validity_are_bounded_and_summarized():
    frame = pd.DataFrame(
        {
            "row_id": range(8),
            "region": ["north"] * 4 + ["south"] * 4,
            "value": [None, None, 1.0, 2.0, 3.0, 0.0, np.inf, -9999.0],
            "aux": [None, None, 5.0, 6.0, 7.0, 8.0, 9.0, -1.0],
            "status": ["N/A", "ok", "ok", "ok", "ok", "ok", "ok", "ok"],
        }
    )
    spec = TableSpec.from_contract(
        _contract(
            [
                ("row_id", "int64"),
                ("region", "string"),
                ("value", "float64"),
                ("aux", "float64"),
                ("status", "string"),
            ],
            natural_key=["row_id"],
            required_nonnull=["row_id", "region"],
            value_columns=["value", "aux"],
            min_nonnull_frac=0.5,
        )
    )

    profile = profile_frame(frame, spec, exactness=Exactness.SAMPLED)

    pairs = profile.metric("missingness_validity", "co_missingness_pairs").value
    pair = next(item for item in pairs if {item["left"], item["right"]} == {"value", "aux"})
    assert pair["both_missing_count"] == 2
    assert pair["phi"] == 1.0
    conditional = profile.metric("missingness_validity", "conditional_missingness").value
    north_value = next(
        item
        for item in conditional
        if item["condition_column"] == "region"
        and item["condition_value"] == "north"
        and item["target_column"] == "value"
    )
    assert north_value["missing_rate"] == 0.5
    validity = profile.metric("missingness_validity", "validity_summary").value
    assert validity["infinite_count"] == 1
    assert validity["zero_count"] == 2  # value plus the numeric row_id key
    assert validity["numeric_sentinel_candidate_count"] == 1
    assert validity["string_sentinel_count"] == 1
    assert all(metric.exactness == Exactness.SAMPLED for _, _, metric in profile.iter_metrics())


def test_temporal_panel_seasonality_autocorrelation_and_drift_have_evidence():
    dates = pd.date_range("2022-01-01", periods=36, freq="MS")
    rows = []
    for region_index, region in enumerate(["a", "b", "c", "d"]):
        for index, date in enumerate(dates):
            if region == "d" and index == 5:
                continue
            rows.append(
                {
                    "region": region,
                    "date": date,
                    "value": float(10 * np.sin(2 * np.pi * index / 12) + index + region_index),
                }
            )
    frame = pd.DataFrame(rows)
    spec = TableSpec.from_contract(
        _contract(
            [("region", "string"), ("date", "timestamp[ns]"), ("value", "float64")],
            natural_key=["region", "date"],
            required_nonnull=["region", "date"],
            value_columns=["value"],
            min_nonnull_frac=0.5,
        )
    )

    profile = profile_frame(frame, spec)

    support = profile.metric("temporal_structure", "temporal_analysis_support").value
    assert support["panel_balance"]["status"] == "supported"
    assert support["cadence_and_gaps"]["status"] == "supported"
    assert support["seasonality"]["status"] == "supported"
    assert support["autocorrelation"]["status"] == "supported"
    assert support["distribution_drift"]["status"] == "supported"
    panel = profile.metric("temporal_structure", "panel_balance").value
    assert panel["entity_count"] == 4
    assert panel["complete_entity_count"] == 3
    cadence = profile.metric("temporal_structure", "cadence_and_gap_evidence").value
    assert cadence["inferred_cadence"] == "monthly"
    seasonal = profile.metric("temporal_structure", "seasonality_evidence").value
    assert seasonal[0]["n_timestamps"] == 36
    assert seasonal[0]["eta_squared_month_of_year"] is not None
    autocorrelation = profile.metric("temporal_structure", "autocorrelation_evidence").value
    assert autocorrelation[0]["n_effective_pairs"] == 35
    drift = profile.metric("temporal_structure", "distribution_drift_evidence").value
    assert drift[0]["early_n"] >= 20
    assert drift[0]["late_n"] >= 20


def test_progressive_curve_reports_decreases_without_silently_removing_them():
    frame = pd.DataFrame(
        {
            "state": ["a"] * 4 + ["b"] * 4,
            "year": [2024] * 8,
            "week_of_year": [1, 2, 3, 4] * 2,
            "pct_harvested": [10.0, 20.0, 5.0, 40.0, 1.0, 2.0, 3.0, 4.0],
        }
    )
    spec = TableSpec.from_contract(
        _contract(
            [
                ("state", "string"),
                ("year", "int64"),
                ("week_of_year", "int64"),
                ("pct_harvested", "float64"),
            ],
            natural_key=["state", "year", "week_of_year"],
            required_nonnull=["state", "year", "week_of_year"],
            value_columns=["pct_harvested"],
            min_nonnull_frac=0.5,
            freshness_sla={"cadence": "weekly"},
        )
    )

    profile = profile_frame(frame, spec)

    support = profile.metric("temporal_structure", "temporal_analysis_support").value
    assert support["progressive_curve"]["status"] == "supported"
    curves = profile.metric("temporal_structure", "progressive_curve_evidence").value
    assert curves[0]["decrease_or_reset_count"] == 1
    assert curves[0]["groups_with_decrease_or_reset"] == 1
    assert curves[0]["monotonicity_expected_by_name"] is True


def test_categorical_association_reports_effective_n_and_bias_corrected_cramers_v():
    frame = pd.DataFrame(
        {
            "row_id": range(40),
            "category_a": ["a"] * 20 + ["b"] * 20,
            "category_b": ["x"] * 20 + ["y"] * 20,
            "value": np.arange(40, dtype=float),
        }
    )
    spec = TableSpec.from_contract(
        _contract(
            [
                ("row_id", "int64"),
                ("category_a", "string"),
                ("category_b", "string"),
                ("value", "float64"),
            ],
            natural_key=["row_id"],
            required_nonnull=["row_id"],
            value_columns=["value"],
            min_nonnull_frac=0.5,
        )
    )

    profile = profile_frame(frame, spec)

    associations = profile.metric(
        "within_source_relationships", "categorical_associations"
    ).value
    pair = next(
        item
        for item in associations
        if {item["left"], item["right"]} == {"category_a", "category_b"}
    )
    assert pair["n"] == 40
    assert pair["cramers_v"] == 1.0
    assert pair["cramers_v_bias_corrected"] > 0.95


def test_vintage_revision_trajectory_and_release_lag_are_source_only():
    frame = pd.DataFrame(
        {
            "entity": ["a", "a", "b", "b"],
            "observation_date": ["2024-01-01"] * 4,
            "release_date": ["2024-01-15", "2024-01-30"] * 2,
            "estimate": [10.0, 12.0, 5.0, 5.0],
        }
    )
    spec = TableSpec.from_contract(
        _contract(
            [
                ("entity", "string"),
                ("observation_date", "date32[day]"),
                ("release_date", "date32[day]"),
                ("estimate", "float64"),
            ],
            natural_key=["release_date", "entity", "observation_date"],
            required_nonnull=["release_date", "entity", "observation_date"],
            value_columns=["estimate"],
            min_nonnull_frac=0.5,
            knowledge_date_col="release_date",
            knowledge_semantics="vintage",
            publication_lag_days=None,
        )
    )

    profile = profile_frame(frame, spec)

    support = profile.metric("pit_leakage", "pit_analysis_support").value
    assert support["revision_trajectories"]["status"] == "supported"
    assert support["release_lag"]["status"] == "supported"
    revisions = profile.metric("pit_leakage", "revision_trajectory_evidence").value
    assert revisions[0]["transition_count"] == 2
    assert revisions[0]["changed_transition_count"] == 1
    assert revisions[0]["changed_entity_count"] == 1
    lag = profile.metric("pit_leakage", "release_lag_evidence").value
    assert lag["observation_axis"] == "observation_date"
    assert lag["negative_lag_count"] == 0
    assert lag["lag_days_quantiles"]["0.5"] == 21.5


def test_unsupported_and_no_evidence_are_explicit_and_selection_is_bounded():
    data: dict[str, object] = {"row_id": range(40), "value": np.arange(40, dtype=float)}
    columns = [("row_id", "int64"), ("value", "float64")]
    for index in range(14):
        data[f"missing_{index:02d}"] = [
            None if row % (index + 2) == 0 else row for row in range(40)
        ]
        columns.append((f"missing_{index:02d}", "float64"))
    for index in range(8):
        data[f"category_{index:02d}"] = ["a" if row % 2 else "b" for row in range(40)]
        columns.append((f"category_{index:02d}", "string"))
    frame = pd.DataFrame(data)
    spec = TableSpec.from_contract(
        _contract(
            columns,
            natural_key=["row_id"],
            required_nonnull=["row_id"],
            value_columns=["value"],
            min_nonnull_frac=0.5,
        )
    )

    profile = profile_frame(frame, spec)

    pairs = profile.metric("missingness_validity", "co_missingness_pairs").value
    association_columns = profile.metric(
        "within_source_relationships", "categorical_association_columns"
    ).value
    temporal_support = profile.metric(
        "temporal_structure", "temporal_analysis_support"
    ).value
    pit_support = profile.metric("pit_leakage", "pit_analysis_support").value
    assert len(pairs) <= 66  # C(12, 2)
    assert len(association_columns) <= 6
    assert temporal_support["panel_balance"]["status"] == "unsupported"
    assert temporal_support["seasonality"]["status"] == "unsupported"
    assert pit_support["revision_trajectories"]["status"] == "unsupported"
    assert pit_support["release_lag"]["status"] == "unsupported"


def test_signal_diagnostics_use_only_governed_values_and_stable_group_axes():
    dates = pd.date_range("2022-01-01", periods=36, freq="MS")
    rows = []
    for region_index, region in enumerate(["north", "south"]):
        for index, date in enumerate(dates):
            signal = float(index + region_index + 5 * np.sin(2 * np.pi * index / 12))
            rows.append(
                {
                    "row_id": len(rows),
                    "region": region,
                    "date": date,
                    "ingest_date": "2025-01-01" if index < 18 else "2025-02-01",
                    "year": date.year,
                    "month": date.month,
                    "day": date.day,
                    "value_a": signal,
                    "value_b": signal * 2,
                }
            )
    frame = pd.DataFrame(rows)
    spec = TableSpec.from_contract(
        _contract(
            [
                ("row_id", "int64"),
                ("region", "string"),
                ("date", "timestamp[ns]"),
                ("ingest_date", "date32[day]"),
                ("year", "int64"),
                ("month", "int64"),
                ("day", "int64"),
                ("value_a", "float64"),
                ("value_b", "float64"),
            ],
            natural_key=["region", "date"],
            required_nonnull=["region", "date"],
            value_columns=["value_a", "value_b"],
            min_nonnull_frac=0.5,
            publication_lag_days=1,
        )
    )

    profile = profile_frame(frame, spec, exactness=Exactness.SAMPLED)

    heterogeneity = profile.metric("distributions", "group_heterogeneity").value
    assert {item["group_column"] for item in heterogeneity} == {"region"}
    assert {item["value_column"] for item in heterogeneity} == {"value_a", "value_b"}
    assert profile.metric(
        "within_source_relationships", "correlation_columns"
    ).value == ["value_a", "value_b"]
    assert {
        item["column"]
        for metric_name in (
            "autocorrelation_evidence",
            "distribution_drift_evidence",
            "regime_shift_evidence",
            "seasonality_evidence",
        )
        for item in profile.metric("temporal_structure", metric_name).value
    } == {"value_a", "value_b"}
    panel = profile.metric("temporal_structure", "panel_balance").value
    panel_support = profile.metric(
        "temporal_structure", "temporal_analysis_support"
    ).value["panel_balance"]
    assert panel["scope"] == "sampled_analysis_frame_only"
    assert panel["full_source_balance_claimed"] is False
    assert "not a full-source panel-balance claim" in panel["sampling_artifact_caveat"]
    assert panel_support["full_source_balance_claimed"] is False


def test_progressive_curve_preserves_entity_season_and_knowledge_axes():
    rows = []
    for as_of_date in ("2024-06-01", "2024-06-08"):
        for commodity_id in (101, 202):
            for period, value in enumerate((1.0, 3.0, 6.0), start=1):
                rows.append(
                    {
                        "as_of_date": as_of_date,
                        "commodity_id": commodity_id,
                        "market_year": 2024,
                        "period_in_season": period,
                        "cumulative_value": value + commodity_id,
                    }
                )
    frame = pd.DataFrame(rows)
    spec = TableSpec.from_contract(
        _contract(
            [
                ("as_of_date", "date32[day]"),
                ("commodity_id", "int64"),
                ("market_year", "int64"),
                ("period_in_season", "int64"),
                ("cumulative_value", "float64"),
            ],
            table_name="silver_esr_compact_like",
            natural_key=[
                "as_of_date",
                "commodity_id",
                "market_year",
                "period_in_season",
            ],
            required_nonnull=[
                "as_of_date",
                "commodity_id",
                "market_year",
                "period_in_season",
            ],
            value_columns=["cumulative_value"],
            min_nonnull_frac=0.5,
            knowledge_date_col="as_of_date",
            knowledge_semantics="vintage",
        )
    )

    profile = profile_frame(frame, spec)

    curves = profile.metric("temporal_structure", "progressive_curve_evidence").value
    assert len(curves) == 1
    curve = curves[0]
    assert curve["column"] == "cumulative_value"
    assert curve["sequence_column"] == "period_in_season"
    assert curve["group_columns"] == ["as_of_date", "commodity_id", "market_year"]
    assert curve["ambiguous_duplicate_sequence_rows_excluded"] == 0
    assert curve["transition_count"] == 8
    assert curve["decrease_or_reset_count"] == 0


def test_progressive_curve_excludes_observation_date_from_curve_identity():
    frame = pd.DataFrame(
        {
            "commodity": ["corn"] * 3,
            "state": ["iowa"] * 3,
            "year": [2024] * 3,
            "date": pd.to_datetime(["2024-05-01", "2024-05-08", "2024-05-15"]),
            "week_of_year": [18, 19, 20],
            "pct_harvested": [1.0, 3.0, 8.0],
        }
    )
    spec = TableSpec.from_contract(
        _contract(
            [
                ("commodity", "string"),
                ("state", "string"),
                ("year", "int64"),
                ("date", "date32[day]"),
                ("week_of_year", "int64"),
                ("pct_harvested", "float64"),
            ],
            natural_key=["commodity", "state", "year", "date"],
            required_nonnull=["commodity", "state", "year", "date"],
            value_columns=["week_of_year", "pct_harvested"],
            min_nonnull_frac=0.5,
            publication_lag_days=1,
        )
    )

    profile = profile_frame(frame, spec)

    curve = profile.metric("temporal_structure", "progressive_curve_evidence").value[0]
    assert curve["column"] == "pct_harvested"
    assert curve["sequence_column"] == "week_of_year"
    assert curve["group_columns"] == ["commodity", "state", "year"]
    assert curve["transition_count"] == 2


def test_repository_statistics_thresholds_are_authoritative():
    thresholds = eda_statistics_thresholds()

    assert thresholds["min_trend_points"] == 8
    assert thresholds["min_scatter_points"] == 12
    assert thresholds["robust_outlier_iqr_multiplier"] == 1.5
    assert thresholds["high_correlation_abs"] == 0.85
    assert thresholds["recent_window_fraction"] == 0.2
    assert thresholds["categorical_rare_rate"] == 0.01


def test_arithmetic_identity_mismatch_drives_a_high_severity_work_order():
    frame = pd.DataFrame(
        {
            "row_id": [1, 2, 3],
            "production_mt": [20.0, 30.0, 99.0],
            "area_harvested_ha": [10.0, 10.0, 10.0],
            "yield_t_ha": [2.0, 3.0, 4.0],
        }
    )
    spec = TableSpec.from_contract(
        _contract(
            [
                ("row_id", "int64"),
                ("production_mt", "float64"),
                ("area_harvested_ha", "float64"),
                ("yield_t_ha", "float64"),
            ],
            natural_key=["row_id"],
            required_nonnull=["row_id"],
            value_columns=["production_mt", "area_harvested_ha", "yield_t_ha"],
            min_nonnull_frac=0.5,
            publication_lag_days=0,
        )
    )

    profile = profile_frame(frame, spec)

    finding = next(item for item in profile.findings if item.code == "EDA-INTEGRITY-001")
    identity = profile.metric(
        "within_source_relationships", "accounting_relationships"
    ).value[0]
    assert identity["mismatch_rows"] == 1
    assert identity["mismatch_rate"] == 1 / 3
    assert finding.severity.value == "high"
    assert profile.disposition.value == "needs_contract_or_data_fix"


def test_progressive_sequence_ambiguity_drives_a_work_order():
    frame = pd.DataFrame(
        {
            "state": ["a", "a", "a", "a"],
            "year": [2024] * 4,
            "week_of_year": [1, 2, 2, 3],
            "pct_harvested": [10.0, 20.0, 21.0, 30.0],
        }
    )
    spec = TableSpec.from_contract(
        _contract(
            [
                ("state", "string"),
                ("year", "int64"),
                ("week_of_year", "int64"),
                ("pct_harvested", "float64"),
            ],
            natural_key=["state", "year", "week_of_year"],
            required_nonnull=["state", "year", "week_of_year"],
            value_columns=["pct_harvested"],
            min_nonnull_frac=0.5,
            publication_lag_days=0,
        )
    )

    profile = profile_frame(frame, spec)

    curve = profile.metric("temporal_structure", "progressive_curve_evidence").value[0]
    assert curve["ambiguous_duplicate_sequence_rows_excluded"] == 2
    assert any(item.code == "EDA-TEMPORAL-001" for item in profile.findings)
    assert profile.disposition.value == "needs_contract_or_data_fix"


def test_negative_publication_lag_drives_a_pit_work_order():
    frame = pd.DataFrame(
        {
            "entity": ["a", "b", "c"],
            "observation_date": ["2024-01-10"] * 3,
            "release_date": ["2024-01-09", "2024-01-11", "2024-01-12"],
            "estimate": [1.0, 2.0, 3.0],
        }
    )
    spec = TableSpec.from_contract(
        _contract(
            [
                ("entity", "string"),
                ("observation_date", "date32[day]"),
                ("release_date", "date32[day]"),
                ("estimate", "float64"),
            ],
            natural_key=["release_date", "entity", "observation_date"],
            required_nonnull=["release_date", "entity", "observation_date"],
            value_columns=["estimate"],
            min_nonnull_frac=0.5,
            knowledge_date_col="release_date",
            knowledge_semantics="vintage",
        )
    )

    profile = profile_frame(frame, spec)

    lag = profile.metric("pit_leakage", "release_lag_evidence").value
    assert lag["negative_lag_count"] == 1
    assert any(item.code == "EDA-PIT-003" for item in profile.findings)
    assert profile.disposition.value == "needs_contract_or_data_fix"


def test_wasde_release_before_marketing_year_end_is_forecast_lead_not_pit_failure():
    frame = pd.DataFrame(
        {
            "entity": ["corn", "wheat"],
            "marketing_year_end_date": ["2026-08-31", "2026-05-31"],
            "release_date": ["2025-06-12", "2025-07-11"],
            "estimate": [100.0, 200.0],
        }
    )
    spec = TableSpec.from_contract(
        _contract(
            [
                ("entity", "string"),
                ("marketing_year_end_date", "date32[day]"),
                ("release_date", "date32[day]"),
                ("estimate", "float64"),
            ],
            table_name="silver_wasde",
            natural_key=["release_date", "entity", "marketing_year_end_date"],
            required_nonnull=["release_date", "entity", "marketing_year_end_date"],
            value_columns=["estimate"],
            min_nonnull_frac=0.5,
            knowledge_date_col="release_date",
            knowledge_semantics="vintage",
        )
    )

    profile = profile_frame(frame, spec)

    lag = profile.metric("pit_leakage", "release_lag_evidence").value
    assert lag["negative_lag_count"] == 2
    assert lag["negative_lag_is_pit_contradiction"] is False
    assert lag["timing_semantics"] == "forecast_horizon_offset"
    assert "release_date <= feature cutoff" in lag["interpretation"]
    assert profile.metric("pit_leakage", "knowledge_time_readiness").value["status"] == "ready"
    assert not any(item.code == "EDA-PIT-003" for item in profile.findings)
