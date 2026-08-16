"""PRICE_AND_PLAYBOOKS W2 -- the silver_futures_eod producer TASK. Hermetic: a fake S3, no AWS.

This file exists because the task is where the three most expensive W2 defects lived, and none of
them was reachable from the transform tests:

  * the nightly INCREMENTAL publish overwriting the whole current-year partition with five days of
    rows (``build_partition_objects`` emits one object per (slug, year) at a FIXED key and never
    merges), i.e. silent automated destruction of canonical history;
  * the SYMBOLOGY injection taking the step-1 ``parent -> instrument_id`` resolve, which maps every
    instrument to the literal ``'ZC.FUT'`` so the outright filter drops 100% of the purchased bars;
  * the fetch job and the silver task deriving the incremental raw FILENAME separately, so the
    chain could never read the payload it had just bought.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest
from leviathan.silver import futures_eod_contracts as FC
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import raw_databento_key
from leviathan.transforms.bronze_to_silver import databento_eod as S
from leviathan.transforms.raw_to_bronze import databento_eod as T

_REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "futures_eod_task", _REPO / "jobs" / "batch" / "futures_eod_task.py")
T2 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(T2)

SCALE = T.FIXED_PRICE_SCALE


class FakeS3:
    """get_object / list_objects_v2 over an in-memory ``{key: bytes}`` map."""

    def __init__(self, objects: dict | None = None):
        self.objects = dict(objects or {})
        self.gets: list[str] = []

    def get_object(self, *, Bucket, Key):  # noqa: N803 -- boto3 kwarg casing
        self.gets.append(Key)
        if Key not in self.objects:
            raise KeyError(Key)

        class _Body:
            def __init__(self, data):
                self._data = data

            def read(self):
                return self._data

        return {"Body": _Body(self.objects[Key])}

    def list_objects_v2(self, *, Bucket, Prefix, **kw):  # noqa: N803
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}


def _bronze(dates: list[str], *, sym: str = "ZCZ6", slug: str = "corn_cbot") -> pd.DataFrame:
    """A minimal GLBX bronze frame the silver projection accepts."""
    return pd.DataFrame({
        "trade_date": pd.to_datetime(dates),
        "leviathan_slug": slug,
        "raw_symbol": sym,
        "contract_month": "2026-12",
        "instrument_id": 42,
        "publisher_id": 1,
        "open": 3.5, "high": 3.6, "low": 3.4, "close": 3.55,
        "volume": 100,
        "settle": 3.54,
        "open_interest": pd.array([1000] * len(dates), dtype="Int64"),
        "settle_flags": pd.array([pd.NA] * len(dates), dtype="Int64"),
        "dataset": T.GLBX,
        "root": "ZC",
    })


def _contract() -> dict:
    return load_registry().table("silver_futures_eod")


def _canonical_body(df: pd.DataFrame, contract: dict) -> tuple[str, bytes]:
    """The ONE canonical object a (slug, year) partition of ``df`` publishes to."""
    from leviathan.silver.partitioned_producer import build_partition_objects

    objs = build_partition_objects(df, contract, partition_cols=T2._PARTITION_COLS)
    assert len(objs) == 1
    return objs[0].canonical_key, objs[0].body


# ---------------------------------------------------------------------------
class TestPayloadKeyAgreement:
    """The writer and the reader must derive ONE name. They run back to back in one Step Function."""

    def test_backfill_key_is_the_function_the_fetch_job_writes_with(self):
        from leviathan.storage.paths import databento_payload_filename

        spec = importlib.util.spec_from_file_location(
            "fetch_databento_eod", _REPO / "jobs" / "ingest" / "fetch_databento_eod.py")
        fetch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fetch)
        # Same object, not merely the same string today.
        assert fetch.payload_filename is databento_payload_filename

        want = raw_databento_key("glbx_mdp3", "ZC", 2016,
                                 fetch.payload_filename("ohlcv-1d", "ZC", 2016))
        got = T2.resolve_payload_key(FakeS3(), "b", dataset=T.GLBX, root="ZC", year=2016,
                                     schema="ohlcv-1d", mode="backfill")
        assert got == want

    def test_incremental_reads_the_as_of_payload_the_fetch_job_wrote(self):
        """The regression: the reader used a hard-coded {schema}_{root}_{year} name while the
        writer stamped the file with its own as-of date, so the chain read a stale object or none."""
        stale = raw_databento_key("glbx_mdp3", "ZC", 2026, "ohlcv-1d_ZC_2026.dbn.zst")
        fresh = raw_databento_key("glbx_mdp3", "ZC", 2026, "ohlcv-1d_ZC_20260728.dbn.zst")
        older = raw_databento_key("glbx_mdp3", "ZC", 2026, "ohlcv-1d_ZC_20260721.dbn.zst")
        s3 = FakeS3({stale: b"x", older: b"x", fresh: b"x"})
        got = T2.resolve_payload_key(s3, "b", dataset=T.GLBX, root="ZC", year=2026,
                                     schema="ohlcv-1d", mode="incremental")
        assert got == fresh

    def test_incremental_falls_back_to_the_backfill_object(self):
        stale = raw_databento_key("glbx_mdp3", "ZC", 2026, "ohlcv-1d_ZC_2026.dbn.zst")
        got = T2.resolve_payload_key(FakeS3({stale: b"x"}), "b", dataset=T.GLBX, root="ZC",
                                     year=2026, schema="ohlcv-1d", mode="incremental")
        assert got == stale

    def test_the_statistics_leg_uses_the_same_resolution(self):
        fresh = raw_databento_key("glbx_mdp3", "ZC", 2026, "statistics_ZC_20260728.dbn.zst")
        got = T2.resolve_payload_key(FakeS3({fresh: b"x"}), "b", dataset=T.GLBX, root="ZC",
                                     year=2026, schema="statistics", mode="incremental")
        assert got == fresh


# ---------------------------------------------------------------------------
class TestUniquenessAssertion:
    """F2's precondition, enforced on the AUTOMATED path -- gate 1 lives in a script no chain runs."""

    def test_clean_frame_passes(self):
        T2.assert_no_duplicates(S.build_databento_eod_silver(_bronze(["2026-07-20", "2026-07-21"])))

    def test_the_f2_double_bar_is_a_hard_fail(self):
        df = S.build_databento_eod_silver(_bronze(["2026-07-20", "2026-07-20"]))
        with pytest.raises(ValueError, match="double bar survived|duplicate"):
            T2.assert_no_duplicates(df)

    def test_empty_frame_is_not_an_error(self):
        T2.assert_no_duplicates(pd.DataFrame())


