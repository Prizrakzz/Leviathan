"""DATA REPAIRS 0929 / FUT-1 + FUT-2 -- the price domain, the write guard and the declared failing share.

THE DEFECT THIS DECK HOLDS THE LINE ON (measured 2026-09-29 on a read-only copy of every canonical
partition of silver_futures_eod, 580,628 rows): 462 rows stored a 0 in settle / open / high / low /
close -- 219 of them a settle of 0.0 -- all on IFUS.IMPACT. The March-2026 cocoa row of 2026-01-12 read
open 5,330, high 5,455, low 0, close 0, settle 0 on 28,750 lots, and the served 63-session change on
July-2026 cocoa printed "+3,630, rising" for a contract that fell ~1,841. Nothing on the write path
fenced it: ``scale_fixed_price`` masks only the UNDEF sentinel, ``apply_ice_settle`` copies the close
into settle, ``lint_frame`` has no positivity rule.

WHAT IS PINNED: every contract DECLARES a price domain (complete against CONTRACT_MAP, fail closed);
the guard at the one write seam stores an out-of-domain price as NaN WITH A REASON and moves nothing
else (no row removed; volume and open interest never read for a decision -- a 0 there is real); the
guard runs after the canonical merge, so a stored zero is repaired by the next write; the reason is
carried across passes; the failing share is read from the table declaration, never typed in code;
the ICE zero-bar locator is a count, never a rule. Hermetic: no AWS.
"""
from __future__ import annotations

import copy
import importlib.util
import io
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
from leviathan.silver import futures_eod_contracts as FC
from leviathan.silver.partitioned_producer import build_partition_objects
from leviathan.silver.registry import load_registry
from leviathan.transforms.bronze_to_silver import databento_eod as S
from leviathan.transforms.raw_to_bronze import databento_eod as T

_REPO = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "futures_eod_task", _REPO / "jobs" / "batch" / "futures_eod_task.py")
T2 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(T2)

REASON = FC.PRICE_NULL_REASON_COLUMN


class FakeS3:
    def __init__(self, objects: dict | None = None):
        self.objects = dict(objects or {})

    def get_object(self, *, Bucket, Key):  # noqa: N803 -- boto3 kwarg casing
        if Key not in self.objects:
            raise KeyError(Key)
        data = self.objects[Key]

        class _Body:
            def read(self):
                return data

        return {"Body": _Body()}


def _contract() -> dict:
    return load_registry().table("silver_futures_eod")


def _contract_with_reason() -> dict:
    """The declaration as the generator renders it once ``additive_columns_hidden
    [("price_null_reason", "string")]`` is curated for silver_futures_eod: appended LAST, glue_type
    None (hidden from Glue until the gated ADD COLUMNS), target string, nullable."""
    c = copy.deepcopy(_contract())
    if REASON not in {p["name"] for p in c["physical_columns"]}:
        c["physical_columns"].append({"name": REASON, "glue_type": None, "arrow_type": None,
                                      "parquet_physical_type": None, "target_arrow_type": "string",
                                      "nullable": True})
    return c


def _cocoa_bronze(rows: list[dict]) -> pd.DataFrame:
    """ICE cocoa bronze rows (prices already scaled), settle := close as apply_ice_settle does."""
    base = {"leviathan_slug": "cocoa", "raw_symbol": "CC  FMH0026!", "contract_month": "2026-03",
            "instrument_id": 7, "publisher_id": 97, "volume": 100, "open_interest": pd.NA,
            "settle_flags": pd.NA, "dataset": T.IFUS, "root": "CC"}
    df = pd.DataFrame([{**base, **r} for r in rows])
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["settle"] = df["close"]
    df["open_interest"] = df["open_interest"].astype("Int64")
    df["settle_flags"] = df["settle_flags"].astype("Int64")
    df["volume"] = df["volume"].astype("Int64")
    return df


def _silver(rows: list[dict]) -> pd.DataFrame:
    return S.build_databento_eod_silver(_cocoa_bronze(rows))


# The census row itself: March-2026 cocoa on 2026-01-12, as stored.
_ZERO_BAR = {"trade_date": "2026-01-12", "open": 5330.0, "high": 5455.0, "low": 0.0, "close": 0.0,
             "volume": 28750}
_GOOD_BAR = {"trade_date": "2026-01-09", "open": 5400.0, "high": 5520.0, "low": 5380.0,
             "close": 5471.0, "volume": 25000}


