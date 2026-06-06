"""yfinance futures bronze → silver transform.

Combines per-slug bronze DataFrames into a single long-format silver table
with five price features per (date, leviathan_slug):

price_z_2yr
    (close - rolling_504d_mean) / rolling_504d_std.
    504 trading days ≈ 2 calendar years.  Answers "is price elevated vs its
    recent history?"  Primary input to the analogue lookup engine: years
    where current production forecast matches historical production AND price
    is in the same z-score band are the highest-quality analogues.

realized_vol_30d
    Annualised 30-day realised volatility from clean log returns
    (roll dates excluded from the rolling window via NaN passthrough).
    ``log_return.rolling(30, min_periods=15).std() * sqrt(252)``
    Input to vol_regime flag and to the Tier 3 spread conviction score.

momentum_60d / momentum_1yr
    Cumulative log return over 60 / 252 non-roll trading days.
    Computed from cumulative log returns where roll dates contribute zero
    (not NaN) to avoid gaps in the cumulative series.  This is the
    economically correct treatment: a roll is a contract switch, not a
    price event.
    ``exp(cum_log_return[t] - cum_log_return[t-N]) - 1``

vol_regime
    Binary flag: 1 if realized_vol_30d > rolling 252-day 75th percentile.
    1 = elevated vol regime, 0 = normal.  Used by the Tier 2 model to
    weight the spread conviction score down during high-vol periods.

All features are computed per leviathan_slug independently — no cross-slug
contamination in rolling windows.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# Rolling window parameters
_PRICE_Z_WINDOW   = 504   # 2yr of trading days (~252/yr)
_PRICE_Z_MIN      = 252   # min 1yr before producing z-score
_VOL_WINDOW       = 30
_VOL_MIN          = 15
_VOL_REGIME_WINDOW = 252
_VOL_REGIME_MIN    = 100
_MOM_SHORT         = 60
_MOM_LONG          = 252

SILVER_COLUMNS: list[str] = [
    "date",
    "leviathan_slug",
    "close",
    "log_return",
    "price_z_2yr",
    "realized_vol_30d",
    "momentum_60d",
    "momentum_1yr",
    "vol_regime",
    "source",
]


def _features_for_slug(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all silver features for a single leviathan_slug group."""
    g = df.sort_values("date").reset_index(drop=True).copy()

    # ------------------------------------------------------------------
    # price_z_2yr — level feature, no roll masking needed
    # ------------------------------------------------------------------
    roll_price = g["close"].rolling(_PRICE_Z_WINDOW, min_periods=_PRICE_Z_MIN)
    g["price_z_2yr"] = (
        (g["close"] - roll_price.mean()) / roll_price.std()
    ).round(4).astype("float32")

    # ------------------------------------------------------------------
    # realized_vol_30d — uses clean log returns (roll dates = NaN)
    # NaN values are skipped by pandas rolling by default
    # ------------------------------------------------------------------
    g["realized_vol_30d"] = (
        g["log_return"]
        .rolling(_VOL_WINDOW, min_periods=_VOL_MIN)
        .std()
        .mul(math.sqrt(252))
        .round(4)
        .astype("float32")
    )

    # ------------------------------------------------------------------
    # vol_regime — elevated vol flag
    # ------------------------------------------------------------------
    vol_p75 = g["realized_vol_30d"].rolling(
        _VOL_REGIME_WINDOW, min_periods=_VOL_REGIME_MIN
    ).quantile(0.75)
    g["vol_regime"] = (g["realized_vol_30d"] > vol_p75).astype("int8")

    # ------------------------------------------------------------------
    # momentum — cumulative log return, roll dates contribute 0
    # ------------------------------------------------------------------
    cum_lr = g["log_return"].fillna(0.0).cumsum()
    g["momentum_60d"] = (
        (np.exp(cum_lr - cum_lr.shift(_MOM_SHORT)) - 1)
        .round(4)
        .astype("float32")
    )
    g["momentum_1yr"] = (
        (np.exp(cum_lr - cum_lr.shift(_MOM_LONG)) - 1)
        .round(4)
        .astype("float32")
    )

    g["source"] = "yfinance"
    return g[SILVER_COLUMNS]


def build_futures_silver(dfs: list[pd.DataFrame]) -> pd.DataFrame:
    """Combine per-slug bronze DataFrames into the silver feature table.

    Args:
        dfs: List of bronze DataFrames, one per slug.  Each must contain
             at minimum ``date``, ``leviathan_slug``, ``close``,
             ``log_return`` columns.

    Returns:
        Long-format DataFrame with columns :data:`SILVER_COLUMNS`, sorted
        by ``(date, leviathan_slug)``.

    Raises:
        ValueError: If no DataFrames are provided or all are empty.
    """
    if not dfs:
        raise ValueError("futures silver: no input DataFrames")

    combined = pd.concat(dfs, ignore_index=True)
    if combined.empty:
        raise ValueError("futures silver: all input DataFrames are empty")

    slug_results = []
    for slug, grp in combined.groupby("leviathan_slug", sort=False):
        slug_results.append(_features_for_slug(grp))

    result = (
        pd.concat(slug_results, ignore_index=True)
        .sort_values(["date", "leviathan_slug"])
        .reset_index(drop=True)
    )

    for slug, grp in result.groupby("leviathan_slug"):
        non_null_z   = int(grp["price_z_2yr"].notna().sum())
        non_null_vol = int(grp["realized_vol_30d"].notna().sum())
        z_max        = float(grp["price_z_2yr"].max()) if non_null_z else float("nan")
        logger.info(
            "futures silver %s: %d rows  z_non_null=%d  vol_non_null=%d  z_max=%.2f",
            slug, len(grp), non_null_z, non_null_vol, z_max,
        )

    return result
