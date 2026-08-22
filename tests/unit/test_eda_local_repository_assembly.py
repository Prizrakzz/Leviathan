from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
# The [eda] extra backs this suite (nbformat/nbclient/jsonschema/matplotlib/IPython ride the
# EDA image, not the base dev env). A dev env without the extra SKIPS loudly instead of
# breaking collection -- the pdfplumber/[batch] precedent (test_pdfpage.py).
for _mod in ("nbformat", "nbclient", "jsonschema", "matplotlib", "IPython"):
    pytest.importorskip(_mod, reason="[eda] extra not installed")

import yaml

from jobs.utils import assemble_silver_eda_repository as assembly
from leviathan.eda.models import TableSpec
from leviathan.silver.registry import SilverRegistry, load_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_ID = "20260718T000000Z_local-assembly"
LOCAL_SOURCE_SHA256 = "f" * 64
SNAPSHOT_PARQUET_SHA256 = "1" * 64


@dataclass(frozen=True)
class LocalAssemblyFixture:
    repo_root: Path
    eda_root: Path
    registry: SilverRegistry
    overlays: dict[str, dict[str, Any]]
    identity: dict[str, str]


def _scope() -> dict[str, Any]:
    return {
        "source_layer": "silver",
        "legacy_gold_read": False,
        "model_ready_read": False,
        "target_aware_analysis": False,
        "production_feature_config_mutated": False,
    }


def _fake_contract(table_name: str) -> dict[str, Any]:
    return {
        "table_name": table_name,
        "layer": "silver",
        "domain": (
            "model_output"
            if table_name == assembly.MODEL_OUTPUT_TABLE
            else "fixture"
        ),
        "lifecycle_class": "source",
        "s3_root": f"s3://leviathan-dev-shahem-001/silver/{table_name[7:]}",
        "natural_key": ["date"],
        "required_nonnull": ["date"],
        "value_columns": [],
        "physical_columns": [
            {
                "name": "date",
                "target_arrow_type": "date32[day]",
                "nullable": False,
            }
        ],
        "partition_keys": [],
        "publication_lag_days": None,
        "knowledge_date_col": None,
        "knowledge_semantics": None,
        "min_nonnull_frac": None,
        "min_nonnull_frac_overrides": {},
        "notes": "Local repository-assembly fixture only.",
    }


