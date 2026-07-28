"""SILVER-F013 partitioned-producer runtime (PRICE_AND_PLAYBOOKS W1.0 / D5).

The registered-partition sibling of test_flat_producer. Pure Python + the in-memory Glue/S3 fakes --
no AWS, no network. Covers the four invariants the helper exists to enforce (partition columns live
in the PATH not the body; partition_values order == the contract's declared partition_keys order;
directory key == COLUMN name, no ESR-style remap; every partition value typed and non-null, so
neither `leviathan_slug=nan` nor `trade_year=2026.0` can ever be registered), the INV-2 encode, the
conditional-invariant row_validator hook, and -- the plan's post-ship check, done OFFLINE because
this lane may not touch AWS -- a ZERO-ROW registered partition round-tripping through F013
write-verify-register.
"""
from __future__ import annotations

import io

import pandas as pd
import pyarrow.parquet as pq
import pytest
from leviathan.silver.partitioned_producer import (
    DEFAULT_OBJECT_NAME,
    build_partition_objects,
    build_partitioned_publish,
    partition_object_key,
    partition_value_str,
)
from leviathan.silver.publisher import ManifestState, PublishStrategy
from leviathan.silver.registry import load_registry

from tests.unit.silver.conftest import (
    TEST_BUCKET,
    TEST_DB,
    canonical_authorization,
    dryrun_authorization,
    shadow_authorization,
)

TABLE = "silver_futures_eod"
TEST_PREFIX = "silver/futures_eod"
TEST_ROOT = f"s3://{TEST_BUCKET}/{TEST_PREFIX}"


@pytest.fixture(scope="module")
def contract():
    """The REAL F010 contract (so the schema under test is the shipped one), repointed at the
    allowlisted TEST bucket/database -- the fakes must never carry the production names."""
    import copy
    c = copy.deepcopy(load_registry().table(TABLE))
    c["s3_bucket"], c["s3_root"], c["s3_prefix"] = TEST_BUCKET, TEST_ROOT, TEST_PREFIX
    c["glue_database"] = TEST_DB
    return c


def _rows(n: int = 2, slug: str = "corn_cbot", year: int = 2026) -> pd.DataFrame:
    """A DataFrame in the contract's shape PLUS the two partition columns."""
    return pd.DataFrame({
        "trade_date": pd.to_datetime([f"2026-07-{20 + i:02d}" for i in range(n)]),
        "contract_month": ["2026-12"] * n,
        "instrument_kind": ["futures"] * n,
        "raw_symbol": ["ZCZ6"] * n,
        "settle": [417.25 + i for i in range(n)],
        "settle_kind": ["settlement"] * n,
        "open": [None] * n, "high": [None] * n, "low": [None] * n, "close": [None] * n,
        "volume": pd.array([None] * n, dtype="Int64"),
        "open_interest": pd.array([None] * n, dtype="Int64"),
        "unit": ["US cents/bushel"] * n,
        "currency": ["USD"] * n,
        "expiry_date": pd.to_datetime(["2026-12-14"] * n),
        "source": ["databento_glbx_mdp3"] * n,
        "dataset": ["GLBX.MDP3"] * n,
        "leviathan_slug": [slug] * n,
        "trade_year": [year] * n,
    })


class TestObjectKey:
    def test_hive_layout_uses_the_column_names_verbatim(self):
        key = partition_object_key(TEST_PREFIX, ["leviathan_slug", "trade_year"], ["corn_cbot", 2026])
        assert key == f"{TEST_PREFIX}/leviathan_slug=corn_cbot/trade_year=2026/{DEFAULT_OBJECT_NAME}"
        # NOT the ESR special case: that table alone maps column as_of_date -> directory as_of=.
        assert "as_of=" not in key

    def test_unencodable_partition_value_fails_closed(self):
        for bad in ("", "a/b", "a=b"):
            with pytest.raises(ValueError):
                partition_object_key(TEST_PREFIX, ["leviathan_slug"], [bad])

    def test_null_partition_value_fails_closed(self):
        # str(nan) is the perfectly encodable string 'nan', so an unguarded render REGISTERS the
        # partition leviathan_slug=nan and orphans the rows behind a slug predicate forever.
        for bad in (None, float("nan")):
            with pytest.raises(ValueError, match="NULL"):
                partition_object_key(TEST_PREFIX, ["leviathan_slug"], [bad])

    def test_int_typed_partition_value_renders_without_a_decimal_point(self):
        # pandas widens ANY column that has ever held a NaN to float64, so trade_year arrives 2026.0.
        assert partition_value_str("trade_year", 2026.0, "int") == "2026"
        assert partition_value_str("trade_year", 2026, "int") == "2026"
        assert partition_value_str("trade_year", "2026", "int") == "2026"

    def test_non_integral_value_for_an_int_key_is_refused_never_truncated(self):
        with pytest.raises(ValueError, match="not an exact integer"):
            partition_value_str("trade_year", 2026.5, "int")
        with pytest.raises(ValueError, match="not numeric"):
            partition_value_str("trade_year", "Q3", "int")

    def test_a_string_key_keeps_its_value_verbatim(self):
        assert partition_value_str("leviathan_slug", "corn_cbot", "string") == "corn_cbot"

    def test_length_mismatch_fails_closed(self):
        with pytest.raises(ValueError):
            partition_object_key(TEST_PREFIX, ["leviathan_slug", "trade_year"], ["corn_cbot"])


