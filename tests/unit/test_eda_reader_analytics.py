from __future__ import annotations

import json

import pandas as pd

from leviathan.eda.models import Exactness, TableSpec
from leviathan.eda.profiling import profile_frame
from leviathan.eda.reader_analytics import (
    _temporal_values,
    assess_chart_plan,
    build_quality_scorecard,
    build_reader_evidence,
    build_reader_insights,
    ordinary_describe,
    select_reader_preview,
)
from leviathan.eda.reader_metadata import build_reader_metadata
from leviathan.silver.registry import load_registry


def _contract(**overrides):
    contract = {
        "table_name": "silver_reader_demo",
        "layer": "silver",
        "domain": "prices",
        "lifecycle_class": "source",
        "s3_root": "s3://leviathan-dev-shahem-001/silver/reader_demo",
        "physical_columns": [
            {"name": "commodity", "target_arrow_type": "string", "nullable": False},
            {"name": "date", "target_arrow_type": "date32[day]", "nullable": False},
            {"name": "value", "target_arrow_type": "float64", "nullable": False},
            {"name": "note", "target_arrow_type": "string", "nullable": True},
        ],
        "partition_keys": [],
        "natural_key": ["commodity", "date"],
        "required_nonnull": ["commodity", "date", "value"],
        "value_columns": ["value"],
        "min_nonnull_frac": 1.0,
        "knowledge_date_col": None,
        "knowledge_semantics": "publication_lag",
        "publication_lag_days": 1,
        "coverage_axis": "date",
    }
    contract.update(overrides)
    return contract


def _frame(rows: int = 12) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "commodity": ["cocoa" if index % 2 else "coffee" for index in range(rows)],
            "date": pd.date_range("2024-01-01", periods=rows, freq="D"),
            "value": [float(index) for index in range(rows)],
            "note": [None if index == 0 else f"row-{index}" for index in range(rows)],
        }
    )


def _metadata(table_name: str = "silver_reader_demo") -> dict:
    return {
        "table_name": table_name,
        "archetype": "continuous_market_macro_climate",
        "row_meaning": "One commodity observation per day.",
        "column_descriptions": {
            "commodity": "Commodity represented by the row.",
            "date": "Observation date.",
            "value": "Observed source value.",
            "note": "Optional source note.",
        },
        "units": {"value": "USD per tonne"},
        "why_it_matters": {"value": "Reviewed primary measure for source-only analysis."},
        "primary_measures": ["value"],
        "preview_strata": ["commodity"],
        "pit_notes": ["Apply the governed one-day publication lag."],
        "anti_features": ["Do not use observations published after the cutoff."],
        "dashboard_kpis": [
            {"kpi_id": "source_rows", "label": "Rows", "kind": "row_count", "columns": []},
            {"kpi_id": "columns", "label": "Columns", "kind": "column_count", "columns": []},
            {"kpi_id": "coverage", "label": "Coverage", "kind": "time_coverage", "columns": ["date"]},
            {"kpi_id": "entities", "label": "Commodities", "kind": "distinct_entities", "columns": ["commodity"]},
            {"kpi_id": "complete", "label": "Completeness", "kind": "missingness", "columns": ["value"]},
            {"kpi_id": "duplicates", "label": "Duplicate rate", "kind": "duplicate_rate", "columns": ["commodity", "date"]},
            {"kpi_id": "latest", "label": "Latest value", "kind": "latest_value", "columns": ["value"]},
        ],
        "insight_rules": [
            {"insight_id": "coverage", "kind": "coverage_span", "columns": ["date", "commodity"]},
            {"insight_id": "missing", "kind": "missingness", "columns": ["value"]},
            {"insight_id": "extremes", "kind": "robust_extremes", "columns": ["date", "value", "commodity"], "minimum_rows": 4},
            {"insight_id": "latest", "kind": "latest_change", "columns": ["date", "value", "commodity"], "minimum_rows": 2},
        ],
        "chart_plan": [
            {"id": "trend", "type": "line", "x": "date", "y": "value"},
            {"id": "distribution", "type": "distribution", "column": "value"},
        ],
    }


