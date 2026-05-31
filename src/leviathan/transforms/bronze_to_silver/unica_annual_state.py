"""Silver transform for UNICA Brazil Centre-South annual production by state.

Converts per-season EAV bronze rows (long format, 5 variables × 27 states/regions)
into a wide annual table keyed on (harvest_year, state_region).

Design notes
------------
* **Source** — UNICA historical HTML table (idTabela=2495, tipoHistorico=4),
  which reports cumulative annual totals per Brazilian state and regional
  aggregate for the Centre-South milling region.

* **Granularity** — one row per (harvest_year, state_region).  41 seasons
  (1980/1981–2020/2021) × 27 rows each = 1,107 output rows.

* **period_label** — in this bronze the period_label column holds the state
  or region name (e.g. "São Paulo", "South-Central Region", "Brazil") rather
  than a fortnight label.  It is renamed to ``state_region`` in silver.

* **Values are annual totals** — no CTD/incremental distinction needed.

* **Coverage** — 1980/1981–2020/2021 (historical HTML source).
  Post-2020/2021 data is sourced from ``unica_biweekly`` PDFs (separate pipeline).

No S3 or AWS dependencies — pure data transformation.
"""
from __future__ import annotations

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# Maps bronze EAV variable names to silver column names.
_VAR_TO_COL: dict[str, str] = {
    "cane_crushed_t":       "cane_crushed_t",
    "sugar_produced_t":     "sugar_produced_t",
    "ethanol_total_m3":     "ethanol_total_m3",
    "ethanol_hydrous_m3":   "ethanol_hydrous_m3",
    "ethanol_anhydrous_m3": "ethanol_anhydrous_m3",
}

# Canonical output column order.
OUTPUT_COLUMNS: list[str] = [
    "harvest_year",
    "state_region",
    "cane_crushed_t",
    "sugar_produced_t",
    "ethanol_total_m3",
    "ethanol_hydrous_m3",
    "ethanol_anhydrous_m3",
    "source",
]


def transform_unica_annual_state(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Transform UNICA annual-by-state bronze EAV rows to wide silver.

    Args:
        df_bronze: Concatenation of all per-season bronze Parquets.  Must
            contain columns ``(harvest_year, period_label, variable, value)``.
            The ``source`` column is optional; defaults to ``"unica"`` if absent.

    Returns:
        Wide DataFrame with columns defined by ``OUTPUT_COLUMNS``, one row per
        (harvest_year, state_region), sorted ascending by those keys.

    Raises:
        ValueError: If required columns are missing from ``df_bronze``.
    """
    required = {"harvest_year", "period_label", "variable", "value"}
    missing = required - set(df_bronze.columns)
    if missing:
        raise ValueError(f"UNICA bronze missing columns: {sorted(missing)}")

    df = df_bronze.copy()

    # Drop rows for variables not in our target set.
    wanted = set(_VAR_TO_COL.keys())
    df = df[df["variable"].isin(wanted)].copy()
    if df.empty:
        logger.warning("UNICA annual state silver: no matching variables in bronze input")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    # Rename period_label → state_region (the label IS the state/region name).
    df = df.rename(columns={"period_label": "state_region"})

    # Drop rows with empty/null state_region.
    df = df[df["state_region"].notna()].copy()
    df = df[df["state_region"].astype(str).str.strip() != ""].copy()
    df = df[~df["state_region"].astype(str).str.lower().isin({"nan", "none", "total"})].copy()

    if df.empty:
        logger.warning("UNICA annual state silver: no rows after state_region filter")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    # Determine source value before pivot.
    source_val = df["source"].iloc[0] if "source" in df.columns else "unica"

    # Deduplicate — guard against duplicate ingestion runs.
    df = df.drop_duplicates(subset=["harvest_year", "state_region", "variable"], keep="first")

    # Rename variable values to silver column names, then pivot.
    df["variable"] = df["variable"].map(_VAR_TO_COL)

    wide = df.pivot_table(
        index=["harvest_year", "state_region"],
        columns="variable",
        values="value",
        aggfunc="first",
    ).reset_index()
    wide.columns.name = None

    # Ensure all expected metric columns are present (sparse years may lack some).
    for col in _VAR_TO_COL.values():
        if col not in wide.columns:
            wide[col] = float("nan")

    wide["source"] = source_val

    wide = wide.sort_values(["harvest_year", "state_region"]).reset_index(drop=True)

    logger.info(
        "UNICA annual state silver: %d rows (%d seasons)",
        len(wide),
        wide["harvest_year"].nunique(),
    )

    # Reorder and return only OUTPUT_COLUMNS.
    for col in OUTPUT_COLUMNS:
        if col not in wide.columns:
            wide[col] = float("nan")
    return wide[OUTPUT_COLUMNS].reset_index(drop=True)
