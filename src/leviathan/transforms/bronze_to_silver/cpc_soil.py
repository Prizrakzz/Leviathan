from __future__ import annotations

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.transforms.bronze_to_silver._weather_long import melt_weather_to_long

logger = get_logger(__name__)


def cpc_soil_bronze_to_silver(df: pd.DataFrame, source_label: str = "dataframe") -> pd.DataFrame:
    """Apply silver cleaning rules to a CPC soil moisture bronze DataFrame.

    Returns a long/tidy DataFrame with one row per (date, region, variable).
    Columns: date, year, month, day, country, region, commodity, source,
             ingest_date, variable, value.

    The bronze ``variable`` column (CPC code, e.g. ``"w"``) and the
    ``latitude``/``longitude`` columns are dropped — they are not part of the
    silver schema.
    """
    silver = melt_weather_to_long(df, "soil_moisture_mm", source_label)
    logger.info(
        "CPC soil silver transform: %d input rows → %d long rows", len(df), len(silver)
    )
    return silver
