"""Bronze transform for UNICA Center-South Brazil production HTML pages.

Parses the PHP server-rendered production-and-milling table from the
UNICADATA portal (unicadata.com.br) and normalises it into a long/tidy
bronze DataFrame.

Source
------
One HTML page per harvest year, stored in S3 at:
    raw/production/source=unica/harvest_year={YYYY_YY}/production_milling.html

The page contains a table with:
  - One row per fortnight (quinzena) within the harvest year
  - Columns: cane crushed (t), sugar produced (t), total ethanol (m³),
    hydrous ethanol (m³), anhydrous ethanol (m³)

Output schema
-------------
Long/tidy format: (harvest_year, period_label, fortnight_number, variable, value)
"""
from __future__ import annotations

import io
import re

import pandas as pd
from bs4 import BeautifulSoup

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# Known UNICA column header substrings → canonical snake_case names
_COL_MAP: dict[str, str] = {
    "cana":           "cane_crushed_t",
    "cane":           "cane_crushed_t",
    "açúcar":         "sugar_produced_t",
    "sugar":          "sugar_produced_t",
    "acucar":         "sugar_produced_t",
    "etanol total":   "ethanol_total_m3",
    "total ethanol":  "ethanol_total_m3",
    "etanol hidrat":  "ethanol_hydrous_m3",
    "hydrous":        "ethanol_hydrous_m3",
    "etanol anid":    "ethanol_anhydrous_m3",
    "anhydrous":      "ethanol_anhydrous_m3",
}


def _canonicalize_col(header: str) -> str:
    low = header.strip().lower()
    # Normalise accented chars
    for accented, plain in [("ç", "c"), ("ú", "u"), ("á", "a"), ("ã", "a")]:
        low = low.replace(accented, plain)
    for pattern, canonical in _COL_MAP.items():
        if pattern.lower() in low:
            return canonical
    return re.sub(r"[^a-z0-9]+", "_", low).strip("_") or "unknown"


def extract_unica(
    raw_bytes: bytes,
    harvest_year: str,
    ingest_date: str,
) -> pd.DataFrame:
    """Parse a UNICA production-and-milling HTML page into a long/tidy DataFrame.

    Args:
        raw_bytes:    Raw bytes of the PHP-rendered HTML page as stored in S3.
        harvest_year: Harvest year label in slash or underscore format,
                      e.g. ``"2024/25"`` or ``"2024_25"``.
        ingest_date:  ISO date string when bronze was written.

    Returns:
        Long-format DataFrame with columns
        ``(harvest_year, period_label, fortnight_number, variable, value)``.
        May be empty if the page structure could not be parsed.
    """
    hy_canonical = harvest_year.replace("/", "_")
    html = raw_bytes.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")

    tables = soup.find_all("table")
    if not tables:
        logger.warning("UNICA: no <table> found for harvest_year=%s", hy_canonical)
        return pd.DataFrame()

    # Find the production table: the largest table with numeric data
    best_df: pd.DataFrame | None = None
    for tbl in tables:
        try:
            df_list = pd.read_html(io.StringIO(str(tbl)), header=0)
        except Exception:  # noqa: BLE001
            continue
        for df in df_list:
            if df.shape[0] > 5 and df.shape[1] >= 3:
                if best_df is None or df.shape[0] * df.shape[1] > best_df.shape[0] * best_df.shape[1]:
                    best_df = df

    if best_df is None or best_df.empty:
        logger.warning("UNICA: no suitable data table found for harvest_year=%s", hy_canonical)
        return pd.DataFrame()

    # Map column names
    df = best_df.rename(columns={c: _canonicalize_col(str(c)) for c in best_df.columns})

    # First column is the period label (e.g. "1ª Quinzena de Abril" or "Abril 1ª")
    first_col = df.columns[0]
    df = df.rename(columns={first_col: "period_label"})
    df["period_label"] = df["period_label"].astype(str).str.strip()

    # Drop separator/total rows
    df = df[df["period_label"].str.len() > 0]
    df = df[~df["period_label"].str.lower().isin({"nan", "none", "total"})]
    df = df[~df["period_label"].str.match(r"^\s*$")]

    if df.empty:
        logger.warning("UNICA: no data rows after cleaning for harvest_year=%s", hy_canonical)
        return pd.DataFrame()

    # Add fortnight sequence number
    df = df.reset_index(drop=True)
    df["fortnight_number"] = df.index + 1

    # Melt to long format
    value_cols = [c for c in df.columns if c not in ("period_label", "fortnight_number")]
    df_long = df.melt(
        id_vars=["period_label", "fortnight_number"],
        value_vars=value_cols,
        var_name="variable",
        value_name="value",
    )
    df_long["value"] = pd.to_numeric(
        df_long["value"].astype(str).str.replace(",", "", regex=False),
        errors="coerce",
    )
    df_long = df_long.dropna(subset=["value"])

    # Bronze metadata
    df_long["harvest_year"] = hy_canonical
    df_long["source"] = "unica"
    df_long["ingest_date"] = ingest_date

    logger.info(
        "UNICA extract complete  harvest_year=%s  rows=%d  variables=%s",
        hy_canonical,
        len(df_long),
        sorted(df_long["variable"].unique()),
    )
    return df_long
