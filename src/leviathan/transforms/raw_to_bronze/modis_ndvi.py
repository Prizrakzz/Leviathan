"""Parse an AppEEARS MODIS NDVI results CSV into per-region DataFrames.

AppEEARS CSV format (one row per sample point per composite date)
-----------------------------------------------------------------
Column names vary slightly by task name, but always contain:

    Category   — commodity name (our ``category`` field at submission)
    ID         — region name    (our ``id`` field at submission)
    Latitude
    Longitude
    Date       — YYYY-MM-DD (start of the 16-day composite)
    MOD13Q1_061__250m_16_days_NDVI
    MOD13Q1_061__250m_16_days_pixel_reliability

AppEEARS applies the product scale factor to valid pixels before exporting
to CSV, so NDVI values arrive as physical floats (range ~-0.2 to 1.0) rather
than raw int16.  Fill pixels are output with their raw fill sentinel:
- NDVI fill   : -3000.0  (raw int16 fill = -3000, physical equivalent -0.3)
- Quality fill: -1.0     (raw int8 fill  = -1)

MODIS 16-day period number
--------------------------
Periods 1–23 within a calendar year, derived from day-of-year (DOY):

    period = (DOY - 1) // 16 + 1

This yields 22 complete 16-day periods (352 days) plus period 23 which
covers the remaining 13–14 days of the year.
"""
from __future__ import annotations

import io
from datetime import datetime

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# AppEEARS returns physical float values; fill pixels keep their raw sentinel.
_NDVI_PHYSICAL_MIN = -0.3  # slightly below valid min (-0.2) to catch fill sentinel -3000.0
_NDVI_PHYSICAL_MAX = 1.0   # valid MODIS NDVI physical max


def _find_column(df: pd.DataFrame, substring: str) -> str:
    """Return the first column name that contains *substring* (case-insensitive)."""
    matches = [c for c in df.columns if substring.lower() in c.lower()]
    if not matches:
        raise ValueError(
            f"No column containing '{substring}' found in CSV. "
            f"Available columns: {list(df.columns)}"
        )
    return matches[0]


def parse_appeears_csv(
    csv_bytes: bytes,
    region_to_country: dict[str, str],
    ingest_date: str,
) -> pd.DataFrame:
    """Parse a raw AppEEARS results CSV into a clean bronze DataFrame.

    Args:
        csv_bytes:          Raw bytes of the AppEEARS results CSV.
        region_to_country:  Mapping of region_id → country name, built from
                            geography configs.  Used to add the ``country``
                            column that is not present in the CSV itself.
        ingest_date:        ISO date string ``YYYY-MM-DD`` stamped on every row.

    Returns:
        DataFrame with columns:
            date, year, period, commodity, country, region,
            latitude, longitude, ndvi_raw, ndvi, pixel_reliability, ingest_date
        Rows with fill values or unknown regions are dropped.
    """
    df = pd.read_csv(io.BytesIO(csv_bytes))

    # Normalise column names: strip whitespace
    df.columns = [c.strip() for c in df.columns]

    # Locate the key columns by substring rather than exact name so we are
    # resilient to minor AppEEARS naming changes across versions.
    ndvi_col = _find_column(df, "NDVI")
    quality_col = _find_column(df, "pixel_reliability")

    # Rename to canonical names
    df = df.rename(columns={
        "ID": "region",
        "Category": "commodity",
        "Latitude": "latitude",
        "Longitude": "longitude",
        "Date": "date",
        ndvi_col: "ndvi_raw",
        quality_col: "pixel_reliability",
    })

    required = {"region", "commodity", "latitude", "longitude", "date", "ndvi_raw", "pixel_reliability"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"AppEEARS CSV missing expected columns after rename: {missing}")

    # Deduplicate: AppEEARS may emit the same (commodity, region, date) more than once.
    # NOTE: must include "commodity" in the key — a single CSV can contain multiple
    # commodities that share region IDs (e.g. soybean_oil_cbot and soybeans_cbot both
    # use ar_soy_buenos_aires).  Deduplicating on (region, date) alone would silently
    # discard all but the first commodity's rows for shared regions.
    before_dedup = len(df)
    df = df.drop_duplicates(subset=["commodity", "region", "date"])
    if len(df) < before_dedup:
        logger.warning("Dropped %d duplicate (commodity, region, date) rows", before_dedup - len(df))

    # Parse date and derive year + MODIS period
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    bad_dates = df["date"].isna().sum()
    if bad_dates:
        logger.warning("Dropped %d rows with unparseable dates", bad_dates)
    df = df.dropna(subset=["date"])
    df["year"] = df["date"].apply(lambda d: d.year).astype("int16")
    df["period"] = df["date"].apply(
        lambda d: (datetime(d.year, d.month, d.day).timetuple().tm_yday - 1) // 16 + 1
    ).astype("int8")

    # Cast numeric columns
    # ndvi_raw: AppEEARS delivers pre-scaled physical floats (valid range -0.2..1.0)
    df["ndvi_raw"] = pd.to_numeric(df["ndvi_raw"], errors="coerce").astype("float32")
    # pixel_reliability: integer quality code 0-3; fill = -1 (fits in Int8)
    df["pixel_reliability"] = pd.to_numeric(df["pixel_reliability"], errors="coerce").astype("Int8")
    df["latitude"] = df["latitude"].astype("float32")
    df["longitude"] = df["longitude"].astype("float32")

    # Drop fill / out-of-range values (fill sentinel = -3000.0; valid physical range -0.2..1.0)
    before = len(df)
    df = df[
        df["ndvi_raw"].notna()
        & (df["ndvi_raw"] >= _NDVI_PHYSICAL_MIN)
        & (df["ndvi_raw"] <= _NDVI_PHYSICAL_MAX)
    ]
    dropped = before - len(df)
    if dropped:
        logger.debug("Dropped %d fill/out-of-range NDVI rows", dropped)

    # ndvi mirrors ndvi_raw (AppEEARS already applied the scale factor)
    df["ndvi"] = df["ndvi_raw"]

    # Add country from region lookup
    df["country"] = df["region"].map(region_to_country)
    unknown = df["country"].isna().sum()
    if unknown:
        unknown_regions = df[df["country"].isna()]["region"].unique().tolist()
        logger.warning(
            "Dropping %d rows with unknown region→country mapping: %s",
            unknown, unknown_regions[:10],
        )
        df = df.dropna(subset=["country"])

    df["ingest_date"] = ingest_date

    # Final column order
    cols = [
        "date", "year", "period",
        "commodity", "country", "region",
        "latitude", "longitude",
        "ndvi_raw", "ndvi", "pixel_reliability",
        "ingest_date",
    ]
    df = df[cols].copy()

    logger.info(
        "Parsed AppEEARS CSV: %d rows, %d unique regions, years %s–%s",
        len(df),
        df["region"].nunique(),
        int(df["year"].min()),
        int(df["year"].max()),
    )
    return df.reset_index(drop=True)
