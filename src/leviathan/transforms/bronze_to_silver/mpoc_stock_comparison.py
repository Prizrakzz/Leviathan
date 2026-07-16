"""SILVER-F055: MPOC stock-comparison producer (silver_mpoc_stock_comparison).

Grain: ``country x oil_type x year x month``. Consumes the "Oils and Fats Ending Stocks" grids off
the single live MPOC Stock Comparison page.

Live layout (as fetched 2026): the page renders ONE table per country (China, India, Pakistan,
Bangladesh, USA). Each table is::

    header row : ['Country : China']                                  <- country identity
    row 0      : ['Oils and Fats Ending Stocks']                      <- section marker
    row 1      : ['', 'Palm Oil (MT)', 'Soybean Oil (MT)', ...,       <- oil-type GROUP header
                  'Other Oils (MT)', 'Total Ending Stocks (MT)']
    row 2      : ['', 2026, 2025, 2026, 2025, ...]                    <- year sub-header (2 per group)
    rows 3..14 : ['January', <palm 2026>, <palm 2025>, <soy 2026>, ...]  <- one row per month

So oil_type is a COLUMN GROUP, the year is a sub-header, and the month is the row label. Each oil
group spans two year columns (current + prior). 'Other Oils' / 'Total Ending Stocks' are dropped
(not canonical oil types). Blank / '-' cells are missing, never 0.

Provenance (plan L697): the source-as-of is MANDATORY but lives in the RUN/INPUT MANIFEST, not as a
row column. :func:`transform_stock_comparison` takes ``as_of_date`` for the manifest but never emits
it. Conflicting snapshot cells (the same (country, oil_type, year, month) with two different values
inside one snapshot) fail closed, as does an unresolvable layout (:class:`MpocDriftError`).

Output: ``[country, oil_type, year, month, ending_stocks_mt, source]``. Pure + AWS-free.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.silver.mpoc.adapter import (
    NormalizedTable,
    normalize_country,
    normalize_oil_type,
    parse_month,
    parse_number,
)

logger = get_logger(__name__)

OUTPUT_COLUMNS: list[str] = ["country", "oil_type", "year", "month", "ending_stocks_mt", "source"]

# Per-country tables are identified by a "Country : <name>" header cell; the ending-stocks marker
# names the grid. Both are structural anchors used to fail closed on a drifted page.
_COUNTRY_HEADER_RE = re.compile(r"country\s*[:\-]\s*(.+)", re.IGNORECASE)
_YEAR_CELL_RE = re.compile(r"^(19|20)\d{2}$")
STOCK_MARKER = "ending stock"


class MpocDriftError(ValueError):
    """The stock-comparison layout drifted from the expected contract (fail closed)."""


class MpocConflictError(ValueError):
    """Two different ending-stock values for one snapshot cell (fail closed)."""


@dataclass(frozen=True)
class MpocStockRelease:
    """One fetched stock-comparison snapshot: its tables + the mandatory source-as-of provenance."""

    as_of_date: str            # ISO YYYY-MM-DD -- manifest provenance ONLY, never a row column
    tables: list[NormalizedTable]
    source: str = "mpoc"


def _country_from_header(header: tuple[str, ...]) -> Optional[str]:
    """Normalized country from a 'Country : China' header cell, or None if the header is not one."""
    if not header:
        return None
    m = _COUNTRY_HEADER_RE.match((header[0] or "").strip())
    if not m:
        return None
    return normalize_country(m.group(1))


def _oil_label(cell: str) -> Optional[str]:
    """Normalized oil type from a group label like 'Palm Oil (MT)' / 'Soybean Oil (MT)*'.

    Strips the trailing unit parenthetical and footnote asterisks before normalization; returns
    None for non-oil group labels ('Other Oils', 'Total Ending Stocks')."""
    s = re.sub(r"\(.*?\)", "", cell or "")   # drop '(MT)' unit
    s = s.replace("*", "").strip()
    if not s:
        return None
    return normalize_oil_type(s)


def _year_or_none(cell: str) -> Optional[int]:
    s = (cell or "").strip()
    return int(s) if _YEAR_CELL_RE.match(s) else None


def _locate_grid(rows: list[tuple[str, ...]]) -> Optional[tuple[int, dict[int, tuple[str, int]]]]:
    """Find the (oil-group header row index, {value_col: (oil_type, year)}) for a country table.

    The oil-group header is the first row naming >=2 canonical oil types; the row directly below it
    is the year sub-header. Each oil group spans an equal number of year columns. Returns None when
    the grid cannot be located (caller raises drift)."""
    oil_idx = None
    for i, row in enumerate(rows):
        if sum(1 for c in row[1:] if _oil_label(c) is not None) >= 2:
            oil_idx = i
            break
    if oil_idx is None or oil_idx + 1 >= len(rows):
        return None
    oil_row = rows[oil_idx]
    year_row = rows[oil_idx + 1]
    n_groups = len(oil_row) - 1
    n_val = len(year_row) - 1
    if n_groups <= 0 or n_val <= 0 or n_val % n_groups != 0:
        return None
    per = n_val // n_groups
    col_map: dict[int, tuple[str, int]] = {}
    for j in range(1, n_val + 1):
        g = (j - 1) // per
        oil = _oil_label(oil_row[1 + g]) if 1 + g < len(oil_row) else None
        year = _year_or_none(year_row[j]) if j < len(year_row) else None
        if oil is not None and year is not None:
            col_map[j] = (oil, year)
    if not col_map:
        return None
    return oil_idx, col_map


def _emit_country_rows(
    table: NormalizedTable,
    country: str,
    source: str,
    seen: dict[tuple, float],
    records: list[dict],
) -> None:
    """Melt one country's ending-stock grid into (country, oil_type, year, month) rows.

    Raises :class:`MpocDriftError` if the country table lacks the expected oil/year grid and
    :class:`MpocConflictError` on a duplicated cell with a different value."""
    located = _locate_grid(list(table.rows))
    if located is None:
        raise MpocDriftError(
            f"MPOC stock-comparison: country {country!r} table lacks an oil/year grid "
            f"(header {list(table.header)})"
        )
    oil_idx, col_map = located
    for row in table.rows[oil_idx + 2:]:
        if not row:
            continue
        month = parse_month(row[0])
        if month is None:
            continue  # section marker / notes row, not a calendar month
        for col, (oil_type, year) in col_map.items():
            val = parse_number(row[col]) if col < len(row) else None
            if val is None:
                continue  # blank / '-' cell is missing, never 0.0
            key = (country, oil_type, year, month)
            if key in seen and seen[key] != val:
                raise MpocConflictError(
                    f"conflicting ending-stocks for {key}: {seen[key]} vs {val}"
                )
            if key in seen:
                continue
            seen[key] = val
            records.append({
                "country": country,
                "oil_type": oil_type,
                "year": int(year),
                "month": int(month),
                "ending_stocks_mt": val,
                "source": source,
            })


def transform_stock_comparison(release: MpocStockRelease) -> pd.DataFrame:
    """Melt the MPOC per-country stock-comparison grids into the silver ending-stocks long table.

    ``release.as_of_date`` is provenance for the caller's manifest and is NOT emitted as a row.
    Each country renders its own table (country in a 'Country : X' header); oil types are column
    groups, the year is a sub-header, and the month is the row label. A page with no resolvable
    per-country grid, or a country table missing the oil/year structure, fails closed."""
    country_tables = [
        (t, c) for t in release.tables if (c := _country_from_header(t.header)) is not None
    ]
    if not country_tables:
        raise MpocDriftError(
            "MPOC stock-comparison: no per-country 'Country : <name>' ending-stock table resolved"
        )
    # Page-identity guard: confirm we are on the ending-stocks page (the marker sits in each
    # country table's title row) and not some other page that merely carries 'Country :' headers.
    if not any(
        STOCK_MARKER in (cell or "").lower()
        for table, _ in country_tables
        for row in (table.header, *table.rows)
        for cell in row
    ):
        raise MpocDriftError(
            f"MPOC stock-comparison: {STOCK_MARKER!r} marker absent from the country tables"
        )

    seen: dict[tuple, float] = {}
    records: list[dict] = []
    for table, country in country_tables:
        _emit_country_rows(table, country, release.source, seen, records)

    if not records:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    df = pd.DataFrame.from_records(records)
    df = df.sort_values(["country", "oil_type", "year", "month"]).reset_index(drop=True)
    return df[OUTPUT_COLUMNS]
