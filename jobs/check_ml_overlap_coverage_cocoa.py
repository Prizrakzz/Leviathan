"""ML join overlap check — all queries run via Athena inside AWS.

Verifies that every config country appears in both silver datasets and that
every (country, year) in the 1981-2023 overlap window has data in both.

Run: python jobs/check_ml_overlap_coverage_cocoa.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

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
    wthr_rows = run_query(athena, f"SELECT DISTINCT country FROM {ATHENA_DB}.silver_weather")

    fao_keys = {r["country_key"] for r in fao_rows}
    wthr_keys = {r["country"] for r in wthr_rows}
    cfg_set = set(countries)

    print(f"Config countries ({len(cfg_set)}):            {sorted(cfg_set)}")
    print(f"FAOSTAT silver country_keys ({len(fao_keys)}):    {sorted(fao_keys)}")
    print(f"Weather silver countries ({len(wthr_keys)}):      {sorted(wthr_keys)}")
    print(f"\nMissing from FAOSTAT silver:  {sorted(cfg_set - fao_keys) or 'None'}")
    print(f"Missing from weather silver:  {sorted(cfg_set - wthr_keys) or 'None'}")
    print(f"Can ML-join on:               {sorted(cfg_set & fao_keys & wthr_keys)}")


def check_year_matrix(athena, countries: list[str]) -> None:
    print(f"\nPER-COUNTRY-YEAR MATRIX  ({OVERLAP_START}-{OVERLAP_END})")
    print("=" * 70)

    wthr_rows = run_query(athena, f"""
        SELECT DISTINCT country, year
        FROM {ATHENA_DB}.silver_weather
        WHERE year BETWEEN {OVERLAP_START} AND {OVERLAP_END}
    """)
    fao_rows = run_query(athena, f"""
        SELECT DISTINCT country_key, year
        FROM {ATHENA_DB}.silver_production
        WHERE year BETWEEN {OVERLAP_START} AND {OVERLAP_END}
    """)

    wthr_pairs = {(r["country"], int(r["year"])) for r in wthr_rows}
    fao_pairs  = {(r["country_key"], int(r["year"])) for r in fao_rows}

    missing_wthr: list[dict] = []
    missing_fao:  list[dict] = []

    for country in countries:
        for year in range(OVERLAP_START, OVERLAP_END + 1):
            if (country, year) not in wthr_pairs:
                missing_wthr.append({"country": country, "year": year})
            if (country, year) not in fao_pairs:
                missing_fao.append({"country": country, "year": year})

    print(f"Missing (country, year) from weather silver:    {len(missing_wthr)}")
    if missing_wthr:
        for row in missing_wthr[:50]:
            print(f"  {row['country']} {row['year']}")

    print(f"Missing (country, year) from FAOSTAT silver:    {len(missing_fao)}")
    if missing_fao:
        for row in missing_fao[:50]:
            print(f"  {row['country']} {row['year']}")

    if not missing_wthr and not missing_fao:
        print("  All config countries have data in both datasets for every overlap year.")


def main() -> None:
    print("ML OVERLAP COVERAGE CHECK - cocoa")
    print("=" * 70)
    print(f"Overlap window: {OVERLAP_START}-{OVERLAP_END}")

    countries, regions = load_config()
    print(f"Config: {len(countries)} countries - {countries}")

    print("\nInitialising Athena catalog (idempotent)...")
    athena = ensure_catalog(commodity=COMMODITY, countries=countries, regions=regions)

    check_country_overlap(athena, countries)
    check_year_matrix(athena, countries)

    print("\nDone.")


if __name__ == "__main__":
    main()
