"""Bronze transform for CONAB per-bulletin Excel (previsão de safra) files.

Reads coffee production forecast XLS/XLSX files downloaded from the
CONAB gov.br portal and normalises them into a long/tidy bronze DataFrame.

Format notes
------------
Files may be either:
  - OLE compound document (.xls, Excel 97-2003) — read with ``xlrd``
  - Open XML (.xlsx) — read with ``openpyxl``

Format is detected from the first four bytes (magic number), not from
the file extension.

Sheet structure
---------------
Each sheet typically covers one commodity type (Arabica, Robusta/Conilon,
or Total Café).  Rows correspond to Brazilian states and regional totals.
Columns contain the CONAB production elements (area, yield, production).

The sheet/column names are in Brazilian Portuguese.  A best-effort
pt-BR → English mapping is applied to known patterns; unrecognised
column names are retained as-is (snake_cased) so no data is silently lost.

Output schema
-------------
Long/tidy format per row:
    (safra_year, survey, commodity, region, element, value, unit)
"""
from __future__ import annotations

import io
import re
from typing import Any

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# Magic bytes for format detection
_OLE_MAGIC  = b"\xd0\xcf\x11\xe0"
_OOXML_MAGIC = b"PK\x03\x04"

# Sheet name → leviathan commodity slug (case-insensitive substring match)
_SHEET_COMMODITY_MAP: dict[str, str] = {
    "arábica":   "arabica_coffee",
    "arabica":   "arabica_coffee",
    "robusta":   "robusta_coffee",
    "conilon":   "robusta_coffee",
    "total":     "arabica_coffee",   # aggregate sheet → maps to total
    "café":      "arabica_coffee",   # fallback
    "cafe":      "arabica_coffee",
}

# Known pt-BR column headers → English element names (substring match)
_ELEMENT_MAP: dict[str, str] = {
    "área em formação":       "area_in_formation_ha",
    "area em formacao":       "area_in_formation_ha",
    "área em produção":       "area_in_production_ha",
    "area em producao":       "area_in_production_ha",
    "área total":             "area_total_ha",
    "area total":             "area_total_ha",
    "produtividade":          "yield_bags_per_ha",
    "produção":               "production_thousand_bags",
    "producao":               "production_thousand_bags",
    "prod.":                  "production_thousand_bags",
}


def _detect_engine(raw_bytes: bytes) -> str:
    """Return ``"xlrd"`` for OLE .xls or ``"openpyxl"`` for Open XML .xlsx."""
    if raw_bytes[:4] == _OLE_MAGIC:
        return "xlrd"
    if raw_bytes[:4] == _OOXML_MAGIC:
        return "openpyxl"
    # Fallback: try openpyxl
    logger.warning("CONAB XLS: unknown magic bytes — defaulting to openpyxl engine")
    return "openpyxl"


def _snake(s: str) -> str:
    s = s.strip().lower()
    # Normalise accented characters (best-effort without unidecode)
    replacements = [
        ("á", "a"), ("ã", "a"), ("â", "a"), ("à", "a"),
        ("é", "e"), ("ê", "e"), ("í", "i"), ("ó", "o"),
        ("ô", "o"), ("ú", "u"), ("ç", "c"),
    ]
    for accented, plain in replacements:
        s = s.replace(accented, plain)
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def _map_element(raw_col: str) -> str:
    """Map a raw pt-BR column header to an English element name."""
    low = raw_col.strip().lower()
    for pattern, canonical in _ELEMENT_MAP.items():
        if pattern in low:
            return canonical
    return _snake(raw_col)


def _infer_commodity(sheet_name: str) -> str:
    """Map a sheet name to a leviathan commodity slug."""
    low = sheet_name.strip().lower()
    for pattern, slug in _SHEET_COMMODITY_MAP.items():
        if pattern in low:
            return slug
    return "unknown"