class TestBuildObjects:
    def test_one_object_per_partition_with_ordered_values(self, contract):
        df = pd.concat([_rows(2, "corn_cbot", 2026), _rows(1, "cocoa", 2025)], ignore_index=True)
        objs = build_partition_objects(df, contract)
        assert [o.partition_values for o in objs] == [["cocoa", "2025"], ["corn_cbot", "2026"]]
        assert [o.row_count for o in objs] == [1, 2]
        assert objs[1].canonical_key.endswith(
            "leviathan_slug=corn_cbot/trade_year=2026/part-000.parquet")
        # the Glue partition LOCATION the publisher derives from the key
        assert objs[1].location_prefix().endswith("leviathan_slug=corn_cbot/trade_year=2026/")

    def test_partition_columns_are_dropped_from_the_parquet_body(self, contract):
        objs = build_partition_objects(_rows(2), contract)
        t = pq.read_table(io.BytesIO(objs[0].body))
        assert "leviathan_slug" not in t.schema.names
        assert "trade_year" not in t.schema.names
        # ...and the body is EXACTLY the contract's declared column order (INV-2 writer order).
        assert t.schema.names == [c["name"] for c in contract["physical_columns"]]

    def test_inv2_types_survive_the_encode(self, contract):
        import pyarrow as pa
        t = pq.read_table(io.BytesIO(build_partition_objects(_rows(2), contract)[0].body))
        assert t.schema.field("trade_date").type == pa.timestamp("us")
        assert t.schema.field("settle").type == pa.float64()
        assert t.schema.field("volume").type == pa.int64()
        # an all-null OHLC column stays double, never arrow null (the s3-lane null-type hazard)
        assert t.schema.field("open").type == pa.float64()

    def test_null_metrics_are_computed_for_the_value_column_only(self, contract):
        obj = build_partition_objects(_rows(2), contract)[0]
        assert obj.null_metrics == {"settle": 1.0}

    def test_wrong_partition_order_fails_closed(self, contract):
        # transposing registered partition values is silent at write time and unrecoverable after.
        with pytest.raises(ValueError, match="order is load-bearing"):
            build_partition_objects(_rows(2), contract,
                                    partition_cols=["trade_year", "leviathan_slug"])

    def test_missing_partition_column_fails_closed(self, contract):
        with pytest.raises(ValueError, match="missing partition column"):
            build_partition_objects(_rows(2).drop(columns=["trade_year"]), contract)

    def test_flat_contract_is_refused(self):
        flat = load_registry().table("silver_cot")
        with pytest.raises(ValueError, match="flat_producer"):
            build_partition_objects(pd.DataFrame(), flat)

    def test_a_nan_slug_never_becomes_the_partition_nan(self, contract):
        # REGRESSION: dropna=False keeps the null group (better than pandas silently DROPPING those
        # rows), but the render must then REJECT it -- str(nan)=='nan' encodes fine as a path segment,
        # so the unguarded version wrote leviathan_slug=nan straight into write-verify-REGISTER.
        df = _rows(2)
        df.loc[0, "leviathan_slug"] = None
        with pytest.raises(ValueError, match="NULL"):
            build_partition_objects(df, contract)

    def test_a_float_dtype_trade_year_renders_as_an_int_partition(self, contract):
        # REGRESSION: any trade_year column that has ever held a NaN is float64 in pandas, and
        # str(2026.0)=='2026.0' -- a value Athena reads back as NULL against the `int` Glue key.
        df = _rows(2)
        df["trade_year"] = df["trade_year"].astype("float64")
        objs = build_partition_objects(df, contract)
        assert objs[0].partition_values == ["corn_cbot", "2026"]
        assert objs[0].canonical_key.endswith("trade_year=2026/part-000.parquet")
        assert "2026.0" not in objs[0].canonical_key


