from __future__ import annotations

from dataclasses import replace

import pandas as pd

from leviathan.eda.candidates import (
    generate_feature_candidates,
    validate_feature_candidates,
)
from leviathan.eda.models import (
    CandidateClassification,
    CandidateReadiness,
    ReadinessDisposition,
    TableSpec,
)
from leviathan.eda.profiling import profile_frame
from leviathan.silver.registry import load_registry


def _contract(**overrides):
    contract = {
        "table_name": "silver_test_source",
        "layer": "silver",
        "domain": "prices",
        "lifecycle_class": "source",
        "s3_root": "s3://leviathan-dev-shahem-001/silver/test_source",
        "physical_columns": [
            {"name": "commodity", "target_arrow_type": "string", "nullable": False},
            {"name": "region", "target_arrow_type": "string", "nullable": False},
            {"name": "date", "target_arrow_type": "date32[day]", "nullable": False},
            {"name": "value", "target_arrow_type": "float64", "nullable": True},
        ],
        "partition_keys": [],
        "natural_key": ["commodity", "region", "date"],
        "required_nonnull": ["commodity", "region", "date"],
        "value_columns": ["value"],
        "min_nonnull_frac": 0.5,
        "knowledge_date_col": None,
        "knowledge_semantics": "data_date",
        "freshness_sla": {"cadence": "monthly"},
    }
    contract.update(overrides)
    return contract


def _frame():
    return pd.DataFrame(
        {
            "commodity": ["corn"] * 24,
            "region": ["US"] * 24,
            "date": pd.date_range("2024-01-01", periods=24, freq="MS").astype(str),
            "value": [None, 0.0] + [float(2 ** i) for i in range(2, 24)],
        }
    )


def test_candidate_generation_is_source_only_evidence_backed_and_deterministic():
    spec = TableSpec.from_contract(_contract())
    frame = _frame()
    profile = profile_frame(frame, spec)

    first = generate_feature_candidates(frame, profile, spec)
    second = generate_feature_candidates(frame, profile, spec)

    assert [candidate.to_dict() for candidate in first] == [candidate.to_dict() for candidate in second]
    assert len({candidate.candidate_id for candidate in first}) == len(first)
    assert any(candidate.transformation["operation"] == "identity" for candidate in first)
    assert any(candidate.transformation["operation"] == "lag" for candidate in first)
    assert any(candidate.transformation["operation"] == "log1p" for candidate in first)
    assert all(candidate.visibility_class == "review_required" for candidate in first)
    assert all(
        candidate.readiness == CandidateReadiness.NEEDS_CONTRACT_OR_DATA_FIX
        for candidate in first
    )
    assert all(
        "derive availability" in candidate.knowledge_time_rule
        for candidate in first
    )
    assert validate_feature_candidates(first, spec) == ()


def test_temporal_candidates_group_only_by_stable_entity_axes_and_require_governed_pit():
    contract = _contract(
        physical_columns=[
            *_contract()["physical_columns"],
            {"name": "year", "target_arrow_type": "int64", "nullable": False},
            {"name": "month", "target_arrow_type": "int64", "nullable": False},
        ],
        natural_key=["commodity", "region", "date", "year", "month"],
        publication_lag_days=2,
    )
    spec = TableSpec.from_contract(contract)
    frame = _frame().assign(
        year=lambda value: pd.to_datetime(value["date"]).dt.year,
        month=lambda value: pd.to_datetime(value["date"]).dt.month,
    )
    profile = profile_frame(frame, spec)

    candidates = generate_feature_candidates(
        frame,
        profile,
        spec,
        overlay={"table_name": spec.table_name, "units": {"value": "USD/t"}},
    )
    temporal = [
        candidate
        for candidate in candidates
        if candidate.transformation["operation"] in {"lag", "difference", "rolling_mean"}
    ]

    assert temporal
    assert all(
        candidate.transformation["group_by"] == ["commodity", "region"]
        for candidate in temporal
    )
    assert all(candidate.readiness == CandidateReadiness.READY_FOR_PROTOTYPE for candidate in temporal)
    assert all("date + 2 day" in candidate.knowledge_time_rule for candidate in temporal)