def _parse_sheet(
    df_raw: pd.DataFrame,
    sheet_name: str,
    safra_year: int,
    survey: int,
) -> pd.DataFrame | None:
    """Try to parse one worksheet into long-format rows.

    Returns None if the sheet appears to be a cover or legend page.
    """
    if df_raw.shape[1] < 3 or df_raw.shape[0] < 3:
        return None

    commodity = _infer_commodity(sheet_name)

    # Heuristic: find the header row — the first row that contains a known
    # element keyword in any cell.
    header_idx: int | None = None
    for i, row in df_raw.iterrows():
        row_str = " ".join(str(v).lower() for v in row.values)
        if any(kw in row_str for kw in ("área", "area", "produtividade", "produção", "producao")):
            header_idx = int(str(i))
            break

    if header_idx is None:
        # Fall back to treating row 0 as header
        header_idx = 0

    # Re-read with the correct header
    df = df_raw.iloc[header_idx + 1:].copy()
    raw_headers = list(df_raw.iloc[header_idx])

    # Map headers to element names
    mapped_headers: list[str] = []
    for h in raw_headers:
        mapped_headers.append(_map_element(str(h)) if pd.notna(h) else "unknown_col")

    df.columns = mapped_headers[: len(df.columns)]

    # First column is the region/state name
    region_col = df.columns[0]
    df = df.rename(columns={region_col: "region"})
    df["region"] = df["region"].astype(str).str.strip()

    # Drop rows where region is empty or looks like a header repeat
    df = df[df["region"].str.len() > 0]
    df = df[~df["region"].str.lower().isin({"nan", "none", ""})]

    if df.empty:
        return None

    # Melt value columns to long format
    value_cols = [c for c in df.columns if c not in ("region", "unknown_col")]
    if not value_cols:
        return None

    df_long = df.melt(
        id_vars=["region"],
        value_vars=value_cols,
        var_name="element",
        value_name="value",
    )
    df_long["value"] = pd.to_numeric(
        df_long["value"].astype(str).str.replace(",", ".", regex=False),
        errors="coerce",
    )
    df_long["commodity"] = commodity
    df_long["sheet_name"] = sheet_name
    df_long["safra_year"] = safra_year
    df_long["survey"] = survey

    return df_long.dropna(subset=["value"])


def extract_conab_xls(
    raw_bytes: bytes,
    safra_year: int,
    survey: int,
    ingest_date: str,
) -> pd.DataFrame:
    """Parse a CONAB bulletin XLS/XLSX into a long/tidy bronze DataFrame.

    Args:
        raw_bytes:   Raw bytes of the Excel file as stored in S3.
        safra_year:  Marketing year (e.g. ``2026``).
        survey:      Survey number within the season (1–5).
        ingest_date: ISO date string when bronze was written.

    Returns:
        Long-format DataFrame with columns
        ``(safra_year, survey, commodity, sheet_name, region, element, value)``.

    Raises:
        ValueError: If no parseable sheets are found.
    """
    engine = _detect_engine(raw_bytes)
    logger.info("CONAB XLS safra=%d survey=%d  engine=%s", safra_year, survey, engine)

    xl = pd.ExcelFile(io.BytesIO(raw_bytes), engine=engine)
    frames: list[pd.DataFrame] = []

    for sheet in xl.sheet_names:
        try:
            df_raw = xl.parse(sheet, header=None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("CONAB: could not parse sheet '%s': %s", sheet, exc)
            continue

        df_parsed = _parse_sheet(df_raw, sheet, safra_year, survey)
        if df_parsed is not None and not df_parsed.empty:
            frames.append(df_parsed)

    if not frames:
        raise ValueError(
            f"CONAB XLS safra={safra_year} survey={survey}: no parseable sheets found"
        )

    result = pd.concat(frames, ignore_index=True)
    result["source"] = "conab_xls"
    result["ingest_date"] = ingest_date

    logger.info(
        "CONAB XLS extract complete  safra=%d  survey=%d  rows=%d  sheets=%d",
        safra_year, survey, len(result), len(frames),
    )
    return result
