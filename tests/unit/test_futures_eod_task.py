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


# ---------------------------------------------------------------------------
# V2-4 (2026-09-02) -- the SETTLEMENT-TAPE unit on the silver side: the statistics stream is the
# row skeleton, the ohlcv payload is ABSENT by design, the straddle probe looks for statistics,
# the nightly unit is NON-BLOCKING, and a backfill assembly must be month-continuous.
# ---------------------------------------------------------------------------
class TestSettlementTapeUnit:
    @staticmethod
    def _artifact() -> dict:
        d0, d1 = "2017-01-01", "2018-01-01"
        return {
            "dataset": T.GLBX, "root": "CPO", "year": 2017,
            "leviathan_slug": "malaysian_crude_palm_oil_cme",
            "window": {"start": d0, "end_exclusive": d1},
            "outright_symbols": ["CPOZ6", "CPOF7"], "dropped_symbols": ["CPOZ6-CPOF7"],
            "dropped_count": 1,
            "resolve_step1": {"result": {"CPO.FUT": [{"d0": d0, "d1": d1, "s": "42"},
                                                     {"d0": d0, "d1": d1, "s": "43"}]},
                              "stype_in": "parent", "stype_out": "instrument_id"},
            # CPOZ6 (Dec 2016) is listed only until its first-business-day-of-January termination
            "resolve_step2": [{"result": {"42": [{"d0": d0, "d1": "2017-01-04", "s": "CPOZ6"}],
                                          "43": [{"d0": d0, "d1": d1, "s": "CPOF7"}]},
                               "stype_in": "instrument_id", "stype_out": "raw_symbol"}],
        }

    @staticmethod
    def _stats_dbn(*, in_band: bool = False) -> bytes:
        dbn = pytest.importorskip("databento_dbn")
        mappings = []
        if in_band:
            # a batch DBN carries its own SymbolMappingMsg set; decode_dbn PREFERS it and the
            # artifact is only the fallback -- so an artifact with no STEP-2 chunks still decodes
            from datetime import date
            from types import SimpleNamespace as _NS
            mappings = [
                _NS(raw_symbol="CPOZ6", intervals=[_NS(start_date=date(2017, 1, 1),
                                                       end_date=date(2017, 1, 4), symbol="42")]),
                _NS(raw_symbol="CPOF7", intervals=[_NS(start_date=date(2017, 1, 1),
                                                       end_date=date(2018, 1, 1), symbol="43")]),
            ]
        meta = dbn.Metadata(dataset="GLBX.MDP3", start=0, stype_in=dbn.SType.RAW_SYMBOL,
                            stype_out=dbn.SType.INSTRUMENT_ID, schema=dbn.Schema.STATISTICS,
                            symbols=["CPOZ6", "CPOF7"], partial=[], not_found=[],
                            mappings=mappings)
        rows = []

        def _msg(iid, day, stat_type, price=None, qty=None):
            ts = int(pd.Timestamp(f"{day}T20:00:00Z").value)
            ref = int(pd.Timestamp(f"{day}T00:00:00Z").value)
            return bytes(dbn.StatMsg(
                publisher_id=1, instrument_id=iid, ts_event=ts, ts_recv=ts, ts_ref=ref,
                price=T.UNDEF_PRICE if price is None else int(round(price * SCALE)),
                quantity=T.UNDEF_STAT_QUANTITY if qty is None else qty,
                sequence=0, ts_in_delta=0, stat_type=stat_type, channel_id=65535,
                update_action=dbn.StatUpdateAction.NEW, stat_flags=0))

        rows.append(_msg(42, "2017-01-03", dbn.StatType.SETTLEMENT_PRICE, price=790.25))
        rows.append(_msg(42, "2017-01-03", dbn.StatType.OPEN_INTEREST, qty=120))
        rows.append(_msg(43, "2017-01-03", dbn.StatType.SETTLEMENT_PRICE, price=795.0))
        rows.append(_msg(43, "2017-01-04", dbn.StatType.SETTLEMENT_PRICE, price=796.5))
        rows.append(_msg(43, "2017-01-04", dbn.StatType.OPEN_INTEREST, qty=130))
        return bytes(meta.encode()) + b"".join(rows)

    def _s3(self, *, with_stats: bool = True, artifact: dict | None = None,
            in_band: bool = False) -> FakeS3:
        art = self._artifact() if artifact is None else artifact
        objs = {raw_databento_key("glbx_mdp3", "CPO", 2017, "symbology_CPO_2017.json"):
                json.dumps(art).encode("utf-8")}
        if with_stats:
            objs[raw_databento_key("glbx_mdp3", "CPO", 2017,
                                   "statistics_CPO_2017.dbn.zst")] = self._stats_dbn(in_band=in_band)
        return FakeS3(objs)

    def test_the_loader_builds_the_settlement_spine_with_no_ohlcv_object(self):
        pytest.importorskip("databento")
        s3 = self._s3()
        bronze, stats = T2.load_unit_bronze(s3, "b", dataset=T.GLBX, root="CPO", year=2017)
        assert stats["settlement_base"] is True
        assert len(bronze) == 3 == stats["rows_out"]
        assert bronze["settle"].notna().all()
        for col in ("open", "high", "low", "close"):
            assert bronze[col].isna().all(), col
        assert bronze["volume"].isna().all()
        by = bronze.set_index("raw_symbol")["contract_month"].to_dict()
        assert by["CPOZ6"] == "2016-12", "the December straddler decodes on its listing interval"
        assert by["CPOF7"] == "2017-01"
        assert bronze.set_index(["raw_symbol", "trade_date"]).loc[
            ("CPOZ6", pd.Timestamp("2017-01-03")), "open_interest"] == 120
        assert stats["dropped_symbols_recorded"] == 1
        assert stats["glbx_settle_coverage"]["settle_nonnull_frac"] == 1.0
        assert stats["glbx_settle_coverage"]["oi_keys_without_settle"] == 0
        assert stats["rows_beyond_horizon"] == 0 and stats["horizon_months"] == 60
        assert stats["anchor_fallbacks"] == 0, "every outright carried its resolved d0"
        assert not any("ohlcv-1d" in k for k in s3.gets), "no ohlcv-1d object is ever asked for"
        # ... and the silver projection tolerates the NULL bar columns
        silver = S.build_databento_eod_silver(bronze)
        assert FC.lint_frame(silver) == []
        assert set(silver["unit"]) == {"USD/metric ton"} and set(silver["currency"]) == {"USD"}
        assert set(silver["source"]) == {"databento_glbx_mdp3"}
        assert silver["close"].isna().all() and silver["settle"].notna().all()

    def test_the_unit_record_carries_the_window_fence_counters(self):
        """D3 defect 2: the loader's unit record must NAME how many statistics records belonged
        to another unit, and which sessions they were -- a silent drop of a vendor record is what
        let two units claim 2016-12-30 in the first place. Zero is recorded, never omitted."""
        pytest.importorskip("databento")
        _b, stats = T2.load_unit_bronze(self._s3(), "b", dataset=T.GLBX, root="CPO", year=2017)
        assert stats["stat_rows_outside_unit_window"] == 0
        assert stats["stat_dates_outside_unit_window"] == []
        assert stats["unit_trade_date_window"] == ["2017-01-01", "2018-01-01"]

    def test_a_settlement_tape_unit_without_its_statistics_object_is_a_missing_unit(self):
        with pytest.raises(FileNotFoundError, match="statistics"):
            T2.load_unit_bronze(self._s3(with_stats=False), "b", dataset=T.GLBX, root="CPO",
                                year=2017)

    def test_an_artifact_without_step2_decodes_on_the_window_anchor_and_counts_the_fallbacks(
            self, caplog):
        """STEP-12 F10: a symbology artifact re-landed by an older fetch carries no
        ``resolve_step2`` (so no ``d0`` per symbol). The DBN's own in-band mappings still decode
        the symbols and every outright falls back to the WINDOW anchor -- bounded by the 74-month
        decode window, backstopped by the row lint -- but that degraded anchor is NAMED AND
        COUNTED in the unit record, never silent."""
        import logging

        pytest.importorskip("databento")
        caplog.set_level(logging.INFO)
        art = {k: v for k, v in self._artifact().items() if k != "resolve_step2"}
        assert T.symbol_anchors_from_artifact(art) == {}
        bronze, stats = T2.load_unit_bronze(self._s3(artifact=art, in_band=True), "b",
                                            dataset=T.GLBX, root="CPO", year=2017)
        assert len(bronze) == 3
        assert stats["anchor_fallbacks"] == 2
        assert "databento settlement CPO/2017: 2 of 2 outright(s) carry no resolved d0 anchor" \
            in caplog.text
        by = bronze.set_index("raw_symbol")["contract_month"].to_dict()
        assert by["CPOZ6"] == "2016-12" and by["CPOF7"] == "2017-01", \
            "the window anchor still resolves this shape (the grace month admits December)"
        # ... and the fully-anchored artifact counts ZERO
        _b, full = T2.load_unit_bronze(self._s3(), "b", dataset=T.GLBX, root="CPO", year=2017)
        assert full["anchor_fallbacks"] == 0

    def test_the_straddle_probe_looks_for_statistics_on_a_settlement_tape_root(self):
        stats_only = FakeS3({raw_databento_key("glbx_mdp3", "CPO", 2027,
                                               "statistics_CPO_20270104.dbn.zst"): b"x"})
        ohlcv_only = FakeS3({raw_databento_key("glbx_mdp3", "CPO", 2027,
                                               "ohlcv-1d_CPO_20270104.dbn.zst"): b"x"})
        assert T2._incremental_unit_landed(stats_only, "b", T.GLBX, "CPO", 2027) is True
        assert T2._incremental_unit_landed(ohlcv_only, "b", T.GLBX, "CPO", 2027) is False
        # the bar-driven roots are UNCHANGED: ohlcv-1d is what they look for
        zc_stats = FakeS3({raw_databento_key("glbx_mdp3", "ZC", 2027,
                                             "statistics_ZC_20270104.dbn.zst"): b"x"})
        zc_ohlcv = FakeS3({raw_databento_key("glbx_mdp3", "ZC", 2027,
                                             "ohlcv-1d_ZC_20270104.dbn.zst"): b"x"})
        assert T2._incremental_unit_landed(zc_stats, "b", T.GLBX, "ZC", 2027) is False
        assert T2._incremental_unit_landed(zc_ohlcv, "b", T.GLBX, "ZC", 2027) is True

    def test_unit_root_reads_the_label(self):
        assert T2._unit_root("GLBX.MDP3 CPO/2026") == "CPO"
        assert T2._unit_root("GLBX.MDP3 ZC/2026") == "ZC"
        assert T2._unit_root("2026-07-29") is None
        assert T2._unit_root("IFUS.IMPACT XX/2026") is None