# ---------------------------------------------------------------------------
class TestIncrementalMerge:
    """THE CRITICAL ONE. An incremental run owns five days and stages the WHOLE trade_year object."""

    def test_merge_keeps_the_history_the_incremental_window_does_not_own(self):
        contract = _contract()
        prior = S.build_databento_eod_silver(
            _bronze([f"2026-0{m}-1{d}" for m in (1, 2, 3) for d in range(1, 6)]))
        key, body = _canonical_body(prior, contract)
        s3 = FakeS3({key: body})

        new = S.build_databento_eod_silver(_bronze(["2026-07-27", "2026-07-28"]))
        merged, rec = T2.merge_with_canonical(new, contract, s3)

        assert rec["partitions_merged"] == 1
        assert rec["prior_rows"] == len(prior)
        assert len(merged) == len(prior) + len(new)
        assert set(prior["trade_date"]) <= set(merged["trade_date"])
        assert list(merged.columns) == S.SILVER_COLUMNS

    def test_without_the_merge_the_partition_would_collapse(self):
        """The defect, stated as a measurement: the staged object IS the whole partition."""
        contract = _contract()
        prior = S.build_databento_eod_silver(_bronze(["2026-01-05", "2026-02-05", "2026-03-05"]))
        key, body = _canonical_body(prior, contract)
        new = S.build_databento_eod_silver(_bronze(["2026-07-27", "2026-07-28"]))
        unmerged_key, _ = _canonical_body(new, contract)
        # SAME key, fewer rows -> the put replaces three months of history with two days.
        assert unmerged_key == key
        merged, _ = T2.merge_with_canonical(new, contract, FakeS3({key: body}))
        assert len(merged) == 5

    def test_new_rows_win_a_natural_key_collision(self):
        """A corrected settlement must be able to land on a date already published."""
        contract = _contract()
        prior = S.build_databento_eod_silver(_bronze(["2026-07-27"]))
        key, body = _canonical_body(prior, contract)
        revised = _bronze(["2026-07-27"])
        revised["settle"] = 9.99
        merged, _ = T2.merge_with_canonical(S.build_databento_eod_silver(revised), contract,
                                            FakeS3({key: body}))
        assert len(merged) == 1
        assert merged["settle"].iloc[0] == pytest.approx(9.99)

    def test_an_absent_canonical_partition_is_a_pass_through(self):
        contract = _contract()
        new = S.build_databento_eod_silver(_bronze(["2026-07-27"]))
        merged, rec = T2.merge_with_canonical(new, contract, FakeS3())
        assert rec["partitions_merged"] == 0 and len(merged) == 1

    def test_the_merge_result_still_passes_the_row_validator(self):
        from leviathan.silver.flat_producer import authorize_for_contract
        from leviathan.silver.partitioned_producer import build_partitioned_publish

        contract = _contract()
        prior = S.build_databento_eod_silver(_bronze(["2026-01-05", "2026-02-05"]))
        key, body = _canonical_body(prior, contract)
        new = S.build_databento_eod_silver(_bronze(["2026-07-27"]))
        merged, _ = T2.merge_with_canonical(new, contract, FakeS3({key: body}))
        T2.assert_no_duplicates(merged)
        plan = build_partitioned_publish(
            df=merged, contract=contract,
            auth=authorize_for_contract(contract, publish_mode="dry-run", env={}),
            job="futures_eod_databento", partition_cols=T2._PARTITION_COLS,
            s3_client=None, row_validator=FC.lint_frame)
        assert plan.row_count == 3 and plan.partition_count == 1

    def test_merge_refuses_to_run_blind(self):
        with pytest.raises(ValueError, match="live S3 client"):
            T2.merge_with_canonical(S.build_databento_eod_silver(_bronze(["2026-07-27"])),
                                    _contract(), None)

    def test_a_canonical_object_of_the_wrong_shape_is_refused(self):
        """Merging against an object whose columns are not the contract's would silently drop a
        column on the way back out, so it fails closed instead."""
        import io

        import pyarrow as pa
        import pyarrow.parquet as pq

        contract = _contract()
        prior = S.build_databento_eod_silver(_bronze(["2026-01-05"]))
        key, body = _canonical_body(prior, contract)
        short = pq.read_table(io.BytesIO(body)).to_pandas().drop(columns=["volume"])
        buf = io.BytesIO()
        pq.write_table(pa.Table.from_pandas(short, preserve_index=False), buf)
        with pytest.raises(ValueError, match="does not carry the contract shape"):
            T2.merge_with_canonical(S.build_databento_eod_silver(_bronze(["2026-07-27"])),
                                    contract, FakeS3({key: buf.getvalue()}))


