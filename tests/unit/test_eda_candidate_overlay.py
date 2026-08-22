from __future__ import annotations

import pytest

# The [eda] extra backs this suite (nbformat/nbclient/jsonschema/matplotlib/IPython ride the
# EDA image, not the base dev env). A dev env without the extra SKIPS loudly instead of
# breaking collection -- the pdfplumber/[batch] precedent (test_pdfpage.py).
for _mod in ("nbformat", "nbclient", "jsonschema", "matplotlib", "IPython"):
    pytest.importorskip(_mod, reason="[eda] extra not installed")

import pandas as pd

from leviathan.eda import cli
from leviathan.eda.candidates import (
    candidate_generation_metadata,
    generate_feature_candidates,
)
from leviathan.eda.models import (
    CandidateClassification,
    CandidateReadiness,
    TableSpec,
)
from leviathan.eda.profiling import profile_frame
from leviathan.eda.render import render_summary


def _contract(**overrides):
    contract = {
        "table_name": "silver_overlay_test",
        "layer": "silver",
        "domain": "trade",
        "lifecycle_class": "source",
        "s3_root": "s3://leviathan-dev-shahem-001/silver/overlay_test",
        "physical_columns": [
            {"name": "commodity", "target_arrow_type": "string", "nullable": False},
            {"name": "date", "target_arrow_type": "date32[day]", "nullable": False},
            {"name": "value", "target_arrow_type": "float64", "nullable": True},
            {
                "name": "is_final_or_latest",
                "target_arrow_type": "bool",
                "nullable": False,
            },
        ],
        "partition_keys": [],
        "natural_key": ["commodity", "date"],
        "required_nonnull": ["commodity", "date"],
        "value_columns": ["value"],
        "min_nonnull_frac": 0.5,
        "knowledge_date_col": None,
        "knowledge_semantics": "data_date",
        "freshness_sla": {"cadence": "monthly"},
    }
    contract.update(overrides)
    return contract


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "commodity": ["corn"] * 24,
            "date": pd.date_range("2024-01-01", periods=24, freq="MS").astype(str),
            "value": [float(index + 1) for index in range(24)],
            "is_final_or_latest": [False] * 23 + [True],
        }
    )


def _profile_and_spec():
    spec = TableSpec.from_contract(_contract())
    frame = _frame()
    return frame, profile_frame(frame, spec), spec


def test_overlay_blocker_suppresses_candidates_and_records_reason():
    frame, profile, spec = _profile_and_spec()
    overlay = {
        "table_name": spec.table_name,
        "feature_disposition": "blocked",
        "no_candidate_reason": "Natural-key contract repair is required.",
    }

    candidates = generate_feature_candidates(frame, profile, spec, overlay=overlay)
    metadata = candidate_generation_metadata(
        profile, spec, candidates, overlay=overlay
    )
    summary = render_summary(
        profile, candidates, overlay=overlay, candidate_metadata=metadata
    )

    assert candidates == ()
    assert metadata["effective_disposition"] == "blocked"
    assert metadata["no_candidate_rationale"] == overlay["no_candidate_reason"]
    assert (
        summary["feature_opportunity_map"]["no_candidate_rationale"]["value"]
        == overlay["no_candidate_reason"]
    )


def test_overlay_controls_readiness_coverage_units_and_evidence_references():
    frame, profile, spec = _profile_and_spec()
    overlay = {
        "table_name": spec.table_name,
        "feature_disposition": "diagnostic_only",
        "source_keys": ["esr"],
        "existing_feature_families": ["esr_exports"],
        "existing_feature_visibility": {"esr_exports": "prior_history"},
        "units": {"value": "metric tonnes"},
    }

    candidates = generate_feature_candidates(
        frame,
        profile,
        spec,
        overlay=overlay,
        evidence_index={"distributions": "distributions-output"},
    )
    positive = [
        candidate
        for candidate in candidates
        if candidate.classification != CandidateClassification.ANTI_FEATURE
    ]

    assert positive
    assert all(candidate.classification == CandidateClassification.NEW for candidate in positive)
    assert all(candidate.readiness == CandidateReadiness.DIAGNOSTIC_ONLY for candidate in positive)
    assert all(candidate.unit == "metric tonnes" for candidate in positive)
    assert all(candidate.visibility_class == "review_required" for candidate in candidates)
    assert any("cell:distributions-output" in candidate.evidence for candidate in positive)
    assert all(any(ref.startswith("cell:") for ref in candidate.evidence) for candidate in positive)
    assert all(candidate.transformation["source_context"]["source_keys"] == ["esr"] for candidate in candidates)
    assert any(candidate.classification == CandidateClassification.ANTI_FEATURE for candidate in candidates)


