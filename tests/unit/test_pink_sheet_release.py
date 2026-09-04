"""PINK SHEET VINTAGES lane (a): the release-clock module, pinned.

``leviathan.common.pink_sheet_release`` is the ONE place both lanes derive a release's content key
and its knowledge date, so every rule it encodes is pinned here rather than discovered live:

  * the CONTENT KEY (last monthly row + 1 month) reproduces all six measured vintages;
  * ``expected_month_count`` reproduces 780/792/796/798/799/800;
  * ``is_full_restatement`` sees a HOLE and a DUPLICATE, which a count alone cannot;
  * ``workbook_kind`` classifies PK / OLE2 / HTML byte fixtures, so a lying origin and a real legacy
    .xls are never counted together;
  * the clock LADDER takes the origin Last-Modified only when it agrees with the derived month, and
    the month-end is UNREACHABLE from the ladder by construction.

AWS-free, network-free, and every workbook-shaped assertion is driven through synthetic month lists
rather than a checked-in 700 KB binary.
"""
from __future__ import annotations

import calendar

import pytest
from leviathan.common import pink_sheet_release as R

# The six vintages measured 2026-09-03: release -> row count. Every one hole-free 1960M01..R-1.
MEASURED = {
    "2025M01": 780,
    "2026M01": 792,
    "2026M05": 796,
    "2026M07": 798,
    "2026M08": 799,
    "2026M09": 800,
}


class TestMonthArithmetic:
    @pytest.mark.parametrize("release,n", sorted(MEASURED.items()))
    def test_expected_month_count_reproduces_every_measured_vintage(self, release, n):
        assert R.expected_month_count(release) == n

    @pytest.mark.parametrize("release,n", sorted(MEASURED.items()))
    def test_expected_months_is_the_hole_free_run_from_1960M01(self, release, n):
        months = R.expected_months(release)
        assert len(months) == n
        assert months[0] == "1960M01"
        # the last data month is one BEFORE the release -- a Pink Sheet published in R carries
        # data through R-1, which is the whole basis of the content key.
        year, month = int(release[:4]), int(release[5:7])
        prev = (year - 1, 12) if month == 1 else (year, month - 1)
        assert months[-1] == "%04dM%02d" % prev

    def test_december_rolls_the_year(self):
        assert R.expected_month_count("2027M01") == R.expected_month_count("2026M12") + 1
        assert R.expected_months("2027M01")[-1] == "2026M12"

    @pytest.mark.parametrize("bad", ["2026-09", "2026M9", "202609", "", "Sep 2026", "2026M13x"])
    def test_a_malformed_release_month_raises_rather_than_defaulting(self, bad):
        # A release month that cannot be parsed is REFUSED. Defaulting it is how a workbook gets
        # filed under a guessed month and acquires a permanently quotable wrong knowledge date.
        with pytest.raises(ValueError):
            R.expected_month_count(bad)


class TestFullRestatement:
    @pytest.mark.parametrize("release", sorted(MEASURED))
    def test_the_complete_run_is_a_full_restatement(self, release):
        assert R.is_full_restatement(R.expected_months(release)) is True

    def test_a_hole_is_seen_even_when_the_count_is_right(self):
        """THE POINT OF THE SET CHECK: 796 rows with a month missing and a month duplicated counts
        the same as a clean history. A count alone cannot see a hole."""
        months = R.expected_months("2026M05")
        assert len(months) == 796
        holed = [m for m in months if m != "1971M04"] + ["2026M04"]   # drop one, duplicate one
        assert len(holed) == 796                                      # the count still says 796
        assert R.is_full_restatement(holed) is False

    def test_a_truncated_history_is_not_a_full_restatement(self):
        assert R.is_full_restatement(R.expected_months("2026M05")[12:]) is False

    def test_empty_is_not_a_full_restatement(self):
        assert R.is_full_restatement([]) is False

    def test_a_TRAILING_PARTIAL_MONTH_is_invisible_without_the_declared_release(self):
        """THE MEASUREMENT THE REFUTE MADE, kept as the negative half of the pin.

        A workbook whose last monthly row is LABELLED but value-blank runs 1960M01..2026M09 while
        the release it is filed under is 2026M09. Measured against the run's OWN max the run derives
        2026M10 and self-certifies: n == expected == 801, hole-free, full=True. Every prefix-complete
        run does. That is why the check needs a second input, not a cleverer rule."""
        run = R.expected_months("2026M09") + ["2026M09"]      # the trailing labelled-but-blank row
        assert len(run) == 801 == R.expected_month_count("2026M10")
        assert R.is_full_restatement(run) is True             # against its own max -- blind

    def test_the_DECLARED_release_sees_the_trailing_partial_month(self):
        """Measured against the release the rows are FILED under, the same run fails: 2026M09's
        history ends at 2026M08, so a 2026M09 row is one month too many. This is the shape
        build_silver_vintages gates on -- bronze rows carry the declared release_ym."""
        run = R.expected_months("2026M09") + ["2026M09"]
        assert R.is_full_restatement(run, "2026M09") is False
        # and its mirror: the same release one month SHORT is refused too.
        assert R.is_full_restatement(R.expected_months("2026M09")[:-1], "2026M09") is False

    def test_the_declared_release_still_accepts_the_run_it_should(self):
        assert R.is_full_restatement(R.expected_months("2026M09"), "2026M09") is True
        # a run filed under the WRONG month is refused even though it is internally perfect
        assert R.is_full_restatement(R.expected_months("2026M09"), "2026M08") is False


