"""Silver transforms for FNC Colombia coffee Excel bronze data."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import reduce

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.transforms.raw_to_bronze.fnc_excel import _snake

logger = get_logger(__name__)

LEVIATHAN_SLUG = "arabica_coffee"
COUNTRY = "colombia"
SOURCE = "fnc_colombia"

MONTHLY_OUTPUT_COLUMNS = [
    "leviathan_slug",
    "country",
    "year",
    "month",
    "date",
    "production_bags_60kg",
    "ex_dock_price_usd_cents_per_lb",
    "internal_price_cop_per_125kg",
    "exports_bags_60kg",
    "exports_value_usd_m",
    "source",
]

AREA_OUTPUT_COLUMNS = [
    "leviathan_slug",
    "country",
    "department",
    "department_raw",
    "year",
    "area_ha",
    "source",
]

EXPORTS_PORT_TYPE_OUTPUT_COLUMNS = [
    "leviathan_slug",
    "country",
    "year",
    "month",
    "date",
    "port",
    "port_raw",
    "coffee_type",
    "coffee_type_raw",
    "exports_bags_60kg",
    "exports_value_usd",
    "source",
]

_MONTHLY_SERIES_TO_COLUMN = {
    "produccion_mensual": ("production_bags_60kg", 1000.0),
    "precio_ex_dock_mensual": ("ex_dock_price_usd_cents_per_lb", 1.0),
    "precio_interno_mensual": ("internal_price_cop_per_125kg", 1.0),
    "exportaciones_total_volumen": ("exports_bags_60kg", 1000.0),
    "exportaciones_total_valor": ("exports_value_usd_m", 1.0),
}


@dataclass(frozen=True)
class FncColombiaSilver:
    monthly: pd.DataFrame
    area_department: pd.DataFrame
    exports_port_type: pd.DataFrame


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _date_or_none(value: object) -> date | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _validate_unique(df: pd.DataFrame, key_cols: list[str], value_col: str, label: str) -> pd.DataFrame:
    duplicate_mask = df.duplicated(subset=key_cols, keep=False)
    if not duplicate_mask.any():
        return df

    duplicates = df.loc[duplicate_mask].copy()
    conflicts: list[tuple[object, ...]] = []
    for key, group in duplicates.groupby(key_cols, dropna=False):
        if group[value_col].dropna().nunique() > 1:
            conflicts.append(key)

    if conflicts:
        preview = ", ".join(str(item) for item in conflicts[:5])
        raise ValueError(f"FNC Colombia {label} has conflicting duplicate rows for {preview}")

    return df.drop_duplicates(subset=key_cols, keep="last").copy()


def _monthly_metric_frame(series_name: str, df: pd.DataFrame) -> pd.DataFrame:
    output_col, multiplier = _MONTHLY_SERIES_TO_COLUMN[series_name]
    required = {"year", "month", "date", "value"}
    if missing := required - set(df.columns):
        raise ValueError(f"FNC bronze series {series_name!r} is missing columns: {missing}")

    work = df.copy()
    work["year"] = pd.to_numeric(work["year"], errors="coerce")
    work["month"] = pd.to_numeric(work["month"], errors="coerce")
    work[output_col] = pd.to_numeric(work["value"], errors="coerce") * multiplier
    work["date"] = work["date"].map(_date_or_none)
    work = work.dropna(subset=["year", "month", "date"]).copy()
    if work.empty:
        return pd.DataFrame(columns=["year", "month", "date", output_col])
    work["year"] = work["year"].astype(int)
    work["month"] = work["month"].astype(int)
    work = work[["year", "month", "date", output_col]].dropna(subset=[output_col])
    return _validate_unique(
        work,
        ["year", "month", "date"],
        output_col,
        series_name,
    )


def transform_fnc_colombia_monthly(bronze_series: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Create the business-facing monthly FNC Colombia coffee table."""
    frames = [
        _monthly_metric_frame(series_name, bronze_series[series_name])
        for series_name in _MONTHLY_SERIES_TO_COLUMN
        if series_name in bronze_series and not bronze_series[series_name].empty
    ]
    if not frames:
        return _empty(MONTHLY_OUTPUT_COLUMNS)

    monthly = reduce(
        lambda left, right: left.merge(right, on=["year", "month", "date"], how="outer"),
        frames,
    )
    monthly["leviathan_slug"] = LEVIATHAN_SLUG
    monthly["country"] = COUNTRY
    monthly["source"] = SOURCE

    for col in MONTHLY_OUTPUT_COLUMNS:
        if col not in monthly.columns:
            monthly[col] = pd.NA
    for col in [
        "production_bags_60kg",
        "ex_dock_price_usd_cents_per_lb",
        "internal_price_cop_per_125kg",
        "exports_bags_60kg",
        "exports_value_usd_m",
    ]:
        monthly[col] = pd.to_numeric(monthly[col], errors="coerce").astype("Float64")

    monthly = monthly[MONTHLY_OUTPUT_COLUMNS].sort_values(["year", "month"], kind="stable")
    logger.info("FNC Colombia monthly silver produced %d rows", len(monthly))
    return monthly.reset_index(drop=True)


