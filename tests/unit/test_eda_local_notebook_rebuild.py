"""Focused safety tests for the local Silver notebook correction utility."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

# The [eda] extra backs this suite (nbformat/nbclient/jsonschema/matplotlib/IPython ride the
# EDA image, not the base dev env). A dev env without the extra SKIPS loudly instead of
# breaking collection -- the pdfplumber/[batch] precedent (test_pdfpage.py).
for _mod in ("nbformat", "nbclient", "jsonschema", "matplotlib", "IPython"):
    pytest.importorskip(_mod, reason="[eda] extra not installed")

import nbformat
import pytest

from jobs.utils import rebuild_local_silver_eda_notebooks as rebuild
from leviathan.eda.models import Exactness, ReadinessDisposition, ReviewStatus
from leviathan.eda.source_aggregates import SOURCE_AGGREGATE_SCHEMA_VERSION
from leviathan.silver.registry import APPROVED_BUCKET


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _campaign_manifest(table_name: str = "silver_wasde") -> dict[str, object]:
    campaign_id = "readerfirst-test-abc123"
    prefix = f"eda/silver/campaign_id={campaign_id}/table={table_name}/_machine/snapshot"
    return {
        "table_name": table_name,
        "campaign_id": campaign_id,
        "source_layer": "silver",
        "analysis_scope": {
            "source_layer": "silver",
            "legacy_gold_read": False,
            "model_ready_read": False,
            "target_aware_analysis": False,
            "production_feature_config_mutated": False,
        },
        "snapshot": {
            "table_name": table_name,
            "campaign_id": campaign_id,
            "destination": f"s3://{APPROVED_BUCKET}/{prefix}",
            "manifest_uri": f"s3://{APPROVED_BUCKET}/{prefix}/manifest.json",
            "parquet_uri": f"s3://{APPROVED_BUCKET}/{prefix}/part-000.parquet",
            "frame_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
            "parquet_sha256": "c" * 64,
            "parquet_bytes": 123,
            "decision": {
                "exactness": "exact",
                "source_row_count": 10,
                "snapshot_row_count": 10,
            },
        },
    }


def test_snapshot_uri_is_exactly_bound_to_campaign_and_table() -> None:
    manifest = _campaign_manifest()
    assert rebuild._require_snapshot_uri("silver_wasde", manifest).endswith(
        "/table=silver_wasde/_machine/snapshot/part-000.parquet"
    )

    manifest["snapshot"]["parquet_uri"] = str(  # type: ignore[index]
        manifest["snapshot"]["parquet_uri"]  # type: ignore[index]
    ).replace("table=silver_wasde", "table=silver_esr")
    with pytest.raises(rebuild.LocalNotebookRebuildError, match="exact immutable"):
        rebuild._require_snapshot_uri("silver_wasde", manifest)


@pytest.mark.parametrize("segment", ["gold", "_shadow", "_staging", "_tasks", ".hidden"])
def test_snapshot_boundary_rejects_gold_and_control_segments(segment: str) -> None:
    with pytest.raises(rebuild.LocalNotebookRebuildError):
        rebuild._assert_safe_snapshot_key(
            table_name="silver_wasde",
            key=f"eda/silver/{segment}/_machine/snapshot/part-000.parquet",
        )


def test_source_fingerprint_matches_v1_path_and_byte_algorithm(tmp_path: Path) -> None:
    files = {
        "src/leviathan/eda/a.py": b"A\r\n",
        "src/leviathan/eda/nested/b.py": b"B\n",
        **{
            relative: f"payload:{relative}".encode()
            for relative in rebuild.SOURCE_FINGERPRINT_STATIC_FILES
        },
    }
    for relative, payload in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    lines = [rebuild.SOURCE_FINGERPRINT_VERSION]
    lines.extend(
        f"{relative}\0{_sha(files[relative])}" for relative in sorted(files)
    )
    expected = _sha("\n".join(lines).encode("utf-8"))
    assert rebuild._source_fingerprint(tmp_path) == expected


def test_inherited_sampled_source_aggregates_are_hash_and_inventory_bound() -> None:
    table_name = "silver_nasa_power"
    manifest = _campaign_manifest(table_name)
    manifest["snapshot"]["decision"] = {  # type: ignore[index]
        "exactness": Exactness.SAMPLED.value,
        "source_row_count": 100,
        "snapshot_row_count": 20,
    }
    manifest["source_inventory_summary"] = {
        "total_rows": 100,
        "fragment_count": 3,
        "inventory_manifest_sha256": "d" * 64,
    }
    aggregates: dict[str, object] = {
        "schema_version": SOURCE_AGGREGATE_SCHEMA_VERSION,
        "table_name": table_name,
        "exactness": Exactness.EXACT.value,
        "source_shape": [100, 4],
        "source_object_count": 3,
        "source_manifest_sha256": "d" * 64,
        "time_coverage": {"column": "date", "min": "2020-01-01", "max": "2020-01-02"},
        "column_statistics": {},
        "entity_coverage": {},
        "chart_tables": {},
        "chart_priority": [],
    }
    aggregate_hash = _sha(
        json.dumps(
            aggregates,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    )
    aggregates["aggregate_sha256"] = aggregate_hash
    summary = {"provenance": {"source_aggregate_sha256": aggregate_hash}}

    assert (
        rebuild._validate_source_aggregates(
            table_name=table_name,
            aggregates=aggregates,
            campaign_manifest=manifest,
            prior_summary=summary,
        )
        is aggregates
    )

    aggregates["source_shape"] = [101, 4]
    with pytest.raises(rebuild.LocalNotebookRebuildError, match="identity/hash mismatch"):
        rebuild._validate_source_aggregates(
            table_name=table_name,
            aggregates=aggregates,
            campaign_manifest=manifest,
            prior_summary=summary,
        )


def test_reused_profile_removes_only_stale_esr_parity_finding() -> None:
    payload = {
        "table_name": "silver_esr",
        "analysis_exactness": "exact",
        "disposition": "diagnostic_only",
        "analyzer_routes": ["wide_panel"],
        "blockers": ["governed blocker"],
        "findings": [
            {
                "code": "EDA-SEMANTIC-PARITY-001",
                "title": "stale",
                "severity": "high",
                "message": "stale parity interpretation",
                "risk": "stale",
                "evidence": [],
                "confidence": "high",
            },
            {
                "code": "EDA-VALUE-001",
                "title": "retain",
                "severity": "medium",
                "message": "retain this finding",
                "risk": "real",
                "evidence": ["metric:x"],
                "confidence": "high",
            },
        ],
        "sections": {
            "schema_contract": {
                "name": "schema_contract",
                "metrics": {
                    "row_count": {
                        "name": "row_count",
                        "value": 10,
                        "exactness": "exact",
                        "unit": "rows",
                    }
                },
            }
        },
    }
    profile = rebuild._remove_stale_esr_parity_finding(
        rebuild._deserialize_profile("silver_esr", payload)
    )
    assert profile.disposition == ReadinessDisposition.DIAGNOSTIC_ONLY
    assert profile.blockers == ("governed blocker",)
    assert [finding.code for finding in profile.findings] == ["EDA-VALUE-001"]


def test_reviewed_candidate_yaml_is_deserialized_without_losing_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rebuild, "validate_feature_candidates", lambda *_: None)
    raw = {
        "candidate_id": "eda:silver_esr:x:level",
        "source_table": "silver_esr",
        "classification": "new",
        "mechanism": "mechanism",
        "source_columns": ["x"],
        "transformation": {"operation": "identity", "column": "x"},
        "aggregation_window": None,
        "lag": 1,
        "output_grain": "entity x date",
        "unit": "units",
        "observation_time_rule": "order by date",
        "knowledge_time_rule": "knowledge_date <= cutoff",
        "visibility_class": "review_required",
        "applicable_commodities": ["all_observed"],
        "applicable_geographies": ["all_observed"],
        "missingness_policy": "preserve",
        "normalization_policy": "none",
        "clipping_policy": "none",
        "expected_range": None,
        "semantic_scope": "source only",
        "feature_policy": "proposal only",
        "future_target_compatibility": "later PIT-safe review",
        "evidence": ["cell:distributions-output"],
        "counter_evidence": [],
        "computation_primitive": "identity",
        "readiness": "diagnostic_only",
        "feature_family": None,
        "review_status": "accepted",
    }
    document = {
        "table_name": "silver_esr",
        "candidate_count": 1,
        "candidates": [raw],
    }
    candidates = rebuild._deserialize_candidates(
        table_name="silver_esr",
        spec=object(),  # type: ignore[arg-type]
        document=document,
    )
    assert candidates[0].review_status == ReviewStatus.ACCEPTED
    assert candidates[0].to_dict() == raw


def test_prepare_helpers_clear_outputs_and_cleanup_inheriting_stage(tmp_path: Path) -> None:
    notebook = nbformat.v4.new_notebook(
        cells=[
            nbformat.v4.new_code_cell(
                "1 + 1",
                execution_count=3,
                outputs=[nbformat.v4.new_output("execute_result", data={"text/plain": "2"})],
            )
        ]
    )
    rebuild._clear_notebook_outputs(notebook)
    assert notebook.cells[0].execution_count is None
    assert notebook.cells[0].outputs == []

    directory = tmp_path / "silver_esr"
    directory.mkdir()
    with rebuild._inheriting_staging_directory(directory) as staging:
        assert staging.parent == directory.parent.resolve()
        assert staging.name.startswith(".silver_esr-local-eda-rebuild-")
        staging.mkdir(exist_ok=True)
        (staging / "artifact").write_text("prepared", encoding="utf-8")
        staged_path = staging
    assert not staged_path.exists()


def test_prepare_and_reuse_flags_are_an_explicit_pair(tmp_path: Path) -> None:
    with pytest.raises(rebuild.LocalNotebookRebuildError, match="must be used together"):
        rebuild.rebuild_table(
            repo_root=tmp_path,
            table_name="silver_esr",
            local_source_sha256="a" * 64,
            timeout_seconds=1,
            reuse_existing_profile=True,
            prepare_only=False,
        )
