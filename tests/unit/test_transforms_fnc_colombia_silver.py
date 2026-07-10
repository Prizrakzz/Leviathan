"""Unit tests for FNC Colombia bronze -> silver transforms."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from leviathan.transforms.bronze_to_silver.fnc_colombia import (
    AREA_OUTPUT_COLUMNS,
    EXPORTS_PORT_TYPE_OUTPUT_COLUMNS,
    MONTHLY_OUTPUT_COLUMNS,
    transform_fnc_colombia_area_department,
    transform_fnc_colombia_bronze_to_silver,
    transform_fnc_colombia_monthly,
)


def _monthly_series(value: float, series_name: str, unit: str = "unit") -> pd.DataFrame:
    return pd.DataFrame([
        {
            "series_name": series_name,
            "year": 2024,
            "month": 1,
            "date": date(2024, 1, 1),
            "value": value,
            "unit": unit,
            "source": "fnc_excel",
        }
    ])


def _bronze_series() -> dict[str, pd.DataFrame]:
    return {
        "produccion_mensual": _monthly_series(700.0, "produccion_mensual"),
        "precio_ex_dock_mensual": _monthly_series(310.5, "precio_ex_dock_mensual"),
        "precio_interno_mensual": _monthly_series(1_950_000.0, "precio_interno_mensual"),
        "exportaciones_total_volumen": _monthly_series(925.0, "exportaciones_total_volumen"),
        "exportaciones_total_valor": _monthly_series(363.3, "exportaciones_total_valor"),
        "area_departamento": pd.DataFrame([
            {
                "series_name": "area_departamento",
                "year": 2024,
                "department_raw": "Nariño",
                "department": "narino",
                "area_1000_ha": 35.2,
            }
        ]),
        "exportaciones_puerto_tipo": pd.DataFrame([
            {
                "series_name": "exportaciones_puerto_tipo",
                "year": 2024,
                "month": 1,
                "date": date(2024, 1, 1),
                "port_raw": "Aerp. El Dorado",
                "port": "aerp_el_dorado",
                "coffee_type_raw": "Café Verde",
                "coffee_type": "cafe_verde",
                "exports_bags_60kg": 84.0,
                "exports_value_usd": 60776.73,
            }
        ]),
    }


def test_monthly_silver_pivots_and_converts_units() -> None:
    monthly = transform_fnc_colombia_monthly(_bronze_series())
    assert list(monthly.columns) == MONTHLY_OUTPUT_COLUMNS
    assert len(monthly) == 1
    row = monthly.iloc[0]
    assert row["leviathan_slug"] == "arabica_coffee"
    assert row["country"] == "colombia"
    assert row["production_bags_60kg"] == pytest.approx(700_000.0)
    assert row["exports_bags_60kg"] == pytest.approx(925_000.0)
    assert row["exports_value_usd_m"] == pytest.approx(363.3)
    assert row["ex_dock_price_usd_cents_per_lb"] == pytest.approx(310.5)
    assert row["internal_price_cop_per_125kg"] == pytest.approx(1_950_000.0)


def test_area_department_silver_normalizes_and_converts_area() -> None:
    area = transform_fnc_colombia_area_department(_bronze_series()["area_departamento"])
    assert list(area.columns) == AREA_OUTPUT_COLUMNS
    row = area.iloc[0]
    assert row["leviathan_slug"] == "arabica_coffee"
    assert row["department"] == "narino"
    assert row["area_ha"] == pytest.approx(35_200.0)


def test_exports_port_type_silver_outputs_expected_columns() -> None:
    silver = transform_fnc_colombia_bronze_to_silver(_bronze_series())
    exports = silver.exports_port_type
    assert list(exports.columns) == EXPORTS_PORT_TYPE_OUTPUT_COLUMNS
    row = exports.iloc[0]
    assert row["port"] == "aerp_el_dorado"
    assert row["coffee_type"] == "cafe_verde"
    assert row["exports_bags_60kg"] == pytest.approx(84.0)
    assert row["exports_value_usd"] == pytest.approx(60776.73)


def test_conflicting_duplicate_monthly_metric_raises() -> None:
    duplicate = pd.concat([
        _monthly_series(700.0, "produccion_mensual"),
        _monthly_series(701.0, "produccion_mensual"),
    ])
    with pytest.raises(ValueError, match="conflicting duplicate"):
        transform_fnc_colombia_monthly({"produccion_mensual": duplicate})
