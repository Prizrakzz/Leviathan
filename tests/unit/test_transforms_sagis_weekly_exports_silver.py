"""SILVER-F059: SAGIS weekly exports bronze -> silver (snapshot selection + leakage-free metrics).

Pure Python -- no S3/AWS.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from leviathan.transforms.bronze_to_silver.sagis_weekly_exports import (
    NATURAL_KEY,
    OUTPUT_COLUMNS,
    SagisDoubleCountError,
    WeeklyExportRow,
    derive_week_ending_dates,
    parse_week_ending_end,
    season_start_year,
    select_authoritative_snapshot,
    transform_weekly_exports,
)


def _row(season, week, val, snap_week, is_total=True, snapshot_id=None, week_ending=None):
    return WeeklyExportRow(
        season=season, crop="maize", week_number=week, prog_exports_mt=val, is_total=is_total,
        snapshot_id=snapshot_id or f"{season}-w{snap_week}", snapshot_week=snap_week,
        week_ending=week_ending,
    )


class TestSeasonParse:
    @pytest.mark.parametrize("s,exp", [("2024-25", 2024), ("2024/25", 2024), ("xx", None)])
    def test_start_year(self, s, exp):
        assert season_start_year(s) == exp


class TestSnapshotSelection:
    def test_widest_week_snapshot_wins(self):
        rows = [_row("2024-25", 5, 140, 3), _row("2024-25", 5, 150, 10)]
        chosen = select_authoritative_snapshot(rows)
        assert len(chosen) == 1 and chosen[0].prog_exports_mt == 150   # week-10 snapshot wins

    def test_per_season_independent(self):
        rows = [_row("2023-24", 5, 120, 52), _row("2024-25", 5, 150, 10), _row("2024-25", 5, 140, 3)]
        chosen = select_authoritative_snapshot(rows)
        seasons = {r.season for r in chosen}
        assert seasons == {"2023-24", "2024-25"} and len(chosen) == 2


class TestGradeTotalDedup:
    def test_prefers_total_row(self):
        rows = [
            _row("2024-25", 5, 150, 10, is_total=True),
            _row("2024-25", 5, 60, 10, is_total=False, snapshot_id="2024-25-w10"),   # a grade row
            _row("2024-25", 5, 90, 10, is_total=False, snapshot_id="2024-25-w10"),
        ]
        df = transform_weekly_exports(rows)
        assert len(df) == 1 and df.prog_exports_mt.iloc[0] == 150    # not 150+60+90

    def test_sums_grades_when_no_total(self):
        rows = [
            _row("2024-25", 5, 60, 10, is_total=False, snapshot_id="2024-25-w10"),
            _row("2024-25", 5, 90, 10, is_total=False, snapshot_id="2024-25-w10"),
        ]
        df = transform_weekly_exports(rows)
        assert df.prog_exports_mt.iloc[0] == 150

    def test_conflicting_totals_fail_closed(self):
        rows = [
            _row("2024-25", 5, 150, 10, is_total=True, snapshot_id="2024-25-w10"),
            _row("2024-25", 5, 999, 10, is_total=True, snapshot_id="2024-25-w10"),
        ]
        with pytest.raises(SagisDoubleCountError):
            transform_weekly_exports(rows)


class TestTrailingMetrics:
    @pytest.fixture()
    def silver(self) -> pd.DataFrame:
        rows = [_row(s, 5, v, 52) for s, v in
                [("2021-22", 100), ("2022-23", 110), ("2023-24", 120)]]
        rows.append(_row("2024-25", 5, 150, 10))
        return transform_weekly_exports(rows)

    def test_schema_and_key(self, silver):
        assert list(silver.columns) == OUTPUT_COLUMNS
        assert not silver.duplicated(subset=NATURAL_KEY).any()

    def test_pct_of_prior_yr(self, silver):
        cur = silver[silver.season == "2024-25"].iloc[0]
        assert cur.pct_of_prior_yr == pytest.approx(125.0)   # 150 / 120 * 100

    def test_z_vs_3yr(self, silver):
        cur = silver[silver.season == "2024-25"].iloc[0]
        # prior 3 = [100,110,120]; mean 110, stdev 10 -> (150-110)/10 = 4.0
        assert cur.z_vs_3yr_avg == pytest.approx(4.0)

    def test_no_lookahead_earliest_season_is_null(self, silver):
        early = silver[silver.season == "2021-22"].iloc[0]
        assert pd.isna(early.pct_of_prior_yr) and pd.isna(early.z_vs_3yr_avg)

    def test_z_null_when_under_two_priors(self):
        rows = [_row("2022-23", 5, 110, 52), _row("2023-24", 5, 120, 52)]
        df = transform_weekly_exports(rows)
        # 2023-24 has only ONE prior season (2022-23) -> stdev undefined -> honest null
        r = df[df.season == "2023-24"].iloc[0]
        assert pd.isna(r.z_vs_3yr_avg) and r.pct_of_prior_yr == pytest.approx(120.0 / 110.0 * 100)


class TestParseWeekEndingEnd:
    """The END-of-range parser against the EXACT free-text formats present in live silver (probed
    2026-07-23, all 1204 rows parse). ``(day, month, year_or_None)``."""

    @pytest.mark.parametrize("text,expected", [
        ("3 - 9 May 2003", (9, 5, 2003)),          # week-1: explicit 4-digit year
        ("10 - 16 May", (16, 5, None)),            # no year (the common case)
        ("31 May - 6 Jun", (6, 6, None)),          # cross-month, no year -> END month is Jun
        ("27 Dec - 2 Jan 2004", (2, 1, 2004)),     # cross-YEAR week: END is 2 Jan, carries 2004
        ("2 - 8Aug", (8, 8, None)),                # missing space before the month
        ("30 Apr - 6 May '05", (6, 5, 2005)),      # two-digit apostrophe year -> 2005
        ("07 Oct/Okt - 14 Oct/Okt 2016", (14, 10, 2016)),  # bilingual Eng/Afr month + zero-pad
        ("1 - 7 Mar/Mrt 2014", (7, 3, 2014)),      # Afrikaans-only-distinct abbrev resolves via Eng
        ("30 Sep - 6 Oct/Okt", (6, 10, None)),     # bilingual month, no year
        ("14 May/Mei - 20 May/Mei 2016", (20, 5, 2016)),
        ("02 Dec/Des - 08 Dec/Des 2023", (8, 12, 2023)),
    ])
    def test_real_formats(self, text, expected):
        assert parse_week_ending_end(text) == expected

    @pytest.mark.parametrize("text", [None, "", "   ", "garbage", "5 -", "- 9 Xyz", "9 Foo 2003"])
    def test_unparseable_is_none(self, text):
        assert parse_week_ending_end(text) is None


class TestDeriveWeekEndingDates:
    """Group-level (one season+crop) year inference: anchor, carry-forward, Dec->Jan wrap, explicit
    re-anchor, no-year-week-1 fallback, and the 53-week season that laps its start month."""

    def test_maize_season_carry_and_year_wrap(self):
        # A real maize-shaped slice: week 1 carries 2003, most weeks omit the year, the Dec->Jan
        # week carries 2004. May 2003 ... through the wrap ... Jan 2004.
        weeks = [
            (1, "3 - 9 May 2003"), (2, "10 - 16 May"), (13, "26 Jul - 1 Aug"),
            (14, "2 - 8Aug"), (34, "20 - 26 Dec"), (35, "27 Dec - 2 Jan 2004"),
            (36, "3 - 9 Jan"), (52, "24 - 30 Apr"),
        ]
        got = derive_week_ending_dates("2003-04", weeks)
        assert got[1] == dt.date(2003, 5, 9)
        assert got[2] == dt.date(2003, 5, 16)
        assert got[14] == dt.date(2003, 8, 8)      # missing-space month parsed
        assert got[34] == dt.date(2003, 12, 26)
        assert got[35] == dt.date(2004, 1, 2)      # cross-year week: bumps into 2004
        assert got[36] == dt.date(2004, 1, 9)      # carry stays in 2004 after the wrap
        assert got[52] == dt.date(2004, 4, 30)

    def test_wrap_detected_without_any_explicit_year_after_week1(self):
        # ONLY week-1 carries a year; the Dec->Jan wrap must be found by month-decrease alone.
        weeks = [(1, "3 - 9 May 2003"), (34, "20 - 26 Dec"), (35, "27 Dec - 2 Jan"),
                 (40, "31 Jan - 6 Feb")]
        got = derive_week_ending_dates("2003-04", weeks)
        assert got[34] == dt.date(2003, 12, 26)
        assert got[35] == dt.date(2004, 1, 2)      # month decreases 12 -> 1 => year bumps
        assert got[40] == dt.date(2004, 2, 6)

    def test_week1_without_year_falls_back_to_season_start(self):
        # 2005-06 maize week-1 in live data omits a 4-digit year; the season string anchors it.
        weeks = [(1, "1 - 7 May"), (2, "8 - 14 May")]
        got = derive_week_ending_dates("2005-06", weeks)
        assert got[1] == dt.date(2005, 5, 7)
        assert got[2] == dt.date(2005, 5, 14)

    def test_short_year_anchor(self):
        weeks = [(1, "30 Apr - 6 May '05"), (2, "7 - 13 May")]
        got = derive_week_ending_dates("2005-06", weeks)
        assert got[1] == dt.date(2005, 5, 6)
        assert got[2] == dt.date(2005, 5, 13)

    def test_53_week_season_laps_start_month(self):
        # A 53-week season ends back in May of the SECOND calendar year; the pivot-month rule would
        # mis-assign week 53 to year N -- the carry+wrap rule keeps it in N+1.
        weeks = [(1, "3 - 9 May 2003"), (35, "27 Dec - 2 Jan 2004"), (52, "24 - 30 Apr"),
                 (53, "1 - 7 May")]
        got = derive_week_ending_dates("2003-04", weeks)
        assert got[52] == dt.date(2004, 4, 30)
        assert got[53] == dt.date(2004, 5, 7)      # NOT 2003-05-07

    def test_wheat_october_start(self):
        # Wheat starts in October of the season-start year (a different pivot than maize's May).
        weeks = [(1, "4 - 10 Oct 2003"), (13, "27 Dec - 2 Jan 2004"), (14, "3 - 9 Jan")]
        got = derive_week_ending_dates("2003-04", weeks)
        assert got[1] == dt.date(2003, 10, 10)
        assert got[13] == dt.date(2004, 1, 2)
        assert got[14] == dt.date(2004, 1, 9)

    def test_null_week_ending_is_none_and_does_not_break_carry(self):
        weeks = [(1, "3 - 9 May 2003"), (2, None), (3, "17 - 23 May")]
        got = derive_week_ending_dates("2003-04", weeks)
        assert got[1] == dt.date(2003, 5, 9)
        assert got[2] is None                      # unparseable -> honest null
        assert got[3] == dt.date(2003, 5, 23)      # carry survives the gap


class TestWeekEndingDateInTransform:
    """End-to-end: the transform emits week_ending_date, and it round-trips date32 through the REAL
    contract's writer schema (the publish-time dtype trap)."""

    def _rows(self):
        return [
            _row("2003-04", 1, 100.0, 52, week_ending="3 - 9 May 2003"),
            _row("2003-04", 2, 150.0, 52, week_ending="10 - 16 May"),
        ]

    def test_column_present_and_valued(self):
        df = transform_weekly_exports(self._rows())
        assert "week_ending_date" in df.columns
        assert list(df.columns) == OUTPUT_COLUMNS
        vals = dict(zip(df.week_number, df.week_ending_date))
        assert vals[1] == dt.date(2003, 5, 9)
        assert vals[2] == dt.date(2003, 5, 16)

    def test_null_week_ending_row_yields_null_date(self):
        # A grade-only week (dedup sets week_ending=None) -> null date, never a crash.
        rows = [
            _row("2003-04", 5, 60.0, 10, is_total=False, snapshot_id="2003-04-w10"),
            _row("2003-04", 5, 90.0, 10, is_total=False, snapshot_id="2003-04-w10"),
        ]
        df = transform_weekly_exports(rows)
        assert df.week_ending_date.isna().all()

    def test_encodes_date32_through_real_contract(self):
        # Proves the datetime.date column encodes as the contract's date32[day] via the flat
        # publisher -- the exact path the batch task publishes on (guards the publish-time trap).
        import io

        import pyarrow.parquet as pq

        from leviathan.silver.flat_producer import encode_parquet
        from leviathan.silver.registry import load_registry

        contract = load_registry().table("silver_sagis_weekly_exports")
        df = transform_weekly_exports(self._rows())
        body = encode_parquet(df, contract)
        table = pq.read_table(io.BytesIO(body))
        assert str(table.schema.field("week_ending_date").type) == "date32[day]"
        assert table.column("week_ending_date").to_pylist() == [dt.date(2003, 5, 9),
                                                                 dt.date(2003, 5, 16)]