# ---------------------------------------------------------------------------
class TestLoadUnitBronze:
    """End to end over a batch-shaped DBN + a REAL symbology artifact. The step-1 regression."""

    @staticmethod
    def _artifact(window=("2026-01-01", "2027-01-01")) -> dict:
        """Exactly what jobs/ingest/fetch_databento_eod.py lands, both resolve steps included."""
        d0, d1 = window
        return {
            "dataset": T.GLBX, "root": "ZC", "year": 2026, "leviathan_slug": "corn_cbot",
            "window": {"start": d0, "end_exclusive": d1},
            "outright_symbols": ["ZCZ6"], "dropped_symbols": ["ZCH6-ZCK6"], "dropped_count": 1,
            # STEP 1 -- parent -> instrument_id. Injecting THIS is the defect: every instrument_id
            # would map to the literal 'ZC.FUT' and the outright filter would drop every bar.
            "resolve_step1": {"result": {"ZC.FUT": [{"d0": d0, "d1": d1, "s": "42"}]},
                              "stype_in": "parent", "stype_out": "instrument_id"},
            # STEP 2 -- instrument_id -> raw_symbol, chunked. This is the usable mapping.
            "resolve_step2": [{"result": {"42": [{"d0": d0, "d1": d1, "s": "ZCZ6"}]},
                               "stype_in": "instrument_id", "stype_out": "raw_symbol"}],
        }

    @staticmethod
    def _dbn_bytes():
        dbn = pytest.importorskip("databento_dbn")
        meta = dbn.Metadata(dataset="GLBX.MDP3", start=0, stype_in=dbn.SType.RAW_SYMBOL,
                            stype_out=dbn.SType.INSTRUMENT_ID, schema=dbn.Schema.OHLCV_1D,
                            symbols=["ZCZ6"], partial=[], not_found=[], mappings=[])
        rows = []
        for day in ("2026-07-20", "2026-07-21", "2026-07-22"):
            rows.append(bytes(dbn.OHLCVMsg(
                rtype=dbn.RType.OHLCV_1D, publisher_id=1, instrument_id=42,
                ts_event=int(pd.Timestamp(day, tz="UTC").value),
                open=3552500000, high=3600000000, low=3500000000, close=3575000000,
                volume=1234)))
        return bytes(meta.encode()) + b"".join(rows)

    def test_bronze_rows_are_non_zero(self):
        pytest.importorskip("databento")
        payload = self._dbn_bytes()
        art = self._artifact()
        s3 = FakeS3({
            raw_databento_key("glbx_mdp3", "ZC", 2026, "symbology_ZC_2026.json"):
                json.dumps(art).encode("utf-8"),
            raw_databento_key("glbx_mdp3", "ZC", 2026, "ohlcv-1d_ZC_2026.dbn.zst"): payload,
        })
        bronze, stats = T2.load_unit_bronze(s3, "b", dataset=T.GLBX, root="ZC", year=2026)
        assert len(bronze) == 3, "the step-1 injection made this ZERO"
        assert set(bronze["raw_symbol"]) == {"ZCZ6"}
        assert set(bronze["contract_month"]) == {"2026-12"}
        assert stats["dropped_symbols_recorded"] == 1
        # No statistics object in the fixture -> settle stays NULL (F3), never the close.
        assert bronze["settle"].isna().all()

    def test_the_step1_shape_is_refused_outright(self):
        pytest.importorskip("databento")
        art = self._artifact()
        with pytest.raises(ValueError, match="stype_out"):
            T.decode_dbn(self._dbn_bytes(), schema="ohlcv-1d",
                         symbology_json={**art["resolve_step1"],
                                         "symbols": ["ZC.FUT"], "start_date": "2026-01-01",
                                         "end_date": "2027-01-01", "partial": [], "not_found": [],
                                         "message": "OK", "status": 0})

    def test_a_missing_payload_names_the_key(self):
        s3 = FakeS3()
        with pytest.raises(FileNotFoundError, match="ohlcv-1d"):
            T2.load_unit_bronze(s3, "b", dataset=T.GLBX, root="ZC", year=2026)


