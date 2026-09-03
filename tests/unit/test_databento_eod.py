"""PRICE_AND_PLAYBOOKS W2 -- the Databento transform surface. Hermetic: no network, no AWS, no
vendor package (the DBN decode lane is exercised only where ``databento`` happens to be importable).

Covers the things a later wave could silently break AND every defect the plan/recon named:
  * the outright filter, including the measured ``T12Q6`` leak through the bare GLBX regex;
  * the DOWNLOAD-YEAR-ANCHORED decade rule at the 2016-vs-2026 boundary;
  * the fixed-point 1e-9 scaling and BOTH undefined sentinels (``to_df`` masks the price one only);
  * the statistics reduction: stat_type selection, DELETE retraction, preliminary->final by ts_recv,
    and ts_ref as the trading date;
  * the ICE double-bar dedupe under both named rules;
  * the F-A raw_symbol -> one instrument_id hard fail;
  * that the silver frame goes through ``build_partitioned_publish`` WITH
    ``row_validator=FC.lint_frame`` -- proven by a frame that only that validator can reject.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from leviathan.silver import futures_eod_contracts as FC
from leviathan.transforms.bronze_to_silver import databento_eod as S
from leviathan.transforms.raw_to_bronze import databento_eod as T

GLBX, IFUS, IFEU = T.GLBX, T.IFUS, T.IFEU
SCALE = T.FIXED_PRICE_SCALE


def _ohlcv(rows: list[dict]) -> pd.DataFrame:
    """A decoded ohlcv-1d frame: fixed-point prices, raw ints, a `symbol` column."""
    return pd.DataFrame(rows, columns=["ts_event", "instrument_id", "publisher_id", "symbol",
                                       "open", "high", "low", "close", "volume"])


def _bar(ts, iid, sym, px, *, pub=1, vol=100):
    p = int(round(px * SCALE))
    return {"ts_event": ts, "instrument_id": iid, "publisher_id": pub, "symbol": sym,
            "open": p, "high": p + SCALE, "low": p - SCALE, "close": p, "volume": vol}


# ---------------------------------------------------------------------------
class TestOutrightFilter:
    """F1: parent symbology is DISCOVERY only; the filter is regex AND an exact root match."""

    def test_glbx_outright_accepted(self):
        assert T.is_outright("ZCH6", "ZC", GLBX)
        assert T.is_outright("ZCZ6", "ZC", GLBX)
        assert T.is_outright("KEN4", "KE", GLBX)

    def test_the_measured_t12q6_leak_is_rejected(self):
        # The orchestrator's 2026-07-28 live smoke: ZC.FUT for 2016 leaked 'T12Q6' through the bare
        # GLBX regex. The regex alone MATCHES it -- only the root conjunct rejects it.
        assert T.GLBX_OUTRIGHT_RE.match("T12Q6"), "the bare regex admits it -- that is the point"
        assert not T.is_outright("T12Q6", "ZC", GLBX)

    def test_glbx_spread_complex_rejected(self):
        for sym in ("ZCH6-ZCK6", "ZC:BF H6-K6-N6", "ZCH6-ZCK6-ZCN6", ""):
            assert not T.is_outright(sym, "ZC", GLBX)

    def test_ice_outright_accepted_and_variants_rejected(self):
        assert T.is_outright("KC  FMZ0026!", "KC", IFUS)
        assert T.is_outright("RC  FMX0026!", "RC", IFEU)
        # _Z TAS suffixes and numeric-id instruments -- present in EVERY year 2018-2026, so
        # dropping them loses no history.
        assert not T.is_outright("KC  FMZ0026_Z!", "KC", IFUS)
        assert not T.is_outright("SB   99   6512548", "SB", IFUS)
        assert not T.is_outright("RC    3  30305098", "RC", IFEU)

    def test_single_character_root_is_not_swallowed_by_startswith(self):
        # The IFEU white-sugar root is the single character "W" ("WS" is a 422). A bare
        # startswith(root) would let a two-character root's symbol through.
        assert T.is_outright("W   FMH0026!", "W", IFEU)
        assert not T.is_outright("WS  FMH0026!", "W", IFEU)

    def test_partition_symbols_reports_a_nonzero_drop_count(self):
        # Gate 2's metric: it must be non-zero for EVERY root, GLBX included.
        keep, drop = T.partition_symbols(
            ["ZCH6", "ZCZ6", "ZCH6-ZCK6", "T12Q6", "ZC:BF H6-K6-N6"], "ZC", GLBX)
        assert keep == ["ZCH6", "ZCZ6"]
        assert len(drop) == 3

    def test_unknown_dataset_fails_closed(self):
        with pytest.raises(ValueError):
            T.symbol_root("ZCH6", "XNAS.ITCH")


class TestDecadeRule:
    """D2: the GLBX single-digit year is anchored on the DOWNLOAD year, never datetime.now()."""

    def test_same_symbol_decodes_differently_per_request_year(self):
        assert T.contract_month_str("ZCH6", "ZC", GLBX, 2016) == "2016-03"
        assert T.contract_month_str("ZCH6", "ZC", GLBX, 2026) == "2026-03"

    def test_smallest_year_at_or_after_the_anchor(self):
        assert T.resolve_glbx_year(6, 2016) == 2016      # exact
        assert T.resolve_glbx_year(6, 2015) == 2016      # forward within the decade
        assert T.resolve_glbx_year(5, 2016) == 2025      # wraps to the next decade
        assert T.resolve_glbx_year(0, 2026) == 2030
        assert T.resolve_glbx_year(9, 2010) == 2019

    def test_the_2016_vs_2026_boundary_is_exact_for_every_month_code(self):
        for code in T.MONTH_CODES:
            assert T.contract_month_str(f"ZC{code}6", "ZC", GLBX, 2016).startswith("2016-")
            assert T.contract_month_str(f"ZC{code}6", "ZC", GLBX, 2026).startswith("2026-")

    def test_decode_is_wall_clock_independent(self, monkeypatch):
        # A backfill re-run in 2031 over the 2016 raw bytes must decode identically. The rule takes
        # no clock at all -- freezing one would be untestable, so this asserts the signature
        # instead: the only year input is the caller-supplied anchor.
        before = T.contract_month_str("ZCH6", "ZC", GLBX, 2016)
        monkeypatch.setenv("TZ", "UTC")
        assert T.contract_month_str("ZCH6", "ZC", GLBX, 2016) == before == "2016-03"

    def test_ice_is_unambiguous_and_ignores_the_anchor(self):
        for anchor in (2019, 2026, 2031):
            assert T.contract_month_str("KC  FMZ0026!", "KC", IFUS, anchor) == "2026-12"
            assert T.contract_month_str("RC  FMX0019!", "RC", IFEU, anchor) == "2019-11"

    def test_decode_refuses_a_non_outright(self):
        with pytest.raises(ValueError, match="not an outright"):
            T.decode_symbol("ZCH6-ZCK6", "ZC", GLBX, 2016)


class TestPriceScaling:
    def test_fixed_point_1e9(self):
        got = T.scale_fixed_price([3552500000, 4177500000])
        assert got.tolist() == pytest.approx([3.5525, 4.1775])

    def test_undef_price_becomes_nan(self):
        got = T.scale_fixed_price([T.UNDEF_PRICE, 1_000_000_000])
        assert np.isnan(got.iloc[0]) and got.iloc[1] == 1.0

    def test_stat_quantity_sentinels_masked_both_widths(self):
        # to_df masks UNDEF_PRICE on PRICE fields only -- quantity leaks i64-max straight into
        # open_interest unless masked here. v1 files use the i4 max instead.
        got = T.mask_stat_quantity([T.UNDEF_STAT_QUANTITY, T.UNDEF_STAT_QUANTITY_V1, 51234])
        assert pd.isna(got.iloc[0]) and pd.isna(got.iloc[1]) and got.iloc[2] == 51234


class TestOhlcvBronze:
    def test_glbx_bronze_shape_and_values(self):
        df = _ohlcv([_bar("2016-03-01T00:00:00Z", 1, "ZCH6", 3.5525),
                     _bar("2016-03-02T00:00:00Z", 1, "ZCH6", 3.5875),
                     _bar("2016-03-01T00:00:00Z", 2, "ZCH6-ZCK6", 0.01)])
        out, stats = T.build_ohlcv_bronze(df, dataset=GLBX, root="ZC", request_year=2016)
        assert list(out.columns) == T.BRONZE_COLUMNS
        assert len(out) == 2
        assert set(out["contract_month"]) == {"2016-03"}
        assert out["leviathan_slug"].unique().tolist() == ["corn_cbot"]
        assert out["close"].iloc[0] == pytest.approx(3.5525)
        assert stats["dropped_symbols"] == 1 and stats["outright_symbols"] == 1
        assert out["settle"].isna().all(), "GLBX settle comes from statistics, never from close"

    def test_empty_frame_returns_the_bronze_shape(self):
        out, stats = T.build_ohlcv_bronze(_ohlcv([]), dataset=GLBX, root="ZC", request_year=2016)
        assert out.empty and list(out.columns) == T.BRONZE_COLUMNS and stats["rows_out"] == 0

    def test_root_dataset_mismatch_fails_closed(self):
        with pytest.raises(ValueError, match="does not belong"):
            T.build_ohlcv_bronze(_ohlcv([]), dataset=IFUS, root="ZC", request_year=2016)

    def test_fa_same_date_ambiguity_is_a_hard_fail(self):
        # F-A, per-date form: one symbol on two ids on the SAME date is genuinely ambiguous --
        # the ohlcv/statistics join and F2's falsification test both key on it.
        df = _ohlcv([_bar("2016-03-01T00:00:00Z", 1, "ZCH6", 3.5),
                     _bar("2016-03-01T12:00:00Z", 2, "ZCH6", 3.6)])
        with pytest.raises(ValueError, match="F-A violated"):
            T.build_ohlcv_bronze(df, dataset=GLBX, root="ZC", request_year=2016)

    def test_fa_disjoint_relisting_is_decodable_and_passes(self):
        # AMENDED 2026-07-29, measured on ZCN4/ZC-2010 (the transform-side twin of the fetch-side
        # KEN4 amendment): GLBX recycles instrument_ids, so one symbol on two ids on DISJOINT
        # dates is a re-listing, not ambiguity -- every (symbol, date) still has exactly one id.
        df = _ohlcv([_bar("2016-03-01T00:00:00Z", 1, "ZCH6", 3.5),
                     _bar("2016-03-02T00:00:00Z", 2, "ZCH6", 3.6)])
        out, _meta = T.build_ohlcv_bronze(df, dataset=GLBX, root="ZC", request_year=2016)
        assert len(out) == 2

    def test_fa_check_is_a_no_op_on_a_clean_frame(self):
        T.assert_symbol_instrument_1to1(
            pd.DataFrame({"raw_symbol": ["ZCH6", "ZCH6"], "instrument_id": [1, 1]}), label="x")


class TestIceDedupe:
    """F2/D4: ICE emits ~2 bars per contract per UTC day; GLBX emits exactly 1."""

    def _pair(self):
        return _ohlcv([
            _bar("2026-07-20T22:00:00Z", 7, "KC  FMZ0026!", 3.00, pub=97, vol=10),   # on-venue
            _bar("2026-07-20T23:30:00Z", 7, "KC  FMZ0026!", 3.05, pub=98, vol=1),    # XOFF, later
        ])

    def test_default_rule_keeps_the_last_by_ts_event(self):
        out, _ = T.build_ohlcv_bronze(self._pair(), dataset=IFUS, root="KC", request_year=2026,
                                      ice_bar_rule="keep_last_by_ts_event")
        assert len(out) == 1
        assert out["close"].iloc[0] == pytest.approx(3.05)
        assert out["publisher_id"].iloc[0] == 98

    def test_publisher_rule_keeps_the_on_venue_bar(self):
        out, _ = T.build_ohlcv_bronze(self._pair(), dataset=IFUS, root="KC", request_year=2026,
                                      ice_bar_rule="prefer_on_venue_publisher")
        assert len(out) == 1
        assert out["publisher_id"].iloc[0] == 97
        assert out["close"].iloc[0] == pytest.approx(3.00)

    def test_either_rule_leaves_the_key_unique(self):
        for rule in T.ICE_BAR_RULES:
            out, _ = T.build_ohlcv_bronze(self._pair(), dataset=IFUS, root="KC",
                                          request_year=2026, ice_bar_rule=rule)
            assert not out.duplicated(subset=["raw_symbol", "trade_date"]).any()

    def test_unknown_rule_fails_closed(self):
        with pytest.raises(ValueError, match="unknown ICE_BAR_RULE"):
            T.dedupe_ice_bars(pd.DataFrame({"raw_symbol": ["x"], "trade_date": [1]}), rule="vibes")

    def test_glbx_is_not_deduped(self):
        out, stats = T.build_ohlcv_bronze(
            _ohlcv([_bar("2016-03-01T00:00:00Z", 1, "ZCH6", 3.5)]),
            dataset=GLBX, root="ZC", request_year=2016)
        assert stats["ice_dedupe"] is None and len(out) == 1

    def test_probe_reports_the_publisher_split(self):
        out, _ = T.build_ohlcv_bronze(self._pair(), dataset=IFUS, root="KC", request_year=2026)
        # After the dedupe there is nothing left to split -- the probe is meant for the PRE-dedupe
        # frame, which is what the task records.
        assert T.probe_ice_bar_rule(out)["dup_keys"] == 0
        pre = pd.DataFrame({"raw_symbol": ["KC  FMZ0026!"] * 2,
                            "trade_date": [pd.Timestamp("2026-07-20")] * 2,
                            "publisher_id": [97, 98]})
        probe = T.probe_ice_bar_rule(pre)
        assert probe["dup_keys"] == 1 and probe["publisher_split_keys"] == 1
        assert probe["recommended_rule"] == "prefer_on_venue_publisher"


class TestStatisticsJoin:
    """D3: settle + open_interest from the statistics schema; the ohlcv close stays in close."""

    def _stat(self, sym, ts_recv, ts_ref, stat_type, *, price=None, qty=None,
              action=T.STAT_UPDATE_ACTION_NEW, iid=1, flags=0):
        return {"ts_recv": ts_recv, "ts_event": ts_recv, "ts_ref": ts_ref, "instrument_id": iid,
                "symbol": sym,
                "price": T.UNDEF_PRICE if price is None else int(round(price * SCALE)),
                "quantity": T.UNDEF_STAT_QUANTITY if qty is None else qty,
                "stat_type": stat_type, "update_action": action, "sequence": 0,
                "stat_flags": flags, "channel_id": 65535}

    def test_settlement_and_open_interest(self):
        df = pd.DataFrame([
            self._stat("ZCH6", "2016-03-01T20:00:00Z", "2016-03-01T00:00:00Z",
                       T.STAT_TYPE_SETTLEMENT_PRICE, price=3.5875, flags=8),
            self._stat("ZCH6", "2016-03-01T20:00:00Z", "2016-03-01T00:00:00Z",
                       T.STAT_TYPE_OPEN_INTEREST, qty=51234),
        ])
        out = T.build_statistics_bronze(df, root="ZC", request_year=2016)
        assert len(out) == 1
        assert out["settle"].iloc[0] == pytest.approx(3.5875)
        assert out["open_interest"].iloc[0] == 51234
        assert out["settle_flags"].iloc[0] == 8

    def test_settlement_quantity_sentinel_never_becomes_open_interest(self):
        df = pd.DataFrame([self._stat("ZCH6", "2016-03-01T20:00:00Z", "2016-03-01T00:00:00Z",
                                      T.STAT_TYPE_SETTLEMENT_PRICE, price=3.5)])
        out = T.build_statistics_bronze(df, root="ZC", request_year=2016)
        assert pd.isna(out["open_interest"].iloc[0])

    def test_trade_date_comes_from_ts_ref_not_ts_recv(self):
        # A settlement RECEIVED on the 2nd for the trading date of the 1st belongs to the 1st.
        df = pd.DataFrame([self._stat("ZCH6", "2016-03-02T02:00:00Z", "2016-03-01T00:00:00Z",
                                      T.STAT_TYPE_SETTLEMENT_PRICE, price=3.5)])
        out = T.build_statistics_bronze(df, root="ZC", request_year=2016)
        assert out["trade_date"].iloc[0] == pd.Timestamp("2016-03-01")

    def test_final_supersedes_preliminary_by_ts_recv(self):
        df = pd.DataFrame([
            self._stat("ZCH6", "2016-03-01T20:00:00Z", "2016-03-01T00:00:00Z",
                       T.STAT_TYPE_SETTLEMENT_PRICE, price=3.50),
            self._stat("ZCH6", "2016-03-02T02:00:00Z", "2016-03-01T00:00:00Z",
                       T.STAT_TYPE_SETTLEMENT_PRICE, price=3.60),
        ])
        out = T.build_statistics_bronze(df, root="ZC", request_year=2016)
        assert out["settle"].iloc[0] == pytest.approx(3.60)

    def test_a_retracted_settlement_is_dropped(self):
        df = pd.DataFrame([
            self._stat("ZCH6", "2016-03-01T20:00:00Z", "2016-03-01T00:00:00Z",
                       T.STAT_TYPE_SETTLEMENT_PRICE, price=3.50),
            self._stat("ZCH6", "2016-03-02T02:00:00Z", "2016-03-01T00:00:00Z",
                       T.STAT_TYPE_SETTLEMENT_PRICE, price=3.50,
                       action=T.STAT_UPDATE_ACTION_DELETE),
        ])
        out = T.build_statistics_bronze(df, root="ZC", request_year=2016)
        assert out.empty, "the last record by ts_recv was a DELETE -- the statistic was retracted"

    def test_other_stat_types_are_ignored(self):
        df = pd.DataFrame([self._stat("ZCH6", "2016-03-01T20:00:00Z", "2016-03-01T00:00:00Z",
                                      13, price=3.5)])   # VWAP
        assert T.build_statistics_bronze(df, root="ZC", request_year=2016).empty

    def test_statistics_on_an_ice_root_is_refused(self):
        with pytest.raises(ValueError, match="GLBX-only"):
            T.build_statistics_bronze(pd.DataFrame(), root="KC", request_year=2026)

    def test_join_leaves_close_alone_and_never_backfills_settle(self):
        ohlcv, _ = T.build_ohlcv_bronze(
            _ohlcv([_bar("2016-03-01T00:00:00Z", 1, "ZCH6", 3.5525),
                    _bar("2016-03-02T00:00:00Z", 1, "ZCH6", 3.5600)]),
            dataset=GLBX, root="ZC", request_year=2016)
        stats = T.build_statistics_bronze(pd.DataFrame([
            self._stat("ZCH6", "2016-03-01T20:00:00Z", "2016-03-01T00:00:00Z",
                       T.STAT_TYPE_SETTLEMENT_PRICE, price=3.5875)]),
            root="ZC", request_year=2016)
        joined = T.join_glbx_statistics(ohlcv, stats)
        assert joined.loc[0, "settle"] == pytest.approx(3.5875)
        assert joined.loc[0, "close"] == pytest.approx(3.5525), "F3: close is NOT the settlement"
        assert pd.isna(joined.loc[1, "settle"]), "no settlement -> NULL, never a close fallback"

    def test_ice_settle_is_the_close_with_null_open_interest(self):
        ohlcv, _ = T.build_ohlcv_bronze(
            _ohlcv([_bar("2026-07-20T22:00:00Z", 7, "KC  FMZ0026!", 3.0, pub=97)]),
            dataset=IFUS, root="KC", request_year=2026)
        out = T.apply_ice_settle(ohlcv)
        assert out["settle"].iloc[0] == pytest.approx(out["close"].iloc[0])
        assert pd.isna(out["open_interest"].iloc[0])


# ---------------------------------------------------------------------------
def _glbx_silver_bronze() -> pd.DataFrame:
    ohlcv, _ = T.build_ohlcv_bronze(
        _ohlcv([_bar("2016-03-01T00:00:00Z", 1, "ZCH6", 3.5525),
                _bar("2016-03-02T00:00:00Z", 1, "ZCH6", 3.5600)]),
        dataset=GLBX, root="ZC", request_year=2016)
    return T.join_glbx_statistics(ohlcv, None)


class TestSilverFrame:
    def test_column_order_is_the_contract_declaration_order(self):
        out = S.build_databento_eod_silver(_glbx_silver_bronze())
        assert list(out.columns) == S.SILVER_COLUMNS
        assert S.PHYSICAL_COLUMNS[:3] == ["trade_date", "contract_month", "instrument_kind"]
        assert S.PARTITION_COLUMNS == ["leviathan_slug", "trade_year"]

    def test_label_columns_are_map_derived(self):
        out = S.build_databento_eod_silver(_glbx_silver_bronze())
        rec = FC.contract_for("corn_cbot")
        for col in ("unit", "currency", "settle_kind", "source"):
            assert set(out[col]) == {rec[col]}
        assert set(out["instrument_kind"]) == {"futures"}
        assert out["contract_month"].notna().all()

    def test_ice_leg_carries_the_close_settle_kind_and_the_cad_canola_unit(self):
        ohlcv, _ = T.build_ohlcv_bronze(
            _ohlcv([_bar("2026-07-20T22:00:00Z", 9, "RS  FMX0026!", 6.5, pub=97)]),
            dataset=IFUS, root="RS", request_year=2026)
        out = S.build_databento_eod_silver(T.apply_ice_settle(ohlcv))
        assert out["settle_kind"].iloc[0] == "close"
        assert out["unit"].iloc[0] == "CAD/t" and out["currency"].iloc[0] == "CAD"

    def test_trade_year_is_a_real_int(self):
        out = S.build_databento_eod_silver(_glbx_silver_bronze())
        assert str(out["trade_year"].dtype) == "int64"
        assert set(out["trade_year"]) == {2016}

    def test_expiry_date_is_never_derived(self):
        out = S.build_databento_eod_silver(_glbx_silver_bronze())
        assert out["expiry_date"].isna().all()

    def test_non_databento_slug_is_refused(self):
        b = _glbx_silver_bronze()
        b["leviathan_slug"] = "french_wheat_matif"
        with pytest.raises(ValueError, match="not Databento-covered|not a Databento"):
            S.build_databento_eod_silver(b)

    def test_empty_in_empty_out(self):
        assert S.build_databento_eod_silver(pd.DataFrame()).empty


class TestPublishWiring:
    """The transform MUST reach S3 through build_partitioned_publish WITH lint_frame."""

    def _contract(self):
        from leviathan.silver.registry import load_registry
        return load_registry().table("silver_futures_eod")

    def _auth(self, contract):
        from leviathan.silver.flat_producer import authorize_for_contract
        return authorize_for_contract(contract, publish_mode="dry-run", env={})

    def test_plan_builds_offline_with_the_row_validator(self):
        from leviathan.silver.partitioned_producer import build_partitioned_publish

        contract = self._contract()
        df = S.build_databento_eod_silver(_glbx_silver_bronze())
        plan = build_partitioned_publish(
            df=df, contract=contract, auth=self._auth(contract), job="futures_eod_databento",
            partition_cols=["leviathan_slug", "trade_year"], s3_client=None,
            row_validator=FC.lint_frame)
        assert plan.partition_count == 1 and plan.row_count == len(df)
        # partition columns live in the PATH, never the body
        assert plan.staged[0].canonical_key.endswith(
            "leviathan_slug=corn_cbot/trade_year=2016/part-000.parquet")
        assert plan.staged[0].partition_values == ["corn_cbot", "2016"]

    def test_the_validator_is_what_rejects_a_dropped_delivery_month(self):
        # Only lint_frame can catch this: the F010 contract declares contract_month merely
        # nullable, so N such rows collapse to ONE natural key and duplicate_check cannot see it.
        from leviathan.silver.partitioned_producer import build_partitioned_publish

        contract = self._contract()
        df = S.build_databento_eod_silver(_glbx_silver_bronze())
        df["contract_month"] = None
        with pytest.raises(ValueError, match="NULL contract_month"):
            build_partitioned_publish(
                df=df, contract=contract, auth=self._auth(contract), job="futures_eod_databento",
                partition_cols=["leviathan_slug", "trade_year"], s3_client=None,
                row_validator=FC.lint_frame)

    def test_the_validator_rejects_a_guessed_unit(self):
        from leviathan.silver.partitioned_producer import build_partitioned_publish

        contract = self._contract()
        df = S.build_databento_eod_silver(_glbx_silver_bronze())
        df["unit"] = "USD/bushel"
        with pytest.raises(ValueError, match="do not match"):
            build_partitioned_publish(
                df=df, contract=contract, auth=self._auth(contract), job="futures_eod_databento",
                partition_cols=["leviathan_slug", "trade_year"], s3_client=None,
                row_validator=FC.lint_frame)

    def test_the_producer_task_wires_it(self):
        from pathlib import Path
        task = (Path(__file__).resolve().parents[2] / "jobs" / "batch" / "futures_eod_task.py")
        text = task.read_text(encoding="utf-8")
        assert "row_validator=FC.lint_frame" in text
        assert "build_partitioned_publish" in text


class TestStatisticsVocabularyPin:
    """The four stat constants are asserted by COMMENT everywhere else -- TestStatisticsJoin builds
    its fixtures FROM them, so it is self-consistent by construction and would not notice a
    renumbering. If StatType ever renumbers, build_statistics_bronze returns an EMPTY frame and
    every GLBX row lands settle=NULL under settle_kind='settlement' -- which gate 6's label
    cross-tab cannot see. Pinned against the installed package, which costs nothing."""

    def test_stat_type_values_match_the_installed_enum(self):
        dbn = pytest.importorskip("databento_dbn")
        assert T.STAT_TYPE_SETTLEMENT_PRICE == int(dbn.StatType.SETTLEMENT_PRICE)
        assert T.STAT_TYPE_OPEN_INTEREST == int(dbn.StatType.OPEN_INTEREST)

    def test_update_action_values_match_the_installed_enum(self):
        dbn = pytest.importorskip("databento_dbn")
        assert T.STAT_UPDATE_ACTION_NEW == int(dbn.StatUpdateAction.NEW)
        assert T.STAT_UPDATE_ACTION_DELETE == int(dbn.StatUpdateAction.DELETE)


class TestSymbologyFromArtifact:
    """The step-1 trap: parent->instrument_id maps EVERY instrument to the literal '<ROOT>.FUT'."""

    ART = {
        "window": {"start": "2026-01-01", "end_exclusive": "2027-01-01"},
        "resolve_step1": {"result": {"ZC.FUT": [{"d0": "2026-01-01", "d1": "2027-01-01",
                                                 "s": "42"}]},
                          "stype_in": "parent", "stype_out": "instrument_id"},
        "resolve_step2": [
            {"result": {"42": [{"d0": "2026-01-01", "d1": "2027-01-01", "s": "ZCZ6"}]}},
            {"result": {"43": [{"d0": "2026-01-01", "d1": "2027-01-01", "s": "ZCH6"}]}},
        ],
    }

    def test_merges_every_step2_chunk(self):
        out = T.symbology_from_artifact(self.ART)
        assert out["stype_in"] == "instrument_id" and out["stype_out"] == "raw_symbol"
        assert out["result"]["42"][0]["s"] == "ZCZ6"
        assert out["result"]["43"][0]["s"] == "ZCH6"
        assert set(out) == set(T.SYMBOLOGY_RESOLVE_KEYS)

    def test_never_returns_the_parent_mapping(self):
        out = T.symbology_from_artifact(self.ART)
        assert "ZC.FUT" not in out["result"]
        assert all(str(k).isdigit() for k in out["result"])

    def test_a_step1_only_artifact_yields_nothing(self):
        assert T.symbology_from_artifact({"resolve_step1": self.ART["resolve_step1"]}) is None
        assert T.symbology_from_artifact({}) is None
        assert T.symbology_from_artifact(None) is None

    def test_entries_with_no_symbol_are_skipped(self):
        art = {"resolve_step2": [{"result": {"42": [{"d0": "a", "d1": "b", "s": None}]}}]}
        assert T.symbology_from_artifact(art) is None


class TestStatisticsJoinCalendar:
    """A ts_ref-vs-ts_event skew leaves every GLBX row settle=NULL with no gate firing."""

    @staticmethod
    def _frames(shift_days: int):
        dates = pd.to_datetime(["2026-07-20", "2026-07-21", "2026-07-22"])
        bars = pd.DataFrame({"raw_symbol": "ZCZ6", "trade_date": dates})
        stats = pd.DataFrame({"raw_symbol": "ZCZ6",
                              "trade_date": dates + pd.Timedelta(days=shift_days)})
        return bars, stats

    def test_aligned_calendars_report_offset_zero(self):
        rec = T.statistics_join_diagnostics(*self._frames(0))
        assert rec["best_offset_days"] == 0
        assert rec["matched_at_zero"] == 3

    def test_a_systematic_one_day_skew_is_detected(self):
        # A contiguous run shifted by a day still overlaps in the middle, so the signal is not
        # "zero matched" -- it is that a NON-ZERO shift matches strictly more than zero does.
        rec = T.statistics_join_diagnostics(*self._frames(1))
        assert rec["best_offset_days"] == -1
        assert rec["overlap_by_offset"]["-1"] > rec["matched_at_zero"]

    def test_empty_inputs_are_inert(self):
        assert T.statistics_join_diagnostics(pd.DataFrame(), None)["best_offset_days"] is None


class TestGlbxSettleCoverage:
    def test_reports_the_non_null_fraction(self):
        df = pd.DataFrame({"settle": [1.0, np.nan, 3.0, 4.0],
                           "open_interest": pd.array([1, 2, None, 4], dtype="Int64")})
        rec = T.glbx_settle_coverage(df)
        assert rec["rows"] == 4 and rec["settle_nonnull"] == 3
        assert rec["settle_nonnull_frac"] == pytest.approx(0.75)
        assert rec["open_interest_nonnull_frac"] == pytest.approx(0.75)

    def test_an_empty_frame_is_inert(self):
        assert T.glbx_settle_coverage(pd.DataFrame())["settle_nonnull_frac"] is None


class TestRootCoverage:
    def test_sixteen_roots_all_mapped_into_contract_map(self):
        # 15 -> 16 (V2-4, 2026-09-02): CPO joined the GLBX block, and the loop below REQUIRES the
        # palm slug's CONTRACT_MAP source to be databento_glbx_mdp3 -- the Route B re-key.
        assert len(T.ROOT_MAP) == 16
        for root, (dataset, slug) in T.ROOT_MAP.items():
            assert dataset in T.DATASET_SLUGS
            assert slug in FC.CONTRACT_MAP
            assert FC.CONTRACT_MAP[slug]["source"] == f"databento_{T.DATASET_SLUGS[dataset]}"
        assert T.ROOT_MAP["CPO"] == (T.GLBX, "malaysian_crude_palm_oil_cme")

    def test_none_of_the_sixteen_is_a_cash_index(self):
        slugs = {slug for _r, (_d, slug) in T.ROOT_MAP.items()}
        assert not (slugs & FC.CASH_INDEX_SLUGS)

    def test_history_windows_match_the_plan(self):
        assert T.ROOT_FIRST_DATE["ZC"] == "2010-06-06"
        assert T.ROOT_FIRST_DATE["KE"] == "2014-01-01"
        assert T.ROOT_FIRST_DATE["KC"] == T.ROOT_FIRST_DATE["RC"] == "2018-12-23"
        # CPO opens at the 60-month regime, NOT the GLBX dataset first date (V2-4 M2: the tape has
        # a Jan-Jul 2016 hole and an unverified, id-recycled 24-month regime before it).
        assert T.ROOT_FIRST_DATE["CPO"] == "2016-08-01"
        assert T.SETTLEMENT_TAPE_ROOTS == frozenset({"CPO"})
        assert T.SETTLEMENT_TAPE_ROOTS <= set(T.ROOT_MAP)


class TestDbnDecodeLane:
    """The vendor lane, exercised only where the package is importable."""

    @staticmethod
    def _symbology_json(iid: str, sym: str) -> dict:
        """The ten keys databento's InstrumentMap.insert_json validates -- a missing one raises."""
        return {"result": {iid: [{"d0": "2026-01-01", "d1": "2027-01-01", "s": sym}]},
                "symbols": [iid], "stype_in": "instrument_id", "stype_out": "raw_symbol",
                "start_date": "2026-01-01", "end_date": "2027-01-01",
                "partial": [], "not_found": [], "message": "OK", "status": 0}

    def test_decode_round_trip(self):
        pytest.importorskip("databento")
        dbn = pytest.importorskip("databento_dbn")
        meta = dbn.Metadata(dataset="GLBX.MDP3", start=0, stype_in=dbn.SType.RAW_SYMBOL,
                            stype_out=dbn.SType.INSTRUMENT_ID, schema=dbn.Schema.OHLCV_1D,
                            symbols=["ZCZ6"], partial=[], not_found=[], mappings=[])
        assert meta.version == T.MAX_DBN_VERSION
        msg = dbn.OHLCVMsg(rtype=dbn.RType.OHLCV_1D, publisher_id=1, instrument_id=42,
                           ts_event=int(pd.Timestamp("2026-07-24", tz="UTC").value),
                           open=3552500000, high=3600000000, low=3500000000,
                           close=3575000000, volume=1234)
        raw = T.decode_dbn(bytes(meta.encode()) + bytes(msg), schema="ohlcv-1d",
                           symbology_json=self._symbology_json("42", "ZCZ6"))
        assert "symbol" in raw.columns
        out, _ = T.build_ohlcv_bronze(raw, dataset=GLBX, root="ZC", request_year=2026)
        assert len(out) == 1
        assert out["contract_month"].iloc[0] == "2026-12"
        # 1e-9 fixed point, applied exactly once by this module (price_type='fixed' decode).
        assert out["close"].iloc[0] == pytest.approx(3.575)
        assert out["low"].iloc[0] == pytest.approx(3.5)

    def test_decode_refuses_a_payload_with_no_symbol_mappings(self):
        pytest.importorskip("databento")
        dbn = pytest.importorskip("databento_dbn")
        meta = dbn.Metadata(dataset="GLBX.MDP3", start=0, stype_in=dbn.SType.RAW_SYMBOL,
                            stype_out=dbn.SType.INSTRUMENT_ID, schema=dbn.Schema.OHLCV_1D,
                            symbols=["ZCZ6"], partial=[], not_found=[], mappings=[])
        with pytest.raises(ValueError, match="no symbol mappings"):
            T.decode_dbn(bytes(meta.encode()), schema="ohlcv-1d")

    def test_decode_version_gate_is_a_ceiling_not_an_equality(self):
        # AMENDED 2026-07-29 on real purchased data: the vendor rendered every GLBX payload as
        # DBN v1 and every IFUS/IFEU payload as v3 in the SAME buy, and the installed client
        # NORMALIZES old versions on read (verified live: ZC/2016 v1 decoded to the plan's
        # measured bar count to the row, sane settlements and OI). So OLDER-than-max must
        # decode; NEWER-than-max must fail closed (a future struct layout is unknowable).
        pytest.importorskip("databento")
        dbn = pytest.importorskip("databento_dbn")
        meta = dbn.Metadata(dataset="GLBX.MDP3", start=0, stype_in=dbn.SType.RAW_SYMBOL,
                            stype_out=dbn.SType.INSTRUMENT_ID, schema=dbn.Schema.OHLCV_1D,
                            symbols=["ZCZ6"], partial=[], not_found=[], mappings=[])
        msg = dbn.OHLCVMsg(rtype=dbn.RType.OHLCV_1D, publisher_id=1, instrument_id=42,
                           ts_event=int(pd.Timestamp("2026-07-24", tz="UTC").value),
                           open=3552500000, high=3600000000, low=3500000000,
                           close=3575000000, volume=1234)
        # this file is v3; a ceiling of 1 makes it NEWER-than-max -> refused
        with pytest.raises(ValueError, match="NEWER than the installed client"):
            T.decode_dbn(bytes(meta.encode()) + bytes(msg), schema="ohlcv-1d",
                         symbology_json=self._symbology_json("42", "ZCZ6"),
                         max_version=1)
        # ...while the SAME bytes decode under a ceiling >= the file's version (the production
        # v1-under-v3 case, exercised here as v3-under-v5: older-or-equal always passes).
        raw = T.decode_dbn(bytes(meta.encode()) + bytes(msg), schema="ohlcv-1d",
                           symbology_json=self._symbology_json("42", "ZCZ6"),
                           max_version=5)
        assert len(raw) == 1