def _candidate_document(
    table_name: str, candidates: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    rows = candidates or []
    return {
        "schema_version": "leviathan.feature-candidates/v1",
        "table_name": table_name,
        "analysis_scope": "source-only canonical Silver; review-only",
        "production_feature_config_mutated": False,
        "candidate_count": len(rows),
        "no_candidate_reason": "No candidate is needed in this assembly fixture.",
        "candidates": rows,
    }


def _valid_candidate(table_name: str) -> dict[str, Any]:
    return {
        "candidate_id": f"eda:{table_name}:forbidden_output_feature",
        "source_table": table_name,
        "classification": "new",
        "feature_family": None,
        "mechanism": "Fixture candidate used to prove output-plane quarantine.",
        "source_columns": ["date"],
        "transformation": {"operation": "identity"},
        "aggregation_window": None,
        "lag": 1,
        "output_grain": "date",
        "unit": None,
        "observation_time_rule": "Use the observation date.",
        "knowledge_time_rule": "Require publication before cutoff.",
        "visibility_class": "review_required",
        "applicable_commodities": [],
        "applicable_geographies": [],
        "missingness_policy": "Preserve missing values.",
        "normalization_policy": "None.",
        "clipping_policy": "None.",
        "expected_range": None,
        "semantic_scope": "Fixture only.",
        "feature_policy": "Never auto-promote.",
        "future_target_compatibility": "Not eligible.",
        "evidence": ["metric:fixture"],
        "counter_evidence": [],
        "computation_primitive": "identity",
        "readiness": "blocked",
        "review_status": "unreviewed",
    }


def _artifact_record(path: Path, *, uri: str) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "uri": uri,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _refresh_manifest_artifacts(directory: Path, table_name: str) -> None:
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    prefix = (
        "s3://leviathan-dev-shahem-001/eda/silver/"
        f"campaign_id={manifest['campaign_id']}/table={table_name}"
    )
    manifest["artifacts"] = {
        leaf: _artifact_record(directory / leaf, uri=f"{prefix}/{leaf}")
        for leaf in (
            "spec.yaml",
            "summary.json",
            "feature_candidates.yaml",
            f"{table_name}_eda.ipynb",
        )
    }
    manifest_path.write_bytes(assembly._canonical_json_bytes(manifest))


def _write_local_override(
    fixture: LocalAssemblyFixture,
    table_name: str,
    *,
    local_source_sha256: str = LOCAL_SOURCE_SHA256,
) -> None:
    directory = fixture.eda_root / table_name
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    summary_path = directory / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    provenance = summary["provenance"]
    snapshot = manifest["snapshot"]
    provenance["local_notebook_reexecution"] = {
        "mode": "local_from_immutable_campaign_snapshot",
        "source_campaign_id": manifest["campaign_id"],
        "source_snapshot_uri": snapshot["parquet_uri"],
        "source_snapshot_sha256": snapshot["parquet_sha256"],
        "local_eda_source_sha256": local_source_sha256,
        "live_silver_read": False,
        "s3_write": False,
    }
    summary_path.write_bytes(assembly._canonical_json_bytes(summary))
    notebook_path = directory / f"{table_name}_eda.ipynb"
    notebook_path.write_bytes(notebook_path.read_bytes() + b"corrected-local\n")
    candidates = yaml.safe_load(
        (directory / "feature_candidates.yaml").read_text(encoding="utf-8")
    ) or {}
    local_manifest = {
        "schema_version": assembly.LOCAL_OVERRIDE_SCHEMA_VERSION,
        "table_name": table_name,
        "status": "executed_local_from_immutable_campaign_snapshot",
        "source_layer": "silver",
        "source_campaign_id": manifest["campaign_id"],
        "source_campaign_manifest": provenance["portable_manifest_uri"],
        "source_snapshot_uri": snapshot["parquet_uri"],
        "source_snapshot_sha256": snapshot["parquet_sha256"],
        "local_eda_source_sha256": local_source_sha256,
        "analysis_scope": {
            "live_silver_read": False,
            "s3_write": False,
            "gold_read": False,
            "target_analysis": False,
            "training": False,
            "producer_execution": False,
        },
        "candidate_count": candidates["candidate_count"],
        "artifacts": {
            "notebook": assembly._file_record(notebook_path),
            "summary": assembly._file_record(summary_path),
            "feature_candidates": assembly._file_record(
                directory / "feature_candidates.yaml"
            ),
            "spec": assembly._file_record(directory / "spec.yaml"),
        },
    }
    (directory / "local_manifest.json").write_bytes(
        assembly._canonical_json_bytes(local_manifest)
    )


def _write_fake_dossier(
    *,
    eda_root: Path,
    table_name: str,
    contract: dict[str, Any],
    overlay: dict[str, Any],
    registry_sha256: str,
    identity: dict[str, str],
) -> None:
    directory = eda_root / table_name
    directory.mkdir(parents=True)
    spec_sha256 = assembly._sha256_json(overlay)
    contract_sha256 = TableSpec.from_contract(contract).contract_hash
    snapshot_prefix = (
        "s3://leviathan-dev-shahem-001/eda/silver/"
        f"campaign_id={identity['campaign_id']}/table={table_name}/_machine/snapshot"
    )
    candidate_document = _candidate_document(table_name)
    disposition = (
        "excluded_leakage"
        if table_name == assembly.MODEL_OUTPUT_TABLE
        else "needs_contract_or_data_fix"
    )
    summary = {
        "schema_version": "leviathan.silver-eda-summary/v1",
        "table_name": table_name,
        "analysis_scope": _scope(),
        "decision_capsule": {
            "row_count": {"value": 2},
            "pit_status": {"value": "fixture"},
        },
        "feature_candidates": [],
        "profile": {
            "table_name": table_name,
            "disposition": disposition,
            "analysis_exactness": "exact",
            "blockers": [],
            "findings": [],
            "analyzer_routes": ["wide_panel"],
        },
        "reader": {
            "feature_quarantined": table_name == assembly.MODEL_OUTPUT_TABLE,
        },
        "provenance": {
            **identity,
            "contract_sha256": contract_sha256,
            "spec_sha256": spec_sha256,
            "frozen_frame_sha256": "e" * 64,
            "snapshot_uri": f"{snapshot_prefix}/part-000.parquet",
            "snapshot_manifest_uri": f"{snapshot_prefix}/manifest.json",
            "portable_manifest_uri": (
                "s3://leviathan-dev-shahem-001/eda/silver/"
                f"campaign_id={identity['campaign_id']}/table={table_name}/manifest.json"
            ),
            "source_total_rows": 2,
        },
    }
    (directory / "spec.yaml").write_bytes(assembly._canonical_yaml_bytes(overlay))
    (directory / "summary.json").write_bytes(assembly._canonical_json_bytes(summary))
    (directory / "feature_candidates.yaml").write_bytes(
        assembly._canonical_yaml_bytes(candidate_document)
    )
    (directory / f"{table_name}_eda.ipynb").write_bytes(b"fixture-notebook\n")
    manifest = {
        "schema_version": assembly.CAMPAIGN_SCHEMA_VERSION,
        "campaign_id": identity["campaign_id"],
        "table_name": table_name,
        "source_layer": "silver",
        "analysis_complete": True,
        "evidence_valid": True,
        **identity,
        "registry_sha256": registry_sha256,
        "contract_sha256": contract_sha256,
        "spec_sha256": spec_sha256,
        "source_inventory_summary": {"root_uri": contract["s3_root"]},
        # Deliberately vary source-replica identity by table.  Repository
        # assembly constrains output identity, not the originating replica.
        "source_replica": {
            "manifest_uri": (
                "s3://leviathan-dev-shahem-001/eda/silver/"
                f"campaign_id=older-{table_name}/table={table_name}/"
                "_machine/source_replica/manifest.json"
            )
        },
        "snapshot": {
            "frame_sha256": "e" * 64,
            "parquet_uri": f"{snapshot_prefix}/part-000.parquet",
            "parquet_sha256": SNAPSHOT_PARQUET_SHA256,
            "manifest_uri": f"{snapshot_prefix}/manifest.json",
        },
        "artifacts": {},
    }
    (directory / "manifest.json").write_bytes(assembly._canonical_json_bytes(manifest))
    _refresh_manifest_artifacts(directory, table_name)


def _rewrite_candidates(
    fixture: LocalAssemblyFixture,
    table_name: str,
    candidates: list[dict[str, Any]],
) -> None:
    directory = fixture.eda_root / table_name
    document = _candidate_document(table_name, candidates)
    summary_path = directory / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["feature_candidates"] = candidates
    summary_path.write_bytes(assembly._canonical_json_bytes(summary))
    (directory / "feature_candidates.yaml").write_bytes(
        assembly._canonical_yaml_bytes(document)
    )
    _refresh_manifest_artifacts(directory, table_name)


def _file_hashes(directory: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.iterdir())
        if path.is_file()
    }


