"""Bronze extraction for MPOB Overview of the Malaysian Oil Palm Industry PDFs.

Parses the two statistics table pages (last 2 pages of each PDF) and returns
a long/EAV bronze DataFrame with national annual totals.

PDF layout varies by year:
- 2010: 4 pages; pdfplumber cannot extract data rows → skipped.
- 2011: 4 pages; single table on last page, current year is 2nd numeric column.
- 2012: 5 pages; supply/demand on page 3, price table on page 4 (split-row
  format); current year is 2nd numeric column.
- 2013: 6 pages; current year is 2nd numeric column.
- 2014–2016: current year is 1st numeric column.

Variable mapping (national totals only)
----------------------------------------
Supply/demand table:

    Section "CPO PRODUCTION"           / row "MALAYSIA"          → production__crude_palm_oil
    Section "PRODUCTION" (early years) / row "CRUDE PALM OIL"    → production__crude_palm_oil
    Section "CLOSING STOCKS"           / row "TOTAL PALM OIL"    → closing_stocks__palm_oil
    Section "EXPORT (TONNES)"          / row "PALM OIL"          → exports__palm_oil
    Section "IMPORT (TONNES)"          / row "PALM OIL"          → imports__palm_oil

Price table:

    Section "PRICE"                    / row "FFB (MILL GATE)"   → ffb_price__ffb

No S3 or AWS dependencies — pure data transformation.
"""
from __future__ import annotations

import io

import pandas as pd
import pdfplumber

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# Each entry: (section_keyword_upper, row_label_upper, bronze_variable_name).
# section_keyword: substring that must appear in the section header (uppercased).
# row_label_upper: must exactly equal the row's primary label (uppercased, stripped).
# Two production rules: post-2012 PDFs use "CPO PRODUCTION" / "MALAYSIA";
# 2011-2012 PDFs use "PRODUCTION" (no CPO prefix) / "CRUDE PALM OIL".
_VAR_TARGETS: list[tuple[str, str, str]] = [
    ("CPO PRODUCTION",    "MALAYSIA",        "production__crude_palm_oil"),
    ("PRODUCTION",        "CRUDE PALM OIL",  "production__crude_palm_oil"),
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
        n = len(pdf.pages)

        # Collect all tables from the last 2 pages.
        all_tables: list[list[list[str | None]]] = []
        for pg_idx in [n - 2, n - 1]:
            if pg_idx < 0 or pg_idx >= n:
                continue
            for table in pdf.pages[pg_idx].extract_tables():
                if table:
                    all_tables.append(table)

        # Determine year-column order once for the whole PDF by scanning all
        # tables.  Some tables (e.g. the price table) lack a year header row;
        # the supply/demand table always has one, so first-found wins.
        use_second = False
        for table in all_tables:
            detected = _current_year_is_second(table, year)
            if detected is not None:
                use_second = detected
                break

        for table in all_tables:
            rows.extend(_parse_stats_table(table, year, use_second=use_second))

    # Deduplicate: keep first extracted value per variable (multiple tables may
    # match the same section keyword across pages).
    seen: set[str] = set()
    deduped: list[dict] = []
    for r in rows:
        if r["variable"] not in seen:
            seen.add(r["variable"])
            deduped.append(r)
    rows = deduped

    if not rows:
        logger.warning("MPOB overview PDF year=%d: no statistics extracted", year)
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["release_type"] = "overview_pdf"
    df["source"] = "mpob"
    df["ingest_date"] = ingest_date
    logger.info("MPOB overview PDF year=%d rows=%d", year, len(df))
    return df


def _current_year_is_second(
    table: list[list[str | None]], year: int
) -> bool | None:
    """Return True if the current year column appears *after* the prior year.

    Scans the first four rows for a cell equal to ``str(year)``.  If a
    four-digit year string appears before that position the current year is
    the second column; otherwise it is the first.  Returns ``None`` when the
    year string cannot be found in the table header (e.g. price tables in
    some early PDFs that lack an explicit year row).
    """
    year_str = str(year)
    for row in table[:4]:
        for i, cell in enumerate(row):
            if not cell or str(cell).strip() != year_str:
                continue
            # Check whether a 4-digit year appears before position i.
            for j in range(i):
                c = row[j]
                if c and str(c).strip().isdigit() and len(str(c).strip()) == 4:
                    return True
            return False
    return None  # year not found in this table's header


def _parse_stats_table(
    table: list[list[str | None]],
    year: int,
    use_second: bool = False,
) -> list[dict]:
    """Extract target EAV records from one pdfplumber table.

    Iterates rows, tracks the current section header, and emits a record
    whenever a (section, row_label) pair matches a ``_VAR_TARGETS`` entry.
    When ``use_second`` is True the second numeric in each data row is taken
    (for PDFs where the prior year is listed first).  A look-ahead to the
    following row is performed when the current row yields no value (handles
    split-row price tables in some early PDFs).
    """
    records: list[dict] = []
    current_section = ""
    n_col = 2 if use_second else 1

    i = 0
    while i < len(table):
        raw_row = table[i]
        i += 1
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

            val = _nth_numeric(raw_row, n_col)

            # Split-row format: value may be on the next row (label row has
            # only a percentage-change figure, actual values on the next row).
            if val is None and i < len(table):
                next_row = table[i]
                next_label, _ = _row_label(next_row)
                if not next_label:  # continuation row — no label
                    val = _nth_numeric(next_row, n_col)

            if val is None:
                logger.warning(
                    "MPOB PDF year=%d: no numeric for section=%r label=%r",
                    year,
                    current_section,
                    label,
                )
            else:
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


def _nth_numeric(row: list[str | None], n: int = 1) -> float | None:
    """Return the *n*-th numeric value found in columns 2 onward (1-indexed).

    Returns ``None`` if fewer than *n* numerics are found.
    """
    count = 0
    for cell in row[2:]:
        if cell is None:
            continue
        s = str(cell).strip()
        if not s:
            continue
        val = _parse_num(s)
        if val is not None:
            count += 1
            if count == n:
                return val
    return None


def _first_numeric(row: list[str | None]) -> float | None:
    """Return the first numeric value found in columns 2 onward.

    Used by :func:`_row_label` to distinguish section headers from sub-total
    rows.  For value extraction use :func:`_nth_numeric` instead.
    """
    return _nth_numeric(row, 1)


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
