"""PSD / WASDE supply-demand features (Tier 2 inputs at the spine grain).

Input: wide PSD silver (``leviathan_slug, country, market_year,
wasde_release_month, release_date, ..., su_ratio, su_ratio_yoy_delta,
production_mt_revision, ending_stocks_mt_revision, ...``) already filtered to
the commodity's slug by the extractor, with ``country`` standardized to the
spine convention.

Vintage discipline: every family here goes through
``visibility.visible_slice(..., "prior_marketing_year", ...)`` which selects
the PRIOR marketing year and the latest release published on/before the
crop-year start — the balance sheet actually known at planting.  Never the
marketing year that begins at harvest, never a later revision.
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
from leviathan.features.visibility import visible_slice

_FAMILY_TO_COLUMN = {
    "psd_ending_stock_su_ratio": "su_ratio",
    "psd_su_ratio_yoy_delta": "su_ratio_yoy_delta",
    "wasde_production_revision": "production_mt_revision",
    "wasde_stocks_revision": "ending_stocks_mt_revision",
}


def _psd_value_family(ctx: FeatureContext, spec, column: str, feature: str) -> pd.DataFrame:
    df = ctx.inputs.get("psd")
    if df is None or df.empty or ctx.calendar is None:
        return empty_result()
    if column not in df.columns:
        return empty_result()

    rows: list[tuple[str, int, str, float]] = []
    for crop_year in ctx.crop_years:
        visible = visible_slice(df, "prior_marketing_year", ctx.calendar, crop_year)
        if visible.empty:
            continue
        # One row per country in the selected vintage; duplicate countries in a
        # single vintage indicate an upstream bug — keep-last after sort for
        # determinism, the spine output validation will flag natural-key dupes.
        visible = visible.sort_values("release_date").drop_duplicates("country", keep="last")
        indexed = visible.set_index("country")[column]
        for country in ctx.countries:
            value = indexed.get(country, np.nan)
            rows.append((country, crop_year, feature, value))
    return make_result(rows)


def compute_psd_ending_stock_su_ratio(ctx: FeatureContext, spec) -> pd.DataFrame:
    return _psd_value_family(
        ctx, spec, "su_ratio", "psd_ending_stock_su_ratio"
    )


def compute_psd_su_ratio_yoy_delta(ctx: FeatureContext, spec) -> pd.DataFrame:
    return _psd_value_family(
        ctx, spec, "su_ratio_yoy_delta", "psd_su_ratio_yoy_delta"
    )


def compute_wasde_production_revision(ctx: FeatureContext, spec) -> pd.DataFrame:
    return _psd_value_family(
        ctx, spec, "production_mt_revision", "wasde_production_revision"
    )


def compute_wasde_stocks_revision(ctx: FeatureContext, spec) -> pd.DataFrame:
    return _psd_value_family(
        ctx, spec, "ending_stocks_mt_revision", "wasde_stocks_revision"
    )


def compute_psd_available(ctx: FeatureContext, spec) -> pd.DataFrame:
    """1 when a point-in-time PSD vintage exists for the country and crop year."""
    df = ctx.inputs.get("psd")
    rows: list[tuple[str, int, str, float]] = []
    for crop_year in ctx.crop_years:
        countries_with_data: set[str] = set()
        if df is not None and not df.empty and ctx.calendar is not None:
            visible = visible_slice(df, "prior_marketing_year", ctx.calendar, crop_year)
            if not visible.empty:
                countries_with_data = set(visible["country"].unique())
        for country in ctx.countries:
            rows.append((
                country, crop_year, "psd_available",
                float(country in countries_with_data),
            ))
    return make_result(rows)


# ---------------------------------------------------------------------------
# WAP non-US production revision
# ---------------------------------------------------------------------------

# Maps Leviathan slug → WAP Table 01 commodity category.
_SLUG_TO_WAP_COMMODITY: dict[str, str] = {
    "corn_cbot": "coarse_grains",
    "campinas_corn_reference_bmf": "coarse_grains",
    "french_maize_matif": "coarse_grains",
    "soft_red_winter_wheat_cbot": "wheat",
    "hard_red_winter_wheat_kcbt": "wheat",
    "hard_red_spring_wheat_mgex": "wheat",
    "french_wheat_matif": "wheat",
    "soybeans_cbot": "oilseeds",
    "soybeans_no_1_dce": "oilseeds",
    "soybeans_no_2_dce": "oilseeds",
    "soybean_meal_cbot": "oilseeds",
    "soybean_oil_cbot": "oilseeds",
    "soybean_meal_dce": "oilseeds",
    "soybean_oil_dce": "oilseeds",
    "cotton": "cotton",
    "rough_rice_cbot": "rice",
}


def compute_wap_nonUS_production_revision(ctx: FeatureContext, spec) -> pd.DataFrame:
    """Latest WAP non-US production revision published before the crop-year start.

    The USDA FAS publishes the World Agricultural Production (WAP) circular
    monthly.  ``revision_mmt`` is the month-on-month change in the annual
    production estimate for the ``total_foreign`` (non-US world) aggregate.

    For each crop year Y we find the most recent WAP release published before
    ``crop_year_start(Y)``, read ``revision_mmt`` for the mapped WAP commodity
    category, then z-score the series of those annual revision values vs. the
    trailing baseline.  This captures the direction and magnitude of the most
    recent pre-season market adjustment.

    Emits:
      wap_nonUS_production_revision_z — z-scored non-US production revision
    """
    wap_commodity = _SLUG_TO_WAP_COMMODITY.get(ctx.commodity)
    if wap_commodity is None:
        return empty_result()
    df = ctx.inputs.get("wap_revisions")
    if df is None or df.empty or ctx.calendar is None:
        return empty_result()

    filtered = df[
        (df["commodity"] == wap_commodity) &
        (df["country"] == "total_foreign") &
        (df["vintage_type"] == "year")
    ].copy()
    if filtered.empty:
        return empty_result()

    filtered["release_ts"] = pd.to_datetime(
        filtered["release_month"].astype(str) + "-01", errors="coerce"
    )
    filtered = filtered.dropna(subset=["release_ts", "revision_mmt"])

    baselines = ctx.params.get("baselines", {})
    window_years = int(baselines.get("window_years", 30))
    min_years = int(baselines.get("min_years", 10))

    # Extract the latest revision before each crop year start for every year
    # in the silver (not just ctx.crop_years) to build a full baseline series.
    all_years = sorted(filtered["release_ts"].dt.year.unique())
    annual_revisions: dict[int, float] = {}

    for yr in all_years:
        cutoff = pd.Timestamp(ctx.calendar.crop_year_start(yr))
        eligible = filtered[filtered["release_ts"] < cutoff]
        if eligible.empty:
            continue
        latest = eligible.sort_values("release_ts").iloc[-1]
        rev = latest["revision_mmt"]
        if not np.isnan(rev):
            annual_revisions[yr] = float(rev)

    if not annual_revisions:
        return empty_result()

    z = trailing_baseline_z(
        pd.Series(annual_revisions, dtype=float).sort_index(),
        window_years, min_years,
    )

    rows: list[tuple[str, int, str, float]] = []
    for crop_year in ctx.crop_years:
        val = z.get(crop_year, np.nan)
        if np.isnan(val):
            continue
        for country in ctx.countries:
            rows.append((country, crop_year, "wap_nonUS_production_revision_z", float(val)))
    return make_result(rows)


# ---------------------------------------------------------------------------
# MPOB Malaysian palm oil fundamentals
# ---------------------------------------------------------------------------

def compute_mpob_fundamentals(ctx: FeatureContext, spec) -> pd.DataFrame:
    """Annual Malaysian palm oil production, exports, and S/U ratio from MPOB.

    MPOB publishes monthly CPO statistics.  We sum production and exports over
    the prior marketing year and take the final month's S/U ratio as the
    end-of-year stock-to-use proxy.  All three annual series are z-scored vs.
    a 10-year trailing baseline (min_years=5 due to the short Dec-2016 history).

    The same MPOB data applies to both palm slugs (both track Malaysian CPO).

    Emits:
      mpob_production_z  — annual CPO production z-score
      mpob_exports_z     — annual palm oil exports z-score
      mpob_su_ratio_z    — end-of-year S/U ratio z-score
    """
    df = ctx.inputs.get("mpob")
    if df is None or df.empty or ctx.calendar is None:
        return empty_result()

    mpob = df.copy()
    mpob["date"] = pd.to_datetime(mpob["date"], errors="coerce")
    mpob = mpob.dropna(subset=["date"])

    cys = ctx.calendar.crop_year_start_month

    def _crop_year(dt: pd.Timestamp) -> int:
        return dt.year if dt.month >= cys else dt.year - 1

    mpob["crop_year"] = mpob["date"].map(_crop_year)

    baselines = ctx.params.get("baselines", {})
    window_years = int(baselines.get("window_years", 10))
    min_years = int(baselines.get("min_years", 5))

    # Annual aggregates for ALL available crop years (needed for z-score baseline).
    annual = (
        mpob.groupby("crop_year")
        .agg(
            production=("production_cpo_mt", "sum"),
            exports=("exports_palm_oil_mt", "sum"),
            su_ratio_last=("su_ratio", "last"),
        )
        .sort_index()
    )

    z_prod = trailing_baseline_z(annual["production"], window_years, min_years)
    z_exp = trailing_baseline_z(annual["exports"], window_years, min_years)
    z_su = trailing_baseline_z(annual["su_ratio_last"], window_years, min_years)

    rows: list[tuple[str, int, str, float]] = []
    for crop_year in ctx.crop_years:
        prior = crop_year - 1
        for country in ctx.countries:
            if not np.isnan(z_prod.get(prior, np.nan)):
                rows.append((country, crop_year, "mpob_production_z", float(z_prod[prior])))
            if not np.isnan(z_exp.get(prior, np.nan)):
                rows.append((country, crop_year, "mpob_exports_z", float(z_exp[prior])))
            if not np.isnan(z_su.get(prior, np.nan)):
                rows.append((country, crop_year, "mpob_su_ratio_z", float(z_su[prior])))
    return make_result(rows)
