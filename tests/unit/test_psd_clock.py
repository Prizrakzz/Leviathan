"""THE PSD CLOCK's shape, pinned hermetically.

T10/P10, T11/P11 and T12/P15.  NO Glue, NO S3, NO live catalog: the fixture is a
banked snapshot of the registered ``silver_wasde`` partitions written by
``scripts/silver/gen_wasde_release_calendar.py``.  The LIVE reconcile between the
calendar and the PSD stamps is a shadow-run gate reading, not a unit test -- what
this file pins is the FUNCTION.

Nothing in ``src/`` or ``jobs/`` may import this fixture.  A calendar frozen into
the worker image would make the clock's fail-closed raise red-stop ``psd_monthly``
every month, because ``silver_wasde``'s newest partition and the newest PSD stamp
advance in lockstep and the DAG fires on days 8-13.
"""
from __future__ import annotations

import calendar as _calendar
import json
from pathlib import Path

import pandas as pd
import pytest
from leviathan.transforms.bronze_to_silver.psd_clock import (
    _PSD_MONTH_END_CODES,
    DISPOSITION_MC_ZERO,
    DISPOSITION_MONTH_END_FALLBACK,
    DISPOSITION_MONTH_END_WMT,
    DISPOSITION_WASDE_DAY,
    PsdClockError,
    psd_release_date,
    psd_release_date_and_disposition,
    psd_release_dates,
)
from leviathan.transforms.bronze_to_silver.usda_psd import (
    _PSD_COMMODITY_TO_MYS,
    _PSD_COMMODITY_TO_SLUGS,
)

_FIXTURE = (Path(__file__).resolve().parents[1] / "fixtures" / "wasde"
            / "release_calendar.json")
BANKED = json.loads(_FIXTURE.read_text(encoding="ascii"))
CAL: dict[str, int] = {k: int(v) for k, v in BANKED["calendar"].items()}

# A non-WM&T sheet (corn) and a WM&T one (cheese), used throughout.
CORN = 440000
CHEESE = 240000


# ---------------------------------------------------------------------------
# T10 / P10 -- the four day conventions
# ---------------------------------------------------------------------------

class TestTheFourDayConventions:
    def test_a_covered_month_takes_the_registered_wasde_day(self) -> None:
        date, disp = psd_release_date_and_disposition(CORN, 2024, 2026, 5, calendar=CAL)
        assert date == "2026-05-%02d" % CAL["2026-05"]
        assert disp == DISPOSITION_WASDE_DAY

    def test_an_uncovered_month_takes_the_LAST_day_of_that_month(self) -> None:
        """Month-end is PIT-conservative: an absent entry may only make a number LATER."""
        assert "2006-07" in BANKED["uningested_months"]
        date, disp = psd_release_date_and_disposition(CORN, 2006, 2006, 7, calendar=CAL)
        assert date == "2006-07-31"
        assert disp == DISPOSITION_MONTH_END_FALLBACK

    def test_a_february_fallback_respects_leap_years(self) -> None:
        """The month-end day is computed, never assumed to be 28, 30 or 31."""
        uncovered = next(m for m in BANKED["missing_months_2006_plus"] if m.endswith("-10"))
        year, month = int(uncovered[:4]), int(uncovered[5:])
        date, _ = psd_release_date_and_disposition(CORN, year, year, month, calendar=CAL)
        assert date == "%s-%02d" % (uncovered, _calendar.monthrange(year, month)[1])

    def test_a_wm_and_t_sheet_takes_month_end_even_when_the_month_IS_covered(self) -> None:
        """The eight circular sheets do not ride the WASDE day at all."""
        assert "2026-07" in CAL
        date, disp = psd_release_date_and_disposition(CHEESE, 2024, 2026, 7, calendar=CAL)
        assert date == "2026-07-31"
        assert disp == DISPOSITION_MONTH_END_WMT
        # ...and the very same (calendar_year, month_code) on a NON-member code
        # takes the registered day instead. Same stamp, two conventions, by code.
        other, other_disp = psd_release_date_and_disposition(CORN, 2024, 2026, 7, calendar=CAL)
        assert other == "2026-07-%02d" % CAL["2026-07"]
        assert other_disp == DISPOSITION_WASDE_DAY
        assert other != date

    def test_month_code_zero_anchors_to_january_first_of_the_MARKETING_year(self) -> None:
        date, disp = psd_release_date_and_disposition(CORN, 1990, 1989, 0, calendar=CAL)
        assert date == "1990-01-01"
        assert disp == DISPOSITION_MC_ZERO

    def test_the_thin_wrapper_returns_just_the_date(self) -> None:
        assert psd_release_date(CORN, 2024, 2026, 5, calendar=CAL) == \
            psd_release_date_and_disposition(CORN, 2024, 2026, 5, calendar=CAL)[0]


