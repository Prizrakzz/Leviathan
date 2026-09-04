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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

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


class TestVenueCalendar:
    """LANE A / A-1 + A-3 -- the venue no-settlement calendar inside the session floor.

    THE MEASURED INCIDENT. On 2026-09-02 and 2026-09-03 the 08:00Z databento chain lost its GATE
    and its PROMOTE for all 16 boards on an IFEU verdict. ``pd.bdate_range`` is freq ``B`` --
    Mon-Fri, no holiday awareness -- and 2026-08-31 is a Monday
    (``date.fromisoformat('2026-08-31').strftime('%a')`` -> ``Mon``), the last Monday of August,
    ICE Europe closed, sitting inside the 5-day window of the 09-02, 09-03, 09-04 and 09-05 fires.

    THE QUESTION THIS CLASS COVERS BOTH SIDES OF, AND WHICH SIDE THE BANKED LOGS LANDED ON. The
    production lines read ``only 1 of 3 expected session(s) present (window
    2026-08-28..2026-09-01)`` on the 09-02 fire. That window ends at T-1 over 3 weekdays: the LAG 1
    arithmetic. The committed code declares IFEU lag 2, under which the same fire scores expected
    2, present 1 and PASSES on the margin. The 09-04 fire then passed with IFEU holding 2 sessions,
    which lag 1 would have red-ed and lag 2 does not -- so the resolved lag CHANGED between the
    fires (the 2026-09-03 r2 repin), and the surviving reading is image drift, not a code path.
    ``TestFixPassSessionFloor`` below carries that settlement as pins.

    The parametrisation here still covers BOTH readings, because the calendar is the structural
    answer under either: at lag 1 the entry flips the measured red to green; at lag 2 the fire sits
    at ``present == expected - 1``, i.e. the one-holiday margin fully consumed, which is exactly
    the state D-PR-16 refused to leave the leg in -- the NEXT absence of any kind, for any reason,
    false-reds all 8 ICE units.
    """

    _FIRE_LAG1 = ("2026-09-03", 1, "2026-08-29", 3, 1, 2)
    _FIRE_LAG2 = ("2026-09-05", 2, "2026-08-31", 4, 2, 3)

    @staticmethod
    def _freeze(monkeypatch, fire: str):
        """Pin ``datetime.now(tz=utc)`` inside the task to an 08:00Z fire date."""
        fixed = datetime.fromisoformat(fire + "T08:00:00+00:00")

        class _DT(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed

        monkeypatch.setattr(TASK, "datetime", _DT)

    @staticmethod
    def _calendar(monkeypatch, tmp_path, declared: dict):
        """Point the calendar leaf at a fixture file. ``{dataset: [iso day, ...]}``."""
        import yaml
        from leviathan.silver import venue_calendar as VC

        doc: dict = {"version": 1, "datasets": {}}
        for dataset, days in declared.items():
            by_year: dict = {}
            for day in days:
                by_year.setdefault(int(day[:4]), []).append(day)
            doc["datasets"][dataset] = {
                "venue": "fixture", "source_url": "https://example.invalid/cal",
                "years": {year: {"complete": True, "verified_on": "2026-09-04",
                                 "verified_by": "fixture",
                                 "holidays": [{"day": d, "name": "a named closure",
                                               "basis": "published"} for d in sorted(ds)]}
                          for year, ds in by_year.items()},
            }
        path = tmp_path / "venue_holidays.yaml"
        path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
        monkeypatch.setattr(VC, "VENUE_HOLIDAYS_PATH", path)
        VC.load_venue_holidays.cache_clear()
        monkeypatch.delenv("LEVIATHAN_VENUE_CALENDAR", raising=False)
        return path

    @staticmethod
    def _off(monkeypatch):
        monkeypatch.setenv("LEVIATHAN_VENUE_CALENDAR", "off")

    def _verdict(self, dates, since, dataset):
        return TASK._truncation_error(_frame(list(dates), 5), SPEC, mode="incremental",
                                      since=since, dataset=dataset)

    @pytest.fixture(autouse=True)
    def _cold_cache(self):
        from leviathan.silver import venue_calendar as VC
        VC.load_venue_holidays.cache_clear()
        yield
        VC.load_venue_holidays.cache_clear()

    @pytest.mark.parametrize("fire,lag,since,weekdays,present_n,real",
                             [_FIRE_LAG1, _FIRE_LAG2], ids=["lag1-reading", "lag2-reading"])
    def test_the_2026_08_31_ice_europe_case_fails_without_the_calendar_and_passes_with_it(
            self, monkeypatch, tmp_path, fire, lag, since, weekdays, present_n, real):
        """THE HEADLINE FAIL-THEN-PASS PIN, on the date that actually broke the chain.

        Same frame, same window, same margin, same lag -- only the declared calendar differs. The
        assertion is on the EXPECTED NUMBER in the message, because that number is the whole
        difference: without the calendar a UK bank holiday is counted as a session ICE Europe owed
        us. In the lag-1 reading the message reproduced here is character-for-character the one
        production logged: ``only 1 of 3 expected session(s) present (window
        2026-08-29..2026-09-02)``.
        """
        monkeypatch.setattr(TASK, "_EXPECTED_LAG_SESSIONS", {TASK.IFEU: lag})
        self._freeze(monkeypatch, fire)
        # the window's weekday sessions, of which 2026-08-31 is the one ICE Europe did not publish
        sessions = [d.date().isoformat()
                    for d in pd.bdate_range(since, pd.Timestamp(fire) - pd.Timedelta(days=lag))]
        assert len(sessions) == weekdays and "2026-08-31" in sessions, sessions
        held = [d for d in sessions if d != "2026-08-31"][-present_n:]
        assert len(held) == present_n

        self._off(monkeypatch)
        err = self._verdict(held, since, TASK.IFEU)
        assert err is not None, "the pre-Lane-A arithmetic charges the holiday as a lost session"
        assert ("only %d of %d expected session(s) present" % (present_n, weekdays)) in err
        assert ("window %s..%s" % (since, sessions[-1])) in err

        self._calendar(monkeypatch, tmp_path, {TASK.IFEU: ["2026-08-31"]})
        assert self._verdict(held, since, TASK.IFEU) is None, (
            "with 2026-08-31 declared the real count is %d, and %d of %d is inside the window"
            % (real, present_n, real))

    def test_the_declaration_is_scoped_to_the_venue_that_closed(self, monkeypatch, tmp_path):
        """2026-08-31 is a UK bank holiday. CME and ICE US both settled that Monday, so declaring
        it against GLBX or IFUS would silently delete a real expected session from two venues that
        were open -- a mis-inferred floor with a US-shaped blast radius."""
        monkeypatch.setattr(TASK, "_EXPECTED_LAG_SESSIONS", {TASK.IFEU: 1, TASK.IFUS: 1})
        self._freeze(monkeypatch, "2026-09-03")
        self._calendar(monkeypatch, tmp_path, {TASK.IFEU: ["2026-08-31"]})
        held = ["2026-09-01"]
        assert self._verdict(held, "2026-08-29", TASK.IFEU) is None
        for other in (TASK.GLBX, TASK.IFUS):
            err = self._verdict(held, "2026-08-29", other)
            assert err is not None and "of 3 expected" in err, other

    def test_a_us_holiday_inside_a_glbx_window_no_longer_reds_corn(self, monkeypatch, tmp_path):
        """The GLBX half. Window 2026-07-03..2026-07-07 carries 3 weekdays; Independence Day 2026
        falls on SATURDAY 07-04, so the observed no-settlement date is Friday 2026-07-03."""
        self._freeze(monkeypatch, "2026-07-08")
        held = ["2026-07-06"]
        self._off(monkeypatch)
        err = self._verdict(held, "2026-07-03", TASK.GLBX)
        assert err is not None and "only 1 of 3 expected session(s) present" in err

        self._calendar(monkeypatch, tmp_path, {TASK.GLBX: ["2026-07-03"]})
        assert self._verdict(held, "2026-07-03", TASK.GLBX) is None

    def test_a_holiday_dated_on_a_weekend_subtracts_nothing(self, monkeypatch, tmp_path):
        """The arithmetic iterates a WEEKDAY range, so a Saturday entry is inert rather than a
        silent -1. This is why the YAML must carry the OBSERVED date (Fri 2026-07-03), not the
        nominal one (Sat 2026-07-04)."""
        self._freeze(monkeypatch, "2026-07-08")
        assert date.fromisoformat("2026-07-04").weekday() == 5, "the fixture's premise"
        self._calendar(monkeypatch, tmp_path, {TASK.GLBX: ["2026-07-04"]})
        err = self._verdict(["2026-07-06"], "2026-07-03", TASK.GLBX)
        assert err is not None and "only 1 of 3 expected session(s) present" in err

    def test_a_holiday_free_glbx_window_is_byte_identical_to_the_pre_calendar_verdict(
            self, monkeypatch, tmp_path):
        """THE REGRESSION FENCE. Over a grid of frames on a window carrying no declared GLBX date,
        the verdict STRING with the calendar on must equal the verdict string with it off. Not
        "both fail" -- the same characters, counts included."""
        self._freeze(monkeypatch, "2026-07-08")
        grid = [[], ["2026-07-07"], ["2026-07-06", "2026-07-07"],
                ["2026-07-03", "2026-07-06", "2026-07-07"]]
        self._off(monkeypatch)
        before = [self._verdict(days, "2026-07-03", TASK.GLBX) for days in grid]
        self._calendar(monkeypatch, tmp_path, {TASK.IFEU: ["2026-08-31"]})   # nothing for GLBX
        after = [self._verdict(days, "2026-07-03", TASK.GLBX) for days in grid]
        assert after == before, list(zip(grid, before, after))
        assert before[0] is not None and before[-1] is None, "anti-vacuity: the grid spans both"

    def test_the_calendar_off_switch_reproduces_the_pre_lane_a_arithmetic(self, monkeypatch,
                                                                          tmp_path):
        """RB2, and it is the rollback the operator gets. With the switch off, a DECLARED date is
        charged as a lost session again -- byte for byte, A-3 included."""
        self._freeze(monkeypatch, "2026-07-08")
        self._calendar(monkeypatch, tmp_path, {TASK.GLBX: ["2026-07-03"]})
        assert self._verdict(["2026-07-06"], "2026-07-03", TASK.GLBX) is None
        for value in ("off", "OFF", "0", "false", "no"):
            monkeypatch.setenv("LEVIATHAN_VENUE_CALENDAR", value)
            err = self._verdict(["2026-07-06"], "2026-07-03", TASK.GLBX)
            assert err is not None and "of 3 expected" in err, value
        monkeypatch.setenv("LEVIATHAN_VENUE_CALENDAR", "offf")
        assert self._verdict(["2026-07-06"], "2026-07-03", TASK.GLBX) is None, \
            "a TYPO leaves the fence ON rather than silently reverting it"

    def test_the_margin_is_still_one_after_the_calendar(self, monkeypatch, tmp_path):
        """ANTI-VACUITY, and D-PR-16's law honoured literally. With the holiday removed, the real
        window is 2 sessions: losing one further session still passes on the margin, losing both
        still fails. A-1 corrects what `expected` MEANS; it does not buy slack."""
        self._freeze(monkeypatch, "2026-07-08")
        self._calendar(monkeypatch, tmp_path, {TASK.GLBX: ["2026-07-03"]})
        assert self._verdict(["2026-07-06", "2026-07-07"], "2026-07-03", TASK.GLBX) is None
        assert self._verdict(["2026-07-07"], "2026-07-03", TASK.GLBX) is None, "the margin"
        err = self._verdict([], "2026-07-03", TASK.GLBX)
        assert err is not None and "only 0 of 2 expected session(s) present" in err

    def test_an_empty_unit_is_truncated_even_when_expected_is_one(self, monkeypatch, tmp_path):
        """A-3, the hole A-1 opens and closes in the same breath.

        Subtracting a holiday from an already-short window can drive the ICE `expected` from 2 to
        1, and at expected 1 the predicate `present < expected - 1` reads `present < 0` -- FALSE
        for every frame INCLUDING an empty one. Without this clause a holiday week turns the ICE
        detector OFF on 3 of the 5 weekly fires, which is exactly what D-PR-16 forbids.
        """
        monkeypatch.setattr(TASK, "_EXPECTED_LAG_SESSIONS", {TASK.IFEU: 2})
        self._freeze(monkeypatch, "2026-09-03")
        self._calendar(monkeypatch, tmp_path, {TASK.IFEU: ["2026-08-31"]})
        # window 2026-08-29..2026-09-01 holds 2 weekdays; one is declared -> expected 1
        err = self._verdict([], "2026-08-29", TASK.IFEU)
        assert err is not None and "only 0 of 1 expected session(s) present" in err
        assert self._verdict(["2026-09-01"], "2026-08-29", TASK.IFEU) is None

    def test_the_year_clip_runs_before_the_holiday_subtraction(self, monkeypatch, tmp_path):
        """D-PR-45 interaction. The January-straddle clip moves since_d / window_end and the
        subtraction only READS them, so the clip's own early return still fires with the calendar
        armed, and a date outside the clipped window subtracts nothing."""
        self._freeze(monkeypatch, "2027-01-08")
        self._calendar(monkeypatch, tmp_path,
                       {TASK.GLBX: ["2027-01-01", "2027-01-05"]})     # 01-01 is OUTSIDE the window
        # a 2026-dated frame: clipped to [2027-01-03 .. 2026-12-31], since > end -> None, unchanged
        assert self._verdict(["2026-12-31"], "2027-01-03", TASK.GLBX) is None
        # the 2027 window holds 4 weekdays; only 2027-01-05 is inside it -> expected 3, not 2
        err = self._verdict(["2027-01-07"], "2027-01-03", TASK.GLBX)
        assert err is not None and "only 1 of 3 expected session(s) present" in err


class TestFixPassSessionFloor:
    """FIX PASS -- A-R1, A-R3, A-R4, A-R11 and A-N1, each pinned on the measurement that closed it.

    The lane's review left five things unproved about this arithmetic and the refutation added a
    sixth. All six are settled here, and every one of them is a NUMBER rather than a story:

      A-R1  which venue the 2026-09-02 fire's verdict belonged to. The review reproduced the quoted
            line character for character for a GLBX unit and concluded the attribution was an
            inference. The banked log settles it the other way: the two failing lines are LABELLED
            ``IFEU.IMPACT RC/2026`` and ``IFEU.IMPACT W/2026``, and all 7 GLBX and all 6 IFUS units
            on that same fire logged healthy lines.
      A-R3  the run printed a verdict and nothing else, so the lag it resolved had to be
            reconstructed from banked events days later. ``_session_floor_facts`` returns it.
      A-R4  A-3 diverged from HEAD on any 1-weekday window, holiday or not -- 1,366 measured cases,
            316 of them plain GLBX, which declares nothing. The guard is ``removed``, not the
            switch.
      A-R11 a declared date the tape CONTRADICTS was invisible although the arithmetic already
            computed it.
      A-N1  "one holiday reds the check" is false under lag 2 and true under lag 1, and the two
            fires ran one of each. Both are pinned, and so is the margin case in between.
    """

    # The two banked fires, as they were actually logged.
    #   2026-09-02 08:30Z FAILED: IFEU RC + W, "only 1 of 3 expected session(s) present
    #                             (window 2026-08-28..2026-09-01)" -- a T-1 window, i.e. LAG 1.
    #   2026-09-04 08:36Z PASSED: 16/16. IFEU held 2 sessions (RC 18 rows / 10 outrights, W 24/14)
    #                             where GLBX held 4 and IFUS 3 -- LAG 2, margin fully consumed.
    _INCIDENT = "2026-08-31"

    @staticmethod
    def _fixture(monkeypatch, tmp_path, declared):
        return TestVenueCalendar._calendar(monkeypatch, tmp_path, declared)

    @staticmethod
    def _freeze(monkeypatch, fire):
        TestVenueCalendar._freeze(monkeypatch, fire)

    @pytest.fixture(autouse=True)
    def _cold_cache(self):
        from leviathan.silver import venue_calendar as VC
        VC.load_venue_holidays.cache_clear()
        yield
        VC.load_venue_holidays.cache_clear()

    def _verdict(self, dates, since, dataset, per_day=5):
        return TASK._truncation_error(_frame(list(dates), per_day), SPEC, mode="incremental",
                                      since=since, dataset=dataset)

    # ------------------------------------------------------------------ A-R4
    @pytest.mark.parametrize("dataset", [TASK.GLBX, TASK.IFUS, TASK.IFEU, None, "NOT.A.DATASET"])
    def test_a_one_session_holiday_free_window_is_byte_identical_to_head(
            self, monkeypatch, tmp_path, dataset):
        """A-R4, THE BOUNDARY THE OLD FENCE COULD NOT SEE.

        MEASURED, 19,699 cases (fire dates 2026-06-01..2027-02-01 x lookback {1,2,3,5,7} x five
        dataset tokens x every present-count) against the HEAD blob: 1,392 divergences, of which
        1,366 removed NO holiday from the window and EVERY ONE sat on a window holding exactly ONE
        weekday session -- 316 of them plain GLBX, which declares nothing anywhere in the shipped
        file. HEAD returns None there (``present < 0`` is False); the pre-fix build returned "only
        0 of 1 expected session(s) present", i.e. exit 1, i.e. no gate and no promote. The
        scheduled path never reaches a 1-session window, but a one-day operator REPAIR run does.

        The old regression fence ran its grid on a 3-weekday window, so it could not see this. This
        one runs on the boundary itself, for every dataset token including the two that DO declare.
        """
        self._freeze(monkeypatch, "2026-06-02")               # Tuesday: T-1 = Monday 2026-06-01
        self._fixture(monkeypatch, tmp_path, {TASK.IFEU: [self._INCIDENT]})
        monkeypatch.setattr(TASK, "_EXPECTED_LAG_SESSIONS", {})   # every token resolves to lag 1
        for present in ([], ["2026-06-01"]):
            assert self._verdict(present, "2026-06-01", dataset) is None, \
                f"a 1-weekday window declares nothing for {dataset}: HEAD returns None"

    def test_the_regression_fence_grid_now_spans_a_one_session_window(self, monkeypatch, tmp_path):
        """The byte-identity fence, extended to window lengths 1 through 4 rather than 3 only.

        Same discipline as before -- the verdict STRING with the calendar on must equal the string
        with it off, not merely the pass/fail -- but the grid now includes the length the review
        measured a divergence at.
        """
        self._freeze(monkeypatch, "2026-07-08")               # T-1 = Tue 2026-07-07
        windows = {"2026-07-07": [[], ["2026-07-07"]],
                   "2026-07-06": [[], ["2026-07-07"], ["2026-07-06", "2026-07-07"]],
                   "2026-07-03": [[], ["2026-07-07"], ["2026-07-06", "2026-07-07"],
                                  ["2026-07-03", "2026-07-06", "2026-07-07"]],
                   "2026-07-02": [[], ["2026-07-07"], ["2026-07-06", "2026-07-07"],
                                  ["2026-07-02", "2026-07-03", "2026-07-06", "2026-07-07"]]}
        monkeypatch.setenv("LEVIATHAN_VENUE_CALENDAR", "off")
        before = {s: [self._verdict(d, s, TASK.GLBX) for d in g] for s, g in windows.items()}
        self._fixture(monkeypatch, tmp_path, {TASK.IFEU: [self._INCIDENT]})   # nothing for GLBX
        after = {s: [self._verdict(d, s, TASK.GLBX) for d in g] for s, g in windows.items()}
        assert after == before, (before, after)
        assert before["2026-07-07"] == [None, None], "the 1-session window: HEAD says None twice"
        assert before["2026-07-03"][0] is not None, "anti-vacuity: the grid still spans both"

    def test_the_guard_is_the_subtraction_and_not_the_switch(self, monkeypatch, tmp_path):
        """A-3 must still fire where it was built to: a window the calendar actually shortened.

        With the calendar ON but nothing removed from THIS window, an empty unit on a 1-session
        window is HEAD's None. With one date removed from a 2-session window -- expected 2 -> 1,
        where ``present < expected - 1`` reads ``present < 0`` and is false for every frame -- the
        empty unit is caught. That is the whole of A-3 and none of A-R4.
        """
        self._freeze(monkeypatch, "2026-09-03")
        monkeypatch.setattr(TASK, "_EXPECTED_LAG_SESSIONS", {TASK.IFEU: 2})
        self._fixture(monkeypatch, tmp_path, {TASK.IFEU: [self._INCIDENT]})
        # window 2026-08-29..2026-09-01 = 2 weekdays, one of them declared -> expected 1
        err = self._verdict([], "2026-08-29", TASK.IFEU)
        assert err is not None and "only 0 of 1 expected session(s) present" in err
        # the same shape with NOTHING removed: 1 weekday, expected 1, and HEAD says None
        assert self._verdict([], "2026-09-01", TASK.IFEU) is None

    # ------------------------------------------------------------------ A-R1 / A-N1
    def test_the_banked_2026_09_02_fire_reds_at_lag_one_and_the_entry_flips_it_green(
            self, monkeypatch, tmp_path):
        """A-R1 + A-N1, the fire as it was ACTUALLY logged.

        The banked line is ``IFEU.IMPACT RC/2026: only 1 of 3 expected session(s) present (window
        2026-08-28..2026-09-01)``. since = T-5 = 2026-08-28 and window_end = T-1 = 2026-09-01 is
        the LAG 1 arithmetic over 3 weekdays (Fri 08-28, Mon 08-31, Tue 09-01). This reproduces
        that string exactly with the calendar off, and shows the declared 2026-08-31 turning it
        into a pass: expected 3 -> 2 against present 1, where 1 < 1 is False.

        This is the half the refutation's A-N1 missed by assuming lag 2: the entry DOES close the
        incident, because the incident did not run at lag 2.
        """
        self._freeze(monkeypatch, "2026-09-02")
        monkeypatch.setattr(TASK, "_EXPECTED_LAG_SESSIONS", {TASK.IFEU: 1})
        monkeypatch.setenv("LEVIATHAN_VENUE_CALENDAR", "off")
        err = self._verdict(["2026-08-28"], "2026-08-28", TASK.IFEU)
        assert err == ("only 1 of 3 expected session(s) present "
                       "(window 2026-08-28..2026-09-01) -- treating as a truncated download, "
                       "not a thin market"), "the banked line, character for character"
        self._fixture(monkeypatch, tmp_path, {TASK.IFEU: [self._INCIDENT]})
        assert self._verdict(["2026-08-28"], "2026-08-28", TASK.IFEU) is None

    def test_at_the_declared_lag_the_closure_never_reds_a_healthy_unit_it_eats_the_margin(
            self, monkeypatch, tmp_path):
        """A-N1's core claim, UPHELD as arithmetic and pinned so nobody re-derives the false one.

        The 2026-09-04 fire passed with IFEU holding 2 sessions against a 3-weekday lag-2 window --
        ``present == expected - 1``, green, margin fully consumed. So under the DECLARED lag one
        venue holiday does not red a healthy unit; it spends the margin. What the entry buys there
        is the margin back: with 2026-08-31 removed the same frame sits at ``present == expected``,
        and the unit can lose one further session before it reds instead of zero.
        """
        self._freeze(monkeypatch, "2026-09-04")
        monkeypatch.setattr(TASK, "_EXPECTED_LAG_SESSIONS", {TASK.IFEU: 2})
        healthy = ["2026-09-01", "2026-09-02"]                # 2026-08-31 closed
        monkeypatch.setenv("LEVIATHAN_VENUE_CALENDAR", "off")
        assert self._verdict(healthy, "2026-08-30", TASK.IFEU) is None, "green on the margin"
        assert self._verdict(["2026-09-02"], "2026-08-30", TASK.IFEU) is not None, \
            "and with the margin spent, ONE further absence reds it"
        self._fixture(monkeypatch, tmp_path, {TASK.IFEU: [self._INCIDENT]})
        assert self._verdict(healthy, "2026-08-30", TASK.IFEU) is None
        assert self._verdict(["2026-09-02"], "2026-08-30", TASK.IFEU) is None, \
            "the margin is BACK: one further absence is absorbed again"
        assert self._verdict([], "2026-08-30", TASK.IFEU) is not None, "two absences still red"

    @pytest.mark.parametrize("weekdays,present", [(2, 1), (3, 2), (4, 3), (5, 4)])
    def test_a_unit_at_exactly_present_equals_expected_minus_one_is_green_in_both_arms(
            self, monkeypatch, tmp_path, weekdays, present):
        """A-N1 step 3. The margin's CONSEQUENCE, stated as a pin rather than left to a reader.

        ``present < expected - 1`` means a unit sitting at exactly one session short is GREEN. The
        incident story is only coherent with that fact in front of it, and it holds identically
        with the calendar on and off, at every window length the scheduled fires produce.
        """
        since, days = _window(weekdays)
        for arm in ("off", "on"):
            if arm == "off":
                monkeypatch.setenv("LEVIATHAN_VENUE_CALENDAR", "off")
            else:
                self._fixture(monkeypatch, tmp_path, {TASK.IFEU: [self._INCIDENT]})
            assert self._verdict(days[:present], since, TASK.GLBX) is None, (arm, weekdays)
            assert self._verdict(days[:present - 1], since, TASK.GLBX) is not None, \
                (arm, weekdays, "two short is still a verdict")

    # ------------------------------------------------------------------ A-R3
    def test_the_facts_record_names_the_dataset_the_lag_and_what_it_removed(
            self, monkeypatch, tmp_path):
        """A-R3 + the brief. What the RUN resolved, per unit, in the fire's own log.

        On 2026-09-02 the two failing units printed an ERROR line and no stats line at all, so the
        fire could not say which lag it had used -- and the answer (lag 1 against a tree that
        declares lag 2) took a banked-log reconstruction days later. Every field below is one the
        reconstruction had to derive by hand.
        """
        self._freeze(monkeypatch, "2026-09-03")
        monkeypatch.setattr(TASK, "_EXPECTED_LAG_SESSIONS", {TASK.IFEU: 2, TASK.GLBX: 1})
        self._fixture(monkeypatch, tmp_path, {TASK.IFEU: [self._INCIDENT]})
        facts = TASK._session_floor_facts(_frame(["2026-09-01"], 5), SPEC, mode="incremental",
                                          since="2026-08-29", dataset=TASK.IFEU)
        assert facts["applies"] is True
        assert facts["dataset"] == TASK.IFEU
        assert facts["lag"] == 2
        assert facts["since"] == "2026-08-29" and facts["window_end"] == "2026-09-01"
        assert facts["weekdays"] == 2 and facts["holidays_removed"] == ["2026-08-31"]
        assert facts["expected"] == 1 and facts["present"] == 1
        assert facts["calendar"] == "on" and facts["verdict"] is None
        # the GLBX half of the same fire: same window, lag 1, NOTHING removed
        glbx = TASK._session_floor_facts(_frame(["2026-09-01"], 5), SPEC, mode="incremental",
                                         since="2026-08-29", dataset=TASK.GLBX)
        assert glbx["lag"] == 1 and glbx["holidays_removed"] == [] and glbx["expected"] == 3

    def test_the_facts_and_the_verdict_are_one_arithmetic(self, monkeypatch, tmp_path):
        """``_truncation_error`` IS ``_session_floor_facts(...)["verdict"]``. Pinned over a grid so
        the log line and the verdict can never drift apart, which is the failure mode a second
        implementation of the same arithmetic would ship with."""
        self._freeze(monkeypatch, "2026-09-03")
        self._fixture(monkeypatch, tmp_path, {TASK.IFEU: [self._INCIDENT]})
        seen = set()
        for dataset in (TASK.GLBX, TASK.IFUS, TASK.IFEU, None):
            for mode in ("incremental", "backfill"):
                for days in ([], ["2026-09-01"], ["2026-08-28", "2026-09-01"]):
                    frame = _frame(days, 5)
                    facts = TASK._session_floor_facts(frame, SPEC, mode=mode, since="2026-08-29",
                                                      dataset=dataset)
                    err = TASK._truncation_error(frame, SPEC, mode=mode, since="2026-08-29",
                                                 dataset=dataset)
                    assert facts["verdict"] == err
                    seen.add(err is None)
        assert seen == {True, False}, "anti-vacuity: the grid produced both outcomes"

    def test_a_leg_with_no_unit_floor_resolves_to_nothing_at_all(self):
        """The 22:30Z free chain, at the facts level. Every non-databento spec carries
        min_rows_per_unit = 0, so the floor does not APPLY and there is nothing to log -- which is
        why the free legs are a strict no-op for this whole lane."""
        czce = TASK._SOURCE_SPECS["czce"]
        assert czce.min_rows_per_unit == 0
        facts = TASK._session_floor_facts(_frame(["2026-09-01"], 5), czce, mode="incremental",
                                          since="2026-08-29", dataset=None)
        assert facts["applies"] is False and facts["verdict"] is None

    # ------------------------------------------------------------------ A-R11
    def test_a_declared_date_the_tape_contradicts_is_named_and_changes_no_verdict(
            self, monkeypatch, tmp_path):
        """A-R11. If a declared no-settlement date is WRONG the unit holds rows on it, and the
        arithmetic already computed that -- it was simply never read.

        NARROWED from the review's ``present > expected``, and the narrowing is measured: under
        D-PR-16 an ICE window ends at T-2 while the frame may legitimately hold the T-1 bar, so
        ``present > expected`` is the routine healthy ICE shape and would have fired on every
        healthy ICE fire. A row ON a declared closure cannot be routine.
        """
        self._freeze(monkeypatch, "2026-09-03")
        monkeypatch.setattr(TASK, "_EXPECTED_LAG_SESSIONS", {TASK.IFEU: 2})
        self._fixture(monkeypatch, tmp_path, {TASK.IFEU: [self._INCIDENT]})
        traded = _frame(["2026-08-31", "2026-09-01"], 5)
        facts = TASK._session_floor_facts(traded, SPEC, mode="incremental", since="2026-08-29",
                                          dataset=TASK.IFEU)
        assert facts["contradicted"] == ["2026-08-31"]
        assert facts["verdict"] is None, "it names an entry; it never changes a verdict"
        # the honest half: a HEALTHY ICE unit holding the T-1 bar is NOT a contradiction
        clean = TASK._session_floor_facts(_frame(["2026-09-01", "2026-09-02"], 5), SPEC,
                                          mode="incremental", since="2026-08-29",
                                          dataset=TASK.IFEU)
        assert clean.get("contradicted") == [] and clean["present"] > clean["expected"], \
            "present > expected is the ROUTINE ICE shape and must not be charged as a defect"
