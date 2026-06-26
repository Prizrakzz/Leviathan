"""Phase 7 feature families from existing high-value silver sources.

These computations intentionally use the legacy annual feature-spine contract:
one value per ``(country, crop_year, feature)``.  Without a historical
multi-snapshot as-of axis, each family uses information that is available before
the crop-year start, or a completed prior season, rather than reading later
in-season releases.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from leviathan.features.computations.base import (
    FeatureContext,
    empty_result,
    make_result,
    trailing_baseline_z,
)


# ---------------------------------------------------------------------------
# USDA WASDE direct estimate revisions
# ---------------------------------------------------------------------------

_SLUG_TO_WASDE_COMMODITY: dict[str, str] = {
    "corn_cbot": "corn",
    "campinas_corn_reference_bmf": "corn",
    "french_maize_matif": "corn",
    "soft_red_winter_wheat_cbot": "wheat",
    "hard_red_winter_wheat_kcbt": "wheat",
    "hard_red_spring_wheat_mgex": "wheat",
    "french_wheat_matif": "wheat",
    "soybeans_cbot": "soybeans",
    "soybeans_no_1_dce": "soybeans",
    "soybeans_no_2_dce": "soybeans",
    "soybean_meal_cbot": "soybean_meal",
    "soybean_meal_dce": "soybean_meal",
    "soybean_oil_cbot": "soybean_oil",
    "soybean_oil_dce": "soybean_oil",
    "rough_rice_cbot": "rice",
    "cotton": "cotton",
    "raw_sugar": "sugar",
    "white_sugar": "sugar",
}

_WASDE_COMPONENT_FEATURES: dict[str, str] = {
    "production": "wasde_production_revision_z",
    "ending_stocks": "wasde_ending_stocks_revision_z",
    "exports": "wasde_exports_revision_z",
    "total_use": "wasde_total_use_revision_z",
    "domestic_total": "wasde_domestic_use_revision_z",
}


def _marketing_year_start(value: object) -> int | None:
    match = re.search(r"\d{4}", str(value))
    if not match:
        return None
    return int(match.group(0))


def _latest_before(
    df: pd.DataFrame,
    *,
    date_col: str,
    cutoff: pd.Timestamp,
) -> pd.DataFrame:
    visible = df[pd.to_datetime(df[date_col], errors="coerce") < cutoff].copy()
    if visible.empty:
        return visible
    visible[date_col] = pd.to_datetime(visible[date_col], errors="coerce")
    return visible.sort_values(date_col)


def _zscore_yearly(
    series: pd.Series,
    ctx: FeatureContext,
) -> pd.Series:
    baselines = ctx.params.get("baselines", {})
    window_years = int(baselines.get("window_years", 30))
    min_years = int(baselines.get("min_years", 5))
    return trailing_baseline_z(series.sort_index(), window_years, min_years)


def compute_wasde_direct_revisions(ctx: FeatureContext, spec) -> pd.DataFrame:
    """Latest prior-marketing-year WASDE revisions before crop-year start.

    Emits:
      wasde_latest_revision
      wasde_consecutive_revision_count
      wasde_production_revision_z
      wasde_ending_stocks_revision_z
      wasde_exports_revision_z
      wasde_total_use_revision_z
      wasde_domestic_use_revision_z

    ``wasde_latest_revision`` and the streak count refer to production.  The
    component-specific features normalize latest revisions against the trailing
    history for the same country/region, avoiding unit-scale leakage across
    commodities.
    """
    wasde_commodity = _SLUG_TO_WASDE_COMMODITY.get(ctx.commodity)
    if wasde_commodity is None:
        return empty_result()
    df = ctx.inputs.get("wasde")
    if df is None or df.empty or ctx.calendar is None:
        return empty_result()

    wasde = df[df["commodity"] == wasde_commodity].copy()
    if wasde.empty:
        return empty_result()
    wasde["release_date"] = pd.to_datetime(wasde["release_date"], errors="coerce")
    wasde["marketing_year_start"] = wasde["marketing_year"].map(_marketing_year_start)
    wasde["revision"] = pd.to_numeric(wasde["revision"], errors="coerce")
    wasde = wasde.dropna(subset=["release_date", "marketing_year_start"])
    if wasde.empty:
        return empty_result()

    rows: list[tuple[str, int, str, float]] = []

    for country in ctx.countries:
        region_rows = wasde[wasde["region"].astype(str) == country]
        if region_rows.empty and country == "united_states":
            region_rows = wasde[wasde["region"].astype(str).isin({"united_states", "us"})]
        if region_rows.empty:
            continue

        latest_by_component: dict[str, dict[int, float]] = {
            attr: {} for attr in _WASDE_COMPONENT_FEATURES
        }
        streak_by_year: dict[int, float] = {}

        first_year = int(region_rows["release_date"].dt.year.min())
        last_year = max(ctx.crop_years)
        candidate_crop_years = list(range(first_year, last_year + 1))

        for crop_year in candidate_crop_years:
            target_market_year = crop_year + ctx.calendar.mkt_year_offset
            cutoff = pd.Timestamp(ctx.calendar.crop_year_start(crop_year))
            eligible = region_rows[
                (region_rows["release_date"] < cutoff)
                & (region_rows["marketing_year_start"] <= target_market_year)
            ].copy()
            if eligible.empty:
                continue

            selected_attr_rows: dict[str, pd.DataFrame] = {}
            for attr in _WASDE_COMPONENT_FEATURES:
                attr_pool = eligible[eligible["attribute"] == attr].dropna(subset=["revision"])
                if attr_pool.empty:
                    continue
                latest_market_year = attr_pool["marketing_year_start"].max()
                attr_rows = attr_pool[attr_pool["marketing_year_start"] == latest_market_year]
                if attr_rows.empty:
                    continue
                latest = attr_rows.sort_values("release_date").iloc[-1]
                latest_by_component[attr][crop_year] = float(latest["revision"])
                selected_attr_rows[attr] = attr_rows

            latest_rows = None
            for attr in ("production", "ending_stocks", "exports", "total_use", "domestic_total"):
                if attr in selected_attr_rows:
                    latest_rows = selected_attr_rows[attr].sort_values("release_date")
                    break
            if latest_rows is not None and not latest_rows.empty:
                rev = float(latest_rows.iloc[-1]["revision"])
                if crop_year in ctx.crop_years:
                    rows.append((country, crop_year, "wasde_latest_revision", rev))
                signs = np.sign(latest_rows["revision"].to_numpy(dtype=float))
                if signs.size:
                    last_sign = signs[-1]
                    count = 0
                    for sign in signs[::-1]:
                        if sign == 0 or sign != last_sign:
                            break
                        count += 1
                    streak_by_year[crop_year] = float(count * last_sign)

        for crop_year, streak in streak_by_year.items():
            if crop_year in ctx.crop_years:
                rows.append((country, crop_year, "wasde_consecutive_revision_count", streak))

        for attr, feature in _WASDE_COMPONENT_FEATURES.items():
            series = pd.Series(latest_by_component[attr], dtype=float)
            if series.empty:
                continue
            z = _zscore_yearly(series, ctx)
            for crop_year in ctx.crop_years:
                val = z.get(crop_year, np.nan)
                if not np.isnan(val):
                    rows.append((country, crop_year, feature, float(val)))

    return make_result(rows)


# ---------------------------------------------------------------------------
# USDA NASS citrus forecasts
# ---------------------------------------------------------------------------

def _season_start_year(value: object) -> int | None:
    match = re.search(r"\d{4}", str(value))
    if not match:
        return None
    return int(match.group(0))


def compute_nass_citrus_revisions(ctx: FeatureContext, spec) -> pd.DataFrame:
    """Completed prior-season US all-orange forecast revisions for FCOJ.

    Emits:
      nass_citrus_forecast_revision_z
      nass_citrus_prior_report_change_z
      nass_citrus_finalization_gap_z
    """
    if ctx.commodity != "frozen_orange_juice":
        return empty_result()
    df = ctx.inputs.get("nass_citrus")
    if df is None or df.empty or ctx.calendar is None:
        return empty_result()

    citrus = df[
        (df["crop"] == "all_orange") & (df["state"] == "united_states")
    ].copy()
    if citrus.empty:
        return empty_result()
    citrus["release_date"] = pd.to_datetime(citrus["release_date"], errors="coerce")
    citrus["season_start_year"] = citrus["season"].map(_season_start_year)
    citrus["forecast_1000_boxes"] = pd.to_numeric(
        citrus["forecast_1000_boxes"], errors="coerce"
    )
    citrus["revision_1000_boxes"] = pd.to_numeric(
        citrus["revision_1000_boxes"], errors="coerce"
    )
    citrus = citrus.dropna(subset=["release_date", "season_start_year"])

    final_forecast: dict[int, float] = {}
    latest_revision: dict[int, float] = {}
    prior_report_change: dict[int, float] = {}

    for season_year, group in citrus.groupby("season_start_year"):
        group = group.sort_values("release_date").dropna(subset=["forecast_1000_boxes"])
        if group.empty:
            continue
        season_year = int(season_year)
        final_forecast[season_year] = float(group.iloc[-1]["forecast_1000_boxes"])
        last_revision = group["revision_1000_boxes"].dropna()
        if not last_revision.empty:
            latest_revision[season_year] = float(last_revision.iloc[-1])
        if len(group) >= 2:
            prior_report_change[season_year] = float(
                group.iloc[-1]["forecast_1000_boxes"] - group.iloc[-2]["forecast_1000_boxes"]
            )

    if not final_forecast:
        return empty_result()

    final_series = pd.Series(final_forecast, dtype=float).sort_index()
    final_gap = final_series - final_series.shift(1)
    feature_series = {
        "nass_citrus_forecast_revision_z": _zscore_yearly(
            pd.Series(latest_revision, dtype=float), ctx
        ),
        "nass_citrus_prior_report_change_z": _zscore_yearly(
            pd.Series(prior_report_change, dtype=float), ctx
        ),
        "nass_citrus_finalization_gap_z": _zscore_yearly(final_gap.dropna(), ctx),
    }

    rows: list[tuple[str, int, str, float]] = []
    for crop_year in ctx.crop_years:
        season_year = crop_year + ctx.calendar.mkt_year_offset
        for country in ctx.countries:
            if country != "united_states":
                continue
            for feature, series in feature_series.items():
                val = series.get(season_year, np.nan)
                if not np.isnan(val):
                    rows.append((country, crop_year, feature, float(val)))
    return make_result(rows)


# ---------------------------------------------------------------------------
# AMS cotton quality
# ---------------------------------------------------------------------------

def compute_ams_cotton_quality(ctx: FeatureContext, spec) -> pd.DataFrame:
    """Prior-season US cotton tenderability and quality z-scores."""
    if ctx.commodity != "cotton":
        return empty_result()
    df = ctx.inputs.get("ams_cotton_quality")
    if df is None or df.empty or ctx.calendar is None:
        return empty_result()

    quality = df[
        (df["commodity"] == "cotton") & (df["geography"] == "us_total")
    ].copy()
    if quality.empty:
        return empty_result()
    quality["season"] = pd.to_numeric(quality["season"], errors="coerce").astype("Int64")
    for col in ("percent_tenderable", "avg_staple", "samples_classed"):
        if col in quality.columns:
            quality[col] = pd.to_numeric(quality[col], errors="coerce")
    quality = quality.dropna(subset=["season", "percent_tenderable"])

    by_year = (
        quality.sort_values("season")
        .drop_duplicates("season", keep="last")
        .set_index("season")
    )
    tender = by_year["percent_tenderable"].astype(float)
    tender_z = _zscore_yearly(tender, ctx)
    staple_z = (
        _zscore_yearly(by_year["avg_staple"].dropna().astype(float), ctx)
        if "avg_staple" in by_year else pd.Series(dtype=float)
    )

    rows: list[tuple[str, int, str, float]] = []
    for crop_year in ctx.crop_years:
        season = crop_year + ctx.calendar.mkt_year_offset
        for country in ctx.countries:
            if country != "united_states":
                continue
            if season in tender.index:
                rows.append((country, crop_year, "ams_percent_tenderable", tender[season]))
            val = tender_z.get(season, np.nan)
            if not np.isnan(val):
                rows.append((country, crop_year, "ams_percent_tenderable_z", float(val)))
            val = staple_z.get(season, np.nan)
            if not np.isnan(val):
                rows.append((country, crop_year, "ams_avg_staple_z", float(val)))
    return make_result(rows)


# ---------------------------------------------------------------------------
# UNICA sugarcane crush and sugar allocation
# ---------------------------------------------------------------------------

def _unica_harvest_start(value: object) -> int | None:
    match = re.search(r"\d{4}", str(value))
    if not match:
        return None
    return int(match.group(0))


def compute_unica_sugar_biweekly(ctx: FeatureContext, spec) -> pd.DataFrame:
    """Completed prior Brazil Center-South cane crush and sugar mix."""
    if ctx.commodity not in {"raw_sugar", "white_sugar"}:
        return empty_result()
    df = ctx.inputs.get("unica_biweekly")
    if df is None or df.empty or ctx.calendar is None:
        return empty_result()

    unica = df[df["region"] == "centro_sul"].copy()
    if unica.empty:
        return empty_result()
    unica["harvest_start_year"] = unica["harvest_year"].map(_unica_harvest_start)
    for col in ("cane_crushed_t", "sugar_produced_t", "ethanol_total_m3"):
        unica[col] = pd.to_numeric(unica[col], errors="coerce")
    unica = unica.dropna(subset=["harvest_start_year", "cane_crushed_t", "sugar_produced_t"])

    annual = (
        unica.groupby("harvest_start_year")
        .agg(
            cane_crushed_t=("cane_crushed_t", "max"),
            sugar_produced_t=("sugar_produced_t", "max"),
            ethanol_total_m3=("ethanol_total_m3", "max"),
        )
        .sort_index()
    )
    if annual.empty:
        return empty_result()
    annual["sugar_mix_pct"] = np.where(
        annual["cane_crushed_t"] > 0,
        annual["sugar_produced_t"] / annual["cane_crushed_t"] * 100.0,
        np.nan,
    )
    annual["ethanol_mix_proxy_pct"] = np.where(
        annual["cane_crushed_t"] > 0,
        annual["ethanol_total_m3"] / annual["cane_crushed_t"] * 100.0,
        np.nan,
    )

    feature_series = {
        "unica_cane_crush_pace_z": _zscore_yearly(annual["cane_crushed_t"], ctx),
        "unica_sugar_output_pace_z": _zscore_yearly(annual["sugar_produced_t"], ctx),
        "unica_sugar_mix_pct": annual["sugar_mix_pct"],
        "unica_ethanol_mix_pct": annual["ethanol_mix_proxy_pct"],
    }

    rows: list[tuple[str, int, str, float]] = []
    for crop_year in ctx.crop_years:
        harvest_year = crop_year + ctx.calendar.mkt_year_offset
        for country in ctx.countries:
            if country != "brazil":
                continue
            for feature, series in feature_series.items():
                val = series.get(harvest_year, np.nan)
                if not np.isnan(val):
                    rows.append((country, crop_year, feature, float(val)))
    return make_result(rows)
