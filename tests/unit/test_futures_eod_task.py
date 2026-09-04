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


class TestPerUnitWithhold:
    """LANE A / A-2 -- a truncation verdict withholds ONE unit; the family still gates and promotes.

    THE MEASURED BLAST RADIUS THIS CLOSES. A truncation verdict on one unit increments a run-level
    ``failures`` counter whose only expression is ``return 1 if failures else 0`` -- AFTER the
    shadow publish. In the state machine (infra/terraform/modules/step_functions/main.tf:225-284)
    Silver is a Map state with Retry and NO Catch, Next = Gate, and Gate Next = Promote, so a
    non-zero Silver exit ends the execution there. ONE unit's verdict therefore cost all 16 boards
    (ROOT_MAP: GLBX 8, IFUS 6, IFEU 2) their gate and their promote on 2026-09-02 and 2026-09-03.

    SENSITIVITY IS UNTOUCHED: same predicate, same one-holiday margin, same D-PR-16 lag. Only the
    CONSEQUENCE moves, from 16 boards to 1 unit. And it is only safe to move it now: making a
    KNOWN-WRONG check non-blocking would have made a whole-dataset false verdict quiet, whereas
    with A-1 a truncation verdict means something again.

    DEFAULT OFF, and that is deliberate -- see ``test_the_withhold_is_off_until_it_has_a_surface``.
    """

    _ROOTS = sorted(T.ROOT_MAP)
    _SINCE = "2026-07-27"
    _DATES = ["2026-07-27", "2026-07-28", "2026-07-29"]
    _REAL_PUBLISH = staticmethod(T2.publish)

    @pytest.fixture(autouse=True)
    def _fixture_calendar(self, monkeypatch, tmp_path):
        """A-R14 -- THE TIME BOMB, DISARMED. These ~24 cases drive main(), which runs the REAL
        arming lint against the REAL shipped calendar with a window year taken from ``_SINCE`` and
        the real clock. That is vacuous only while NOTHING is armed: the moment an operator arms a
        venue per the fill-and-arm workflow, every calendar year in which the run's window year is
        not also armed turns this whole class into VENUE_CALENDAR refusals (rc == 1) and reds a
        suite that has nothing to do with the calendar. The sibling lint class already points at a
        tmp fixture; this one now does too, so the withhold's pins measure the withhold.
        """
        import yaml
        from leviathan.silver import venue_calendar as VC
        path = tmp_path / "venue_holidays.yaml"
        path.write_text(yaml.safe_dump({"version": 1, "datasets": {}}, sort_keys=False),
                        encoding="utf-8")
        monkeypatch.setattr(VC, "VENUE_HOLIDAYS_PATH", path)
        VC.load_venue_holidays.cache_clear()
        yield
        VC.load_venue_holidays.cache_clear()

    @classmethod
    def _units_for(cls, roots):
        return [(f"{T.ROOT_MAP[r][0]} {r}/2026", r, T.ROOT_MAP[r][1]) for r in roots]

    def _run(self, monkeypatch, caplog, *, truncate=None, mode="incremental", withhold="on",
             roots=None, source="databento", published=None, rows_kept=1):
        """16 units by default, ``truncate`` naming the roots whose frame is charged as truncated.

        The truncation verdict is monkeypatched (as the m10 suite does) so the harness measures the
        CONSEQUENCE of a verdict, never the arithmetic that produces one -- that arithmetic has its
        own suite in tests/unit/silver/test_futures_eod_truncation_floor.py.
        """
        import logging
        caplog.set_level(logging.INFO)
        truncate = dict(truncate or {})
        roots = list(roots if roots is not None else self._ROOTS)
        monkeypatch.setattr(T2, "get_thread_local_s3_client", lambda region: FakeS3({}))
        if withhold is None:
            monkeypatch.delenv("LEVIATHAN_UNIT_WITHHOLD", raising=False)
        else:
            monkeypatch.setenv("LEVIATHAN_UNIT_WITHHOLD", withhold)
        current: dict = {}

        def _bind(label, root, slug):
            def _load():
                current["label"] = label
                if root in truncate:
                    n = truncate[root]
                    dates = self._DATES[:n]
                else:
                    dates = self._DATES
                return _bronze(dates, sym=f"{root}Z6", slug=slug), {"rows_out": len(dates)}
            return _load

        units = [(label, _bind(label, root, slug), T.ROOT_MAP[root][0])
                 for label, root, slug in self._units_for(roots)]
        monkeypatch.setattr(T2, "select_units", lambda *a, **k: units)

        def _trunc(bronze, spec, *, mode, since, dataset=None):
            root = T2._unit_root(current.get("label", ""))
            if root in truncate:
                return (f"only {truncate[root]} of 3 expected session(s) present "
                        f"(window 2026-07-27..2026-07-29) -- treating as a truncated download, "
                        f"not a thin market")
            return None

        monkeypatch.setattr(T2, "_truncation_error", _trunc)

        def _publish(df, contract, auth, s3c, glue, **kw):
            if published is not None:
                published.append(df.copy())
            return self._REAL_PUBLISH(df, contract, auth, s3c, glue, **kw)

        monkeypatch.setattr(T2, "publish", _publish)
        argv = ["--bucket", "b", "--aws-region", "us-east-1", "--mode", mode, "--source", source]
        if mode == "incremental":
            argv += ["--since", self._SINCE, "--no-merge"]
        return T2.main(argv)

    @staticmethod
    def _record(caplog) -> dict:
        tag = "UNIT_WITHHOLD_RECORD "
        lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith(tag)]
        assert len(lines) == 1, lines
        return json.loads(lines[0][len(tag):])

    @staticmethod
    def _withheld_lines(caplog) -> list:
        return [r.getMessage() for r in caplog.records
                if r.getMessage().startswith("UNIT_WITHHELD ")]

    def test_one_withheld_unit_lets_fifteen_siblings_publish_and_exits_zero(
            self, monkeypatch, caplog):
        """THE 15-SIBLINGS PIN. This is the whole point of A-2: on 09-02 and 09-03 the gate and the
        promote never ran for any board because one unit was charged."""
        published: list = []
        rc = self._run(monkeypatch, caplog, truncate={"RC": 1}, published=published)
        assert rc == 0
        assert "publish dry-run" in caplog.text, "the family still publishes"
        df = published[-1]
        slugs = set(df["leviathan_slug"])
        assert len(slugs) == 16, sorted(slugs)
        healthy = [s for r, s in ((r, T.ROOT_MAP[r][1]) for r in self._ROOTS) if r != "RC"]
        assert all(int((df["leviathan_slug"] == s).sum()) == 3 for s in healthy)
        assert int((df["leviathan_slug"] == T.ROOT_MAP["RC"][1]).sum()) == 1, \
            "the withheld unit's PARTIAL rows still ride the merge (STEP-12 F3)"

    def test_the_withheld_unit_is_declared_by_name_with_its_reason_and_its_slug(
            self, monkeypatch, caplog):
        """A withhold that is not DECLARED is a silent skip. The line carries the unit label, the
        slug (which is what an operator or a per-slug freshness emitter needs), the rows kept, and
        the verdict verbatim."""
        rc = self._run(monkeypatch, caplog, truncate={"RC": 1})
        assert rc == 0
        lines = self._withheld_lines(caplog)
        assert len(lines) == 1, lines
        assert lines[0].startswith("UNIT_WITHHELD IFEU.IMPACT RC/2026 slug=robusta_coffee "
                                   "rows_kept=1: ")
        assert "expected session(s) present" in lines[0] and "truncated download" in lines[0]
        stats = TestSettlementTapeNonBlocking._unit_stats(caplog, "IFEU.IMPACT RC/2026")
        assert stats["unit_withheld"] == 1 and stats["rows_kept"] == 1
        assert "truncated download" in stats["unit_withheld_reason"]

    def test_the_summary_line_counts_units_and_withholds(self, monkeypatch, caplog):
        """The machine-readable record, mirroring SETTLEMENT_TAPE_SKIPS. The two halves are kept
        SEPARATE in the JSON (kept-partial vs genuinely empty) and counted TOGETHER in the text,
        because the operator's question is "which boards did not fully publish this fire"."""
        rc = self._run(monkeypatch, caplog, truncate={"RC": 1, "W": 0})
        assert rc == 0
        assert ("UNIT_WITHHOLD_SUMMARY units=16 withheld=2 "
                "truncated=['IFEU.IMPACT RC/2026', 'IFEU.IMPACT W/2026']") in caplog.text
        assert self._record(caplog) == {
            "units": 16, "withheld": 2, "withheld_empty": 1, "withheld_partial_kept": 1,
            "rows_kept": 1, "truncated": ["IFEU.IMPACT RC/2026", "IFEU.IMPACT W/2026"],
            "slugs": ["robusta_coffee", "white_sugar"]}

    def test_an_empty_withheld_unit_names_its_slug_from_the_root_map(self, monkeypatch, caplog):
        """An EMPTY unit has no frame to ask for its slug, so the label's root is resolved through
        the same ROOT_MAP select_units built the label from. It must never guess."""
        rc = self._run(monkeypatch, caplog, truncate={"W": 0})
        assert rc == 0
        assert ("UNIT_WITHHELD IFEU.IMPACT W/2026 slug=white_sugar rows_kept=0: "
                in self._withheld_lines(caplog)[0])
        assert self._record(caplog)["withheld_empty"] == 1

    def test_every_unit_withheld_is_exit_one(self, monkeypatch, caplog):
        """THE ALL-WITHHELD PIN. Every board truncated is a FAMILY-wide verdict, not a per-unit
        one, so it keeps the exit code it has today -- and it keeps it whether or not the units
        held partial rows, because "all 16 boards are truncated" is the alarm regardless.

        It still PUBLISHES first: the F3 discipline is that data is never dropped to make a point,
        and a partial frame can only ADD sessions to canonical (union, new-wins, no-shrink).
        """
        published: list = []
        rc = self._run(monkeypatch, caplog, truncate={r: 1 for r in self._ROOTS},
                       published=published)
        assert rc == 1
        assert ("UNIT_WITHHOLD_ALL 15 of 16 unit(s) withheld (+1 settlement-tape thin)"
                in caplog.text), \
            "the CPO mark tape takes the m10 arm first; it still published nothing complete"
        assert "publish dry-run" in caplog.text, "the partial rows are still written"
        assert len(published[-1]) == 16
        assert self._record(caplog)["withheld"] == 15
        assert "SETTLEMENT_TAPE_THIN GLBX.MDP3 CPO/2026" in caplog.text

    def test_every_unit_withheld_and_all_empty_is_exit_one_with_nothing_published(
            self, monkeypatch, caplog):
        """The zero-row corner of the same pin: nothing to publish, and the existing
        no-bronze-frames exit survives with the withhold count added to its message."""
        rc = self._run(monkeypatch, caplog, truncate={r: 0 for r in self._ROOTS})
        assert rc == 1
        assert ("no bronze frames produced from 16 (root, year)(s) (15 withheld as truncated)"
                in caplog.text)
        assert "publish dry-run" not in caplog.text

    def test_a_single_unit_run_whose_only_unit_is_withheld_is_exit_one(self, monkeypatch, caplog):
        """The regression fence for the m10 suite's positive control
        (test_a_truncated_bar_driven_unit_still_fails_the_nightly): a run selecting ONE unit that
        is then withheld is "every unit withheld", so it stays exit 1."""
        rc = self._run(monkeypatch, caplog, roots=["ZC"], truncate={"ZC": 1})
        assert rc == 1
        assert "UNIT_WITHHOLD_ALL 1 of 1 unit(s) withheld" in caplog.text

    def test_a_withheld_units_partial_rows_still_ride_the_merge(self, monkeypatch, caplog):
        """THE F3 PIN, GENERALISED. STEP-12 F3 measured that DROPPING a partial frame left every
        session that sat only inside skipped windows permanently absent from canonical, silently
        (the shipped cadence loses a present Wednesday after a Mon+Tue absence in three exit-0
        fires). Doing that on 16 units instead of 1 would reopen the class 16 times wider.

        Here the withheld unit holds ONLY the Wednesday: it must be in the published frame.
        """
        published: list = []
        monkeypatch.setattr(TestPerUnitWithhold, "_DATES", ["2026-07-29"], raising=False)
        rc = self._run(monkeypatch, caplog, truncate={"RC": 1}, roots=["ZC", "RC"],
                       published=published)
        assert rc == 0
        df = published[-1]
        rc_rows = df[df["leviathan_slug"] == "robusta_coffee"]
        assert set(rc_rows["trade_date"].dt.strftime("%Y-%m-%d")) == {"2026-07-29"}, \
            "the session the payload DID deliver lands; dropping it would lose it for good"

    @pytest.mark.parametrize("exc", [ValueError("settle_flags out of range on one row"),
                                     RuntimeError("DBN version 9 is NEWER than the client"),
                                     KeyError("ts_ref"), OSError("transient S3 fault")])
    def test_a_non_floor_exception_is_still_exit_one(self, monkeypatch, caplog, exc):
        """A-2 scopes the TRUNCATION verdict and nothing else. A bad row, a decode error or a
        transient fault is the loud FAILED it has always been -- swallowing those is the
        silent-hole class, and the m10 suite already pins the same boundary for CPO."""
        import logging
        caplog.set_level(logging.INFO)
        monkeypatch.setenv("LEVIATHAN_UNIT_WITHHOLD", "on")
        monkeypatch.setattr(T2, "get_thread_local_s3_client", lambda region: FakeS3({}))

        def _raise():
            raise exc

        zc = _bronze(self._DATES)
        monkeypatch.setattr(T2, "select_units", lambda *a, **k: [
            ("GLBX.MDP3 ZC/2026", lambda: (zc, {}), T.GLBX),
            ("IFEU.IMPACT RC/2026", _raise, T.IFEU)])
        monkeypatch.setattr(T2, "_truncation_error", lambda *a, **k: None)
        rc = T2.main(["--bucket", "b", "--aws-region", "us-east-1", "--mode", "incremental",
                      "--since", self._SINCE, "--no-merge"])
        assert rc == 1
        assert "FAILED" in caplog.text and "IFEU.IMPACT RC/2026" in caplog.text
        assert self._withheld_lines(caplog) == []
        assert self._record(caplog)["withheld"] == 0, "the record still clears the metric"

    def test_a_backfill_truncation_is_still_blocking(self, monkeypatch, caplog):
        """K7, already the estate's ruling in this file: an operator-driven backfill with an empty
        year is a STOP, not a skip. A-2 is incremental-only."""
        rc = self._run(monkeypatch, caplog, mode="backfill", roots=["ZC", "RC"],
                       truncate={"RC": 1})
        assert rc == 1
        assert self._withheld_lines(caplog) == []
        assert "UNIT_WITHHOLD_SUMMARY" not in caplog.text
        assert "IFEU.IMPACT RC/2026: only 1 of 3 expected session(s) present" in caplog.text

    def test_a_healthy_fire_records_withheld_zero(self, monkeypatch, caplog):
        """The summary is emitted on EVERY eligible fire, healthy ones included. freshness.py's
        own words: "An alarm that only receives a datapoint while it is breaching can never
        CLEAR." The per-unit UNIT_WITHHELD line is the one that is absent when healthy -- that is
        what the metric filter counts, and its default_value = 0 clears the metric."""
        rc = self._run(monkeypatch, caplog)
        assert rc == 0
        assert self._withheld_lines(caplog) == []
        assert "UNIT_WITHHOLD_SUMMARY units=16 withheld=0 truncated=[]" in caplog.text
        assert self._record(caplog) == {
            "units": 16, "withheld": 0, "withheld_empty": 0, "withheld_partial_kept": 0,
            "rows_kept": 0, "truncated": [], "slugs": []}

    def test_the_free_legs_never_reach_the_withhold_path(self, monkeypatch, caplog):
        """The 22:30Z free chain is the NO-OP witness for this whole lane. Its five legs carry
        min_rows_per_unit = 0, so _truncation_error returns before any of this code; and even when
        a verdict is forced onto a non-databento leg here, the withhold path is not eligible and
        the verdict is the blocking failure it has always been."""
        import logging
        caplog.set_level(logging.INFO)
        monkeypatch.setenv("LEVIATHAN_UNIT_WITHHOLD", "on")
        monkeypatch.setattr(T2, "get_thread_local_s3_client", lambda region: FakeS3({}))
        monkeypatch.setattr(T2, "select_units", lambda *a, **k: [
            ("2026-07-29", lambda: (_bronze(["2026-07-29"]), {}), None)])
        monkeypatch.setattr(T2, "_truncation_error", lambda *a, **k: "forced verdict")
        rc = T2.main(["--bucket", "b", "--aws-region", "us-east-1", "--mode", "incremental",
                      "--source", "czce", "--since", self._SINCE, "--no-merge"])
        assert rc == 1
        assert self._withheld_lines(caplog) == []
        assert "UNIT_WITHHOLD_SUMMARY" not in caplog.text and "LANE_A_LEVERS" not in caplog.text
        assert T2._SOURCE_SPECS["czce"].min_rows_per_unit == 0, \
            "the real reason a free leg never gets here: it has no per-unit floor at all"

    def test_the_withhold_is_off_until_it_has_a_surface(self, monkeypatch, caplog):
        """THE DEVIATION, PINNED. The Lane A design has the withhold default ON; this build ships
        it default OFF, and the reason is measured rather than cautious.

        Exit 1 is TODAY the only path by which this failure reaches the owner
        (infra/terraform/modules/silver_observability/main.tf:212-245: "this alarm is the ONLY path
        by which a class-A/E1/F producer failure reaches the owner"). FreshnessLagDays cannot see
        one withheld board -- it is TABLE-granular (freshness.py:136-151 takes MAX LastModified
        over the whole canonical prefix, and the 13 non-ICE slugs rewrite their objects every
        fire) -- and the value census has no recency term (jobs/audit/value_census.py:214-233). So
        turning exit 1 into exit 0 BEFORE the UNIT_WITHHELD metric filter and its alarms exist
        would make the failure SILENT, which is strictly worse than a family-wide red. The withhold
        arms with its surface, in one operator act, never by landing code.
        """
        rc = self._run(monkeypatch, caplog, truncate={"RC": 1}, withhold=None)
        assert rc == 1, "default OFF: the pre-Lane-A blocking behaviour"
        assert self._withheld_lines(caplog) == []
        assert "IFEU.IMPACT RC/2026: only 1 of 3 expected session(s) present" in caplog.text
        assert "LANE_A_LEVERS venue_calendar=on unit_withhold=OFF" in caplog.text, \
            "the state of a fence must never have to be inferred from behaviour"
        for value in ("off", "0", "", "yes please"):
            caplog.clear()
            assert self._run(monkeypatch, caplog, truncate={"RC": 1}, withhold=value) == 1, value
        for value in ("on", "1", "true", "yes"):
            caplog.clear()
            assert self._run(monkeypatch, caplog, truncate={"RC": 1}, withhold=value) == 0, value