class TestSettlementTapeNonBlocking:
    """V2-4 m10 on the SILVER side, as narrowed by STEP-12 F3. In the nightly a CPO unit that is
    THIN keeps its partial rows (the merge is a union, new-wins -- a dropped frame left permanent
    silent holes in the palm partition), a MISSING statistics payload is skipped, any OTHER
    exception is the blocking FAILED it always was, and every thin is stamped machine-readably.
    A BACKFILL keeps the unit blocking (an empty year is a stop, K7)."""

    _PALM = "malaysian_crude_palm_oil_cme"
    _REAL_PUBLISH = staticmethod(T2.publish)

    def _run(self, monkeypatch, *, mode: str, cpo_loader, caplog, zc_dates=None,
             since="2026-07-27", merge=False, s3=None, published=None):
        import logging
        caplog.set_level(logging.INFO)
        monkeypatch.setattr(T2, "get_thread_local_s3_client",
                            lambda region: s3 if s3 is not None else FakeS3({}))
        # the healthy bar-driven unit
        zc = _bronze(zc_dates or ["2026-07-27", "2026-07-28", "2026-07-29"])

        def _units(args, s3_client, bucket, spec):
            return [("GLBX.MDP3 ZC/2026", lambda: (zc, {"rows_out": 3}), T.GLBX),
                    ("GLBX.MDP3 CPO/2026", cpo_loader, T.GLBX)]

        # the truncation verdict is keyed on the frame: healthy for corn, THIN for a palm frame
        # carrying fewer than 3 sessions (the walk below needs a passing second fire)
        def _trunc(bronze, spec, *, mode, since, dataset=None):
            if (len(bronze) and set(bronze["leviathan_slug"]) == {self._PALM}
                    and bronze["trade_date"].nunique() < 3):
                return (f"only {bronze['trade_date'].nunique()} of 5 expected session(s) present "
                        f"-- treating as a truncated download")
            return None

        def _publish(df, contract, auth, s3c, glue, **kw):
            if published is not None:
                published.append(df.copy())
            return self._REAL_PUBLISH(df, contract, auth, s3c, glue, **kw)

        monkeypatch.setattr(T2, "select_units", _units)
        monkeypatch.setattr(T2, "_truncation_error", _trunc)
        monkeypatch.setattr(T2, "publish", _publish)
        argv = ["--bucket", "b", "--aws-region", "us-east-1", "--mode", mode]
        if mode == "incremental":
            argv += ["--since", since]
            if not merge:
                argv += ["--no-merge"]
        return T2.main(argv)

    @classmethod
    def _palm_frame(cls, dates=("2026-07-27",)):
        return _bronze(list(dates), sym="CPOU6", slug=cls._PALM)

    @staticmethod
    def _skips_record(caplog) -> dict:
        tag = "SETTLEMENT_TAPE_SKIPS "
        lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith(tag)]
        assert len(lines) == 1, lines
        return json.loads(lines[0][len(tag):])

    @staticmethod
    def _unit_stats(caplog, label: str) -> dict:
        tag = f"unit {label}: "
        lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith(tag)]
        assert len(lines) == 1, lines
        return json.loads(lines[0][len(tag):])

    def test_a_thin_settlement_tape_unit_keeps_its_partial_rows_and_does_not_red_the_nightly(
            self, monkeypatch, caplog):
        published: list = []
        rc = self._run(monkeypatch, mode="incremental", caplog=caplog,
                       cpo_loader=lambda: (self._palm_frame(), {"rows_out": 1}),
                       published=published)
        assert rc == 0
        assert "SETTLEMENT_TAPE_THIN GLBX.MDP3 CPO/2026" in caplog.text
        assert "publish dry-run" in caplog.text, "the family still publishes"
        df = published[-1]
        palm = df[df["leviathan_slug"] == self._PALM]
        assert len(palm) == 1 and set(palm["trade_date"]) == {pd.Timestamp("2026-07-27")}, \
            "the PARTIAL frame is KEPT, never dropped"
        assert int((df["leviathan_slug"] == "corn_cbot").sum()) == 3
        # the machine-readable stamps: the unit line and the run-level record
        stats = self._unit_stats(caplog, "GLBX.MDP3 CPO/2026")
        assert stats["settlement_tape_thin"] == 1 and stats["rows_kept"] == 1
        assert "truncated download" in stats["settlement_tape_thin_reason"]
        assert self._skips_record(caplog) == {
            "settlement_tape_thin": 1, "settlement_tape_thin_units": ["GLBX.MDP3 CPO/2026"]}
        assert "settlement_tape_thin" not in json.dumps(self._unit_stats(caplog, "GLBX.MDP3 ZC/2026"))

    def test_a_thin_fire_followed_by_a_pass_leaves_no_hole_in_canonical(self, monkeypatch,
                                                                         caplog):
        """The verifier's walk: Mon 07-27 + Tue 07-28 ABSENT from the mark tape, Wed 07-29
        PRESENT. Fire 1 (a window ending 07-29) is THIN; before F3 its frame was dropped and
        07-29 -- present in the payload -- never landed. Now fire 1 publishes 07-29 and fire 2
        (a passing window from 07-30) merges on top of it: every session ANY fire's payload
        held is in canonical."""
        contract = _contract()
        published: list = []
        rc = self._run(monkeypatch, mode="incremental", caplog=caplog, since="2026-07-25",
                       cpo_loader=lambda: (self._palm_frame(["2026-07-29"]), {}),
                       published=published)
        assert rc == 0 and "SETTLEMENT_TAPE_THIN" in caplog.text
        fire1 = published[-1]
        palm1 = fire1[fire1["leviathan_slug"] == self._PALM].reset_index(drop=True)
        assert set(palm1["trade_date"]) == {pd.Timestamp("2026-07-29")}
        key, body = _canonical_body(palm1, contract)     # what fire 1 wrote for the palm partition
        caplog.clear()
        published.clear()
        rc = self._run(monkeypatch, mode="incremental", caplog=caplog, since="2026-07-30",
                       zc_dates=["2026-07-30", "2026-07-31", "2026-08-03"],
                       cpo_loader=lambda: (self._palm_frame(["2026-07-30", "2026-07-31",
                                                             "2026-08-03"]), {}),
                       merge=True, s3=FakeS3({key: body}), published=published)
        assert rc == 0 and "SETTLEMENT_TAPE_THIN" not in caplog.text
        fire2 = published[-1]
        palm2 = fire2[fire2["leviathan_slug"] == self._PALM]
        assert set(palm2["trade_date"].dt.strftime("%Y-%m-%d")) == {
            "2026-07-29", "2026-07-30", "2026-07-31", "2026-08-03"}, "no hole: 07-29 survived"

    def test_a_missing_statistics_object_does_not_red_the_nightly_either(self, monkeypatch, caplog):
        def _raise():
            raise FileNotFoundError("GLBX.MDP3 CPO/2026: settlement-tape root with NO statistics "
                                    "payload")

        rc = self._run(monkeypatch, mode="incremental", caplog=caplog, cpo_loader=_raise)
        assert rc == 0
        assert "SETTLEMENT_TAPE_THIN" in caplog.text and "FileNotFoundError" in caplog.text
        assert self._skips_record(caplog)["settlement_tape_thin_units"] == ["GLBX.MDP3 CPO/2026"]

    @pytest.mark.parametrize("exc", [ValueError("settle_flags out of range on one row"),
                                     RuntimeError("DBN version 9 is NEWER than the client"),
                                     KeyError("ts_ref"), OSError("transient S3 fault")])
    def test_any_other_exception_on_the_cpo_unit_is_still_a_blocking_failure(self, monkeypatch,
                                                                              caplog, exc):
        """STEP-12 F3 (2): the except-path swallow is the m10 shape ONLY. A bad row, a decode
        error or a transient fault on the palm unit is the loud FAILED it is on every root --
        a skip there is the silent-hole class."""
        def _raise():
            raise exc

        rc = self._run(monkeypatch, mode="incremental", caplog=caplog, cpo_loader=_raise)
        assert rc == 1
        assert "FAILED" in caplog.text and "GLBX.MDP3 CPO/2026" in caplog.text
        assert "SETTLEMENT_TAPE_THIN" not in caplog.text and "SETTLEMENT_TAPE_SKIPS" not in caplog.text

    def test_the_except_path_swallow_is_exactly_the_missing_payload_shape(self):
        assert T2._settlement_tape_thin_exception(FileNotFoundError("no statistics payload"))
        for exc in (ValueError("x"), RuntimeError("x"), KeyError("x"), OSError("x"),
                    PermissionError("x")):
            assert not T2._settlement_tape_thin_exception(exc), type(exc).__name__

    def test_the_same_verdict_still_fails_a_backfill(self, monkeypatch, caplog):
        rc = self._run(monkeypatch, mode="backfill", caplog=caplog,
                       cpo_loader=lambda: (self._palm_frame(), {}))
        assert rc == 1
        assert "SETTLEMENT_TAPE_THIN" not in caplog.text and "SETTLEMENT_TAPE_SKIPS" not in caplog.text

    def test_a_truncated_bar_driven_unit_still_fails_the_nightly(self, monkeypatch, caplog):
        """The positive control: the non-blocking path is keyed on the ROOT, so corn's truncation
        is the loud red it always was."""
        monkeypatch.setattr(T2, "get_thread_local_s3_client", lambda region: FakeS3({}))
        zc = _bronze(["2026-07-27"])
        monkeypatch.setattr(T2, "select_units", lambda *a, **k: [
            ("GLBX.MDP3 ZC/2026", lambda: (zc, {}), T.GLBX)])
        monkeypatch.setattr(T2, "_truncation_error", lambda *a, **k: "only 1 of 5 -- truncated")
        assert T2.main(["--bucket", "b", "--aws-region", "us-east-1", "--mode", "incremental",
                        "--since", "2026-07-27", "--no-merge"]) == 1

    def test_a_healthy_fire_stamps_nothing(self, monkeypatch, caplog):
        rc = self._run(monkeypatch, mode="incremental", caplog=caplog,
                       cpo_loader=lambda: (self._palm_frame(["2026-07-27", "2026-07-28",
                                                             "2026-07-29"]), {}))
        assert rc == 0
        assert "SETTLEMENT_TAPE_THIN" not in caplog.text and "SETTLEMENT_TAPE_SKIPS" not in caplog.text


