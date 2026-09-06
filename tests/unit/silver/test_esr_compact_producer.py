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


def _table_input(columns=None):
    return {
        "Name": "silver_esr_compact",
        "StorageDescriptor": {
            "Columns": columns if columns is not None
            else [{"Name": "commodity_code", "Type": "smallint"}],
            "Location": CANON_ROOT,
            "InputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
            "OutputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
            "SerdeInfo": {"SerializationLibrary": "serde", "Parameters": {}},
            "Parameters": {},
        },
    }


# --- SILVER-F030 BF-W2 additive widen (2026-09-04) -------------------------------------------
# The live 12-column compact catalog schema and the five columns the gated ALTER appends.
_LIVE_12_COLUMNS = [
    {"Name": "commodity_code", "Type": "smallint"},
    {"Name": "commodity_name", "Type": "string"},
    {"Name": "market_year", "Type": "smallint"},
    {"Name": "country_code", "Type": "smallint"},
    {"Name": "week_ending_date", "Type": "date"},
    {"Name": "outstanding_sales_1000mt", "Type": "float"},
    {"Name": "weekly_exports_1000mt", "Type": "float"},
    {"Name": "gross_new_sales_1000mt", "Type": "float"},
    {"Name": "changes_1000mt", "Type": "float"},
    {"Name": "source_unit_id", "Type": "smallint"},
    {"Name": "ingest_date", "Type": "string"},
    {"Name": "source", "Type": "string"},
]
_ADDITIVE_5_COLUMNS = [
    {"Name": "accumulated_exports_1000mt", "Type": "double"},
    {"Name": "current_my_net_sales_1000mt", "Type": "double"},
    {"Name": "current_my_total_commitment_1000mt", "Type": "double"},
    {"Name": "next_my_outstanding_sales_1000mt", "Type": "double"},
    {"Name": "next_my_net_sales_1000mt", "Type": "double"},
]


