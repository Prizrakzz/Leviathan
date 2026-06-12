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