def test_reader_evidence_is_reader_first_complete_and_json_serializable() -> None:
    frame = _frame(12)
    spec = TableSpec.from_contract(_contract())
    profile = profile_frame(frame, spec)

    evidence = build_reader_evidence(
        frame,
        profile,
        spec,
        _metadata(),
        provenance={"source_row_count": 12, "manifest_sha256": "abc123"},
    )

    assert evidence["source_shape"]["source_shape"] == [12, 4]
    assert evidence["schema_version"] == "leviathan.silver-eda-reader-evidence/v1"
    assert evidence["archetype"] == "continuous_market_macro_climate"
    assert evidence["source_shape"]["analysis_rows"] == 12
    assert evidence["source_shape"]["exactness"] == "exact"
    assert evidence["display_policy"]["mode"] == "full_dataframe"
    assert evidence["preview"]["displayed_rows"] == 12
    assert len(evidence["preview"]["records"]) == 12
    assert "Data columns" in evidence["df_info_text"]
    assert {row["column"] for row in evidence["column_dictionary"]} == set(frame.columns)
    value = next(row for row in evidence["column_dictionary"] if row["column"] == "value")
    assert value["meaning"] == "Observed source value."
    assert value["why_it_matters"] == "Reviewed primary measure for source-only analysis."
    assert value["unit"] == "USD per tonne"
    assert evidence["ordinary_statistics"]["numeric"]["row_count"] == 1
    assert evidence["ordinary_statistics"]["categorical"]["row_count"] == 2
    assert len(evidence["dashboard_kpis"]) == 7
    assert {item["status"] for item in evidence["dashboard_kpis"]} == {"evaluated"}
    assert all(item["detail"] and item["scope"] for item in evidence["dashboard_kpis"])
    assert len(evidence["reader_insights"]) == 4
    assert {item["status"] for item in evidence["reader_insights"]} == {"evaluated"}
    assert all(item["caveat"] and item["references"] for item in evidence["reader_insights"])
    assert evidence["chart_plan"]["ready_chart_count"] == 2
    assert evidence["pit_summary"]["status"] == "ready"
    assert evidence["anti_feature_summary"]["entries"]
    json.dumps(evidence, allow_nan=False)


def test_large_preview_is_bounded_deduplicated_and_order_independent() -> None:
    frame = _frame(250)
    frame = pd.concat([frame, frame.iloc[[17]]], ignore_index=True)
    spec = TableSpec.from_contract(_contract())
    metadata = _metadata()

    first = select_reader_preview(
        frame,
        spec,
        metadata,
        source_rows=len(frame),
        exactness="exact",
    )
    shuffled = select_reader_preview(
        frame.sample(frac=1.0, random_state=77).reset_index(drop=True),
        spec,
        metadata,
        source_rows=len(frame),
        exactness="exact",
    )

    assert first["mode"] == "deterministic_preview"
    assert first["displayed_rows"] == 40
    assert first["records"] == shuffled["records"]
    assert len({json.dumps(row, sort_keys=True) for row in first["records"]}) == 40
    reasons = " ".join(first["selection_reasons"])
    assert "earliest coverage" in reasons
    assert "latest coverage" in reasons
    assert "stratified by commodity" in reasons


def test_tiny_table_shows_every_row_and_does_not_force_an_underpowered_chart() -> None:
    frame = _frame(2)
    spec = TableSpec.from_contract(_contract())
    profile = profile_frame(frame, spec)

    evidence = build_reader_evidence(
        frame,
        profile,
        spec,
        {**_metadata(), "chart_plan": []},
    )

    assert evidence["preview"]["mode"] == "full_dataframe"
    assert evidence["preview"]["displayed_rows"] == 2
    assert evidence["preview"]["records"] == [
        {
            "commodity": "coffee",
            "date": "2024-01-01T00:00:00",
            "value": 0.0,
            "note": None,
        },
        {
            "commodity": "cocoa",
            "date": "2024-01-02T00:00:00",
            "value": 1.0,
            "note": "row-1",
        },
    ]
    assert evidence["chart_plan"]["ready_chart_count"] == 0
    assert evidence["chart_plan"]["overall_status"] == "no_chart_warranted"
    assert len(evidence["reader_insights"]) >= 3


def test_sampled_scope_never_presents_analysis_rows_as_source_shape() -> None:
    frame = _frame(50)
    spec = TableSpec.from_contract(_contract())
    profile = profile_frame(frame, spec, exactness=Exactness.SAMPLED)

    evidence = build_reader_evidence(
        frame,
        profile,
        spec,
        _metadata(),
        provenance={"source_rows": 10_000},
    )

    assert evidence["source_shape"]["source_shape"] == [10_000, 4]
    assert evidence["source_shape"]["analysis_shape"] == [50, 4]
    assert evidence["source_shape"]["exactness"] == "sampled"
    assert evidence["display_policy"]["mode"] == "deterministic_preview"
    assert all(item["exactness"] == "sampled" for item in evidence["reader_insights"])


