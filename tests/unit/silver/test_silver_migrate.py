"""SILVER-F012: plan/apply/rollback catalog migration tool.

Covers: registry-enumerated planning (create / additive-update / property-update / no-op), unsafe-diff
refusal (drop column, partition-key change, type narrowing), CREATE-is-bootstrap-only, concurrent
apply rejection (live-hash drift), stale-fence rejection, registered-partition SD audit, migration
manifest emission, rollback-plan from an R0 _raw snapshot, and executable restore with hash/fence
protection + post-restore verification. In-memory fakes; AWS-free."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from leviathan.silver import catalog
from leviathan.silver.lease import Lease
from leviathan.silver.migrate import (
    CatalogMigrator,
    ChangeType,
    MigrationConflict,
    UnsafeMigration,
    build_desired_table,
    raw_snapshot_to_table_input,
)

from tests.unit.silver.conftest import canonical_authorization, dryrun_authorization

BUCKET = "leviathan-test"
BASE = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)


# A minimal registry contract (bypasses the real 43-file registry so the test is self-contained).
def _contract(name="silver_demo", cols=None, pks=None, root="s3://leviathan-test/silver/demo",
              partition_mode="flat"):
    return {
        "table_name": name,
        "s3_root": root,
        "partition_mode": partition_mode,
        "physical_columns": cols or [
            {"name": "a", "glue_type": "string"}, {"name": "b", "glue_type": "double"}],
        "partition_keys": pks or [],
    }


class _Reg:
    def __init__(self, contracts):
        self.tables = {c["table_name"]: c for c in contracts}

    def names(self):
        return sorted(self.tables)


def _migrator(fake_glue, contracts, auth=None, lease=None, token=None, tmp=None):
    return CatalogMigrator(
        database="leviathan_test", auth=auth or canonical_authorization(), glue_client=fake_glue,
        registry=_Reg(contracts), lease=lease, fencing_token=token, migrations_dir=tmp,
    )


def _held_lease(fake_s3):
    # Acquire at real now with a long TTL so the production recheck (which uses real wall-clock now)
    # passes deterministically throughout the test.
    lease = Lease(bucket=BUCKET, prefix="silver/", lock_id="leviathan_test._table",
                  s3_client=fake_s3, owner="op-a", run_id="r1", ttl_seconds=100_000)
    state = lease.acquire()
    return lease, state.fencing_token


def _simulate_theft(fake_s3, lease):
    """Deterministically overwrite the lock object with a different holder (higher token, far-future
    expiry) -- as if another operator stole the lease -- so a recheck fences op-a out regardless of
    wall-clock time."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from leviathan.silver.lease import LeaseState
    far = (_dt.now(_tz.utc) + _td(hours=1)).isoformat()
    stolen = LeaseState(lock_id=lease.lock_id, owner="op-b", run_id="r2",
                        fencing_token=(lease.state.fencing_token + 1),
                        acquired_at=far, expires_at=far, heartbeat_at=far)
    fake_s3.store[(BUCKET, lease.key)] = stolen.to_json()


def _live_from_desired(desired, ddl="111"):
    """Simulate a live Glue table equal to the desired (plus AWS noise)."""
    live = json.loads(json.dumps(desired))
    live["Parameters"] = {**live.get("Parameters", {}), "transient_lastDdlTime": ddl}
    live["VersionId"] = "1"
    return live


# --------------------------------------------------------------------------- desired synthesis
def test_build_desired_table_shape():
    d = build_desired_table(_contract())
    assert d["TableType"] == "EXTERNAL_TABLE"
    assert d["StorageDescriptor"]["Location"] == "s3://leviathan-test/silver/demo"
    assert [c["Name"] for c in d["StorageDescriptor"]["Columns"]] == ["a", "b"]
    assert d["Parameters"]["EXTERNAL"] == "TRUE"


