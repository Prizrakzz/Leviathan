"""Bronze extraction for MPOB Overview of the Malaysian Oil Palm Industry PDFs.

Parses the two statistics table pages (0-indexed pages 5–6) from the annual
PDF and returns a long/EAV bronze DataFrame with national annual totals.

Variable mapping (national totals only)
----------------------------------------
Page 6 (idx 5) — supply/demand table:

    Section "CPO PRODUCTION (TONNES)"  / row "MALAYSIA"          → production__crude_palm_oil
    Section "CLOSING STOCKS (TONNES)"  / row "TOTAL PALM OIL"    → closing_stocks__palm_oil
    Section "EXPORT (TONNES)"          / row "PALM OIL"          → exports__palm_oil
    Section "IMPORT (TONNES)"          / row "PALM OIL"          → imports__palm_oil

Page 7 (idx 6) — price/yield table:

    Section "PRICE (RM/TONNE)"         / row "FFB (MILL GATE)"   → ffb_price__ffb

Only the current-year column is extracted; the prior-year comparison column
is ignored (it will appear as the current-year value in the previous year's
PDF).  Tables use a multi-column layout where each variable spans several
sub-columns; the current-year value is always the *first* numeric value found
in columns 2+ of a data row.

No S3 or AWS dependencies — pure data transformation.
"""
from __future__ import annotations

import io

import pandas as pd
import pdfplumber

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# Stats table pages (0-indexed): page 5 = supply/demand, page 6 = price/yield.
_STATS_PAGES = (5, 6)

# Each entry: (section_keyword_upper, row_label_upper, bronze_variable_name).
# section_keyword: substring that must appear in the section header (uppercased).
# row_label_upper: must exactly equal the row's primary label (uppercased, stripped).
_VAR_TARGETS: list[tuple[str, str, str]] = [
    ("CPO PRODUCTION",    "MALAYSIA",        "production__crude_palm_oil"),
    ("CLOSING STOCKS",    "TOTAL PALM OIL",  "closing_stocks__palm_oil"),
    ("EXPORT (TONNES)",   "PALM OIL",        "exports__palm_oil"),
    ("IMPORT (TONNES)",   "PALM OIL",        "imports__palm_oil"),
    ("PRICE",             "FFB (MILL GATE)", "ffb_price__ffb"),
]


def extract_mpob_overview_annual(
    pdf_bytes: bytes,
    year: int,
    ingest_date: str,
) -> pd.DataFrame:
    """Parse MPOB overview PDF stats pages into a long/EAV bronze DataFrame.

    Args:
        pdf_bytes:   Raw PDF bytes from S3.
        year:        Calendar year the overview covers (e.g. ``2015``).
        ingest_date: ISO date string when the bronze Parquet is written.

    Returns:
        Long-format DataFrame with columns
        ``(year, variable, value, release_type, source, ingest_date)``.
        Contains at most 5 rows (one per canonical variable).
        May be empty if the stats table pages are not found or are malformed.
    """
    rows: list[dict] = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for pg_idx in _STATS_PAGES:
            if pg_idx >= len(pdf.pages):
                logger.warning("MPOB overview PDF year=%d: page index %d not found", year, pg_idx)
                continue
            tables = pdf.pages[pg_idx].extract_tables()
            for table in tables:
                rows.extend(_parse_stats_table(table, year))

    if not rows:
        logger.warning("MPOB overview PDF year=%d: no statistics extracted", year)
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["release_type"] = "overview_pdf"
    df["source"] = "mpob"
    df["ingest_date"] = ingest_date
    logger.info("MPOB overview PDF year=%d rows=%d", year, len(df))
    return df


def _parse_stats_table(
    table: list[list[str | None]],
    year: int,
) -> list[dict]:
    """Extract target EAV records from one pdfplumber table.

    Iterates rows, tracks the current section header, and emits a record
    whenever a (section, row_label) pair matches a ``_VAR_TARGETS`` entry.
    """
    records: list[dict] = []
    current_section = ""

    for raw_row in table:
        if not raw_row:
            continue

        label, is_section_header = _row_label(raw_row)
        if not label:
            continue

        if is_section_header:
            current_section = label.upper()
            continue

        label_upper = label.upper().strip()
        for sec_kw, row_kw, var_name in _VAR_TARGETS:
            if sec_kw not in current_section:
                continue
            if row_kw != label_upper:
                continue
            val = _first_numeric(raw_row)
            if val is None:
                logger.warning(
                    "MPOB PDF year=%d: no numeric for section=%r label=%r",
                    year,
                    current_section,
                    label,
                )
                break
            records.append({"year": year, "variable": var_name, "value": val})
            break  # matched; move to next row

    return records


def _row_label(row: list[str | None]) -> tuple[str, bool]:
    """Return ``(label, is_section_header)`` for a pdfplumber table row.

    pdfplumber renders colspan cells by placing the text in the first cell
    and ``None`` in the merged cells.  Section-header rows in the MPOB
    overview PDF have:
      - col[0]: empty/None  (the actual label is in col[1])
      - col[1]: section name (e.g. "CPO PRODUCTION (TONNES)")
      - col[2+]: all None or empty  (no numeric values)

    Normal data rows have a non-empty col[0] (e.g. "MALAYSIA", "PALM OIL").

    Sub-total rows (e.g. "TOTAL PALM OIL") have:
      - col[0]: empty
      - col[1]: sub-total label starting with "TOTAL"
      - col[2+]: numeric values present

    Returns:
        ``(label, True)``  — section header (skip, update current_section).
        ``(label, False)`` — data row or sub-total row (check against targets).
        ``("", False)``    — no meaningful label; row should be skipped.
    """
    col0 = (row[0] or "").strip()
    col1 = (row[1] or "").strip() if len(row) > 1 else ""

    if col0:
        return col0, False  # normal data row

    if col1:
        # Section header if no numeric values present; sub-total if values present.
        has_numeric = _first_numeric(row) is not None
        return col1, not has_numeric

    return "", False


def _first_numeric(row: list[str | None]) -> float | None:
    """Return the first numeric value found in columns 2 onward.

    The multi-column layout places the current-year value before the
    prior-year comparison; taking the first numeric in col[2+] always
    yields the current-year figure regardless of row type.

    Returns ``None`` if no numeric value is found in the row.
    """
    for cell in row[2:]:
        if cell is None:
            continue
        s = str(cell).strip()
        if not s:
            continue
        val = _parse_num(s)
        if val is not None:
            return val
    return None


def _parse_num(s: str) -> float | None:
    """Parse a numeric string, handling commas and parenthesized negatives.

    Examples::

        _parse_num("19,961,581")  →  19961581.0
        _parse_num("(332,602)")   →  -332602.0
        _parse_num("459.00")      →  459.0
        _parse_num("")            →  None
        _parse_num("MALAYSIA")    →  None
    """
    s = s.strip()
    if not s:
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    s = s.replace(",", "").strip()
    if not s:
        return None
    try:
        val = float(s)
        return -val if negative else val
    except ValueError:
        return None