@pytest.fixture
def local_repository(tmp_path: Path) -> LocalAssemblyFixture:
    repo_root = tmp_path / "repo"
    eda_root = repo_root / "eda"
    eda_root.mkdir(parents=True)
    production_registry = load_registry()
    icco_contract = production_registry.table(assembly.ICCO_REFERENCE_TABLE)
    table_names = sorted(assembly.LOCAL_OVERRIDE_TABLES)
    table_names.extend(f"silver_fixture_{index:02d}" for index in range(35))
    table_names.extend(
        [assembly.ICCO_REFERENCE_TABLE, assembly.MODEL_OUTPUT_TABLE]
    )
    contracts = {
        table_name: (
            icco_contract
            if table_name == assembly.ICCO_REFERENCE_TABLE
            else _fake_contract(table_name)
        )
        for table_name in table_names
    }
    registry = SilverRegistry(tables=contracts)
    overlays = {
        table_name: {
            "schema_version": 1,
            "table_name": table_name,
            "semantic_work_orders": [],
        }
        for table_name in table_names
    }
    icco_source = REPO_ROOT / "eda" / assembly.ICCO_REFERENCE_TABLE
    shutil.copytree(icco_source, eda_root / assembly.ICCO_REFERENCE_TABLE)
    overlays[assembly.ICCO_REFERENCE_TABLE] = yaml.safe_load(
        (icco_source / "spec.yaml").read_text(encoding="utf-8")
    )
    registry_sha256 = assembly._registry_hash(registry)
    identity = {
        "campaign_id": CAMPAIGN_ID,
        "registry_sha256": registry_sha256,
        "git_sha": "a" * 40,
        "image_digest": "sha256:" + "b" * 64,
        "eda_source_sha256": "c" * 64,
        "eda_config_sha256": "d" * 64,
    }
    for table_name in sorted(set(table_names) - {assembly.ICCO_REFERENCE_TABLE}):
        _write_fake_dossier(
            eda_root=eda_root,
            table_name=table_name,
            contract=contracts[table_name],
            overlay=overlays[table_name],
            registry_sha256=registry_sha256,
            identity=identity,
        )
    return LocalAssemblyFixture(
        repo_root=repo_root,
        eda_root=eda_root,
        registry=registry,
        overlays=overlays,
        identity=identity,
    )


