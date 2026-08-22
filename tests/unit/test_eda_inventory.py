from __future__ import annotations

import io
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from leviathan.eda.inventory import (
    FragmentLimitExceeded,
    RegisteredLocation,
    SilverTable,
    UnsafeSilverPathError,
    assert_canonical_silver_uri,
    inventory_table,
    load_current_silver_tables,
)
from leviathan.eda.reader import read_inventory


def _contract(
    table_name: str,
    prefix: str,
    *,
    partition_mode: str = "flat",
    partition_keys: tuple[tuple[str, str], ...] = (),
) -> dict:
    return {
        "table_name": table_name,
        "layer": "silver",
        "s3_bucket": "test-leviathan",
        "s3_prefix": prefix,
        "s3_root": f"s3://test-leviathan/{prefix}",
        "partition_mode": partition_mode,
        "partition_keys": [
            {"name": name, "glue_type": typ, "projected": partition_mode == "projected"}
            for name, typ in partition_keys
        ],
        "glue_database": "leviathan_test",
        "fingerprint": {"schema_fingerprint_sha256": "abc"},
    }


def _write(path: Path, values: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"value": values}), path)


def test_registry_universe_is_exactly_current_silver_and_excludes_gold() -> None:
    tables = load_current_silver_tables()
    assert len(tables) == 42
    assert {item.table_name for item in tables} == {
        item.table_name for item in tables if item.contract["layer"] == "silver"
    }
    assert "gold_weather_z" not in {item.table_name for item in tables}
    assert all(item.root_uri.startswith("s3://leviathan-dev-shahem-001/silver/") for item in tables)


@pytest.mark.parametrize(
    "uri",
    [
        "s3://test-leviathan/gold/weather_z/part.parquet",
        "s3://test-leviathan/silver/foo/_shadow/part.parquet",
        "s3://test-leviathan/silver/foo/_staging/part.parquet",
        "s3://test-leviathan/silver/foo/_tasks/part.parquet",
        "s3://test-leviathan/silver/foo/.hidden/part.parquet",
        "s3://test-leviathan/silver/foo/gold/part.parquet",
        "s3://test-leviathan/silver/foo/model_ready/part.parquet",
        "s3://test-leviathan/silver/foo/targets/part.parquet",
        "s3://test-leviathan/silver/foo/GOLD/part.parquet",
    ],
)
def test_source_path_guard_rejects_gold_and_control_paths(uri: str) -> None:
    with pytest.raises(UnsafeSilverPathError):
        assert_canonical_silver_uri(uri, expected_bucket="test-leviathan")


def test_local_inventory_has_exact_identity_footer_partitions_and_stable_hash(
    tmp_path: Path,
) -> None:
    table = SilverTable(
        "silver_demo",
        _contract(
            "silver_demo",
            "silver/demo",
            partition_mode="projected",
            partition_keys=(("commodity", "string"), ("year", "int")),
        ),
    )
    _write(tmp_path / "silver/demo/commodity=corn/year=2024/part-000.parquet", [1, 2, 3])

    first = inventory_table(table, local_root=tmp_path)
    second = inventory_table(table, local_root=tmp_path)

    assert first.fragment_count == 1
    assert first.total_rows == 3
    assert first.objects[0].partition_values == {"commodity": "corn", "year": "2024"}
    assert first.objects[0].checksum_sha256 == first.objects[0].etag
    assert first.objects[0].footer is not None
    assert first.objects[0].footer.columns == (("value", "int64"),)
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.to_dict() == second.to_dict()


def test_silver_production_first_partition_key_fence_excludes_foreign_subtree(
    tmp_path: Path,
) -> None:
    table = SilverTable(
        "silver_production",
        _contract(
            "silver_production",
            "silver/production",
            partition_mode="projected",
            partition_keys=(("commodity", "string"), ("year", "int")),
        ),
    )
    canonical = "silver/production/commodity=corn/year=2024/part-000.parquet"
    foreign = (
        "silver/production/source=usda_esr/commodity_code=101/"
        "market_year=2024/as_of_date=2024-01-01/part-000.parquet"
    )
    _write(tmp_path / canonical, [1])
    _write(tmp_path / foreign, [2])

    inventory = inventory_table(table, local_root=tmp_path)

    assert [item.key for item in inventory.objects] == [canonical]
    assert inventory.rejected_keys == (foreign,)