def test_manifest_results_follow_final_effective_overlay_disposition() -> None:
    frame, profile, spec = _profile_and_spec()
    overlay = {
        "table_name": spec.table_name,
        "feature_disposition": "diagnostic_only",
        "source_keys": ["esr"],
        "units": {"value": "metric tonnes"},
    }
    candidates = generate_feature_candidates(frame, profile, spec, overlay=overlay)
    generation = candidate_generation_metadata(
        profile, spec, candidates, overlay=overlay
    )
    summary = render_summary(
        profile,
        candidates,
        overlay=overlay,
        candidate_metadata=generation,
    )
    candidate_document = cli._candidate_document(spec.table_name, candidates)

    results = cli._portable_result_summary(summary, candidate_document)

    assert profile.disposition.value == "needs_contract_or_data_fix"
    assert summary["profile"]["disposition"] == "diagnostic_only"
    assert results == {
        "disposition": "diagnostic_only",
        "analysis_exactness": summary["profile"]["analysis_exactness"],
        "candidate_count": candidate_document["candidate_count"],
        "blocker_count": len(summary["profile"]["blockers"]),
        "finding_count": len(summary["profile"]["findings"]),
    }


def test_exact_existing_mapping_carries_family_and_current_visibility():
    frame, profile, spec = _profile_and_spec()
    overlay = {
        "table_name": spec.table_name,
        "feature_disposition": "candidate_source",
        "source_keys": ["covered_source"],
        "existing_feature_families": ["current_level"],
        "existing_feature_visibility": {"current_level": "prior_history"},
        "existing_candidate_families": {"level": "current_level"},
        "units": {"value": "index"},
    }

    candidates = generate_feature_candidates(frame, profile, spec, overlay=overlay)
    existing = next(
        candidate
        for candidate in candidates
        if candidate.transformation["operation"] == "identity"
    )

    assert existing.classification == CandidateClassification.EXISTING
    assert existing.feature_family == "current_level"
    assert existing.visibility_class == "prior_history"
    assert existing.review_status.value == "unreviewed"


def test_uncovered_source_proposals_are_new_and_serializer_is_plan_complete():
    frame, profile, spec = _profile_and_spec()
    overlay = {
        "table_name": spec.table_name,
        "feature_disposition": "candidate_source",
        "source_keys": ["registered_but_unused"],
        "existing_feature_families": [],
        "units": {"value": "index"},
    }

    candidates = generate_feature_candidates(frame, profile, spec, overlay=overlay)
    positive = next(
        candidate
        for candidate in candidates
        if candidate.classification != CandidateClassification.ANTI_FEATURE
    )
    payload = positive.to_dict()

    assert positive.classification == CandidateClassification.NEW
    assert payload["review_status"] == "unreviewed"
    assert isinstance(payload["transformation"], dict)
    assert isinstance(payload["source_columns"], list)
    assert isinstance(payload["evidence"], list)
    assert {
        "aggregation_window",
        "applicable_commodities",
        "applicable_geographies",
        "candidate_id",
        "classification",
        "clipping_policy",
        "computation_primitive",
        "counter_evidence",
        "evidence",
        "expected_range",
        "feature_family",
        "feature_policy",
        "future_target_compatibility",
        "knowledge_time_rule",
        "lag",
        "mechanism",
        "missingness_policy",
        "normalization_policy",
        "observation_time_rule",
        "output_grain",
        "readiness",
        "review_status",
        "semantic_scope",
        "source_columns",
        "source_table",
        "transformation",
        "unit",
        "visibility_class",
    } == set(payload)


def test_excluded_overlay_produces_zero_candidates_even_for_regular_silver():
    frame, profile, spec = _profile_and_spec()
    overlay = {
        "table_name": spec.table_name,
        "feature_disposition": "excluded_leakage",
        "no_candidate_reason": "Generated output plane.",
    }

    assert generate_feature_candidates(frame, profile, spec, overlay=overlay) == ()