class TestPlan:
    def test_dry_run_needs_no_clients_and_stops_before_canonical(self, contract):
        plan = build_partitioned_publish(df=_rows(2), contract=contract,
                                         auth=dryrun_authorization(), job="futures_eod_test")
        assert plan.publisher.strategy is PublishStrategy.REGISTERED
        assert plan.partition_count == 1 and plan.row_count == 2
        m = plan.run()
        assert m.state is ManifestState.VALIDATED       # halted before promote/catalog
        assert m.partition_actions == []

    def test_shadow_without_a_client_fails_closed_at_plan_time(self, contract):
        with pytest.raises(ValueError, match="requires a live s3_client"):
            build_partitioned_publish(df=_rows(2), contract=contract,
                                      auth=shadow_authorization(), job="futures_eod_test")

    def test_projected_or_flat_contract_is_refused(self):
        # silver_fgis is partition_mode=projected. (This was silver_nasa_power until the
        # SILVER-F047 registry catch-up of 2026-07-28 deprojected THAT table to
        # partition_mode=registered, at which point the fixture silently stopped exercising the
        # guard. A table's partition_mode is registry state: re-pick the fixture when it moves,
        # and assert the precondition so the next move fails loudly instead of quietly.)
        proj = load_registry().table("silver_fgis")
        assert proj.get("partition_mode") != "registered"
        with pytest.raises(ValueError, match="registered"):
            build_partitioned_publish(df=pd.DataFrame(), contract=proj,
                                      auth=dryrun_authorization(), job="x")

    def test_row_validator_runs_before_a_single_byte_is_staged(self, contract):
        # The conditional-invariant hook: rules the F010 contract cannot express (it only carries
        # UNCONDITIONAL required_nonnull) are enforced HERE, at plan-build time.
        seen = {}

        def _validator(df):
            seen["rows"] = len(df)
            return ["contract_month is NULL on a futures row"]

        with pytest.raises(ValueError, match="conditional-invariant violation"):
            build_partitioned_publish(df=_rows(2), contract=contract, auth=dryrun_authorization(),
                                      job="futures_eod_test", row_validator=_validator)
        assert seen["rows"] == 2

    def test_futures_eod_lint_frame_wired_as_the_row_validator_fails_closed(self, contract):
        # The real validator on the real table: a futures row whose delivery month was dropped is
        # natural-key-colliding (N rows -> ONE key) and duplicate_check cannot see it (NULL != NULL).
        from leviathan.silver import futures_eod_contracts as FC
        df = _rows(2)
        df["contract_month"] = None
        with pytest.raises(ValueError, match="conditional-invariant violation"):
            build_partitioned_publish(df=df, contract=contract, auth=dryrun_authorization(),
                                      job="futures_eod_test", row_validator=FC.lint_frame)
        # ...and the clean frame passes straight through.
        plan = build_partitioned_publish(df=_rows(2), contract=contract, auth=dryrun_authorization(),
                                         job="futures_eod_test", row_validator=FC.lint_frame)
        assert plan.row_count == 2

    def test_value_floor_rejects_an_all_null_settle(self, contract):
        df = _rows(2)
        df["settle"] = None
        plan = build_partitioned_publish(df=df, contract=contract, auth=dryrun_authorization(),
                                         job="futures_eod_test")
        from leviathan.silver.publisher import PublisherError
        with pytest.raises(PublisherError, match="non-null floor"):
            plan.run()


def _register_table(fake_glue):
    fake_glue.tables[TABLE] = {
        "Name": TABLE,
        "StorageDescriptor": {
            "Columns": [{"Name": "trade_date", "Type": "timestamp"}],
            "Location": TEST_ROOT,
            "InputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
            "OutputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
            "SerdeInfo": {"SerializationLibrary": "serde", "Parameters": {"serialization.format": "1"}},
            "Parameters": {},
        },
    }


