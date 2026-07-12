"""ICCO cocoa bronze -> silver transform (SILVER-F051, half-orphan restore).

Reduces the long-format QBCS bronze (one row per release x vintage x metric) into the canonical
``silver_icco_cocoa`` table: one authoritative row per cocoa year, consumed by the feature layer.

Authoritative-release selection (reverse-engineered + validated bit-for-bit against the 15-row
physical silver for the four balance-sheet metrics):

  * Only the ``current`` vintage is authoritative (the in-season/just-closed figure for that cocoa
    year). The ``prior`` vintage rows -- the same year re-published a year later inside the next
    bulletin -- are NOT used to overwrite the current figure.
  * For each (cocoa_year, metric) the value is taken from the LATEST release_date that published a
    non-null value for it. This handles releases that drop a single metric (e.g. a bulletin that
    omits surplus/deficit) by falling back to the most recent release that carried it, while
    production/grindings/stocks still take the newest release.
  * ``latest_release_date`` is the newest current-vintage release for the cocoa year.

Derived columns:

  su_ratio             = end_stocks_kt / grindings_kt   (the stock/use ratio; NaN if grindings 0/NaN)
  grindings_3yr_trend  = trailing 3-cocoa-year rolling mean of grindings (min_periods=2, no lookahead)
  grindings_trend_dev  = grindings_kt - grindings_3yr_trend

NOTE (documented deviation): the ORIGINAL producer's ``grindings_3yr_trend`` / ``grindings_trend_dev``
used a windowing this rebuild could not reproduce bit-for-bit from the available bronze (it appears
to smooth a cross-release/final-vintage grindings series that the tracked bronze does not retain).
The four value columns (production_kt, grindings_kt, end_stocks_kt, su_ratio) and surplus_deficit_kt
DO reproduce the physical silver exactly; the two trend analytics are re-derived here with a
well-defined, no-lookahead trailing window (they are not value-census gated columns).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

_METRIC_TO_COLUMN = {
    "world_production_kt": "production_kt",
    "world_grindings_kt": "grindings_kt",
    "end_season_stocks_kt": "end_stocks_kt",
    "surplus_deficit_kt": "surplus_deficit_kt",
}
_TREND_WINDOW = 3
_TREND_MIN_PERIODS = 2

SILVER_COLUMNS: list[str] = [
    "cocoa_year",
    "latest_release_date",
    "production_kt",
    "grindings_kt",
    "end_stocks_kt",
    "surplus_deficit_kt",
    "su_ratio",
    "grindings_3yr_trend",
    "grindings_trend_dev",
    "source",
]


def build_icco_silver(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Transform the ICCO QBCS bronze corpus into the silver balance-sheet table.

    Args:
        df_bronze: Concatenated bronze from
            :func:`~leviathan.transforms.raw_to_bronze.icco_cocoa.extract_icco_bronze` across every
            ingested release; must carry ``release_date``, ``cocoa_year``, ``vintage``, ``metric``,
            ``value_kt``.

    Returns:
        DataFrame with columns :data:`SILVER_COLUMNS`, one row per cocoa year, sorted by cocoa
        year, with zero duplicate ``cocoa_year`` rows.

    Raises:
        ValueError: If required columns are missing or the bronze is empty.
    """
    required = {"release_date", "cocoa_year", "vintage", "metric", "value_kt"}
    missing = required - set(df_bronze.columns)
    if missing:
        raise ValueError(f"ICCO bronze missing required columns: {sorted(missing)}")
    if df_bronze.empty:
        raise ValueError("ICCO bronze DataFrame is empty")

    cur = df_bronze[(df_bronze["vintage"] == "current") & df_bronze["value_kt"].notna()].copy()
    if cur.empty:
        raise ValueError("ICCO bronze has no non-null current-vintage rows")
    cur = cur.sort_values("release_date")

    # latest non-null value per (cocoa_year, metric)
    last = cur.groupby(["cocoa_year", "metric"], as_index=False).tail(1)
    wide = last.pivot_table(index="cocoa_year", columns="metric", values="value_kt",
                            aggfunc="first")
    wide = wide.rename(columns=_METRIC_TO_COLUMN)
    for col in _METRIC_TO_COLUMN.values():
        if col not in wide.columns:
            wide[col] = np.nan

    latest_release = cur.groupby("cocoa_year")["release_date"].max().rename("latest_release_date")
    df = wide.join(latest_release).reset_index().sort_values("cocoa_year").reset_index(drop=True)

    # stock/use ratio (guard div-by-zero / null)
    grind = df["grindings_kt"]
    df["su_ratio"] = np.where((grind.notna()) & (grind != 0), df["end_stocks_kt"] / grind, np.nan)

    # trailing 3-cocoa-year grindings trend (no lookahead) + deviation
    df["grindings_3yr_trend"] = (
        df["grindings_kt"].rolling(_TREND_WINDOW, min_periods=_TREND_MIN_PERIODS).mean()
    )
    df["grindings_trend_dev"] = df["grindings_kt"] - df["grindings_3yr_trend"]

    df["source"] = "icco_qbcs"

    dup = df.duplicated(subset=["cocoa_year"]).sum()
    if dup:
        raise ValueError(f"ICCO silver: {int(dup)} duplicate cocoa_year rows")

    result = df[SILVER_COLUMNS].reset_index(drop=True)
    logger.info("ICCO silver: %d cocoa years (%s..%s)", len(result),
                result["cocoa_year"].min(), result["cocoa_year"].max())
    return result
