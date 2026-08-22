from __future__ import annotations

import json

import pandas as pd

from leviathan.eda.models import Exactness, ReadinessDisposition, TableSpec
from leviathan.eda.profiling import _required_null_message, profile_frame
from leviathan.silver.registry import load_registry


def _contract(**overrides):
    contract = {
        "table_name": "silver_test_panel",
        "layer": "silver",
        "domain": "balance_sheet",
        "lifecycle_class": "source",
        "s3_root": "s3://leviathan-dev-shahem-001/silver/test_panel",
        "physical_columns": [
            {"name": "commodity", "target_arrow_type": "string", "nullable": False},
            {"name": "region", "target_arrow_type": "string", "nullable": False},
            {"name": "date", "target_arrow_type": "date32[day]", "nullable": False},
            {"name": "release_date", "target_arrow_type": "string", "nullable": False},
            {"name": "variable", "target_arrow_type": "string", "nullable": False},
            {"name": "value", "target_arrow_type": "float64", "nullable": True},
            {"name": "aux", "target_arrow_type": "float64", "nullable": True},
        ],
        "partition_keys": [],
        "natural_key": ["release_date", "commodity", "region", "date", "variable"],
        "required_nonnull": ["release_date", "commodity", "region", "date", "variable"],
        "value_columns": ["value"],
        "min_nonnull_frac": 0.5,
        "knowledge_date_col": "release_date",
        "knowledge_semantics": "vintage",
        "vintage_retention": "per-vintage",
        "freshness_sla": {"cadence": "monthly"},
        "coverage_axis": "commodity x region x date x variable",
    }
    contract.update(overrides)
    return contract


def _frame(duplicate: bool = False) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=12, freq="MS")
    frame = pd.DataFrame(
        {
            "commodity": ["Corn", " corn "] + ["Corn"] * 10,
            "region": ["US"] * 12,
            "date": dates.astype(str),
            "release_date": (dates + pd.Timedelta(days=15)).astype(str),
            "variable": ["production"] * 12,
            "value": [0.0, 1.0, None, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 100.0],
            "aux": [float(i * 2) for i in range(12)],
        }
    )
    if duplicate:
        frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    return frame


def test_profile_covers_quality_temporal_relationship_and_pit_sections():
    spec = TableSpec.from_contract(_contract())
    profile = profile_frame(_frame(), spec)

    assert profile.disposition == ReadinessDisposition.READY_FOR_FEATURE_IDEATION
    assert set(profile.sections) == {
        "schema_contract",
        "grain_integrity",
        "missingness_validity",
        "distributions",
        "entity_vocabulary_coverage",
        "temporal_structure",
        "within_source_relationships",
        "pit_leakage",
        "join_readiness",
        "feature_engineering_readiness",
    }
    assert profile.metric("schema_contract", "row_count").value == 12
    assert profile.metric("grain_integrity", "duplicate_key_rows").value == 0
    missing = profile.metric("missingness_validity", "column_missingness").value
    assert missing["value"]["null_count"] == 1
    distributions = profile.metric("distributions", "numeric_distributions").value
    assert set(distributions) == {"value"}
    assert distributions["value"]["max"] == 100.0
    vocab = profile.metric("entity_vocabulary_coverage", "vocabularies").value
    assert "corn" in vocab["commodity"]["normalisation_collisions"]
    temporal = profile.metric("temporal_structure", "temporal_columns").value
    assert temporal["date"]["distinct_timestamp_count"] == 12
    correlation_columns = profile.metric(
        "within_source_relationships", "correlation_columns"
    ).value
    pairs = profile.metric("within_source_relationships", "correlation_pairs").value
    assert correlation_columns == ["value"]
    assert pairs == []  # aux is physical but is not a governed value column
    assert profile.metric("pit_leakage", "knowledge_vintage_count").value == 12
    assert all(metric.exactness == Exactness.EXACT for _, _, metric in profile.iter_metrics())


