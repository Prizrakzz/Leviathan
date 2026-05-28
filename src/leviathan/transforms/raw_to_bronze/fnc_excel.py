"""Bronze transform for FNC Colombia bulk Excel data files.

Extracts the 7 named series from the two FNC Excel files and writes them
as long/tidy bronze Parquets.

Source files
------------
  Precios-area-y-produccion-de-cafe-YYYY-N.xlsx
    Series extracted:
      produccion_mensual         — monthly production (1000s 60kg bags), 1956+
      precio_ex_dock_mensual     — external price (USD cents/lb), 1913+
      precio_interno_mensual     — internal price (COP/125kg), 1944+
      area_departamento          — area by department (1000s ha), 2002+

  Exportaciones-YYYY-N.xlsx
    Series extracted:
      exportaciones_total_volumen — monthly volume (1000s 60kg bags), 1958+
      exportaciones_total_valor   — monthly value (M USD), 1958+
      exportaciones_puerto_tipo   — volume+value by port and type, 2000+

Sheet structure (common pattern)
---------------------------------
- Row 0–N: title / metadata rows
- A column with year (int) or date label
- Remaining columns: country/product/market headings
- Values may be blank, "n.d.", or numeric
"""
from __future__ import annotations

import io
import re

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Sheet → series name mapping (case-insensitive substring match on sheet name)
# ---------------------------------------------------------------------------

_SHEET_SERIES_MAP: dict[str, str] = {
    "producción mensual":       "produccion_mensual",
    "produccion mensual":       "produccion_mensual",
    "precio ex_dock mensual":   "precio_ex_dock_mensual",
    "precio interno mensual":   "precio_interno_mensual",
    "área cult":                "area_departamento",
    "area cult":                "area_departamento",
    "total_volumen":            "exportaciones_total_volumen",
    "total_valor":              "exportaciones_total_valor",
    "puerto_tipo":              "exportaciones_puerto_tipo",
}


def _snake(s: str) -> str:
    s = s.strip().lower()
    for accented, plain in [
        ("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n"),
    ]:
        s = s.replace(accented, plain)
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def _infer_series(sheet_name: str) -> str | None:
    low = sheet_name.strip().lower()
    for pattern, canonical in _SHEET_SERIES_MAP.items():
        if pattern in low:
            return canonical
    return None


def _find_header_row(df_raw: pd.DataFrame) -> int:
    """Find the first row that looks like a data header (contains a year-ish value)."""
    for i in range(min(10, len(df_raw))):
        row_vals = df_raw.iloc[i].astype(str)
        # A data row starts when column 0 looks like a 4-digit year
        if re.match(r"^\d{4}$", row_vals.iloc[0].strip()):
            return i
    return 0


def _parse_series_sheet(
    df_raw: pd.DataFrame,
    series_name: str,
    filename: str,
) -> pd.DataFrame:
    """Normalise one FNC Excel sheet into a long/tidy DataFrame."""
    if df_raw.shape[1] < 2 or df_raw.shape[0] < 3:
        return pd.DataFrame()

    # Find where header row is
    header_row = _find_header_row(df_raw)

    # Use row above data as column headers (if it exists)
    if header_row > 0:
        col_headers = [str(v).strip() for v in df_raw.iloc[header_row - 1]]
    else:
        col_headers = [f"col_{i}" for i in range(df_raw.shape[1])]

    df = df_raw.iloc[header_row:].copy()
    df.columns = col_headers[: df.shape[1]]

    # Rename first column to "period"
    first_col = df.columns[0]
    df = df.rename(columns={first_col: "period"})
    df["period"] = df["period"].astype(str).str.strip()

    # Keep only rows where period looks like a year or date
    period_mask = df["period"].str.match(r"^\d{4}")
    df = df.loc[period_mask].copy()

    if df.empty:
        return pd.DataFrame()

    # Melt all non-period columns to long
    value_cols = [c for c in df.columns if c != "period"]
    df_long = df.melt(
        id_vars=["period"],
        value_vars=value_cols,
        var_name="dimension",
        value_name="value",
    )
    df_long["dimension"] = df_long["dimension"].astype(str).apply(_snake)
    df_long["value"] = pd.to_numeric(
        df_long["value"].astype(str).str.replace(",", ".", regex=False),
        errors="coerce",
    )
    df_long["series_name"] = series_name
    df_long["source_file"] = filename

    return df_long.dropna(subset=["value"])


def extract_fnc_excel(
    raw_bytes: bytes,
    filename: str,
    ingest_date: str,
) -> dict[str, pd.DataFrame]:
    """Parse a FNC Colombia bulk Excel file into a dict of series DataFrames.

    Args:
        raw_bytes:   Raw bytes of the XLSX file as stored in S3.
        filename:    Original filename (used as metadata and to distinguish the
                     two FNC files).
        ingest_date: ISO date string when bronze was written.

    Returns:
        Dict mapping series name → long-format DataFrame.
        May be empty if no target sheets were found.
    """
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

        df = _parse_series_sheet(df_raw, series_name, filename)
        if df.empty:
            logger.warning("FNC: sheet '%s' parsed to empty DataFrame", sheet)
            continue

        df["source"] = "fnc_excel"
        df["ingest_date"] = ingest_date
        results[series_name] = df
        logger.info("FNC: series '%s'  rows=%d", series_name, len(df))

    logger.info(
        "FNC extract complete  file=%s  series=%s",
        filename, list(results.keys()),
    )
    return results
