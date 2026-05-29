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
        tbl_str = str(tbl)
        parsed: list[pd.DataFrame] | None = None
        for hdr_row in (0, 1):
            try:
                df_list = pd.read_html(io.StringIO(tbl_str), header=hdr_row)
                if not df_list:
                    continue
                # Use header=1 only when header=0 puts a label word in the
                # first cell, indicating the actual header row is row 1
                # (common in MPOB pages that have a title row above the header).
                if hdr_row == 0 and _looks_like_misaligned_header(df_list[0]):
                    logger.debug(
                        "MPOB: header row looks misaligned (%s), retrying with header=1",
                        df_list[0].columns.tolist()[:3],
                    )
                    continue  # try hdr_row=1
                parsed = df_list
                break
            except Exception as exc:  # noqa: BLE001
                logger.debug("MPOB: read_html header=%d failed: %s", hdr_row, exc)
                continue
        if parsed:
            frames.extend(parsed)

    return frames


def _looks_like_misaligned_header(df: pd.DataFrame) -> bool:
    """Return True when the first data row appears to be the real header row.

    This happens on MPOB pages where an outer title row (e.g. "Palm Oil
    Statistics") is parsed by pandas as the column names while the actual
    column labels ("Month", "CPO Production", …) end up as the first data row.
    """
    if df.empty or df.shape[1] < 2:
        return False
    first_cell = str(df.iloc[0, 0]).strip().lower()
    return first_cell in ("month", "year", "date", "period", "item", "description")


def _is_data_table(df: pd.DataFrame) -> bool:
    """Return True if the DataFrame looks like an MPOB production data table."""
    if df.shape[0] < 3 or df.shape[1] < 3:
        return False
    _KEYWORDS = ("production", "export", "stock", "ffb", "cpo", "pko", "palm")
    col_text = " ".join(str(c).lower() for c in df.columns)
    if any(kw in col_text for kw in _KEYWORDS):
        return True
    # Also scan cell content — catches layouts where keyword-bearing column
    # labels appear as data-row values rather than pandas column headers.
    cell_text = " ".join(str(v) for v in df.values.flatten()).lower()
    return any(kw in cell_text for kw in _KEYWORDS)


def _parse_col_month_year(col_label: str, base_year: int) -> "tuple[int, int] | None":
    """Return ``(month, year)`` from a month-column header.

    Handles formats like ``'Jan 19'``, ``'Feb'``, ``'Nov (r)'``, ``'Dec (p)'``.
    When no two-digit year suffix is present the ``base_year`` is used.
    Returns ``None`` if the label does not contain a recognisable month name.
    """
    # Strip parenthetical annotations: (r), (p), (e), …
    col_clean = re.sub(r"\s*\([^)]*\)", "", str(col_label)).strip()
    # Remove non-alphanumeric chars except spaces
    col_clean = re.sub(r"[^A-Za-z0-9 ]", " ", col_clean).strip().lower()
    parts = col_clean.split()
    if not parts:
        return None
    month = _MONTH_NAMES.get(parts[0][:3])
    if month is None:
        return None
    if len(parts) >= 2:
        try:
            yr = int(parts[1])
            year = yr + 2000 if yr < 100 else yr
        except ValueError:
            year = base_year
    else:
        year = base_year
    return month, year


def _normalize_annual_table(
    df: pd.DataFrame,
    year: int,
) -> pd.DataFrame:
    """Normalise an annual summary table to long format.

    Dispatches between two orientations:

    * **Month-as-columns** (current MPOB annual summary HTML): col 0 holds
      commodity / section labels; remaining columns are month-year headers
      such as ``'Dec 18'``, ``'Jan 19'``, ``'Feb'``, …  Section-header rows
      (colspan cells like *"PRODUCTION (TONNES)"*) appear as rows where all
      value columns are NaN.

    * **Month-as-rows** (legacy fallback): col 0 holds month labels;
      remaining columns hold variable names.
    """
    if df.empty or df.shape[1] < 3:
        return pd.DataFrame()

    # Count how many non-label column headers parse as month abbreviations.
    col_month_map: dict[str, tuple[int, int]] = {}
    for c in df.columns[1:]:
        parsed = _parse_col_month_year(str(c), year)
        if parsed is not None:
            col_month_map[c] = parsed

    if len(col_month_map) >= 3:
        return _normalize_annual_table_wide(df, year, col_month_map)
    else:
        return _normalize_annual_table_long(df, year)


def _normalize_annual_table_wide(
    df: pd.DataFrame,
    year: int,
    col_month_map: dict[str, "tuple[int, int]"],
) -> pd.DataFrame:
    """Normalise MPOB annual summary where months are *columns*.

    Rows are either section-header rows (all value columns NaN, first cell is
    e.g. ``'PRODUCTION (TONNES)'``) or commodity data rows.  Output schema:
    ``(year, month, variable, value)`` where ``variable`` encodes
    ``<section>__<commodity>`` (e.g. ``'production__crude_palm_oil'``).
    """
    value_col_names = list(col_month_map.keys())
    records: list[dict] = []
    current_section = "unknown"

    for _, row in df.iterrows():
        label = str(row.iloc[0]).strip()
        if not label or label.lower() in ("nan", "\xa0", "", "none"):
            continue

        has_values = row[value_col_names].notna().any()
        if not has_values:
            # Section-header colspan row — extract clean section name
            section_clean = re.sub(r"\s*\([^)]*\)", "", label).strip().lower()
            current_section = re.sub(r"[^a-z0-9]+", "_", section_clean).strip("_") or "unknown"
            continue

        # Data row: commodity label + per-month numeric values
        commodity = re.sub(r"\s*\([^)]*\)", "", label).strip()
        commodity_key = re.sub(r"[^a-z0-9]+", "_", commodity.lower()).strip("_")
        var_name = (
            f"{current_section}__{commodity_key}"
            if current_section != "unknown"
            else commodity_key
        )

        for col_name, (m, y) in col_month_map.items():
            val = row[col_name]
            if pd.isna(val):
                continue
            try:
                val_float = float(
                    str(val).replace(",", "").replace("\u00a0", "").strip()
                )
            except (ValueError, TypeError):
                continue
            records.append({"year": y, "month": m, "variable": var_name, "value": val_float})

    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records)


def _normalize_annual_table_long(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Normalise legacy MPOB annual format where months are *rows*."""
    rename = {c: _canonicalize_col(str(c)) for c in df.columns}
    df = df.rename(columns=rename)

    first_col = df.columns[0]
    df = df.rename(columns={first_col: "month_label"})
    df["month_label"] = df["month_label"].astype(str).str.strip()

    df["month"] = df["month_label"].apply(_parse_month_number)
    df = df.dropna(subset=["month"])
    df["month"] = df["month"].astype(int)
    df["year"] = year

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
