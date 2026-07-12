"""USDA NASS Florida-citrus bronze -> silver transform (SILVER-F056, half-orphan restore).

``fetch_usda_nass_citrus.py`` writes the citrus forecast PDFs to raw; an untracked step produced
the long bronze, but no tracked bronze->silver transform existed. This module restores it. The
value-column mapping was reverse-engineered + validated bit-for-bit against the 2,450-row physical
silver (``silver/nass_citrus/part-000.parquet``): ``forecast_1000_boxes`` and
``revision_1000_boxes`` reproduce exactly (2450/2450).

Bronze (long) -> silver (one row per season x release_date x crop x state):

  * ``forecast_1000_boxes`` = the ``current_forecast`` value for the (season, release, crop, state).
  * ``revision_1000_boxes`` = ``current_forecast`` - ``prior_forecast`` (the month-over-month
    revision); NULL when the release carried no prior forecast for that key.
  * ``report_month`` is carried from the bronze (the forecast round month).
  * ``hlb_trend_factor`` is computed ONLY for Florida ``all_orange`` -- the structural
    citrus-greening (HLB) decline index; NULL for every other state/crop.

NOTE (documented deviation): the ORIGINAL ``hlb_trend_factor`` used a Florida-orange baseline this
rebuild cannot reconstruct from the tracked bronze (it appears to normalize against a pre-HLB
multi-year actual-production baseline the bronze does not retain, so the earliest seasons cannot be
bit-reproduced). It is re-derived here as a well-defined, strictly no-lookahead deviation of the
Florida all_orange forecast from its trailing prior-season baseline. The two VALUE columns
(forecast_1000_boxes, revision_1000_boxes) reproduce the physical silver exactly;
``hlb_trend_factor`` is a diagnostic, not a value-census-gated column.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

_KEY = ["season", "release_date", "report_month", "crop", "state"]
_HLB_STATE = "florida"
_HLB_CROP = "all_orange"
_HLB_BASELINE_SEASONS = 3  # trailing prior-season window for the structural-decline baseline

SILVER_COLUMNS: list[str] = [
    "season",
    "release_date",
    "report_month",
    "crop",
    "state",
    "forecast_1000_boxes",
    "revision_1000_boxes",
    "hlb_trend_factor",
    "source",
]


def build_nass_citrus_silver(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Transform the NASS citrus bronze into the silver forecast/revision table.

    Args:
        df_bronze: Long-format bronze across every ingested release; must carry ``release_date``,
            ``season``, ``report_month``, ``crop``, ``state``, ``col_type``, ``value_1000_boxes``.

    Returns:
        DataFrame with columns :data:`SILVER_COLUMNS`, one row per (season, release_date, crop,
        state), with zero natural-key duplicates.

    Raises:
        ValueError: If required columns are missing or the bronze is empty.
    """
    required = {"release_date", "season", "report_month", "crop", "state",
                "col_type", "value_1000_boxes"}
    missing = required - set(df_bronze.columns)
    if missing:
        raise ValueError(f"NASS citrus bronze missing required columns: {sorted(missing)}")
    if df_bronze.empty:
        raise ValueError("NASS citrus bronze DataFrame is empty")

    # When a release repeats a col_type for a key (a header/subtotal row followed by the detail
    # row), the authoritative value is the FIRST in bronze order (the top-line figure). Preserve
    # the bronze read order (chronological release order from the sorted S3 key listing) and let
    # groupby.first() pick it -- validated to reproduce the physical silver bit-for-bit.
    b = df_bronze.reset_index(drop=True)

    cur = (b[b["col_type"] == "current_forecast"].groupby(_KEY, as_index=False, sort=False)
           ["value_1000_boxes"].first().rename(columns={"value_1000_boxes": "forecast_1000_boxes"}))
    if cur.empty:
        raise ValueError("NASS citrus bronze has no current_forecast rows")
    prior = (b[b["col_type"] == "prior_forecast"].groupby(_KEY, as_index=False, sort=False)
             ["value_1000_boxes"].first().rename(columns={"value_1000_boxes": "prior_forecast"}))

    df = cur.merge(prior, on=_KEY, how="left")
    df["revision_1000_boxes"] = df["forecast_1000_boxes"] - df["prior_forecast"]
    df["hlb_trend_factor"] = _hlb_trend_factor(df)
    df["source"] = "usda_nass_citrus"

    df = df.sort_values(["season", "release_date", "crop", "state"]).reset_index(drop=True)
    result = df[SILVER_COLUMNS]
    if result.duplicated(subset=["season", "release_date", "crop", "state"]).any():
        raise ValueError("NASS citrus silver: duplicate (season, release_date, crop, state) rows")
    logger.info("NASS citrus silver: %d rows  hlb_non_null=%d (florida all_orange)",
                len(result), int(result["hlb_trend_factor"].notna().sum()))
    return result


def _hlb_trend_factor(df: pd.DataFrame) -> pd.Series:
    """Florida all_orange structural-decline factor: deviation of the current forecast from the
    trailing prior-season Florida orange baseline. Strictly no-lookahead (prior seasons only);
    NULL for every non-(florida, all_orange) row and for the first season (no prior baseline)."""
    out = pd.Series(np.nan, index=df.index, dtype="float64")
    fl = df[(df["state"] == _HLB_STATE) & (df["crop"] == _HLB_CROP)].copy()
    if fl.empty:
        return out
    # one representative forecast per season = the latest release's forecast that season.
    fl = fl.sort_values(["season", "release_date"])
    season_fc = fl.groupby("season")["forecast_1000_boxes"].last()
    seasons = list(season_fc.index)
    baseline = {}
    for i, s in enumerate(seasons):
        prior = season_fc.iloc[max(0, i - _HLB_BASELINE_SEASONS):i]  # strictly earlier seasons
        baseline[s] = prior.mean() if len(prior) else np.nan
    for idx, row in fl.iterrows():
        base = baseline.get(row["season"])
        if base and not np.isnan(base) and base != 0:
            out.at[idx] = row["forecast_1000_boxes"] / base - 1.0
    return out