def test_weather_adapter_emits_crop_stage_climatology_and_threshold_proposals_only():
    contract = _contract(
        table_name="silver_chirps",
        domain="weather",
        s3_root="s3://leviathan-dev-shahem-001/silver/chirps",
        physical_columns=[
            *_contract()["physical_columns"],
            {"name": "variable", "target_arrow_type": "string", "nullable": False},
            {"name": "year", "target_arrow_type": "int64", "nullable": False},
            {"name": "month", "target_arrow_type": "int64", "nullable": False},
        ],
        natural_key=["commodity", "region", "variable", "date", "year", "month"],
    )
    spec = TableSpec.from_contract(contract)
    frame = _frame().assign(
        variable="precipitation",
        year=lambda value: pd.to_datetime(value["date"]).dt.year,
        month=lambda value: pd.to_datetime(value["date"]).dt.month,
    )
    profile = profile_frame(frame, spec)

    candidates = generate_feature_candidates(
        frame,
        profile,
        spec,
        overlay={
            "table_name": spec.table_name,
            "adapters": ["weather", "long_metric"],
            "units": {"value": "millimetres"},
        },
    )
    operations = {candidate.transformation["operation"] for candidate in candidates}

    assert {
        "crop_stage_aggregate",
        "past_only_climatology_anomaly",
        "agronomic_threshold_duration",
    }.issubset(operations)
    assert not {"lag", "difference", "rolling_mean"}.intersection(operations)
    adapter_candidates = [
        candidate
        for candidate in candidates
        if candidate.transformation["operation"] in operations
        and candidate.computation_primitive
        in {
            "crop_stage_aggregate",
            "past_only_climatology_anomaly",
            "agronomic_threshold_duration",
        }
    ]
    assert all(
        candidate.transformation["group_by"]
        == ["commodity", "region", "variable"]
        for candidate in adapter_candidates
    )
    assert all(
        candidate.readiness == CandidateReadiness.NEEDS_CONTRACT_OR_DATA_FIX
        for candidate in adapter_candidates
    )


def test_vintage_adapter_compares_releases_within_outcome_season():
    contract = _contract(
        table_name="silver_wasde",
        domain="balance_sheet",
        s3_root="s3://leviathan-dev-shahem-001/silver/wasde",
        physical_columns=[
            {"name": "commodity", "target_arrow_type": "string", "nullable": False},
            {"name": "region", "target_arrow_type": "string", "nullable": False},
            {"name": "release_date", "target_arrow_type": "date32[day]", "nullable": False},
            {"name": "marketing_year", "target_arrow_type": "string", "nullable": False},
            {"name": "attribute", "target_arrow_type": "string", "nullable": False},
            {"name": "unit", "target_arrow_type": "string", "nullable": False},
            {"name": "estimate_number", "target_arrow_type": "int64", "nullable": False},
            {"name": "value", "target_arrow_type": "float64", "nullable": True},
        ],
        natural_key=[
            "release_date",
            "commodity",
            "region",
            "marketing_year",
            "attribute",
            "unit",
            "estimate_number",
        ],
        required_nonnull=[
            "release_date",
            "commodity",
            "region",
            "marketing_year",
            "attribute",
            "unit",
            "estimate_number",
        ],
        knowledge_date_col="release_date",
        knowledge_semantics="vintage",
    )
    spec = TableSpec.from_contract(contract)
    frame = pd.DataFrame(
        {
            "commodity": ["corn"] * 12,
            "region": ["US"] * 12,
            "release_date": pd.date_range("2024-01-01", periods=12, freq="MS").astype(str),
            "marketing_year": ["2024/25"] * 12,
            "attribute": ["production"] * 12,
            "unit": ["million tonnes"] * 12,
            "estimate_number": list(range(1, 13)),
            "value": [float(value) for value in range(12)],
        }
    )
    profile = profile_frame(frame, spec)

    candidates = generate_feature_candidates(
        frame,
        profile,
        spec,
        overlay={"table_name": spec.table_name, "adapters": ["vintage_revision"]},
    )
    revision = next(
        candidate
        for candidate in candidates
        if candidate.transformation["operation"] == "vintage_difference"
    )

    assert revision.transformation["order_by"] == "release_date"
    assert revision.transformation["group_by"] == [
        "commodity",
        "region",
        "marketing_year",
        "attribute",
        "unit",
    ]
    assert not any(
        candidate.transformation["operation"] in {"lag", "rolling_mean"}
        for candidate in candidates
    )