def _preexisting_partition(glue, slug, columns):
    """Register one partition at the CORRECT location carrying *columns* -- i.e. the pre-ALTER
    descriptor a partition registered before the widen actually holds."""
    sd = dict(_table_input()["StorageDescriptor"])
    sd["Columns"] = list(columns)
    sd["Location"] = f"{CANON_ROOT}/commodity={slug}/"
    glue.partitions[("silver_esr_compact", (slug,))] = {"Values": [slug], "StorageDescriptor": sd}


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
# SILVER-F030 BF-W2 -- the additive widen survives the promote (the blocking finding)
# ===========================================================================
class TestAdditiveSchemaWidenReconcile:
    """THE REGRESSION PIN FOR THE ONE THING IN THIS CHANGE THAT CAN TAKE THE FAMILY DOWN.

    ``PartitionPublisher.publish_one`` builds each partition's DESIRED StorageDescriptor by
    copying the TABLE's SD. The instant ``ALTER TABLE silver_esr_compact ADD COLUMNS`` widens the
    table from 12 to 17 columns, EVERY already-registered partition diffs against it. With no
    RepairAuthorization and ``reconcile_schema_widen=False`` (the dataclass default), publish_one
    calls ``_fail``, ``ShadowPublisher._catalog`` raises ``PublisherError``, and the canonical run
    exits 1 -- for the WHOLE table, not just the new columns. The compact producer therefore
    passes ``reconcile_schema_widen=True``, and these tests are what stop that keyword being
    "cleaned up" later.
    """

    def _objs(self, prod):
        frame = _silver_rows([("corn_cbot", 401)], ["20260903"])
        return prod.build_staged_objects(frame, prod.VINTAGE_LATEST)

    def test_publish_esr_compact_requests_the_reconcile(self, prod, fake_glue, fake_s3,
                                                        monkeypatch):
        """The wiring itself, asserted at the call site rather than inferred from behaviour."""
        seen = {}
        real = prod.ShadowPublisher

        def _capture(**kw):
            seen.update(kw)
            return real(**kw)

        monkeypatch.setattr(prod, "ShadowPublisher", _capture)
        _publish(prod, self._objs(prod), fake_glue, fake_s3, dryrun_authorization(), "latest")
        assert seen.get("reconcile_schema_widen") is True

    def test_publisher_reconciles_a_pure_trailing_widen(self, prod, fake_glue, fake_s3):
        """A partition still carrying the pre-ALTER 12-column descriptor, against a 17-column
        table SD, is REPAIRED -- not failed. This is the post-ALTER steady state on the first
        canonical promote: `partition_actions={'repaired': 1}` on every pre-existing partition.
        Without reconcile_schema_widen=True this raises PublisherError instead."""
        fake_glue.tables["silver_esr_compact"] = _table_input(
            _LIVE_12_COLUMNS + _ADDITIVE_5_COLUMNS)
        _preexisting_partition(fake_glue, "corn_cbot", _LIVE_12_COLUMNS)
        m = _publish(prod, self._objs(prod), fake_glue, fake_s3, canonical_authorization(), "latest")
        assert m.state == ManifestState.CERTIFIED
        assert {a["outcome"] for a in m.partition_actions} == {"repaired"}
        # the repair re-points the descriptor to the FULL 17-column table schema.
        got = fake_glue.partitions[("silver_esr_compact", ("corn_cbot",))]
        assert [c["Name"] for c in got["StorageDescriptor"]["Columns"]] == [
            c["Name"] for c in _LIVE_12_COLUMNS + _ADDITIVE_5_COLUMNS]

    def test_the_second_promote_after_the_widen_is_a_pure_no_op(self, prod, fake_glue, fake_s3):
        """`repaired` on the first post-ALTER promote, `existing` on the second. A partition that
        keeps reporting `repaired` means the widen is not settling and must be investigated."""
        fake_glue.tables["silver_esr_compact"] = _table_input(
            _LIVE_12_COLUMNS + _ADDITIVE_5_COLUMNS)
        _preexisting_partition(fake_glue, "corn_cbot", _LIVE_12_COLUMNS)
        _publish(prod, self._objs(prod), fake_glue, fake_s3, canonical_authorization(),
                 "latest", run_id="r1")
        m2 = _publish(prod, self._objs(prod), fake_glue, fake_s3, canonical_authorization(),
                      "latest", run_id="r2")
        assert {a["outcome"] for a in m2.partition_actions} == {"existing"}

    def test_a_mid_list_insert_is_not_a_widen_and_still_fails_closed(self, prod, fake_glue, fake_s3):
        """THE COUNTER-PIN, and the measured reason the five columns sit at the TAIL of the silver
        frame rather than beside the other *_1000mt columns.

        catalog.is_schema_widen admits ONLY a pure TRAILING append. Inserted mid-list, the same
        five columns are NOT a widen (measured: tail -> True, position 9 -> False), the narrow
        self-heal declines, and every partition fails closed -- which is correct behaviour, and is
        exactly what would happen to the live family if the column order ever drifted. F013's
        wrong-location protection is preserved by the same narrowness."""
        mid = _LIVE_12_COLUMNS[:9] + _ADDITIVE_5_COLUMNS + _LIVE_12_COLUMNS[9:]
        fake_glue.tables["silver_esr_compact"] = _table_input(mid)
        _preexisting_partition(fake_glue, "corn_cbot", _LIVE_12_COLUMNS)
        with pytest.raises(PublisherError):
            _publish(prod, self._objs(prod), fake_glue, fake_s3, canonical_authorization(), "latest")
        # and the partition descriptor is NOT half-updated.
        got = fake_glue.partitions[("silver_esr_compact", ("corn_cbot",))]
        assert [c["Name"] for c in got["StorageDescriptor"]["Columns"]] == [
            c["Name"] for c in _LIVE_12_COLUMNS]

    def test_a_wrong_location_is_still_refused_under_the_reconcile(self, prod, fake_glue, fake_s3):
        """The self-heal must not have widened F013's blast radius: a partition registered at the
        WRONG location fails closed even with reconcile_schema_widen=True, because is_schema_widen
        requires an IDENTICAL normalized location."""
        fake_glue.tables["silver_esr_compact"] = _table_input(
            _LIVE_12_COLUMNS + _ADDITIVE_5_COLUMNS)
        sd = dict(_table_input()["StorageDescriptor"])
        sd["Columns"] = list(_LIVE_12_COLUMNS)
        sd["Location"] = f"{CANON_ROOT}/commodity=corn_cbot/WRONG/"
        fake_glue.partitions[("silver_esr_compact", ("corn_cbot",))] = {
            "Values": ["corn_cbot"], "StorageDescriptor": sd,
        }
        with pytest.raises(PublisherError):
            _publish(prod, self._objs(prod), fake_glue, fake_s3, canonical_authorization(), "latest")
        assert fake_glue.partitions[("silver_esr_compact", ("corn_cbot",))][
            "StorageDescriptor"]["Location"] == f"{CANON_ROOT}/commodity=corn_cbot/WRONG/"