def test_registered_local_inventory_uses_only_explicit_glue_locations(tmp_path: Path) -> None:
    table = SilverTable(
        "silver_registered",
        _contract(
            "silver_registered",
            "silver/registered",
            partition_mode="registered",
            partition_keys=(("commodity", "string"), ("year", "int")),
        ),
    )
    included = "silver/registered/corn/2024/part-000.parquet"
    unregistered = "silver/registered/corn/2023/part-000.parquet"
    _write(tmp_path / included, [1])
    _write(tmp_path / unregistered, [2])
    location = RegisteredLocation(
        "s3://test-leviathan/silver/registered/corn/2024",
        {"commodity": "corn", "year": "2024"},
    )

    inventory = inventory_table(
        table,
        local_root=tmp_path,
        registered_partition_locations=[location],
    )

    assert [item.key for item in inventory.objects] == [included]
    assert inventory.objects[0].partition_values == {"commodity": "corn", "year": "2024"}


def test_fragment_cap_aborts_inventory(tmp_path: Path) -> None:
    table = SilverTable("silver_demo", _contract("silver_demo", "silver/demo"))
    _write(tmp_path / "silver/demo/a.parquet", [1])
    _write(tmp_path / "silver/demo/b.parquet", [2])

    with pytest.raises(FragmentLimitExceeded, match="Fragment cap 1"):
        inventory_table(table, local_root=tmp_path, fragment_cap=1)


class _Pages:
    def __init__(self, pages: list[dict]):
        self.pages = pages

    def paginate(self, **_kwargs):
        return list(self.pages)


class _S3:
    def __init__(self) -> None:
        self.head_calls: list[tuple[str, str]] = []

    def get_paginator(self, name: str):
        assert name == "list_objects_v2"
        return _Pages(
            [
                {
                    "Contents": [
                        {"Key": "silver/demo/part-000.parquet"},
                        {"Key": "silver/demo/_staging/part-000.parquet"},
                    ]
                }
            ]
        )

    def head_object(self, *, Bucket: str, Key: str):
        self.head_calls.append((Bucket, Key))
        return {
            "ContentLength": 123,
            "ETag": '"etag-1"',
            "VersionId": "v1",
            "LastModified": datetime(2026, 7, 17, tzinfo=timezone.utc),
        }


def test_s3_manifest_heads_only_canonical_parquet_objects() -> None:
    table = SilverTable("silver_demo", _contract("silver_demo", "silver/demo"))
    s3 = _S3()

    inventory = inventory_table(
        table,
        s3_client=s3,
        include_footer_metadata=False,
    )

    assert s3.head_calls == [("test-leviathan", "silver/demo/part-000.parquet")]
    assert inventory.objects[0].identity == "version:v1"
    assert inventory.rejected_keys == ("silver/demo/_staging/part-000.parquet",)


def test_suspended_bucket_null_version_is_not_treated_as_immutable() -> None:
    class NullVersionS3(_S3):
        def head_object(self, *, Bucket: str, Key: str):
            result = super().head_object(Bucket=Bucket, Key=Key)
            result["VersionId"] = "null"
            return result

    table = SilverTable("silver_demo", _contract("silver_demo", "silver/demo"))
    inventory = inventory_table(
        table,
        s3_client=NullVersionS3(),
        include_footer_metadata=False,
    )

    assert inventory.objects[0].version_id is None
    assert inventory.objects[0].identity == "etag:etag-1"


class _VersionedS3(_S3):
    def __init__(self, payload: bytes) -> None:
        super().__init__()
        self.payload = payload
        self.get_calls: list[dict] = []

    def head_object(self, *, Bucket: str, Key: str, VersionId: str | None = None):
        self.head_calls.append((Bucket, Key))
        assert VersionId in {None, "v1"}
        return {
            "ContentLength": len(self.payload),
            "ETag": '"etag-1"',
            "VersionId": "v1",
            "LastModified": datetime(2026, 7, 17, tzinfo=timezone.utc),
        }

    def get_object(self, **kwargs):
        self.get_calls.append(dict(kwargs))
        assert kwargs["VersionId"] == "v1"
        start_text, end_text = kwargs["Range"].removeprefix("bytes=").split("-", 1)
        start, end = int(start_text), int(end_text)
        return {
            "Body": io.BytesIO(self.payload[start : end + 1]),
            "ETag": '"etag-1"',
            "VersionId": "v1",
        }


def test_versioned_footer_bytes_are_read_from_manifest_version(tmp_path: Path) -> None:
    parquet = tmp_path / "versioned.parquet"
    _write(parquet, [1, 2, 3])
    s3 = _VersionedS3(parquet.read_bytes())
    table = SilverTable("silver_demo", _contract("silver_demo", "silver/demo"))

    inventory = inventory_table(table, s3_client=s3)

    assert inventory.total_rows == 3
    assert s3.get_calls
    assert all(call.get("VersionId") == "v1" for call in s3.get_calls)
    s3.get_calls.clear()

    result = read_inventory(inventory, contract=table.contract, s3_client=s3)

    assert result.table["value"].to_pylist() == [1, 2, 3]
    assert s3.get_calls
    assert all(call.get("VersionId") == "v1" for call in s3.get_calls)
