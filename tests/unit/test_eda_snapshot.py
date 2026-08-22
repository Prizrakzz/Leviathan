from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pyarrow as pa
import pytest

from leviathan.eda.inventory import (
    ObjectManifestEntry,
    TableInventory,
    UnsafeSilverPathError,
)
from leviathan.eda.snapshot import (
    SnapshotThresholds,
    UnsafeSnapshotDestination,
    WriteOnceViolation,
    freeze_and_write_snapshot,
    freeze_frame,
    stable_table_sha256,
    validate_s3_output_root,
    write_local_snapshot,
    write_s3_snapshot,
)


def _inventory(*, total_size: int = 100) -> TableInventory:
    obj = ObjectManifestEntry(
        uri="s3://test-leviathan/silver/demo/part-000.parquet",
        bucket="test-leviathan",
        key="silver/demo/part-000.parquet",
        size=total_size,
        etag="etag",
        last_modified="2026-07-17T00:00:00Z",
        version_id="v1",
        checksum_sha256=None,
        partition_values={},
        footer=None,
    )
    return TableInventory(
        table_name="silver_demo",
        layer="silver",
        bucket="test-leviathan",
        root_uri="s3://test-leviathan/silver/demo",
        partition_mode="flat",
        partition_keys=(),
        contract_sha256="contract",
        registry_fingerprint={},
        objects=(obj,),
        source_mode="s3",
    )


def _table() -> pa.Table:
    return pa.table(
        {
            "commodity": ["corn"] * 4 + ["soy"] * 4 + ["wheat"] * 4,
            "year": [2020, 2021, 2022, 2023] * 3,
            "value": list(range(12)),
        }
    )


def test_full_policy_is_exact_and_stably_hashed() -> None:
    table = _table()
    frozen = freeze_frame(table, _inventory(), "campaign-a")

    assert frozen.decision.exactness == "exact"
    assert frozen.decision.snapshot_row_count == 12
    assert frozen.frame_sha256 == stable_table_sha256(table)


def test_deterministic_sample_is_bounded_and_preserves_feasible_strata() -> None:
    table = _table()
    thresholds = SnapshotThresholds(
        full_row_limit=3,
        full_compressed_byte_limit=1,
        sample_row_limit=3,
    )
    first = freeze_frame(
        table,
        _inventory(),
        "campaign-a",
        thresholds=thresholds,
        stratum_columns=["commodity"],
        identity_columns=["commodity", "year", "value"],
    )
    second = freeze_frame(
        table,
        _inventory(),
        "campaign-a",
        thresholds=thresholds,
        stratum_columns=["commodity"],
        identity_columns=["commodity", "year", "value"],
    )

    assert first.decision.exactness == "sampled"
    assert first.table.num_rows == 3
    assert set(first.table["commodity"].to_pylist()) == {"corn", "soy", "wheat"}
    assert first.frame_sha256 == second.frame_sha256
    assert first.table.equals(second.table)


def test_size_threshold_alone_forces_sampling() -> None:
    table = _table()
    frozen = freeze_frame(
        table,
        _inventory(total_size=101),
        "campaign-a",
        thresholds=SnapshotThresholds(
            full_row_limit=100,
            full_compressed_byte_limit=100,
            sample_row_limit=5,
        ),
    )
    assert frozen.decision.exactness == "sampled"
    assert frozen.table.num_rows == 5


def test_local_snapshot_is_write_once_and_manifest_hashes_source(tmp_path: Path) -> None:
    inventory = _inventory()
    frozen = freeze_frame(_table(), inventory, "campaign-a")

    artifact = write_local_snapshot(frozen, inventory, "campaign-a", tmp_path)
    manifest_path = Path(artifact.manifest_uri)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert Path(artifact.parquet_uri).is_file()
    assert manifest["source_manifest_sha256"] == inventory.manifest_sha256
    assert manifest["frozen_frame_sha256"] == frozen.frame_sha256
    assert manifest["manifest_sha256"] == artifact.manifest_sha256
    table_dir = tmp_path / "campaign_id=campaign-a" / "table=silver_demo"
    assert not (table_dir / "manifest.json").exists()
    assert manifest_path == table_dir / "_machine" / "snapshot" / "manifest.json"
    with pytest.raises(WriteOnceViolation):
        write_local_snapshot(frozen, inventory, "campaign-a", tmp_path)


def test_freeze_and_write_local_convenience_path(tmp_path: Path) -> None:
    artifact = freeze_and_write_snapshot(
        _table(),
        _inventory(),
        "campaign-b",
        tmp_path,
    )
    normalized = artifact.destination.replace("\\", "/")
    assert normalized.endswith(
        "campaign_id=campaign-b/table=silver_demo/_machine/snapshot"
    )


def test_snapshot_rejects_nested_gold_source_even_with_silver_layer() -> None:
    inventory = _inventory()
    entry = replace(
        inventory.objects[0],
        uri="s3://test-leviathan/silver/demo/gold/part.parquet",
        key="silver/demo/gold/part.parquet",
    )

    with pytest.raises(UnsafeSilverPathError, match="forbidden"):
        freeze_frame(_table(), replace(inventory, objects=(entry,)), "campaign-a")


class _S3Writer:
    def __init__(self) -> None:
        self.keys: list[str] = []
        self.parquet_request: dict | None = None

    def put_object(self, **kwargs) -> dict:
        self.keys.append(kwargs["Key"])
        if kwargs["Key"].endswith("part-000.parquet"):
            self.parquet_request = {
                key: value for key, value in kwargs.items() if key != "Body"
            }
            return {"ChecksumSHA256": kwargs["ChecksumSHA256"]}
        return {}


def test_s3_snapshot_uses_isolated_machine_namespace() -> None:
    inventory = _inventory()
    frozen = freeze_frame(_table(), inventory, "campaign-c")
    s3 = _S3Writer()

    artifact = write_s3_snapshot(
        frozen,
        inventory,
        "campaign-c",
        "s3://test-leviathan/eda/silver",
        s3_client=s3,
    )

    machine_prefix = (
        "eda/silver/campaign_id=campaign-c/table=silver_demo/_machine/snapshot/"
    )
    assert s3.keys
    assert all(key.startswith(machine_prefix) for key in s3.keys)
    assert artifact.manifest_uri.endswith("/_machine/snapshot/manifest.json")
    assert s3.parquet_request is not None
    assert s3.parquet_request["ContentLength"] == artifact.parquet_bytes
    assert s3.parquet_request["IfNoneMatch"] == "*"
    assert s3.parquet_request["ChecksumSHA256"]
    assert s3.parquet_request["Metadata"] == {
        "sha256": artifact.parquet_sha256,
        "frame-sha256": artifact.frame_sha256,
        "campaign-id": "campaign-c",
        "table-name": "silver_demo",
    }
    assert (
        "eda/silver/campaign_id=campaign-c/table=silver_demo/manifest.json"
        not in s3.keys
    )


@pytest.mark.parametrize(
    "uri",
    [
        "s3://test-leviathan/gold",
        "s3://test-leviathan/eda/silver/extra",
        "s3://another-bucket/eda/silver",
    ],
)
def test_s3_destination_guard_rejects_everything_outside_exact_campaign_root(uri: str) -> None:
    with pytest.raises(UnsafeSnapshotDestination):
        validate_s3_output_root(uri, expected_bucket="test-leviathan")


def test_s3_destination_guard_accepts_only_eda_silver_root() -> None:
    assert validate_s3_output_root(
        "s3://test-leviathan/eda/silver/", expected_bucket="test-leviathan"
    ) == ("test-leviathan", "eda/silver")