def transform_fnc_colombia_area_department(df: pd.DataFrame) -> pd.DataFrame:
    """Create annual Colombian coffee area by department."""
    required = {"year", "department_raw", "department", "area_1000_ha"}
    if missing := required - set(df.columns):
        raise ValueError(f"FNC area_departamento bronze is missing columns: {missing}")
    if df.empty:
        return _empty(AREA_OUTPUT_COLUMNS)

    work = df.copy()
    work["year"] = pd.to_numeric(work["year"], errors="coerce")
    work["area_ha"] = pd.to_numeric(work["area_1000_ha"], errors="coerce") * 1000.0
    work["department_raw"] = work["department_raw"].astype(str).str.strip()
    work["department"] = work["department"].fillna(work["department_raw"]).map(_snake)
    work = work.dropna(subset=["year", "area_ha"]).copy()
    work["year"] = work["year"].astype(int)
    work["leviathan_slug"] = LEVIATHAN_SLUG
    work["country"] = COUNTRY
    work["source"] = SOURCE

    work = _validate_unique(
        work,
        ["department", "year"],
        "area_ha",
        "area_departamento",
    )
    area = work[AREA_OUTPUT_COLUMNS].sort_values(["year", "department"], kind="stable")
    logger.info("FNC Colombia area department silver produced %d rows", len(area))
    return area.reset_index(drop=True)


def transform_fnc_colombia_exports_port_type(df: pd.DataFrame) -> pd.DataFrame:
    """Create monthly Colombian coffee exports by port and coffee type."""
    required = {
        "year",
        "month",
        "date",
        "port_raw",
        "port",
        "coffee_type_raw",
        "coffee_type",
        "exports_bags_60kg",
        "exports_value_usd",
    }
    if missing := required - set(df.columns):
        raise ValueError(f"FNC exportaciones_puerto_tipo bronze is missing columns: {missing}")
    if df.empty:
        return _empty(EXPORTS_PORT_TYPE_OUTPUT_COLUMNS)

    work = df.copy()
    work["year"] = pd.to_numeric(work["year"], errors="coerce")
    work["month"] = pd.to_numeric(work["month"], errors="coerce")
    work["date"] = work["date"].map(_date_or_none)
    work["port_raw"] = work["port_raw"].astype(str).str.strip()
    work["coffee_type_raw"] = work["coffee_type_raw"].astype(str).str.strip()
    work["port"] = work["port"].fillna(work["port_raw"]).map(_snake)
    work["coffee_type"] = work["coffee_type"].fillna(work["coffee_type_raw"]).map(_snake)
    work["exports_bags_60kg"] = pd.to_numeric(work["exports_bags_60kg"], errors="coerce")
    work["exports_value_usd"] = pd.to_numeric(work["exports_value_usd"], errors="coerce")
    work = work.dropna(subset=["year", "month", "date"]).copy()
    work["year"] = work["year"].astype(int)
    work["month"] = work["month"].astype(int)

    group_cols = [
        "year",
        "month",
        "date",
        "port",
        "port_raw",
        "coffee_type",
        "coffee_type_raw",
    ]
    grouped = work.groupby(group_cols, dropna=False, as_index=False).agg(
        exports_bags_60kg=("exports_bags_60kg", "sum"),
        exports_value_usd=("exports_value_usd", "sum"),
    )
    grouped["leviathan_slug"] = LEVIATHAN_SLUG
    grouped["country"] = COUNTRY
    grouped["source"] = SOURCE
    exports = grouped[EXPORTS_PORT_TYPE_OUTPUT_COLUMNS].sort_values(
        ["year", "month", "port", "coffee_type"],
        kind="stable",
    )
    logger.info("FNC Colombia export port/type silver produced %d rows", len(exports))
    return exports.reset_index(drop=True)


def transform_fnc_colombia_bronze_to_silver(
    bronze_series: dict[str, pd.DataFrame],
) -> FncColombiaSilver:
    """Convert FNC Colombia bronze series into all silver tables."""
    monthly = transform_fnc_colombia_monthly(bronze_series)
    area = transform_fnc_colombia_area_department(
        bronze_series.get("area_departamento", pd.DataFrame())
    )
    exports = transform_fnc_colombia_exports_port_type(
        bronze_series.get("exportaciones_puerto_tipo", pd.DataFrame())
    )
    return FncColombiaSilver(
        monthly=monthly,
        area_department=area,
        exports_port_type=exports,
    )
