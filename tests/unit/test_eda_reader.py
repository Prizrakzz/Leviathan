from __future__ import annotations

import io
from dataclasses import replace
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import leviathan.eda.reader as reader_module
from leviathan.eda.inventory import (
    ObjectManifestEntry,
    SilverTable,
    TableInventory,
    UnsafeSilverPathError,
    inventory_table,
)
from leviathan.eda.reader import (
    ContractBindingError,
    ObjectDriftError,
    PartitionMaterializationError,
    iter_inventory_batches,
    read_for_analysis,
    read_inventory,
    read_replica_for_analysis,
    replica_bound_s3_client,
)
from leviathan.eda.replica import ReplicaArtifact, ReplicaObjectArtifact


def test_align_scalar_schema_drift_preserves_values_as_text() -> None:
    from leviathan.eda.reader import _align_tables

    older = pa.table({"as_of_date": pa.array(["2024-01-01"], type=pa.large_string())})
    newer = pa.table({"as_of_date": pa.array([date(2024, 1, 2)], type=pa.date32())})
    aligned = _align_tables([older, newer], ["as_of_date"])
    assert aligned.schema.field("as_of_date").type == pa.large_string()
    assert aligned["as_of_date"].to_pylist() == ["2024-01-01", "2024-01-02"]


def _contract() -> dict:
    return {
        "table_name": "silver_demo",
        "layer": "silver",
        "s3_bucket": "test-leviathan",
        "s3_prefix": "silver/demo",
        "s3_root": "s3://test-leviathan/silver/demo",
        "partition_mode": "projected",
        "partition_keys": [
            {"name": "commodity", "glue_type": "string", "projected": True},
            {"name": "year", "glue_type": "int", "projected": True},
        ],
        "physical_columns": [
            {"name": "date"},
            {"name": "value"},
        ],
        "fingerprint": {},
    }


def _write(path: Path, value: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table({"date": ["2024-01-01"], "value": [value]}),
        path,
    )


def _inventory(tmp_path: Path) -> tuple[dict, TableInventory]:
    contract = _contract()
    _write(tmp_path / "silver/demo/commodity=corn/year=2024/a.parquet", 1.0)
    _write(tmp_path / "silver/demo/commodity=soy/year=2023/b.parquet", 2.0)
    return contract, inventory_table(SilverTable("silver_demo", contract), local_root=tmp_path)


def test_reader_materializes_typed_hive_partitions(tmp_path: Path) -> None:
    contract, inventory = _inventory(tmp_path)

    result = read_inventory(inventory, contract=contract)

    assert result.row_count == 2
    assert result.object_count == 2
    assert result.manifest_sha256 == inventory.manifest_sha256
    assert result.table.column_names == ["date", "value", "commodity", "year"]
    assert result.table["year"].type == pa.int64()
    rows = sorted(result.table.to_pylist(), key=lambda row: row["commodity"])
    assert rows == [
        {"date": "2024-01-01", "value": 1.0, "commodity": "corn", "year": 2024},
        {"date": "2024-01-01", "value": 2.0, "commodity": "soy", "year": 2023},
    ]


def test_projected_compaction_uses_in_file_values_for_missing_path_dimensions(
    tmp_path: Path,
) -> None:
    contract = _contract()
    contract["partition_keys"] = [
        {"name": "commodity", "glue_type": "string", "projected": True},
        {"name": "country", "glue_type": "string", "projected": True},
        {"name": "region", "glue_type": "string", "projected": True},
        {"name": "year", "glue_type": "int", "projected": True},
        {"name": "month", "glue_type": "int", "projected": True},
    ]
    path = tmp_path / "silver/demo/commodity=corn/year=2024/part.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                "date": ["2024-01-01"],
                "value": [1.0],
                "country": ["BR"],
                "region": ["PR"],
                "month": [1],
            }
        ),
        path,
    )
    inventory = inventory_table(SilverTable("silver_demo", contract), local_root=tmp_path)
    assert inventory.objects[0].partition_values == {
        "commodity": "corn",
        "year": "2024",
    }
    result = read_inventory(
        inventory,
        contract=contract,
        columns=["commodity", "country", "region", "year", "month", "value"],
    )
    row = result.table.to_pylist()[0]
    assert row["country"] == "BR"
    assert row["region"] == "PR"
    assert row["month"] == 1
    assert row["year"] == 2024