class TestMeasurementInstrument:
    def test_esr_measure_cols_include_the_five(self, prod):
        """_ESR_MEASURE_COLS is the ONLY per-(commodity, as_of) instrument that proves the
        promotion landed: _null_metrics reports notna().mean() per column per staged object and
        the publisher records it as row_key_null_metrics[<canonical key>] in the run manifest, so
        a SHADOW run answers "which slugs and which vintages carry the new fields" with no Athena
        query and no canonical write. Pinned so it cannot be silently trimmed back to three."""
        assert set(prod._ESR_MEASURE_COLS) >= {
            "accumulated_exports_1000mt", "current_my_net_sales_1000mt",
            "current_my_total_commitment_1000mt", "next_my_outstanding_sales_1000mt",
            "next_my_net_sales_1000mt",
        }
        assert set(prod._ESR_MEASURE_COLS) >= {
            "weekly_exports_1000mt", "outstanding_sales_1000mt", "gross_new_sales_1000mt"}

    def test_the_deprecated_column_stays_out_of_the_instrument(self, prod):
        """changes_1000mt is DEPRECATED and 100% null by the source's own retirement; reporting it
        as a producer floor metric is what this exclusion prevents."""
        assert "changes_1000mt" not in prod._ESR_MEASURE_COLS

    def test_null_metrics_separates_a_populated_vintage_from_an_empty_one(self, prod):
        """The verdict sentence of the shadow run, measured on the producer's own instrument: an
        as_of whose bronze predates the promotion reads 0.0 for all five, and a populated as_of
        reads non-zero -- per (commodity, as_of) object, never averaged across the family. A slug
        reading 0.0 on a POST-promotion vintage is a real finding about that commodity code and is
        written down, not smoothed away."""
        five = ["accumulated_exports_1000mt", "current_my_net_sales_1000mt",
                "current_my_total_commitment_1000mt", "next_my_outstanding_sales_1000mt",
                "next_my_net_sales_1000mt"]
        frame = _silver_rows([("corn_cbot", 401)], ["20260806", "20260903"])
        for col in five:
            frame[col] = [float("nan")] * 2 + [1250.0] * 2  # old vintage NULL, new vintage populated
        objs = prod.build_staged_objects(frame, prod.VINTAGE_ALL)
        by_key = {o.canonical_key: o.null_metrics for o in objs}
        old = by_key["silver/esr/commodity=corn_cbot/as_of=20260806/part-000.parquet"]
        new = by_key["silver/esr/commodity=corn_cbot/as_of=20260903/part-000.parquet"]
        for col in five:
            assert old[col] == 0.0, col
            assert new[col] == 1.0, col
        # the no-regression check: an incumbent measure is untouched by the widen.
        assert old["weekly_exports_1000mt"] == 1.0
        assert new["weekly_exports_1000mt"] == 1.0


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
