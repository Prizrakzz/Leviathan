"""PRICE_AND_PLAYBOOKS W1c -- the DCE bronze -> ``silver_futures_eod`` projection.

The parse half lives in ``tests/unit/test_dce_eod.py`` and its fixtures are reused verbatim here
(one payload shape, one place -- the free-chain suite's idiom): the real 2026-07-29 daily quote body
and the real 2016 vendor history workbook, both captured live.

What this file is about is the ONE thing this leg's projection has that no other free leg's does:
TWO payload kinds landing in ONE series. The workbook covers the whole calendar year INCLUDING
sessions the daily capture already landed, so a contract-session can arrive twice, and the rule is
narrow on purpose --

  * IDENTICAL rows are the same observation read twice and collapse (keeping the last, which the
    task's history-first unit ordering makes the fresher post-close capture);
  * a REVISED row at the same natural key does NOT collapse. It reaches
    ``futures_eod_task.assert_no_duplicates`` and hard-fails the run, because silently picking one
    of two disagreeing settlements is the defect.

The collapse is measured on the PROJECTION and not on bronze, and that distinction is load-bearing:
the daily API publishes no turnover and no open-interest change, so a bronze-level comparison would
read every overlapping session as a conflict and fail the first backfill that met the forward feed.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest
from leviathan.silver import futures_eod_contracts as FC
from leviathan.transforms.bronze_to_silver import dce_eod as S
from leviathan.transforms.raw_to_bronze import dce_eod as T

_REPO = Path(__file__).resolve().parents[2]


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TASK = _load("jobs/batch/futures_eod_task.py", "futures_eod_task_dce_silver")
# The parse suite's fixtures and helpers -- settled_daily(), history_workbook(), the raw bytes.
_PARSE = _load("tests/unit/test_dce_eod.py", "dce_parse_suite")

_SESSION = pd.Timestamp("2026-07-30")          # the fixture body's OWN tradeDate (it rolled to T+1)


def daily_bronze(variety: str = "p", payload: bytes = None):
    """The settled daily board, as bronze. The fixture caught the night session, so the parse
    suite's ``settled_daily`` is what a post-close capture actually looks like."""
    return T.parse_dce_daily_json(payload or _PARSE.settled_daily(), variety=variety,
                                  as_of_date="2026-07-29")[0]


def restamped(variety: str) -> bytes:
    """The same board served for another VARIETY -- how the four soy contracts reach this leg.

    Only the contract code's variety letter moves; every price is the palm-olein capture's, which
    is exactly what a five-slug projection test needs and is never a claim about soy prices."""
    obj = json.loads(_PARSE.settled_daily().decode("utf-8"))
    for rec in obj["data"]:
        rec["contractId"] = variety + str(rec["contractId"])[1:]
    return json.dumps(obj).encode("utf-8")


def history_twin(daily: pd.DataFrame) -> pd.DataFrame:
    """The SAME contract-session as ``daily``, shaped as the YEAR WORKBOOK carries it.

    The workbook publishes two columns the daily endpoint does not -- ``oi_change`` and
    ``turnover`` -- and NEITHER is a contract column. That is the whole reason the overlap is
    resolved after the projection: on bronze these two rows differ, on silver they are identical."""
    twin = daily.copy()
    twin["oi_change"] = 123
    twin["turnover"] = 1.0e8
    return twin


def silver(*frames: pd.DataFrame) -> pd.DataFrame:
    return S.build_dce_eod_silver(pd.concat(list(frames), ignore_index=True))


