from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.common.types import NasaPowerPayload

logger = get_logger(__name__)


def parse_nasa_power_date(date_value: str) -> str:
    """Parse a YYYYMMDD date key and return an ISO date string YYYY-MM-DD."""
    return datetime.strptime(date_value, "%Y%m%d").date().isoformat()


def extract_parameter_data(payload: NasaPowerPayload) -> dict[str, dict[str, float | int | None]]:
    """Expected shape: ``properties.parameter.<PARAM>.<YYYYMMDD> = value``."""
    try:
        return payload["properties"]["parameter"]
    except KeyError as exc:
        raise ValueError("NASA POWER payload missing properties.parameter") from exc


def nasa_power_payload_to_daily_dataframe(
    payload: NasaPowerPayload,
    source_file_name: str,
    commodity: str,
    country: str,
    region: str,
    ingest_date: str,
) -> pd.DataFrame:
    parameter_data = extract_parameter_data(payload)

    all_dates: set[str] = set()

    for values_by_date in parameter_data.values():
        all_dates.update(values_by_date.keys())

    records: list[dict[str, str | int | float | None]] = []

    for raw_date in sorted(all_dates):
        record: dict[str, str | int | float | None] = {
            "date": parse_nasa_power_date(raw_date),
            "year": int(raw_date[:4]),
            "month": int(raw_date[4:6]),
            "day": int(raw_date[6:8]),
            "source": "nasa_power",
            "commodity": commodity,
            "country": country,
            "region": region,
            "ingest_date": ingest_date,
            "source_file_name": source_file_name,
        }

        for parameter_name, values_by_date in parameter_data.items():
            column_name = parameter_name.lower()
            record[column_name] = values_by_date.get(raw_date)

        records.append(record)

    df = pd.DataFrame.from_records(records)

    if df.empty:
        raise ValueError(f"No daily records extracted from {source_file_name}")

    return df


def transform_nasa_power_json_to_bronze(
    raw_json_path: str | Path,
    output_base_dir: str | Path,
    commodity: str,
    country: str,
    region: str,
    ingest_date: str,
) -> Path:
    """Partitioning by country/region/year/month is the caller's responsibility."""
    raw_json_path = Path(raw_json_path)
    output_base_dir = Path(output_base_dir)

    if not raw_json_path.exists():
        raise FileNotFoundError(f"Raw NASA POWER JSON not found: {raw_json_path}")

    with raw_json_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    df = nasa_power_payload_to_daily_dataframe(
        payload=payload,
        source_file_name=raw_json_path.name,
        commodity=commodity,
        country=country,
        region=region,
        ingest_date=ingest_date,
    )

    years = df["year"].unique()
    months = df["month"].unique()

    if len(years) != 1 or len(months) != 1:
        raise ValueError(
            f"Expected one month per raw JSON file; found years={years}, months={months}"
        )

    year = int(years[0])
    month = int(months[0])

    output_dir = (
        output_base_dir
        / "source=nasa_power"
        / f"commodity={commodity}"
        / f"country={country}"
        / f"region={region}"
        / f"year={year}"
        / f"month={month:02d}"
    )

    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / "part-000.parquet"

    df.to_parquet(
        output_path,
        index=False,
        engine="pyarrow",
        compression="snappy",
    )

    logger.info("Wrote NASA POWER bronze Parquet: %s rows=%s", output_path, len(df))

    return output_path