def _hybrid_projected_inventory(
    tmp_path: Path,
    *,
    physical_year: int | None = None,
    include_month: bool = True,
) -> tuple[dict, TableInventory]:
    contract = _contract()
    contract["partition_keys"] = [
        {"name": "commodity", "glue_type": "string", "projected": True},
        {"name": "country", "glue_type": "string", "projected": True},
        {"name": "region", "glue_type": "string", "projected": True},
        {"name": "year", "glue_type": "int", "projected": True},
        {"name": "month", "glue_type": "int", "projected": True},
    ]
    values: dict[str, list[object]] = {
        "date": ["2024-01-01", "2024-01-02"],
        "value": [1.0, 2.0],
        "country": ["BR", "BR"],
        "region": ["PR", "PR"],
    }
    if include_month:
        values["month"] = [1, 1]
    if physical_year is not None:
        values["year"] = [physical_year, physical_year]
    path = tmp_path / "silver/demo/commodity=corn/year=2024/part.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(values), path, row_group_size=1)
    return contract, inventory_table(
        SilverTable("silver_demo", contract),
        local_root=tmp_path,
    )


def test_streaming_projection_reads_file_backed_partition_dimensions(
    tmp_path: Path,
) -> None:
    contract, inventory = _hybrid_projected_inventory(tmp_path)

    batches = list(
        iter_inventory_batches(
            inventory,
            contract=contract,
            columns=["commodity", "country", "region", "year", "month", "value"],
            batch_size=1,
        )
    )

    combined = pa.concat_tables(batches)
    assert combined.to_pylist() == [
        {
            "commodity": "corn",
            "country": "BR",
            "region": "PR",
            "year": 2024,
            "month": 1,
            "value": 1.0,
        },
        {
            "commodity": "corn",
            "country": "BR",
            "region": "PR",
            "year": 2024,
            "month": 1,
            "value": 2.0,
        },
    ]


@pytest.mark.parametrize("streaming", [False, True])
def test_hybrid_projection_rejects_path_file_partition_conflicts(
    tmp_path: Path,
    streaming: bool,
) -> None:
    contract, inventory = _hybrid_projected_inventory(tmp_path, physical_year=2023)

    with pytest.raises(PartitionMaterializationError, match="conflicts with Hive value"):
        if streaming:
            list(
                iter_inventory_batches(
                    inventory,
                    contract=contract,
                    columns=["year", "value"],
                    batch_size=1,
                )
            )
        else:
            read_inventory(
                inventory,
                contract=contract,
                columns=["year", "value"],
            )


@pytest.mark.parametrize("streaming", [False, True])
def test_hybrid_projection_rejects_partition_missing_from_path_and_file(
    tmp_path: Path,
    streaming: bool,
) -> None:
    contract, inventory = _hybrid_projected_inventory(tmp_path, include_month=False)

    with pytest.raises(PartitionMaterializationError, match="absent from both"):
        if streaming:
            list(
                iter_inventory_batches(
                    inventory,
                    contract=contract,
                    columns=["month", "value"],
                    batch_size=1,
                )
            )
        else:
            read_inventory(
                inventory,
                contract=contract,
                columns=["month", "value"],
            )


def test_reader_column_projection_can_request_partition_columns(tmp_path: Path) -> None:
    contract, inventory = _inventory(tmp_path)

    result = read_inventory(
        inventory,
        contract=contract,
        columns=["year", "value"],
    )

    assert result.table.column_names == ["year", "value"]
    assert sorted(result.table["year"].to_pylist()) == [2023, 2024]


def test_streaming_reader_scans_exact_rows_and_materializes_partitions(
    tmp_path: Path,
) -> None:
    contract = _contract()
    path = tmp_path / "silver/demo/commodity=corn/year=2024/a.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                "date": [f"2024-01-{day:02d}" for day in range(1, 8)],
                "value": [float(day) for day in range(1, 8)],
            }
        ),
        path,
        row_group_size=3,
    )
    inventory = inventory_table(SilverTable("silver_demo", contract), local_root=tmp_path)

    batches = list(
        iter_inventory_batches(
            inventory,
            contract=contract,
            columns=["commodity", "year", "date", "value"],
            batch_size=2,
        )
    )

    assert sum(batch.num_rows for batch in batches) == 7
    assert max(batch.num_rows for batch in batches) <= 2
    combined = pa.concat_tables(batches)
    assert combined.column_names == ["commodity", "year", "date", "value"]
    assert combined["commodity"].to_pylist() == ["corn"] * 7
    assert combined["year"].to_pylist() == [2024] * 7


def test_reader_rejects_object_changed_after_inventory(tmp_path: Path) -> None:
    contract, inventory = _inventory(tmp_path)
    _write(Path(inventory.objects[0].local_path), 999.0)

    with pytest.raises(ObjectDriftError, match="Content drift"):
        read_inventory(inventory, contract=contract)


