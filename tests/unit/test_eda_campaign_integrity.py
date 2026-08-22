from __future__ import annotations

import base64
import hashlib
import io
import json
import zlib
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

# The [eda] extra backs this suite (nbformat/nbclient/jsonschema/matplotlib/IPython ride the
# EDA image, not the base dev env). A dev env without the extra SKIPS loudly instead of
# breaking collection -- the pdfplumber/[batch] precedent (test_pdfpage.py).
for _mod in ("nbformat", "nbclient", "jsonschema", "matplotlib", "IPython"):
    pytest.importorskip(_mod, reason="[eda] extra not installed")

import nbformat
import pytest
import yaml

from jobs.utils import sync_silver_eda_artifacts as sync
from leviathan.eda import cli
from leviathan.eda.campaign import build_table_overlay
from leviathan.eda.models import TableSpec
from leviathan.eda.notebooks import (
    ROOT_SECTIONS,
    SILVER_SECTIONS,
    NotebookContractError,
)
from leviathan.silver.registry import APPROVED_BUCKET, load_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_ID = "20260718T000000Z_integrity"
TABLE = "silver_wasde"


def test_replica_load_precedes_any_live_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table = SimpleNamespace(
        table_name="silver_demo",
        root_uri="s3://leviathan-dev-shahem-001/silver/demo",
    )
    sentinel = object()
    monkeypatch.setattr(cli, "load_s3_replica", lambda **_kwargs: sentinel)

    def reject_live_inventory(*_args, **_kwargs):
        raise AssertionError("completed replica must prevent live Silver inventory")

    monkeypatch.setattr(cli, "inventory_table", reject_live_inventory)
    result = cli._load_or_create_table_replica(
        table=table,
        campaign_id="replica-a",
        bucket=APPROVED_BUCKET,
        s3_client=object(),
        glue_client=object(),
        expected_contract_sha256="a" * 64,
        allow_create=True,
    )
    assert result is sentinel


def test_explicit_prior_replica_campaign_never_falls_back_to_live_silver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table = SimpleNamespace(
        table_name="silver_demo",
        root_uri="s3://leviathan-dev-shahem-001/silver/demo",
    )

    def missing(**_kwargs):
        raise cli.ReplicaNotFound("missing")

    monkeypatch.setattr(cli, "load_s3_replica", missing)
    monkeypatch.setattr(
        cli,
        "inventory_table",
        lambda *_args, **_kwargs: pytest.fail("must not inventory live Silver"),
    )
    with pytest.raises(cli.CampaignError, match="requested replica campaign"):
        cli._load_or_create_table_replica(
            table=table,
            campaign_id="prior-a",
            bucket=APPROVED_BUCKET,
            s3_client=object(),
            glue_client=object(),
            expected_contract_sha256="a" * 64,
            allow_create=False,
        )


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, default=str) + "\n"
    ).encode("utf-8")