# ===========================================================================
# V2-4 (2026-09-02) -- CPO on the Databento lane: the settlement-spine bronze, the listing-
# interval-anchored decade decode, the horizon lint and the month-continuity census.
# ===========================================================================
_PROBE = __import__("pathlib").Path(__file__).resolve().parents[2] / "data" / "batch_runs" \
    / "cpo_databento_probe_20260902.json"


def _probe_years() -> dict[int, list[str]]:
    """``{year: outright symbols}`` from the committed $0 probe (the measured symbol sets)."""
    import json
    doc = json.loads(_PROBE.read_text(encoding="utf-8"))
    return {int(y["year"]): list(y.get("outrights") or []) for y in doc["years"]}


class TestListingIntervalDecade:
    """V2-4 M1: CPO terminates on the last CME business day of the month OR the first business
    day of the NEXT month, so CPOZ<d> resolves inside the next-year window and the bare
    download-year rule lifts it a decade (measured: 2017 CPOZ6 -> 2026-12). The fix anchors on
    the resolved listing interval for roots that DECLARE a horizon; the 7 live GLBX roots keep the
    shipped rule byte-for-byte."""

    LIFTED = {2017: "CPOZ6", 2019: "CPOZ8", 2020: "CPOZ9", 2021: "CPOZ0", 2022: "CPOZ1",
              2023: "CPOZ2", 2025: "CPOZ4", 2026: "CPOZ5"}

    def test_the_probe_s_december_straddlers_decode_to_the_prior_december(self):
        years = _probe_years()
        for year, sym in self.LIFTED.items():
            assert sym in years[year], f"{sym} is not in the probe window {year}"
            got = T.contract_month_str(sym, "CPO", GLBX, year)
            assert got == f"{year - 1}-12", f"{year} {sym} -> {got} (a decade lift?)"

    def test_every_probe_outright_decodes_inside_the_listing_horizon(self):
        """No symbol in any 2016+ window may land outside [Dec of year-1, Dec of year+5]."""
        for year, syms in _probe_years().items():
            if year < 2016:
                continue
            for sym in syms:
                cm = T.contract_month_str(sym, "CPO", GLBX, year)
                assert f"{year - 1}-12" <= cm <= f"{year + 5}-12", (year, sym, cm)

    def test_the_bare_rule_would_have_lifted_them(self):
        # The measurement the fix answers, kept as a witness: the shipped rule reads digit 6 in a
        # 2017 window as 2026.
        assert T.resolve_glbx_year(6, 2017) == 2026

    def test_a_symbol_s_own_d0_anchor_is_honoured(self):
        from datetime import date
        # CPOZ2 first listed in December 2017 (60 months out) decodes to 2022-12 on its own d0.
        assert T.contract_month_str("CPOZ2", "CPO", GLBX, 2017,
                                    anchor=date(2017, 12, 1)) == "2022-12"
        # ... and to the same month on the window-start fallback (the +12-month slack).
        assert T.contract_month_str("CPOZ2", "CPO", GLBX, 2017) == "2022-12"

    def test_an_impossible_symbol_fails_closed_rather_than_lifting(self):
        # CPOZ3 cannot be listed in the 2017 window (2023-12 is 71+ months past January 2017).
        with pytest.raises(ValueError, match="no decade candidate"):
            T.contract_month_str("CPOZ3", "CPO", GLBX, 2017)

    def test_the_seven_live_glbx_roots_keep_the_shipped_rule_byte_for_byte(self):
        assert "ZC" not in T.GLBX_LISTING_HORIZON_MONTHS
        assert T.contract_month_str("ZCH6", "ZC", GLBX, 2016) == "2016-03"
        assert T.contract_month_str("ZCH6", "ZC", GLBX, 2026) == "2026-03"
        # the shipped rule's own decade wrap is UNCHANGED for an undeclared root
        assert T.contract_month_str("ZCZ5", "ZC", GLBX, 2026) == "2035-12"

    def test_symbol_anchors_come_from_the_step2_chunks(self):
        from datetime import date
        art = {"resolve_step2": [{"result": {
            "42": [{"d0": "2017-01-01", "d1": "2017-01-04", "s": "CPOZ6"}],
            "43": [{"d0": "2017-12-04", "d1": None, "s": "CPOZ2"},
                   {"d0": "2017-06-01", "d1": "2017-09-01", "s": "CPOZ2"}]}}]}
        got = T.symbol_anchors_from_artifact(art)
        assert got == {"CPOZ6": date(2017, 1, 1), "CPOZ2": date(2017, 6, 1)}
        assert T.symbol_anchors_from_artifact(None) == {}


