from __future__ import annotations

import pandas as pd
import pytest

from leviathan.transforms.bronze_to_silver.usda_wasde import (
    OUTPUT_COLUMNS,
    transform_wasde_bronze_to_silver,
)


def _bronze(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "table_name": "World Corn Supply and Use",
        "region": "World",
        "market_year": "2024/25",
        "status": "Proj.",
        "projection_month": "",
        "unit": "Million Metric Tons",
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def test_wasde_silver_computes_adjacent_revision() -> None:
    df = _bronze([
        {"release_date": "2024-05-10", "attribute": "production", "value": 1200.0},
        {"release_date": "2024-06-12", "attribute": "production", "value": 1195.0},
        {"release_date": "2024-07-12", "attribute": "production", "value": 1201.0},
    ])
    out = transform_wasde_bronze_to_silver(df)
    assert list(out.columns) == OUTPUT_COLUMNS
    assert out["commodity"].unique().tolist() == ["corn"]
    assert out["table_type"].unique().tolist() == ["world"]
    assert out["revision"].tolist() == [pytest.approx(float("nan"), nan_ok=True), -5.0, 6.0]
    assert out["revision_direction"].tolist() == ["none", "down", "up"]
    assert out["is_first_estimate"].tolist() == [True, False, False]
    assert out["is_final_or_latest"].tolist() == [False, False, True]


def test_wasde_silver_rejects_parser_artifacts_and_unsupported_units() -> None:
    df = _bronze([
        {"release_date": "2024-05-10", "attribute": "production", "value": 1200.0},
        {"release_date": "2024-05-10", "attribute": "col_7", "value": 1.0},
        {"release_date": "2024-05-10", "attribute": "exports", "unit": "Made Up Unit", "value": 2.0},
        {"release_date": "2024-05-10", "table_name": "Unrelated Livestock Table", "attribute": "production", "value": 3.0},
    ])
    out = transform_wasde_bronze_to_silver(df)
    assert len(out) == 1
    assert out.iloc[0]["attribute"] == "production"


def test_wasde_silver_duplicate_conflicts_raise() -> None:
    df = _bronze([
        {"release_date": "2024-05-10", "attribute": "production", "value": 1200.0},
        {"release_date": "2024-05-10", "attribute": "production", "value": 1201.0},
    ])
    with pytest.raises(ValueError, match="duplicate estimate conflicts"):
        transform_wasde_bronze_to_silver(df)


def test_wasde_silver_same_duplicate_value_deduplicates() -> None:
    df = _bronze([
        {"release_date": "2024-05-10", "attribute": "production", "value": 1200.0},
        {"release_date": "2024-05-10", "attribute": "production", "value": 1200.0},
    ])
    out = transform_wasde_bronze_to_silver(df)
    assert len(out) == 1
