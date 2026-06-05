"""Bronze transform for yfinance futures continuous front-month OHLCV.

Reads the raw OHLCV Parquet stored by the ingest script and adds:

  is_roll_date
    True when ``abs(close / close_prev - 1) > 0.05`` (5% threshold).
    Continuous futures contracts are stitched unadjusted at each roll —
    the price "jumps" by the spread between expiring and new front month.
    Corn rolls ~July 14-15 each year (Jul→Dec) producing 17–23% artifacts.
    The 5% threshold is empirical and catches all confirmed roll artifacts
    while rarely firing on genuine single-day price moves (most commodity
    futures have circuit breakers well below 5%).

  log_return
    ``ln(close / close_prev)`` set to NaN on roll dates.
    Roll dates contribute zero information about economic price movement;
    NaN signals the downstream silver transform to exclude them from
    return-based calculations.

Roll count by contract (confirmed from live testing, 2000-2026):
  corn_cbot=113, soybean_meal_cbot=123, arabica_coffee=196, cocoa=224,
  frozen_orange_juice=270, raw_sugar=176.  Higher counts for illiquid
  softs reflect more frequent roll schedules and thinner markets.

Data note
---------
yfinance returns unadjusted price levels for futures — ``auto_adjust=True``
only adjusts for equity splits/dividends, not futures roll gaps.  The raw
close price is suitable for level features (z-score vs rolling mean) but
not for return-based features without roll masking.
"""
from __future__ import annotations

import io
import math

import numpy as np
import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# Empirical roll detection threshold — single-day |pct_change| exceeding
# this almost certainly represents a roll gap, not a genuine price event.
_ROLL_THRESHOLD = 0.05   # 5%

# Ticker map — confirmed live 2026-06-05 (all 12 return ≥5,000 rows)
TICKER_MAP: dict[str, str] = {
    "corn_cbot":                    "ZC=F",
    "soybeans_cbot":                "ZS=F",
    "soybean_oil_cbot":             "ZL=F",
    "soybean_meal_cbot":            "ZM=F",
    "soft_red_winter_wheat_cbot":   "ZW=F",
    "hard_red_winter_wheat_kcbt":   "KE=F",
    "arabica_coffee":               "KC=F",
    "cocoa":                        "CC=F",
    "cotton":                       "CT=F",
    "raw_sugar":                    "SB=F",
    "rough_rice_cbot":              "ZR=F",
    "frozen_orange_juice":          "OJ=F",
}

BRONZE_COLUMNS: list[str] = [
    "date",
    "leviathan_slug",
    "ticker",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "log_return",
    "is_roll_date",
    "source",
]


def extract_yfinance_bronze(
    raw_bytes: bytes,
    slug: str,
    ticker: str,
) -> pd.DataFrame:
    """Parse a raw yfinance OHLCV Parquet into bronze.

    Args:
        raw_bytes: Raw bytes of the per-slug raw Parquet from S3.
        slug:      Leviathan slug, e.g. ``"corn_cbot"``.
        ticker:    Yahoo Finance ticker, e.g. ``"ZC=F"``.

    Returns:
        DataFrame with columns :data:`BRONZE_COLUMNS`, sorted by date.

    Raises:
        ValueError: If the raw file is empty or missing required columns.
    """
    df = pd.read_parquet(io.BytesIO(raw_bytes))

    if df.empty:
        raise ValueError(f"yfinance bronze {slug}: raw Parquet is empty")

    # Normalise column names — yfinance may return MultiIndex columns
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Lowercase column names
    df.columns = [c.lower() for c in df.columns]

    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"yfinance bronze {slug}: missing columns {missing}")

    df = df.reset_index()  # date is the index in yfinance downloads
    # Normalise date column name (yfinance uses 'Date' or 'Datetime')
    date_col = next((c for c in df.columns if c.lower() == "date"), None)
    if date_col is None:
        raise ValueError(f"yfinance bronze {slug}: no date column found")
    df = df.rename(columns={date_col: "date"})
    df["date"] = pd.to_datetime(df["date"]).dt.date

    # Cast price columns
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float32")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")

    # Drop rows with zero or negative close (data quality error)
    bad_price = (df["close"].isna()) | (df["close"] <= 0)
    if bad_price.any():
        logger.warning(
            "yfinance bronze %s: dropping %d rows with null/non-positive close",
            slug, int(bad_price.sum()),
        )
        df = df[~bad_price].copy()

    df = df.sort_values("date").reset_index(drop=True)

    # Roll detection
    pct_chg = df["close"].pct_change().abs()
    df["is_roll_date"] = pct_chg > _ROLL_THRESHOLD

    # Log return — NaN on roll dates (roll = zero economic information)
    raw_log_ret = np.log(df["close"] / df["close"].shift(1))
    df["log_return"] = raw_log_ret.where(~df["is_roll_date"]).astype("float32")

    df["leviathan_slug"] = slug
    df["ticker"]         = ticker
    df["source"]         = "yfinance"

    result = df[BRONZE_COLUMNS].reset_index(drop=True)

    roll_count = int(df["is_roll_date"].sum())
    logger.info(
        "yfinance bronze %s: %d rows  %s – %s  rolls=%d",
        slug, len(result),
        str(result["date"].iloc[0]), str(result["date"].iloc[-1]),
        roll_count,
    )
    return result
