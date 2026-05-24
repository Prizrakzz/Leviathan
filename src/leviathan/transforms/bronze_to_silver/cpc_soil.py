from __future__ import annotations

import pandas as pd

from leviathan.common.constants import SILVER_WEATHER_ID_COLS
from leviathan.common.logging import get_logger

logger = get_logger(__name__)

_REQUIRED_BRONZE_COLS = set(SILVER_WEATHER_ID_COLS) | {"soil_moisture_mm"}


def cpc_soil_bronze_to_silver(df: pd.DataFrame, source_label: str = "dataframe") -> pd.DataFrame:
    """Apply silver cleaning rules to a CPC soil moisture bronze DataFrame.

    Returns a long/tidy DataFrame with one row per (date, region, variable).
    Columns: date, year, month, day, country, region, commodity, source,
             ingest_date, variable, value.

    The bronze ``variable`` column (CPC code, e.g. ``"w"``) and the
    ``latitude``/``longitude`` columns are dropped — they are not part of the
    silver schema.
    """
    missing = _REQUIRED_BRONZE_COLS - set(df.columns)
    if missing:
        raise ValueError(
            f"Missing required CPC soil bronze columns in {source_label}: {missing}"
        )

    df = df.copy()

    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["month"] = pd.to_numeric(df["month"], errors="coerce").astype("Int64")
    df["day"] = pd.to_numeric(df["day"], errors="coerce").astype("Int64")
    df["soil_moisture_mm"] = pd.to_numeric(df["soil_moisture_mm"], errors="coerce")

    df = df.dropna(subset=["date", "year", "month", "day", "country", "region"])
    df["year"] = df["year"].astype(int)
    df["month"] = df["month"].astype(int)
    df["day"] = df["day"].astype(int)

    df = df.drop_duplicates(
        subset=["date", "country", "region", "source"],
        keep="last",
    )

    silver = df[list(SILVER_WEATHER_ID_COLS) + ["soil_moisture_mm"]].copy()

    silver = silver.melt(
        id_vars=SILVER_WEATHER_ID_COLS,
        value_vars=["soil_moisture_mm"],
        var_name="variable",
        value_name="value",
    )

    silver = silver.sort_values(["country", "region", "date"]).reset_index(drop=True)
    logger.info(
        "CPC soil silver transform: %d rows → %d long rows", len(df), len(silver)
    )
    return silver