def test_empty_frame_has_no_fake_zero_denominator_rates() -> None:
    frame = _frame(0)
    spec = TableSpec.from_contract(_contract())
    profile = profile_frame(frame, spec)

    evidence = build_reader_evidence(frame, profile, spec, _metadata())
    checks = {item["check_id"]: item for item in evidence["quality_scorecard"]["checks"]}

    assert evidence["display_policy"]["mode"] == "empty"
    assert checks["grain"]["status"] == "not_assessed"
    assert checks["missingness"]["status"] == "not_assessed"
    assert checks["missingness"]["evidence"]["maximum_null_rate"] is None
    assert checks["cadence"]["status"] == "not_assessed"
    assert evidence["ordinary_statistics"]["status"] == "empty"
    assert len(evidence["reader_insights"]) == 4
    json.dumps(evidence, allow_nan=False)


def test_contextual_validity_separates_structural_blanks_from_explicit_sentinels() -> None:
    spec = TableSpec.from_contract(_contract())

    blanks = _frame(4).assign(note=["", "   ", "source qualification", "available"])
    blank_check = next(
        item
        for item in build_quality_scorecard(
            blanks,
            profile_frame(blanks, spec),
            spec,
            _metadata(),
        )["checks"]
        if item["check_id"] == "validity"
    )
    assert blank_check["status"] == "PASS"
    assert blank_check["evidence"]["blank_strings"] == 2
    assert blank_check["evidence"]["blank_strings_by_column"] == {"note": 2}
    assert blank_check["evidence"]["explicit_sentinel_values"] == 0
    assert blank_check["evidence"]["sentinel_values"] == 0
    assert "not treated as invalid" in blank_check["summary"]

    sentinels = _frame(4).assign(note=["N/A", "unknown", "-", "ok"])
    sentinel_check = next(
        item
        for item in build_quality_scorecard(
            sentinels,
            profile_frame(sentinels, spec),
            spec,
            _metadata(),
        )["checks"]
        if item["check_id"] == "validity"
    )
    assert sentinel_check["status"] == "CAVEAT"
    assert sentinel_check["evidence"]["explicit_sentinel_values"] == 3
    assert sentinel_check["evidence"]["explicit_sentinels_by_column_token"] == {
        "note": {"-": 1, "n/a": 1, "unknown": 1}
    }

    governed = {
        **_metadata(),
        "quality_rules": [
            {
                "rule_id": "note_required_nonblank",
                "kind": "required_nonblank",
                "column": "note",
                "columns": ["note"],
            }
        ],
    }
    governed_check = next(
        item
        for item in build_quality_scorecard(
            blanks,
            profile_frame(blanks, spec),
            spec,
            governed,
        )["checks"]
        if item["check_id"] == "validity"
    )
    assert governed_check["status"] == "CAVEAT"
    assert governed_check["evidence"][
        "blank_strings_in_required_nonblank_columns_by_column"
    ] == {"note": 2}


def test_zero_comparable_identity_is_not_assessed_instead_of_zero_percent() -> None:
    frame = _frame(3).assign(value=pd.NA, comparison=pd.NA)
    contract = _contract(
        physical_columns=_contract()["physical_columns"]
        + [{"name": "comparison", "target_arrow_type": "float64", "nullable": True}],
        required_nonnull=["commodity", "date"],
    )
    spec = TableSpec.from_contract(contract)
    profile = profile_frame(frame, spec)
    metadata = {
        **_metadata(),
        "quality_rules": [
            {
                "rule_id": "value_equals_comparison",
                "kind": "identity",
                "left": "value",
                "right": "comparison",
            }
        ],
    }

    evidence = build_reader_evidence(frame, profile, spec, metadata)
    identity = next(
        item
        for item in evidence["quality_scorecard"]["checks"]
        if item["check_id"] == "rule:value_equals_comparison"
    )

    assert identity["status"] == "not_assessed"
    assert identity["evidence"]["comparable_rows"] == 0
    assert identity["evidence"]["violation_rate"] is None