def test_distributions_exclude_numeric_identifiers_calendar_and_ungoverned_columns():
    frame = _frame().assign(
        commodity_id=1,
        country_id=840,
        row_id=range(12),
        year=2024,
        month=range(1, 13),
    )

    profile = profile_frame(frame, TableSpec.from_contract(_contract()))

    distributions = profile.metric("distributions", "numeric_distributions").value
    constants = profile.metric("distributions", "constant_numeric_columns").value
    excluded = profile.metric(
        "distributions", "excluded_numeric_identifier_time_columns"
    ).value
    excluded_non_measures = profile.metric(
        "distributions", "excluded_numeric_non_measure_columns"
    ).value
    assert set(distributions) == {"value"}
    assert constants == []
    assert set(excluded) == {"commodity_id", "country_id", "month", "row_id", "year"}
    assert set(excluded_non_measures) == {
        "aux",
        "commodity_id",
        "country_id",
        "month",
        "row_id",
        "year",
    }


def test_duplicate_key_is_interpreted_as_feature_readiness_risk():
    profile = profile_frame(_frame(duplicate=True), TableSpec.from_contract(_contract()))

    assert profile.disposition == ReadinessDisposition.NEEDS_CONTRACT_OR_DATA_FIX
    assert profile.metric("grain_integrity", "duplicate_key_rows").value == 2
    assert any(finding.code == "EDA-GRAIN-001" for finding in profile.findings)


def test_required_null_message_never_rounds_tiny_blocker_to_100_percent_complete():
    message = _required_null_message(6_992_396, 6_992_403)

    assert message == (
        "7 of 6,992,403 rows (0.000100%) contain at least one null required field."
    )
    assert "100.00%" not in message


def test_contract_incomplete_table_is_blocked_but_has_inferred_grain_evidence():
    contract = _contract(natural_key=[], value_columns=[], min_nonnull_frac=None)
    profile = profile_frame(_frame(), TableSpec.from_contract(contract), exactness=Exactness.SAMPLED)

    assert profile.disposition == ReadinessDisposition.BLOCKED
    assert profile.metric("grain_integrity", "inferred_candidate_key").value
    assert "registry natural_key is incomplete" in profile.blockers
    assert "registry value_columns is incomplete" in profile.blockers
    assert all(metric.exactness == Exactness.SAMPLED for _, _, metric in profile.iter_metrics())


def test_model_predictions_is_profiled_but_excluded_from_feature_plane():
    contract = load_registry().table("silver_model_predictions")
    spec = TableSpec.from_contract(contract)
    frame = pd.DataFrame(
        {
            "model_family": ["xgb"],
            "prediction_date": ["2026-01-01"],
            "y_actual": [1.0],
            "y_pred": [0.8],
            "target": ["yield"],
        }
    )

    profile = profile_frame(frame, spec)

    assert profile.disposition == ReadinessDisposition.EXCLUDED_LEAKAGE
    assert profile.metric("pit_leakage", "feature_eligible_source").value is False
    assert any(finding.code == "EDA-LEAK-001" for finding in profile.findings)
    assert profile.metric("distributions", "numeric_distributions").value == {}
    assert profile.metric("distributions", "group_heterogeneity").value == []
    assert profile.metric(
        "within_source_relationships", "correlation_columns"
    ).value == []
    assert profile.metric("within_source_relationships", "correlation_pairs").value == []
    assert profile.metric("within_source_relationships", "pearson_matrix").value == {}
    assert profile.metric("within_source_relationships", "spearman_matrix").value == {}
    assert profile.metric(
        "within_source_relationships", "categorical_associations"
    ).value == []
    temporal_signal_metrics = (
        "autocorrelation_evidence",
        "distribution_drift_evidence",
        "progressive_curve_evidence",
        "regime_shift_evidence",
        "seasonality_evidence",
    )
    assert all(
        profile.metric("temporal_structure", name).value == []
        for name in temporal_signal_metrics
    )
    vocabularies = profile.metric(
        "entity_vocabulary_coverage", "vocabularies"
    ).value
    quarantined = profile.metric(
        "entity_vocabulary_coverage", "quarantined_output_value_columns"
    ).value
    prohibited_payload = {
        "distributions": profile.metric(
            "distributions", "numeric_distributions"
        ).value,
        "relationships": profile.sections["within_source_relationships"].to_dict(),
        "vocabularies": vocabularies,
    }
    assert "target" not in vocabularies
    assert {"target", "y_actual", "y_pred"} <= set(quarantined)
    assert "yield" not in json.dumps(prohibited_payload)


