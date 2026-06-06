"""World Bank food CPI bronze → silver transform.

Combines bronze Parquets for all countries into a single long-format
silver table with expanding-window z-scores per country.

Features produced
-----------------
cpi_yoy_pct
    Raw annual % change in overall CPI (carried from bronze).  Used as
    a proxy for food inflation — see raw_to_bronze/world_bank_food_cpi.py
    for the data-note justification.

cpi_yoy_z_5yr
    Expanding-window z-score of cpi_yoy_pct using a 5-year minimum
    observation window per country.  Reactive — captures recent
    inflation spikes relative to the last 5+ years of that country's
    own history.  Primary signal for intervention risk detection.

cpi_yoy_z_10yr
    Expanding-window z-score with a 10-year minimum window.  Provides
    longer structural context — useful for countries with episodic
    hyperinflation (Russia 1998, Ukraine 2014–2015) where a short
    window may over-normalise otherwise extreme readings.

cpi_available
    Binary flag: 1 if cpi_yoy_pct is non-null for this (country, year),
    0 otherwise.  Russia and Ukraine have structural NaN pre-1993 (no
    Soviet-era data).  Passed to XGBoost as an explicit missingness
    signal alongside the NaN cpi_yoy_pct value.

Z-score design: expanding window, not rolling
---------------------------------------------
Russia and Ukraine have only 32 years of data.  A fixed rolling window
(e.g. 10yr) would drop valid early observations for these countries.
Expanding window is more data-efficient: the z-score for year T uses
the mean and standard deviation of all years 1..T-1 (strictly prior),
which is also point-in-time correct — no look-ahead bias.

The z-score is computed per country independently.  India's 5% reading
means something different from Ukraine's 5% reading.  Cross-country
normalisation would destroy the signal.
"""
from __future__ import annotations

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# Rolling window sizes (years)
_WINDOW_5YR  = 5
_WINDOW_10YR = 10
_MIN_PERIODS_5YR  = 3
_MIN_PERIODS_10YR = 5

SILVER_COLUMNS: list[str] = [
    "country_iso",
    "country_name",
    "year",
    "cpi_yoy_pct",
    "cpi_yoy_z_5yr",
    "cpi_yoy_z_10yr",
    "cpi_available",
    "source",
]


def _rolling_zscore(series: pd.Series, window: int, min_periods: int) -> pd.Series:
    """Compute a strictly prior rolling-window z-score.

    For each position t, uses mean and std of the ``window`` years
    immediately prior (shift(1) + rolling ensures no look-ahead).

    Rolling window (not expanding) is intentional: governments react to
    CPI elevated relative to *recent* experience, not all history.
    Including 1960s hyperinflation (Indonesia 1966: 1136%) in the baseline
    makes modern moderate spikes look near-zero — useless for intervention
    risk detection.  A 10-year rolling window captures "elevated vs the
    last decade," which is the correct reference frame for policy pressure.

    Returns NaN where fewer than ``min_periods`` prior observations
    are available (structural for the first ~10 years per country).
    """
    rolled = series.shift(1).rolling(window=window, min_periods=min_periods)
    mu  = rolled.mean()
    std = rolled.std()
    return ((series - mu) / std).round(4)


def build_food_cpi_silver(dfs: list[pd.DataFrame]) -> pd.DataFrame:
    """Combine per-country bronze DataFrames into the silver table.

    Args:
        dfs: List of bronze DataFrames, one per country (IND, RUS, IDN, UKR).
             Each must contain columns from
             :data:`~leviathan.transforms.raw_to_bronze.world_bank_food_cpi.BRONZE_COLUMNS`.

    Returns:
        Long-format DataFrame with columns :data:`SILVER_COLUMNS`, sorted by
        ``(country_iso, year)``.

    Raises:
        ValueError: If no DataFrames are provided or all are empty.
    """
    if not dfs:
        raise ValueError("Food CPI silver: no input DataFrames provided")

    combined = pd.concat(dfs, ignore_index=True)
    if combined.empty:
        raise ValueError("Food CPI silver: all input DataFrames are empty")

    combined = combined.sort_values(["country_iso", "year"]).reset_index(drop=True)

    # Compute expanding z-scores per country independently
    z5   = []
    z10  = []

    for country, grp in combined.groupby("country_iso", sort=False):
        g = grp.sort_values("year")
        z5.append(_rolling_zscore(g["cpi_yoy_pct"], _WINDOW_5YR,  _MIN_PERIODS_5YR))
        z10.append(_rolling_zscore(g["cpi_yoy_pct"], _WINDOW_10YR, _MIN_PERIODS_10YR))

    combined["cpi_yoy_z_5yr"]  = pd.concat(z5).astype("float32")   # rolling 5yr
    combined["cpi_yoy_z_10yr"] = pd.concat(z10).astype("float32")  # rolling 10yr
    combined["cpi_available"]  = combined["cpi_yoy_pct"].notna().astype("int8")
    combined["source"]         = "wb_food_cpi"

    result = (
        combined[SILVER_COLUMNS]
        .sort_values(["country_iso", "year"])
        .reset_index(drop=True)
    )

    for country, grp in result.groupby("country_iso"):
        non_null  = int(grp["cpi_yoy_pct"].notna().sum())
        z5_nn     = int(grp["cpi_yoy_z_5yr"].notna().sum())
        yr_min    = int(grp["year"].min())
        yr_max    = int(grp["year"].max())
        latest    = grp.loc[grp["cpi_yoy_pct"].notna(), "cpi_yoy_pct"].iloc[-1] if non_null else float("nan")
        logger.info(
            "Food CPI silver %s: %d rows  non-null=%d  z5yr_non_null=%d  "
            "range=%d–%d  latest=%.1f%%",
            country, len(grp), non_null, z5_nn, yr_min, yr_max, latest,
        )

    return result
