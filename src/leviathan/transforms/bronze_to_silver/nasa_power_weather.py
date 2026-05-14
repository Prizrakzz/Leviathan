from __future__ import annotations

import pandas as pd

from leviathan.common.logging import get_logger


logger = get_logger(__name__)


WEATHER_RENAME_MAP = {
    "t2m": "temperature_2m_mean_c",
    "t2m_max": "temperature_2m_max_c",
    "t2m_min": "temperature_2m_min_c",
    "prectotcorr": "precipitation_mm",
    "rh2m": "relative_humidity_2m_pct",
    "ws2m": "wind_speed_2m_m_s",
    "allsky_sfc_sw_dwn": "solar_radiation_mj_m2_day",
}


def clean_one_weather_df(df: pd.DataFrame, source_label: str = "dataframe") -> pd.DataFrame:
    """Apply silver cleaning rules to an already-loaded bronze weather DataFrame.

    Returns a long/tidy DataFrame with one row per (date, variable) combination.
    Columns: date, year, month, day, country, region, commodity, source,
             ingest_date, variable, value.
    """
    required = {"date", "year", "month", "day", "country", "region", "commodity", "source"}
    missing = required - set(df.columns)

    if missing:
        raise ValueError(f"Missing required NASA POWER bronze columns in {source_label}: {missing}")

    df = df.copy()

    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["month"] = pd.to_numeric(df["month"], errors="coerce").astype("Int64")
    df["day"] = pd.to_numeric(df["day"], errors="coerce").astype("Int64")

    df = df.rename(columns=WEATHER_RENAME_MAP)

    weather_cols = list(WEATHER_RENAME_MAP.values())

    for col in weather_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Columns to keep before melt: identity + weather variable columns
    id_cols = [
        "date",
        "year",
        "month",
        "day",
        "country",
        "region",
        "commodity",
        "source",
        "ingest_date",
    ]
    present_weather_cols = [col for col in weather_cols if col in df.columns]
    keep_cols = id_cols + present_weather_cols

    silver = df[keep_cols].copy()

    silver = silver.dropna(subset=["date", "year", "month", "day", "country", "region"])
    silver["year"] = silver["year"].astype(int)
    silver["month"] = silver["month"].astype(int)
    silver["day"] = silver["day"].astype(int)

    # Dedup on wide format before melt (cheaper than post-melt dedup)
    silver = silver.drop_duplicates(
        subset=["date", "country", "region", "source"],
        keep="last",
    )

    silver = silver.melt(
        id_vars=id_cols,
        value_vars=present_weather_cols,
        var_name="variable",
        value_name="value",
    )

    silver = silver.dropna(subset=["value"])

    return silver.reset_index(drop=True)