class TestWorkbookKind:
    def test_pk_magic_is_an_xlsx(self):
        assert R.workbook_kind(b"PK\x03\x04rest-of-a-zip") == R.KIND_XLSX

    def test_ole2_magic_is_a_legacy_xls(self):
        # A REAL legacy .xls: openpyxl cannot read it and the fetch's PK gate refuses it. Counted
        # APART from a lying origin because the cause and the answer are different.
        assert R.workbook_kind(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1more") == R.KIND_OLE2

    def test_the_measured_2016_html_body_is_not_a_workbook(self):
        # MEASURED: the 2016 epoch's unhyphenated URL 200s with 100,826 bytes beginning
        # '\n    \n\n\n<!DOCTYPE' under Content-Type application/vnd...spreadsheetml.sheet.
        body = b"\x0a    \x0a\x0a\x0a<!DOCTYPE html><html><body>not a workbook</body></html>"
        assert R.workbook_kind(body) == R.KIND_NOT_WORKBOOK

    def test_empty_bytes_are_not_a_workbook(self):
        assert R.workbook_kind(b"") == R.KIND_NOT_WORKBOOK

    def test_a_non_xlsx_body_never_reaches_the_parser(self):
        with pytest.raises(ValueError, match="not an xlsx"):
            R.monthly_rows(b"<!DOCTYPE html>")


class TestReleaseClock:
    def test_origin_last_modified_wins_when_it_agrees_with_the_derived_month(self):
        date, source = R.release_clock("2026M09", b"",
                                       http_last_modified="Tue, 02 Sep 2026 11:04:00 GMT")
        assert (date, source) == ("2026-09-02", R.SOURCE_ORIGIN_LAST_MODIFIED)

    def test_a_disagreeing_origin_header_is_IGNORED_not_trusted(self):
        """A Last-Modified from a different month is not this release's publication instant -- it is
        a CDN touch or a re-upload, and taking it would put the wrong knowledge date on every row."""
        date, source = R.release_clock("2026M09", b"",
                                       http_last_modified="Fri, 01 Aug 2025 11:04:00 GMT")
        assert (date, source) == ("2026-09-01", R.SOURCE_DERIVED_MONTH_FIRST)

    def test_an_unparseable_origin_header_falls_through_rather_than_raising(self):
        date, source = R.release_clock("2026M09", b"", http_last_modified="not a date")
        assert (date, source) == ("2026-09-01", R.SOURCE_DERIVED_MONTH_FIRST)

    def test_no_header_takes_the_first_of_the_derived_month(self):
        assert R.release_clock("2026M05", b"") == ("2026-05-01", R.SOURCE_DERIVED_MONTH_FIRST)

    def test_the_archive_fallback_carries_its_OWN_token(self):
        """So the corpus can tell an origin-clocked vintage from an archive-clocked one. Two rows
        that both say 'first of the month' are not the same evidence."""
        date, source = R.release_clock("2019M04", b"", archive=True)
        assert (date, source) == ("2019-04-01", R.SOURCE_DERIVED_MONTH_FIRST_ARCHIVE)
        assert source != R.SOURCE_DERIVED_MONTH_FIRST

    @pytest.mark.parametrize("release", sorted(MEASURED))
    def test_the_month_end_is_unreachable_from_the_ladder(self, release):
        """THE DECISIVE PROPERTY. The as-of guard is a LEXICAL compare, so a vintage stamped
        2026-09-30 is unselectable at every asof from 2026-09-02 to 2026-09-29: a point-in-time read
        inside the release month would silently serve the PREVIOUS vintage while a one-clock gate
        still passed."""
        year, month = int(release[:4]), int(release[5:7])
        last = calendar.monthrange(year, month)[1]
        month_end = R.month_end_iso(release)
        assert month_end.endswith("-%02d" % last)
        # rung 2, and rung 1 at every day of the month
        assert R.release_clock(release, b"")[0] != month_end
        for day in (1, 15, last):
            got, source = R.release_clock(
                release, b"", http_last_modified=_rfc1123(year, month, day))
            # THE CLAMP. This assertion previously read `got == stamp` for EVERY day, which pinned
            # the defect rather than the law: on the last day of the month rung 1 returned the one
            # value the ladder forbids, and a legitimate late-month origin re-upload would have gone
            # unselectable at every in-month asof. Rung 1 now obeys "NEVER THE MONTH-END" too --
            # clamped to the day before, under its OWN token so a clamped row is counted rather than
            # read as a clean origin clock.
            if day == last:
                assert got == "%04d-%02d-%02d" % (year, month, last - 1)
                assert source == R.SOURCE_ORIGIN_LAST_MODIFIED_CLAMPED
            else:
                assert got == "%04d-%02d-%02d" % (year, month, day)
                assert source == R.SOURCE_ORIGIN_LAST_MODIFIED
            assert got != month_end
            assert got < month_end
        # and rung 2 is always the FIRST, which is the earliest selectable day of the month
        assert R.release_clock(release, b"")[0] == "%04d-%02d-01" % (year, month)

    def test_the_clamp_is_ONE_DAY_early_and_lands_inside_the_release_month(self):
        """The clamp's magnitude is stated, not left to inference: one day EARLY, the same direction
        as rung 2's declared 1-5 day window and strictly smaller than it. It never leaves the
        release month, so a clamped row is still selectable at every asof from day 30 onward."""
        got, source = R.release_clock(
            "2026M09", b"", http_last_modified="Wed, 30 Sep 2026 23:59:00 GMT")
        assert (got, source) == ("2026-09-29", R.SOURCE_ORIGIN_LAST_MODIFIED_CLAMPED)
        assert got.startswith("2026-09")
        # February, the shortest month, and a leap February -- the clamp is arithmetic on the real
        # month length, never a hard-coded 30.
        assert R.release_clock("2026M02", b"",
                               http_last_modified="Sat, 28 Feb 2026 10:00:00 GMT")[0] == "2026-02-27"
        assert R.release_clock("2024M02", b"",
                               http_last_modified="Thu, 29 Feb 2024 10:00:00 GMT")[0] == "2024-02-28"

    def test_the_clamped_token_is_its_own_rung_and_the_set_is_closed(self):
        """A fourth token, not a re-use of an existing one: reporting a clamped row as
        `origin_last_modified` would hide a fabricated day inside a count of clean origin clocks."""
        assert R.SOURCE_ORIGIN_LAST_MODIFIED_CLAMPED == "origin_last_modified_clamped"
        assert R.SOURCE_ORIGIN_LAST_MODIFIED_CLAMPED != R.SOURCE_ORIGIN_LAST_MODIFIED
        assert R.RELEASE_DATE_SOURCES == {
            "origin_last_modified", "origin_last_modified_clamped",
            "derived_month_first", "derived_month_first_archive"}

    def test_the_derived_fallback_is_1_to_5_days_EARLY_and_that_is_declared(self):
        """MEASURED Description stamps: Apr 2 / Jul 2 / Aug 4 / Jan 3 / Jan 6 / Sep 2. The fallback
        is EARLY by 1-5 days -- a bounded, declared early-knowledge window, counted per row in
        release_date_source and never silenced."""
        described = {"2026M05": "2026-04-02", "2026M07": "2026-07-02", "2026M08": "2026-08-04",
                     "2026M01": "2026-01-06", "2025M01": "2025-01-03", "2026M09": "2026-09-02"}
        import datetime as dt
        for release, stamp in described.items():
            got, source = R.release_clock(release, b"")
            assert source == R.SOURCE_DERIVED_MONTH_FIRST
            if got[:7] == stamp[:7]:                       # same month -> a measurable delta
                delta = (dt.date.fromisoformat(stamp) - dt.date.fromisoformat(got)).days
                assert 0 <= delta <= 5, (release, got, stamp, delta)
            else:
                # 2026M05's own Description tail says 'April 2, 2026' -- the workbook's stamp is a
                # MONTH STALE, which is exactly why no in-file stamp is ever the clock.
                assert release == "2026M05"


def _rfc1123(year: int, month: int, day: int) -> str:
    import datetime as dt
    from email.utils import format_datetime
    return format_datetime(dt.datetime(year, month, day, 11, 4, tzinfo=dt.timezone.utc),
                           usegmt=True)


def _workbook(months: list[str], *, sheet: str = R.SHEET_NAME,
              junk_rows: tuple[str, ...] = ("Annual averages", "")) -> bytes:
    """A REAL xlsx laid out like the Pink Sheet: four preamble rows, a header at row 5 (0-indexed
    4), the month label in column 0, plus the notes/aggregate rows the shipped extractor's
    ``^\\d{4}M\\d{2}$`` mask exists to drop.

    Built rather than checked in: a 700 KB binary fixture in the tree would be the object under
    test AND a thing nobody re-reads. This exercises the same openpyxl path the producer uses.
    """
    import io as _io

    from openpyxl import Workbook

    book = Workbook()
    sheet_obj = book.active
    sheet_obj.title = sheet
    # FOUR preamble rows, so the header lands at 0-indexed row 4 -- ``_HEADER_ROW`` in the shipped
    # extractor, i.e. row 5 of the workbook. Getting this off by one is not cosmetic: pandas would
    # take the FIRST MONTH ROW as the header, silently drop it, and the content key would come back
    # a month short with no error anywhere.
    sheet_obj.append(["World Bank Commodity Price Data (The Pink Sheet)"])
    sheet_obj.append(["Updated on January 06, 2025"])     # the A4-class stamp: WRONG YEAR in 1 of 6
    sheet_obj.append([None])
    sheet_obj.append([None])
    sheet_obj.append(["Month", "Crude oil, Brent", "Soybean oil"])   # header row, 0-indexed 4
    for i, month in enumerate(months):
        sheet_obj.append([month, 70.0 + i, 900.0 + i])
    for junk in junk_rows:
        sheet_obj.append([junk, None, None])
    buf = _io.BytesIO()
    book.save(buf)
    return buf.getvalue()


class TestContentKeyOnARealWorkbook:
    """The content key, driven through the SAME openpyxl + sheet-by-name + row-mask path the
    shipped extractor uses. Nothing here is stubbed."""

    @pytest.mark.parametrize("release", ["2025M01", "2026M05", "2026M09"])
    def test_round_trip_derives_the_release_the_months_imply(self, release):
        body = _workbook(R.expected_months(release))
        assert R.derived_release_ym(body) == release
        assert len(R.monthly_rows(body)) == R.expected_month_count(release)
        assert R.is_full_restatement(R.monthly_rows(body)) is True

    def test_notes_and_aggregate_rows_are_dropped_by_the_mask(self):
        body = _workbook(R.expected_months("2026M05"),
                         junk_rows=("Annual averages", "Quarterly averages", "1960-2026"))
        assert len(R.monthly_rows(body)) == 796      # the three junk rows are not months
        assert R.derived_release_ym(body) == "2026M05"

    def test_the_sheet_is_addressed_by_NAME_not_by_position(self):
        """Reading sheet 0 positionally is the bug the shipped extractor already avoids. A workbook
        whose 'Monthly Prices' sheet is absent must RAISE, never silently parse a different one."""
        body = _workbook(R.expected_months("2026M05"), sheet="Annual Prices")
        with pytest.raises(Exception):
            R.derived_release_ym(body)

    def test_a_workbook_with_no_month_rows_refuses_rather_than_guesses(self):
        body = _workbook([], junk_rows=("Annual averages",))
        with pytest.raises(ValueError):
            R.derived_release_ym(body)

    def test_the_derived_month_ignores_row_ORDER(self):
        """The rule is 'the LAST monthly row', and the workbook is ascending -- but the
        implementation takes the MAX so a re-sorted or interleaved sheet cannot move the key."""
        months = R.expected_months("2026M05")
        assert R.derived_release_ym(_workbook(list(reversed(months)))) == "2026M05"