def test_chart_plan_enforces_trend_threshold_and_rejects_unsupported_types() -> None:
    frame = _frame(20).assign(second=lambda item: item["value"] * 2)
    contract = _contract(
        physical_columns=_contract()["physical_columns"]
        + [{"name": "second", "target_arrow_type": "float64", "nullable": False}],
        value_columns=["value", "second"],
    )
    spec = TableSpec.from_contract(contract)
    metadata = {
        "chart_plan": [
            {"id": "short-trend", "type": "line", "x": "date", "y": "value"},
            {"id": "small-scatter", "type": "scatter", "x": "value", "y": "second"},
        ]
    }

    seven = assess_chart_plan(frame.iloc[:7], spec, metadata, source_rows=7)
    nineteen = assess_chart_plan(frame.iloc[:19], spec, metadata, source_rows=19)
    twenty = assess_chart_plan(frame, spec, metadata, source_rows=20)

    assert {item["chart_id"]: item["status"] for item in seven["charts"]} == {
        "short-trend": "skipped",
        "small-scatter": "not_assessed",
    }
    assert nineteen["charts"][0]["status"] == "ready"
    assert nineteen["charts"][1]["status"] == "not_assessed"
    assert twenty["charts"][0]["status"] == "ready"
    assert twenty["charts"][1]["status"] == "not_assessed"


def test_descriptive_metadata_rules_do_not_duplicate_the_concise_scorecard() -> None:
    frame = _frame(12)
    spec = TableSpec.from_contract(_contract())
    profile = profile_frame(frame, spec)
    metadata = {
        **_metadata(),
        "quality_rules": [
            {"rule_id": "grain", "kind": "declared_or_inferred_grain"},
            {"rule_id": "duplicates", "kind": "duplicate_rate"},
            {"rule_id": "missingness", "kind": "missingness"},
            {"rule_id": "validity", "kind": "numeric_validity"},
            {"rule_id": "cadence", "kind": "temporal_gaps"},
            {"rule_id": "coverage", "kind": "coverage"},
            {"rule_id": "schema_drift", "kind": "schema_drift"},
            {
                "rule_id": "identity",
                "kind": "unsupported",
                "detail": "No governed identity is declared.",
            },
        ],
    }

    evidence = build_reader_evidence(frame, profile, spec, metadata)
    checks = evidence["quality_scorecard"]["checks"]

    assert len(checks) == 8
    assert len({item["check_id"] for item in checks}) == 8
    identity = next(item for item in checks if item["check_id"] == "arithmetic_identities")
    assert identity["status"] == "not_assessed"
    assert identity["summary"] == "No governed identity is declared."


def test_chart_plan_preserves_config_and_requires_bound_parity_evidence() -> None:
    frame = _frame(20)
    spec = TableSpec.from_contract(_contract())
    configured = {
        "chart_plan": [
            {
                "chart_id": "distribution",
                "chart_type": "distribution",
                "columns": ["value"],
                "minimum_rows": 25,
                "purpose": "Explain the source distribution.",
                "roles": {"measure": "value"},
                "aggregation": "none",
            }
        ]
    }

    assessed = assess_chart_plan(frame, spec, configured, source_rows=20)
    chart = assessed["charts"][0]

    assert chart["status"] == "skipped"
    assert chart["minimum_rows"] == 25
    assert chart["purpose"] == "Explain the source distribution."
    assert chart["roles"] == {"measure": "value"}
    assert chart["aggregation"] == "none"

    parity_plan = {
        "chart_plan": [
            {
                "chart_id": "paired_parity",
                "chart_type": "parity",
                "columns": ["date", "value"],
            }
        ]
    }
    unbound = assess_chart_plan(frame, spec, parity_plan, source_rows=20)
    bound = assess_chart_plan(
        frame,
        spec,
        parity_plan,
        source_rows=20,
        relationship_evidence={
            "relationship_checks": [
                {
                    "relationship": "silver_esr_to_silver_esr_compact",
                    "status": "complete",
                    "matched_keys": 17,
                    "value_parity": {"value": {"mismatch_rate": 0.0}},
                }
            ]
        },
    )

    assert unbound["charts"][0]["status"] == "not_assessed"
    assert bound["charts"][0]["status"] == "ready"
    assert bound["charts"][0]["eligible_rows"] == 17
    assert bound["charts"][0]["plotted_rows"] is None
    assert bound["plotted_rows"] is None


