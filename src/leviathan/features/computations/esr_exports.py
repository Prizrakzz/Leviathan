"""USDA ESR export commitment feature computations.

Three features from weekly export sales data aggregated to annual marketing-year
totals with 5-year trailing z-scores.  All use prior_history visibility:
the data for marketing_year = crop_year + mkt_year_offset is the completed
prior year's export programme, known before the new crop year begins.

Emits:
  esr_outstanding_sales_z — z-score of year-end outstanding (backlog) sales
  esr_export_pace_z       — z-score of total annual shipments
  esr_net_commitment_z    — z-score of net new sales (gross + changes, where
                            changes < 0 for cancellations)
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


def compute_esr_exports(ctx: FeatureContext, spec) -> pd.DataFrame:
    """Aggregate ESR weekly data to annual marketing-year z-score features."""
    df = ctx.inputs.get("esr")
    if df is None or df.empty or ctx.calendar is None:
        return empty_result()

    # --- Annual total shipments: sum weekly_exports across all countries/weeks ---
    annual_exports = (
        df.groupby("market_year")["weekly_exports_1000mt"]
        .sum()
        .rename("total_exports")
    )

    # --- Year-end outstanding: sum outstanding_sales at the last week of each MY ---
    last_week_per_year = df.groupby("market_year")["week_ending_date"].max()
    df = df.copy()
    df["_last_week"] = df["market_year"].map(last_week_per_year)
    year_end_rows = df[df["week_ending_date"] == df["_last_week"]]
    annual_outstanding = (
        year_end_rows.groupby("market_year")["outstanding_sales_1000mt"]
        .sum()
        .rename("end_outstanding")
    )

    # --- Net new commitments: gross_new_sales + changes (cancellations are negative) ---
    df["_net_row"] = (
        df["gross_new_sales_1000mt"].fillna(0.0)
        + df["changes_1000mt"].fillna(0.0)
    )
    net_commit = df.groupby("market_year")["_net_row"].sum().rename("net_commitment")

    # Combine and compute z-scores
    annual = pd.concat([annual_exports, annual_outstanding, net_commit], axis=1).sort_index()
    annual = annual.dropna(how="all")
    if len(annual) < 3:
        return empty_result()

    z_pace = trailing_baseline_z(annual["total_exports"], window_years=5, min_years=3)
    z_outstanding = trailing_baseline_z(annual["end_outstanding"], window_years=5, min_years=3)
    z_net = trailing_baseline_z(annual["net_commitment"], window_years=5, min_years=3)

    rows: list[tuple[str, int, str, float]] = []

    for crop_year in ctx.crop_years:
        mkt_year = crop_year + ctx.calendar.mkt_year_offset

        pace_val = z_pace.get(mkt_year, np.nan)
        out_val = z_outstanding.get(mkt_year, np.nan)
        net_val = z_net.get(mkt_year, np.nan)

        for country in ctx.countries:
            if not np.isnan(pace_val):
                rows.append((country, crop_year, "esr_export_pace_z", float(pace_val)))
            if not np.isnan(out_val):
                rows.append((country, crop_year, "esr_outstanding_sales_z", float(out_val)))
            if not np.isnan(net_val):
                rows.append((country, crop_year, "esr_net_commitment_z", float(net_val)))

    return make_result(rows)