# ---------------------------------------------------------------------------
# THE FAIL-CLOSED RAISE
# ---------------------------------------------------------------------------

class TestItFailsClosed:
    def test_a_stamp_month_newer_than_the_calendar_RAISES(self) -> None:
        """Never a silent month-end fallback on the FRESHEST release.

        The calendar and the PSD stamp advance in lockstep monthly.  A silent
        fallback here would move TODAY's citation by up to ~19 days with no
        counter; the raise is the ordering alarm.
        """
        newest = max(CAL)
        year, month = int(newest[:4]), int(newest[5:])
        month += 1
        if month == 13:
            year, month = year + 1, 1
        with pytest.raises(PsdClockError, match="NEWER than the newest registered"):
            psd_release_date(CORN, 2026, year, month, calendar=CAL)

    def test_the_newest_covered_month_itself_does_NOT_raise(self) -> None:
        newest = max(CAL)
        assert psd_release_date(CORN, 2026, int(newest[:4]), int(newest[5:]),
                                calendar=CAL) == "%s-%02d" % (newest, CAL[newest])

    def test_an_empty_calendar_RAISES(self) -> None:
        with pytest.raises(PsdClockError, match="EMPTY"):
            psd_release_date(CORN, 2024, 2026, 5, calendar={})

    def test_a_month_code_zero_row_still_needs_a_calendar(self) -> None:
        """No branch of the clock may run against an unmeasured calendar."""
        with pytest.raises(PsdClockError, match="EMPTY"):
            psd_release_date(CORN, 1990, 1989, 0, calendar={})

    def test_the_calendar_keyword_has_no_default(self) -> None:
        with pytest.raises(TypeError):
            psd_release_date(CORN, 2024, 2026, 5)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# A MISSING STAMP IS A REFUSAL, NEVER A DEFAULT
#
# Bronze casts month_code with errors="coerce" (raw_to_bronze/usda_psd.py) so an
# unparseable value arrives as NA with no log line, and calendar_year is not in
# that cast's column set at all.  An earlier cut answered a fillna(0), which
# turned a missing calendar_year into the INVENTED date '0000-05-31' and a missing
# or negative month_code into a silent mc_zero_anchor at market_year-01-01.  Both
# sort before every historical asof: it is the leakage class this lane exists to
# close, produced by the module whose docstring promises it never invents a date.
#
# MEASURED: the three banked bronze snapshots carry ZERO nulls in either column
# (0 of 2,088,504 / 2,090,920 / 2,092,687 rows, in scope and out), so this fence is
# INERT today.  It is a fence against a source-format change, not a repair.
# ---------------------------------------------------------------------------

