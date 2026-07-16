"""SILVER-F054: MPOC monthly trade-statistics producer (silver_mpoc_trade_stats_monthly).

Grain: ``year x month``. Consumes the "Malaysia's Exports & Imports" monthly table off each annual
MPOC Trade Statistics page. Validates 12-month completeness and resolves the source table via the
F052 header-signature finder + drift check.

Table layout (live pages): the monthly table has a TWO-ROW header -- a group row
``['', 'Exports', 'Imports']`` over a year sub-header ``['', <yr>, <yr-1>, <yr>, <yr-1>]`` -- and
month names sit in the first cell of each data row. The exports/imports column for THIS page's year
is resolved from the year sub-header, so a page that lists the prior year first (older archives:
``['', 2008, 2009, 2008, 2009]``) still maps to the correct column. Note the identity ``"monthly"``
was NEVER a safe anchor: on pages that still carry section headings it matches "Monthly Average
Prices" (the CPO local-prices table) -- resolution is by header signature, not heading text.

Output: ``[year, month, exports_mt, imports_mt, source]``. Pure + AWS-free.
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
    find_table_by_header,
    parse_month,
    parse_number,
)

logger = get_logger(__name__)

OUTPUT_COLUMNS: list[str] = ["year", "month", "exports_mt", "imports_mt", "source"]

# The monthly Exports/Imports table is resolved by its header signature (both an 'export' and an
# 'import' column): heading text is unreliable on the live tab-widget layout, and "monthly" wrongly
# matches the "Monthly Average Prices" CPO table on the older heading-bearing archives.
_MONTHLY_HEADER_TOKENS = ["export", "import"]
_REQUIRED_COLUMNS = ["export", "import"]

_YEAR_CELL_RE = re.compile(r"^(19|20)\d{2}$")


@dataclass(frozen=True)
class MpocMonthlyRelease:
    year: int
    tables: list[NormalizedTable]
    source: str = "mpoc"


class MpocDriftError(ValueError):
    """A year page's monthly table drifted from the expected contract (fail closed)."""


class MpocCompletenessError(ValueError):
    """A calendar year is present but does not carry a clean 1..12 month set (fail closed)."""


def _find_col(header_l: list[str], *tokens: str) -> int:
    for i, h in enumerate(header_l):
        if any(tok in h for tok in tokens):
            return i
    return -1


def _is_year_subheader(row: tuple[str, ...]) -> bool:
    """True for the year sub-header row: empty first cell + at least one bare 4-digit-year cell.

    Distinguishes the ``['', 2023, 2022, 2023, 2022]`` sub-header from month data rows (whose first
    cell is a month name)."""
    if not row or (row[0] or "").strip():
        return False
    return any(_YEAR_CELL_RE.match((c or "").strip()) for c in row[1:])


def _group_year_column(
    header: tuple[str, ...], year_row: tuple[str, ...], group_token: str, page_year: int
) -> int:
    """Column index carrying ``page_year`` under the header group whose label holds ``group_token``.

    The group header (e.g. ``['', 'Exports', 'Imports']``) has one cell per group; the year
    sub-header splits each group evenly into its year columns. Returns the column whose year label
    equals ``page_year`` (falling back to the group's first column), or -1 if the group is absent /
    the split is irregular."""
    groups = list(header[1:])
    n_groups = len(groups)
    n_val = len(year_row) - 1
    if n_groups <= 0 or n_val <= 0 or n_val % n_groups != 0:
        return -1
    per = n_val // n_groups
    for gi, glabel in enumerate(groups):
        if group_token in (glabel or "").lower():
            start = 1 + gi * per
            for c in range(start, min(start + per, len(year_row))):
                if str(page_year) in (year_row[c] or ""):
                    return c
            return start  # page year not listed; default to the group's first year column
    return -1


def _month_or_none(label: str) -> Optional[int]:
    """Parse a single calendar month from a row label, or ``None`` for aggregate/notes rows.

    Rejects range/total rows ('Jan-Dec', 'Jan - Dec', '*Jan-Dec', 'Total', averages) that would
    otherwise be misread as a month (e.g. parse_month('Jan-Dec') -> Jan)."""
    s = (label or "").strip().lstrip("*").strip()
    low = s.lower()
    if not low:
        return None
    if any(sep in low for sep in ("-", "–", "—")):  # hyphen / en / em dash range row
        return None
    if "total" in low or "average" in low:
        return None
    return parse_month(s)


def _rows_for_release(release: MpocMonthlyRelease) -> list[dict]:
    table = find_table_by_header(release.tables, header_all=_MONTHLY_HEADER_TOKENS)
    drift = diagnose_table_drift(table, expected_columns=_REQUIRED_COLUMNS)
    if drift:
        raise MpocDriftError(
            f"MPOC monthly {release.year}: layout drift {[d.to_dict() for d in drift]}"
        )
    assert table is not None
    header_l = [h.lower() for h in table.header]
    rows = list(table.rows)

    # Two-row header (live layout): a year sub-header row splits the Exports/Imports groups into
    # per-year columns. Resolve THIS page-year's columns from it; the remaining rows are months.
    if rows and _is_year_subheader(rows[0]):
        year_row = rows[0]
        rows = rows[1:]
        exp_col = _group_year_column(table.header, year_row, "export", release.year)
        imp_col = _group_year_column(table.header, year_row, "import", release.year)
    else:
        # Single-row header (synthetic/simple): the group labels are the value columns directly.
        exp_col = _find_col(header_l, "export")
        imp_col = _find_col(header_l, "import")

    if exp_col < 0 or imp_col < 0:
        raise MpocDriftError(
            f"MPOC monthly {release.year}: could not resolve export/import columns from "
            f"header {list(table.header)}"
        )

    out: list[dict] = []
    for row in rows:
        if not row:
            continue
        month = _month_or_none(row[0])
        if month is None:
            continue  # a subtotal/notes/range row, not a calendar month
        out.append({
            "year": int(release.year),
            "month": month,
            "exports_mt": parse_number(row[exp_col]) if 0 <= exp_col < len(row) else None,
            "imports_mt": parse_number(row[imp_col]) if 0 <= imp_col < len(row) else None,
            "source": release.source,
        })
    return out


def transform_trade_stats_monthly(
    releases: list[MpocMonthlyRelease], *, require_full_year: bool = False
) -> pd.DataFrame:
    """Transform annual MPOC pages into the silver monthly trade-stats table.

    Duplicate (year, month) rows are collapsed keeping the first. When ``require_full_year`` a
    year that is present must carry months 1..12 with no gaps/dupes, else
    :class:`MpocCompletenessError`. Rows sorted (year, month)."""
    records: list[dict] = []
    for rel in releases:
        records.extend(_rows_for_release(rel))
    if not records:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df = pd.DataFrame.from_records(records)
    df = df.drop_duplicates(subset=["year", "month"], keep="first")

    if require_full_year:
        for year, grp in df.groupby("year"):
            months = sorted(int(m) for m in grp["month"])
            if months != list(range(1, 13)):
                raise MpocCompletenessError(
                    f"year {year} is not a complete 1..12 month set: {months}"
                )

    df = df.sort_values(["year", "month"]).reset_index(drop=True)
    return df[OUTPUT_COLUMNS]
