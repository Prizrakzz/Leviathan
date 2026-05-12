from __future__ import annotations

from pathlib import Path

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


def load_bronze_weather(bronze_root: str | Path) -> list[Path]:
    bronze_root = Path(bronze_root)
    parquet_files = sorted(bronze_root.rglob("*.parquet"))

    if not parquet_files:
        raise FileNotFoundError(f"No bronze NASA POWER Parquet files found under {bronze_root}")

    return parquet_files


def clean_one_weather_df(df: pd.DataFrame, source_label: str = "dataframe") -> pd.DataFrame:
    """Apply silver cleaning rules to an already-loaded bronze weather DataFrame.

    This is the core transform.  ``clean_one_weather_file`` is a thin wrapper
    that reads from a local Path before delegating here.  Glue jobs that read
    from S3 directly should call this function instead.
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

    keep_cols = [
        "date",
        "year",
        "month",
        "day",
        "country",
        "region",
        "commodity",
        "source",
        "ingest_date",
        "source_file_name",
    ]

    for col in weather_cols:
        if col in df.columns:
            keep_cols.append(col)

    silver = df[keep_cols].copy()

    silver = silver.dropna(subset=["date", "year", "month", "day", "country", "region"])
    silver["year"] = silver["year"].astype(int)
    silver["month"] = silver["month"].astype(int)
    silver["day"] = silver["day"].astype(int)

    silver = silver.drop_duplicates(
        subset=["date", "country", "region", "commodity", "source"],
        keep="last",
    )

    return silver


def clean_one_weather_file(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    return clean_one_weather_df(df, source_label=str(path))


def transform_nasa_power_weather_to_silver(
    bronze_root: str | Path,
    output_root: str | Path,
) -> list[Path]:
    parquet_files = load_bronze_weather(bronze_root)
    output_root = Path(output_root)

    written_files: list[Path] = []

    for bronze_file in parquet_files:
        silver = clean_one_weather_file(bronze_file)

        if silver.empty:
            logger.warning("Skipping empty silver weather output for %s", bronze_file)
            continue

        country = silver["country"].iloc[0]
        region = silver["region"].iloc[0]
        year = int(silver["year"].iloc[0])
        month = int(silver["month"].iloc[0])

        output_dir = (
            output_root
            / "source=nasa_power"
            / "commodity=cocoa"
            / f"country={country}"
            / f"region={region}"
            / f"year={year}"
            / f"month={month:02d}"
        )

        output_dir.mkdir(parents=True, exist_ok=True)

        output_path = output_dir / "part-000.parquet"

        silver.to_parquet(
            output_path,
            index=False,
            engine="pyarrow",
            compression="snappy",
        )

        logger.info("Wrote silver NASA POWER weather file: %s rows=%s", output_path, len(silver))
        written_files.append(output_path)

    return written_files