class TestAMissingStampIsARefusal:
    @pytest.mark.parametrize("bad", [None, float("nan"), pd.NA])
    def test_a_missing_month_code_RAISES(self, bad) -> None:
        with pytest.raises(PsdClockError, match="month_code is MISSING"):
            psd_release_date(CORN, 2024, 2026, bad, calendar=CAL)

    def test_a_negative_month_code_RAISES_instead_of_becoming_the_mc0_anchor(self) -> None:
        with pytest.raises(PsdClockError, match="NEGATIVE"):
            psd_release_date(CORN, 2024, 2026, -1, calendar=CAL)

    def test_month_code_zero_is_a_VALUE_and_still_answers(self) -> None:
        """0 is the declared pre-WASDE-tracking anchor.  It is not a gap."""
        date, disp = psd_release_date_and_disposition(CORN, 1990, 1989, 0, calendar=CAL)
        assert (date, disp) == ("1990-01-01", DISPOSITION_MC_ZERO)

    @pytest.mark.parametrize("bad", [None, float("nan"), pd.NA, 0, -5])
    def test_a_missing_or_nonpositive_calendar_year_RAISES_on_a_STAMPED_row(self, bad) -> None:
        with pytest.raises(PsdClockError, match="calendar_year"):
            psd_release_date(CORN, 2024, bad, 5, calendar=CAL)

    def test_the_year_0000_date_the_old_fillna_produced_is_UNREACHABLE(self) -> None:
        """The exact defect, named: calendar_year=None used to answer '0000-05-31'."""
        with pytest.raises(PsdClockError):
            psd_release_date(CORN, 2024, None, 5, calendar=CAL)

    def test_a_missing_calendar_year_on_an_mc_ZERO_row_still_answers(self) -> None:
        """mc == 0 never reads calendar_year, so it must not be refused for one."""
        assert psd_release_date(CORN, 1990, None, 0, calendar=CAL) == "1990-01-01"

    def test_the_vectorised_form_refuses_the_SAME_inputs(self) -> None:
        with pytest.raises(PsdClockError, match="month_code is MISSING"):
            psd_release_dates(pd.Series([CORN]), pd.Series([2024]),
                              pd.Series([2026]), pd.Series([pd.NA], dtype="Int64"),
                              calendar=CAL)
        with pytest.raises(PsdClockError, match="NEGATIVE"):
            psd_release_dates(pd.Series([CORN]), pd.Series([2024]),
                              pd.Series([2026]), pd.Series([-1]), calendar=CAL)
        with pytest.raises(PsdClockError, match="calendar_year is MISSING"):
            psd_release_dates(pd.Series([CORN]), pd.Series([2024]),
                              pd.Series([pd.NA], dtype="Int64"), pd.Series([5]),
                              calendar=CAL)

    def test_a_bad_calendar_year_on_an_mc_ZERO_row_does_NOT_stop_the_frame(self) -> None:
        """The vectorised check is scoped to STAMPED rows, exactly like the scalar."""
        dates, disp = psd_release_dates(
            pd.Series([CORN, CORN]), pd.Series([1990, 2024]),
            pd.Series([pd.NA, 2026], dtype="Int64"), pd.Series([0, 5]), calendar=CAL,
        )
        assert list(dates) == ["1990-01-01", "2026-05-%02d" % CAL["2026-05"]]
        assert list(disp) == [DISPOSITION_MC_ZERO, DISPOSITION_WASDE_DAY]


class TestTheVectorisedFormIsNotASecondImplementation:
    def test_an_mc_ZERO_ONLY_frame_still_needs_a_calendar(self) -> None:
        """The scalar reaches _calendar_max_month on EVERY path; so must this one.

        Without the up-front validation the vectorised form short-circuits the
        mc == 0 rows and RETURNS dates where psd_release_date RAISES -- the two
        forms disagreeing on the error path, which is the only place the "one
        implementation" claim can quietly stop being true.  Contained in
        production only because the batch task raises on an empty catalog first,
        and "contained by something else" is not the property this module claims.
        """
        with pytest.raises(PsdClockError, match="EMPTY"):
            psd_release_dates(pd.Series([CORN]), pd.Series([1990]),
                              pd.Series([1989]), pd.Series([0]), calendar={})
        with pytest.raises(PsdClockError, match="EMPTY"):
            psd_release_date(CORN, 1990, 1989, 0, calendar={})


# ---------------------------------------------------------------------------
# T12 / P15 -- the month-end set is a LITERAL, and its complement is only REPORTED
# ---------------------------------------------------------------------------