def test_footer_schema_drift_uses_exact_object_evidence() -> None:
    frame = _frame(12)
    spec = TableSpec.from_contract(_contract())
    profile = profile_frame(frame, spec)

    def schema_check(provenance: dict) -> dict:
        scorecard = build_quality_scorecard(
            frame,
            profile,
            spec,
            _metadata(),
            source_rows=12,
            provenance=provenance,
        )
        return next(
            item for item in scorecard["checks"] if item["check_id"] == "schema_drift"
        )

    absent = schema_check({})
    consistent = schema_check(
        {
            "coverage_catalog": {
                "footer_complete": True,
                "object_count": 3,
                "schema_sha256_object_counts": {"a" * 64: 3},
            }
        }
    )
    drifted = schema_check(
        {
            "coverage_catalog": {
                "footer_complete": True,
                "object_count": 3,
                "schema_sha256_object_counts": {"a" * 64: 2, "b" * 64: 1},
            }
        }
    )
    incomplete = schema_check(
        {
            "coverage_catalog": {
                "footer_complete": False,
                "object_count": 3,
                "schema_sha256_object_counts": {"a" * 64: 2, "missing": 1},
            }
        }
    )

    assert absent["status"] == "not_assessed"
    assert consistent["status"] == "PASS"
    assert drifted["status"] == "CAVEAT"
    assert incomplete["status"] == "CAVEAT"
    assert all(item["exactness"] == "footer-derived" for item in (absent, consistent, drifted, incomplete))


