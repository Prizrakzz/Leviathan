"""SILVER-F081: catalog/object recovery rehearsal tool.

The isolation guard must refuse the prod db / prod bucket / canonical mode FAIL-CLOSED (before any
mutation), the snapshot round-trip must verify byte-for-byte on the managed catalog subset (a real
registered-partition table from the R0 baseline), and a corrupted readback must be caught.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_TOOL = _REPO / "scripts" / "silver" / "rehearse_recovery.py"


@pytest.fixture(scope="module")
def rr():
    spec = importlib.util.spec_from_file_location("rehearse_recovery", _TOOL)
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so the frozen dataclasses can resolve string annotations.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Isolation guard -- fail-closed.
# ---------------------------------------------------------------------------
class TestIsolationGuard:
    def test_refuses_prod_database(self, rr):
        with pytest.raises(rr.RehearsalGuardError) as exc:
            rr.assert_rehearsal_isolated("leviathan_dev", env={}, argv=[])
        assert "production Glue database" in str(exc.value)

    def test_refuses_non_rehearsal_name(self, rr):
        with pytest.raises(rr.RehearsalGuardError) as exc:
            rr.assert_rehearsal_isolated("leviathan_scratch", env={}, argv=[])
        assert "rehearsal pattern" in str(exc.value)

    def test_refuses_prod_write_bucket(self, rr):
        with pytest.raises(rr.RehearsalGuardError) as exc:
            rr.assert_rehearsal_isolated(
                "leviathan_rehearsal", write_bucket="leviathan-dev-shahem-001", env={}, argv=[])
        assert "production bucket" in str(exc.value)

    def test_refuses_canonical_publish_mode(self, rr):
        with pytest.raises(rr.RehearsalGuardError) as exc:
            rr.assert_rehearsal_isolated(
                "leviathan_rehearsal", env={}, argv=["--publish-mode", "canonical"])
        assert "canonical" in str(exc.value)

    def test_refuses_empty_database(self, rr):
        with pytest.raises(rr.RehearsalGuardError):
            rr.assert_rehearsal_isolated("", env={}, argv=[])

    def test_accepts_isolated_rehearsal(self, rr):
        # default rehearsal db, dry-run mode -> no raise.
        rr.assert_rehearsal_isolated("leviathan_rehearsal", env={}, argv=[])
        rr.assert_rehearsal_isolated("my_rehearsal_db", env={}, argv=["--publish-mode", "dry-run"])


# ---------------------------------------------------------------------------
# Byte-for-byte round-trip verification (synthetic + real snapshot).
# ---------------------------------------------------------------------------
def _synthetic_table():
    return {
        "Name": "silver_demo",
        "DatabaseName": "leviathan_dev",
        "CreateTime": "2026-06-18 03:00:10+03:00",
        "VersionId": "3",
        "TableType": "EXTERNAL_TABLE",
        "StorageDescriptor": {
            "Columns": [{"Name": "a", "Type": "string"}, {"Name": "b", "Type": "bigint"}],
            "Location": "s3://leviathan-dev-shahem-001/silver/demo",
            "InputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
            "OutputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
            "SerdeInfo": {"SerializationLibrary": "lib", "Parameters": {"serialization.format": "1"}},
            "Parameters": {},
        },
        "PartitionKeys": [{"Name": "dt", "Type": "string"}],
        "Parameters": {"EXTERNAL": "TRUE", "transient_lastDdlTime": "1781740810"},
    }


class TestRoundTrip:
    def test_build_table_input_strips_readonly_keys(self, rr):
        tinput = rr.build_table_input(_synthetic_table())
        for k in ("DatabaseName", "CreateTime", "VersionId"):
            assert k not in tinput
        assert tinput["Name"] == "silver_demo"

    def test_simulated_readback_verifies_byte_for_byte(self, rr):
        snap = _synthetic_table()
        tinput = rr.build_table_input(snap)
        readback = rr.simulate_readback_table(tinput, "leviathan_rehearsal")
        v = rr.verify_restore(snap, readback, [], [])
        assert v.table_match is True
        assert not v.table_diffs
        assert v.ok is True

    def test_corrupted_readback_is_caught(self, rr):
        import copy
        snap = _synthetic_table()
        tinput = rr.build_table_input(snap)
        readback = copy.deepcopy(rr.simulate_readback_table(tinput, "leviathan_rehearsal"))
        # drop a column -> managed subset diverges (deepcopy so we don't also mutate the snapshot).
        readback["StorageDescriptor"]["Columns"] = readback["StorageDescriptor"]["Columns"][:1]
        v = rr.verify_restore(snap, readback, [], [])
        assert v.table_match is False
        assert v.table_diffs
        assert v.ok is False

    def test_dry_run_real_registered_table_byte_for_byte(self, rr):
        # silver_esr: 370 registered partitions with explicit as_of= locations.
        raw = rr.raw_dir_for(rr.DEFAULT_BASELINE)
        plan = rr.rehearse_dry_run("silver_esr", raw, "leviathan_rehearsal", argv=[], env={})
        v = plan["verify"]
        assert v["byte_for_byte_ok"] is True
        assert v["table_match"] is True
        assert v["partitions_total"] == v["partitions_matched"] == 370
        assert plan["definition"]["partition_keys"] == ["commodity_code", "market_year", "as_of_date"]
        # the explicit per-partition locations survived into the plan.
        assert plan["sample_partition_locations"]
        assert "as_of=" in plan["sample_partition_locations"][0]["location"]

    def test_dry_run_flat_table(self, rr):
        raw = rr.raw_dir_for(rr.DEFAULT_BASELINE)
        plan = rr.rehearse_dry_run("silver_cot", raw, "leviathan_rehearsal", argv=[], env={})
        assert plan["verify"]["byte_for_byte_ok"] is True
        assert plan["definition"]["partition_keys"] == []
        assert plan["verify"]["partitions_total"] == 0

    def test_partition_mismatch_reported(self, rr):
        # snapshot has one partition; readback drops it -> mismatch.
        part = {"Values": ["2020"], "StorageDescriptor": {"Location": "s3://b/x", "Columns": []}}
        v = rr.verify_restore(_synthetic_table(),
                              rr.simulate_readback_table(rr.build_table_input(_synthetic_table()),
                                                         "leviathan_rehearsal"),
                              [part], [])
        assert v.partitions_total == 1
        assert v.partitions_matched == 0
        assert v.partition_mismatches[0]["problem"] == "missing in readback"


class TestDryRunPlan:
    def test_dry_run_issues_no_aws_and_refuses_prod(self, rr):
        raw = rr.raw_dir_for(rr.DEFAULT_BASELINE)
        with pytest.raises(rr.RehearsalGuardError):
            rr.rehearse_dry_run("silver_cot", raw, "leviathan_dev", argv=[], env={})

    def test_partition_chunking_is_100(self, rr):
        raw = rr.raw_dir_for(rr.DEFAULT_BASELINE)
        plan = rr.rehearse_dry_run("silver_esr", raw, "leviathan_rehearsal", argv=[], env={})
        batch_calls = [c for c in plan["planned_aws_calls"] if c["call"] == "glue.batch_create_partition"]
        assert len(batch_calls) == 4  # 370 / 100 -> 4 chunks
        assert [c["partition_inputs"] for c in batch_calls] == [100, 100, 100, 70]

    def test_cleanup_and_gate_command_present(self, rr):
        raw = rr.raw_dir_for(rr.DEFAULT_BASELINE)
        plan = rr.rehearse_dry_run("silver_cot", raw, "leviathan_rehearsal", argv=[], env={})
        assert plan["cleanup"]["call"] == "glue.delete_table"
        assert "create-database" in plan["gate_command_create_database"]
        assert "leviathan_rehearsal" in plan["gate_command_create_database"]

    def test_missing_snapshot_raises(self, rr, tmp_path):
        with pytest.raises(FileNotFoundError):
            rr.rehearse_dry_run("silver_cot", tmp_path, "leviathan_rehearsal", argv=[], env={})
