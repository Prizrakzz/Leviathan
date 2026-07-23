"""SILVER-F013: exact, repairable registered-partition publication -- create, exact idempotent reuse,
wrong-location rejection, authorized repair, partial batch, recovery from certified evidence, S3->Glue
reconciliation, ESR as_of mapping, and canonical-guard denial. In-memory fakes; AWS-free."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from leviathan.silver.lease import Lease, LeaseLost
from leviathan.silver.partition_publish import (
    PartitionPublisher,
    PartitionSpec,
    PublicationResult,
    PartitionOutcome,
    RepairAuthorization,
    esr_partition_location,
)

from tests.unit.silver.conftest import (
    canonical_authorization,
    dryrun_authorization,
)

ROOT = "s3://leviathan-test/silver/production/source=usda_esr"
BUCKET = "leviathan-test"


def _sd(location):
    return {
        "Columns": [{"Name": "commodity_name", "Type": "string"}],
        "Location": location,
        "InputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
        "OutputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
        "SerdeInfo": {"SerializationLibrary": "serde", "Parameters": {"serialization.format": "1"}},
        "Parameters": {},
    }


def _publisher(fake_glue, fake_s3, auth=None, lease=None, token=None, validator=None):
    return PartitionPublisher(
        database="leviathan_test", table="silver_esr", bucket=BUCKET, allowed_root=ROOT,
        glue_client=fake_glue, s3_client=fake_s3, auth=auth or canonical_authorization(),
        table_sd=_sd(ROOT), lease=lease, fencing_token=token,
        object_validator=validator or (lambda k: (True, "ok")),
    )


def _spec(cc, my, asof):
    loc = esr_partition_location(ROOT, cc, my, asof)
    return PartitionSpec(values=[str(cc), str(my), asof], location=loc,
                         object_key=f"silver/production/source=usda_esr/commodity_code={cc}"
                                    f"/market_year={my}/as_of={asof}/part-000.parquet")


def test_esr_location_maps_column_to_as_of_directory():
    loc = esr_partition_location(ROOT, 101, 2000, "20260524")
    assert loc.endswith("/commodity_code=101/market_year=2000/as_of=20260524/")
    assert "as_of_date=" not in loc  # directory key is as_of, NOT as_of_date (step 8)


def test_create_new_partition(fake_glue, fake_s3):
    pub = _publisher(fake_glue, fake_s3)
    res = pub.publish([_spec(101, 2000, "20260524")])
    assert res.created == 1 and res.failed == 0
    assert ("silver_esr", ("101", "2000", "20260524")) in fake_glue.partitions


def test_exact_idempotent_reuse(fake_glue, fake_s3):
    pub = _publisher(fake_glue, fake_s3)
    spec = _spec(101, 2000, "20260524")
    pub.publish([spec])
    res2 = pub.publish([spec])  # same location -> exact match, no-op
    assert res2.existing == 1 and res2.created == 0 and res2.failed == 0
    assert res2.actions[0].outcome is PartitionOutcome.EXISTING


def test_wrong_location_rejected_without_repair(fake_glue, fake_s3):
    pub = _publisher(fake_glue, fake_s3)
    spec = _spec(101, 2000, "20260524")
    pub.publish([spec])
    # now attempt to publish the SAME values at a DIFFERENT location, no repair authority.
    wrong = PartitionSpec(values=["101", "2000", "20260524"],
                          location=ROOT + "/commodity_code=101/market_year=2000/as_of=WRONG/",
                          object_key="silver/production/source=usda_esr/x/part-000.parquet")
    res = pub.publish([wrong])
    assert res.failed == 1 and res.repaired == 0
    assert "no repair authority" in res.actions[0].detail


def test_authorized_repair_updates_location(fake_glue, fake_s3):
    pub = _publisher(fake_glue, fake_s3)
    spec = _spec(101, 2000, "20260524")
    pub.publish([spec])
    new_loc = ROOT + "/commodity_code=101/market_year=2000/as_of=20260524/_run=v2/"
    versioned = PartitionSpec(values=["101", "2000", "20260524"], location=new_loc,
                              object_key="silver/production/source=usda_esr/v2/part-000.parquet")
    repair = RepairAuthorization.for_values([["101", "2000", "20260524"]])
    res = pub.publish([versioned], repair=repair)
    assert res.repaired == 1 and res.failed == 0
    stored = fake_glue.partitions[("silver_esr", ("101", "2000", "20260524"))]
    assert stored["StorageDescriptor"]["Location"] == new_loc


def test_location_outside_allowed_root_fails(fake_glue, fake_s3):
    pub = _publisher(fake_glue, fake_s3)
    bad = PartitionSpec(values=["101", "2000", "20260524"],
                        location="s3://leviathan-test/OTHER/x/", object_key="OTHER/x/part.parquet")
    res = pub.publish([bad])
    assert res.failed == 1
    assert "allowed root" in res.actions[0].detail


def test_new_partition_validation_failure_blocks_registration(fake_glue, fake_s3):
    pub = _publisher(fake_glue, fake_s3, validator=lambda k: (False, "zero bytes"))
    res = pub.publish([_spec(101, 2000, "20260524")])
    assert res.failed == 1 and res.created == 0
    assert ("silver_esr", ("101", "2000", "20260524")) not in fake_glue.partitions


def test_partial_batch_failure_isolated(fake_glue, fake_s3):
    # one good, one outside root.
    good = _spec(101, 2000, "20260524")
    bad = PartitionSpec(values=["999", "2000", "20260524"],
                        location="s3://leviathan-test/OTHER/", object_key="OTHER/part.parquet")
    res = _publisher(fake_glue, fake_s3).publish([good, bad])
    assert res.created == 1 and res.failed == 1
    assert not res.ok


def test_dryrun_plans_but_does_not_register(fake_glue, fake_s3):
    pub = _publisher(fake_glue, fake_s3, auth=dryrun_authorization())
    res = pub.publish([_spec(101, 2000, "20260524")])
    assert res.planned == 1 and res.created == 0
    assert fake_glue.partitions == {}  # canonical catalog untouched


def test_fencing_token_stale_aborts_create(fake_s3, fake_glue):
    lease = Lease(bucket=BUCKET, prefix="silver/", lock_id="silver_esr._table", s3_client=fake_s3,
                  owner="op-a", run_id="r1", ttl_seconds=100)
    base = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)
    granted = lease.acquire(now=base)
    # someone steals the lease.
    other = Lease(bucket=BUCKET, prefix="silver/", lock_id="silver_esr._table", s3_client=fake_s3,
                  owner="op-b", run_id="r2", ttl_seconds=100)
    from datetime import timedelta
    other.acquire(now=base + timedelta(seconds=200))
    pub = _publisher(fake_glue, fake_s3, lease=lease, token=granted.fencing_token)
    res = pub.publish([_spec(101, 2000, "20260524")])
    # publish() captures the LeaseLost per-partition as a FAILED outcome (never mutates).
    assert res.failed == 1 and res.created == 0
    assert fake_glue.partitions == {}


def test_s3_to_glue_reconciliation_detects_location_mismatch(fake_glue, fake_s3):
    pub = _publisher(fake_glue, fake_s3)
    live = [
        {"Values": ["101", "2000", "20260524"],
         "StorageDescriptor": {"Location": ROOT + "/commodity_code=101/market_year=2000/as_of=20260524/"}},
        {"Values": ["102", "2001", "20260524"],
         "StorageDescriptor": {"Location": ROOT + "/commodity_code=102/market_year=2001/as_of=OLD/"}},
    ]
    s3 = {
        "101/2000/20260524": ROOT + "/commodity_code=101/market_year=2000/as_of=20260524/",
        "102/2001/20260524": ROOT + "/commodity_code=102/market_year=2001/as_of=20260524/",  # moved
        "103/2002/20260524": ROOT + "/commodity_code=103/market_year=2002/as_of=20260524/",  # new
    }
    report = pub.reconcile_from_s3(live, s3)
    assert report["exact"] is False
    assert report["missing_in_glue"] == ["103/2002/20260524"]
    assert len(report["location_mismatch"]) == 1
    assert report["location_mismatch"][0]["values"] == ["102", "2001", "20260524"]


def test_recovery_requires_certified_manifest(fake_glue, fake_s3):
    pub = _publisher(fake_glue, fake_s3)
    with pytest.raises(Exception):
        pub.recover([_spec(101, 2000, "20260524")], run_manifest={"state": "VALIDATED"})


def test_recovery_registers_with_certified_manifest_and_fingerprint(fake_glue, fake_s3):
    pub = _publisher(fake_glue, fake_s3)
    spec = _spec(101, 2000, "20260524")
    res = pub.recover(
        [spec], run_manifest={"state": "CERTIFIED"},
        expected_fingerprint="fp1", fingerprint_fn=lambda k: "fp1",
    )
    assert res.created == 1 and res.failed == 0


def test_recovery_fingerprint_mismatch_fails(fake_glue, fake_s3):
    pub = _publisher(fake_glue, fake_s3)
    spec = _spec(101, 2000, "20260524")
    res = pub.recover(
        [spec], run_manifest={"state": "CERTIFIED"},
        expected_fingerprint="fp1", fingerprint_fn=lambda k: "DIFFERENT",
    )
    assert res.failed == 1 and res.created == 0
    assert ("silver_esr", ("101", "2000", "20260524")) not in fake_glue.partitions


def test_athena_smoke_sql_is_sargable_and_filtered():
    pub = _publisher(None, None)
    sql = pub.athena_smoke_sql(["101", "2000", "20260524"], ["commodity_code", "market_year", "as_of_date"])
    assert "commodity_code = '101'" in sql
    assert "market_year = '2000'" in sql
    assert "as_of_date = '20260524'" in sql
    assert "count(*)" in sql


# --------------------------------------------------------------------------- schema-widen reconcile (F047)
_WIDEN_COLS = [
    {"Name": "date", "Type": "date"},
    {"Name": "value", "Type": "double"},
    {"Name": "country", "Type": "string"},
    {"Name": "region", "Type": "string"},
    {"Name": "month", "Type": "bigint"},
]
_PREWIDEN_COLS = _WIDEN_COLS[:2]  # the pre-widen partition descriptor (leading prefix)


def _widen_sd(location, cols):
    sd = _sd(location)
    sd["Columns"] = cols
    return sd


def _widen_publisher(fake_glue, fake_s3, *, reconcile):
    return PartitionPublisher(
        database="leviathan_test", table="silver_esr", bucket=BUCKET, allowed_root=ROOT,
        glue_client=fake_glue, s3_client=fake_s3, auth=canonical_authorization(),
        table_sd=_widen_sd(ROOT, _WIDEN_COLS),          # TABLE carries the widened (14-col-style) SD
        object_validator=lambda k: (True, "ok"), reconcile_schema_widen=reconcile,
    )


def _seed_prewiden_partition(fake_glue, spec, cols=_PREWIDEN_COLS):
    key = ("silver_esr", tuple(spec.values))
    fake_glue.partitions[key] = {"Values": list(spec.values),
                                 "StorageDescriptor": _widen_sd(spec.location, cols)}
    return key


def test_schema_widen_reconciled_when_enabled(fake_glue, fake_s3):
    spec = _spec(101, 2000, "20260524")
    key = _seed_prewiden_partition(fake_glue, spec)         # partition SD narrower than table SD
    pub = _widen_publisher(fake_glue, fake_s3, reconcile=True)
    res = pub.publish([spec])
    assert res.repaired == 1 and res.failed == 0
    # partition SD is now the widened table columns (country/region/month projectable), location intact.
    stored = fake_glue.partitions[key]["StorageDescriptor"]
    assert [c["Name"] for c in stored["Columns"]] == [c["Name"] for c in _WIDEN_COLS]
    assert stored["Location"] == spec.location


def test_schema_widen_fails_closed_when_disabled(fake_glue, fake_s3):
    # default OFF: the pre-widen partition still fails (the observed Jul-22/23 daily behavior).
    spec = _spec(101, 2000, "20260524")
    _seed_prewiden_partition(fake_glue, spec)
    pub = _widen_publisher(fake_glue, fake_s3, reconcile=False)
    res = pub.publish([spec])
    assert res.failed == 1 and res.repaired == 0
    assert "no repair authority" in res.actions[0].detail


def test_reconcile_does_not_repoint_wrong_location(fake_glue, fake_s3):
    # a genuinely WRONG-location partition (not a widen) must still fail even with reconcile ON.
    spec = _spec(101, 2000, "20260524")
    wrong_loc = ROOT + "/commodity_code=101/market_year=2000/as_of=WRONG/"
    _seed_prewiden_partition(  # existing registered at the WRONG location, narrow cols
        fake_glue, PartitionSpec(values=spec.values, location=wrong_loc), cols=_PREWIDEN_COLS)
    pub = _widen_publisher(fake_glue, fake_s3, reconcile=True)
    res = pub.publish([spec])   # desired location differs -> not a widen -> fail closed
    assert res.failed == 1 and res.repaired == 0
    assert fake_glue.partitions[("silver_esr", tuple(spec.values))]["StorageDescriptor"]["Location"] == wrong_loc
