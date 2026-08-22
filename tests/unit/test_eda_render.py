from __future__ import annotations

import pandas as pd
import pytest

from leviathan.eda.candidates import generate_feature_candidates
from leviathan.eda.models import TableSpec
from leviathan.eda.profiling import profile_frame
from leviathan.eda.render import (
    render_feature_candidate_catalog,
    render_markdown_summary,
    render_readiness_index,
    render_summary,
    summary_json,
)


def _result(table_name="silver_render_test"):
    contract = {
        "table_name": table_name,
        "layer": "silver",
        "domain": "macro",
        "lifecycle_class": "source",
        "s3_root": f"s3://leviathan-dev-shahem-001/silver/{table_name}",
        "physical_columns": [
            {"name": "date", "target_arrow_type": "date32[day]", "nullable": False},
            {"name": "value", "target_arrow_type": "float64", "nullable": True},
        ],
        "partition_keys": [],
        "natural_key": ["date"],
        "required_nonnull": ["date"],
        "value_columns": ["value"],
        "min_nonnull_frac": 0.5,
        "knowledge_date_col": None,
        "knowledge_semantics": "data_date",
        "freshness_sla": {"cadence": "monthly"},
    }
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=12, freq="MS").astype(str),
            "value": range(12),
        }
    )
    spec = TableSpec.from_contract(contract)
    profile = profile_frame(frame, spec)
    candidates = generate_feature_candidates(frame, profile, spec)
    return profile, candidates


def test_summary_is_deterministic_and_explicitly_source_only():
    profile, candidates = _result()
    provenance = {"campaign_id": "c1", "git_sha": "abc"}

    first = render_summary(profile, candidates, provenance)
    second = render_summary(profile, candidates, provenance)

    assert first == second
    assert summary_json(profile, candidates, provenance) == summary_json(
        profile, candidates, provenance
    )
    assert first["analysis_scope"]["legacy_gold_read"] is False
    assert first["analysis_scope"]["target_aware_analysis"] is False
    assert first["decision_capsule"]["candidate_count"]["exactness"] == "exact"
    assert "Legacy gold/model-ready inputs: not read" in render_markdown_summary(
        profile, candidates
    )


def test_catalog_and_readiness_index_are_sorted_and_complete():
    profile_b, candidates_b = _result("silver_b")
    profile_a, candidates_a = _result("silver_a")

    catalog = render_feature_candidate_catalog(
        {"silver_b": candidates_b, "silver_a": candidates_a}
    )
    index = render_readiness_index(
        [profile_b, profile_a], {"silver_b": candidates_b, "silver_a": candidates_a}
    )

    assert list(catalog["tables"]) == ["silver_a", "silver_b"]
    assert [row["table_name"] for row in index["rows"]] == ["silver_a", "silver_b"]
    assert index["table_count"] == 2
    assert index["analysis_scope"]["gold_contracts_included"] == 0


def test_summary_rejects_cross_table_candidate_mix():
    profile_a, _ = _result("silver_a")
    _, candidates_b = _result("silver_b")

    with pytest.raises(ValueError, match="table mismatch"):
        render_summary(profile_a, candidates_b)