class TestMonthContinuityOnBackfill:
    """V2-4 M2: an internal hole in a backfill assembly fails the run BEFORE any byte is staged,
    naming the months -- covers() would otherwise route a window inside it to the table."""

    def _run(self, monkeypatch, frame, caplog, *extra):
        import logging
        caplog.set_level(logging.INFO)
        monkeypatch.setattr(T2, "get_thread_local_s3_client", lambda region: FakeS3({}))
        monkeypatch.setattr(T2, "select_units", lambda *a, **k: [
            ("GLBX.MDP3 ZC/2026", lambda: (frame, {}), T.GLBX)])
        monkeypatch.setattr(T2, "_truncation_error", lambda *a, **k: None)
        return T2.main(["--bucket", "b", "--aws-region", "us-east-1", "--mode", "backfill",
                        *extra])

    def test_a_hole_fails_the_backfill_and_names_the_months(self, monkeypatch, caplog):
        rc = self._run(monkeypatch, _bronze(["2026-01-05", "2026-02-05", "2026-04-06"]), caplog)
        assert rc == 1
        assert "MONTH_CONTINUITY corn_cbot" in caplog.text and "2026-03" in caplog.text
        assert "publish dry-run" not in caplog.text, "nothing is staged past a hole"

    def test_a_continuous_span_publishes(self, monkeypatch, caplog):
        rc = self._run(monkeypatch, _bronze(["2026-01-05", "2026-02-05", "2026-03-05"]), caplog)
        assert rc == 0 and "MONTH_CONTINUITY" not in caplog.text

    def test_report_mode_records_the_hole_and_publishes(self, monkeypatch, caplog):
        """STEP-12 F8: ``--continuity report`` mirrors ``--row-floor report`` -- the lawful way to
        publish a shipped-root REPAIR backfill over a real vendor-outage month. The hole is still
        named (MONTH_CONTINUITY), the run continues, the bytes stage."""
        rc = self._run(monkeypatch, _bronze(["2026-01-05", "2026-02-05", "2026-04-06"]), caplog,
                       "--continuity", "report")
        assert rc == 0
        assert "MONTH_CONTINUITY corn_cbot" in caplog.text and "2026-03" in caplog.text
        assert "--continuity report: continuing anyway" in caplog.text
        assert "publish dry-run" in caplog.text

    def test_enforce_is_the_default_and_the_only_other_value_is_report(self, monkeypatch, caplog):
        rc = self._run(monkeypatch, _bronze(["2026-01-05", "2026-02-05", "2026-04-06"]), caplog,
                       "--continuity", "enforce")
        assert rc == 1 and "continuing anyway" not in caplog.text
        with pytest.raises(SystemExit):
            T2.main(["--bucket", "b", "--aws-region", "us-east-1", "--mode", "backfill",
                     "--continuity", "maybe"])
