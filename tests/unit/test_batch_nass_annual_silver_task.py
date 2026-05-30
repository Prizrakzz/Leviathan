"""Unit tests for the NASS annual silver Batch task helpers."""
from __future__ import annotations

from jobs.batch.nass_annual_silver_task import _select_keys


def test_select_keys_filters_bronze_commodity_and_year() -> None:
    keys = [
        "bronze/production/source=usda_nass/series=annual/commodity=corn_cbot/year=2024/part-000.parquet",
        "bronze/production/source=usda_nass/series=annual/commodity=corn_cbot/year=2023/part-000.parquet",
        "bronze/production/source=usda_nass/series=annual/commodity=soybean_meal_cbot/year=2024/part-000.parquet",
    ]
    selected = _select_keys(keys, bronze_commodities="corn_cbot", years="2024", limit=0)
    assert selected == [keys[0]]


def test_select_keys_limit_keeps_sorted_prefix() -> None:
    keys = [
        "bronze/production/source=usda_nass/series=annual/commodity=corn_cbot/year=2025/part-000.parquet",
        "bronze/production/source=usda_nass/series=annual/commodity=corn_cbot/year=2023/part-000.parquet",
        "bronze/production/source=usda_nass/series=annual/commodity=corn_cbot/year=2024/part-000.parquet",
    ]
    selected = _select_keys(keys, bronze_commodities="all", years="all", limit=2)
    assert ["/year=2023/", "/year=2024/"] == [
        f"/year={key.split('/year=')[1].split('/')[0]}/" for key in selected
    ]
