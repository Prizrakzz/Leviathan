"""SILVER-F031 (option-b per-week vintage path) + SILVER-F032 (registered-partition publication
fail-safe) for the ESR compact producer (jobs/batch/bronze_to_silver_esr_task.py).

F031: --vintage-mode latest (default, one file per commodity slug) vs all (per-(slug, as_of)
      registered-partition layout that NEVER collapses to max(as_of)); canonical/compact parity.
F032: the compact write routes through the F015 shadow publisher + F013 registered-partition
      publisher -- dry-run plans (catalog untouched), canonical create is idempotent, a wrong
      pre-registered location is never silently accepted (no false success), and the bronze->silver
      ordering guard fires before any write.

In-memory fakes (shared conftest); AWS-free under the F002 isolation guard.
"""
from __future__ import annotations

import datetime
import importlib.util
import io
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from leviathan.silver.publisher import ManifestState, PublisherError
from tests.unit.silver.conftest import (
    canonical_authorization,
    dryrun_authorization,
    shadow_authorization,
)

_REPO = Path(__file__).resolve().parents[3]
_PRODUCER = _REPO / "jobs" / "batch" / "bronze_to_silver_esr_task.py"
BUCKET = "leviathan-test"
CANON_ROOT = f"s3://{BUCKET}/silver/esr"


