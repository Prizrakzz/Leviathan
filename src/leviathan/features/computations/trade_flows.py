"""Trade-flow, production-revision, and SA grain feature computations.

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
# SAGIS: SA maize progressive deliveries
# ---------------------------------------------------------------------------

# SAGIS weekly deliveries silver uses "maize" for the combined SA white+yellow
# maize crop — no white/yellow split at the delivery level.  Both SA maize
# slugs share the same delivery z-score.
_SAGIS_DELIVERY_SLUGS: frozenset[str] = frozenset({
    "south_african_white_maize_jse",
    "south_african_yellow_maize_jse",
})

# SAGIS CEC silver has white_maize / yellow_maize splits.
_SAGIS_CEC_SLUG_TO_CROP: dict[str, str] = {
    "south_african_white_maize_jse": "white_maize",
    "south_african_yellow_maize_jse": "yellow_maize",
}


def _sagis_season_end_year(season: str) -> int:
    """April end-year for a SAGIS season string "YYYY-YY"."""
    # "2023-24" → first_year=2023 → end April 2024 → end_year = 2024
    first_year = int(season.split("-")[0])
    return first_year + 1


def compute_sagis_deliveries_z(ctx: FeatureContext, spec) -> pd.DataFrame:
    """End-of-season progressive delivery z-score vs. prior 3-year average.

    SAGIS publishes weekly cumulative delivery totals and a precomputed
    ``z_vs_3yr_avg`` at each week.  We take the row with the highest
    ``week_number`` for the last completed SA marketing season before the
    crop-year start — i.e., the season whose April end-date precedes
    ``crop_year_start(crop_year)``.

    SA maize marketing year: May → April.
    Season "YYYY-YY" → delivery of the crop planted in Oct (YYYY-1),
    ending April (YYYY+1).  SAGIS does not split by white/yellow at the
    delivery level, so both SA maize slugs receive the same feature.

    Emits:
      sagis_delivery_z  — end-of-season z-score vs. 3-year average
    """
    if ctx.commodity not in _SAGIS_DELIVERY_SLUGS:
        return empty_result()
    df = ctx.inputs.get("sagis_deliveries")
    if df is None or df.empty or ctx.calendar is None:
        return empty_result()

    maize = df[df["crop"] == "maize"].copy()
    if maize.empty:
        return empty_result()

    rows: list[tuple[str, int, str, float]] = []

    for crop_year in ctx.crop_years:
        cutoff = pd.Timestamp(ctx.calendar.crop_year_start(crop_year))
        # Keep seasons whose April end-date is strictly before the cutoff.
        eligible = maize[
            maize["season"].map(lambda s: pd.Timestamp(f"{_sagis_season_end_year(s)}-04-30")) < cutoff
        ]
        if eligible.empty:
            continue
        latest_season = eligible["season"].max()
        season_rows = eligible[eligible["season"] == latest_season]
        end_row = season_rows.loc[season_rows["week_number"].idxmax()]
        z = end_row["z_vs_3yr_avg"]
        if pd.isna(z):
            continue
        for country in ctx.countries:
            rows.append((country, crop_year, "sagis_delivery_z", float(z)))

    return make_result(rows)


def compute_sagis_cec_revision(ctx: FeatureContext, spec) -> pd.DataFrame:
    """Latest CEC revision surprise before the crop-year start.

    The SAGIS Crop Estimates Committee publishes production estimates from
    November (initial) through February (final).  ``revision_surprise`` is
    the surprise relative to the historical distribution of revisions between
    successive estimates (precomputed in silver as a z-score equivalent).

    We take the latest CEC release whose ``release_date`` is strictly before
    ``crop_year_start(crop_year)``.

    Emits:
      sagis_cec_revision_surprise  — revision surprise (precomputed in silver)
    """
    cec_crop = _SAGIS_CEC_SLUG_TO_CROP.get(ctx.commodity)
    if cec_crop is None:
        return empty_result()
    df = ctx.inputs.get("sagis_cec")
    if df is None or df.empty or ctx.calendar is None:
        return empty_result()

    filtered = df[(df["crop"] == cec_crop) & (df["scope"] == "total")].copy()
    if filtered.empty:
        return empty_result()

    filtered["release_date"] = pd.to_datetime(filtered["release_date"], errors="coerce")
    filtered = filtered.dropna(subset=["release_date", "revision_surprise"])

    rows: list[tuple[str, int, str, float]] = []

    for crop_year in ctx.crop_years:
        cutoff = pd.Timestamp(ctx.calendar.crop_year_start(crop_year))
        eligible = filtered[filtered["release_date"] < cutoff]
        if eligible.empty:
            continue
        latest = eligible.sort_values("release_date").iloc[-1]
        val = latest["revision_surprise"]
        if pd.isna(val):
            continue
        for country in ctx.countries:
            rows.append((country, crop_year, "sagis_cec_revision_surprise", float(val)))

    return make_result(rows)


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
