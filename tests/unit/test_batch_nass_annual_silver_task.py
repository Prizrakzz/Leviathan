"""Unit tests for the NASS annual silver Batch task helpers."""
from __future__ import annotations

import pandas as pd
from leviathan.storage.paths import silver_nass_annual_key

from jobs.batch import nass_annual_silver_task as task


def _silver_row(slug: str, state: str, year: int) -> dict[str, object]:
    return {
        "leviathan_slug": slug,
        "country": "united_states",
        "state": state,
        "year": year,
        "marketing_year": year,
        "area_planted_ha": 1.0,
        "area_harvested_ha": 1.0,
        "yield_t_ha": 1.0,
        "production_mt": 1.0,
        "area_planted_cv_pct": None,
        "area_harvested_cv_pct": None,
        "yield_cv_pct": None,
        "production_cv_pct": None,
        "source": "usda_nass",
    }


def test_select_keys_filters_bronze_commodity_and_year() -> None:
    keys = [
        "bronze/production/source=usda_nass/series=annual/commodity=corn_cbot/year=2024/part-000.parquet",
        "bronze/production/source=usda_nass/series=annual/commodity=corn_cbot/year=2023/part-000.parquet",
        "bronze/production/source=usda_nass/series=annual/commodity=soybean_meal_cbot/year=2024/part-000.parquet",
    ]
    selected = task._select_keys(keys, bronze_commodities="corn_cbot", years="2024", limit=0)
    assert selected == [keys[0]]


def test_select_keys_limit_keeps_sorted_prefix() -> None:
    keys = [
        "bronze/production/source=usda_nass/series=annual/commodity=corn_cbot/year=2025/part-000.parquet",
        "bronze/production/source=usda_nass/series=annual/commodity=corn_cbot/year=2023/part-000.parquet",
        "bronze/production/source=usda_nass/series=annual/commodity=corn_cbot/year=2024/part-000.parquet",
    ]
    selected = task._select_keys(keys, bronze_commodities="all", years="all", limit=2)
    assert ["/year=2023/", "/year=2024/"] == [
        f"/year={key.split('/year=')[1].split('/')[0]}/" for key in selected
    ]


def test_transform_keys_workers_match_sequential(monkeypatch) -> None:
    keys = ["key-a", "key-b"]

    def fake_load(_bucket: str, key: str, _region: str) -> pd.DataFrame:
        state = "IA" if key == "key-a" else "IL"
        return pd.DataFrame([_silver_row("corn_cbot", state, 2024)])

    monkeypatch.setattr(task, "_load_and_transform", fake_load)

    sequential, sequential_errors = task._transform_keys("bucket", keys, "region", workers=1)
    parallel, parallel_errors = task._transform_keys("bucket", keys, "region", workers=2)

    sequential_df = pd.concat(sequential).sort_values("state").reset_index(drop=True)
    parallel_df = pd.concat(parallel).sort_values("state").reset_index(drop=True)

    assert sequential_errors == 0
    assert parallel_errors == 0
    pd.testing.assert_frame_equal(sequential_df, parallel_df)


def test_transform_keys_ignores_empty_outputs(monkeypatch) -> None:
    keys = ["empty", "non-empty"]

    def fake_load(_bucket: str, key: str, _region: str) -> pd.DataFrame:
        if key == "empty":
            return pd.DataFrame(columns=task.OUTPUT_COLUMNS)
        return pd.DataFrame([_silver_row("corn_cbot", "IA", 2024)])

    monkeypatch.setattr(task, "_load_and_transform", fake_load)

    frames, errors = task._transform_keys("bucket", keys, "region", workers=2)

    assert errors == 0
    assert len(frames) == 1
    assert frames[0].iloc[0]["state"] == "IA"


def test_transform_keys_aggregates_worker_errors(monkeypatch) -> None:
    keys = ["good", "bad"]

    def fake_load(_bucket: str, key: str, _region: str) -> pd.DataFrame:
        if key == "bad":
            raise ValueError("boom")
        return pd.DataFrame([_silver_row("corn_cbot", "IA", 2024)])

    monkeypatch.setattr(task, "_load_and_transform", fake_load)

    frames, errors = task._transform_keys("bucket", keys, "region", workers=2)

    assert errors == 1
    assert len(frames) == 1
    assert frames[0].iloc[0]["state"] == "IA"


def test_write_partitions_groups_by_slug_and_year(monkeypatch) -> None:
    calls: list[tuple[str, int, str]] = []

    def fake_write_partition(
        _bucket: str,
        _region: str,
        commodity: str,
        year: int,
        df: pd.DataFrame,
        _force: bool,
    ) -> str:
        calls.append((commodity, year, silver_nass_annual_key(commodity, year)))
        assert set(df["leviathan_slug"]) == {commodity}
        assert set(df["year"]) == {year}
        return "written"

    monkeypatch.setattr(task, "_write_partition", fake_write_partition)
    final = pd.DataFrame(
        [
            _silver_row("corn_cbot", "IA", 2024),
            _silver_row("corn_cbot", "IL", 2024),
            _silver_row("soybeans_cbot", "IA", 2023),
        ]
    )

    written, skipped = task._write_partitions(
        final,
        bucket="bucket",
        aws_region="region",
        force_overwrite=True,
        workers=2,
    )

    assert written == 2
    assert skipped == 0
    assert sorted(calls) == [
        (
            "corn_cbot",
            2024,
            "silver/nass_annual/commodity=corn_cbot/year=2024/part-000.parquet",
        ),
        (
            "soybeans_cbot",
            2023,
            "silver/nass_annual/commodity=soybeans_cbot/year=2023/part-000.parquet",
        ),
    ]
