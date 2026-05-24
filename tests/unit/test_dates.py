"""Unit tests for leviathan.common.dates."""
from __future__ import annotations

from datetime import date

import pytest

from leviathan.common.dates import MonthWindow, month_windows


class TestMonthWindow:
    def test_fields_accessible(self):
        w = MonthWindow(
            year=2020,
            month=3,
            start_date=date(2020, 3, 1),
            end_date=date(2020, 3, 31),
        )
        assert w.year == 2020
        assert w.month == 3
        assert w.start_date == date(2020, 3, 1)
        assert w.end_date == date(2020, 3, 31)

    def test_start_yyyymmdd(self):
        w = MonthWindow(2020, 3, date(2020, 3, 1), date(2020, 3, 31))
        assert w.start_yyyymmdd == "20200301"

    def test_end_yyyymmdd(self):
        w = MonthWindow(2020, 3, date(2020, 3, 1), date(2020, 3, 31))
        assert w.end_yyyymmdd == "20200331"

    def test_month_key_format(self):
        w = MonthWindow(2020, 3, date(2020, 3, 1), date(2020, 3, 31))
        assert w.month_key == "2020-03"

    def test_month_key_zero_pads_single_digit(self):
        w = MonthWindow(2021, 1, date(2021, 1, 1), date(2021, 1, 31))
        assert w.month_key == "2021-01"

    def test_is_frozen_dataclass(self):
        w = MonthWindow(2020, 1, date(2020, 1, 1), date(2020, 1, 31))
        with pytest.raises(Exception):
            w.year = 2021  # type: ignore[misc]


class TestMonthWindows:
    def test_single_year_has_12_windows(self):
        assert len(month_windows(2020, 2020)) == 12

    def test_two_years_has_24_windows(self):
        assert len(month_windows(2020, 2021)) == 24

    def test_start_date_always_first_of_month(self):
        for w in month_windows(2020, 2022):
            assert w.start_date.day == 1

    def test_year_and_month_set_correctly_for_first_window(self):
        windows = month_windows(2020, 2020)
        assert windows[0].year == 2020
        assert windows[0].month == 1

    def test_year_and_month_set_correctly_for_last_window(self):
        windows = month_windows(2020, 2021)
        assert windows[-1].year == 2021
        assert windows[-1].month == 12

    def test_february_end_date_leap_year(self):
        windows = month_windows(2020, 2020)
        feb = next(w for w in windows if w.month == 2)
        assert feb.end_date == date(2020, 2, 29)

    def test_february_end_date_non_leap_year(self):
        windows = month_windows(2021, 2021)
        feb = next(w for w in windows if w.month == 2)
        assert feb.end_date == date(2021, 2, 28)

    def test_march_end_date_is_31(self):
        windows = month_windows(2020, 2020)
        march = next(w for w in windows if w.month == 3)
        assert march.end_date.day == 31

    def test_april_end_date_is_30(self):
        windows = month_windows(2020, 2020)
        april = next(w for w in windows if w.month == 4)
        assert april.end_date.day == 30

    def test_windows_in_chronological_order(self):
        windows = month_windows(2019, 2021)
        for i in range(1, len(windows)):
            assert windows[i].start_date > windows[i - 1].start_date

    def test_start_yyyymmdd_first_window(self):
        windows = month_windows(2020, 2020)
        assert windows[0].start_yyyymmdd == "20200101"

    def test_end_yyyymmdd_december(self):
        windows = month_windows(2020, 2020)
        dec = next(w for w in windows if w.month == 12)
        assert dec.end_yyyymmdd == "20201231"

    def test_month_key_first_window(self):
        windows = month_windows(2020, 2020)
        assert windows[0].month_key == "2020-01"

    def test_each_window_start_matches_year_month(self):
        for w in month_windows(2019, 2020):
            assert w.start_date == date(w.year, w.month, 1)