@pytest.fixture(autouse=True)
def deterministic_notebook_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        assembly, "read_and_validate_notebook", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        assembly,
        "build_readiness_notebook",
        lambda **_kwargs: {"fixture": "readiness-notebook"},
    )

    def execute_fixture(_notebook: Any, output_path: Path, **_kwargs: Any) -> None:
        Path(output_path).write_bytes(b"deterministic-executed-root-notebook\n")

    monkeypatch.setattr(assembly, "execute_notebook", execute_fixture)
    monkeypatch.setattr(assembly, "_strip_execution_timing", lambda path: path.read_bytes())


def _assemble(
    fixture: LocalAssemblyFixture,
    *,
    local_overrides: frozenset[str] | None = None,
) -> dict[str, Any]:
    return assembly.assemble_repository(
        repo_root=fixture.repo_root,
        eda_root=fixture.eda_root,
        registry=fixture.registry,
        overlays=fixture.overlays,
        local_overrides=local_overrides,
    )


def test_assembles_exactly_42_completed_local_dossiers(
    local_repository: LocalAssemblyFixture,
) -> None:
    result = _assemble(local_repository)

    assert result["complete"] is True
    assert result["table_count"] == 42
    assert result["constituent_campaign_id"] == CAMPAIGN_ID
    assembly_document = json.loads(
        (local_repository.eda_root / "repository_assembly.json").read_text(
            encoding="utf-8"
        )
    )
    assert assembly_document["complete"] is True
    assert len(assembly_document["dossiers"]) == 42
    assert (
        assembly_document["dossiers"][assembly.ICCO_REFERENCE_TABLE][
            "campaign_exception"
        ]
        is True
    )


def test_rejects_a_missing_dossier(
    local_repository: LocalAssemblyFixture,
) -> None:
    shutil.rmtree(local_repository.eda_root / "silver_fixture_00")

    with pytest.raises(assembly.RepositoryAssemblyError, match="missing=.*fixture_00"):
        _assemble(local_repository)