class TestTheMonthEndSetIsALiteral:
    """It cannot be generated from a publishing-cadence threshold, and trying kills.

    A cadence rule captures FIFTEEN of the 47 mapped codes, fires the ingest clamp
    160 times over the three banked bronze snapshots (64 / 40 / 56) and produces a
    minimum gap of -18 days.  Three of the seven extra codes it would catch --
    224200, 224400 and 230000 -- are dairy siblings of set members 223000 and
    240000 with the IDENTICAL {7, 12} publishing cadence, so no threshold can
    separate them.  With the eight-member literal the clamp fires ZERO times.
    """

    def test_the_set_is_exactly_these_eight_codes(self) -> None:
        assert _PSD_MONTH_END_CODES == frozenset({
            111000, 114200, 223000, 240000, 571120, 585100, 612000, 711100,
        })
        assert len(_PSD_MONTH_END_CODES) == 8

    def test_every_member_is_on_the_mapped_roster(self) -> None:
        assert _PSD_MONTH_END_CODES <= set(_PSD_COMMODITY_TO_SLUGS)

    def test_the_complement_over_the_mapped_roster_has_exactly_39_members(self) -> None:
        complement = set(_PSD_COMMODITY_TO_SLUGS) - _PSD_MONTH_END_CODES
        assert len(complement) == 39
        assert len(_PSD_COMMODITY_TO_SLUGS) == 47

    def test_the_three_dairy_SIBLINGS_are_deliberately_OUTSIDE_the_set(self) -> None:
        """The measured reason a cadence threshold cannot generate this set.

        224200 (butter), 224400 (NFDM) and 230000 (WMP) publish in exactly the same
        two calendar months as 223000 (fluid milk) and 240000 (cheese), which ARE
        members.  Any rule that separates them is reading the WM&T circular, not a
        cadence.
        """
        for sibling in (224200, 224400, 230000):
            assert sibling in _PSD_COMMODITY_TO_SLUGS
            assert sibling not in _PSD_MONTH_END_CODES

    def test_nothing_here_asserts_the_complement_s_cadence(self) -> None:
        """Reported, never pinned. Seven complement codes publish in fewer than
        twelve calendar months (113000, 115000, 224200, 224400, 230000, 459900,
        814200) and take the registered WASDE day anyway, because they are not
        WM&T circular sheets. This test records that sentence and asserts only
        that those seven are, in fact, outside the set."""
        for code in (113000, 115000, 224200, 224400, 230000, 459900, 814200):
            assert code not in _PSD_MONTH_END_CODES

    def test_the_mys_map_is_still_a_ROSTER_fence_and_no_longer_a_clock(self) -> None:
        """_PSD_COMMODITY_TO_MYS keeps rule R1 and loses its date-making job.

        THE RULE DID NOT MOVE; THE MECHANISM DID.  R1 used to be enforced BY
        ACCIDENT -- step 4b's ``.map(...).astype(int)`` raised "cannot convert
        float NaN to integer" for the WHOLE frame when a mapped code had no entry
        -- and that cast is DELETED with the rotation.  The fence is now the
        explicit ``_assert_every_in_scope_code_has_a_marketing_year`` at step 3b of
        usda_psd.py, which is what keeps the two dicts' key sets identical.  What
        also moved is that NOTHING reads its VALUES to compute a date any more --
        which is exactly why a clock test is the right place to say so.
        """
        assert set(_PSD_COMMODITY_TO_MYS) == set(_PSD_COMMODITY_TO_SLUGS)
        # corn's marketing year starts in September and that changes NO date.
        assert _PSD_COMMODITY_TO_MYS[CORN] == 9
        assert psd_release_date(CORN, 2024, 2026, 5, calendar=CAL) == \
            psd_release_date(410000, 2024, 2026, 5, calendar=CAL)   # wheat, MYS=6


# ---------------------------------------------------------------------------
# T11 / P11 -- the three shutdown months are absent from BOTH sides
# ---------------------------------------------------------------------------

class TestTheShutdownMonths:
    """{2013-10, 2019-01, 2025-10} -- the CANCELLED WASDEs.

    USDA published nothing in those months, so they are absences in the SOURCE.
    They must never appear in the calendar (there is no partition to register) and
    they must never appear as a PSD stamp (there was no release to stamp with).
    The two gap classes are kept distinct in the fixture on purpose: a test that
    cannot tell "USDA cancelled it" from "we have not ingested it" cannot pin the
    month-end fallback's meaning either.
    """

    def test_no_shutdown_month_is_in_the_banked_calendar(self) -> None:
        for month in ("2013-10", "2019-01", "2025-10"):
            assert month not in CAL
            assert month in BANKED["shutdown_months"]

    def test_the_two_gap_classes_are_declared_separately(self) -> None:
        assert BANKED["uningested_months"] == ["2006-07", "2008-10"]
        assert set(BANKED["missing_months_2006_plus"]) == (
            set(BANKED["shutdown_months"]) | set(BANKED["uningested_months"])
        )

    def test_every_registered_day_over_2006_is_inside_8_to_14(self) -> None:
        """The declared exception set is EMPTY today.

        It becomes {2008-10: 28} if and when that partition is backfilled --
        2008-10-28 is the only day outside 8..14 in 244 manifest months 2006+, and
        it is a v2/v3 CORRECTION that may have displaced the primary release.  The
        exception is DECLARED before a gate asserts against it, never discovered
        by one.
        """
        assert BANKED["registered_days_2006_plus"] == [8, 9, 10, 11, 12, 13, 14]
        for month, day in CAL.items():
            if month >= "2006":
                assert 8 <= day <= 14, "%s registered day %d" % (month, day)

    def test_NO_registered_month_resolves_to_a_day_1_JANUARY(self) -> None:
        """The unstated premise under release_date -> wasde_release_month, stated.

        Step 10's dedup key (usda_psd.py) sheds wasde_release_month and claims to
        discriminate identically, and the numbers card refuses to declare a
        vintage_tiebreak on the same ground.  Both rest on the mc == 0 anchor
        (``market_year-01-01``) being a value NO REAL STAMP CAN PRODUCE.  Over 2006+
        the 8..14 fence above already guarantees that.  It does NOT apply to the
        pre-2006 span, where the registered days run 1..16 -- so the premise needs
        its own pin, and this is it.

        MEASURED on the 472 registered partitions: exactly ONE month lands on day 1
        at all (2000-04) and NO January does, in any year.  A January-day-1
        registration would collide a stamped January row with that marketing year's
        mc == 0 anchor on the step-10 key and one of them would be dropped by
        bronze_ingest_date, silently.  It is a property of the CALENDAR, so it is
        pinned here rather than raised in the producer: a producer-side raise would
        red a correct run for a real USDA scheduling change.
        """
        january_day_ones = sorted(m for m, day in CAL.items()
                                  if m[5:7] == "01" and int(day) == 1)
        assert january_day_ones == []
        assert sorted(m for m, day in CAL.items() if int(day) == 1) == ["2000-04"]


