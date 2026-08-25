"""Bronze -> wide silver transform for Frankfurter FX (SILVER-F040).

Produces ``silver_fred_fx`` (a documented legacy misnomer; the true source is
Frankfurter -- see ADR-003). Pivots the long bronze (one row per date x currency)
into the wide daily silver (one row per date) and derives, per currency, a 90-day
percent change.

Frozen semantics (ADR-003):
  * direction -- each ``<ccy>_usd`` column is units of local currency per 1 USD;
  * ``<ccy>_usd_pct_change_90d`` -- PERCENT change (x100) versus the last available
    observation AT OR BEFORE ``date - 90 CALENDAR days`` (calendar-day lag, not an
    observation-count lag; the latter would be named ``_90obs``); null when no such
    prior observation exists or either endpoint value is null/zero;
  * grain -- one row per valid source observation date; ``count(*) == count(DISTINCT
    date)`` (asserted); weekends/holidays are never synthesized;
  * an absent currency stays null across the whole column (INV-4) -- the column is
    still emitted so the schema is stable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pyarrow as pa

from leviathan.common.logging import get_logger
from leviathan.transforms.raw_to_bronze.frankfurter_fx import SERIES_MAP, SOURCE

logger = get_logger(__name__)

_LAG_DAYS = 90
_PCT_ROUND = 6

# Column order matches the silver_fred_fx registry contract exactly.
# FX-1 (projection wave, 2026-08-25): 3 -> 14 (incl. GBP for D-3's cocoa GBP_cross). The incumbents keep their positions (additive columns
# only -- the Glue ALTER is ADD COLUMNS, D-4); the ten new are the measured region_map demand (FX-4:
# 19 declining legs across 13 boards). ARS stays although dead at source since 2020-10-30 (ADR-003 /
# FX-6 -- the column is history, the refusal lives in region_map's Argentina entry losing its
# currency key). SERVE THE DEMAND, fetch rides SERIES_MAP -- do not add a column here without its
# cascade consumer.
_RATE_COLUMNS: list[str] = ["brl_usd", "ars_usd", "cny_usd",
                            "idr_usd", "inr_usd", "myr_usd", "thb_usd", "try_usd",
                            "aud_usd", "cad_usd", "zar_usd", "mxn_usd", "eur_usd", "gbp_usd"]
SILVER_COLUMNS: list[str] = ["date"]
for _c in _RATE_COLUMNS:
    SILVER_COLUMNS.append(_c)
    SILVER_COLUMNS.append(f"{_c}_pct_change_90d")
SILVER_COLUMNS.append("source")

# INV-2 explicit writer schema, matching the registry target_arrow_type (date is a
# text ISO string; all rates + pct-changes are float64). A test reconciles this literal
# against the registry contract.
SILVER_ARROW_SCHEMA = pa.schema(
    [("date", pa.string())]
    + [f for c in _RATE_COLUMNS for f in (
        (c, pa.float64()), (f"{c}_pct_change_90d", pa.float64()))]
    + [("source", pa.string())]
)


def silver_arrow_schema() -> pa.Schema:
    return SILVER_ARROW_SCHEMA


def _pct_change_90d_calendar(dates: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Percent change vs the last observation at/before ``date - 90 calendar days``.

    ``dates`` is a sorted ``datetime64[ns]`` array; ``values`` a float array aligned to it.
    Returns a float array (NaN where no prior obs, or either endpoint null/zero).
    """
    targets = dates - np.timedelta64(_LAG_DAYS, "D")
    # index of the LAST date <= target (searchsorted 'right' - 1).
    idx = np.searchsorted(dates, targets, side="right") - 1
    valid = idx >= 0
    prior = np.full(values.shape, np.nan, dtype="float64")
    prior[valid] = values[idx[valid]]
    with np.errstate(divide="ignore", invalid="ignore"):
        pct = (values - prior) / prior * 100.0
    bad = (~valid) | np.isnan(prior) | (prior == 0.0) | np.isnan(values)
    pct[bad] = np.nan
    return np.round(pct, _PCT_ROUND)


def build_fx_silver(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Transform the long Frankfurter FX bronze into the wide daily silver.

    Args:
        df_bronze: Output of
            :func:`leviathan.transforms.raw_to_bronze.frankfurter_fx.extract_fx_bronze`
            (columns date, currency, rate_local_per_usd, source).

    Returns:
        Wide DataFrame with :data:`SILVER_COLUMNS`, one row per date, sorted ascending.

    Raises:
        ValueError: On missing required columns, empty input, or a broken date grain.
    """
    required = {"date", "currency", "rate_local_per_usd"}
    missing = required - set(df_bronze.columns)
    if missing:
        raise ValueError(f"Frankfurter FX bronze missing required columns: {missing}")
    if df_bronze.empty:
        raise ValueError("Frankfurter FX bronze is empty")

    # Pivot long -> wide on the mapped column names. Duplicate (date, currency) would raise
    # in pivot; the bronze transform already fails closed on conflicts, so this is a belt.
    wide = (
        df_bronze
        .assign(col=df_bronze["currency"].map(SERIES_MAP))
        .pivot(index="date", columns="col", values="rate_local_per_usd")
    )
    # Guarantee every configured rate column exists (an absent currency -> all-null column).
    for c in _RATE_COLUMNS:
        if c not in wide.columns:
            wide[c] = np.nan
    wide = wide[_RATE_COLUMNS].reset_index()

    # Date grain: one row per distinct date.
    if len(wide) != wide["date"].nunique():
        raise ValueError("Frankfurter FX silver: count(*) != count(DISTINCT date)")

    wide = wide.sort_values("date").reset_index(drop=True)
    date64 = pd.to_datetime(wide["date"]).to_numpy()

    for c in _RATE_COLUMNS:
        vals = wide[c].to_numpy(dtype="float64")
        wide[f"{c}_pct_change_90d"] = _pct_change_90d_calendar(date64, vals)
        wide[c] = wide[c].astype("float64")

    wide["source"] = SOURCE
    result = wide[SILVER_COLUMNS].reset_index(drop=True)

    # Hard grain assertion (INV): unique date, count(*) == count(DISTINCT date).
    assert len(result) == result["date"].nunique(), "date grain violated"

    # FX-1: the nonnull census loops the CONFIGURED columns -- the old literal brl/ars/cny line would
    # have reported three of thirteen and hidden a dead new currency on its first fire.
    nonnull = "  ".join(f"{c}={int(result[c].notna().sum())}" for c in _RATE_COLUMNS)
    logger.info(
        "Frankfurter FX silver: %d rows  range=%s..%s  nonnull: %s",
        len(result), result["date"].min(), result["date"].max(), nonnull,
    )
    return result
