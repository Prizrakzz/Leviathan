"""Bronze transform for FNC Colombia bulk Excel data files.

FNC publishes two full-history Excel workbooks for Colombian coffee statistics.
The sheets are not laid out as a single tidy table, so this module parses each
known sheet shape explicitly and emits typed bronze series for silver.
"""
from __future__ import annotations

import io
import re
import unicodedata
from datetime import date

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

MONTHLY_SERIES_UNITS = {
    "produccion_mensual": "1000_bags_60kg",
    "precio_ex_dock_mensual": "usd_cents_per_lb",
    "precio_interno_mensual": "cop_per_125kg",
    "exportaciones_total_volumen": "1000_bags_60kg",
    "exportaciones_total_valor": "usd_m",
}

_SHEET_SERIES_PATTERNS: tuple[tuple[str, str], ...] = (
    ("produccion_mensual", "produccion_mensual"),
    ("precio_ex_dock_mensual", "precio_ex_dock_mensual"),
    ("precio_interno_mensual", "precio_interno_mensual"),
    ("area_cult_dep_producto", "area_departamento"),
    ("total_volumen", "exportaciones_total_volumen"),
    ("total_valor", "exportaciones_total_valor"),
    ("puerto_tipo_vol_val", "exportaciones_puerto_tipo"),
)


