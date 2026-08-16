"""The mode-aware truncated-download verdict (2026-08-01 RCA).

The first-ever incremental databento fire failed on the flat per-unit floor: ZR delivered 17 rows
(4 outrights x 5 sessions, settlement join 17/17 COMPLETE) and OJ 14 -- healthy thin markets, both
charged as truncated downloads because _MIN_ROWS_PER_UNIT=25 was calibrated on FULL-YEAR units
(thinnest legit year = ZR 2019 at 750 bars). The flat floor was simultaneously too weak for dense
roots in incremental: corn truncated to 2 of 5 days still cleared 25 rows. Vendor truncation cuts
WHOLE DAYS, it does not thin a complete book -- so incremental mode now checks DAY COVERAGE per
unit and backfill keeps the flat floor byte-identically.
"""
from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[3]


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TASK = _load("jobs/batch/futures_eod_task.py", "futures_eod_task_floor")
SPEC = TASK._SOURCE_SPECS["databento"]


def _frame(dates: list[str], rows_per_day: int) -> pd.DataFrame:
    recs = [{"trade_date": pd.Timestamp(d), "raw_symbol": f"S{i}"}
            for d in dates for i in range(rows_per_day)]
    return pd.DataFrame(recs)


def _window(n_weekdays: int) -> tuple[str, list[str]]:
    """since + the weekday sessions in [since, yesterday-UTC], mirroring main()'s computation."""
    end = datetime.now(tz=timezone.utc).date() - timedelta(days=1)
    days: list[str] = []
    cur = end
    while len(days) < n_weekdays:
        if cur.weekday() < 5:
            days.append(cur.isoformat())
        cur -= timedelta(days=1)
    return days[-1], sorted(days)


class TestIncrementalDayCoverage:
    def test_the_rca_shape_zr_17_rows_over_all_sessions_is_healthy(self):
        # 4 outrights x ~5 sessions ~ 17 rows -- under the old flat floor, over the day floor.
        since, days = _window(5)
        bronze = _frame(days, 4)[:17]
        assert TASK._truncation_error(bronze, SPEC, mode="incremental", since=since) is None

    def test_oj_thin_but_full_coverage_is_healthy(self):
        since, days = _window(5)
        bronze = _frame(days, 3)[:14]
        assert TASK._truncation_error(bronze, SPEC, mode="incremental", since=since) is None

    def test_one_missing_day_is_the_holiday_margin(self):
        since, days = _window(5)
        bronze = _frame(days[1:], 4)                     # 4 of 5 sessions -- a venue holiday
        assert TASK._truncation_error(bronze, SPEC, mode="incremental", since=since) is None

    def test_two_missing_days_is_a_truncated_download_even_when_dense(self):
        # The hole the flat floor MISSED: dense corn truncated to 2 of 5 days still cleared 25 rows.
        since, days = _window(5)
        bronze = _frame(days[:2], 13)                    # 26 rows -- old floor passes, coverage fails
        err = TASK._truncation_error(bronze, SPEC, mode="incremental", since=since)
        assert err is not None and "expected session(s) present" in err

    def test_empty_unit_is_truncated(self):
        since, _days = _window(5)
        bronze = _frame([], 0)
        assert TASK._truncation_error(bronze, SPEC, mode="incremental", since=since) is not None


class TestBackfillFloorUnchanged:
    def test_under_25_rows_still_fails(self):
        bronze = _frame(["2019-01-02"], 17)
        err = TASK._truncation_error(bronze, SPEC, mode="backfill", since=None)
        assert err is not None and "floor 25" in err

    def test_at_or_over_25_rows_passes(self):
        bronze = _frame(["2019-01-02", "2019-01-03"], 13)
        assert TASK._truncation_error(bronze, SPEC, mode="backfill", since=None) is None

    def test_sources_without_a_unit_floor_never_charge(self):
        czce = TASK._SOURCE_SPECS["czce"]
        assert TASK._truncation_error(_frame([], 0), czce, mode="incremental", since=None) is None


class TestExpectedLagSessions:
    """D-PR-16: window_end is the LAST SESSION THAT DATASET PUBLISHES TO, not a bare yesterday.

    Measured 2026-08-16 over four consecutive green fires: GLBX.MDP3 publishes through T-1, both
    ICE datasets through T-2. Before this the ICE legs sat at exactly present == expected - 1 on
    every fire, i.e. the one-holiday margin was consumed by structural lag and a single venue
    holiday would have false-failed all 8 ICE units."""

    def _lagged_window(self, n_weekdays: int, lag: int) -> tuple[str, list[str]]:
        """since + the sessions in [since, window_end] where window_end is `lag` weekdays back."""
        cur = datetime.now(tz=timezone.utc).date() - timedelta(days=1)
        stepped = 0
        while True:
            if cur.weekday() < 5:
                stepped += 1
                if stepped == lag:
                    break
            cur -= timedelta(days=1)
        days: list[str] = []
        while len(days) < n_weekdays:
            if cur.weekday() < 5:
                days.append(cur.isoformat())
            cur -= timedelta(days=1)
        return days[-1], sorted(days)

    def test_glbx_lag_one_is_byte_identical_to_the_old_window(self):
        # The regression fence: lag 1 must reproduce pre-D-PR-16 exactly.
        since, days = _window(5)
        bronze = _frame(days, 4)
        assert TASK._truncation_error(bronze, SPEC, mode="incremental", since=since,
                                      dataset=TASK.GLBX) is None
        assert TASK._truncation_error(bronze, SPEC, mode="incremental", since=since) is None

    def test_ice_us_full_coverage_at_lag_two_passes_with_the_margin_intact(self):
        # 4 of 4 ICE sessions present AND one more allowed to go missing -- the margin restored.
        since, days = self._lagged_window(4, 2)
        assert TASK._truncation_error(_frame(days, 5), SPEC, mode="incremental", since=since,
                                      dataset=TASK.IFUS) is None
        assert TASK._truncation_error(_frame(days[1:], 5), SPEC, mode="incremental", since=since,
                                      dataset=TASK.IFUS) is None

    def test_ice_europe_uses_the_same_lag_as_ice_us(self):
        since, days = self._lagged_window(4, 2)
        assert TASK._truncation_error(_frame(days, 5), SPEC, mode="incremental", since=since,
                                      dataset=TASK.IFEU) is None

    def test_ice_two_missing_sessions_is_still_a_truncated_download(self):
        # Anti-vacuity: the lag declaration must not turn the detector off.
        since, days = self._lagged_window(4, 2)
        err = TASK._truncation_error(_frame(days[:2], 13), SPEC, mode="incremental", since=since,
                                     dataset=TASK.IFUS)
        assert err is not None and "expected session(s) present" in err

    def test_the_measured_2026_08_lags_are_the_declared_ones(self):
        assert TASK._EXPECTED_LAG_SESSIONS == {TASK.GLBX: 1, TASK.IFUS: 2, TASK.IFEU: 2}

    def test_an_undeclared_dataset_falls_back_to_lag_one(self):
        since, days = _window(5)
        assert TASK._truncation_error(_frame(days, 4), SPEC, mode="incremental", since=since,
                                      dataset="NOT.A.DATASET") is None
