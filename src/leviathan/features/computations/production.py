"""FAOSTAT production features and training labels.

Input: long FAOSTAT silver
(``commodity, source, country, variable, year, unit, value, flag, is_official,
ingest_date``), annual grain.

Point-in-time: all FEATURES here use years strictly before the observation crop
year (``prior_history``) — production for year Y is the outcome being predicted
and is only emitted as a label.  ``faostat_production_yoy`` for crop year Y is
the Y-2 -> Y-1 change, the most recent YoY known at planting.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from leviathan.features.computations.base import (
    FeatureContext,
    empty_result,
    make_result,
)

_LABEL_VARIABLES = ("production_quantity", "area_harvested", "yield")


def _production_series(df: pd.DataFrame, country: str) -> pd.Series:
    """Per-year production_quantity for one country, deduped keep-last."""
    sub = df.loc[
        (df["country"] == country) & (df["variable"] == "production_quantity")
    ].copy()
    if sub.empty:
        return pd.Series(dtype=float)
    sub["year"] = pd.to_numeric(sub["year"], errors="coerce").astype("Int64")
    sub["value"] = pd.to_numeric(sub["value"], errors="coerce")
    sub = sub.dropna(subset=["year", "value"]).drop_duplicates("year", keep="last")
    series = sub.set_index(sub["year"].astype(int))["value"].sort_index()
    return series


def compute_faostat_production_yoy(ctx: FeatureContext, spec) -> pd.DataFrame:
    df = ctx.inputs.get("production:faostat")
    if df is None or df.empty:
        return empty_result()

    rows: list[tuple[str, int, str, float]] = []
    for country in ctx.countries:
        series = _production_series(df, country)
        if series.empty:
            continue
        for crop_year in ctx.crop_years:
            prev1 = series.get(crop_year - 1, np.nan)
            prev2 = series.get(crop_year - 2, np.nan)
            value = (
                (prev1 - prev2) / prev2
                if pd.notna(prev1) and pd.notna(prev2) and prev2 != 0
                else np.nan
            )
            rows.append((country, crop_year, "faostat_production_yoy", value))
    return make_result(rows)


def compute_faostat_production_trend_dev(ctx: FeatureContext, spec) -> pd.DataFrame:
    """Relative deviation of the last KNOWN year (Y-1) from its linear trend.

    Trend is fit on the trailing ``production.trend_years`` window ending at
    Y-1 — never on data from Y or later.
    """
    df = ctx.inputs.get("production:faostat")
    if df is None or df.empty:
        return empty_result()

    prod_params = ctx.params.get("production", {})
    trend_years = int(prod_params.get("trend_years", 10))
    min_points = int(prod_params.get("trend_min_years", 5))

    rows: list[tuple[str, int, str, float]] = []
    for country in ctx.countries:
        series = _production_series(df, country)
        if series.empty:
            continue
        for crop_year in ctx.crop_years:
            window = series.loc[
                (series.index >= crop_year - trend_years) & (series.index < crop_year)
            ]
            value = np.nan
            if len(window) >= min_points and (crop_year - 1) in window.index:
                slope, intercept = np.polyfit(
                    window.index.to_numpy(dtype=float), window.to_numpy(dtype=float), 1
                )
                predicted = slope * (crop_year - 1) + intercept
                if predicted != 0:
                    value = (window.loc[crop_year - 1] - predicted) / abs(predicted)
            rows.append((country, crop_year, "faostat_production_trend_dev", value))
    return make_result(rows)


def compute_faostat_available(ctx: FeatureContext, spec) -> pd.DataFrame:
    """Structural-availability flag: 1 when any prior-year production is visible."""
    df = ctx.inputs.get("production:faostat")
    rows: list[tuple[str, int, str, float]] = []
    for country in ctx.countries:
        series = (
            _production_series(df, country)
            if df is not None and not df.empty
            else pd.Series(dtype=float)
        )
        for crop_year in ctx.crop_years:
            visible = series.loc[series.index < crop_year]
            rows.append((country, crop_year, "faostat_available", float(not visible.empty)))
    return make_result(rows)


def compute_faostat_labels(ctx: FeatureContext, spec) -> pd.DataFrame:
    """Training labels: the observation year's own FAOSTAT outcomes.

    Labels are the deliberate exception to the visibility choke point — they
    ARE the future the features must not see.  The spine marks them
    ``is_label=true``; they are never served as model inputs.
    """
    df = ctx.inputs.get("production:faostat")
    if df is None or df.empty:
        return empty_result()

    sub = df.loc[df["variable"].isin(_LABEL_VARIABLES)].copy()
    if sub.empty:
        return empty_result()
    sub["year"] = pd.to_numeric(sub["year"], errors="coerce").astype("Int64")
    sub["value"] = pd.to_numeric(sub["value"], errors="coerce")
    sub = sub.dropna(subset=["year", "value"])
    sub = sub.drop_duplicates(["country", "variable", "year"], keep="last")

    rows: list[tuple[str, int, str, float]] = []
    for country in ctx.countries:
        country_df = sub.loc[sub["country"] == country]
        if country_df.empty:
            continue
        indexed = country_df.set_index([country_df["year"].astype(int), "variable"])["value"]
        for crop_year in ctx.crop_years:
            for variable in _LABEL_VARIABLES:
                value = indexed.get((crop_year, variable), np.nan)
                rows.append((country, crop_year, f"label_{variable}", value))
    return make_result(rows)