def _normalise_text(value: object) -> str:
    text = "" if pd.isna(value) else str(value).strip().lower()
    text = "".join(
        ch
        for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def _snake(value: object) -> str:
    return _normalise_text(value)


def _date_or_none(value: object) -> date | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _first_day(year: int, month: int) -> date:
    return date(int(year), int(month), 1)


def _infer_series(sheet_name: object) -> str | None:
    normalised = _normalise_text(sheet_name)
    for pattern, series_name in _SHEET_SERIES_PATTERNS:
        if pattern in normalised:
            return series_name
    return None


def _numeric(value: object) -> float | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    if _normalise_text(text) in {"", "n_d", "nd", "nan", "none"}:
        return None
    parsed = pd.to_numeric(pd.Series([text.replace(",", ".")]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return None
    return float(parsed)


def _parse_monthly_sheet(
    df_raw: pd.DataFrame,
    series_name: str,
    filename: str,
) -> pd.DataFrame:
    """Parse FNC monthly date/value sheets."""
    for row_idx in range(len(df_raw)):
        for col_idx in range(max(df_raw.shape[1] - 1, 0)):
            parsed_date = _date_or_none(df_raw.iat[row_idx, col_idx])
            parsed_value = _numeric(df_raw.iat[row_idx, col_idx + 1])
            if parsed_date is None or parsed_value is None:
                continue

            records: list[dict[str, object]] = []
            for _, row in df_raw.iloc[row_idx:, [col_idx, col_idx + 1]].iterrows():
                observed_date = _date_or_none(row.iloc[0])
                value = _numeric(row.iloc[1])
                if observed_date is None or value is None:
                    continue
                records.append({
                    "series_name": series_name,
                    "year": observed_date.year,
                    "month": observed_date.month,
                    "date": observed_date,
                    "value": value,
                    "unit": MONTHLY_SERIES_UNITS[series_name],
                    "source_file": filename,
                })
            return pd.DataFrame(records)

    return pd.DataFrame()


def _parse_area_department_sheet(df_raw: pd.DataFrame, filename: str) -> pd.DataFrame:
    """Parse the annual department-by-year cultivated area sheet."""
    header_row: int | None = None
    department_col: int | None = None
    for row_idx in range(len(df_raw)):
        for col_idx, value in enumerate(df_raw.iloc[row_idx].tolist()):
            if _normalise_text(value) == "departamento":
                header_row = row_idx
                department_col = col_idx
                break
        if header_row is not None:
            break

    if header_row is None or department_col is None:
        return pd.DataFrame()

    headers = df_raw.iloc[header_row].tolist()
    records: list[dict[str, object]] = []
    for _, row in df_raw.iloc[header_row + 1:].iterrows():
        department_raw = row.iloc[department_col]
        if pd.isna(department_raw):
            continue
        department_raw = str(department_raw).strip()
        if not department_raw or _normalise_text(department_raw) == "total":
            continue

        for col_idx, header_value in enumerate(headers):
            match = re.search(r"\d{4}", str(header_value))
            if not match:
                continue
            value = _numeric(row.iloc[col_idx])
            if value is None:
                continue
            records.append({
                "series_name": "area_departamento",
                "year": int(match.group()),
                "department_raw": department_raw,
                "department": _snake(department_raw),
                "area_1000_ha": value,
                "unit": "1000_ha",
                "source_file": filename,
            })

    return pd.DataFrame(records)


def _parse_port_type_sheet(df_raw: pd.DataFrame, filename: str) -> pd.DataFrame:
    """Parse monthly export volume/value by port and coffee type."""
    header_row: int | None = None
    for row_idx in range(len(df_raw)):
        header_values = [_normalise_text(value) for value in df_raw.iloc[row_idx].tolist()]
        if "ano" in header_values and "mes" in header_values:
            header_row = row_idx
            break

    if header_row is None:
        return pd.DataFrame()

    raw_headers = [_normalise_text(value) for value in df_raw.iloc[header_row].tolist()]
    keep_positions = [idx for idx, header in enumerate(raw_headers) if header and header != "nan"]
    data = df_raw.iloc[header_row + 1:, keep_positions].copy()
    data.columns = [raw_headers[idx] for idx in keep_positions]
    data = data.rename(columns={
        "ano": "year",
        "mes": "month",
        "puerto_de_embarque": "port_raw",
        "tipo_de_cafe": "coffee_type_raw",
        "sacos_de_60_kg_exportados": "exports_bags_60kg",
        "valor_provisional_de_la_exportacion_usd": "exports_value_usd",
    })

    required = {
        "year",
        "month",
        "port_raw",
        "coffee_type_raw",
        "exports_bags_60kg",
        "exports_value_usd",
    }
    if missing := required - set(data.columns):
        raise ValueError(f"FNC export port/type sheet is missing columns: {missing}")

    records: list[dict[str, object]] = []
    for _, row in data.iterrows():
        year = _numeric(row["year"])
        month = _numeric(row["month"])
        if year is None or month is None:
            continue
        port_raw = "" if pd.isna(row["port_raw"]) else str(row["port_raw"]).strip()
        coffee_type_raw = (
            "" if pd.isna(row["coffee_type_raw"]) else str(row["coffee_type_raw"]).strip()
        )
        if not port_raw or not coffee_type_raw:
            continue
        records.append({
            "series_name": "exportaciones_puerto_tipo",
            "year": int(year),
            "month": int(month),
            "date": _first_day(int(year), int(month)),
            "port_raw": port_raw,
            "port": _snake(port_raw),
            "coffee_type_raw": coffee_type_raw,
            "coffee_type": _snake(coffee_type_raw),
            "exports_bags_60kg": _numeric(row["exports_bags_60kg"]),
            "exports_value_usd": _numeric(row["exports_value_usd"]),
            "source_file": filename,
        })

    result = pd.DataFrame(records)
    if result.empty:
        return result
    return result.dropna(subset=["exports_bags_60kg", "exports_value_usd"], how="all")


def _parse_series_sheet(
    df_raw: pd.DataFrame,
    series_name: str,
    filename: str,
) -> pd.DataFrame:
    if series_name in MONTHLY_SERIES_UNITS:
        return _parse_monthly_sheet(df_raw, series_name, filename)
    if series_name == "area_departamento":
        return _parse_area_department_sheet(df_raw, filename)
    if series_name == "exportaciones_puerto_tipo":
        return _parse_port_type_sheet(df_raw, filename)
    raise ValueError(f"Unsupported FNC series: {series_name}")


def extract_fnc_excel(
    raw_bytes: bytes,
    filename: str,
    ingest_date: str,
) -> dict[str, pd.DataFrame]:
    """Parse a FNC Colombia bulk Excel file into named bronze series."""
    xl = pd.ExcelFile(io.BytesIO(raw_bytes), engine="openpyxl")
    results: dict[str, pd.DataFrame] = {}

    for sheet in xl.sheet_names:
        series_name = _infer_series(sheet)
        if series_name is None:
            logger.debug("FNC: skipping sheet '%s' (no series match)", sheet)
            continue

        try:
            df_raw = xl.parse(sheet, header=None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("FNC: could not parse sheet '%s': %s", sheet, exc)
            continue

        try:
            df = _parse_series_sheet(df_raw, series_name, filename)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "FNC parser failed sheet='%s': %s",
                sheet,
                exc,
                exc_info=True,
            )
            continue
        if df.empty:
            logger.warning("FNC: sheet '%s' parsed to empty DataFrame", sheet)
            continue

        df["source"] = "fnc_excel"
        df["ingest_date"] = ingest_date
        results[series_name] = df.reset_index(drop=True)
        logger.info("FNC: series '%s' rows=%d", series_name, len(df))

    logger.info("FNC extract complete file=%s series=%s", filename, list(results.keys()))
    return results
