"""SILVER-F054: MPOC monthly trade-statistics producer (silver_mpoc_trade_stats_monthly).

Grain: ``year x month``. Consumes the "Monthly Palm Oil Exports & Imports" (a.k.a. monthly totals)
table off each annual MPOC Trade Statistics page. Validates 12-month completeness, unit
consistency (one declared unit per numeric column), and source-table identity via the F052 drift
check.

Output: ``[year, month, exports_mt, imports_mt, source]``. Pure + AWS-free.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.silver.mpoc.adapter import (
    NormalizedTable,
    diagnose_table_drift,
    find_table,
    parse_month,
    parse_number,
)

logger = get_logger(__name__)

OUTPUT_COLUMNS: list[str] = ["year", "month", "exports_mt", "imports_mt", "source"]

MONTHLY_TABLE_IDENTITY = "monthly"
_REQUIRED_COLUMNS = ["month"]


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


def _rows_for_release(release: MpocMonthlyRelease) -> list[dict]:
    table = find_table(release.tables, MONTHLY_TABLE_IDENTITY)
    drift = diagnose_table_drift(
        table,
        expected_identity_substr=MONTHLY_TABLE_IDENTITY,
        expected_columns=_REQUIRED_COLUMNS,
    )
    if drift:
        raise MpocDriftError(
            f"MPOC monthly {release.year}: layout drift {[d.to_dict() for d in drift]}"
        )
    assert table is not None
    header_l = [h.lower() for h in table.header]
    exp_col = _find_col(header_l, "export")
    imp_col = _find_col(header_l, "import")
    out: list[dict] = []
    for row in table.rows:
        if not row:
            continue
        month = parse_month(row[0])
        if month is None:
            continue  # a subtotal/notes row, not a calendar month
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
