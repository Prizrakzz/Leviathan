from __future__ import annotations

from pathlib import Path

import pandas as pd


def count_files(root: Path, pattern: str) -> int:
    if not root.exists():
        return 0
    return len(list(root.rglob(pattern)))


def main() -> None:
    faostat_bronze_root = Path("data/bronze/production/faostat/qcl")
    nasa_raw_root = Path("data/raw/weather/nasa_power/cocoa")
    nasa_bronze_root = Path("data/bronze/weather/nasa_power/cocoa")
    metadata_root = Path("data/metadata/runs/nasa_power/cocoa")

    print("PHASE 2 LOCAL CHECK")
    print("=" * 50)

    print(f"FAOSTAT bronze Parquet files: {count_files(faostat_bronze_root, '*.parquet')}")
    print(f"NASA POWER raw JSON files:     {count_files(nasa_raw_root, '*.json')}")
    print(f"NASA POWER bronze Parquet:    {count_files(nasa_bronze_root, '*.parquet')}")
    print(f"NASA POWER metadata files:    {count_files(metadata_root, '*.json')}")

    parquet_files = sorted(nasa_bronze_root.rglob("*.parquet"))

    if parquet_files:
        sample = pd.read_parquet(parquet_files[0])

        print("\nSample NASA POWER bronze file:")
        print(parquet_files[0])

        print("\nShape:")
        print(sample.shape)

        print("\nColumns:")
        print(list(sample.columns))

        print("\nDate range:")
        print(sample["date"].min(), "→", sample["date"].max())

        print("\nSample rows:")
        print(sample.head())


if __name__ == "__main__":
    main()