def _yaml_bytes(value: Any) -> bytes:
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True, width=100).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _executed_notebook(
    *,
    table: str | None,
    campaign_id: str,
    frame_uri_override: str | None = None,
) -> bytes:
    sections = SILVER_SECTIONS if table else ROOT_SECTIONS
    cells = [
        nbformat.v4.new_markdown_cell(f"## {title}", id=cell_id) for cell_id, title in sections
    ]
    frame_uri = None
    portable_manifest_uri = None
    frozen_frame_sha256 = None
    if table:
        prefix = f"{sync.campaign_prefix(campaign_id)}/table={table}"
        frame_uri = f"s3://{APPROVED_BUCKET}/{prefix}/_machine/snapshot/part-000.parquet"
        if frame_uri_override is not None:
            frame_uri = frame_uri_override
        portable_manifest_uri = f"s3://{APPROVED_BUCKET}/{prefix}/manifest.json"
        frozen_frame_sha256 = "e" * 64
        payload = {
            "summary": {},
            "overlay": {},
            "contract": {},
            "provenance": {
                "campaign_id": campaign_id,
                "frozen_frame_sha256": frozen_frame_sha256,
            },
            "frame_uri": frame_uri,
            "manifest_uri": portable_manifest_uri,
        }
        encoded = base64.b64encode(
            zlib.compress(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
        ).decode("ascii")
        setup = nbformat.v4.new_code_cell(f'_PAYLOAD_B64 = "{encoded}"', id="parameters-and-setup")
        setup.execution_count = 1
        cells.append(setup)
    for index in range(3):
        cell = nbformat.v4.new_code_cell(f"# embedded chart {index}", id=f"chart-{index}")
        cell.execution_count = index + 2
        cell.outputs = [
            nbformat.v4.new_output(
                "display_data",
                data={"image/png": "AA==", "text/plain": "<Figure>"},
                metadata={},
            )
        ]
        cells.append(cell)
    notebook = nbformat.v4.new_notebook(cells=cells)
    notebook.metadata["leviathan_eda"] = {
        "schema_version": 1,
        "campaign_id": campaign_id,
        "frame_uri": frame_uri,
        "portable_manifest_uri": portable_manifest_uri,
        "frozen_frame_sha256": frozen_frame_sha256,
        "source_only": True,
        "mandatory_sections": [cell_id for cell_id, _ in sections],
    }
    if table:
        notebook.metadata["leviathan_eda"]["table_name"] = table
    return nbformat.writes(notebook).encode("utf-8")


def _table_artifacts() -> tuple[dict[str, bytes], dict[str, Any]]:
    registry = load_registry()
    contract = registry.table(TABLE)
    overlay = build_table_overlay(contract, repo_root=REPO_ROOT)
    runtime = {
        "git_sha": "a" * 40,
        "image_digest": "sha256:" + "b" * 64,
        "eda_source_sha256": "9" * 64,
        "eda_config_sha256": "c" * 64,
    }
    provenance_identity = {
        "registry_sha256": sync._registry_hash(registry),
        "contract_sha256": TableSpec.from_contract(contract).contract_hash,
        "spec_sha256": sync._sha256_json(overlay),
    }
    scope = {
        "source_layer": "silver",
        "legacy_gold_read": False,
        "model_ready_read": False,
        "target_aware_analysis": False,
        "production_feature_config_mutated": False,
    }
    summary = {
        "table_name": TABLE,
        "analysis_scope": scope,
        "provenance": {
            "campaign_id": CAMPAIGN_ID,
            **runtime,
            **provenance_identity,
        },
        "profile": {
            "table_name": TABLE,
            "disposition": "blocked",
            "analysis_exactness": "exact",
        },
    }
    reader_evidence = {
        "schema_version": "leviathan.silver-eda-reader-evidence/v1",
        "table_name": TABLE,
        "archetype": overlay["archetype"],
    }
    summary["reader"] = reader_evidence
    candidates = {
        "schema_version": "leviathan.feature-candidates/v1",
        "table_name": TABLE,
        "analysis_scope": "source-only canonical Silver; review-only",
        "production_feature_config_mutated": False,
        "candidate_count": 0,
        "no_candidate_reason": "test",
        "candidates": [],
    }
    portable = {
        "spec.yaml": _yaml_bytes(overlay),
        "summary.json": _json_bytes(summary),
        "feature_candidates.yaml": _yaml_bytes(candidates),
        f"{TABLE}_eda.ipynb": _executed_notebook(table=TABLE, campaign_id=CAMPAIGN_ID),
    }
    machine_candidates = _json_bytes(candidates)
    profile_bytes = _json_bytes(
        {
            "table_name": TABLE,
            "disposition": "blocked",
            "analysis_exactness": "exact",
        }
    )
    table_prefix = f"{sync.campaign_prefix(CAMPAIGN_ID)}/table={TABLE}"
    snapshot_prefix = f"{table_prefix}/_machine/snapshot"
    source_key_prefix = contract["s3_root"].split(f"s3://{APPROVED_BUCKET}/", 1)[1]
    source_object = {
        "uri": f"s3://{APPROVED_BUCKET}/{source_key_prefix}/part-000.parquet",
        "bucket": APPROVED_BUCKET,
        "key": f"{source_key_prefix}/part-000.parquet",
        "size": 100,
        "etag": "source-etag",
        "last_modified": "2026-07-18T00:00:00Z",
        "version_id": None,
        "checksum_sha256": None,
        "identity": "etag:source-etag",
        "partition_values": {},
        "footer": {
            "row_count": 2,
            "row_group_count": 1,
            "columns": [{"name": "estimate", "type": "double"}],
            "schema_sha256": "d" * 64,
            "created_by": "test",
            "row_group_rows": [2],
        },
    }
    source_inventory = {
        "table_name": TABLE,
        "layer": "silver",
        "bucket": APPROVED_BUCKET,
        "root_uri": contract["s3_root"],
        "partition_mode": contract["partition_mode"],
        "partition_keys": [item["name"] for item in contract["partition_keys"]],
        "contract_sha256": provenance_identity["contract_sha256"],
        "registry_fingerprint": {},
        "objects": [source_object],
        "source_mode": "s3",
        "rejected_keys": [],
    }
    source_manifest_sha = cli._sha256_compact_json(source_inventory)
    source_inventory.update(
        {
            "fragment_count": 1,
            "total_bytes": 100,
            "total_rows": 2,
            "manifest_sha256": source_manifest_sha,
        }
    )
    parquet_payload = b"parquet-evidence"
    parquet_sha256 = _sha(parquet_payload)
    snapshot_manifest = {
        "schema_version": 1,
        "campaign_id": CAMPAIGN_ID,
        "table_name": TABLE,
        "source_layer": "silver",
        "source_root": contract["s3_root"],
        "source_manifest_sha256": source_manifest_sha,
        "source_inventory": source_inventory,
        "snapshot_policy": {
            "exactness": "exact",
            "identity_columns": ["estimate"],
            "reason": "fixture exact frame",
            "seed": 123,
            "snapshot_row_count": 2,
            "source_compressed_bytes": 100,
            "source_row_count": 2,
            "stratum_columns": ["estimate"],
        },
        "frozen_frame_sha256": "e" * 64,
        "parquet_sha256": parquet_sha256,
        "parquet_bytes": len(parquet_payload),
        "parquet_file": "part-000.parquet",
    }
    snapshot_manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps(
            snapshot_manifest,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    snapshot_artifact = {
        "table_name": TABLE,
        "campaign_id": CAMPAIGN_ID,
        "destination": f"s3://{APPROVED_BUCKET}/{snapshot_prefix}",
        "parquet_uri": f"s3://{APPROVED_BUCKET}/{snapshot_prefix}/part-000.parquet",
        "manifest_uri": f"s3://{APPROVED_BUCKET}/{snapshot_prefix}/manifest.json",
        "frame_sha256": snapshot_manifest["frozen_frame_sha256"],
        "parquet_sha256": snapshot_manifest["parquet_sha256"],
        "parquet_bytes": snapshot_manifest["parquet_bytes"],
        "manifest_sha256": snapshot_manifest["manifest_sha256"],
        "decision": snapshot_manifest["snapshot_policy"],
    }
    replica_prefix = f"{table_prefix}/_machine/source_replica"
    replica_objects_prefix = f"{replica_prefix}/objects"
    replica_object_key = f"{replica_objects_prefix}/part-000.parquet"
    replica_object_payload = b"r" * 100
    replica_manifest = {
        "schema_version": 1,
        "artifact_type": "immutable_silver_source_replica",
        "campaign_id": CAMPAIGN_ID,
        "table_name": TABLE,
        "source_layer": "silver",
        "source_root_uri": contract["s3_root"],
        "source_manifest_sha256": source_manifest_sha,
        "source_inventory": source_inventory,
        "source_object_count": 1,
        "source_total_bytes": 100,
        "replica_prefix_uri": f"s3://{APPROVED_BUCKET}/{replica_prefix}",
        "objects_prefix_uri": f"s3://{APPROVED_BUCKET}/{replica_objects_prefix}",
        "objects": [
            {
                "source": {
                    key: source_object.get(key)
                    for key in (
                        "uri",
                        "key",
                        "size",
                        "etag",
                        "version_id",
                        "checksum_sha256",
                        "identity",
                    )
                },
                "destination": {
                    "uri": f"s3://{APPROVED_BUCKET}/{replica_object_key}",
                    "key": replica_object_key,
                    "size": 100,
                    "etag": "replica-etag",
                    "version_id": "replica-version",
                    "checksum_sha256": None,
                    "identity": "version:replica-version",
                },
                "copy_guard": "etag:source-etag",
            }
        ],
    }
    replica_manifest["replica_manifest_sha256"] = cli._sha256_compact_json(replica_manifest)
    source_replica = {
        "destination": f"s3://{APPROVED_BUCKET}/{replica_prefix}",
        "objects_prefix_uri": f"s3://{APPROVED_BUCKET}/{replica_objects_prefix}",
        "manifest_uri": f"s3://{APPROVED_BUCKET}/{replica_prefix}/manifest.json",
        "source_manifest_sha256": source_manifest_sha,
        "replica_manifest_sha256": replica_manifest["replica_manifest_sha256"],
        "object_count": 1,
        "total_bytes": 100,
    }
    summary["provenance"].update(
        {
            "snapshot_uri": snapshot_artifact["parquet_uri"],
            "snapshot_manifest_uri": snapshot_artifact["manifest_uri"],
            "frozen_frame_sha256": snapshot_artifact["frame_sha256"],
            "snapshot_policy": snapshot_artifact["decision"],
            "portable_manifest_uri": (f"s3://{APPROVED_BUCKET}/{table_prefix}/manifest.json"),
            "source_replica": source_replica,
        }
    )
    portable["summary.json"] = _json_bytes(summary)
    coverage_catalog = {
        "exactness": "footer-derived",
        "footer_complete": True,
        "object_count": 1,
        "source_row_count": 2,
        "source_compressed_bytes": 100,
        "partition_strata": [
            {
                "partition_values": {},
                "object_count": 1,
                "row_count": 2,
                "row_group_count": 1,
                "rows_known": True,
            }
        ],
        "objects": [
            {
                "key": source_object["key"],
                "partition_values": {},
                "row_count": 2,
                "row_group_count": 1,
                "schema_sha256": "d" * 64,
            }
        ],
    }
    sampling_evidence = {
        "sample_seed": None,
        "sampling_strategy": None,
        "sampling_strata": [],
        "sampled_row_groups": [],
    }
    machine_evidence = {
        cli.MACHINE_EVIDENCE_FILES["source_inventory"]: _json_bytes(
            cli._machine_evidence_document(
                campaign_id=CAMPAIGN_ID,
                table_name=TABLE,
                evidence_key="source_inventory",
                evidence=source_inventory,
            )
        ),
        cli.MACHINE_EVIDENCE_FILES["coverage_catalog"]: _json_bytes(
            cli._machine_evidence_document(
                campaign_id=CAMPAIGN_ID,
                table_name=TABLE,
                evidence_key="coverage_catalog",
                evidence=coverage_catalog,
            )
        ),
        cli.MACHINE_EVIDENCE_FILES["sampling_evidence"]: _json_bytes(
            cli._machine_evidence_document(
                campaign_id=CAMPAIGN_ID,
                table_name=TABLE,
                evidence_key="sampling_evidence",
                evidence=sampling_evidence,
            )
        ),
        cli.MACHINE_EVIDENCE_FILES["reader_evidence"]: _json_bytes(
            cli._machine_evidence_document(
                campaign_id=CAMPAIGN_ID,
                table_name=TABLE,
                evidence_key="reader_evidence",
                evidence=reader_evidence,
            )
        ),
    }
    all_artifacts = {
        **portable,
        "_machine/profile.json": profile_bytes,
        "_machine/feature_candidates.json": machine_candidates,
        **machine_evidence,
    }
    artifact_records = {
        leaf: {
            "uri": f"s3://{APPROVED_BUCKET}/{table_prefix}/{leaf}",
            "sha256": _sha(payload),
            "bytes": len(payload),
        }
        for leaf, payload in all_artifacts.items()
    }
    manifest = {
        "schema_version": cli.SCHEMA_VERSION,
        "campaign_id": CAMPAIGN_ID,
        "table_name": TABLE,
        "source_layer": "silver",
        "analysis_complete": True,
        "evidence_valid": True,
        "analysis_scope": scope,
        **runtime,
        **provenance_identity,
        "source_inventory_summary": cli._source_inventory_summary(source_inventory),
        "source_replica": source_replica,
        "coverage_summary": cli._coverage_summary(coverage_catalog),
        "sampling_strategy": None,
        "sampling_strata": [],
        "sampled_row_group_count": 0,
        "snapshot": snapshot_artifact,
        "results": {
            "disposition": "blocked",
            "analysis_exactness": "exact",
            "candidate_count": 0,
            "blocker_count": 0,
            "finding_count": 0,
        },
        "detailed_evidence": {
            name: {
                "relative_key": relative_key,
                **artifact_records[relative_key],
            }
            for name, relative_key in cli.MACHINE_EVIDENCE_FILES.items()
        },
        "artifacts": artifact_records,
    }
    objects = {f"{table_prefix}/{leaf}": payload for leaf, payload in portable.items()}
    objects.update(
        {
            f"{table_prefix}/manifest.json": _json_bytes(manifest),
            f"{table_prefix}/_machine/profile.json": profile_bytes,
            f"{table_prefix}/_machine/feature_candidates.json": machine_candidates,
            **{f"{table_prefix}/{leaf}": payload for leaf, payload in machine_evidence.items()},
            f"{snapshot_prefix}/manifest.json": _json_bytes(snapshot_manifest),
            f"{snapshot_prefix}/part-000.parquet": parquet_payload,
            f"{replica_prefix}/manifest.json": _json_bytes(replica_manifest),
            replica_object_key: replica_object_payload,
        }
    )
    return objects, manifest


def _complete_campaign_objects() -> dict[str, bytes]:
    objects, manifest = _table_artifacts()
    prefix = sync.campaign_prefix(CAMPAIGN_ID)
    catalog = {
        "schema_version": "leviathan.feature-candidate-catalog/v1",
        "campaign_id": CAMPAIGN_ID,
        "tables": {TABLE: {"candidate_count": 0, "candidates": []}},
    }
    root_notebook = _executed_notebook(table=None, campaign_id=CAMPAIGN_ID)
    catalog_bytes = _yaml_bytes(catalog)
    campaign_manifest = {
        "schema_version": cli.SCHEMA_VERSION,
        "campaign_id": CAMPAIGN_ID,
        "registry_sha256": manifest["registry_sha256"],
        "git_sha": manifest["git_sha"],
        "image_digest": manifest["image_digest"],
        "eda_source_sha256": manifest["eda_source_sha256"],
        "eda_config_sha256": manifest["eda_config_sha256"],
        "expected_tables": [TABLE],
        "table_count": 1,
        "complete": True,
        "root_artifacts": {
            "00_feature_engineering_readiness.ipynb": {
                "sha256": _sha(root_notebook),
                "bytes": len(root_notebook),
            },
            "feature_candidate_catalog.yaml": {
                "sha256": _sha(catalog_bytes),
                "bytes": len(catalog_bytes),
            },
        },
        "table_manifest_sha256": {TABLE: sync._sha256_json(manifest)},
    }
    campaign_manifest_bytes = _json_bytes(campaign_manifest)
    finalize_marker = {
        "campaign_id": CAMPAIGN_ID,
        "registry_sha256": manifest["registry_sha256"],
        "campaign_manifest_sha256": _sha(campaign_manifest_bytes),
        "git_sha": manifest["git_sha"],
        "image_digest": manifest["image_digest"],
        "eda_source_sha256": manifest["eda_source_sha256"],
        "eda_config_sha256": manifest["eda_config_sha256"],
    }
    objects.update(
        {
            f"{prefix}/00_feature_engineering_readiness.ipynb": root_notebook,
            f"{prefix}/feature_candidate_catalog.yaml": catalog_bytes,
            f"{prefix}/campaign_manifest.json": campaign_manifest_bytes,
            f"{prefix}/{sync.FINALIZE_MARKER}": _json_bytes(finalize_marker),
        }
    )
    return objects


def _replace_table_artifact(
    objects: dict[str, bytes],
    manifest: dict[str, Any],
    *,
    leaf: str,
    payload: bytes,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    mutated_objects = deepcopy(objects)
    mutated_manifest = deepcopy(manifest)
    table_prefix = f"{sync.campaign_prefix(CAMPAIGN_ID)}/table={TABLE}"
    mutated_objects[f"{table_prefix}/{leaf}"] = payload
    record = {
        "uri": f"s3://{APPROVED_BUCKET}/{table_prefix}/{leaf}",
        "sha256": _sha(payload),
        "bytes": len(payload),
    }
    mutated_manifest["artifacts"][leaf] = record
    for name, relative_key in cli.MACHINE_EVIDENCE_FILES.items():
        if relative_key == leaf:
            mutated_manifest["detailed_evidence"][name] = {
                "relative_key": relative_key,
                **record,
            }
    mutated_objects[f"{table_prefix}/manifest.json"] = _json_bytes(mutated_manifest)
    return mutated_objects, mutated_manifest


class _ObjectStore:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    def head_object(
        self, *, Bucket: str, Key: str, ChecksumMode: str | None = None
    ) -> dict[str, Any]:
        assert Bucket == APPROVED_BUCKET
        payload = self.objects[Key]
        if "/_machine/source_replica/objects/" in Key:
            assert ChecksumMode is None
            return {
                "ContentLength": len(payload),
                "ETag": '"replica-etag"',
                "VersionId": "replica-version",
            }
        if "/_machine/snapshot/" in Key and Key.endswith("part-000.parquet"):
            assert ChecksumMode == "ENABLED"
            _, manifest = _table_artifacts()
            snapshot = manifest["snapshot"]
            return {
                "ContentLength": len(payload),
                "ChecksumSHA256": base64.b64encode(hashlib.sha256(payload).digest()).decode(
                    "ascii"
                ),
                "Metadata": {
                    "sha256": snapshot["parquet_sha256"],
                    "frame-sha256": snapshot["frame_sha256"],
                    "campaign-id": CAMPAIGN_ID,
                    "table-name": TABLE,
                },
            }
        return {"ContentLength": len(payload)}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        assert Bucket == APPROVED_BUCKET
        return {"Body": io.BytesIO(self.objects[Key])}

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        assert bucket == APPROVED_BUCKET
        Path(filename).write_bytes(self.objects[key])


def test_portable_manifest_v2_is_compact_and_binds_full_machine_evidence() -> None:
    objects, manifest = _table_artifacts()
    table_prefix = f"{sync.campaign_prefix(CAMPAIGN_ID)}/table={TABLE}"
    manifest_bytes = objects[f"{table_prefix}/manifest.json"]

    assert manifest["schema_version"] == cli.SCHEMA_VERSION
    assert len(manifest_bytes) <= cli.PORTABLE_MANIFEST_SIZE_LIMIT_BYTES
    assert not {"source_inventory", "coverage_catalog", "sampled_row_groups"}.intersection(manifest)
    assert set(manifest["detailed_evidence"]) == set(cli.MACHINE_EVIDENCE_FILES)
    for name, relative_key in cli.MACHINE_EVIDENCE_FILES.items():
        payload = objects[f"{table_prefix}/{relative_key}"]
        record = manifest["detailed_evidence"][name]
        assert record == {"relative_key": relative_key, **manifest["artifacts"][relative_key]}
        assert record["bytes"] == len(payload)
        assert record["sha256"] == _sha(payload)


def test_runtime_identity_requires_and_cross_checks_source_fingerprint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_path = tmp_path / "eda-build.json"
    identity = {
        "git_sha": "a" * 40,
        "image_digest": "sha256:" + "b" * 64,
        "eda_source_sha256": "c" * 64,
        "eda_config_sha256": "d" * 64,
    }
    metadata_path.write_text(
        json.dumps(
            {
                "eda_source_fingerprint": "leviathan.eda-source/v1",
                "git_sha": identity["git_sha"],
                "eda_source_sha256": identity["eda_source_sha256"],
                "eda_config_sha256": identity["eda_config_sha256"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEVIATHAN_GIT_SHA", identity["git_sha"])
    monkeypatch.setenv("LEVIATHAN_EDA_IMAGE_DIGEST", identity["image_digest"])
    monkeypatch.setenv("LEVIATHAN_EDA_SOURCE_SHA", identity["eda_source_sha256"])
    monkeypatch.setenv("LEVIATHAN_EDA_CONFIG_SHA", identity["eda_config_sha256"])
    monkeypatch.setenv("LEVIATHAN_EDA_BUILD_METADATA", str(metadata_path))
    monkeypatch.setenv("LEVIATHAN_EDA_REQUIRE_BUILD_METADATA", "1")

    assert cli._runtime_identity() == identity

    monkeypatch.setenv("LEVIATHAN_EDA_SOURCE_SHA", "e" * 64)
    with pytest.raises(cli.CampaignError, match="differs from image build metadata"):
        cli._runtime_identity()

    monkeypatch.delenv("LEVIATHAN_EDA_SOURCE_SHA")
    with pytest.raises(cli.CampaignError, match="identity is incomplete"):
        cli._runtime_identity()


def test_finalizer_validates_full_table_evidence_and_runtime_identity(tmp_path: Path) -> None:
    objects, manifest = _table_artifacts()
    registry = load_registry()
    overlay = build_table_overlay(registry.table(TABLE), repo_root=REPO_ROOT)
    result = cli._validate_table_artifacts(
        client=_ObjectStore(objects),
        bucket=APPROVED_BUCKET,
        prefix=sync.campaign_prefix(CAMPAIGN_ID),
        table_name=TABLE,
        campaign_id=CAMPAIGN_ID,
        registry_sha256=manifest["registry_sha256"],
        contract_sha256=manifest["contract_sha256"],
        spec_sha256=manifest["spec_sha256"],
        expected_spec=overlay,
        runtime_identity={
            key: manifest[key]
            for key in (
                "git_sha",
                "image_digest",
                "eda_source_sha256",
                "eda_config_sha256",
            )
        },
        temp=tmp_path,
    )
    assert result[0]["evidence_valid"] is True

    with pytest.raises(cli.CampaignError, match="stale, cross-campaign, or incomplete"):
        cli._validate_table_artifacts(
            client=_ObjectStore(objects),
            bucket=APPROVED_BUCKET,
            prefix=sync.campaign_prefix(CAMPAIGN_ID),
            table_name=TABLE,
            campaign_id=CAMPAIGN_ID,
            registry_sha256=manifest["registry_sha256"],
            contract_sha256=manifest["contract_sha256"],
            spec_sha256=manifest["spec_sha256"],
            expected_spec=overlay,
            runtime_identity={**manifest, "image_digest": "sha256:" + "0" * 64},
            temp=tmp_path,
        )


def test_replica_validator_accepts_recorded_prior_campaign_namespace() -> None:
    objects, portable_manifest = _table_artifacts()
    output_table_prefix = f"{sync.campaign_prefix(CAMPAIGN_ID)}/table={TABLE}"
    current_prefix = f"{output_table_prefix}/_machine/source_replica"
    prior_campaign = "prior-replica-campaign"
    prior_prefix = f"eda/silver/campaign_id={prior_campaign}/table={TABLE}/_machine/source_replica"
    current_manifest_key = f"{current_prefix}/manifest.json"
    current_object_key = f"{current_prefix}/objects/part-000.parquet"
    prior_manifest_key = f"{prior_prefix}/manifest.json"
    prior_object_key = f"{prior_prefix}/objects/part-000.parquet"
    replica_manifest = json.loads(objects.pop(current_manifest_key))
    objects[prior_object_key] = objects.pop(current_object_key)
    replica_manifest["campaign_id"] = prior_campaign
    replica_manifest["replica_prefix_uri"] = f"s3://{APPROVED_BUCKET}/{prior_prefix}"
    replica_manifest["objects_prefix_uri"] = f"s3://{APPROVED_BUCKET}/{prior_prefix}/objects"
    destination = replica_manifest["objects"][0]["destination"]
    destination["key"] = prior_object_key
    destination["uri"] = f"s3://{APPROVED_BUCKET}/{prior_object_key}"
    replica_manifest.pop("replica_manifest_sha256")
    replica_manifest["replica_manifest_sha256"] = cli._sha256_compact_json(replica_manifest)
    objects[prior_manifest_key] = _json_bytes(replica_manifest)
    source_replica = portable_manifest["source_replica"]
    source_replica.update(
        {
            "destination": f"s3://{APPROVED_BUCKET}/{prior_prefix}",
            "objects_prefix_uri": f"s3://{APPROVED_BUCKET}/{prior_prefix}/objects",
            "manifest_uri": f"s3://{APPROVED_BUCKET}/{prior_manifest_key}",
            "replica_manifest_sha256": replica_manifest["replica_manifest_sha256"],
        }
    )
    source_document = json.loads(
        objects[f"{output_table_prefix}/{cli.MACHINE_EVIDENCE_FILES['source_inventory']}"]
    )["source_inventory"]

    cli._validate_replica_evidence(
        client=_ObjectStore(objects),
        bucket=APPROVED_BUCKET,
        table_prefix=output_table_prefix,
        table_name=TABLE,
        campaign_id=CAMPAIGN_ID,
        manifest=portable_manifest,
        source_inventory=source_document,
    )


def test_finalizer_rejects_summary_and_machine_profile_identity_drift(
    tmp_path: Path,
) -> None:
    objects, manifest = _table_artifacts()
    registry = load_registry()
    overlay = build_table_overlay(registry.table(TABLE), repo_root=REPO_ROOT)
    common = {
        "bucket": APPROVED_BUCKET,
        "prefix": sync.campaign_prefix(CAMPAIGN_ID),
        "table_name": TABLE,
        "campaign_id": CAMPAIGN_ID,
        "registry_sha256": manifest["registry_sha256"],
        "contract_sha256": manifest["contract_sha256"],
        "spec_sha256": manifest["spec_sha256"],
        "expected_spec": overlay,
        "runtime_identity": {
            key: manifest[key]
            for key in (
                "git_sha",
                "image_digest",
                "eda_source_sha256",
                "eda_config_sha256",
            )
        },
        "temp": tmp_path,
    }

    table_prefix = f"{sync.campaign_prefix(CAMPAIGN_ID)}/table={TABLE}"
    summary = json.loads(objects[f"{table_prefix}/summary.json"])
    summary["provenance"]["registry_sha256"] = "0" * 64
    bad_objects, _ = _replace_table_artifact(
        objects,
        manifest,
        leaf="summary.json",
        payload=_json_bytes(summary),
    )
    with pytest.raises(cli.CampaignError, match="summary provenance mismatch"):
        cli._validate_table_artifacts(client=_ObjectStore(bad_objects), **common)

    machine_profile = json.loads(objects[f"{table_prefix}/_machine/profile.json"])
    machine_profile["disposition"] = "ready"
    bad_objects, _ = _replace_table_artifact(
        objects,
        manifest,
        leaf="_machine/profile.json",
        payload=_json_bytes(machine_profile),
    )
    with pytest.raises(cli.CampaignError, match="machine/portable profile identity mismatch"):
        cli._validate_table_artifacts(client=_ObjectStore(bad_objects), **common)


def test_finalizer_rejects_snapshot_checksum_inventory_and_notebook_drift(
    tmp_path: Path,
) -> None:
    objects, manifest = _table_artifacts()
    registry = load_registry()
    overlay = build_table_overlay(registry.table(TABLE), repo_root=REPO_ROOT)
    common = {
        "bucket": APPROVED_BUCKET,
        "prefix": sync.campaign_prefix(CAMPAIGN_ID),
        "table_name": TABLE,
        "campaign_id": CAMPAIGN_ID,
        "registry_sha256": manifest["registry_sha256"],
        "contract_sha256": manifest["contract_sha256"],
        "spec_sha256": manifest["spec_sha256"],
        "expected_spec": overlay,
        "runtime_identity": {
            key: manifest[key]
            for key in (
                "git_sha",
                "image_digest",
                "eda_source_sha256",
                "eda_config_sha256",
            )
        },
        "temp": tmp_path,
    }
    table_prefix = f"{sync.campaign_prefix(CAMPAIGN_ID)}/table={TABLE}"

    corrupt_parquet = deepcopy(objects)
    corrupt_parquet[f"{table_prefix}/_machine/snapshot/part-000.parquet"] = b"PARQUET-EVIDENCE"
    with pytest.raises(cli.CampaignError, match="hash metadata mismatch"):
        cli._validate_table_artifacts(client=_ObjectStore(corrupt_parquet), **common)

    corrupt_replica = deepcopy(objects)
    corrupt_replica[f"{table_prefix}/_machine/source_replica/objects/part-000.parquet"] = b"r" * 99
    with pytest.raises(cli.CampaignError, match="replica object identity drift"):
        cli._validate_table_artifacts(client=_ObjectStore(corrupt_replica), **common)

    inventory_leaf = cli.MACHINE_EVIDENCE_FILES["source_inventory"]
    inventory_document = json.loads(objects[f"{table_prefix}/{inventory_leaf}"])
    inventory_document["source_inventory"]["total_rows"] = 999
    corrupt_inventory, _ = _replace_table_artifact(
        objects,
        manifest,
        leaf=inventory_leaf,
        payload=_json_bytes(inventory_document),
    )
    with pytest.raises(cli.CampaignError, match="source inventory hash/totals mismatch"):
        cli._validate_table_artifacts(client=_ObjectStore(corrupt_inventory), **common)

    foreign_frame = (
        f"s3://{APPROVED_BUCKET}/eda/silver/campaign_id=foreign/"
        f"table={TABLE}/_machine/snapshot/part-000.parquet"
    )
    foreign_notebook = _executed_notebook(
        table=TABLE,
        campaign_id=CAMPAIGN_ID,
        frame_uri_override=foreign_frame,
    )
    corrupt_notebook, _ = _replace_table_artifact(
        objects,
        manifest,
        leaf=f"{TABLE}_eda.ipynb",
        payload=foreign_notebook,
    )
    with pytest.raises(NotebookContractError, match="snapshot/campaign identity mismatch"):
        cli._validate_table_artifacts(client=_ObjectStore(corrupt_notebook), **common)


def test_finalizer_recomputes_full_coverage_evidence(tmp_path: Path) -> None:
    objects, manifest = _table_artifacts()
    registry = load_registry()
    overlay = build_table_overlay(registry.table(TABLE), repo_root=REPO_ROOT)
    table_prefix = f"{sync.campaign_prefix(CAMPAIGN_ID)}/table={TABLE}"
    coverage_leaf = cli.MACHINE_EVIDENCE_FILES["coverage_catalog"]
    coverage_document = json.loads(objects[f"{table_prefix}/{coverage_leaf}"])
    coverage_document["coverage_catalog"]["source_row_count"] = 999
    bad_objects, bad_manifest = _replace_table_artifact(
        objects,
        manifest,
        leaf=coverage_leaf,
        payload=_json_bytes(coverage_document),
    )
    bad_manifest["coverage_summary"] = cli._coverage_summary(coverage_document["coverage_catalog"])
    bad_objects[f"{table_prefix}/manifest.json"] = _json_bytes(bad_manifest)

    with pytest.raises(cli.CampaignError, match="coverage catalog source totals mismatch"):
        cli._validate_table_artifacts(
            client=_ObjectStore(bad_objects),
            bucket=APPROVED_BUCKET,
            prefix=sync.campaign_prefix(CAMPAIGN_ID),
            table_name=TABLE,
            campaign_id=CAMPAIGN_ID,
            registry_sha256=manifest["registry_sha256"],
            contract_sha256=manifest["contract_sha256"],
            spec_sha256=manifest["spec_sha256"],
            expected_spec=overlay,
            runtime_identity={
                key: manifest[key]
                for key in (
                    "git_sha",
                    "image_digest",
                    "eda_source_sha256",
                    "eda_config_sha256",
                )
            },
            temp=tmp_path,
        )


def test_finalizer_does_not_claim_marker_before_dossier_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NoWrites:
        def __init__(self) -> None:
            self.puts: list[dict[str, Any]] = []

        def put_object(self, **kwargs: Any) -> None:
            self.puts.append(kwargs)

    client = _NoWrites()
    monkeypatch.setenv("LEVIATHAN_EDA_IMAGE_DIGEST", "sha256:" + "1" * 64)
    monkeypatch.setenv("LEVIATHAN_EDA_SOURCE_SHA", "3" * 64)
    monkeypatch.setenv("LEVIATHAN_EDA_CONFIG_SHA", "2" * 64)
    monkeypatch.setattr(cli.boto3, "client", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(
        cli,
        "_validate_table_artifacts",
        lambda **_kwargs: (_ for _ in ()).throw(cli.CampaignError("invalid dossier")),
    )

    with pytest.raises(cli.CampaignError, match="invalid dossier"):
        cli.finalize_campaign(
            campaign_id=CAMPAIGN_ID,
            bucket=APPROVED_BUCKET,
            aws_region="us-east-1",
            output_prefix=sync.campaign_prefix(CAMPAIGN_ID),
        )
    assert client.puts == []


def test_sync_validates_campaign_manifest_and_swaps_complete_table_directory(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "eda"
    existing = destination / TABLE
    existing.mkdir(parents=True)
    (existing / "target_readiness_appendix.ipynb").write_text("preserve me", encoding="utf-8")
    objects = _complete_campaign_objects()
    plan = sync.build_sync_plan(
        campaign_id=CAMPAIGN_ID,
        tables=[TABLE],
        destination=destination,
        include_root=True,
    )
    sync.sync_artifacts(
        client=_ObjectStore(objects),
        bucket=APPROVED_BUCKET,
        plan=plan,
    )

    assert (destination / "campaign_manifest.json").exists()
    assert not (destination / sync.FINALIZE_MARKER).exists()
    assert (destination / TABLE / "spec.yaml").exists()
    assert (destination / TABLE / "target_readiness_appendix.ipynb").read_text(
        encoding="utf-8"
    ) == "preserve me"


def test_sync_rejects_spec_drift_before_touching_destination(tmp_path: Path) -> None:
    destination = tmp_path / "eda"
    existing = destination / TABLE
    existing.mkdir(parents=True)
    sentinel = existing / "sentinel.txt"
    sentinel.write_text("unchanged", encoding="utf-8")
    objects, manifest = _table_artifacts()
    bad_spec = _yaml_bytes({"table_name": TABLE, "title": "stale spec"})
    objects, _ = _replace_table_artifact(
        objects,
        manifest,
        leaf="spec.yaml",
        payload=bad_spec,
    )
    plan = sync.build_sync_plan(
        campaign_id=CAMPAIGN_ID,
        tables=[TABLE],
        destination=destination,
        include_root=False,
    )

    with pytest.raises(ValueError, match="invalid portable"):
        sync.sync_artifacts(
            client=_ObjectStore(objects),
            bucket=APPROVED_BUCKET,
            plan=plan,
        )
    assert sentinel.read_text(encoding="utf-8") == "unchanged"


def test_sync_rejects_bulky_v1_manifest_shape_before_replacement(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "eda"
    existing = destination / TABLE
    existing.mkdir(parents=True)
    sentinel = existing / "sentinel.txt"
    sentinel.write_text("unchanged", encoding="utf-8")
    objects, manifest = _table_artifacts()
    table_prefix = f"{sync.campaign_prefix(CAMPAIGN_ID)}/table={TABLE}"
    manifest["coverage_catalog"] = {"analysis_strata": []}
    objects[f"{table_prefix}/manifest.json"] = _json_bytes(manifest)
    plan = sync.build_sync_plan(
        campaign_id=CAMPAIGN_ID,
        tables=[TABLE],
        destination=destination,
        include_root=False,
    )

    with pytest.raises(ValueError, match="stale, cross-campaign, or incomplete"):
        sync.sync_artifacts(
            client=_ObjectStore(objects),
            bucket=APPROVED_BUCKET,
            plan=plan,
        )
    assert sentinel.read_text(encoding="utf-8") == "unchanged"


def test_sync_rejects_campaign_manifest_root_hash_drift(tmp_path: Path) -> None:
    destination = tmp_path / "eda"
    destination.mkdir()
    sentinel = destination / "00_feature_engineering_readiness.ipynb"
    sentinel.write_text("old root", encoding="utf-8")
    objects = _complete_campaign_objects()
    key = f"{sync.campaign_prefix(CAMPAIGN_ID)}/campaign_manifest.json"
    campaign_manifest = json.loads(objects[key])
    campaign_manifest["root_artifacts"]["00_feature_engineering_readiness.ipynb"]["sha256"] = (
        "0" * 64
    )
    campaign_manifest_bytes = _json_bytes(campaign_manifest)
    objects[key] = campaign_manifest_bytes
    marker_key = f"{sync.campaign_prefix(CAMPAIGN_ID)}/{sync.FINALIZE_MARKER}"
    marker = json.loads(objects[marker_key])
    marker["campaign_manifest_sha256"] = _sha(campaign_manifest_bytes)
    objects[marker_key] = _json_bytes(marker)
    plan = sync.build_sync_plan(
        campaign_id=CAMPAIGN_ID,
        tables=[TABLE],
        destination=destination,
        include_root=True,
    )

    with pytest.raises(ValueError, match="root hash mismatch"):
        sync.sync_artifacts(
            client=_ObjectStore(objects),
            bucket=APPROVED_BUCKET,
            plan=plan,
        )
    assert sentinel.read_text(encoding="utf-8") == "old root"


def test_sync_campaign_hash_binds_verbatim_portable_manifest_bytes(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "eda"
    destination.mkdir()
    objects = _complete_campaign_objects()
    table_key = f"{sync.campaign_prefix(CAMPAIGN_ID)}/table={TABLE}/manifest.json"
    table_manifest = json.loads(objects[table_key])
    table_manifest["source_inventory_summary"]["row_group_count"] += 1
    objects[table_key] = _json_bytes(table_manifest)
    plan = sync.build_sync_plan(
        campaign_id=CAMPAIGN_ID,
        tables=[TABLE],
        destination=destination,
        include_root=True,
    )

    with pytest.raises(ValueError, match="dossier hashes do not match"):
        sync.sync_artifacts(
            client=_ObjectStore(objects),
            bucket=APPROVED_BUCKET,
            plan=plan,
        )


def test_sync_requires_terminal_finalize_marker_before_replacement(tmp_path: Path) -> None:
    destination = tmp_path / "eda"
    destination.mkdir()
    sentinel = destination / "feature_candidate_catalog.yaml"
    sentinel.write_text("old catalog", encoding="utf-8")
    objects = _complete_campaign_objects()
    marker_key = f"{sync.campaign_prefix(CAMPAIGN_ID)}/{sync.FINALIZE_MARKER}"
    marker = json.loads(objects[marker_key])
    marker["campaign_manifest_sha256"] = "0" * 64
    objects[marker_key] = _json_bytes(marker)
    plan = sync.build_sync_plan(
        campaign_id=CAMPAIGN_ID,
        tables=[TABLE],
        destination=destination,
        include_root=True,
    )

    with pytest.raises(ValueError, match="finalize marker identity/hash mismatch"):
        sync.sync_artifacts(
            client=_ObjectStore(objects),
            bucket=APPROVED_BUCKET,
            plan=plan,
        )
    assert sentinel.read_text(encoding="utf-8") == "old catalog"


def test_sync_rolls_back_installed_table_when_later_root_swap_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "eda"
    existing = destination / TABLE
    existing.mkdir(parents=True)
    table_sentinel = existing / "sentinel.txt"
    table_sentinel.write_text("old table", encoding="utf-8")
    root_sentinel = destination / "00_feature_engineering_readiness.ipynb"
    root_sentinel.write_text("old root", encoding="utf-8")
    plan = sync.build_sync_plan(
        campaign_id=CAMPAIGN_ID,
        tables=[TABLE],
        destination=destination,
        include_root=True,
    )

    real_replace = sync.os.replace
    failed = False

    def fail_once_on_root_install(source: str | Path, target: str | Path) -> None:
        nonlocal failed
        source_path = Path(source)
        target_path = Path(target)
        if not failed and "prepared" in source_path.parts and target_path == root_sentinel:
            failed = True
            raise OSError("simulated root install failure")
        real_replace(source, target)

    monkeypatch.setattr(sync.os, "replace", fail_once_on_root_install)
    with pytest.raises(OSError, match="simulated root install failure"):
        sync.sync_artifacts(
            client=_ObjectStore(_complete_campaign_objects()),
            bucket=APPROVED_BUCKET,
            plan=plan,
        )

    assert failed is True
    assert table_sentinel.read_text(encoding="utf-8") == "old table"
    assert root_sentinel.read_text(encoding="utf-8") == "old root"
    assert not (existing / "spec.yaml").exists()


def test_put_once_accepts_only_identical_existing_bytes() -> None:
    existing = b"same"

    class _Precondition(Exception):
        response = {"Error": {"Code": "PreconditionFailed"}}

    class _AlreadyExists:
        def put_object(self, **_kwargs: Any) -> None:
            raise _Precondition()

        def get_object(self, **_kwargs: Any) -> dict[str, Any]:
            return {"Body": io.BytesIO(existing)}

    result = cli._put_once(
        _AlreadyExists(),
        bucket=APPROVED_BUCKET,
        key=f"{sync.campaign_prefix(CAMPAIGN_ID)}/campaign_manifest.json",
        body=existing,
        content_type="application/json",
        allow_identical_existing=True,
    )
    assert result == {"IdempotentMatch": True}

    with pytest.raises(cli.CampaignError, match="already exists"):
        cli._put_once(
            _AlreadyExists(),
            bucket=APPROVED_BUCKET,
            key=f"{sync.campaign_prefix(CAMPAIGN_ID)}/campaign_manifest.json",
            body=b"different",
            content_type="application/json",
            allow_identical_existing=True,
        )