@pytest.fixture(scope="module")
def prod():
    spec = importlib.util.spec_from_file_location("b2s_esr_task", _PRODUCER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Helpers: a silver frame mimicking transform_esr_bronze_to_silver output.
# ---------------------------------------------------------------------------
def _silver_rows(slug_code_pairs, as_ofs, market_year=2024):
    """Build a silver-shaped frame across commodities x as_of vintages x 2 countries/weeks."""
    rows = []
    for as_of in as_ofs:
        for name, code in slug_code_pairs:
            for country, week in ((351, datetime.date(2024, 9, 12)), (1220, datetime.date(2024, 9, 19))):
                rows.append({
                    "commodity_code": code, "commodity_name": name, "market_year": market_year,
                    "country_code": country, "week_ending_date": week,
                    "outstanding_sales_1000mt": 50.0, "weekly_exports_1000mt": 25.0,
                    "gross_new_sales_1000mt": 30.0, "changes_1000mt": float("nan"),
                    "source_unit_id": 1, "as_of_date": as_of, "ingest_date": "2026-05-24",
                    "source": "usda_esr",
                })
    return pd.DataFrame(rows)


def _table_input():
    return {
        "Name": "silver_esr_compact",
        "StorageDescriptor": {
            "Columns": [{"Name": "commodity_code", "Type": "smallint"}],
            "Location": CANON_ROOT,
            "InputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
            "OutputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
            "SerdeInfo": {"SerializationLibrary": "serde", "Parameters": {}},
            "Parameters": {},
        },
    }


def _publish(prod, objects, glue, s3, auth, vintage_mode, shadow_prefix=None, run_id="t"):
    return prod.publish_esr_compact(
        objects, bucket=BUCKET, s3_client=s3, glue_client=glue, auth=auth,
        vintage_mode=vintage_mode, shadow_prefix=shadow_prefix, run_id=run_id,
    )


# ===========================================================================
# SILVER-F031 -- vintage-mode key selection + staging
# ===========================================================================
class TestVintageModeKeySelection:
    KEYS = [
        "bronze/production/source=usda_esr/commodity_code=401/market_year=2024/as_of=20260524/part-000.parquet",
        "bronze/production/source=usda_esr/commodity_code=401/market_year=2024/as_of=20260712/part-000.parquet",
        "bronze/production/source=usda_esr/commodity_code=801/market_year=2024/as_of=20260524/part-000.parquet",
    ]

    def test_latest_keeps_only_max_as_of_per_code_year(self, prod):
        sel = prod._select_keys(self.KEYS, prod.VINTAGE_LATEST)
        # 401/2024 collapses to the 20260712 snapshot; 801/2024 keeps its single snapshot.
        assert len(sel) == 2
        assert all("as_of=20260524" not in k for k in sel if "commodity_code=401" in k)
        assert any("commodity_code=401/market_year=2024/as_of=20260712" in k for k in sel)

    def test_all_retains_every_vintage(self, prod):
        sel = prod._select_keys(self.KEYS, prod.VINTAGE_ALL)
        assert len(sel) == 3  # nothing collapsed


class TestBuildStagedObjects:
    def test_latest_one_object_per_slug_partition_is_commodity(self, prod):
        frame = _silver_rows([("corn_cbot", 401), ("soybeans_cbot", 801)], ["20260712"])
        objs = prod.build_staged_objects(frame, prod.VINTAGE_LATEST)
        assert len(objs) == 2
        for o in objs:
            assert o.partition_values is not None and len(o.partition_values) == 1
            assert o.canonical_key.endswith("/part-000.parquet")
            assert "/as_of=" not in o.canonical_key
            assert o.row_count == 2

    def test_all_one_object_per_slug_and_as_of_never_collapsed(self, prod):
        frame = _silver_rows([("corn_cbot", 401)], ["20260524", "20260712"])
        objs = prod.build_staged_objects(frame, prod.VINTAGE_ALL)
        # two as_of vintages -> TWO objects (per-week), not one collapsed max(as_of).
        assert len(objs) == 2
        keys = sorted(o.canonical_key for o in objs)
        assert keys == [
            "silver/esr/commodity=corn_cbot/as_of=20260524/part-000.parquet",
            "silver/esr/commodity=corn_cbot/as_of=20260712/part-000.parquet",
        ]
        for o in objs:
            assert len(o.partition_values) == 2  # [slug, as_of] -- the registered as_of dimension
            assert o.partition_values[0] == "corn_cbot"

    def test_all_mode_requires_as_of_column(self, prod):
        frame = _silver_rows([("corn_cbot", 401)], ["20260712"]).drop(columns=["as_of_date"])
        with pytest.raises(ValueError, match="as_of_date"):
            prod.build_staged_objects(frame, prod.VINTAGE_ALL)

    def test_parity_all_objects_partition_the_full_frame_with_no_loss(self, prod):
        """Canonical<->compact parity at the producer level: the union of rows across the option-b
        objects equals the full transformed frame, and each object holds exactly its (slug, as_of)
        slice -- no row dropped, duplicated, or misfiled (the canonical silver_esr holds the same
        rows keyed by the same tuple)."""
        frame = _silver_rows([("corn_cbot", 401), ("soybeans_cbot", 801)], ["20260524", "20260712"])
        objs = prod.build_staged_objects(frame, prod.VINTAGE_ALL)
        assert len(objs) == 4  # 2 commodities x 2 vintages
        total = 0
        for o in objs:
            df = pq.read_table(io.BytesIO(o.body)).to_pandas()
            total += len(df)
            assert set(df["as_of_date"].unique()) == {o.partition_values[1]}
            assert set(df["commodity_name"].unique()) == {o.partition_values[0]}
        assert total == len(frame)  # no row lost or duplicated across the partitioning


# ===========================================================================
# SILVER-F032 -- registered-partition publication fail-safe
# ===========================================================================
class TestPublishFailSafe:
    def _objs(self, prod, vintage_mode="latest", as_ofs=("20260712",)):
        frame = _silver_rows([("corn_cbot", 401), ("soybeans_cbot", 801)], list(as_ofs))
        return prod.build_staged_objects(frame, vintage_mode)

    def test_dry_run_plans_and_touches_no_catalog(self, prod, fake_glue, fake_s3):
        objs = self._objs(prod)
        m = _publish(prod, objs, fake_glue, fake_s3, dryrun_authorization(), "latest")
        # halts before canonical: no partitions registered, no DATA object written (only the
        # control-plane run manifest under _manifests/ is persisted, as the publisher always does).
        assert m.state == ManifestState.VALIDATED
        assert fake_glue.partitions == {}
        data_keys = [k for k in fake_s3.keys() if "/_manifests/" not in k]
        assert data_keys == []

    def test_shadow_writes_shadow_only_never_canonical(self, prod, fake_glue, fake_s3):
        objs = self._objs(prod)
        m = _publish(prod, objs, fake_glue, fake_s3, shadow_authorization(), "latest",
                     shadow_prefix="silver/_shadow/esr")
        assert m.state == ManifestState.VALIDATED
        assert fake_glue.partitions == {}          # catalog untouched
        data_keys = [k for k in fake_s3.keys() if "/_manifests/" not in k]
        assert data_keys                            # objects DID land...
        assert all(k.startswith("silver/_shadow/esr/") for k in data_keys)  # ...in shadow only
        # and NO canonical data object exists at the live compact location.
        assert not any(k.startswith("silver/esr/commodity=") for k in data_keys)

    def test_canonical_registers_commodity_partitions(self, prod, fake_glue, fake_s3):
        fake_glue.tables["silver_esr_compact"] = _table_input()
        objs = self._objs(prod)
        m = _publish(prod, objs, fake_glue, fake_s3, canonical_authorization(), "latest")
        assert m.state == ManifestState.CERTIFIED
        assert ("silver_esr_compact", ("corn_cbot",)) in fake_glue.partitions
        assert ("silver_esr_compact", ("soybeans_cbot",)) in fake_glue.partitions

    def test_option_b_registers_as_of_partition_dimension(self, prod, fake_glue, fake_s3):
        fake_glue.tables["silver_esr_compact"] = _table_input()
        objs = self._objs(prod, vintage_mode="all", as_ofs=("20260524", "20260712"))
        m = _publish(prod, objs, fake_glue, fake_s3, canonical_authorization(), "all")
        assert m.state == ManifestState.CERTIFIED
        # [commodity, as_of] two-value partitions -- the registered per-week dimension.
        assert ("silver_esr_compact", ("corn_cbot", "20260712")) in fake_glue.partitions
        assert ("silver_esr_compact", ("corn_cbot", "20260524")) in fake_glue.partitions

    def test_idempotent_rerun_is_a_no_op(self, prod, fake_glue, fake_s3):
        fake_glue.tables["silver_esr_compact"] = _table_input()
        objs = self._objs(prod)
        _publish(prod, objs, fake_glue, fake_s3, canonical_authorization(), "latest", run_id="r1")
        before = dict(fake_glue.partitions)
        objs2 = self._objs(prod)
        m2 = _publish(prod, objs2, fake_glue, fake_s3, canonical_authorization(), "latest", run_id="r2")
        assert m2.state == ManifestState.CERTIFIED
        # exact same partition set -- no duplicate, no wrong location introduced.
        assert set(fake_glue.partitions) == set(before)
        # the re-publish recorded every partition as an idempotent EXISTING match.
        outcomes = {a["outcome"] for a in m2.partition_actions}
        assert outcomes == {"existing"}

    def test_wrong_preregistered_location_is_never_silently_accepted(self, prod, fake_glue, fake_s3):
        """The F013 hazard: a partition already registered at the WRONG location must FAIL (no false
        success), and the wrong location is NOT overwritten in place."""
        fake_glue.tables["silver_esr_compact"] = _table_input()
        wrong_loc = f"{CANON_ROOT}/commodity=corn_cbot/WRONG/"
        sd = dict(_table_input()["StorageDescriptor"]); sd["Location"] = wrong_loc
        fake_glue.partitions[("silver_esr_compact", ("corn_cbot",))] = {
            "Values": ["corn_cbot"], "StorageDescriptor": sd,
        }
        objs = self._objs(prod)
        with pytest.raises(PublisherError):
            _publish(prod, objs, fake_glue, fake_s3, canonical_authorization(), "latest")
        # the wrong location survives untouched (never overwritten before validation).
        assert fake_glue.partitions[("silver_esr_compact", ("corn_cbot",))][
            "StorageDescriptor"]["Location"] == wrong_loc

    def test_registration_failure_yields_no_false_success(self, prod, fake_glue, fake_s3):
        """A create_partition failure fails the run (manifest FAILED / raises) -- never a spurious
        success marker."""
        fake_glue.tables["silver_esr_compact"] = _table_input()

        def _boom(**kw):
            raise RuntimeError("glue create_partition throttled")
        fake_glue.create_partition = _boom  # type: ignore[assignment]
        objs = self._objs(prod)
        with pytest.raises(PublisherError):
            _publish(prod, objs, fake_glue, fake_s3, canonical_authorization(), "latest")
        assert fake_glue.partitions == {}  # nothing falsely registered


# ===========================================================================
# SILVER-F032 -- bronze->silver ordering guard
# ===========================================================================
class TestBronzeOrderingGuard:
    def test_empty_bronze_refuses_to_write_silver(self, prod):
        with pytest.raises(prod.BronzeNotReadyError, match="no bronze"):
            prod.assert_bronze_ready([], [])

    def test_bronze_present_but_unparseable_selection_refuses(self, prod):
        with pytest.raises(prod.BronzeNotReadyError, match="empty silver"):
            prod.assert_bronze_ready(["bronze/production/source=usda_esr/garbage.parquet"], [])

    def test_ready_bronze_passes(self, prod):
        keys = ["bronze/production/source=usda_esr/commodity_code=401/market_year=2024/as_of=20260712/part-000.parquet"]
        prod.assert_bronze_ready(keys, keys)  # no raise


# ===========================================================================
# SILVER-F032 -- read-only reconcile of the existing 10 compact partitions
# ===========================================================================
class TestPartitionReconcileReadOnly:
    def test_existing_10_compact_partitions_reconcile_without_mutation(self, prod, fake_glue, fake_s3):
        """Publishing the current commodity set against a catalog that already holds those exact
        partitions is a pure EXISTING reconcile -- the 10 partitions are unchanged (no mutation)."""
        fake_glue.tables["silver_esr_compact"] = _table_input()
        slugs = ["corn_cbot", "soybeans_cbot"]
        for slug in slugs:
            sd = dict(_table_input()["StorageDescriptor"])
            sd["Location"] = f"{CANON_ROOT}/commodity={slug}/"
            fake_glue.partitions[("silver_esr_compact", (slug,))] = {
                "Values": [slug], "StorageDescriptor": sd,
            }
        before = {k: dict(v) for k, v in fake_glue.partitions.items()}
        frame = _silver_rows([("corn_cbot", 401), ("soybeans_cbot", 801)], ["20260712"])
        objs = prod.build_staged_objects(frame, prod.VINTAGE_LATEST)
        m = _publish(prod, objs, fake_glue, fake_s3, canonical_authorization(), "latest")
        assert m.state == ManifestState.CERTIFIED
        assert {a["outcome"] for a in m.partition_actions} == {"existing"}
        assert fake_glue.partitions == before  # byte-for-byte unchanged


# ===========================================================================
# SILVER-F031 -- the option-b path decision record artifact
# ===========================================================================
class TestOptionBArtifact:
    def test_option_b_path_record_exists_and_is_gated(self):
        import json
        path = _REPO / "reports" / "silver_readiness" / "R2_esr" / "F031_option_b_path.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["package"] == "SILVER-F031"
        assert "BF-W2" in doc["execution_gate"]
        # all three option-b legs are built (a: promotion, b: de-collapse, c: as_of dimension).
        ob = doc["option_b_change"]
        assert ob["a_raw_to_bronze_weekly_promotion"]["built"] is True
        assert ob["b_remove_the_latest_snapshot_collapse"]["built"] is True
        assert ob["c_as_of_registered_partition_dimension"]["built"] is True
        assert ob["b_remove_the_latest_snapshot_collapse"]["default"].startswith("latest")
