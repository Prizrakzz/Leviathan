"""SILVER-F059: SAGIS weekly exports bronze -> silver (snapshot selection + leakage-free metrics).

Pure Python -- no S3/AWS.
"""
from __future__ import annotations

import pandas as pd
import pytest

from leviathan.transforms.bronze_to_silver.sagis_weekly_exports import (
    NATURAL_KEY,
    OUTPUT_COLUMNS,
    SagisDoubleCountError,
    WeeklyExportRow,
    season_start_year,
    select_authoritative_snapshot,
    transform_weekly_exports,
)


def _row(season, week, val, snap_week, is_total=True, snapshot_id=None):
    return WeeklyExportRow(
        season=season, crop="maize", week_number=week, prog_exports_mt=val, is_total=is_total,
        snapshot_id=snapshot_id or f"{season}-w{snap_week}", snapshot_week=snap_week,
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
