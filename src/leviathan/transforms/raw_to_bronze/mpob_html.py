"""Bronze transform for MPOB BEPI palm oil HTML statistics pages.

Handles two release types stored in S3 raw:

``annual_summary``
    One HTML page per calendar year.  Contains 12 monthly rows of national
    CPO production, closing stocks, exports, imports, and FFB price.
    S3 key: ``raw/production/source=mpob/release_type=annual_summary/year={y}/...``

``monthly_release``
    One HTML page per calendar month.  Contains national + Peninsular Malaysia
    / Sabah / Sarawak regional breakdown for one specific month.
    S3 key: ``raw/production/source=mpob/release_type=monthly_release/year={y}/month={mm}/...``

Both layouts share the same core table structure.  The first column is a
month label (annual) or a row-group label (monthly).  Remaining columns are
the production variables.

Known quirks
------------
- 2020 monthly pages may say "Under Construction" — transform returns empty
  and the task script logs a warning.
- Some annual pages from early years use a slightly different table layout.
  The transform is defensive and falls back gracefully.
"""
from __future__ import annotations

import io
import re

import pandas as pd
from bs4 import BeautifulSoup

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# Sentinel text that indicates an "Under Construction" page
_UNDER_CONSTRUCTION_MARKER = "under construction"

# Known MPOB column header substrings → canonical snake_case names
_COL_MAP: dict[str, str] = {
    "production":       "production_mt",
    "closing stocks":   "closing_stocks_mt",
    "closing stock":    "closing_stocks_mt",
    "exports":          "exports_mt",
    "export":           "exports_mt",
    "imports":          "imports_mt",
    "import":           "imports_mt",
    "ffb price":        "ffb_price_myr_per_mt",
    "ffb":              "ffb_price_myr_per_mt",
    "peninsular":       "peninsular_malaysia_mt",
    "sabah":            "sabah_mt",
    "sarawak":          "sarawak_mt",
}

# Month name → month number mapping (MPOB uses English month names)
_MONTH_NAMES: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _canonicalize_col(header: str) -> str:
    low = header.strip().lower()
    for pattern, canonical in _COL_MAP.items():
        if pattern in low:
            return canonical
    return re.sub(r"[^a-z0-9]+", "_", low).strip("_") or "unknown"


def _parse_month_number(text: str) -> int | None:
    low = text.strip().lower()
    for name, num in _MONTH_NAMES.items():
        if name in low:
            return num
    return None


def _extract_tables_from_html(html: str) -> list[pd.DataFrame]:
    """Parse all HTML tables using BeautifulSoup and return as DataFrames."""
    soup = BeautifulSoup(html, "html.parser")

    # Check for "under construction" pages
    page_text = soup.get_text().lower()
    if _UNDER_CONSTRUCTION_MARKER in page_text:
        logger.warning("MPOB: page appears to be 'Under Construction'")
        return []

    tables = soup.find_all("table")
    if not tables:
        # Some pages embed data in <pre> or inline text — return empty
        logger.warning("MPOB: no <table> elements found in page")
        return []

    frames: list[pd.DataFrame] = []
    for tbl in tables:
        try:
            # Use pandas to parse the table HTML
            df_list = pd.read_html(io.StringIO(str(tbl)), header=0)
            frames.extend(df_list)
        except Exception:  # noqa: BLE001
            continue

    return frames


def _is_data_table(df: pd.DataFrame) -> bool:
    """Return True if the DataFrame looks like an MPOB production data table."""
    if df.shape[0] < 3 or df.shape[1] < 3:
        return False
    col_text = " ".join(str(c).lower() for c in df.columns)
    return any(kw in col_text for kw in ("production", "export", "stock", "ffb"))


def _normalize_annual_table(
    df: pd.DataFrame,
    year: int,
) -> pd.DataFrame:
    """Normalise an annual summary table to long format."""
    # Map column names
    rename = {c: _canonicalize_col(str(c)) for c in df.columns}
    df = df.rename(columns=rename)

    # First column should be month label
    first_col = df.columns[0]
    df = df.rename(columns={first_col: "month_label"})
    df["month_label"] = df["month_label"].astype(str).str.strip()

    # Extract month number
    df["month"] = df["month_label"].apply(_parse_month_number)
    df = df.dropna(subset=["month"])
    df["month"] = df["month"].astype(int)
    df["year"] = year

    # Melt to long format
    value_cols = [c for c in df.columns if c not in ("month_label", "month", "year")]
    df_long = df.melt(
        id_vars=["year", "month"],
        value_vars=value_cols,
        var_name="variable",
        value_name="value",
    )
    df_long["value"] = pd.to_numeric(
        df_long["value"].astype(str).str.replace(",", "", regex=False),
        errors="coerce",
    )
    return df_long.dropna(subset=["value"])


