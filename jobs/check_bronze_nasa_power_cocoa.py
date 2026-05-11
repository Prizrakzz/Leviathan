from __future__ import annotations

from pathlib import Path

import pandas as pd


def main() -> None:
    bronze_root = Path("data/bronze/weather/nasa_power/cocoa")

    parquet_files = sorted(bronze_root.rglob("*.parquet"))

    if not parquet_files:
        raise FileNotFoundError(f"No Parquet files found under {bronze_root}")

    print(f"Found bronze Parquet files: {len(parquet_files)}")

    frames = []

    for file in parquet_files:
        df = pd.read_parquet(file)
        df["bronze_file"] = str(file)
        frames.append(df)

    all_df = pd.concat(frames, ignore_index=True)

    print("\nShape:")
    print(all_df.shape)

    print("\nColumns:")
    print(list(all_df.columns))

    print("\nDate range:")
    print(all_df["date"].min(), "→", all_df["date"].max())

    print("\nCountries:")
    print(all_df["country"].value_counts())

    print("\nRegions:")
    print(all_df["region"].value_counts())

    print("\nNull counts for weather variables:")
    weather_cols = [
        col
        for col in all_df.columns
        if col
        not in {
            "date",
            "year",
            "month",
            "day",
            "source",
            "commodity",
            "country",
            "region",
            "ingest_date",
            "source_file_name",
            "bronze_file",
        }
    ]

    print(all_df[weather_cols].isna().sum())

    print("\nSample:")
    print(all_df.head(10))


if __name__ == "__main__":
    main()