"""Silver transforms for UNICA Center-South biweekly (quinzenal) bulletin data.

Converts the five bronze Parquet tables produced by the biweekly PDF extract
into four clean silver tables.  Each function is a pure data transformation —
no S3 or AWS dependencies.

Output tables
-------------
season_history     : One row per (harvest_year, fortnight_seq, region).
                     Deduplicated — each slot keeps the reading from the
                     latest bulletin that reported it.

release_series     : One row per (harvest_year, position_date, region).
                     The accumulated-total vintage series as published on each
                     bulletin release date; used for revision-surprise features.

corn_ethanol       : One row per (harvest_year, fortnight_seq).
                     Corn-derived ethanol production by fortnight; deduplicated.

monthly_ethanol_sales : One row per (harvest_year, month_num).
                     Prefers final (non-partial) monthly totals; falls back to
                     the latest partial reading for the current month.

Fortnight calendar
------------------
UNICA's crushing season runs April–March.  A fortnight label of ``DD/MM``
maps to the first year of the harvest_year range when month ≥ 4, and the
second year when month ≤ 3.  Example: harvest_year = ``"2023_2024"`` →
``15/04`` → 2023-04-15; ``31/01`` → 2024-01-31.
"""
from __future__ import annotations

import datetime
from typing import Optional

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _resolve_position_date(s: Optional[str]) -> Optional[datetime.date]:
    """Parse a ``DD/MM/YYYY`` position-date string to a :class:`datetime.date`.

    Returns ``None`` if *s* is ``None``, empty, or cannot be parsed.
    """
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.datetime.strptime(s.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def _resolve_fortnight_date(
    label: Optional[str],
    harvest_year: str,
) -> Optional[datetime.date]:
    """Resolve a ``DD/MM`` fortnight label to a full calendar date.

    Uses UNICA's April–March crushing season:
    - month 4–12 → first (start) year of *harvest_year*
    - month 1–3  → second (end) year of *harvest_year*

    Args:
        label:        ``"DD/MM"`` string, e.g. ``"15/04"``.
        harvest_year: ``"YYYY_YYYY"`` string, e.g. ``"2023_2024"``.

    Returns:
        Resolved :class:`datetime.date`, or ``None`` if either argument is
        unparseable.
    """
    if not label or not isinstance(label, str):
        return None
    try:
        parts = harvest_year.split("_")
        year_start = int(parts[0])
        year_end = int(parts[1])
        day_str, month_str = label.strip().split("/")
        day = int(day_str)
        month = int(month_str)
        year = year_start if month >= 4 else year_end
        return datetime.date(year, month, day)
    except (ValueError, IndexError, AttributeError):
        return None


def _resolve_ingest_date(s: Optional[str]) -> Optional[datetime.date]:
    """Parse an ``YYYY-MM-DD`` ingest-date string to a :class:`datetime.date`.

    Returns ``None`` on failure.
    """
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.datetime.strptime(s.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Table 1: season_history
# ---------------------------------------------------------------------------

_SEASON_HISTORY_VAR_MAP: dict[str, str] = {
    "cane_crushed":       "cane_crushed_t",
    "sugar_produced":     "sugar_produced_t",
    "ethanol_total":      "ethanol_total_m3",
    "ethanol_anhydrous":  "ethanol_anhydrous_m3",
    "ethanol_hydrous":    "ethanol_hydrous_m3",
}

SEASON_HISTORY_COLUMNS: list[str] = [
    "harvest_year",
    "fortnight_seq",
    "fortnight_label",
    "fortnight_date",
    "region",
    "cane_crushed_t",
    "sugar_produced_t",
    "ethanol_total_m3",
    "ethanol_anhydrous_m3",
    "ethanol_hydrous_m3",
    "source_idm",
    "source_position_date",
]


def transform_season_history(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Transform ``fortnight_production`` bronze rows to the season history silver.

    Args:
        df_bronze: Concatenation of all ``fortnight_production`` bronze Parquets.
            Required columns: ``harvest_year``, ``idm``, ``fortnight_seq``,
            ``fortnight_label``, ``region``, ``variable``, ``period``,
            ``value``, ``unit``, ``position_date``, ``ingest_date``.

    Returns:
        Wide DataFrame keyed on ``(harvest_year, fortnight_seq, region)``,
        one row per slot.  See ``SEASON_HISTORY_COLUMNS`` for the full schema.

    Raises:
        ValueError: If required columns are missing.
    """
    required = {
        "harvest_year", "idm", "fortnight_seq", "fortnight_label",
        "region", "variable", "period", "value", "position_date", "ingest_date",
    }
    missing = required - set(df_bronze.columns)
    if missing:
        raise ValueError(f"season_history bronze missing columns: {sorted(missing)}")

    df = df_bronze.copy()

    # Keep only current-year readings (not the prior-year comparison values).
    df = df[df["period"] == "current"].copy()
    if df.empty:
        logger.warning("season_history: no 'current' period rows in bronze input")
        return pd.DataFrame(columns=SEASON_HISTORY_COLUMNS)

    # Keep only known variables.
    df = df[df["variable"].isin(_SEASON_HISTORY_VAR_MAP)].copy()
    if df.empty:
        logger.warning("season_history: no recognised variables in bronze input")
        return pd.DataFrame(columns=SEASON_HISTORY_COLUMNS)

    # Parse position_date → sortable date; fall back to ingest_date.
    df["_pos_date"] = df["position_date"].map(_resolve_position_date)
    df["_ing_date"] = df["ingest_date"].map(_resolve_ingest_date)
    df["_sort_date"] = df["_pos_date"].where(df["_pos_date"].notna(), df["_ing_date"])

    # Dedup: per (harvest_year, fortnight_seq, region, variable) keep latest.
    df = (
        df.sort_values("_sort_date", ascending=False, na_position="last")
        .drop_duplicates(
            subset=["harvest_year", "fortnight_seq", "region", "variable"],
            keep="first",
        )
    )

    # Preserve source metadata before pivot (one row per dedup key).
    meta_cols = ["harvest_year", "fortnight_seq", "fortnight_label", "region",
                 "idm", "position_date"]
    meta = (
        df[meta_cols]
        .drop_duplicates(subset=["harvest_year", "fortnight_seq", "region"])
        .rename(columns={"idm": "source_idm", "position_date": "source_position_date"})
    )

    # Rename variable values for silver column names.
    df["variable"] = df["variable"].map(_SEASON_HISTORY_VAR_MAP)

    # Pivot.
    wide = df.pivot_table(
        index=["harvest_year", "fortnight_seq", "region"],
        columns="variable",
        values="value",
        aggfunc="first",
    ).reset_index()
    wide.columns.name = None

    # Ensure all metric columns present even if absent from this data.
    for col in _SEASON_HISTORY_VAR_MAP.values():
        if col not in wide.columns:
            wide[col] = float("nan")

    # Merge metadata.
    wide = wide.merge(meta, on=["harvest_year", "fortnight_seq", "region"], how="left")

    # Add fortnight_date.
    wide["fortnight_date"] = wide.apply(
        lambda r: _resolve_fortnight_date(r["fortnight_label"], r["harvest_year"]),
        axis=1,
    )

    wide = wide.sort_values(
        ["harvest_year", "region", "fortnight_seq"]
    ).reset_index(drop=True)

    for col in SEASON_HISTORY_COLUMNS:
        if col not in wide.columns:
            wide[col] = None

    logger.info(
        "season_history: %d rows (%d seasons, %d regions)",
        len(wide),
        wide["harvest_year"].nunique(),
        wide["region"].nunique(),
    )
    return wide[SEASON_HISTORY_COLUMNS].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Table 2: release_series
# ---------------------------------------------------------------------------

_RELEASE_SERIES_VARS: set[str] = {
    "cane_crushed",
    "sugar_produced",
    "ethanol_total",
    "ethanol_anhydrous",
    "ethanol_hydrous",
}

# Maps (variable, value_type) → silver column name.
def _release_col(var: str, vtype: str, unit: str) -> str:
    return f"{var}_{vtype}_{unit}"


RELEASE_SERIES_COLUMNS: list[str] = [
    "harvest_year",
    "position_date",
    "region",
    "cane_crushed_current_t",
    "cane_crushed_prior_t",
    "sugar_produced_current_t",
    "sugar_produced_prior_t",
    "ethanol_total_current_m3",
    "ethanol_total_prior_m3",
    "ethanol_anhydrous_current_m3",
    "ethanol_anhydrous_prior_m3",
    "ethanol_hydrous_current_m3",
    "ethanol_hydrous_prior_m3",
]

# Maps (variable, unit) → prefix used in column construction.
_RELEASE_VAR_UNIT: dict[str, str] = {
    "cane_crushed":      "t",
    "sugar_produced":    "t",
    "ethanol_total":     "m3",
    "ethanol_anhydrous": "m3",
    "ethanol_hydrous":   "m3",
}


def transform_release_series(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Transform ``summary_snapshot`` bronze rows to the release series silver.

    Args:
        df_bronze: Concatenation of all ``summary_snapshot`` bronze Parquets.
            Required columns: ``harvest_year``, ``idm``, ``period_type``,
            ``region``, ``variable``, ``current_value``, ``prior_value``,
            ``position_date``.

    Returns:
        Wide DataFrame keyed on ``(harvest_year, position_date, region)``.
        See ``RELEASE_SERIES_COLUMNS`` for the full schema.

    Raises:
        ValueError: If required columns are missing.
    """
    required = {
        "harvest_year", "idm", "period_type", "region",
        "variable", "current_value", "prior_value", "position_date",
    }
    missing = required - set(df_bronze.columns)
    if missing:
        raise ValueError(f"release_series bronze missing columns: {sorted(missing)}")

    df = df_bronze.copy()

    # Keep accumulated readings only.
    df = df[df["period_type"] == "accumulated"].copy()
    if df.empty:
        logger.warning("release_series: no 'accumulated' period_type rows in bronze input")
        return pd.DataFrame(columns=RELEASE_SERIES_COLUMNS)

    df = df[df["variable"].isin(_RELEASE_SERIES_VARS)].copy()

    # Dedup: one canonical row per (harvest_year, position_date, region, variable).
    df = df.drop_duplicates(
        subset=["harvest_year", "position_date", "region", "variable"],
        keep="first",
    )

    # Melt current_value and prior_value into a single long-form column, then
    # build a composite column key and pivot once.
    long_rows = []
    for _, row in df.iterrows():
        var = row["variable"]
        unit = _RELEASE_VAR_UNIT.get(var, "")
        for vtype in ("current", "prior"):
            col_name = f"{var}_{vtype}_{unit}"
            val = row["current_value"] if vtype == "current" else row["prior_value"]
            long_rows.append({
                "harvest_year":  row["harvest_year"],
                "position_date": row["position_date"],
                "region":        row["region"],
                "col_name":      col_name,
                "value":         val,
            })

    if not long_rows:
        return pd.DataFrame(columns=RELEASE_SERIES_COLUMNS)

    long = pd.DataFrame(long_rows)
    long = long.drop_duplicates(
        subset=["harvest_year", "position_date", "region", "col_name"],
        keep="first",
    )

    wide = long.pivot_table(
        index=["harvest_year", "position_date", "region"],
        columns="col_name",
        values="value",
        aggfunc="first",
    ).reset_index()
    wide.columns.name = None

    for col in RELEASE_SERIES_COLUMNS:
        if col not in wide.columns:
            wide[col] = float("nan")

    wide = wide.sort_values(
        ["harvest_year", "region", "position_date"]
    ).reset_index(drop=True)

    logger.info(
        "release_series: %d rows (%d seasons, %d unique position_dates)",
        len(wide),
        wide["harvest_year"].nunique(),
        wide["position_date"].nunique(),
    )
    return wide[RELEASE_SERIES_COLUMNS].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Table 3: corn_ethanol
# ---------------------------------------------------------------------------

CORN_ETHANOL_COLUMNS: list[str] = [
    "harvest_year",
    "fortnight_seq",
    "fortnight_label",
    "fortnight_date",
    "anhydrous_quinzenal_kl",
    "hydrous_quinzenal_kl",
    "total_quinzenal_kl",
    "anhydrous_accum_kl",
    "hydrous_accum_kl",
    "total_accum_kl",
    "source_idm",
    "source_position_date",
]

_CORN_ETHANOL_VALUE_COLS: list[str] = [
    "anhydrous_quinzenal_kl",
    "hydrous_quinzenal_kl",
    "total_quinzenal_kl",
    "anhydrous_accum_kl",
    "hydrous_accum_kl",
    "total_accum_kl",
]


def transform_corn_ethanol(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Transform ``corn_ethanol`` bronze rows to the corn ethanol silver.

    Args:
        df_bronze: Concatenation of all ``corn_ethanol`` bronze Parquets.
            Required columns: ``harvest_year``, ``idm``, ``fortnight_seq``,
            ``fortnight_label``, ``position_date``, ``ingest_date``, and all
            six numeric value columns.

    Returns:
        Wide DataFrame keyed on ``(harvest_year, fortnight_seq)``.
        See ``CORN_ETHANOL_COLUMNS`` for the full schema.

    Raises:
        ValueError: If required columns are missing.
    """
    required = {
        "harvest_year", "idm", "fortnight_seq", "fortnight_label",
        "position_date", "ingest_date",
    }
    missing = required - set(df_bronze.columns)
    if missing:
        raise ValueError(f"corn_ethanol bronze missing columns: {sorted(missing)}")

    df = df_bronze.copy()

    # Parse dates for dedup ordering.
    df["_pos_date"] = df["position_date"].map(_resolve_position_date)
    df["_ing_date"] = df["ingest_date"].map(_resolve_ingest_date)
    df["_sort_date"] = df["_pos_date"].where(df["_pos_date"].notna(), df["_ing_date"])

    # Dedup: per (harvest_year, fortnight_seq) keep row from latest bulletin.
    df = (
        df.sort_values("_sort_date", ascending=False, na_position="last")
        .drop_duplicates(subset=["harvest_year", "fortnight_seq"], keep="first")
    )

    # Rename metadata columns.
    df = df.rename(columns={
        "idm": "source_idm",
        "position_date": "source_position_date",
    })

    # Add fortnight_date.
    df["fortnight_date"] = df.apply(
        lambda r: _resolve_fortnight_date(r["fortnight_label"], r["harvest_year"]),
        axis=1,
    )

    # Ensure all value columns present.
    for col in _CORN_ETHANOL_VALUE_COLS:
        if col not in df.columns:
            df[col] = float("nan")

    for col in CORN_ETHANOL_COLUMNS:
        if col not in df.columns:
            df[col] = None

    df = df.sort_values(["harvest_year", "fortnight_seq"]).reset_index(drop=True)

    logger.info(
        "corn_ethanol: %d rows (%d seasons)",
        len(df),
        df["harvest_year"].nunique(),
    )
    return df[CORN_ETHANOL_COLUMNS].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Table 4: monthly_ethanol_sales
# ---------------------------------------------------------------------------

MONTHLY_ETHANOL_SALES_COLUMNS: list[str] = [
    "harvest_year",
    "month_num",
    "month_label",
    "month_date",
    "is_partial",
    "total_current_m3",
    "total_prior_m3",
    "external_current_m3",
    "external_prior_m3",
    "internal_current_m3",
    "internal_prior_m3",
    "source_idm",
    "source_position_date",
]

_MONTHLY_SALES_VALUE_COLS: list[str] = [
    "total_current_m3",
    "total_prior_m3",
    "external_current_m3",
    "external_prior_m3",
    "internal_current_m3",
    "internal_prior_m3",
]


def transform_monthly_ethanol_sales(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Transform ``monthly_ethanol_sales`` bronze rows to the monthly sales silver.

    Deduplication prefers the latest bulletin where the month is final
    (``is_partial == False``).  If only partial readings exist for a month,
    the latest partial reading is used.

    Args:
        df_bronze: Concatenation of all ``monthly_ethanol_sales`` bronze Parquets.
            Required columns: ``harvest_year``, ``idm``, ``month_num``,
            ``month_label``, ``is_partial``, ``position_date``, ``ingest_date``,
            and the six numeric value columns.

    Returns:
        Wide DataFrame keyed on ``(harvest_year, month_num)``.
        See ``MONTHLY_ETHANOL_SALES_COLUMNS`` for the full schema.

    Raises:
        ValueError: If required columns are missing.
    """
    required = {
        "harvest_year", "idm", "month_num", "month_label",
        "is_partial", "position_date", "ingest_date",
    }
    missing = required - set(df_bronze.columns)
    if missing:
        raise ValueError(f"monthly_ethanol_sales bronze missing columns: {sorted(missing)}")

    df = df_bronze.copy()

    # Normalise is_partial to bool (Parquet may deserialize as object).
    df["is_partial"] = df["is_partial"].astype(bool)

    # Parse dates for dedup ordering.
    df["_pos_date"] = df["position_date"].map(_resolve_position_date)
    df["_ing_date"] = df["ingest_date"].map(_resolve_ingest_date)
    df["_sort_date"] = df["_pos_date"].where(df["_pos_date"].notna(), df["_ing_date"])

    # Sort so that: final rows (is_partial=False) come before partial rows,
    # then by latest date within each group.
    df = df.sort_values(
        ["is_partial", "_sort_date"],
        ascending=[True, False],   # False = partial goes last; latest date first
        na_position="last",
    ).drop_duplicates(subset=["harvest_year", "month_num"], keep="first")

    # Add month_date: month 4-12 → year_start, 1-3 → year_end.
    def _month_date(row: pd.Series) -> Optional[str]:
        try:
            parts = str(row["harvest_year"]).split("_")
            year_start = int(parts[0])
            year_end = int(parts[1])
            m = int(row["month_num"])
            if m <= 0:
                return None
            year = year_start if m >= 4 else year_end
            return f"{year}-{m:02d}-01"
        except (ValueError, IndexError):
            return None

    df["month_date"] = df.apply(_month_date, axis=1)

    # Rename metadata columns.
    df = df.rename(columns={
        "idm": "source_idm",
        "position_date": "source_position_date",
    })

    # Ensure all value columns present.
    for col in _MONTHLY_SALES_VALUE_COLS:
        if col not in df.columns:
            df[col] = float("nan")

    for col in MONTHLY_ETHANOL_SALES_COLUMNS:
        if col not in df.columns:
            df[col] = None

    df = df.sort_values(["harvest_year", "month_num"]).reset_index(drop=True)

    logger.info(
        "monthly_ethanol_sales: %d rows (%d seasons)",
        len(df),
        df["harvest_year"].nunique(),
    )
    return df[MONTHLY_ETHANOL_SALES_COLUMNS].reset_index(drop=True)