def test_esr_pre_boundary_rows_are_not_declared_genuine_pit_history():
    contract = _contract(
        table_name="silver_esr_compact",
        s3_root="s3://leviathan-dev-shahem-001/silver/esr_compact",
        knowledge_date_col="release_date",
    )
    frame = _frame()
    frame.loc[0, "release_date"] = "2026-05-01"
    frame.loc[1, "release_date"] = "2026-06-01"

    profile = profile_frame(frame, TableSpec.from_contract(contract))
    boundary = profile.metric("pit_leakage", "synthetic_backfill_boundary").value

    assert boundary["treated_as_genuine_pit"] is False
    assert boundary["pre_boundary_row_count"] >= 1


def test_missing_knowledge_time_and_publication_lag_emits_actionable_work_order():
    contract = _contract(
        knowledge_date_col=None,
        knowledge_semantics=None,
        publication_lag_days=None,
        natural_key=["commodity", "region", "date", "variable"],
        required_nonnull=["commodity", "region", "date", "variable"],
    )

    profile = profile_frame(_frame(), TableSpec.from_contract(contract))

    readiness = profile.metric("pit_leakage", "knowledge_time_readiness").value
    finding = next(item for item in profile.findings if item.code == "EDA-PIT-002")
    assert profile.disposition == ReadinessDisposition.NEEDS_CONTRACT_OR_DATA_FIX
    assert readiness["status"] == "needs_contract_or_data_fix"
    assert readiness["basis"] is None
    assert finding.severity.value == "high"
    assert "publication lag" in finding.remediation


def test_governed_publication_lag_is_a_valid_knowledge_time_fallback():
    contract = _contract(
        knowledge_date_col=None,
        knowledge_semantics=None,
        publication_lag_days=7,
        natural_key=["commodity", "region", "date", "variable"],
        required_nonnull=["commodity", "region", "date", "variable"],
    )

    profile = profile_frame(_frame(), TableSpec.from_contract(contract))

    readiness = profile.metric("pit_leakage", "knowledge_time_readiness").value
    assert profile.disposition == ReadinessDisposition.READY_FOR_FEATURE_IDEATION
    assert readiness["status"] == "ready"
    assert readiness["basis"] == "publication_lag"
    assert all(item.code != "EDA-PIT-002" for item in profile.findings)


def test_publication_lag_requires_a_parseable_observation_axis():
    contract = _contract(
        knowledge_date_col=None,
        knowledge_semantics=None,
        publication_lag_days=7,
        natural_key=["commodity", "region", "variable"],
        required_nonnull=["commodity", "region", "variable"],
    )
    frame = _frame().drop(columns=["date", "release_date"])

    profile = profile_frame(frame, TableSpec.from_contract(contract))

    readiness = profile.metric("pit_leakage", "knowledge_time_readiness").value
    assert profile.metric("temporal_structure", "temporal_observation_axis").value is None
    assert profile.disposition == ReadinessDisposition.NEEDS_CONTRACT_OR_DATA_FIX
    assert readiness["status"] == "needs_contract_or_data_fix"
    assert readiness["basis"] is None
    assert readiness["observation_axis"] is None
    assert "no parseable non-knowledge observation-time axis" in readiness["reason"]
    assert any(item.code == "EDA-PIT-002" for item in profile.findings)


def test_declared_knowledge_time_must_be_present_and_fully_parseable():
    contract = _contract(
        publication_lag_days=7,
        natural_key=["commodity", "region", "date", "variable"],
        required_nonnull=["commodity", "region", "date", "variable"],
    )
    frames = [
        _frame().drop(columns=["release_date"]),
        _frame().assign(release_date="not-a-date"),
    ]

    for frame in frames:
        profile = profile_frame(frame, TableSpec.from_contract(contract))
        readiness = profile.metric("pit_leakage", "knowledge_time_readiness").value
        assert profile.disposition == ReadinessDisposition.NEEDS_CONTRACT_OR_DATA_FIX
        assert readiness["status"] == "needs_contract_or_data_fix"
        assert readiness["basis"] is None
        assert any(item.code == "EDA-PIT-002" for item in profile.findings)
