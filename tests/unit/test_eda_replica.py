from __future__ import annotations

import hashlib
import io
import json
from dataclasses import replace

import pytest

from leviathan.eda.inventory import ObjectManifestEntry, TableInventory
from leviathan.eda.replica import (
    MAX_SINGLE_COPY_BYTES,
    PartialReplicaError,
    ReplicaManifestError,
    ReplicaNotFound,
    ReplicaObjectTooLarge,
    ReplicaVerificationError,
    ReplicaWriteOnceViolation,
    UnsafeReplicaDestination,
    UnsafeReplicaSource,
    load_s3_replica,
    validate_replica_output_root,
    wait_for_s3_replica,
    write_s3_replica,
)


def _entry(
    relative: str,
    *,
    size: int,
    etag: str,
    version_id: str | None,
) -> ObjectManifestEntry:
    key = f"silver/demo/{relative}"
    return ObjectManifestEntry(
        uri=f"s3://test-leviathan/{key}",
        bucket="test-leviathan",
        key=key,
        size=size,
        etag=etag,
        last_modified="2026-07-18T00:00:00Z",
        version_id=version_id,
        checksum_sha256=None,
        partition_values={},
        footer=None,
    )


def _inventory(
    objects: tuple[ObjectManifestEntry, ...] | None = None,
) -> TableInventory:
    return TableInventory(
        table_name="silver_demo",
        layer="silver",
        bucket="test-leviathan",
        root_uri="s3://test-leviathan/silver/demo",
        partition_mode="flat",
        partition_keys=(),
        contract_sha256="contract-sha",
        registry_fingerprint={"schema_fingerprint_sha256": "schema-sha"},
        objects=objects
        if objects is not None
        else (
            _entry(
                "year=2025/part-000.parquet",
                size=13,
                etag="source-etag-a",
                version_id="source-version-a",
            ),
            _entry(
                "year=2026/part-000.parquet",
                size=17,
                etag="source-etag-b",
                version_id=None,
            ),
        ),
        source_mode="s3",
    )


class _FakeClientError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _FakeS3:
    def __init__(
        self,
        inventory: TableInventory,
        *,
        marker_exists: bool = False,
        destination_size_delta: int = 0,
        head_etag_override: str | None = None,
    ) -> None:
        self.source_sizes = {item.key: item.size for item in inventory.objects}
        self.source_etags = {item.key: item.etag for item in inventory.objects}
        self.marker_exists = marker_exists
        self.destination_size_delta = destination_size_delta
        self.head_etag_override = head_etag_override
        self.operations: list[tuple[str, str]] = []
        self.puts: dict[str, dict] = {}
        self.copies: list[dict] = []
        self.destinations: dict[str, dict] = {}

    def put_object(self, **kwargs) -> dict:
        key = kwargs["Key"]
        self.operations.append(("put", key))
        if key.endswith("/_WRITE_ONCE") and self.marker_exists:
            raise _FakeClientError("PreconditionFailed")
        if kwargs.get("IfNoneMatch") == "*" and key in self.puts:
            raise _FakeClientError("PreconditionFailed")
        self.puts[key] = dict(kwargs)
        return {"ETag": '"put-etag"'}

    def copy_object(self, **kwargs) -> dict:
        key = kwargs["Key"]
        source_key = kwargs["CopySource"]["Key"]
        self.operations.append(("copy", key))
        self.copies.append(dict(kwargs))
        destination_etag = self.source_etags[source_key]
        destination_version = f"destination-version-{len(self.copies)}"
        self.destinations[key] = {
            "ContentLength": self.source_sizes[source_key] + self.destination_size_delta,
            "ETag": f'"{destination_etag}"',
            "VersionId": destination_version,
        }
        return {
            "CopyObjectResult": {"ETag": f'"{destination_etag}"'},
            "VersionId": destination_version,
        }

    def head_object(self, **kwargs) -> dict:
        key = kwargs["Key"]
        self.operations.append(("head", key))
        if key in self.destinations:
            result = dict(self.destinations[key])
        elif key in self.puts:
            body = self.puts[key]["Body"]
            result = {"ContentLength": len(body), "ETag": '"put-etag"'}
        elif key.endswith("/_WRITE_ONCE") and self.marker_exists:
            result = {"ContentLength": 1, "ETag": '"marker-etag"'}
        else:
            raise _FakeClientError("NoSuchKey")
        if self.head_etag_override is not None:
            result["ETag"] = f'"{self.head_etag_override}"'
        return result

    def get_object(self, **kwargs) -> dict:
        key = kwargs["Key"]
        self.operations.append(("get", key))
        if key not in self.puts:
            raise _FakeClientError("NoSuchKey")
        return {"Body": io.BytesIO(self.puts[key]["Body"])}


