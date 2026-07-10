"""Unit tests for the CONAB coffee silver Batch task helpers."""
from __future__ import annotations

import pandas as pd
import pytest
from leviathan.storage.paths import silver_conab_coffee_key

from jobs.batch import conab_coffee_silver_task as task


def _silver_row(
    commodity: str = "arabica_coffee",
    safra_year: int = 2025,
    survey_number: int = 1,
    region: str = "minas_gerais",
) -> dict[str, object]:
    return {
        "commodity": commodity,
        "country": "brazil",
        "safra_year": safra_year,
        "survey_number": survey_number,
        "region": region,
        "area_in_production_ha": 10.0,
        "yield_bags_per_ha": 20.0,
        "production_thousand_bags": 200.0,
        "production_revision_thousand_bags": None,
        "source": "conab_xls",
    }


def test_list_bronze_keys_filters_by_safra_year(monkeypatch) -> None:
    keys = [
        "bronze/production/source=conab_xls/safra_year=2024/survey=02/part-000.parquet",
        "bronze/production/source=conab_xls/safra_year=2025/survey=01/part-000.parquet",
        "bronze/production/source=conab_xls/safra_year=2025/survey=02/part-000.parquet",
        "bronze/production/source=conab_xls/safra_year=2025/survey=02/_SUCCESS",
    ]

    def fake_list_s3_keys(_bucket: str, _prefix: str, aws_region: str) -> list[str]:
        assert aws_region == "us-east-1"
        return keys

    monkeypatch.setattr(task, "list_s3_keys", fake_list_s3_keys)

    selected = task._list_bronze_keys("bucket", "us-east-1", {2025})

    assert selected == keys[1:3]


def test_write_grouped_uses_conab_silver_path(monkeypatch) -> None:
    calls: list[str] = []

    def fake_write(_bucket, _region, key, df, _force):
        calls.append(key)
        assert set(df["commodity"]) == {"arabica_coffee"}
        assert set(df["safra_year"]) == {2025}
        return "written"

    monkeypatch.setattr(task, "_write_parquet", fake_write)
    df = pd.DataFrame([_silver_row(), _silver_row(survey_number=2)])

    written, skipped = task._write_grouped(df, "bucket", "region", True)

    assert written == 1
    assert skipped == 0
    assert calls == [silver_conab_coffee_key(2025, "arabica_coffee")]


def test_validate_uniqueness_raises_on_duplicate_output_rows() -> None:
    df = pd.DataFrame([_silver_row(), _silver_row()])

    with pytest.raises(ValueError, match="duplicate output rows"):
        task._validate_uniqueness(df)


def test_conab_silver_path_does_not_overlap_other_prefixes() -> None:
    key = silver_conab_coffee_key(2025, "robusta_coffee")

    assert key == "silver/conab_coffee/commodity=robusta_coffee/safra_year=2025/part-000.parquet"
    assert not key.startswith("silver/production/")
    assert not key.startswith("silver/nass_annual/")
    assert not key.startswith("silver/nass_crop_progress/")