# --------------------------------------------------------------------------- plan classification
def test_plan_create_when_absent(fake_glue):
    mig = _migrator(fake_glue, [_contract()])
    plan = mig.plan_table("silver_demo")
    assert plan.change_type is ChangeType.CREATE
    assert plan.live_hash is None
    assert "create_table" in plan.glue_call


def test_plan_noop_when_identical(fake_glue):
    contract = _contract()
    desired = build_desired_table(contract)
    fake_glue.tables["silver_demo"] = _live_from_desired(desired)
    plan = _migrator(fake_glue, [contract]).plan_table("silver_demo")
    assert plan.is_noop and plan.change_type is ChangeType.NOOP


def test_plan_additive_update_on_new_column(fake_glue):
    contract = _contract()
    desired = build_desired_table(contract)
    fake_glue.tables["silver_demo"] = _live_from_desired(desired)
    # registry gains a column -> additive update.
    contract2 = _contract(cols=[{"name": "a", "glue_type": "string"},
                                 {"name": "b", "glue_type": "double"},
                                 {"name": "c", "glue_type": "int"}])
    plan = _migrator(fake_glue, [contract2]).plan_table("silver_demo")
    assert plan.change_type is ChangeType.ADDITIVE_UPDATE
    assert any("columns" in d for d in plan.diffs)
    assert not plan.unsafe


def test_plan_property_update_only(fake_glue):
    contract = _contract(partition_mode="projected",
                         pks=[{"name": "y", "glue_type": "int", "projected": True}])
    desired = build_desired_table(contract)
    # live is same but missing the projection.enabled param -> property-only diff.
    live = _live_from_desired(desired)
    live["Parameters"].pop("projection.enabled", None)
    fake_glue.tables["silver_demo"] = live
    plan = _migrator(fake_glue, [contract]).plan_table("silver_demo")
    assert plan.change_type is ChangeType.PROPERTY_UPDATE


# --------------------------------------------------------------------------- unsafe refusals
def test_unsafe_drop_column_refused(fake_glue):
    # live has an extra column the registry no longer declares -> DROP.
    contract = _contract(cols=[{"name": "a", "glue_type": "string"}])
    desired = build_desired_table(contract)
    live = _live_from_desired(desired)
    live["StorageDescriptor"]["Columns"].append({"Name": "b", "Type": "double"})
    fake_glue.tables["silver_demo"] = live
    mig = _migrator(fake_glue, [contract])
    plan = mig.plan_table("silver_demo")
    assert any("DROP column" in u for u in plan.unsafe)
    with pytest.raises(UnsafeMigration):
        mig.apply_table(plan)


def test_unsafe_type_narrowing_refused(fake_glue):
    contract = _contract(cols=[{"name": "a", "glue_type": "string"},
                               {"name": "b", "glue_type": "int"}])   # registry says int (narrow)
    desired = build_desired_table(contract)
    live = _live_from_desired(desired)
    # live is bigint -> registry int == narrowing.
    for c in live["StorageDescriptor"]["Columns"]:
        if c["Name"] == "b":
            c["Type"] = "bigint"
    fake_glue.tables["silver_demo"] = live
    plan = _migrator(fake_glue, [contract]).plan_table("silver_demo")
    assert any("NARROW" in u for u in plan.unsafe)


def test_unsafe_partition_key_change_refused(fake_glue):
    contract = _contract(pks=[{"name": "y", "glue_type": "int"}], partition_mode="registered")
    desired = build_desired_table(contract)
    live = _live_from_desired(desired)
    live["PartitionKeys"] = [{"Name": "z", "Type": "int"}]  # different key name
    fake_glue.tables["silver_demo"] = live
    plan = _migrator(fake_glue, [contract]).plan_table("silver_demo")
    assert any("partition-key change" in u for u in plan.unsafe)