def test_production_temporal_candidates_keep_row_level_unit_in_grouping() -> None:
    contract = _contract(
        table_name="silver_production",
        physical_columns=[
            *_contract()["physical_columns"],
            {"name": "unit", "target_arrow_type": "string", "nullable": False},
        ],
        natural_key=["commodity", "region", "unit", "date"],
        required_nonnull=["commodity", "region", "unit", "date"],
        publication_lag_days=0,
    )
    spec = TableSpec.from_contract(contract)
    frame = _frame().assign(unit="metric tonnes")
    profile = profile_frame(frame, spec)

    candidates = generate_feature_candidates(frame, profile, spec)
    temporal = [
        candidate
        for candidate in candidates
        if candidate.transformation["operation"] in {"difference", "lag", "rolling_mean"}
    ]

    assert temporal
    assert all(
        candidate.transformation["group_by"] == ["commodity", "region", "unit"]
        for candidate in temporal
    )


def test_candidate_validation_rejects_columns_outside_registry_contract():
    spec = TableSpec.from_contract(_contract())
    frame = _frame()
    profile = profile_frame(frame, spec)
    candidate = generate_feature_candidates(frame, profile, spec)[0]

    errors = validate_feature_candidates(
        [replace(candidate, source_columns=("legacy_target",))], spec
    )

    assert any("outside registry contract" in error for error in errors)


def test_contract_blocker_suppresses_speculative_positive_candidates():
    spec = TableSpec.from_contract(
        _contract(natural_key=[], value_columns=[], min_nonnull_frac=None)
    )
    profile = profile_frame(_frame(), spec)

    assert profile.disposition == ReadinessDisposition.BLOCKED
    assert generate_feature_candidates(_frame(), profile, spec) == ()


def test_model_prediction_output_plane_has_exactly_zero_candidates():
    spec = TableSpec.from_contract(load_registry().table("silver_model_predictions"))
    frame = pd.DataFrame({"y_actual": [1.0], "y_pred": [0.9], "target": ["yield"]})
    profile = profile_frame(frame, spec)

    assert profile.disposition == ReadinessDisposition.EXCLUDED_LEAKAGE
    assert generate_feature_candidates(frame, profile, spec) == ()


def test_final_only_unica_history_emits_only_diagnostic_anti_features():
    spec = TableSpec.from_contract(
        _contract(
            table_name="silver_unica_biweekly_season_history",
            s3_root="s3://leviathan-dev-shahem-001/silver/unica_history",
        )
    )
    frame = _frame()
    profile = profile_frame(frame, spec)
    candidates = generate_feature_candidates(frame, profile, spec)

    assert profile.disposition == ReadinessDisposition.DIAGNOSTIC_ONLY
    assert candidates
    assert all(c.classification == CandidateClassification.ANTI_FEATURE for c in candidates)
    assert all(c.readiness == CandidateReadiness.DIAGNOSTIC_ONLY for c in candidates)


