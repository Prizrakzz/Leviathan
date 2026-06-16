from __future__ import annotations

import pandas as pd

from leviathan.common.constants import SILVER_WEATHER_ID_COLS


def melt_weather_to_long(
    df: pd.DataFrame,
    variable_col: str,
    source_label: str,
) -> pd.DataFrame:
    """Clean, deduplicate, and melt a weather bronze DataFrame to long format.

    Shared by the CHIRPS and CPC soil moisture bronze→silver transforms.
    *variable_col* is the single measurement column to melt (e.g.
    ``"precipitation_mm"`` or ``"soil_moisture_mm"``).

    Steps applied:
    1. Coerce date/year/month/day and the measurement column to correct types.
    2. Drop rows missing any id column or the date columns.
    3. Deduplicate on (date, country, region, source), keeping last.
    4. Melt to long format with ``variable`` / ``value`` columns.
    5. Sort by country, region, date.

    Returns a long DataFrame with columns matching ``SILVER_WEATHER_ID_COLS``
    plus ``variable`` and ``value``.
    """
    required = set(SILVER_WEATHER_ID_COLS) | {variable_col}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"Missing required bronze columns in {source_label}: {missing}"
        )

    df = df.copy()

    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["month"] = pd.to_numeric(df["month"], errors="coerce").astype("Int64")
    df["day"] = pd.to_numeric(df["day"], errors="coerce").astype("Int64")
    df[variable_col] = pd.to_numeric(df[variable_col], errors="coerce")

    df = df.dropna(subset=["date", "year", "month", "day", "country", "region"])
    df["year"] = df["year"].astype(int)
    df["month"] = df["month"].astype(int)
    df["day"] = df["day"].astype(int)

    df = df.drop_duplicates(
        subset=["date", "country", "region", "source"],
        keep="last",
    )

    silver = df[list(SILVER_WEATHER_ID_COLS) + [variable_col]].copy()

    silver = silver.melt(
        id_vars=SILVER_WEATHER_ID_COLS,
        value_vars=[variable_col],
        var_name="variable",
        value_name="value",
    )

    silver = silver.dropna(subset=["value"])

    return silver.sort_values(["country", "region", "date"]).reset_index(drop=True)
