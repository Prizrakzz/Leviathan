from __future__ import annotations

import pandas as pd

from leviathan.eda.assessment import apply_semantic_assessment
from leviathan.eda.models import ReadinessDisposition, TableSpec
from leviathan.eda.profiling import profile_frame


def _contract(**overrides):
    contract = {
        "table_name": "silver_assessment_test",
        "layer": "silver",
        "domain": "prices",
        "lifecycle_class": "source",
        "s3_root": "s3://leviathan-dev-shahem-001/silver/assessment_test",
        "physical_columns": [
            {"name": "commodity", "target_arrow_type": "string", "nullable": False},
            {"name": "date", "target_arrow_type": "date32[day]", "nullable": False},
            {"name": "value", "target_arrow_type": "float64", "nullable": False},
        ],
        "partition_keys": [],
        "natural_key": ["commodity", "date"],
        "required_nonnull": ["commodity", "date", "value"],
        "value_columns": ["value"],
        "min_nonnull_frac": 1.0,
        "knowledge_date_col": None,
        "knowledge_semantics": "publication_lag",
        "publication_lag_days": 0,
    }
    contract.update(overrides)
    return contract


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "commodity": ["corn"] * 12,
            "date": pd.date_range("2024-01-01", periods=12, freq="MS"),
            "value": [float(value) for value in range(12)],
        }
    )


def test_unresolved_units_degrade_ready_source_and_emit_work_order_finding() -> None:
    spec = TableSpec.from_contract(_contract())
    profile = profile_frame(_frame(), spec)
    assert profile.disposition == ReadinessDisposition.READY_FOR_FEATURE_IDEATION

    assessed = apply_semantic_assessment(
        profile,
        spec,
        overlay={
            "table_name": spec.table_name,
            "units": {"value": "source-native / verify"},
        },
    )

    assert assessed.disposition == ReadinessDisposition.NEEDS_CONTRACT_OR_DATA_FIX
    assert "EDA-SEMANTIC-UNIT-001" in {finding.code for finding in assessed.findings}
    assert (
        assessed.metric("feature_engineering_readiness", "disposition").value
        == "needs_contract_or_data_fix"
    )


def test_weather_row_expansion_is_a_hard_blocker() -> None:
    spec = TableSpec.from_contract(_contract(domain="weather"))
    profile = profile_frame(_frame(), spec)

    assessed = apply_semantic_assessment(
        profile,
        spec,
        overlay={
            "table_name": spec.table_name,
            "adapters": ["weather"],
            "units": {"value": "millimetres"},
        },
        source_specific_checks=[
            {
                "governed_mapping_status": {
                    "status": "complete",
                    "readiness": "row_expansion_blocked",
                }
            }
        ],
    )

    assert assessed.disposition == ReadinessDisposition.BLOCKED
    assert "governed weather join would expand rows" in assessed.blockers


def test_unassessed_derived_lineage_and_sampled_esr_parity_are_actionable() -> None:
    spec = TableSpec.from_contract(_contract(lifecycle_class="derived"))
    profile = profile_frame(_frame(), spec)

    assessed = apply_semantic_assessment(
        profile,
        spec,
        overlay={
            "table_name": spec.table_name,
            "units": {"value": "index"},
        },
        source_specific_checks=[
            {
                "check": "derived_lineage",
                "status": "lineage_not_assessed",
                "repair_required": True,
                "evidence": "No governed peer contract.",
            }
        ],
        relationship_checks=[
            {
                "relationship": "silver_esr_to_silver_esr_compact",
                "status": "complete",
                "exactness": "sampled",
                "raw_only_keys": 1,
                "compact_only_keys": 2,
                "value_parity": {},
            }
        ],
    )

    codes = {finding.code for finding in assessed.findings}
    assert {"EDA-SEMANTIC-LINEAGE-001", "EDA-SEMANTIC-PARITY-001"} <= codes
    parity = next(finding for finding in assessed.findings if "PARITY" in finding.code)
    assert parity.confidence == "medium"
    assert assessed.disposition == ReadinessDisposition.NEEDS_CONTRACT_OR_DATA_FIX


def test_compact_only_coverage_extension_does_not_degrade_esr_parity() -> None:
    spec = TableSpec.from_contract(_contract())
    profile = profile_frame(_frame(), spec)

    assessed = apply_semantic_assessment(
        profile,
        spec,
        overlay={
            "table_name": spec.table_name,
            "units": {"value": "index"},
        },
        relationship_checks=[
            {
                "relationship": "silver_esr_to_silver_esr_compact",
                "status": "complete",
                "exactness": "exact",
                "matched_keys": 753_062,
                "raw_only_keys": 0,
                "compact_only_keys": 783_388,
                "raw_duplicate_key_excess": 0,
                "compact_duplicate_key_excess": 0,
                "row_expansion": False,
                "shared_key_parity_status": "pass",
                "value_parity": {
                    "value": {
                        "comparable_rows": 753_062,
                        "mismatch_rows": 0,
                        "mismatch_rate": 0.0,
                    }
                },
            }
        ],
    )

    assert assessed.disposition == ReadinessDisposition.READY_FOR_FEATURE_IDEATION
    assert "EDA-SEMANTIC-PARITY-001" not in {
        finding.code for finding in assessed.findings
    }
    assert (
        assessed.metric("feature_engineering_readiness", "disposition").value
        == "ready_for_feature_ideation"
    )


def test_clean_esr_parity_does_not_hide_existing_value_population_caveat() -> None:
    spec = TableSpec.from_contract(_contract(min_nonnull_frac=0.5))
    frame = _frame().copy()
    frame.loc[:6, "value"] = None
    profile = profile_frame(frame, spec)
    assert "EDA-VALUE-001" in {finding.code for finding in profile.findings}

    assessed = apply_semantic_assessment(
        profile,
        spec,
        overlay={
            "table_name": spec.table_name,
            "units": {"value": "index"},
        },
        relationship_checks=[
            {
                "relationship": "silver_esr_to_silver_esr_compact",
                "status": "complete",
                "exactness": "exact",
                "matched_keys": 12,
                "raw_only_keys": 0,
                "compact_only_keys": 12,
                "raw_duplicate_key_excess": 0,
                "compact_duplicate_key_excess": 0,
                "row_expansion": False,
                "shared_key_parity_status": "pass",
                "value_parity": {
                    "value": {
                        "comparable_rows": 12,
                        "mismatch_rows": 0,
                        "mismatch_rate": 0.0,
                    }
                },
            }
        ],
    )

    codes = {finding.code for finding in assessed.findings}
    assert "EDA-VALUE-001" in codes
    assert "EDA-SEMANTIC-PARITY-001" not in codes
    assert assessed.disposition == ReadinessDisposition.NEEDS_CONTRACT_OR_DATA_FIX