# ---------------------------------------------------------------------------
class TestChainWiring:
    def test_the_descriptor_promotes_behind_the_gate_and_never_from_silver(self):
        """ARMED 2026-07-29. The F2 condition this test used to hold the line on is DISCHARGED:
        the uniqueness assertion passed on PURCHASED data (15/15 roots, 187 partitions) and P3
        resolved ICE_BAR_RULE to prefer_on_venue_publisher against measured double bars.

        The invariant that outlives the flip: the SILVER phase stages shadow, and canonical is
        reached only through the PROMOTE phase, which runs after the gate. Autonomous populates
        promote; it must never turn a silver task canonical."""
        desc = json.loads((_REPO / "configs" / "silver" / "dags"
                           / "futures_eod_databento.json").read_text(encoding="utf-8"))
        assert desc["promote_mode"] == "autonomous"
        rendered = json.loads((_REPO / "configs" / "silver" / "dags" / "_rendered"
                               / "futures_eod_databento.input.json").read_text(encoding="utf-8"))
        silver = rendered["phases"]["silver"]["tasks"][0]["command"]
        assert "--publish-mode" in silver and silver[silver.index("--publish-mode") + 1] == "shadow"
        promote = rendered["promote"]["tasks"]
        assert len(promote) == 1
        pcmd = promote[0]["command"]
        assert pcmd[pcmd.index("--publish-mode") + 1] == "canonical"

    def test_the_task_merges_before_an_incremental_publish(self):
        src = (_REPO / "jobs" / "batch" / "futures_eod_task.py").read_text(encoding="utf-8")
        assert "merge_with_canonical" in src and "assert_no_duplicates" in src