# ---------------------------------------------------------------------------
class TestThePriceDomainIsDeclaredPerContract:
    def test_every_contract_declares_exactly_one_domain(self):
        assert set(FC.PRICE_DOMAIN) == set(FC.CONTRACT_MAP)
        assert set(FC.PRICE_DOMAIN.values()) <= FC.PRICE_DOMAINS
        assert FC.lint_price_domain() == []

    def test_a_contract_with_no_declared_domain_fails_closed(self, monkeypatch):
        monkeypatch.setitem(FC.CONTRACT_MAP, "new_contract_x", dict(FC.CONTRACT_MAP["cocoa"]))
        assert any("new_contract_x" in e for e in FC.lint_price_domain())
        frame = _silver([_GOOD_BAR]).assign(leviathan_slug="new_contract_x")
        with pytest.raises(ValueError, match="no declared PRICE_DOMAIN"):
            FC.guard_prices(frame)

    def test_the_domain_lives_outside_the_records(self):
        """lint_map refuses any extra record field and config_check binds the records by name, so
        the declaration is a sibling map -- the record shape is unchanged."""
        assert FC.lint_map() == []
        assert all(set(rec) == set(FC._REQUIRED_FIELDS) for rec in FC.CONTRACT_MAP.values())


# ---------------------------------------------------------------------------
class TestTheGuard:
    def test_the_census_bar_is_stored_missing_with_its_reason(self):
        out, rec = FC.guard_prices(_silver([_ZERO_BAR]))
        row = out.iloc[0]
        assert np.isnan(row["settle"]) and np.isnan(row["low"]) and np.isnan(row["close"])
        assert row["open"] == 5330.0 and row["high"] == 5455.0
        assert int(row["volume"]) == 28750
        assert row[REASON] == ("settle:nonpositive_value;low:nonpositive_value;"
                               "close:nonpositive_value")
        assert rec["rows_nulled"] == 1
        assert rec["cells_nulled"] == {"settle": {"nonpositive_value": 1},
                                       "low": {"nonpositive_value": 1},
                                       "close": {"nonpositive_value": 1}}
        assert rec["slug_days"] == [{"leviathan_slug": "cocoa", "trade_date": "2026-01-12",
                                     "rows": 1, "rows_nulled": 1, "share": 1.0}]

    def test_a_row_inside_its_domain_is_returned_bit_identical(self):
        before = _silver([_GOOD_BAR])
        out, rec = FC.guard_prices(before)
        for col in before.columns:
            assert out[col].equals(before[col]), col
        assert out[REASON].isna().all() and rec["rows_nulled"] == 0

    def test_no_row_is_removed_and_no_other_column_moves(self):
        before = _silver([_GOOD_BAR, _ZERO_BAR])
        out, _ = FC.guard_prices(before)
        assert len(out) == len(before) and out.index.equals(before.index)
        for col in before.columns:
            if col not in FC.PRICE_COLUMNS:
                assert out[col].equals(before[col]), col

    def test_volume_and_open_interest_zeros_and_nulls_are_never_touched(self):
        """T-FUT-2: 3,785 real volume zeros (CZCE, JSE) and 1,406 real open-interest zeros; the CPO
        tape carries volume NULL on every row. None of them is a price."""
        frame = _silver([_GOOD_BAR, _ZERO_BAR])
        frame["volume"] = pd.array([0, pd.NA], dtype="Int64")
        frame["open_interest"] = pd.array([0, pd.NA], dtype="Int64")
        out, _ = FC.guard_prices(frame)
        assert out["volume"].equals(frame["volume"])
        assert out["open_interest"].equals(frame["open_interest"])

    def test_a_value_missing_on_arrival_is_named_absent_on_arrival(self):
        frame = _silver([_GOOD_BAR])
        for col in ("open", "high", "low", "close"):
            frame[col] = np.nan
        out, rec = FC.guard_prices(frame)
        assert out[REASON].iloc[0] == ("open:absent_on_arrival;high:absent_on_arrival;"
                                       "low:absent_on_arrival;close:absent_on_arrival")
        assert rec["rows_nulled"] == 0, "the guard nulled nothing; it only named what arrived missing"

    def test_a_nonfinite_value_is_nulled_whatever_the_domain(self, monkeypatch):
        frame = _silver([_GOOD_BAR])
        frame.loc[0, "high"] = np.inf
        out, _ = FC.guard_prices(frame)
        assert np.isnan(out["high"].iloc[0]) and out[REASON].iloc[0] == "high:nonfinite_value"
        monkeypatch.setitem(FC.PRICE_DOMAIN, "cocoa", "signed")
        out, _ = FC.guard_prices(frame)
        assert np.isnan(out["high"].iloc[0])

    def test_a_signed_contract_keeps_a_negative_and_a_zero_settle(self, monkeypatch):
        """T-FUT-1: a market whose price can legitimately print at or below zero is ruled by ITS
        declaration, not by this code."""
        monkeypatch.setitem(FC.PRICE_DOMAIN, "cocoa", "signed")
        frame = _silver([_ZERO_BAR])
        frame.loc[0, "settle"] = -37.63
        out, rec = FC.guard_prices(frame)
        assert out["settle"].iloc[0] == -37.63 and out["close"].iloc[0] == 0.0
        assert rec["rows_nulled"] == 0 and pd.isna(out[REASON].iloc[0])

    def test_a_carried_reason_survives_a_second_pass(self):
        """The nightly re-reads a repaired prior (NaN + reason). Recomputing on the NaN alone would
        downgrade nonpositive_value to absent_on_arrival; the carried token wins."""
        once, _ = FC.guard_prices(_silver([_ZERO_BAR]))
        twice, rec2 = FC.guard_prices(once)
        assert twice[REASON].iloc[0] == once[REASON].iloc[0]
        assert rec2["rows_nulled"] == 0 and rec2["reason_tokens_carried"] == 3
        for col in once.columns:
            assert twice[col].equals(once[col]), col

    def test_a_token_follows_the_value_not_the_other_way_round(self):
        frame = _silver([_GOOD_BAR])
        frame[REASON] = "close:nonpositive_value"      # the close is present again
        out, _ = FC.guard_prices(frame)
        assert pd.isna(out[REASON].iloc[0])

    def test_a_malformed_token_fails_closed(self):
        frame = _silver([_GOOD_BAR])
        frame[REASON] = "close:guessed_origin"
        with pytest.raises(ValueError, match="guessed_origin"):
            FC.guard_prices(frame)

    def test_an_empty_frame_gains_the_column_and_nothing_else(self):
        out, rec = FC.guard_prices(S.build_databento_eod_silver(pd.DataFrame()))
        assert len(out) == 0 and REASON in out.columns and rec["rows"] == 0