def test_rejects_a_scaffold_or_incomplete_dossier(
    local_repository: LocalAssemblyFixture,
) -> None:
    manifest_path = (
        local_repository.eda_root / "silver_fixture_00" / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["analysis_complete"] = False
    manifest_path.write_bytes(assembly._canonical_json_bytes(manifest))

    with pytest.raises(
        assembly.RepositoryAssemblyError,
        match="scaffold, stale, or incomplete",
    ):
        _assemble(local_repository)


def test_rejects_mixed_output_campaign_runtime_identity(
    local_repository: LocalAssemblyFixture,
) -> None:
    directory = local_repository.eda_root / "silver_fixture_00"
    manifest_path = directory / "manifest.json"
    summary_path = directory / "summary.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    different_digest = "sha256:" + "9" * 64
    manifest["image_digest"] = different_digest
    summary["provenance"]["image_digest"] = different_digest
    summary_path.write_bytes(assembly._canonical_json_bytes(summary))
    manifest_path.write_bytes(assembly._canonical_json_bytes(manifest))
    _refresh_manifest_artifacts(directory, "silver_fixture_00")

    with pytest.raises(
        assembly.RepositoryAssemblyError,
        match="do not share one campaign/runtime identity",
    ):
        _assemble(local_repository)


def test_strict_default_rejects_corrected_local_bytes(
    local_repository: LocalAssemblyFixture,
) -> None:
    table_name = "silver_wasde"
    _write_local_override(local_repository, table_name)

    with pytest.raises(
        assembly.RepositoryAssemblyError,
        match="differs from its completed manifest",
    ):
        _assemble(local_repository)


def test_explicit_allowlisted_overrides_bind_all_five_local_manifests(
    local_repository: LocalAssemblyFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def capture_root(**kwargs: Any) -> dict[str, str]:
        captured.update(kwargs)
        return {"fixture": "readiness-notebook"}

    monkeypatch.setattr(assembly, "build_readiness_notebook", capture_root)
    for table_name in assembly.LOCAL_OVERRIDE_TABLES:
        _write_local_override(local_repository, table_name)

    result = _assemble(
        local_repository,
        local_overrides=assembly.LOCAL_OVERRIDE_TABLES,
    )

    assert result["local_overrides"] == sorted(assembly.LOCAL_OVERRIDE_TABLES)
    assembly_document = json.loads(
        (local_repository.eda_root / "repository_assembly.json").read_text(
            encoding="utf-8"
        )
    )
    assert sorted(assembly_document["local_overrides"]) == sorted(
        assembly.LOCAL_OVERRIDE_TABLES
    )
    for table_name in assembly.LOCAL_OVERRIDE_TABLES:
        dossier = assembly_document["dossiers"][table_name]
        assert dossier["local_override"] is True
        assert "local_manifest.json" in dossier["artifacts"]
        assert (
            assembly_document["local_overrides"][table_name]["artifact_authority"]
            == "local_manifest.json"
        )
    provenance = captured["provenance"]
    assert (
        provenance["assembly_mode"]
        == "local_offline_repository_with_corrected_notebooks"
    )
    assert sorted(provenance["local_notebook_overrides"]) == sorted(
        assembly.LOCAL_OVERRIDE_TABLES
    )


def test_rejects_non_allowlisted_local_override(
    local_repository: LocalAssemblyFixture,
) -> None:
    with pytest.raises(
        assembly.RepositoryAssemblyError,
        match="not allowlisted",
    ):
        _assemble(
            local_repository,
            local_overrides=frozenset({"silver_fixture_00"}),
        )


def test_rejects_local_override_artifact_hash_drift(
    local_repository: LocalAssemblyFixture,
) -> None:
    table_name = "silver_wasde"
    _write_local_override(local_repository, table_name)
    notebook_path = (
        local_repository.eda_root / table_name / f"{table_name}_eda.ipynb"
    )
    notebook_path.write_bytes(notebook_path.read_bytes() + b"drift\n")

    with pytest.raises(
        assembly.RepositoryAssemblyError,
        match="differs from local_manifest.json",
    ):
        _assemble(
            local_repository,
            local_overrides=frozenset({table_name}),
        )


def test_rejects_local_override_snapshot_or_scope_escape(
    local_repository: LocalAssemblyFixture,
) -> None:
    table_name = "silver_nasa_power"
    _write_local_override(local_repository, table_name)
    local_manifest_path = (
        local_repository.eda_root / table_name / "local_manifest.json"
    )
    local_manifest = json.loads(local_manifest_path.read_text(encoding="utf-8"))
    local_manifest["source_snapshot_uri"] = "s3://bucket/gold/unsafe.parquet"
    local_manifest["analysis_scope"]["gold_read"] = True
    local_manifest_path.write_bytes(assembly._canonical_json_bytes(local_manifest))

    with pytest.raises(
        assembly.RepositoryAssemblyError,
        match="invalid corrected-local manifest identity or scope",
    ):
        _assemble(
            local_repository,
            local_overrides=frozenset({table_name}),
        )


def test_rejects_mixed_local_override_source_identity(
    local_repository: LocalAssemblyFixture,
) -> None:
    tables = ("silver_esr", "silver_esr_compact")
    _write_local_override(local_repository, tables[0])
    _write_local_override(local_repository, tables[1], local_source_sha256="2" * 64)

    with pytest.raises(
        assembly.RepositoryAssemblyError,
        match="do not share one local EDA source identity",
    ):
        _assemble(local_repository, local_overrides=frozenset(tables))


def test_model_predictions_must_have_zero_feature_candidates(
    local_repository: LocalAssemblyFixture,
) -> None:
    candidate = _valid_candidate(assembly.MODEL_OUTPUT_TABLE)
    _rewrite_candidates(local_repository, assembly.MODEL_OUTPUT_TABLE, [candidate])

    with pytest.raises(
        assembly.RepositoryAssemblyError,
        match="must be excluded_leakage with zero candidates",
    ):
        _assemble(local_repository)


def test_assembly_never_changes_the_accepted_icco_reference(
    local_repository: LocalAssemblyFixture,
) -> None:
    directory = local_repository.eda_root / assembly.ICCO_REFERENCE_TABLE
    before = _file_hashes(directory)

    _assemble(local_repository)

    assert _file_hashes(directory) == before


def test_repository_assembly_and_root_artifacts_are_deterministic(
    local_repository: LocalAssemblyFixture,
) -> None:
    first = _assemble(local_repository)
    first_hashes = {
        name: assembly._file_record(local_repository.eda_root / name)
        for name in assembly.ROOT_OUTPUT_FILES
    }

    second = _assemble(local_repository)
    second_hashes = {
        name: assembly._file_record(local_repository.eda_root / name)
        for name in assembly.ROOT_OUTPUT_FILES
    }

    assert second["repository_assembly_id"] == first["repository_assembly_id"]
    assert second_hashes == first_hashes


def test_rejects_an_executed_notebook_over_the_budget(
    local_repository: LocalAssemblyFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table_name = "silver_fixture_00"
    directory = local_repository.eda_root / table_name
    notebook_path = directory / f"{table_name}_eda.ipynb"
    notebook_path.write_bytes(b"123456")
    _refresh_manifest_artifacts(directory, table_name)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    artifacts, _ = assembly._artifact_binding(
        table_name=table_name, directory=directory
    )
    monkeypatch.setattr(assembly, "NOTEBOOK_SIZE_LIMIT_BYTES", 5)

    with pytest.raises(assembly.RepositoryAssemblyError, match="exceeds 5 bytes"):
        assembly._validate_manifest_artifacts(
            table_name=table_name,
            directory=directory,
            manifest=manifest,
            artifacts=artifacts,
        )