# --------------------------------------------------------------------------- apply
def test_apply_create_writes_table_and_manifest(fake_s3, fake_glue, tmp_path):
    lease, token = _held_lease(fake_s3)
    mig = _migrator(fake_glue, [_contract()], lease=lease, token=token, tmp=tmp_path)
    plan = mig.plan_table("silver_demo")
    out = mig.apply_table(plan)
    assert out["applied"] is True and out["change_type"] == "create"
    assert "silver_demo" in fake_glue.tables
    # migration manifest emitted under the (tmp) migrations dir.
    manifests = list(tmp_path.glob("*_silver_demo_create.json"))
    assert len(manifests) == 1
    payload = json.loads(manifests[0].read_text())
    assert payload["change_type"] == "create" and payload["guard_mode"] == "canonical"


def test_apply_create_is_bootstrap_only_conflict_if_now_exists(fake_s3, fake_glue, tmp_path):
    lease, token = _held_lease(fake_s3)
    contract = _contract()
    mig = _migrator(fake_glue, [contract], lease=lease, token=token, tmp=tmp_path)
    plan = mig.plan_table("silver_demo")  # planned CREATE
    # table appears after the plan was cut.
    fake_glue.tables["silver_demo"] = _live_from_desired(build_desired_table(contract))
    with pytest.raises(MigrationConflict):
        mig.apply_table(plan)


def test_apply_refused_on_live_hash_drift(fake_s3, fake_glue, tmp_path):
    lease, token = _held_lease(fake_s3)
    contract = _contract(cols=[{"name": "a", "glue_type": "string"},
                               {"name": "b", "glue_type": "double"},
                               {"name": "c", "glue_type": "int"}])
    fake_glue.tables["silver_demo"] = _live_from_desired(
        build_desired_table(_contract()))  # live has 2 cols
    mig = _migrator(fake_glue, [contract], lease=lease, token=token, tmp=tmp_path)
    plan = mig.plan_table("silver_demo")  # additive update, live_hash frozen
    # someone else mutates the live table after the plan was cut.
    drifted = _live_from_desired(build_desired_table(_contract()))
    drifted["StorageDescriptor"]["Columns"].append({"Name": "zzz", "Type": "string"})
    fake_glue.tables["silver_demo"] = drifted
    with pytest.raises(MigrationConflict):
        mig.apply_table(plan)


def test_apply_refused_on_stale_fence(fake_s3, fake_glue, tmp_path):
    lease, token = _held_lease(fake_s3)
    mig = _migrator(fake_glue, [_contract()], lease=lease, token=token, tmp=tmp_path)
    plan = mig.plan_table("silver_demo")
    _simulate_theft(fake_s3, lease)  # another operator stole the lease after we planned
    with pytest.raises(Exception):  # LeaseLost surfaces via _fence (before the create_table call)
        mig.apply_table(plan)
    assert "silver_demo" not in fake_glue.tables


def test_apply_without_lease_refused(fake_glue, tmp_path):
    mig = _migrator(fake_glue, [_contract()], tmp=tmp_path)  # no lease/token
    plan = mig.plan_table("silver_demo")
    with pytest.raises(MigrationConflict):
        mig.apply_table(plan)


def test_dryrun_apply_plans_only(fake_glue, tmp_path):
    mig = _migrator(fake_glue, [_contract()], auth=dryrun_authorization(), tmp=tmp_path)
    plan = mig.plan_table("silver_demo")
    out = mig.apply_table(plan)
    assert out["applied"] is False and out["reason"] == "non-canonical-plan-only"
    assert "silver_demo" not in fake_glue.tables


# --------------------------------------------------------------------------- registered partition audit
def test_registered_partition_audit_on_schema_change(fake_glue):
    contract = _contract(name="silver_esr", partition_mode="registered",
                         pks=[{"name": "as_of_date", "glue_type": "string"}],
                         cols=[{"name": "a", "glue_type": "string"},
                               {"name": "b", "glue_type": "double"},
                               {"name": "c", "glue_type": "int"}])
    live = _live_from_desired(build_desired_table(_contract(
        name="silver_esr", partition_mode="registered",
        pks=[{"name": "as_of_date", "glue_type": "string"}])))
    fake_glue.tables["silver_esr"] = live
    plan = _migrator(fake_glue, [contract]).plan_table("silver_esr")
    assert plan.registered_partition_audit is not None
    assert plan.registered_partition_audit["registered"] is True
    assert "F013" in plan.registered_partition_audit["action"]


