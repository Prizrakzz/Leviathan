"""Pipeline completeness check — validates every layer against config ground truth.

Layers 1, 2, 4 (raw/bronze): ListObjectsV2 — file presence only, zero data downloaded.
Layers 3, 5 (silver):        Athena SQL — queries run inside AWS, only counts returned.

Run: python jobs/check_pipeline_completeness_cocoa.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import boto3
import pandas as pd
import yaml

# athena_utils lives in the same jobs/ directory
sys.path.insert(0, str(Path(__file__).parent))
from athena_utils import (
    ATHENA_DB,
    AWS_REGION,
    BUCKET,
    FAOSTAT_END_YEAR,
    FAOSTAT_START_YEAR,
    WEATHER_END_YEAR,
    WEATHER_START_YEAR,
    ensure_catalog,
    run_query,
)

COMMODITY = os.environ.get("LEVIATHAN_COMMODITY", "cocoa")
OVERLAP_START = WEATHER_START_YEAR
OVERLAP_END = FAOSTAT_END_YEAR
METRICS = ["area_harvested", "production_quantity", "yield"]
CONFIG_PATH = Path("configs/geographies/cocoa_regions.yaml")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config() -> tuple[list[str], list[str], list[tuple[str, str]]]:
    with CONFIG_PATH.open() as f:
        cfg = yaml.safe_load(f)
    countries: list[str] = []
    regions: list[str] = []
    pairs: list[tuple[str, str]] = []
    for block in cfg["regions"]:
        c = block["country"]
        countries.append(c)
        for loc in block["locations"]:
            r = loc["region"]
            regions.append(r)
            pairs.append((c, r))
    return countries, regions, pairs


# ---------------------------------------------------------------------------
# ListObjectsV2 helpers (raw / bronze — file presence, no data downloaded)
# ---------------------------------------------------------------------------

def _list_keys(prefix: str, suffix: str = "") -> list[str]:
    s3 = boto3.client("s3", region_name=AWS_REGION)
    paginator = s3.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            if not suffix or obj["Key"].endswith(suffix):
                keys.append(obj["Key"])
    return keys


def _hive(key: str, field: str) -> str:
    for part in key.split("/"):
        if part.startswith(f"{field}="):
            return part[len(field) + 1:]
    return ""


# ---------------------------------------------------------------------------
# Layer checks
# ---------------------------------------------------------------------------

def check_raw_weather(pairs: list[tuple[str, str]]) -> None:
    print("\n[1/5] RAW WEATHER  (ListObjectsV2 — file presence)")
    print("=" * 70)
    keys = _list_keys(f"raw/weather/source=nasa_power/commodity={COMMODITY}/", ".json")
    actual = {
        (_hive(k, "country"), _hive(k, "region"), int(_hive(k, "year")), int(_hive(k, "month")))
        for k in keys
        if all(_hive(k, f) for f in ("country", "region", "year", "month"))
    }
    expected = {
        (c, r, y, m)
        for c, r in pairs
        for y in range(WEATHER_START_YEAR, WEATHER_END_YEAR + 1)
        for m in range(1, 13)
    }
    missing = sorted(expected - actual)
    print(f"Files found:        {len(keys)}")
    print(f"Expected (c,r,y,m): {len(expected)}")
    print(f"Missing (c,r,y,m):  {len(missing)}")
    if missing:
        print(pd.DataFrame(missing, columns=["country", "region", "year", "month"]).to_string(index=False))


def check_bronze_weather(pairs: list[tuple[str, str]]) -> None:
    print("\n[2/5] BRONZE WEATHER  (ListObjectsV2 — file presence)")
    print("=" * 70)
    keys = _list_keys(f"bronze/weather/source=nasa_power/commodity={COMMODITY}/", ".parquet")
    actual = {
        (_hive(k, "country"), _hive(k, "region"), int(_hive(k, "year")), int(_hive(k, "month")))
        for k in keys
        if all(_hive(k, f) for f in ("country", "region", "year", "month"))
    }
    expected = {
        (c, r, y, m)
        for c, r in pairs
        for y in range(WEATHER_START_YEAR, WEATHER_END_YEAR + 1)
        for m in range(1, 13)
    }
    missing = sorted(expected - actual)
    print(f"Files found:        {len(keys)}")
    print(f"Expected (c,r,y,m): {len(expected)}")
    print(f"Missing (c,r,y,m):  {len(missing)}")
    if missing:
        print(pd.DataFrame(missing, columns=["country", "region", "year", "month"]).to_string(index=False))


def check_silver_weather(athena, pairs: list[tuple[str, str]]) -> None:
    print("\n[3/5] SILVER WEATHER  (Athena SQL — runs in AWS)")
    print("=" * 70)

    rows = run_query(athena, f"""
        SELECT country, region, year, month, COUNT(*) AS n
        FROM {ATHENA_DB}.silver_weather
        GROUP BY country, region, year, month
    """)
    actual = {(r["country"], r["region"], int(r["year"]), int(r["month"])) for r in rows}
    expected = {
        (c, r, y, m)
        for c, r in pairs
        for y in range(WEATHER_START_YEAR, WEATHER_END_YEAR + 1)
        for m in range(1, 13)
    }
    missing = sorted(expected - actual)
    total_rows = sum(int(r["n"]) for r in rows)
    print(f"Total rows:         {total_rows:,}")
    print(f"Expected (c,r,y,m): {len(expected)}")
    print(f"Missing (c,r,y,m):  {len(missing)}")
    if missing:
        print(pd.DataFrame(missing, columns=["country", "region", "year", "month"]).to_string(index=False))

    gap_rows = run_query(athena, f"""
        SELECT country, region,
               date_diff('day', min(date), max(date)) + 1 AS expected_days,
               COUNT(DISTINCT date)                        AS actual_days
        FROM {ATHENA_DB}.silver_weather
        GROUP BY country, region
    """)
    problems = [r for r in gap_rows if r["expected_days"] != r["actual_days"]]
    print(f"\nRegions with day gaps: {len(problems)}")
    if problems:
        print(pd.DataFrame(problems).to_string(index=False))


def check_bronze_faostat() -> None:
    print("\n[4/5] BRONZE FAOSTAT  (ListObjectsV2 — file presence)")
    print("=" * 70)
    keys = _list_keys(
        f"bronze/production/source=faostat/dataset=QCL/commodity={COMMODITY}/", ".parquet"
    )
    years = {int(_hive(k, "year")) for k in keys if _hive(k, "year")}
    missing_years = sorted(set(range(FAOSTAT_START_YEAR, FAOSTAT_END_YEAR + 1)) - years)
    print(f"Files found: {len(keys)}")
    print(f"Year range:  {min(years) if years else '?'} → {max(years) if years else '?'}")
    print(f"Missing years ({FAOSTAT_START_YEAR}–{FAOSTAT_END_YEAR}): {missing_years or 'None'}")


def check_silver_faostat(athena, countries: list[str]) -> None:
    print("\n[5/5] SILVER FAOSTAT  (Athena SQL — runs in AWS)")
    print("=" * 70)

    rows = run_query(athena, f"""
        SELECT country_key, metric, year, COUNT(*) AS n
        FROM {ATHENA_DB}.silver_production
        GROUP BY country_key, metric, year
    """)
    actual = {(r["country_key"], r["metric"], int(r["year"])) for r in rows}
    total_rows = sum(int(r["n"]) for r in rows)
    distinct_keys = sorted({r["country_key"] for r in rows})

    missing = [
        {"country_key": c, "metric": m, "year": y}
        for c in countries
        for m in METRICS
        for y in range(OVERLAP_START, OVERLAP_END + 1)
        if (c, m, y) not in actual
    ]

    print(f"Total rows:    {total_rows:,}")
    print(f"country_keys:  {distinct_keys}")
    print(f"Missing (country_key, metric, year) in overlap window {OVERLAP_START}–{OVERLAP_END}: {len(missing)}")
    if missing:
        mdf = pd.DataFrame(missing)
        summary = (
            mdf.groupby(["country_key", "metric"])["year"]
            .apply(lambda s: f"{int(s.min())}–{int(s.max())} ({len(s)} yrs)")
            .reset_index(name="missing_years")
        )
        print(summary.to_string(index=False))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    print("PIPELINE COMPLETENESS CHECK — cocoa")
    print("=" * 70)
    print(f"Bucket: s3://{BUCKET}  |  Region: {AWS_REGION}  |  Commodity: {COMMODITY}")
    print(f"Weather years:     {WEATHER_START_YEAR}–{WEATHER_END_YEAR}")
    print(f"FAOSTAT years:     {FAOSTAT_START_YEAR}–{FAOSTAT_END_YEAR}")
    print(f"ML overlap window: {OVERLAP_START}–{OVERLAP_END}")

    countries, regions, pairs = load_config()
    print(f"\nConfig: {len(countries)} countries, {len(pairs)} (country, region) pairs")
    print(f"Countries: {countries}")

    print("\nInitialising Athena catalog (idempotent)...")
    athena = ensure_catalog(commodity=COMMODITY, countries=countries, regions=regions)

    check_raw_weather(pairs)
    check_bronze_weather(pairs)
    check_silver_weather(athena, pairs)
    check_bronze_faostat()
    check_silver_faostat(athena, countries)

    print("\n" + "=" * 70)
    print("Done.")


if __name__ == "__main__":
    main()