def _manifest_from(fake: _FakeS3) -> tuple[str, dict]:
    manifest_key = next(key for key in fake.puts if key.endswith("/manifest.json"))
    body = fake.puts[manifest_key]["Body"]
    return manifest_key, json.loads(body.decode("utf-8"))


def _manifest_digest(manifest: dict) -> str:
    payload = dict(manifest)
    payload.pop("replica_manifest_sha256")
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def test_replica_copies_exact_object_set_with_version_or_etag_guard() -> None:
    inventory = _inventory()
    s3 = _FakeS3(inventory)

    artifact = write_s3_replica(
        inventory,
        "campaign-a",
        "s3://test-leviathan/eda/silver",
        s3_client=s3,
    )

    prefix = "eda/silver/campaign_id=campaign-a/table=silver_demo/_machine/source_replica"
    assert artifact.destination == f"s3://test-leviathan/{prefix}"
    assert artifact.object_count == 2
    assert artifact.total_bytes == 30
    assert [item.destination_key for item in artifact.objects] == [
        f"{prefix}/objects/year=2025/part-000.parquet",
        f"{prefix}/objects/year=2026/part-000.parquet",
    ]

    versioned, unversioned = s3.copies
    assert versioned["CopySource"] == {
        "Bucket": "test-leviathan",
        "Key": "silver/demo/year=2025/part-000.parquet",
        "VersionId": "source-version-a",
    }
    assert "CopySourceIfMatch" not in versioned
    assert unversioned["CopySource"] == {
        "Bucket": "test-leviathan",
        "Key": "silver/demo/year=2026/part-000.parquet",
    }
    assert unversioned["CopySourceIfMatch"] == "source-etag-b"

    manifest_key, manifest = _manifest_from(s3)
    assert s3.operations[-1] == ("put", manifest_key)
    assert manifest["source_manifest_sha256"] == inventory.manifest_sha256
    assert manifest["source_inventory"] == inventory.to_dict()
    assert manifest["source_object_count"] == 2
    assert manifest["source_total_bytes"] == 30
    assert len(manifest["objects"]) == 2
    assert manifest["replica_manifest_sha256"] == _manifest_digest(manifest)
    assert artifact.replica_manifest_sha256 == manifest["replica_manifest_sha256"]
    assert s3.puts[manifest_key]["IfNoneMatch"] == "*"
    assert s3.puts[manifest_key]["Metadata"] == {
        "replica-manifest-sha256": artifact.replica_manifest_sha256
    }


def test_literal_null_source_version_uses_etag_guard() -> None:
    inventory = _inventory(
        (
            _entry(
                "part-000.parquet",
                size=10,
                etag="source-etag",
                version_id="null",
            ),
        )
    )
    s3 = _FakeS3(inventory)

    artifact = write_s3_replica(
        inventory,
        "campaign-null",
        "s3://test-leviathan/eda/silver",
        s3_client=s3,
    )

    request = s3.copies[0]
    assert "VersionId" not in request["CopySource"]
    assert request["CopySourceIfMatch"] == "source-etag"
    assert artifact.objects[0].copy_guard == "etag:source-etag"


def test_replica_claim_is_write_once_and_prevents_all_copy_calls() -> None:
    inventory = _inventory()
    s3 = _FakeS3(inventory, marker_exists=True)

    with pytest.raises(ReplicaWriteOnceViolation, match="already claimed"):
        write_s3_replica(
            inventory,
            "campaign-a",
            "s3://test-leviathan/eda/silver",
            s3_client=s3,
        )

    assert not s3.copies
    assert s3.operations == [
        (
            "put",
            "eda/silver/campaign_id=campaign-a/table=silver_demo/"
            "_machine/source_replica/_WRITE_ONCE",
        )
    ]


def test_oversized_object_fails_preflight_before_claim() -> None:
    oversized = _entry(
        "part-000.parquet",
        size=MAX_SINGLE_COPY_BYTES + 1,
        etag="etag",
        version_id=None,
    )
    inventory = _inventory((oversized,))
    s3 = _FakeS3(inventory)

    with pytest.raises(ReplicaObjectTooLarge, match="5 GiB"):
        write_s3_replica(
            inventory,
            "campaign-a",
            "s3://test-leviathan/eda/silver",
            s3_client=s3,
        )

    assert s3.operations == []


