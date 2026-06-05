"""Bronze transform for Quandl CHRIS continuous futures JSON files.

Parses the Nasdaq Data Link (formerly Quandl) CHRIS dataset JSON response
for a single (slug, tenor) series.

CHRIS dataset
-------------
The Continuous Rolling Contracts dataset (CHRIS) provides roll-adjusted
continuous series for each commodity.  C1 = front month (1st nearby),
C2 = 2nd nearby, C3 = 3rd nearby.  The roll adjustment uses the
Panama canal (backward adjustment) method — all historical prices are
adjusted so there are no gaps at roll dates.  This makes CHRIS suitable
for return-based calculations (momentum, spread z-scores) without any
roll masking.

API endpoint
------------
    https://data.nasdaq.com/api/v3/datasets/{dataset_id}.json
        ?api_key={key}&start_date={YYYY-MM-DD}

Response structure:
    {"dataset": {
        "column_names": ["Date", "Open", "High", "Low", "Last", "Change",
                         "Settle", "Volume", "Open Interest", ...],
        "data": [["2026-06-04", 423.25, 425.0, ...], ...]
    }}

Key column: ``Settle`` (official daily settlement price from the exchange).
This is superior to yfinance's ``Close`` (last trade price) for spread
calculations — settlement is the authoritative closing price used by the
exchange for margin calls and mark-to-market.

Dataset ID mapping
------------------
Format: ``CHRIS/{exchange}_{symbol}{tenor}``
  corn_cbot                  CHRIS/CME_C{1,2,3}
  soybeans_cbot              CHRIS/CME_S{1,2,3}
  soybean_oil_cbot           CHRIS/CME_BO{1,2,3}
  soybean_meal_cbot          CHRIS/CME_SM{1,2,3}
  soft_red_winter_wheat_cbot CHRIS/CME_W{1,2,3}
  hard_red_winter_wheat_kcbt CHRIS/CME_KW{1,2,3}
  arabica_coffee             CHRIS/ICE_KC{1,2,3}
  cocoa                      CHRIS/ICE_CC{1,2,3}
  cotton                     CHRIS/ICE_CT{1,2,3}
  raw_sugar                  CHRIS/ICE_SB{1,2,3}
  rough_rice_cbot            CHRIS/CME_RR{1,2,3}  (may end ~2021 — verify)
  frozen_orange_juice        CHRIS/ICE_OJ{1,2,3}
"""
from __future__ import annotations

import json

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

BRONZE_COLUMNS: list[str] = [
    "date",
    "leviathan_slug",
    "tenor",
    "settle",
    "volume",
    "open_interest",
    "source",
]

# Column names as returned by Quandl CHRIS (case-insensitive match below)
_SETTLE_CANDIDATES   = {"settle", "settlement price", "last settle"}
_VOLUME_CANDIDATES   = {"volume", "vol"}
_OI_CANDIDATES       = {"open interest", "openinterest", "prev. day open interest",
                         "previous day open interest"}


def _find_col(column_names: list[str], candidates: set[str]) -> int | None:
    """Return the index of the first column name matching any candidate."""
    for i, name in enumerate(column_names):
        if name.lower() in candidates:
            return i
    return None


def extract_chris_bronze(
    raw_bytes: bytes,
    slug: str,
    tenor: int,
    dataset_id: str,
) -> pd.DataFrame:
    """Parse a Quandl CHRIS JSON response into bronze Parquet.

    Args:
        raw_bytes:  Raw bytes of the ``part-000.json`` from S3.
        slug:       Leviathan slug, e.g. ``"corn_cbot"``.
        tenor:      1, 2, or 3.
        dataset_id: Full Quandl dataset ID, e.g. ``"CHRIS/CME_C1"``.

    Returns:
        DataFrame with columns :data:`BRONZE_COLUMNS`, sorted ascending
        by date.

    Raises:
        ValueError: If the JSON is malformed or no parseable rows found.
    """
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"CHRIS {dataset_id}: invalid JSON — {exc}") from exc

    dataset = payload.get("dataset", {})
    col_names: list[str] = dataset.get("column_names", [])
    data_rows: list[list] = dataset.get("data", [])

    if not data_rows:
        # Quandl may return empty data for discontinued contracts
        logger.warning("CHRIS %s: no data rows — contract may be discontinued", dataset_id)
        return pd.DataFrame(columns=BRONZE_COLUMNS)

    # Locate required columns by name (Quandl column order can vary)
    # Column 0 is always Date
    settle_idx = _find_col(col_names, _SETTLE_CANDIDATES)
    vol_idx    = _find_col(col_names, _VOLUME_CANDIDATES)
    oi_idx     = _find_col(col_names, _OI_CANDIDATES)

    if settle_idx is None:
        raise ValueError(
            f"CHRIS {dataset_id}: 'Settle' column not found in {col_names}"
        )

    rows = []
    for row in data_rows:
        try:
            date    = pd.to_datetime(row[0]).date()
            settle  = float(row[settle_idx]) if row[settle_idx] is not None else None
            volume  = int(row[vol_idx]) if (vol_idx is not None and row[vol_idx] is not None) else 0
            oi      = int(row[oi_idx]) if (oi_idx is not None and row[oi_idx] is not None) else 0
        except (ValueError, TypeError, IndexError):
            continue
        if settle is not None and settle > 0:
            rows.append({
                "date":           date,
                "leviathan_slug": slug,
                "tenor":          tenor,
                "settle":         settle,
                "volume":         volume,
                "open_interest":  oi,
            })

    if not rows:
        raise ValueError(f"CHRIS {dataset_id}: no valid rows after parsing")

    df = pd.DataFrame(rows)
    df["settle"]         = df["settle"].astype("float32")
    df["volume"]         = df["volume"].astype("int64")
    df["open_interest"]  = df["open_interest"].astype("int64")
    df["source"]         = "quandl_chris"

    df = (
        df[BRONZE_COLUMNS]
        .sort_values("date")
        .reset_index(drop=True)
    )

    logger.info(
        "CHRIS bronze %s (C%d): %d rows  %s – %s  settle_last=%.2f",
        slug, tenor, len(df),
        str(df["date"].iloc[0]), str(df["date"].iloc[-1]),
        float(df["settle"].iloc[-1]),
    )
    return df