# ---------------------------------------------------------------------------
class TestTheDeclaredFailingShare:
    """O-6: the share is DECLARED in the table declaration (range_rules.price_domain_guard, rendered
    by the generator) and never typed in code; absent -> the guard nulls and reports, it does not
    fail a run; malformed -> fail closed."""

    def test_no_declaration_means_no_share_to_fail_on(self):
        # today's declaration carries none; once the integrator renders one it must parse to exactly
        # the two declared facts (never a default filled in by code)
        rule = FC.price_guard_rule(_contract())
        assert rule is None or set(rule) == {"denominator", "max_nulled_share"}
        assert FC.price_guard_rule({}) is None
        assert FC.price_guard_breaches({"rows": 10, "rows_nulled": 10}, None) == []

    @pytest.mark.parametrize("rule", [
        {"denominator": "slug_week", "max_nulled_share": 0.5},
        {"denominator": "slug_day", "max_nulled_share": 0},
        {"denominator": "slug_day", "max_nulled_share": 1.5},
        {"denominator": "slug_day", "max_nulled_share": True},
        "0.75",
    ])
    def test_a_malformed_declaration_fails_closed(self, rule):
        with pytest.raises(ValueError):
            FC.price_guard_rule({"range_rules": {"price_domain_guard": rule}})

    def test_each_denominator_names_the_group_it_judges(self):
        # five of ten cocoa rows on 2026-01-12 carried a zero (the census day)
        rows = [dict(_ZERO_BAR, contract_month=m) for m in ("2026-03", "2026-05", "2026-07",
                                                             "2026-09", "2026-12")]
        rows += [dict(_GOOD_BAR, trade_date="2026-01-12", contract_month=m)
                 for m in ("2027-03", "2027-05", "2027-07", "2027-09", "2027-12")]
        bronze = _cocoa_bronze(rows)
        bronze["contract_month"] = [r["contract_month"] for r in rows]
        bronze["raw_symbol"] = [f"CC  FM{i}!" for i in range(len(rows))]
        _, rec = FC.guard_prices(S.build_databento_eod_silver(bronze))
        day = {"denominator": "slug_day", "max_nulled_share": 0.4}
        assert FC.price_guard_breaches(rec, day) == [
            "cocoa 2026-01-12: 5 of 10 rows (0.5000 > 0.4)"]
        assert FC.price_guard_breaches(rec, dict(day, max_nulled_share=0.75)) == []
        assert FC.price_guard_breaches(rec, {"denominator": "slug", "max_nulled_share": 0.4})
        assert FC.price_guard_breaches(rec, {"denominator": "run", "max_nulled_share": 0.5}) == []


