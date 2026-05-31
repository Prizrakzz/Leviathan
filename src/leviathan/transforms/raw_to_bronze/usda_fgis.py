"""Bronze transform for USDA AMS FGIS Export Inspection data.

Converts per-year CSV files from S3 raw into typed bronze Parquets.

Granularity
-----------
One row per shipment inspection (per-shipment).  Aggregation to weekly
or monthly export volumes is deferred to silver.

Marketing year derivation
-------------------------
A ``marketing_year`` column is computed from grain type and inspection date:

    WHEAT (all classes), OATS : Jun 1 – May 31
    All other grains           : Sep 1 – Aug 31

The ``marketing_year`` value is the calendar year in which the season starts
(e.g. 2024 for the 2024/25 season).

Units
-----
``mt``     — metric tonnes (as reported by FGIS)
``pounds`` — US pounds (as reported by FGIS; redundant but preserved)
"""
from __future__ import annotations

import io

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# Grain types that use a June 1 marketing-year start.
_WHEAT_GRAINS: frozenset[str] = frozenset({
    "WHEAT",
    "HRW",
    "HRS",
    "SRW",
    "SOFT WHITE WHEAT",
    "HARD WHITE WHEAT",
    "DURUM WHEAT",
    "WHITE WHEAT",
    "OATS",
})

_DATE_COLS = ("date", "cert_date")
_FLOAT_COLS = frozenset({"mt", "pounds"})
_INT_COLS = frozenset({"week", "month", "quarter", "year"})


def _add_marketing_year(df: pd.DataFrame) -> pd.DataFrame:
    """Add a vectorised ``marketing_year`` column derived from grain and date."""
    # Prefer cert_date (post-2018 FGIS format); fall back to date (legacy format).
    if "cert_date" in df.columns:
        raw_date = df["cert_date"]
    else:
        raw_date = df.get("date", pd.Series(dtype="object"))
    date_ser = pd.to_datetime(raw_date, errors="coerce")
    grain_upper = df.get("grain", pd.Series(dtype="object")).astype(str).str.strip().str.upper()

    is_wheat = grain_upper.isin(_WHEAT_GRAINS)
    cal_year = date_ser.dt.year.fillna(
        df.get("year", pd.Series(0, index=df.index))
    ).astype(int)
    month = date_ser.dt.month.fillna(1).astype(int)

    # Jun-start: MY = cal_year if month >= 6 else cal_year - 1
    wheat_my = cal_year.where(month >= 6, cal_year - 1)
    # Sep-start: MY = cal_year if month >= 9 else cal_year - 1
    other_my = cal_year.where(month >= 9, cal_year - 1)

    df["marketing_year"] = wheat_my.where(is_wheat, other_my).astype("Int64")
    return df


def extract_fgis(
    raw_bytes: bytes,
    release_year: int,
    ingest_date: str,
) -> pd.DataFrame:
    """Parse a raw FGIS annual CSV into a typed bronze DataFrame.

    Args:
        raw_bytes:    Raw CSV bytes as stored in S3.
        release_year: Calendar year of the file (from ``CY{year}.csv``).
        ingest_date:  ISO date string (``YYYY-MM-DD``) when the bronze was written.

    Returns:
        DataFrame with bronze schema; one row per shipment inspection.

    Raises:
        ValueError: If the CSV is empty after parsing.
    """
    df = pd.read_csv(io.BytesIO(raw_bytes), low_memory=False)

    if df.empty:
        raise ValueError(f"FGIS CSV for year {release_year} is empty")

    # Normalize column names to snake_case
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # Parse date columns
    for col in _DATE_COLS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date

    # Numeric type casts
    for col in _INT_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in _FLOAT_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Derived marketing year
    df = _add_marketing_year(df)

    # Bronze metadata
    df["source"] = "usda_fgis_export_inspections"
    df["release_year"] = release_year
    df["ingest_date"] = ingest_date

    logger.info("FGIS year=%d  rows=%d", release_year, len(df))
    return df