def test_reader_post_read_identity_check_catches_mid_scan_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract, inventory = _inventory(tmp_path)
    original = reader_module._read_object
    changed = False

    def mutate_after_read(*args, **kwargs):
        nonlocal changed
        table = original(*args, **kwargs)
        if not changed:
            changed = True
            entry = args[0]
            _write(Path(entry.local_path), 500.0)
        return table

    monkeypatch.setattr(reader_module, "_read_object", mutate_after_read)

    with pytest.raises(ObjectDriftError, match="Content drift"):
        read_inventory(inventory, contract=contract)


def test_reader_rejects_forged_gold_manifest(tmp_path: Path) -> None:
    contract, inventory = _inventory(tmp_path)
    first = inventory.objects[0]
    forged = replace(
        first,
        uri="s3://test-leviathan/gold/old/part.parquet",
        key="gold/old/part.parquet",
    )
    bad = replace(inventory, root_uri="s3://test-leviathan/gold/old", objects=(forged,))

    with pytest.raises(UnsafeSilverPathError):
        read_inventory(bad, contract=contract, verify_identity=False)


def test_reader_enforces_silver_production_first_key_fence(tmp_path: Path) -> None:
    path = tmp_path / "silver/production/source=usda_esr/part.parquet"
    _write(path, 1.0)
    flat_contract = {
        **_contract(),
        "s3_prefix": "silver/production",
        "s3_root": "s3://test-leviathan/silver/production",
        "partition_mode": "flat",
        "partition_keys": [],
    }
    source = inventory_table(
        SilverTable("silver_demo", flat_contract),
        local_root=tmp_path,
    )
    bad = replace(
        source,
        table_name="silver_production",
        partition_keys=("commodity", "year"),
    )

    with pytest.raises(UnsafeSilverPathError, match="first-partition-key fence"):
        read_inventory(bad, verify_identity=False)


def test_reader_binds_contract_table_name_and_hash(tmp_path: Path) -> None:
    contract, inventory = _inventory(tmp_path)
    wrong_name = {**contract, "table_name": "silver_other"}
    wrong_hash = {**contract, "notes": "mutated after inventory"}

    with pytest.raises(ContractBindingError, match="table_name"):
        read_inventory(inventory, contract=wrong_name)
    with pytest.raises(ContractBindingError, match="contract hash"):
        read_inventory(inventory, contract=wrong_hash)
    with pytest.raises(ContractBindingError, match="requires the authoritative"):
        read_inventory(inventory)


def test_reader_rejects_forbidden_segment_nested_below_silver(tmp_path: Path) -> None:
    contract, inventory = _inventory(tmp_path)
    entry = inventory.objects[0]
    forged = replace(
        entry,
        uri="s3://test-leviathan/silver/demo/targets/part.parquet",
        key="silver/demo/targets/part.parquet",
    )
    bad = replace(inventory, objects=(forged,))

    with pytest.raises(UnsafeSilverPathError):
        read_inventory(bad, contract=contract, verify_identity=False)


def test_bounded_analysis_read_is_deterministic_and_footer_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract()
    for commodity, year in (("corn", 2024), ("soy", 2023), ("wheat", 2022)):
        path = tmp_path / f"silver/demo/commodity={commodity}/year={year}/part.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(
            pa.table(
                {
                    "date": [f"{year}-01-{day:02d}" for day in range(1, 31)],
                    "value": [float(day) for day in range(30)],
                }
            ),
            path,
            row_group_size=7,
        )
    inventory = inventory_table(SilverTable("silver_demo", contract), local_root=tmp_path)

    def reject_exact_read(*_args, **_kwargs):
        raise AssertionError("oversized path must not call the whole-object reader")

    monkeypatch.setattr(reader_module, "_read_object", reject_exact_read)
    first = read_for_analysis(
        inventory,
        "campaign-x",
        contract=contract,
        full_row_limit=1,
        full_compressed_byte_limit=1,
        sample_row_limit=12,
        batch_size=3,
    )
    second = read_for_analysis(
        inventory,
        "campaign-x",
        contract=contract,
        full_row_limit=1,
        full_compressed_byte_limit=1,
        sample_row_limit=12,
        batch_size=3,
    )

    assert first.exactness == "sampled"
    assert first.source_row_count == 90
    assert first.row_count == 12
    assert first.table.equals(second.table)
    assert first.sample_seed == second.sample_seed
    assert {row["commodity"] for row in first.table.to_pylist()} == {
        "corn",
        "soy",
        "wheat",
    }
    assert first.coverage_catalog["footer_complete"] is True
    assert first.coverage_catalog["object_count"] == 3
    assert len(first.coverage_catalog["partition_strata"]) == 3
    assert sum(item.selected_rows for item in first.row_group_selections) == 12


