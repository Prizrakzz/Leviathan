from __future__ import annotations

from pathlib import Path

import pandas as pd


EXPECTED_WEATHER_START_YEAR = 1981


def load_parquet_dataset(root: Path) -> pd.DataFrame:
    files = sorted(root.rglob("*.parquet"))

    if not files:
        raise FileNotFoundError(f"No Parquet files found under {root}")

    return pd.concat([pd.read_parquet(file) for file in files], ignore_index=True)


def check_faostat_coverage() -> pd.DataFrame:
    root = Path("data/silver/production/faostat/cocoa")
    df = load_parquet_dataset(root)

    cocoa_yield = df[df["metric"].isin(["yield", "production_quantity", "area_harvested"])]

    print("\nFAOSTAT SILVER COVERAGE")
    print("=" * 60)
    print("Rows:", len(cocoa_yield))
    print("Years:", int(cocoa_yield["year"].min()), "->", int(cocoa_yield["year"].max()))
    print("Metrics:", sorted(cocoa_yield["metric"].dropna().unique()))
    print("Countries:", cocoa_yield["country_key"].nunique())

    return cocoa_yield


def check_weather_coverage() -> pd.DataFrame:
    root = Path("data/silver/weather/nasa_power/cocoa")
    df = load_parquet_dataset(root)

    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month

    print("\nNASA POWER SILVER COVERAGE")
    print("=" * 60)
    print("Rows:", len(df))
    print("Dates:", df["date"].min().date(), "->", df["date"].max().date())
    print("Years:", int(df["year"].min()), "->", int(df["year"].max()))
    print("Countries:", sorted(df["country"].dropna().unique()))
    print("Regions:", df[["country", "region"]].drop_duplicates().shape[0])

    return df


def check_missing_region_months(weather: pd.DataFrame) -> None:
    regions = weather[["country", "region"]].drop_duplicates()
    min_year = int(weather["year"].min())
    max_year = int(weather["year"].max())

    expected = []

    for _, row in regions.iterrows():
        for year in range(min_year, max_year + 1):
            for month in range(1, 13):
                expected.append(
                    {
                        "country": row["country"],
                        "region": row["region"],
                        "year": year,
                        "month": month,
                    }
                )

    expected_df = pd.DataFrame(expected)

    actual_df = weather[["country", "region", "year", "month"]].drop_duplicates()

    missing = expected_df.merge(
        actual_df,
        on=["country", "region", "year", "month"],
        how="left",
        indicator=True,
    )

    missing = missing[missing["_merge"] == "left_only"].drop(columns=["_merge"])

    print("\nMISSING WEATHER REGION-MONTH PARTITIONS")
    print("=" * 60)
    print("Missing region-months:", len(missing))

    if not missing.empty:
        print(missing.head(50))


def check_missing_days(weather: pd.DataFrame) -> None:
    print("\nMISSING WEATHER DAYS BY REGION")
    print("=" * 60)

    problems = []

    for (country, region), group in weather.groupby(["country", "region"]):
        min_date = group["date"].min()
        max_date = group["date"].max()

        expected_dates = pd.date_range(min_date, max_date, freq="D")
        actual_dates = pd.to_datetime(group["date"].drop_duplicates())

        missing_dates = expected_dates.difference(actual_dates)

        if len(missing_dates) > 0:
            problems.append(
                {
                    "country": country,
                    "region": region,
                    "min_date": min_date.date(),
                    "max_date": max_date.date(),
                    "missing_days": len(missing_dates),
                    "first_missing_day": missing_dates[0].date(),
                }
            )

    if not problems:
        print("No missing days inside each region's loaded date range.")
    else:
        print(pd.DataFrame(problems).head(50))


def check_overlap(faostat: pd.DataFrame, weather: pd.DataFrame) -> None:
    faostat_years = set(faostat["year"].dropna().astype(int).unique())
    weather_years = set(weather["year"].dropna().astype(int).unique())

    overlap_years = sorted(faostat_years.intersection(weather_years))

    print("\nML OVERLAP COVERAGE")
    print("=" * 60)

    if not overlap_years:
        print("No overlap between FAOSTAT years and NASA POWER weather years.")
        return

    print("Overlap years:", min(overlap_years), "->", max(overlap_years))
    print("Number of overlap years:", len(overlap_years))

    if min(overlap_years) > EXPECTED_WEATHER_START_YEAR:
        print(
            f"WARNING: overlap starts at {min(overlap_years)}, "
            f"but expected weather start year is {EXPECTED_WEATHER_START_YEAR}."
        )

    expected_years = set(range(min(overlap_years), max(overlap_years) + 1))
    missing_overlap_years = sorted(expected_years - set(overlap_years))

    if missing_overlap_years:
        print("Missing years inside overlap range:", missing_overlap_years)
    else:
        print("No missing years inside overlap range.")


def main() -> None:
    faostat = check_faostat_coverage()
    weather = check_weather_coverage()

    check_missing_region_months(weather)
    check_missing_days(weather)
    check_overlap(faostat, weather)


if __name__ == "__main__":
    main()