class TestVenueCalendarArmingLint:
    """LANE A / A-1c -- the arming lint at the call site, scoped to the datasets a run selected.

    An unarmed venue is NOT a refusal: that is the pre-Lane-A world for that venue, carried by the
    one-holiday margin exactly as it is today, and it is what makes landing this code safe while
    the calendar is still being filled. An ARMED venue that stops covering a year the window
    touches IS a refusal -- that is DRIFT on a fence someone is relying on, and it must never be
    silent. The "this year AND next" requirement lives in CI instead, so the forcing function reds
    there before any 08:00Z fire can red in production.
    """

    @staticmethod
    def _calendar(monkeypatch, tmp_path, doc):
        import yaml
        from leviathan.silver import venue_calendar as VC
        path = tmp_path / "venue_holidays.yaml"
        path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
        monkeypatch.setattr(VC, "VENUE_HOLIDAYS_PATH", path)
        VC.load_venue_holidays.cache_clear()
        return path

    @staticmethod
    def _armed(dataset, year, day):
        return {"version": 1, "datasets": {dataset: {
            "venue": "fixture", "source_url": "https://example.invalid/cal",
            "years": {year: {"complete": True, "verified_on": "2026-09-04",
                             "verified_by": "fixture",
                             "holidays": [{"day": day, "name": "a named closure",
                                           "basis": "published"}]}}}}}

    def _run(self, monkeypatch, caplog, since):
        import logging
        caplog.set_level(logging.INFO)
        monkeypatch.setattr(T2, "get_thread_local_s3_client", lambda region: FakeS3({}))
        monkeypatch.setattr(T2, "select_units", lambda *a, **k: [
            ("IFEU.IMPACT RC/2026", lambda: (_bronze(["2026-07-29"], slug="robusta_coffee"), {}),
             T.IFEU)])
        monkeypatch.setattr(T2, "_truncation_error", lambda *a, **k: None)
        return T2.main(["--bucket", "b", "--aws-region", "us-east-1", "--mode", "incremental",
                        "--since", since, "--no-merge"])

    @pytest.fixture(autouse=True)
    def _cold_cache(self):
        from leviathan.silver import venue_calendar as VC
        VC.load_venue_holidays.cache_clear()
        yield
        VC.load_venue_holidays.cache_clear()

    def test_an_unarmed_venue_does_not_refuse_the_run(self, monkeypatch, caplog, tmp_path):
        self._calendar(monkeypatch, tmp_path, {"version": 1, "datasets": {
            T.IFEU: {"venue": "v", "source_url": "TO BE FILLED", "years": {}}}})
        assert self._run(monkeypatch, caplog, "2026-07-27") == 0
        assert "VENUE_CALENDAR" not in caplog.text

    def test_an_armed_venue_that_stops_covering_the_window_refuses_by_name(
            self, monkeypatch, caplog, tmp_path):
        """The window's years are what the lint requires -- not a fixed roster. A run whose
        --since sits in a year the armed venue does not declare is refused, naming both."""
        self._calendar(monkeypatch, tmp_path, self._armed(T.IFEU, 2026, "2026-08-31"))
        assert self._run(monkeypatch, caplog, "2025-12-30") == 1
        assert "VENUE_CALENDAR IFEU.IMPACT: 2025 is missing or not complete: true" in caplog.text
        assert "VENUE_CALENDAR refusing the run" in caplog.text
        assert "publish dry-run" not in caplog.text, "nothing is staged past the refusal"

    def test_the_refusal_is_scoped_to_the_datasets_the_run_selected(self, monkeypatch, caplog,
                                                                     tmp_path):
        """--root ZC needs only GLBX, so a stale IFUS calendar must not stop it. This is why the
        lint runs AFTER select_units; the stated cost of that placement is that select_units' S3
        LISTs have already run, and a LIST writes nothing."""
        doc = self._armed(T.IFUS, 2026, "2026-08-31")
        self._calendar(monkeypatch, tmp_path, doc)
        assert self._run(monkeypatch, caplog, "2025-12-30") == 0, \
            "the run selects IFEU only; IFUS being stale is not its problem"
        assert "VENUE_CALENDAR" not in caplog.text

    def test_the_off_switch_disarms_the_lint_too(self, monkeypatch, caplog, tmp_path):
        """RB2 must be a complete rollback: a lever that turned the arithmetic off but left the
        refusal armed would be a rollback that still reds."""
        self._calendar(monkeypatch, tmp_path, self._armed(T.IFEU, 2026, "2026-08-31"))
        monkeypatch.setenv("LEVIATHAN_VENUE_CALENDAR", "off")
        assert self._run(monkeypatch, caplog, "2025-12-30") == 0
        assert "VENUE_CALENDAR" not in caplog.text
        assert "LANE_A_LEVERS venue_calendar=OFF" in caplog.text