def test_replica_bound_reader_redirects_head_and_ranged_get_only_to_manifest_object(
    tmp_path: Path,
) -> None:
    contract = _contract()
    path = tmp_path / "silver/demo/commodity=corn/year=2024/part.parquet"
    _write(path, 7.5)
    local_inventory = inventory_table(
        SilverTable("silver_demo", contract),
        local_root=tmp_path,
    )
    source = replace(local_inventory.objects[0], local_path=None)
    inventory = replace(local_inventory, objects=(source,), source_mode="s3")
    destination_key = (
        "eda/silver/campaign_id=replica-a/table=silver_demo/"
        "_machine/source_replica/objects/commodity=corn/year=2024/part.parquet"
    )
    mapping = ReplicaObjectArtifact(
        source_uri=source.uri,
        source_key=source.key,
        source_size=source.size,
        source_etag=source.etag,
        source_version_id=None,
        source_checksum_sha256=source.checksum_sha256,
        source_identity=source.identity,
        destination_uri=f"s3://test-leviathan/{destination_key}",
        destination_key=destination_key,
        destination_size=source.size,
        destination_etag="replica-etag",
        destination_version_id=None,
        destination_checksum_sha256=None,
        destination_identity="etag:replica-etag",
        copy_guard=f"etag:{source.etag}",
    )
    artifact = ReplicaArtifact(
        table_name="silver_demo",
        campaign_id="replica-a",
        destination=(
            "s3://test-leviathan/eda/silver/campaign_id=replica-a/"
            "table=silver_demo/_machine/source_replica"
        ),
        objects_prefix_uri=(
            "s3://test-leviathan/eda/silver/campaign_id=replica-a/"
            "table=silver_demo/_machine/source_replica/objects"
        ),
        marker_uri="s3://test-leviathan/eda/silver/marker",
        manifest_uri="s3://test-leviathan/eda/silver/manifest.json",
        source_manifest_sha256=inventory.manifest_sha256,
        replica_manifest_sha256="a" * 64,
        object_count=1,
        total_bytes=source.size,
        objects=(mapping,),
        source_inventory=inventory,
    )
    payload = path.read_bytes()

    class PhysicalReplicaS3:
        def __init__(self) -> None:
            self.head_calls: list[dict] = []
            self.get_calls: list[dict] = []

        def head_object(self, **kwargs):
            self.head_calls.append(dict(kwargs))
            assert kwargs == {
                "Bucket": "test-leviathan",
                "Key": destination_key,
                "IfMatch": "replica-etag",
            }
            return {
                "ContentLength": len(payload),
                "ETag": '"replica-etag"',
                "VersionId": "null",
            }

        def get_object(self, **kwargs):
            self.get_calls.append(dict(kwargs))
            assert kwargs["Bucket"] == "test-leviathan"
            assert kwargs["Key"] == destination_key
            assert kwargs["IfMatch"] == "replica-etag"
            assert "VersionId" not in kwargs
            start_text, end_text = kwargs["Range"].removeprefix("bytes=").split("-", 1)
            start, end = int(start_text), int(end_text)
            block = payload[start : end + 1]
            return {
                "Body": io.BytesIO(block),
                "ContentLength": len(block),
                "ContentRange": f"bytes {start}-{end}/{len(payload)}",
                "ETag": '"replica-etag"',
                "VersionId": "null",
            }

    physical = PhysicalReplicaS3()
    bound = replica_bound_s3_client(artifact, s3_client=physical)
    first_bytes = bound.get_object(
        Bucket="test-leviathan",
        Key=source.key,
        Range="bytes=0-3",
        IfMatch=source.etag,
    )["Body"].read()
    assert first_bytes == payload[:4]

    result = read_replica_for_analysis(
        artifact,
        "analysis-b",
        contract=contract,
        s3_client=physical,
    )

    assert result.table["value"].to_pylist() == [7.5]
    assert result.table["commodity"].to_pylist() == ["corn"]
    assert result.table["year"].to_pylist() == [2024]
    assert physical.head_calls
    assert len(physical.get_calls) > 1
    with pytest.raises(UnsafeSilverPathError, match="non-manifest source"):
        bound.get_object(
            Bucket="test-leviathan",
            Key="gold/old/part.parquet",
            Range="bytes=0-1",
        )
