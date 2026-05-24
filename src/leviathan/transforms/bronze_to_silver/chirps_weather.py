from __future__ import annotations

import pandas as pd

from leviathan.common.constants import SILVER_WEATHER_ID_COLS
from leviathan.common.logging import get_logger

logger = get_logger(__name__)

_REQUIRED_BRONZE_COLS = set(SILVER_WEATHER_ID_COLS) | {"precipitation_mm"}


def chirps_bronze_to_silver(df: pd.DataFrame, source_label: str = "dataframe") -> pd.DataFrame:
    """Apply silver cleaning rules to a CHIRPS bronze DataFrame.

    Returns a long/tidy DataFrame with one row per (date, region, variable).
    Columns: date, year, month, day, country, region, commodity, source,
             ingest_date, variable, value.
    """
    missing = _REQUIRED_BRONZE_COLS - set(df.columns)
    if missing:
        raise ValueError(f"Missing required CHIRPS bronze columns in {source_label}: {missing}")

    df = df.copy()

    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["month"] = pd.to_numeric(df["month"], errors="coerce").astype("Int64")
    df["day"] = pd.to_numeric(df["day"], errors="coerce").astype("Int64")
    df["precipitation_mm"] = pd.to_numeric(df["precipitation_mm"], errors="coerce")

    df = df.dropna(subset=["date", "year", "month", "day", "country", "region"])
    df["year"] = df["year"].astype(int)
    df["month"] = df["month"].astype(int)
    df["day"] = df["day"].astype(int)

    df = df.drop_duplicates(
        subset=["date", "country", "region", "source"],
        keep="last",
    )

    silver = df[list(SILVER_WEATHER_ID_COLS) + ["precipitation_mm"]].copy()

    silver = silver.melt(
        id_vars=SILVER_WEATHER_ID_COLS,
        value_vars=["precipitation_mm"],
        var_name="variable",
        value_name="value",
    )

    silver = silver.sort_values(["country", "region", "date"]).reset_index(drop=True)
    logger.info("CHIRPS silver transform: %d rows → %d long rows", len(df), len(silver))
    return silver