class TestSettlementSpine:
    """The V2-4 build item: the statistics stream IS the row skeleton for SETTLEMENT_TAPE_ROOTS."""

    @staticmethod
    def _stat(sym, iid, ts_recv, ts_ref, stat_type, *, price=None, qty=None, action=1, flags=0):
        return {"ts_recv": ts_recv, "ts_event": ts_recv, "rtype": 24, "publisher_id": 1,
                "instrument_id": iid, "ts_ref": ts_ref, "symbol": sym,
                "price": T.UNDEF_PRICE if price is None else int(round(price * SCALE)),
                "quantity": T.UNDEF_STAT_QUANTITY if qty is None else qty,
                "sequence": 0, "ts_in_delta": 0, "stat_type": stat_type, "channel_id": 65535,
                "update_action": action, "stat_flags": flags}

    def _frame(self) -> pd.DataFrame:
        s = self._stat
        return pd.DataFrame([
            s("CPOZ6", 42, "2017-01-03T20:00:00Z", "2017-01-03T00:00:00Z",
              T.STAT_TYPE_SETTLEMENT_PRICE, price=790.25, flags=8),
            s("CPOZ6", 42, "2017-01-03T20:00:00Z", "2017-01-03T00:00:00Z",
              T.STAT_TYPE_OPEN_INTEREST, qty=120),
            s("CPOF7", 43, "2017-01-03T20:00:00Z", "2017-01-03T00:00:00Z",
              T.STAT_TYPE_SETTLEMENT_PRICE, price=795.0),
            s("CPOF7", 43, "2017-01-04T20:00:00Z", "2017-01-04T00:00:00Z",
              T.STAT_TYPE_SETTLEMENT_PRICE, price=796.5),
            s("CPOF7", 43, "2017-01-04T20:00:00Z", "2017-01-04T00:00:00Z",
              T.STAT_TYPE_OPEN_INTEREST, qty=130),
            s("CPOZ1", 44, "2017-01-04T20:00:00Z", "2017-01-04T00:00:00Z",
              T.STAT_TYPE_SETTLEMENT_PRICE, price=810.0),
            # a settlement later RETRACTED -> no row for that key
            s("CPOZ1", 44, "2017-01-05T20:00:00Z", "2017-01-05T00:00:00Z",
              T.STAT_TYPE_SETTLEMENT_PRICE, price=811.0),
            s("CPOZ1", 44, "2017-01-05T22:00:00Z", "2017-01-05T00:00:00Z",
              T.STAT_TYPE_SETTLEMENT_PRICE, price=811.0, action=T.STAT_UPDATE_ACTION_DELETE),
            # the spread complex is dropped by the outright filter
            s("CPOF7-CPOG7", 99, "2017-01-04T20:00:00Z", "2017-01-04T00:00:00Z",
              T.STAT_TYPE_SETTLEMENT_PRICE, price=1.0),
        ])

    def test_membership(self):
        assert T.SETTLEMENT_TAPE_ROOTS == frozenset({"CPO"})
        assert T.SETTLEMENT_TAPE_ROOTS <= set(T.ROOT_MAP)
        assert T.GLBX_LISTING_HORIZON_MONTHS == {"CPO": 60}

    def test_keep_instrument_id_default_keeps_the_five_column_shape(self):
        five = T.build_statistics_bronze(self._frame(), root="CPO", request_year=2017)
        assert list(five.columns) == ["raw_symbol", "trade_date", "settle", "open_interest",
                                      "settle_flags"]
        six = T.build_statistics_bronze(self._frame(), root="CPO", request_year=2017,
                                        keep_instrument_id=True)
        assert list(six.columns) == list(five.columns) + ["instrument_id"]
        assert six.drop(columns=["instrument_id"]).equals(five)
        assert six["instrument_id"].tolist() == [43, 43, 44, 42]

    def test_rows_carry_settle_and_null_ohlcv_with_the_anchored_decode(self):
        stats = T.build_statistics_bronze(self._frame(), root="CPO", request_year=2017,
                                          keep_instrument_id=True)
        out, rec = T.build_settlement_bronze(stats, None, dataset=GLBX, root="CPO",
                                             request_year=2017)
        assert list(out.columns) == T.BRONZE_COLUMNS
        assert len(out) == 4 == rec["rows_out"] == rec["statistics_keys"]
        assert out["settle"].notna().all()
        for col in ("open", "high", "low", "close"):
            assert out[col].isna().all(), col
        assert out["volume"].isna().all() and out["publisher_id"].isna().all()
        assert str(out["volume"].dtype) == "Int64"
        by = out.set_index("raw_symbol")["contract_month"].to_dict()
        assert by["CPOZ6"] == "2016-12", "the December straddler: never 2026-12"
        assert by["CPOF7"] == "2017-01" and by["CPOZ1"] == "2021-12"
        assert set(out["leviathan_slug"]) == {"malaysian_crude_palm_oil_cme"}
        assert set(out["dataset"]) == {GLBX} and set(out["root"]) == {"CPO"}
        assert out.set_index(["raw_symbol", "trade_date"]).loc[
            ("CPOZ6", pd.Timestamp("2017-01-03")), "open_interest"] == 120
        assert out["instrument_id"].tolist() == [43, 43, 44, 42]
        assert rec["settlement_base"] is True and rec["bar_keys_attached"] == 0
        assert rec["horizon_months"] == 60 and rec["rows_beyond_horizon"] == 0
        assert rec["anchor_fallbacks"] == 3, \
            "no anchors supplied: every outright decoded on the window anchor, and that is COUNTED"

    def test_a_matching_bar_attaches_and_a_stray_bar_is_dropped(self):
        stats = T.build_statistics_bronze(self._frame(), root="CPO", request_year=2017,
                                          keep_instrument_id=True)
        bars, _ = T.build_ohlcv_bronze(_ohlcv([
            _bar("2017-01-03T00:00:00Z", 43, "CPOF7", 795.0, vol=3),
            _bar("2017-01-10T00:00:00Z", 43, "CPOF7", 799.0, vol=5),   # no settlement that day
        ]), dataset=GLBX, root="CPO", request_year=2017)
        out, rec = T.build_settlement_bronze(stats, bars, dataset=GLBX, root="CPO",
                                             request_year=2017)
        assert len(out) == 4, "the skeleton is the statistics keys; the stray bar adds no row"
        row = out.set_index(["raw_symbol", "trade_date"]).loc[("CPOF7", pd.Timestamp("2017-01-03"))]
        assert row["close"] == pytest.approx(795.0) and row["volume"] == 3
        assert row["settle"] == pytest.approx(795.0)
        assert rec["bar_keys_attached"] == 1 and rec["bars_without_settlement_dropped"] == 1
        assert out["close"].notna().sum() == 1, "every other row keeps OHLC NULL"

    def test_an_empty_statistics_frame_yields_zero_rows(self):
        out, rec = T.build_settlement_bronze(pd.DataFrame(), None, dataset=GLBX, root="CPO",
                                             request_year=2017)
        assert out.empty and list(out.columns) == T.BRONZE_COLUMNS and rec["rows_out"] == 0

    def test_a_non_member_root_is_refused(self):
        with pytest.raises(ValueError, match="not a settlement-tape root"):
            T.build_settlement_bronze(pd.DataFrame(), None, dataset=GLBX, root="ZC",
                                      request_year=2017)

    def test_anchor_fallbacks_are_counted_and_logged_for_a_horizon_declaring_root(self, caplog):
        """STEP-12 F10: a symbol without a resolved d0 decodes on the window anchor -- bounded by
        the decode window and linted by the horizon fence, but a degraded anchor is NAMED AND
        COUNTED in the unit record, never silent. A root with no declared horizon reports the
        count as ABSENT (None), not zero: the anchor is inert there."""
        import logging
        from datetime import date

        caplog.set_level(logging.INFO)
        stats = T.build_statistics_bronze(self._frame(), root="CPO", request_year=2017,
                                          keep_instrument_id=True)
        full = {"CPOZ6": date(2016, 12, 1), "CPOF7": date(2017, 1, 1), "CPOZ1": date(2017, 1, 4)}
        out, rec = T.build_settlement_bronze(stats, None, dataset=GLBX, root="CPO",
                                             request_year=2017, symbol_anchors=full)
        assert rec["anchor_fallbacks"] == 0 and "no resolved d0 anchor" not in caplog.text
        by = out.set_index("raw_symbol")["contract_month"].to_dict()
        assert by == {"CPOZ6": "2016-12", "CPOF7": "2017-01", "CPOZ1": "2021-12"}
        partial = {"CPOZ6": date(2016, 12, 1), "CPOF7": date(2017, 1, 1)}
        _o, rec = T.build_settlement_bronze(stats, None, dataset=GLBX, root="CPO",
                                            request_year=2017, symbol_anchors=partial)
        assert rec["anchor_fallbacks"] == 1
        assert ("databento settlement CPO/2017: 1 of 3 outright(s) carry no resolved d0 anchor"
                in caplog.text) and "CPOZ1" in caplog.text
        _o, rec = T.build_settlement_bronze(pd.DataFrame(), None, dataset=GLBX, root="CPO",
                                            request_year=2017)
        assert rec["anchor_fallbacks"] == 0
        # the bar leg of the same root counts the same way ...
        _b, rec = T.build_ohlcv_bronze(_ohlcv([
            _bar("2017-01-03T00:00:00Z", 43, "CPOF7", 795.0, vol=3)]),
            dataset=GLBX, root="CPO", request_year=2017)
        assert rec["anchor_fallbacks"] == 1
        # ... and a bar-driven root declares no horizon: absent, never zero
        _b, rec = T.build_ohlcv_bronze(_ohlcv([
            _bar("2017-01-03T00:00:00Z", 43, "ZCH7", 3.5, vol=3)]),
            dataset=GLBX, root="ZC", request_year=2017)
        assert rec["anchor_fallbacks"] is None
        _b, rec = T.build_ohlcv_bronze(T.empty_ohlcv_frame(), dataset=GLBX, root="ZC",
                                       request_year=2017)
        assert rec["anchor_fallbacks"] is None

    def test_the_horizon_lint_refuses_a_decade_lifted_row(self):
        bad = pd.DataFrame({"raw_symbol": ["CPOZ6"], "trade_date": pd.to_datetime(["2017-01-03"]),
                            "contract_month": ["2026-12"]})
        v = T.contract_horizon_violations(bad, "CPO")
        assert len(v) == 1 and int(v["months_ahead"].iloc[0]) == 119
        with pytest.raises(ValueError, match="outside the declared listing horizon"):
            T.lint_contract_horizon(bad, "CPO", label="x")
        ok = pd.DataFrame({"raw_symbol": ["CPOZ6", "CPOZ1"],
                           "trade_date": pd.to_datetime(["2017-01-03", "2017-01-03"]),
                           "contract_month": ["2016-12", "2021-12"]})
        assert T.contract_horizon_violations(ok, "CPO").empty
        T.lint_contract_horizon(ok, "CPO", label="x")
        # inert for a root with no declared horizon
        assert T.contract_horizon_violations(bad.assign(raw_symbol="ZCZ6"), "ZC").empty

    def test_empty_ohlcv_frame_passes_the_bar_builder_s_column_check(self):
        out, rec = T.build_ohlcv_bronze(T.empty_ohlcv_frame(), dataset=GLBX, root="CPO",
                                        request_year=2017)
        assert out.empty and rec["rows_out"] == 0

    def test_glbx_settle_coverage_reports_oi_keys_without_settle(self):
        df = pd.DataFrame({"settle": [1.0, np.nan, 3.0, np.nan],
                           "open_interest": pd.array([1, 2, None, None], dtype="Int64")})
        rec = T.glbx_settle_coverage(df)
        assert rec["oi_keys_without_settle"] == 1
        assert T.glbx_settle_coverage(pd.DataFrame())["oi_keys_without_settle"] is None


