"""Unit tests for CONAB coffee XLS bronze -> silver transforms."""
from __future__ import annotations

import pandas as pd
import pytest

from leviathan.transforms.bronze_to_silver.conab_coffee import (
    OUTPUT_COLUMNS,
    transform_conab_coffee_bronze_to_silver,
)


def _row(
    *,
    safra_year: int = 2025,
    survey: int = 1,
    sheet_name: str = "2 Café Arábica",
    region: str = "MG",
    element: str = "production_thousand_bags",
    value: float = 1000.0,
) -> dict[str, object]:
    return {
        "safra_year": safra_year,
        "survey": survey,
        "commodity": "coffee",
        "sheet_name": sheet_name,
        "region": region,
        "element": element,
        "value": value,
        "unit": "test",
    }


def _metric_rows(
    *,
    safra_year: int,
    survey: int,
    sheet_name: str,
    region: str,
    production: float,
) -> list[dict[str, object]]:
    return [
        _row(
            safra_year=safra_year,
            survey=survey,
            sheet_name=sheet_name,
            region=region,
            element="area_in_production_ha",
            value=10.0,
        ),
        _row(
            safra_year=safra_year,
            survey=survey,
            sheet_name=sheet_name,
            region=region,
            element="yield_bags_per_ha",
            value=20.0,
        ),
        _row(
            safra_year=safra_year,
            survey=survey,
            sheet_name=sheet_name,
            region=region,
            element="production_thousand_bags",
            value=production,
        ),
    ]


def test_pivots_metrics_and_computes_revision_delta() -> None:
    bronze = pd.DataFrame(
        _metric_rows(
            safra_year=2025,
            survey=1,
            sheet_name="2 Café Arábica",
            region="MG",
            production=1000.0,
        )
        + _metric_rows(
            safra_year=2025,
            survey=2,
            sheet_name="2 Café Arábica",
            region="MG",
            production=1125.0,
        )
    )

    silver = transform_conab_coffee_bronze_to_silver(bronze)

    assert list(silver.columns) == OUTPUT_COLUMNS
    assert len(silver) == 2
    first, second = silver.iloc[0], silver.iloc[1]
    assert first["commodity"] == "arabica_coffee"
    assert first["country"] == "brazil"
    assert first["region"] == "minas_gerais"
    assert first["area_in_production_ha"] == pytest.approx(10.0)
    assert first["yield_bags_per_ha"] == pytest.approx(20.0)
    assert pd.isna(first["production_revision_thousand_bags"])
    assert second["production_revision_thousand_bags"] == pytest.approx(125.0)


def test_maps_arabica_robusta_and_normalizes_regions() -> None:
    bronze = pd.DataFrame(
        _metric_rows(
            safra_year=2026,
            survey=1,
            sheet_name="2 Café Arábica",
            region="BRASIL",
            production=1700.0,
        )
        + _metric_rows(
            safra_year=2026,
            survey=1,
            sheet_name="3 Café Conilon",
            region="ES",
            production=900.0,
        )
    )

    silver = transform_conab_coffee_bronze_to_silver(bronze)

    assert set(silver["commodity"]) == {"arabica_coffee", "robusta_coffee"}
    assert set(silver["region"]) == {"brazil", "espirito_santo"}


def test_excludes_total_sheet_macroregions_and_unknown_elements() -> None:
    bronze = pd.DataFrame(
        [
            _row(sheet_name="1 Café Total", region="MG", value=1.0),
            _row(sheet_name="2 Café Arábica", region="Sul de Minas", value=2.0),
            _row(sheet_name="2 Café Arábica", region="MG", element="ignored_metric", value=3.0),
            _row(sheet_name="2 Café Arábica", region="MG", value=4.0),
        ]
    )

    silver = transform_conab_coffee_bronze_to_silver(bronze)

    assert len(silver) == 1
    row = silver.iloc[0]
    assert row["commodity"] == "arabica_coffee"
    assert row["region"] == "minas_gerais"
    assert row["production_thousand_bags"] == pytest.approx(4.0)


def test_conflicting_duplicate_metric_raises() -> None:
    bronze = pd.DataFrame(
        [
            _row(value=1000.0),
            _row(value=1001.0),
        ]
    )

    with pytest.raises(ValueError, match="conflicting duplicate metrics"):
        transform_conab_coffee_bronze_to_silver(bronze)