def _normalize_monthly_table(
    df: pd.DataFrame,
    year: int,
    month: int,
) -> pd.DataFrame:
    """Normalise a monthly release table to long format."""
    rename = {c: _canonicalize_col(str(c)) for c in df.columns}
    df = df.rename(columns=rename)

    first_col = df.columns[0]
    df = df.rename(columns={first_col: "region"})
    df["region"] = df["region"].astype(str).str.strip()
    df = df[df["region"].str.len() > 0]

    df["year"] = year
    df["month"] = month

    value_cols = [c for c in df.columns if c not in ("region", "year", "month")]
    df_long = df.melt(
        id_vars=["region", "year", "month"],
        value_vars=value_cols,
        var_name="variable",
        value_name="value",
    )
    df_long["value"] = pd.to_numeric(
        df_long["value"].astype(str).str.replace(",", "", regex=False),
        errors="coerce",
    )
    return df_long.dropna(subset=["value"])


def extract_mpob_annual(
    raw_bytes: bytes,
    year: int,
    ingest_date: str,
) -> pd.DataFrame:
    """Parse an MPOB annual summary HTML page into a long/tidy bronze DataFrame.

    Args:
        raw_bytes:   Raw bytes of the HTML page as stored in S3.
        year:        Calendar year the page covers.
        ingest_date: ISO date string when bronze was written.

    Returns:
        Long-format DataFrame with columns
        ``(year, month, variable, value, release_type, source, ingest_date)``.
        May be empty if the page is "Under Construction" or malformed.
    """
    html = raw_bytes.decode("utf-8", errors="replace")
    tables = _extract_tables_from_html(html)

    frames: list[pd.DataFrame] = []
    for df in tables:
        if not _is_data_table(df):
            continue
        try:
            df_norm = _normalize_annual_table(df, year)
            if not df_norm.empty:
                frames.append(df_norm)
        except Exception as exc:  # noqa: BLE001
            logger.warning("MPOB annual: table parse error year=%d: %s", year, exc)

    if not frames:
        logger.warning("MPOB annual: no data tables found for year=%d", year)
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True).drop_duplicates()
    result["release_type"] = "annual_summary"
    result["source"] = "mpob"
    result["ingest_date"] = ingest_date

    logger.info("MPOB annual year=%d  rows=%d", year, len(result))
    return result


def extract_mpob_monthly(
    raw_bytes: bytes,
    year: int,
    month: int,
    ingest_date: str,
) -> pd.DataFrame:
    """Parse an MPOB monthly release HTML page into a long/tidy bronze DataFrame.

    Args:
        raw_bytes:   Raw bytes of the HTML page as stored in S3.
        year:        Calendar year.
        month:       Calendar month (1–12).
        ingest_date: ISO date string when bronze was written.

    Returns:
        Long-format DataFrame.  May be empty for "Under Construction" pages.
    """
    html = raw_bytes.decode("utf-8", errors="replace")
    tables = _extract_tables_from_html(html)

    frames: list[pd.DataFrame] = []
    for df in tables:
        if not _is_data_table(df):
            continue
        try:
            df_norm = _normalize_monthly_table(df, year, month)
            if not df_norm.empty:
                frames.append(df_norm)
        except Exception as exc:  # noqa: BLE001
            logger.warning("MPOB monthly: table parse error %d-%02d: %s", year, month, exc)

    if not frames:
        logger.warning("MPOB monthly: no data tables found for %d-%02d", year, month)
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True).drop_duplicates()
    result["release_type"] = "monthly_release"
    result["source"] = "mpob"
    result["ingest_date"] = ingest_date

    logger.info("MPOB monthly %d-%02d  rows=%d", year, month, len(result))
    return result
