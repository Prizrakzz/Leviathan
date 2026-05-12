"""ML join overlap check — all queries run via Athena inside AWS.

Verifies that every config country appears in both silver datasets and that
every (country, year) in the 1981-2023 overlap window has data in both.

Run: python jobs/check_ml_overlap_coverage_cocoa.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from athena_utils import ATHENA_DB, ensure_catalog, run_query

COMMODITY = os.environ.get("LEVIATHAN_COMMODITY", "cocoa")
OVERLAP_START = 1981
OVERLAP_END = 2023
CONFIG_PATH = Path("configs/geographies/cocoa_regions.yaml")


def load_config() -> tuple[list[str], list[str]]:
    with CONFIG_PATH.open() as f:
        config = yaml.safe_load(f)
    countries = [r["country"] for r in config["regions"]]
    regions = [loc["region"] for r in config["regions"] for loc in r["locations"]]
    return countries, regions


def check_country_overlap(athena, countries: list[str]) -> None:
    print("\nCOUNTRY-LEVEL OVERLAP")
    print("=" * 70)

    fao_rows = run_query(athena, f"SELECT DISTINCT country_key FROM {ATHENA_DB}.silver_production")
    wthr_rows = run_query(athena, f"SELECT DISTINCT country    FROM {ATHENA_DB}.silver_weather")

    fao_keys = {r["country_key"] for r in fao_rows}
    wthr_keys = {r["country"] for r in wthr_rows}
    cfg_set = set(countries)

    print(f"Config countries ({len(cfg_set)}):       {sorted(cfg_set)}")
    print(f"FAOSTAT silver country_keys ({len(fao_keys)}): {sorted(fao_keys)}")
    print(f"Weather silver countries ({len(wthr_keys)}):   {sorted(wthr_keys)}")
    print(f"\nMissing from FAOSTAT silver:  {sorted(cfg_set - fao_keys)  or 'None'}")
    print(f"Missing from weather silver:  {sorted(cfg_set - wthr_keys) or 'None'}")
    print(f"Can ML-join on:               {sorted(cfg_set & fao_keys & wthr_keys)}")

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


def check_country_overlap(faostat: pd.DataFrame, weather: pd.DataFrame) -> None:
    """Check that every config country appears as country_key in FAOSTAT and as country in weather."""
    config_countries = load_config_countries()
    faostat_countries = set(faostat["country_key"].dropna().unique())
    weather_countries = set(weather["country"].dropna().unique())

    print("\nCOUNTRY-LEVEL OVERLAP CHECK")
    print("=" * 60)
    print(f"Config countries ({len(config_countries)}): {sorted(config_countries)}")
    print(f"FAOSTAT country_keys ({len(faostat_countries)}): {sorted(faostat_countries)}")
    print(f"Weather countries ({len(weather_countries)}): {sorted(weather_countries)}")

    missing_from_faostat = [c for c in config_countries if c not in faostat_countries]
    missing_from_weather = [c for c in config_countries if c not in weather_countries]

    print("\nConfig countries missing from FAOSTAT silver:")
    print(missing_from_faostat if missing_from_faostat else "  None")

    print("\nConfig countries missing from weather silver:")
    print(missing_from_weather if missing_from_weather else "  None")

    in_both = faostat_countries & weather_countries
    print(f"\nCountries in both datasets ({len(in_both)}): {sorted(in_both)}")


def check_country_year_matrix(faostat: pd.DataFrame, weather: pd.DataFrame) -> None:
    """For every (config_country, year) in the overlap window, verify data exists in both."""
    config_countries = load_config_countries()

    faostat_pairs = set(
        zip(faostat["country_key"].dropna().astype(str), faostat["year"].dropna().astype(int))
    )
    weather_pairs = set(
        zip(weather["country"].dropna().astype(str), weather["year"].dropna().astype(int))
    )

    missing_faostat: list[dict] = []
    missing_weather: list[dict] = []

    for country in config_countries:
        for year in range(OVERLAP_START, OVERLAP_END + 1):
            if (country, year) not in faostat_pairs:
                missing_faostat.append({"country": country, "year": year})
            if (country, year) not in weather_pairs:
                missing_weather.append({"country": country, "year": year})

    print(f"\nPER-COUNTRY-YEAR MATRIX ({OVERLAP_START}–{OVERLAP_END})")
    print("=" * 60)

    print(f"Missing (country, year) from FAOSTAT: {len(missing_faostat)}")
    if missing_faostat:
        print(pd.DataFrame(missing_faostat).to_string(index=False))

    print(f"\nMissing (country, year) from weather: {len(missing_weather)}")
    if missing_weather:
        print(pd.DataFrame(missing_weather).to_string(index=False))

    if not missing_faostat and not missing_weather:
        print("  All config countries have data in both datasets for every overlap year.")


def check_overlap(faostat: pd.DataFrame, weather: pd.DataFrame) -> None:
    faostat_years = set(faostat["year"].dropna().astype(int).unique())
    weather_years = set(weather["year"].dropna().astype(int).unique())

    overlap_years = sorted(faostat_years.intersection(weather_years))

    print("\nML YEAR OVERLAP COVERAGE")
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

def main() -> None:
    countries, regions = load_config()
    athena = ensure_catalog(commodity=COMMODITY, countries=countries, regions=regions)
    check_country_overlap(athena, countries)
    check_year_matrix(athena, countries)
    print("\nDone.")


if __name__ == "__main__":
    main()
