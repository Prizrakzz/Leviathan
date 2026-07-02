"""USDA ESR export commitment feature computations.

Three features from weekly export sales data aggregated to annual marketing-year
totals with 5-year trailing z-scores.  All use prior_history visibility: for each
crop year the features describe the latest FULLY COMPLETED export programme — the
most recent ESR marketing-year group whose last reported week ends before the
crop-year start.  Selection is by DATA DATES, never by market-year label
arithmetic, because the source labels use a different convention than PSD:

  ESR ``market_year`` is the FAS END-year label (confirmed 2026-07-03 from the
  silver week windows): corn/soybeans MY Sep-2023..Aug-2024 = market_year 2024
  (PSD calls the same year 2023); wheat runs Jun..Jun; soybean oil Oct..Oct.
  The previous ``crop_year + mkt_year_offset`` selection matched the completed
  programme for corn/soybeans only by accident (the label mismatch and the
  offset cancelling) and picked a YEAR-STALE programme for winter wheat.
  Completedness via ``max(week_ending_date) < crop_year_start`` is
  convention-proof and leakage-safe by construction.  See
  docs/ML_EXPERIMENT_DATA_AUDIT_REPORT.md section 3.1.

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


def _latest_completed_market_year(
    group_last_week: pd.Series, crop_year_start: pd.Timestamp
):
    """The market_year label of the most recent programme fully completed before
    ``crop_year_start`` (its last reported week ends strictly before it), or None.
    Labels are opaque here — only the week dates decide."""
    last = pd.to_datetime(group_last_week, errors="coerce")
    completed = last[last < crop_year_start]
    if completed.empty:
        return None
    return completed.idxmax()


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
        # Latest fully completed programme known at planting — selected by week
        # dates, not by label arithmetic (labels are the source's convention).
        start = pd.Timestamp(ctx.calendar.crop_year_start(crop_year))
        mkt_year = _latest_completed_market_year(last_week_per_year, start)
        if mkt_year is None:
            continue

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