class TestMonthContinuity:
    """V2-4 M2: an internal hole in a banked span must never route to no_tape_rows silently."""

    def test_a_hole_names_the_missing_months(self):
        f = pd.DataFrame({"leviathan_slug": ["x"] * 4,
                          "trade_date": pd.to_datetime(["2016-08-02", "2016-09-01", "2016-11-03",
                                                        "2017-01-04"])})
        assert T.month_continuity_holes(f) == {"x": ["2016-10", "2016-12"]}

    def test_a_continuous_span_has_no_holes(self):
        f = pd.DataFrame({"leviathan_slug": ["x"] * 3,
                          "trade_date": pd.to_datetime(["2016-08-02", "2016-09-01", "2016-10-03"])})
        assert T.month_continuity_holes(f) == {}

    def test_non_adjacent_years_are_two_spans_not_one_hole(self):
        f = pd.DataFrame({"leviathan_slug": ["x"] * 3,
                          "trade_date": pd.to_datetime(["2016-12-30", "2018-01-04", "2018-02-01"])})
        assert T.month_continuity_holes(f) == {}

    def test_the_measured_cpo_hole_sits_outside_the_floor(self):
        # The 2015 window ends CPON6 (Jul 2016) and the 2016 window's first decoded month is
        # 2016-08: Jan..Jul 2016 resolve nothing. The root's first usable date is the answer.
        years = _probe_years()
        months_2016 = sorted({T.contract_month_str(s, "CPO", GLBX, 2016) for s in years[2016]})
        assert months_2016[0] == "2016-08"
        assert T.ROOT_FIRST_DATE["CPO"] == "2016-08-01"
        assert T.root_years("CPO", 2026) == list(range(2016, 2027))
        assert T.year_window("CPO", 2016) == ("2016-08-01", "2017-01-01")
        assert T.window_anchor("CPO", 2016).isoformat() == "2016-08-01"

    def test_an_empty_or_shapeless_frame_is_inert(self):
        assert T.month_continuity_holes(pd.DataFrame()) == {}
        assert T.month_continuity_holes(pd.DataFrame({"trade_date": [1]})) == {}