@pytest.mark.parametrize(
    "output_root",
    [
        "s3://test-leviathan/gold",
        "s3://test-leviathan/eda/silver/extra",
        "s3://another-bucket/eda/silver",
    ],
)
def test_output_guard_accepts_only_same_bucket_exact_eda_silver_root(
    output_root: str,
) -> None:
    with pytest.raises(UnsafeReplicaDestination):
        validate_replica_output_root(output_root, expected_bucket="test-leviathan")


def test_output_guard_accepts_approved_root_with_trailing_slash() -> None:
    assert validate_replica_output_root(
        "s3://test-leviathan/eda/silver/",
        expected_bucket="test-leviathan",
    ) == ("test-leviathan", "eda/silver")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda inventory: replace(inventory, layer="gold"),
        lambda inventory: replace(
            inventory,
            root_uri="s3://test-leviathan/gold/demo",
        ),
        lambda inventory: replace(
            inventory,
            objects=(
                replace(
                    inventory.objects[0],
                    uri=("s3://test-leviathan/silver/demo/_shadow/part-000.parquet"),
                    key="silver/demo/_shadow/part-000.parquet",
                ),
            ),
        ),
        lambda inventory: replace(
            inventory,
            objects=(
                replace(
                    inventory.objects[0],
                    uri="s3://test-leviathan/silver/other/part-000.parquet",
                    key="silver/other/part-000.parquet",
                ),
            ),
        ),
        lambda inventory: replace(
            inventory,
            objects=(
                replace(
                    inventory.objects[0],
                    uri="s3://foreign/silver/demo/part-000.parquet",
                    bucket="foreign",
                    key="silver/demo/part-000.parquet",
                ),
            ),
        ),
    ],
)
def test_gold_control_and_foreign_sources_fail_before_claim(mutate) -> None:
    inventory = mutate(_inventory())
    s3 = _FakeS3(inventory)

    with pytest.raises(UnsafeReplicaSource):
        write_s3_replica(
            inventory,
            "campaign-a",
            "s3://test-leviathan/eda/silver",
            s3_client=s3,
        )

    assert s3.operations == []


def test_unpinned_source_fails_before_claim() -> None:
    unpinned = _entry(
        "part-000.parquet",
        size=10,
        etag="",
        version_id=None,
    )
    inventory = _inventory((unpinned,))
    s3 = _FakeS3(inventory)

    with pytest.raises(UnsafeReplicaSource, match="neither VersionId nor ETag"):
        write_s3_replica(
            inventory,
            "campaign-a",
            "s3://test-leviathan/eda/silver",
            s3_client=s3,
        )

    assert s3.operations == []


def test_destination_size_mismatch_aborts_before_manifest() -> None:
    inventory = _inventory()
    s3 = _FakeS3(inventory, destination_size_delta=1)

    with pytest.raises(ReplicaVerificationError, match="size mismatch"):
        write_s3_replica(
            inventory,
            "campaign-a",
            "s3://test-leviathan/eda/silver",
            s3_client=s3,
        )

    assert not any(key.endswith("/manifest.json") for key in s3.puts)


def test_destination_copy_response_and_head_identity_must_agree() -> None:
    inventory = _inventory()
    s3 = _FakeS3(inventory, head_etag_override="different-etag")

    with pytest.raises(ReplicaVerificationError, match="ETag mismatch"):
        write_s3_replica(
            inventory,
            "campaign-a",
            "s3://test-leviathan/eda/silver",
            s3_client=s3,
        )

    assert not any(key.endswith("/manifest.json") for key in s3.puts)


def test_empty_exact_inventory_still_creates_a_hash_bound_manifest() -> None:
    inventory = _inventory(())
    s3 = _FakeS3(inventory)

    artifact = write_s3_replica(
        inventory,
        "campaign-empty",
        "s3://test-leviathan/eda/silver",
        s3_client=s3,
    )

    _, manifest = _manifest_from(s3)
    assert artifact.object_count == 0
    assert artifact.total_bytes == 0
    assert manifest["objects"] == []
    assert manifest["replica_manifest_sha256"] == _manifest_digest(manifest)


