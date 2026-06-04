"""CFTC COT bronze → silver transform.

Produces a single silver table:

    silver/cot/part-000.parquet

One row per (report_date, leviathan_slug), weekly, 2006–present.
Covers 14 Leviathan contracts with CFTC disaggregated futures data.

Features produced
-----------------
mm_net_z_3yr
    Rolling 156-week (3-year) z-score of managed money net contracts.
    The primary ``cot_net_managed_money_z_{commodity}`` feature.
    At ±2σ = contrarian signal: crowded positioning that tends to
    mean-revert regardless of fundamentals.

mm_pct_oi_z_3yr
    Same z-score on mm_net normalised by open interest.
    Preferred for cross-commodity comparison since absolute contract
    counts are not comparable between a 1.6M OI corn market and a
    125K OI cocoa market.

Deduplication
-------------
The bulk 2006-2016 file and individual annual files may share rows at
year boundaries.  The silver deduplicates on (report_date, leviathan_slug),
keeping the row from the most recently parsed file (individual year files
override the bulk file for any overlapping dates).

Rolling window
--------------
156 weeks = 3 years of weekly data.  Min periods = 52 (1 year) to
produce z-scores for the first two years of data.  The rolling window is
applied per leviathan_slug independently.
"""
from __future__ import annotations

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

_ROLLING_WINDOW  = 156   # 3 years of weekly data
_MIN_PERIODS     = 52    # 1 year minimum before producing z-scores

SILVER_COLUMNS: list[str] = [
    "report_date",
    "leviathan_slug",
    "open_interest",
    "mm_long",
    "mm_short",
    "mm_spread",
    "mm_net",
    "mm_pct_oi",
    "mm_net_z_3yr",
    "mm_pct_oi_z_3yr",
    "source",
]


def _rolling_zscore(series: pd.Series, window: int, min_periods: int) -> pd.Series:
    roll = series.rolling(window=window, min_periods=min_periods)
    return (series - roll.mean()) / roll.std()


def build_cot_silver(dfs: list[pd.DataFrame]) -> pd.DataFrame:
    """Transform CFTC COT bronze DataFrames into the weekly silver table.

    Args:
        dfs: List of bronze DataFrames, one per year-label file.

    Returns:
        DataFrame with columns :data:`SILVER_COLUMNS`, sorted by
        (report_date, leviathan_slug).
    """
    if not dfs:
        return pd.DataFrame(columns=SILVER_COLUMNS)

    combined = pd.concat(dfs, ignore_index=True)
    if combined.empty:
        return pd.DataFrame(columns=SILVER_COLUMNS)

    # Dedup: if a (report_date, slug) appears in both bulk and annual file,
    # keep the last occurrence (annual files are appended after the bulk file
    # when the caller sorts by year_label — individual years override bulk).
    combined = combined.drop_duplicates(
        subset=["report_date", "leviathan_slug"], keep="last"
    )

    combined["report_date"] = pd.to_datetime(combined["report_date"])
    combined = combined.sort_values(["leviathan_slug", "report_date"]).reset_index(drop=True)

    # Rolling z-scores per slug (each commodity independently)
    z_net    = []
    z_pct_oi = []

    for slug, group in combined.groupby("leviathan_slug", sort=False):
        g = group.sort_values("report_date")
        z_net.append(_rolling_zscore(g["mm_net"].astype(float), _ROLLING_WINDOW, _MIN_PERIODS))
        z_pct_oi.append(_rolling_zscore(g["mm_pct_oi"].astype(float), _ROLLING_WINDOW, _MIN_PERIODS))

    combined["mm_net_z_3yr"]    = pd.concat(z_net).round(4)
    combined["mm_pct_oi_z_3yr"] = pd.concat(z_pct_oi).round(4)

    # Convert report_date back to string for consistency with other silver tables
    combined["report_date"] = combined["report_date"].dt.strftime("%Y-%m-%d")
    combined["source"] = "cftc_cot"

    result = (
        combined[SILVER_COLUMNS]
        .sort_values(["report_date", "leviathan_slug"])
        .reset_index(drop=True)
    )

    logger.info(
        "COT silver: %d rows  slugs=%d  weeks=%d  date_range=%s–%s  "
        "z_non_null=%d",
        len(result),
        result["leviathan_slug"].nunique(),
        result["report_date"].nunique(),
        result["report_date"].min(),
        result["report_date"].max(),
        int(result["mm_net_z_3yr"].notna().sum()),
    )
    return result