def test_esr_progressive_candidates_do_not_invent_an_iso_week_cutoff():
    contract = _contract(
        table_name="silver_esr_compact",
        domain="trade_flows",
        physical_columns=[
            {"name": "commodity", "target_arrow_type": "string", "nullable": False},
            {"name": "commodity_code", "target_arrow_type": "int64", "nullable": False},
            {"name": "market_year", "target_arrow_type": "int64", "nullable": False},
            {"name": "as_of_date", "target_arrow_type": "date32[day]", "nullable": False},
            {"name": "country_code", "target_arrow_type": "int64", "nullable": False},
            {"name": "week_ending_date", "target_arrow_type": "date32[day]", "nullable": False},
            {"name": "ingest_date", "target_arrow_type": "date32[day]", "nullable": True},
            {"name": "weekly_exports_1000mt", "target_arrow_type": "float64", "nullable": True},
            {"name": "outstanding_sales_1000mt", "target_arrow_type": "float64", "nullable": True},
            {"name": "gross_new_sales_1000mt", "target_arrow_type": "float64", "nullable": True},
            {"name": "changes_1000mt", "target_arrow_type": "float64", "nullable": True},
        ],
        natural_key=[
            "commodity_code",
            "market_year",
            "as_of_date",
            "country_code",
            "week_ending_date",
        ],
        required_nonnull=[
            "commodity_code",
            "market_year",
            "as_of_date",
            "country_code",
            "week_ending_date",
        ],
        value_columns=[
            "weekly_exports_1000mt",
            "outstanding_sales_1000mt",
            "gross_new_sales_1000mt",
            "changes_1000mt",
        ],
        knowledge_date_col="as_of_date",
        knowledge_semantics="vintage",
        publication_lag_days=0,
    )
    dates = pd.date_range("2024-09-01", periods=24, freq="7D")
    frame = pd.DataFrame(
        {
            "commodity": ["corn"] * 24,
            "commodity_code": [101] * 24,
            "market_year": [2024] * 12 + [2025] * 12,
            "as_of_date": pd.to_datetime(["2026-05-31"] * 24),
            "country_code": [1] * 24,
            "week_ending_date": dates,
            "ingest_date": pd.to_datetime(["2026-06-01"] * 24),
            "weekly_exports_1000mt": [float(value) for value in range(1, 25)],
            "outstanding_sales_1000mt": [float(100 - value) for value in range(24)],
            "gross_new_sales_1000mt": [float(value * 2) for value in range(24)],
            "changes_1000mt": [float(value - 3) for value in range(24)],
        }
    )
    spec = TableSpec.from_contract(contract)
    candidates = generate_feature_candidates(
        frame,
        profile_frame(frame, spec),
        spec,
        overlay={
            "table_name": spec.table_name,
            "adapters": ["vintage_revision", "progressive_cumulative"],
            "units": {
                name: "thousand metric tonnes"
                for name in contract["value_columns"]
            },
        },
    )

    assert candidates
    assert not any(
        candidate.transformation["operation"] == "cumulative_curve_increment"
        for candidate in candidates
    )
    pace = [
        candidate
        for candidate in candidates
        if candidate.transformation["operation"] == "seasonal_pace"
    ]
    assert pace == []
    assert all("ingest_date" not in candidate.observation_time_rule for candidate in candidates)