# ---------------------------------------------------------------------------
# The banked fixture is a FIXTURE
# ---------------------------------------------------------------------------

def test_no_runtime_module_imports_the_banked_calendar() -> None:
    """F5's fence, asserted rather than trusted.

    A grep is the honest instrument here: the fixture is JSON, so an import would
    be an open() of its path, and the only legitimate readers are the unit suite
    and the generator that writes it.
    """
    root = Path(__file__).resolve().parents[2]
    offenders = []
    for area in ("src", "jobs"):
        for path in (root / area).rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "release_calendar.json" in text:
                offenders.append(str(path.relative_to(root)))
    assert offenders == [], (
        "a runtime module reads the BANKED calendar: %s. The runtime calendar is read "
        "live from the registered silver_wasde partitions; a baked one red-stops "
        "psd_monthly every month." % offenders
    )


# ---------------------------------------------------------------------------
# Post-fix re-review M1 / minor 1: the anchor's OWN inputs are refusals too
# ---------------------------------------------------------------------------

class TestTheAnchorInputsAreRefusalsNotDefaults:
    """market_year and commodity_code are BOTH in bronze's errors='coerce' set, so an NA arrives
    silently. The vectorised form used to fillna(0) them: an NA market_year on an mc == 0 row
    printed '0000-01-01' (the date that sorts before every asof) and an NA commodity_code took the
    WASDE day as a non-WM&T code. Both are raises now, in both forms."""

    def test_an_NA_market_year_on_an_mc_zero_row_RAISES_vectorised(self) -> None:
        with pytest.raises(PsdClockError, match="market_year is MISSING or non-positive"):
            psd_release_dates(pd.Series([440000]), pd.Series([float("nan")]), pd.Series([1989]),
                              pd.Series([0]), calendar=CAL)

    def test_an_NA_market_year_on_an_mc_zero_row_RAISES_scalar(self) -> None:
        with pytest.raises(PsdClockError, match="market_year is MISSING"):
            psd_release_date_and_disposition(440000, float("nan"), 1989, 0, calendar=CAL)
        with pytest.raises(PsdClockError, match="not a real year"):
            psd_release_date_and_disposition(440000, 0, 1989, 0, calendar=CAL)

    def test_an_NA_commodity_code_RAISES_in_both_forms(self) -> None:
        with pytest.raises(PsdClockError, match="commodity_code is MISSING"):
            psd_release_dates(pd.Series([float("nan")]), pd.Series([2025]), pd.Series([2026]),
                              pd.Series([5]), calendar=CAL)
        with pytest.raises(PsdClockError, match="commodity_code is MISSING"):
            psd_release_date_and_disposition(float("nan"), 2025, 2026, 5, calendar=CAL)

    def test_a_real_mc_zero_row_still_anchors_to_market_year_january_first(self) -> None:
        dates, disp = psd_release_dates(pd.Series([440000]), pd.Series([1989]), pd.Series([1989]),
                                        pd.Series([0]), calendar=CAL)
        assert dates.tolist() == ["1989-01-01"]
        assert psd_release_date_and_disposition(440000, 1989, 1989, 0, calendar=CAL)[0] == "1989-01-01"