# --------------------------------------------------------------------------- rollback + restore
def _raw_snapshot():
    return {
        "Name": "silver_demo", "DatabaseName": "leviathan_test", "TableType": "EXTERNAL_TABLE",
        "CreateTime": "2026-06-23 17:41:11+03:00", "UpdateTime": "2026-07-05 05:11:21+03:00",
        "VersionId": "1", "CreatedBy": "arn:aws:iam::x:user/y", "CatalogId": "x",
        "IsRegisteredWithLakeFormation": False, "IsMultiDialectView": False,
        "IsMaterializedView": False,
        "PartitionKeys": [],
        "Parameters": {"EXTERNAL": "TRUE", "transient_lastDdlTime": "999"},
        "StorageDescriptor": {
            "Columns": [{"Name": "a", "Type": "string"}, {"Name": "b", "Type": "double"}],
            "Location": "s3://leviathan-test/silver/demo",
            "InputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
            "OutputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
            "SerdeInfo": {"SerializationLibrary": "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe",
                          "Parameters": {"serialization.format": "1"}},
            "Parameters": {},
        },
    }


def test_raw_snapshot_to_table_input_drops_readonly_fields():
    ti = raw_snapshot_to_table_input(_raw_snapshot())
    for banned in ("CreateTime", "UpdateTime", "VersionId", "CreatedBy", "CatalogId",
                   "DatabaseName", "IsRegisteredWithLakeFormation"):
        assert banned not in ti
    assert ti["Name"] == "silver_demo"


def test_rollback_plan_is_readonly(fake_glue):
    mig = _migrator(fake_glue, [_contract()])
    out = mig.rollback_plan("silver_demo", snapshot=_raw_snapshot())
    assert "update_table" in out["restore_call"]
    assert out["expected_hash_after"] == catalog.hash_table(
        raw_snapshot_to_table_input(_raw_snapshot()))
    assert fake_glue.tables == {}  # nothing mutated


def test_restore_executes_and_verifies(fake_s3, fake_glue):
    lease, token = _held_lease(fake_s3)
    mig = _migrator(fake_glue, [_contract()], lease=lease, token=token)
    out = mig.restore_table("silver_demo", snapshot=_raw_snapshot())
    assert out["restored"] is True
    assert "silver_demo" in fake_glue.tables
    assert out["verified_hash"] == catalog.hash_table(raw_snapshot_to_table_input(_raw_snapshot()))


def test_restore_refused_if_current_hash_mismatches(fake_s3, fake_glue):
    lease, token = _held_lease(fake_s3)
    fake_glue.tables["silver_demo"] = _live_from_desired(build_desired_table(_contract()))
    mig = _migrator(fake_glue, [_contract()], lease=lease, token=token)
    with pytest.raises(MigrationConflict):
        mig.restore_table("silver_demo", snapshot=_raw_snapshot(),
                          expected_current_hash="deadbeef")  # wrong expected hash


def test_narrowing_check_is_direction_aware():
    # Live-caught at the BF-W3 ONI T7 flag widen: tinyint->bigint (int8->int64) is a WIDEN and
    # must be applyable; the reverse stays refused. Unparseable widths stay fail-closed.
    from leviathan.silver.types import is_narrowing_change

    assert is_narrowing_change("int64", "int32") is True      # narrow refused
    assert is_narrowing_change("int32", "int64") is False     # widen legal
    assert is_narrowing_change("int8", "int64") is False      # the ONI flag widen
    assert is_narrowing_change("float64", "float32") is True
    assert is_narrowing_change("float32", "float64") is False
    assert is_narrowing_change("float64", "int64") is True    # base change refused
    assert is_narrowing_change("int64", "int64") is False     # no-op
    assert is_narrowing_change("timestamp[us]", "timestamp[ms]") is True  # fail-closed