def test_same_cutoff_revision_and_climatology_insight_adapters_execute() -> None:
    progressive_contract = _contract(
        physical_columns=[
            {"name": "commodity", "target_arrow_type": "string", "nullable": False},
            {"name": "date", "target_arrow_type": "date32[day]", "nullable": False},
            {"name": "season", "target_arrow_type": "string", "nullable": False},
            {"name": "week_of_year", "target_arrow_type": "int64", "nullable": False},
            {"name": "cumulative", "target_arrow_type": "float64", "nullable": False},
        ],
        natural_key=["commodity", "season", "week_of_year"],
        required_nonnull=["commodity", "date", "season", "week_of_year", "cumulative"],
        value_columns=["cumulative"],
    )
    progressive_frame = pd.DataFrame(
        {
            "commodity": ["cocoa"] * 6,
            "date": pd.date_range("2024-01-01", periods=6, freq="7D"),
            "season": ["2023/24"] * 3 + ["2024/25"] * 3,
            "week_of_year": [1, 2, 3, 1, 2, 3],
            "cumulative": [10.0, 20.0, 30.0, 12.0, 24.0, 37.0],
        }
    )
    progressive_spec = TableSpec.from_contract(progressive_contract)
    progressive = build_reader_insights(
        progressive_frame,
        profile_frame(progressive_frame, progressive_spec),
        progressive_spec,
        {
            "primary_measures": ["cumulative"],
            "insight_rules": [
                {"insight_id": "pace", "kind": "same_cutoff_pace", "columns": ["date", "cumulative", "commodity"]},
                {"insight_id": "missing", "kind": "missingness", "columns": ["cumulative"]},
                {"insight_id": "extremes", "kind": "robust_extremes", "columns": ["cumulative"], "minimum_rows": 4},
            ],
        },
        source_rows=6,
    )
    pace = next(item for item in progressive if item["insight_id"] == "pace")
    assert pace["status"] == "evaluated"
    assert pace["evidence"]["cutoff"] == 3
    assert pace["evidence"]["delta"] == 7.0

    revision_contract = _contract(
        physical_columns=[
            {"name": "commodity", "target_arrow_type": "string", "nullable": False},
            {"name": "market_year", "target_arrow_type": "string", "nullable": False},
            {"name": "release_date", "target_arrow_type": "date32[day]", "nullable": False},
            {"name": "estimate", "target_arrow_type": "float64", "nullable": False},
        ],
        natural_key=["commodity", "market_year", "release_date"],
        required_nonnull=["commodity", "market_year", "release_date", "estimate"],
        value_columns=["estimate"],
        knowledge_date_col="release_date",
        knowledge_semantics="release",
        publication_lag_days=None,
    )
    revision_frame = pd.DataFrame(
        {
            "commodity": ["cocoa"] * 3,
            "market_year": ["2025/26"] * 3,
            "release_date": pd.to_datetime(["2025-05-01", "2025-06-01", "2025-07-01"]),
            "estimate": [100.0, 104.0, 103.0],
        }
    )
    revision_spec = TableSpec.from_contract(revision_contract)
    revision = build_reader_insights(
        revision_frame,
        profile_frame(revision_frame, revision_spec),
        revision_spec,
        {
            "primary_measures": ["estimate"],
            "insight_rules": [
                {"insight_id": "revisions", "kind": "revision_depth", "columns": ["release_date", "estimate", "commodity"], "minimum_rows": 2},
                {"insight_id": "coverage", "kind": "coverage_span", "columns": ["release_date", "commodity"]},
                {"insight_id": "missing", "kind": "missingness", "columns": ["estimate"]},
            ],
        },
        source_rows=3,
    )
    revisions = next(item for item in revision if item["insight_id"] == "revisions")
    assert revisions["status"] == "evaluated"
    assert revisions["evidence"]["transition_count"] == 2

    climate_frame = pd.DataFrame(
        {
            "commodity": ["cocoa"] * 36,
            "date": pd.date_range("2022-01-01", periods=36, freq="MS"),
            "value": [float((index % 12) + index // 12) for index in range(36)],
            "note": [None] * 36,
        }
    )
    climate_frame.loc[35, "value"] = 100.0
    climate_spec = TableSpec.from_contract(_contract())
    climate = build_reader_insights(
        climate_frame,
        profile_frame(climate_frame, climate_spec),
        climate_spec,
        {
            "primary_measures": ["value"],
            "insight_rules": [
                {"insight_id": "anomaly", "kind": "climatology_anomaly", "columns": ["date", "value", "commodity"], "minimum_rows": 8},
                {"insight_id": "coverage", "kind": "coverage_span", "columns": ["date", "commodity"]},
                {"insight_id": "missing", "kind": "missingness", "columns": ["value"]},
            ],
        },
        source_rows=36,
    )
    anomaly = next(item for item in climate if item["insight_id"] == "anomaly")
    assert anomaly["status"] == "evaluated"
    assert anomaly["evidence"]["usable_anomaly_rows"] == 36


def test_latest_change_uses_natural_key_grain_and_truly_latest_numeric_year() -> None:
    contract = _contract(
        table_name="silver_nass_annual",
        physical_columns=[
            {"name": "commodity", "target_arrow_type": "string", "nullable": False},
            {"name": "leviathan_slug", "target_arrow_type": "string", "nullable": True},
            {"name": "state", "target_arrow_type": "string", "nullable": False},
            {"name": "year", "target_arrow_type": "int64", "nullable": False},
            {"name": "area_planted_ha", "target_arrow_type": "float64", "nullable": True},
        ],
        natural_key=["commodity", "state", "year"],
        required_nonnull=["commodity", "state", "year"],
        value_columns=["area_planted_ha"],
        coverage_axis="year",
    )
    frame = pd.DataFrame(
        {
            "commodity": ["corn"] * 6,
            "leviathan_slug": ["corn"] * 6,
            "state": ["LEGACY", "LEGACY", "IOWA", "KANSAS", "IOWA", "KANSAS"],
            "year": pd.Series([1922, 1923, 2025, 2025, 2026, 2026], dtype="Int64"),
            "area_planted_ha": [10.0, 11.0, 100.0, 200.0, 105.0, 210.0],
        }
    )
    spec = TableSpec.from_contract(contract)
    insights = build_reader_insights(
        frame,
        profile_frame(frame, spec),
        spec,
        {
            "primary_measures": ["area_planted_ha"],
            "units": {"area_planted_ha": "hectares"},
            "insight_rules": [
                {
                    "insight_id": "latest",
                    "kind": "latest_change",
                    # Deliberately omit state and include a redundant slug to
                    # reproduce the pilot's old 1922 -> 1923 failure.
                    "columns": [
                        "year",
                        "area_planted_ha",
                        "commodity",
                        "leviathan_slug",
                    ],
                    "minimum_rows": 2,
                },
                {"insight_id": "coverage", "kind": "coverage_span", "columns": ["year", "commodity"]},
                {"insight_id": "missing", "kind": "missingness", "columns": ["area_planted_ha"]},
            ],
        },
        source_rows=6,
    )
    latest = next(item for item in insights if item["insight_id"] == "latest")

    assert latest["status"] == "evaluated"
    assert latest["evidence"]["prior_period"] == "2025"
    assert latest["evidence"]["latest_period"] == "2026"
    assert latest["evidence"]["measure"] == "area_planted_ha"
    assert latest["evidence"]["unit"] == "hectares"
    assert "state" in latest["evidence"]["entity"]
    assert "leviathan_slug" not in latest["evidence"]["entity"]
    assert "area_planted_ha (hectares)" in latest["statement"]
    assert "from 2025 to 2026" in latest["statement"]


def test_temporal_parser_rejects_wasde_control_and_vintage_strings_safely() -> None:
    values = pd.Series(
        [
            "1-12-01",
            "0001-12-01",
            "9999-12-01",
            "2025/26",
            "projection-2026",
            "2026-07-18",
            "2026-07",
            "20260718",
            "2026",
        ],
        dtype="string",
    )

    parsed = _temporal_values(values)

    assert parsed.iloc[:5].isna().all()
    assert parsed.iloc[5:].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-07-18",
        "2026-07-01",
        "2026-07-18",
        "2026-01-01",
    ]
    assert str(parsed.dtype) == "datetime64[ns]"


def test_wasde_reader_separates_release_dates_from_outcome_seasons() -> None:
    contract = load_registry().table("silver_wasde")
    spec = TableSpec.from_contract(contract)
    metadata = build_reader_metadata(
        contract,
        # Reproduce the stale overlay ordering that previously selected the
        # outcome season as if it were publication time.
        overlay={"observation_time_candidates": ["marketing_year", "release_date"]},
    )
    frame = pd.DataFrame(
        {
            "release_date": pd.to_datetime(
                ["1985-01-11", "1985-02-08", "2026-06-12", "2026-07-10"]
            ),
            "source_table_id": ["A", "A", "B", "B"],
            "commodity": ["corn", "corn", "wheat", "wheat"],
            "table_type": ["world", "world", "world", "world"],
            "region": ["United States"] * 4,
            "marketing_year": ["1985/86", "1985/86", "2025/26", "2025/26"],
            "attribute": ["production"] * 4,
            "unit": ["million metric tonnes"] * 3 + [""],
            "estimate": [100.0, 101.0, 200.0, 202.0],
            "estimate_role": ["current"] * 4,
            "projection_month": [""] * 4,
        }
    )
    insights = build_reader_insights(
        frame,
        profile_frame(frame, spec),
        spec,
        metadata,
        source_rows=4,
    )
    release = next(
        item for item in insights if item["insight_id"] == "release_coverage_span"
    )
    seasons = next(
        item for item in insights if item["insight_id"] == "outcome_season_coverage"
    )
    extremes = next(
        item for item in insights if item["insight_id"] == "notable_extremes"
    )

    assert release["status"] == "evaluated"
    assert release["evidence"]["start"].startswith("1985-01-11")
    assert release["evidence"]["end"].startswith("2026-07-10")
    assert "1985-01-11 through 2026-07-10" in release["statement"]
    assert seasons["status"] == "evaluated"
    assert seasons["evidence"] == {
        "distinct_outcome_seasons": 2,
        "earliest_outcome_season": "1985/86",
        "entity_distinct_counts": {
            "commodity": 2,
            "region": 1,
            "attribute": 1,
        },
        "latest_outcome_season": "2025/26",
        "season_column": "marketing_year",
    }
    assert "not publication timing" in seasons["statement"]
    assert extremes["status"] == "not_assessed"
    scope = extremes["evidence"]["compatibility_scope"]
    assert "unit" in scope["incompatible_columns"]
    assert scope["column_profiles"]["unit"]["missing_or_malformed_rows"] == 1
    assert "single IQR would mix incompatible scales" in extremes["statement"]


def test_wasde_ordinary_describe_only_counts_actual_release_dates_as_temporal() -> None:
    contract = _contract(
        table_name="silver_wasde",
        domain="balance_sheet",
        physical_columns=[
            {"name": "release_date", "target_arrow_type": "date32[day]", "nullable": False},
            {"name": "commodity", "target_arrow_type": "string", "nullable": False},
            {"name": "marketing_year", "target_arrow_type": "string", "nullable": False},
            {"name": "projection_month", "target_arrow_type": "string", "nullable": True},
            {"name": "estimate", "target_arrow_type": "float64", "nullable": True},
        ],
        natural_key=["release_date", "commodity", "marketing_year", "projection_month"],
        required_nonnull=["release_date", "commodity", "marketing_year"],
        value_columns=["estimate"],
        knowledge_date_col="release_date",
        knowledge_semantics="vintage",
        publication_lag_days=None,
        coverage_axis="release_date",
    )
    frame = pd.DataFrame(
        {
            "release_date": ["2026-01-12", "2026-02-10"],
            "commodity": ["corn", "corn"],
            "marketing_year": ["2025/26", "2025/26"],
            "projection_month": ["1-12-01", "2-12-01"],
            "estimate": [100.0, 101.0],
        }
    )
    spec = TableSpec.from_contract(contract)

    temporal = {
        row["column"]: row for row in ordinary_describe(frame, spec)["temporal"]["records"]
    }

    assert temporal["release_date"] == {
        "column": "release_date",
        "count": 2,
        "distinct": 2,
        "max": "2026-02-10T00:00:00",
        "min": "2026-01-12T00:00:00",
    }
    assert temporal["marketing_year"]["count"] == 0
    assert temporal["marketing_year"]["min"] is None
    assert temporal["projection_month"]["count"] == 0
    assert temporal["projection_month"]["max"] is None


def test_model_output_quarantine_contains_no_payload_values_or_feature_evidence() -> None:
    contract = _contract(
        table_name="silver_model_predictions",
        domain="model_output",
        s3_root="s3://leviathan-dev-shahem-001/silver/model_predictions",
        physical_columns=[
            {"name": "model_family", "target_arrow_type": "string", "nullable": False},
            {"name": "prediction_date", "target_arrow_type": "date32[day]", "nullable": False},
            {"name": "target", "target_arrow_type": "string", "nullable": False},
            {"name": "y_actual", "target_arrow_type": "float64", "nullable": True},
            {"name": "y_pred", "target_arrow_type": "float64", "nullable": False},
        ],
        natural_key=["model_family", "prediction_date", "target"],
        required_nonnull=["model_family", "prediction_date", "target", "y_pred"],
        value_columns=["target", "y_actual", "y_pred"],
        knowledge_semantics="ingest",
        publication_lag_days=None,
    )
    frame = pd.DataFrame(
        {
            "model_family": ["secret-model"],
            "prediction_date": ["2026-01-01"],
            "target": ["yield-secret"],
            "y_actual": [9876.5],
            "y_pred": [8765.4],
        }
    )
    spec = TableSpec.from_contract(contract)
    profile = profile_frame(frame, spec)
    metadata = {
        "table_name": "silver_model_predictions",
        "row_meaning": "One generated prediction output.",
        "feature_quarantined": True,
        "chart_plan": [{"id": "forbidden", "type": "scatter", "x": "y_actual", "y": "y_pred"}],
    }

    evidence = build_reader_evidence(frame, profile, spec, metadata)
    serialized = json.dumps(evidence, allow_nan=False)

    assert evidence["feature_quarantined"] is True
    assert evidence["preview"]["mode"] == "schema_only_quarantine"
    assert evidence["preview"]["records"] == []
    assert evidence["ordinary_statistics"]["status"] == "withheld_output_quarantine"
    assert 4 <= len(evidence["dashboard_kpis"]) <= 8
    assert all(
        item["status"] in {"evaluated", "not_assessed"}
        and item["detail"]
        and item["scope"]
        for item in evidence["dashboard_kpis"]
    )
    assert {item["insight_id"] for item in evidence["reader_insights"]} == {
        "schema_quality",
        "record_coverage",
        "candidate_grain",
    }
    assert evidence["notable_rows"]["records"] == []
    assert evidence["chart_plan"]["ready_chart_count"] == 0
    assert evidence["chart_plan"]["overall_status"] == "quarantined"
    assert evidence["pit_summary"]["status"] == "excluded_leakage"
    assert evidence["anti_feature_summary"]["feature_quarantined"] is True
    sensitive = {row["column"]: row for row in evidence["column_dictionary"]}
    assert all(row["value_access"] == "quarantined" for row in sensitive.values())
    assert all(row["example"] is None and row["distinct_count"] is None for row in sensitive.values())
    assert "yield-secret" not in serialized
    assert "secret-model" not in serialized
    assert "9876.5" not in serialized
    assert "8765.4" not in serialized


def test_metadata_table_mismatch_fails_before_building_evidence() -> None:
    frame = _frame(3)
    spec = TableSpec.from_contract(_contract())
    profile = profile_frame(frame, spec)

    try:
        build_reader_evidence(frame, profile, spec, _metadata("silver_wrong"))
    except ValueError as exc:
        assert "table names do not match" in str(exc)
    else:
        raise AssertionError("metadata mismatch must fail")


def test_exact_scope_rejects_source_analysis_row_mismatch() -> None:
    frame = _frame(3)
    spec = TableSpec.from_contract(_contract())
    profile = profile_frame(frame, spec)

    try:
        build_reader_evidence(
            frame,
            profile,
            spec,
            _metadata(),
            provenance={"source_rows": 99},
        )
    except ValueError as exc:
        assert "exact analysis requires" in str(exc)
    else:
        raise AssertionError("exact scope mismatch must fail")
