"""Schema / shape / quality sanity check on silver layers — queries run via Athena in AWS.

Checks: row counts, null counts per column, duplicate keys, date ranges, official flag
distribution. No data is downloaded — all computation happens inside AWS.

Run: python jobs/check_stage3_cocoa.py
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
CONFIG_PATH = Path("configs/geographies/cocoa_regions.yaml")


def load_config() -> tuple[list[str], list[str]]:
    with CONFIG_PATH.open() as f:
        cfg = yaml.safe_load(f)
    countries = [r["country"] for r in cfg["regions"]]
    regions = [loc["region"] for r in cfg["regions"] for loc in r["locations"]]
    return countries, regions


def check_production(athena) -> None:
    print("\nSILVER PRODUCTION — schema / shape / quality")
    print("=" * 70)

    # Row count + dedup check
    dedup = run_query(athena, f"""
        SELECT
            COUNT(*) AS total_rows,
            COUNT(DISTINCT country_key || '|' || metric || '|' || CAST(year AS VARCHAR)) AS distinct_keys
        FROM {ATHENA_DB}.silver_production
    """)
    total = int(dedup[0]["total_rows"])
    distinct = int(dedup[0]["distinct_keys"])
    print(f"Total rows:   {total:,}")
    print(f"Distinct (country_key, metric, year) keys: {distinct:,}")
    print(f"Duplicate rows: {total - distinct}")

    # Per-(country_key, metric) summary
    summary = run_query(athena, f"""
        SELECT
            country_key,
            metric,
            MIN(year)  AS min_year,
            MAX(year)  AS max_year,
            COUNT(*)   AS rows,
            COUNT(DISTINCT year) AS years_covered,
            SUM(CASE WHEN value IS NULL THEN 1 ELSE 0 END) AS null_values,
            SUM(CASE WHEN is_official = true THEN 1 ELSE 0 END) AS official_rows
        FROM {ATHENA_DB}.silver_production
        GROUP BY country_key, metric
        ORDER BY country_key, metric
    """)
    print("\nPer (country_key, metric):")
    print(pd.DataFrame(summary).to_string(index=False))

    # Flag distribution
    flags = run_query(athena, f"""
        SELECT COALESCE(flag, '(null)') AS flag, COUNT(*) AS n
        FROM {ATHENA_DB}.silver_production
        GROUP BY flag
        ORDER BY n DESC
    """)
    print("\nFlag distribution:")
    print(pd.DataFrame(flags).to_string(index=False))

    # Warn on country/metric combos with zero official rows
    zero_official = [r for r in summary if int(r["official_rows"]) == 0]
    if zero_official:
        print("\nWARNING — (country_key, metric) with zero official rows:")
        print(pd.DataFrame(zero_official)[["country_key", "metric", "years_covered"]].to_string(index=False))
    else:
        print("\nAll (country_key, metric) combos have at least one official row.")


def check_weather(athena) -> None:
    print("\nSILVER WEATHER — schema / shape / quality")
    print("=" * 70)

    # Row count + dedup check
    dedup = run_query(athena, f"""
        SELECT
            COUNT(*) AS total_rows,
            COUNT(DISTINCT country || '|' || region || '|' || CAST(date AS VARCHAR)) AS distinct_keys
        FROM {ATHENA_DB}.silver_weather
    """)
    total = int(dedup[0]["total_rows"])
    distinct = int(dedup[0]["distinct_keys"])
    print(f"Total rows:   {total:,}")
    print(f"Distinct (country, region, date) keys: {distinct:,}")
    print(f"Duplicate rows: {total - distinct}")

    # Per-(country, region) summary
    summary = run_query(athena, f"""
        SELECT
            country,
            region,
            MIN(date)  AS min_date,
            MAX(date)  AS max_date,
            COUNT(*)   AS rows,
            COUNT(DISTINCT date) AS distinct_days,
            SUM(CASE WHEN temperature_2m_mean_c    IS NULL THEN 1 ELSE 0 END) AS null_temp_mean,
            SUM(CASE WHEN precipitation_mm         IS NULL THEN 1 ELSE 0 END) AS null_precip,
            SUM(CASE WHEN relative_humidity_2m_pct IS NULL THEN 1 ELSE 0 END) AS null_rh,
            SUM(CASE WHEN solar_radiation_mj_m2_day IS NULL THEN 1 ELSE 0 END) AS null_solar
        FROM {ATHENA_DB}.silver_weather
        GROUP BY country, region
        ORDER BY country, region
    """)
    print("\nPer (country, region):")
    print(pd.DataFrame(summary).to_string(index=False))


def main() -> None:
    print("STAGE 3 COCOA SILVER CHECK")
    print("=" * 70)

    countries, regions = load_config()
    athena = ensure_catalog(commodity=COMMODITY, countries=countries, regions=regions)

    check_production(athena)
    check_weather(athena)

    print("\nDone.")


if __name__ == "__main__":
    main()

