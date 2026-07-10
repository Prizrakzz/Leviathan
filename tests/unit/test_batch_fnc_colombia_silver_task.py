"""Unit tests for FNC Colombia silver Batch task helpers."""
from __future__ import annotations

from datetime import date

import pandas as pd
from leviathan.storage.paths import (
    silver_fnc_colombia_area_department_key,
    silver_fnc_colombia_exports_port_type_key,
    silver_fnc_colombia_monthly_key,
)

from jobs.batch import fnc_colombia_silver_task as task


def test_filter_years_keeps_selected_years() -> None:
    df = pd.DataFrame({"year": [2023, 2024], "value": [1, 2]})
    filtered = task._filter_years(df, {2024})
    assert filtered["year"].tolist() == [2024]


def test_write_grouped_uses_fnc_monthly_path(monkeypatch) -> None:
    calls: list[str] = []

    def fake_write(_bucket, _region, key, df, _force):
        calls.append(key)
        assert set(df["year"]) == {2024}
        return "written"

    monkeypatch.setattr(task, "_write_parquet", fake_write)
    df = pd.DataFrame([
        {
            "leviathan_slug": "arabica_coffee",
            "country": "colombia",
            "year": 2024,
            "month": 1,
            "date": date(2024, 1, 1),
            "production_bags_60kg": 1.0,
            "ex_dock_price_usd_cents_per_lb": None,
            "internal_price_cop_per_125kg": None,
            "exports_bags_60kg": None,
            "exports_value_usd_m": None,
            "source": "fnc_colombia",
        }
    ])

    written, skipped = task._write_grouped(
        df,
        task.MONTHLY_OUTPUT_COLUMNS,
        "bucket",
        "region",
        True,
        silver_fnc_colombia_monthly_key,
    )

    assert written == 1
    assert skipped == 0
    assert calls == [
        "silver/fnc_colombia/monthly/commodity=arabica_coffee/year=2024/part-000.parquet"
    ]


def test_path_helpers_do_not_overlap_other_silver_prefixes() -> None:
    paths = {
        silver_fnc_colombia_monthly_key(2024),
        silver_fnc_colombia_area_department_key(2024),
        silver_fnc_colombia_exports_port_type_key(2024),
    }
    assert paths == {
        "silver/fnc_colombia/monthly/commodity=arabica_coffee/year=2024/part-000.parquet",
        "silver/fnc_colombia/area_department/commodity=arabica_coffee/year=2024/part-000.parquet",
        "silver/fnc_colombia/exports_port_type/commodity=arabica_coffee/year=2024/part-000.parquet",
    }
    assert all(not path.startswith("silver/production/") for path in paths)
    assert all(not path.startswith("silver/nass_") for path in paths)