def _zero_row_object(contract, slug: str, year: int):
    """A StagedObject for a partition whose group is EMPTY -- a real shape (a session with no prints
    for that contract) that the grouping path can never produce, so it is built explicitly here."""
    from leviathan.silver.flat_producer import encode_parquet
    from leviathan.silver.publisher import StagedObject
    body_df = _rows(1).iloc[0:0].drop(columns=["leviathan_slug", "trade_year"])
    return StagedObject(
        canonical_key=partition_object_key(TEST_PREFIX, ["leviathan_slug", "trade_year"],
                                           [slug, year]),
        body=encode_parquet(body_df, contract),
        partition_values=[slug, str(year)],
        row_count=0,
    )


class TestRegisteredRoundTrip:
    """The plan's post-ship check, run OFFLINE against the fakes (this lane may not touch AWS)."""

    def test_canonical_publish_registers_the_partition_at_its_explicit_location(
            self, contract, fake_glue, fake_s3):
        _register_table(fake_glue)
        plan = build_partitioned_publish(
            df=_rows(2), contract=contract, auth=canonical_authorization(),
            job="futures_eod_test", s3_client=fake_s3, glue_client=fake_glue, run_id="r1")
        m = plan.run()
        assert m.state is ManifestState.CERTIFIED
        key = (TABLE, ("corn_cbot", "2026"))
        assert key in fake_glue.partitions
        loc = fake_glue.partitions[key]["StorageDescriptor"]["Location"]
        assert loc == f"{TEST_ROOT}/leviathan_slug=corn_cbot/trade_year=2026/"
        assert m.partition_actions[0]["outcome"] == "created"
        # the canonical object was promoted from the shadow copy, never written over first
        assert any(k.endswith("leviathan_slug=corn_cbot/trade_year=2026/part-000.parquet")
                   for _, k in fake_s3.store)

    def test_an_empty_frame_publishes_nothing(self, contract):
        # no groups -> no objects -> no partition ever registered. A zero-row RUN is a no-op, which
        # is different from a zero-row PARTITION (below).
        assert build_partition_objects(_rows(0), contract) == []

    def test_zero_row_partition_round_trips_when_the_floor_is_lowered(
            self, contract, fake_glue, fake_s3):
        # The plan's post-ship check: "a zero-row registered partition round-trips through F013
        # write-verify-register." It only passes with min_rows=0 -- the house default
        # ValidationHooks(min_rows=1) rejects an empty object at STAGED->VALIDATED, so a smoke run
        # left on the default fails BY DESIGN rather than by defect. Both directions are proven
        # (see the sibling test), which is why the helper documents the knob.
        _register_table(fake_glue)
        plan = build_partitioned_publish(
            df=_rows(1), contract=contract, auth=canonical_authorization(),
            job="futures_eod_zero", s3_client=fake_s3, glue_client=fake_glue, run_id="r0",
            min_rows=0)
        m = plan.publisher.run([_zero_row_object(contract, "corn_cbot", 2026)])
        assert m.state is ManifestState.CERTIFIED
        assert (TABLE, ("corn_cbot", "2026")) in fake_glue.partitions
        assert m.partition_actions[0]["outcome"] == "created"

    def test_zero_row_partition_is_rejected_under_the_default_floor(
            self, contract, fake_glue, fake_s3):
        _register_table(fake_glue)
        from leviathan.silver.publisher import PublisherError
        plan = build_partitioned_publish(
            df=_rows(1), contract=contract, auth=canonical_authorization(),
            job="futures_eod_zero_default", s3_client=fake_s3, glue_client=fake_glue, run_id="rz")
        with pytest.raises(PublisherError, match="min_rows"):
            plan.publisher.run([_zero_row_object(contract, "cocoa", 2025)])
        assert (TABLE, ("cocoa", "2025")) not in fake_glue.partitions

    def test_idempotent_republish_is_a_no_op(self, contract, fake_glue, fake_s3):
        _register_table(fake_glue)
        for run in ("r1", "r2"):
            m = build_partitioned_publish(
                df=_rows(2), contract=contract, auth=canonical_authorization(),
                job="futures_eod_test", s3_client=fake_s3, glue_client=fake_glue, run_id=run).run()
        assert m.partition_actions[0]["outcome"] == "existing"   # exact managed match, no repair
