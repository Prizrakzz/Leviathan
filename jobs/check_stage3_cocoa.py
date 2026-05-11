from __future__ import annotations

from pathlib import Path

import pandas as pd


def count_files(root: Path, pattern: str) -> int:
    if not root.exists():
        return 0
    return len(list(root.rglob(pattern)))


def check_production() -> None:
    root = Path("data/silver/production/faostat/cocoa")
    files = sorted(root.rglob("*.parquet"))

    print("\nSILVER PRODUCTION")
    print("=" * 50)
    print(f"Files: {len(files)}")

    if not files:
        return

    df = pd.concat([pd.read_parquet(file) for file in files], ignore_index=True)

    print("Shape:", df.shape)
    print("Years:", df["year"].min(), "to", df["year"].max())
    print("Metrics:", sorted(df["metric"].unique()))
    print("Countries:", df["country"].nunique())

    dupes = df.duplicated(
        subset=["country_key", "commodity", "metric", "year", "source"]
    ).sum()

    print("Duplicate country/year/metric rows:", dupes)

    if "flag" in df.columns:
        print("\nFlag distribution:")
        print(df["flag"].value_counts(dropna=False))

    if "is_official" in df.columns:
        official_count = df["is_official"].sum()
        total = len(df)
        print(f"\nOfficial rows: {official_count}/{total} ({100 * official_count / total:.1f}%)")

        all_estimated = (
            df.groupby(["country_key", "metric"])["is_official"]
            .sum()
            .reset_index()
        )
        zero_official = all_estimated[all_estimated["is_official"] == 0]
        if not zero_official.empty:
            print("\nWARNING - country/metric combos with zero official rows:")
            print(zero_official)

    print(df.head())


def check_weather() -> None:
    root = Path("data/silver/weather/nasa_power/cocoa")
    files = sorted(root.rglob("*.parquet"))

    print("\nSILVER WEATHER")
    print("=" * 50)
    print(f"Files: {len(files)}")

    if not files:
        return

    df = pd.concat([pd.read_parquet(file) for file in files], ignore_index=True)

    print("Shape:", df.shape)
    print("Date range:", df["date"].min(), "to", df["date"].max())
    print("Countries:", df["country"].nunique())
    print("Regions:", df["region"].nunique())

    dupes = df.duplicated(
        subset=["date", "country", "region", "commodity", "source"]
    ).sum()

    print("Duplicate region/date rows:", dupes)

    weather_cols = [
        "temperature_2m_mean_c",
        "temperature_2m_max_c",
        "temperature_2m_min_c",
        "precipitation_mm",
        "relative_humidity_2m_pct",
        "wind_speed_2m_m_s",
        "solar_radiation_mj_m2_day",
    ]

    existing_weather_cols = [col for col in weather_cols if col in df.columns]

    print("\nNull counts:")
    print(df[existing_weather_cols].isna().sum())

    print("\nSample:")
    print(df.head())


def main() -> None:
    print("STAGE 3 COCOA SILVER CHECK")
    print("=" * 50)

    check_production()
    check_weather()


if __name__ == "__main__":
    main()

