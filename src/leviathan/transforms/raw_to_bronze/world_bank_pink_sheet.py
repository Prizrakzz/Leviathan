"""Bronze transform for the World Bank Pink Sheet (monthly commodity prices).

Extracts the 6 fertiliser / energy series used as cost-of-production proxies:

  - Urea E. Europe bulk spot (USD/mt)
  - DAP spot (USD/mt)
  - Potassium chloride standard (USD/mt)
  - Natural gas US (USD/mmbtu)
  - Natural gas Europe (USD/mmbtu)
  - Phosphate rock (USD/mt)

Source format
-------------
Excel workbook with many sheets.  The relevant sheet is "Monthly Prices"
(header on row 5, index=4).  Column 0 contains dates in ``YYYYMXX`` format
(e.g. ``"1960M01"``).

The 6 target series are identified by case-insensitive substring matching on
the column header.  This is defensive against minor header wording changes
between WB releases.

Output schema
-------------
Long/tidy format:  (release_ym, date, series_name, value_usd)
"""
from __future__ import annotations

import io
from typing import Sequence

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# Substring patterns → canonical bronze series names.
# Each pattern must match exactly one column. For a REQUIRED series (see ``_REQUIRED_SERIES``) a
# missing or ambiguous header FAILS the extract (SILVER-F023: a disappeared/ambiguous required
# header must never publish a silently narrowed table); a non-required series only WARNs.
#
# SILVER-F023 restores the 9 commodity-price series the narrowed producer had dropped. The patterns
# are chosen to be unambiguous against the World Bank "Monthly Prices" nominal sheet headers
# (e.g. "Crude oil, Brent" vs "Crude oil, average/Dubai/WTI"; "Soybeans" vs "Soybean oil/meal").
_SERIES_PATTERNS: dict[str, str] = {
    # fertilizer + energy
    "urea":                "urea_e_europe_bulk_spot_usd_mt",
    "dap":                 "dap_spot_usd_mt",
    "potassium chloride":  "potassium_chloride_std_usd_mt",
    "natural gas, us":     "natural_gas_us_usd_mmbtu",
    "natural gas, europe": "natural_gas_europe_usd_mmbtu",
    "phosphate rock":      "phosphate_rock_usd_mt",
    # commodity prices (SILVER-F023)
    "crude oil, brent":    "crude_oil_brent_usd_bbl",
    "soybeans":            "soybeans_usd_mt",
    "soybean oil":         "soybean_oil_usd_mt",
    "soybean meal":        "soybean_meal_usd_mt",
    "palm oil":            "palm_oil_usd_mt",
    "sugar, world":        "sugar_world_usd_kg",
    "wheat, us hrw":       "wheat_us_hrw_usd_mt",
    "wheat, us srw":       "wheat_us_srw_usd_mt",
    "rapeseed oil":        "rapeseed_oil_usd_mt",
}

# The governed series whose absence/ambiguity is FATAL to the extract (the full 15-series contract).
_REQUIRED_SERIES: frozenset[str] = frozenset(_SERIES_PATTERNS.values())

_SHEET_NAME = "Monthly Prices"
_HEADER_ROW = 4   # 0-indexed; row 5 in the workbook (1-indexed)


