"""Trade-flow and production-revision feature computations.

Two families:
  conab_production_revision — Brazil CONAB intra-season production revision vs
                              the initial safra estimate, for arabica/robusta coffee.
  fgis_export_pace_yoy      — USDA FGIS weekly export inspection cumulative
                              year-over-year change for the five US grain contracts.

Point-in-time discipline:
  conab  — uses the safra year = marketing_year (Y + mkt_year_offset); takes the
           latest survey published within that safra year on or before crop-year
           start (survey_number is used as a relative ordering proxy since no
           exact publication timestamps are stored in silver).
  fgis   — uses the prior marketing year's final cumulative export total compared
           to the year before that, so the feature is available in full at the
           start of the new crop year.
"""
from __future__ import annotations

import pandas as pd

from leviathan.features.computations.base import (
    FeatureContext,
    empty_result,
    make_result,
)


# ---------------------------------------------------------------------------
# CONAB production revision
# ---------------------------------------------------------------------------

def compute_conab_production_revision(ctx: FeatureContext, spec) -> pd.DataFrame:
    """Latest CONAB national production revision before the crop-year start.

    CONAB publishes 8–10 surveys per safra year (survey_number 1 → N).
    Survey 1 has no revision; later surveys revise upward or downward.
    We pick the last available survey from the prior safra year (determined by
    mkt_year_offset) and emit the revision for the national aggregate (Brazil).

    Emits:
      conab_production_revision_bags  — thousand bags vs. initial estimate
    """
    df = ctx.inputs.get("conab")
    if df is None or df.empty or ctx.calendar is None:
        return empty_result()

    # Filter to national aggregate only (region == 'brazil').
    nat = df[df["region"] == "brazil"].copy()
    if nat.empty:
        return empty_result()

    rows: list[tuple[str, int, str, float]] = []

    for crop_year in ctx.crop_years:
        safra_year = crop_year + ctx.calendar.mkt_year_offset
        safra_rows = nat[nat["safra_year"] == safra_year]
        if safra_rows.empty:
            continue

        # survey_number is the temporal ordering proxy (higher = later in safra).
        latest = safra_rows.sort_values("survey_number").iloc[-1]
        revision = latest.get("production_revision_thousand_bags")
        if pd.isna(revision):
            continue

        for country in ctx.countries:
            rows.append((country, crop_year, "conab_production_revision_bags", float(revision)))

    return make_result(rows)


# ---------------------------------------------------------------------------
# FGIS export pace YoY
# ---------------------------------------------------------------------------

def compute_fgis_export_pace_yoy(ctx: FeatureContext, spec) -> pd.DataFrame:
    """Year-over-year change in US export inspection cumulative volume.

    For each prior marketing year MY = crop_year + mkt_year_offset, we sum all
    weekly export volumes across all destination countries to get the full-year
    total, then compare to MY-1.  The result is a fractional change:
      (MY_total - prev_total) / prev_total

    Emits:
      fgis_export_pace_yoy  — fractional YoY change in total export volume
    """
    df = ctx.inputs.get("fgis")
    if df is None or df.empty or ctx.calendar is None:
        return empty_result()

    # FGIS silver is loaded already filtered to this commodity's slug.
    # Sum weekly exports per marketing year (destination-agnostic total).
    annual = (
        df.groupby("marketing_year", as_index=False)["exports_mt_weekly"]
        .sum()
        .rename(columns={"exports_mt_weekly": "total_mt"})
        .sort_values("marketing_year")
    )
    annual = annual[annual["total_mt"] > 0]
    if len(annual) < 2:
        return empty_result()

    annual = annual.set_index("marketing_year")["total_mt"]

    rows: list[tuple[str, int, str, float]] = []

    for crop_year in ctx.crop_years:
        mkt_year = crop_year + ctx.calendar.mkt_year_offset
        prev_year = mkt_year - 1
        if mkt_year not in annual.index or prev_year not in annual.index:
            continue
        prev_total = annual[prev_year]
        if prev_total == 0:
            continue
        yoy = (annual[mkt_year] - prev_total) / prev_total
        for country in ctx.countries:
            rows.append((country, crop_year, "fgis_export_pace_yoy", float(yoy)))

    return make_result(rows)
