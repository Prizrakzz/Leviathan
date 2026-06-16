from __future__ import annotations

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.transforms.bronze_to_silver._weather_long import melt_weather_to_long

logger = get_logger(__name__)


def chirps_bronze_to_silver(df: pd.DataFrame, source_label: str = "dataframe") -> pd.DataFrame:
    """Apply silver cleaning rules to a CHIRPS bronze DataFrame.

    Returns a long/tidy DataFrame with one row per (date, region, variable).
    Columns: date, year, month, day, country, region, commodity, source,
             ingest_date, variable, value.
    """
    df = df.copy()
    df["precipitation_mm"] = df["precipitation_mm"].clip(lower=0.0)
    silver = melt_weather_to_long(df, "precipitation_mm", source_label)
    logger.info("CHIRPS silver transform: %d input rows → %d long rows", len(df), len(silver))
    return silver
