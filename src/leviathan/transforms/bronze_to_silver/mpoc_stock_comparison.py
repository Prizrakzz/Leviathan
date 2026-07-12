"""SILVER-F055: MPOC stock-comparison producer (silver_mpoc_stock_comparison).

Grain: ``country x oil_type x year x month``. Consumes the "Oils and Fats Ending Stocks" grid off
the single live MPOC Stock Comparison page. Each row identifies a (country, oil_type); the month
columns (e.g. 'Nov 2024') are melted into (year, month) ending-stock observations.

Provenance (plan L697): the source-as-of is MANDATORY but lives in the RUN/INPUT MANIFEST, not as a
row column -- adding it as a physical column is a separate additive registry/DDL/Glue migration.
:func:`transform_stock_comparison` therefore takes ``as_of_date`` for the manifest but never emits
it. Conflicting snapshot cells (the same (country, oil_type, year, month) with two different values
inside one snapshot) fail closed.

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
    diagnose_table_drift,
    find_table,
    normalize_country,
    normalize_oil_type,
    parse_month,
    parse_number,
)

logger = get_logger(__name__)

OUTPUT_COLUMNS: list[str] = ["country", "oil_type", "year", "month", "ending_stocks_mt", "source"]

STOCK_TABLE_IDENTITY = "ending stock"
_REQUIRED_COLUMNS = ["country"]

_YEAR_RE = re.compile(r"(19|20)\d{2}")
_YY_RE = re.compile(r"[-/\s](\d{2})$")


class MpocDriftError(ValueError):
    """The stock-comparison table drifted from the expected contract (fail closed)."""


class MpocConflictError(ValueError):
    """Two different ending-stock values for one snapshot cell (fail closed)."""


@dataclass(frozen=True)
class MpocStockRelease:
    """One fetched stock-comparison snapshot: its tables + the mandatory source-as-of provenance."""

    as_of_date: str            # ISO YYYY-MM-DD -- manifest provenance ONLY, never a row column
    tables: list[NormalizedTable]
    source: str = "mpoc"


def _parse_year_month_header(cell: str) -> Optional[tuple[int, int]]:
    """Parse a month-column header ('Nov 2024', 'November 2024', 'Nov-24') into (year, month)."""
    month = None
    for tok in re.split(r"[\s\-/]+", cell.strip()):
        m = parse_month(tok)
        if m is not None:
            month = m
            break
    if month is None:
        return None
    ym = _YEAR_RE.search(cell)
    if ym:
        return int(ym.group(0)), month
    yy = _YY_RE.search(cell)
    if yy:
        return 2000 + int(yy.group(1)), month
    return None


def _identify_cols(header: tuple[str, ...]) -> tuple[int, Optional[int], dict[int, tuple[int, int]]]:
    """Return (country_col, oil_col_or_None, {col_index: (year, month)}) for a stock grid header."""
    header_l = [h.lower() for h in header]
    country_col = 0
    oil_col: Optional[int] = None
    for i, h in enumerate(header_l):
        if i == 0:
            continue
        if oil_col is None and any(t in h for t in ("oil", "product", "commodity", "type")):
            oil_col = i
            break
    month_cols: dict[int, tuple[int, int]] = {}
    for i, h in enumerate(header):
        if i in (country_col, oil_col):
            continue
        ym = _parse_year_month_header(h)
        if ym is not None:
            month_cols[i] = ym
    return country_col, oil_col, month_cols


def transform_stock_comparison(release: MpocStockRelease) -> pd.DataFrame:
    """Melt the MPOC stock-comparison grid into the silver ending-stocks long table.

    ``release.as_of_date`` is provenance for the caller's manifest and is NOT emitted as a row.
    A row's oil_type comes from a dedicated oil column when present, else from the country cell
    carrying a 'Country - Oil' compound label. Unknown countries/oil-types are skipped (logged)."""
    table = find_table(release.tables, STOCK_TABLE_IDENTITY)
    drift = diagnose_table_drift(
        table,
        expected_identity_substr=STOCK_TABLE_IDENTITY,
        expected_columns=_REQUIRED_COLUMNS,
    )
    if drift:
        raise MpocDriftError(f"MPOC stock-comparison layout drift {[d.to_dict() for d in drift]}")
    assert table is not None
    country_col, oil_col, month_cols = _identify_cols(table.header)
    if not month_cols:
        raise MpocDriftError("MPOC stock-comparison: no month/year columns parsed from header")

    seen: dict[tuple, float] = {}
    records: list[dict] = []
    current_country: Optional[str] = None
    for row in table.rows:
        if not row:
            continue
        raw_label = row[country_col] if country_col < len(row) else ""
        oil_type: Optional[str] = None
        country = normalize_country(raw_label)
        if oil_col is not None and oil_col < len(row):
            oil_type = normalize_oil_type(row[oil_col])
            if country is not None:
                current_country = country
            else:
                country = current_country  # oil rows under a country header block
        else:
            # compound "Country - Oil" label in a single column
            parts = re.split(r"[-:]", raw_label, maxsplit=1)
            if len(parts) == 2:
                country = normalize_country(parts[0]) or current_country
                oil_type = normalize_oil_type(parts[1])
            elif country is not None:
                current_country = country
        if country is None or oil_type is None:
            continue
        for col, (yy, mm) in month_cols.items():
            val = parse_number(row[col]) if col < len(row) else None
            if val is None:
                continue
            key = (country, oil_type, yy, mm)
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
                "year": int(yy),
                "month": int(mm),
                "ending_stocks_mt": val,
                "source": release.source,
            })
    if not records:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    df = pd.DataFrame.from_records(records)
    df = df.sort_values(["country", "oil_type", "year", "month"]).reset_index(drop=True)
    return df[OUTPUT_COLUMNS]