class TestFixPassResolvedState:
    """FIX PASS -- A-R2, A-R3, A-R6, A-R7 and A-R13 at the CALL SITE.

    WHAT THE BANKED FIRES ACTUALLY SAID, because every pin below exists because of it. On the
    2026-09-02 08:30Z fire two units failed and the log named them: ``IFEU.IMPACT RC/2026`` and
    ``IFEU.IMPACT W/2026``, both "only 1 of 3 expected session(s) present (window
    2026-08-28..2026-09-01)". That window ends at T-1 over three weekdays -- the LAG 1 arithmetic
    -- while this tree declares IFEU lag 2. On the 2026-09-04 08:36Z fire all 16 units passed, and
    IFEU passed holding TWO sessions, which lag 1 would have red-ed (expected 4, present 2) and
    lag 2 does not (expected 3, present 2, green on the margin). So the resolved lag CHANGED
    between the two fires, and NOTHING IN EITHER LOG SAID SO: the run printed a verdict and no
    inputs, so settling it took a reconstruction from banked CloudWatch events days later.

    The plumbing itself is sound and is pinned here so it stays that way -- select_units sets
    ``dataset = ROOT_MAP[root][0]`` unconditionally for every databento unit, all 16 roots carry a
    non-empty token, and those tokens are the same module-level constants the lag map and the
    calendar key on. What was missing was never the wiring; it was the DETECTOR.
    """

    _SINCE = "2026-07-27"
    _DATES = ["2026-07-27", "2026-07-28", "2026-07-29"]

    @pytest.fixture(autouse=True)
    def _cold_cache(self):
        from leviathan.silver import venue_calendar as VC
        VC.load_venue_holidays.cache_clear()
        yield
        VC.load_venue_holidays.cache_clear()

    @staticmethod
    def _calendar(monkeypatch, tmp_path, text: str):
        from leviathan.silver import venue_calendar as VC
        path = tmp_path / "venue_holidays.yaml"
        path.write_text(text, encoding="utf-8")
        monkeypatch.setattr(VC, "VENUE_HOLIDAYS_PATH", path)
        VC.load_venue_holidays.cache_clear()
        return path

    _EMPTY_CAL = "version: 1\ndatasets: {}\n"
    _BROKEN_CAL = ("version: 1\ndatasets:\n  IFEU.IMPACT:\n    venue: v\n"
                   "    source_url: https://example.invalid/c\n    years:\n      2026:\n"
                   "        complete: 'true'\n        verified_on: '2026-09-04'\n"
                   "        verified_by: t\n        holidays: []\n")

    def _run(self, monkeypatch, caplog, *, roots=("ZC", "RC"), truncate=(), raise_on=(),
             argv_extra=()):
        import logging
        caplog.set_level(logging.INFO)
        monkeypatch.setattr(T2, "get_thread_local_s3_client", lambda region: FakeS3({}))

        def _bind(root, slug):
            def _load():
                if root in raise_on:
                    raise RuntimeError(f"{root} exploded")
                return _bronze(self._DATES, sym=f"{root}Z6", slug=slug), {"rows_out": 3}
            return _load

        units = [(f"{T.ROOT_MAP[r][0]} {r}/2026", _bind(r, T.ROOT_MAP[r][1]), T.ROOT_MAP[r][0])
                 for r in roots]
        monkeypatch.setattr(T2, "select_units", lambda *a, **k: units)

        def _trunc(bronze, spec, *, mode, since, dataset=None):
            slug = str(bronze["leviathan_slug"].iloc[0]) if len(bronze) else ""
            root = next((r for r in roots if T.ROOT_MAP[r][1] == slug), "")
            if root in truncate:
                return ("only 1 of 3 expected session(s) present (window "
                        "2026-07-27..2026-07-29) -- treating as a truncated download, "
                        "not a thin market")
            return None

        monkeypatch.setattr(T2, "_truncation_error", _trunc)
        return T2.main(["--bucket", "b", "--aws-region", "us-east-1", "--mode", "incremental",
                        "--since", self._SINCE, "--no-merge", *argv_extra])

    @staticmethod
    def _levers(caplog) -> str:
        lines = [r.getMessage() for r in caplog.records
                 if r.getMessage().startswith("LANE_A_LEVERS ")]
        assert len(lines) == 1, lines
        return lines[0]

    @staticmethod
    def _floors(caplog) -> dict:
        tag = "SESSION_FLOOR "
        out = {}
        for rec in caplog.records:
            msg = rec.getMessage()
            if msg.startswith(tag):
                rec_json = json.loads(msg[len(tag):])
                out[rec_json["unit"]] = rec_json
        return out

    # ------------------------------------------------------------------ A-R2
    def test_every_databento_unit_carries_a_lag_mapped_dataset_token(self):
        """A-R2, THE PLUMBING QUESTION, ANSWERED BY READING THE PATH RATHER THAN GUESSING IT.

        The review carried "the dataset token is not reaching the check" as a live hypothesis and
        the refutation called it unreachable. It IS unreachable, and this is the pin that keeps it
        so: ROOT_MAP's 16 roots all carry a non-empty dataset, every one of those tokens is a key
        in _EXPECTED_LAG_SESSIONS, and they are the SAME module-level constants -- imported, not
        re-spelt -- that the lag map and the calendar look up. A future refactor that starts
        returning None (or a differently-spelt token) for a databento unit reds here, where the
        cost is a test, rather than in a fire that silently falls back to lag 1.
        """
        assert len(T.ROOT_MAP) == 16
        assert [r for r, (ds, _slug) in T.ROOT_MAP.items() if not ds] == []
        tokens = sorted({ds for ds, _slug in T.ROOT_MAP.values()})
        assert tokens == sorted([T.GLBX, T.IFUS, T.IFEU])
        for token in tokens:
            assert token in T2._EXPECTED_LAG_SESSIONS, token
        assert T2._EXPECTED_LAG_SESSIONS == {T.GLBX: 1, T.IFUS: 2, T.IFEU: 2}
        assert T2._EXPECTED_LAG_SESSIONS.get(None or "", 1) == 1, "the documented fallback"

    def test_select_units_hands_every_databento_unit_its_dataset(self, monkeypatch):
        """The same claim one level up, at the function that builds the tuples the loop unpacks."""
        monkeypatch.setattr(T2, "_incremental_unit_landed", lambda *a, **k: True)

        class _Args:
            roots = None
            mode = "incremental"
            since = "2026-07-27"
            years = None
            ice_bar_rule = "prefer_on_venue_publisher"

        units = T2.select_units(_Args(), FakeS3({}), "b", T2._SOURCE_SPECS["databento"])
        assert units, "the roster is not empty"
        assert all(ds in T2._EXPECTED_LAG_SESSIONS for _lbl, _ld, ds in units)
        assert all(lbl.startswith(ds) for lbl, _ld, ds in units), \
            "the LABEL carries the dataset too -- which is how the 09-02 fire named IFEU"

    # ------------------------------------------------------------------ A-R3
    def test_the_levers_line_prints_what_the_run_resolved(self, monkeypatch, caplog, tmp_path):
        """A-R3 + the brief. The run-level half: how many units, which dataset tokens actually
        arrived, the lag each resolves to, and the calendar years the window touches.

        ``datasets=[]`` on a 16-unit fire would prove the token is not arriving, from the log
        alone, on the first fire, with no AWS call. And ``lags={'IFEU.IMPACT': 2, ...}`` is the
        single line whose absence made the 09-02 fire unreadable.
        """
        self._calendar(monkeypatch, tmp_path, self._EMPTY_CAL)
        assert self._run(monkeypatch, caplog, roots=("ZC", "RC", "KC")) == 0
        line = self._levers(caplog)
        assert "LANE_A_LEVERS venue_calendar=on unit_withhold=OFF units=3" in line
        assert "datasets=['GLBX.MDP3', 'IFEU.IMPACT', 'IFUS.IMPACT']" in line
        assert "lags={'GLBX.MDP3': 1, 'IFEU.IMPACT': 2, 'IFUS.IMPACT': 2}" in line
        assert "calendar_years=[2026" in line, "year(--since); a straddle adds year(T-1)"
        assert "declaring=[] armed=[]" in line

    def test_the_session_floor_line_is_emitted_for_a_failing_unit_too(self, monkeypatch, caplog,
                                                                      tmp_path):
        """A-R3's per-unit half, and the exact gap the incident had.

        A unit charged as truncated takes the ERROR branch and emits NO ``unit ...`` stats line --
        which is why the 09-02 fire's two failing IFEU units left nothing behind but a verdict.
        SESSION_FLOOR is emitted BEFORE the branch, so the failing unit is precisely the one whose
        resolved dataset, lag, window, weekday count, holidays removed and present/expected are on
        the record.
        """
        self._calendar(monkeypatch, tmp_path, self._EMPTY_CAL)
        assert self._run(monkeypatch, caplog, roots=("ZC", "RC"), truncate=("RC",)) == 1
        floors = self._floors(caplog)
        assert sorted(floors) == ["GLBX.MDP3 ZC/2026", "IFEU.IMPACT RC/2026"]
        failing = floors["IFEU.IMPACT RC/2026"]
        assert failing["dataset"] == "IFEU.IMPACT" and failing["lag"] == 2
        assert failing["verdict"] == "truncated"
        assert failing["holidays_removed"] == [] and failing["calendar"] == "on"
        assert set(failing) >= {"since", "window_end", "weekdays", "expected", "present"}
        assert floors["GLBX.MDP3 ZC/2026"]["lag"] == 1
        assert floors["GLBX.MDP3 ZC/2026"]["verdict"] == "ok"
        assert "unit IFEU.IMPACT RC/2026:" not in caplog.text, \
            "the failing unit still emits no stats line -- which is why SESSION_FLOOR exists"

    def test_the_floor_line_is_absent_where_the_floor_does_not_apply(self, monkeypatch, caplog):
        """The 22:30Z free chain: min_rows_per_unit = 0, the floor never applies, and nothing is
        logged for it. A line emitted where no fence runs would be noise pretending to be state."""
        import logging
        caplog.set_level(logging.INFO)
        monkeypatch.setattr(T2, "get_thread_local_s3_client", lambda region: FakeS3({}))
        monkeypatch.setattr(T2, "select_units", lambda *a, **k: [
            ("2026-07-29", lambda: (_bronze(["2026-07-29"], sym="RM701",
                                            slug="rapeseed_meal_zce"), {}), None)])
        rc = T2.main(["--bucket", "b", "--aws-region", "us-east-1", "--mode", "incremental",
                      "--source", "czce", "--since", self._SINCE, "--no-merge",
                      "--row-floor", "report"])
        assert rc == 0
        assert "SESSION_FLOOR" not in caplog.text and "LANE_A_LEVERS" not in caplog.text
        assert T2._SOURCE_SPECS["czce"].min_rows_per_unit == 0, "the reason: no per-unit floor"

    # ------------------------------------------------------------------ A-R7
    def test_a_malformed_calendar_is_a_named_refusal_not_a_traceback(self, monkeypatch, caplog,
                                                                     tmp_path):
        """A-R7. The module's rule 2 promises a hard error on a malformed file, and it delivered
        one -- as an uncaught ValueError out of ``main``. Fail-closed, but the operator got a stack
        trace where every other fence in this file gives one line naming the file and the lever.
        """
        self._calendar(monkeypatch, tmp_path, self._BROKEN_CAL)
        assert self._run(monkeypatch, caplog, roots=("RC",)) == 1
        assert "VENUE_CALENDAR refusing the run" in caplog.text
        assert "venue_holidays.yaml is unreadable" in caplog.text
        assert "complete must be a BOOLEAN" in caplog.text, "the reason, not just the refusal"
        assert "LEVIATHAN_VENUE_CALENDAR=off" in caplog.text, "and the lever that gets past it"
        assert "publish dry-run" not in caplog.text, "nothing is staged past the refusal"

    # ------------------------------------------------------------------ A-R6
    def test_the_off_switch_survives_an_unreadable_calendar(self, monkeypatch, caplog, tmp_path):
        """A-R6. RB2 must be a COMPLETE rollback, and the most likely reason anyone reaches for it
        is a bad calendar edit -- which was the one case it did not cover: the levers line called
        ``declaring_datasets()`` unguarded, so the run died inside the LOG LINE, on exactly the
        file the rollback exists to escape from.
        """
        self._calendar(monkeypatch, tmp_path, self._BROKEN_CAL)
        monkeypatch.setenv("LEVIATHAN_VENUE_CALENDAR", "off")
        assert self._run(monkeypatch, caplog, roots=("RC",)) == 0
        line = self._levers(caplog)
        assert "venue_calendar=OFF" in line
        assert "declaring=[] armed=[]" in line, "off means off: the file is not read at all"
        assert "VENUE_CALENDAR" not in caplog.text.replace("LEVIATHAN_VENUE_CALENDAR", "")

    def test_an_unreadable_calendar_is_printed_as_unreadable_never_thrown_from_a_log_line(
            self, monkeypatch, caplog, tmp_path):
        """The other half of A-R6: with the calendar ON and the file broken, the levers line still
        prints -- saying UNREADABLE -- and the REFUSAL is what stops the run. A log line must
        never be the thing that raises."""
        self._calendar(monkeypatch, tmp_path, self._BROKEN_CAL)
        assert self._run(monkeypatch, caplog, roots=("RC",)) == 1
        line = self._levers(caplog)
        assert "declaring=UNREADABLE armed=UNREADABLE" in line
        assert "venue_calendar=on" in line

    # ------------------------------------------------------------------ A-R13
    def test_the_family_verdict_counts_what_published_not_a_denominator(self, monkeypatch, caplog,
                                                                        tmp_path):
        """A-R13. ``all_withheld`` was ``(withheld + thin) == len(units)`` -- a denominator any
        unit in neither bucket could dilute.

        THE CONSTRUCTIBLE CASE: one root raises (a non-floor failure, so it is neither withheld nor
        thin) and every other root is withheld. Nothing published. The old denominator read
        1 + 0 != 2 and stayed silent about it; counting the units that actually took the healthy
        path says what is true -- no board published fully -- and says it in the line an operator
        reads. The exit code was already 1 here on the exception; what changes is that the
        family-wide event is NAMED.
        """
        self._calendar(monkeypatch, tmp_path, self._EMPTY_CAL)
        monkeypatch.setenv("LEVIATHAN_UNIT_WITHHOLD", "on")
        rc = self._run(monkeypatch, caplog, roots=("ZC", "RC"), truncate=("RC",),
                       raise_on=("ZC",))
        assert rc == 1
        assert "UNIT_WITHHOLD_ALL 1 of 2 unit(s) withheld" in caplog.text
        assert "FAILED" in caplog.text, "the exception is still a blocking failure"

    def test_a_single_publishing_sibling_clears_the_family_verdict(self, monkeypatch, caplog,
                                                                   tmp_path):
        """The anti-vacuity half. One board that publishes fully is enough to make the fire a
        per-unit event rather than a family-wide one, which is the entire point of the withhold."""
        self._calendar(monkeypatch, tmp_path, self._EMPTY_CAL)
        monkeypatch.setenv("LEVIATHAN_UNIT_WITHHOLD", "on")
        assert self._run(monkeypatch, caplog, roots=("ZC", "RC"), truncate=("RC",)) == 0
        assert "UNIT_WITHHOLD_ALL" not in caplog.text
        assert "UNIT_WITHHOLD_SUMMARY units=2 withheld=1" in caplog.text

    # ------------------------------------------------------------------ A-R11 at the call site
    def test_a_contradicted_entry_is_warned_once_per_unit_and_summarised(self, monkeypatch,
                                                                         caplog, tmp_path):
        """A-R11 at the call site. A declared date the TAPE holds rows on is the one calendar
        defect the arming lint cannot see -- it checks a year's presence and its declared
        completeness, never its correctness. It never changes a verdict; it names the entry."""
        self._calendar(monkeypatch, tmp_path,
                       "version: 1\ndatasets:\n  GLBX.MDP3:\n    venue: v\n"
                       "    source_url: https://example.invalid/c\n    years:\n      2026:\n"
                       "        complete: false\n        verified_on: '2026-09-04'\n"
                       "        verified_by: t\n        holidays:\n"
                       "          - {day: 2026-07-28, name: a wrong entry, basis: tape}\n")
        assert self._run(monkeypatch, caplog, roots=("ZC",)) == 0
        assert "VENUE_CALENDAR_CONTRADICTED GLBX.MDP3 ZC/2026" in caplog.text
        assert "['2026-07-28']" in caplog.text
        assert '"contradicted": ["GLBX.MDP3 ZC/2026"]' in caplog.text