# ---------------------------------------------------------------------------
class TestTheContractShape:
    def test_the_seventeen_physical_columns_plus_the_two_partition_keys(self):
        out = silver(daily_bronze())
        assert list(out.columns) == FC.SILVER_COLUMNS
        assert FC.PHYSICAL_COLUMNS + FC.PARTITION_COLUMNS == FC.SILVER_COLUMNS

    def test_the_row_validator_passes_on_every_projected_frame(self):
        """``lint_frame`` is the row_validator on EVERY publish -- it is not optional here."""
        assert FC.lint_frame(silver(daily_bronze())) == []

    def test_the_labels_are_map_derived_and_never_source_parsed(self):
        out = silver(daily_bronze())
        assert set(out["unit"]) == {"CNY/t"} and set(out["currency"]) == {"CNY"}
        assert set(out["settle_kind"]) == {"settlement"}
        assert set(out["source"]) == {"dce"}

    def test_every_row_is_a_futures_row_with_a_delivery_month(self):
        """A NULL month on a futures row collapses N natural keys to ONE, and SQL's
        duplicate_check cannot see it because every NULL is distinct."""
        out = silver(daily_bronze())
        assert set(out["instrument_kind"]) == {"futures"}
        assert out["contract_month"].notna().all()
        assert set(out["contract_month"]) >= {"2026-08", "2027-01"}

    def test_expiry_date_and_dataset_stay_null(self):
        out = silver(daily_bronze())
        assert out["expiry_date"].isna().all()
        assert out["dataset"].isna().all()

    def test_the_partition_year_is_the_sessions_own_year(self):
        out = silver(daily_bronze())
        assert set(out["trade_year"]) == {2026}
        assert (out["trade_year"] == out["trade_date"].dt.year).all()

    def test_the_dtypes_are_the_contract_dtypes(self):
        out = silver(daily_bronze())
        got = {c: str(t) for c, t in out.dtypes.items()}
        assert got["trade_date"] == "datetime64[us]" and got["expiry_date"] == "datetime64[us]"
        assert got["settle"] == got["open"] == got["close"] == "float64"
        assert got["volume"] == got["open_interest"] == "Int64"
        assert got["trade_year"] == "int64"
        assert got["contract_month"] == got["raw_symbol"] == "string"

    def test_an_empty_bronze_frame_is_an_empty_silver_frame_not_an_error(self):
        for empty in (None, pd.DataFrame()):
            out = S.build_dce_eod_silver(empty)
            assert len(out) == 0 and list(out.columns) == FC.SILVER_COLUMNS


# ---------------------------------------------------------------------------
class TestSourceFidelity:
    def test_settle_is_the_venues_settlement_and_the_close_is_the_close(self):
        """Neither is ever substituted for the other. The fixture's settled form sets both from
        lastPrice, so they are pulled apart here to prove the two columns are read separately."""
        obj = json.loads(_PARSE.settled_daily().decode("utf-8"))
        for rec in obj["data"]:
            rec["settlePrice"] = float(rec["lastPrice"]) + 1.0
        last = {str(r["contractId"]): float(r["lastPrice"]) for r in obj["data"]}["p2609"]
        out = silver(daily_bronze(payload=json.dumps(obj).encode("utf-8")))
        row = out[out["raw_symbol"] == "p2609"].iloc[0]
        assert float(row["close"]) == pytest.approx(last)            # closePrice == lastPrice
        assert float(row["settle"]) == pytest.approx(last + 1.0)     # settlePrice, pulled apart
        assert row["settle"] != row["close"]

    def test_the_session_shape_survives_cell_for_cell(self):
        out = silver(daily_bronze())
        row = out[out["raw_symbol"] == "p2609"].iloc[0]
        assert float(row["open"]) == pytest.approx(9400.0)
        assert float(row["high"]) == pytest.approx(9416.0)
        assert float(row["low"]) == pytest.approx(9348.0)
        assert int(row["volume"]) == 127012 and int(row["open_interest"]) == 365988

    def test_three_bronze_columns_are_dropped_and_that_is_declared(self):
        """prev_settle is the PRIOR session's settle and is already its own row (double-counting it
        is the MIAX Prev_Settle trap); oi_change and turnover have no contract column."""
        bronze = daily_bronze()
        for col in ("prev_settle", "oi_change", "turnover"):
            assert col in bronze.columns
            assert col not in FC.SILVER_COLUMNS
        assert set(silver(bronze).columns).isdisjoint({"prev_settle", "oi_change", "turnover"})

    def test_the_zero_sentinel_arrived_as_null_and_a_zero_count_survived(self):
        """The masking is BRONZE's and is not redone here -- what this pins is that the projection
        carries both halves of it through: NULL prices, and a 0 volume that stays 0 because it is
        the true observation that the contract did not trade."""
        grid = [["palm olein", "p1602", "20160104", "0", "0", "0", "4,732", "4,726", "4,732",
                 "6", "6", "0", "26", "0", "0"]]
        bronze, _ = T.parse_dce_history_xlsx(_PARSE.history_workbook(grid), variety="p")
        row = silver(bronze).iloc[0]
        assert pd.isna(row["open"]) and pd.isna(row["high"]) and pd.isna(row["low"])
        assert float(row["close"]) == pytest.approx(4732.0)
        assert float(row["settle"]) == pytest.approx(4732.0)
        assert int(row["volume"]) == 0 and not pd.isna(row["volume"])
        assert int(row["open_interest"]) == 26