def test_crop_progress_increments_are_limited_to_reviewed_cumulative_measures():
    contract = _contract(
        table_name="silver_nass_crop_progress",
        domain="crop_condition",
        physical_columns=[
            {"name": "commodity", "target_arrow_type": "string", "nullable": False},
            {"name": "state", "target_arrow_type": "string", "nullable": False},
            {"name": "year", "target_arrow_type": "int64", "nullable": False},
            {"name": "date", "target_arrow_type": "date32[day]", "nullable": False},
            {"name": "week_of_year", "target_arrow_type": "int64", "nullable": True},
            {"name": "pct_planted", "target_arrow_type": "float64", "nullable": True},
            {"name": "pct_emerged", "target_arrow_type": "float64", "nullable": True},
            {"name": "pct_harvested", "target_arrow_type": "float64", "nullable": True},
            {"name": "pct_good_excellent", "target_arrow_type": "float64", "nullable": True},
        ],
        natural_key=["commodity", "state", "year", "date"],
        required_nonnull=["commodity", "state", "year", "date"],
        value_columns=[
            "week_of_year",
            "pct_planted",
            "pct_emerged",
            "pct_good_excellent",
            "pct_harvested",
        ],
        publication_lag_days=1,
    )
    dates = pd.date_range("2024-04-01", periods=24, freq="7D")
    frame = pd.DataFrame(
        {
            "commodity": ["corn"] * 24,
            "state": ["IOWA"] * 24,
            "year": [2024] * 12 + [2025] * 12,
            "date": dates,
            "week_of_year": list(range(1, 13)) * 2,
            "pct_planted": [float(value) for value in list(range(5, 65, 5)) * 2],
            "pct_emerged": [float(value) for value in list(range(2, 50, 4)) * 2],
            "pct_harvested": [float(value) for value in list(range(0, 60, 5)) * 2],
            "pct_good_excellent": [float(70 - (value % 6)) for value in range(24)],
        }
    )
    spec = TableSpec.from_contract(contract)
    candidates = generate_feature_candidates(
        frame,
        profile_frame(frame, spec),
        spec,
        overlay={
            "table_name": spec.table_name,
            "adapters": ["progressive_cumulative"],
            "units": {
                "pct_planted": "percent",
                "pct_emerged": "percent",
                "pct_harvested": "percent",
                "pct_good_excellent": "percent",
            },
        },
    )
    increments = {
        candidate.transformation["column"]
        for candidate in candidates
        if candidate.transformation["operation"] == "cumulative_curve_increment"
    }
    pace = {
        candidate.transformation["column"]
        for candidate in candidates
        if candidate.transformation["operation"] == "seasonal_pace"
    }

    assert increments == {"pct_planted", "pct_emerged", "pct_harvested"}
    assert "pct_good_excellent" not in increments
    assert "week_of_year" not in pace
    assert {"pct_planted", "pct_emerged", "pct_harvested", "pct_good_excellent"} <= pace
    assert all(
        candidate.transformation["order_by"] == "week_of_year"
        for candidate in candidates
        if candidate.transformation["operation"]
        in {"cumulative_curve_increment", "seasonal_pace"}
    )


def test_generic_candidates_exclude_control_revision_and_composite_time_fields():
    contract = _contract(
        table_name="silver_noaa_oni",
        domain="climate_index",
        physical_columns=[
            {"name": "year", "target_arrow_type": "int64", "nullable": False},
            {"name": "month", "target_arrow_type": "int64", "nullable": False},
            {"name": "oni_anom", "target_arrow_type": "float64", "nullable": True},
            {"name": "cpi_available", "target_arrow_type": "bool", "nullable": True},
            {"name": "revision_value", "target_arrow_type": "float64", "nullable": True},
            {"name": "period_index", "target_arrow_type": "int64", "nullable": True},
        ],
        natural_key=["year", "month"],
        required_nonnull=["year", "month"],
        value_columns=["oni_anom", "cpi_available", "revision_value", "period_index"],
        publication_lag_days=None,
    )
    frame = pd.DataFrame(
        {
            "year": [2024] * 12 + [2025] * 12,
            "month": list(range(1, 13)) * 2,
            "oni_anom": [float(value) / 10 for value in range(24)],
            "cpi_available": [True, False] * 12,
            "revision_value": [float(value) for value in range(24)],
            "period_index": list(range(24)),
        }
    )
    spec = TableSpec.from_contract(contract)
    candidates = generate_feature_candidates(
        frame,
        profile_frame(frame, spec),
        spec,
        overlay={
            "table_name": spec.table_name,
            "units": {"oni_anom": "index points"},
        },
    )

    assert candidates
    assert {candidate.transformation["column"] for candidate in candidates} == {"oni_anom"}
    assert not any(
        candidate.transformation["operation"] in {"lag", "difference", "rolling_mean"}
        for candidate in candidates
    )
    assert all("ingest_date" not in candidate.observation_time_rule for candidate in candidates)