# ---------------------------------------------------------------------------
class TestTheWriteSeam:
    def test_the_seam_stages_the_reason_only_where_the_declaration_carries_it(self):
        assert T2.write_columns(_contract_with_reason()) == FC.SILVER_COLUMNS + [REASON]
        today = _contract()
        declared = {p["name"] for p in today["physical_columns"]}
        assert T2.write_columns(today) == FC.SILVER_COLUMNS + (
            [REASON] if REASON in declared else [])

    @pytest.mark.parametrize("with_reason", [False, True])
    def test_a_zero_never_reaches_the_staged_bytes(self, with_reason):
        contract = _contract_with_reason() if with_reason else copy.deepcopy(_contract())
        if not with_reason:
            contract["physical_columns"] = [p for p in contract["physical_columns"]
                                            if p["name"] != REASON]
        guarded, _ = T2.guard_for_write(_silver([_GOOD_BAR, _ZERO_BAR]), contract)
        objs = build_partition_objects(guarded, contract, partition_cols=T2._PARTITION_COLS)
        body = pq.read_table(io.BytesIO(objs[0].body)).to_pandas()
        z = body[body["trade_date"] == pd.Timestamp("2026-01-12")].iloc[0]
        assert np.isnan(z["settle"]) and np.isnan(z["close"]) and np.isnan(z["low"])
        assert (REASON in body.columns) is with_reason
        assert list(body.columns)[:len(FC.PHYSICAL_COLUMNS)] == FC.PHYSICAL_COLUMNS

    def test_a_declared_share_above_its_cap_refuses_the_write(self):
        contract = _contract_with_reason()
        contract["range_rules"] = {"price_domain_guard": {"denominator": "slug_day",
                                                          "max_nulled_share": 0.75}}
        with pytest.raises(ValueError, match="cocoa 2026-01-12"):
            T2.guard_for_write(_silver([_ZERO_BAR]), contract)
        # the same frame under a looser declaration writes (1 of 1 is not ABOVE 1.0)
        contract["range_rules"]["price_domain_guard"]["max_nulled_share"] = 1.0
        T2.guard_for_write(_silver([_ZERO_BAR]), contract)

    def test_publish_goes_through_the_guard_and_keeps_the_row_validator(self, monkeypatch):
        seen = {}

        def _capture(**kw):
            seen.update(kw)

            class _Plan:
                partition_count = 1
                row_count = len(kw["df"])

                @staticmethod
                def run():
                    return "manifest"
            return _Plan()

        monkeypatch.setattr(T2, "build_partitioned_publish", _capture)
        out = T2.publish(_silver([_ZERO_BAR]), _contract(), auth=None, s3_client=None,
                         glue_client=None)
        assert out == "manifest"
        assert np.isnan(seen["df"]["settle"].iloc[0])
        assert seen["row_validator"] is FC.lint_frame
        src = (_REPO / "jobs" / "batch" / "futures_eod_task.py").read_text(encoding="utf-8")
        assert "row_validator=FC.lint_frame" in src     # gate 8's literal wiring check

    def test_a_canonical_prior_carrying_a_zero_is_repaired_by_the_incremental_pass(self):
        """T-FUT-3: the nightly unions canonical priors UNCHANGED; a guard before the merge would
        leave the 19 stored cocoa zeros of 2026 in place forever."""
        contract = _contract_with_reason()
        prior = _silver([_ZERO_BAR])
        prior17 = prior.copy()
        objs = build_partition_objects(prior17, _contract(), partition_cols=T2._PARTITION_COLS)
        s3 = FakeS3({objs[0].canonical_key: objs[0].body})       # a 17-column canonical object
        fresh = _silver([dict(_GOOD_BAR, trade_date="2026-01-13")])
        merged, rec = T2.merge_with_canonical(fresh, contract, s3)
        assert rec["partitions_merged"] == 1 and list(merged.columns) == T2.write_columns(contract)
        guarded, grec = T2.guard_for_write(merged, contract)
        old = guarded[guarded["trade_date"] == pd.Timestamp("2026-01-12")].iloc[0]
        assert np.isnan(old["settle"]) and old[REASON].startswith("settle:nonpositive_value")
        assert grec["rows_nulled"] == 1

    def test_the_merge_tolerates_exactly_the_write_seam_column(self):
        """T-FUT-4: every stored partition lacks the new column (tolerated, filled); a repaired
        partition carries it (tolerated, carried); any other drift is still refused."""
        contract = _contract_with_reason()
        once, _ = T2.guard_for_write(_silver([_ZERO_BAR]), contract)
        objs = build_partition_objects(once, contract, partition_cols=T2._PARTITION_COLS)
        key = objs[0].canonical_key
        merged, _ = T2.merge_with_canonical(_silver([dict(_GOOD_BAR, trade_date="2026-01-13")]),
                                            contract, FakeS3({key: objs[0].body}))
        carried = merged[merged["trade_date"] == pd.Timestamp("2026-01-12")][REASON].iloc[0]
        assert carried == once[REASON].iloc[0]

        import pyarrow as pa
        odd = pq.read_table(io.BytesIO(objs[0].body)).to_pandas().assign(extra_col=1)
        buf = io.BytesIO()
        pq.write_table(pa.Table.from_pandas(odd, preserve_index=False), buf)
        with pytest.raises(ValueError, match="does not carry the contract shape"):
            T2.merge_with_canonical(_silver([_GOOD_BAR]), contract, FakeS3({key: buf.getvalue()}))
        # a declaration WITHOUT the column refuses a prior that carries it (never silently dropped)
        with pytest.raises(ValueError, match="does not carry the contract shape"):
            bare = copy.deepcopy(_contract())
            bare["physical_columns"] = [p for p in bare["physical_columns"] if p["name"] != REASON]
            T2.merge_with_canonical(_silver([_GOOD_BAR]), bare, FakeS3({key: objs[0].body}))


