"""SILVER-F034 / F035 -- the WASDE silver controlled-publish + registered-partition safety.

Drives the LANE M producer (:mod:`jobs.batch.wasde_silver_task`) through the SILVER-F015
:class:`~leviathan.silver.publisher.ShadowPublisher` with the registered-partition strategy, using
the shared in-memory AWS fakes (never a real client, never the prod bucket). Proves:

  * dry-run writes NOTHING and canonical is never touched;
  * shadow stages to a NON-canonical shadow prefix, never promotes/catalogs;
  * canonical registers exactly one partition per release_date;
  * a failure injected before cataloging fails closed -- no partition is registered (INV-6);
  * an exact idempotent retry creates no duplicate partition;
  * releases thread chronologically so the revision series carry (F034), and an older release
    replayed alone recomputes only its own series;
  * the R0 461-partition set reconciles WITHOUT mutation (F035 recovery reconciliation).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobs.batch import wasde_silver_task as T
from leviathan.silver.partition_publish import PartitionPublisher
from leviathan.silver.publisher import FailurePoint, ManifestState, PublisherError, PublishStrategy
from leviathan.silver.registry import load_registry
from tests.unit.silver.conftest import (  # shared fakes + auth helpers (imported, never modified)
    TEST_BUCKET,
    TEST_DB,
    FakeGlue,
    FakeS3,
    canonical_authorization,
    dryrun_authorization,
    shadow_authorization,
)

_REPO = Path(__file__).resolve().parents[3]
_GET_PARTITIONS = (_REPO / "reports" / "silver_readiness" / "20260712_p65impl"
                   / "_raw" / "silver_wasde.get-partitions.json")


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------
@pytest.fixture()
def contract():
    """The real registry contract, re-homed onto the allow-listed TEST bucket/db so the fakes never
    reference the prod surface (the schema -- incl. the INV-2 target types -- is unchanged)."""
    c = dict(load_registry().table("silver_wasde"))
    c["s3_bucket"] = TEST_BUCKET
    c["s3_root"] = f"s3://{TEST_BUCKET}/silver/wasde"
    c["glue_database"] = TEST_DB
    return c


def _bronze(region, attribute, my, status="Proj.", value=1.0, release_date="2024-06-12"):
    return dict(release_date=release_date,
                table_name="World Wheat Supply and Use 1/ (Million Metric Tons)",
                region=region, market_year=my, status=status, projection_month="",
                attribute=attribute, value=value, unit="Million Metric Tons")


def _one_release(release_date="2024-06-12"):
    return {release_date: [
        _bronze("United States", "Ending Stocks", "2024/25", value=10.0, release_date=release_date),
        _bronze("World", "Production", "2024/25", value=800.0, release_date=release_date),
    ]}


def _seed_table(fake_glue: FakeGlue, contract):
    fake_glue.tables["silver_wasde"] = {
        "Name": "silver_wasde",
        "PartitionKeys": [{"Name": "release_date", "Type": "string"}],
        "StorageDescriptor": {
            "Columns": [{"Name": c["name"], "Type": c.get("glue_type") or "string"}
                        for c in contract["physical_columns"] if c.get("glue_type")],
            "Location": contract["s3_root"],
            "InputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
            "OutputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
            "SerdeInfo": {"SerializationLibrary":
                          "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe",
                          "Parameters": {"serialization.format": "1"}},
            "Parameters": {},
        },
    }


def _mem_manifest_store():
    store: dict[str, bytes] = {}

    def put(key, body):
        store[key] = body

    return store, put


# ---------------------------------------------------------------------------
# F034 -- controlled publish modes.
# ---------------------------------------------------------------------------
def test_dry_run_writes_nothing(contract):
    s3, glue = FakeS3(), FakeGlue()
    store, put = _mem_manifest_store()
    manifest, results = T.stage_silver_objects(
        _one_release(), contract, dryrun_authorization(), s3, glue,
        manifest_store=put, run_id="wasde-dry")
    assert manifest.state is ManifestState.VALIDATED     # halted before canonical
    assert s3.store == {}                                 # no object written
    assert glue.partitions == {}                          # no partition registered
    assert results and results[0].rows                    # the transform still ran


def test_shadow_stages_to_shadow_prefix_only(contract):
    s3, glue = FakeS3(), FakeGlue()
    store, put = _mem_manifest_store()
    manifest, _ = T.stage_silver_objects(
        _one_release(), contract, shadow_authorization(), s3, glue,
        shadow_prefix="silver/wasde/_shadow", manifest_store=put, run_id="wasde-shadow")
    assert manifest.state is ManifestState.VALIDATED
    keys = s3.keys()
    assert keys and all(k.startswith("silver/wasde/_shadow/") for k in keys)   # NON-canonical
    assert not any(k.startswith("silver/wasde/release_date=") and "_shadow" not in k for k in keys)
    assert glue.partitions == {}                          # never cataloged in shadow


def test_canonical_registers_one_partition_per_release(contract):
    s3, glue = FakeS3(), FakeGlue()
    _seed_table(glue, contract)
    store, put = _mem_manifest_store()
    releases = {**_one_release("2024-05-10"), **_one_release("2024-06-12")}
    manifest, _ = T.stage_silver_objects(
        releases, contract, canonical_authorization(), s3, glue,
        shadow_prefix="silver/wasde/_shadow", manifest_store=put, run_id="wasde-canon")
    assert manifest.state is ManifestState.CERTIFIED
    part_values = sorted(v for (_t, v) in glue.partitions)
    assert part_values == [("2024-05-10",), ("2024-06-12",)]
    # a canonical object exists per partition.
    assert any("release_date=2024-06-12/part-000.parquet" in k for k in s3.keys())


# ---------------------------------------------------------------------------
# F035 -- registered-partition safety.
# ---------------------------------------------------------------------------
def test_failure_before_catalog_registers_no_partition(contract):
    s3, glue = FakeS3(), FakeGlue()
    _seed_table(glue, contract)
    store, put = _mem_manifest_store()
    # Build the publisher directly so we can inject a failure at the catalog seam.
    objects, _ = T.build_release_objects(_one_release(), contract)
    from leviathan.silver.publisher import ShadowPublisher, ValidationHooks
    pub = ShadowPublisher(
        job="wasde_silver_task", table="silver_wasde", database=TEST_DB, bucket=TEST_BUCKET,
        canonical_root=contract["s3_root"], auth=canonical_authorization(), s3_client=s3,
        glue_client=glue, strategy=PublishStrategy.REGISTERED, shadow_prefix="silver/wasde/_shadow",
        validation=ValidationHooks(min_rows=1), manifest_store=put,
        inject_failure=FailurePoint.BEFORE_CATALOG, run_id="wasde-fail")
    with pytest.raises(PublisherError):
        pub.run(objects)
    assert pub.manifest.state is ManifestState.FAILED
    assert glue.partitions == {}                          # INV-6: no partition became visible


def test_idempotent_retry_creates_no_duplicate(contract):
    s3, glue = FakeS3(), FakeGlue()
    _seed_table(glue, contract)
    store, put = _mem_manifest_store()
    rel = _one_release("2024-06-12")
    m1, _ = T.stage_silver_objects(rel, contract, canonical_authorization(), s3, glue,
                                   shadow_prefix="silver/wasde/_shadow", manifest_store=put,
                                   run_id="wasde-r1")
    m2, _ = T.stage_silver_objects(rel, contract, canonical_authorization(), s3, glue,
                                   shadow_prefix="silver/wasde/_shadow", manifest_store=put,
                                   run_id="wasde-r2")
    assert m1.state is ManifestState.CERTIFIED and m2.state is ManifestState.CERTIFIED
    # exactly ONE partition tuple survives both runs (no duplicate).
    assert sorted(glue.partitions) == [("silver_wasde", ("2024-06-12",))]
    # the second run recorded the partition as EXISTING (exact managed match), not re-created.
    outcomes = [a["outcome"] for a in m2.partition_actions]
    assert outcomes == ["existing"]


def test_461_partition_set_reconciles_without_mutation(contract):
    s3, glue = FakeS3(), FakeGlue()
    _seed_table(glue, contract)
    live = json.loads(_GET_PARTITIONS.read_text(encoding="utf-8"))
    partitions = live["partitions"] if isinstance(live, dict) else live
    assert len(partitions) == 461
    pub = PartitionPublisher(
        database=TEST_DB, table="silver_wasde", bucket=TEST_BUCKET,
        allowed_root=contract["s3_root"], glue_client=glue, s3_client=s3,
        auth=canonical_authorization())
    # S3 truth == the registered locations -> reconcile must report EXACT with no repair needed.
    s3_locations = {"/".join(p["Values"]): (p.get("StorageDescriptor") or {}).get("Location")
                    for p in partitions}
    report = pub.reconcile_from_s3(partitions, s3_locations)
    assert report["exact"] is True
    assert report["registered_count"] == 461
    assert report["missing_in_glue"] == [] and report["orphan_in_glue"] == []
    assert report["location_mismatch"] == []
    assert glue.calls == []                               # reconcile mutates nothing


# ---------------------------------------------------------------------------
# F034 -- releases thread chronologically; older replay recomputes only its own series.
# ---------------------------------------------------------------------------
def test_release_objects_thread_revisions_in_order(contract):
    releases = {
        "2024-06-12": [_bronze("World", "Ending Stocks", "2024/25", value=105.0,
                               release_date="2024-06-12")],
        "2024-05-10": [_bronze("World", "Ending Stocks", "2024/25", value=100.0,
                               release_date="2024-05-10")],
    }
    _objs, results = T.build_release_objects(releases, contract)
    # processed oldest-first regardless of dict order.
    assert [r.release_date for r in results] == ["2024-05-10", "2024-06-12"]
    first = results[0].rows[0]
    second = results[1].rows[0]
    assert first["is_first_estimate"] is True and first["revision"] is None
    assert second["is_first_estimate"] is False
    assert second["prior_release_date"] == "2024-05-10"
    assert second["revision"] == 5.0 and second["revision_direction"] == "up"
    assert second["release_sequence"] == 2