def test_completed_replica_load_reconstructs_and_revalidates_exact_inventory() -> None:
    inventory = _inventory()
    s3 = _FakeS3(inventory)
    written = write_s3_replica(
        inventory,
        "campaign-load",
        "s3://test-leviathan/eda/silver",
        s3_client=s3,
    )

    loaded = load_s3_replica(
        table_name="silver_demo",
        campaign_id="campaign-load",
        output_root="s3://test-leviathan/eda/silver",
        expected_bucket="test-leviathan",
        expected_contract_sha256=inventory.contract_sha256,
        expected_root_uri=inventory.root_uri,
        s3_client=s3,
    )

    assert loaded.source_inventory.to_dict() == inventory.to_dict()
    assert loaded.replica_manifest_sha256 == written.replica_manifest_sha256
    assert loaded.objects == written.objects


def test_load_distinguishes_absent_and_partial_replica() -> None:
    inventory = _inventory()
    absent = _FakeS3(inventory)
    with pytest.raises(ReplicaNotFound, match="No replica exists"):
        load_s3_replica(
            table_name="silver_demo",
            campaign_id="campaign-absent",
            output_root="s3://test-leviathan/eda/silver",
            expected_bucket="test-leviathan",
            s3_client=absent,
        )

    partial = _FakeS3(inventory, marker_exists=True)
    with pytest.raises(PartialReplicaError, match="claimed but incomplete"):
        load_s3_replica(
            table_name="silver_demo",
            campaign_id="campaign-partial",
            output_root="s3://test-leviathan/eda/silver",
            expected_bucket="test-leviathan",
            s3_client=partial,
        )


def test_load_rejects_manifest_hash_and_physical_identity_drift() -> None:
    inventory = _inventory()
    s3 = _FakeS3(inventory)
    write_s3_replica(
        inventory,
        "campaign-drift",
        "s3://test-leviathan/eda/silver",
        s3_client=s3,
    )
    manifest_key, _ = _manifest_from(s3)
    original = s3.puts[manifest_key]["Body"]
    s3.puts[manifest_key]["Body"] = original.replace(
        b'"source_total_bytes":30', b'"source_total_bytes":31'
    )
    with pytest.raises(ReplicaManifestError, match="SHA-256"):
        load_s3_replica(
            table_name="silver_demo",
            campaign_id="campaign-drift",
            output_root="s3://test-leviathan/eda/silver",
            expected_bucket="test-leviathan",
            s3_client=s3,
        )

    s3.puts[manifest_key]["Body"] = original
    first_destination = next(iter(s3.destinations.values()))
    first_destination["ETag"] = '"changed"'
    with pytest.raises(ReplicaVerificationError, match="identity drift"):
        load_s3_replica(
            table_name="silver_demo",
            campaign_id="campaign-drift",
            output_root="s3://test-leviathan/eda/silver",
            expected_bucket="test-leviathan",
            s3_client=s3,
        )


def test_load_rejects_internally_inconsistent_destination_identity() -> None:
    inventory = _inventory()
    s3 = _FakeS3(inventory)
    write_s3_replica(
        inventory,
        "campaign-identity",
        "s3://test-leviathan/eda/silver",
        s3_client=s3,
    )
    manifest_key, manifest = _manifest_from(s3)
    manifest["objects"][0]["destination"]["identity"] = "etag:not-the-recorded-etag"
    manifest["replica_manifest_sha256"] = _manifest_digest(manifest)
    s3.puts[manifest_key]["Body"] = (
        json.dumps(
            manifest,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        + b"\n"
    )

    with pytest.raises(ReplicaManifestError, match="internally inconsistent"):
        load_s3_replica(
            table_name="silver_demo",
            campaign_id="campaign-identity",
            output_root="s3://test-leviathan/eda/silver",
            expected_bucket="test-leviathan",
            s3_client=s3,
        )


def test_wait_for_concurrent_replica_polls_until_manifest_is_visible() -> None:
    inventory = _inventory()
    s3 = _FakeS3(inventory)
    write_s3_replica(
        inventory,
        "campaign-race",
        "s3://test-leviathan/eda/silver",
        s3_client=s3,
    )
    manifest_key, _ = _manifest_from(s3)
    saved_manifest = s3.puts.pop(manifest_key)
    sleeps: list[float] = []

    def reveal_manifest(seconds: float) -> None:
        sleeps.append(seconds)
        s3.puts[manifest_key] = saved_manifest

    loaded = wait_for_s3_replica(
        table_name="silver_demo",
        campaign_id="campaign-race",
        output_root="s3://test-leviathan/eda/silver",
        expected_bucket="test-leviathan",
        s3_client=s3,
        timeout_seconds=5,
        poll_seconds=0.5,
        sleep_fn=reveal_manifest,
        monotonic_fn=lambda: 0.0,
    )

    assert loaded.source_manifest_sha256 == inventory.manifest_sha256
    assert sleeps == [0.5]
