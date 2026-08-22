from __future__ import annotations

import json
from pathlib import Path

import pytest

# The [eda] extra backs this suite (nbformat/nbclient/jsonschema/matplotlib/IPython ride the
# EDA image, not the base dev env). A dev env without the extra SKIPS loudly instead of
# breaking collection -- the pdfplumber/[batch] precedent (test_pdfpage.py).
for _mod in ("nbformat", "nbclient", "jsonschema", "matplotlib", "IPython"):
    pytest.importorskip(_mod, reason="[eda] extra not installed")

import pandas as pd
from jsonschema import Draft202012Validator

from leviathan.eda.campaign import build_all_overlays
from leviathan.eda.candidates import generate_feature_candidates
from leviathan.eda.models import TableSpec
from leviathan.eda.profiling import profile_frame
from leviathan.silver.registry import load_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = REPO_ROOT / "eda" / "_config" / "schemas"


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))


def test_all_42_table_overlays_match_canonical_schema() -> None:
    registry = load_registry()
    overlays = build_all_overlays(registry, repo_root=REPO_ROOT)
    validator = Draft202012Validator(_schema("table_spec.schema.json"))
    assert len(overlays) == 42
    for name, overlay in overlays.items():
        errors = sorted(validator.iter_errors(overlay), key=lambda item: list(item.path))
        assert not errors, f"{name}: {[error.message for error in errors]}"


def test_generated_candidate_matches_canonical_interface_schema() -> None:
    contract = load_registry().table("silver_fred_fx")
    spec = TableSpec.from_contract(contract)
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2023-01-01", periods=24, freq="MS"),
            "brl_usd": range(24),
            "brl_usd_pct_change_90d": range(24),
            "ars_usd": range(24),
            "ars_usd_pct_change_90d": range(24),
            "cny_usd": range(24),
            "cny_usd_pct_change_90d": range(24),
            "source": ["FRED"] * 24,
        }
    )
    overlay = build_all_overlays(load_registry(), repo_root=REPO_ROOT)["silver_fred_fx"]
    profile = profile_frame(frame, spec)
    candidates = generate_feature_candidates(
        frame,
        profile,
        spec,
        overlay=overlay,
        evidence_index={
            "distributions": "distributions-output",
            "missingness_validity": "missingness-validity-output",
            "temporal_structure": "temporal-structure-output",
        },
    )
    assert candidates
    validator = Draft202012Validator(_schema("feature_candidate.schema.json"))
    for candidate in candidates:
        errors = sorted(
            validator.iter_errors(candidate.to_dict()), key=lambda item: list(item.path)
        )
        assert not errors, [error.message for error in errors]


def test_completed_manifest_requires_immutable_runtime_provenance() -> None:
    validator = Draft202012Validator(_schema("manifest.schema.json"))
    scaffold = {
        "schema_version": "leviathan.silver-eda-campaign/v2",
        "campaign_id": None,
        "table_name": "silver_wasde",
        "source_layer": "silver",
        "analysis_complete": False,
        "status": "pending_batch_campaign",
        "contract_sha256": "1" * 64,
        "spec_sha256": "2" * 64,
    }
    assert not list(validator.iter_errors(scaffold))

    completed = {
        **scaffold,
        "campaign_id": "20260718T000000Z_deadbeef",
        "analysis_complete": True,
        "evidence_valid": True,
    }
    messages = [error.message for error in validator.iter_errors(completed)]
    for field in (
        "git_sha",
        "registry_sha256",
        "image_digest",
        "eda_source_sha256",
        "eda_config_sha256",
    ):
        assert any(field in message for message in messages)

    completed.update(
        {
            "git_sha": "a" * 40,
            "registry_sha256": "b" * 64,
            "image_digest": "sha256:" + "c" * 64,
            "eda_source_sha256": "e" * 64,
            "eda_config_sha256": "d" * 64,
            "analysis_scope": {"source_layer": "silver"},
            "source_inventory_summary": {
                "root_uri": "s3://bucket/silver/wasde",
                "partition_mode": "flat",
                "partition_keys": [],
                "source_mode": "s3",
                "fragment_count": 1,
                "total_bytes": 100,
                "total_rows": 2,
                "row_group_count": 1,
                "footer_complete": True,
                "rejected_key_count": 0,
                "inventory_manifest_sha256": "e" * 64,
            },
            "source_replica": {
                "destination": (
                    "s3://bucket/eda/silver/campaign_id=20260718T000000Z_deadbeef/"
                    "table=silver_wasde/_machine/source_replica"
                ),
                "objects_prefix_uri": (
                    "s3://bucket/eda/silver/campaign_id=20260718T000000Z_deadbeef/"
                    "table=silver_wasde/_machine/source_replica/objects"
                ),
                "manifest_uri": (
                    "s3://bucket/eda/silver/campaign_id=20260718T000000Z_deadbeef/"
                    "table=silver_wasde/_machine/source_replica/manifest.json"
                ),
                "source_manifest_sha256": "e" * 64,
                "replica_manifest_sha256": "f" * 64,
                "object_count": 1,
                "total_bytes": 100,
            },
            "coverage_summary": {
                "exactness": "footer-derived",
                "footer_complete": True,
                "object_count": 1,
                "source_row_count": 2,
                "source_compressed_bytes": 100,
                "partition_stratum_count": 1,
                "analysis_strata_complete": False,
                "analysis_stratum_count": 0,
                "analysis_strata_source_row_count": None,
                "analysis_strata_sampled_row_count": None,
                "represented_analysis_stratum_count": 0,
                "unrepresented_analysis_stratum_count": 0,
            },
            "sampling_strategy": None,
            "sampling_strata": [],
            "sampled_row_group_count": 0,
            "snapshot": {},
            "results": {
                "disposition": "blocked",
                "analysis_exactness": "exact",
                "candidate_count": 0,
                "blocker_count": 1,
                "finding_count": 1,
            },
        }
    )
    artifact_base = (
        "s3://bucket/eda/silver/campaign_id=20260718T000000Z_deadbeef/"
        "table=silver_wasde/"
    )
    machine_paths = {
        "source_inventory": "_machine/source_inventory.json",
        "coverage_catalog": "_machine/coverage_catalog.json",
        "sampling_evidence": "_machine/sampling_evidence.json",
        "reader_evidence": "_machine/reader_evidence.json",
    }
    portable_paths = {
        "spec.yaml",
        "summary.json",
        "feature_candidates.yaml",
        "_machine/profile.json",
        "_machine/feature_candidates.json",
        *machine_paths.values(),
    }
    completed["artifacts"] = {
        path: {
            "uri": artifact_base + path,
            "bytes": 1,
            "sha256": "f" * 64,
        }
        for path in portable_paths
    }
    completed["detailed_evidence"] = {
        name: {
            "relative_key": path,
            **completed["artifacts"][path],
        }
        for name, path in machine_paths.items()
    }
    assert not list(validator.iter_errors(completed))