# ---------------------------------------------------------------------------
class TestJanuaryStraddle:
    """D-PR-45 / D-SG G1-7, dated: must land before 2027-01-01.

    A Databento unit is one (root, CALENDAR YEAR) payload and --since defaults to today-5d, so
    from Jan 1 to Jan 5 the incremental window spans two years. Both years are selected, and each
    unit is judged against the window CLIPPED TO ITS OWN YEAR -- the select_units fix alone would
    have doubled the failure, charging both straddle units as truncated against the full window."""

    class _Args:
        def __init__(self, since, mode="incremental", roots=None, years=None):
            self.since, self.mode, self.roots, self.years = since, mode, roots, years
            self.ice_bar_rule = "prefer_on_venue_publisher"

    def _labels(self, monkeypatch, today, since, roots=("ZC",)):
        import datetime as _dt

        class _FixedDT(_dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return _dt.datetime(today[0], today[1], today[2], tzinfo=tz)

        monkeypatch.setattr(T2, "datetime", _FixedDT)
        # s3_client None: there is nothing to list here, so every candidate year is shown.
        units = T2.select_units(self._Args(since, roots=list(roots)), None, "b",
                                T2.source_spec("databento"))
        return sorted(label for label, *_rest in units)

    def test_a_straddling_window_selects_both_years(self, monkeypatch):
        labels = self._labels(monkeypatch, (2027, 1, 4), "2026-12-30")
        assert any(l.endswith("/2026") for l in labels), labels
        assert any(l.endswith("/2027") for l in labels), labels

    def test_a_normal_window_still_selects_exactly_one_year(self, monkeypatch):
        labels = self._labels(monkeypatch, (2026, 8, 16), "2026-08-11")
        assert len(labels) == 1 and labels[0].endswith("/2026"), labels

    def test_the_unit_carries_its_dataset_for_the_lag_lookup(self, monkeypatch):
        import datetime as _dt

        class _FixedDT(_dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return _dt.datetime(2026, 8, 16, tzinfo=tz)

        monkeypatch.setattr(T2, "datetime", _FixedDT)
        units = T2.select_units(self._Args("2026-08-11", roots=["ZC", "KC"]), None, "b",
                                T2.source_spec("databento"))
        assert {dataset for _l, _ldr, dataset in units} == {T.GLBX, T.IFUS}

    def test_a_straddle_year_with_no_landed_payload_is_skipped(self, monkeypatch):
        """The fetch leg keys the whole window under year(--since), so on Jan 2-5 the new year's
        raw prefix is empty -- selecting it anyway would raise FileNotFoundError in the loader."""
        import datetime as _dt

        class _FixedDT(_dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return _dt.datetime(2027, 1, 4, tzinfo=tz)

        monkeypatch.setattr(T2, "datetime", _FixedDT)
        labels = sorted(label for label, *_r in T2.select_units(
            self._Args("2026-12-30", roots=["ZC"]), FakeS3({}), "b",
            T2.source_spec("databento")))
        assert labels == ["GLBX.MDP3 ZC/2026"], labels

    def test_each_straddle_unit_is_judged_against_its_own_year(self, monkeypatch):
        """Without the clip in _truncation_error, BOTH straddle units read as truncated."""
        import datetime as _dt

        class _FixedDT(_dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return _dt.datetime(2027, 1, 6, tzinfo=tz)

        monkeypatch.setattr(T2, "datetime", _FixedDT)
        spec = T2.source_spec("databento")
        dec = pd.DataFrame({"trade_date": pd.to_datetime(["2026-12-30", "2026-12-31"])})
        jan = pd.DataFrame({"trade_date": pd.to_datetime(["2027-01-04", "2027-01-05"])})
        assert T2._truncation_error(dec, spec, mode="incremental", since="2026-12-30") is None
        assert T2._truncation_error(jan, spec, mode="incremental", since="2026-12-30") is None