# ---------------------------------------------------------------------------
class TestTheReguardRepair:
    """FUT-3: the stored rows are repaired by writing the NAMED canonical objects back through the
    guard -- no raw read, no re-derivation, so only the out-of-domain prices can move, the partition
    cannot shrink, and a current-year partition is never truncated to a backfill payload (N-8)."""

    @staticmethod
    def _store(frame: pd.DataFrame, contract: dict) -> tuple[str, FakeS3]:
        objs = build_partition_objects(frame, contract, partition_cols=T2._PARTITION_COLS)
        return objs[0].canonical_key, FakeS3({objs[0].canonical_key: objs[0].body})

    def test_the_partition_argument_is_a_mapped_slug_and_a_year(self):
        assert T2.parse_reguard_partition("cocoa/2022") == ("cocoa", 2022)
        for bad in ("cocoa", "cocoa/22", "not_a_slug/2022", "cocoa/20x2"):
            with pytest.raises(ValueError):
                T2.parse_reguard_partition(bad)

    def test_a_stored_partition_is_read_whole_and_only_its_zeros_move(self):
        stored = _silver([_GOOD_BAR, _ZERO_BAR])
        _key, s3 = self._store(stored, _contract())            # a 17-column object, as today
        contract = _contract_with_reason()
        df, rec = T2.read_canonical_partitions([("cocoa", 2026)], contract, s3)
        assert rec["rows_by_partition"] == {"cocoa/2026": 2}
        guarded, grec = T2.guard_for_write(df, contract)
        assert len(guarded) == len(stored) and grec["rows_nulled"] == 1
        good = guarded[guarded["trade_date"] == pd.Timestamp("2026-01-09")].iloc[0]
        assert pd.isna(good[REASON]) and good["settle"] == 5471.0

    def test_a_missing_object_is_an_error_never_a_skip(self):
        with pytest.raises(FileNotFoundError, match="never creates one"):
            T2.read_canonical_partitions([("cocoa", 2031)], _contract(), FakeS3())
        with pytest.raises(ValueError, match="at least one"):
            T2.read_canonical_partitions([], _contract(), FakeS3())

    def test_main_reguard_publishes_the_guarded_object_and_nothing_else(self, monkeypatch):
        stored = _silver([_GOOD_BAR, _ZERO_BAR])
        _key, s3 = self._store(stored, _contract())
        seen = {}

        def _capture(**kw):
            seen.update(kw)

            class _Plan:
                partition_count = 1
                row_count = len(kw["df"])

                @staticmethod
                def run():
                    class _M:
                        class state:  # noqa: N801 -- mirrors ManifestState
                            value = "VALIDATED"
                    return _M()
            return _Plan()

        monkeypatch.setattr(T2, "build_partitioned_publish", _capture)
        monkeypatch.setattr(T2, "get_thread_local_s3_client", lambda _region: s3)
        monkeypatch.setattr(T2, "preflight", lambda _spec: True)
        monkeypatch.setattr(T2, "select_units", lambda *a, **k: pytest.fail("reguard loads no unit"))
        rc = T2.main(["--mode", "reguard", "--partition", "cocoa/2026", "--bucket", "b",
                      "--aws-region", "us-east-1"])
        assert rc == 0
        assert len(seen["df"]) == 2 and seen["df"]["settle"].isna().sum() == 1
        assert seen["row_validator"] is FC.lint_frame

    def test_the_partition_flag_is_refused_outside_reguard(self, monkeypatch):
        monkeypatch.setattr(T2, "get_thread_local_s3_client", lambda _region: FakeS3())
        monkeypatch.setattr(T2, "preflight", lambda _spec: True)
        assert T2.main(["--mode", "backfill", "--partition", "cocoa/2026", "--bucket", "b",
                        "--aws-region", "us-east-1"]) == 1
        assert T2.main(["--mode", "reguard", "--bucket", "b", "--aws-region", "us-east-1"]) == 1