# ---------------------------------------------------------------------------
class TestTheTwoPayloadSeam:
    """The daily captures and the history workbooks overlap in time BY CONSTRUCTION."""

    def test_an_identical_overlap_collapses_to_one_row_per_contract(self):
        daily = daily_bronze()
        out = silver(history_twin(daily), daily)                # history FIRST, as the task orders
        assert len(out) == len(daily) == 12
        assert out.groupby(["leviathan_slug", "contract_month", "trade_date"]).size().max() == 1

    def test_the_collapse_is_measured_on_what_is_PUBLISHED_not_on_bronze(self):
        """The daily endpoint publishes no turnover and no oi_change; the workbook publishes both.
        Compared as BRONZE the two rows differ on every overlapping session -- which would have
        hard-failed the first backfill that met the forward feed. Neither column is in the
        contract, so on the projection they are the same row."""
        daily = daily_bronze()
        twin = history_twin(daily)
        assert not twin[["oi_change", "turnover"]].equals(daily[["oi_change", "turnover"]])
        assert len(silver(twin, daily)) == 12

    def test_a_revised_overlap_is_NOT_collapsed_and_fails_the_uniqueness_assertion(self):
        """The whole point of the narrow rule: a corrected settlement is a real conflict, and
        picking one of two disagreeing numbers silently is the defect this refuses to commit."""
        daily = daily_bronze()
        revised = history_twin(daily)
        revised.loc[revised["raw_symbol"] == "p2608", "settle"] = 1.0
        out = silver(revised, daily)
        assert len(out) == 13                                   # the pair survived, uncollapsed
        with pytest.raises(ValueError, match="duplicate natural key"):
            TASK.assert_no_duplicates(out)

    def test_the_survivor_of_an_identical_pair_is_the_last_frame(self):
        """Identical rows make the survivor's identity moot by construction -- what is pinned here
        is the ORDER contract: the task lists history first so the fresher post-close daily capture
        is what keep='last' would retain the moment anything CAN differ."""
        daily = daily_bronze()
        out = silver(history_twin(daily), daily)
        assert out["settle"].notna().all()
        assert set(out["trade_date"]) == {_SESSION}

    def test_the_real_workbook_and_a_daily_capture_are_one_series(self):
        """The 2016 workbook (2,928 rows, every listed contract x every session) and the 2026 daily
        board, projected together -- two payload kinds, one slug, two year partitions."""
        hist, _ = T.parse_dce_history_xlsx(_PARSE.HISTORY_RAW, variety="p", year=2016)
        out = silver(hist, daily_bronze())
        assert len(out) == _PARSE.HISTORY_DATA_ROWS + 12
        assert set(out["leviathan_slug"]) == {"palm_olein_dce"}
        assert sorted(set(out["trade_year"])) == [2016, 2026]
        assert FC.lint_frame(out) == []
        TASK.assert_no_duplicates(out)


# ---------------------------------------------------------------------------
class TestTheFiveVarieties:
    def test_five_varieties_become_five_slugs_and_five_partitions(self):
        frames = [daily_bronze(v, restamped(v)) for v in sorted(T.DCE_VARIETY_MAP)]
        out = silver(*frames)
        assert set(out["leviathan_slug"]) == set(T.DCE_VARIETY_MAP.values())
        assert len(out) == 12 * 5
        assert out[FC.PARTITION_COLUMNS].drop_duplicates().shape[0] == 5
        assert FC.lint_frame(out) == []
        TASK.assert_no_duplicates(out)

    def test_a_slug_this_leg_does_not_own_is_refused(self):
        bronze = daily_bronze()
        bronze.loc[0, "leviathan_slug"] = "rapeseed_meal_zce"
        with pytest.raises(ValueError, match="not DCE contracts"):
            S.build_dce_eod_silver(bronze)

    def test_a_bronze_frame_missing_a_column_is_refused(self):
        with pytest.raises(ValueError, match="missing columns"):
            S.build_dce_eod_silver(daily_bronze().drop(columns=["settle"]))

    def test_a_null_session_would_orphan_the_partition_and_is_refused(self):
        bronze = daily_bronze()
        bronze.loc[0, "trade_date"] = pd.NaT
        with pytest.raises(ValueError, match="trade_year=nan"):
            S.build_dce_eod_silver(bronze)


# ---------------------------------------------------------------------------
class TestHostWiring:
    def test_the_task_dispatches_this_builder(self):
        assert TASK._silver_builder("dce") is S.build_dce_eod_silver

    def test_the_leg_is_implemented_and_its_floor_is_still_unarmed(self):
        """IMPLEMENTED is not ARMED. Only one of the five varieties has ever been captured live, so
        there is no measured whole-day minimum and any number here would be the F-C trap: a floor
        sitting between 'correct' and 'four varieties silently missing'."""
        spec = TASK.source_spec("dce")
        assert spec.implemented is True and spec.todo == ""
        assert spec.rows_per_day == 0
        assert TASK.assert_row_floor(silver(daily_bronze()), spec, mode="backfill") == []

    def test_build_silver_routes_the_source_through_the_projection(self):
        daily = daily_bronze()
        out = TASK.build_silver([history_twin(daily), daily], source="dce")
        assert list(out.columns) == FC.SILVER_COLUMNS and len(out) == 12