def _match_columns(
    columns: Sequence[str],
    patterns: dict[str, str],
    required: "frozenset[str]" = frozenset(),
) -> dict[str, str]:
    """Return a rename map {original_header: canonical_name} for matched series.

    A canonical name in ``required`` that has NO match or an AMBIGUOUS (>1) match raises
    ``ValueError`` -- SILVER-F023 fail-closed: a disappeared/ambiguous required header must never
    publish a silently narrowed table. A non-required series only WARNs (legacy behaviour)."""
    col_lower = {c: c.lower() for c in columns}
    result: dict[str, str] = {}
    missing: list[str] = []
    ambiguous: list[str] = []
    for pattern, canonical in patterns.items():
        matches = [orig for orig, low in col_lower.items() if pattern.lower() in low]
        if not matches:
            if canonical in required:
                missing.append(canonical)
            else:
                logger.warning("Pink Sheet: no column matched pattern '%s'", pattern)
        elif len(matches) > 1:
            if canonical in required:
                ambiguous.append(f"{canonical} <- {matches}")
            else:
                logger.warning(
                    "Pink Sheet: pattern '%s' matched %d columns %s — using first",
                    pattern, len(matches), matches,
                )
                result[matches[0]] = canonical
        else:
            result[matches[0]] = canonical
    if missing or ambiguous:
        raise ValueError(
            "Pink Sheet: required governed series unresolved -- "
            f"missing={sorted(missing)} ambiguous={sorted(ambiguous)}. "
            "Refusing to publish a narrowed table (SILVER-F023)."
        )
    return result


def extract_pink_sheet(
    raw_bytes: bytes,
    release_ym: str,
) -> pd.DataFrame:
    """Parse a raw Pink Sheet XLSX into a long/tidy bronze DataFrame.

    Args:
        raw_bytes:  Raw bytes of the Excel workbook as stored in S3.
        release_ym: Release year-month in ``YYYYMmm`` format (e.g. ``"2026M05"``),
                    stored as a metadata column.

    Returns:
        Long-format DataFrame with columns
        ``(release_ym, date, series_name, value_usd)``.

    Raises:
        ValueError: If the sheet or date column cannot be found, or if no
                    target series columns are matched.
    """
    df_raw = pd.read_excel(
        io.BytesIO(raw_bytes),
        sheet_name=_SHEET_NAME,
        header=_HEADER_ROW,
        engine="openpyxl",
    )

    if df_raw.empty:
        raise ValueError(f"Pink Sheet sheet '{_SHEET_NAME}' is empty")

    # Column 0 contains dates in "YYYYMXX" format (e.g. "1960M01") or blank
    # rows used as separators.
    date_col = df_raw.columns[0]
    df_raw = df_raw.dropna(subset=[date_col])

    # Remove aggregates / notes rows that don't look like dates
    date_mask = df_raw[date_col].astype(str).str.match(r"^\d{4}M\d{2}$")
    df_raw = df_raw.loc[date_mask].copy()

    if df_raw.empty:
        raise ValueError(f"Pink Sheet: no valid date rows found in '{_SHEET_NAME}'")

    # Parse dates
    df_raw["date"] = pd.to_datetime(
        df_raw[date_col].astype(str), format="%YM%m", errors="coerce"
    ).dt.date
    df_raw = df_raw.dropna(subset=["date"])

    # Match target series columns
    other_cols = list(df_raw.columns[1:])
    rename_map = _match_columns(other_cols, _SERIES_PATTERNS, required=_REQUIRED_SERIES)
    if not rename_map:
        raise ValueError(
            f"Pink Sheet: no target series columns found. Available: {other_cols[:10]}"
        )

    # Keep only matched columns + date
    keep = ["date"] + list(rename_map.keys())
    df_wide = df_raw[[c for c in keep if c in df_raw.columns]].rename(columns=rename_map)

    # Melt to long format
    value_cols = [c for c in df_wide.columns if c != "date"]
    df_long = df_wide.melt(id_vars=["date"], value_vars=value_cols,
                           var_name="series_name", value_name="value_usd")
    df_long["value_usd"] = pd.to_numeric(df_long["value_usd"], errors="coerce")

    # Bronze metadata
    df_long["release_ym"] = release_ym
    df_long["source"] = "world_bank_pink_sheet"

    df_long = df_long.sort_values(["series_name", "date"]).reset_index(drop=True)

    logger.info(
        "Pink Sheet extract complete  release=%s  rows=%d  series=%s",
        release_ym,
        len(df_long),
        sorted(df_long["series_name"].unique()),
    )
    return df_long