# ---------------------------------------------------------------------------
class TestTheZeroBarLocator:
    """FUT-1 'where the zero enters': ICE prints two bars per (symbol, day) -- the venue's and the
    off-exchange XOFF -- and the dedupe keeps the venue's. The locator COUNTS, on the next run from
    raw, whether a kept bar carrying a price <= 0 had a fully positive twin. It never changes a row."""

    @staticmethod
    def _raw(venue: dict, xoff: dict) -> pd.DataFrame:
        s = T.FIXED_PRICE_SCALE
        ts = pd.Timestamp("2026-01-12 23:00", tz="UTC")
        rows = []
        for pub, bar in ((97, venue), (98, xoff)):
            rows.append({"ts_event": ts, "instrument_id": 1, "symbol": "CC  FMH0026!",
                         "open": int(bar["open"] * s), "high": int(bar["high"] * s),
                         "low": int(bar["low"] * s), "close": int(bar["close"] * s),
                         "volume": bar["volume"], "publisher_id": pub})
        return pd.DataFrame(rows)

    def test_a_kept_zero_bar_with_a_positive_twin_is_counted_and_left_alone(self):
        raw = self._raw(_ZERO_BAR, dict(_GOOD_BAR, volume=12))
        bronze, stats = T.build_ohlcv_bronze(raw, dataset=T.IFUS, root="CC", request_year=2026)
        loc = stats["nonpositive_bars"]
        assert loc["bars_in"] == 2 and loc["bars_in_nonpositive"] == 1
        assert loc["bars_kept_nonpositive"] == 1
        assert loc["bars_kept_nonpositive_with_positive_twin"] == 1
        assert len(bronze) == 1 and bronze["close"].iloc[0] == 0.0, \
            "the locator counts; the guard at the write nulls"
        assert loc["examples"][0]["kept_publisher_id"] == 97
        assert loc["examples"][0]["twin_publisher_id"] == 98

    def test_a_clean_unit_reports_zeros(self):
        raw = self._raw(_GOOD_BAR, _GOOD_BAR)
        _, stats = T.build_ohlcv_bronze(raw, dataset=T.IFUS, root="CC", request_year=2026)
        loc = stats["nonpositive_bars"]
        assert loc["bars_in_nonpositive"] == 0 and loc["bars_kept_nonpositive"] == 0
        assert loc["examples"] == []
