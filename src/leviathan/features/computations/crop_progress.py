"""USDA NASS crop progress feature computations.

One family:
  nass_crop_progress_ge_z — national season-average % Good+Excellent z-score

GE% is published weekly by NASS for the six US crops tracked in
silver/nass_crop_progress/.  It starts in 1986 (varying state coverage),
so z-scores are reliable from ~1996 onwards with min_years=10.

Point-in-time discipline: crop_year_direct — the season-average GE% is
only emitted when the FULL season's data is available (i.e., when the
last observed date in the silver for this year is at or after the end of
the standard GE% survey window).  Partial seasons yield NaN.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from leviathan.features.computations.base import (
    FeatureContext,
    empty_result,
    make_result,
    trailing_baseline_z,
)


def compute_nass_crop_progress_ge_z(ctx: FeatureContext, spec) -> pd.DataFrame:
    """National season-average % Good+Excellent, z-scored vs. trailing baseline.

    For each crop year we:
      1. Filter to weeks where pct_good_excellent is not null (active survey
         window — typically May through October for corn and soybeans).
      2. Average pct_good_excellent across all reporting states per week to
         get a US national composite.
      3. Average the weekly nationals to a single annual score.
      4. Require the season to be complete: the latest date with a non-null
         GE% value must be ≤ the last observed date in the silver, AND the
         latest week of the prior years must have passed (we compare the
         max week_number observed for this crop year against the median max
         week across completed prior years).
      5. Z-score the annual series vs. trailing baseline (window=30, min=10).

    Emits:
      nass_ge_pct_z — national season-average GE% z-score
    """
    df = ctx.inputs.get("nass_crop_progress")
    if df is None or df.empty or ctx.calendar is None:
        return empty_result()

    nass = df.copy()
    nass["date"] = pd.to_datetime(nass["date"], errors="coerce")
    nass = nass.dropna(subset=["date"])

    # Assign crop year using calendar's start month.
    cys = ctx.calendar.crop_year_start_month

    def _crop_year(dt: pd.Timestamp) -> int:
        return dt.year if dt.month >= cys else dt.year - 1

    nass["crop_year"] = nass["date"].map(_crop_year)

    baselines = ctx.params.get("baselines", {})
    window_years = int(baselines.get("window_years", 30))
    min_years = int(baselines.get("min_years", 10))

    # Work only with rows that have GE% data.
    ge_rows = nass.dropna(subset=["pct_good_excellent"])
    if ge_rows.empty:
        return empty_result()

    last_obs = nass["date"].max()

    # Compute the typical max week_number at which GE% reporting ends,
    # using all years that have at least 10 weeks of GE% data.
    yearly_max_week = (
        ge_rows.groupby("crop_year")["date"].max()
    )
    # A year is "complete" if its last GE% date is strictly before last_obs
    # (data was available for the full season before our cutoff).
    complete_years = yearly_max_week[yearly_max_week < last_obs]

    if len(complete_years) < min_years:
        return empty_result()

    # Median end-of-season date across complete years (used to detect
    # incomplete current-year seasons).
    median_end_month = int(complete_years.dt.month.median())
    median_end_day = int(complete_years.dt.day.median())

    # Annual national season-average GE% across ALL years in silver
    # (not just ctx.crop_years) to build a complete baseline for z-scoring.
    annual_ge: dict[int, float] = {}
    for crop_year, group in ge_rows.groupby("crop_year"):
        season_last_date = group["date"].max()
        # Require the season to be complete: latest GE% date must be >= median
        # end-of-season date for this year.
        expected_end = pd.Timestamp(
            year=int(season_last_date.year),
            month=median_end_month,
            day=min(median_end_day, 28),
        )
        if season_last_date < expected_end:
            continue
        if season_last_date > last_obs:
            continue
        # National season average: mean across states per week, then mean across weeks.
        weekly_national = group.groupby("date")["pct_good_excellent"].mean()
        if weekly_national.empty or len(weekly_national) < 4:
            continue
        annual_ge[int(crop_year)] = float(weekly_national.mean())

    if not annual_ge:
        return empty_result()

    z = trailing_baseline_z(
        pd.Series(annual_ge, dtype=float).sort_index(),
        window_years, min_years,
    )

    rows: list[tuple[str, int, str, float]] = []
    for crop_year in ctx.crop_years:
        val = z.get(crop_year, np.nan)
        if np.isnan(val):
            continue
        for country in ctx.countries:
            rows.append((country, crop_year, "nass_ge_pct_z", float(val)))
    return make_result(rows)
